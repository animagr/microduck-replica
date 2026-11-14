"""For tonight's A/B: count falls in each recording block, compute falls per minute, then sum chip and gyro separately and judge whether the difference is meaningful (read-only).

Usage:
  python ab_blocks.py chip1=recording1.jsonl gyro1=recording2.jsonl chip2=... gyro2=...
  python ab_blocks.py chip1=recording.jsonl@120-300     # only look at seconds 120~300 from the start of this recording (by wall clock)
Labels must start with chip or gyro to enter the comparison; old recordings use an old prefix and only get per-block numbers. Any other prefix is an error and doesn't enter the comparison.
Each block's actual mode is identified from the recording: imu.fusion with fused → chip mode; with chip → gyro mode; no imu.fusion → old version.
If a label doesn't match the mode in the recording, an [error] is reported and that block doesn't enter the comparison.

Definitions:
  Upright walking frames = policy == walk, torque on (safety.limp false), not fallen (safety.fallen false).
  Timing only counts upright walking frames with tilt ≤30° (lying after a fall, leaning, or being held up don't count); time is computed from wall differences, gaps >0.1 s aren't timed.
  One fall = a rising edge of safety.fallen after upright walking frames; a rising edge less than 3 s after the end of the previous fall counts as the same fall (the fall detection flips back and forth).
            Rising edges in non-walking states (held / homing etc.) or with torque off are listed separately and not counted. The log records the time since the previous fall for each, so ones near the 3 s boundary can be re-checked.
  Stick fall = a fall with the joystick pushed within 2 s before the rising edge.
  Primary metric = falls per stick minute = stick falls / minutes of joystick pushing (the operator keeps stick time the same for both modes; how long it stands without pushing is unrelated to mode).
  Reference      = falls per upright walking minute = all falls / upright walking minutes. If the two denominators lead to different conclusions, say so on the spot.
  Walking segment = consecutive upright walking frames (gaps <0.2 s count as consecutive); a fall within 1 s after the segment end counts as "ended in a fall".
  Chip step = gravity from the previous frame extrapolated with this frame's gyro differs from this frame by >5° (same definition as judge_block / glitch_rate), counted only on upright walking frames.
            The chip path: chip mode and the old version use safety.gravity; gyro mode uses imu.fusion.chip, with the same
            normalization + per-component three-point median as safety.gravity added, so the two modes are comparable. Frames with verdict == disabled already publish the chip attitude, counted as chip.
  Published step = the same criterion applied to safety.gravity (what the policy actually sees); should be near 0 in gyro mode.
  Step before fall = the chip path has a step within 1.5 s before the fall (no baseline: the share of arbitrary stick moments with a step in the preceding 1.5 s is itself 12–47%, reference only).
  Body shake (guardrail) = upright walking segments with the joystick pushed and tilt ≤30° (each ≥1.5 s) and no fall within 2 s after the segment end; RMS of body roll and pitch rates (°/s);
            gyro no more than 10% higher than chip. The original definition including pre-fall stumbling is listed separately for reference (it would count the fall rate again).
  Upright walking frames of the minority mode in a block >1 s → this block doesn't enter the comparison (the key was changed midway; split blocks at the moment of the change).
Comparison: sum each mode separately, rate ratio = gyro / chip; p-value from an exact conditional binomial test (with the total fall count fixed, whether gyro's share deviates from its share of time),
      95% interval by Clopper-Pearson. Decide the number and order of blocks before running on the robot (chip, gyro, gyro, chip...); don't decide whether to add blocks while watching the p-value.
Logs: categorized and leveled, written to ab_blocks.log in the same directory as the first recording; the report is also appended to ab_report.txt.
The 10-15 first version was independently reviewed and changed per the review: old/unknown labels excluded from comparison, median added to gyro's chip path,
  timing with tilt ≤30°, stick denominator, pre-fall segments removed from the guardrail, disabled counted as chip, mixed-mode blocks excluded entirely, bad arguments don't crash, warning when the same file is reused.
"""
import json
import math
import os
import sys
import time

