"""Tracking of robotd's four startup steps (tuning plan v2 §2.3, §5 T1; scratchpad console/tuning-plan.md).

robotd itself splits startup into four steps and pushes them via robot.startupSubscribe (fork robotd main.rs:4671-4686, 1445-1456):
    First reply = the current state of the four steps: {"steps": {"1": {"status", "detail"}, ...}, "build": ...}
    After that, changes are pushed as notifications {"method": "robot.startup", "params": same shape}; it ends when the client sends a line or disconnects.
status is one of starting / waiting / success / failed. The original messages of the four steps are at main.rs:1205, 1482, 1773-1808, 2184-2232, 4137.

This module only does two things:
- StartupTrack: tracks the result (written by startup_loop started from robotd.py; read by tune.py, state.py). Discarded and restarted on every hello (robotd restarted);
  for each step it records when Studio first saw that status (time.monotonic(): on the duck, seconds since boot).
- startup_loop: while robotd is there and the four steps of this hello have not all succeeded, opens a connection to subscribe; closes it when all four succeed (or one fails).
  Older robotd versions don't have this method: log "unsupported" once and don't ask again for this hello.
- startup_todo: adds two lines to the overview to-do list (called by state.py): while starting, shows "第 N/4 步：<original message>" (Step N/4: <original message>); "step 3 succeeded but walking not loaded" is shown in red.

This module does not import state.py (state.py imports it).
"""
import asyncio
import sys
import time

from .rpc import RpcError, Unreachable, encode, open_conn, read_message

STEPS = ("1", "2", "3", "4")
STEP_NAMES = {"1": "配置和控制线程", "2": "舵机总线和 IMU", "3": "加载模型", "4": "第一个控制周期"}
READ_TIMEOUT_S = 2.0          # how long without messages in the subscription before looking around (has robotd restarted, should Studio pause)
RETRY_S = (1.0, 2.0, 5.0)
POLICY_OFF = "策略按配置关闭"   # fork main.rs:2229: step 3 succeeded but the walking policy is not loaded (also this message when the execution config is broken, review T-R1)


class StartupTrack:
    def __init__(self):
        self.epoch = None          # which hello this belongs to (rd.hello.at)
        self.steps = {}            # "1".."4" -> {"status", "detail", "at"}; at = when Studio first saw this status (monotonic)
        self.build = None
        self.done = False          # all four steps success, or one failed: no need to subscribe again for this hello
        self.unsupported = None    # old robotd without startupSubscribe: the reason
        self.error = None          # most recent subscription error (will retry)
        self.at = None             # most recent update (monotonic)

    def reset(self, epoch):
        self.__init__()
        self.epoch = epoch

    def update(self, report, now=None):
        """Received a snapshot of the four steps (reply or notification). Ignores anything that is not a dict."""
        if not isinstance(report, dict):
            return
        now = time.monotonic() if now is None else now
        steps = report.get("steps") if isinstance(report.get("steps"), dict) else {}
        for k in STEPS:
            row = steps.get(k)
            if not isinstance(row, dict):
                continue
            status, detail = row.get("status"), row.get("detail")
            old = self.steps.get(k)
            if old and old["status"] == status and old["detail"] == detail:
                continue
            at = old["at"] if old and old["status"] == status else now
            self.steps[k] = {"status": status if isinstance(status, str) else None,
                             "detail": detail if isinstance(detail, str) else None, "at": at}
        if isinstance(report.get("build"), str):
            self.build = report["build"]
        self.at = now
        self.error = None
        self.done = (all((self.steps.get(k) or {}).get("status") == "success" for k in STEPS)
                     or any((self.steps.get(k) or {}).get("status") == "failed" for k in STEPS))

    def current(self):
        """(step number, that step) -- the first one that is not success; returns (None, None) if all succeeded."""
        for k in STEPS:
            row = self.steps.get(k)
            if not row or row.get("status") != "success":
                return k, row
        return None, None

    def policy_off(self):
        """Step 3 succeeded with the original message "策略按配置关闭" (policy disabled by config)."""
        row = self.steps.get("3") or {}
        return row.get("status") == "success" and POLICY_OFF in (row.get("detail") or "")

    def view(self, now=None):
        """The four rows pushed to the page. at_s: on the duck, seconds since boot (monotonic counts from boot on Linux); meaningless on a computer, boot_clock makes that clear."""
        rows = []
        for k in STEPS:
            row = self.steps.get(k)
            rows.append({"n": int(k), "name": STEP_NAMES[k], "status": (row or {}).get("status"),
                         "detail": (row or {}).get("detail"),
                         "at_s": round(row["at"], 1) if row and row.get("at") is not None else None})
        n, row = self.current()
        return {"rows": rows, "known": bool(self.steps), "done": self.done, "now": int(n) if n else None,
                "unsupported": self.unsupported, "error": self.error, "build": self.build,
                "boot_clock": sys.platform.startswith("linux")}


async def startup_loop(rd):
    """Background task started from robotd.py (backstopped by _supervise like polling). Read-only: only sends robot.startupSubscribe."""
    track = rd.startup
    fails = 0
    while True:
        if rd.addr == "none":
            return
        epoch = rd.hello.at
        if rd.paused or rd.present is not True or epoch is None:
            await asyncio.sleep(1.0)
            continue
        if track.epoch != epoch:
            track.reset(epoch)            # robotd did a new hello (most likely restarted): the old four steps are discarded
        if track.done or track.unsupported:
            await asyncio.sleep(1.0)
            continue
        try:
            await _follow(rd, track, epoch)
            fails = 0
        except (Unreachable, OSError, asyncio.TimeoutError) as e:
            fails += 1
            track.error = f"订阅启动步骤没成：{e}"
            await asyncio.sleep(RETRY_S[min(fails - 1, len(RETRY_S) - 1)])


