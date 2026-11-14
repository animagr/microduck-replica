"""Backend of the overview reorg (overview-merge-plan.md §5, review overview-merge-review.md): onboarding checklist (studio/onboard.py),
board temperature cell (state.cpu_view), calibration status only counts if read after this hello (robotd.fresh_calib), the IMU page's "核对过" (checked) record.

The checklist's rules follow the "final rule for each checklist step" table at the end of the review (§5 O14 changed it to 6 rows, task 11 added "写进主程序" (commit to main program)); each step is tested in four states: ✓ ok · ● todo · ○ no · ? unk.
How to run (in the studio directory):
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_onboard'])"
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

from fake_robotd import FakeRobotd  # noqa: E402
from studio import onboard as O  # noqa: E402
from studio.imu import ImuBackend  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Robotd, Sample, fresh_calib  # noqa: E402
from studio.state import cpu_view, summarize, todo  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
XBOX = "78:86:2E:BB:13:28"


def recorded():
    f = FakeRobotd(FIXTURE)
    return copy.deepcopy(f.bus), copy.deepcopy(f.calib), copy.deepcopy(f.health)


BUS, CALIB, HEALTH = recorded()
BUILD = BUS["build"]


def calib_with(dirs=None, **joint_zero):
    c = copy.deepcopy(CALIB)
    for j in c["calibration"]["joints"]:
        if j["name"] in joint_zero:
            j["zero_raw"] = joint_zero[j["name"]]
        if dirs and j["name"] in dirs:
            j["direction"] = dirs[j["name"]]
    return c


def pad_view(known=True, pads=(), attached=False, device=None, estop="ok", checks=None):
    pads = [dict(p) for p in pads]
    active = next((p for p in pads if p.get("connected")), None)
    return {"known": known, "error": None if known else "读不到", "pads": pads, "active": active, "attached": attached,
            "device": device, "estop": {"state": estop, "checks": checks or []}}


XPAD = {"mac": XBOX, "name": "Xbox Wireless Controller", "paired": True, "trusted": True, "connected": True}


def inp(bus=None, calib="rec", pad=None, studio=None, present=True, servo_session=False, commit=None, starting_s=None):
    bus = copy.deepcopy(BUS) if bus is None else bus
    calib = copy.deepcopy(CALIB) if calib == "rec" else calib
    return {"bench": False, "present": present, "bus": bus, "calib": calib, "servo_session": servo_session,
            "pad": pad if pad is not None else pad_view(), "studio_servo": studio or {"ids": set(), "time": None},
            "fp": O.full_fp(bus, calib), "commit": commit, "starting_s": starting_s}


def row(view, key):
    return next(r for r in view["rows"] if r["key"] == key)


class FakeRd:
    """What robotd.Robotd looks like (onboard / summarize only read these)."""

    def __init__(self, bus=None, calib="rec", health="rec", present=True):
        self.addr = "tcp:x"
        self.present = present
        self.bus, self.calib, self.health = Sample(), Sample(), Sample()
        self.policies, self.state, self.pad, self.sysinfo, self.hello = Sample(), Sample(), Sample(), Sample(), Sample()
        self.calib_valid_after = None
        self.bus.set(copy.deepcopy(BUS) if bus is None else bus)
        if calib is not None:
            self.calib.set(copy.deepcopy(CALIB) if calib == "rec" else calib)
        if health is not None:
            self.health.set(copy.deepcopy(HEALTH) if health == "rec" else health)
        self.policies.set({"sitting": False, "homed": True})
        from studio.estop import EStop
        self.estop = EStop()


# ---------------- Each checklist step ----------------

class RowTest(unittest.TestCase):
    def test_header(self):
        self.assertTrue(O.header_of(inp())["ok"])
        self.assertEqual(O.header_of(inp(present=False))["kind"], "absent")
        stuck = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus", "error": "motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the lsm6dsv16x IMU"}
        h = O.header_of(inp(bus=stuck, calib=None))
        self.assertEqual(h["kind"], "stuck_calib")
        self.assertIn("标定或 IMU 方向没过", h["text"])
        self.assertIn("verified IMU mounting", h["raw"])
        h = O.header_of(inp(bus=dict(stuck, error="Feetech Sync Read timeout; missing IDs [21]"), calib=None))
        self.assertEqual(h["kind"], "starting")
        self.assertIn("等待总线设备响应", h["text"])
        self.assertEqual(O.header_of(inp(bus={"mode": "commissioning", "phase": "ready"}))["kind"], "commissioning")
        self.assertEqual(O.header_of(inp(servo_session=True))["kind"], "servo")

    def test_header_commissioning_boot_report_and_snapshot(self):
        """Task 16: before a successful read in calibration mode, busStatus is a startup report (starting); after a successful read, every live snapshot counts as the main program being up.
        When a startup phase has been reported for more than 30 seconds in a row, the card header no longer says "还在启动" (still starting) (Oct 20 real hardware: the old fork always reports configuring_bus)."""
        boot = {"build": BUILD, "mode": "commissioning", "phase": "configuring_bus", "port": "/dev/ttyS2"}
        h = O.header_of(inp(bus=boot))
        self.assertEqual((h["kind"], h["text"]), ("starting", "主程序还在启动"))
        h = O.header_of(inp(bus=boot, starting_s=31))
        self.assertEqual(h["kind"], "starting")
        self.assertIn("主程序一直报「启动中」，超过 30 秒了", h["text"])
        self.assertIn("旧版主程序的毛病", h["text"])
        self.assertIn("去日志页", h["text"])
        self.assertNotIn("10 秒", h["text"])
        h = O.header_of(inp(bus=dict(boot, phase="waiting_for_bus", error="Feetech Sync Read timeout"), starting_s=40))
        self.assertIn("等待总线设备响应", h["text"])
        self.assertEqual(h["raw"], "Feetech Sync Read timeout")
        for phase in ("ready", "moving", "stop_unconfirmed", "power_pending", "read_error"):
            with self.subTest(phase=phase):
                self.assertEqual(O.header_of(inp(bus={"mode": "commissioning", "phase": phase}))["kind"], "commissioning")
        h = O.header_of(inp(bus={"mode": "commissioning", "phase": "read_error", "last_cycle_error": "missing IDs [21]"}))
        self.assertIn("读舵机出错", h["text"])
        self.assertEqual(h["raw"], "missing IDs [21]")                         # carries the main program's original message as is

    def test_servo_four_states(self):
        rec = {}
        # ● All 15 are 2048 in the main program's file, but Studio has no record (could be bundled seed values or hand edits): go to the servo page + "已完成" (Done) / "跳过" (Skip)
        # (the former second button "已经校过，核对一下" (already calibrated, check it) is now "已完成" (Done): user Oct 20)
        r = row(O.evaluate(inp(), rec), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertEqual([a["do"] for a in r["actions"]], ["servos"])
        self.assertEqual(r["mark"]["done"], {"confirm": False, "ask": None})
        self.assertIn("已完成", r["text"])
        # ● zero_raw is not 2048: the two zero-position schemes would conflict; list which servo and by how many degrees
        r = row(O.evaluate(inp(calib=calib_with(left_knee=1990)), rec), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("两套零位会打架", r["text"])
        self.assertIn("左膝 1990（差 -5.1°）", r["text"])
        # ✓ Studio's servo page marked all 15, and the recorded joint fingerprint hasn't changed (code review C9-3: rule table "and the fingerprint hasn't changed")
        stu = {"ids": set(O.SERVO_IDS), "time": "2026-10-18 03:12:00"}
        ss = {"servo_studio": {"at": 1.7e9, "fp": O.joints_fp(CALIB), "src": stu["time"]}}
        r = row(O.evaluate(inp(studio=stu), ss), "servo")
        self.assertEqual((r["state"], r["when"]), ("ok", "2026-10-18 03:12:00"))
        r = row(O.evaluate(inp(studio=stu), {"servo_studio": dict(ss["servo_studio"], fp="old")}), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("舵机页标过以后", r["text"])
        # ✓ Clicked "已经校过，核对一下" (already calibrated, check it), fingerprint unchanged; fingerprint changed → ●
        fp = O.joints_fp(CALIB)
        self.assertEqual(row(O.evaluate(inp(), {"confirm_servo": {"at": 1.7e9, "fp": fp}}), "servo")["state"], "ok")
        r = row(O.evaluate(inp(), {"confirm_servo": {"at": 1.7e9, "fp": "old"}}), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("改过了", r["text"])
        # ○ The main program says some are uncalibrated / stuck on a calibration error
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = ["left_knee"]
        self.assertEqual(row(O.evaluate(inp(calib=c), rec), "servo")["state"], "no")
        stuck = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus", "error": "motion requires all 15 calibrated joints"}
        r = row(O.evaluate(inp(bus=stuck, calib=None), rec), "servo")
        self.assertEqual(r["state"], "no")
        self.assertIn("同一句话", r["text"])
        self.assertEqual(row(O.evaluate(inp(bus={"mode": "commissioning", "phase": "ready", "calibrated": False}, calib=None), rec),
                             "servo")["state"], "no")
        # ? Calibration file not read since this connection
        self.assertEqual(row(O.evaluate(inp(calib=None), rec), "servo")["state"], "unk")

    def test_imu_four_states(self):
        src, mount = "lsm6dsv16x", CALIB["imu_mount"]["quat"]
        mfp = O.mount_fp(src, mount)
        r = row(O.evaluate(inp(), {}), "imu")
        self.assertEqual(r["state"], "todo")                                  # the file says confirmed, but Studio hasn't checked it
        self.assertIn("8.5°", r["text"])
        ok = {"at": 1.7e9, "source": src, "mount_fp": mfp, "diff_deg": 0.8, "tilt_deg": 1.2, "ok": True}
        self.assertEqual(row(O.evaluate(inp(), {"imu_check": ok}), "imu")["state"], "ok")
        r = row(O.evaluate(inp(), {"imu_check": dict(ok, diff_deg=3.4, ok=False)}), "imu")
        self.assertEqual(r["state"], "todo")
        self.assertIn("差 3.4°", r["text"])
        r = row(O.evaluate(inp(), {"imu_check": dict(ok, mount_fp="other")}), "imu")      # orientation changed and not checked since
        self.assertEqual(r["state"], "todo")
        self.assertIn("改过了", r["text"])
        c = copy.deepcopy(CALIB)
        c["imu_mount"]["verified"] = False
        self.assertEqual(row(O.evaluate(inp(calib=c), {"imu_check": ok}), "imu")["state"], "no")
        self.assertEqual(row(O.evaluate(inp(bus={"mode": "commissioning", "phase": "ready", "imu_mount_verified": False},
                                            calib=None), {}), "imu")["state"], "no")
        self.assertEqual(row(O.evaluate(inp(calib=None), {"imu_check": ok}), "imu")["state"], "unk")

    def test_stuck_calib_distinguishes_servo_and_imu(self):
        """F5: the main program's message can't tell which item it is; only block IMU when IMU is explicitly unconfirmed, only block servos when joints are uncalibrated."""
        stuck = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus",
                 "error": "motion requires all 15 calibrated joints, measured limits and verified IMU mounting"}

        # Only servos uncalibrated, IMU confirmed: the IMU row isn't hard (can be skipped), the servo row is hard as before
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = ["left_knee"]
        bus = copy.deepcopy(stuck)
        bus["native"] = {"imu_mount_verified": True}
        r_servo = row(O.evaluate(inp(bus=bus, calib=c), {}), "servo")
        r_imu = row(O.evaluate(inp(bus=bus, calib=c), {}), "imu")
        self.assertEqual(r_servo["state"], "no")
        self.assertTrue(r_servo["hard"])
        self.assertIsNone(r_imu["hard"])

        # IMU explicitly unconfirmed, joints all calibrated (uncalibrated_joints is an empty list): IMU row hard, servo row not hard
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = []
        c["imu_mount"]["verified"] = False
        bus = copy.deepcopy(stuck)
        bus["native"] = {"imu_mount_verified": False}
        r_servo = row(O.evaluate(inp(bus=bus, calib=c), {}), "servo")
        r_imu = row(O.evaluate(inp(bus=bus, calib=c), {}), "imu")
        self.assertIsNone(r_servo["hard"])
        self.assertTrue(r_imu["hard"])
        self.assertEqual(r_imu["state"], "no")

        # Neither known: the IMU row isn't hard (unk, can be skipped), the servo row is hard as before
        bus = copy.deepcopy(stuck)
        r_servo = row(O.evaluate(inp(bus=bus, calib=None), {}), "servo")
        r_imu = row(O.evaluate(inp(bus=bus, calib=None), {}), "imu")
        self.assertTrue(r_servo["hard"])
        self.assertIsNone(r_imu["hard"])
        self.assertEqual(r_imu["state"], "unk")

    def test_pad_four_states(self):
        self.assertEqual(row(O.evaluate(inp(pad=pad_view(pads=[XPAD])), {}), "pad")["state"], "ok")
        r = row(O.evaluate(inp(pad=pad_view(pads=[dict(XPAD, connected=False)])), {}), "pad")
        self.assertEqual(r["state"], "ok")
        self.assertIn("没连", r["text"])
        r = row(O.evaluate(inp(pad=pad_view(pads=[dict(XPAD, trusted=False)])), {}), "pad")
        self.assertEqual(r["state"], "todo")
        self.assertIn("修复", r["text"])
        self.assertEqual(row(O.evaluate(inp(pad=pad_view()), {}), "pad")["state"], "no")
        r = row(O.evaluate(inp(pad=pad_view(known=False)), {"pads_seen": {XBOX: "Xbox Wireless Controller"}}), "pad")
        self.assertEqual(r["state"], "unk")                                    # configd unreadable: can't say "not configured yet"
        self.assertIn("以前配过 Xbox", r["text"])
        r = row(O.evaluate(inp(pad=pad_view(known=False, attached=True, device={"name": "Pro Controller"})), {}), "pad")
        self.assertEqual(r["state"], "ok")                                     # the bypass seeing attached counts as evidence
        self.assertEqual(row(O.evaluate(dict(inp(), pad=None), {}), "pad")["state"], "unk")   # bench mode has no gamepad backend

    def test_estop_four_states(self):
        rec = {"estop": {"at": 1.7e9, "ms": 180, "mac": XBOX, "name": "Xbox", "build": BUILD}}
        p = pad_view(pads=[XPAD])
        self.assertEqual(row(O.evaluate(inp(pad=p), {}), "estop")["state"], "no")
        r = row(O.evaluate(inp(pad=p), rec), "estop")
        self.assertEqual(r["state"], "ok")
        self.assertIn("180 ms", r["text"])
        other = dict(XPAD, mac="98:B6:E9:28:06:09", name="Pro Controller")
        r = row(O.evaluate(inp(pad=pad_view(pads=[other])), rec), "estop")
        self.assertEqual((r["state"], r["text"]), ("todo", "换了手柄：再测一次"))
        r = row(O.evaluate(inp(pad=p, bus=dict(copy.deepcopy(BUS), build="new-build")), rec), "estop")
        self.assertEqual((r["state"], r["text"]), ("todo", "主程序升级过：再测一次"))
        bad = pad_view(pads=[XPAD], estop="bad", checks=[{"key": "netpad", "label": "没开 UDP 手柄（netpad）", "ok": False, "why": "开着 [netpad]"}])
        r = row(O.evaluate(inp(pad=bad), rec), "estop")
        self.assertEqual(r["state"], "todo")
        self.assertIn("netpad", r["text"])
        r = row(O.evaluate(inp(pad=pad_view(known=False)), rec), "estop")      # tested, can't verify right now
        self.assertEqual(r["state"], "unk")
        # When not connected: the only paired one also counts as "the current gamepad"
        self.assertEqual(row(O.evaluate(inp(pad=pad_view(pads=[dict(XPAD, connected=False)])), rec), "estop")["state"], "ok")

    def test_walk_four_states(self):
        fp = O.full_fp(BUS, CALIB)
        self.assertEqual(row(O.evaluate(inp(), {}), "walk")["state"], "no")
        r = row(O.evaluate(inp(), {"stood": {"at": 1.7e9, "fp": fp}}), "walk")
        self.assertEqual(r["state"], "todo")
        self.assertIn("还没走过", r["text"])
        self.assertEqual(row(O.evaluate(inp(), {"stood": {"at": 1.7e9, "fp": fp}, "walked": {"at": 1.7e9, "fp": fp}}),
                             "walk")["state"], "ok")
        r = row(O.evaluate(inp(), {"stood": {"at": 1.7e9, "fp": "old"}, "walked": {"at": 1.7e9, "fp": "old"}}), "walk")
        self.assertEqual(r["state"], "todo")
        self.assertIn("标定改过以后还没站过、走过", r["text"])
        r = row(O.evaluate(inp(calib=None), {"stood": {"at": 1.7e9, "fp": fp}}), "walk")
        self.assertEqual(r["state"], "unk")
        self.assertIn("没法核对", r["text"])

    def test_next_points_at_first_not_done_and_not_unknown(self):
        v = O.evaluate(inp(calib=None, pad=pad_view(pads=[XPAD])), {})
        self.assertEqual([r["state"] for r in v["rows"]][:2], ["unk", "unk"])
        self.assertEqual(v["next"], "estop")                                   # skip ?, point to the first ● / ○
        self.assertFalse(v["all_done"])
        fp, mfp = O.full_fp(BUS, CALIB), O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"])
        rec = {"confirm_servo": {"at": 1.7e9, "fp": O.joints_fp(CALIB)},
               "imu_check": {"at": 1.7e9, "source": "lsm6dsv16x", "mount_fp": mfp, "diff_deg": 0.5, "tilt_deg": 1, "ok": True},
               "estop": {"at": 1.7e9, "ms": 1, "mac": XBOX, "name": "x", "build": BUILD},
               "stood": {"at": 1.7e9, "fp": fp}, "walked": {"at": 1.7e9, "fp": fp}}
        v = O.evaluate(inp(pad=pad_view(pads=[XPAD])), rec)
        self.assertTrue(v["all_done"])
        self.assertIsNone(v["next"])
        json.dumps(v)                                                          # can be pushed directly to the page


# ---------------- Records, files ----------------

class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.dir = Path(self.tmp.name) / "state"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_bad_file_is_moved_aside_and_does_not_crash(self):
        (self.dir / "onboarding.json").write_text("{坏了", encoding="utf-8")
        ob = O.Onboarding(str(self.dir), self.log)
        self.assertEqual(ob.rec, {})
        self.assertTrue((self.dir / "onboarding.json.bad").exists())
        self.assertTrue(any("读不出来" in e["msg"] for e in self.log.recent(20)))
        ob.tick(FakeRd())                                                     # can still evaluate
        self.assertEqual(len(ob.view()["rows"]), 6)
        (self.dir / "onboarding.json").write_text("[1, 2]", encoding="utf-8")  # same if the top level isn't an object
        self.assertEqual(O.Onboarding(str(self.dir), self.log).rec, {})

    def test_save_is_atomic_and_reloads(self):
        ob = O.Onboarding(str(self.dir), self.log)
        self.assertTrue(ob.note_estop({"ms": 120, "mac": XBOX.lower(), "name": "Xbox", "build": BUILD}))
        self.assertTrue(ob.save())
        self.assertFalse(ob.save())                                           # not written if unchanged
        data = json.loads((self.dir / "onboarding.json").read_text(encoding="utf-8"))
        self.assertEqual(data["estop"]["mac"], XBOX)                          # MAC normalized to upper case
        self.assertEqual(data["v"], 1)
        self.assertFalse([f for f in os.listdir(self.dir) if f.startswith(".onboarding-")])   # no temp file left behind
        self.assertEqual(O.Onboarding(str(self.dir), self.log).rec["estop"]["ms"], 120)

    def test_stood_and_walked_are_recorded_with_fingerprint(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        t = 1000.0
        for _ in range(8):                                                    # standing and holding for 3.5 seconds
            ob.tick(rd, now=t)
            t += 0.5
        self.assertEqual(ob.rec["stood"]["fp"], O.full_fp(BUS, CALIB))
        self.assertNotIn("walked", ob.rec)
        walking = copy.deepcopy(BUS)
        walking["policy_enabled"] = True
        rd.bus.set(walking)
        rd.state.set({"move": {"applied": [0.2, 0, 0]}})
        for _ in range(6):                                                    # walking for 2.5 seconds
            rd.state.set({"move": {"applied": [0.2, 0, 0]}})
            ob.tick(rd, now=t)
            t += 0.5
        self.assertIn("walked", ob.rec)
        self.assertEqual(row(ob.view(), "walk")["state"], "ok")
        # Servo zero position changed (fingerprint changed): must redo
        rd.calib.set(calib_with(left_knee=2000))
        ob.tick(rd, now=t)
        self.assertEqual(row(ob.view(), "walk")["state"], "todo")

    def test_servo_session_freezes_rows(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        ob.tick(rd)
        before = [r["state"] for r in ob.view()["rows"]]

        class Servo:
            state = "open"
        rd.calib.set(None)
        ob.tick(rd, servo=Servo())
        v = ob.view()
        self.assertTrue(v["frozen"])
        self.assertEqual(v["header"]["kind"], "servo")
        self.assertEqual([r["state"] for r in v["rows"]], before)

    def test_confirm_servo_checks_the_file(self):
        ob = O.Onboarding(str(self.dir), self.log)
        ok, why = ob.confirm_servo(FakeRd(calib=calib_with(left_knee=1990)), "电脑")
        self.assertFalse(ok)
        self.assertIn("2048", why)
        ok, why = ob.confirm_servo(FakeRd(calib=None), "电脑")
        self.assertFalse(ok)
        ok, why = ob.confirm_servo(FakeRd(), "电脑")
        self.assertTrue(ok, why)
        self.assertEqual(ob.rec["confirm_servo"]["fp"], O.joints_fp(CALIB))
        ob.tick(FakeRd())
        self.assertEqual(row(ob.view(), "servo")["state"], "ok")

    def test_studio_servo_record_reads_eeprom_backups(self):
        d = self.dir / "servo-calib"
        d.mkdir()
        (d / "eeprom-20261018-031200001.json").write_text(json.dumps(
            {"time": "2026-10-18 03:12:00", "targets": {str(i): 2048 for i in O.SERVO_IDS}, "bad": {"23": "读不到"}, "sim": False}),
            encoding="utf-8")
        (d / "eeprom-20261018-031300001.json").write_text(json.dumps(
            {"time": "2026-10-18 03:13:00", "targets": {"23": 2048}, "bad": {}, "sim": False}), encoding="utf-8")
        (d / "eeprom-20261018-031400001.json").write_text(json.dumps(
            {"time": "2026-10-18 03:14:00", "targets": {"99": 2048}, "sim": True}), encoding="utf-8")       # simulated ones don't count
        (d / "undone-eeprom-20261018-031500001.json").write_text("{}", encoding="utf-8")                   # undone ones don't count
        (d / "eeprom-broken.json").write_text("{坏", encoding="utf-8")
        r = O.studio_servo_record(str(self.dir))
        self.assertEqual(r["ids"], set(O.SERVO_IDS))
        self.assertEqual(r["time"], "2026-10-18 03:13:00")
        self.assertEqual(O.studio_servo_record(str(self.dir / "nope")), {"ids": set(), "time": None})

    def test_cpu_hysteresis(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        for c, hot in ((79.0, False), (80.0, True), (78.0, True), (77.5, True), (76.9, False), (79.9, False)):
            rd.health.set(dict(HEALTH, cpu_temp_c=c))
            ob.tick(rd)
            self.assertEqual(ob.cpu_hot, hot, c)
            # The to-do uses the same hysteresis hot as the board cell: still there at 78 °C
            v = cpu_view(rd.health.value, 0.1, BUS, True, None, ob)
            items = todo(rd.health.value, BUS, {"stale": []}, "ok", v, {}, {"pct": 60}, "holding")
            self.assertEqual(any(i["key"] == "cpu" for i in items), hot, c)

    def test_read_board_like_robotd(self):
        th, cf = self.dir / "thermal", self.dir / "cpufreq"
        for name, temp in (("thermal_zone0", "76875"), ("thermal_zone1", "81250"), ("thermal_zone2", "-1000")):
            (th / name).mkdir(parents=True)
            (th / name / "temp").write_text(temp)
        for name, kind, cur, mx in (("cooling_device0", "cpufreq-cpu0", "3", "6"), ("cooling_device1", "devfreq-gpu", "6", "6")):
            (th / name).mkdir()
            for k, v in (("type", kind), ("cur_state", cur), ("max_state", mx)):
                (th / name / k).write_text(v)
        (cf / "policy0").mkdir(parents=True)
        (cf / "policy0" / "scaling_max_freq").write_text("1008000")
        (cf / "policy0" / "cpuinfo_max_freq").write_text("1800000")
        b = O.read_board(str(th), str(cf))
        self.assertEqual(b["c"], 81.25)                                        # the hottest one; ≤ 0 skipped
        self.assertEqual(b["throttle"], {"khz": 1008000, "max_khz": 1800000, "level": 3, "max_level": 6})   # the GPU's doesn't count
        self.assertIsNone(O.read_board(str(self.dir / "nope"), str(self.dir / "nope2")))


# ---------------- Board temperature cell ----------------

class CpuViewTest(unittest.TestCase):
    def test_health_stale_is_not_normal(self):
        """Review O5: when health is stale, don't write "normal": both c and throttled are None, and the cell shows "—" plus a reason."""
        v = cpu_view(None, 12.4, BUS, True)
        self.assertIsNone(v["c"])
        self.assertIsNone(v["throttled"])
        self.assertIn("12 秒没更新", v["why"])
        self.assertIn("调试模式", cpu_view(None, None, {"mode": "commissioning"}, True)["why"])
        self.assertIn("等待总线设备响应", cpu_view(None, None, {"mode": "motion", "phase": "waiting_for_bus"}, True)["why"])
        self.assertIn("没在跑", cpu_view(None, None, None, False)["why"])

        class Servo:
            state = "open"
        self.assertIn("调舵机", cpu_view(None, None, BUS, True, Servo())["why"])
        self.assertIn("没报温度", cpu_view({"battery": {}}, 0.5, BUS, True)["why"])

    def test_throttled_limited_hot(self):
        h = dict(HEALTH, cpu_temp_c=92.4, cpu_throttle={"level": 4, "max_level": 6, "khz": 1008000, "max_khz": 1800000})
        v = cpu_view(h, 0.5, BUS, True)
        self.assertEqual((v["c"], v["throttled"], v["limited"], v["src"]), (92.4, True, False, "robotd"))
        self.assertTrue(v["hot"])
        items = todo(h, BUS, {"stale": []}, "ok", v, {}, {"pct": 60}, "holding")
        self.assertIn("降频了：1008 / 1800 MHz", next(i for i in items if i["key"] == "cpu")["msg"])
        h = dict(HEALTH, cpu_throttle={"level": 0, "max_level": 6, "khz": 1200000, "max_khz": 1800000})
        v = cpu_view(h, 0.5, BUS, True)
        self.assertEqual((v["throttled"], v["limited"]), (False, True))       # frequency-capped, not due to heat
        v = cpu_view(HEALTH, 0.5, BUS, True)
        self.assertEqual((v["c"], v["throttled"], v["limited"], v["hot"]), (76.9, False, False, False))

    def test_studio_reads_board_when_robotd_does_not(self):
        class Ob:
            cpu_hot = True
            board = {"c": 83.0, "throttle": {"level": 0, "max_level": 6, "khz": 1800000, "max_khz": 1800000}}
        v = cpu_view(None, None, {"mode": "commissioning"}, True, None, Ob())
        self.assertEqual((v["c"], v["src"], v["hot"], v["throttled"]), (83.0, "studio", True, False))

    def test_summarize_carries_onboarding_and_todo_keys(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            log = Log(Path(tmp.name) / "logs", echo=False, background=False)
            ob = O.Onboarding(tmp.name, log)
            rd = FakeRd()
            ob.tick(rd)
            s = summarize(rd, {}, ob=ob)
            self.assertEqual(len(s["onboarding"]["rows"]), 6)
            self.assertEqual(s["cpu"]["c"], 76.9)
            self.assertTrue(all("key" in t for t in s["todo"]))
            rd.health = Sample()                                               # health unreadable
            s = summarize(rd, {}, ob=ob)
            self.assertIsNone(s["cpu"]["c"])
            self.assertIsNone(s["cpu"]["throttled"])
            self.assertTrue(s["cpu"]["why"])
        finally:
            tmp.cleanup()


# ---------------- Calibration status only counts if read after this hello (review O5) ----------------

class CalibFreshTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRobotd(FIXTURE)
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", Log(Path(self.tmp.name), echo=False, background=False))
        self.rd.start()

    async def asyncTearDown(self):
        await self.rd.stop()
        self.s1.close()
        self.s2.close()
        self.tmp.cleanup()

    async def wait_for(self, cond, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.02)
        return cond()

    def calib_asks(self):
        return sum(1 for _, m in self.fake.calls if m == "robot.busCommand")

    async def test_old_calib_does_not_count_after_restart(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None))
        # After robotd restarts it's stuck waiting for the bus (calibration / IMU not passed): the old "all 15 calibrated" doesn't count
        self.fake.set_posture("stuck_calib")
        self.fake.restart(0.2)
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_valid_after is not None and self.rd.calib.at < self.rd.calib_valid_after
                                            and (self.rd.bus.value or {}).get("phase") == "waiting_for_bus"))
        self.assertIsNone(self.rd.calib_fresh())
        self.assertIsNotNone(self.rd.calib.value)                              # the old value is still there, just not trusted
        # Bus opened (phase becomes control): ask again
        n = self.calib_asks()
        self.fake.set_posture("holding")
        self.assertTrue(await self.wait_for(lambda: self.calib_asks() > n and self.rd.calib_fresh() is not None, 6.0))


