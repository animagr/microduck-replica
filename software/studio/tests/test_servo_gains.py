"""P / D / torque limit when enabling torque are the same as the main program (user, Oct 19: "P, D and so on should match the main program, i.e. default P5, D0, torque limit 1000").

Compared against the fork firmware (duck-control/src/hd1910.rs, hd1910_test.rs):
RAM 48..51 in one packet [limit low, limit high, P, D], sync_read 48×4 readback check, don't touch EEPROM 21/22, don't touch lock flag 55.
Runs with the protocol-level simulated servo (sim_bus): the simulated servo powers up with factory P32 / D40 / torque limit 1000.
"""
import json
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio.bus import feetech  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.servo import IDS, ServoSession  # noqa: E402
from studio.servo_ops import MainGains, _walk_contract, contract_kp, load_servo_params  # noqa: E402

FORK = Path(os.environ["MICRODUCK_FORK"]) if os.environ.get("MICRODUCK_FORK") else None
FORK_WALK = FORK / "packaging" / "models" / "1cbf8730eadd75a5704332c9f3c10f60" / "deployment-contract.json" if FORK else None


def run_gains(sv):
    """The simulated servo's running (P, D, torque limit): RAM 50, 51, 48..49."""
    return sv.r[50], sv.r[51], sv.r[48] | sv.r[49] << 8


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def bump(path, n):
    """Shift the mtime (two writes within the same second may leave mtime unchanged; this uses mtime_ns + size, but shift it anyway to be safe)."""
    t = time.time() + n
    os.utime(path, (t, t))


class Recorder:
    """Record every packet on the bus (ID, instruction, params) to see the write order and which registers were written."""

    def __init__(self, ser):
        self.packets = []
        orig = ser._handle

        def handle(sid, instr, p):
            self.packets.append((sid, instr, bytes(p)))
            return orig(sid, instr, p)
        ser._handle = handle

    def writes(self):
        """[(index, address, {id: data})]: both WRITE and SYNC_WRITE are flattened per ID."""
        out = []
        for n, (sid, instr, p) in enumerate(self.packets):
            if instr == feetech.WRITE:
                out.append((n, p[0], {sid: p[1:]}))
            elif instr == feetech.SYNC_WRITE:
                addr, ln, rest = p[0], p[1], p[2:]
                out.append((n, addr, {rest[k]: rest[k + 1:k + 1 + ln] for k in range(0, len(rest), ln + 1)}))
        return out

    def first_torque_on(self, sid):
        return next((n for n, a, d in self.writes() if a == 40 and d.get(sid, b"\x00")[:1] == b"\x01"), None)

    def gains_writes(self, sid):
        return [n for n, a, d in self.writes() if a == 48 and len(d.get(sid, b"")) == 4]


# ---------------- The main program's torque-enable parameters (no bus) ----------------

class MainGainsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.params = self.dir / "servo-test-parameters.json"
        self.toml = self.dir / "robotd.toml"
        self.warns = []

    def tearDown(self):
        self.tmp.cleanup()

    def mg(self, tomls=None):
        return MainGains(params_path=str(self.params), robotd_tomls=tomls if tomls is not None else (str(self.toml),),
                         log=lambda msg, cat="总线", level="info": self.warns.append((cat, level, msg)))

    def test_no_files_is_v167_default_5_0_1000(self):
        g = MainGains(params_path=str(self.dir / "nope" / "servo-test-parameters.json"), robotd_tomls=()).get()
        self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (5, 0, 1000, "主程序默认"))
        self.assertIn("没有主程序的配置", g["detail"])        # on a computer (bench / demo) this is the message
        self.assertIsNone(g["warn"])

    def test_valid_file_wins(self):
        write_json(self.params, {"kp": 3, "kd": 1, "torque_limit": 681})
        g = self.mg().get()
        self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (3, 1, 681, "参数文件"))
        self.assertEqual(self.warns, [])

    def test_bad_or_out_of_range_file_falls_back_and_warns(self):
        """Same set of bad files as fork hd1910_test.rs:111-121, plus 5.0, true, duplicate keys (serde rejects all of them)."""
        bad = ['{"kp":256,"kd":0,"torque_limit":681}', '{"kp":3,"kd":0,"torque_limit":1001}', '{"kp":3,"kd":0}',
               '{"kp":0,"kd":0,"torque_limit":681}', '{"kp":33,"kd":0,"torque_limit":681}',
               '{"kp":3,"kd":65,"torque_limit":681}', '{"kp":3,"kd":0,"torque_limit":199}',
               '{"kp":3,"kd":0,"torque_limit":681,"extra":1}', 'not json', '{"kp":5.0,"kd":0,"torque_limit":1000}',
               '{"kp":true,"kd":0,"torque_limit":1000}', '{"kp":3,"kp":4,"kd":0,"torque_limit":1000}', '[1,2,3]']
        for n, text in enumerate(bad):
            with self.subTest(text=text):
                write_json(self.params, text)
                with self.assertRaises(ValueError):
                    load_servo_params(str(self.params))
                self.warns.clear()
                g = self.mg().get()
                self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (5, 0, 1000, "主程序默认"))
                self.assertIn("不合法", g["warn"])
                self.assertEqual([(c, lv) for c, lv, _ in self.warns], [("总线", "warn")])

    def test_boundaries_accepted(self):
        for kp, kd, lim in ((1, 0, 200), (32, 64, 1000)):
            write_json(self.params, {"kp": kp, "kd": kd, "torque_limit": lim})
            self.assertEqual(load_servo_params(str(self.params)), (kp, kd, lim))

    def test_contract_kp_fw_used_without_file(self):
        model = self.dir / "models" / "walk"
        model.mkdir(parents=True)
        write_json(model / "deployment-contract.json", {"model": {"actuators": [{"kp_fw": 4.0}]}})
        self.toml.write_text(f'[policy]\nwalk = "{(model / "policy.onnx").as_posix()}"\n', encoding="utf-8")
        g = self.mg().get()
        self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (4, 0, 1000, "主程序默认"))
        self.assertIn("kp_fw", g["detail"])
        # kp_fw in the contract is invalid: P falls back to 5
        for bad in ({"model": {"actuators": [{"kp_fw": 4.5}]}}, {"model": {"actuators": [{"kp_fw": 40}]}},
                    {"model": {"actuators": [{}, {}]}}, {"model": {}}):
            write_json(model / "deployment-contract.json", bad)
            bump(model / "deployment-contract.json", len(json.dumps(bad)))
            self.assertEqual(self.mg().get()["kp"], 5, bad)

    def test_walk_path_resolution_like_robotd(self):
        self.toml.write_text("[policy]\nmode = \"walk\"\n", encoding="utf-8")
        self.assertEqual(_walk_contract(str(self.toml)), "/opt/robot/policies/current/deployment-contract.json")
        self.toml.write_text('[policy]\nwalk = "none"\n', encoding="utf-8")     # walk doesn't accept "none", falls back to default
        self.assertEqual(_walk_contract(str(self.toml)), "/opt/robot/policies/current/deployment-contract.json")
        self.toml.write_text('[policy]\nwalk = "/opt/robot/feetech-ft5-r5/models/abc/policy.onnx"\n', encoding="utf-8")
        self.assertEqual(_walk_contract(str(self.toml)), "/opt/robot/feetech-ft5-r5/models/abc/deployment-contract.json")

    @unittest.skipUnless(FORK_WALK is not None and FORK_WALK.is_file(), "设 MICRODUCK_FORK 指向 fork 固件目录才跑")
    def test_real_fork_walk_contract_is_5(self):
        """The walk model packaged by the fork (walk in packaging/robotd-profile.toml) has kp_fw 5."""
        self.assertEqual(contract_kp(str(FORK_WALK)), 5)

    def test_cached_by_mtime(self):
        write_json(self.params, {"kp": 3, "kd": 1, "torque_limit": 681})
        mg = self.mg()
        self.assertEqual(mg.get()["kp"], 3)
        write_json(self.params, {"kp": 7, "kd": 1, "torque_limit": 681})
        bump(self.params, 5)
        self.assertEqual(mg.get(max_age=60)["kp"], 3)           # no stat within max_age
        self.assertEqual(mg.get()["kp"], 7)                     # reread when the file changes
        self.params.unlink()
        self.assertEqual(mg.get()["source"], "主程序默认")      # deleted: back to default


# ---------------- On the bus: every path that enables torque ----------------

class SimBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = []

    def tearDown(self):
        for s in self.sessions:
            s.close()
        self.tmp.cleanup()

    def open(self, params=None):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        s = ServoSession(Log(Path(d) / "logs", echo=False, background=False), sim=True, state_dir=d)
        ok, why = s.open("测试")
        self.assertTrue(ok, why)
        end = time.monotonic() + 2
        while len(s.rows) < 15 and time.monotonic() < end:
            time.sleep(0.02)
        self.sessions.append(s)
        # no /etc/robot on a computer: defaults are 5/0/1000; tests that need a params file use another MainGains pointed at a temp dir
        pp = os.path.join(d, "etc", "servo-test-parameters.json")
        if params is not None:
            os.makedirs(os.path.dirname(pp))
            write_json(pp, params)
        s.ops.gains = MainGains(params_path=pp, robotd_tomls=(), log=s.ops.log)
        return s

    @staticmethod
    def sim(s, i):
        return s.sim_serial.servos[i]


