"""Criteria script for hardware runs (read-only, standard library only): produces numbers for one duck_rec recording (50 Hz RobotState jsonl) according to the stopping rules.
Usage: python judge_block.py recording.jsonl [start_s end_s] (seconds = wall seconds relative to the file's first frame)

10-15 second version: step rules revised based on real-hardware shadow data and an independent review; for the full background see docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md §5.5.
Step = gravity from the previous frame extrapolated 20 ms with the gyro differs from this frame by >5°, counted only on upright walking frames (policy == walk, torque on, safety.fallen false).
  Published path = safety.gravity (in gyro mode this is the fused attitude the policy sees), paired with this frame's gyro (both have passed the three-point median, so their delays line up).
  Shadow path = imu.fusion.fused (the raw fused value in chip mode, not median filtered), paired with the next frame's gyro (the recorded gyro has passed the median and lags one frame).
Each step is classified by the fusion verdicts within ±2 frames around it:
  Hard: verdicts include realign_long / realign_gap / fallback / follow (the only four that let fusion jump a whole step) → a single one means go back to chip, no exemption applies;
  Soft: verdicts only accepted / rejected / slew (with these the fusion only integrates or corrects ≤0.1° per frame, so it can't jump a whole step):
      within 1.0 s before a fall's rising edge, or previous frame's published tilt ≥30° (already falling, fall detection hasn't caught up) → exempt, just recorded;
      otherwise ≥3 per block → go back to chip; 1–2 → recorded, inspected one by one after the block.
Also listed: frames among upright walking frames with a hard verdict (cross-check with before/after-block counts: an increase in realign/fallback must match post-fall / HOME moments in the recording; if it doesn't, treat it as a real jump).
Standing still: consecutive frames with policy == held, torque on, |ω| < 20°/s, split into 10 s windows; each window needs median θ ≤0.5° and P90 ≤1° (tilting and pushing frames are naturally removed by |ω|).
"""
import json, math, sys

HARD = {'realign_long', 'realign_gap', 'fallback', 'follow'}
PRE_FALL, TILT_EXEMPT, STEP_DEG, SOFT_MAX = 1.0, 30.0, 5.0, 3


def grav(q):
    w, x, y, z = q
    return (-2 * (x * z - w * y), -2 * (y * z + w * x), -(1 - 2 * (x * x + y * y)))


def ang(a, b):
    c = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    return math.degrees(math.atan2(math.sqrt(sum(v*v for v in c)), sum(x*y for x, y in zip(a, b))))


def step(g0, g1, w, dt):
    pr = (g0[0] - (w[1]*g0[2] - w[2]*g0[1])*dt, g0[1] - (w[2]*g0[0] - w[0]*g0[2])*dt, g0[2] - (w[0]*g0[1] - w[1]*g0[0])*dt)
    return ang(pr, g1)


def tilt(g):
    n = math.sqrt(sum(v * v for v in g)) or 1.0
    return math.degrees(math.acos(max(-1.0, min(1.0, -g[2] / n))))


def wdeg(r):
    return math.degrees(math.sqrt(sum(v * v for v in r['imu']['gyro'])))


rows = []
for line in open(sys.argv[1], encoding='utf-8'):
    try: r = json.loads(line)
    except ValueError: continue
    if 'imu' in r and 'safety' in r and 'wall' in r: rows.append(r)
rows.sort(key=lambda r: r['wall'])
if not rows:
    sys.exit('录像里没有状态帧')
T0 = rows[0]['wall']
if len(sys.argv) >= 4:
    a, b = float(sys.argv[2]), float(sys.argv[3]); rows = [r for r in rows if a <= r['wall'] - T0 <= b]
fus = lambda r: (r['imu'] or {}).get('fusion') or {}
up = lambda r: r['policy'] == 'walk' and not r['safety']['limp'] and not r['safety'].get('fallen')
modes = {'chip' if fus(r).get('fused') else 'gyro' if fus(r).get('chip') else 'old' for r in rows}
falls = [rows[i]['wall'] for i in range(1, len(rows)) if rows[i]['safety'].get('fallen') and not rows[i-1]['safety'].get('fallen')]


def verdicts_near(i):
    return [fus(rows[j]).get('verdict') for j in range(max(0, i - 2), min(len(rows), i + 3))]


def classify(i):
    """Hard / exempt / soft, plus explanation."""
    vs = verdicts_near(i)
    if HARD & set(vs):
        return '硬', vs
    t = rows[i]['wall']
    nf = min((f - t for f in falls if f >= t), default=None)
    if nf is not None and nf <= PRE_FALL:
        return '豁免(摔前%.2fs)' % nf, vs
    if tilt(rows[i - 1]['safety']['gravity']) >= TILT_EXEMPT:
        return '豁免(上一帧倾角%.0f°)' % tilt(rows[i - 1]['safety']['gravity']), vs
    return '软', vs


up_frames, up_time = 0, 0.0
pub, shadow = [], []
for i in range(1, len(rows)):
    p, c = rows[i - 1], rows[i]
    dt = c['wall'] - p['wall']
    if not 0.015 < dt < 0.03 or not (up(c) and up(p)):
        continue
    up_frames += 1; up_time += dt
    e = step(p['safety']['gravity'], c['safety']['gravity'], c['imu']['gyro'], dt)
    if e > STEP_DEG:
        pub.append((i, e))
    fp, fc = fus(p), fus(c)
    if fp.get('fused') and fc.get('fused') and i + 1 < len(rows):
        e2 = step(grav(fp['fused']), grav(fc['fused']), rows[i + 1]['imu']['gyro'], dt)
        if e2 > STEP_DEG:
            shadow.append((i, e2))

