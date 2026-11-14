"""Gamepad page backend (studio/pad.py, pad_drive.py, pad_combo.py): everything uses fake configd / Bluetooth / padd tap / robotd, so it runs on a computer without Bluetooth.
Real ports (rpc_call, PaddTap, RobotPort, BtSession pipe reading) are tested with local TCP fake services / real subprocesses.

How to run (from the studio directory):
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_pad'])"
"""
import copy
import itertools
import json
import math
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio import pad as P  # noqa: E402
from studio import pad_combo as C  # noqa: E402
from studio import pad_drive as D  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.rpc import RpcError, Timeout, Unreachable  # noqa: E402

PRO = "98:B6:E9:28:06:09"        # the classic face of the Switch clone (the example in configd/src/pad.rs:169)
PRO_LE = "98:B6:ED:28:06:09"     # the LE face of the same gamepad
XBOX = "78:86:2E:BB:13:28"
FAST = {"poll": 0.01, "status_watch": 0.05, "status_job": 0.02, "padd": 0.6, "connect": 0.3, "readback": 0.3,
        "torque": 0.5, "press": 0.5, "lease": 5.0, "scan_tick": 0.02, "pair_window": 1, "scan_min": 0.1,
        "probe": 0.02, "shutdown_hold": 0.4, "select_long": 0.2, "relax_guard": 0.3,
        "walk_verify": 0.2, "walk_verify_poll": 0.02}
# robot.policies recorded on real hardware (tests/fixtures/now-20261018.jsonl:5), paths shortened
POLICIES = {"enabled": True, "homed": True, "mode": "walk", "sitting": False,
            "skills": ["roulade", "kick_left", "kick_right", "roller_stand"],
            "slots": [{"slot": "walk", "path": "/w.onnx"}, {"slot": "stand", "path": None},
                      {"slot": "sitstand", "path": "/s.onnx"}, {"slot": "ground_pick", "path": "/g.onnx"}]}


def wait_until(cond, timeout=3.0, what="条件"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError(f"{timeout} 秒没等到：{what}")


def bus(torque_on=True, **kw):
    b = {"mode": "motion", "phase": "control", "torque_off_pending": False,
         "native": {"torque_state_confirmed": bool(torque_on),
                    "hd1910": {"restore_pending": False, "temporary_gains_applied": False}}}
    b.update(kw)
    return b


# ---------------- Fakes ----------------

class FakeConfigd:
    def __init__(self):
        self.status = {"driver": "active", "pads": []}
        self.status_exc = None
        self.pair_result = None
        self.pair_exc = None
        self.pair_delay = 0.0
        self.on_pair = None
        self.forget_exc = None
        self.calls = []
        self.lk = threading.Lock()

    def call(self, method, params=None, timeout=3.0):
        with self.lk:
            self.calls.append((method, copy.deepcopy(params)))
        if method == "pad.status":
            if self.status_exc:
                raise self.status_exc
            with self.lk:
                return copy.deepcopy(self.status)
        if method == "pad.pair":
            time.sleep(self.pair_delay)
            if self.pair_exc:
                raise self.pair_exc
            if self.on_pair:
                self.on_pair(params)
            return copy.deepcopy(self.pair_result)
        if method == "pad.forget":
            if self.forget_exc:
                raise self.forget_exc
            return {"removed": True}
        raise RpcError(method, -32601, "method not found")

    def connect_pad(self, mac, name, connected=True, trusted=True):
        with self.lk:
            self.status["pads"] = [{"mac": mac, "name": name, "paired": True, "trusted": trusted, "connected": connected}]


class FakeBt:
    def __init__(self):
        self.state = {"present": True, "powered": True, "pairable": True, "blocked": False}
        self.found = []
        self.infos = {}
        self.calls = []
        self.scan_exc = None
        self.pair_exc = None
        self.pair_excs = []          # raised in order (used to act out retrying with a new session after agent registration fails)
        self.on_pair = None
        self.removed = None
        self.pairable_ok = False
        self.on_reconnect = None
        self.reconnect_errors = []

    def adapter(self):
        return dict(self.state)

    def power_on(self):
        self.calls.append("power_on")
        self.state["powered"] = True

    def pairable_on(self):
        self.calls.append("pairable_on")
        if not self.pairable_ok:
            raise P.BtError("bt_permission", "org.freedesktop.DBus.Error.AccessDenied")
        self.state["pairable"] = True

    def pairable_off(self):
        self.calls.append("pairable_off")
        self.state["pairable"] = False

    def scan_start(self):
        self.calls.append("scan_start")
        if self.scan_exc:
            raise self.scan_exc

    def devices(self):
        return [dict(d, seen_at=time.monotonic()) for d in self.found]

    def scan_stop(self):
        self.calls.append("scan_stop")

    def info(self, mac):
        return dict(self.infos.get(mac, {}))

    def reconnect(self, mac, timeout=5.0):
        self.calls.append(("reconnect", mac, timeout))
        if self.reconnect_errors:
            raise self.reconnect_errors.pop(0)
        if self.on_reconnect:
            self.on_reconnect(mac)

    def pair_device(self, mac, classic, cancel, step):
        self.calls.append(("pair_device", mac, classic))
        for key in ("pair", "trust", "connect"):
            step(key, "doing")
            if key == "pair" and self.pair_excs:
                raise self.pair_excs.pop(0)
            if self.pair_exc and key == "pair":
                raise self.pair_exc
            step(key, "ok")
        if self.on_pair:
            self.on_pair(mac)

    def remove(self, mac):
        self.calls.append(("remove", mac))
        if isinstance(self.removed, Exception):
            raise self.removed
        return True

    def close(self):
        self.calls.append("close")


XBOX_DEV = {"name": "Xbox Wireless Controller", "node": "/dev/input/event5", "unique": "78:86:2e:bb:13:28", "bus": 5,
            "vendor": 1118, "product": 2835,
            "axes": [{"code": c, "name": n, "min": lo, "max": hi, "flat": 0, "fuzz": 0, "value": v} for c, n, lo, hi, v in (
                (0, "ABS_X", -32768, 32767, 0), (1, "ABS_Y", -32768, 32767, 0), (2, "ABS_Z", -32768, 32767, 0),
                (5, "ABS_RZ", -32768, 32767, 0), (10, "ABS_BRAKE", 0, 1023, 0), (9, "ABS_GAS", 0, 1023, 0),
                (16, "ABS_HAT0X", -1, 1, 0), (17, "ABS_HAT0Y", -1, 1, 0))],
            "buttons": [{"code": c, "name": n, "pressed": False} for c, n in (
                (0x130, "BTN_SOUTH"), (0x131, "BTN_EAST"), (0x133, "BTN_NORTH"), (0x134, "BTN_WEST"),
                (0x136, "BTN_TL"), (0x137, "BTN_TR"), (0x13A, "BTN_SELECT"), (0x13B, "BTN_START"))]}
PRO_DEV = {"name": "Pro Controller", "node": "/dev/input/event6", "unique": PRO.lower(), "bus": 5, "vendor": 0x057E,
           "product": 0x2009,
           "axes": [{"code": c, "name": n, "min": -32767, "max": 32767, "flat": 0, "fuzz": 0, "value": 0} for c, n in (
               (0, "ABS_X"), (1, "ABS_Y"), (3, "ABS_RX"), (4, "ABS_RY"))]
           + [{"code": 16, "name": "ABS_HAT0X", "min": -1, "max": 1, "flat": 0, "fuzz": 0, "value": 0},
              {"code": 17, "name": "ABS_HAT0Y", "min": -1, "max": 1, "flat": 0, "fuzz": 0, "value": 0}],
           "buttons": [{"code": c, "name": "x", "pressed": False} for c in (0x130, 0x131, 0x133, 0x134, 0x13A, 0x13B)]}


class FakeHelper:
    """Fake root helper. With available=False all existing tests still go through configd / bluetoothctl."""

    def __init__(self):
        self.is_available = False
        self.pair_result = (True, "paired", {})
        self.pair_exc = None
        self.pair_delay = 0.0
        self.on_pair = None
        self.forget_result = (True, "forgotten", {"removed": True})
        self.forget_exc = None
        self.pair_calls = []
        self.forget_calls = []

    def available(self):
        return self.is_available

    def pad_pair(self, by, mac=None, timeout=60):
        self.pair_calls.append((by, mac, timeout))
        time.sleep(self.pair_delay)
        if self.pair_exc:
            raise self.pair_exc
        if self.on_pair:
            self.on_pair(mac)
        return copy.deepcopy(self.pair_result)

    def pad_forget(self, by, mac, timeout=60):
        self.forget_calls.append((by, mac, timeout))
        if self.forget_exc:
            raise self.forget_exc
        return copy.deepcopy(self.forget_result)


class FakeTap:
    def __init__(self):
        self.on_report = self.on_state = None
        self.running = False
        self.starts = 0

    def start(self, on_report, on_state):
        self.on_report, self.on_state = on_report, on_state
        self.running = True
        self.starts += 1
        on_state("waiting", None)

    def stop(self):
        self.running = False

    def alive(self):
        return self.running

    def attach(self, dev):
        self.on_report({"report": "attached", "device": copy.deepcopy(dev)})

    def key(self, code, down):
        self.on_report({"report": "frame", "seq": 1, "at_us": 0,
                        "events": [{"kind": 1, "code": code, "value": 1 if down else 0, "name": "BTN"},
                                   {"kind": 0, "code": 0, "value": 0, "name": "SYN_REPORT"}]})

    def axis(self, code, value):
        self.on_report({"report": "frame", "seq": 2, "at_us": 0,
                        "events": [{"kind": 3, "code": code, "value": value, "name": "ABS"}]})


class FakeRobot:
    """Fake robotd: notify is recorded into sent; call into calls. busStatus returns self.bus (that's what the e-stop test itself asks)."""

    def __init__(self):
        self.sent = []
        self.calls = []
        self.fail = None
        self.bus = bus()
        self.replies = {}
        self.lk = threading.Lock()

    def notify(self, method, params):
        if self.fail:
            raise self.fail
        with self.lk:
            self.sent.append((method, dict(params)))

    def call(self, method, params=None, timeout=3.0):
        with self.lk:
            self.calls.append((method, copy.deepcopy(params)))
        if method == "pad.bindings" and method not in self.replies:
            return {"bindings": [{"button": "a", "skill": "ground_pick", "overridden": False}]}
        if method == "robot.busStatus":
            return copy.deepcopy(self.bus)
        r = self.replies.get(method)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(params)
        if r is not None:
            return copy.deepcopy(r)
        if method == "robot.enable":
            # really enable/disable the policy: Studio's "start walking" (「开始走」) reads back busStatus for policy_enabled, so the fake has to follow too
            on = bool((params or {}).get("on"))
            with self.lk:
                self.bus["policy_enabled"] = on
            return {"accepted": True}
        if method in ("robot.init", "robot.do", "robot.sound", "robot.stop"):
            return {"accepted": True}
        raise RpcError(method, -32601, "nope")

    def methods(self):
        with self.lk:
            return [m for m, _ in self.calls if m != "robot.busStatus"]


class PadTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.cfg, self.bt, self.tap, self.robot = FakeConfigd(), FakeBt(), FakeTap(), FakeRobot()
        self.helper = FakeHelper()
        self.toml = "[netpad]\nenabled = false\n"
        self.weird = False
        self.presses = 0
        self.ops = P.PadOps(self.log, configd=self.cfg, bt=self.bt, tap=self.tap, robot=self.robot, helper=self.helper,
                            waits=FAST, read_text=lambda p: self.toml, exists=lambda p: self.weird,
                            state_dir=str(Path(self.tmp.name) / "state"))
        self.robot_ok()
        # the first time Studio sees the main program running: a background thread sends robot.pose {"active": false} once (round-3 V1). Wait for it to be sent before clearing, so other tests start clean
        wait_until(lambda: self.ops._pose_reset == "done", what="连上主程序时的 pose 复位")
        with self.robot.lk:
            self.robot.sent.clear()

    def tearDown(self):
        self.ops.close()
        self.tmp.cleanup()

    def robot_ok(self, torque_on=True, **kw):
        """Feed a robotd readback (in the app's robot_view format), and make the fake robotd's busStatus return the same."""
        view = {"present": True, "bus": bus(torque_on), "bus_at": time.monotonic(), "estop_active": False, "paused": None,
                "estop_presses": self.presses}
        view.update(kw)
        if isinstance(view.get("bus"), dict):
            self.robot.bus = copy.deepcopy(view["bus"])
        self.ops.feed_robot(view)

    def relax_pressed(self):
        """The "release torque" (「卸力」) button at the top was pressed once (estop.press_count +1 in robotd.py)."""
        self.presses += 1
        self.robot_ok(torque_on=False)

    def wiz(self):
        return self.ops.snapshot()["wizard"]

    def steps(self):
        return {s["key"]: s["state"] for s in self.wiz()["steps"]}

    def wait_wiz(self, state, timeout=4.0):
        wait_until(lambda: self.wiz()["state"] == state, timeout, f"向导变成 {state}（现在 {self.wiz()['state']} · {self.wiz().get('error')}）")
        return self.wiz()

    def watch(self):
        self.ops.handle({"op": "watch"})
        wait_until(lambda: self.tap.running, what="旁路打开")


# ---------------- Scan ----------------

class ScanTest(PadTestBase):
    def test_scan_lists_pads_first_and_merges_two_faces(self):
        self.bt.found = [
            {"mac": "AA:BB:CC:00:11:22", "name": "Galaxy Buds", "icon": "audio-headset", "rssi": -70},
            {"mac": PRO_LE, "name": "BLE Controller_280609", "rssi": -55},
            {"mac": PRO, "name": "Pro Controller", "cls": 0x2508, "rssi": -50},
        ]
        self.ops.handle({"op": "scan", "seconds": 0.2})
        w = self.wait_wiz("waiting")
        self.assertEqual(w["phase"], "pick")
        macs = [d["mac"] for d in w["devices"]]
        self.assertEqual(macs[0], PRO)                    # gamepads first
        self.assertNotIn(PRO_LE, macs)                     # the LE face of the same gamepad is merged away
        buds = next(d for d in w["devices"] if d["mac"] == "AA:BB:CC:00:11:22")
        self.assertFalse(buds["pad"])
        self.assertEqual(buds["why_not"], "像是耳机")
        self.assertEqual(w["devices"][0]["kind"], "switch")
        self.assertEqual(w["picked"], PRO)                 # only one is in pairing mode: recommend it
        self.assertEqual(self.steps(), {"ready": "ok", "scan": "ok", "pick": "doing"})
        self.assertIn("scan_stop", self.bt.calls)
        self.assertIn("close", self.bt.calls)              # review 5: close the bluetoothctl session as soon as the scan is done
        self.assertIsNone(w["error"])

    def test_scan_with_nothing_says_put_pad_in_pairing_mode(self):
        self.ops.handle({"op": "scan", "seconds": 0.1})
        w = self.wait_wiz("waiting")
        self.assertEqual(w["error"]["code"], "not_found")
        self.assertIn("快闪", w["error"]["fix"])

    def test_adapter_problems(self):
        self.bt.state["blocked"] = True
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "rfkill")
        self.bt.state.update(blocked=False, present=False)
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "no_adapter")
        self.assertEqual(self.steps()["ready"], "fail")
        # bluetoothd not running: say bluez_down, not "wait a minute" (review 17)
        self.bt.state = {"present": None, "error": "Waiting to connect to bluetoothd...", "code": "bluez_down"}
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "bluez_down")
        # Bluetooth off: turn it on automatically and continue; not bondable: only warn during the scan, don't change it (it is turned on temporarily only when pairing)
        self.bt.state = {"present": True, "powered": False, "pairable": False, "blocked": False}
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.wait_wiz("waiting")
        self.assertIn("power_on", self.bt.calls)
        self.assertNotIn("pairable_on", self.bt.calls)
        ready = next(s for s in self.wiz()["steps"] if s["key"] == "ready")
        self.assertEqual(ready["state"], "ok")
        self.assertIn("可绑定", ready["note"])

    def test_scan_start_failure_is_explained(self):
        self.bt.scan_exc = P.BtError(P.classify("Failed to start discovery: org.bluez.Error.InProgress"), "Failed to start discovery: org.bluez.Error.InProgress")
        self.ops.handle({"op": "scan", "seconds": 0.1})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "busy")
        self.assertEqual(self.steps()["scan"], "fail")
        self.assertIn("close", self.bt.calls)

    def test_cancel_and_busy(self):
        self.ops.handle({"op": "scan", "seconds": 5})
        wait_until(lambda: self.steps().get("scan") == "doing", what="开始搜索")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "scan", "seconds": 5})          # only one at a time
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "pair", "mac": PRO})            # "pair this" during a scan: the backend rejects it (the page button is grayed out too, review 18a)
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "wizard_reset"})
        t0 = time.monotonic()
        self.ops.handle({"op": "cancel"})
        w = self.wait_wiz("failed", timeout=1.0)
        self.assertEqual(w["error"]["code"], "cancelled")
        self.assertLess(time.monotonic() - t0, 1.0)
        self.ops.handle({"op": "wizard_reset"})
        self.assertEqual(self.wiz()["state"], "idle")

    def test_refused_while_walking(self):
        """Review 8: no scanning/pairing while walking / the policy is running (scanning occupies the radio, and a stuck gamepad would leave the duck walking)."""
        self.robot_ok(posture="policy", bus=bus(policy_enabled=True))
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "scan", "seconds": 1})
        self.assertIn("先停下", str(cm.exception))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "pair"})


# ---------------- Pairing ----------------

