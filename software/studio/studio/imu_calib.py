"""IMU mount orientation calibration (done standing): pure computation. Touches no hardware and no network, uses only the standard library math.

The page samples a series of gravity readings: stand still → lean forward → lean back → lean left → lean right, hands them to solve(), and gets back the mount orientation, stance compensation,
whether each step passed, and quality metrics. Whether and how to write it into the duck is not handled here (see imu-page-plan.md).

## Conventions (all checked against real-hardware data, see the "Facts" section of the plan)
- Body frame B: x forward (toward the head), y left, z up. robot.state.safety.gravity is in this frame,
  about (0, 0, -1) when standing upright (tests/fixtures/now-20261018.jsonl line 10: [0.044, 0.016, -0.999]).
- Quaternions are always [w, x, y, z] (robot.state.imu.quat and verify-imu's mount_wxyz both use this order).
- Attitude quaternion q (body → world) to gravity: g = R(q)ᵀ·(0, 0, -1). That's how robotd's safety.gravity is computed (then a median of 3 points).
- Mount orientation q_mount: chip frame → body frame, v_body = q_mount ⊗ v_chip ⊗ q_mount*; robotd computes the body attitude as
  q_body = q_chip ⊗ q_mount⁻¹ (fork firmware duck-control/src/imu.rs:137-151).

## Sample format
Each sample is a dict (or just [gx, gy, gz]), in any one of three forms:
    {"g": [gx, gy, gz]}       gravity direction (only the direction is used, length doesn't matter) —— robot.state.safety.gravity
    {"acc": [ax, ay, az]}     accelerometer reading: at rest it reads 1 g upward; negate it to get gravity
    {"quat": [w, x, y, z]}    attitude (body → world)
May carry "t" (seconds) and "step" (used to split into steps for a flat list). Readings with inf / nan are dropped.

## frame
- "body" (default): readings are already converted to the body frame using the mount orientation **stored** on the duck. Motion mode's robot.state and debug mode's
  busStatus.last_sample.imu (gravity, quaternion_wxyz, fork firmware robotd/src/feetech_commissioning.rs:1236-1255)
  are both like this. The result is a "correction", new orientation = correction ∘ old orientation, so old_mount (the stored orientation) must be given.
- "sensor": readings are in the chip's raw axes (robotd doesn't provide this data now; reserved for reading the chip directly later). The result is the mount orientation itself.

## How readings are taken for each step (the page web/imu.js uses the same rules to decide "it's held still, next step"; parameters for both sides are in RULES)
- Hold segment: counting back from the last reading of this step, the consecutive readings within hold_band_deg of the last reading; single jumpy readings in between are skipped
  (the BNO085 occasionally has a jumpy frame). If it overshoots and comes back to hold, only the hold segment after coming back counts.
- Level reference: before the hold segment, the last run of readings that are "within level_deg of the on-table rest, self-wobble ≤ ref_spread_deg, ≥ ref_min_n in a row".
  When a person lifts the duck the hands can't be exactly level, so each step uses its own leveling moment as zero, and hands off by a few degrees aren't counted as "tilting diagonally".
  If none is found, the on-table rest moment is used.
- How much and which way it tilts: the hold segment's average direction relative to the level reference. Both "minimum / maximum" are judged on the hold segment.

## Principle
1. Standing still (on the table, hands off): gravity reversed is "up".
2. Each of the four steps has a tilt direction d = horizontal component(hold − level); its azimuth in the horizontal plane minus the azimuth this step should have (forward 0°, left 90°,
   back 180°, right −90°) is the heading c that this step believes is "forward".
3. The c of the forward and back steps should be the same (different → both tilted to the same side); likewise left and right; the forward/back pair and left/right pair should also agree (off by ~180° →
   one pair was done reversed; off by a dozen-odd degrees → tilted diagonally, called cross). The circular mean of the four c is taken as "forward", and each step's distance from it is how "diagonal" that step was.
4. "Up" + "forward" are orthogonalized into three axes.
5. Stance compensation: "up" isn't forced to vertical but is the gravity home_gravity the body should have in the official HOME pose (default (0,0,-1);
   in the official training HOME the body is level, see the plan). The deviation read while standing —— whether the chip is mounted crooked or the legs tilt the body —— is all folded into
   the mount orientation. After calibration, the reading when standing = the official HOME reading. Gravity alone can't separate these two causes, so over 5° requires human confirmation.
6. Forward/back and left/right **both** reversed (the duck turned around) can't be caught by self-checks, only by comparing with the old orientation: a heading change over 90° requires human confirmation.
"""
import math

