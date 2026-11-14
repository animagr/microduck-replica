"""Battery level estimation (battery-plan.md v2 final): warnings only, no automatic actions of any kind.

The duck has no fuel gauge and no ADC; the only measurement is the supply voltage reported by each of the 15 servos (0.1 V steps; the servos run directly on raw battery voltage).
So the battery level can only come from a "voltage lookup": accurate at rest, reading low under load when the voltage sags. The approach here (review B-R1…B-R15 + user decision on 10-18):

    one reading per second   among the fresh servos within 3.0–9.5 V, drop the highest 3 and lowest 3 and average (median if fewer than 9, skip this second if fewer than 5)
    three state classes       rest = relaxed · light = torque on but not moving (holding, standing, sitting) · heavy = walking / performing an action / fallen
    calm stretch         rest, light continuously for ≥ 30 seconds; each second take its median over the last 30 seconds and record one "calm reading"
    estimate           the highest calm reading in the last 5 minutes (= the calmest moment) + reading calibration → divide by 2 and look up;
                   if it never stopped in the 5 minutes → look up the median of the last 30 seconds directly, labeled "walking, rough estimate from under-load voltage, reads low" (a rough estimate yields at most the yellow bar)
    startup           after boot / Studio restart / no voltage readable for more than 10 seconds, the first 30 seconds only show "估算中" (estimating), no yellow or red
    display           integer, unchanged if within 2% of the previous value (dead band)
    warnings           a condition must hold for 60 consecutive seconds to light up, and must return 3% above the line for 60 consecutive seconds to clear;
                   under-load line: median of the last 10 seconds (after calibration) below 6.9 V for 30 consecutive seconds → the most prominent warning, cleared only after 60 seconds back above 7.0 V

Pure computation: no network, no bus, no threads, and time is passed in from outside (tests can fast-forward). Logging is done by the caller with the events feed() returns
(log_events); reading and writing the settings file also lives here (atomic writes; if corrupt, rename to .bad, use defaults, log a warn).
"""
import json
import math
import os
import tempfile
from collections import deque

LOG_CAT = "电池"

# 2S lithium-ion 18650 (NP-F550 etc.) resting open-circuit voltage → charge level. A compromise blended from several common 18650 curves, shaped toward lithium cobalt oxide:
# at the same voltage NMC cells have more charge, so this table is conservative (reports lower than actual), error about ±15% (battery-plan.md §1.1, review B-R5)
OCV_TABLE = ((4.20, 100), (4.15, 95), (4.10, 89), (4.05, 83), (4.00, 77), (3.95, 70), (3.90, 63), (3.85, 55),
             (3.80, 46), (3.75, 37), (3.70, 28), (3.65, 19), (3.60, 12), (3.55, 8), (3.50, 5), (3.40, 2),
             (3.30, 1), (3.00, 0))
CELLS = 2                       # HD-1910 maximum is 8.4 V: only 2S can be used
V_MIN, V_MAX = 3.0, 9.5         # a single servo reading outside this range is treated as not read
RD_EMPTY_V, RD_FULL_V = 6.6, 8.2    # robotd's own linear mapping (fork duck-control/src/model.rs:118-137), only used for comparison

ESTIMATING_S = 30       # the first 30 seconds after startup only show "估算中" (estimating) (B-R2)
CALM_S = 30             # a calm stretch must be at least this long to count (B-R4: 60 → 30)
CALM_WINDOW_S = 300     # "the calmest moment in the last 5 minutes"
LOAD_ROUGH_S = 30       # without a calm stretch, the rough estimate uses the median of the last 30 seconds
GAP_S = 10.0            # no voltage from any of the 15 servos for more than 10 seconds → start over (B-R4)
RUN_GAP_S = 10.0        # two samples in a calm stretch further apart than this break it
KEEP_S = CALM_WINDOW_S + 60
WARN_HOLD_S = 60        # yellow / red: must persist 60 seconds to light up and to clear
HYST_PCT = 3
LOW_MED_S = 10          # the under-load line looks at the median of the last 10 seconds
LOW_HOLD_S = 30         # under-load line: must persist 30 seconds to light up
LOW_CLEAR_HOLD_S = 60   # cleared only after returning 0.1 V above the line for 60 seconds
LOW_CLEAR_V = 0.1
DEADBAND_PCT = 2
GLITCH_V = 1.0          # this second is 1.0 V or more below the median of the last 60 seconds: log an entry (to tell a real brownout from a bad reading, B-R4).
                        # Not the 0.5 V the review suggested: when duck #1 walks, a one-second reading 0.5–0.8 V below the median is common (12 times in the 10-12 15:32 session); that is real load
GLITCH_EVERY_S = 60     # log at most one entry per minute
JUMP_PCT = 10           # estimate more than 10% higher than last time: log "battery swapped or charged"

