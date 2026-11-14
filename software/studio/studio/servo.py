"""Bus session for the servo page: Studio opens the servo bus itself (like servo-web), reads the 15 servos and relaxes them on the bus.

This step (servo page 4a) is **read-only**: apart from relax, nothing is written to the servos. Hold and set-center come in later steps.

Why open the bus ourselves: neither robotd version can "torque up a single servo and keep holding it" (official writes all 15 at once;
the stock board firmware's move relaxes once it reaches position), see scratchpad console/servo-page-plan.md. So the servo page, like servo-web,
talks to the servos directly from Studio while robotd is stopped. **The bus has exactly one entry point: ServoSession.open().**

Threads: the Feetech bus is blocking I/O (pyserial); polling runs in a thread (50 Hz) and puts results in snapshot,
and the web side takes the latest at 10 Hz. Relax doesn't queue: it is sent directly on the calling thread (each bus packet is locked, interleaved with polling),
waiting at most for the packet polling is currently receiving (a few milliseconds).

Relax = latched e-stop (plan 1.3, review S4): send sync_write 40=0 → sync_read 40 readback → rewrite one by one those that didn't become 0,
at most three rounds. Once latched, everything added later ("torque up, write target, write zero position") checks latched first, and requires the user to click "解除" (release).

Hand-back / leave (third-round code review D2, D3): servo operations (servo_ops.handle) run in a thread, so hand-back can race with "a hold just clicked":
when "hold" arrives first and "leave" later in the same packet, 35 out of 40 times the servos were still torqued after hand-back. Therefore:
- Every servo operation is accounted for on entry and exit (op_begin / op_end; the app records it in the event loop already, so it counts as in flight even before the thread starts);
- Hand-back / leave first sets closing (subsequent servo operations are all refused, and manual torque-up may not clear the relax latch), waits for in-flight ones to finish (with a timeout; on timeout no hand-back),
  then reads torque once on the spot (not the once-per-second cache), then relaxes and closes the bus;
- Leave: no hand-back while calibration / motion / liveliness is running; hand back only if all 15 torques are read on the spot and all are 0; unreadable ones are assumed to possibly still be holding.
"""
import contextlib
import json
import os
import subprocess
import sys
import threading
import time

from .bus import feetech
from .startup_status import servo_observations

IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]     # same order as robotd's JOINT_NAMES
NAMES = {
    20: ("左髋偏航", "Left Hip Yaw"), 21: ("左髋横滚", "Left Hip Roll"), 22: ("左髋俯仰", "Left Hip Pitch"),
    23: ("左膝", "Left Knee"), 24: ("左踝", "Left Ankle"),
    30: ("颈部俯仰", "Neck Pitch"), 31: ("头部俯仰", "Head Pitch"), 32: ("头部偏航", "Head Yaw"),
    33: ("头部横滚", "Head Roll"), 34: ("嘴巴", "Mouth"),
    10: ("右髋偏航", "Right Hip Yaw"), 11: ("右髋横滚", "Right Hip Roll"), 12: ("右髋俯仰", "Right Hip Pitch"),
    13: ("右膝", "Right Knee"), 14: ("右踝", "Right Ankle"),
}
GROUP = {**{i: "R" for i in (10, 11, 12, 13, 14)}, **{i: "L" for i in (20, 21, 22, 23, 24)},
         **{i: "H" for i in (30, 31, 32, 33, 34)}}
# The direction in which HD-1910 readings increase is opposite to the model (XL330); servo-web checked each one on real hardware on 2026-09-20: all 15 are −1
DEFAULT_DIRECTIONS = {i: -1 for i in IDS}
POLL_HZ = 50
TORQUE_EVERY_S = 1.0          # the torque switch is read separately, once per second
STATIC_REGS = {13: "temp_limit", 21: "p", 22: "d", 33: "mode", 8: "resp_level", 19: "unload",
               50: "p_run", 51: "d_run"}    # 21/22 are stored in EEPROM; the HD-1910's running P/D are in RAM 50/51 (servo_ops writes these before torquing up)
BATTERY_FULL_V, BATTERY_EMPTY_V = 8.2, 6.6      # official duck-control/src/model.rs, same algorithm
LEAVE_WAIT_S = 3.0            # leaving the servo page: maximum wait for in-flight servo operations to finish (no hand-back if they don't)
HANDBACK_WAIT_S = 10.0        # clicking "交还主程序" (hand back to main program): same as above (calibration stops before the next servo when it sees closing)
# While any of these is running = "work not finished yet": leaving the servo page doesn't hand back (third-round code review D3a: leaving while one-click calibration ran interrupted the remaining servos with the relax latch)
BUSY_OPS = {"calibrate": "正在校准", "undo": "正在撤销校准", "timing": "正在测总线时序", "scan_all": "正在扫全网",
            "scan": "正在扫描", "set_id": "正在改 ID", "reboot": "正在重启舵机", "write_reg": "正在写寄存器"}