class PairTest(PadTestBase):
    def paired_result(self, mac=PRO, name="Pro Controller", trusted=True, connected=True):
        return {"outcome": "paired", "pad": {"mac": mac, "name": name, "paired": True, "trusted": trusted, "connected": connected}}

    def test_pair_from_list_via_configd_then_padd_then_keys(self):
        self.bt.found = [{"mac": PRO, "name": "Pro Controller", "cls": 0x2508, "rssi": -50}]
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.wait_wiz("waiting")
        self.watch()
        self.cfg.pair_result = self.paired_result()
        self.cfg.on_pair = lambda params: self.cfg.connect_pad(PRO, "Pro Controller")
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.steps().get("padd") == "doing", what="等 padd")
        self.assertIn(("pad.pair", {"timeout_seconds": 1, "mac": PRO}), self.cfg.calls)
        self.assertIn("close", self.bt.calls)               # first close our own scan session so we don't fight configd over the default agent
        self.tap.attach(PRO_DEV)
        wait_until(lambda: self.wiz()["phase"] == "keys", what="进入按键测试")
        for code in (0x130, 0x131, 0x133, 0x134):
            self.tap.key(code, True)
            self.tap.key(code, False)
        self.tap.axis(0, 30000)
        self.tap.axis(3, -30000)
        w = self.wait_wiz("done")
        self.assertEqual(set(self.steps().values()), {"ok"})
        self.assertIn("configd", w["via"])
        self.assertEqual(w["result_name"], "Pro Controller")
        snap = self.ops.snapshot()
        self.assertEqual(snap["status"]["active"]["mac"], PRO)
        self.assertEqual(snap["live"]["device"]["kind"], "switch")
        json.dumps(snap, ensure_ascii=False)                # can be pushed to the page

    def test_pairable_is_turned_on_only_for_pairing_and_restored(self):
        """Review 5: "bondable" is only turned on temporarily while pairing, and turned back after pairing (whether it succeeded or not)."""
        self.bt.state["pairable"] = False
        self.bt.pairable_ok = True
        self.cfg.pair_result = {"outcome": "failed", "reason": "timeout", "detail": "the pad did not finish pairing"}
        self.ops.handle({"op": "pair", "mac": PRO})
        self.wait_wiz("failed")
        self.assertEqual([c for c in self.bt.calls if str(c).startswith("pairable")], ["pairable_on", "pairable_off"])

    def test_configd_failures_in_plain_words(self):
        cases = [
            ({"outcome": "failed", "reason": "not_found", "detail": "nothing at all turned up"}, "not_found"),
            ({"outcome": "failed", "reason": "not_found", "detail": "nothing that looks like a gamepad turned up. These were in range"}, "not_found_pad"),
            ({"outcome": "failed", "reason": "ambiguous", "detail": "more than one pad is in pairing mode: a, b"}, "ambiguous"),
            ({"outcome": "failed", "reason": "timeout", "detail": "the pad did not finish pairing"}, "timeout"),
            ({"outcome": "failed", "reason": "no_adapter", "detail": "no Bluetooth adapter."}, "no_adapter"),
            ({"outcome": "failed", "reason": "rejected", "detail": "org.bluez.Error.AuthenticationFailed"}, "auth_failed"),
            ({"outcome": "failed", "reason": "rejected", "detail": "org.bluez.Error.Failed: le-connection-abort-by-local"}, "le_abort"),
            ({"outcome": "failed", "reason": "rejected", "detail": "something new"}, "rejected"),
        ]
        for result, code in cases:
            with self.subTest(code=code, detail=result["detail"]):
                self.cfg.pair_result = result
                self.ops.handle({"op": "pair", "mac": XBOX})
                w = self.wait_wiz("failed")
                self.assertEqual(w["error"]["code"], code)
                self.assertEqual(self.steps()["pair"], "fail")
                self.assertTrue(w["error"]["msg"] and w["error"]["fix"])
                self.assertIn(result["detail"], w["error"]["raw"])
                self.assertEqual(w["retry"], {"op": "pair", "mac": XBOX})

    def test_configd_timeout_down_and_no_permission(self):
        self.cfg.pair_exc = Timeout("pad.pair 2 秒没回话")
        self.ops.handle({"op": "pair", "mac": XBOX})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "timeout")
        # configd absent and no MAC: say configd isn't running
        self.cfg.pair_exc = Unreachable("/run/configd.sock 不在")
        self.ops.handle({"op": "pair"})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "configd_down")
        # review 17: socket exists but no permission to connect; must not be reported as "configd absent"
        self.cfg.pair_exc = P.NoPermission("没权限连 unix:/run/configd.sock")
        self.ops.handle({"op": "pair"})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "socket_perm")
        self.assertIn("robot 组", w["error"]["fix"])

    def test_cancel_then_new_pair_while_configd_still_busy(self):
        """Review 10 / R7: "stop" was clicked while configd's pad.pair is still running: don't allow new pairing or scanning."""
        self.cfg.pair_delay = 0.6
        self.cfg.pair_result = {"outcome": "failed", "reason": "timeout", "detail": "x"}
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: any(m == "pad.pair" for m, _ in self.cfg.calls), what="configd 在配")
        self.ops.handle({"op": "cancel"})
        self.wait_wiz("failed")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "pair", "mac": PRO})
        self.assertIn("configd", str(cm.exception))
        self.assertIsNotNone(self.wiz()["configd_busy_s"])
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "scan", "seconds": 1})
        wait_until(lambda: self.wiz()["configd_busy_s"] is None, what="configd 做完")
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.wait_wiz("waiting")

    def test_permission_denied_falls_back_to_one_bluetoothctl_session(self):
        self.watch()
        self.cfg.pair_exc = RpcError("pad.pair", 14, "uid 1000 / gid 1000 may not change this robot's configuration")
        self.bt.infos[PRO] = {"cls": 0x2508, "name": "Pro Controller"}
        self.bt.on_pair = lambda mac: self.cfg.connect_pad(mac, "Pro Controller")
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.steps().get("padd") == "doing", what="等 padd")
        self.assertIn(("pair_device", PRO, True), self.bt.calls)       # classic Bluetooth order
        self.tap.attach(PRO_DEV)
        wait_until(lambda: self.wiz()["phase"] == "keys", what="进入按键测试")
        self.assertIn("bluetoothctl", self.wiz()["via"])
        self.ops.handle({"op": "keys_done"})
        self.assertEqual(self.wiz()["state"], "done")

    def test_fallback_failure_and_auto_pick_without_permission(self):
        self.cfg.pair_exc = RpcError("pad.pair", 14, "may not change this robot's configuration")
        raw = "Failed to pair: org.bluez.Error.AuthenticationFailed"
        self.bt.pair_exc = P.BtError(P.classify(raw), raw)
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "auth_failed")
        self.assertIn("别的设备", w["error"]["fix"])
        # no MAC (auto-pick) and no permission: can't pair by itself, report the lack of permission truthfully and give the SSH method
        self.ops.handle({"op": "pair"})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "permission")
        self.assertIn("sudo robotctl pad pair", w["error"]["fix"])

    def test_connected_but_padd_never_opens_it(self):
        self.watch()
        self.cfg.pair_result = self.paired_result()
        self.cfg.on_pair = lambda params: self.cfg.connect_pad(PRO, "Pro Controller")
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "no_input")
        self.assertEqual(self.steps()["padd"], "fail")
        self.assertEqual(self.steps()["connect"], "ok")

    def test_padd_not_running(self):
        self.watch()
        self.cfg.pair_result = self.paired_result()

        def on_pair(params):
            self.cfg.connect_pad(PRO, "Pro Controller")
            self.cfg.status["driver"] = "failed"
        self.cfg.on_pair = on_pair
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "padd_down")

    def test_paired_but_never_connects_and_untrusted(self):
        self.cfg.pair_result = self.paired_result(trusted=False, connected=False)
        self.cfg.on_pair = lambda params: self.cfg.connect_pad(PRO, "Pro Controller", connected=False, trusted=False)
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "not_connected")
        self.assertEqual(self.steps()["trust"], "fail")

    def test_bad_mac_and_forget(self):
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "pair", "mac": "nope"})
        self.assertEqual(self.ops.handle({"op": "forget", "mac": PRO.lower()}), {"removed": True})
        # configd refuses to delete (not root): fall back to bluetoothctl remove
        self.cfg.forget_exc = RpcError("pad.forget", 14, "may not change")
        self.assertEqual(self.ops.handle({"op": "forget", "mac": PRO}), {"removed": True})
        self.assertIn(("remove", PRO), self.bt.calls)
        # neither works: refuse, and give the SSH method
        self.bt.removed = P.BtError("bt_permission", "org.freedesktop.DBus.Error.AccessDenied")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "forget", "mac": PRO})
        self.assertIn("bluetooth", str(cm.exception))

    def helper_paired(self, mac=PRO, name="Pro Controller", trusted=True, connected=True):
        pair = {"outcome": "paired",
                "pad": {"mac": mac, "name": name, "paired": True, "trusted": trusted, "connected": connected}}
        return (True, "paired", {"pair": pair, "stderr": ["paused btd while the pad bonds"], "stdout": json.dumps(pair)})

    def test_pair_via_helper_then_padd_then_keys(self):
        """Main path: the new helper runs the official robotctl pad pair; doesn't turn on "bondable" and doesn't go through configd."""
        self.watch()
        self.helper.is_available = True
        self.helper.pair_result = self.helper_paired()
        self.helper.on_pair = lambda mac: self.cfg.connect_pad(PRO, "Pro Controller")
        self.ops.handle({"op": "pair", "mac": PRO}, by="电脑 127.0.0.1")
        wait_until(lambda: self.steps().get("padd") == "doing", what="等 padd")
        self.assertEqual(self.helper.pair_calls[0][:2], ("电脑 127.0.0.1", PRO))
        w = self.wiz()
        self.assertIn("小助手", w["via"])
        self.assertIn("robotctl pad pair", w["via"])
        self.assertIs(w["helper_available"], True)
        self.assertEqual([c for c in self.cfg.calls if c[0] == "pad.pair"], [])
        self.assertNotIn("pairable_on", self.bt.calls)
        self.assertNotIn("pairable_off", self.bt.calls)
        self.tap.attach(PRO_DEV)
        wait_until(lambda: self.wiz()["phase"] == "keys", what="进入按键测试")
        self.ops.handle({"op": "keys_done"})
        self.assertEqual(self.wiz()["state"], "done")

    def recovery_pair(self, connected=True):
        self.watch()
        self.ops.w.update(reconnect_after=0.03, reconnect_interval=0.03, reconnect_timeout=0.05)
        self.helper.is_available = True
        self.helper.pair_result = self.helper_paired(connected=connected)
        self.helper.on_pair = lambda mac: self.cfg.connect_pad(PRO, "Pro Controller", connected=False)

    def reconnect_ready(self, mac):
        self.cfg.connect_pad(mac, "Pro Controller")
        self.tap.attach(PRO_DEV)

    def test_helper_stale_connected_recovers_until_matching_input_is_ready(self):
        """The main path returned Connected after pairing, but the link has dropped; only after an extra connect is there event/attached."""
        self.recovery_pair()
        self.bt.on_reconnect = self.reconnect_ready
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.wiz()["phase"] == "keys" or self.wiz()["state"] == "failed")
        self.assertEqual(self.wiz()["phase"], "keys", self.wiz())
        self.assertEqual([x[1] for x in self.bt.calls if isinstance(x, tuple) and x[0] == "reconnect"], [PRO])
        self.assertEqual(self.helper.forget_calls, [])
        self.assertFalse(set(self.robot.methods()) - {"pad.bindings"})

    def test_helper_bonded_but_disconnected_also_recovers(self):
        self.recovery_pair(connected=False)
        self.bt.on_reconnect = self.reconnect_ready
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.wiz()["phase"] == "keys" or self.wiz()["state"] == "failed")
        self.assertEqual(self.wiz()["phase"], "keys", self.wiz())

    def test_matching_input_wins_over_stale_disconnected_configd(self):
        self.recovery_pair(connected=False)
        self.bt.on_reconnect = lambda mac: self.tap.attach(PRO_DEV)
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.wiz()["phase"] == "keys" or self.wiz()["state"] == "failed")
        self.assertEqual(self.wiz()["phase"], "keys", self.wiz())
        self.assertEqual(len([x for x in self.bt.calls if isinstance(x, tuple) and x[0] == "reconnect"]), 1)

    def test_matching_input_received_during_last_reconnect_is_not_lost_at_deadline(self):
        self.recovery_pair()
        clock, offset = self.ops.clock, [0]
        self.ops.clock = lambda: clock() + offset[0]
        def ready_then_timeout(mac):
            self.tap.attach(PRO_DEV)
            offset[0] += 1.0
        self.bt.on_reconnect = ready_then_timeout
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.wiz()["phase"] == "keys" or self.wiz()["state"] == "failed")
        self.assertEqual(self.wiz()["phase"], "keys", self.wiz())

    def test_reconnect_attempts_are_bounded_and_do_not_count_as_input_success(self):
        self.recovery_pair()
        self.helper.on_pair = lambda mac: self.cfg.connect_pad(PRO, "Pro Controller")
        self.bt.reconnect_errors = [P.BtError("busy", "br-connection-busy")] * 5
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "no_input")
        calls = [x for x in self.bt.calls if isinstance(x, tuple) and x[0] == "reconnect"]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(0 < x[2] <= 0.05 for x in calls))

    def test_cancel_while_reconnecting_cannot_advance_or_retry(self):
        self.recovery_pair()
        def cancel(mac):
            self.ops.handle({"op": "cancel"})
            self.reconnect_ready(mac)
        self.bt.on_reconnect = cancel
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "cancelled")
        self.assertEqual(len([x for x in self.bt.calls if isinstance(x, tuple) and x[0] == "reconnect"]), 1)

    def test_cancel_on_final_connection_deadline_keeps_cancelled_reason(self):
        self.recovery_pair(connected=False)
        clock, offset = self.ops.clock, [0]
        self.ops.clock = lambda: clock() + offset[0]
        def cancel_then_timeout(mac):
            self.ops.handle({"op": "cancel"})
            offset[0] += 1.0
            raise P.BtError("timeout", "connect deadline")
        self.bt.on_reconnect = cancel_then_timeout
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        wait_until(lambda: not self.ops._job[1].is_alive())
        self.assertEqual(self.wiz()["error"]["code"], "cancelled", w)

    def test_another_attached_controller_is_not_pairing_success_or_reconnect_target(self):
        self.recovery_pair()
        self.tap.attach(XBOX_DEV)
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "wrong_input")
        self.assertFalse(any(isinstance(x, tuple) and x[0] == "reconnect" for x in self.bt.calls))

    def test_driver_failure_while_disconnected_does_not_start_reconnect(self):
        self.recovery_pair(connected=False)
        def failed(mac):
            self.cfg.connect_pad(mac, "Pro Controller", connected=False)
            self.cfg.status["driver"] = "failed"
        self.helper.on_pair = failed
        self.ops.handle({"op": "pair", "mac": PRO})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "padd_down")
        self.assertFalse(any(isinstance(x, tuple) and x[0] == "reconnect" for x in self.bt.calls))

    def test_policy_start_while_waiting_does_not_start_reconnect(self):
        self.recovery_pair()
        def driving(mac):
            self.cfg.connect_pad(mac, "Pro Controller", connected=False)
            self.robot_ok(posture="policy", bus=bus(policy_enabled=True))
        self.helper.on_pair = driving
        self.ops.handle({"op": "pair", "mac": PRO})
        self.assertEqual(self.wait_wiz("failed")["error"]["code"], "driving")
        self.assertFalse(any(isinstance(x, tuple) and x[0] == "reconnect" for x in self.bt.calls))

    def test_unavailable_tap_keeps_explicit_unverified_compatibility_path(self):
        self.recovery_pair()
        def no_tap(mac):
            self.cfg.connect_pad(mac, "Pro Controller")
            self.tap.on_state("denied", "permission")
        self.helper.on_pair = no_tap
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.wiz()["phase"] == "keys" or self.wiz()["state"] == "failed")
        self.assertEqual(self.wiz()["phase"], "keys", self.wiz())
        padd = next(s for s in self.wiz()["steps"] if s["key"] == "padd")
        self.assertIn("没法再核对", padd["note"])
        self.assertFalse(any(isinstance(x, tuple) and x[0] == "reconnect" for x in self.bt.calls))

    def test_controller_arriving_during_unverified_fallback_is_checked_again(self):
        for device, expected in ((XBOX_DEV, "failed"), (PRO_DEV, "waiting")):
            with self.subTest(device=device["name"]):
                self.ops.handle({"op": "wizard_reset"})
                self.ops._tap_report({"report": "detached", "why": "test"})
                self.recovery_pair()
                def no_tap(mac):
                    self.cfg.connect_pad(mac, "Pro Controller")
                    self.tap.on_state("denied", "permission")
                self.helper.on_pair = no_tap
                step = self.ops._step
                def late_input(jid, key, state, note=None):
                    step(jid, key, state, note)
                    if key == "padd" and state == "ok" and "没法再核对" in (note or ""):
                        self.tap.attach(device)
                with mock.patch.object(self.ops, "_step", side_effect=late_input):
                    self.ops.handle({"op": "pair", "mac": PRO})
                    wait_until(lambda: self.wiz()["phase"] == "keys" or self.wiz()["state"] == "failed")
                w = self.wiz()
                self.assertEqual(w["state"], expected, w)
                if expected == "failed":
                    self.assertEqual(w["error"]["code"], "wrong_input")
                else:
                    padd = next(s for s in w["steps"] if s["key"] == "padd")
                    self.assertEqual(padd["note"], PRO_DEV["name"])

    def test_matching_late_input_clears_readiness_failure_but_not_cancel(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                self.ops.handle({"op": "wizard_reset"})
                self.ops._tap_report({"report": "detached", "why": "test"})
                self.recovery_pair()
                self.ops.handle({"op": "pair", "mac": PRO})
                self.wait_wiz("failed")
                if cancelled:
                    self.ops.handle({"op": "cancel"})
                self.tap.attach(PRO_DEV)
                w = self.wiz()
                if cancelled:
                    self.assertEqual(w["state"], "failed")
                else:
                    self.assertEqual(w["phase"], "keys", w)
                    self.assertIsNone(w["error"])
                    self.assertEqual(self.steps()["connect"], "ok")
                    self.assertEqual(self.steps()["padd"], "ok")
                self.ops._tap_report({"report": "detached", "why": "test"})

    def test_helper_failures_in_plain_words(self):
        cases = [
            ("not_found", "nothing that looks like a gamepad turned up", "not_found"),
            ("ambiguous", "more than one pad is in pairing state", "ambiguous"),
            ("timeout", "the pad did not finish pairing", "timeout"),
            ("no_adapter", "no Bluetooth adapter", "no_adapter"),
            ("other", "something new", "other"),
        ]
        self.helper.is_available = True
        for reason, detail, code in cases:
            with self.subTest(reason=reason):
                self.helper.pair_result = (False, "pair_failed", {
                    "reason": reason,
                    "pair": {"outcome": "failed", "reason": reason, "detail": detail},
                    "stderr": ["warning: could not power-cycle the Bluetooth adapter"],
                    "msg": f"robotctl 说配对失败：{reason}",
                })
                self.ops.handle({"op": "pair", "mac": XBOX})
                w = self.wait_wiz("failed")
                self.assertEqual(w["error"]["code"], code)
                self.assertIn(detail, w["error"]["raw"])
                self.assertIn("could not power-cycle", w["error"]["raw"])
                self.assertEqual(w["retry"], {"op": "pair", "mac": XBOX})

    def test_helper_process_timeout_is_reported(self):
        self.helper.is_available = True
        self.helper.pair_result = (False, "timeout", {"msg": "robotctl pad pair 超过 90 秒，已经杀掉", "stderr": []})
        self.ops.handle({"op": "pair", "mac": PRO})
        w = self.wait_wiz("failed")
        self.assertEqual(w["error"]["code"], "timeout")
        self.assertIn("超", w["error"]["raw"] + w["error"]["msg"])

    def test_old_helper_bad_verb_falls_back_to_configd(self):
        self.watch()
        self.helper.is_available = True
        self.helper.pair_result = (False, "bad_verb", {"msg": "只认这几个动词"})
        self.cfg.pair_result = self.paired_result()
        self.cfg.on_pair = lambda params: self.cfg.connect_pad(PRO, "Pro Controller")
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.steps().get("padd") == "doing", what="后备路等 padd")
        self.assertIn(("pad.pair", {"timeout_seconds": 1, "mac": PRO}), self.cfg.calls)
        self.assertIs(self.wiz()["helper_available"], False)
        self.assertIn("configd", self.wiz()["via"])
        self.tap.attach(PRO_DEV)
        wait_until(lambda: self.wiz()["phase"] == "keys", what="进入按键测试")

    def test_fallback_agent_failure_reopens_session_once(self):
        self.cfg.pair_exc = RpcError("pad.pair", 14, "may not change this robot's configuration")
        self.bt.infos[PRO] = {"cls": 0x2508, "name": "Pro Controller"}
        self.bt.pair_excs = [P.BtError("agent", "Failed to register agent object")]
        self.bt.on_pair = lambda mac: self.cfg.connect_pad(PRO, "Pro Controller")
        self.ops.handle({"op": "pair", "mac": PRO})
        wait_until(lambda: self.steps().get("padd") == "doing", what="重试后等 padd")
        pairs = [c for c in self.bt.calls if isinstance(c, tuple) and c[:2] == ("pair_device", PRO)]
        self.assertEqual(len(pairs), 2)
        self.assertIn("close", self.bt.calls)
        self.tap.attach(PRO_DEV)
        wait_until(lambda: self.wiz()["phase"] == "keys", what="进入按键测试")

    def test_padd_wait_default_is_30_seconds(self):
        self.assertEqual(P.PADD_WAIT_S, 30)
        self.assertEqual(self.ops.w["padd"], FAST["padd"])       # waits shortened for the test, doesn't really wait 30 s

    def test_forget_via_helper_and_old_helper_falls_back(self):
        self.helper.is_available = True
        self.helper.forget_result = (True, "forgotten", {"removed": True})
        self.assertEqual(self.ops.handle({"op": "forget", "mac": PRO}, by="电脑"), {"removed": True})
        self.assertEqual(self.helper.forget_calls[0][:2], ("电脑", PRO))
        self.assertEqual([c for c in self.cfg.calls if c[0] == "pad.forget"], [])
        # old helper returns bad_verb: fall back to configd → bluetoothctl as before
        self.helper.forget_result = (False, "bad_verb", {"msg": "只认这几个动词"})
        self.assertEqual(self.ops.handle({"op": "forget", "mac": PRO}), {"removed": True})
        self.assertIn(("pad.forget", {"mac": PRO}), self.cfg.calls)
        self.assertIs(self.wiz()["helper_available"], False)

    def test_forget_connected_pad_while_walking_is_refused(self):
        self.cfg.connect_pad(PRO, "Pro Controller")
        self.ops.handle({"op": "refresh"})
        self.robot_ok(posture="walking")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "forget", "mac": PRO})
        self.assertIn("停下", str(cm.exception))


# ---------------- E-stop ----------------

