"""IMU page: end-to-end from frontend sampling (the real code of web/imu.js, run with Node) → backend imu_calib.solve.

tests/imu_wizard_e2e.mjs feeds simulated readings to the page's sampling logic and prints, for each scenario, which steps it recorded, how far it got and what it sampled
(i.e. the list the page would send to imu.op solve); here it is handed to Python to compute, verifying that "whatever the frontend lets through, the backend accepts, and computes correctly".
Requires Node (≥ 20.6) on the computer; skipped without Node (e.g. on the duck). To run on its own:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_imu_wizard_e2e'])"
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from studio import imu_calib as ic  # noqa: E402

NODE = shutil.which("node")
ALL = {"still": True, "fwd": True, "back": True, "left": True, "right": True}


@unittest.skipUnless(NODE, "没装 Node，跳过前端采集的端到端测试")
class CollectToSolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, str(HERE / "imu_wizard_e2e.mjs")], capture_output=True, text=True,
                           encoding="utf-8", timeout=60, cwd=str(HERE.parent))
        if r.returncode != 0:
            raise AssertionError(f"Node 脚本出错：{r.stderr[-2000:]}")
        cls.out = json.loads(r.stdout)
        # The simulated old orientation is wrong by ERR (reading = ERR · true gravity): the correct correction = ERR⁻¹
        err = tuple(tuple(row) for row in cls.out["err"])
        cls.want = ic.q_from_mat(ic.mat_t(err))

    def solve(self, sc, name):
        self.assertEqual(sc["phase"], "solving", f"{name}：停在 {sc['phase']}，记下了 {sc['done']}")
        res = ic.solve(sc["samples"], frame="body", old_mount=(1.0, 0.0, 0.0, 0.0))
        self.assertTrue(res["ok"], f"{name}：前端放行了，后端却判「{res['reason']}」")
        err = ic.q_angle_deg(ic.q_mul(ic.q_conj(res["mount"]), self.want))
        return res, err

    def test_normal_with_duplicates(self):
        sc = self.out["normal"]
        res, err = self.solve(sc, "normal")
        self.assertLess(err, 0.5)
        self.assertAlmostEqual(res["parts"]["pitch_deg"], 3.0, delta=0.3)
        self.assertAlmostEqual(res["parts"]["yaw_deg"], 4.0, delta=0.5)
        # Each frame pushed twice (same state_t_ns): counted only once; one event per completed step (the page uses it to beep), the last one is all
        self.assertEqual(sum(sc["counts"].values()) + sc["seg"], sc["pushed"])
        self.assertEqual(sc["events"], ["still", "fwd", "back", "left", "all"])

    def test_dedupe_without_timestamp(self):
        sc = self.out["normal_nokey"]
        _, err = self.solve(sc, "normal_nokey")
        self.assertLess(err, 0.5)
        self.assertEqual(sum(sc["counts"].values()) + sc["seg"], sc["pushed"])

    def test_any_order(self):
        """Any order: right, back, left, forward."""
        sc = self.out["any_order"]
        _, err = self.solve(sc, "any_order")
        self.assertLess(err, 0.5)
        self.assertEqual(sc["events"], ["still", "right", "back", "left", "all"])

    def test_overshoot(self):
        _, err = self.solve(self.out["overshoot"], "overshoot")
        self.assertLess(err, 0.5)

    def test_spike(self):
        _, err = self.solve(self.out["spike"], "spike")
        self.assertLess(err, 0.5)

    def test_still_spike_not_reset(self):
        """Two glitchy frames at rest: the frontend doesn't restart counting (still passes in about 3 seconds), and the backend accepts it too."""
        _, err = self.solve(self.out["still_spike"], "still_spike")
        self.assertLess(err, 0.5)
        self.assertLessEqual(self.out["still_spike"]["counts"]["still"], 32)

    def test_hand_offset(self):
        res, err = self.solve(self.out["hand_offset"], "hand_offset")
        self.assertLess(err, 1.0)
        self.assertTrue(all(res["steps"][k]["ref"] == "端平那一下" for k in ic.TILTS))

    def test_too_small_not_taken(self):
        sc = self.out["too_small"]
        self.assertEqual(sc["phase"], "collect")
        self.assertEqual(sc["done"], {"still": True, "fwd": False, "back": False, "left": False, "right": False})

    def test_offline_pauses(self):
        sc = self.out["offline"]
        self.assertEqual(sc["phase"], "collect")
        self.assertEqual(sc["counts"]["still"], 0)
        self.assertIn("读数断了", sc["paused"])

    def test_wrong_direction_then_fix(self):
        """The backward tilt step tilts forward again: doesn't count (forward tilt already recorded); clicking finish says backward tilt is missing; sampling another backward tilt completes it and it can be computed."""
        sc = self.out["back_wrong"]
        self.assertEqual(sc["before"]["phase"], "collect")
        self.assertFalse(sc["before"]["done"]["back"])
        self.assertTrue(sc["before"]["done"]["left"] and sc["before"]["done"]["right"])
        self.assertEqual(sc["short"], {"phase": "short", "missing": ["back"]})
        _, err = self.solve(sc["after"], "back_wrong 补完")
        self.assertLess(err, 0.5)

    def test_end_early(self):
        sc = self.out["short"]
        self.assertEqual(sc["phase"], "short")
        self.assertEqual(sc["missing"], ["back", "left", "right"])

    def test_redo_one_step(self):
        """Only redo left tilt: the other steps stay as they were, and it's complete again automatically after redoing."""
        sc = self.out["redo"]
        self.assertEqual(sc["mid"]["phase"], "collect")
        self.assertEqual(sc["mid"]["done"], dict(ALL, left=False))
        self.assertEqual(sc["mid"]["left"], 0)
        self.assertTrue(sc["fwd_kept"])
        res, err = self.solve(sc["after"], "redo")
        self.assertLess(err, 0.5)
        self.assertAlmostEqual(res["steps"]["left"]["tilt_deg"], 18, delta=0.6)


if __name__ == "__main__":
    unittest.main()