class Refused(Exception):
    """This operation can't be done right now (relax latched, bus not open, handing back, bad parameters). The reason is shown directly on the page. servo_ops uses this one too."""


def angle_deg(raw, direction):
    return None if raw is None else direction * (raw - 2048) * 360.0 / 4096


def battery_percent(volts):
    if not volts or volts <= 0:
        return None
    return max(0.0, min(1.0, (volts - BATTERY_EMPTY_V) / (BATTERY_FULL_V - BATTERY_EMPTY_V))) * 100


def robotd_active():
    """Is robotd running? On a computer (no systemctl) treat it as not running; on Linux, a systemctl error / timeout returns None (can't tell)."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        r = subprocess.run(["systemctl", "is-active", "robotd"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() in ("active", "activating", "reloading")
    except (OSError, subprocess.TimeoutExpired):
        return None


def boot_id():
    """ID of this boot: reads /proc/sys/kernel/random/boot_id; returns None if unreadable (Windows, file missing)."""
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


BASELINE_PREFIX = "servo-baseline-"
_baseline_mem = {}       # when boot_id is unreadable (on a computer, demo) the baseline is kept only in this process: (state_dir, is demo) -> {id: {"41","46"}}


class ServoSession:
    def __init__(self, log, port=None, sim=False, directions=None, baud=1_000_000, state_dir="."):
        self.log, self.port, self.sim, self.baud, self.state_dir = log, port, sim, baud, state_dir
        self.ops = None                  # servo_ops.ServoOps: only present while the bus is open
        self.directions = {**DEFAULT_DIRECTIONS, **(directions or {})}    # keys are int: dict(..., **d) crashes because keys aren't strings (Oct 19: Studio wouldn't start after duck #2 saved directions)
        self.bus = None
        self.state = "closed"            # closed / opening / open / error
        self.error = None
        self.latched = False             # relax latch
        self.relaxing = False
        self.last_relax = None           # {"ok", "ms", "bad", "at"}
        self.static = {}                 # id -> {temp_limit, p, d, mode, ...}
        self.rows = {}                   # id -> most recently read state
        self.torque = {}                 # id -> 0/1/None
        self.torque_at = None
        self.hz = 0.0
        self.opened_at = None
        self.by = None
        self._stop = threading.Event()
        self._thread = None
        self._window = []                # (time, asked, missed) for the last few seconds, used to compute the frame loss rate
        self.sim_serial = None
        self.handed_back_at = None       # time of the last hand-back to the main program (monotonic): until the main program connects, the page keeps prompting "needs to be started manually"
        self.closing = False             # handing back / leaving: new servo operations are all refused, and manual torque-up may not clear the relax latch (review D2)
        self._cv = threading.Condition()
        self._inflight = {}              # in-flight servo operations: token -> operation name
        self._tok = 0
        self.restored = False            # this session was taken over again after a Studio restart (review D1)
        self.orphan = None               # the session was open at last exit and couldn't be taken over this time: {"why", "at"} (the relax button directs to the servo page to take over)
        self.helper_available = None     # is the root helper that starts / stops robotd available: hand-back prompt says "正在把主程序起回来…" (bringing the main program back…) (review D12)
        self.conflict_at = None          # robotd was found started manually during the session (monotonic, review D9)
        self.probe_robotd = None         # whether to check if robotd came up during the session: None = only with a real serial port (demo servos come with a fake robotd that is always there)
        self.boot_id = None              # used to record the 41/46 baseline on the first takeover in this boot (result of boot_id())
        self.baseline = {}               # id -> {"41": raw integer, "46": raw integer}: written back before hand-back
        self.handback_note = None        # servos whose relax wasn't confirmed after a successful hand-back (for the banner; cleared on next takeover)
        self.giveback_error = None       # why the main program didn't come up after hand-back (banner turns red)
        self.giveback_hint = None        # how to recover when the main program didn't come up (two variants: flag present / absent)
        self.marker_error = None         # session marker wasn't written: after a Studio restart it won't know the session is still open

    # ---- Open / close ----

    def open(self, by=None, port=None, restored=False):
        """Opens the bus (blocking; the caller puts it in a thread). Returns (ok, reason).
        port: serial port chosen on the page (on a computer with a USB-to-TTL adapter it is COM5 or similar, like servo-web); "sim" = simulated servos.
        Can't switch ports while already open (switching would close the real bus first, leaving servos holding while the e-stop can't relax them): must hand back before switching.
        restored: continuing the previous session after a Studio restart (review D1); set together with state="open",
        so whoever sees "open" sees at the same moment that it is a takeover (previously it was set later outside the thread, leaving a window)."""
        if port:
            want_sim = port == "sim"
            if self.state == "open" and (want_sim != self.sim or (not want_sim and port != self.port)):
                # Switching ports while tuning servos would close the real bus first, with all 15 still holding and the e-stop unable to relax them: never switch
                return False, "调舵机中不能换串口：先点「交还主程序」，再换"
            self.sim = want_sim
            if not want_sim:
                self.port = port
        if self.state in ("open", "opening"):
            return True, None
        if not self.sim and not self.port:
            self.state, self.error = "closed", None
            return False, "先选一个串口（电脑上插 USB 转 TTL）或者「演示（没接舵机）」"
        self.state, self.error, self.by = "opening", None, by
        try:
            if self.sim:
                from .bus.sim_bus import SimSerial
                self.sim_serial = SimSerial(IDS, phys=_sim_home())
                self.bus = feetech.FeetechBus(None, ser=self.sim_serial)
                where = "演示（没接舵机，软件里假装有 15 颗）"
            else:
                active = robotd_active()
                if active is None:
                    raise RuntimeError("查不了主程序在不在（systemctl 出错）：为了不跟它抢串口，先不开")
                if active:
                    raise RuntimeError("主程序 robotd 还在用舵机总线。先停主程序（下一步做成网页上一键接管）")
                self.bus = feetech.FeetechBus(self.port, self.baud)
                where = f"{self.port} @ {self.baud}"
            self.log.info(f"打开舵机总线：{where}", cat="总线", raw=f"by={by}")
            found = [i for i in IDS if self.bus.ping(i) is not None]
            missing = [i for i in IDS if i not in found]
            self._read_static(found)
            self._record_baseline(found)
            self._read_torque()
            self.restored = bool(restored)
            self.state, self.opened_at, self.latched = "open", time.monotonic(), False
            from .servo_ops import ServoOps
            self.ops = ServoOps(self, self.state_dir)
            self.ops.read_phase()
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="servo-poll", daemon=True)
            self._thread.start()
            msg = f"舵机总线打开了：{len(found)}/15 颗有应答"
            if missing:
                self.log.warn(msg, cat="总线", raw=f"没应答：{missing}", hint="看那颗的线有没有插好、有没有电")
            else:
                self.log.info(msg, cat="总线")
            return True, None
        except Exception as e:  # noqa: BLE001
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
            self.log.error("打不开舵机总线", cat="总线", raw=self.error,
                           hint="鸭子上要先停主程序；电脑上要接好 USB 转 TTL；端口写对了吗")
            self._close_bus()
            return False, self.error

    def holding(self):
        """How many servos are currently torqued (torque readback is 1, from the once-per-second cache: for page display only; hand-back / leave decisions use read_torque_now). 0 when the bus isn't open."""
        if self.state != "open":
            return 0
        return sum(1 for i in IDS if self.torque.get(i) == 1)

    def unknown(self):
        """How many servos' torque can't be read (no response): they may also be holding. 0 when the bus isn't open."""
        if self.state != "open":
            return 0
        return sum(1 for i in IDS if self.torque.get(i) not in (0, 1))

    @property
    def halted(self):
        """Relax latched, or handing back: background transitions, liveliness and calibration wrap-up may no longer torque up / move."""
        return self.latched or self.closing

    # ---- In-flight servo operations (review D2) ----

    def op_begin(self, name):
        """Record a servo operation (the app calls this in the event loop, before the thread starts). Handing back / bus not open: raises Refused. Returns a token for op_end."""
        with self._cv:
            if self.closing:
                raise Refused("正在交还主程序：舵机操作不收了")
            if self.state != "open":
                raise Refused("舵机总线没打开：先点「开始调舵机」")
            self._tok += 1
            tok = self._tok
            self._inflight[tok] = str(name or "?")
            return tok

    def op_end(self, tok):
        """Done (calling again is harmless)."""
        with self._cv:
            if self._inflight.pop(tok, None) is not None:
                self._cv.notify_all()

    @contextlib.contextmanager
    def op_slot(self, name):
        tok = self.op_begin(name)
        try:
            yield
        finally:
            self.op_end(tok)

    def wait_ops(self, timeout):
        """Wait for all in-flight servo operations to finish; returns False on timeout."""
        with self._cv:
            return self._cv.wait_for(lambda: not self._inflight, timeout)

    def inflight_names(self):
        with self._cv:
            return sorted(set(self._inflight.values()))

    def _busy_locked(self):
        """Calibration / motion / liveliness running: returns a reason; None if not running (call while holding _cv)."""
        for name in self._inflight.values():
            if name in BUSY_OPS:
                return BUSY_OPS[name]
        ops = self.ops
        if ops is not None:
            if ops.calib_lock.locked():
                return "正在校准"
            if ops._motion is not None and ops._motion.is_alive() and not ops._motion_stop.is_set():
                return "动作在跑"
            if ops.idle_running:
                return "灵动在跑"
        return None

    def read_torque_now(self):
        """Reads the 15 torque switches once on the spot (no cache): {id: 0 / 1 / None (no response)}. All None on a bus error."""
        try:
            got = self._read_torque()
        except Exception as e:  # noqa: BLE001
            self.log.warn("当场读扭矩没读到", cat="总线", raw=f"{type(e).__name__}: {e}")
            return {i: None for i in IDS}
        return {i: (v[1][0] if v else None) for i, v in ((i, got.get(i)) for i in IDS)}

    def leave(self, why, wait_s=LEAVE_WAIT_S, before_close=None):
        """Leaving the servo page / nobody watching (blocking, put in a thread): if hand-back is possible, relax and close the bus. Returns (result, details):
            ("closed", None)       wasn't open in the first place
            ("kept", {"why", "holding", "unknown"})   didn't hand back (work not finished, some still holding, some unreadable, in-flight operations didn't finish in time)
            ("handed_back", None)  relaxed and closed the bus (the app handles the main program side)"""
        with self._cv:
            if self.state != "open":
                return "closed", None
            busy = self._busy_locked()
            if busy:
                return "kept", {"why": busy, "holding": self.holding(), "unknown": self.unknown()}
            self.closing = True
        try:
            if not self.wait_ops(wait_s):
                return "kept", {"why": f"还有舵机操作没做完（{'、'.join(self.inflight_names())}）", "holding": self.holding(),
                                "unknown": self.unknown()}
            tq = self.read_torque_now()
            on = [i for i in IDS if tq.get(i) == 1]
            unk = [i for i in IDS if tq.get(i) not in (0, 1)]
            if on or unk:
                parts = ([f"{len(on)} 颗保持着"] if on else []) + ([f"{len(unk)} 颗读不到扭矩（可能也在保持）"] if unk else [])
                return "kept", {"why": "、".join(parts), "holding": len(on), "unknown": len(unk)}
            ok, reason = self.relax_all(why)
            if not ok:
                self.log.warn("交还前卸力没全部确认", cat="安全", raw=reason, hint="主程序启动时还会再卸一次；不放心就关电源")
            bad, _unknown = self._restore_baseline()
            if bad:
                ids = "、".join(f"#{i}" for i in bad)
                msg = f"{len(bad)} 颗加速度/速度没写回（{ids}）：没交还。舵机已经松了；再点一次「交还主程序」重试"
                self.log.error("41/46 基线没写回：没交还", cat="安全", raw=ids, dedup=False, hint=msg)
                return "kept", {"why": msg, "holding": self.holding(), "unknown": self.unknown()}
            if before_close is not None:
                before_close()          # clear the "tuning servos" pause together before closing the bus: by the time outsiders see closed, the state is complete (same ordering requirement as review D1/D2)
            self.close()
            return "handed_back", None
        finally:
            with self._cv:
                self.closing = False

    def hand_back_bus(self, why, wait_s=HANDBACK_WAIT_S, before_close=None):
        """Click "交还主程序" (hand back to main program) (blocking, put in a thread): set closing → stop motion / liveliness → wait for in-flight operations → relax and read back → close the bus.
        If they don't finish in time, don't hand back; returns (False, reason)."""
        with self._cv:
            if self.state != "open":
                return True, None
            self.closing = True
        try:
            if self.ops is not None:
                self.ops.idle_running = False
                self.ops._motion_stop.set()
            if not self.wait_ops(wait_s):
                names = "、".join(self.inflight_names()) or "?"
                return False, f"还有舵机操作没做完（{names}），等了 {wait_s:.0f} 秒：没交还。等它做完再点「交还主程序」"
            ok, reason = self.relax_all(why)
            if not ok:
                self.log.warn("交还前卸力没全部确认", cat="安全", raw=reason, hint="主程序启动时还会再卸一次；不放心就关电源")
            bad, unknown = self._restore_baseline()
            if bad:
                ids = "、".join(f"#{i}" for i in bad)
                msg = f"{len(bad)} 颗加速度/速度没写回（{ids}）：没交还。舵机已经松了；再点一次「交还主程序」重试"
                self.log.error("41/46 基线没写回：没交还", cat="安全", raw=ids, dedup=False, hint=msg)
                return False, msg
            relax_bad = list((self.last_relax or {}).get("bad") or [])
            note_ids = sorted(set(relax_bad) | set(unknown), key=IDS.index)
            note = (f"{'、'.join(f'#{i}' for i in note_ids)} 没确认卸力：主程序起来时会再卸一次；不放心就关电源"
                    if note_ids else None)
            if before_close is not None:
                before_close()          # clear the "tuning servos" pause together before closing the bus: by the time outsiders see closed, the state is complete
            self.close()
            return True, note
        finally:
            with self._cv:
                self.closing = False

    def close(self):
        """Closes the bus (blocking). Only closes the serial port, doesn't change servo state (also used when Studio exits or robotd is found started manually: no relax, no writes).
        Hand-back to the main program (relax, read back, then close) goes through hand_back_bus / leave."""
        if self.ops is not None:
            self.ops.idle_running = False
            self.ops._motion_stop.set()
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._close_bus()
        self.ops = None
        if self.state != "closed":
            self.log.info("关掉舵机总线", cat="总线", dedup=False)
        self.state = "closed"
        self.rows, self.torque = {}, {}
        self.restored = False

    def _close_bus(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:  # noqa: BLE001
                pass
        self.bus = None

    # ---- Read ----

    def _read_static(self, ids):
        for sid in ids:
            d = {}
            for addr, key in STATIC_REGS.items():
                try:
                    d[key] = self.bus.read_u8(sid, addr)
                except feetech.BusError:
                    d[key] = None
            try:
                d["offset"] = feetech.sign15(self.bus.read_u16(sid, 31))
                d["torque_limit"] = self.bus.read_u16(sid, 48)
            except feetech.BusError:
                d.setdefault("offset", None)
            self.static[sid] = d

    def _baseline_path(self, bid):
        return os.path.join(self.state_dir, f"{BASELINE_PREFIX}{bid}.json")

    def _baseline_load(self, bid):
        """Read this boot's baseline. If boot_id is unreadable, or for a demo session, use process memory (separated by state directory + demo or not)."""
        if bid is None:
            return _baseline_mem.setdefault((os.path.abspath(self.state_dir), bool(self.sim)), {})
        try:
            with open(self._baseline_path(bid), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        regs = data.get("regs") if isinstance(data, dict) else None
        out = {}
        if isinstance(regs, dict):
            for k, v in regs.items():
                try:
                    sid = int(k)
                except (TypeError, ValueError):
                    continue
                if sid in IDS and isinstance(v, dict) and isinstance(v.get("41"), int) and isinstance(v.get("46"), int):
                    out[sid] = {"41": v["41"] & 0xFF, "46": v["46"] & 0xFFFF}
        return out

    def _baseline_save(self, bid, regs):
        """Atomically writes servo-baseline-<boot_id>.json (write a temp file first, then os.replace)."""
        path = self._baseline_path(bid)
        data = {"v": 1, "boot_id": bid, "at": time.time(),
                "regs": {str(i): dict(regs[i]) for i in IDS if i in regs}}
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            self.log.warn("41/46 基线没写进文件（这次进程里还记着）", cat="总线", step=path,
                          raw=f"{type(e).__name__}: {e}", hint="看看 state 目录满没满、有没有权限")

    def _record_baseline(self, found):
        """On the first takeover in this boot, records the raw values of 41 (1 byte) / 46 (2 bytes).
        If a file for the same boot_id already exists it is not overwritten; only servos that responded this time and aren't in the file yet are added;
        if boot_id is unreadable, it is kept only in process memory. Demo sessions only use process memory and don't touch the baseline file in the state directory."""
        bid = boot_id()
        self.boot_id = bid
        if self.sim:
            # Demo servos' 41/46 are fake: don't read, write or delete the baseline in state, only keep it in process memory
            regs = self._baseline_load(None)
        else:
            if bid is not None:
                current = os.path.basename(self._baseline_path(bid))
                try:
                    names = os.listdir(self.state_dir)
                except OSError:
                    names = []
                for name in names:                  # baselines from other boots are no longer useful
                    if name.startswith(BASELINE_PREFIX) and name.endswith(".json") and name != current:
                        try:
                            os.remove(os.path.join(self.state_dir, name))
                        except OSError:
                            pass
            regs = self._baseline_load(bid)
        added = False
        for sid in found:
            if sid in regs:
                continue
            try:
                regs[sid] = {"41": self.bus.read_u8(sid, 41), "46": self.bus.read_u16(sid, 46)}
            except feetech.BusError as e:
                self.log.warn(f"41/46 基线：#{sid} 读不到，跳过", cat="总线", step="读 41/46 基线",
                              raw=f"{type(e).__name__}: {e}", hint="这颗这次可能不在总线上")
                continue
            added = True
        self.baseline = regs
        if not self.sim and bid is not None and added:
            self._baseline_save(bid, regs)

    def _restore_baseline(self):
        """Before hand-back, write 41/46 back to the baseline and read back, retrying at most 2 times.
        Returns (servos with wrong readback, servos with no response): the former blocks hand-back; the latter can't be handled by the main program either when it comes up, so only a warning is logged."""
        if self.state != "open" or self.bus is None:
            return [], []
        base = getattr(self, "baseline", None) or {}
        missing = [i for i in IDS if i not in base]
        if missing:
            self.log.info(f"交接：{len(missing)} 颗没有 41/46 基线（这次开机接管时没应答），跳过", cat="总线",
                          raw=f"没有基线：{missing}", dedup=False)
        bad, unknown = [], []
        for sid in IDS:
            want = base.get(sid)
            if not want:
                continue
            outcome, last = "unknown", None
            for _ in range(3):                      # first try + 2 retries
                try:
                    self.bus.write_u8(sid, 41, int(want["41"]) & 0xFF)
                    self.bus.write_u16(sid, 46, int(want["46"]) & 0xFFFF)
                    got41 = self.bus.read_u8(sid, 41)
                    got46 = self.bus.read_u16(sid, 46)
                except feetech.BusError as e:
                    outcome, last = "unknown", e
                    continue
                if got41 == (int(want["41"]) & 0xFF) and got46 == (int(want["46"]) & 0xFFFF):
                    outcome = "ok"
                    break
                outcome, last = "bad", f"回读 41={got41}、46={got46}，要的是 {want['41']}、{want['46']}"
            if outcome == "ok":
                continue
            if outcome == "bad":
                bad.append(sid)
                self.log.error(f"41/46 基线写回没对上：#{sid}", cat="安全", step="回读 41/46",
                               raw=str(last), hint="回读不对就不交还，再点一次「交还主程序」")
            else:
                unknown.append(sid)
                self.log.warn(f"41/46 基线写回：#{sid} 没应答，没确认", cat="安全", step="写/回读 41/46",
                              raw=f"{type(last).__name__}: {last}", hint="主程序起来时也管不了它")
        return bad, unknown

    def refresh_static(self, ids):
        """After calibration or a register write, re-read these servos' offset, P/D and so on (the expanded rows in the table need to show new values)."""
        if self.bus is not None:
            self._read_static([i for i in ids if i in IDS])

    def _read_torque(self):
        got = self.bus.sync_read(IDS, 40, 1)
        self.torque = {sid: (v[1][0] if v else None) for sid, v in got.items()}
        self.torque_at = time.monotonic()
        return got

    def _loop(self):
        period = 1.0 / POLL_HZ
        n, t_rate = 0, time.monotonic()
        next_torque = time.monotonic() + TORQUE_EVERY_S
        while not self._stop.is_set():
            t0 = time.monotonic()
            if self.ops is not None and self.ops.calib_lock.locked():
                # Don't grab the bus during calibration or timing tests: one stuck sync_read can take hundreds of milliseconds, landing right in the torque-off window
                self._stop.wait(0.02)
                continue
            try:
                states = self.bus.states(IDS)
                now = time.monotonic()
                for sid, s in states.items():
                    if s is not None:
                        s["at"] = now
                        self.rows[sid] = s
                if now >= next_torque:
                    self._read_torque()
                    next_torque = now + TORQUE_EVERY_S
            except Exception as e:  # noqa: BLE001 -- serial port unplugged or similar: log once, wait a bit and retry
                self.log.error("读舵机出错", cat="总线", raw=f"{type(e).__name__}: {e}", dedup=True)
                time.sleep(0.5)
            n += 1
            if time.monotonic() - t_rate >= 1.0:
                self.hz = n / (time.monotonic() - t_rate)
                n, t_rate = 0, time.monotonic()
                self._note_window()
            left = period - (time.monotonic() - t0)
            if left > 0:
                self._stop.wait(left)

    def _note_window(self):
        tot = self._totals()
        self._window.append((time.monotonic(), tot[0], tot[1]))
        self._window = self._window[-6:]        # last 5 seconds

    def _totals(self):
        per = self.bus.per_id if self.bus else {}
        return (sum(c["asked"] for c in per.values()), sum(c["missed"] for c in per.values()))

    def drop_rate(self):
        if len(self._window) < 2:
            return None
        (_, a0, m0), (_, a1, m1) = self._window[0], self._window[-1]
        return None if a1 == a0 else (m1 - m0) / (a1 - a0)

    # ---- Relax ----

    def relax_all(self, by=None):
        """Relax all 15 on the bus and confirm by readback (blocking, a few to a dozen-odd milliseconds). Returns (all confirmed, reason)."""
        if self.state != "open" or self.bus is None:
            return False, "舵机总线没打开"
        self.latched, self.relaxing = True, True
        if self.ops is not None:                 # stop ongoing transitions and liveliness first (once latched they can't write anyway)
            self.ops.idle_running = False
            self.ops._motion_stop.set()
        t0 = time.monotonic()
        bad = list(IDS)
        try:
            self.bus.sync_write(40, 1, [(sid, b"\x00") for sid in IDS])
            for _ in range(3):
                got = self._read_torque()
                bad = [sid for sid, v in got.items() if v is None or v[1][0] != 0]
                if not bad:
                    break
                for sid in bad:                      # write again one by one for those not confirmed
                    try:
                        self.bus.write_u8(sid, 40, 0)
                    except feetech.BusError:
                        pass
        except Exception as e:  # noqa: BLE001
            self.log.error("总线卸力出错", cat="安全", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="用手捏住鸭子，关电源")
        finally:
            self.relaxing = False
        ms = round((time.monotonic() - t0) * 1000)
        self.last_relax = {"ok": not bad, "ms": ms, "bad": bad, "at": time.monotonic()}
        if bad:
            self.log.error(f"总线卸力：{len(bad)} 颗没确认", cat="安全", step="sync_read 40 回读",
                           raw=f"没确认：{bad}", ctx={"by": by, "ms": ms}, hint="可能是线松了没应答；关电源最保险", dedup=False)
            return False, f"{len(bad)} 颗没确认：{bad}"
        # State-change logs are recorded every time (review D13: 1-minute dedup would swallow a second hand-back or second relax, and things wouldn't match up afterwards)
        self.log.info(f"总线卸力：15 颗全部确认（{ms} ms）", cat="安全", step="sync_read 40 回读", raw=f"by={by}", dedup=False)
        return True, None

    # ---- For the web page ----

    def snapshot(self):
        now = time.monotonic()
        rows, volts = [], []
        per = self.bus.per_id if self.bus else {}
        for sid in IDS:
            s = self.rows.get(sid)
            st = self.static.get(sid, {})
            c = per.get(sid, {})
            age = None if not s else now - s["at"]
            fresh = age is not None and age < 0.5
            if fresh and s.get("volt"):
                volts.append(s["volt"])
            cn, en = NAMES[sid]
            rows.append({
                "id": sid, "cn": cn, "en": en, "group": GROUP[sid], "dir": self.directions[sid],
                "raw": s["pos"] if s else None,
                "deg": round(angle_deg(s["pos"], self.directions[sid]), 1) if s else None,
                "volt": s["volt"] if s else None, "temp": s["temp"] if s else None,
                "temp_limit": st.get("temp_limit"), "load": s["load"] if s else None,
                "current_ma": round(s["current_ma"]) if s else None,
                "status": s["status_text"] if s else None, "moving": s["moving"] if s else None,
                "torque": self.torque.get(sid), "fresh": fresh, "age_ms": None if age is None else round(age * 1000),
                "p": st.get("p"), "d": st.get("d"), "mode": st.get("mode"), "offset": st.get("offset"),
                "comm": {k: c.get(k, 0) for k in ("asked", "ok", "missed", "alarm", "streak", "max_streak")},
            })
        avg_v = round(sum(volts) / len(volts), 2) if volts else None
        torque_fresh = self.torque_at is not None and now - self.torque_at < 2.5
        all_off = torque_fresh and all(self.torque.get(i) == 0 for i in IDS)
        dr = self.drop_rate()
        return {
            "t": "servo", "state": self.state, "error": self.error, "sim": self.sim, "source": "bus",
            "port": "演示（没接舵机）" if self.sim else self.port,
            "marker_error": self.marker_error,
            "online": sum(1 for r in rows if r["fresh"]), "total": len(IDS),
            "hz": round(self.hz, 1), "avg_volts": avg_v, "battery_pct": battery_percent(avg_v),
            "drop_rate": None if dr is None else round(dr, 4),
            "bus": dict(self.bus.stats) if self.bus else None,
            "holding": sum(1 for i in IDS if self.torque.get(i) == 1),
            "all_off": all_off, "latched": self.latched, "relaxing": self.relaxing, "closing": self.closing,
            "last_relax": None if not self.last_relax else {k: v for k, v in self.last_relax.items() if k != "at"},
            "rows": rows,
            # Page header "软硬：P5 · D0 · 限力 1000（跟主程序一样）" (Stiffness: P5 · D0 · torque limit 1000 (same as main program)); also fill each row with running P/D/torque limit (servo_ops.gains_view)
            "gains": ops.gains_view(rows) if (ops := self.ops) is not None else None,
        }

    def estop_status(self):
        """For the top-bar relax button: during a servo session, bus readback is authoritative."""
        if self.state != "open":
            return {"state": "unavailable", "why": "舵机总线没打开，只能关电源"}
        if self.relaxing:
            return {"state": "pending", "why": "卸力中…"}
        s = self.snapshot()
        if s["all_off"]:
            return {"state": "confirmed", "why": "15 颗都已卸力（总线回读）"}
        return {"state": "ready", "why": "调舵机中：卸力直接走总线"}


def view_from_robotd(bus, directions, state="closed", error=None, sim=False):
    """When the bus isn't taken over, the servo page still has its table: data comes from the main program's busStatus (it reads the servos anyway), view only.
    Angles use the same algorithm as after takeover (direction × (reading − 2048)), so numbers match before and after takeover.
    The main program's position_rad is computed against its own zero position (zero_raw); it isn't used here."""
    # Robotd carries IPC receipt/error evidence. The legacy dict form stays valid
    # for ordinary feedback, but cannot establish fresh startup observations.
    rd = bus if hasattr(bus, "bus") else None
    if rd is not None:
        bus = rd.bus.value
    observations = servo_observations(bus, present=getattr(rd, "present", None),
                                      bus_age_s=rd.bus.age() if rd is not None else None,
                                      bus_error=getattr(rd.bus, "error", None) if rd is not None else None)
    if observations is not None:
        return _view_startup_observations(observations, directions, state, error, sim)
    native = (bus or {}).get("native") if isinstance(bus, dict) and isinstance(bus.get("native"), dict) else {}
    joints = {j.get("id"): j for j in (native.get("joints") or []) if isinstance(j, dict)}
    torque_on = native.get("torque_enabled")
    rows, volts = [], []
    for sid in IDS:
        j = joints.get(sid) or {}
        raw = j.get("position_raw")
        d = DEFAULT_DIRECTIONS[sid] if directions is None else directions.get(sid, -1)
        fresh = j.get("feedback_fresh") is True
        if fresh and isinstance(j.get("volts"), (int, float)):
            volts.append(j["volts"])
        cn, en = NAMES[sid]
        rows.append({
            "id": sid, "cn": cn, "en": en, "group": GROUP[sid], "dir": d,
            "raw": raw, "deg": round(angle_deg(raw, d), 1) if isinstance(raw, int) else None,
            "volt": j.get("volts"), "temp": j.get("temperature_c"), "temp_limit": None,
            "load": j.get("load_raw"), "current_ma": j.get("current_ma"), "status": None, "moving": None,
            "torque": None if torque_on is None else int(bool(torque_on)), "fresh": fresh,
            "age_ms": j.get("sample_age_ms"), "p": None, "d": None, "mode": None, "offset": None,
            "comm": {"asked": None, "ok": None, "missed": j.get("missing_total", 0) or 0, "alarm": 0,
                     "streak": j.get("consecutive_missing", 0) or 0, "max_streak": None},
        })
    avg_v = round(sum(volts) / len(volts), 2) if volts else None
    return {
        "t": "servo", "state": state, "error": error, "sim": sim, "source": "robotd",
        "port": "主程序", "online": sum(1 for r in rows if r["fresh"]), "total": len(IDS),
        "hz": None, "avg_volts": avg_v, "battery_pct": battery_percent(avg_v), "drop_rate": None, "bus": None,
        "holding": sum(1 for r in rows if r["torque"] == 1), "all_off": False, "latched": False,
        "relaxing": False, "last_relax": None, "rows": rows,
    }


def _view_startup_observations(observations, directions, state, error, sim):
    by_id = {row["id"]: row for row in observations["rows"]}
    rows, volts = [], []
    for sid in IDS:
        row = by_id.get(sid, {})
        cn, en = NAMES[sid]
        volt = row.get("volts")
        if volt is not None:
            volts.append(volt)
        rows.append({
            "id": sid, "cn": cn, "en": en, "group": GROUP[sid],
            "dir": DEFAULT_DIRECTIONS[sid] if directions is None else directions.get(sid, -1),
            "raw": row.get("position_raw"), "deg": None, "volt": volt,
            "temp": row.get("temperature_c"), "temp_limit": None, "load": row.get("load_raw"),
            "speed_raw": row.get("speed_raw"), "current_raw": row.get("current_raw"), "current_ma": None,
            "responding": row.get("responding"), "fresh": row.get("responding") is True,
            "feedback_fresh": row.get("feedback_fresh", False), "age_ms": row.get("check_age_ms"),
            "torque": None, "status": None, "moving": None, "p": None, "d": None, "mode": None, "offset": None,
            "comm": {key: None for key in ("asked", "ok", "missed", "alarm", "streak", "max_streak")},
        })
    avg_v = round(sum(volts) / len(volts), 2) if volts else None
    return {"t": "servo", "state": state, "error": error, "sim": sim, "source": "robotd", "diagnostic": True,
            "port": "主程序", "online": observations["online"], "total": len(IDS),
            "hz": None, "avg_volts": avg_v, "battery_pct": battery_percent(avg_v), "drop_rate": None, "bus": None,
            "holding": None, "all_off": False, "latched": False, "relaxing": False, "last_relax": None, "rows": rows}


def _sim_home():
    """Simulated servos placed in the official standing pose (reading = 2048 + direction × angle), so the 3D view shows it standing."""
    home = {20: 0.0, 21: -0.0873, 22: -0.4579, 23: -0.0049, 24: 0.4530, 30: 0.3491, 31: 0.3491,
            32: 0.0, 33: 0.0, 34: 0.0, 10: 0.0, 11: 0.0873, 12: 0.4579, 13: 0.0049, 14: -0.4530}
    return {sid: round(2048 + DEFAULT_DIRECTIONS[sid] * rad * 4096 / (2 * 3.141592653589793)) for sid, rad in home.items()}


def list_ports():
    """Serial ports currently visible on the system. Port names change after replugging USB, so the page lets you pick directly (like servo-web)."""
    try:
        from serial.tools import list_ports as lp
        return [{"device": p.device, "desc": (p.description or "").strip()} for p in lp.comports()]
    except Exception:  # noqa: BLE001
        return []


def load_directions(state_dir):
    """Direction table: use servo-directions.json from the state directory if present, otherwise all −1."""
    p = os.path.join(state_dir, "servo-directions.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return {int(k): int(v) for k, v in d.items() if k.isdigit() and int(v) in (1, -1)}
    except (OSError, ValueError):
        return {}