GAP = 0.1            # frame intervals longer than this aren't timed
SEG_GAP = 0.2        # gap allowed within a walking segment
MERGE = 3.0          # merge window for fall detection flipping back and forth
PRE_FALL = 1.5       # how far to look back before a fall
STEP_DEG = 5.0
SHAKE_MIN = 1.5
TILT_MAX = 30.0      # timing/body shake only count upright walking frames with tilt ≤30° (lying after a fall or being held don't count)
STICK_RECENT = 2.0   # joystick pushed within this long before the rising edge → counts as a "stick fall"
SHAKE_SKIP = 2.0     # body shake only uses segments with no fall within this long after the segment end
MIX_MAX = 50         # upright walking frames of the non-majority mode exceed this many (1 s) → error for this block

LOG = None


def log(cat, level, msg):
    line = '%s [%s][%s] %s' % (time.strftime('%H:%M:%S'), level, cat, msg)
    if LOG:
        LOG.write(line + '\n')
        LOG.flush()
    if level != 'INFO':
        print(line, file=sys.stderr)


def grav(q):
    w, x, y, z = q
    return (-2 * (x * z - w * y), -2 * (y * z + w * x), -(1 - 2 * (x * x + y * y)))


def ang(a, b):
    c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return math.degrees(math.atan2(math.sqrt(sum(v * v for v in c)), sum(x * y for x, y in zip(a, b))))


def step(g0, g1, w, dt):
    pr = (g0[0] - (w[1] * g0[2] - w[2] * g0[1]) * dt, g0[1] - (w[2] * g0[0] - w[0] * g0[2]) * dt,
          g0[2] - (w[0] * g0[1] - w[1] * g0[0]) * dt)
    return ang(pr, g1)


def fusion(r):
    return (r.get('imu') or {}).get('fusion')


def frame_mode(r):
    f = fusion(r)
    if not f:
        return 'old'
    if f.get('fused') is not None:
        return 'chip'
    if f.get('chip') is not None:
        # when disabled, what's published is already the chip (bno08x.rs sample()/HostImuSample.quat), counted as chip
        return 'chip' if f.get('verdict') == 'disabled' else 'gyro'
    return '?'


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v) if n > 0 else None


def chip_gravs(rows, mode):
    """Per-frame gravity of the chip path. In gyro mode imu.fusion.chip hasn't been median filtered, so this adds the
    same processing as safety.gravity (normalize first, then per-component three-point median, restarting after gaps), so the two modes are comparable."""
    if mode != 'gyro':
        return [r['safety']['gravity'] for r in rows]
    raw = []
    for r in rows:
        f = fusion(r)
        raw.append(_norm(grav(f['chip'])) if f and f.get('chip') else None)
    out, hist = [], []
    for i, g in enumerate(raw):
        if g is None or (i and rows[i]['wall'] - rows[i - 1]['wall'] > GAP):
            hist = []
        if g is None:
            out.append(None)
            continue
        hist = (hist + [g])[-3:]
        h = hist if len(hist) == 3 else [hist[0]] * (3 - len(hist)) + hist
        out.append(tuple(sorted(c)[1] for c in zip(*h)))
    return out


def tilt(r):
    g = r['safety']['gravity']
    n = math.sqrt(sum(v * v for v in g))
    return math.degrees(math.acos(max(-1.0, min(1.0, -g[2] / n)))) if n > 0 else 0.0


def upright(r):
    return r['policy'] == 'walk' and not r['safety']['limp'] and not r['safety'].get('fallen')


def upright_t(r):
    """For timing: upright walking and tilt ≤ TILT_MAX. Steps are still counted with upright(), so frames where the chip jumps beyond 30° aren't missed."""
    return upright(r) and tilt(r) <= TILT_MAX


def stick(r):
    req = (r.get('move') or {}).get('requested') or [0, 0, 0]
    return max(abs(v) for v in req) > 1e-6


