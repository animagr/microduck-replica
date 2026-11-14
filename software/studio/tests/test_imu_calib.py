"""Pure computation of IMU standing calibration (studio/imu_calib.py).

Synthetic data: random mounting orientation + reading noise + a human hand tilting imprecisely, to see whether it can be recovered; insufficient tilt and self-contradictory directions must be judged as failures.
Also uses the real-hardware recording now-20261018.jsonl to verify two conventions: quaternion [w,x,y,z] (body → world), safety.gravity = R(q)ᵀ·(0,0,-1).
"""
import json
import math
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from studio import imu_calib as ic  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
HZ = 10


def q_axis(axis, deg):
    a = ic.unit(axis)
    h = math.radians(deg) / 2
    return ic.q_normalize((math.cos(h), a[0] * math.sin(h), a[1] * math.sin(h), a[2] * math.sin(h)))


def q_random(rng):
    q = [rng.gauss(0, 1) for _ in range(4)]
    return ic.q_normalize(q)


def q_diff_deg(a, b):
    return ic.q_angle_deg(ic.q_mul(ic.q_conj(a), b))


def jitter(rng, g, sigma_deg):
    """Add a bit of noise to a direction (Gaussian per axis, σ given as an angle)."""
    s = math.radians(sigma_deg)
    return ic.unit(ic.add(g, (rng.gauss(0, s), rng.gauss(0, s), rng.gauss(0, s))))


class Duck:
    """Synthesize a duck: world frame z up; body attitude at HOME is stance (body → world); the chip is mounted per mount (chip → body).
    A human hand tilts the whole duck about a horizontal world axis: forward tilt = rotate +θ about +y (head down), left tilt = rotate −θ about +x (left side down).
    skew: the hand isn't aligned, so the tilt axis is off by a few degrees about the vertical.
    hand: after lifting, the small rotation between the hand's "zero" and standing on the table (nobody can hold it exactly level)."""

    def __init__(self, mount, stance=(1.0, 0.0, 0.0, 0.0), old_mount=None, noise_deg=0.15, seed=1, hand=(1.0, 0.0, 0.0, 0.0)):
        self.mount, self.stance, self.hand = mount, stance, hand
        self.old = old_mount
        self.rng = random.Random(seed)
        self.noise = noise_deg

    def reading(self, q_wb):
        g_b = ic.gravity_from_quat(q_wb)                                    # gravity in the body frame
        g_s = ic.mat_vec(ic.mat_t(ic.mat_from_q(self.mount)), g_b)          # chip frame
        if self.old is None:
            return g_s
        return ic.q_rotate(self.old, g_s)                                    # converted to the "old body frame" using the old orientation (like robot.state)

    def pose(self, step, deg, skew=0.0):
        if step == "still":
            return self.stance
        axis = {"fwd": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}[step]
        axis = ic.q_rotate(q_axis((0, 0, 1), skew), axis)
        return ic.q_mul(q_axis(axis, deg), ic.q_mul(self.hand, self.stance))

    def samples(self, step, deg=18.0, skew=0.0, seconds=None, ramp=True, noise=None, pause=0.0, overshoot=0.0):
        """Readings for one step: (lift and hold level for pause seconds) → slowly tilt over (ramp) → (overshoot by overshoot° and come back) → hold for 1 second."""
        noise = self.noise if noise is None else noise
        out = []
        if step == "still":
            n = int((seconds or 3.0) * HZ)
            for i in range(n):
                out.append({"t": i / HZ, "g": list(jitter(self.rng, self.reading(self.stance), noise))})
            return out
        for i in range(int(pause * HZ)):
            out.append({"g": list(jitter(self.rng, self.reading(self.pose(step, 0.0, skew)), noise))})
        n_ramp = 8 if ramp else 0
        for i in range(n_ramp):
            d = deg * (i + 1) / (n_ramp + 1)
            out.append({"t": i / HZ, "g": list(jitter(self.rng, self.reading(self.pose(step, d, skew)), noise))})
        for d in ((deg + overshoot, deg + overshoot * 0.5) if overshoot else ()):
            out.append({"g": list(jitter(self.rng, self.reading(self.pose(step, d, skew)), noise))})
        for i in range(int((seconds or 1.0) * HZ)):
            out.append({"t": (n_ramp + i) / HZ, "g": list(jitter(self.rng, self.reading(self.pose(step, deg, skew)), noise))})
        return out

    def run(self, tilts=None, skews=None, **kw):
        tilts = tilts or {}
        skews = skews or {}
        return {k: self.samples(k, deg=tilts.get(k, 18.0), skew=skews.get(k, 0.0), **kw) for k in ic.STEPS}


