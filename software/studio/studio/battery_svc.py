"""Hooking battery estimation into Studio (battery-plan.md v2 §6 B2/B3): a 1 Hz loop feeds the estimator, summarize only reads results, plus the page's battery.op.

Why a separate loop (review B-R7): summarize runs 10 times per second per page, so feeding samples there would mean 30 duplicate values per second with three pages open.
Here it ticks once per second, deduplicating by busStatus's sample time (Sample.at); during servo tuning (Studio holds the bus itself and robotd is deliberately stopped)
it takes each servo's voltage from servo.snapshot(), the same register, so there is no restart when switching.

Settings are stored in state_dir/battery-settings.json (read, written and validated by studio/battery.py); a change replaces the estimator's settings immediately and takes effect on the next tick.
Warnings only: no commands are sent to the duck from here.
"""
import asyncio
import os
import time

from . import battery as B
from .state import JOINT_CN, MAX_AGE

TICK_S = 1.0
BUS_STALE_S = 3.0       # busStatus not updated for this long: treat this tick as no new data (after 10 seconds the estimator restarts by itself)
# For development (end-to-end tests, screenshots): estimator time is fast-forwarded by this factor (30 s estimating and 60 s before lighting up become 1.5 s and 3 s at 20x).
# When fast-forwarding, every tick feeds the latest reading as a new sample (no dedup by busStatus sample time). Do not set on the duck
SPEED_ENV = "STUDIO_BATTERY_SPEED"


class BatteryService:
    def __init__(self, robotd, log, state_dir=None, servo=None, onboard=None, speed=None):
        self.rd, self.log, self.state_dir, self.servo, self.onboard = robotd, log, state_dir, servo, onboard
        self.settings = B.load_settings(state_dir, log)
        self.est = B.Estimator(self.settings)
        self.names = None
        self.errors = 0
        if speed is None:
            try:
                speed = float(os.environ.get(SPEED_ENV) or 1.0)
            except ValueError:
                speed = 1.0
        self.speed = max(1.0, speed)
        self._t0 = time.monotonic()
        if self.speed != 1.0:
            log.warn(f"开发用：电量估算按 {self.speed:g} 倍速快进", cat=B.LOG_CAT, raw=f"{SPEED_ENV}={self.speed:g}",
                     hint="只给端到端测试、截图用；鸭子上不要设这个环境变量")

    def clock(self, now=None):
        """Time used by the estimator (scaled by the factor when fast-forwarding)."""
        now = time.monotonic() if now is None else now
        return self._t0 + (now - self._t0) * self.speed

    # ---- One tick ----

    def sample(self, now):
        """This tick's input: (voltage, fresh, cls, key, source, name) or None (no new data)."""
        sv = self.servo
        if sv is not None and getattr(sv, "state", None) == "open":
            snap = sv.snapshot()
            rows = snap.get("rows") if isinstance(snap, dict) else None
            vs, fr = B.servo_session_volts(rows)
            if vs is None:
                return None
            names = [r.get("cn") if isinstance(r, dict) else None for r in rows]
            # The servo table has no sample time: dedup by second (the estimator also dedups by time when no key is given)
            return vs, fr, B.classify_servo_session(rows), ("servo", int(now)), "servo", names
        bus = self.rd.bus.value
        age = self.rd.bus.age(now)
        if bus is None or age is None or age > BUS_STALE_S:
            return None
        vs, fr = B.robotd_volts(bus)
        if vs is None:
            return None
        st_age = self.rd.state.age(now)
        st = self.rd.state.value if st_age is not None and st_age <= MAX_AGE["state"] else None
        joints = ((bus.get("native") or {}).get("joints") or []) if isinstance(bus.get("native"), dict) else []
        names = [JOINT_CN.get(j.get("name"), j.get("name")) if isinstance(j, dict) else None for j in joints]
        cls = B.classify_robotd(bus, st) if st is not None else None
        if cls is None and st is None and isinstance(bus.get("native"), dict):
            # The state stream is not pushing (robotd does not push robot.state when nobody is watching the page): only look at busStatus. Relaxed is relaxed;
            # torque on with the policy off = holding HOME (will not walk); with the policy on it may be walking, so count it as unknown
            torque = bus["native"].get("torque_state_confirmed")
            if torque is False:
                cls = "rest"
            elif torque is True and bus.get("policy_enabled") is False:
                cls = "light"
        return vs, fr, cls, ("bus", self.rd.bus.at), "robotd", names

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        s = self.sample(now)
        t = self.clock(now)
        if s is None:
            events = self.est.feed(t, None)
        else:
            vs, fr, cls, key, source, names = s
            self.names = names
            events = self.est.feed(t, vs, fr, cls, key=key if self.speed == 1.0 else None, source=source)
        B.log_events(self.log, events)
        return events

    def view(self, now=None):
        """For summarize (10 times per second × each page): reads memory only, computes no new samples."""
        now = time.monotonic() if now is None else now
        h = self.rd.health
        health = h.value if h.age(now) is not None and h.age(now) <= MAX_AGE["health"] else None
        rd = (health or {}).get("battery") if isinstance(health, dict) else None
        shutdown = getattr(self.onboard, "battery_shutdown", None) if self.onboard is not None else None
        return self.est.view(self.clock(now), rd=rd, names=self.names, shutdown=shutdown)

    async def loop(self):
        while True:
            await asyncio.sleep(TICK_S / self.speed)
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                self.log.error("电量估算出错", cat=B.LOG_CAT, raw=f"{type(e).__name__}: {e}", exc=True,
                               hint="这是 Studio 的问题，导出诊断包发出来；不影响站和走")
                await asyncio.sleep(5.0)

    # ---- The page's battery.op ----

    async def handle(self, args, by="?"):
        """{op:"get"} → settings + notes; {op:"set", values:{…}} → validate, save, take effect immediately;
        {op:"calibrate", measured_v} → compute a reading calibration (not saved; set after the page confirms). Invalid input raises ValueError (with a human-readable reason)."""
        op = (args or {}).get("op")
        if op == "get":
            return self._payload()
        if op == "set":
            values = (args or {}).get("values")
            good, errors = B.validate_settings(values, self.settings)
            if errors:
                raise ValueError("；".join(errors))
            old = dict(self.settings)
            if good == old:
                return self._payload()
            try:
                saved = await asyncio.to_thread(B.save_settings, self.state_dir, good)
            except B.SettingsError as e:
                self.log.warn("电池设置没存进去", cat=B.LOG_CAT, raw=str(e), hint="state 目录满了或者没权限")
                raise ValueError(str(e)) from None
            self.settings = saved
            self.est.set_settings(saved)
            self.log.info(f"电池设置改了：{B.settings_changes(old, saved)}", cat=B.LOG_CAT, raw=f"by={by}")
            return self._payload()
        if op == "calibrate":
            mv = (args or {}).get("measured_v")
            r = self.est.calibrate(self.clock(), mv)
            if r["ok"]:
                self.log.info(f"「我量了电池电压」：{r['reason']}（还没存，等确认）", cat=B.LOG_CAT, raw=f"by={by}")
            return dict(r, current=self.settings["cal_offset_v"])
        raise ValueError(f"不认识的电池操作：{op}")

    def _payload(self):
        return {"settings": dict(self.settings), "defaults": dict(B.DEFAULTS), "ranges": {k: list(v) for k, v in B.RANGES.items()},
                "presets": dict(B.PRESETS), "path": B.settings_path(self.state_dir)}
