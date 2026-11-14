"""Talks to the services on the duck: 4 connections to robotd + 1 to configd (review-impl-plan I4).

| Connection | Only does                                                   |
| stream  | robot.subscribe {"hz":10}. Opened only while someone is watching; closed 10 s after the last viewer leaves |
| poll    | hello (once), health 2 s, busStatus 1 s (10 Hz while confirming a relax), policies 2 s, calibration-status (once on connect and once when phase becomes control; only results after this hello count) |
| cmd     | motion commands (only used from S1b on)                       |
| relax   | only sends robot.relax; opens a new connection every time (no long-lived connection) |
| startup steps | robot.startupSubscribe: opened when the four steps of this hello have not all succeeded; closed once all succeed / one step fails (startup.py) |
| configd | pad.status 5 s、system.info 60 s                               |

Why separate: one robotd connection handles one request at a time, so a relax must not queue behind a busStatus with a 2-second timeout.
Why the subscription is "open only while someone is watching": as long as there is one subscriber, robotd's control thread has to build a frame every tick (regardless of hz),
so don't make it do useless work when nobody is watching (review-tech-v3 T4).

All times use time.monotonic(): when the duck boots without network, the wall clock is stuck at 1970 (I12).
This module **does not import anything serial-port related**: this version of Studio has no code path at all that can open ttyS2 (I1).
"""
import asyncio
import time

from .estop import CONFIRM_TIMEOUT_S, JOIN_S, RESEND_AT_S, STARTING_PHASES, EStop, evidence
from .log import log_cmd
from .rpc import Conn, RpcError, Timeout, Unreachable, call_once, encode, open_conn, read_message
from .startup import StartupTrack, startup_loop

API_VERSION = 42                     # duck-ipc-proto; a mismatch is only logged, not rejected
KNOWN_BUILDS = ("1fa8438-feetech-ft6-control.43", "4734cbb-feetech-imu-auto-control.44",
                "0791fcd-feetech-qinmo-control.45", "0791fcd-feetech-qinmo-control.46",
                "0791fcd-feetech-qinmo-control.47")
BACKOFF = (0.5, 1.0, 2.0, 5.0)
STREAM_HZ = 10
STREAM_LINGER_S = 10.0


class Sample:
    __slots__ = ("value", "at", "error")

    def __init__(self):
        self.value, self.at, self.error = None, None, None

    def set(self, value):
        self.value, self.at, self.error = value, time.monotonic(), None

    def fail(self, error):
        self.error = str(error)

    def age(self, now=None):
        if self.at is None:
            return None
        return (time.monotonic() if now is None else now) - self.at