class GainsOnBusTest(SimBase):
    def test_sim_powers_up_with_factory_gains(self):
        s = self.open()
        sv = self.sim(s, 22)
        self.assertEqual(run_gains(sv), (32, 40, 1000))
        self.assertEqual((sv.r[21], sv.r[22], sv.r[23]), (32, 40, 0))

    def test_torque_on_writes_5_0_1000_before_torque_only_ram(self):
        s = self.open()
        rec = Recorder(s.sim_serial)
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
        sv = self.sim(s, 22)
        self.assertEqual(r["on"], [22])
        self.assertEqual(sv.r[40], 1)
        self.assertEqual(run_gains(sv), (5, 0, 1000))
        self.assertEqual((sv.r[21], sv.r[22], sv.r[52], sv.r[55]), (32, 40, 0, 1))   # EEPROM, I and lock flag untouched
        self.assertEqual(r["gains"], {"kp": 5, "kd": 0, "limit": 1000, "source": "主程序默认"})
        g = rec.gains_writes(22)
        self.assertEqual(len(g), 1)
        self.assertLess(g[0], rec.first_torque_on(22))                       # write P/D/torque limit first, then enable torque
        self.assertEqual(rec.writes()[[n for n, *_ in rec.writes()].index(g[0])][2][22], struct.pack("<H", 1000) + bytes([5, 0]))
        touched = {a for _, a, d in rec.writes() if 22 in d}
        self.assertFalse(touched & {21, 22, 23, 55}, touched)                # EEPROM P/D/I not written, lock untouched
        # in the table: running P/D/torque limit are readback values, same as the main program
        snap = s.snapshot()
        row = {x["id"]: x for x in snap["rows"]}[22]
        self.assertEqual((row["p_run"], row["d_run"], row["limit"], row["gains_ok"]), (5, 0, 1000, True))
        self.assertEqual((snap["gains"]["kp"], snap["gains"]["kd"], snap["gains"]["limit"]), (5, 0, 1000))
        self.assertEqual(snap["gains"]["differ_on"], [])

    def test_only_writes_servos_that_differ(self):
        s = self.open()
        self.sim(s, 20).r[50], self.sim(s, 20).r[51] = 5, 0              # 20 is already 5/0/1000
        rec = Recorder(s.sim_serial)
        s.ops.handle({"op": "torque", "on": 1, "ids": [20, 21]})
        self.assertEqual(rec.gains_writes(20), [])
        self.assertEqual(len(rec.gains_writes(21)), 1)
        s.ops.handle({"op": "torque", "on": 0, "ids": [20, 21]})
        rec.packets.clear()
        s.ops.handle({"op": "torque", "on": 1, "ids": [20, 21]})              # enable torque again: all correct, nothing written
        self.assertEqual([a for _, a, _ in rec.writes() if a == 48], [])
        self.assertEqual((self.sim(s, 20).r[40], self.sim(s, 21).r[40]), (1, 1))

    def test_rewrites_after_servo_reboot(self):
        s = self.open()
        s.ops.handle({"op": "torque", "on": 1, "ids": [23]})
        s.ops.handle({"op": "reboot", "id": 23})                              # reboot: RAM back to factory P32/D40
        self.assertEqual(run_gains(self.sim(s, 23)), (32, 40, 1000))
        s.ops.handle({"op": "torque", "on": 1, "ids": [23]})
        self.assertEqual(run_gains(self.sim(s, 23)), (5, 0, 1000))

    def test_params_file_values_used(self):
        s = self.open(params={"kp": 3, "kd": 1, "torque_limit": 681})
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [22, 12]})
        self.assertEqual(r["on"], [22, 12])
        for i in (22, 12):
            self.assertEqual(run_gains(self.sim(s, i)), (3, 1, 681))
        self.assertEqual(r["gains"]["source"], "参数文件")
        self.assertEqual(s.snapshot()["gains"]["source"], "参数文件")

    def test_bad_params_file_uses_default_and_warns(self):
        s = self.open(params={"kp": 0, "kd": 0, "torque_limit": 681})       # older version allowed kp=0, the fork rejects it
        s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
        self.assertEqual(run_gains(self.sim(s, 22)), (5, 0, 1000))
        warns = s.log.recent(cats=["总线"], min_level="warn")
        self.assertTrue(any("不合法" in e["msg"] for e in warns), warns)
        self.assertIn("不合法", s.snapshot()["gains"]["warn"])

    def test_readback_mismatch_refuses_torque_and_logs_register(self):
        s = self.open()
        self.sim(s, 22).readonly = {50}                                       # P can't be written
        rec = Recorder(s.sim_serial)
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [22, 21]})
        self.assertEqual(r["on"], [21])
        self.assertEqual(self.sim(s, 22).r[40], 0)                           # torque not enabled
        self.assertEqual(self.sim(s, 21).r[40], 1)
        self.assertIn("50（P）写 5 读回 32", r["bad"]["22"])
        self.assertIsNone(rec.first_torque_on(22))
        errs = s.log.recent(cats=["总线"], min_level="error")
        self.assertTrue(any("#22" in e["msg"] and "50（P）" in e["msg"] for e in errs), errs)

    def test_no_reply_refuses_torque(self):
        s = self.open()
        self.sim(s, 24).muted = {48}                                          # reads from 48 on don't come back
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [24]})
        self.assertEqual(r["on"], [])
        self.assertIn("读不到 P/D/限力", r["bad"]["24"])
        self.assertEqual(self.sim(s, 24).r[40], 0)

    def test_already_on_with_other_gains_is_only_checked(self):
        """Servos with torque on don't get P changed (changing P on a loaded joint makes it sag briefly): only check, and highlight the page header yellow. The fork's arm also only checks while torque is on."""
        s = self.open()
        sv = self.sim(s, 13)
        sv.r[40] = 1                                                          # torque enabled elsewhere, still factory P32/D40
        s._read_torque()
        rec = Recorder(s.sim_serial)
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [13]})
        self.assertEqual(r["on"], [13])
        self.assertIn("13", r["differ"])
        self.assertEqual(run_gains(sv), (32, 40, 1000))
        self.assertEqual(rec.gains_writes(13), [])
        snap = s.snapshot()
        self.assertEqual(snap["gains"]["differ_on"], [13])
        self.assertFalse({x["id"]: x for x in snap["rows"]}[13]["gains_ok"])
        # release then hold: fixed
        s.ops.handle({"op": "torque", "on": 0, "ids": [13]})
        s.ops.handle({"op": "torque", "on": 1, "ids": [13]})
        self.assertEqual(run_gains(sv), (5, 0, 1000))
        self.assertEqual(s.snapshot()["gains"]["differ_on"], [])

    def test_manual_register_write_flags_header(self):
        s = self.open()
        s.ops.handle({"op": "torque", "on": 1, "ids": [20]})
        s.ops.handle({"op": "write_reg", "id": 20, "addr": 50, "size": 1, "value": 10})   # advanced usage still allowed
        self.assertEqual(self.sim(s, 20).r[50], 10)
        g = s.snapshot()["gains"]
        self.assertEqual([(m["id"], m["addr"], m["value"]) for m in g["manual"]], [(20, 50, 10)])
        self.assertEqual(g["differ_on"], [20])
        self.assertTrue(any("手动改了" in e["msg"] for e in s.log.recent(cats=["总线"], min_level="warn")))
        s.ops.handle({"op": "torque", "on": 1, "ids": [20]})                  # clicking hold with torque on: only check, don't change back
        self.assertEqual(self.sim(s, 20).r[50], 10)
        s.ops.handle({"op": "torque", "on": 0, "ids": [20]})
        s.ops.handle({"op": "torque", "on": 1, "ids": [20]})                  # release then hold: write back the main program's values
        self.assertEqual(self.sim(s, 20).r[50], 5)
        self.assertEqual(s.snapshot()["gains"]["manual"], [])
        # EEPROM P (21): only used after power-up, always remembered as "manually changed"; enabling torque still writes the running 5
        s.ops.handle({"op": "write_reg", "id": 21, "addr": 21, "size": 1, "value": 20, "unlock": True})
        s.ops.handle({"op": "write_reg", "id": 21, "addr": 48, "size": 2, "value": 700})
        self.assertEqual(self.sim(s, 21).r[21], 20)
        s.ops.handle({"op": "torque", "on": 1, "ids": [21]})
        self.assertEqual(run_gains(self.sim(s, 21)), (5, 0, 1000))
        self.assertEqual([(m["id"], m["addr"]) for m in s.snapshot()["gains"]["manual"]], [(21, 21)])