class EStopTest(PadTestBase):
    def ready(self):
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.watch()
        self.tap.attach(XBOX_DEV)
        wait_until(lambda: self.ops.snapshot()["estop"]["ok"], what="急停四条都 ✓")

    def state(self):
        return self.ops.snapshot()["estop_test"]["state"]

    def start_armed(self):
        self.ready()
        self.ops.handle({"op": "estop_test", "action": "start"})
        wait_until(lambda: self.state() == "armed", what="确认上着力、等按 Select")

    def press_select(self):
        self.tap.key(0x13A, True)
        self.assertEqual(self.state(), "pressed")
        wait_until(lambda: self.ops.test.get("_on_while_pressed") is not None or self.ops.test.get("_press_err"),
                   what="按着的时候问过一次扭矩")

    def test_checks(self):
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        es = self.ops.snapshot()["estop"]
        self.assertTrue(es["ok"])
        self.assertEqual(es["state"], "ok")
        self.assertEqual([c["key"] for c in es["checks"]], ["pad", "padd", "robotd", "netpad"])
        self.toml = "[netpad]\nenabled = true\nport = 4210\n"
        self.ops._refresh_files()
        es = self.ops.snapshot()["estop"]
        self.assertFalse(es["ok"])
        self.assertEqual(es["state"], "bad")
        self.assertFalse(next(c for c in es["checks"] if c["key"] == "netpad")["ok"])
        # review 7: an unreadable robotd.toml is not treated as "off": the overall verdict gets no ✓, says "not checked"
        self.toml = None
        self.ops._refresh_files()
        es = self.ops.snapshot()["estop"]
        self.assertFalse(es["ok"])
        self.assertEqual(es["state"], "unknown")
        self.assertIn("没核对", next(c for c in es["checks"] if c["key"] == "netpad")["why"])
        self.ops.read_text = lambda p: (_ for _ in ()).throw(PermissionError(13, "Permission denied"))
        self.ops._refresh_files()
        es = self.ops.snapshot()["estop"]
        self.assertEqual(es["state"], "unknown")
        self.assertIn("没权限", next(c for c in es["checks"] if c["key"] == "netpad")["why"])
        # file absent: robotd uses all defaults, netpad off by default
        self.ops.read_text = lambda p: (_ for _ in ()).throw(FileNotFoundError(2, "No such file"))
        self.ops._refresh_files()
        self.assertTrue(self.ops.snapshot()["estop"]["ok"])
        # main program absent / debug mode: doesn't count as valid
        self.robot_ok(present=False)
        self.assertFalse(self.ops.snapshot()["estop"]["ok"])
        self.robot_ok(bus=dict(bus(), mode="commissioning"))
        self.assertFalse(self.ops.snapshot()["estop"]["ok"])
        self.assertEqual(self.ops.estop_ok(), False)        # the lightweight version from review 23 matches snapshot

    def test_tap_is_evidence_when_configd_unreadable(self):
        """Review 16: the first unit normally has configd off; seeing attached on the tap counts as evidence of "gamepad connected, padd running"."""
        self.cfg.status_exc = Unreachable("/run/configd.sock 不在")
        self.watch()
        self.tap.attach(XBOX_DEV)
        es = self.ops.snapshot()["estop"]
        by = {c["key"]: c for c in es["checks"]}
        self.assertTrue(by["pad"]["ok"])
        self.assertIn("旁路", by["pad"]["why"])
        self.assertTrue(by["padd"]["ok"])
        self.assertTrue(es["ok"])

    def test_connected_but_no_input_device_is_not_effective(self):
        self.cfg.connect_pad(PRO, "Pro Controller")
        self.watch()
        self.ops._attach_wait_since = time.monotonic() - 10       # subscribed for 10 s, padd never opened it
        es = self.ops.snapshot()["estop"]
        self.assertFalse(es["ok"])
        self.assertFalse(next(c for c in es["checks"] if c["key"] == "input")["ok"])

    def test_passes_only_with_select_seen_and_torque_read_back_off(self):
        self.start_armed()
        self.press_select()
        self.assertIs(self.ops.test["_on_while_pressed"], True)
        self.tap.key(0x13A, False)
        self.assertEqual(self.state(), "released")
        time.sleep(0.05)
        self.robot_ok(torque_on=False)                          # padd sent relax: readback confirms torque OFF
        wait_until(lambda: self.state() == "passed", what="通过")
        t = self.ops.snapshot()["estop_test"]
        self.assertIsInstance(t["ms"], int)
        self.assertNotIn("_released_at", t)                     # internal fields are not pushed to the page

    def test_r1_torque_already_off_before_select_is_not_a_pass(self):
        """Review 1 / R1: if the top "release torque" was already confirmed (estop_active back to False), or a fall auto-released torque, before Select is pressed: must not tick."""
        self.start_armed()
        self.robot_ok(torque_on=False, estop_active=False)      # torque was already off before Select was pressed
        wait_until(lambda: self.state() == "failed", what="还没按就判没通过")
        self.assertEqual(self.ops.snapshot()["estop_test"]["failed_at"], "early_off")
        self.tap.key(0x13A, True)                               # pressing Select afterwards with readback OFF: still can't flip to pass
        self.tap.key(0x13A, False)
        self.robot_ok(torque_on=False)
        time.sleep(0.1)
        self.assertEqual(self.state(), "failed")

    def test_r1b_top_relax_pressed_during_test_is_not_a_pass(self):
        """The top "release torque" was also pressed during the test (press_count changed): doesn't count even if the readback is OFF afterwards."""
        self.start_armed()
        self.press_select()
        self.tap.key(0x13A, False)
        self.relax_pressed()
        wait_until(lambda: self.state() == "failed", what="没通过")
        self.assertEqual(self.ops.snapshot()["estop_test"]["failed_at"], "relax")

    def test_r2_long_hold_is_shutdown_not_estop(self):
        """Review 1 / R2: holding for a full 2 s makes padd send robot.shutdown (sit down and power off): fail immediately."""
        self.start_armed()
        self.press_select()
        wait_until(lambda: self.ops.snapshot()["estop_test"]["held_long"], what="按太久的警告")
        wait_until(lambda: self.state() == "failed", what="按满了直接判失败")
        t = self.ops.snapshot()["estop_test"]
        self.assertEqual(t["failed_at"], "long")
        self.assertIn("shutdown", t["why"])
        self.tap.key(0x13A, False)
        self.robot_ok(torque_on=False)
        time.sleep(0.1)
        self.assertEqual(self.state(), "failed")                # readback OFF after release doesn't flip it to pass either

    def test_off_readback_asked_before_release_does_not_count(self):
        """Only readbacks requested "after release" count: an OFF obtained before release (torque was off while held) fails."""
        self.start_armed()
        self.robot.bus = bus(False)                             # robotd already reports OFF at the moment of pressing
        self.tap.key(0x13A, True)
        wait_until(lambda: self.ops.test.get("_on_while_pressed") is not None or self.state() == "failed", what="按着时问过")
        self.tap.key(0x13A, False)
        wait_until(lambda: self.state() == "failed", what="没通过")
        self.assertIn(self.ops.snapshot()["estop_test"]["failed_at"], ("pressed_off", "early_off"))

    def test_fails_when_readback_never_shows_torque_off(self):
        self.start_armed()
        self.press_select()
        self.tap.key(0x13A, False)
        wait_until(lambda: self.state() == "failed", what="没通过")
        t = self.ops.snapshot()["estop_test"]
        self.assertEqual(t["failed_at"], "readback")
        self.assertIn("顶上的「卸力」", t["fix"])

    def test_waits_for_torque_then_times_out_without_select(self):
        self.ready()
        self.robot_ok(torque_on=False)                          # limp: wait for it to stand up first
        self.ops.handle({"op": "estop_test", "action": "start"})
        self.assertEqual(self.state(), "need_torque")
        time.sleep(0.05)
        self.robot_ok(torque_on=True)
        wait_until(lambda: self.state() == "armed", what="上力了")
        wait_until(lambda: self.state() == "failed", what="没按 Select")
        self.assertEqual(self.ops.snapshot()["estop_test"]["failed_at"], "press")

    def test_refused_when_path_is_broken(self):
        self.cfg.status["driver"] = "failed"
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "estop_test", "action": "start"})
        self.assertIn("padd", str(cm.exception))


# ---------------- Web remote: sticks ----------------

class MoveTest(PadTestBase):
    def test_sends_official_fields_clamped(self):
        r = self.ops.handle({"op": "move", "vx": 1.0, "vy": -0.1, "vyaw": 9, "seq": 1})
        self.assertEqual(r["sent"], [0.3, -0.1, 1.5])
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.3, "vy": -0.1, "vyaw": 1.5}))
        self.assertEqual(self.ops.snapshot()["virtual"]["owner"], "web")
        # review 21: updates faster than 25 Hz are not dropped; wait a bit and send the latest one
        r = self.ops.handle({"op": "move", "vx": 0.1, "seq": 2})
        self.assertTrue(r["merged"])
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.1, "vy": 0.0, "vyaw": 0.0}))
        self.ops.handle({"op": "stop", "seq": 3})
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}))
        self.assertIsNone(self.ops.snapshot()["virtual"]["owner"])
        lim = self.ops.snapshot()["virtual"]["limits"]
        self.assertEqual((lim["v"], lim["w"]), (0.3, 1.5))
        self.assertIn("官方默认", lim["src"])

    def test_merging_keeps_only_the_newest(self):
        self.ops.handle({"op": "move", "vx": 0.1, "seq": 1})
        out = {}
        ts = [threading.Thread(target=lambda s=s: out.__setitem__(s, self.ops.handle({"op": "move", "vx": 0.1 * s, "seq": s})))
              for s in (2, 3)]
        for t in ts:
            t.start()
            time.sleep(0.005)
        for t in ts:
            t.join()
        self.assertIn("dropped", out[2])                     # a newer update arrived while waiting: the old one isn't sent
        self.assertEqual(self.robot.sent[-1][1]["vx"], 0.3)

    def test_r8_stale_move_after_stop_is_dropped(self):
        """Review 3 / R8: the page sends move then stop, but stop arrives first in to_thread: any older move arriving afterwards is dropped."""
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 10})
        self.ops.handle({"op": "stop", "seq": 12})
        r = self.ops.handle({"op": "move", "vx": 0.3, "seq": 11})     # older than stop
        self.assertIn("dropped", r)
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}))
        self.assertIsNone(self.ops.snapshot()["virtual"]["owner"])
        r = self.ops.handle({"op": "move", "vx": 0.1, "seq": 13})     # a new press works as usual
        self.assertEqual(r["sent"][0], 0.1)

    def test_owner_only_stop_fences_its_own_frames_without_stopping_another_driver(self):
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 1}, conn="a")
        before = list(self.robot.sent)
        result = self.ops.handle({"op": "stop", "seq": 2, "owned_only": True}, conn="b")
        self.assertIn("dropped", result)
        self.assertEqual(self.robot.sent, before)
        self.assertEqual(self.ops._seq_of("b")["stop"], 2)
        result = self.ops.handle({"op": "stop", "seq": 3, "owned_only": True}, conn="a")
        self.assertTrue(result["sent"])
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}))

    def test_refused_cases(self):
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": float("nan")})
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": "fast"})
        self.robot_ok(present=False)
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": 0.1})
        # review 14: main program state unknown (not in motion mode, stale readback): not allowed either
        self.robot_ok(bus=bus(mode="weird"))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": 0.1})
        self.robot_ok(bus_at=time.monotonic() - 10)
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": 0.1})
        self.robot_ok()
        # physical gamepad connected: padd sends zero velocity every 0.1 s and would override the web one → refuse, the page mirrors
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "move", "vx": 0.1})
        self.assertIn("实体手柄", str(cm.exception))
        snap = self.ops.snapshot()["virtual"]
        self.assertEqual(snap["owner"], "pad")
        self.assertTrue(snap["mirror"])
        self.assertEqual(self.robot.sent, [])
        # web stick not open while mirroring: releasing doesn't send 0 either (don't interrupt the physical gamepad: second review, general 2)
        self.assertEqual(self.ops.handle({"op": "stop"}), {"sent": False})
        self.assertEqual(self.robot.sent, [])
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "drive", "on": True})        # opening the web stick isn't accepted while mirroring

    def test_stale_pad_status_does_not_block_forever(self):
        """Review 15: configd stopped and the status is stuck at "connected": after 15 s it is no longer treated as a connected physical gamepad."""
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        self.ops._status_at = time.monotonic() - 30
        self.assertEqual(self.ops.handle({"op": "move", "vx": 0.1})["sent"][0], 0.1)

    def test_relax_guard(self):
        """No stick input accepted within 2 s after torque release (enable / release share one slot, last write wins)."""
        self.relax_pressed()
        self.robot_ok()
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "move", "vx": 0.1})
        self.assertIn("卸力", str(cm.exception))

    def test_send_failure_is_refused_not_retried(self):
        self.robot.fail = Unreachable("/run/robotd.sock 不在")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": 0.1})

    def test_one_page_drives_at_a_time(self):
        """Review 19, 25: only one page can drive at a time; other pages must click "take over" (「接管」); if the page holding the wheel disconnects, stop immediately."""
        self.ops.handle({"op": "move", "vx": 0.1, "seq": 1}, by="电脑 A", conn="a")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "move", "vx": 0.2, "seq": 1}, by="手机 B", conn="b")
        self.assertIn("电脑 A", str(cm.exception))
        self.assertIn("接管", str(cm.exception))
        snap_b = self.ops.snapshot(conn="b")["virtual"]["driver"]
        self.assertEqual((snap_b["by"], snap_b["mine"]), ("电脑 A", False))
        self.assertTrue(self.ops.snapshot(conn="a")["virtual"]["driver"]["mine"])
        self.ops.handle({"op": "drive", "on": True, "force": True}, by="手机 B", conn="b")
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}))   # taking over stops first
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": 0.1, "seq": 2}, by="电脑 A", conn="a")
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 2}, by="手机 B", conn="b")
        self.ops.drop_client("b", "手机 B")
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}))
        self.assertIsNone(self.ops.snapshot()["virtual"]["driver"])
        self.ops.handle({"op": "move", "vx": 0.1, "seq": 3}, by="电脑 A", conn="a")        # once it's free it can be opened

    def test_speed_limits_from_padd_unit(self):
        """Review 24: if the full-stick speed was changed in padd.service, use the changed value; values above the limit are clamped to the limit."""
        files = {D.PADD_UNIT: "[Service]\nExecStart=/opt/robot/daemon/current/bin/padd --max-linear 0.2 --max-angular=1.0\n"}
        self.ops.read_text = lambda p: files[p] if p in files else self.toml
        self.ops._refresh_files()
        self.assertEqual(self.ops.handle({"op": "move", "vx": 1, "vyaw": 5})["sent"], [0.2, 0.0, 1.0])
        files[D.PADD_UNIT] = "ExecStart=/x/padd --max-linear 5\n"
        self.ops._refresh_files()
        lim = self.ops.snapshot()["virtual"]["limits"]
        self.assertEqual(lim["v"], D.V_CEIL)
        self.assertIn("上限", lim["src"])
        # a badly written number (second review I3): don't raise, skip that parameter, and say so on the page
        files[D.PADD_UNIT] = "ExecStart=/x/padd --max-linear 1.2.3 --max-angular 1.0\n"
        self.ops._refresh_files()
        lim = self.ops.snapshot()["virtual"]["limits"]
        self.assertEqual((lim["v"], lim["w"]), (0.3, 1.0))
        self.assertIn("1.2.3", lim["src"])


# ---------------- Stand up / start walking / sit down / skills / sounds ----------------

class MotionTest(PadTestBase):
    def pose(self, posture, keep_guard=False, **kw):
        pol = dict(POLICIES, **kw.pop("pol", {}))
        torque = kw.pop("torque_on", posture not in ("limp",))
        b = kw.pop("bus", bus(torque, policy_enabled=posture in ("policy", "walking") or pol.get("sitting") is True,
                              homed=posture in ("holding", "policy", "walking", "sitting")))
        self.robot_ok(posture=posture, policies=pol, bus=b, **kw)
        if not keep_guard:
            self.ops._relax_at = -1e9          # these tests don't test the torque-release guard: the moment it goes limp doesn't count

    def buttons(self):
        return self.ops.snapshot()["motion"]["buttons"]

    def test_stand_walk_sit_follow_the_official_table(self):
        self.pose("limp")
        b = self.buttons()
        self.assertTrue(b["stand"]["ok"])
        self.assertEqual(b["stand"]["call"], "robot.init")
        self.assertIn("站起来", b["walk"]["why"])
        self.assertIn("站起来", b["sit"]["why"])
        self.ops.handle({"op": "stand"}, by="电脑")
        self.assertEqual(self.robot.calls[-1], ("robot.init", {}))
        # standing and holding: can "start walking"; sitting down needs the policy running (main.rs:4231-4235), say so up front
        self.pose("holding")
        b = self.buttons()
        self.assertFalse(b["stand"]["ok"])
        self.assertTrue(b["walk"]["ok"])
        self.assertIn("开始走", b["sit"]["why"])
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "sit"})
        self.ops.handle({"op": "walk"})
        # after the "start walking" ack it also reads back busStatus to confirm the policy really started, so calls[-1] can't be used
        self.assertIn(("robot.enable", {"on": True, "toggle": False}),
                      [c for c in self.robot.calls if c[0] != "robot.busStatus"])   # no toggle
        # policy running: the button becomes "stop" (「停下」); sit down = sit_toggle
        self.pose("policy")
        b = self.buttons()
        self.assertEqual(b["walk"]["op"], "walk_stop")
        self.assertTrue(b["sit"]["ok"])
        self.ops.handle({"op": "sit"})
        self.assertEqual(self.robot.calls[-1], ("robot.do", {"skill": "sit_toggle"}))
        # sitting: standing up is also sit_toggle, must not send init (lib.rs:2362-2370)
        self.pose("sitting", pol={"sitting": True})
        b = self.buttons()
        self.assertEqual(b["stand"]["call"], "robot.do sit_toggle")
        self.ops.handle({"op": "stand"})
        self.assertEqual(self.robot.calls[-1], ("robot.do", {"skill": "sit_toggle"}))
        log = self.log.recent(50, cats=["命令"])
        self.assertTrue(any("站起来" in e["msg"] and "成功" in e["msg"] for e in log))

    def test_walk_reports_the_real_reason_when_policy_is_refused(self):
        """robot.enable only accepts the request: when home_start_guard rejects the policy start, "start walking succeeded" must not be shown."""
        self.pose("holding")
        self.robot.replies["robot.enable"] = {"accepted": True}      # the ack says accepted, but the policy didn't start
        self.robot.bus["last_enable_refusal"] = (
            "不能进入保持：正在确认实际 HOME 和直立姿态（连续 3 帧）；请回 HOME、扶正后重新按键")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "walk"})
        self.assertIn("不能进入保持", str(cm.exception))
        log = [e["msg"] for e in self.log.recent(50, cats=["命令"])]
        self.assertTrue(any("开始走" in m and "没成功" in m for m in log), log)
        self.assertFalse(any("开始走" in m and "成功" in m and "没成功" not in m for m in log), log)

    def test_walk_falls_back_to_home_start_guard_reason(self):
        self.pose("holding")
        self.robot.replies["robot.enable"] = {"accepted": True}
        self.robot.bus.pop("last_enable_refusal", None)
        self.robot.bus["home_start_guard"] = {"ready": False, "reason": "不能进入保持：舵机反馈不完整或不新鲜"}
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "walk"})
        self.assertIn("舵机反馈不完整", str(cm.exception))

    def test_walk_stop_zeros_speed_then_disables(self):
        """Second review I5: really wait until velocity is zero before sending enable off (delete the waiting part and this test fails)."""
        self.pose("walking", applied=[0.2, 0, 0])
        seen = {}

        def enable(params):
            seen["applied"] = list(self.ops._robot.get("applied") or [])
            seen["params"] = params
            seen["t"] = time.monotonic()
            return {"accepted": True}
        self.robot.replies["robot.enable"] = enable
        t0 = time.monotonic()
        threading.Timer(0.3, lambda: self.pose("walking", applied=[0.0, 0.0, 0.0])).start()
        self.ops.handle({"op": "walk_stop"})
        self.assertEqual(seen["applied"], [0.0, 0.0, 0.0])
        self.assertEqual(seen["params"], {"on": False, "toggle": False})
        self.assertGreaterEqual(seen["t"] - t0, 0.25)
        self.assertEqual(self.robot.methods()[-2:], ["robot.stop", "robot.enable"])

    def test_refusals_are_explained_and_broadcast(self):
        self.pose("policy")
        self.robot.replies["robot.do"] = {"accepted": False, "reason": "the policy is not driving — press Start on the pad"}
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "sit"}, by="手机")
        self.assertIn("开始走", str(cm.exception))
        last = self.ops.snapshot()["motion"]["last"]
        self.assertEqual((last["ok"], last["by"]), (False, "手机"))
        err = [e for e in self.log.recent(20, cats=["命令"]) if e["level"] == "error"]
        self.assertTrue(err and "the policy is not driving" in err[-1]["msg"])

    def test_blocked_states(self):
        for kw, word in (({"paused": "调舵机"}, "调舵机"), ({"present": False}, "没在跑"),
                         ({"bus": bus(mode="commissioning")}, "调试"), ({"bus": bus(phase="waiting_for_bus")}, "启动")):
            with self.subTest(word=word):
                self.pose("limp", **kw)
                with self.assertRaises(P.Refused) as cm:
                    self.ops.handle({"op": "stand"})
                self.assertIn(word, str(cm.exception))
        # no standing up within 2 s after torque release (prevents being pushed back up right after releasing)
        self.pose("limp")
        self.relax_pressed()
        self.pose("limp", keep_guard=True)
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "stand"})
        self.assertIn("卸力", str(cm.exception))

    def test_skills_from_policies(self):
        self.pose("policy")
        sk = {s["name"]: s for s in self.ops.snapshot()["motion"]["skills"]}
        self.assertEqual(list(sk), ["ground_pick", "roulade", "kick_left", "kick_right", "roller_stand"])
        self.assertTrue(sk["kick_left"]["ok"])
        self.assertIn("滑轮", sk["roller_stand"]["why"])       # roller stand-up is only in roller mode
        self.ops.handle({"op": "skill", "name": "kick_left"})
        self.assertEqual(self.robot.calls[-1], ("robot.do", {"skill": "kick_left"}))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "skill", "name": "fly"})
        self.pose("holding")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "skill", "name": "kick_left"})
        self.assertIn("开始走", str(cm.exception))

    def test_sound_works_even_when_limp_and_explains_no_voice(self):
        self.pose("limp")
        self.ops.handle({"op": "sound", "tag": "chirp"})
        self.assertEqual(self.robot.calls[-1], ("robot.sound", {"tag": "chirp"}))
        self.robot.replies["robot.sound"] = {"accepted": False, "reason": "this robot has no voice: audio is disabled"}
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "sound", "tag": "greet"})
        self.assertIn("没有声音", str(cm.exception))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "sound", "tag": "wheee"})       # must be sent continuously while held, not made into a one-shot button

    def test_one_command_at_a_time(self):
        self.pose("limp")
        gate = threading.Event()
        self.robot.replies["robot.init"] = lambda p: (gate.wait(1), {"accepted": True})[1]
        t = threading.Thread(target=self.ops.handle, args=({"op": "stand"},))
        t.start()
        wait_until(lambda: self.ops.snapshot()["motion"]["busy"], what="第一个在路上")
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "stand"})
        self.assertIn("还没回话", str(cm.exception))
        gate.set()
        t.join()

    def test_pad_attached_still_allows_discrete_commands(self):
        """Physical gamepad connected: stand / walk / sit / skills are one-shot requests that don't compete with padd and work as usual; sticks and actions don't."""
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        self.pose("policy")
        self.ops.handle({"op": "skill", "name": "roulade"})
        acts = {a["id"]: a for a in self.ops.snapshot()["motion"]["actions"]}
        self.assertIn("实体手柄", acts["nod"]["why"])