class Robotd:
    def __init__(self, robotd_addr, configd_addr, log):
        self.log = log
        self.addr = robotd_addr
        self.poll = Conn(robotd_addr, "poll", log)
        self.cmd = Conn(robotd_addr, "cmd", log)
        self.cfg = Conn(configd_addr, "configd", log)
        self.hello, self.health, self.bus = Sample(), Sample(), Sample()
        self.policies, self.calib, self.state = Sample(), Sample(), Sample()
        self.pad, self.sysinfo = Sample(), Sample()
        self.present = None          # whether robotd's socket exists; None = not tried yet
        self.absent_since = None
        self.estop = EStop()
        self.viewers = 0             # number of visible pages
        self.force_subscribe = False
        self.background_music = False  # internal action consumer; not disguised as a visible page
        self.stream_open = False
        self._last_viewer_at = 0.0
        self._tasks = []
        self._wake_stream = asyncio.Event()
        self._due = {"health": 0.0, "bus": 0.0, "policies": 0.0}   # next time for each poll item (monotonic)
        self._fails = {}             # consecutive failure count for each poll item
        self._relax_send = None      # relax send in flight (asyncio.Task)
        self._relax_send_started = 0.0
        self._relax_watch = None     # relax resend / timeout watcher
        self._calib_task = None
        # Calibration status (calibration-status) only counts if read "after this hello" (overview reorg review O5): after robotd restarts,
        # during the 20 seconds before it has opened the bus, the old "all 15 calibrated" must not be trusted. None = no hello yet (also None for fakes in tests)
        self.calib_valid_after = None
        self._last_phase = None
        # Since when (monotonic) busStatus has kept reporting a startup phase on this connection; None when not in a startup phase. After 30 seconds the page changes to
        # "一直报启动中" (keeps reporting starting) (Oct 20 real hardware: the old fork's calibration mode always reports configuring_bus)
        self.starting_since = None
        self._wake_poll = asyncio.Event()   # on relax, wakes polling from its backoff sleep
        self._loop = None                   # event loop: used to wake polling when another thread calls set_paused (thread-safe)
        self.paused = None                  # robotd is stopped on purpose while tuning servos: polling paused, don't report "主程序不在" (main program missing)
        self.startup = StartupTrack()       # the four startup steps (written by startup_loop in startup.py; read by the tuning card and to-do list)

    # ---- Lifecycle ----

    def start(self):
        loop = asyncio.get_running_loop()
        self._loop = loop
        if self.addr == "none":
            # Bench mode: main controller not flashed, only tuning servos from a computer via the debug board, no connection to the main program
            self.log.info("台架模式：不连主程序 robotd", cat="robotd")
            self._tasks = []
            return
        self._tasks = [loop.create_task(self._supervise("轮询", self._poll_loop), name="robotd-poll"),
                       loop.create_task(self._supervise("实时状态订阅", self._stream_loop), name="robotd-stream"),
                       loop.create_task(self._supervise("configd 轮询", self._configd_loop), name="configd-poll"),
                       loop.create_task(self._supervise("启动步骤订阅", lambda: startup_loop(self)), name="robotd-startup")]

    async def stop(self):
        # Let an in-flight relax finish sending first (wait at most 1 second); don't cut it off when Studio shuts down
        if self._relax_send is not None and not self._relax_send.done():
            await asyncio.wait({self._relax_send}, timeout=1.0)
        tasks = [t for t in self._tasks + [self._relax_send, self._relax_watch, self._calib_task]
                 if t is not None]
        for t in tasks:
            t.cancel()
        for c in (self.poll, self.cmd, self.cfg):
            c.close()
        # After cancelling, wait for the task to actually exit: if we only cancel without waiting, the task may be stopped right at "future returned, next step not yet run",
        # leaving a cancelling task that never wakes up, and tests / shutdown hang in _cancel_all_tasks.
        # Fallback: wait at most 2 seconds, so even if that happens Studio can still exit.
        pending = [t for t in tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=2.0)

    async def _supervise(self, name, fn):
        """No unexpected error in a background loop may stop it silently (code review #4): log the full error and restart after 1 second."""
        while True:
            try:
                await fn()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.log.error(f"后台任务「{name}」出错，1 秒后重启", cat="系统", raw=f"{type(e).__name__}: {e}",
                               hint="这是 Studio 自己的 bug，请把诊断包发出来", exc=True)
                await asyncio.sleep(1.0)

    def set_paused(self, on, why=None):
        if on and not self.paused:
            self.paused = why or "暂停"
            self.log.info(f"暂停跟主程序的轮询（{self.paused}）", cat="robotd", hint="主程序按计划停着，不是出错")
        elif not on and self.paused:
            self.log.info(f"恢复跟主程序的轮询（{self.paused}结束）", cat="robotd")
            self.paused = None
            # When called from the servo thread (resuming polling before closing the bus) we can't call Event.set directly: in debug mode Future.set_result
            # first marks the event done and then raises in the cross-thread scheduling step, so the waiter never wakes up.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                if self._loop is not None and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._wake_poll.set)
            else:
                self._wake_poll.set()

    def set_viewers(self, n):
        n = max(0, n)
        if n and not self.viewers:
            self._wake_stream.set()
        if self.viewers and not n:
            self._last_viewer_at = time.monotonic()
        self.viewers = n

    def set_background_music(self, on):
        on = bool(on)
        if on != self.background_music:
            self.background_music = on
            self._wake_stream.set()

    # ---- Relax ----

    async def relax(self, by):
        """Press relax once; returns (sent or not, reason). Confirmation comes from busStatus readback (estop.on_bus).

        - The send runs in its own task, so it is not cancelled if the caller (page connection) disconnects (code review #6);
        - At most one send is in flight at a time; repeated presses wait on the same one;
        - A watcher task resends once at 2 seconds and times out at 8 seconds, ending on confirmation or timeout (code review #1)."""
        now = time.monotonic()
        self.estop.press(by, now)
        self._due["bus"] = 0.0          # bring the queued busStatus forward: start reading back every 0.1 s immediately
        self._wake_poll.set()           # if polling is sleeping in backoff (robotd just came back), wake it
        loop = asyncio.get_running_loop()
        # If the in-flight send just started (< 0.3 s), follow it; if it started long ago (robotd is stuck), send another one so this press isn't swallowed (re-review #3)
        if (self._relax_send is None or self._relax_send.done()
                or now - self._relax_send_started > JOIN_S):
            self._start_send(by, "卸力")
        if self._relax_watch is None or self._relax_watch.done():
            self._relax_watch = loop.create_task(self._watch_relax())
        return await asyncio.shield(self._relax_send)

    def _start_send(self, by, what):
        started = time.monotonic()
        self._relax_send_started = started
        self._relax_send = asyncio.get_running_loop().create_task(self._send_relax(by, what, started))

    async def _send_relax(self, by, what, started):
        """Opens a new connection for every send (code review #2: a long-idle connection is already dead after robotd restarts).
        If it can't connect, retry once after 0.1 s (the socket briefly disappears while robotd restarts).
        No step before sending may fail: logging doesn't raise, live fields are only read, not computed (re-review #1)."""
        with log_cmd(self.log, what, "robot.relax", who=by,
                     ctx={"mode": self._mode(), "phase": self._phase()}) as t:
            r = None
            for attempt in (1, 2):
                try:
                    r = await call_once(self.addr, "robot.relax", {}, timeout=3.0, name="卸力", log=self.log)
                    break
                except Unreachable as e:
                    if attempt == 1:
                        await asyncio.sleep(0.1)
                        continue
                    return self._relax_failed(t, started, f"没发出去：{e}")
                except (Timeout, RpcError) as e:
                    return self._relax_failed(t, started, f"没发出去：{e}")
            if isinstance(r, dict) and r.get("accepted") is False:
                return self._relax_failed(t, started, f"主程序没接受卸力：{r.get('reason') or '没说原因'}", reply=r)
            self.estop.sent(started)
            self._mark_present(True)        # robotd replied: it is there (polling may still be in backoff and hasn't noticed it came back)
            note = "已发出，等回读确认"
            if not (isinstance(r, dict) and "accepted" in r):
                note += "（回执里没有 accepted 字段，以回读为准）"
            t.ok(r, note=note)
            return True, None

    def _relax_failed(self, t, started, why, reply=None):
        t.fail(why, hint="要停住它：用手柄 − 或者关电源", raw=reply)
        self.estop.send_failed(started, why)
        return False, why

    async def _watch_relax(self):
        while self.estop.active:
            el = self.estop.elapsed()
            if el >= CONFIRM_TIMEOUT_S:
                bus = self.bus.value
                why = "按了 8 秒还没确认卸力"
                if self.estop.send_error:
                    why += f"（后来那次{self.estop.send_error}）"
                self.estop.finish("timeout", why)
                self.log.error("卸力 8 秒还没确认", cat="安全", step="busStatus 回读",
                               ctx=dict(evidence(bus), bus_age_s=_round(self.bus.age()),
                                        saw_torque_off=self.estop.saw_off, send_error=self.estop.send_error),
                               hint="舵机可能还顶着：用手柄 − 或者关电源；把诊断包发出来")
                return
            # Not confirmed after 2 seconds: resend once. If the readback already shows torque off (only the hd1910 flag missing), don't resend:
            # by then someone may already have stood it up with the gamepad, and a resend would make it go limp again (re-review #5)
            if el >= RESEND_AT_S and not self.estop.resent and not self.estop.saw_off:
                self.estop.resent = True
                if self._relax_send is None or self._relax_send.done():
                    self._start_send(self.estop.last_by, "卸力（2 秒没确认，补发一次）")
            await asyncio.sleep(0.1)

    # ---- Polling ----

    async def _ask(self, key, method, params=None, timeout=2.0, every=1.0):
        """Ask one item. On success schedule the next one per `every`; an error reply or timeout only affects this item (code review #5),
        which is postponed by backoff without blocking the other items. Unreachable is raised (the whole connection is gone)."""
        asked = time.monotonic()
        try:
            r = await self.poll.call(method, params or {}, timeout=timeout)
            if not isinstance(r, dict):
                raise RpcError(method, None, f"回的不是对象（{type(r).__name__}）")
        except (RpcError, Timeout) as e:
            if key == "bus" or isinstance(e, Timeout):
                self.bus.fail(e)
            n = self._fails[key] = self._fails.get(key, 0) + 1
            self._due[key] = time.monotonic() + BACKOFF[min(n - 1, len(BACKOFF) - 1)] * 2
            if n in (1, 10) or n % 60 == 0:      # log one line on the 1st and 10th failure and every 60th after that
                self.log.warn("主程序没回好这项查询", cat="robotd", step=method, raw=f"{e}（连续第 {n} 次）",
                              hint="偶尔一次不要紧；一直这样，看主板温度和 robotd 日志")
            return None, asked
        if self._fails.pop(key, 0) >= 10:
            self.log.info("这项查询恢复了", cat="robotd", step=method)
        self._due[key] = time.monotonic() + every
        return r, asked

    async def _poll_loop(self):
        due = self._due
        fails = 0
        hello_done = False
        hello_link = None             # reconnect count of the polling connection at the moment of hello
        while True:
            if self.paused:
                hello_done = False
                await self._nap(1.0)
                continue
            if hello_done and self.poll.reconnects != hello_link:
                # The polling connection dropped and reconnected (an item timing out makes rpc close the connection; it reconnects automatically next time): robotd may be a new process by now,
                # so treat it as a fresh connection: hello again, invalidate any calibration already read (code review C8)
                hello_done = False
                self.log.info("跟主程序的轮询连接重连过：当成新连上，重新 hello、重读标定状态", cat="robotd")
            try:
                if not hello_done:
                    self.bus.fail("等待这次连接的总线状态")
                    r = await self.poll.call("hello", {"api_version": API_VERSION}, timeout=2.0)
                    self.hello.set(r)
                    self.calib_valid_after = self.hello.at    # calibration status read before this is invalid (review O5)
                    self._last_phase = None
                    self.starting_since = None                # "一直报启动中" (keeps reporting starting) is counted again from this connection
                    self._mark_present(True)
                    hello_done = True
                    hello_link = self.poll.reconnects
                    self._ask_calib(again=True)
                    v = r.get("api_version") if isinstance(r, dict) else None
                    if v != API_VERSION:
                        self.log.warn(f"主程序的接口版本是 {v}，Studio 按 {API_VERSION} 写的", cat="robotd",
                                      hint="一般能用；哪个功能出错，会在那个功能上报出来")
                    ver = r.get("daemon_version") if isinstance(r, dict) else None
                    self.log.info(f"连上主程序（接口 v{v}，版本 {ver}）", cat="robotd")
                now = time.monotonic()
                if now >= due["bus"]:
                    # Calibration mode at 10 Hz: the IMU page's live readings and standing calibration both come from last_sample (calibration mode has no robot.state)
                    every = 0.1 if (self.bus.value or {}).get("mode") == "commissioning" else 1.0
                    bus, asked = await self._ask("bus", "robot.busStatus", every=every)
                    if bus is not None:
                        self.bus.set(bus)
                        self._check_build(bus)
                        # Leaving control (robotd fell back to waiting for the bus, or switched mode): the calibration already read no longer counts (code review C8);
                        # Entering control (or ready in debug mode) from "waiting for bus / starting": only now is the calibration file loaded into robotd
                        # (fork main.rs:1535), so ask again (review O5)
                        phase = bus.get("phase") if isinstance(bus, dict) else None
                        if self._last_phase == "control" and phase != "control":
                            self.calib_valid_after = time.monotonic()
                        if (phase != self._last_phase and self._last_phase is not None and phase is not None
                                and phase not in STARTING_PHASES):
                            self._ask_calib(again=True)
                        self._last_phase = phase
                        if phase in STARTING_PHASES:
                            if self.starting_since is None:
                                self.starting_since = time.monotonic()
                        else:
                            self.starting_since = None
                        if self.estop.on_bus(bus, asked):
                            self.log.info(f"卸力已确认（按下到确认 {self.estop.confirm_ms} ms）", cat="安全",
                                          step="busStatus 回读")
                    if self.estop.active:
                        due["bus"] = min(due["bus"], time.monotonic() + 0.1)
                if now >= due["health"]:
                    r, _ = await self._ask("health", "robot.health", every=2.0)
                    if r is not None:
                        self.health.set(r)
                if now >= due["policies"]:
                    if self._mode() == "motion" and self._phase() == "control":
                        r, _ = await self._ask("policies", "robot.policies", every=2.0)
                        if r is not None:
                            self.policies.set(r)
                    else:
                        due["policies"] = now + 2.0
                fails = 0
            except Unreachable as e:
                self.bus.fail(e)
                hello_done = False
                self._mark_present(False, e)
                fails += 1
                await self._nap(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
                continue
            except (Timeout, RpcError) as e:
                # Only hello gets here
                fails += 1
                self.log.warn("主程序没回好 hello", cat="robotd", raw=str(e),
                              hint="主程序可能正在启动；一直这样，看 robotd 日志")
                await self._nap(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
                continue
            await asyncio.sleep(0.05)

    async def _nap(self, seconds):
        """Backoff sleep; woken up when relax is pressed."""
        try:
            await asyncio.wait_for(self._wake_poll.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self._wake_poll.clear()

    def _ask_calib(self, again=False):
        """Start one _calib_once (don't start another if one is already asking). again: phase just became control; the previous round may be in the "not read, retry in 10 seconds"
        sleep, so kill it and ask again right away (the calibration file only exists now)."""
        if again and self._calib_task is not None and not self._calib_task.done():
            self._calib_task.cancel()
            self._calib_task = None
        if self._calib_task is None or self._calib_task.done():
            self._calib_task = asyncio.get_running_loop().create_task(self._calib_once())

    def calib_fresh(self):
        """Reply to calibration-status, only if read after this hello; returns None if not read / stale (review O5)."""
        return fresh_calib(self)

    async def _calib_once(self):
        """Calibration status is queried only once on connect and once when phase becomes control, on its own connection: it can be slow inside robotd and must not block
        busStatus (re-review #8). On failure retry at most twice, 10 seconds apart; if it still fails, give up (the page shows unknown)."""
        for attempt in range(3):
            try:
                r = await call_once(self.addr, "robot.busCommand", {"action": "calibration-status"},
                                    timeout=5.0, name="标定状态", log=self.log)
                if isinstance(r, dict):
                    self.calib.set(r)
                    return
                self.calib.fail(f"回的不是对象（{type(r).__name__}）")
            except (Unreachable, Timeout, RpcError) as e:
                self.calib.fail(e)
                if attempt == 2:
                    self.log.warn("读不到标定状态", cat="校准", raw=str(e), hint="不影响站和走；页面上标定那一项显示「不知道」")
            await asyncio.sleep(10.0)

    def _mark_present(self, ok, why=None):
        if ok and self.present is not True:
            if self.present is False:
                gone = time.monotonic() - (self.absent_since or time.monotonic())
                self.log.info(f"主程序回来了（断了 {gone:.0f} 秒）", cat="robotd")
            self.present, self.absent_since = True, None
        elif not ok and self.present is not False:
            self.present, self.absent_since = False, time.monotonic()
            self.log.warn("连不上主程序 robotd", cat="robotd", raw=str(why),
                          hint="鸭子主程序没在跑，或者正在重启（重启约 2 秒）。注意：停掉 robotd 不会卸力，舵机可能还顶着")

    def _check_build(self, bus):
        build = (bus or {}).get("build")
        if build and build not in KNOWN_BUILDS and not getattr(self, "_warned_build", False):
            self._warned_build = True
            self.log.warn(f"主程序版本 {build} Studio 还没核对过", cat="robotd",
                          hint="只读显示和卸力照常；以后的运动按钮会先置灰")

    def _mode(self):
        b = self.bus.value
        return b.get("mode") if isinstance(b, dict) else None

    def _phase(self):
        b = self.bus.value
        return b.get("phase") if isinstance(b, dict) else None

    # ---- Subscription ----

    def _want_stream(self):
        if self.paused:
            return False
        if self.force_subscribe or self.background_music or self.viewers > 0:
            return True
        return time.monotonic() - self._last_viewer_at < STREAM_LINGER_S

    async def _stream_loop(self):
        fails = 0
        while True:
            if not self._want_stream() or self._mode() != "motion" or self._phase() != "control":
                self._wake_stream.clear()
                try:
                    await asyncio.wait_for(self._wake_stream.wait(), 1.0)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await self._stream_once()
                fails = 0
            except (Unreachable, RpcError) as e:
                fails += 1
                self.log.warn("实时状态订阅断了", cat="robotd", raw=str(e))
                await asyncio.sleep(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
            except asyncio.TimeoutError:
                fails += 1
                self.log.warn("实时状态 3 秒没来新帧，重新订阅", cat="robotd")

    async def _stream_once(self):
        r, w = await asyncio.wait_for(open_conn(self.addr), 3.0)
        self.stream_open = True
        self.log.info(f"开始订阅实时状态（{STREAM_HZ} Hz，{self.viewers} 个页面在看）", cat="robotd")
        try:
            try:
                w.write(encode(1, "robot.subscribe", {"hz": int(STREAM_HZ)}))   # hz must be an integer (u32)
                await w.drain()
            except (ConnectionError, OSError) as e:
                raise Unreachable(f"订阅请求没发出去：{type(e).__name__}: {e}") from e
            while True:
                msg = await read_message(r, 3.0)
                if msg is None:
                    continue
                if msg.get("id") == 1:
                    if "error" in msg:
                        err = msg["error"] or {}
                        raise RpcError("robot.subscribe", err.get("code"), err.get("message", ""))
                    continue
                if msg.get("method") == "robot.state":
                    self.state.set(msg.get("params"))
                if not self._want_stream():
                    self.log.info("没人在看了，停止订阅", cat="robotd")
                    return
        finally:
            self.stream_open = False
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass

    # ---- configd ----

    async def _configd_loop(self):
        """system.info 60 s, pad.status 5 s; each item backs off on its own errors (code review #19: previously, when system.info
        kept failing, pad.status never got its turn)."""
        due = {"info": 0.0, "pad": 0.0}
        down = {"info": False, "pad": False}
        while True:
            now = time.monotonic()
            for key, method, sample, every in (("info", "system.info", self.sysinfo, 60.0),
                                               ("pad", "pad.status", self.pad, 5.0)):
                if now < due[key]:
                    continue
                try:
                    sample.set(await self.cfg.call(method, {}, timeout=2.0))
                    due[key] = now + every
                    if down[key]:
                        down[key] = False
                        self.log.info(f"configd 的 {method} 恢复了", cat="手柄")
                except (Unreachable, Timeout, RpcError) as e:
                    sample.fail(e)
                    due[key] = now + 5.0
                    if not down[key]:
                        down[key] = True
                        self.log.warn(f"configd 的 {method} 读不到", cat="手柄", raw=str(e),
                                      hint="有的鸭子关掉了 configd；不影响站和走，只是手柄那一栏显示「不知道」")
            await asyncio.sleep(0.5)

    # ---- Read-only self-check (--selfcheck) ----

    async def selfcheck(self):
        """Read-only. Besides asking each item once, also checks the permissions of the three sockets (on the robot, the robot group is the most common snag),
        and whether "query on a new connection without hello first" works (relax always sends directly on a new connection)."""
        import grp
        import os
        import pwd
        out = {}
        try:
            me = pwd.getpwuid(os.getuid()).pw_name
            groups = sorted(grp.getgrgid(g).gr_name for g in os.getgroups())
            out["用户"] = f"{me} · 组 {','.join(groups)}"
        except (ImportError, KeyError, OSError) as e:
            out["用户"] = f"（查不到：{e}）"
        for path in ("/run/robotd.sock", "/run/configd.sock", "/run/padd/pad.sock"):
            if not os.path.exists(path):
                out[path] = "不在"
            else:
                out[path] = "可读写" if os.access(path, os.R_OK | os.W_OK) else "没权限（把用户加进 robot 组）"
        for name, method, params, addr in (
            ("新连接直接查", "robot.health", {}, self.addr),
            ("hello", "hello", {"api_version": API_VERSION}, self.addr),
            ("busStatus", "robot.busStatus", {}, self.addr),
            ("pad.status", "pad.status", {}, self.cfg.addr),
            ("system.info", "system.info", {}, self.cfg.addr),
        ):
            try:
                r = await call_once(addr, method, params, timeout=3.0)
                if name == "busStatus":
                    out[name] = f"ok · mode={r.get('mode')} phase={r.get('phase')} build={r.get('build')}"
                elif name == "hello":
                    out[name] = f"ok · 接口 v{r.get('api_version')} 版本 {r.get('daemon_version')}"
                else:
                    out[name] = "ok"
            except Exception as e:  # noqa: BLE001
                out[name] = f"失败：{e}"
        return out


def _round(x, nd=2):
    return None if x is None else round(x, nd)


def fresh_calib(rd):
    """The value of rd.calib, but only if read "after this hello" (overview reorg review O5). If rd has no calib_valid_after (fakes in tests)
    don't block. Anything that is not a dict is None."""
    s = getattr(rd, "calib", None)
    if s is None or not isinstance(s.value, dict) or s.at is None:
        return None
    after = getattr(rd, "calib_valid_after", None)
    if after is not None and s.at < after:
        return None
    return s.value