# Every path that enables torque: (name, prepare, do, which servo to check). prepare runs before "can't write" is set (prepare may itself need to enable torque once)
def _hold_one(t, s):
    s.ops.handle({"op": "torque", "on": 1, "ids": [22]})


def _hold_all(t, s):
    s.ops.handle({"op": "torque", "on": 1})


def _idle(t, s):
    s.ops.handle({"op": "idle", "on": True})
    s.ops.handle({"op": "idle", "on": False})
    if s.ops._idle_thread:
        s.ops._idle_thread.join(5)


def _calib_from_off(t, s):
    s.ops.handle({"op": "calibrate", "ids": "22"})                           # holds automatically after calibration (torque_on_aligned)


def _prep_on_stale(t, s):
    """22 has torque on, but RAM still has factory P32/D40 (e.g. torque enabled elsewhere): calibration / undo must write them before restoring torque."""
    s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
    sv = t.sim(s, 22)
    sv.r[50], sv.r[51] = 32, 40


def _prep_calibrated_stale(t, s):
    s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
    s.ops.handle({"op": "calibrate", "ids": "22"})
    sv = t.sim(s, 22)
    sv.r[50], sv.r[51] = 32, 40


def _undo(t, s):
    s.ops.handle({"op": "undo"})


PATHS = [
    ("单颗保持", None, _hold_one, 22),
    ("全部扭矩开", None, _hold_all, 22),
    ("灵动（头部上力）", None, _idle, 31),
    ("校准后自动保持（原来松着）", None, _calib_from_off, 22),
    ("校准里恢复扭矩（原来上着力）", _prep_on_stale, _calib_from_off, 22),
    ("撤销里恢复扭矩（原来上着力）", _prep_calibrated_stale, _undo, 22),
]