class FreshCalibTest(unittest.TestCase):
    def test_fresh_calib_without_hello_info(self):
        class R:
            calib = Sample()
        r = R()
        self.assertIsNone(fresh_calib(r))
        r.calib.set({"x": 1})
        self.assertEqual(fresh_calib(r), {"x": 1})                             # fake object without calib_valid_after: not blocked
        r.calib_valid_after = time.monotonic() + 1
        self.assertIsNone(fresh_calib(r))


# ---------------- The IMU page's "核对过" (checked) (review O4: only records a note, doesn't write to the duck) ----------------

class ImuCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.ob = O.Onboarding(self.tmp.name, self.log)
        self.imu = ImuBackend(FakeRd(), self.log, self.tmp.name)
        self.imu.on_check = self.ob.note_imu_check
        self.view = self.imu.view()
        self.old = self.view["mount"]["quat"]

    def tearDown(self):
        self.tmp.cleanup()

    def res(self, diff, tilt):
        return {"ok": True, "parts": {"total_deg": diff, "stand_tilt_deg": tilt}}

    def test_close_enough_is_recorded(self):
        c = self.imu._check(self.res(0.9, 1.5), self.view, self.old, True, "电脑")
        self.assertTrue(c["ok"] and c["recorded"])
        rec = self.ob.rec["imu_check"]
        self.assertEqual(rec["mount_fp"], O.mount_fp("lsm6dsv16x", self.old))
        self.ob.tick(FakeRd())
        self.assertEqual(row(self.ob.view(), "imu")["state"], "ok")

    def test_far_or_tilted_is_recorded_but_not_ok(self):
        c = self.imu._check(self.res(3.2, 1.0), self.view, self.old, True, "电脑")
        self.assertFalse(c["ok"])
        self.assertIn("差 3.2°", c["why"])
        self.assertFalse(self.ob.rec["imu_check"]["ok"])
        c = self.imu._check(self.res(0.5, 7.0), self.view, self.old, True, "电脑")
        self.assertIn("站姿倾斜", c["why"])

    def test_unverified_mount_is_not_recorded(self):
        c = self.imu._check(self.res(0.5, 1.0), self.view, self.old, False, "电脑")
        self.assertFalse(c["ok"] or c["recorded"])
        self.assertNotIn("imu_check", self.ob.rec)