class Helpers(unittest.TestCase):
    def test_quat_matrix_roundtrip(self):
        rng = random.Random(7)
        for _ in range(200):
            q = q_random(rng)
            self.assertLess(q_diff_deg(q, ic.q_from_mat(ic.mat_from_q(q))), 1e-6)

    def test_q_between(self):
        rng = random.Random(8)
        for _ in range(100):
            a = ic.unit((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
            b = ic.unit((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
            self.assertLess(ic.angle_deg(ic.q_rotate(ic.q_between(a, b), a), b), 1e-6)
        self.assertLess(ic.angle_deg(ic.q_rotate(ic.q_between((0, 0, 1), (0, 0, -1)), (0, 0, 1)), (0, 0, -1)), 1e-6)

    def test_describe_standard_mounts(self):
        d = ic.describe_mount((1, 0, 0, 0))
        self.assertEqual(d["text"], "芯片 x 朝前，芯片 y 朝左，芯片 z 朝上")
        self.assertLess(d["off_deg"], 1e-6)
        self.assertEqual(len(ic.STANDARD_MOUNTS), 24)
        # Rotate 90° about y: chip x → body down, z → body forward
        d = ic.describe_mount(q_axis((0, 1, 0), 90))
        self.assertEqual(d["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")
        d = ic.describe_mount(ic.q_mul(q_axis((0, 1, 0), 90), q_axis((1, 0, 0), 7)))
        self.assertAlmostEqual(d["off_deg"], 7.0, places=3)

    def test_sample_formats(self):
        g = ic.unit((0.1, -0.2, -0.97))
        self.assertLess(ic.angle_deg(ic.sample_gravity({"g": g}), g), 1e-9)
        self.assertLess(ic.angle_deg(ic.sample_gravity(list(g)), g), 1e-9)
        self.assertLess(ic.angle_deg(ic.sample_gravity({"acc": ic.scale(g, -9.81)}), g), 1e-9)
        self.assertLess(ic.angle_deg(ic.sample_gravity({"quat": ic.q_between(g, ic.DOWN)}), g), 1e-6)
        self.assertIsNone(ic.sample_gravity({"g": [0, 0, 0]}))
        self.assertIsNone(ic.sample_gravity({"quat": [1, 2]}))
        self.assertIsNone(ic.sample_gravity("x"))

    def test_tilt_of_directions(self):
        g0 = ic.DOWN
        for step, want in (("fwd", 0), ("left", 90), ("back", 180), ("right", -90)):
            duck = Duck((1, 0, 0, 0), noise_deg=0)
            g = duck.reading(duck.pose(step, 15))
            t, d = ic.tilt_of(g0, g)
            self.assertAlmostEqual(t, 15, places=6)
            self.assertAlmostEqual(abs(((d - want) + 180) % 360 - 180), 0, places=6, msg=step)


class RealData(unittest.TestCase):
    """Real-hardware recording: are the conventions right."""

    def rows(self):
        out = []
        for line in FIXTURE.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("kind") == "notify" and (r.get("msg") or {}).get("method") == "robot.state":
                out.append(r["msg"]["params"])
        return out

    def test_gravity_is_projected_quat_wxyz(self):
        rows = self.rows()
        self.assertGreater(len(rows), 20)
        # robotd's gravity is the median of the last 3 readings (official duck-control/src/imu.rs:140-155), so it differs slightly from the quaternion at this instant:
        # at most 0.08° in the recording. If the convention were wrong (xyzw, or rotation reversed) it would be off by degrees to tens of degrees
        exact = 0
        for p in rows:
            g = ic.gravity_from_quat(p["imu"]["quat"])
            d = ic.angle_deg(g, p["safety"]["gravity"])
            self.assertLess(d, 0.25)
            exact += d < 1e-3
        self.assertGreater(exact, 0)
        wrong = ic.gravity_from_quat([rows[0]["imu"]["quat"][i] for i in (1, 2, 3, 0)])       # read as xyzw
        self.assertGreater(ic.angle_deg(wrong, rows[0]["safety"]["gravity"]), 5)      # actually 17° off

    def test_still_on_real_standing_data(self):
        rows = self.rows()
        st, g0 = ic.check_still([{"g": p["safety"]["gravity"]} for p in rows])
        self.assertTrue(st["ok"], st)
        self.assertLess(st["spread_deg"], 0.2)
        self.assertAlmostEqual(ic.tilt_of(ic.DOWN, g0)[0], 2.6, delta=0.2)   # consistent with home_start_guard.tilt_deg 2.63°


class Solve(unittest.TestCase):
    def assertMount(self, res, want, tol):
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], want), tol, res)

    def test_sensor_frame_random_mounts_exact(self):
        rng = random.Random(11)
        for i in range(30):
            mount = q_random(rng)
            res = ic.solve(Duck(mount, noise_deg=0.0, seed=i).run(), frame="sensor")
            self.assertMount(res, mount, 0.01)
            self.assertEqual(res["quality"]["grade"], "good")

    def test_sensor_frame_noise_and_human_error(self):
        rng = random.Random(12)
        worst = 0.0
        for i in range(40):
            mount = q_random(rng)
            skews = {k: rng.uniform(-5, 5) for k in ic.TILTS}
            tilts = {k: rng.uniform(12, 28) for k in ic.TILTS}
            res = ic.solve(Duck(mount, noise_deg=0.3, seed=100 + i).run(tilts, skews), frame="sensor")
            self.assertTrue(res["ok"], res.get("reason"))
            worst = max(worst, q_diff_deg(res["mount"], mount))
        self.assertLess(worst, 5.0)        # ±5° hand skew over four steps partly cancels out; only heading has error, up/down is set by rest and is very accurate

    def test_body_frame_corrects_old_mount(self):
        """robot.state readings already have the old orientation applied: correction ∘ old orientation = true orientation; an 8.5° crooked mount can be computed."""
        rng = random.Random(13)
        for i in range(20):
            mount = q_random(rng)
            err = q_axis((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)), rng.uniform(0, 12))
            old = ic.q_normalize(ic.q_mul(err, mount))
            res = ic.solve(Duck(mount, old_mount=old, noise_deg=0.0, seed=i).run(), frame="body", old_mount=old)
            self.assertMount(res, mount, 0.01)
            self.assertAlmostEqual(res["parts"]["total_deg"], ic.q_angle_deg(err), delta=0.01)
        # Only mounted 8.5° crooked forward (the case of duck #1's lunge on Oct 12): the extracted forward tilt ≈ 8.5°, heading ≈ 0
        mount = q_axis((0, 1, 0), 90)
        old = ic.q_normalize(ic.q_mul(q_axis((0, 1, 0), -8.5), mount))
        res = ic.solve(Duck(mount, old_mount=old, noise_deg=0.0).run(), frame="body", old_mount=old)
        self.assertMount(res, mount, 0.01)
        self.assertAlmostEqual(res["parts"]["pitch_deg"], 8.5, delta=0.05)
        self.assertAlmostEqual(res["parts"]["yaw_deg"], 0.0, delta=0.05)
        self.assertTrue(res["confirm"])                    # 8.5° > 8°: needs human confirmation
        self.assertEqual(res["standard"]["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")

    def test_small_correction_needs_no_confirm(self):
        mount = q_axis((0, 1, 0), 90)
        old = ic.q_normalize(ic.q_mul(q_axis((1, 0, 0), 2.0), mount))
        res = ic.solve(Duck(mount, old_mount=old).run(), frame="body", old_mount=old)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["confirm"], [])

    def test_stance_tilt_is_folded_in(self):
        """At HOME the body actually tilts 4° forward (because of the legs): after overall compensation, the reading when standing = official HOME (level)."""
        mount = q_axis((0, 0, 1), 30)
        stance = q_axis((0, 1, 0), 4.0)
        res = ic.solve(Duck(mount, stance=stance, noise_deg=0.0).run(), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        g_still_sensor = ic.mat_vec(ic.mat_t(ic.mat_from_q(mount)), ic.gravity_from_quat(stance))
        self.assertLess(ic.angle_deg(ic.q_rotate(res["mount"], g_still_sensor), ic.DOWN), 1e-6)
        # Heading is unaffected: in the new body frame forward tilt is still toward +x
        g_fwd = ic.mat_vec(ic.mat_t(ic.mat_from_q(mount)), ic.gravity_from_quat(ic.q_mul(q_axis((0, 1, 0), 18), stance)))
        g_new = ic.q_rotate(res["mount"], g_fwd)
        self.assertGreater(g_new[0], 0.25)
        self.assertLess(abs(g_new[1]), 1e-6)

    def test_home_gravity_not_level(self):
        """The official HOME body already tilts 3° forward, and the duck stands exactly like that: the true orientation is recovered as is."""
        rng = random.Random(14)
        stance = q_axis((0, 1, 0), 3.0)
        hg = ic.gravity_from_quat(stance)
        for i in range(10):
            mount = q_random(rng)
            res = ic.solve(Duck(mount, stance=stance, noise_deg=0.0, seed=i).run(), frame="sensor", home_gravity=hg)
            self.assertMount(res, mount, 0.01)

    def test_flat_list_same_as_dict(self):
        data = Duck(q_axis((1, 1, 0), 40)).run()
        flat = [dict(s, step=k) for k in ic.STEPS for s in data[k]]
        a, b = ic.solve(data, frame="sensor"), ic.solve(flat, frame="sensor")
        self.assertEqual(a["mount"], b["mount"])

    def test_acc_and_quat_inputs_match(self):
        data = Duck(q_axis((0, 1, 1), 70), noise_deg=0.2).run()
        acc = {k: [{"acc": list(ic.scale(s["g"], -9.81))} for s in v] for k, v in data.items()}
        quat = {k: [{"quat": list(ic.q_between(s["g"], ic.DOWN))} for s in v] for k, v in data.items()}
        r0, r1, r2 = (ic.solve(d, frame="sensor") for d in (data, acc, quat))
        self.assertLess(q_diff_deg(r0["mount"], r1["mount"]), 1e-6)
        self.assertLess(q_diff_deg(r0["mount"], r2["mount"]), 1e-4)

    def test_result_is_json(self):
        res = ic.solve(Duck(q_axis((0, 1, 0), 90), old_mount=(1, 0, 0, 0)).run(), frame="body", old_mount=(1, 0, 0, 0))
        json.dumps(res, ensure_ascii=False)


class Fails(unittest.TestCase):
    mount = q_axis((0, 1, 0), 90)

    def solve(self, data):
        return ic.solve(data, frame="sensor")

    def test_tilt_too_small(self):
        res = self.solve(Duck(self.mount).run(tilts={"fwd": 6}))
        self.assertFalse(res["ok"])
        self.assertFalse(res["steps"]["fwd"]["ok"])
        self.assertIn("前倾", res["reason"])
        self.assertIn("至少", res["reason"])

    def test_tilt_too_big(self):
        res = self.solve(Duck(self.mount).run(tilts={"left": 45}))
        self.assertFalse(res["ok"])
        self.assertIn("太多", res["steps"]["left"]["msg"])

    def test_still_not_still(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["still"] = duck.samples("still", noise=2.0)
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("晃", res["reason"])

    def test_still_too_short(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["still"] = duck.samples("still", seconds=0.8)
        self.assertFalse(self.solve(data)["ok"])

    def test_missing_step(self):
        data = Duck(self.mount).run()
        data["right"] = []
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("右倾", res["reason"])

    def test_not_held_still(self):
        """Tilted to 18° and came right back without holding: only one or two readings near the maximum tilt."""
        duck = Duck(self.mount)
        data = duck.run()
        swing = [2, 4, 6, 8, 10, 12, 14, 16, 18, 16, 14, 12, 10, 8, 6, 4, 2]
        data["back"] = [{"g": list(duck.reading(duck.pose("back", d)))} for d in swing]
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("没停住", res["steps"]["back"]["msg"])

    def test_circling_not_held(self):
        """Tilt stays at 15°, but the direction circles around: enough tilt and enough held readings, but the direction wobbles too much."""
        duck = Duck(self.mount)
        data = duck.run()
        data["fwd"] = [{"g": list(duck.reading(duck.pose("fwd", 15, skew=s)))} for s in range(-30, 31, 5)]
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("没停住", res["steps"]["fwd"]["msg"])

    def test_same_side_twice(self):
        """The "后倾" (tilt back) step actually tilted forward again."""
        duck = Duck(self.mount)
        data = duck.run()
        data["back"] = duck.samples("fwd")
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("前倾和后倾", res["reason"])

    def test_left_right_swapped(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("做反了", res["reason"])
        # When the old orientation is trustworthy (frame=body) it can say which pair was done backwards
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount)
        self.assertFalse(res["ok"])
        self.assertIn("左倾、右倾做反了", res["reason"])

    def test_tilted_diagonally(self):
        """Left tilt and right tilt are both 30° off (each step only 15° off, but the two pairs differ by 30°): front-back and left-right aren't perpendicular."""
        res = self.solve(Duck(self.mount).run(skews={"left": 30, "right": 30}))
        self.assertFalse(res["ok"])
        self.assertIn("不垂直", res["reason"])

    def test_turned_around_needs_confirm(self):
        """Front-back and left-right both done backwards (the duck turned around): the self-check can't detect it, but compared with the old orientation the heading changed by 180°, so it needs human confirmation."""
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["fwd"], data["back"] = duck.samples("back"), duck.samples("fwd")
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(abs(res["parts"]["yaw_deg"]), 170)
        self.assertTrue(any("转了个身" in c for c in res["confirm"]))

    def test_body_frame_without_old_mount(self):
        res = ic.solve(Duck(self.mount, old_mount=self.mount).run(), frame="body")
        self.assertTrue(res["ok"])
        self.assertNotIn("mount", res)
        self.assertTrue(res["notes"])

    def test_bad_frame(self):
        with self.assertRaises(ValueError):
            ic.solve({}, frame="world")
        with self.assertRaises(ValueError):
            ic.solve({}, mode="quick")


class RobotdFormula(unittest.TestCase):
    """A1: synthesize readings exactly like the fork firmware robotd's TrunkFrame::push (duck-control/src/imu.rs:137-170):
        q_body = q_chip ⊗ mount⁻¹, gravity = rotate_inverse(q_body, [0,0,-1]) = q⁻¹·v·q.
    Quaternion multiplication and rotation are written separately here, not using the code under test's q_mul / q_rotate / gravity_from_quat."""

    @staticmethod
    def hmul(a, b):                       # Hamilton product, written term by term like the textbook
        w1, x1, y1, z1 = a
        w2, x2, y2, z2 = b
        return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)

    @staticmethod
    def conj(q):
        return (q[0], -q[1], -q[2], -q[3])

    @classmethod
    def rotate_inverse(cls, q, v):        # q⁻¹ · (0, v) · q
        r = cls.hmul(cls.hmul(cls.conj(q), (0.0, v[0], v[1], v[2])), q)
        return r[1:]

    @staticmethod
    def axis_angle(axis, deg):
        n = math.sqrt(sum(a * a for a in axis))
        h = math.radians(deg) / 2
        return (math.cos(h),) + tuple(a / n * math.sin(h) for a in axis)

    @staticmethod
    def norm4(q):
        n = math.sqrt(sum(c * c for c in q))
        return tuple(c / n for c in q)

    def test_robotd_pipeline_any_old_mount(self):
        rng = random.Random(31)
        worst = 0.0
        for _ in range(60):
            true_mount = self.norm4([rng.gauss(0, 1) for _ in range(4)])     # chip → body (the true one)
            stored = self.norm4([rng.gauss(0, 1) for _ in range(4)])         # what's stored on the duck (any amount of error is fine)
            stance = self.axis_angle((0, 0, 1), rng.uniform(-180, 180))       # standing: level, any yaw

            def reading(q_trunk_world):
                q_sensor_world = self.hmul(q_trunk_world, true_mount)         # chip attitude = body attitude ⊗ chip→body
                q_trunk_robotd = self.hmul(q_sensor_world, self.conj(stored))  # robotd: q_chip ⊗ mount⁻¹
                g = self.rotate_inverse(q_trunk_robotd, (0.0, 0.0, -1.0))
                # Also check the convention of the code under test while we're at it: gravity_from_quat agrees with rotate_inverse
                self.assertLess(ic.angle_deg(g, ic.gravity_from_quat(q_trunk_robotd)), 1e-4)   # acos near 0 is only accurate to ~1e-6°
                return {"g": list(g)}

            data = {"still": [reading(stance)] * 20}
            for k, ax in {"fwd": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}.items():
                ax_w = self.rotate_inverse(self.conj(stance), ax)              # this body axis in the world (q·v·q⁻¹)
                data[k] = [reading(self.hmul(self.axis_angle(ax_w, 18), stance))] * 10
            res = ic.solve(data, frame="body", old_mount=stored, old_verified=False)
            self.assertTrue(res["ok"], res.get("reason"))
            d = abs(sum(a * b for a, b in zip(res["mount"], true_mount)))
            worst = max(worst, math.degrees(2 * math.acos(min(1.0, d))))
        self.assertLess(worst, 0.01)          # rounding error from a dozen or so chained multiplications, amplified by acos near 1

    def test_default_mounts_in_words(self):
        # BNO08x default: trunk_imu.rs:63 "mounted sensor X left, Y up, Z forward"
        self.assertEqual(ic.describe_mount([0.5, 0.5, 0.5, 0.5])["text"], "芯片 x 朝左，芯片 y 朝上，芯片 z 朝前")
        # Bus board default: official imu.rs:76 "trunk = [+raw_z, +raw_y, −raw_x]"
        r = math.sqrt(0.5)
        self.assertEqual(ic.describe_mount([r, 0, r, 0])["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")
        # What duck #2 currently has stored (fixture line 6): standard mounting plus a 6° offset
        d = ic.describe_mount([0.698208849, 0.036261753, 0.714055021, 0.036261753])
        self.assertEqual(d["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")
        self.assertAlmostEqual(d["off_deg"], 6.0, delta=0.1)


class HumanHandling(unittest.TestCase):
    """A2: situations that come up with a real human hand."""
    mount = q_axis((0, 1, 0), 90)

    def test_overshoot_then_settle(self):
        """Overshoot by 4° and come back to hold: only the held segment after coming back counts."""
        res = ic.solve(Duck(self.mount, noise_deg=0.2).run(overshoot=4.0), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], self.mount), 1.0)
        self.assertAlmostEqual(res["steps"]["fwd"]["tilt_deg"], 18, delta=0.6)

    def test_overshoot_reviewer_case(self):
        """The reviewer's example: tilt to 21°, come back to 17° and hold for 1.5 seconds (previously judged "only 1 reading")."""
        g = lambda d: {"g": list(ic.gravity_from_quat(q_axis((0, 1, 0), d)))}
        still = [g(0)] * 30
        step = lambda ax, d, n=15: [{"g": list(ic.gravity_from_quat(q_axis(ax, d)))}] * n
        data = {"still": still, "fwd": [g(x) for x in (4, 8, 12, 16, 19, 21, 19)] + [g(17)] * 15,
                "back": step((0, -1, 0), 17), "left": step((-1, 0, 0), 17), "right": step((1, 0, 0), 17)}
        res = ic.solve(data, frame="body", old_mount=(1, 0, 0, 0))
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertAlmostEqual(res["steps"]["fwd"]["tilt_deg"], 17, delta=0.01)

    def test_single_spike(self):
        """A glitchy frame mixed into the hold (the BNO085 kind), whether in the middle or at the end, should not be judged a failure."""
        duck = Duck(self.mount, noise_deg=0.1)
        data = duck.run()
        spike = {"g": list(duck.reading(duck.pose("fwd", 33)))}
        data["fwd"] = data["fwd"][:13] + [spike] + data["fwd"][13:]
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["steps"]["fwd"]["skipped"], 1)
        data["back"] = data["back"] + [{"g": list(duck.reading(duck.pose("back", 33)))}]
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], self.mount), 0.5)

    def test_hand_reference_offset(self):
        """The hand's zero is off by 4.9° when lifted (holding level only requires within 5°): each step uses its own level moment as zero, so it's no longer judged as "tilting at an angle"."""
        rng = random.Random(41)
        for i in range(20):
            hand = q_axis((rng.gauss(0, 1), rng.gauss(0, 1), 0), 4.9)
            mount = q_random(rng)
            duck = Duck(mount, noise_deg=0.0, seed=i, hand=hand)
            res = ic.solve(duck.run(tilts={"fwd": 13, "back": 13, "left": 13, "right": 13}, pause=0.8), frame="sensor")
            self.assertTrue(res["ok"], res.get("reason"))
            self.assertEqual(res["steps"]["fwd"]["ref"], "端平那一下")
            self.assertAlmostEqual(res["steps"]["fwd"]["ref_offset_deg"], 4.9, delta=0.3)   # the level window may include the first reading of the ramp (along the tilt direction, doesn't affect heading)
            self.assertLess(q_diff_deg(res["mount"], mount), 0.3)
            self.assertLess(res["quality"]["max_skew_deg"], 1.0)      # a 4.9° zero offset leaves only a tiny second-order residual

    def test_consistent_twist_fails(self):
        """Forward and backward tilts both twisted by 15° (reviewer's probe3: previously "opposite difference 0" passed with heading off by 7.5°): front-back vs. left-right differ by 15° → judged as failure."""
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"fwd": 15, "back": 15}), frame="sensor")
        self.assertFalse(res["ok"])
        self.assertIn("不垂直", res["reason"])
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"fwd": 5, "back": 5}), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))           # a 5° twist is still usable, heading accurate to about ±2.5°
        self.assertAlmostEqual(res["quality"]["yaw_uncert_deg"], 2.5, delta=0.1)

    def test_tilt_max_by_any_held_reading(self):
        """G6: a single 36° in the held segment already counts as too much (previously passed based on the 34.6° average)."""
        g = lambda ax, d: {"g": list(ic.gravity_from_quat(q_axis(ax, d)))}
        still = [g((0, 1, 0), 0)] * 30
        step = lambda ax, d: [g(ax, d)] * 12
        data = {"still": still, "fwd": step((0, 1, 0), 34.5) + [g((0, 1, 0), 36)],
                "back": step((0, -1, 0), 17), "left": step((-1, 0, 0), 17), "right": step((1, 0, 0), 17)}
        res = ic.solve(data, frame="body", old_mount=(1, 0, 0, 0))
        self.assertFalse(res["ok"])
        self.assertIn("太多", res["reason"])
        self.assertAlmostEqual(res["steps"]["fwd"]["max_tilt_deg"], 36, delta=0.01)

    def test_bad_numbers_dropped(self):
        """G5: inf / nan readings are dropped without crashing."""
        self.assertIsNone(ic.sample_gravity({"g": [float("inf"), 0, -1]}))
        self.assertIsNone(ic.sample_gravity({"g": [float("nan"), 0, -1]}))
        self.assertIsNone(ic.sample_gravity({"acc": [0, float("inf"), 9.8]}))
        self.assertIsNone(ic.sample_gravity({"quat": [float("nan"), 0, 0, 0]}))
        self.assertIsNone(ic.sample_gravity({"g": [1e308, 1e308, 1e308]}))     # squaring overflows to inf
        data = Duck(self.mount).run()
        data["still"] = data["still"][:25] + [{"g": [float("inf"), 0, 0]}] * 10
        data["left"] = data["left"] + [{"g": [float("nan")] * 3}]
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["steps"]["still"]["dropped"], 10)
        self.assertEqual(res["steps"]["left"]["dropped"], 1)
        data["still"] = [{"g": [float("inf"), 0, 0]}] * 30
        res = ic.solve(data, frame="sensor")
        self.assertFalse(res["ok"])
        self.assertIn("静止的读数只有 0 个", res["reason"])

    def test_still_spikes_tolerated(self):
        """Two glitchy frames during the 3 seconds of rest (under 10% of 30 frames): doesn't count as shaking; only a constant 2° wobble does."""
        duck = Duck(self.mount, noise_deg=0.1)
        data = duck.run()
        spike = {"g": list(duck.reading(duck.pose("left", 12)))}
        data["still"][5] = spike
        data["still"][20] = spike
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(res["steps"]["still"]["max_dev_deg"], 10)
        self.assertLess(q_diff_deg(res["mount"], self.mount), 0.5)

    def test_big_stand_offset_needs_confirm(self):
        """G4: while standing, readings more than 5° from HOME (hand pressing at rest, tilted table, legs not calibrated) need human confirmation."""
        duck = Duck(self.mount, stance=q_axis((0, 1, 0), 6.0), old_mount=self.mount, noise_deg=0.0)
        res = ic.solve(duck.run(), frame="body", old_mount=self.mount)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertAlmostEqual(res["parts"]["stand_tilt_deg"], 6.0, delta=0.01)
        self.assertTrue(any("离官方 HOME 差 6.0°" in c for c in res["confirm"]))
        duck = Duck(self.mount, stance=q_axis((0, 1, 0), 4.0), old_mount=self.mount, noise_deg=0.0)
        res = ic.solve(duck.run(), frame="body", old_mount=self.mount)
        self.assertFalse(any("离官方 HOME" in c for c in res["confirm"]))

    def test_flip_after_coarse(self):
        """The old orientation was written by the last coarse calibration: the turned-around hint changes to "上次粗校可能做反了" (the last coarse calibration may have been done backwards)."""
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["fwd"], data["back"] = duck.samples("back"), duck.samples("fwd")
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount, old_source="coarse")
        self.assertTrue(any("上次粗校可能做反了" in c for c in res["confirm"]))


