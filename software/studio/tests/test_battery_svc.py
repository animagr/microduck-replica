"""Battery estimation wired into Studio (battery-plan.md v2 §6 B2/B3): the 1 Hz service (studio/battery_svc.py), battery in summarize / to-dos
(also shown while tuning servos: review B-R6), battery.op on the settings page, the fake robotd's battery script, and "站起来" (stand up) no longer blocked by battery level.
How to run (in the studio directory):
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_battery_svc'])"
"""
import asyncio
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

from fake_robotd import BAT_OFFSETS, FakeRobotd  # noqa: E402
from studio import battery as B  # noqa: E402
from studio.battery_svc import BatteryService  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Robotd  # noqa: E402
from studio.state import summarize  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


def fixture_bus():
    for line in open(FIXTURE, encoding="utf-8"):
        d = json.loads(line)
        if d.get("method") == "robot.busStatus":
            return d["reply"]["result"]
    raise AssertionError("回放里没有 busStatus")


def set_sample(sample, value, at):
    sample.value, sample.at, sample.error = value, at, None


def bus_with(volts, torque=True, policy=False):
    b = copy.deepcopy(fixture_bus())
    for j, v in zip(b["native"]["joints"], volts):
        j["volts"] = v
        j["feedback_fresh"] = True
    b["native"]["torque_state_confirmed"] = torque
    b["policy_enabled"] = policy
    return b


class FakeServo:
    """What it looks like when Studio holds the bus itself while tuning servos: state open, snapshot() gives each servo's voltage / torque."""

    def __init__(self, volt=7.2, torque=0):
        self.state, self.volt, self.torque_v = "open", volt, torque
        self.latched, self.sim, self.port, self.handed_back_at = False, True, None, None

    def snapshot(self):
        rows = [{"id": i, "cn": f"第{i}颗", "volt": self.volt, "fresh": True, "torque": self.torque_v} for i in range(15)]
        return {"t": "servo", "state": self.state, "rows": rows, "online": 15, "total": 15,
                "avg_volts": self.volt, "battery_pct": B.linear_pct(self.volt), "all_off": self.torque_v == 0}

    def estop_status(self):
        return {"state": "confirmed", "why": "15 颗都已卸力（总线回读）"}

    def holding(self):
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = Log(self.dir / "logs", echo=False, background=False)
        self.rd = Robotd("none", "none", self.log)
        self.state = str(self.dir / "state")

    def tearDown(self):
        self.tmp.cleanup()

    def svc(self, **kw):
        return BatteryService(self.rd, self.log, self.state, **kw)

    def feed_bus(self, svc, volts, n, t0=None, torque=True, policy=False, per_tick=1):
        """n seconds: a new busStatus every second (sample time = that second), tick per_tick times per second (simulating several pages). Returns the next second."""
        t = time.monotonic() if t0 is None else t0
        for i in range(n):
            now = t + i
            set_sample(self.rd.bus, bus_with([volts] * 15 if isinstance(volts, float) else volts, torque, policy), now)
            for k in range(per_tick):
                svc.tick(now + k * 0.1)
        return t + n

    def msgs(self, cat=B.LOG_CAT):
        return [e["msg"] for e in self.log.recent(200, cats=[cat], min_level="debug")]