# ---------------- Code review C1–C9 (the cases in scratchpad console/overviewreview/repro_onboard.py) ----------------

class ReviewFixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.dir = Path(self.tmp.name) / "state"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        (self.dir / "onboarding.json").write_text(json.dumps(data), encoding="utf-8")

    def test_c1_bad_single_records_are_dropped_and_hot_still_works(self):
        """C1: valid JSON, but a single entry has the wrong type (diff_deg is null, walked is an empty object): that entry is dropped and a warn logged, the checklist still evaluates;
        at 85 °C the board's "有点热" (a bit hot) still lights up."""
        src, m = "lsm6dsv16x", CALIB["imu_mount"]["quat"]
        self.write({"v": 1, "imu_check": {"source": src, "mount_fp": O.mount_fp(src, m), "ok": True, "diff_deg": None},
                    "walked": {}, "stood": {"at": 1.7e9, "fp": O.full_fp(BUS, CALIB)}, "future_key": {"x": 1}})
        ob = O.Onboarding(str(self.dir), self.log)
        self.assertNotIn("imu_check", ob.rec)
        self.assertNotIn("walked", ob.rec)
        self.assertIn("stood", ob.rec)                                     # the good entries are still used
        self.assertIn("future_key", ob.rec)                                # unknown keys are kept as is
        warns = [e["msg"] for e in self.log.recent(30) if "格式不对" in e["msg"]]
        self.assertEqual(len(warns), 2)
        rd = FakeRd()
        rd.health.set(dict(HEALTH, cpu_temp_c=85.0))
        ob.tick(rd)
        self.assertTrue(ob.cpu_hot)
        self.assertEqual(row(ob.view(), "imu")["state"], "todo")
        self.assertEqual(row(ob.view(), "walk")["state"], "todo")
        # A null number in the record doesn't raise either (passed straight to evaluate, without validation)
        v = O.evaluate(inp(), {"imu_check": {"source": src, "mount_fp": O.mount_fp(src, m), "ok": False, "diff_deg": None},
                               "estop": {"at": 1.7e9, "ms": None, "mac": XBOX, "build": BUILD}})
        self.assertIn("差 ?°", row(v, "imu")["text"])

    def test_c1_evaluate_error_shows_question_marks_and_hysteresis_keeps_going(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        rd.health.set(dict(HEALTH, cpu_temp_c=85.0))
        real = O.evaluate
        O.evaluate = lambda inp, rec: 1 / 0
        try:
            ob.tick(rd)
            ob.tick(rd)
        finally:
            O.evaluate = real
        v = ob.view()
        self.assertEqual(v["header"]["kind"], "error")
        self.assertEqual([r["state"] for r in v["rows"]], ["unk"] * 6)
        self.assertIn("ZeroDivisionError", v["rows"][0]["text"])
        self.assertTrue(ob.cpu_hot)                                        # hysteresis isn't affected by checklist errors
        self.assertEqual(sum(1 for e in self.log.recent(30) if "上手清单判的时候出错" in e["msg"]), 1)   # the same kind of error is logged only once
        ob.tick(rd)
        self.assertEqual(ob.view()["header"]["kind"], "ok")                # recovers once fixed

    def test_c2_no_fingerprint_does_not_overwrite_records(self):
        """C2: robotd just restarted and calibration hasn't been read back yet (fingerprint None) while standing a full 3 seconds: don't write, don't overwrite the old record that has a fingerprint."""
        ob = O.Onboarding(str(self.dir), self.log)
        fp = O.full_fp(BUS, CALIB)
        ob.rec = {"stood": {"at": 1.7e9, "fp": fp}, "walked": {"at": 1.7e9, "fp": fp}}
        rd = FakeRd()
        rd.calib_valid_after = rd.calib.at + 1.0                           # calibration not read since this hello
        walking = copy.deepcopy(BUS)
        walking["policy_enabled"] = True
        rd.bus.set(walking)
        t = 1000.0
        for _ in range(10):
            rd.state.set({"move": {"applied": [0.2, 0, 0]}})
            ob.tick(rd, now=t)
            t += 0.5
        self.assertEqual(ob.rec["stood"]["fp"], fp)
        self.assertEqual(ob.rec["walked"]["fp"], fp)
        rd.calib.set(copy.deepcopy(CALIB))                                 # read back, content unchanged
        rd.calib_valid_after = rd.calib.at - 0.001
        ob.tick(rd, now=t)
        self.assertEqual(row(ob.view(), "walk")["state"], "ok")

    def test_c4_native_says_unverified_is_not_unknown(self):
        """C4: busStatus explicitly says IMU orientation is unconfirmed and calibration status is unreadable: step 2 is ○, not ?."""
        bus = copy.deepcopy(BUS)
        bus["native"]["imu_mount_verified"] = False
        r = row(O.evaluate(inp(bus=bus, calib=None), {}), "imu")
        self.assertEqual(r["state"], "no")
        self.assertIn("还没确认", r["text"])
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd(bus=bus, calib=None)
        ob.tick(rd)
        s = summarize(rd, {}, ob=ob)
        self.assertIn("imu_unverified", [t["key"] for t in s["todo"]])    # the to-do is still there (the frontend dedupes only when this checklist row is ○)
        self.assertEqual(row(s["onboarding"], "imu")["state"], "no")

    def test_c9_tick_does_not_touch_files(self):
        """C9-1: reading the servo-calib directory and /sys/class/thermal happens in io() (in a thread); tick only uses the cache."""
        ob = O.Onboarding(str(self.dir), self.log)
        calls = []
        real_scan, real_board = O.studio_servo_record, O.read_board
        O.studio_servo_record = lambda d: calls.append("scan") or {"ids": set(O.SERVO_IDS), "time": "2026-10-18 03:12:00"}
        O.read_board = lambda *a: calls.append("board") or {"c": 83.0, "throttle": None}
        try:
            rd = FakeRd(health=None)                                       # robotd doesn't report temperature
            ob._board_ok = True
            for _ in range(3):
                ob.tick(rd)
            self.assertEqual(calls, [])
            self.assertTrue(ob.need_board(rd))
            ob.io(board=True, now=0.0)
            self.assertEqual(calls, ["scan", "board"])
            ob.io(board=False, now=1.0)                                    # directory unchanged and 10 seconds not up: not re-read
            self.assertEqual(calls, ["scan", "board"])
            ob.io(board=False, now=20.0)
            self.assertEqual(calls.count("scan"), 2)
            ob.tick(rd)
            self.assertEqual(row(ob.view(), "servo")["state"], "ok")       # the cached Studio record is still used
            self.assertIn("servo_studio", ob.rec)                          # first match: record the fingerprint (C9-3)
            self.assertFalse(rd.health.value)
            self.assertFalse(ob.need_board(FakeRd()))                      # robotd reports temperature: no need to read it ourselves
        finally:
            O.studio_servo_record, O.read_board = real_scan, real_board

    def test_c9_studio_record_fingerprint_change_needs_recheck(self):
        ob = O.Onboarding(str(self.dir), self.log)
        ob._studio = {"ids": set(O.SERVO_IDS), "time": "2026-10-18 03:12:00"}
        rd = FakeRd()
        ob.tick(rd)
        self.assertEqual(row(ob.view(), "servo")["state"], "ok")
        rd.calib.set(calib_with(left_knee=2048, mouth=2048))
        js = rd.calib.value["calibration"]["joints"]
        js[0]["direction"] = 1                                             # direction changed: joint fingerprint changes, zero position still 2048
        ob.tick(rd)
        r = row(ob.view(), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("改过了", r["text"])

    def test_c9_concurrent_saves_keep_the_newest(self):
        """C9-2: two places saving at the same time (the 0.5-second small task, the "核对一下" (check it) button): the older one must not land on disk later and overwrite the newer one."""
        import threading
        ob = O.Onboarding(str(self.dir), self.log)
        real = O.os.replace
        first = {"slow": True}

        def slow_replace(a, b):
            if first["slow"]:
                first["slow"] = False
                time.sleep(0.3)
            return real(a, b)
        O.os.replace = slow_replace
        try:
            ob._put("stood", {"at": 1.0, "fp": "old"})
            ta = threading.Thread(target=ob.save)
            ta.start()
            time.sleep(0.05)
            ob._put("stood", {"at": 2.0, "fp": "new"})
            tb = threading.Thread(target=ob.save)
            tb.start()
            ta.join()
            tb.join()
        finally:
            O.os.replace = real
        data = json.loads((self.dir / "onboarding.json").read_text(encoding="utf-8"))
        self.assertEqual(data["stood"]["fp"], "new")


class PollReconnectTest(unittest.IsolatedAsyncioTestCase):
    """C8: the polling connection timed out and reconnected, or robotd left control: calibration already read doesn't count; hello again and re-read."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRobotd(FIXTURE)
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", Log(Path(self.tmp.name), echo=False, background=False))
        self.rd.start()

    async def asyncTearDown(self):
        await self.rd.stop()
        await asyncio.sleep(0.05)
        self.s1.close()
        self.s2.close()
        self.tmp.cleanup()

    async def wait_for(self, cond, timeout=6.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.02)
        return cond()

    def hellos(self):
        return sum(1 for _, m in self.fake.calls if m == "hello")

    async def test_timeout_reconnect_is_a_new_hello(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None))
        n, after0 = self.hellos(), self.rd.calib_valid_after
        self.fake.delays["robot.busStatus"] = 2.6                          # robotd stuck > 2 seconds: polling times out and closes the connection
        self.assertTrue(await self.wait_for(lambda: self.rd.poll.reconnects > 0, 8.0))
        self.fake.delays.pop("robot.busStatus", None)
        self.assertTrue(await self.wait_for(lambda: self.hellos() > n, 8.0))
        # When the fake robotd records the hello, Studio hasn't received the reply yet: wait for it to arrive and invalidate what was read before
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_valid_after > after0, 4.0))
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None and self.rd.calib.at > self.rd.calib_valid_after))

    async def test_leaving_control_invalidates_calib(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None
                                            and (self.rd.bus.value or {}).get("phase") == "control"))
        self.fake.set_posture("starting")                                  # not restarted, fell back to waiting for the bus
        self.assertTrue(await self.wait_for(lambda: (self.rd.bus.value or {}).get("phase") == "waiting_for_bus"))
        self.assertIsNone(self.rd.calib_fresh())
        self.fake.set_posture("holding")
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None))


# ---------------- Skip / redo (user Oct 18 on duck #2: "should allow skipping and redoing") ----------------

class FakePad:
    def __init__(self, view):
        self.view = view

    def onboard_view(self):
        return copy.deepcopy(self.view)


class SkipTest(unittest.TestCase):
    """Every row can be "已完成" (Done) / "跳过" (Skip) at any time (user Oct 20); ones with consequences need two clicks, and the backend refuses without confirmed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.ob = O.Onboarding(self.tmp.name, self.log)
        self.rd = FakeRd()
        self.pad = FakePad(pad_view(pads=[XPAD]))

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self):
        self.ob.tick(self.rd, self.pad)
        return self.ob.view()

    def test_each_step_skip_and_unskip(self):
        rec_fp = {"servo": O.joints_fp(CALIB), "imu": O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"]),
                  "estop": O._hash([XBOX, BUILD]), "walk": O.full_fp(BUS, CALIB)}
        self.pad.view = pad_view(pads=[XPAD])
        v = self.tick()
        for key in ("servo", "imu", "estop", "walk"):
            with self.subTest(step=key):
                r = row(v, key)
                if r["state"] in ("todo", "no"):
                    self.assertEqual(r["mark"]["skip"]["confirm"], key == "estop")   # the e-stop test needs two clicks; the other steps here have no consequences
                    if key == "estop":
                        ok, why = self.ob.skip(key, self.rd, self.pad, by="电脑 1.2.3.4")
                        self.assertFalse(ok)                                         # the page's two-step confirmation can't rely on the frontend alone
                        self.assertIn("要点两次确认：确定跳过？没测过", why)
                    ok, why = self.ob.skip(key, self.rd, self.pad, by="电脑 1.2.3.4", confirmed=key == "estop")
                    self.assertTrue(ok, why)
                    self.assertEqual(self.ob.rec["skipped"][key]["fp"], rec_fp[key])
                    self.assertEqual(self.ob.rec["skipped"][key]["by"], "电脑 1.2.3.4")
                    r = row(self.tick(), key)
                    self.assertEqual((r["state"], r["marked"]), ("skip", "skip"))
                    self.assertIn("跳过了（先不做）", r["text"])
                    self.assertEqual(r["go"], O.GO[key])                       # where "去做" (Go do it) / "重新做" (Redo) goes
                    ok, _ = self.ob.unskip(key, by="电脑 1.2.3.4")
                    self.assertTrue(ok)
                    self.assertNotIn(key, self.ob.rec["skipped"])
                    self.assertIn(row(self.tick(), key)["state"], ("todo", "no"))
        # Pair gamepad: can be skipped when not paired, no fingerprint bound
        self.pad.view = pad_view()
        self.assertEqual(row(self.tick(), "pad")["state"], "no")
        self.assertTrue(self.ob.skip("pad", self.rd, self.pad, by="手机")[0])
        self.assertIsNone(self.ob.rec["skipped"]["pad"]["fp"])
        self.assertEqual(row(self.tick(), "pad")["state"], "skip")
        msgs = [e["msg"] for e in self.log.recent(50)]
        self.assertIn("上手清单：IMU 方向 跳过（电脑 1.2.3.4）", msgs)
        self.assertIn("上手清单：IMU 方向 取消跳过（电脑 1.2.3.4）", msgs)
        self.assertTrue(any(e["cat"] == "校准" for e in self.log.recent(50) if "跳过" in e["msg"]))
        self.assertTrue(self.ob.save())                                       # atomic write, reads back the same
        self.assertEqual(O.Onboarding(self.tmp.name, self.log).rec["skipped"], self.ob.rec["skipped"])

    def test_every_row_offers_done_and_skip(self):
        """Three buttons: every unfinished row (● ○ ?) carries "已完成" (Done) / "跳过" (Skip) (mark); ✓ rows that Studio has its own record of don't (only redo)."""
        self.ob.rec["walked"] = {"at": 1.7e9, "fp": O.full_fp(BUS, CALIB)}
        v = self.tick()
        for r in v["rows"]:
            with self.subTest(step=r["key"]):
                if r["state"] == "ok":
                    self.assertIsNone(r["mark"])
                else:
                    self.assertEqual(set(r["mark"]), {"done", "skip", "ack"})
        ok, why = self.ob.skip("walk", self.rd, self.pad)
        self.assertFalse(ok)
        self.assertIn("已经完成", why)
        self.assertFalse(self.ob.skip("nope", self.rd)[0])
        self.assertFalse(self.ob.mark("imu", "bogus", self.rd)[0])

    def test_unknown_row_needs_two_clicks_and_binds_fingerprint_later(self):
        """Unreadable (?) rows used to be unskippable: now clickable with two clicks; if the fingerprint is unreadable it is recorded as null first and bound by tick once read (after that, changes still invalidate it)."""
        self.rd.calib_valid_after = self.rd.calib.at + 1                       # calibration not read since this hello
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "unk")
        self.assertTrue(r["mark"]["skip"]["confirm"])
        self.assertIn("确定跳过？这一步现在读不到", r["mark"]["skip"]["ask"])
        self.assertIn("确定标成已完成？这一步现在读不到", r["mark"]["done"]["ask"])
        ok, why = self.ob.skip("imu", self.rd, self.pad)
        self.assertFalse(ok)
        self.assertIn("要点两次确认", why)
        self.assertTrue(self.ob.skip("imu", self.rd, self.pad, by="电脑", confirmed=True)[0])
        rec = self.ob.rec["skipped"]["imu"]
        self.assertIsNone(rec["fp"])
        self.assertIn("unk", rec["ack"])
        self.assertEqual(row(self.tick(), "imu")["state"], "skip")
        # Read back: bind the current fingerprint and log a line
        self.rd.calib_valid_after = self.rd.calib.at - 0.001
        self.assertEqual(row(self.tick(), "imu")["state"], "skip")
        self.assertEqual(self.ob.rec["skipped"]["imu"]["fp"], O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"]))
        self.assertTrue(any("现在读到了、绑上" in e["msg"] for e in self.log.recent(30)))
        self.assertTrue(self.ob.save())
        self.assertEqual(O.Onboarding(self.tmp.name, self.log).rec["skipped"]["imu"]["ack"], ["unk", "fp"])   # ack can be saved and read back

    def test_imu_native_unverified_needs_two_clicks(self):
        """The main program explicitly says IMU orientation is unconfirmed (hard): previously the button was grayed out and the backend refused; now it's clickable, the second click shows the consequence, and the backend refuses without confirmed."""
        bus = copy.deepcopy(BUS)
        bus["native"]["imu_mount_verified"] = False
        self.rd.bus.set(bus)
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "no")
        self.assertTrue(r["mark"]["skip"]["confirm"])
        self.assertEqual(r["mark"]["skip"]["ask"], "确定跳过？主程序没确认 IMU 方向：跳过了鸭子也站不起来")
        self.assertEqual(r["mark"]["done"]["ask"], "确定标成已完成？主程序没确认 IMU 方向：标成已完成鸭子也站不起来")
        ok, why = self.ob.skip("imu", self.rd, self.pad, by="电脑")
        self.assertFalse(ok)
        self.assertIn("跳过了鸭子也站不起来", why)
        self.assertNotIn("imu", self.ob.rec.get("skipped") or {})
        # Previously skipped (without confirming this issue): doesn't count when the main program explicitly says it's unconfirmed
        self.ob.rec["skipped"] = {"imu": {"at": 1.7e9, "by": "x", "fp": O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"])}}
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "no")
        self.assertIn("跳过不管用", r["note"])
        # Confirmed with two clicks: counts (ack contains hard), and the real underlying situation goes into note
        self.ob.rec["skipped"] = {}
        self.assertTrue(self.ob.skip("imu", self.rd, self.pad, by="电脑", confirmed=True)[0])
        self.assertIn("hard", self.ob.rec["skipped"]["imu"]["ack"])
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "skip")
        self.assertIn("还没确认", r["note"])
        bus["native"]["imu_mount_verified"] = True                             # the main program confirmed it: stays skipped
        self.rd.bus.set(bus)
        self.assertEqual(row(self.tick(), "imu")["state"], "skip")

    def test_fingerprint_change_voids_skip_but_none_does_not(self):
        self.assertTrue(self.ob.skip("servo", self.rd, self.pad)[0])
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad, confirmed=True)[0])
        # Unreadable (fingerprint None): not invalidated
        self.rd.calib_valid_after = self.rd.calib.at + 1
        self.pad.view = pad_view(known=False)
        v = self.tick()
        self.assertEqual(row(v, "servo")["state"], "skip")
        self.assertEqual(row(v, "estop")["state"], "skip")
        # Read back and the calibration changed (direction changed, zero position still 2048) / a different gamepad: invalidated, back to ●, stating what changed
        self.rd.calib.set(calib_with(dirs={"left_knee": 1}))
        self.rd.calib_valid_after = self.rd.calib.at - 0.001
        other = dict(XPAD, mac="98:B6:E9:28:06:09", name="Pro Controller")
        self.pad.view = pad_view(pads=[other])
        v = self.tick()
        r = row(v, "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("跳过以后舵机零位改过了", r["text"])
        r = row(v, "estop")
        self.assertEqual(r["state"], "todo")
        self.assertIn("跳过以后手柄（或主程序版本）改过了", r["text"])
        self.assertTrue(r["mark"]["skip"]["confirm"])                         # can skip again (binding the new one), still with two clicks
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad, confirmed=True)[0])
        self.assertEqual(row(self.tick(), "estop")["state"], "skip")

    def test_fingerprint_unknown_can_still_be_marked(self):
        """Two gamepads paired for the e-stop test, neither connected, so it can't tell which one (fingerprint None): previously unskippable; now skippable with two clicks, and the fingerprint is bound once one connects."""
        two = [dict(XPAD, connected=False), dict(XPAD, mac="98:B6:E9:28:06:09", connected=False)]
        self.pad.view = pad_view(pads=two)
        r = row(self.tick(), "estop")
        self.assertIn("先连上一只手柄再测", r["text"])                     # review D11: state clearly what to do
        self.assertTrue(r["mark"]["skip"]["confirm"])
        self.assertIn("fp", r["mark"]["ack"])
        self.assertFalse(self.ob.skip("estop", self.rd, self.pad)[0])
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad, confirmed=True)[0])
        self.assertIsNone(self.ob.rec["skipped"]["estop"]["fp"])
        self.pad.view = pad_view(pads=[dict(XPAD, connected=True), two[1]])
        self.assertEqual(row(self.tick(), "estop")["state"], "skip")
        self.assertEqual(self.ob.rec["skipped"]["estop"]["fp"], O._hash([XBOX, BUILD]))

    def test_web_only_estop_can_be_skipped(self):
        """Web only (definitely no physical gamepad): the e-stop test row says "空格就是急停……可以跳过这步" (Space is the e-stop… you can skip this step) and can be skipped; once a gamepad is paired later, the skip is invalidated."""
        self.pad.view = pad_view()
        r = row(self.tick(), "estop")
        self.assertIn("空格就是急停", r["text"])
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad, confirmed=True)[0])
        self.assertEqual(row(self.tick(), "estop")["state"], "skip")
        self.pad.view = pad_view(pads=[XPAD])
        self.assertEqual(row(self.tick(), "estop")["state"], "todo")

    def test_skip_counts_as_done_and_next_moves(self):
        self.ob.rec["confirm_servo"] = {"at": 1.7e9, "fp": O.joints_fp(CALIB)}
        v = self.tick()
        self.assertEqual(v["next"], "imu")
        self.assertTrue(self.ob.skip("imu", self.rd, self.pad)[0])
        v = self.tick()
        self.assertEqual(v["next"], "estop")                                   # the pair-gamepad row is ✓ (XPAD connected): move on to the e-stop test
        self.assertEqual(v["skipped_n"], 1)
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad, confirmed=True)[0])
        self.ob.rec["walked"] = {"at": 1.7e9, "fp": O.full_fp(BUS, CALIB)}
        v = self.tick()
        self.assertTrue(v["all_done"])
        self.assertIsNone(v["next"])
        self.assertEqual(v["skipped_n"], 2)
        json.dumps(v)

    def test_bad_skipped_records_are_dropped(self):
        Path(self.tmp.name, "onboarding.json").write_text(json.dumps({"v": 1, "skipped": {
            "imu": {"at": 1.7e9, "by": "x", "fp": "abc"}, "servo": {"at": "昨天"}, "nope": {"at": 1}, "pad": [1]}}), encoding="utf-8")
        ob = O.Onboarding(self.tmp.name, self.log)
        self.assertEqual(list(ob.rec["skipped"]), ["imu"])
        self.assertEqual(sum(1 for e in self.log.recent(30) if "skipped." in e["msg"]), 3)
        Path(self.tmp.name, "onboarding.json").write_text(json.dumps({"v": 1, "skipped": "全跳"}), encoding="utf-8")
        self.assertNotIn("skipped", O.Onboarding(self.tmp.name, self.log).rec)
        ob.tick(self.rd, self.pad)                                             # can still evaluate
        self.assertEqual(len(ob.view()["rows"]), 6)

    def test_hard_block_servo_needs_two_clicks(self):
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = ["left_knee"]
        self.rd.calib.set(c)
        r = row(self.tick(), "servo")
        self.assertEqual(r["mark"]["skip"]["ask"], "确定跳过？主程序说标定没做完：跳过了鸭子也站不起来")
        self.assertFalse(self.ob.skip("servo", self.rd, self.pad)[0])
        self.assertTrue(self.ob.skip("servo", self.rd, self.pad, confirmed=True)[0])
        r = row(self.tick(), "servo")
        self.assertEqual(r["state"], "skip")
        self.assertIn("1 颗还没标", r["note"])


