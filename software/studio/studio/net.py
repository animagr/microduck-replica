"""Wi-Fi setup: read netcheck's status file, call configd's net.status / scan / connect / forget, and toggle the hotspot via the helper.

The image's microduck-netcheck opens a hotspot at boot if it can't connect to Wi-Fi (NM connection name Microduck-Hotspot, address 10.42.0.1),
and writes the current state into /run/microduck/net.json. Studio only reads it:

    {"mode": "wifi" | "hotspot" | "none",
     "hotspot_ssid": "Microduck-c51b", "hotspot_ip": "10.42.0.1", "hotspot_psk": "microduck",
     "hostname": "duck-c51b", "since": 1790000000.0,
     "scan": [{"ssid": "Home", "signal": 72, "security": "wpa_psk"}], "scan_at": 1790000000.0}

If the file is missing (development on a computer, old image) it's treated as "unknown": the page hides the whole Wi-Fi block, everything else as usual.
In hotspot mode wlan0 can't scan (AP mode); if configd's net.scan is empty / errors, use the scan from before the hotspot was opened in the file, marked cached.

Passwords: the home Wi-Fi password is passed only once, in memory, from the web page → configd, and is never written to logs, state, last-try, or the diagnostics bundle.
hotspot.psk in state is the public password of the duck's own hotspot (microduck), which the page shows to the user; it's not the home password.
"""
import asyncio
import json
import os
import re
import socket
import time
from pathlib import Path

from . import helper
from .log import log_cmd
from .rpc import Conn, RpcError, Timeout, Unreachable, call_once

NET_STATE = "/run/microduck/net.json"
LAST_TRY_NAME = "net-last-try.json"
READ_EVERY_S = 2.0
STATUS_EVERY_S = 5.0
STATUS_TIMEOUT_S = 4.0
CONNECT_DELAY_S = 2.0          # let the page receive "starting to switch" first, then touch the hotspot
CONNECT_TIMEOUT_S = 60.0
SCAN_TIMEOUT_S = 15.0
FORGET_TIMEOUT_S = 10.0
STATUS_MAX_AGE_S = 15.0        # every 5 seconds; only treated as unknown after three failures
PORT = 8000
HOTSPOT_IP = "10.42.0.1"       # NetworkManager's default shared-hotspot address (used when net.json has no hotspot_ip)
OWN_PREFIX = "Microduck-"      # the duck's hotspots are all named Microduck-xxxx (named by netcheck)
PSK_HEX = re.compile(r"^[0-9A-Fa-f]{64}$")
PERMISSION = "Studio 没权限改 WiFi（configd 没放行 radxa）"

REASON_TEXT = {
    "bad_key": "密码不对",
    "not_found": "鸭子找不到这个 WiFi（名字对吗？离路由器近一点；隐藏的 WiFi 现在不支持）",
    "timeout": "连上了但拿不到地址，可以再试一次",
    "studio_timeout": "鸭子的配网程序 60 秒没回话",
    "unsupported": "这个 WiFi 鸭子连不了（企业认证或没填密码）",
    "other": "没连上",
}


class Refused(Exception):
    """The Wi-Fi setup operation can't be done / bad parameters: message is plain language for the page."""


def validate_ssid(value):
    """SSID is 1–32 bytes (UTF-8; one Chinese character is 3 bytes). No strip: spaces around an SSID may be part of the name."""
    if not isinstance(value, str) or value == "":
        raise Refused("WiFi 名字要是 1–32 个字节")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as e:
        raise Refused(f"WiFi 名字里有不能用的字符：{e}") from None
    if size > 32:
        raise Refused("WiFi 名字最长 32 个字节（中文一个字算 3 个）")
    if "\x00" in value:
        raise Refused("WiFi 名字里不能有 NUL")
    return value