# ---------------- Actions, combo actions ----------------

class ActionTest(PadTestBase):
    def setUp(self):
        super().setUp()
        self.robot_ok(posture="policy", policies=POLICIES)

    def heads(self):
        return [p for m, p in self.robot.sent if m == "robot.head"]

    def keep_holding(self, stop, conn=None):
        while not stop.is_set():
            self.ops.handle({"op": "action_hold"}, conn=conn)
            self.robot_ok(posture="policy", policies=POLICIES)
            time.sleep(0.1)

    def test_hold_to_run_then_release_recenters_head(self):
        r = self.ops.handle({"op": "action_start", "id": "nod"}, by="电脑")
        self.assertGreater(r["seconds"], 0.5)
        stop = threading.Event()
        threading.Thread(target=self.keep_holding, args=(stop,), daemon=True).start()
        wait_until(lambda: len(self.heads()) > 3, what="在点头")
        self.assertTrue(any(abs(h["head_pitch"]) > 0.1 for h in self.heads()))
        stop.set()
        self.ops.handle({"op": "action_stop"})
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="停了")
        self.assertEqual(self.heads()[-1], {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0})
        self.assertIn("停了", self.ops.snapshot()["motion"]["last_action"]["result"])

    def test_page_stops_saying_hold_means_stop(self):
        """Release, page switch, network loss, going to background: once the page stops saying "still held", stop within 0.45 s and close the mouth."""
        self.ops.handle({"op": "action_start", "id": "mouth"})
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, timeout=2, what="自己停")
        mouths = [p for m, p in self.robot.sent if m == "robot.mouth"]
        self.assertTrue(mouths and mouths[-1] == {"open": 0.0})
        self.assertIn("没说", self.ops.snapshot()["motion"]["last_action"]["result"])

    def test_relax_and_pad_attach_interrupt(self):
        stop = threading.Event()
        self.ops.handle({"op": "action_start", "id": "hello"})
        threading.Thread(target=self.keep_holding, args=(stop,), daemon=True).start()
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is not None, what="在做")
        stop.set()
        self.presses += 1
        self.robot_ok(posture="policy", policies=POLICIES)          # torque release pressed at the top
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="卸力打断")
        self.assertIn("卸力", self.ops.snapshot()["motion"]["last_action"]["result"])
        self.assertEqual(self.robot.calls[0], ("robot.sound", {"tag": "greet"}))
        # physical gamepad connects: also interrupts
        time.sleep(FAST["relax_guard"] + 0.05)
        self.robot_ok(posture="policy", policies=POLICIES)
        stop = threading.Event()
        self.ops.handle({"op": "action_start", "id": "shake"})
        threading.Thread(target=self.keep_holding, args=(stop,), daemon=True).start()
        self.watch()
        self.tap.attach(XBOX_DEV)
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="手柄连上打断")
        stop.set()
        self.assertIn("实体手柄", self.ops.snapshot()["motion"]["last_action"]["result"])

    def test_actions_need_policy_and_one_at_a_time(self):
        self.ops.handle({"op": "action_start", "id": "nod"}, conn="a")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "action_start", "id": "shake"}, conn="a")
        self.ops.handle({"op": "action_stop"}, conn="a")
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="停了")
        self.robot_ok(posture="holding", policies=POLICIES)
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "action_start", "id": "nod"}, conn="a")
        self.assertIn("开始走", str(cm.exception))

    def test_user_combos_saved_loaded_and_validated(self):
        combo = {"id": "wave", "name": "挥挥手", "steps": [{"do": "sound", "tag": "coo"}, {"do": "nod", "times": 9},
                                                          {"do": "mouth", "open": 3, "ms": 50}]}
        self.ops.handle({"op": "combo_save", "combo": combo})
        saved = next(c for c in self.ops.snapshot()["motion"]["combos"] if c["id"] == "wave")
        self.assertFalse(saved["builtin"])
        self.assertIn("点头 4 次", saved["text"])             # clamped into range
        again = P.PadOps(self.log, robot=self.robot, state_dir=self.ops.state_dir)
        self.assertEqual([c["id"] for c in again._user_combos], ["wave"])
        for bad, word in (({"id": "hello", "name": "x", "steps": [{"do": "wait"}]}, "内置"),
                          ({"id": "w2", "name": "x", "steps": [{"do": "move", "vx": 1}]}, "不认识"),
                          ({"id": "w3", "name": "x", "steps": [{"do": "skill", "name": "sit_toggle"}]}, "坐下"),
                          ({"id": "W!", "name": "x", "steps": [{"do": "wait"}]}, "编号")):
            with self.subTest(word=word):
                with self.assertRaises(P.Refused) as cm:
                    self.ops.handle({"op": "combo_save", "combo": bad})
                self.assertIn(word, str(cm.exception))
        self.ops.handle({"op": "combo_delete", "id": "wave"})
        self.assertFalse(any(c["id"] == "wave" for c in self.ops.snapshot()["motion"]["combos"]))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "combo_delete", "id": "hello"})

    def test_broken_combo_file_is_skipped_with_a_log_line(self):
        path = Path(self.ops.state_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / C.COMBO_FILE).write_text('{"combos": [{"id": "ok1", "name": "好", "steps": [{"do": "nod"}]}, {"id": "bad"}]}',
                                         encoding="utf-8")
        ops = P.PadOps(self.log, robot=self.robot, state_dir=str(path))
        self.assertEqual([c["id"] for c in ops._user_combos], ["ok1"])
        self.assertTrue(any("跳过" in e["msg"] for e in self.log.recent(20, cats=["手柄"])))


class Review2Test(PadTestBase):
    """Counterexamples from the second review (padreview2 repro2.py Q1–Q8, repro3.py Q9)."""

    def feed(self, posture="policy", **kw):
        pol = kw.pop("pol", {})
        policies = None if pol is None else dict(POLICIES, **pol)
        b = kw.pop("bus", bus(kw.pop("torque_on", True), policy_enabled=posture in ("policy", "walking"), homed=True))
        self.robot_ok(posture=posture, policies=policies, bus=b, **kw)

    def test_q1_drive_off_then_late_move_is_dropped(self):
        """Turn off the web stick → stop(6) → a late move(5) from the thread pool: not sent, can't get the wheel back; only another drive on unlocks it."""
        self.feed()
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 4}, by="A", conn="a")
        self.ops.handle({"op": "drive", "on": False}, by="A", conn="a")
        self.ops.handle({"op": "stop", "seq": 6}, by="A", conn="a")
        n = len(self.robot.sent)
        self.assertIn("dropped", self.ops.handle({"op": "move", "vx": 0.2, "seq": 5}, by="A", conn="a"))
        self.assertIn("dropped", self.ops.handle({"op": "move", "vx": 0.2, "seq": 7}, by="A", conn="a"))
        self.assertEqual(len(self.robot.sent), n)
        snap = self.ops.snapshot(conn="a")["virtual"]
        self.assertIsNone(snap["driver"])
        self.assertIsNone(snap["owner"])
        self.ops.handle({"op": "watch"}, conn="a")              # an open page doesn't renew the wheel
        self.assertIsNone(self.ops.snapshot(conn="a")["virtual"]["driver"])
        self.ops.handle({"op": "drive", "on": True}, by="A", conn="a")
        self.assertEqual(self.ops.handle({"op": "move", "vx": 0.1, "seq": 8}, by="A", conn="a")["sent"][0], 0.1)

    def test_q2_disconnect_then_late_move_is_dropped(self):
        """Page disconnected: first mark_gone synchronously, then drop_client in the thread pool; late moves afterwards aren't sent, and other pages can open right away."""
        self.feed()
        self.assertTrue(self.ops.new_conn() != self.ops.new_conn())
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 7}, by="A", conn="a")
        self.assertTrue(self.ops.mark_gone("a"))
        self.assertIsNone(self.ops.snapshot()["virtual"]["driver"])      # released at the synchronous step
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "move", "vx": 0.25, "seq": 8}, by="A", conn="a")
        self.ops.drop_client("a", "A")
        self.assertEqual(self.robot.sent[-1], ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}))
        self.assertIn("dropped", self.ops._move({"vx": 0.25, "seq": 9}, "a", "A"))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "drive", "on": True}, by="A", conn="a")   # a disconnected page can never get it back
        self.assertEqual(self.ops.handle({"op": "move", "vx": 0.1, "seq": 1}, by="B", conn="b")["sent"][0], 0.1)

    def test_q3_walk_stop_from_any_page_and_while_busy(self):
        """"Stop (stand)" (「停下（站好）」) ignores the wheel and doesn't queue; one-shot commands don't take the wheel."""
        self.feed("holding")
        self.ops.handle({"op": "walk"}, by="手机 A", conn="a")
        self.assertIsNone(self.ops.snapshot()["virtual"]["driver"])
        self.feed("walking", applied=[0.0, 0.0, 0.0])
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 1}, by="手机 A", conn="a")     # A is pushing the stick
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "skill", "name": "kick_left"}, by="电脑 B", conn="b")
        gate = threading.Event()
        self.robot.replies["robot.do"] = lambda p: (gate.wait(1), {"accepted": True})[1]
        t = threading.Thread(target=self.ops.handle, args=({"op": "skill", "name": "kick_left"}, "手机 A", "a"))
        t.start()
        wait_until(lambda: self.ops.snapshot()["motion"]["busy"], what="技能在路上")
        self.ops.handle({"op": "walk_stop"}, by="电脑 B", conn="b")                    # another page, previous request not answered yet: still stops
        self.assertEqual(self.robot.methods()[-2:], ["robot.stop", "robot.enable"])
        gate.set()
        t.join()

    def test_q4_halt_does_not_eat_the_next_move(self):
        self.feed()
        self.ops.handle({"op": "move", "vx": 0.2, "seq": 1}, conn="a")
        self.ops.handle({"op": "stop", "seq": 2}, conn="a")
        self.ops._halt("点了停下", "a")
        self.assertEqual(self.ops.handle({"op": "move", "vx": 0.2, "seq": 3}, conn="a")["sent"][0], 0.2)

    def test_q5_relax_guard_covers_everything_and_all_sources(self):
        """Torque-release guard: the moment the top button is pressed (note_relax), gamepad Select / falling (readback torque on→off) all count; blocks walk / sit / skill / actions / sticks."""
        self.feed("policy")
        self.ops.note_relax("电脑")
        for args in ({"op": "sit"}, {"op": "skill", "name": "kick_left"}, {"op": "action_start", "id": "nod"},
                     {"op": "move", "vx": 0.1}):
            with self.subTest(op=args["op"]):
                with self.assertRaises(P.Refused) as cm:
                    self.ops.handle(args)
                self.assertIn("卸", str(cm.exception))
        self.ops.handle({"op": "sound", "tag": "chirp"})                 # a chirp doesn't move joints: still allowed
        time.sleep(FAST["relax_guard"] + 0.05)
        self.feed("holding")
        self.ops.handle({"op": "walk"})
        self.ops._relax_at = -1e9
        self.feed("holding")
        self.feed("limp", torque_on=False)                                # torque release not going through Studio (gamepad Select, falling)
        b = self.ops.snapshot()["motion"]["buttons"]
        self.assertFalse(b["stand"]["ok"])
        self.assertIn("卸", b["stand"]["why"])
        self.feed("holding")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "walk"})

    def test_q6_seated_and_limp_is_blocked_with_a_clear_reason(self):
        self.feed("sitting", torque_on=False, pol={"sitting": True, "enabled": False})
        self.ops._relax_at = -1e9
        b = self.ops.snapshot()["motion"]["buttons"]
        self.assertFalse(b["stand"]["ok"])
        self.assertIn("锁存", b["stand"]["why"])
        self.assertIn("站起来", b["walk"]["why"])
        self.assertEqual(b["sit"]["why"], "已经坐着了")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "stand"})
        self.assertNotIn("robot.do", self.robot.methods())
        self.assertNotIn("robot.init", self.robot.methods())

    def test_q7_relax_interrupts_combo_recenters_and_stops_calling(self):
        stop = threading.Event()

        def hold():
            while not stop.is_set():
                self.ops.handle({"op": "action_hold"}, conn="a")
                time.sleep(0.05)
        self.feed()
        self.ops.handle({"op": "action_start", "id": "happy"}, conn="a")     # chirp → mouth opens and closes → nod
        threading.Thread(target=hold, daemon=True).start()
        wait_until(lambda: any(m == "robot.mouth" for m, _ in self.robot.sent), what="在张嘴")
        self.ops.note_relax("电脑")
        n_calls = len(self.robot.calls)
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="打断")
        stop.set()
        self.assertIn("卸力", self.ops.snapshot()["motion"]["last_action"]["result"])
        self.assertEqual([m for m, _ in self.robot.calls[n_calls:] if m in ("robot.do", "robot.sound")], [])
        tail = {m: p for m, p in self.robot.sent[-2:]}
        self.assertEqual(tail.get("robot.mouth"), {"open": 0.0})
        self.assertEqual(tail.get("robot.head"), {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0})
        # skill combo: torque released after the first kick, while waiting: the second kick isn't sent
        self.ops._relax_at = -1e9
        time.sleep(0.05)
        self.feed()
        stop = threading.Event()
        threading.Thread(target=hold, daemon=True).start()
        self.ops.handle({"op": "action_start", "id": "kicks"}, conn="a")
        wait_until(lambda: ("robot.do", {"skill": "kick_left"}) in self.robot.calls, what="第一脚")
        self.ops.note_relax("电脑")
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="打断")
        stop.set()
        self.assertNotIn(("robot.do", {"skill": "kick_right"}), self.robot.calls)

    def test_q8_mirror_sends_nothing(self):
        self.watch()
        self.tap.attach(XBOX_DEV)
        self.feed()
        for args in ({"op": "move", "vx": 0.1, "seq": 1}, {"op": "action_start", "id": "nod"}, {"op": "drive", "on": True}):
            with self.assertRaises(P.Refused):
                self.ops.handle(args, by="A", conn="a")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "drive", "on": True, "force": True}, by="B", conn="b")
        self.ops.mark_gone("b")
        self.ops.drop_client("b", "B")
        self.ops.handle({"op": "stop", "seq": 2}, conn="a")
        self.assertEqual(self.robot.sent, [])

    def test_q9_stale_policies_disable_sit_and_stand(self):
        from studio.state import posture
        b = bus(True, policy_enabled=True, homed=True)
        self.robot_ok(posture=posture(True, b, None, {"move": {"applied": [0, 0, 0]}}), policies=None, bus=b)
        btn = self.ops.snapshot()["motion"]["buttons"]
        for k in ("sit", "stand"):
            self.assertFalse(btn[k]["ok"])
            self.assertIn("是不是坐着", btn[k]["why"])
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "sit"})
        b2 = bus(False)
        self.robot_ok(posture=posture(True, b2, None, None), policies=None, bus=b2)
        self.ops._relax_at = -1e9
        self.assertFalse(self.ops.snapshot()["motion"]["buttons"]["stand"]["ok"])
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "stand"})
        self.assertEqual([m for m in self.robot.methods() if m in ("robot.do", "robot.init")], [])

    def test_walk_waits_for_pairing_and_unknown_pad_is_said(self):
        self.feed("holding")
        self.ops.handle({"op": "scan", "seconds": 2})
        wait_until(lambda: self.steps().get("scan") == "doing", what="在搜索")
        self.assertIn("配对", self.ops.snapshot()["motion"]["buttons"]["walk"]["why"])
        self.ops.handle({"op": "cancel"})
        self.wait_wiz("failed")
        # configd unreadable and no permission to read keys: the page says "can't tell whether a physical gamepad is present"
        self.cfg.status_exc = Unreachable("/run/configd.sock 不在")
        self.watch()
        self.tap.on_state("denied", "没权限连 unix:/run/padd/pad.sock")
        self.ops._status_at = time.monotonic() - 30                      # the pad.status obtained during the earlier scan has also expired
        v = self.ops.snapshot()["virtual"]
        self.assertFalse(v["mirror"])
        self.assertIn("按键也读不到", v["pad_unknown"])

    def test_user_combo_with_roller_skill_follows_skill_rules(self):
        self.feed("policy")
        self.ops.handle({"op": "combo_save", "combo": {"id": "roll", "name": "滚起来", "steps": [{"do": "skill", "name": "roller_stand"}]}})
        row = next(c for c in self.ops.snapshot()["motion"]["combos"] if c["id"] == "roll")
        self.assertFalse(row["ok"])
        self.assertIn("轮滑", row["why"])
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "action_start", "id": "roll"})

    def test_safe_snapshot_and_masked_diag(self):
        self.bt.found = [{"mac": PRO, "name": "Pro Controller", "cls": 0x2508, "rssi": -50}]
        self.ops.handle({"op": "scan", "seconds": 0.1})
        self.wait_wiz("waiting")
        d = json.dumps(self.ops.diag(), ensure_ascii=False)
        self.assertNotIn(PRO, d)
        self.assertNotIn("Pro Controller", d)
        self.assertIn('"count": 1', d)
        with mock.patch.object(self.ops, "_motion_view", side_effect=ValueError("坏了")):
            self.assertIsNone(self.ops.safe_snapshot())
            self.assertIsNone(self.ops.safe_snapshot())
        errs = [e for e in self.log.recent(50, cats=["手柄"]) if "跳过这一帧" in e["msg"]]
        self.assertEqual(len(errs), 1)
        self.assertIs(self.ops.executor_for({"op": "move"}), self.ops._fast_pool)
        self.assertIsNone(self.ops.executor_for({"op": "pair"}))