# policy labels in robot.state: these mean "not performing an action" (fork robotd main.rs:3706-3720, control.rs:592)
CALM_LABELS = {"held", "walk", "stand", "homing", "sit"}
CLS_CN = {"rest": "卸力", "light": "站着 / 坐着", "heavy": "走路 / 做动作"}

MAINTENANCE = "放空了尽快充；长期不用存一半电（约 7.4–7.6 V）"
WARN_ONLY = "只警告：没电时鸭子不会自己停，用完关电源、拔电池（挂着卸力也在耗电）"


# ---------------- Lookup ----------------

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def soc_from_cell(vc):
    """Per-cell voltage → charge % (0–100, float; linear interpolation between grid points, clamped at both ends)."""
    if not _num(vc):
        return None
    if vc >= OCV_TABLE[0][0]:
        return 100.0
    for (hi_v, hi_p), (lo_v, lo_p) in zip(OCV_TABLE, OCV_TABLE[1:]):
        if lo_v <= vc <= hi_v:
            return lo_p + (vc - lo_v) / (hi_v - lo_v) * (hi_p - lo_p)
    return 0.0


def soc_from_pack(v, cells=CELLS):
    return soc_from_cell(v / cells) if _num(v) else None


def linear_pct(v):
    """robotd's algorithm: 6.6 V = 0%, 8.2 V = 100%, linear in between (under-load basis, reads high at the low end)."""
    if not _num(v) or v <= 0:
        return None
    return max(0.0, min(1.0, (v - RD_EMPTY_V) / (RD_FULL_V - RD_EMPTY_V))) * 100


# ---------------- One reading per second ----------------

def trimmed(volts, fresh=None):
    """15 voltages → this second's reading: (value or None, how many were used, [(index, voltage)] of the valid ones).
    Valid = a finite number, within 3.0–9.5 V, and fresh for that servo if fresh is given.
    ≥ 9 servos: drop the highest 3 and lowest 3 and average; 5–8: take the median; fewer than 5: return None."""
    valid = []
    for i, v in enumerate(volts or ()):
        if fresh is not None and (i >= len(fresh) or fresh[i] is not True):
            continue
        if _num(v) and V_MIN <= v <= V_MAX:
            valid.append((i, float(v)))
    n = len(valid)
    if n < 5:
        return None, n, valid
    xs = sorted(v for _, v in valid)
    if n >= 9:
        mid = xs[3:-3]
        return sum(mid) / len(mid), n, valid
    return _median(xs), n, valid


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def classify(torque_on, moving=False, fallen=False, label=None):
    """rest / light / heavy; None if torque cannot be read (this second counts neither as calm nor as anything other than for the under-load line)."""
    if torque_on is False:
        return "rest"
    if torque_on is not True:
        return None
    if moving or fallen or (isinstance(label, str) and label not in CALM_LABELS):
        return "heavy"
    return "light"


def classify_robotd(bus, state):
    """robotd's busStatus + robot.state → state class. Torque comes from native.torque_state_confirmed (confirmed by readback, not the command);
    motion comes from a nonzero move.applied, whether the policy label is an action (kicking, rolling, limp_fall…), and safety.fallen."""
    native = (bus or {}).get("native") if isinstance((bus or {}).get("native"), dict) else {}
    torque = native.get("torque_state_confirmed")
    st = state if isinstance(state, dict) else {}
    applied = (st.get("move") or {}).get("applied") if isinstance(st.get("move"), dict) else None
    moving = isinstance(applied, list) and any(_num(x) and abs(x) > 1e-3 for x in applied)
    fallen = (st.get("safety") or {}).get("fallen") is True if isinstance(st.get("safety"), dict) else False
    return classify(torque if isinstance(torque, bool) else None, moving, fallen, st.get("policy"))


def robotd_volts(bus):
    """busStatus → (15 voltages, 15 fresh flags). Returns (None, None) if unreadable."""
    native = (bus or {}).get("native") if isinstance((bus or {}).get("native"), dict) else {}
    joints = native.get("joints")
    if not isinstance(joints, list) or not joints:
        return None, None
    js = [j if isinstance(j, dict) else {} for j in joints]
    return [j.get("volts") for j in js], [j.get("feedback_fresh") is True for j in js]


def classify_servo_session(rows):
    """During servo tuning Studio holds the bus itself: any servo with torque on counts as light, all off counts as rest, unreadable returns None."""
    flags = [r.get("torque") for r in rows or () if isinstance(r, dict)]
    known = [bool(f) for f in flags if f is not None and f in (0, 1)]   # servo.py stores 0 / 1 (True / False also accepted)
    if not known:
        return None
    return "light" if any(known) else "rest"


def servo_session_volts(rows):
    """rows from servo.snapshot() → (voltages, fresh)."""
    rs = [r if isinstance(r, dict) else {} for r in rows or ()]
    if not rs:
        return None, None
    return [r.get("volt") for r in rs], [r.get("fresh") is True for r in rs]