DOWN = (0.0, 0.0, -1.0)
STEPS = ("still", "fwd", "back", "left", "right")
STEP_CN = {"still": "静止站好", "fwd": "前倾", "back": "后倾", "left": "左倾", "right": "右倾"}
TILTS = ("fwd", "back", "left", "right")
EXPECT_DIR = {"fwd": 0.0, "left": 90.0, "back": 180.0, "right": -90.0}   # which way gravity shifts when tilting this way (counterclockwise from +x, degrees)

# Criteria. The page web/imu.js's RULES uses the same names: the front end is slightly stricter (tilt ≥12°, ≤30°, hold 1 second), so anything the front end lets through is definitely accepted here.
RULES = {
    "still_min_n": 15,              # at least this many readings when still (1.5 seconds at 10 Hz; the page samples 3 seconds)
    "still_max_spread_deg": 1.5,    # readings wobble at most this much when still (by the 90th percentile: one or two jumpy frames don't count, only constant wobbling does)
    "level_deg": 5.0,               # level: within this much of the on-table rest
    "ref_min_n": 5,                 # the leveling moment needs at least this many consecutive readings (0.5 seconds)
    "ref_spread_deg": 1.5,          # self-wobble at most this much while level
    "hold_band_deg": 1.8,           # hold segment: within this much of this step's last reading
    "hold_min_n": 5,                # hold segment needs at least this many readings (the page requires holding a full 1 second, ≥8 readings)
    "tilt_min_deg": 10.0,           # hold segment must tilt at least this much relative to level: with too little tilt, hand shake dominates and "forward" can't be pinned down
    "tilt_max_deg": 35.0,           # tilt at most this much: more and the feet slip and readings get unstable
    "pair_max_deg": 60.0,           # "forward" from lean-forward and lean-back differ by more than this: both tilted to the same side (likewise left/right)
    "skew_max_deg": 20.0,           # each step may deviate at most this much from the agreed direction
    "cross_max_deg": 12.0,          # the forward/back pair and left/right pair differ at most this much (with difference Δ, the heading is off by about Δ/2)
    "good_skew_deg": 10.0,          # each step skewed ≤10° and the two pairs differing ≤6° rates "good"
    "good_cross_deg": 6.0,
    "big_change_deg": 8.0,          # changed this much from the old orientation: warn "module may be mounted crooked / mounting was changed"
    "stand_confirm_deg": 5.0,       # stance compensation over this much requires human confirmation (when robotd verifies orientation itself it only allows 5° for upright)
    "flip_deg": 90.0,               # heading changed this much: most likely both forward/back and left/right were reversed (the duck turned around), requires human confirmation
}


# ---------------- Vectors ----------------

def _v(x):
    return (float(x[0]), float(x[1]), float(x[2]))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    """Unit vector; returns None for zero vectors or those with inf / nan."""
    n = norm(a)
    if not (math.isfinite(n) and n > 1e-9):
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def angle_deg(a, b):
    """Angle between two vectors (degrees); returns None if either has no computable direction."""
    ua, ub = unit(a), unit(b)
    if ua is None or ub is None:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(ua, ub)))))


def horiz(v, up):
    """v with the component along up removed (up is a unit vector)."""
    return sub(v, scale(up, dot(v, up)))


def signed_angle_deg(a, b, axis):
    """Signed angle (degrees, positive by the right-hand rule) from a to b around axis. a and b are first projected onto the plane perpendicular to axis."""
    ha, hb = unit(horiz(a, axis)), unit(horiz(b, axis))
    if ha is None or hb is None:
        return None
    return math.degrees(math.atan2(dot(cross(ha, hb), axis), dot(ha, hb)))


def wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def circ_mean_deg(ds):
    s = sum(math.sin(math.radians(d)) for d in ds)
    c = sum(math.cos(math.radians(d)) for d in ds)
    if abs(s) < 1e-9 and abs(c) < 1e-9:
        return None
    return math.degrees(math.atan2(s, c))


# ---------------- Matrices (row-major, 3×3 nested tuples) ----------------

def mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def mat_vec(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


def mat_t(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


# ---------------- Quaternions [w, x, y, z] ----------------

def q_normalize(q):
    if len(q) != 4 or not all(math.isfinite(float(c)) for c in q):
        raise ValueError("四元数要 4 个有限的数")
    n = math.sqrt(sum(float(c) * float(c) for c in q))
    if not n > 1e-12:
        raise ValueError("四元数长度是 0")
    q = tuple(float(c) / n for c in q)
    return q if q[0] >= 0 else tuple(-c for c in q)     # normalize to w ≥ 0 (q and −q are the same rotation)


def q_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def q_conj(q):
    return (q[0], -q[1], -q[2], -q[3])


def q_rotate(q, v):
    return mat_vec(mat_from_q(q), v)


def mat_from_q(q):
    w, x, y, z = q_normalize(q)
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def q_from_mat(m):
    """Rotation matrix → quaternion (Shepperd, numerically stable)."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)
    return q_normalize(q)


def q_angle_deg(q):
    """How many degrees this rotation turns (0–180)."""
    w = abs(q_normalize(q)[0])
    return math.degrees(2 * math.acos(min(1.0, w)))


def q_between(a, b):
    """Shortest rotation taking unit vector a to b."""
    a, b = unit(a), unit(b)
    c = dot(a, b)
    if c < -0.999999:
        # Exactly opposite: rotate 180° about any axis perpendicular to a
        axis = unit(cross(a, (1.0, 0.0, 0.0))) or unit(cross(a, (0.0, 1.0, 0.0)))
        return (0.0, axis[0], axis[1], axis[2])
    x = cross(a, b)
    return q_normalize((1.0 + c, x[0], x[1], x[2]))


def gravity_from_quat(q):
    """Attitude (body → world) → gravity direction in the body frame, same algorithm as robotd's safety.gravity."""
    r = mat_from_q(q)
    return (-r[2][0], -r[2][1], -r[2][2])


def compose_mount(correction, old_mount):
    """New mount orientation = correction ∘ old orientation (both in the chip → body convention):
    v_new_body = R_corr · v_old_body = R_corr · R_old · v_chip."""
    return q_normalize(q_mul(correction, old_mount))


# ---------------- Standard mountings (the 24 with chip axes aligned to body axes) ----------------

_AXIS_CN = {(1, 0): "前", (1, 1): "左", (1, 2): "上", (-1, 0): "后", (-1, 1): "右", (-1, 2): "下"}


def _standard_mounts():
    out = []
    perms = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
    for p in perms:
        for sx in (1, -1):
            for sy in (1, -1):
                for sz in (1, -1):
                    m = [[0.0] * 3 for _ in range(3)]
                    for col, (row, s) in enumerate(zip(p, (sx, sy, sz))):
                        m[row][col] = float(s)      # chip axis col → body axis row
                    m = tuple(tuple(r) for r in m)
                    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
                    if det > 0:
                        out.append(m)
    return out


STANDARD_MOUNTS = _standard_mounts()


def describe_mount(q):
    """Describe the mount orientation in plain language: which way the chip's x / y / z each point on the body (taking the closest standard mounting), plus how many degrees off."""
    best, best_deg = None, None
    for m in STANDARD_MOUNTS:
        d = q_angle_deg(q_mul(q_conj(q_from_mat(m)), q))
        if best_deg is None or d < best_deg:
            best, best_deg = m, d
    words = []
    for col, name in enumerate("xyz"):
        row = next(r for r in range(3) if best[r][col] != 0)
        words.append(f"芯片 {name} 朝{_AXIS_CN[(int(best[row][col]), row)]}")
    return {"text": "，".join(words), "off_deg": round(best_deg, 2), "quat": list(q_from_mat(best))}


# ---------------- Sampling ----------------

def _finite3(x):
    if not isinstance(x, (list, tuple)) or len(x) != 3:
        return None
    try:
        v = _v(x)
    except (TypeError, ValueError):
        return None
    return v if all(math.isfinite(c) for c in v) else None


def sample_gravity(s):
    """One sample → gravity unit vector in the body (or chip) frame; unrecognized or with inf / nan returns None (the reading is dropped)."""
    try:
        if isinstance(s, (list, tuple)):
            v = _finite3(s)
            return unit(v) if v else None
        if not isinstance(s, dict):
            return None
        if s.get("g") is not None:
            v = _finite3(s["g"])
            return unit(v) if v else None
        if s.get("acc") is not None:
            v = _finite3(s["acc"])
            a = unit(v) if v else None
            return None if a is None else scale(a, -1.0)
        if s.get("quat") is not None:
            return gravity_from_quat(s["quat"])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return None


def sum_vec(vs):
    s = (0.0, 0.0, 0.0)
    for v in vs:
        s = add(s, v)
    return s


def mean_dir(vs):
    return unit(sum_vec(vs)) if vs else None


def spread_deg(vs, m):
    return max((angle_deg(v, m) or 0.0 for v in vs), default=0.0)


def spread_p90_deg(vs, m):
    """90th percentile of angles from m (the ⌊0.9·(n−1)⌋-th after sorting): used for the still step, so individual jumpy readings don't count as wobble. Same algorithm as the page's spreadP90."""
    ds = sorted(angle_deg(v, m) or 0.0 for v in vs)
    return ds[int(0.9 * (len(ds) - 1))] if ds else 0.0


def trimmed_mean_dir(vs):
    """Average first, drop the 10% farthest from the average (beyond the 90th percentile), then average again: individual jumpy readings can't skew "up". Same algorithm as the page's trimmedMeanDir."""
    m = mean_dir(vs)
    if m is None:
        return None
    lim = spread_p90_deg(vs, m)
    keep = [v for v in vs if (angle_deg(v, m) or 0.0) <= lim + 1e-9]
    return mean_dir(keep) or m


def group_steps(samples):
    """{"still": [...], ...} is used as is; a flat list is grouped by each sample's "step"."""
    if isinstance(samples, dict):
        return {k: list(samples.get(k) or []) for k in STEPS}
    out = {k: [] for k in STEPS}
    for s in samples or []:
        if isinstance(s, dict) and s.get("step") in out:
            out[s["step"]].append(s)
    return out


def tilt_of(g0, g):
    """How many degrees it tilts relative to g0, and which way (azimuth in the horizontal plane defined by g0, measured from +x, degrees).
    The tilt ring on the page uses the same algorithm (tiltOf in web/imu.js)."""
    t = angle_deg(g0, g)
    up = scale(g0, -1.0)
    d = signed_angle_deg((1.0, 0.0, 0.0), sub(g, g0), up) if unit(horiz(sub(g, g0), up)) else None
    return t, d


# ---------------- Hold segment, level reference (the page web/imu.js's findHold / findRef follow this line by line) ----------------

def _run_back(gs, end, band):
    """Count back from gs[end]: consecutive readings within band of gs[end]; single jumpy readings in between are skipped. Returns (index list, number skipped)."""
    last = gs[end]
    idx, skipped, j = [end], 0, end - 1
    while j >= 0:
        if angle_deg(gs[j], last) <= band:
            idx.append(j)
            j -= 1
        elif j - 1 >= 0 and angle_deg(gs[j - 1], last) <= band:
            skipped += 1                  # single jumpy reading: skip it and keep counting back
            j -= 1
        else:
            break
    return sorted(idx), skipped


def find_hold(gs, rules=RULES):
    """Hold segment: count back from the last reading (if the last one itself is jumpy, start from the second to last), take the longer run."""
    if not gs:
        return [], 0
    best = _run_back(gs, len(gs) - 1, rules["hold_band_deg"])
    if len(gs) >= 2:
        alt = _run_back(gs, len(gs) - 2, rules["hold_band_deg"])
        if len(alt[0]) > len(best[0]) + 1:
            best = alt
    return best


def find_ref(gs, g0, before, rules=RULES):
    """Level reference: the last run in gs[:before] of readings "within level_deg of g0, self-wobble ≤ ref_spread_deg, ≥ ref_min_n in a row",
    returns the average direction; returns None if not found."""
    n = rules["ref_min_n"]
    for end in range(before, n - 1, -1):
        win = gs[end - n:end]
        if all((angle_deg(g0, v) or 0.0) <= rules["level_deg"] for v in win):
            m = mean_dir(win)
            if m is not None and spread_deg(win, m) <= rules["ref_spread_deg"]:
                return m
    return None


# ---------------- Each step ----------------

def _r(x, nd=2):
    return None if x is None else round(x, nd)


def _gs(samples):
    return [g for g in (sample_gravity(s) for s in samples) if g is not None]


def check_still(samples, rules=RULES):
    gs = _gs(samples)
    out = {"step": "still", "name": STEP_CN["still"], "n": len(gs), "dropped": len(samples) - len(gs), "ok": False}
    if len(gs) < rules["still_min_n"]:
        out["msg"] = f"静止的读数只有 {len(gs)} 个（至少 {rules['still_min_n']} 个）：数据断了，或者采得太短"
        return out, None
    g0 = trimmed_mean_dir(gs)
    if g0 is None:
        out["msg"] = "静止的读数加起来是 0，算不出方向"
        return out, None
    spread = spread_p90_deg(gs, g0)
    out["spread_deg"] = _r(spread)
    out["max_dev_deg"] = _r(spread_deg(gs, g0))
    if spread > rules["still_max_spread_deg"]:
        out["msg"] = f"静止时读数晃了 {spread:.1f}°（最多 {rules['still_max_spread_deg']}°）：扶稳、别碰桌子，再来"
        return out, None
    out.update(ok=True, msg="稳")
    return out, g0


def check_tilt(step, samples, g0, rules=RULES):
    """Returns (this step's description, average gravity of the hold segment, level reference)."""
    gs = _gs(samples)
    name = STEP_CN[step]
    out = {"step": step, "name": name, "n": len(gs), "dropped": len(samples) - len(gs), "ok": False}
    if not gs:
        out["msg"] = f"「{name}」没有读数"
        return out, None, None
    idx, skipped = find_hold(gs, rules)
    hold = [gs[i] for i in idx]
    ref = find_ref(gs, g0, idx[0], rules)
    out["ref"] = "端平那一下" if ref is not None else "桌上静止"
    ref = ref or g0
    out["ref_offset_deg"] = _r(angle_deg(g0, ref))
    g = mean_dir(hold)
    tilt = angle_deg(ref, g) if g is not None else None
    tmax = max(angle_deg(ref, v) for v in hold)       # "maximum" is judged by the most-tilted reading in the hold segment, not the average
    out.update(n_used=len(hold), skipped=skipped, tilt_deg=_r(tilt), max_tilt_deg=_r(tmax),
               spread_deg=_r(spread_deg(hold, g) if g else None))
    if len(hold) < rules["hold_min_n"] or g is None:
        out["msg"] = f"「{name}」倾到位以后没停住（停住的读数只有 {len(hold)} 个）：倾到位停 1 秒"
        return out, None, None
    if tilt < rules["tilt_min_deg"]:
        out["msg"] = f"「{name}」只倾了 {tilt:.1f}°，至少要 {rules['tilt_min_deg']:.0f}°"
        return out, None, None
    if tmax > rules["tilt_max_deg"]:
        out["msg"] = f"「{name}」倾了 {tmax:.0f}°，太多了（最多 {rules['tilt_max_deg']:.0f}°）：脚会滑，读数也不稳"
        return out, None, None
    out.update(ok=True, msg=f"倾了 {tilt:.0f}°")
    return out, g, ref


# ---------------- Main function ----------------

def solve(samples, frame="body", old_mount=None, home_gravity=DOWN, rules=None, mode="full", old_verified=True,
          old_source=None):
    """Compute the mount orientation. For samples see the module docstring; returns a dict (all types JSON can send directly).

    mode="full": five steps (precise standing calibration). mode="coarse": only the "still" and "lean forward" steps ("lean back" is used too if present),
    for a duck whose orientation has never been confirmed and can't stand up: done limp, held up with both hands; the result is handed to robotd's verify-imu to verify again.
    Rough calibration has no left/right steps, fewer self-checks, and inaccurate stance compensation (held up isn't standing), so a precise standing calibration is still needed afterward; the result asks a person to tick it after comparing with the module's
    actual mounting (plan S1).
    old_verified=False: the old orientation is only a default (never verified), so it isn't used to judge "changed too much / turned around".
    old_source="coarse": the old orientation was written by the last rough calibration, so the "turned around" notice becomes "上次粗校可能做反了" (the last rough calibration may have been done reversed).

    Returned fields:
        ok         True / False
        reason     when not ok, one plain-language sentence (the first place that went wrong)
        redo       when not ok, which steps to redo (the page uses this to have the person redo only those steps, not start over)
        steps      each step: {step, name, ok, msg, n, n_used, tilt_deg, spread_deg, skew_deg, ref, ...}
        correction [w,x,y,z]: "current reading frame" → body frame (with frame="sensor" this is the mount orientation)
        mount      [w,x,y,z]: the new mount orientation (with frame="body", only present if old_mount is given)
        parts      the correction broken down (the first four only with frame="body"): pitch_deg (+ = reading leans forward of HOME when standing),
                   roll_deg (+ = leans left), yaw_deg (+ = the true forward is to the left of the current reading's "forward", counterclockwise seen from above),
                   stand_tilt_deg (how many degrees the standing reading is from HOME), total_deg (total rotation of the correction in degrees)
        quality    fb_pair_deg, lr_pair_deg, cross_deg, max_skew_deg (smaller is better), grade (good / ok / coarse), yaw_uncert_deg
        standard   which standard mounting the new orientation is closest to, and how many degrees off
        notes      things to know; confirm: things that need human confirmation before writing (the page needs a checkbox for each)
    """
    rules = dict(RULES, **(rules or {}))
    if frame not in ("body", "sensor"):
        raise ValueError("frame 只能是 body 或 sensor")
    if mode not in ("full", "coarse"):
        raise ValueError("mode 只能是 full 或 coarse")
    hg = unit(_v(home_gravity))
    if hg is None:
        raise ValueError("home_gravity 是零向量")
    steps = group_steps(samples)
    res = {"ok": False, "reason": None, "redo": [], "steps": {}, "frame": frame, "mode": mode, "rules": rules,
           "notes": [], "confirm": []}
    need = TILTS if mode == "full" else ("fwd",)
    optional = () if mode == "full" else ("back",)

    st, g0 = check_still(steps["still"], rules)
    res["steps"]["still"] = st
    gs, refs = {}, {}
    for k in need + optional:
        if g0 is None:
            res["steps"][k] = {"step": k, "name": STEP_CN[k], "ok": False, "msg": "先要静止那一步合格"}
            continue
        if k in optional and not steps[k]:
            continue
        res["steps"][k], g, ref = check_tilt(k, steps[k], g0, rules)
        if g is not None:
            gs[k], refs[k] = g, ref
    bad = [res["steps"][k] for k in ("still",) + need if not res["steps"][k]["ok"]]
    bad += [res["steps"][k] for k in optional if k in res["steps"] and not res["steps"][k]["ok"]]
    if bad:
        res["reason"] = bad[0]["msg"]
        # When the still step fails, the tilt steps are only "need a passing still first": just redo still, and keep the tilt readings for recomputing
        res["redo"] = ["still"] if g0 is None else [b["step"] for b in bad]
        return res

    up = scale(g0, -1.0)
    # Zero of the azimuth: the current reading frame's +x projected onto the horizontal plane (with raw chip axes x may be exactly vertical, then use +y)
    axis0 = unit(horiz((1.0, 0.0, 0.0), up)) or unit(horiz((0.0, 1.0, 0.0), up))
    c = {}
    for k in gs:
        d = horiz(sub(gs[k], refs[k]), up)
        az = signed_angle_deg(axis0, d, up)
        if az is None:
            res["reason"] = f"「{STEP_CN[k]}」倾的方向算不出来：重做这一步"
            res["redo"] = [k]
            return res
        c[k] = wrap180(az - EXPECT_DIR[k])      # which way this step believes "forward" points
    q = {}
    res["quality"] = q

    def pair(a, b):
        if a in c and b in c:
            d = abs(wrap180(c[a] - c[b]))
            q[f"{'fb' if a == 'fwd' else 'lr'}_pair_deg"] = _r(d)
            if d > rules["pair_max_deg"]:
                res["reason"] = (f"{STEP_CN[a]}和{STEP_CN[b]}的方向对不上（差了 {d:.0f}°，应该正好相反）："
                                 "是不是两次往同一边倾了？")
                res["redo"] = [a, b]
                return False
        return True

    if not pair("fwd", "back") or not pair("left", "right"):
        return res
    if mode == "full":
        psi_fb = circ_mean_deg([c["fwd"], c["back"]])
        psi_lr = circ_mean_deg([c["left"], c["right"]])
        crs = abs(wrap180(psi_fb - psi_lr))
        q["cross_deg"] = _r(crs)
        if crs > 90.0:
            res["reason"], res["redo"] = _swapped_reason(psi_fb, psi_lr, frame == "body" and old_verified)
            return res
    psi = circ_mean_deg(list(c.values()))
    skews = {k: wrap180(c[k] - psi) for k in c}
    for k, s in skews.items():
        res["steps"][k]["skew_deg"] = _r(abs(s))
    worst = max(skews, key=lambda k: abs(skews[k]))
    q["max_skew_deg"] = _r(abs(skews[worst]))
    if abs(skews[worst]) > rules["skew_max_deg"]:
        res["reason"] = (f"「{STEP_CN[worst]}」斜了 {abs(skews[worst]):.0f}°（应该正{STEP_CN[worst][0]}方）："
                         "照 3D 上箭头指的方向倾，手别拧")
        res["redo"] = [worst]
        return res
    if mode == "full":
        if crs > rules["cross_max_deg"]:
            res["reason"] = (f"前后和左右不垂直（差了 {crs:.0f}°，朝向会错一半那么多）："
                             "倾的时候手拧着了？照 3D 上的箭头，正前、正后、正左、正右")
            # When the old orientation is trustworthy, the pair farther from the current "forward" is most likely twisted; if not trustworthy, redo all four steps
            if frame == "body" and old_verified:
                res["redo"] = ["left", "right"] if abs(wrap180(psi_lr)) > abs(wrap180(psi_fb)) else ["fwd", "back"]
            else:
                res["redo"] = list(TILTS)
            return res
        q["grade"] = "good" if crs <= rules["good_cross_deg"] and abs(skews[worst]) <= rules["good_skew_deg"] else "ok"
        q["yaw_uncert_deg"] = _r(max(crs / 2, 0.5))
    else:
        q["grade"] = "coarse"
        res["notes"].append("粗校：只用了静止和前倾，左右没验；托着做的，站姿补偿不准。能站以后再站着精校一次")
    p = math.radians(psi)
    x_dir = add(scale(axis0, math.cos(p)), scale(cross(up, axis0), math.sin(p)))
    return _finish(res, g0, up, x_dir, hg, frame, old_mount, old_verified, old_source, rules)


def _swapped_reason(psi_fb, psi_lr, trust_old):
    """The forward/back pair and the left/right pair differ by ~180°: one pair was done reversed. When the old orientation is trustworthy, the pair farther from the current "forward" is the reversed one. Returns (reason, steps to redo)."""
    if trust_old:
        if abs(wrap180(psi_lr)) > abs(wrap180(psi_fb)):
            return "左倾、右倾做反了：左右以鸭子自己的为准（鸭子面对你时，它的左边在你右手边）", ["left", "right"]
        return "前倾、后倾做反了：头那边往下是前倾", ["fwd", "back"]
    return ("前后、左右里有一对做反了：前倾是头那边往下；左右以鸭子自己的为准（鸭子面对你时，它的左边在你右手边）",
            list(TILTS))


def _finish(res, g0, up, x_dir, hg, frame, old_mount, old_verified, old_source, rules):
    """Combine "up" + "forward" → three axes → correction / new orientation; then break it down and check what needs human confirmation."""
    y = unit(cross(up, x_dir))
    x = cross(y, up)
    r_lm = (x, y, up)                        # rows = the three axes of horizontal frame L: v_L = R_LM · v_M
    r_bl = mat_from_q(q_between(DOWN, hg))   # body attitude relative to the horizontal frame at HOME (yaw taken as 0)
    r_bm = mat_mul(r_bl, r_lm)
    corr = q_from_mat(r_bm)
    res["correction"] = [round(c, 9) for c in corr]

    # Breakdown: the stance part (pitch, roll) and the heading part (yaw)
    hp = math.degrees(math.atan2(hg[0], -hg[2]))
    hroll = math.degrees(math.atan2(hg[1], -hg[2]))
    parts = {"total_deg": _r(q_angle_deg(corr))}
    if frame == "body":
        parts["pitch_deg"] = _r(math.degrees(math.atan2(g0[0], -g0[2])) - hp)
        parts["roll_deg"] = _r(math.degrees(math.atan2(g0[1], -g0[2])) - hroll)
        parts["yaw_deg"] = _r(signed_angle_deg((1.0, 0.0, 0.0), x, up))
        parts["stand_tilt_deg"] = _r(angle_deg(g0, hg))
    res["parts"] = parts

    # New orientation
    if frame == "sensor":
        mount = corr
    elif old_mount is not None:
        mount = compose_mount(corr, q_normalize(old_mount))
    else:
        mount = None
        res["notes"].append("没给旧的安装方向，只能给出修正量，算不出新方向")
    if mount is not None:
        res["mount"] = [round(c, 9) for c in mount]
        res["standard"] = describe_mount(mount)

    # Things to know / to confirm
    full = res["mode"] == "full"
    if frame == "body" and old_verified and parts.get("yaw_deg") is not None:
        tot = q_angle_deg(corr)
        if abs(parts["yaw_deg"]) > rules["flip_deg"]:
            if old_source == "coarse":
                res["confirm"].append(
                    f"朝向要改 {parts['yaw_deg']:+.0f}°：上次粗校可能做反了（那次只验了「前」，没验左右）。"
                    "对照模块实际装法，确认现在这次是对的再写")
            else:
                res["confirm"].append(
                    f"朝向要改 {parts['yaw_deg']:+.0f}°。多半是前后、左右都做反了（相当于鸭子转了个身）。"
                    "只有确实把 IMU 模块转着装过，才照这个写")
        elif tot > rules["big_change_deg"]:
            res["confirm"].append(f"跟现在的方向差了 {tot:.1f}°，比较多：模块是不是装歪了、换过装法？确认了再写")
    if frame == "body" and full:
        st = parts["stand_tilt_deg"]
        if st is not None and st > rules["stand_confirm_deg"]:
            res["confirm"].append(
                f"站着时读数离官方 HOME 差 {st:.1f}°（主程序自己验方向时直立只放 {rules['stand_confirm_deg']:.0f}°）："
                "多半是腿的零位没校好、桌子不平，或者静止那 3 秒手碰着鸭子了。确认是模块装歪了再写")
        res["notes"].append(
            f"站着时读数比官方 HOME 前倾 {parts['pitch_deg']:+.1f}°、左倾 {parts['roll_deg']:+.1f}°，会一起折进安装方向"
            "（光靠 IMU 分不清是模块装歪还是腿让机身歪了；腿的零位先校好）")
    if not full and res.get("standard"):
        s = res["standard"]
        res["confirm"].append(
            f"粗校算出来：{s['text']}" + (f"（再偏 {s['off_deg']:.0f}°）" if s["off_deg"] >= 1 else "")
            + "。对照模块实际怎么装的，对得上再写（做反了主程序验不出左右）")
    if res.get("standard") and res["standard"]["off_deg"] > 20:
        res["notes"].append(f"新方向离最近的标准装法（{res['standard']['text']}）也差 {res['standard']['off_deg']:.0f}°：模块是斜着装的？")
    res["ok"] = True
    return res
