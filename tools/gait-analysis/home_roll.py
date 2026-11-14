"""When standing at HOME, how much the two soles differ in roll (left-right), which joint causes it, and which edge is lower (read-only analysis).
Sole normal = direction of the foot collision box's shortest edge; roll = tilt of the normal in the torso y-z plane (+ = normal leans toward the body's left = sole's left side lower).
Roll difference between feet = left foot roll − right foot roll, **relative to the simulated HOME pose**: in the sim model the two soles already differ by 5.97° at HOME (each outer side about 3° lower,
this is model geometry, see the self-check line at the start), and that baseline is subtracted everywhere below. Readings and HOME targets share the same zero, so zero-position errors can't be seen here.
Joint contribution = change in the difference when only that joint is switched from HOME to the measured value (other joints stay at HOME).
Inner/outer edges = with the torso leveled, the average height of the long edge of the foot collision box's bottom face nearer the body's midline (inner) and farther from it (outer); the collision box is a simplified foot, check the real part for the true situation.
Usage: python home_roll.py MJCF.xml name=recording.jsonl ...   (takes the last 150 frames of each segment with policy=held and torque on, statistics per segment)
     python home_roll.py MJCF.xml name=home-capture.json ...(single frame, field joints15)
"""
import json
import math
import sys

import mujoco
import numpy as np

J14 = ['left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle', 'neck_pitch', 'head_pitch',
       'head_yaw', 'head_roll', 'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle']
HOME = np.array([0.0, -0.0873, -0.4579, -0.0049, 0.453, 0.3491, 0.3491, 0.0, 0.0, 0.0, 0.0873, 0.4579, 0.0049, -0.453])
LEG = {'left': [0, 1, 2, 3, 4], 'right': [9, 10, 11, 12, 13]}
NAME = ['髋偏航', '髋横滚', '髋俯仰', '膝', '踝']
CN = {'left': '左', 'right': '右'}

m = mujoco.MjModel.from_xml_path(sys.argv[1]); d = mujoco.MjData(m)
adr = [m.jnt_qposadr[m.joint(n).id] for n in J14]
gid = {s: m.geom(f'{s}_foot_collision').id for s in ('left', 'right')}
base = m.body('trunk_base').id


def fk(q):
    d.qpos[:] = m.qpos0
    for a, v in zip(adr, q): d.qpos[a] = v
    mujoco.mj_kinematics(m, d)
    return d.xmat[base].reshape(3, 3), d.xpos[base]


def rolls(q):
    Rb, _ = fk(q); out = {}
    for s, g in gid.items():
        R = d.geom_xmat[g].reshape(3, 3); n = Rb.T @ R[:, int(np.argmin(m.geom_size[g]))]
        if n[2] < 0: n = -n
        out[s] = math.degrees(math.atan2(n[1], n[2]))       # + = normal leans toward the body's left = sole's left side lower
    return out


def diff(q):
    r = rolls(q); return r['left'] - r['right']


def edges(q):
    """Average height (mm) of the inner and outer edges of each foot's bottom face, in the torso frame.
    Bottom face = the downward-facing face along the collision box's thinnest direction; inner/outer = whichever of the bottom face's two long left/right edges is nearer / farther from the body's midline."""
    Rb, pb = fk(q); out = {}
    for s, g in gid.items():
        R = Rb.T @ d.geom_xmat[g].reshape(3, 3); c = Rb.T @ (d.geom_xpos[g] - pb); h = m.geom_size[g]
        n = int(np.argmin(h)); down = -1.0 if R[2, n] > 0 else 1.0
        rest = [k for k in range(3) if k != n]
        lat = max(rest, key=lambda k: abs(R[1, k])); lon = [k for k in rest if k != lat][0]
        bottom = c + down * h[n] * R[:, n]
        side = {}
        for sg in (-1.0, 1.0):
            e = bottom + sg * h[lat] * R[:, lat]
            side[sg] = (abs(e[1]), np.mean([(e + sx * h[lon] * R[:, lon])[2] for sx in (-1.0, 1.0)]))
        inner, outer = sorted(side.values())                  # the one with smaller |y| is inner
        out[s] = (inner[1] * 1000, outer[1] * 1000)
    return out


def edge_text(q):
    parts = []
    for s, (zi, zo) in edges(q).items():
        parts.append(f"{CN[s]}脚{'外侧' if zo < zi else '内侧'}低 {abs(zo - zi):.1f} mm")
    return '，'.join(parts)


def report(name, Q):
    Q = np.asarray(Q); qm = np.median(Q, axis=0); base_d = diff(HOME)
    total = diff(qm) - base_d
    parts = []
    for s in ('left', 'right'):
        for k, i in enumerate(LEG[s]):
            q1 = HOME.copy(); q1[i] = qm[i]
            c = diff(q1) - base_d
            if abs(c) >= 0.05: parts.append(f"{CN[s]}{NAME[k]} {c:+.2f}°")
    devs = '  '.join(f"{CN[s]}{NAME[k]} {math.degrees(qm[i] - HOME[i]):+.1f}°"
                     for s in ('left', 'right') for k, i in enumerate(LEG[s]) if k in (0, 1))
    print(f"{name:28s} {len(Q):6d} 帧  两脚横滚差 {total:+.2f}°  = {'  '.join(parts)}\n"
          f"{'':36s}髋偏航/髋横滚 实测-HOME：{devs}\n{'':36s}躯干摆正时：{edge_text(qm)}")


def held_segments(path):
    segs, cur = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        try: r = json.loads(line)
        except ValueError: continue
        if not r.get('joints'):
            continue
        j = r['joints']; q = j[:9] + j[10:15]
        if r.get('policy') == 'held' and not (r.get('safety') or {}).get('limp'):
            cur.append(q)
        elif cur:
            if len(cur) >= 100: segs.append(cur)
            cur = []
    if len(cur) >= 100: segs.append(cur)
    return segs


print(f"仿真 HOME 自检：两脚横滚差 {diff(HOME):+.3f}°，{edge_text(HOME)}（下面的差值都减掉了这个基准）")
for spec in sys.argv[2:]:
    name, path = spec.split('=', 1)
    if path.endswith('.json'):
        j = json.load(open(path, encoding='utf-8'))['joints15']; report(name, [j[:9] + j[10:15]])
        continue
    for k, seg in enumerate(held_segments(path)):
        report(f'{name}#{k + 1}', seg[-150:])