# ---------------- Settings ----------------

SETTINGS_FILE = "battery-settings.json"
SETTINGS_VERSION = 1
PRESETS = {"2s_liion": "2S 锂电（NP-F550 等）", "bench": "台架电源（不算电量）"}
DEFAULTS = {"preset": "2s_liion", "warn_pct": 30, "red_pct": 15, "load_floor_v": 6.9, "cal_offset_v": 0.0}
RANGES = {"warn_pct": (15, 60), "red_pct": (5, 40), "load_floor_v": (6.6, 7.4), "cal_offset_v": (-0.5, 0.5)}
LABELS = {"preset": "电池型号", "warn_pct": "提醒线", "red_pct": "红线", "load_floor_v": "负载电压线", "cal_offset_v": "读数校准"}
CAL_CONFIRM_V = 0.3     # a calibration difference beyond ±0.3 V asks for confirmation first (most likely a mismeasurement, B-R11)


class SettingsError(ValueError):
    pass


def _check_item(k, v):
    """Whether one item is valid: returns (normalized value, None) or (None, reason)."""
    if k == "preset":
        return (v, None) if v in PRESETS else (None, f"只能是 {'、'.join(PRESETS)}")
    lo, hi = RANGES[k]
    if not _num(v):
        return None, "要是数字"
    if k in ("warn_pct", "red_pct"):
        if float(v) != int(v):
            return None, "要是整数"
        v = int(v)
    else:
        v = round(float(v), 2)
    if not lo <= v <= hi:
        return None, f"要在 {lo}–{hi} 之间"
    return v, None


def validate_settings(values, base=None):
    """Merge values (may be just a few items) onto base (default DEFAULTS): returns (new settings, [errors…]). If there are errors the new settings must not be used.
    Unknown items count as errors (we want to know if the page sent something wrong); the red line must be at least 5% below the warning line."""
    out = dict(DEFAULTS if base is None else base)
    errors = []
    if not isinstance(values, dict):
        return out, ["设置要是一个对象"]
    for k, v in values.items():
        if k not in DEFAULTS:
            errors.append(f"不认识的设置项「{k}」")
            continue
        good, why = _check_item(k, v)
        if why:
            errors.append(f"{LABELS[k]}{why}（收到 {v!r}）")
        else:
            out[k] = good
    if not errors and out["red_pct"] > out["warn_pct"] - 5:
        errors.append(f"红线（{out['red_pct']}%）要比提醒线（{out['warn_pct']}%）至少低 5%")
    return out, errors


def settings_path(state_dir):
    return os.path.join(state_dir or ".", SETTINGS_FILE)


def load_settings(state_dir, log=None):
    """Read settings. No file = defaults. Corrupt file (not JSON, top level not an object): rename it to .bad and keep it, use defaults, log one warn line;
    individual bad items: use defaults for those items, log one warn line; unknown items are ignored (added by later versions). Never raises."""
    p = settings_path(state_dir)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"顶层不是对象（{type(data).__name__}）")
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (OSError, ValueError) as e:
        bad = p + ".bad"
        try:
            os.replace(p, bad)
        except OSError:
            bad = None
        if log is not None:
            log.warn("电池设置读不出来，用默认值", cat=LOG_CAT, step=p, raw=f"{type(e).__name__}: {e}",
                     hint=(f"坏文件留在 {bad}；去设置页重新存一次就好" if bad else "坏文件改名也没成功，看看 state 目录的权限"))
        return dict(DEFAULTS)
    out, wrong = dict(DEFAULTS), []
    for k in DEFAULTS:
        if k in data:
            good, why = _check_item(k, data[k])
            if why:
                wrong.append(f"{LABELS[k]}={data[k]!r}（{why}）")
            else:
                out[k] = good
    if out["red_pct"] > out["warn_pct"] - 5:
        wrong.append(f"红线 {out['red_pct']}% 没比提醒线 {out['warn_pct']}% 低 5%")
        out["warn_pct"], out["red_pct"] = DEFAULTS["warn_pct"], DEFAULTS["red_pct"]
    if wrong and log is not None:
        log.warn("电池设置里有几项不对，那几项用默认值", cat=LOG_CAT, step=p, raw="；".join(wrong),
                 hint="多半是手改过；去设置页重新存一次就好")
    return out


def save_settings(state_dir, settings):
    """Write back the whole thing (write a temp file and then rename, so a power loss halfway does not corrupt the old one). Validates first and raises SettingsError if invalid; also raises if it cannot write."""
    good, errors = validate_settings(settings, DEFAULTS)
    if errors:
        raise SettingsError("；".join(errors))
    if not state_dir:
        raise SettingsError("这只鸭子没配 state 目录，存不了")
    os.makedirs(state_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".battery-settings-", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(good, v=SETTINGS_VERSION), f, ensure_ascii=False, indent=1)
        os.replace(tmp, settings_path(state_dir))
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise SettingsError(f"存不进去：{type(e).__name__}: {e}") from None
    return good