class Redo(unittest.TestCase):
    """When it fails, redo says clearly which steps need redoing (the page only lets the user redo those steps)."""
    mount = q_axis((0, 1, 0), 90)

    def test_each_failure_names_steps(self):
        duck = Duck(self.mount)
        self.assertEqual(ic.solve(duck.run(tilts={"fwd": 6}), frame="sensor")["redo"], ["fwd"])
        data = duck.run()
        data["right"] = []
        self.assertEqual(ic.solve(data, frame="sensor")["redo"], ["right"])
        data = duck.run()
        data["still"] = duck.samples("still", noise=3.0)
        self.assertEqual(ic.solve(data, frame="sensor")["redo"], ["still"])
        data = duck.run()
        data["back"] = duck.samples("fwd")
        self.assertEqual(ic.solve(data, frame="sensor")["redo"], ["fwd", "back"])
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"left": 30}), frame="sensor")
        self.assertFalse(res["ok"])
        self.assertEqual(res["redo"], ["left"])
        self.assertTrue(ic.solve(duck.run(), frame="sensor")["ok"])

    def test_swapped_and_cross_with_and_without_trust(self):
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        self.assertEqual(ic.solve(data, frame="body", old_mount=self.mount)["redo"], ["left", "right"])
        self.assertEqual(ic.solve(data, frame="body", old_mount=self.mount, old_verified=False)["redo"], list(ic.TILTS))
        twisted = Duck(self.mount, old_mount=self.mount, noise_deg=0.0).run(skews={"fwd": 15, "back": 15})
        res = ic.solve(twisted, frame="body", old_mount=self.mount)
        self.assertIn("不垂直", res["reason"])
        self.assertEqual(res["redo"], ["fwd", "back"])
        self.assertEqual(ic.solve(twisted, frame="body", old_mount=self.mount, old_verified=False)["redo"], list(ic.TILTS))