class ServiceTest(Base):
    def test_robotd_source_and_dedup(self):
        """busStatus once per second; the same one fed several times (3 pages, 10 Hz shouldn't matter) counts only once (review B-R7)."""
        s = self.svc()
        t = self.feed_bus(s, 7.62, 40, per_tick=3)
        self.assertEqual(len(s.est.samples), 40)
        v = s.view(t)
        self.assertEqual(v["mode"], "calm")
        self.assertEqual(v["source"], "robotd")
        self.assertEqual(v["cls"], "light")             # no robot.state: torque on, policy off → holding (won't walk)
        self.assertEqual(v["pct"], round(B.soc_from_pack(7.62)))
        self.assertTrue(any("电量估算起步" in m for m in self.msgs()))

    def test_limp_without_state_stream_is_rest(self):
        s = self.svc()
        t = self.feed_bus(s, 7.62, 40, torque=False)
        self.assertEqual(s.view(t)["cls"], "rest")
        self.assertEqual(s.view(t)["why"], "静置")

    def test_stale_bus_restarts(self):
        s = self.svc()
        t = self.feed_bus(s, 7.62, 40)
        for i in range(15):                              # busStatus stops updating (robotd stopped, disconnected)
            s.tick(t + i)
        self.assertEqual(s.view(t + 15)["mode"], "no_data")
        self.assertTrue(any("读不到电压超过" in m for m in self.msgs()))

    def test_state_stream_classifies_walking(self):
        s = self.svc()
        t = time.monotonic()
        for i in range(60):
            now = t + i
            set_sample(self.rd.bus, bus_with([7.4] * 15, policy=True), now)
            set_sample(self.rd.state, {"policy": "walk", "move": {"applied": [0.2, 0, 0]}, "safety": {"fallen": False}}, now)
            s.tick(now)
        v = s.view(t + 59)
        self.assertEqual(v["cls"], "heavy")
        self.assertEqual(v["mode"], "load_rough")
        self.assertEqual(v["why"], "走路中，按负载电压粗估，偏低")

    def test_servo_session_source_and_todo(self):
        """While tuning servos, voltage comes from Studio's own bus readings; the battery to-do still appears (review B-R6), and the wording says the main program is stopped."""
        servo = FakeServo(volt=7.2)
        s = self.svc(servo=servo)
        t = time.monotonic()
        for i in range(100):
            s.tick(t + i)
        v = s.view(t + 99)
        self.assertEqual(v["source"], "servo")
        self.assertEqual(v["cls"], "rest")
        self.assertTrue(v["red"])
        st = summarize(self.rd, {"label": "鸭"}, servo, now=t + 99, bat=s)
        self.assertEqual(st["posture"], "servo_session")
        self.assertEqual(st["battery"]["pct"], v["pct"])
        keys = [i["key"] for i in st["todo"]]
        self.assertIn("battery", keys)
        self.assertIn("servo_session", keys)
        bat = next(i for i in st["todo"] if i["key"] == "battery")
        self.assertEqual(bat["level"], "error")
        self.assertIn("调舵机时主程序停着，没电它不会自己坐下", bat["hint"])
        self.assertLess(keys.index("battery"), keys.index("servo_session"))   # red ones go first

    def test_switch_robotd_to_servo_keeps_estimate(self):
        servo = FakeServo(volt=7.62)
        servo.state = "closed"
        s = self.svc(servo=servo)
        t = self.feed_bus(s, 7.62, 60, torque=False)
        before = s.view(t)["pct"]
        servo.state = "open"
        for i in range(30):
            s.tick(t + i)
        self.assertEqual(s.view(t + 29)["pct"], before)
        self.assertEqual(s.view(t + 29)["mode"], "calm")

    def test_summarize_without_estimator_is_unchanged(self):
        set_sample(self.rd.bus, bus_with([7.5] * 15), time.monotonic())
        set_sample(self.rd.health, {"battery": {"percent": 55.0, "volts": 7.48}}, time.monotonic())
        st = summarize(self.rd, {"label": "鸭"})
        self.assertEqual(st["battery"], {"pct": 55.0, "volts": 7.48})

    def test_summarize_with_estimator(self):
        s = self.svc()
        t = self.feed_bus(s, 7.30, 120, torque=False)        # 19%: yellow
        set_sample(self.rd.health, {"battery": {"percent": 43.0, "volts": 7.29}}, t)
        st = summarize(self.rd, {"label": "鸭"}, now=t, bat=s)
        b = st["battery"]
        self.assertEqual(b["mode"], "calm")
        self.assertEqual(b["rd_pct"], 43)
        self.assertTrue(b["warn"])
        item = next(i for i in st["todo"] if i["key"] == "battery")
        self.assertEqual(item["level"], "warn")
        self.assertEqual(item["msg"], f"电量约 {b['pct']}%")

    def test_shutdown_wording(self):
        class Ob:
            battery_shutdown = True
        s = self.svc(onboard=Ob())
        t = self.feed_bus(s, 7.15, 120, torque=False)
        hint = next(i for i in B.todo_items(s.view(t)) if i["key"] == "battery")["hint"]
        self.assertIn("6.6 V", hint)
        Ob.battery_shutdown = False
        hint = next(i for i in B.todo_items(s.view(t)) if i["key"] == "battery")["hint"]
        self.assertIn("不会自己停", hint)

    def test_speed(self):
        s = self.svc(speed=20)
        self.assertTrue(any("倍速快进" in m for m in self.msgs()))
        t0 = time.monotonic()
        set_sample(self.rd.bus, bus_with([7.62] * 15, torque=False), t0)
        for i in range(40):                                   # when fast-forwarding, the same busStatus also counts as a new sample: 2 seconds real time = 40 seconds
            s.tick(t0 + i * 0.05)
        self.assertEqual(s.view(t0 + 2.0)["mode"], "calm")