class DoneTest(unittest.TestCase):
    """"已完成" (Done) = I did it before (user Oct 20: "someone may have done it before and would have to go through it again"): done.<step>, ✓ "你标了已完成" (you marked it done), fingerprint rules same as skip."""
    setUp, tearDown, tick = SkipTest.setUp, SkipTest.tearDown, SkipTest.tick

    def test_done_marks_ok_and_cancel(self):
        before = row(self.tick(), "servo")
        self.assertEqual(before["state"], "todo")
        ok, why = self.ob.mark_done("servo", self.rd, self.pad, by="电脑 1.2.3.4")
        self.assertTrue(ok, why)
        self.assertEqual(self.ob.rec["done"]["servo"]["fp"], O.joints_fp(CALIB))
        r = row(self.tick(), "servo")
        self.assertEqual((r["state"], r["marked"], r["text"]), ("ok", "done", "你标了已完成"))
        self.assertEqual(r["note"], before["text"])                          # the real underlying situation; the page's small text says "现在：…" (Now: …)
        self.assertIsNotNone(r["when"])
        self.assertEqual(self.ob.view()["marked_n"], 1)
        self.assertTrue(self.ob.mark_done("servo", self.rd, self.pad)[0])     # click again: already marked
        ok, why = self.ob.skip("servo", self.rd, self.pad)
        self.assertFalse(ok)                                                  # the two are mutually exclusive: cancel first
        self.assertIn("先点「取消」", why)
        self.assertTrue(self.ob.unmark("servo", "done", by="电脑 1.2.3.4")[0])
        self.assertNotIn("servo", self.ob.rec["done"])
        self.assertEqual(row(self.tick(), "servo")["state"], "todo")
        msgs = [e["msg"] for e in self.log.recent(30)]
        self.assertIn("上手清单：舵机零位 标了已完成（电脑 1.2.3.4）", msgs)
        self.assertIn("上手清单：舵机零位 取消已完成（电脑 1.2.3.4）", msgs)

    def test_done_wins_over_skip_and_marking_removes_the_other(self):
        fp = O.joints_fp(CALIB)
        self.ob.rec.update({"skipped": {"servo": {"at": 1.0, "by": "x", "fp": fp}}, "done": {"servo": {"at": 2.0, "by": "x", "fp": fp}}})
        self.assertEqual(row(self.tick(), "servo")["marked"], "done")
        self.ob.rec["done"] = {}
        self.assertTrue(self.ob.unskip("servo")[0])
        self.ob.rec["skipped"] = {"servo": {"at": 1.0, "by": "x", "fp": "old"}}    # an invalidated skip (fingerprint changed) is still in the record
        self.assertEqual(row(self.tick(), "servo")["state"], "todo")
        self.assertTrue(self.ob.mark_done("servo", self.rd, self.pad)[0])
        self.assertNotIn("servo", self.ob.rec["skipped"])                       # marked done: the old skip record is deleted

    def test_done_voided_by_fingerprint_change(self):
        self.assertTrue(self.ob.mark_done("servo", self.rd, self.pad)[0])
        self.rd.calib.set(calib_with(dirs={"left_knee": 1}))
        r = row(self.tick(), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("标了已完成以后舵机零位改过了", r["text"])
        self.assertIn("servo", self.ob.rec["done"])                             # the record stays (counts again if the fingerprint changes back)

    def test_found_problem_with_and_without_ack(self):
        """IMU checked while standing found 8.5° off (found): a "已完成" (Done) confirmed with two clicks stays; ones not confirmed before are invalidated and deleted from the record."""
        src, mount = "lsm6dsv16x", CALIB["imu_mount"]
        mfp = O.mount_fp(src, mount["quat"])
        self.ob.rec["imu_check"] = {"at": 1.7e9, "source": src, "mount_fp": mfp, "diff_deg": 8.5, "tilt_deg": 1.0, "ok": False}
        r = row(self.tick(), "imu")
        self.assertEqual(r["mark"]["done"]["ask"],
                         "确定标成已完成？站着核过，方向差 8.5°：标成已完成走路也会往前冲（一号鸭 10-12 就是装歪 8.5°）")
        ok, why = self.ob.mark_done("imu", self.rd, self.pad)
        self.assertFalse(ok)
        self.assertIn("差 8.5°", why)
        self.assertTrue(self.ob.mark_done("imu", self.rd, self.pad, confirmed=True)[0])
        self.assertIn("found", self.ob.rec["done"]["imu"]["ack"])
        for _ in range(2):
            self.assertEqual(row(self.tick(), "imu")["state"], "ok")
        self.assertIn("imu", self.ob.rec["done"])
        self.ob.rec["done"] = {"imu": {"at": 1.7e9, "by": "x", "fp": mfp}}          # marked before the problem was found
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "todo")
        self.assertIn("标的不算了", r["note"])
        self.assertEqual(self.ob.rec["done"], {})
        self.assertTrue(any("「已完成」作废" in e["msg"] for e in self.log.recent(30)))

    def test_frozen_during_servo_session_needs_two_clicks(self):
        """The checklist is frozen while tuning servos (review D11): previously skip and cancel were both refused; now both are clickable with two clicks (marks only show after hand-back)."""
        self.assertTrue(self.ob.skip("imu", self.rd, self.pad)[0])
        self.tick()

        class Sess:
            state = "open"
        self.ob.tick(self.rd, self.pad, Sess())
        v = self.ob.view()
        self.assertTrue(v["frozen"])
        self.assertIn("要等交还主程序以后才显示", v["frozen_ask"]["skip"])
        self.assertIn("确定取消？", v["frozen_ask"]["undo"])
        ok, why = self.ob.skip("walk", self.rd, self.pad, Sess())
        self.assertFalse(ok)
        self.assertIn("确定跳过？在调舵机", why)
        self.assertTrue(self.ob.skip("walk", self.rd, self.pad, Sess(), confirmed=True)[0])
        ok, why = self.ob.unskip("imu", servo=Sess())
        self.assertFalse(ok)
        self.assertIn("交还主程序以后", why)
        self.assertIn("imu", self.ob.rec["skipped"])
        self.assertFalse(self.ob.unskip("imu")[0])        # no session passed: look at the most recently seen one (still open) -- still needs confirmation (review R6)
        self.assertTrue(self.ob.unskip("imu", confirmed=True)[0])
        self.ob.tick(self.rd, self.pad, Sess())
        self.assertEqual([r["state"] for r in self.ob.view()["rows"]], [r["state"] for r in v["rows"]])   # frozen: display unchanged
        Sess.state = "closed"                             # handed back: evaluate with the new state right away
        self.assertEqual(row(self.tick(), "walk")["state"], "skip")
        self.assertEqual(row(self.tick(), "imu")["state"], "todo")

    def test_records_validation(self):
        good, bad = O.clean_records({"done": {
            "servo": {"at": 1.7e9, "by": "x", "fp": None, "ack": ["hard", "unk"]}, "imu": {"at": 1.7e9, "fp": "x", "ack": [1]},
            "walk": {"at": None, "fp": "x"}, "pad": {"at": 1.7e9, "fp": None}}})
        self.assertEqual(sorted(good["done"]), ["pad", "servo"])
        self.assertEqual(sorted(k for k, _ in bad), ["done.imu", "done.walk"])