class Coarse(unittest.TestCase):
    """Coarse calibration: when the orientation has never been confirmed and it can't stand up, lift it while limp and do "rest + forward tilt (+ backward tilt)"."""

    def test_still_and_fwd_only(self):
        rng = random.Random(21)
        for i in range(20):
            mount = q_random(rng)
            data = Duck(mount, noise_deg=0.0, seed=i).run()
            res = ic.solve({"still": data["still"], "fwd": data["fwd"]}, frame="sensor", mode="coarse")
            self.assertTrue(res["ok"], res.get("reason"))
            self.assertLess(q_diff_deg(res["mount"], mount), 0.01)
            self.assertEqual(res["quality"]["grade"], "coarse")
            self.assertTrue(any("粗校" in n for n in res["notes"]))

    def test_with_back_and_default_old_mount(self):
        """The LSM6DSV16X's default orientation is the identity quaternion (trunk_imu.rs:56-58), far from the true orientation: if never verified, don't ask for "changed too much" confirmation."""
        mount = q_axis((0, 1, 0), 90)
        old = (1.0, 0.0, 0.0, 0.0)
        data = Duck(mount, old_mount=old, noise_deg=0.2).run()
        part = {k: data[k] for k in ("still", "fwd", "back")}
        res = ic.solve(part, frame="body", old_mount=old, mode="coarse", old_verified=False)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], mount), 1.0)
        # Don't compare the unverified default for "changed too much", but the user must still tick a box after checking the module's actual mounting (if done backwards robotd can't detect left/right, plan S1)
        self.assertEqual(len(res["confirm"]), 1)
        self.assertIn("芯片 x 朝下，芯片 y 朝左，芯片 z 朝前", res["confirm"][0])
        res2 = ic.solve(part, frame="body", old_mount=old, mode="coarse", old_verified=True)
        self.assertEqual(len(res2["confirm"]), 2)

    def test_needs_fwd(self):
        data = Duck(q_axis((0, 1, 0), 90)).run()
        res = ic.solve({"still": data["still"]}, frame="sensor", mode="coarse")
        self.assertFalse(res["ok"])
        self.assertIn("前倾", res["reason"])

    def test_back_same_side_fails(self):
        duck = Duck(q_axis((0, 1, 0), 90))
        res = ic.solve({"still": duck.samples("still"), "fwd": duck.samples("fwd"), "back": duck.samples("fwd")},
                       frame="sensor", mode="coarse")
        self.assertFalse(res["ok"])
        self.assertIn("前倾和后倾", res["reason"])


if __name__ == "__main__":
    unittest.main()