def settings_changes(old, new):
    """One line for the log: "red line 15% → 20%; reading calibration +0.00 → +0.12 V". Returns an empty string if nothing changed."""
    unit = {"warn_pct": "%", "red_pct": "%", "load_floor_v": " V", "cal_offset_v": " V"}
    parts = []
    for k in DEFAULTS:
        a, b = old.get(k), new.get(k)
        if a != b:
            fa = PRESETS.get(a, a) if k == "preset" else (f"{a:+.2f}" if k == "cal_offset_v" else a)
            fb = PRESETS.get(b, b) if k == "preset" else (f"{b:+.2f}" if k == "cal_offset_v" else b)
            parts.append(f"{LABELS[k]} {fa}{unit.get(k, '')} → {fb}{unit.get(k, '')}")
    return "；".join(parts)


# ---------------- Estimator ----------------

class _Latch:
    """A switch that turns on after persisting on_s seconds and off after persisting off_s seconds."""

    def __init__(self, on_s, off_s):
        self.on_s, self.off_s = on_s, off_s
        self.on = False
        self._since = None

    def step(self, now, cond_on, cond_off):
        """Returns "on" / "off" (if it just changed on this tick) or None."""
        if not self.on:
            if cond_on:
                self._since = now if self._since is None else self._since
                if now - self._since >= self.on_s:
                    self.on, self._since = True, None
                    return "on"
            else:
                self._since = None
        else:
            if cond_off:
                self._since = now if self._since is None else self._since
                if now - self._since >= self.off_s:
                    self.on, self._since = False, None
                    return "off"
            else:
                self._since = None
        return None

    def reset(self):
        self.on, self._since = False, None


def _ev(level, msg, hint=None, raw=None, ctx=None, step=None):
    return {"level": level, "msg": msg, "hint": hint, "raw": raw, "ctx": ctx, "step": step}