HEAD0 = dict(D.HEAD_ZERO)
POSE_OFF = {"active": False}


class VpadTest(PadTestBase):
    """Round 3: the web gamepad picture itself can be pressed (pad-vpad-plan.md §8, review pad-vpad-review.md V1–V20)."""

    def feed(self, posture="policy", **kw):
        pol = kw.pop("pol", {})
        policies = None if pol is None else dict(POLICIES, **pol)
        b = kw.pop("bus", bus(kw.pop("torque_on", posture != "limp"), policy_enabled=posture in ("policy", "walking"),
                              homed=True))
        self.robot_ok(posture=posture, policies=policies, bus=b, **kw)

    def sent(self, method=None):
        with self.robot.lk:
            return [(m, p) for m, p in self.robot.sent if method is None or m == method]

    def poses(self):
        return [p for _, p in self.sent("robot.pose")]

    def heads(self):
        return [p for _, p in self.sent("robot.head")]

    def s(self):
        """The page's incrementing sequence number (one counter per page, same as nextSeq in pad.js)."""
        return next(self._n)

    def into(self, mode, conn="a", seq=None):
        return self.ops.handle({"op": "mode", "mode": mode, "seq": self.s() if seq is None else seq}, by="电脑 A", conn=conn)

    def stick(self, mode, conn="a", seq=None, **v):
        return self.ops.handle(dict({"op": "sticks", "mode": mode, "seq": self.s() if seq is None else seq,
                                     "lx": 0, "ly": 0, "rx": 0, "ry": 0}, **v), by="电脑 A", conn=conn)

    def stop(self, conn="a"):
        return self.ops.handle({"op": "stop", "seq": self.s()}, conn=conn)

    def body_latched(self, conn="a"):
        self.feed()
        self.into("body", conn)
        self.stick("body", conn, ly=1)
        self.assertEqual(self.poses()[-1]["active"], True)
        self.assertLess(self.poses()[-1]["z"], 0)

    def head_latched(self, conn="a"):
        self.feed()
        self.into("head", conn)
        self.stick("head", conn, lx=0.5)
        self.assertNotEqual(self.heads()[-1], HEAD0)

    def assert_no_empty_pose(self):
        # pitfall: PoseParams defaults to active:true (fork lib.rs:2320-2346), so sending {} actually turns body mode on; exit must always write active:false
        for p in self.poses():
            self.assertIn("active", p)

    # ---- Conversion (appendix 2) ----

    def test_formulas_follow_padd(self):
        lim = {"v": 0.3, "w": 1.5}
        m, p = D.sticks_to_intent("drive", 0, -1, 1, 0, lim, 2.5)        # left stick up, right stick right
        self.assertEqual((m, p), ("robot.move", {"vx": 0.3, "vy": 0.0, "vyaw": -1.5}))
        self.assertEqual(D.sticks_to_intent("drive", 1, 0, 0, 0, lim, 2.5)[1]["vy"], -0.3)   # push right = strafe right (vy negative)
        self.assertEqual(D.sticks_to_intent("drive", 0.05, 0.09, 0, 0, lim, 2.5)[1], {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
        m, p = D.sticks_to_intent("head", 0.5, -1, 0.5, -1, lim, 2.5)
        self.assertEqual(m, "robot.head")
        self.assertEqual(p, {"neck_pitch": 2.5, "head_pitch": -2.5, "head_yaw": -1.25, "head_roll": 1.25})
        m, p = D.sticks_to_intent("body", 0, -1, 1, -1, lim, 2.5)
        self.assertEqual(m, "robot.pose")
        self.assertEqual(p, {"z": 0.01, "roll": 0.26, "pitch": 0.26, "active": True})   # clamped to the training range ±0.26
        self.assertEqual(D.sticks_to_intent("body", 0, 1, 0, 0, lim, 2.5)[1]["z"], -0.025)  # pushing down crouches at most 2.5 cm

    # ---- V1: head / body latch, cleared on every exit path ----

    def test_v1_mode_exit_and_release(self):
        self.head_latched()
        self.stop()                                                           # release: head returns to center (still in head mode)
        self.assertEqual(self.heads()[-1], HEAD0)
        self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode"], "head")
        self.stick("head", ly=-1)
        self.into("drive")                                                    # press Y again: back to walking, head returns to center
        self.assertEqual(self.heads()[-1], HEAD0)
        self.into("body")
        self.stick("body", rx=1)
        self.stop()                                                           # release in body mode: back to center, still in body mode
        self.assertEqual(self.poses()[-1], dict(D.POSE_CENTER))
        self.into("drive")                                                    # exit: always active:false
        self.assertEqual(self.poses()[-1], POSE_OFF)
        self.assert_no_empty_pose()
        self.assertEqual(self.ops._latch, {"head": None, "body": None})

    def test_v1_leaving_page_and_disconnect(self):
        self.body_latched()
        self.ops.handle({"op": "drive", "on": False, "seq": self.s()}, conn="a")   # leave the gamepad page
        self.assertEqual(self.poses()[-1], POSE_OFF)
        self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode"], "drive")
        # disconnect: mark_gone is called synchronously in the event loop, only changes memory and sends nothing; drop_client (thread pool) sends
        self.ops.handle({"op": "drive", "open": True, "seq": self.s()}, conn="b")
        self.body_latched("b")
        n = len(self.sent())
        self.ops.mark_gone("b")
        self.assertEqual(len(self.sent()), n)
        self.ops.drop_client("b", "B")
        wait_until(lambda: self.poses()[-1] == POSE_OFF, what="断开后退出身体模式")
        self.assert_no_empty_pose()

    def test_v1_takeover_and_lease_timeout(self):
        self.body_latched("a")
        self.ops.handle({"op": "drive", "on": True, "force": True}, by="手机 B", conn="b")   # take over
        self.assertEqual(self.poses()[-1], POSE_OFF)
        # wheel idle for 6 s and another page pushes the stick: the head set by the original page is also cleared (round-3 V1 item 4)
        self.ops.handle({"op": "drive", "on": False}, conn="b")
        # watchdog (0.6 s return to center) and mode heartbeat timeout (3 s) set large: only the "wheel idle 6 s, someone else takes over" path may clear it (review R7)
        with mock.patch.object(D, "LEASE_S", 0.2), mock.patch.object(D, "STICK_STALE_S", 60), \
                mock.patch.object(D, "MODE_HB_S", 60):
            self.head_latched("c")
            time.sleep(0.25)
            self.stick("drive", conn="d", ly=-1)
            wait_until(lambda: self.heads()[-1] == HEAD0, timeout=1.0, what="换人后头回正")
            v = self.ops.snapshot(conn="c")["virtual"]
        self.assertEqual(v["mode"], "drive")
        self.assertIn("方向盘 6 秒没动静", v["mode_exit"]["why"])

    def test_v1_relax_sets_a_flag_then_clears_after_the_relax(self):
        """The torque-release entry is in the event loop: only sets a flag, sends nothing; the background thread sends 0.1 s later (queued after the release). Also cleared while mirroring."""
        self.body_latched()
        n = len(self.sent())
        t0 = time.monotonic()
        self.ops.note_relax("电脑")                                         # top release button, space bar, Select on the picture
        self.assertEqual(len(self.sent()), n)                               # nothing sent on the spot
        wait_until(lambda: self.poses()[-1] == POSE_OFF, what="卸力后退出身体模式")
        self.assertGreaterEqual(time.monotonic() - t0, D.RELAX_CLEAR_DELAY_S - 0.02)
        self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode_exit"]["why"], "卸力了")
        # readback sees torque on→off (gamepad Select, falling): cleared the same way
        self.ops._relax_at = -1e9
        self.feed()
        self.into("drive")                    # the page follows the backend back to walking (replies once; only then does the backend allow entering a mode again: review R3)
        # the pose stays "ready to walk", only torque changes from on to off; watchdog set large: only the "readback sees torque off" path may clear it (review R7)
        with mock.patch.object(D, "STICK_STALE_S", 60):
            self.head_latched()
            self.feed("policy", torque_on=False)
            wait_until(lambda: self.heads()[-1] == HEAD0, timeout=1.0, what="回读卸力后头回正")
        self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode_exit"]["why"], "卸力了（回读看到的）")

    def test_v1_pad_attached_clears_even_in_mirror(self):
        self.body_latched()
        self.watch()
        self.tap.attach(XBOX_DEV)                                           # the moment the physical gamepad connects
        wait_until(lambda: self.poses()[-1] == POSE_OFF, what="手柄连上后退出身体模式")
        self.assertTrue(self.ops.snapshot()["virtual"]["mirror"])
        with self.assertRaises(P.Refused):
            self.into("head")                                               # presses on the web page aren't accepted while mirroring
        # the configd path (no tap) counts too
        self.tap.on_report({"report": "detached", "why": "x"})
        self.into("drive")                    # the page follows the backend back to walking
        self.head_latched()
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        wait_until(lambda: self.heads()[-1] == HEAD0, what="configd 说手柄连着后头回正")

    def test_v1_walk_stop_and_start_stop_clear(self):
        self.body_latched()
        self.ops.handle({"op": "walk_stop"}, by="手机 B", conn="b")         # another page clicks "stop (stand)" (「停下（站好）」)
        self.assertEqual(self.poses()[-1], POSE_OFF)
        self.into("drive")                    # the page follows the backend back to walking
        self.head_latched()
        self.ops.handle({"op": "start", "expect": "walk_stop", "src": "svg"}, conn="a")   # Start on the picture (walking → stop)
        self.assertEqual(self.heads()[-1], HEAD0)

    def test_v1_leaving_driving_exits_mode(self):
        self.body_latched()
        self.feed("holding")                                                # policy stopped
        wait_until(lambda: self.poses()[-1] == POSE_OFF, what="策略停了退出身体模式")
        v = self.ops.snapshot(conn="a")["virtual"]
        self.assertEqual(v["mode"], "drive")
        self.assertIn("策略停了", v["mode_exit"]["why"])

    def test_v1_close_and_startup_reset(self):
        self.head_latched()
        self.ops.close()
        self.assertEqual(self.heads()[-1], HEAD0)
        # the first time Studio sees the main program running: send robot.pose {"active": false} once, only once (setUp already waited for and cleared it)
        robot = FakeRobot()
        ops = P.PadOps(self.log, robot=robot, waits=FAST, read_text=lambda p: self.toml, state_dir=self.tmp.name)
        try:
            self.assertEqual(robot.sent, [])
            ops.feed_robot({"present": True, "bus": bus(), "bus_at": time.monotonic()})
            wait_until(lambda: robot.sent == [("robot.pose", {"active": False})], what="连上时的复位")
            ops.feed_robot({"present": False})
            ops.feed_robot({"present": True, "bus": bus(), "bus_at": time.monotonic()})
            time.sleep(0.1)
            self.assertEqual(robot.sent, [("robot.pose", {"active": False})])
            self.assertTrue(any("连上主程序" in e["msg"] for e in self.log.recent(50, cats=["手柄"])))
        finally:
            ops.close()

    # ---- V5: entering/leaving the gamepad page carries sequence numbers; gone can never get it back; actions no longer bypass closed ----

    def test_v5_open_off_out_of_order_and_gone(self):
        self.feed()
        self.ops.handle({"op": "drive", "open": True, "seq": 11}, conn="a")   # left and came back: open(11) arrives first
        self.assertIn("dropped", self.ops.handle({"op": "drive", "on": False, "seq": 10}, conn="a"))   # off(10) arrives late: dropped
        self.assertIn("sent", self.stick("drive", seq=12, ly=-1))
        self.ops.handle({"op": "stop", "seq": 13}, conn="a")
        self.ops.handle({"op": "drive", "on": False, "seq": 21}, conn="a")    # came in and left again: off(21) arrives first
        self.assertIn("dropped", self.ops.handle({"op": "drive", "open": True, "seq": 20}, conn="a"))
        self.assertIn("dropped", self.stick("drive", seq=22, ly=-1))
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "action_start", "id": "mouth"}, conn="a")   # previously action=True could bypass closed
        self.assertIsNone(self.ops.snapshot()["virtual"]["driver"])           # open doesn't take the wheel
        self.ops.handle({"op": "drive", "open": True, "seq": 30}, conn="a")
        self.assertIsNone(self.ops.snapshot()["virtual"]["driver"])
        # a disconnected page can never get it back: open is rejected outright, later frames still dropped
        self.ops.mark_gone("a")
        self.ops.drop_client("a")
        with self.assertRaises(P.Refused):
            self.ops.handle({"op": "drive", "open": True, "seq": 40}, conn="a")
        self.assertIn("dropped", self.ops._sticks({"mode": "drive", "seq": 41, "ly": -1}, "a", "A"))
        self.assertIn("dropped", self.ops._move({"vx": 0.2, "seq": 42}, "a", "A"))

    # ---- V6: separate channels, shared barrier, the backend decides the mode ----

    def test_v6_channels_are_separate_barrier_is_shared(self):
        self.feed()
        self.into("head", seq=1)
        self.assertIn("sent", self.stick("head", seq=5, ry=-1))
        self.assertEqual(self.heads()[-1]["neck_pitch"], 2.5)               # the right stick's y came through
        # the old move channel isn't used in head mode either (review R6, round-3 V6: no velocity sent when not in walk mode)
        self.assertIn("dropped", self.ops.handle({"op": "move", "vx": 0.1, "seq": 6}, conn="a"))
        self.ops.handle({"op": "stop", "seq": 9}, conn="a")
        self.assertIn("dropped", self.stick("head", seq=8, ry=-1))           # shared barrier: everything before stop is void
        # mode mismatch: drop it and tell the page what the backend's mode is now
        r = self.stick("drive", seq=10, ly=-1)
        self.assertEqual((r["mode"], "dropped" in r), ("head", True))
        self.assertFalse(any(p["vx"] for _, p in self.sent("robot.move")))
        # separate channels (checked in walk mode): right after a head frame, the next walk frame doesn't wait 40 ms and isn't judged "superseded by a newer one"
        self.stick("head", seq=11, ry=-1)
        self.into("drive", seq=12)
        r = self.stick("drive", seq=13, ly=-1)
        self.assertEqual((r["sent"][0], r["merged"]), (0.3, False))
        self.assertEqual(self.ops._seq_of("a")["sent"], {"head": 11, "move": 13})

    def test_v6_entering_mode_while_walking_stops_first(self):
        self.feed()
        self.stick("drive", seq=1, ly=-1)
        self.assertEqual(self.sent("robot.move")[-1][1]["vx"], 0.3)
        self.into("head", seq=2)
        self.assertEqual(self.sent("robot.move")[-1][1], {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})

    # ---- V7: Start ----

    def test_v7_start_picks_by_posture_with_expect(self):
        cases = (("limp", {}, "stand", ("robot.init", {})),
                 ("holding", {}, "walk", ("robot.enable", {"on": True, "toggle": False})),
                 ("sitting", {"sitting": True}, "stand", ("robot.do", {"skill": "sit_toggle"})))
        for posture, pol, expect, call in cases:
            with self.subTest(posture=posture):
                b = bus(posture != "limp", policy_enabled=posture == "sitting", homed=True)
                self.robot_ok(posture=posture, policies=dict(POLICIES, **pol), bus=b)
                self.ops._relax_at = -1e9
                self.assertEqual(self.ops.snapshot()["motion"]["start"]["op"], expect)
                r = self.ops.handle({"op": "start", "expect": expect, "src": "svg"}, by="电脑", conn="a")
                self.assertEqual(r["did"], expect)
                # walk reads back busStatus a few more times to confirm the policy started; don't use calls[-1]
                self.assertIn(call, [c for c in self.robot.calls if c[0] != "robot.busStatus"])
        self.feed("policy")
        self.ops.handle({"op": "start", "expect": "walk_stop"}, conn="a")
        self.assertEqual(self.robot.methods()[-2:], ["robot.stop", "robot.enable"])
        # state changed in flight: the page thinks "start walking", the backend decides "stop" → reject, send nothing
        n = len(self.robot.calls)
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "start", "expect": "walk"}, conn="a")
        self.assertIn("状态刚变了", str(cm.exception))
        self.assertEqual(len(self.robot.calls), n)
        # can't read whether it's sitting: reject (second review S2)
        self.feed("holding", pol=None)
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "start", "expect": "walk"}, conn="a")
        self.assertIn("坐着", str(cm.exception))
        self.assertTrue(any("网页手柄 Start → " in e["msg"] for e in self.log.recent(80, cats=["手柄"])))

    def test_v7_start_waits_until_joints_settle(self):
        """Homed, but the actual joint positions haven't reached HOME yet: Start / start walking must not show as pressable yet."""
        guard = {"ready": False, "reason": "关节还没到 HOME", "max_joint_error_deg": 12.3,
                 "joint_tolerance_deg": 5.0, "stable_samples": 1, "tilt_deg": 2.0, "tilt_tolerance_deg": 10.0}
        self.feed("homing", bus=bus(homed=True, home_start_guard=guard))
        mv = self.ops.snapshot()["motion"]
        self.assertEqual(mv["posture"], "homing")
        self.assertFalse(mv["start"]["ok"])
        self.assertEqual(mv["start"]["label"], "站起来")
        self.assertEqual(mv["start"]["why"], "还在站起来，站稳了再点（关节还没到 HOME）")      # includes the reason given by the main program
        self.assertEqual(mv["buttons"]["walk"]["why"], "还在站起来，站稳了再点（关节还没到 HOME）")

    # ---- V4: held keys ----

    def keep(self, held, stop, conn="a", every=0.1):
        while not stop.is_set():
            self.ops.handle({"op": "keys", "held": held, "seq": next(self._kseq)}, conn=conn)
            self.feed()
            time.sleep(every)

    def setUp(self):
        super().setUp()
        self._kseq = itertools.count(100)
        self._n = itertools.count(1000)

    def test_v4_x_hold_keeps_rolling_then_times_out(self):
        self.feed()
        self.ops.handle({"op": "keys", "held": ["x"], "down": ["x"], "seq": 1}, conn="a")
        self.ops.handle({"op": "key", "key": "x", "src": "svg"}, conn="a")          # the moment of pressing: a request, gets the rejection reason
        self.assertEqual(self.robot.calls[-1], ("robot.do", {"skill": "roulade"}))
        stop = threading.Event()
        threading.Thread(target=self.keep, args=(["x"], stop), daemon=True).start()
        time.sleep(0.5)
        stop.set()
        n_do = len(self.sent("robot.do"))
        self.assertGreaterEqual(n_do, 6)                                             # a notification every 40 ms
        self.assertTrue(all(p == {"skill": "roulade"} for _, p in self.sent("robot.do")))
        time.sleep(D.X_HOLD_S + 0.2)                                                 # page stops reporting: stops within 0.3 s
        n = len(self.sent("robot.do"))
        time.sleep(0.2)
        self.assertEqual(len(self.sent("robot.do")), n)
        self.assertLessEqual(n - n_do, 10)

    def test_v4_lt_wheee_and_mouth_end_cleanly(self):
        self.feed()
        self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": 1}, conn="a")
        stop = threading.Event()
        threading.Thread(target=self.keep, args=(["lt"], stop), daemon=True).start()
        time.sleep(0.4)
        stop.set()
        time.sleep(0.15)
        self.ops.handle({"op": "keys", "held": [], "seq": 9999}, conn="a")          # release
        wait_until(lambda: self.sent("robot.mouth")[-1][1] == {"open": 0.0}, what="合嘴")
        sounds = [p for _, p in self.sent("robot.sound")]
        self.assertGreater(sounds.count({"tag": "wheee", "hold": True}), 5)
        self.assertEqual(sounds[-1], {"tag": "wheee", "hold": False})                # the end sends hold:false
        self.assertIn({"open": 1.0}, [p for _, p in self.sent("robot.mouth")])
        # the log only records press and release, not each tick (round-3 V19)
        lines = [e for e in self.log.recent(200, cats=["手柄"]) if "网页手柄 LT" in e["msg"]]
        self.assertEqual(len(lines), 2)

    def test_v4_rt_chirps_once_and_holding_still_works(self):
        """RT: a quack on press (a notification, doesn't occupy "previous request not answered yet"); the mouth follows fork's rules and can also be pressed while standing and holding (round-3 V10)."""
        self.feed("holding")
        self.ops.handle({"op": "keys", "held": ["rt"], "down": ["rt"], "seq": 1}, conn="a")
        stop = threading.Event()
        threading.Thread(target=self.keep, args=(["rt"], stop), daemon=True).start()
        time.sleep(0.3)
        stop.set()
        self.assertEqual([p for _, p in self.sent("robot.sound")], [{"tag": "chirp"}])
        self.assertNotIn("robot.sound", self.robot.methods())                        # it's a notification, not a request
        wait_until(lambda: self.sent("robot.mouth")[-1][1] == {"open": 0.0}, what="0.45 秒没报：合嘴")

    def test_v4_relax_ends_keys_and_heartbeat_does_not_revive(self):
        self.feed()
        self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": 1}, conn="a")
        wait_until(lambda: self.sent("robot.mouth"), what="张嘴")
        self.ops.note_relax("电脑")
        wait_until(lambda: self.sent("robot.mouth")[-1][1] == {"open": 0.0}, what="卸力后合嘴")
        wait_until(lambda: self.sent("robot.sound")[-1][1] == {"tag": "wheee", "hold": False}, what="wheee 停")
        r = self.ops.handle({"op": "keys", "held": ["lt"], "seq": 2}, conn="a")    # the page's heartbeat is still reporting: not renewed
        self.assertEqual((r["held"], r["ended"]), ([], ["lt"]))
        n = len(self.sent())
        time.sleep(0.15)
        self.assertEqual(len(self.sent()), n)

    def test_v4_mouth_actions_and_triggers_are_exclusive(self):
        self.feed()
        stop = threading.Event()

        def hold():
            while not stop.is_set():
                self.ops.handle({"op": "action_hold"}, conn="a")
                time.sleep(0.05)
        self.ops.handle({"op": "action_start", "id": "mouth"}, conn="a")
        threading.Thread(target=hold, daemon=True).start()
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "keys", "held": ["rt"], "down": ["rt"], "seq": 1}, conn="a")
        self.assertIn("张嘴", str(cm.exception))
        stop.set()
        self.ops.handle({"op": "action_stop"}, conn="a")
        wait_until(lambda: self.ops.snapshot()["motion"]["running"] is None, what="动作停了")
        self.ops.handle({"op": "keys", "held": ["rt"], "down": ["rt"], "seq": 2}, conn="a")
        acts = {a["id"]: a for a in self.ops.snapshot()["motion"]["actions"]}
        self.assertIn("LT / RT", acts["mouth"]["why"])

    # ---- V9: head / mouth range read from padd's config; V18: padd's --config ----

    def test_v9_v18_inputs_from_padd_unit(self):
        unit = ("[Service]\nExecStart=\nExecStart=/usr/bin/python3 /opt/robot/feetech-ft5-r5/startup_gate.py --timeout 60 --exec "
                "/opt/robot/feetech-ft5-r5/padd --socket /run/robotd.sock --config /etc/robot/feetech-ft5/robotd.toml "
                "--max-head 2.5 --input-settings /etc/robot/feetech-ft5/pad-settings.json\n")
        files = {D.PADD_UNIT: unit, "/etc/robot/feetech-ft5/pad-settings.json": '{"mouth_percent":60,"head_rad":0.5}',
                 "/etc/robot/feetech-ft5/robotd.toml": "[netpad]\nenabled = false\n[pad_imu_head_control]\nenabled = true\n"}

        def read(p):
            if p in files:
                return files[p]
            raise FileNotFoundError(p)
        self.ops.read_text = read
        self.ops._refresh_files()
        v = self.ops.snapshot()["virtual"]
        self.assertEqual((v["inputs"]["head"], v["inputs"]["mouth"]), (0.5, 60.0))
        self.assertTrue(v["pad_imu_head"])
        self.assertFalse(self.ops.snapshot()["status"]["netpad"])          # [netpad] is also read from padd's --config
        self.feed()
        self.into("head")
        self.stick("head", lx=-1)
        self.assertEqual(self.heads()[-1]["head_yaw"], 0.5)
        with self.assertRaises(P.Refused) as cm:                            # the wheel is in a's hands (taken by that head frame): b can't press
            self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": 3}, by="手机 B", conn="b")
        self.assertIn("接管", str(cm.exception))
        self.into("drive")
        # a settings file padd doesn't accept: keep --max-head, mouth 100% (input_settings.rs:75-78)
        files["/etc/robot/feetech-ft5/pad-settings.json"] = '{"mouth_percent":120,"head_rad":0.5}'
        self.ops._refresh_files()
        inp = self.ops.snapshot()["virtual"]["inputs"]
        self.assertEqual((inp["head"], inp["mouth"]), (2.5, 100.0))
        self.assertIn("不认", inp["src"])

    # ---- V11: watchdog ----

    def test_v11_stale_frame_recenters_and_mode_heartbeat_exits(self):
        with mock.patch.object(D, "STICK_STALE_S", 0.2), mock.patch.object(D, "MODE_HB_S", 0.5):
            self.head_latched()
            wait_until(lambda: self.heads()[-1] == HEAD0, timeout=1.0, what="0.2 秒没新帧：头回正")
            self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode"], "head")   # mode is still there
            self.into("drive")
            self.into("body")
            self.stick("body", ly=-1)
            wait_until(lambda: self.poses()[-1] == dict(D.POSE_CENTER), timeout=1.0, what="身体回中")
            wait_until(lambda: self.poses()[-1] == POSE_OFF, timeout=1.5, what="模式心跳超时：退出身体模式")
        self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode"], "drive")
        self.assertTrue(any("没报还在" in e["msg"] for e in self.log.recent(50, cats=["安全"])))

    # ---- V12: head / body frames dropped when the policy isn't running; mode can still be switched ----

    def test_v12_frames_dropped_when_not_driving(self):
        self.feed("holding")
        r = self.into("head")
        self.assertIn("策略没在跑", r["note"])
        r = self.stick("head", lx=1)
        self.assertIn("策略没在跑", r["dropped"])
        self.assertEqual(self.heads(), [])

    # ---- V13: 4 workers in the fast thread pool; watch doesn't wait for pad.bindings in the fast pool ----

    def test_v13_watch_does_not_wait_for_bindings(self):
        self.assertEqual(self.ops._fast_pool._max_workers, 4)
        self.robot.replies["pad.bindings"] = lambda p: (time.sleep(1.0), {"bindings": []})[1]
        t0 = time.monotonic()
        self.ops.handle({"op": "watch"}, conn="a")
        self.assertLess(time.monotonic() - t0, 0.3)
        wait_until(lambda: "pad.bindings" in self.robot.methods(), what="看守线程去拉了")

    # ---- V14: bindings refresh, how they're used ----

    def test_v14_bindings_refresh_and_rules(self):
        self.ops.w["bindings"] = 0.1
        rows = [{"button": "a", "skill": "sit_toggle", "overridden": True}, {"button": "x", "skill": "", "overridden": True},
                {"button": "lb", "skill": "moonwalk", "overridden": True, "error": "no skill named moonwalk"},
                {"button": "rb", "skill": "kick_right", "overridden": False},
                {"button": "dpad_down", "skill": "sit_toggle", "overridden": False}]
        self.robot.replies["pad.bindings"] = {"bindings": rows}
        self.watch()
        wait_until(lambda: [m for m in self.robot.methods() if m == "pad.bindings"].__len__() >= 2, what="10 秒（测试里 0.1 秒）刷新")
        self.feed()
        keys = self.ops.snapshot()["motion"]["keys"]
        self.assertEqual((keys["a"]["op"], keys["a"]["does"]), ("sit", "坐下"))      # bound to sit_toggle: depending on whether it's sitting, it does sit down / stand up
        self.assertIn("关掉", keys["x"]["why"])
        self.assertIn("moonwalk", keys["lb"]["why"])
        self.ops.handle({"op": "key", "key": "a", "src": "svg"}, conn="a")
        self.assertIn(("robot.do", {"skill": "sit_toggle"}), self.robot.calls)
        for k, word in (("x", "关掉"), ("lb", "moonwalk")):
            with self.assertRaises(P.Refused) as cm:
                self.ops.handle({"op": "key", "key": k, "src": "svg"}, conn="a")
            self.assertIn(word, str(cm.exception))
        self.feed("policy", pol={"sitting": True})
        self.assertEqual(self.ops.snapshot()["motion"]["keys"]["dpad_down"]["op"], "stand")
        self.feed("policy", pol=None)
        self.assertIn("是不是坐着", self.ops.snapshot()["motion"]["keys"]["dpad_down"]["why"])

    # ---- V15: sounds don't occupy "previous request not answered yet" ----

    def test_v15_sound_does_not_take_busy(self):
        self.feed("limp")
        self.ops._relax_at = -1e9
        gate = threading.Event()
        self.robot.replies["robot.init"] = lambda p: (gate.wait(1), {"accepted": True})[1]
        t = threading.Thread(target=self.ops.handle, args=({"op": "stand"},))
        t.start()
        wait_until(lambda: self.ops.snapshot()["motion"]["busy"], what="站起来在路上")
        self.ops.handle({"op": "sound", "tag": "chirp"})
        self.assertTrue(self.ops.snapshot()["motion"]["busy"])
        gate.set()
        t.join()
        self.assertFalse(self.ops.snapshot()["motion"]["busy"])

    # ---- V16: physical gamepad connected, the backend also rejects presses on the picture ----

    def test_v16_svg_keys_refused_in_mirror(self):
        self.feed()
        self.watch()
        self.tap.attach(XBOX_DEV)
        for args in ({"op": "key", "key": "a", "src": "svg"}, {"op": "start", "expect": "walk_stop", "src": "svg"},
                     {"op": "keys", "held": ["lt"], "down": ["lt"]}, {"op": "mode", "mode": "head"},
                     {"op": "sticks", "mode": "drive", "ly": -1}):
            with self.subTest(op=args["op"]):
                with self.assertRaises(P.Refused) as cm:
                    self.ops.handle(args, conn="a")
                self.assertIn("实体手柄", str(cm.exception))
        self.ops.handle({"op": "skill", "name": "kick_left"}, conn="a")   # the big buttons below work as usual (no src)
        self.assertEqual(self.sent(), [])

    # ---- D-pad right / D-pad up: follow official (decided by user Oct 19) ----

    def test_dpad_right_reboots_every_servo_like_official(self):
        """One press sends robot.rebootMotors {"ids":[]} (empty = all); once accepted, record a torque release: no torque enable for 2 s, head returns to center."""
        self.robot.replies["robot.rebootMotors"] = {"accepted": True}
        self.head_latched()
        self.assertTrue(self.ops.snapshot()["motion"]["reboot"]["ok"])
        r = self.ops.handle({"op": "reboot", "src": "svg"}, by="电脑 A", conn="a")
        self.assertEqual(r["did"], "reboot")
        self.assertIn(("robot.rebootMotors", {"ids": []}), self.robot.calls)
        self.assertIn("刚卸了力", self.ops.snapshot()["motion"]["buttons"]["stand"]["why"])
        wait_until(lambda: self.heads() and self.heads()[-1] == HEAD0, what="重启舵机以后头回正")

    def test_dpad_right_works_after_relax_and_while_another_page_drives(self):
        """The rescue path: can be pressed after torque release (that's exactly the official "release, then press" scenario) and while another page holds the wheel."""
        self.robot.replies["robot.rebootMotors"] = {"accepted": True}
        self.feed()
        self.stick("drive", conn="b", ly=-1)                                  # B is pushing the stick
        self.relax_pressed()
        self.ops.handle({"op": "reboot", "src": "svg"}, by="电脑 A", conn="a")
        self.assertEqual([m for m in self.robot.methods() if m == "robot.rebootMotors"], ["robot.rebootMotors"])

    def test_dpad_right_refused_in_servo_session_and_mirror(self):
        self.robot.replies["robot.rebootMotors"] = {"accepted": True}
        self.feed(paused={"by": "舵机页"})
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "reboot", "src": "svg"}, conn="a")
        self.assertIn("调舵机", str(cm.exception))
        self.feed()
        self.watch()
        self.tap.attach(XBOX_DEV)
        for op in ({"op": "reboot", "src": "svg"}, {"op": "drive_mode", "expect": "roller", "src": "svg"}):
            with self.subTest(op=op["op"]):
                with self.assertRaises(P.Refused) as cm:
                    self.ops.handle(op, conn="a")
                self.assertIn("实体手柄", str(cm.exception))
        self.assertNotIn("robot.rebootMotors", self.robot.methods())
        self.assertNotIn("robot.setMode", self.robot.methods())

    def test_dpad_up_switches_walk_and_roller(self):
        """The page only sends after a 3 s hold; the backend picks the target mode from robot.policies' mode and rejects if it differs from expect."""
        self.robot.replies["robot.setMode"] = {"accepted": True}
        self.feed()
        dm = self.ops.snapshot()["motion"]["drive_mode"]
        self.assertEqual((dm["ok"], dm["current"], dm["target"]), (True, "walk", "roller"))
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "drive_mode", "expect": "walk", "src": "svg"}, conn="a")
        self.assertIn("状态刚变了", str(cm.exception))
        self.assertNotIn("robot.setMode", self.robot.methods())
        r = self.ops.handle({"op": "drive_mode", "expect": "roller", "src": "svg"}, conn="a")
        self.assertEqual((r["did"], r["target"]), ("drive_mode", "roller"))
        self.assertEqual(self.robot.calls[-1], ("robot.setMode", {"mode": "roller"}))
        self.feed(pol={"mode": "roller"})
        self.assertEqual(self.ops.snapshot()["motion"]["drive_mode"]["target"], "walk")
        self.robot.replies["robot.setMode"] = {"accepted": True, "reason": "mode already selected"}
        r = self.ops.handle({"op": "drive_mode", "expect": "walk", "src": "svg"}, conn="a")
        self.assertEqual(r["reason"], "已经是走路了")
        self.assertFalse(self.ops.snapshot()["motion"]["busy"])

    def test_dpad_up_refusals(self):
        self.feed()
        self.robot.replies["robot.setMode"] = {"accepted": False,
                                               "reason": "roller ONNX models are not installed; original walking policy unchanged"}
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "drive_mode", "expect": "roller", "src": "svg"}, conn="a")
        self.assertIn("没装轮滑模型", str(cm.exception))
        self.assertFalse(self.ops.snapshot()["motion"]["busy"])
        self.stick("drive", conn="b", ly=-1)                                  # B is pushing the stick: switching mode (which returns to the standing pose) has to wait for it
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "drive_mode", "expect": "roller", "src": "svg"}, conn="a")
        self.assertIn("正在推摇杆", str(cm.exception))
        self.feed(pol=None)
        dm = self.ops.snapshot()["motion"]["drive_mode"]
        self.assertFalse(dm["ok"])
        self.assertIn("走路还是轮滑", dm["why"])
        self.relax_pressed()
        self.assertIn("刚卸了力", self.ops.snapshot()["motion"]["drive_mode"]["why"])