class OpTest(Base):
    def run_op(self, s, args):
        return asyncio.run(s.handle(args, by="测试"))

    def test_get_set(self):
        s = self.svc()
        d = self.run_op(s, {"op": "get"})
        self.assertEqual(d["settings"], B.DEFAULTS)
        self.assertEqual(set(d["presets"]), {"2s_liion", "bench"})
        d = self.run_op(s, {"op": "set", "values": {"red_pct": 20, "load_floor_v": 7.0}})
        self.assertEqual((d["settings"]["red_pct"], s.est.settings["red_pct"]), (20, 20))   # takes effect immediately
        with open(B.settings_path(self.state), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["load_floor_v"], 7.0)
        self.assertTrue(any("电池设置改了：红线 15% → 20%" in m for m in self.msgs()))
        # Restart Studio: read back
        self.assertEqual(self.svc().settings["red_pct"], 20)
        with self.assertRaises(ValueError) as cm:
            self.run_op(s, {"op": "set", "values": {"red_pct": 29}})          # not 5% below the warning line
        self.assertIn("至少低 5%", str(cm.exception))
        with self.assertRaises(ValueError):
            self.run_op(s, {"op": "set", "values": {"capacity_mah": 2600}})
        with self.assertRaises(ValueError):
            self.run_op(s, {"op": "nope"})
        self.assertEqual(s.settings["red_pct"], 20)                           # rejected value didn't change anything

    def test_bench_preset(self):
        s = self.svc()
        self.run_op(s, {"op": "set", "values": {"preset": "bench"}})
        t = self.feed_bus(s, 7.40, 40, torque=False)
        v = s.view(t)
        self.assertEqual(v["mode"], "bench")
        self.assertIsNone(v["pct"])
        self.assertEqual(v["volts"], 7.4)
        self.assertEqual(B.todo_items(v), [])
        self.assertNotIn("放空了尽快充", "\n".join(v["detail"]))                 # no battery, so no care advice
        t = self.feed_bus(s, 6.70, 60, t0=t)
        items = B.todo_items(s.view(t))
        self.assertEqual(items[0]["msg"], "电源电压很低：6.70 V")
        self.assertIn("限流", items[0]["hint"])

    def test_calibrate(self):
        s = self.svc()
        r = self.run_op(s, {"op": "calibrate", "measured_v": 7.8})
        self.assertFalse(r["ok"])                                             # not rested yet
        t0 = time.monotonic() - 45
        self.feed_bus(s, 7.62, 40, t0=t0, torque=False)
        r = self.run_op(s, {"op": "calibrate", "measured_v": 7.80})
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["offset"], 0.18, places=2)
        self.assertEqual(r["current"], 0.0)
        self.assertEqual(s.settings["cal_offset_v"], 0.0)                     # compute only, don't save
        self.run_op(s, {"op": "set", "values": {"cal_offset_v": r["offset"]}})
        self.assertEqual(s.est.off, 0.18)

    def test_bad_file_at_start(self):
        os.makedirs(self.state, exist_ok=True)
        with open(B.settings_path(self.state), "w", encoding="utf-8") as f:
            f.write("{坏")
        s = self.svc()
        self.assertEqual(s.settings, B.DEFAULTS)
        self.assertTrue(os.path.exists(B.settings_path(self.state) + ".bad"))
        self.assertTrue(any("电池设置读不出来" in m for m in self.msgs()))