class EveryTorquePathTest(SimBase):
    def test_every_path_writes_gains_before_torque(self):
        for name, prep, act, sid in PATHS:
            with self.subTest(path=name):
                s = self.open()
                if prep:
                    prep(self, s)
                rec = Recorder(s.sim_serial)
                act(self, s)
                sv = self.sim(s, sid)
                self.assertEqual(sv.r[40], 1, name)
                self.assertEqual(run_gains(sv), (5, 0, 1000), name)
                on = rec.first_torque_on(sid)
                self.assertIsNotNone(on, name)
                g = rec.gains_writes(sid)
                self.assertTrue(g and g[0] < on, f"{name}：P/D/限力 {g} 要在开扭矩 {on} 之前写")
                self.assertEqual((sv.r[21], sv.r[22], sv.r[55]), (32, 40, 1), name)    # EEPROM untouched, locked

    def test_every_path_refuses_torque_when_readback_wrong(self):
        for name, prep, act, sid in PATHS:
            with self.subTest(path=name):
                s = self.open()
                if prep:
                    prep(self, s)
                sv = self.sim(s, sid)
                sv.r[50] = 32
                sv.readonly = {50}                   # P can't be written (the two "was holding torque" paths: calibration / undo turn torque off first, then get stuck on restore)
                rec = Recorder(s.sim_serial)
                act(self, s)
                self.assertEqual(sv.r[40], 0, f"{name}：P 写不进去，不该上力")
                self.assertIsNone(rec.first_torque_on(sid), name)
                errs = s.log.recent(cats=["总线"], min_level="error")
                self.assertTrue(any(f"#{sid}" in e["msg"] and "50（P）" in e["msg"] for e in errs), (name, errs))

    def test_all_torque_writes_go_through_gains(self):
        """grep once: the only places in the servo page that write 1 to the torque switch are the sync_write in torque_on_aligned and _gains_then_torque
        (any new torque-enable path added later must either go through these two or be added here and write P/D/torque limit first)."""
        import re
        on = re.compile(r"write_u8\([^()]*,\s*40,\s*1\)|sync_write\(40,\s*1,.*(bytes\(\[1\]\)|b\"\\x01\")")
        hits = []
        for f in ("servo_ops.py", "servo.py"):
            src = (HERE.parent / "studio" / f).read_text(encoding="utf-8")
            hits += [f"{f}: {ln.strip()}" for ln in src.splitlines() if on.search(ln)]
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(any("_ack(self.bus.write_u8(i, 40, 1))" in h for h in hits), hits)
        self.assertTrue(any("sync_write(40, 1, [(i, bytes([1])) for i in on])" in h for h in hits), hits)


if __name__ == "__main__":
    unittest.main()