def load(path, window):
    rows, bad = [], 0
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if 'imu' in r and 'safety' in r and 'wall' in r:
                rows.append(r)
    rows.sort(key=lambda r: r['wall'])
    if bad:
        log('读取', 'WARN', '%s：%d 行不是 JSON，已跳过' % (path, bad))
    if not rows:
        return rows
    if window:
        w0 = rows[0]['wall']
        rows = [r for r in rows if window[0] <= r['wall'] - w0 <= window[1]]
    return rows


def analyze(label, path, window):
    rows = load(path, window)
    out = {'label': label, 'path': path, 'frames': len(rows)}
    if len(rows) < 2:
        log('读取', 'ERROR', '%s：帧太少（%d）' % (label, len(rows)))
        out['error'] = '帧太少'
        return out
    modes = {}
    for r in rows:
        m = frame_mode(r)
        modes[m] = modes.get(m, 0) + 1
    mode = max(modes, key=modes.get)
    out['modes'] = modes
    out['mode'] = mode
    # Labels only accept chip/gyro/old prefixes; only chip/gyro prefixes enter the comparison (see main)
    want = next((m for m in ('chip', 'gyro', 'old') if label.startswith(m)), None)
    out['want'] = want
    if want is None:
        log('参数', 'ERROR', '%s：标签要以 chip / gyro / old 开头，这块不进对比' % label)
        out['error'] = '标签不认识'
    if len(modes) > 1:
        log('分段', 'WARN', '%s：一块里有多种模式 %s（中途改过键？），按多数 %s 算' % (label, modes, mode))
        # Minority mode exceeds 1 s in upright walking → excluded from comparison, to avoid mixed blocks
        minority_up = sum(1 for r in rows if upright(r) and frame_mode(r) != mode)
        if minority_up > MIX_MAX:
            log('分段', 'ERROR', '%s：非 %s 模式的直立走路帧 %d 帧（>%d），这块不进对比；请按改键时刻切块' % (
                label, mode, minority_up, MIX_MAX))
            out['error'] = '混了别的模式（%d 帧直立走路）' % minority_up
    if want in ('chip', 'gyro') and mode != want:
        log('分段', 'ERROR', '%s：标签是 %s，录像里是 %s，这块不进对比' % (label, want, mode))
        out['error'] = '模式对不上（录像里是 %s）' % mode
    verdicts = {}
    for r in rows:
        f = fusion(r)
        if f and upright(r):
            verdicts[f.get('verdict')] = verdicts.get(f.get('verdict'), 0) + 1
    out['verdicts_up'] = verdicts

    t_up = t_stick = t_tilted = 0.0
    gaps = 0
    chip_steps, pub_steps = [], []
    cg = chip_gravs(rows, mode)
    for i in range(1, len(rows)):
        p, c = rows[i - 1], rows[i]
        dt = c['wall'] - p['wall']
        if dt > GAP:
            gaps += 1
            continue
        if not (upright(c) and upright(p)):
            continue
        if upright_t(c) and upright_t(p):
            t_up += dt
            if stick(c):
                t_stick += dt
        else:
            t_tilted += dt
        if not 0.005 < dt < 0.05:
            continue
        w = c['imu']['gyro']
        if step(p['safety']['gravity'], c['safety']['gravity'], w, dt) > STEP_DEG:
            pub_steps.append(c['wall'])
        g0, g1 = cg[i - 1], cg[i]
        if g0 and g1 and step(g0, g1, w, dt) > STEP_DEG:
            chip_steps.append(c['wall'])
    if gaps:
        log('读取', 'WARN', '%s：%d 处帧间隔 >%.1f s（录像断过），这些空档不计时' % (label, gaps, GAP))
    if t_tilted:
        log('统计', 'INFO', '%s：直立走路状态但倾角 >%.0f° 的 %.1f s 不计时（摔后躺着/被扶着）' % (label, TILT_MAX, t_tilted))
    out.update(t_up=t_up, t_stick=t_stick, t_tilted=t_tilted, chip_steps=len(chip_steps), pub_steps=len(pub_steps))

    # Fall events: first find continuous fallen segments, then merge the flip-flops
    runs, cur = [], None
    for i, r in enumerate(rows):
        f = bool(r['safety'].get('fallen'))
        if f and cur is None:
            cur = i
        elif not f and cur is not None:
            runs.append((cur, i))
            cur = None
    if cur is not None:
        runs.append((cur, len(rows) - 1))
    falls, other = [], []
    since = {}
    falls_stick = []
    last_end = None
    for a, b in runs:
        merged = last_end is not None and rows[a]['wall'] - last_end < MERGE
        gap_prev = None if last_end is None else rows[a]['wall'] - last_end
        last_end = rows[b]['wall']
        if merged:
            continue
        prev = rows[a - 1] if a > 0 else None
        if prev is not None and prev['policy'] == 'walk' and not prev['safety']['limp']:
            ft = rows[a]['wall']
            falls.append(ft)
            since[ft] = gap_prev
            # Joystick pushed within STICK_RECENT s before the rising edge → stick fall (denominator uses joystick-pushing time)
            j = a - 1
            while j >= 0 and ft - rows[j]['wall'] <= STICK_RECENT:
                if stick(rows[j]):
                    falls_stick.append(ft)
                    break
                j -= 1
        else:
            other.append((rows[a]['wall'], rows[a]['policy'], rows[a]['safety']['limp']))
    w0 = rows[0]['wall']
    for wt, pol, limp in other:
        log('摔倒', 'INFO', '%s：%.1f s 处倒地判定，状态 %s 卸力 %s，不计入' % (label, wt - w0, pol, limp))
    out['falls'] = len(falls)
    out['falls_stick'] = len(falls_stick)
    out['other_falls'] = len(other)

    # Walking segments
    segs, cur = [], None
    for p, c in zip(rows, rows[1:]):
        if upright(c) and c['wall'] - p['wall'] <= SEG_GAP and (upright(p) or cur is None):
            if cur is None:
                cur = [c['wall'], c['wall']]
            cur[1] = c['wall']
        elif cur is not None:
            segs.append(cur)
            cur = None
    if cur is not None:
        segs.append(cur)
    segs = [s for s in segs if s[1] - s[0] >= 0.5]
    ended = []
    for s in segs:
        hit = any(0 <= ft - s[1] <= 1.0 for ft in falls)
        ended.append((s[1] - s[0], hit))
    out['segs'] = len(segs)
    out['segs_fall'] = sum(1 for _, h in ended if h)
    fall_durs = sorted(d for d, h in ended if h)
    out['median_to_fall'] = fall_durs[len(fall_durs) // 2] if fall_durs else None
    # Cumulative upright walking time in the block before the first fall
    acc, first = 0.0, None
    if falls:
        for p, c in zip(rows, rows[1:]):
            if c['wall'] >= falls[0]:
                break
            dt = c['wall'] - p['wall']
            if dt <= GAP and upright_t(c) and upright_t(p):
                acc += dt
        first = acc
    out['first_fall'] = first
    out['pre_step'] = sum(1 for ft in falls if any(ft - PRE_FALL <= st < ft for st in chip_steps))
    for ft in falls:
        pre = [st for st in chip_steps if ft - PRE_FALL <= st < ft]
        log('摔倒', 'INFO', '%s：%.1f s 摔倒（%s；距上次倒地结束 %s），摔前 %.1f s 内芯片台阶 %d 次' % (
            label, ft - w0, '推杆' if ft in falls_stick else '没推杆',
            '—' if since[ft] is None else '%.1f s' % since[ft], PRE_FALL, len(pre)))

    # Body shake
    # The guardrail only uses stick segments with "no fall within SHAKE_SKIP s after the segment end" (tilt ≤ TILT_MAX): the original counted pre-fall stumbling,
    # so the guardrail was really measuring the falls themselves. The original definition is kept as *_all for reference.
    def shake_segs(ok):
        ss, cur = [], []
        for r in rows:
            if ok(r):
                if cur and r['wall'] - cur[-1]['wall'] > SEG_GAP:
                    ss.append(cur)
                    cur = []
                cur.append(r)
            elif cur:
                ss.append(cur)
                cur = []
        if cur:
            ss.append(cur)
        return [s for s in ss if s[-1]['wall'] - s[0]['wall'] >= SHAKE_MIN]
    for key, fr in (
            ('', [r for s in shake_segs(lambda r: upright_t(r) and stick(r))
                  if not any(0 <= ft - s[-1]['wall'] <= SHAKE_SKIP for ft in falls) for r in s]),
            ('_all', [r for s in shake_segs(lambda r: upright(r) and stick(r)) for r in s])):
        if fr:
            out['roll_rms' + key] = math.degrees(math.sqrt(sum(r['imu']['gyro'][0] ** 2 for r in fr) / len(fr)))
            out['pitch_rms' + key] = math.degrees(math.sqrt(sum(r['imu']['gyro'][1] ** 2 for r in fr) / len(fr)))
            out['shake_s' + key] = len(fr) / 50
    log('统计', 'INFO', '%s：%s' % (label, {k: v for k, v in out.items() if k not in ('path',)}))
    return out


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def binom_p_two_sided(k, n, p):
    pk = math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i)
                        for i in range(n + 1)
                        if math.comb(n, i) * p ** i * (1 - p) ** (n - i) <= pk * (1 + 1e-9)))