def validate_psk(value):
    """Empty = open network; otherwise 8–63 characters, or 64 hex digits (the two WPA forms)."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise Refused("WiFi 密码要是文字")
    if PSK_HEX.fullmatch(value):
        return value
    if 8 <= len(value) <= 63:
        return value
    raise Refused("WiFi 密码要 8–63 个字符，或者 64 位十六进制")


def validate_connect(ssid, psk):
    return validate_ssid(ssid), validate_psk(psk)


def addresses(host, ip, port=PORT, scheme="http"):
    """The "this duck's address" list: the ones usable now, and which to use per device (10-20 real hardware: Windows with the Clash system proxy on couldn't open .local ——
    it went through the proxy, 502; Windows resolves a dotless hostname via LLMNR, and the proxy bypasses it via <local>; an IP works everywhere).
    The factory HTTPS certificate only covers the hostname, the fixed hotspot address, and the loopback address."""
    out = []
    if ip and (scheme != "https" or ip in (HOTSPOT_IP, "127.0.0.1")):
        out.append({"kind": "ip", "url": f"{scheme}://{ip}:{port}/", "note": "IP：哪台设备都能打开（换了路由器、重新分了地址会变）"})
    out.append({"kind": "host", "url": f"{scheme}://{host}:{port}/", "note": "Windows 电脑用这个：开着代理也能打开"})
    out.append({"kind": "local", "url": f"{scheme}://{host}.local:{port}/", "note": "苹果手机、Mac 用这个"})
    return out


def own_hotspot(n, hotspot_ssid):
    """Whether this scan result entry is the duck's own hotspot (real hardware scanned Microduck-0de6 shown as "已保存" (Saved); tapping it would make people enter the home password there).
    If net.json has hotspot_ssid, match by it; otherwise match ones "starting with Microduck- and saved"."""
    ssid = n.get("ssid") if isinstance(n, dict) else None
    if not isinstance(ssid, str):
        return False
    if hotspot_ssid:
        return ssid == hotspot_ssid
    return ssid.startswith(OWN_PREFIX) and bool(n.get("saved"))


def explain(reason, detail=None):
    """configd failure reason → one sentence on the page. For other, append detail; permission errors are passed on verbatim."""
    if detail and str(detail).strip() == PERMISSION:
        return PERMISSION
    base = REASON_TEXT.get(reason, REASON_TEXT["other"])
    if reason == "other" and detail:
        return f"{base}（{detail}）"
    return base


def _scrub(text, psk=None):
    """One more safety net before writing logs / last-try: the home password and how it appears in URLs are replaced with [已隐藏] ([hidden])."""
    if text is None:
        return None
    out = str(text)
    if psk:
        out = out.replace(psk, "[已隐藏]")
    return out[:600]


def _rpc_error(e, what):
    if isinstance(e, RpcError):
        if e.code == 14 or re.search(r"permission|not authori[sz]ed|not allowed|access denied", e.message or "", re.I):
            return PERMISSION
        return f"{what}：{e.message}"
    if isinstance(e, Timeout):
        return f"{what}超时了（{e}）"
    return f"连不上 configd：{e}"


class Net:
    """Wi-Fi setup state + operations. start() launches two loops: read net.json every 2 seconds, ask configd net.status every 5 seconds (only when the file exists)."""

    def __init__(self, configd_addr, state_file=NET_STATE, state_dir=None, log=None, *, dev_mode=False,
                 hostname=None, port=PORT, scheme="http"):
        self.configd_addr = configd_addr
        self.state_file = Path(state_file)
        self.hostname = hostname
        self.port = int(port)
        self.scheme = "https" if scheme == "https" else "http"
        self.log = log
        self.dev_mode = bool(dev_mode)
        self.last_try_path = Path(state_dir) / LAST_TRY_NAME if state_dir else None
        self.cfg = Conn(configd_addr, "configd-net", log) if configd_addr and configd_addr != "none" else None
        self.info = None
        self.info_at = None
        self.status = None
        self.status_at = None
        self.busy = None
        self.last_try = self._load_last_try()
        self._bad_state_logged = False
        self._status_error_logged = False
        self._tasks = []
        self.connect_task = None       # the background Wi-Fi connection task started by app.py (must not be garbage-collected even if the page disconnects)

    # ---- Lifecycle ----

    def start(self):
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._read_loop(), name="net-state"),
                       loop.create_task(self._status_loop(), name="net-status")]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=1.0)
        self._tasks = []
        if self.cfg is not None:
            self.cfg.close()

    async def _read_loop(self):
        while True:
            try:
                await asyncio.to_thread(self._read_once)
            except Exception as e:  # noqa: BLE001 —— an error reading the status file must not stop all of Studio
                if self.log:
                    self.log.warn("读配网状态文件时出错", cat="网络", step=str(self.state_file),
                                  raw=f"{type(e).__name__}: {e}", dedup=True)
            await asyncio.sleep(READ_EVERY_S)

    def _read_once(self):
        try:
            raw = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            had = self.info is not None
            self.info, self.info_at = None, None
            self.status, self.status_at = None, None
            self._bad_state_logged = False
            if had and self.log:
                self.log.info("配网状态文件不在了：WiFi 那一块先隐藏，别的照常", cat="网络")
            return
        except OSError as e:
            self._state_bad(f"读不了 {self.state_file}：{type(e).__name__}: {e}")
            return
        try:
            data = json.loads(raw)
        except ValueError as e:
            self._state_bad(f"不是 JSON：{e}")
            return
        if not isinstance(data, dict) or data.get("mode") not in ("wifi", "hotspot", "none"):
            self._state_bad("不是对象，或者 mode 不是 wifi / hotspot / none")
            return
        was_bad = self._bad_state_logged
        self.info, self.info_at = data, time.monotonic()
        self._bad_state_logged = False
        if was_bad and self.log:
            self.log.info("配网状态文件又读到了", cat="网络")

    def _state_bad(self, why):
        self.info, self.info_at = None, None
        self.status, self.status_at = None, None
        if self._bad_state_logged or self.log is None:
            return
        self._bad_state_logged = True
        self.log.warn("配网状态文件读不懂：WiFi 那一块先隐藏", cat="网络", step=str(self.state_file),
                      raw=why, hint="这是 netcheck 写的；它下次会重写。别的功能照常，不用管")

    async def _status_loop(self):
        while True:
            if self.cfg is not None and self.info is not None:
                try:
                    r = await self.cfg.call("net.status", {}, timeout=STATUS_TIMEOUT_S)
                    if not isinstance(r, dict):
                        raise RpcError("net.status", None, f"回的不是对象（{type(r).__name__}）")
                    self.status, self.status_at = r, time.monotonic()
                    if self._status_error_logged and self.log:
                        self.log.info("WiFi 状态恢复了", cat="网络")
                    self._status_error_logged = False
                except (Unreachable, Timeout, RpcError) as e:
                    self.status, self.status_at = None, None
                    if not self._status_error_logged and self.log:
                        self._status_error_logged = True
                        self.log.warn("读不到 WiFi 状态", cat="网络", step="configd net.status", raw=str(e),
                                      hint="configd 没在跑？不影响站和走，只是 WiFi 那一块显示不知道")
            else:
                self.status, self.status_at = None, None
                self._status_error_logged = False
            await asyncio.sleep(STATUS_EVERY_S)

    # ---- For the page ----

    def mode(self):
        return self.info.get("mode") if isinstance(self.info, dict) else None

    def view(self, now=None):
        """The net field pushed to the page. File missing / broken = {"known": false}."""
        if not isinstance(self.info, dict):
            return {"known": False}
        now = time.monotonic() if now is None else now
        st = self.status if (isinstance(self.status, dict) and self.status_at is not None
                             and now - self.status_at <= STATUS_MAX_AGE_S) else None
        connected = bool(st and st.get("state") == "connected")
        host = self.info.get("hostname") or self.hostname or socket.gethostname()
        last = None
        if isinstance(self.last_try, dict):
            last = {k: self.last_try.get(k) for k in ("ssid", "at", "ok", "reason", "detail", "ip4")}
            last["reason_text"] = explain(last.get("reason"), last.get("detail"))
        mode = self.info.get("mode")
        ip4 = st.get("ip4") if connected else None
        # IP usable now: in hotspot mode it's the duck hotspot's address (10.42.0.1), otherwise configd net.status's ip4 (absent if not connected)
        ip_now = (self.info.get("hotspot_ip") or HOTSPOT_IP) if mode == "hotspot" else ip4
        hotspot_ip = self.info.get("hotspot_ip") or HOTSPOT_IP
        return {
            "known": True,
            "mode": mode,
            "ssid": st.get("ssid") if connected else None,
            "signal": st.get("signal") if connected else None,
            "ip4": ip4,
            "ip_now": ip_now,
            "hostname": host,
            "url_local": f"{self.scheme}://{host}.local:{self.port}/",
            "url_host": f"{self.scheme}://{host}:{self.port}/",
            "url_hotspot": f"{self.scheme}://{hotspot_ip}:{self.port}/m",
            "urls": addresses(host, ip_now, self.port, self.scheme),
            "hotspot": {"ssid": self.info.get("hotspot_ssid"), "ip": hotspot_ip,
                        "psk": self.info.get("hotspot_psk")},
            "last_try": last,
            "busy": self.busy,
        }

    def begin_connect(self):
        """Claim "connecting": a second connect returns False. Raises Refused when the Wi-Fi setup state is unknown."""
        if not isinstance(self.info, dict):
            raise Refused("不知道鸭子的配网状态：WiFi 功能现在用不了")
        if self.busy is not None:
            return False
        self.busy = "connecting"
        return True

    def begin_hotspot(self):
        """Claim the hotspot toggle: returns False if an operation is already in progress, raises Refused when the Wi-Fi setup state is unknown.
        Kept separate from begin_connect so "connecting to Wi-Fi" and "toggling hotspot" on the page don't cut in on each other."""
        if not isinstance(self.info, dict):
            raise Refused("不知道鸭子的配网状态：WiFi 功能现在用不了")
        if self.busy is not None:
            return False
        self.busy = "hotspot"
        return True

    # ---- Scanning ----

    async def scan(self):
        """configd net.scan. In hotspot mode the NIC may not be able to scan: if empty / error, use the scan from before the hotspot was opened in net.json.
        The duck's own hotspot is filtered out (own_hotspot): otherwise it shows as "已保存" (Saved) in the list, and tapping it would make people enter the home password."""
        if not isinstance(self.info, dict):
            raise Refused("不知道鸭子的配网状态：WiFi 功能现在用不了")
        own = self.info.get("hotspot_ssid")
        result, error = None, None
        with log_cmd(self.log, "扫 WiFi", "configd net.scan") as t:
            try:
                r = await call_once(self.configd_addr, "net.scan", {}, timeout=SCAN_TIMEOUT_S)
                nets = r.get("networks") if isinstance(r, dict) else None
                if not isinstance(nets, list):
                    raise Refused("configd 回的 WiFi 列表看不懂")
                result = [n for n in nets if isinstance(n, dict) and n.get("ssid") and not own_hotspot(n, own)]
                t.ok({"networks": len(result)})
            except (Unreachable, Timeout, RpcError, Refused) as e:
                error = _rpc_error(e, "扫 WiFi") if not isinstance(e, Refused) else str(e)
                result = None
                t.fail(error, hint="热点模式下用开热点前的那次扫描")
        if self.mode() == "hotspot" and not result:
            cached = self.info.get("scan")
            if isinstance(cached, list):
                if self.log:
                    self.log.info("热点模式下用开热点前的扫描结果", cat="网络", raw=error or "configd 回的列表是空的",
                                  dedup=True)
                return {"networks": [n for n in cached if isinstance(n, dict) and not own_hotspot(n, own)], "cached": True,
                        "scan_at": self.info.get("scan_at")}
        if result is None:
            raise Refused(error or "读不到 WiFi 列表")
        return {"networks": result, "cached": False, "scan_at": None}

    # ---- Connecting ----

    async def connect(self, ssid, psk, by):
        """Turn off hotspot → configd net.connect → write last-try. Call begin_connect() first.
        Returns the last-try record (without the password). On failure, turn the hotspot back on immediately; for bad_key, first forget the config this attempt broke."""
        ssid, psk = validate_connect(ssid, psk)
        if self.busy is None:
            self.busy = "connecting"
        if psk and self.log:
            self.log.hide(psk)                    # safety net: in case other code brings the password into the logs, mask it too
        outcome = {"ok": False, "reason": "other", "detail": None, "ip4": None}
        hotspot_stopped = False
        hotspot_down_tried = False
        try:
            await asyncio.sleep(CONNECT_DELAY_S)
            if self.mode() == "hotspot":
                if self.dev_mode:
                    if self.log:
                        self.log.info("电脑上开发（--dev-autologin）：不关热点，直接连 WiFi", cat="网络",
                                      raw=f"by={by}", dedup=False)
                else:
                    if not helper.available(refresh=True):
                        if self.log:
                            self.log.warn("连 WiFi 前发现小助手不在", cat="网络", step="wifi-hotspot-down",
                                          hint="先在鸭子上运行 deploy/install.sh")
                        raise Refused("还没装小助手：先在鸭子上运行 deploy/install.sh，Studio 才能关热点去连 WiFi")
                    hotspot_down_tried = True
                    with log_cmd(self.log, "关热点", "小助手 wifi-hotspot-down", who=by) as th:
                        try:
                            ok_h, result_h, detail_h = await asyncio.to_thread(helper.wifi_hotspot_down, by, ssid)
                        except Exception as e:  # noqa: BLE001
                            th.fail(f"{type(e).__name__}: {e}", hint="看小助手装没装、版本对不对")
                            raise Refused(f"小助手没跑成：{type(e).__name__}: {e}") from None
                        if result_h == "bad_verb":
                            th.fail("小助手太旧，不认 wifi-hotspot-down", hint="重装 deploy/install.sh")
                            raise Refused("小助手太旧，重装 deploy/install.sh")
                        if not ok_h:
                            why = helper.friendly(result_h, detail_h, "wifi-hotspot-down")
                            th.fail(why, raw=str(detail_h), hint="看 nmcli 是不是能看到 Microduck-Hotspot")
                            raise Refused(f"关热点没成：{why}")
                        th.ok({"result": result_h})
                    hotspot_stopped = True
            params = {"ssid": ssid}
            if psk:
                params["psk"] = psk
            with log_cmd(self.log, f"连 WiFi「{ssid}」", "configd net.connect", who=by,
                         args={"ssid": ssid, "密码": "带密码" if psk else "没密码"}) as t:
                try:
                    r = await call_once(self.configd_addr, "net.connect", params, timeout=CONNECT_TIMEOUT_S)
                except (Unreachable, Timeout, RpcError) as e:
                    if isinstance(e, Timeout):
                        outcome = {"ok": False, "reason": "studio_timeout",
                                   "detail": f"鸭子的配网程序 {CONNECT_TIMEOUT_S:.0f} 秒没回话", "ip4": None}
                    else:
                        outcome = {"ok": False, "reason": "other", "detail": _scrub(_rpc_error(e, "连 WiFi"), psk),
                                   "ip4": None}
                    t.fail(explain(outcome["reason"], outcome["detail"]), raw=_scrub(str(e), psk))
                else:
                    outcome = self._read_connect(r, psk)
                    if outcome["ok"]:
                        note = f"IP {outcome['ip4']}" if outcome.get("ip4") else ""
                        t.ok({"outcome": "connected", "ssid": r.get("ssid"), "ip4": r.get("ip4")}, note=note)
                    else:
                        t.fail(explain(outcome["reason"], outcome["detail"]),
                               raw={"outcome": r.get("outcome"), "reason": r.get("reason")} if isinstance(r, dict) else None,
                               hint="热点马上就回来，手机重新连鸭子热点就能看到原因")
        except Refused as e:
            outcome = {"ok": False, "reason": "other", "detail": _scrub(str(e), psk), "ip4": None}
            if self.log:
                self.log.warn("连 WiFi 没开始", cat="网络", step="关热点", raw=_scrub(str(e), psk),
                              hint="看小助手装没装、版本对不对")
        except Exception as e:  # noqa: BLE001 —— Studio's own bugs must also be written to last-try
            outcome = {"ok": False, "reason": "other", "detail": _scrub(f"{type(e).__name__}: {e}", psk), "ip4": None}
            if self.log:
                self.log.error("连 WiFi 时 Studio 出错", cat="网络", raw=_scrub(f"{type(e).__name__}: {e}", psk),
                               exc=True, hint="这是 Studio 的问题，导出诊断包发出来")
        finally:
            rec = {"ssid": ssid, "at": time.time(), "ok": bool(outcome["ok"]),
                   "reason": outcome["reason"], "detail": _scrub(outcome["detail"], psk),
                   "ip4": outcome.get("ip4")}
            self.last_try = rec
            self._save_last_try(rec)
            if outcome["ok"]:
                self._set_connected(ssid, outcome.get("ip4"))
            elif hotspot_down_tried and not outcome["ok"]:
                if hotspot_stopped and outcome["reason"] == "bad_key":
                    await self._forget_bad_key(ssid, by)
                await self._hotspot_up(by)
            self.busy = None
        return rec

    def _read_connect(self, r, psk):
        if not isinstance(r, dict):
            return {"ok": False, "reason": "other", "detail": "configd 回的不是对象", "ip4": None}
        if r.get("outcome") == "connected":
            return {"ok": True, "reason": None, "detail": None, "ip4": r.get("ip4")}
        if r.get("outcome") == "failed":
            reason = r.get("reason") if r.get("reason") in REASON_TEXT else "other"
            detail = _scrub(r.get("detail"), psk) if r.get("detail") else None
            return {"ok": False, "reason": reason, "detail": detail, "ip4": None}
        return {"ok": False, "reason": "other", "detail": _scrub(f"看不懂的回包：{r}", psk), "ip4": None}

    async def _hotspot_up(self, by):
        """Open the hotspot; returns (ok, a sentence for the page). Shared by the hotspot restore after a failed connection and the "户外模式" (Outdoor mode) button."""
        with log_cmd(self.log, "开热点", "小助手 wifi-hotspot-up", who=by) as t:
            try:
                ok, result, detail = await asyncio.to_thread(helper.wifi_hotspot_up, by)
            except Exception as e:  # noqa: BLE001
                why = f"小助手没跑成：{type(e).__name__}: {e}"
                t.fail(why, hint="连接窗口结束后 netcheck 也会自己开")
                return False, why
            if result == "bad_verb":
                why = "小助手太旧，不认 wifi-hotspot-up，重装 deploy/install.sh"
                t.fail(why, hint="连接窗口结束后 netcheck 也会自己开")
                return False, why
            if ok:
                t.ok({"result": result})
                return True, None
            why = helper.friendly(result, detail, "wifi-hotspot-up")
            t.fail(why, raw=str(detail), hint="连接窗口结束后 netcheck 也会自己开")
            return False, why

    async def hotspot_up(self, by):
        """Outdoor mode: open the hotspot right away without waiting for netcheck. Call begin_hotspot() first. Returns (ok, reason)."""
        try:
            if not helper.available(refresh=True):
                raise Refused("还没装小助手：先在鸭子上运行 deploy/install.sh，Studio 才能开热点")
            return await self._hotspot_up(by)
        finally:
            self.busy = None

    async def hotspot_down(self, by, ssid=None):
        """Outdoor mode: turn off the hotspot; NetworkManager reconnects to the home Wi-Fi using the saved config.
        Call begin_hotspot() first. ssid is only written to netcheck's connection window, may be empty. Returns (ok, reason)."""
        try:
            if not helper.available(refresh=True):
                raise Refused("还没装小助手：先在鸭子上运行 deploy/install.sh，Studio 才能关热点")
            with log_cmd(self.log, "关热点", "小助手 wifi-hotspot-down", who=by) as t:
                try:
                    ok, result, detail = await asyncio.to_thread(helper.wifi_hotspot_down, by, ssid)
                except Exception as e:  # noqa: BLE001
                    why = f"小助手没跑成：{type(e).__name__}: {e}"
                    t.fail(why, hint="看小助手装没装、版本对不对")
                    return False, why
                if result == "bad_verb":
                    why = "小助手太旧，不认 wifi-hotspot-down，重装 deploy/install.sh"
                    t.fail(why, hint="重装 deploy/install.sh")
                    return False, why
                if ok:
                    t.ok({"result": result})
                    return True, None
                why = helper.friendly(result, detail, "wifi-hotspot-down")
                t.fail(why, raw=str(detail), hint="看 nmcli 是不是能看到 Microduck-Hotspot")
                return False, why
        finally:
            self.busy = None

    async def _forget_bad_key(self, ssid, by):
        """Wrong password: the official connect has already replaced the same-named config with this wrong password, so forget it first so netcheck won't keep trying it later."""
        with log_cmd(self.log, f"忘掉密码不对的 WiFi「{ssid}」", "configd net.forget", who=by) as t:
            try:
                r = await call_once(self.configd_addr, "net.forget", {"ssid": ssid}, timeout=FORGET_TIMEOUT_S)
            except (Unreachable, Timeout, RpcError) as e:
                t.fail(_rpc_error(e, "忘掉 WiFi"), raw=str(e), hint="热点照样马上开回来；这个配置可能还留着")
                return
            if not isinstance(r, dict):
                t.fail("configd 回的不是对象", raw=repr(r)[:200])
                return
            t.ok({"removed": bool(r.get("removed"))})

    def _set_connected(self, ssid, ip4):
        self.status = {"state": "connected", "ssid": ssid, "ip4": ip4}
        self.status_at = time.monotonic()

    # ---- Forgetting ----

    async def forget(self, ssid):
        ssid = validate_ssid(ssid)
        if not isinstance(self.info, dict):
            raise Refused("不知道鸭子的配网状态：WiFi 功能现在用不了")
        with log_cmd(self.log, f"忘掉 WiFi「{ssid}」", "configd net.forget") as t:
            try:
                r = await call_once(self.configd_addr, "net.forget", {"ssid": ssid}, timeout=FORGET_TIMEOUT_S)
            except (Unreachable, Timeout, RpcError) as e:
                text = _rpc_error(e, "忘掉 WiFi")
                t.fail(text, raw=str(e))
                raise Refused(text) from None
            if not isinstance(r, dict):
                t.fail("configd 回的不是对象", raw=repr(r)[:200])
                raise Refused("configd 回的不是对象")
            removed = bool(r.get("removed"))
            t.ok({"removed": removed})
        if isinstance(self.status, dict) and self.status.get("ssid") == ssid:
            self.status, self.status_at = None, None
        return {"removed": removed}

    # ---- last-try file ----

    def _load_last_try(self):
        if self.last_try_path is None:
            return None
        try:
            data = json.loads(self.last_try_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return {k: data.get(k) for k in ("ssid", "at", "ok", "reason", "detail", "ip4")}

    def _save_last_try(self, rec):
        if self.last_try_path is None:
            return
        try:
            self.last_try_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.last_try_path.with_name(self.last_try_path.name + ".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
            try:
                os.chmod(tmp, 0o644)
            except OSError:
                pass
            os.replace(tmp, self.last_try_path)
        except OSError as e:
            if self.log:
                self.log.warn("上次连 WiFi 的结果没写进去", cat="网络", step=str(self.last_try_path),
                              raw=f"{type(e).__name__}: {e}",
                              hint="页面重新连上时看不到上次失败的原因；看看 state 目录满没满、有没有权限")