print(f'帧 {len(rows)}；模式 {sorted(modes)}；直立走路 {up_frames} 帧 / {up_time:.0f} s；摔倒上升沿 {len(falls)} 次：{[round(f - T0, 1) for f in falls]}')


def report(name, steps, judge):
    counts = {'硬': 0, '软': 0, '豁免': 0}
    lines = []
    for i, e in steps:
        cls, vs = classify(i)
        counts['豁免' if cls.startswith('豁免') else cls] += 1
        nxt = wdeg(rows[i + 1]) if i + 1 < len(rows) else float('nan')
        lines.append('   t=%.2f  %.1f°  %s  |ω| %.0f→%.0f°/s  判定±2帧 %s' % (rows[i]['wall'] - T0, e, cls, wdeg(rows[i]), nxt, vs))
    print(f'{name}：>5° 台阶 {len(steps)} 次 → 硬 {counts["硬"]}、软 {counts["软"]}、豁免 {counts["豁免"]}')
    for l in lines[:30]: print(l)
    if len(lines) > 30: print('   …（共 %d 条）' % len(lines))
    if judge:
        if counts['硬']:
            print('   → 回 chip：有硬台阶（融合整步对齐附近的跳）')
        elif counts['软'] >= SOFT_MAX:
            print(f'   → 回 chip：软台阶 {counts["软"]} 次 ≥{SOFT_MAX}（判据或轴向有系统性问题）')
        elif counts['软']:
            print(f'   → 继续，但块后逐个看这 {counts["软"]} 次')
        else:
            print('   → 没触发')


report('发布那一路（safety.gravity，策略看到的）', pub, judge='gyro' in modes)
if 'chip' in modes:
    print('   （chip 模式下发布的是芯片姿态，上面只作基线，不触发停止规则）')
    report('影子那一路（imu.fusion.fused，配下一帧陀螺）', shadow, judge=False)

hard_frames = [(r['wall'] - T0, fus(r).get('verdict'), up(r)) for r in rows if fus(r).get('verdict') in HARD]
if hard_frames:
    up_hard = [h for h in hard_frames if h[2]]
    print(f'硬判定帧（录像每帧只带最后一条报告的判定）：共 {len(hard_frames)} 帧，其中直立走路帧 {len(up_hard)}')
    for t, v, u in hard_frames[:15]:
        after = [round(t - (f - T0), 2) for f in falls if 0 <= t - (f - T0) <= 10]
        print('   t=%.2f  %s  %s%s' % (t, v, '直立走路' if u else '非直立走路', ('  倒地后 %ss' % after[-1]) if after else ''))
    if up_hard:
        print('   → 直立走路帧里有硬判定：对照计数和录像，不是倒地后/HOME 时的 → 回 chip')

vs_all, vs_up = {}, {}
for r in rows:
    v = fus(r).get('verdict')
    if v:
        vs_all[v] = vs_all.get(v, 0) + 1
        if up(r): vs_up[v] = vs_up.get(v, 0) + 1
if vs_all:
    print('判定（全部帧）:', vs_all); print('判定（直立走路帧）:', vs_up)

# Standing still: consecutive frames that are held, torque on, |ω|<20°/s, split into 10 s windows
wins, cur = [], []
for r in rows:
    ok = r['policy'] == 'held' and not r['safety']['limp'] and wdeg(r) < 20 and 'theta_deg' in fus(r)
    if ok and cur and r['wall'] - cur[0]['wall'] >= 10:
        wins.append(cur); cur = []
    if ok:
        if cur and r['wall'] - cur[-1]['wall'] > 0.1:
            if cur[-1]['wall'] - cur[0]['wall'] >= 5: wins.append(cur)
            cur = []
        cur.append(r)
    elif cur:
        if cur[-1]['wall'] - cur[0]['wall'] >= 5: wins.append(cur)
        cur = []
if cur and cur[-1]['wall'] - cur[0]['wall'] >= 5: wins.append(cur)
if wins:
    bad = []
    worst = (0, 0)
    for wv in wins:
        th = sorted(fus(r)['theta_deg'] for r in wv); n = len(th)
        med, p90 = th[n // 2], th[min(n - 1, int(n * .9))]
        worst = (max(worst[0], med), max(worst[1], p90))
        if med > 0.5 or p90 > 1.0: bad.append((round(wv[0]['wall'] - T0, 1), round(med, 3), round(p90, 3)))
    tot = sum(wv[-1]['wall'] - wv[0]['wall'] for wv in wins)
    print(f'HOME 静站：{len(wins)} 个窗（共 {tot:.0f} s），最差窗 θ 中位 {worst[0]:.3f}°、P90 {worst[1]:.3f}°'
          + (f'；超标窗 {bad} → 回 chip' if bad else '；都在中位 ≤0.5°、P90 ≤1° 以内'))
else:
    print('没有 HOME 静站窗（held、未卸力、|ω|<20°/s、≥5 s）')