def clopper_pearson(k, n, alpha=0.05):
    def solve(f, target):
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if f(mid) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda p: binom_cdf(k - 1, n, p), 1 - alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p), alpha / 2)
    return lower, upper


def fmt(v, f='%.1f', none='—'):
    return none if v is None else f % v


def main():
    global LOG
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    specs = []
    for a in args:
        if '=' not in a:
            print('参数要写成 标签=文件[@起-止]：%s' % a, file=sys.stderr)
            sys.exit(2)
        label, rest = a.split('=', 1)
        window = None
        if '@' in rest:
            rest, w = rest.rsplit('@', 1)
            try:
                lo, hi = (float(v) for v in w.split('-'))
            except ValueError:
                print('%s：时间窗要写成 @起-止（秒，例如 @120-300）：@%s' % (label, w), file=sys.stderr)
                sys.exit(2)
            if hi <= lo:
                print('%s：时间窗结束要大于开始：@%s' % (label, w), file=sys.stderr)
                sys.exit(2)
            window = (lo, hi)
        specs.append((label, rest, window))
    missing = [(label, rest) for label, rest, _ in specs if not os.path.isfile(rest)]
    if missing:
        for label, rest in missing:
            print('%s：文件不存在 %s' % (label, rest), file=sys.stderr)
        sys.exit(1)
    outdir = os.path.dirname(os.path.abspath(specs[0][1]))
    LOG = open(os.path.join(outdir, 'ab_blocks.log'), 'a', encoding='utf-8')
    log('开始', 'INFO', ' '.join(args))
    blocks = [analyze(label, rest, window) for label, rest, window in specs]
    # Overlapping time ranges of the same recording entered the comparison twice → falls would be counted twice; reported only when both blocks are in the comparison, and written into the report
    overlap = []
    compared = lambda b: 'error' not in b and b.get('want') in ('chip', 'gyro') and b['mode'] in ('chip', 'gyro')
    for i in range(len(specs)):
        for j in range(i):
            if not (compared(blocks[i]) and compared(blocks[j])):
                continue
            if os.path.normcase(os.path.abspath(specs[i][1])) != os.path.normcase(os.path.abspath(specs[j][1])):
                continue
            a0, a1 = specs[i][2] or (0, float('inf'))
            b0, b1 = specs[j][2] or (0, float('inf'))
            if a0 < b1 and b0 < a1:
                msg = '%s 和 %s 用了同一份录像的重叠时间段，摔倒会被数两次' % (specs[j][0], specs[i][0])
                log('参数', 'WARN', msg)
                overlap.append(msg)

    lines = []
    lines.append('== A/B 报告 %s ==' % time.strftime('%Y-%m-%d %H:%M:%S'))
    for msg in overlap:
        lines.append('[警告] ' + msg)
    hdr = ('%-8s %-5s %7s %7s %4s %7s %5s %9s %9s %8s %8s %11s %11s' %
           ('块', '模式', '直立走', '推摇杆', '摔', '每直立分', '段', '以摔结束', '摔前中位', '首摔前', '芯片台阶', '摔前有台阶', '颤 横滚/俯仰'))
    lines.append(hdr)
    for b in blocks:
        if 'error' in b and b.get('frames', 0) < 2:
            lines.append('%-8s 出错：%s' % (b['label'], b['error']))
            continue
        rate = b['falls'] / (b['t_up'] / 60) if b['t_up'] > 0 else None
        lines.append('%-8s %-5s %6.0fs %6.0fs %4d %7s %5d %9s %8ss %7ss %8d %11s %11s%s' % (
            b['label'], b['mode'], b['t_up'], b['t_stick'], b['falls'], fmt(rate, '%.2f'), b['segs'],
            '%d/%d' % (b['segs_fall'], b['segs']), fmt(b['median_to_fall']), fmt(b['first_fall']),
            b['chip_steps'], '%d/%d' % (b['pre_step'], b['falls']),
            ('%.0f/%.0f' % (b['roll_rms'], b['pitch_rms'])) if 'roll_rms' in b else '—',
            ('  ← ' + b['error']) if 'error' in b else ''))
        rate_s = b['falls_stick'] / (b['t_stick'] / 60) if b['t_stick'] > 0 else None
        lines.append('%-8s       推杆摔 %d 次 / 推摇杆 %.0f s → 每推杆分钟 %s；倾角>%.0f° 不计时 %.0f s' % (
            '', b['falls_stick'], b['t_stick'], fmt(rate_s, '%.2f'), TILT_MAX, b['t_tilted']))
        if b['mode'] == 'gyro':
            lines.append('%-8s       发布台阶（策略看到的）%d 次；直立走路判定 %s' % ('', b['pub_steps'], b['verdicts_up']))
        if b['other_falls']:
            lines.append('%-8s       另有 %d 次倒地判定不在走路状态，不计入（明细见 ab_blocks.log）' % ('', b['other_falls']))

    tot = {}
    for b in blocks:
        # Prefix old (or an unknown label) doesn't enter the comparison, even if the recording is chip/gyro
        if 'error' in b or b.get('want') not in ('chip', 'gyro') or b['mode'] not in ('chip', 'gyro'):
            continue
        t = tot.setdefault(b['mode'], {'falls': 0, 't': 0.0, 'falls_s': 0, 't_s': 0.0, 'n': 0,
                                       'roll2': 0.0, 'pitch2': 0.0, 'shake_s': 0.0,
                                       'roll2_all': 0.0, 'pitch2_all': 0.0, 'shake_s_all': 0.0})
        t['falls'] += b['falls']
        t['t'] += b['t_up']
        t['falls_s'] += b['falls_stick']
        t['t_s'] += b['t_stick']
        t['n'] += 1
        for key in ('', '_all'):
            if 'roll_rms' + key in b:
                t['roll2' + key] += b['roll_rms' + key] ** 2 * b['shake_s' + key]
                t['pitch2' + key] += b['pitch_rms' + key] ** 2 * b['shake_s' + key]
                t['shake_s' + key] += b['shake_s' + key]
    lines.append('')
    if 'chip' in tot and 'gyro' in tot and tot['chip']['t'] > 0 and tot['gyro']['t'] > 0:
        c, g = tot['chip'], tot['gyro']
        # Output once for each denominator: upright walking (including standing without the stick) and joystick pushing; if the two conclusions differ, say so on the spot
        for name, kf, kt in (('主指标·推摇杆', 'falls_s', 't_s'), ('参考·直立走路', 'falls', 't')):
            if c[kt] <= 0 or g[kt] <= 0:
                lines.append('[%s] 有一边时间为 0，不出对比。' % name)
                continue
            rc, rg = c[kf] / (c[kt] / 60), g[kf] / (g[kt] / 60)
            lines.append('[%s] chip %d 块 %.0f s 摔 %d 次 每分钟 %.2f；gyro %d 块 %.0f s 摔 %d 次 每分钟 %.2f' % (
                name, c['n'], c[kt], c[kf], rc, g['n'], g[kt], g[kf], rg))
            n = c[kf] + g[kf]
            share = g[kt] / (g[kt] + c[kt])
            if n == 0:
                lines.append('[%s] 两边都没摔，比不出摔倒率。' % name)
                continue
            p = binom_p_two_sided(g[kf], n, share)
            lo, hi = clopper_pearson(g[kf], n)
            odds = (1 - share) / share
            rr_lo = lo / (1 - lo) * odds if lo < 1 else float('inf')
            rr_hi = hi / (1 - hi) * odds if hi < 1 else float('inf')
            rr = (rg / rc) if rc > 0 else float('inf')
            verdict = ('gyro 摔得明显少' if rr < 1 else 'gyro 摔得明显多：停 gyro，查原因') if p < 0.05 else '差别还不够大，不能下结论'
            lines.append('[%s] 率比 gyro/chip = %s，95%% 区间 %.2f～%s，p = %.3f → %s' % (
                name, fmt(rr, '%.2f', '∞'), rr_lo, '∞' if math.isinf(rr_hi) else '%.2f' % rr_hi, p, verdict))
        if c['shake_s'] > 0 and g['shake_s'] > 0:
            cr, cp = math.sqrt(c['roll2'] / c['shake_s']), math.sqrt(c['pitch2'] / c['shake_s'])
            gr, gp = math.sqrt(g['roll2'] / g['shake_s']), math.sqrt(g['pitch2'] / g['shake_s'])
            ok = gr <= cr * 1.1 and gp <= cp * 1.1
            lines.append('机身颤（°/s RMS，没摔的推杆段）chip %.0f/%.0f（%.0f s），gyro %.0f/%.0f（%.0f s）→ 护栏%s%s' % (
                cr, cp, c['shake_s'], gr, gp, g['shake_s'], '没超' if ok else '超了（gyro 比 chip 高一成以上）',
                '；有一边不到 20 s，只作参考' if min(c['shake_s'], g['shake_s']) < 20 else ''))
        else:
            lines.append('机身颤：有一边没有「没摔的推杆段」（≥%.1f s），护栏判不了。' % SHAKE_MIN)
        if c['shake_s_all'] > 0 and g['shake_s_all'] > 0:
            lines.append('    参考（原口径，含摔前踉跄）chip %.0f/%.0f，gyro %.0f/%.0f' % (
                math.sqrt(c['roll2_all'] / c['shake_s_all']), math.sqrt(c['pitch2_all'] / c['shake_s_all']),
                math.sqrt(g['roll2_all'] / g['shake_s_all']), math.sqrt(g['pitch2_all'] / g['shake_s_all'])))
    else:
        lines.append('还没有 chip 和 gyro 两种块，不出对比。')
    report = '\n'.join(lines)
    print(report)
    with open(os.path.join(outdir, 'ab_report.txt'), 'a', encoding='utf-8') as fh:
        fh.write(report + '\n\n')
    log('结束', 'INFO', '报告已追加到 %s' % os.path.join(outdir, 'ab_report.txt'))


if __name__ == '__main__':
    main()