class CodeReviewTest(PadTestBase):
    """Counterexamples for R1–R10 of the third code review (vpad-codereview.md). Helpers borrowed from VpadTest (not inherited, so its tests don't run again)."""
    feed, sent, poses, heads, s = VpadTest.feed, VpadTest.sent, VpadTest.poses, VpadTest.heads, VpadTest.s
    into, stick, body_latched, head_latched = VpadTest.into, VpadTest.stick, VpadTest.body_latched, VpadTest.head_latched
    assert_no_empty_pose = VpadTest.assert_no_empty_pose

    def setUp(self):
        super().setUp()
        self._n = itertools.count(1000)

    def first_body_frame_in_flight(self, exit_fn):
        """R1: the first body-mode frame gets stuck on robotd's socket (_latch is still None at that point) while another thread takes an exit path."""
        self.feed()
        self.into("body")
        gate, entered = threading.Event(), threading.Event()
        orig = self.robot.notify

        def slow(method, params):
            if method == "robot.pose" and params.get("active") is True and params.get("z") and not gate.is_set():
                entered.set()
                gate.wait(2)
            return orig(method, params)
        self.robot.notify = slow
        t1 = threading.Thread(target=lambda: self.stick("body", ly=1))
        t1.start()
        self.assertTrue(entered.wait(2))
        t2 = threading.Thread(target=exit_fn)
        t2.start()
        time.sleep(0.15)
        gate.set()
        t1.join(3)
        t2.join(3)
        wait_until(lambda: self.poses()[-1] == POSE_OFF, timeout=1.5, what="退出以后身体模式要关上（不能留着 active:true）")
        time.sleep(0.7)                       # watchdog is 0.6 s: it must not turn it back on
        self.assertEqual(self.poses()[-1], POSE_OFF)
        self.assertIsNone(self.ops._latch["body"])
        self.assert_no_empty_pose()

    def test_r1_first_body_frame_in_flight_then_leave_page(self):
        self.first_body_frame_in_flight(lambda: self.ops.handle({"op": "drive", "on": False, "seq": self.s()}, conn="a"))

    def test_r1_first_body_frame_in_flight_then_disconnect(self):
        self.first_body_frame_in_flight(lambda: (self.ops.mark_gone("a"), self.ops.drop_client("a", "A")))

    def test_r1_first_body_frame_in_flight_then_b_again(self):
        self.first_body_frame_in_flight(lambda: self.into("drive"))

    def test_r2_watchdog_center_cannot_reopen_after_exit(self):
        """R2: the watchdog has queued "return to center (active:true)" but hasn't got the send lock yet when the exit path sends active:false first."""
        with mock.patch.object(D, "STICK_STALE_S", 0.3):
            self.body_latched()
            real = self.ops._send_lk
            armed = threading.Event()

            class Late:
                """Only make the background thread 80 ms slow to get the send lock (thread switched out, lock held by someone else); other threads as usual."""
                def __enter__(s):
                    if threading.current_thread().name == "pad-tick" and armed.is_set():
                        time.sleep(0.08)
                    real.acquire()
                    return s

                def __exit__(s, *a):
                    real.release()
            self.ops._send_lk = Late()
            armed.set()
            time.sleep(0.45)                  # the watchdog should act now (no frame for 0.3 s)
            self.ops.handle({"op": "drive", "on": False, "seq": self.s()}, conn="a")
            time.sleep(0.4)
            armed.clear()
        self.assertEqual(self.poses()[-1], POSE_OFF)
        self.assertEqual(self.ops._latch, {"head": None, "body": None})

    def test_r3_heartbeat_and_stale_enter_do_not_reopen(self):
        self.head_latched()
        self.ops.note_relax("电脑")                                      # the backend exits head mode on behalf of the page
        wait_until(lambda: self.ops.snapshot(conn="a")["virtual"]["mode"] == "drive", what="退出")
        self.ops._relax_at = -1e9
        self.feed()
        r = self.ops.handle({"op": "mode", "mode": "head", "hb": True}, conn="a")   # the page hasn't caught up: heartbeat reports "still in head mode"
        self.assertEqual(r["mode"], "drive")
        self.assertIn("卸力了", r["dropped"])
        r = self.into("head")                                             # an "enter head mode" that hasn't caught up with the snapshot isn't accepted either
        self.assertEqual((r["mode"], "dropped" in r), ("drive", True))
        self.assertEqual(self.ops.snapshot(conn="a")["virtual"]["mode"], "drive")
        self.into("drive")                                                # the page follows back to walking (replies once)
        self.assertEqual(self.into("head")["mode"], "head")              # after that, pressing Y again enters it
        r = self.ops.handle({"op": "mode", "mode": "head", "hb": True}, conn="a")
        self.assertEqual(r, {"mode": "head"})                             # same: only renews "still there"

    def test_r4_late_press_after_release_is_dropped(self):
        self.feed()
        self.ops.handle({"op": "keys", "held": [], "seq": 6}, conn="a")                   # release (6) arrives first
        r = self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": 5}, conn="a")   # press (5) arrives late
        self.assertIn("dropped", r)
        time.sleep(0.15)
        self.assertEqual(self.sent("robot.mouth"), [])

    def test_r5_stale_x_arm_does_not_roll_after_refused_x(self):
        self.feed()
        gate = threading.Event()
        self.robot.replies["robot.do"] = lambda p: (gate.wait(2), {"accepted": True})[1]
        self.ops.handle({"op": "keys", "held": ["x"], "down": ["x"], "seq": 1}, conn="a")
        t = threading.Thread(target=lambda: self.ops.handle({"op": "key", "key": "x", "src": "svg"}, conn="a"))
        t.start()
        time.sleep(0.05)
        self.ops.handle({"op": "keys", "held": [], "seq": 2}, conn="a")                   # a quick tap: release first
        gate.set()
        t.join(3)                                                                            # the request only answers now
        gate2 = threading.Event()
        self.robot.replies["robot.do"] = lambda p: (gate2.wait(2), {"accepted": True})[1]
        ta = threading.Thread(target=lambda: self.ops.handle({"op": "key", "key": "a", "src": "svg"}, conn="a"))
        ta.start()
        wait_until(lambda: self.ops._cmd_busy, what="A 在路上")
        with self.robot.lk:
            self.robot.sent.clear()
        self.ops.handle({"op": "keys", "held": ["x"], "down": ["x"], "seq": 3}, conn="a")
        with self.assertRaises(P.Refused):                                                  # this X is rejected (previous request not answered yet)
            self.ops.handle({"op": "key", "key": "x", "src": "svg"}, conn="a")
        time.sleep(0.15)
        dos = self.sent("robot.do")
        gate2.set()
        ta.join(3)
        self.assertEqual(dos, [], "X 被拒了，不能拿上一下 X 的 arm 连滚（roulade 能抢断正在做的低头捡）")

    def test_r6_drive_frame_never_goes_out_in_head_mode(self):
        self.feed()
        real = D.sticks_to_intent
        fired = []

        def hook(mode, *a):
            if mode == "drive" and not fired:     # _sticks has just checked the mode (walk) and released the lock: another thread switches to head mode
                fired.append(1)
                self.ops.handle({"op": "mode", "mode": "head", "seq": 20}, conn="a")
            return real(mode, *a)
        with mock.patch.object(D, "sticks_to_intent", hook):
            r = self.stick("drive", seq=19, ly=-1)
        self.assertIn("dropped", r)
        self.assertFalse(any(p["vx"] for _, p in self.sent("robot.move")))
        self.into("head", seq=21)
        self.assertIn("dropped", self.ops.handle({"op": "move", "vx": 0.2, "seq": 22}, conn="a"))   # the old move channel is also checked against walk mode

    def test_r7_x_release_stops_rolling_at_once(self):
        """Releasing while X is held: the notification stops on that tick (not relying on the 0.3 s heartbeat timeout)."""
        self.feed()
        self.ops.handle({"op": "keys", "held": ["x"], "down": ["x"], "seq": 1}, conn="a")
        self.ops.handle({"op": "key", "key": "x", "src": "svg"}, conn="a")
        wait_until(lambda: len(self.sent("robot.do")) >= 3, timeout=1.0, what="在连滚")
        self.ops.handle({"op": "keys", "held": [], "seq": 2}, conn="a")
        time.sleep(0.08)                      # at most one more tick in flight
        n = len(self.sent("robot.do"))
        time.sleep(0.2)                       # still within the 0.3 s heartbeat timeout: it stopped because of the release
        self.assertEqual(len(self.sent("robot.do")), n)

    def test_r8_close_waits_for_the_tick_thread(self):
        self.feed()
        self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": 1}, conn="a")
        wait_until(lambda: self.sent("robot.mouth"), what="张嘴")
        self.ops.close()
        self.assertFalse(self.ops._tick_thread.is_alive())
        time.sleep(0.1)
        self.assertEqual(self.sent("robot.mouth")[-1][1], {"open": 0.0})                 # closing the mouth is the last message
        self.assertEqual(self.sent("robot.sound")[-1][1], {"tag": "wheee", "hold": False})

    def test_r9_mode_exit_does_not_grow(self):
        self.head_latched()
        self.ops.note_relax("电脑")
        self.assertIn("a", self.ops._mode_exit)
        self.ops.mark_gone("a")
        self.assertNotIn("a", self.ops._mode_exit)                      # page disconnected: deleted
        self.ops._mode_exit["old"] = {"why": "x", "at": time.monotonic() - 20}
        self.ops._request_clear(None, "y")
        self.assertNotIn("old", self.ops._mode_exit)                    # older than 10 s: deleted

    def test_r10_input_settings_like_padd(self):
        files = {D.PADD_UNIT: "ExecStart=/x/padd --max-head 1.0 --input-settings /s.json\n",
                 "/s.json": '{"mouth_percent": 60, "head_rad": 0.5, "extra": 1}'}

        def read(p):
            if p in files:
                return files[p]
            raise FileNotFoundError(p)
        self.ops.read_text = read
        self.ops._refresh_files()
        inp = self.ops.snapshot()["virtual"]["inputs"]
        self.assertEqual((inp["head"], inp["mouth"]), (1.0, 100.0))    # one extra field: padd rejects the whole file, uses --max-head and mouth 100%
        self.assertIn("不认", inp["src"])
        # the ack written by padd itself: the numbers it's using (the padd that wrote the ack is still alive and the file matches)
        files[D.PADD_INPUT_ACK] = json.dumps({"pid": 4242, "path": "/s.json", "settings": {"mouth_percent": 30, "head_rad": 2.5}})
        self.ops.exists = lambda p: p == "/proc/4242"
        self.ops._refresh_files()
        inp = self.ops.snapshot()["virtual"]["inputs"]
        self.assertEqual((inp["head"], inp["mouth"]), (2.5, 30.0))
        self.assertIn("回执", inp["src"])
        self.ops.exists = lambda p: False                                # the padd that wrote the ack is gone: doesn't count
        self.ops._refresh_files()
        self.assertEqual(self.ops.snapshot()["virtual"]["inputs"]["head"], 1.0)


