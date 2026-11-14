# -*- coding: utf-8 -*-
"""Angles at which leg joints "rotate until parts collide" + whether the official poses press parts against each other.

Used to find mechanical reference points for zero-position calibration: when the duck is folded, which joint is stopped by what, and at how many degrees.
MuJoCo only does forward kinematics (where each part is); whether parts touch is computed by fcl as exact intersection on the raw triangle meshes;
MuJoCo's own collision treats meshes as convex hulls, "fatter" than the real parts, so the computed contact angles come out too small.

  python fold_contact.py --mjcf <microduck_rl>/src/mjlab_microduck/robot/microduck/robot_walk.xml
  python fold_contact.py --mjcf ... --json out.json

Dependencies: mujoco, python-fcl, numpy (pip install mujoco python-fcl numpy).
Geometry pairs that already interpenetrate at the zero position (legs straight) are treated as assembly relationships (servo mounted in a bracket, bearing in a seat) and excluded from the scan.
The official model is the original XL330 geometry; the Feetech version changed 8 mating parts, so the numbers need to be recomputed with the Feetech model.
"""
import argparse
import json
import math
import sys
import time

import fcl
import mujoco
import numpy as np

# keyframe from microduck_rl scene.xml (d424a0c), 14 joints in MJCF order
JOINTS = ["left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
          "neck_pitch", "head_pitch", "head_yaw", "head_roll",
          "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle"]
KEYFRAMES = {
    "STAND": [0, -0.08726646259971647, -0.457924, -0.004940, 0.452984,
              0.3490658503988659, 0.3490658503988659, 0, 0,
              0, 0.08726646259971647, 0.457924, 0.004940, -0.452984],
    "SIT": [0, 0, -0.5236, 1.0472, 0, 0.5, 1.6, 0, 0, 0, 0, 0.5236, -1.0472, 0],
    "FOLD": [0, 0, 1.57, 1.57, 0, 1, 1, 0, 0, 0, 0, -1.57, -1.57, 0],
}