class FakeRobotdBatteryTest(unittest.TestCase):
    def call(self, f, method, params=None):
        return asyncio.run(f.dispatch(method, params or {}))[0]

    def test_script(self):
        f = FakeRobotd(str(FIXTURE), posture="limp")
        recorded = [j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]]
        self.call(f, "fake.set", {"battery": {"v": 7.6}})
        vs = [j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]]
        self.assertEqual(vs, [round(7.6 + o, 1) for o in BAT_OFFSETS])
        self.assertAlmostEqual(B.trimmed(vs)[0], 7.62, delta=0.01)            # duck #2's set: trimmed mean 7.62
        h = self.call(f, "robot.health")["battery"]
        self.assertAlmostEqual(h["volts"], sum(vs) / 15, places=3)
        self.assertAlmostEqual(h["percent"], B.linear_pct(h["volts"]), places=3)
        f.set_posture("holding")                                              # torque on: 0.08 lower
        self.assertLess(B.trimmed([j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]])[0], 7.6)
        self.call(f, "fake.set", {"battery": {"glitch": 4.2}})
        self.assertEqual({j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]}, {4.2})
        self.assertNotEqual({j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]}, {4.2})   # only once
        self.call(f, "fake.set", {"battery": {"gone": True}})
        self.assertEqual({j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]}, {0.0})
        self.call(f, "fake.set", {"battery": None})
        self.assertEqual([j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]], recorded)


try:
    from tests.test_pad import POLICIES, PadTestBase, bus as pad_bus   # noqa: E402
except Exception:  # noqa: BLE001 -- if the gamepad test tooling has problems, the other battery tests still run
    PadTestBase = None

if PadTestBase is not None:
    class StandNotBlockedTest(PadTestBase):
        """User Oct 18: the battery only warns; even at the red line it doesn't block "站起来" (stand up) (previously blocked at 10% per robotd's linear mapping, and the wording even said it would sit down and shut off by itself)."""

        def test_low_battery_does_not_block_stand(self):
            self.robot_ok(torque_on=False, posture="limp", battery_pct=3.0, bus=pad_bus(False), policies=POLICIES)
            self.ops._relax_at = -1e9                        # not just relaxed (right after relaxing there's a separate guard unrelated to battery)
            stand = self.ops.snapshot()["motion"]["buttons"]["stand"]
            self.assertTrue(stand["ok"], stand)
            self.assertEqual(stand["call"], "robot.init")
            self.assertIsNone(stand["why"])

        def test_low_battery_note_follows_robotd_shutdown_setting(self):
            """Task 1 addendum: low battery only warns, doesn't block; the wording follows the real config read by onboard.read_battery_shutdown()."""
            self.robot_ok(torque_on=False, posture="limp", battery_pct=3.0, bus=pad_bus(False), policies=POLICIES)
            self.ops._relax_at = -1e9
            self.ops.battery_shutdown = False
            stand = self.ops.snapshot()["motion"]["buttons"]["stand"]
            self.assertTrue(stand["ok"], stand)
            self.assertIn("电量只剩 3%", stand["note"])
            self.assertIn("先充电再玩", stand["note"])
            self.assertIn("不会自己坐下", stand["note"])
            self.ops.battery_shutdown = True
            note = self.ops.snapshot()["motion"]["buttons"]["stand"]["note"]
            self.assertIn("会自己坐下关机", note)


if __name__ == "__main__":
    unittest.main()