class Batch3SkipTest(unittest.TestCase):
    """Third-round code review D5, D10, D11 (R1–R7 of the repro script repro_onboard.py), revised per the Oct 20 new rules (no longer locked, two clicks)."""
    setUp, tearDown, tick = SkipTest.setUp, SkipTest.tearDown, SkipTest.tick

    def test_found_problems_need_two_clicks_and_old_skips_are_voided(self):
        """D5: IMU checked 8.5° off, e-stop tested but not working now, two zero-position schemes conflicting -- the second click shows the consequence; previous skips (without confirming this issue) are invalidated and deleted."""
        src, mount = "lsm6dsv16x", CALIB["imu_mount"]
        mfp = O.mount_fp(src, mount["quat"])
        efp = O._hash([XBOX, BUILD])
        self.ob.rec.update({
            "imu_check": {"at": 1.7e9, "source": src, "mount_fp": mfp, "diff_deg": 8.5, "tilt_deg": 1.0, "ok": False},
            "estop": {"at": 1.7e9, "ms": 180, "mac": XBOX, "name": "Xbox", "build": BUILD},
            "skipped": {"imu": {"at": 1.7e9, "by": "x", "fp": mfp}, "estop": {"at": 1.7e9, "by": "x", "fp": efp},
                        "servo": {"at": 1.7e9, "by": "x", "fp": O.joints_fp(calib_with(left_knee=1990))}}})
        self.rd.calib.set(calib_with(left_knee=1990))
        self.rd.calib_valid_after = self.rd.calib.at - 0.001
        self.pad.view = pad_view(pads=[XPAD], estop="bad", checks=[{"label": "padd 在跑", "ok": False, "why": "padd 没在跑"}])
        v = self.tick()
        for key, word in (("imu", "差 8.5°"), ("estop", "急停不管用"), ("servo", "两套零位")):
            with self.subTest(step=key):
                r = row(v, key)
                self.assertEqual(r["state"], "todo", r)                         # the detected problem takes precedence; no longer "跳过了" (skipped)
                self.assertTrue(r["mark"]["skip"]["confirm"])
                self.assertIn(word, r["mark"]["skip"]["ask"])
                self.assertNotIn("{v}", r["mark"]["skip"]["ask"])
                self.assertIn("跳过不算了", r["note"])
                self.assertTrue(r["found"])
                ok, why = self.ob.skip(key, self.rd, self.pad)
                self.assertFalse(ok)
                self.assertIn(word, why)
        self.assertEqual(self.ob.rec["skipped"], {})                           # invalidated ones are deleted from the record
        self.assertTrue(any("跳过作废" in e["msg"] for e in self.log.recent(50)))
        self.assertTrue(self.ob.skip("servo", self.rd, self.pad, confirmed=True)[0])   # two clicks: if they still want to skip knowing the consequence, skip
        self.assertEqual(row(self.tick(), "servo")["state"], "skip")
        self.assertIn("servo", self.ob.rec["skipped"])                         # a confirmed issue no longer invalidates it

    def test_skip_records_need_number_at(self):
        """D10: at not a number → dropped and a warn logged. fp may be null (unreadable when marked, bound by tick once read: per C2); anything that's neither a string nor null is dropped."""
        good, bad = O.clean_records({"skipped": {
            "imu": {}, "servo": {"x": 1}, "walk": {"at": None, "fp": "abc"}, "estop": {"at": 1.7e9, "fp": None},
            "pad": {"at": 1.7e9, "by": "x", "fp": None}, "servo2": {"at": 1.7e9, "fp": "a"}, "commit": {"at": 1.7e9, "fp": 3}}})
        self.assertEqual(sorted(good["skipped"]), ["estop", "pad"])
        self.assertEqual(sorted(k for k, _ in bad), ["skipped.commit", "skipped.imu", "skipped.servo", "skipped.servo2", "skipped.walk"])
        p = Path(self.tmp.name) / O.ONBOARD_FILE
        p.write_text(json.dumps({"skipped": {"servo": {"at": 1.7e9, "by": "x", "fp": None}}}), encoding="utf-8")
        ob = O.Onboarding(self.tmp.name, self.log)
        self.assertEqual(ob.rec["skipped"]["servo"]["fp"], None)
        ob.tick(self.rd, self.pad)                                             # fingerprint readable: bind it
        self.assertEqual(ob.rec["skipped"]["servo"]["fp"], O.joints_fp(CALIB))

    def test_estop_ask_text_by_situation(self):
        """D11: the e-stop test confirmation text depends on the situation: never tested / gamepad changed / main program upgraded / e-stop not working now / web only; "已完成" (Done) also needs two clicks."""
        self.pad.view = pad_view(pads=[XPAD])
        m = row(self.tick(), "estop")["mark"]
        self.assertIn("确定跳过？没测过", m["skip"]["ask"])
        self.assertIn("确定标成已完成？没测过", m["done"]["ask"])
        self.pad.view = pad_view(pads=[XPAD], estop="bad", checks=[{"label": "padd 在跑", "ok": False, "why": "padd 没在跑"}])
        r = row(self.tick(), "estop")
        self.assertIn("急停现在不管用（padd 在跑：padd 没在跑）：跳过了也不会变好用", r["mark"]["skip"]["ask"])
        self.assertNotIn("found", r["mark"]["ack"])                            # never tested: not a detected problem
        self.pad.view = pad_view()
        self.assertIn("只用网页", row(self.tick(), "estop")["mark"]["skip"]["ask"])
        self.ob.rec["estop"] = {"at": 1.7e9, "ms": 180, "mac": "98:B6:E9:28:06:09", "name": "Pro", "build": BUILD}
        self.pad.view = pad_view(pads=[XPAD])
        r = row(self.tick(), "estop")
        self.assertIn("换了手柄", r["mark"]["skip"]["ask"])
        self.ob.rec["estop"] = {"at": 1.7e9, "ms": 180, "mac": XBOX, "name": "Xbox", "build": "old-build"}
        self.assertIn("主程序升级过", row(self.tick(), "estop")["mark"]["skip"]["ask"])