class Model:
    def __init__(self, path):
        self.m = mujoco.MjModel.from_xml_path(path)
        self.d = mujoco.MjData(self.m)
        m = self.m
        # Use only the visual meshes (group 2): they match the real parts' shapes; group 3 is the simplified collision geometry used for training
        self.geoms = [g for g in range(m.ngeom) if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH
                      and m.geom_group[g] == 2 and m.geom_dataid[g] >= 0]
        self.bvh = {}
        for g in self.geoms:
            mid = m.geom_dataid[g]
            v = m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid] + m.mesh_vertnum[mid]].astype(np.float64)
            f = m.mesh_face[m.mesh_faceadr[mid]:m.mesh_faceadr[mid] + m.mesh_facenum[mid]].astype(np.int32)
            b = fcl.BVHModel()
            b.beginModel(len(v), len(f))
            b.addSubModel(v, f)
            b.endModel()
            self.bvh[g] = b
        self.q0 = m.qpos0.copy()
        self.baseline = {p for p in self.pairs(self.q0, self.geoms, self.geoms)}

    def name(self, obj, i):
        return mujoco.mj_id2name(self.m, obj, i)

    def label(self, g):
        m = self.m
        return f"{self.name(mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[g])}/{self.name(mujoco.mjtObj.mjOBJ_MESH, m.geom_dataid[g])}"

    def qadr(self, joint):
        return self.m.jnt_qposadr[mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_JOINT, joint)]

    def with_joints(self, values, base=None):
        q = (self.q0 if base is None else base).copy()
        for j, v in values.items():
            q[self.qadr(j)] = v
        return q

    def objects(self, q):
        self.d.qpos[:] = q
        mujoco.mj_kinematics(self.m, self.d)
        return {g: fcl.CollisionObject(self.bvh[g], fcl.Transform(self.d.geom_xmat[g].reshape(3, 3).copy(),
                                                                  self.d.geom_xpos[g].copy()))
                for g in self.geoms}

    def pairs(self, q, set_a, set_b, skip=()):
        """Geometry pairs from set_a × set_b that interpenetrate across parts (different bodies) at pose q."""
        objs = self.objects(q)
        out = set()
        for a in set_a:
            for b in set_b:
                p = (min(a, b), max(a, b))
                if a == b or p in out or p in skip or self.m.geom_bodyid[a] == self.m.geom_bodyid[b]:
                    continue
                if fcl.collide(objs[a], objs[b], fcl.CollisionRequest(), fcl.CollisionResult()) > 0:
                    out.add(p)
        return out

    def subtree_geoms(self, joint):
        m = self.m
        root = m.jnt_bodyid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, joint)]
        bodies = {root}
        grew = True
        while grew:
            grew = False
            for b in range(1, m.nbody):
                if m.body_parentid[b] in bodies and b not in bodies:
                    bodies.add(b)
                    grew = True
        return {g for g in self.geoms if m.geom_bodyid[g] in bodies}

    def sweep(self, joint, sign, base, max_deg=180.0, step=0.25, tol=0.05):
        """Rotate joint from base in the sign direction; return (angle in ° at first contact, the part contacted); None if no contact after max_deg."""
        distal = self.subtree_geoms(joint)
        proximal = set(self.geoms) - distal
        adr = self.qadr(joint)
        start = base[adr]

        def hits(deg):
            q = base.copy()
            q[adr] = start + sign * math.radians(deg)
            return self.pairs(q, distal, proximal, self.baseline)

        prev, a = 0.0, 0.0
        while a <= max_deg:
            if hits(a):
                lo, hi = prev, a
                while hi - lo > tol:
                    mid = (lo + hi) / 2
                    if hits(mid):
                        hi = mid
                    else:
                        lo = mid
                who = sorted({(self.label(x), self.label(y)) for x, y in hits(hi)})
                return math.degrees(start) + sign * hi, who
            prev, a = a, a + step
        return None, []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mjcf", required=True, help="robot_walk.xml（或同结构的模型）")
    ap.add_argument("--json", help="结果另存 JSON")
    a = ap.parse_args()
    t0 = time.time()
    mdl = Model(a.mjcf)
    out = {"mjcf": a.mjcf, "baseline_pairs": sorted((mdl.label(x), mdl.label(y)) for x, y in mdl.baseline),
           "sweeps": {}, "keyframes": {}}
    print(f"零位时就穿插的装配件对 {len(mdl.baseline)} 个（舵机在支架里、轴承在座里），扫描时排除")

    def record(key, res):
        ang, who = res
        out["sweeps"][key] = {"deg": None if ang is None else round(ang, 2), "contact": who[:3]}
        print(f"  {key}：" + ("转满 180° 没碰上" if ang is None else f"{ang:+.2f}°  碰上 {who[:2]}"))

    for side, s in (("left", +1), ("right", -1)):   # s = fold direction of the official FOLD
        print(f"== {side} 腿（折叠方向 {s:+d}）")
        knee = mdl.sweep(f"{side}_knee", s, mdl.q0)
        record(f"{side}.膝折叠（髋、踝 0°）", knee)
        base = mdl.with_joints({f"{side}_hip_pitch": s * 1.57})
        record(f"{side}.膝折叠（髋 {s * 90:+d}°、踝 0°，即官方 FOLD 的髋）", mdl.sweep(f"{side}_knee", s, base))
        if knee[0] is not None:
            qk = mdl.with_joints({f"{side}_knee": math.radians(knee[0] - s * 0.1)})
            hip = mdl.sweep(f"{side}_hip_pitch", s, qk)
            record(f"{side}.髋 pitch 折叠（膝已折到底）", hip)
            if hip[0] is not None:
                qh = qk.copy()
                qh[mdl.qadr(f"{side}_hip_pitch")] = math.radians(hip[0] - s * 0.1)
                record(f"{side}.踝 +（膝、髋都折到底）", mdl.sweep(f"{side}_ankle", +1, qh))
                record(f"{side}.踝 −（膝、髋都折到底）", mdl.sweep(f"{side}_ankle", -1, qh))

    # Neck: the official FOLD has neck / head pitch both at 1 rad (57°). Check whether that's a contact point: starting from legs folded and head/neck at 0°, rotate the neck toward FOLD's direction (+)
    print("== 颈（腿按官方 FOLD 折好）")
    fold = mdl.with_joints(dict(zip(JOINTS, KEYFRAMES["FOLD"])))
    for head, rad in (("0°", 0.0), ("57°，官方 FOLD 的头", 1.0)):
        q = fold.copy()
        q[mdl.qadr("neck_pitch")] = 0.0
        q[mdl.qadr("head_pitch")] = rad
        record(f"颈 pitch 往 FOLD 方向（头 pitch {head}）", mdl.sweep("neck_pitch", +1, q))

    print("== 官方姿势：零件会不会顶在一起")
    for key, vals in KEYFRAMES.items():
        q = mdl.with_joints(dict(zip(JOINTS, vals)))
        bad = mdl.pairs(q, mdl.geoms, mdl.geoms, mdl.baseline)
        who = sorted({(mdl.label(x), mdl.label(y)) for x, y in bad})
        out["keyframes"][key] = who
        print(f"  {key}：" + (f"穿插 {len(who)} 对 {who[:3]}" if who else "不穿插"))
    print(f"用时 {time.time() - t0:.0f} s")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