class ComboTest(unittest.TestCase):
    def test_shapes_and_text(self):
        self.assertAlmostEqual(C.head_at({"do": "nod", "times": 1}, C.NOD_PERIOD_S / 4)[1], C.NOD_AMP, places=3)
        self.assertEqual(C.head_at({"do": "mouth", "open": 0.5, "ms": 300}, 0.1), None)
        self.assertEqual(C.mouth_at({"do": "mouth", "open": 0.5, "ms": 300}, 0.1), 0.5)
        self.assertEqual(C.mouth_at({"do": "mouth", "open": 0.5, "ms": 300}, 0.29), 0.0)     # closed on the last tick
        tilt = C.head_at({"do": "tilt", "side": "left", "ms": 1000}, 0.5)
        self.assertLess(tilt[3], 0)
        for c in C.ACTIONS + C.BUILTIN_COMBOS:
            with self.subTest(c=c["id"]):
                self.assertEqual(C.clean_combo(dict(c, id="x" + c["id"]))["steps"], c["steps"])
                self.assertLess(C.duration(c["steps"]), C.MAX_TOTAL_S)
        self.assertEqual(C.describe(C.BUILTIN_COMBOS[0]["steps"]), "叫一声（打招呼） → 点头 2 次 → 张嘴")
        with self.assertRaises(C.Refused):
            C.clean_combo({"id": "long", "name": "x", "steps": [{"do": "wait", "ms": 3000}] * 8})


# ---------------- Parsing: live key presses, bluetoothctl ----------------

class LiveInputTest(unittest.TestCase):
    def test_xbox_ble_layout(self):
        """Note: the Xbox X / Y keycode swap is a guess (E9 pending hardware check); this only tests "flip by the guessed rule", and the page says it is pending verification."""
        li = P.LiveInput()
        li.attach(XBOX_DEV, 0.0)
        self.assertEqual(li.kind, "xbox")
        self.assertTrue(li.view(0.0)["device"]["keys_unverified"])
        li.frame({"events": [{"kind": 1, "code": 0x133, "value": 1}]}, 1.0)       # guess: the key labeled X reports BTN_X(0x133)
        self.assertTrue(li.buttons["west"])
        li.frame({"events": [{"kind": 3, "code": 2, "value": 32767}, {"kind": 3, "code": 9, "value": 1023},
                             {"kind": 3, "code": 17, "value": -1}]}, 1.1)
        self.assertAlmostEqual(li.axes["rx"], 1.0, places=2)                       # BLE: the right stick is Z
        self.assertAlmostEqual(li.axes["rt"], 1.0, places=2)                       # the trigger is GAS
        self.assertTrue(li.buttons["du"])                                          # D-pad up
        self.assertIn("rs", li.seen)
        self.assertIs(li.frame({"events": [{"kind": 1, "code": 0x13A, "value": 1}]}, 1.2), True)
        self.assertIsNone(li.frame({"events": [{"kind": 1, "code": 0x13A, "value": 2}]}, 1.3))  # auto-repeat is not a release
        self.assertIs(li.frame({"events": [{"kind": 1, "code": 0x13A, "value": 0}]}, 1.4), False)
        li.frame({"events": [{"kind": 1, "code": 0x2C0, "value": 1, "name": "BTN_TRIGGER_HAPPY1"}]}, 1.5)
        self.assertEqual(li.view(2.0)["other"], ["BTN_TRIGGER_HAPPY1"])

    def test_switch_is_positional(self):
        li = P.LiveInput()
        li.attach(PRO_DEV, 0.0)
        self.assertEqual(li.kind, "switch")
        self.assertFalse(li.view(0.0)["device"]["keys_unverified"])
        li.frame({"events": [{"kind": 1, "code": 0x133, "value": 1}, {"kind": 3, "code": 4, "value": -32767}]}, 1.0)
        self.assertTrue(li.buttons["north"])
        self.assertAlmostEqual(li.axes["ry"], -1.0, places=2)


class FakeProc:
    """Fake bluetoothctl process: receives commands on stdin, spits out a few chunks on stdout per the script (a chunk isn't necessarily a whole line: no newline after the prompt)."""

    def __init__(self, script):
        self.script = script
        self.q = queue.Queue()
        self.stdin = self
        self.stdout = iter(self.q.get, None)
        self.got = []
        self.terminated = self.killed = 0
        self.wait_ok = True
        for line in script.get("", []):
            self.q.put(line)

    def write(self, text):
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        cmd = text.strip()
        self.got.append(cmd)
        out = self.script.get(cmd, [])
        for line in out() if callable(out) else out:          # can be a function: the same command answers differently each time
            self.q.put(line)
        if cmd == "quit":
            self.q.put(None)

    def flush(self):
        pass

    def close(self):
        pass

    def wait(self, t=None):
        if not self.wait_ok:
            raise subprocess.TimeoutExpired("bluetoothctl", t)
        return 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1
        self.q.put(None)