class Estimator:
    """One per duck. Fed by a separate 1 Hz loop (not in summarize, which runs 10 times per second per page, review B-R7);
    summarize only calls view(). feed() dedups by the sample key (busStatus sample time), so the same data fed several times counts only once."""

    def __init__(self, settings=None):
        self.settings = dict(DEFAULTS)
        if settings:
            self.set_settings(settings)
        self._ref_pct = None        # the last level shown before starting over (memory only): used to detect "battery swapped or charged"
        self._reset(None)

    # ---- State ----

    def _reset(self, now):
        self.samples = deque()      # (t, raw reading V, cls); raw = without calibration, which is applied at use time so setting changes take effect immediately
        self.calm = deque()         # (t, median of the last 30 seconds, dominant cls)
        self.started_at = None
        self.last_valid_t = None
        self.last_feed_t = None
        self.last_key = None
        self.run_start = None
        self.run_last_t = None
        self.shown = None
        self.mode = "no_data"
        self.est = None             # (pct float, basis V (calibrated), basis: calm / load, cls, basis time)
        self.spread = None
        self.started_logged = False
        self.warn = _Latch(WARN_HOLD_S, WARN_HOLD_S)
        self.red = _Latch(WARN_HOLD_S, WARN_HOLD_S)
        self.low = _Latch(LOW_HOLD_S, LOW_CLEAR_HOLD_S)
        self.low_min = None
        self.glitch_at = None
        self.n_used = 0
        self.source = None

    def set_settings(self, settings):
        good, errors = validate_settings(settings, DEFAULTS)
        if errors:
            raise SettingsError("；".join(errors))
        self.settings = good

    @property
    def off(self):
        return self.settings["cal_offset_v"]

    # ---- Feeding data ----

    def feed(self, now, volts=None, fresh=None, cls=None, key=None, source="robotd"):
        """Call once per second. volts=None or the same key as last time = no new data this second (timers still run: 10 seconds without readings means starting over).
        Returns the log events to record for this tick (recorded by log_events)."""
        events = []
        new = volts is not None and (key is None or key != self.last_key)
        if new and key is None and self.last_feed_t is not None and now - self.last_feed_t < 0.5:
            new = False             # without a key, dedup by time: feeding twice in the same second counts once
        if new:
            self.last_key, self.last_feed_t = key, now
            v, n, valid = trimmed(volts, fresh)
            self.n_used = n
            if v is not None:
                events += self._add(now, v, cls, valid, volts, source)
        if self.last_valid_t is not None and now - self.last_valid_t > GAP_S:
            if self.started_at is not None:
                events.append(_ev("warn", f"15 颗舵机都读不到电压超过 {GAP_S:.0f} 秒：电量重新估算",
                                  hint="舵机断电了（拔电池、换电池）或者总线断了；读数回来后先显示「估算中」30 秒",
                                  ctx={"last_pct": self.shown}))
                if self.shown is not None:
                    self._ref_pct = self.shown
            self._reset(now)
        events += self._evaluate(now)
        return events

    def _add(self, now, v, cls, valid, volts, source):
        events = []
        if self.started_at is None:
            self.started_at = now
        # Glitch: this second is more than 0.5 V below the median of the last 60 seconds (the median itself absorbs it; this just records it, with the 15 raw values)
        recent = [x for t, x, _ in self.samples if now - t <= 60]
        if len(recent) >= 10:
            med = _median(recent)
            if v < med - GLITCH_V and (self.glitch_at is None or now - self.glitch_at >= GLITCH_EVERY_S):
                self.glitch_at = now
                raw = [round(x, 2) if _num(x) else x for x in (volts or [])]
                # Fixed wording with the numbers in the original text: the Studio log records the same sentence only once per minute
                events.append(_ev("warn", "电压读数一下子掉了 1 V 以上",
                                  hint="一两秒的话不影响电量估算；经常出现要查电池接头和总线（看 15 颗原值分得清是真掉电还是读坏了）",
                                  raw=f"这一秒 {v:.2f} V，最近一分钟中位 {med:.2f} V；15 颗：{raw}",
                                  ctx={"cls": cls, "source": source}))
        self.samples.append((now, v, cls))
        self.last_valid_t = now
        self.source = source
        lo = min(valid, key=lambda x: x[1])
        hi = max(valid, key=lambda x: x[1])
        self.spread = {"min": lo[1], "min_i": lo[0], "max": hi[1], "max_i": hi[0], "n": len(valid)}
        # Calm stretch: continuous rest / light; broken if the gap is too long or another state arrives
        if cls in ("rest", "light"):
            if self.run_start is None or self.run_last_t is None or now - self.run_last_t > RUN_GAP_S:
                self.run_start = now
            self.run_last_t = now
            if now - self.run_start >= CALM_S:
                win = [(x, c) for t, x, c in self.samples if t >= now - CALM_S and t >= self.run_start]
                if len(win) >= CALM_S // 2:
                    nrest = sum(1 for _, c in win if c == "rest")
                    self.calm.append((now, _median([x for x, _ in win]), "rest" if nrest * 2 >= len(win) else "light"))
        else:
            self.run_start = self.run_last_t = None
        while self.samples and now - self.samples[0][0] > KEEP_S:
            self.samples.popleft()
        while self.calm and now - self.calm[0][0] > CALM_WINDOW_S:
            self.calm.popleft()
        return events

    # ---- Compute ----

    def _evaluate(self, now):
        events = []
        s = self.settings
        if self.started_at is None:
            self.mode, self.shown, self.est = "no_data", None, None
            return events
        bench = s["preset"] == "bench"
        warming = now - self.started_at < ESTIMATING_S
        while self.calm and now - self.calm[0][0] > CALM_WINDOW_S:
            self.calm.popleft()
        prev_mode = self.mode
        if bench:
            self.mode, self.shown, self.est = "bench", None, None
        elif warming:
            self.mode, self.shown, self.est = "estimating", None, None
        else:
            if self.calm:
                t, v, c = max(self.calm, key=lambda x: x[1])
                vv = v + self.off
                self.mode, self.est = "calm", (soc_from_pack(vv), vv, "calm", c, t)
            else:
                win = [x for t, x, _ in self.samples if now - t <= LOAD_ROUGH_S]
                if win:
                    vv = _median(win) + self.off
                    self.mode, self.est = "load_rough", (soc_from_pack(vv), vv, "load", None, now)
            if self.est is not None:
                pct = self.est[0]
                if self.shown is None or prev_mode != self.mode or abs(pct - self.shown) >= DEADBAND_PCT:
                    self.shown = int(round(pct))
                events += self._log_estimate(now)

        # Warnings: not judged during the 30-second startup (B-R2); bench supplies are not judged by percentage
        if warming:
            return events
        pct = self.shown
        w, r = s["warn_pct"], s["red_pct"]
        have = pct is not None and self.mode in ("calm", "load_rough")
        ch = self.warn.step(now, have and pct <= w, (not have) or pct >= w + HYST_PCT)
        if ch == "on":
            events.append(_ev("warn", f"电量到提醒线 {w}%：现在约 {pct}%",
                              hint="准备充电；" + self._basis_short(), ctx=self._ctx()))
        elif ch == "off":
            events.append(_ev("info", f"电量回到约 {pct}%，提醒收起" if pct is not None else "电量提醒收起", ctx=self._ctx()))
        # A rough estimate (walking the whole time, never stopped) yields at most the yellow bar: looking up under-load voltage reads low, so the red bar only trusts calm-stretch estimates or the under-load line (to avoid crying wolf)
        ch = self.red.step(now, have and self.mode == "calm" and pct <= r, (not have) or pct >= r + HYST_PCT)
        if ch == "on":
            events.append(_ev("error", f"电量到红线 {r}%：现在约 {pct}%",
                              hint="该充电了；" + WARN_ONLY, ctx=self._ctx()))
        elif ch == "off":
            events.append(_ev("info", f"电量回到约 {pct}%，红线收起" if pct is not None else "电量红线收起", ctx=self._ctx()))
        # Under-load line: median of the last 10 seconds (after calibration) below the setting for 30 seconds
        m10 = self.volts_now(now)
        floor = s["load_floor_v"]
        if m10 is not None and m10 < floor:
            self.low_min = m10 if self.low_min is None else min(self.low_min, m10)
        ch = self.low.step(now, m10 is not None and m10 < floor, m10 is not None and m10 >= floor + LOW_CLEAR_V)
        if ch == "on":
            events.append(_ev("error", f"电压很低：最近 {LOW_HOLD_S} 秒都在 {floor:.1f} V 以下（最低 {self.low_min:.2f} V）",
                              hint="先停下、坐下，准备充电；" + WARN_ONLY, ctx=self._ctx()))
        elif ch == "off":
            events.append(_ev("info", f"电压回到 {m10:.2f} V，负载线提醒收起", ctx=self._ctx()))
            self.low_min = None
        if not self.low.on and not (m10 is not None and m10 < floor):
            self.low_min = None
        return events

    def _log_estimate(self, now):
        """Log an entry for the first value after startup; after starting over (no voltage for 10+ seconds), if the first calm-stretch estimate is more than 10% higher than before the gap,
        log "battery swapped or charged". Not judged while readings are continuous: switching from holding to relaxed can read 20% higher on the same battery (the 10-12 15:32 session)."""
        events = []
        pct, vv, kind, c, _ = self.est
        if not self.started_logged:
            self.started_logged = True
            events.append(_ev("info", f"电量估算起步：{self._basis_short()} → 约 {int(round(pct))}%",
                              hint=f"查表估的，误差约 ±15%；读数校准 {self.off:+.2f} V", ctx=self._ctx()))
        ref = self._ref_pct
        if ref is not None and kind == "calm":
            if pct - ref >= JUMP_PCT:
                events.append(_ev("info", f"电量估算比断电前高了 {pct - ref:.0f}%：换了电池或充过电",
                                  hint=f"约 {ref:.0f}% → {pct:.0f}%（{self._basis_short()}）", ctx=self._ctx()))
            self._ref_pct = None
        return events

    # ---- Reading results ----

    def volts_now(self, now):
        """Median of the last 10 seconds (with calibration), for the small text and the under-load line. Returns None with fewer than 5 samples."""
        win = [x for t, x, _ in self.samples if now - t <= LOW_MED_S]
        return _median(win) + self.off if len(win) >= 5 else None

    def level(self):
        if self.red.on or self.low.on:
            return "error"
        return "warn" if self.warn.on else None

    def current_cls(self):
        return self.samples[-1][2] if self.samples else None

    def _basis_short(self):
        if self.est is None:
            return "还没有读数"
        _, vv, kind, c, _ = self.est
        if kind == "calm":
            return f"{'卸力' if c == 'rest' else '站着 / 坐着'}时 {vv:.2f} V"
        return f"走路中 {vv:.2f} V（负载电压，偏低）"

    def _ctx(self):
        return {"mode": self.mode, "pct": self.shown, "cls": self.current_cls(), "source": self.source,
                "basis_v": round(self.est[1], 3) if self.est else None, "cal": self.off,
                "calm_points": len(self.calm), "samples": len(self.samples)}

    def view(self, now, rd=None, names=None, shutdown=None):
        """For the page: the battery cell, details dialog and to-dos all come from here. rd: battery from robotd health ({volts, percent});
        names: Chinese names of the 15 servos (in volts order); shutdown: robotd's configured battery_empty_shutdown (onboard.read_battery_shutdown)."""
        s = self.settings
        v10 = self.volts_now(now)
        cls = self.current_cls()
        rd = rd if isinstance(rd, dict) else {}
        rd_v = rd.get("volts") if _num(rd.get("volts")) else None
        rd_pct = rd.get("percent") if _num(rd.get("percent")) else (linear_pct(v10 - self.off) if v10 is not None else None)
        basis = None
        if self.est is not None:
            pct, vv, kind, c, t = self.est
            basis = {"kind": kind, "cls": c, "volts": round(vv, 2), "cell": round(vv / CELLS, 3),
                     "age_s": round(max(0.0, now - t)), "pct": round(pct, 1)}
        why = {
            "no_data": "读不到电压",
            "estimating": "估算中，刚开始读",
            "bench": "台架电源，不算电量",
            "load_rough": "走路中，按负载电压粗估，偏低",
        }.get(self.mode)
        if self.mode == "calm":
            why = ("静置" if cls == "rest" else "站着 / 坐着" if cls == "light"
                   else "走路中，按停下时的电压估" if cls == "heavy" else "按停下时的电压估")
        detail = self._detail(now, v10, cls, rd_v, rd_pct, names, shutdown)
        return {
            "pct": self.shown,
            "mode": self.mode,
            "level": self.level(),
            "warn": self.warn.on,
            "red": self.red.on,
            "low_volt": self.low.on,
            "volts": round(v10, 2) if v10 is not None else None,
            "cls": cls,
            "why": why,
            "basis": basis,
            "rd_volts": round(rd_v, 2) if rd_v is not None else None,
            "rd_pct": round(rd_pct) if rd_pct is not None else None,
            "spread": self._spread(names),
            "warn_pct": s["warn_pct"], "red_pct": s["red_pct"], "load_floor_v": s["load_floor_v"],
            "cal_offset_v": self.off, "preset": s["preset"], "source": self.source, "shutdown": shutdown,
            "estimating_left_s": (max(0, int(math.ceil(ESTIMATING_S - (now - self.started_at))))
                                  if self.mode == "estimating" else None),
            "detail": detail,
        }

    def _spread(self, names):
        sp = self.spread
        if not sp:
            return None
        nm = lambda i: names[i] if names and i < len(names) else f"第 {i + 1} 颗"
        return {"min": round(sp["min"], 2), "min_name": nm(sp["min_i"]), "max": round(sp["max"], 2),
                "max_name": nm(sp["max_i"]), "n": sp["n"]}

    def _detail(self, now, v10, cls, rd_v, rd_pct, names, shutdown):
        """A few lines of text for the details dialog: how this number was derived (users must be able to check)."""
        s = self.settings
        lines = []
        cal = f"校准 {self.off:+.2f} V"
        if self.mode == "no_data":
            lines.append("读不到舵机电压：舵机没电（没接电池？）或者主程序没在跑")
        elif self.mode == "estimating":
            left = max(0, int(math.ceil(ESTIMATING_S - (now - self.started_at))))
            lines.append(f"刚开始读电压，{left} 秒后出数（头 {ESTIMATING_S} 秒的读数可能正好落在迈步的低谷上，先不算）")
        elif self.mode == "bench":
            lines.append("设置里选的是台架电源：只显示电压，不算电量、不出电量提醒")
        elif self.est is not None:
            pct, vv, kind, c, t = self.est
            if kind == "calm":
                ago = int(now - t)
                when = "现在" if ago < 5 else f"{ago // 60} 分钟前" if ago >= 60 else f"{ago} 秒前"
                lines.append(f"最近 5 分钟最轻松的那会儿（{CLS_CN.get(c, c)}，{when}）：{vv:.2f} V"
                             f"（15 颗去掉最高最低各 3 颗的平均，{cal}）→ 每芯 {vv / CELLS:.2f} V → 约 {pct:.0f}%")
                if c == "light":
                    lines.append("站着、坐着时舵机在用电，电压比卸力低一点，所以这个数偏低一点；卸力静置 30 秒以上最准")
            else:
                lines.append(f"最近 5 分钟一直没停下来：按走路时的电压 {vv:.2f} V（{cal}）粗估约 {pct:.0f}%。"
                             "走路会把电压拉低，所以偏低；停下站一会儿（30 秒）就会按站着的电压重估")
            lines.append("2S 锂电通用查表，误差约 ±15%，没校准时偏保守（报得比实际低）")
        if v10 is not None and self.mode != "no_data":
            lines.append(f"现在：{v10:.2f} V（{CLS_CN.get(cls, '状态不明')}）")
        if self.mode in ("calm", "load_rough"):
            lines.append(f"提醒线 {s['warn_pct']}% · 红线 {s['red_pct']}% · 电压连续 {LOW_HOLD_S} 秒低于 {s['load_floor_v']:.1f} V 也会提醒"
                         "（都只是提醒；查表的 30% 比以前主程序直线的 30% 电压高，黄条会比以前早亮）")
        elif self.mode == "bench":
            lines.append(f"电压连续 {LOW_HOLD_S} 秒低于 {s['load_floor_v']:.1f} V 会提醒（可调电源限流了、线太细时会掉下去）")
        if rd_pct is not None and self.mode != "bench":
            src = f"{rd_v:.2f} V，" if rd_v is not None else ""
            lines.append(f"主程序自己的算法：{rd_pct:.0f}%（{src}6.6–8.2 V 直线，低电量偏高）")
        sp = self._spread(names)
        if sp and self.mode != "no_data":
            lines.append(f"{sp['n']} 颗电压：最低 {sp['min']:.1f} V（{sp['min_name']}）· 最高 {sp['max']:.1f} V（{sp['max_name']}）")
        if self.mode == "bench":
            return lines                # bench supply: no battery, so no charging or maintenance talk
        lines.append(stop_words({"source": self.source, "shutdown": shutdown}))
        lines.append(MAINTENANCE)
        return lines

    # ---- Calibration ----

    def calibrate(self, now, measured_v):
        """"I measured the battery voltage": only accepted after resting relaxed for a full 30 seconds (B-R11). Returns {ok, offset, confirm, reason};
        offset is the new reading calibration (battery terminal − servo reading), saved into settings after the caller confirms. A difference beyond ±0.3 V requires the user to confirm once more."""
        if not _num(measured_v) or not 6.0 <= measured_v <= 9.0:
            return {"ok": False, "offset": None, "confirm": False, "reason": "量到的电压要在 6.0–9.0 V 之间：看看是不是量错了、表笔接反了"}
        win = [(x, c) for t, x, c in self.samples if now - t <= CALM_S]
        rest_long = (self.run_start is not None and now - self.run_start >= CALM_S
                     and len(win) >= CALM_S // 2 and all(c == "rest" for _, c in win))
        if not rest_long:
            return {"ok": False, "offset": None, "confirm": False,
                    "reason": f"要先卸力静置 {CALM_S} 秒以上再量（静置时电压最稳）"}
        raw = _median([x for x, _ in win])
        off = round(measured_v - raw, 2)
        lo, hi = RANGES["cal_offset_v"]
        if not lo <= off <= hi:
            return {"ok": False, "offset": off, "confirm": False,
                    "reason": f"你量的 {measured_v:.2f} V 跟舵机读数 {raw:.2f} V 差了 {off:+.2f} V，超过 ±{hi} V：多半是量错了（量 HAT 的电池输入端）"}
        confirm = abs(off) > CAL_CONFIRM_V
        why = (f"舵机读数 {raw:.2f} V，你量的 {measured_v:.2f} V，差 {off:+.2f} V"
               + ("；差得有点多，确认是在 HAT 的电池输入端量的吗？" if confirm else ""))
        return {"ok": True, "offset": off, "confirm": confirm, "reason": why, "servo_v": round(raw, 3)}


# ---------------- For to-dos and the log ----------------

def stop_words(view):
    """Whether anyone will stop it when the battery is empty: warnings only (user 10-18). During servo tuning the main program is stopped, so even if auto-shutdown is enabled in the config it will not act."""
    if view.get("source") == "servo":
        return "调舵机时主程序停着，没电它不会自己坐下；用完关电源、拔电池"
    if view.get("shutdown") is True:
        return "主程序配置里开着「没电自动坐下关机」：10 秒平均降到 6.6 V 它会坐下关机"
    return WARN_ONLY


def todo_items(view):
    """Estimate → to-dos (most urgent first). Warnings only: the wording only gives advice."""
    if not isinstance(view, dict):
        return []
    items = []
    pct, floor = view.get("pct"), view.get("load_floor_v")
    if view.get("low_volt"):
        v = view.get("volts")
        vtxt = f"：{v:.2f} V" if _num(v) else ""
        if view.get("preset") == "bench":
            items.append({"key": "battery_low_volt", "level": "error", "msg": f"电源电压很低{vtxt}",
                          "hint": f"连续 {LOW_HOLD_S} 秒低于 {floor:.1f} V；看看可调电源是不是限流了、线是不是太细太长"})
        else:
            items.append({"key": "battery_low_volt", "level": "error", "msg": f"电压很低{vtxt}",
                          "hint": f"连续 {LOW_HOLD_S} 秒低于 {floor:.1f} V；先停下、坐下，准备充电。{stop_words(view)}"})
    rough = view.get("mode") == "load_rough"
    tail = "（走路中按负载电压粗估，偏低）" if rough else ""
    if view.get("red") and _num(pct):
        items.append({"key": "battery", "level": "error", "msg": f"电量只剩约 {pct}%",
                      "hint": f"该充电了。{stop_words(view)}"})
    elif view.get("warn") and _num(pct):
        items.append({"key": "battery", "level": "warn", "msg": f"电量约 {pct}%{tail}",
                      "hint": "准备充电；电压查表估的，误差约 ±15%，没校准时偏低"})
    return items


def log_events(log, events):
    """Write the events returned by feed() into the Studio log (category "电池" (battery)). Does nothing if log is None."""
    if log is None:
        return
    for e in events or ():
        log.write(e["msg"], cat=LOG_CAT, level=e["level"], step=e.get("step"), raw=e.get("raw"),
                  hint=e.get("hint"), ctx=e.get("ctx"))