async def _follow(rd, track, epoch):
    r, w = await asyncio.wait_for(open_conn(rd.addr), 3.0)
    try:
        try:
            w.write(encode(1, "robot.startupSubscribe", {}))
            await w.drain()
        except (ConnectionError, OSError) as e:
            raise Unreachable(f"请求没发出去：{type(e).__name__}: {e}") from e
        while True:
            if rd.hello.at != epoch or rd.paused:
                return                    # robotd restarted / Studio is tuning servos: the outer loop will start over
            try:
                msg = await read_message(r, READ_TIMEOUT_S)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                continue
            if msg.get("id") == 1:
                if "error" in msg:
                    err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                    e = RpcError("robot.startupSubscribe", err.get("code"), err.get("message", ""))
                    track.unsupported = f"这一版主程序不报启动步骤（{e}）"
                    rd.log.info("主程序不报启动步骤（老版本没有 robot.startupSubscribe）", cat="robotd", raw=str(e))
                    return
                track.update(msg.get("result"))
            elif msg.get("method") == "robot.startup":
                track.update(msg.get("params"))
            else:
                continue
            _log_change(rd, track)
            if track.done:
                return
    finally:
        try:
            w.close()
        except Exception:  # noqa: BLE001 -- no error matters when closing the connection
            pass


def _log_change(rd, track):
    """Logs a line only when stuck or failed (every successful step is in robotd's own journal). Deduplication of identical lines is done by the log module."""
    n, row = track.current()
    if row and row.get("status") == "failed":
        rd.log.error(f"主程序启动第 {n}/4 步失败", cat="robotd", step=STEP_NAMES[n], raw=row.get("detail"),
                     hint="看日志页里 robotd 的那几行；导出诊断包发出来")
    elif not n and track.policy_off():
        rd.log.warn("主程序起来了，但走路策略没加载（第 3 步：策略按配置关闭）", cat="robotd", step="加载模型",
                    hint="多半是走路模型目录里的执行配置或合同不对；能站不能走")


def _hello_at(rd):
    return getattr(getattr(rd, "hello", None), "at", None)


def walk_unloaded(rd, pol=None, bus=None):
    """Reason (in plain language) why the walking model isn't loaded; None if all is fine (review T-R1: step 3 reports success but the policy is off, while the health check may still be fine).
    Only judged in motion mode while in control; pol is a fresh robot.policies (state.py has already filtered it by MAX_AGE)."""
    if getattr(rd, "paused", None) or getattr(rd, "present", None) is False:
        return None                       # tuning servos / main program missing: the readback at hand is stale
    bus = bus if isinstance(bus, dict) else (rd.bus.value if isinstance(rd.bus.value, dict) else None)
    if not bus or bus.get("mode") != "motion" or bus.get("phase") != "control":
        return None
    if isinstance(pol, dict) and pol.get("enabled") is False:
        return None                       # the policy is disabled in the config on purpose (that's how the bench is configured): not broken
    walk_err = None
    if isinstance(pol, dict):
        for s in pol.get("slots") or []:
            if isinstance(s, dict) and s.get("slot") == "walk" and s.get("error"):
                walk_err = str(s["error"])
    lm = bus.get("loaded_models")
    track = getattr(rd, "startup", None)
    off = bool(track is not None and track.epoch == _hello_at(rd) and track.policy_off())
    missing = "loaded_models" in bus and (not isinstance(lm, dict) or not isinstance(lm.get("walk"), dict))
    if walk_err:
        return f"走路槽加载失败：{walk_err}"
    if missing or off:
        return "主程序说「策略按配置关闭」，走路模型没加载" if off else "主程序没有加载走路模型（loaded_models 里没有 walk）"
    return None


def startup_todo(rd, items, pol=None, bus=None):
    """A second pass after state.py's todo() is computed (tuning plan §3.2):
    - For the "鸭子主程序还在启动" (duck main program still starting) item, replace the hint with the original message of the current step (the raw busStatus.error text it used to show is appended after it);
    - Add a "走路模型没加载" (walking model not loaded) item (red)."""
    try:
        track = getattr(rd, "startup", None)
        if track is not None and track.epoch is not None and track.epoch == _hello_at(rd):
            n, row = track.current()
            for it in items:
                if it.get("key") == "starting" and n and row and row.get("detail"):
                    raw = (bus or {}).get("error") if isinstance(bus, dict) else None
                    hint = f"第 {n}/4 步（{STEP_NAMES[n]}）：{row['detail']}"
                    if raw and raw not in row["detail"]:
                        hint += f"　原文：{raw}"
                    it["hint"] = hint
        why = walk_unloaded(rd, pol, bus)
        if why and not any(it.get("key") == "walk_unloaded" for it in items):
            items.insert(0, {"key": "walk_unloaded", "level": "error", "msg": "走路模型没加载",
                             "hint": f"{why}；能站不能走，看总览下面「运行和调参」"})
    except Exception:  # noqa: BLE001 -- just adds a hint; an error here must not break the whole state push
        pass
    return items