class BluetoothctlTest(unittest.TestCase):
    def test_reconnect_uses_only_requested_mac_and_remaining_time(self):
        calls = []
        def run(argv, timeout):
            calls.append((argv, timeout))
            return 0, "Connection successful\n"
        bt = P.BluetoothCtl(run=run, prefix=("sudo", "-n"), stdbuf=False)
        bt.reconnect(PRO, timeout=0.25)
        self.assertEqual(calls, [(["sudo", "-n", "bluetoothctl", "connect", PRO], 0.25)])
        with self.assertRaises(P.BtError):
            bt.reconnect("--help")
        with self.assertRaises(P.BtError):
            bt.reconnect(PRO, timeout=0)
        self.assertEqual(len(calls), 1)

    def test_reconnect_does_not_accept_another_devices_connection_event(self):
        bt = P.BluetoothCtl(run=lambda argv, timeout: (0, f"[CHG] Device {XBOX} Connected: yes\n"))
        with self.assertRaises(P.BtError):
            bt.reconnect(PRO)

    PROMPT = "\x01\x1b[0;94m\x02[bluetooth]\x01\x1b[0m\x02# "
    T = {"pair": 1.0, "connect": 1.0, "trust": 1.0, "find": 0.3}

    def script(self, pair_ok=True):
        return {
            "": [f"{self.PROMPT}[NEW] Device 11:22:33:44:55:66 Old Phone\n"],                 # cached old device: doesn't count as seen
            "agent off": ["Agent unregistered\n"],
            "agent NoInputNoOutput": ["Agent registered\n"],
            "default-agent": ["Default agent request successful\n"],
            "scan on": ["Discovery started\n", "[CHG] Controller 00:11:22:33:44:55 Discovering: yes\n",
                        f"\r{self.PROMPT}\x1b[K[\x1b[0;92mNEW\x1b[0m] Device {PRO} Pro Controller\n",
                        f"[CHG] Device {PRO} RSSI: 0xffffffc7 (-57)\n"],
            "scan off": ["Discovery stopped\n"],
            # real bluetoothctl's agent question is a readline prompt with no trailing newline (review 4)
            f"pair {PRO}": (["Attempting to pair with " + PRO + "\n", "\x1b[0;91m[agent]\x1b[0m Accept pairing (yes/no): "] if pair_ok else
                            ["Attempting to pair with " + PRO + "\n", "Failed to pair: org.bluez.Error.AuthenticationFailed\n"]),
            "yes": [f"\n[CHG] Device {PRO} Paired: yes\n", "Pairing successful\n"],
            f"trust {PRO}": [f"[CHG] Device {PRO} Trusted: yes\n", f"Changing {PRO} trust succeeded\n"],
            f"connect {PRO}": ["Attempting to connect to " + PRO + "\n", f"[CHG] Device {PRO} Connected: yes\n", "Connection successful\n"],
        }

    def make(self, pair_ok=True, script=None, prefix=()):
        self.proc = FakeProc(script or self.script(pair_ok))
        self.argv = None
        info = ("Device 98:B6:E9:28:06:09 (public)\n\tName: Pro Controller\n\tClass: 0x00002508\n\tIcon: input-gaming\n"
                "\tPaired: no\n\tTrusted: no\n\tConnected: no\n\tUUID: Human Interface Device... (00001124-0000-1000-8000-00805f9b34fb)\n")
        runs = {"info": (0, info), "show": (0, "Controller 00:11:22:33:44:55 (public)\n\tPowered: yes\n\tPairable: no\n\tDiscovering: no\n")}

        def spawn(argv):
            self.argv = argv
            return self.proc
        bt = P.BluetoothCtl(run=lambda argv, timeout=8.0: runs.get(argv[len(prefix) + 1], (1, "")), spawn=spawn,
                            rfkill_dir="/nonexistent", prefix=prefix, stdbuf=True)
        bt.t = dict(self.T)
        return bt

    def test_scan_lists_only_devices_seen_while_discovering(self):
        bt = self.make()
        a = bt.adapter()
        self.assertEqual((a["present"], a["powered"], a["pairable"]), (True, True, False))
        bt.scan_start()
        wait_until(lambda: any(d.get("rssi") == -57 for d in bt.devices()), what="RSSI")
        devs = {d["mac"]: d for d in bt.devices()}
        self.assertEqual(devs[PRO]["name"], "Pro Controller")
        self.assertEqual(devs[PRO]["cls"], 0x2508)
        self.assertIsNone(devs["11:22:33:44:55:66"].get("seen_at"))         # the cache from before the scan doesn't count
        self.assertEqual(self.proc.got[0], "agent off")                     # review 5: first remove the agent registered at startup
        self.assertNotIn("agent NoInputNoOutput", self.proc.got)            # scanning doesn't register an agent
        bt.close()
        self.assertIn("quit", self.proc.got)

    def test_pair_sequence_in_one_session_and_auto_yes_without_newline(self):
        bt = self.make()
        bt.scan_start()
        steps = []
        bt.pair_device(PRO, True, threading.Event(), lambda k, s, n=None: steps.append((k, s)))
        self.assertEqual([c for c in self.proc.got if c.split()[0] in ("pair", "trust", "connect")],
                         [f"pair {PRO}", f"trust {PRO}", f"connect {PRO}"])
        self.assertIn("yes", self.proc.got)                                   # answered yes even though the prompt had no newline
        self.assertEqual(steps[-1], ("connect", "ok"))
        got = self.proc.got
        i_agent, i_pair = got.index("agent NoInputNoOutput"), got.index(f"pair {PRO}")
        self.assertLess(i_agent, i_pair)
        self.assertEqual(got[-1], "agent off")                                # hand the agent back after pairing
        bt.close()

    def test_prompt_outside_pairing_is_answered_no(self):
        s = dict(self.script(), **{"scan on": ["Discovery started\n", "[agent] Authorize service 0000110e (yes/no): "]})
        bt = self.make(script=s)
        bt.scan_start()
        wait_until(lambda: "no" in self.proc.got, what="答 no")
        self.assertNotIn("yes", self.proc.got)
        bt.close()

    def test_pair_failure_classified(self):
        bt = self.make(pair_ok=False)
        bt.scan_start()
        with self.assertRaises(P.BtError) as cm:
            bt.pair_device(PRO, True, threading.Event(), lambda *a: None)
        self.assertEqual(cm.exception.code, "auth_failed")
        self.assertEqual(self.proc.got[-1], "agent off")
        bt.close()

    def test_success_marks_are_locked_to_the_mac(self):
        """Review 11: another device's Paired: yes doesn't count; if this device isn't found, report not_found, not timeout."""
        s = self.script()
        s[f"pair {PRO}"] = ["Attempting to pair with " + PRO + "\n", "[CHG] Device 11:22:33:44:55:66 Paired: yes\n"]
        bt = self.make(script=s)
        bt.scan_start()
        with self.assertRaises(P.BtError) as cm:
            bt.pair_device(PRO, True, threading.Event(), lambda *a: None)
        self.assertEqual(cm.exception.code, "timeout")
        bt.close()
        s = self.script()
        s["scan on"] = ["Discovery started\n"]
        bt = self.make(script=s)
        with self.assertRaises(P.BtError) as cm:
            bt.pair_device(PRO, True, threading.Event(), lambda *a: None)
        self.assertEqual(cm.exception.code, "not_found")
        bt.close()

    def test_startup_agent_registered_late_is_replaced(self):
        """Oct 19, duck #2 (bluetoothctl 5.82): agent off when opening the session replies "No agent is registered", and only afterwards does its built-in agent register;
        during pairing agent NoInputNoOutput replies "Agent is already registered" → remove it first, register once more, and pair as usual."""
        s = self.script()
        offs = iter([["No agent is registered\n", "Agent registered\n"]])
        ons = iter([["Agent is already registered\n"]])
        s["agent off"] = lambda: next(offs, ["Agent unregistered\n"])
        s["agent NoInputNoOutput"] = lambda: next(ons, ["Agent registered\n"])
        bt = self.make(script=s)
        bt.scan_start()
        steps = []
        bt.pair_device(PRO, True, threading.Event(), lambda k, st, n=None: steps.append((k, st)))
        self.assertEqual(steps[-1], ("connect", "ok"))
        got = [c for c in self.proc.got if c.startswith("agent")]
        self.assertEqual(got, ["agent off", "agent NoInputNoOutput", "agent off", "agent NoInputNoOutput", "agent off"])
        bt.close()

    def test_connect_busy_right_after_pairing_waits_then_retries(self):
        """Oct 19, duck #2 G50 Pro: connect right after pairing returns InProgress br-connection-busy (the gamepad is also connecting by itself).
        If the gamepad connected by itself it counts as success; if not, wait a moment and connect again."""
        busy = ["Attempting to connect to " + PRO + "\n", "Failed to connect: org.bluez.Error.InProgress br-connection-busy\n"]
        for self_connects in (True, False):
            with self.subTest(self_connects=self_connects):
                s = self.script()
                first = busy + ([f"[CHG] Device {PRO} Connected: yes\n"] if self_connects else [])
                tries = iter([first])
                s[f"connect {PRO}"] = lambda: next(tries, [f"[CHG] Device {PRO} Connected: yes\n", "Connection successful\n"])
                bt = self.make(script=s)
                bt.t["settle"] = 0.3
                bt.scan_start()
                steps = []
                bt.pair_device(PRO, True, threading.Event(), lambda k, st, n=None: steps.append((k, st)))
                self.assertEqual(steps[-1], ("connect", "ok"))
                self.assertEqual(self.proc.got.count(f"connect {PRO}"), 1 if self_connects else 2)
                bt.close()

    def test_agent_failure_and_scan_failure_close_the_session(self):
        """Review 6: agent registration failed and scanning couldn't start: the session must be closed, leaving no orphan process."""
        s = self.script()
        s["agent NoInputNoOutput"] = ["Failed to register agent object\n"]
        bt = self.make(script=s)
        with self.assertRaises(P.BtError) as cm:
            bt.pair_device(PRO, True, threading.Event(), lambda *a: None)
        self.assertEqual(cm.exception.code, "agent")
        bt.close()
        self.assertIn("quit", self.proc.got)
        s = self.script()
        s["scan on"] = ["Failed to start discovery: org.bluez.Error.NotReady\n"]
        bt = self.make(script=s)
        with self.assertRaises(P.BtError):
            bt.scan_start()
        self.assertIn("quit", self.proc.got)
        self.assertIsNone(bt._session)

    def test_close_escalates_and_sudo_prefix_puts_stdbuf_after_sudo(self):
        bt = self.make(prefix=("sudo", "-n"))
        bt.scan_start()
        self.assertEqual(self.argv, ["sudo", "-n", "stdbuf", "-oL", "bluetoothctl"])
        self.proc.wait_ok = False                                             # doesn't exit after quit: terminate first, then kill
        bt.close()
        self.assertEqual((self.proc.terminated, self.proc.killed), (1, 1))

    def test_real_pipe_prompt_without_newline(self):
        """With a real subprocess (real pipe): the prompt has no newline, and reading in chunks can still answer yes immediately (root cause of review 4)."""
        child = (
            "import sys\n"
            "o=sys.stdout.buffer\n"
            "def w(s):\n    o.write(s.encode()); o.flush()\n"
            "for line in sys.stdin.buffer:\n"
            "    c=line.decode().strip()\n"
            "    if c=='quit': break\n"
            "    if c=='agent off': w('Agent unregistered\\n')\n"
            "    elif c.startswith('pair '): w('Attempting to pair\\n'); w('[agent] Accept pairing (yes/no): ')\n"
            "    elif c=='yes': w('\\nPairing successful\\n')\n")
        spawn = lambda argv: subprocess.Popen([sys.executable, "-I", "-u", "-c", child], stdin=subprocess.PIPE,  # noqa: E731
                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        s = P.BtSession(["bluetoothctl"], spawn)
        try:
            s.answer_yes = True
            s.cmd("pair AA", r"Pairing successful", timeout=5.0)
            self.assertTrue(any(a.endswith("→ yes") for a in s.asked))
        finally:
            s.close()
            s.p.wait(5)


class ParseTest(unittest.TestCase):
    def test_classify(self):
        for raw, code in [("Failed to pair: org.bluez.Error.AuthenticationFailed", "auth_failed"),
                          ("Failed to connect: org.bluez.Error.Failed br-connection-page-timeout", "timeout"),
                          ("Encryption Change: PIN or Key Missing (0x06)", "key_missing"),
                          ("SMP: Pairing Failed: DHKey check failed (0x0b)", "dhkey"),
                          ("Failed to start discovery: org.bluez.Error.NotReady", "powered_off"),
                          ("No default controller available", "no_adapter"),
                          ("Waiting to connect to bluetoothd...", "bluez_down"),
                          ("Device 98:B6:E9:28:06:09 not available", "not_found"),
                          ("org.freedesktop.DBus.Error.AccessDenied: Rejected send message", "bt_permission"),
                          ("connect failed: Permission denied (13)", "not_bondable"),
                          ("Failed to register agent object", "agent"),
                          ("this robot cannot enter a PIN", "pin"),
                          ("something odd", "other")]:
            with self.subTest(raw=raw):
                self.assertEqual(P.classify(raw), code)
        for code in P.FAILS:
            e = P.explain(code)
            self.assertTrue(e["msg"] and e["fix"], code)

    def test_bluetoothd_down_is_not_no_adapter(self):
        bt = P.BluetoothCtl(run=lambda argv, timeout=8.0: (124, "Waiting to connect to bluetoothd..."), rfkill_dir="/nonexistent")
        a = bt.adapter()
        self.assertEqual(a["code"], "bluez_down")

    def test_gamepad_rules_match_configd(self):
        self.assertEqual(P.gamepad_evidence("x", icon="input-gaming"), "classified")
        self.assertEqual(P.gamepad_evidence("x", cls=0x002508), "classified")
        self.assertEqual(P.gamepad_evidence("x", cls=0x002540), None)          # keyboard
        self.assertEqual(P.gamepad_evidence("x", appearance=0x03C4), "classified")
        self.assertEqual(P.gamepad_evidence("BLE Controller_280609"), "name")
        self.assertIsNone(P.gamepad_evidence("Galaxy Buds", icon="audio-headset"))
        self.assertTrue(P.same_pad(PRO, PRO_LE))
        self.assertFalse(P.same_pad(PRO, XBOX))
        self.assertEqual([P.pad_kind(n) for n in ("Xbox Wireless Controller", "DualSense Wireless Controller",
                                                  "Wireless Controller", "Pro Controller", "GameSir-Nova 2 Lite")],
                         ["xbox", "ps", "ps", "switch", "generic"])

    def test_bluetoothctl_lines(self):
        line = "\x01\x1b[0;94m\x02[Pro Controller]\x01\x1b[0m\x02# [CHG] Device 98:B6:E9:28:06:09 RSSI: -61\r"
        self.assertEqual(P.clean_line(line), "[CHG] Device 98:B6:E9:28:06:09 RSSI: -61")
        p = P.parse_props("\tName: Pro Controller\n\tRSSI: 0xffffffc3 (-61)\n\tAppearance: 0x03c4\n\tUUID: A\n\tUUID: B\n")
        d = P.device_from_props(PRO, p)
        self.assertEqual((d["rssi"], d["appearance"], p["uuids"]), (-61, 0x03C4, ["A", "B"]))
        self.assertTrue(math.isfinite(d["rssi"]))

    def test_robot_view_from_a_robotd_like_object(self):
        from studio.robotd import Sample

        class Rd:
            present, paused = True, None
            bus, policies, state, health, pad = Sample(), Sample(), Sample(), Sample(), Sample()
            estop = type("E", (), {"active": False, "press_count": 3})()
        rd = Rd()
        rd.bus.set(bus(policy_enabled=True, homed=True))
        rd.policies.set(dict(POLICIES))
        rd.state.set({"move": {"applied": [0.2, 0, 0]}})
        rd.health.set({"battery": {"percent": 55}})
        v = P.robot_view(rd)
        self.assertEqual((v["posture"], v["estop_presses"], v["battery_pct"]), ("walking", 3, 55))
        self.assertEqual(v["policies"]["skills"], POLICIES["skills"])


# ---------------- Real ports: local TCP fake services (review 20) ----------------

class FakeServer:
    """A local TCP service: for each incoming connection, run handler(sock) in a thread."""

    def __init__(self, handler):
        self.handler = handler
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.addr = f"tcp:127.0.0.1:{self.srv.getsockname()[1]}"
        self.conns = 0
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.alive:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.conns += 1
            threading.Thread(target=self._run, args=(c,), daemon=True).start()

    def _run(self, c):
        try:
            self.handler(c)
        except OSError:
            pass
        finally:
            c.close()

    def close(self):
        self.alive = False
        self.srv.close()


def read_line(c):
    buf = b""
    while not buf.endswith(b"\n"):
        x = c.recv(4096)
        if not x:
            break
        buf += x
    return buf


def free_port_addr():
    s = socket.create_server(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"tcp:127.0.0.1:{port}"


class PortTest(unittest.TestCase):
    def test_rpc_call_skips_junk_and_maps_errors(self):
        def ok(c):
            read_line(c)
            c.sendall(b'[1,2]\n"x"\ngarbage\n{"jsonrpc":"2.0","method":"note"}\n{"jsonrpc":"2.0","id":1,"result":{"ok":1}}\n')
        srv = FakeServer(ok)
        self.assertEqual(P.ConfigdPort(srv.addr).call("pad.status", {}, 2.0), {"ok": 1})
        srv.close()

        def err(c):
            read_line(c)
            c.sendall(b'{"jsonrpc":"2.0","id":1,"error":{"code":14,"message":"may not change"}}\n')
        srv = FakeServer(err)
        with self.assertRaises(RpcError) as cm:
            P.rpc_call(srv.addr, "pad.pair", {}, 2.0)
        self.assertEqual(cm.exception.code, 14)
        srv.close()

        def err_str(c):
            read_line(c)
            c.sendall(b'{"jsonrpc":"2.0","id":1,"error":"bad"}\n')
        srv = FakeServer(err_str)
        with self.assertRaises(RpcError) as cm:
            P.rpc_call(srv.addr, "x", {}, 2.0)
        self.assertEqual(cm.exception.message, "bad")
        srv.close()

        srv = FakeServer(lambda c: read_line(c))           # receive then close: no reply
        with self.assertRaises(Unreachable):
            P.rpc_call(srv.addr, "x", {}, 2.0)
        srv.close()

        srv = FakeServer(lambda c: (read_line(c), time.sleep(1.0)))
        with self.assertRaises(Timeout):
            P.rpc_call(srv.addr, "x", {}, 0.3)
        srv.close()

        with self.assertRaises(Unreachable):
            P.rpc_call("unix:/nonexistent/configd.sock", "x", {}, 1.0)     # on the duck: socket absent
        with self.assertRaises((Unreachable, Timeout)):                    # port nobody listens on: Linux refuses immediately, Windows waits for the timeout
            P.rpc_call(free_port_addr(), "x", {}, 1.0)

    def test_permission_error_is_its_own_kind(self):
        with mock.patch("socket.create_connection", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(P.NoPermission) as cm:
                P.rpc_call("tcp:127.0.0.1:1", "x", {}, 1.0)
        self.assertIn("robot 组", str(cm.exception))

    def test_padd_tap_reports_and_survives_callback_errors(self):
        def tap(c):
            read_line(c)
            dev = {"name": "Pro Controller", "axes": [], "buttons": []}
            c.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"accepted": True}}) + "\n"
                       + "[1]\nnot json\n"
                       + json.dumps({"method": "pad.report", "params": {"report": "attached", "device": dev}}) + "\n"
                       + json.dumps({"method": "pad.report", "params": "nope"}) + "\n"
                       + json.dumps({"method": "pad.report", "params": {"report": "frame", "events": []}}) + "\n").encode())
            time.sleep(0.2)
        srv = FakeServer(tap)
        reports, states, boom = [], [], {"n": 0}

        def on_report(r):
            if r.get("report") == "attached" and boom["n"] == 0:
                boom["n"] += 1
                raise ValueError("回调里出错")
            reports.append(r)
        tmp = tempfile.TemporaryDirectory()
        log = Log(Path(tmp.name), echo=False, background=False)
        t = P.PaddTap(srv.addr, reconnect_s=0.05, log=log)
        t.start(on_report, lambda s, why=None: states.append(s))
        try:
            wait_until(lambda: sum(1 for r in reports if r.get("report") == "attached") >= 1, what="重连后又收到 attached")
            self.assertTrue(t.alive())
            self.assertIn("error", states)
            self.assertIn("waiting", states)
            self.assertTrue(any(r.get("report") == "frame" for r in reports))
            self.assertTrue(any("读手柄按键的线程出错" in e["msg"] for e in log.recent(20)))
        finally:
            t.stop()
            srv.close()
            tmp.cleanup()

    def test_padd_tap_absent_and_refused_subscription(self):
        states = []
        t = P.PaddTap("unix:/nonexistent/pad.sock", reconnect_s=0.05)
        t.start(lambda r: None, lambda s, why=None: states.append((s, why)))
        wait_until(lambda: states, what="报 absent")
        t.stop()
        self.assertEqual(states[0][0], "absent")

        def refuse(c):
            read_line(c)
            c.sendall(b'{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"no such method"}}\n')
            time.sleep(0.2)
        srv = FakeServer(refuse)
        states = []
        t = P.PaddTap(srv.addr, reconnect_s=0.5)
        t.start(lambda r: None, lambda s, why=None: states.append((s, why)))
        wait_until(lambda: any(s == "error" for s, _ in states), what="拒绝订阅")
        t.stop()
        srv.close()
        self.assertIn("no such method", next(w for s, w in states if s == "error"))

    def test_robot_port_notify(self):
        got = []

        def sink(c):
            buf = b""
            while True:
                x = c.recv(4096)
                if not x:
                    break
                buf += x
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    got.append(json.loads(line))
        srv = FakeServer(sink)
        rp = P.RobotPort(srv.addr)
        rp.notify("robot.move", {"vx": 0.1, "vy": 0, "vyaw": 0})
        rp.notify("robot.mouth", {"open": 0.5})
        wait_until(lambda: len(got) == 2, what="收到两条通知")
        self.assertEqual(got[0], {"jsonrpc": "2.0", "method": "robot.move", "params": {"vx": 0.1, "vy": 0, "vyaw": 0}})
        self.assertNotIn("id", got[1])                         # notifications carry no id
        self.assertEqual(srv.conns, 1)                          # persistent connection
        rp._close()
        srv.close()
        with self.assertRaises((Unreachable, Timeout)):
            P.RobotPort(free_port_addr()).notify("robot.move", {"vx": 0})
        with self.assertRaises(Unreachable):
            P.RobotPort("unix:/nonexistent/robotd.sock").notify("robot.move", {"vx": 0})


# ---------------- Overview rearrangement (overview-merge-plan.md §5, review overview-merge-review.md O1, O6, O7, O12, O16) ----------------

class OverviewMergeTest(PadTestBase):
    """Backend rules after the gamepad was merged into the overview. Borrows a few small tools from VpadTest (doesn't inherit it: inheriting would run its tests again)."""
    feed, sent, s, into, stick = VpadTest.feed, VpadTest.sent, VpadTest.s, VpadTest.into, VpadTest.stick

    def setUp(self):
        super().setUp()
        self._n = itertools.count(1000)

    def test_new_connection_is_not_in_pad_area_until_open(self):
        """O1: new connections default to "not in the gamepad area": for a page that hasn't sent drive {open}, sticks, held keys and modes are all dropped, and actions can't get the wheel."""
        self.feed()
        c = self.ops.new_conn()
        r = self.stick("drive", conn=c, ly=-1)
        self.assertIn("dropped", r)
        self.assertEqual(self.sent("robot.move"), [])
        self.assertIn("dropped", self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": self.s()}, conn=c))
        self.assertIn("dropped", self.into("head", conn=c))
        with self.assertRaises(P.Refused) as cm:
            self.ops.handle({"op": "action_start", "id": "nod"}, by="电脑 A", conn=c)
        self.assertIn("不在手柄这一块", str(cm.exception))
        time.sleep(0.15)
        self.assertEqual([m for m, _ in self.sent() if m in ("robot.move", "robot.mouth", "robot.sound", "robot.head")], [])
        # one-shot commands still ignore closed (round-3 V5): anyone can click "stop (stand)"
        self.ops.handle({"op": "walk_stop"}, by="电脑 A", conn=c)
        self.assertIn(("robot.enable", {"on": False, "toggle": False}), self.robot.calls)
        # only accepted after open is sent (the gamepad block is on screen)
        self.feed()
        self.ops.handle({"op": "drive", "open": True, "seq": self.s()}, conn=c)
        self.assertEqual(self.stick("drive", conn=c, ly=-1)["sent"][0], 0.3)

    def test_scroll_out_then_back(self):
        """O1: scrolling out of the gamepad area (drive off): a held stick sends 0 once, frames arriving later are all dropped; scrolling back (open) makes it usable again."""
        self.feed()
        c = self.ops.new_conn()
        self.ops.handle({"op": "drive", "open": True, "seq": self.s()}, conn=c)
        late = self.s()                                                          # a frame sent before scrolling out, arriving late
        self.stick("drive", conn=c, ly=-1)
        self.ops.handle({"op": "drive", "on": False, "seq": self.s()}, conn=c)
        self.assertEqual(self.sent("robot.move")[-1][1], {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
        self.assertIn("dropped", self.stick("drive", conn=c, seq=late, ly=-1))
        self.assertIn("dropped", self.stick("drive", conn=c, ly=-1))
        self.assertTrue(any("离开了手柄区" in e["msg"] for e in self.log.recent(30)))
        self.ops.handle({"op": "drive", "open": True, "seq": self.s()}, conn=c)
        self.assertEqual(self.stick("drive", conn=c, ly=-1)["sent"][0], 0.3)

    def test_estop_pass_is_handed_to_checklist_with_pad_and_build(self):
        """O6: once the e-stop test passes, record which gamepad (MAC) and which main-program version it was tested with."""
        got = []
        self.ops.on_estop_passed = got.append
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.watch()
        self.tap.attach(XBOX_DEV)
        wait_until(lambda: self.ops.snapshot()["estop"]["ok"], what="急停四条都 ✓")
        self.robot_ok(bus=bus(build="1fa8438-feetech-ft6-control.43"))
        self.ops.handle({"op": "estop_test", "action": "start"})
        wait_until(lambda: self.ops.snapshot()["estop_test"]["state"] == "armed", what="等按 Select")
        self.tap.key(0x13A, True)
        wait_until(lambda: self.ops.test.get("_on_while_pressed") is not None, what="按着时问过扭矩")
        self.tap.key(0x13A, False)
        time.sleep(0.05)
        self.robot_ok(torque_on=False, bus=bus(False, build="1fa8438-feetech-ft6-control.43"))
        wait_until(lambda: got, what="交给上手清单")
        self.assertEqual(got[0]["mac"], XBOX)
        self.assertEqual(got[0]["name"], "Xbox Wireless Controller")
        self.assertEqual(got[0]["build"], "1fa8438-feetech-ft6-control.43")
        self.assertIsInstance(got[0]["ms"], int)
        # a hook error is only logged; the e-stop test still counts as passed
        self.ops.on_estop_passed = lambda r: 1 / 0
        self.ops._estop_passed_record()
        self.assertTrue(any("记「测急停过了」时出错" in e["msg"] for e in self.log.recent(20)))

    def test_onboard_view_uses_same_status_and_estop_as_snapshot(self):
        """O7: checklist steps 3 and 4 use the same status / estop as the gamepad snapshot."""
        self.cfg.connect_pad(XBOX, "Xbox Wireless Controller")
        self.ops.handle({"op": "refresh"})
        v, snap = self.ops.onboard_view(), self.ops.snapshot()
        self.assertEqual(v["pads"], snap["status"]["pads"])
        self.assertEqual(v["active"]["mac"], XBOX)
        self.assertEqual(v["estop"]["state"], snap["estop"]["state"])
        self.assertFalse(v["attached"])
        self.watch()
        self.tap.attach(XBOX_DEV)
        self.assertEqual(self.ops.onboard_view()["device"]["unique"], XBOX_DEV["unique"])

    def test_attached_logged_only_when_device_changes(self):
        """O16: scrolling out for 6 s (tap closed) and back yields another attached: the same device doesn't get another row."""
        self.watch()
        for _ in range(3):
            self.tap.attach(XBOX_DEV)
        self.tap.attach(PRO_DEV)
        msgs = [e["msg"] for e in self.log.recent(50) if e["msg"].startswith("padd 打开了手柄")]
        self.assertEqual(len(msgs), 2)

    def test_c7_action_hold_only_counts_for_the_same_press(self):
        """Code review C7: a timer left by the page's previous press (carrying the old press) can't extend this press; old pages without press work as before."""
        self.robot_ok(posture="policy", policies=POLICIES)
        self.ops.handle({"op": "action_start", "id": "nod", "press": 1}, by="电脑 A", conn="a")
        self.assertEqual(self.ops.handle({"op": "action_hold", "press": 1}, conn="a")["running"], "nod")
        self.ops.handle({"op": "action_start", "id": "nod", "press": 2}, by="电脑 A", conn="a")   # released and pressed again
        held = self.ops._action["hold"]
        time.sleep(0.02)
        self.assertIsNone(self.ops.handle({"op": "action_hold", "press": 1}, conn="a")["running"])
        self.assertEqual(self.ops._action["hold"], held)                       # the old one wasn't extended
        self.assertEqual(self.ops.handle({"op": "action_hold", "press": 2}, conn="a")["running"], "nod")
        self.assertEqual(self.ops.handle({"op": "action_hold"}, conn="a")["running"], "nod")   # without a sequence number (old page)
        self.ops.handle({"op": "action_stop"}, conn="a")

    def test_tap_skips_pad_imu_lines_before_parsing(self):
        """O12: lines from the gamepad's built-in IMU are skipped by string match first, not json.loads."""
        imu = json.dumps({"jsonrpc": "2.0", "method": "pad.report", "params": {"report": "imu", "samples": [[0, 0, 0]] * 3}},
                         separators=(",", ":"))
        att = json.dumps({"jsonrpc": "2.0", "method": "pad.report", "params": {"report": "imu_attached", "device": {"name": "imu"}}},
                         separators=(",", ":"))

        def tap(c):
            read_line(c)
            c.sendall(('{"jsonrpc":"2.0","id":1,"result":{"accepted":true}}\n' + (imu + "\n") * 20 + att + "\n").encode())
            time.sleep(0.3)
        srv = FakeServer(tap)
        reports, parsed = [], []
        real = json.loads

        def counting(s, *a, **k):
            parsed.append(s)
            return real(s, *a, **k)
        t = P.PaddTap(srv.addr, reconnect_s=5)
        with mock.patch.object(P.json, "loads", counting):
            t.start(reports.append, lambda s, why=None: None)
            try:
                wait_until(lambda: any(r.get("report") == "imu_attached" for r in reports), what="收到 imu_attached")
            finally:
                t.stop()
                srv.close()
        self.assertFalse(any(r.get("report") == "imu" for r in reports))
        self.assertFalse(any(b'"report":"imu"' in (s if isinstance(s, bytes) else s.encode()) for s in parsed))


if __name__ == "__main__":
    unittest.main()