class StartingTooLongTest(unittest.TestCase):
    """Task 16: the main program has reported a startup phase for more than 30 seconds in a row (Studio counts from this connection): the overview hero, to-dos and checklist header no longer say "通常 10 秒" (usually 10 seconds)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_summarize_todo_and_header(self):
        boot = {"build": BUILD, "mode": "commissioning", "phase": "configuring_bus", "port": "/dev/ttyS2"}
        rd = FakeRd(bus=boot)
        now = time.monotonic()
        rd.starting_since = now - 5
        s = summarize(rd, {}, now=now)
        self.assertEqual((s["posture"], s["starting_s"], s["starting_long"]), ("starting", 5, False))
        self.assertEqual(next(t for t in s["todo"] if t["key"] == "starting")["hint"], "通常 10 秒内完成")
        rd.starting_since = now - 31
        s = summarize(rd, {}, now=now)
        self.assertTrue(s["starting_long"])
        self.assertEqual(s["starting_s"], 31)
        t = next(t for t in s["todo"] if t["key"] == "starting")
        self.assertEqual(t["msg"], "主程序一直报「启动中」")
        self.assertIn("已经 31 秒了", t["hint"])
        self.assertIn("旧版主程序的毛病", t["hint"])
        self.assertNotIn("10 秒", t["hint"])
        ob = O.Onboarding(self.tmp.name, self.log)
        ob.tick(rd)
        self.assertIn("一直报「启动中」", ob.view()["header"]["text"])
        rd.bus.set(dict(boot, phase="ready"))                                 # it's up (live snapshot): no longer counts as starting
        s = summarize(rd, {}, now=now)
        self.assertEqual((s["posture"], s["starting_s"], s["starting_long"]), ("commissioning", None, False))


class BatteryWordingTest(unittest.TestCase):
    """Low battery to-do: whether it sits down and shuts off by itself when the battery is empty follows robotd's config [safety] battery_empty_shutdown (false on duck #2's real hardware)."""

    def test_read_setting_and_wording(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            d = Path(tmp.name)
            fork, official = d / "fork.toml", d / "official.toml"
            self.assertIsNone(O.read_battery_shutdown([str(fork), str(official)]))          # neither present: unreadable
            official.write_text("[safety]\nbattery_empty_shutdown = true\n", encoding="utf-8")
            self.assertIs(O.read_battery_shutdown([str(fork), str(official)]), True)
            fork.write_text("[safety]\nlimp_fall = false\nbattery_empty_shutdown = false\n", encoding="utf-8")
            self.assertIs(O.read_battery_shutdown([str(fork), str(official)]), False)        # the fork's comes first
            fork.write_text("[safety]\nlimp_fall = false\n", encoding="utf-8")
            self.assertIsNone(O.read_battery_shutdown([str(fork)]))                         # this item not set: treated as unreadable
            fork.write_text("坏[", encoding="utf-8")
            self.assertIsNone(O.read_battery_shutdown([str(fork)]))
        finally:
            tmp.cleanup()
        low = {"pct": 9}

        def hint(v):
            return next(i for i in todo(HEALTH, BUS, {"stale": []}, "ok", {}, {}, low, "holding", battery_shutdown=v)
                        if i["key"] == "battery")["hint"]
        self.assertEqual(hint(True), "该充电了；到 6.6 V 它会自己坐下关机")
        self.assertEqual(hint(False), "该充电了；没电时它不会自己坐下，先停下、坐下再充")
        self.assertEqual(hint(None), "该充电了；没电时它不会自己坐下，先停下、坐下再充")


# ---------------- Step 3 "写进主程序" (commit to main program) (task 11) ----------------

def factory_calib():
    c = copy.deepcopy(CALIB)
    cal = c["calibration"]
    cal["motion_enabled"] = False
    cal["imu_mount_verified"] = False
    for j in cal["joints"]:
        j["calibrated"] = False
        j.pop("min_rad", None)
        j.pop("max_rad", None)
    return c


def commit_view(ready=False):
    return {"ready": ready, "items": [
        {"key": "servo", "label": "舵机零位", "ok": False, "text": "还有 15 颗没在 Studio 校过零位",
         "action": {"do": "servos", "label": "去舵机页"}},
        {"key": "directions", "label": "方向", "ok": True, "text": "15 颗都用默认方向（−1）"},
        {"key": "imu", "label": "IMU 方向", "ok": True, "text": "IMU 页站着校过了"},
        {"key": "bus", "label": "舵机总线", "ok": True, "text": "舵机页没开着总线"},
        {"key": "robotd", "label": "主程序", "ok": True, "text": "主程序在线"},
    ], "job": None}


class CommitStepTest(unittest.TestCase):
    def test_order_title_and_number(self):
        v = O.evaluate(inp(), {})
        self.assertEqual([r["key"] for r in v["rows"]], ["servo", "imu", "commit", "pad", "estop", "walk"])
        r = row(v, "commit")
        self.assertEqual(r["n"], 3)
        self.assertEqual(r["title"], "写进主程序")
        self.assertEqual(r["desc"], O.COMMIT_TEXT)

    def test_committed_calibration_is_done(self):
        r = row(O.evaluate(inp(), {}), "commit")
        self.assertEqual(r["state"], "ok")
        self.assertIn("写进主程序了", r["text"])

    def test_factory_shows_readiness_and_action(self):
        cv = commit_view()
        r = row(O.evaluate(inp(calib=factory_calib(), commit=cv), {}), "commit")
        self.assertEqual(r["state"], "todo")
        self.assertIn("还差舵机零位", r["text"])
        self.assertEqual(r["commit"], cv)
        self.assertEqual(r["actions"][0]["do"], "commit")

    def test_unreadable_is_unknown(self):
        r = row(O.evaluate(inp(calib=None), {}), "commit")
        self.assertEqual(r["state"], "unk")

    def test_calib_read_fallback_is_not_unknown(self):
        """Motion mode stuck at waiting_for_bus: no calibration-status, but calib-read read the file."""
        cv = commit_view()
        cv.update({"preview_ok": True, "from_file": True,
                   "note": "主程序现在没在用这份标定，下面是文件里的内容"})
        bus = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus",
               "error": "torque readback at register 40: Feetech Sync Read timeout; missing IDs [21]"}
        r = row(O.evaluate(inp(bus=bus, calib=None, commit=cv), {}), "commit")
        self.assertEqual(r["state"], "todo")
        self.assertIn("主程序现在没在用这份标定", r["desc"])

    def test_skip_is_bound_to_calibration_fingerprint(self):
        bound, fp = O.step_fp("commit", inp())
        self.assertTrue(bound)
        self.assertEqual(fp, O.full_fp(BUS, CALIB))

    def test_marked_steps_and_commit_readiness(self):
        """Task 16: step 1 marked done (at the factory the main program says uncalibrated: two clicks needed) → step 3 readiness "舵机零位" (servo zero position) counts as satisfied;
        task 17: step 2 marked done, orientation unconfirmed in the main program, and no new calibration → "IMU 方向" (IMU orientation) is written per the default mounting, and step 3 is ready."""
        from studio.commit import CommitService
        tmp = tempfile.TemporaryDirectory()
        try:
            log = Log(Path(tmp.name) / "logs", echo=False, background=False)
            fc = factory_calib()
            fc["uncalibrated_joints"] = [j["name"] for j in fc["calibration"]["joints"]]
            fc["calibration"]["imu_mounts"]["lsm6dsv16x"]["verified"] = False
            fc["imu_mount"]["verified"] = False
            bus = {"build": BUILD, "mode": "commissioning", "phase": "ready", "port": "/dev/ttyS2", "calibrated": False,
                   "imu_mount_verified": False, "last_sample": {"servos": [{"id": i} for i in O.SERVO_IDS], "imu": {}}}
            rd = FakeRd(bus=bus, calib=fc)
            ob = O.Onboarding(tmp.name, log)
            svc = CommitService(rd, log, tmp.name)
            ob.commit_service, svc.onboard = svc, ob
            ob.tick(rd)

            def item(key):
                return next(i for i in svc.view(rd)["items"] if i["key"] == key)
            self.assertFalse(item("servo")["ok"])
            r = row(ob.view(), "servo")
            self.assertEqual(r["state"], "no")
            self.assertTrue(r["mark"]["done"]["confirm"])                         # main program says uncalibrated (hard): two clicks needed
            self.assertFalse(ob.mark_done("servo", rd)[0])
            self.assertTrue(ob.mark_done("servo", rd, confirmed=True)[0])
            ob.tick(rd)
            self.assertEqual(row(ob.view(), "servo")["state"], "ok")
            s = item("servo")
            self.assertTrue(s["ok"])
            self.assertEqual(s["text"], "你标了第 1 步已完成：15 颗按 2048 写零位（零位要是用 Studio 的舵机页校过的才对）")
            self.assertIsNone(s["action"])
            self.assertFalse(item("imu")["ok"])
            ob.tick(rd)
            self.assertIn("IMU 方向", row(ob.view(), "commit")["text"])           # step 2 not marked: step 3 still lacks IMU orientation
            self.assertFalse(ob.mark_done("imu", rd)[0])                          # main program says orientation unconfirmed (hard): two clicks needed
            self.assertTrue(ob.mark_done("imu", rd, confirmed=True)[0])
            ob.tick(rd)
            m = item("imu")
            self.assertTrue(m["ok"], m)
            self.assertIn("你标了第 2 步已完成：IMU 按默认装法写（LSM6DSV16X（I²C）：复刻推荐装法", m["text"])
            self.assertEqual(svc.view(rd)["imu_default"]["quat"], [0.7071067811865476, 0.0, 0.7071067811865476, 0.0])
            ob.tick(rd)
            text = row(ob.view(), "commit")["text"]
            self.assertNotIn("IMU 方向", text)
            self.assertNotIn("舵机零位", text)
            self.assertIn("准备齐了", text)                                        # can commit to the main program even with steps 1 and 2 skipped
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
