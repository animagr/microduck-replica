"""The "上手清单" (onboarding checklist) on the overview, plus the hysteresis for the board-temperature cell and the board temperature Studio reads itself (overview reshuffle §5, review O4–O8, O14, O15).

The checklist follows the "final criteria for each checklist step" table at the end of overview-merge-review.md, changed to 6 rows per §5 O14 (task 11 added step 3):
    card header (unnumbered) "连上鸭子" (Connect to the duck)
    1 servo zero positions   2 IMU orientation   3 write to the main program   4 pair gamepad   5 test e-stop   6 stand up, walk a few steps (still two records: stood, walked)
Each step has five states: ok ✓ 完成 (done) · skip ↷ 跳过了 (skipped) · todo ● 该做 / 要重做 (to do / redo) · no ○ 没做 (not done) · unk ? 读不到 (unreadable).
"Do now" = the first ● / ○ step (skipped ones and ones marked done all count as done). Later steps aren't locked and can still be done.

**Every row can be "去做" (Go do it), "已完成" (Done), or "跳过" (Skip) at any time** (user's real-hardware acceptance check on 10-20: "this logic is definitely wrong, let people skip directly",
"someone may have done it before and is going through again"; on 10-18 we already decided every step can be skipped. Duck #2's zero positions were calibrated long ago, yet it used to be locked and forced to recalibrate):
- "Done" = I did it before: record done.<step> = {at, by, fp}, the row shows ✓ and says "你标了已完成（时间）" (you marked it done (time));
- "Skip" = not now: record skipped.<step> = {at, by, fp}, the row shows ↷;
- the two are mutually exclusive (marking one deletes the other); marked rows offer "重新做" (Redo) + "取消" (Cancel), and a ✓ backed by Studio's own record only offers "Redo".
fp is bound to the same things as the step's formal record (servos: joint fingerprint; IMU: chip + orientation; write to main program, stand/walk: calibration fingerprint; test e-stop:
gamepad MAC + main program build; pair gamepad: not bound). When the fingerprint changes the mark is void and the row goes back to ● (the record is kept, and counts again if the fingerprint changes back);
if the fingerprint can't be read when marking, record null first and bind it the first time tick reads it (per C2: unreadable doesn't void).
**No longer locked, but consequential cases need two clicks**: the main program explicitly says it's not done (hard: calibration not finished, IMU orientation not confirmed, torque not allowed), unreadable (?),
a problem was found (found: IMU standing check off by 8.5°, e-stop tested but not working now, two sets of zero positions conflicting, third-round code review D5), test e-stop (review D11),
fingerprint unreadable, while tuning servos (the checklist is frozen, a mark only shows after handback) —— clicking "Done" or "Skip" takes two steps, and the second button states the consequence
(like "确定跳过？主程序说标定没做完：跳过了鸭子也站不起来" (Really skip? The main program says calibration isn't finished: even if skipped, the duck can't stand up)), and the backend also refuses without confirmed.
The ack in the record notes which kinds the second click confirmed: a mark that didn't confirm hard doesn't count while the main program explicitly says no ("the mark doesn't help");
a mark that didn't confirm found is voided and deleted from the record once a problem is found (previously after "Skip" it would keep showing "you said you did it before", hiding the problem).
Both ✓ and skipped rows can "Redo": that's the step's "Go do it"; the old record is kept and only replaced when a new result comes in.
Step 1 marked done / skipped: "servo zero positions" counts as satisfied in step 3's readiness (commit.py reads user_mark); step 2 marked, orientation not confirmed in the main program,
and no new calibration on the IMU page: step 3 writes the IMU in use with the default mounting and marks it confirmed (task 17, commit.py's _default_imu).

**The main program's fields only count as evidence of "not done"** (review O4): the fork's motion mode only opens the bus if all 15 servos are calibrated and the IMU is verified
(fork robotd main.rs:1510-1519), so in the control phase these two fields are always true; and that true may have been filled in by the install script with Duck #1's seed values
(fork packaging/rebuild-config.py:75-99), or written by hand (on 10-17 Duck #2 had verified = true written by hand).
"Done" has to come from Studio's own records: servo-calib/eeprom-*.json left by servo-page calibration, the user having clicked "已经校过，核对一下" (Already calibrated, check it) (old API,
the page no longer shows this button), one complete standing calibration on the IMU page differing < 2° from the orientation the main program uses; or the user's own "Done" mark.

Records are stored in state_dir/onboarding.json (review O6): write a temp file first, then rename; if the file is broken rename it to .bad and keep it, treat as empty, log a warn.
Each record carries "the conditions under which it holds"; when the conditions change it shows "redo", but the record itself isn't deleted:
    e-stop       {at, ms, mac, name, build}      gamepad changed (different MAC), main program upgraded (different build) → test again
    stand / walk {at, fp}                        fp = calibration fingerprint (15 servos' zero_raw / direction + the IMU orientation in use)
    servo check  {at, fp}                        fp = joint fingerprint (only the 15 servos' zero_raw / direction)
    IMU check    {at, source, mount_fp, ...}     chip or orientation changed → check again
    done / skip  done.<step> / skipped.<step> = {at, by, fp, ack?}   fp changed → doesn't count; ack: see above
Time is stored as time.time() (wall clock, for humans); when the duck boots without network the wall clock is stuck at 1970, and the page says "时间不准" (time inaccurate) for years < 2024.
Card swap: the state directory goes with the card, so a new card is naturally empty (zero positions are still in the servo EEPROM; click "Done" on step 1);
reinstalling Studio without touching /var/lib keeps it; swapping the board doesn't clear it (zero positions live in the servos and on the card, not with the board).

Judged in only one place in the backend: app's small task calls tick() every 0.5 seconds, and summarize only reads view() (10 times per second per page, can't write to disk there).
File reads (servo-calib directory, /sys/class/thermal) are done in a thread (io(), code review C9), and tick only uses the cache: a stalled SD card must not block relaxing
in the same event loop. The record file is validated entry by entry when read in; a bad entry is dropped with a warn logged, the others are used; when judging the whole checklist fails, the checklist shows "?" and the reason,
and the board-temperature hysteresis is computed separately and isn't affected by it (code review C1).
"""
import hashlib
import json
import os
import re
import tempfile
import threading
import time

from .estop import STARTING_LONG_S, STARTING_PHASES
from .imu import mount_of
from .robotd import fresh_calib
from .state import JOINT_CN, MAX_AGE, STILL_STARTING, posture, starting_secs
from .startup_status import startup_wait

ONBOARD_FILE = "onboarding.json"
SERVO_IDS = (20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14)   # same as servo.IDS (servo isn't imported here: it brings in the serial port)
STOOD_S = 3.0             # standing (holding / policy / walking with torque confirmed on) continuously this long counts as "has stood up" (review O6)
WALKED_S = 2.0            # walking accumulated this long counts as "has walked"
CPU_WARN_C = 80.0         # same as state.CPU_WARN_C: this board already idles at 77–78 °C
CPU_CLEAR_C = 77.0        # hysteresis: only cleared once it drops below this (review O8: without hysteresis, the gauge band and to-do item flip back and forth, pushing the controls below up and down)
STUDIO_SCAN_S = 10.0      # how often to rescan the servo-calib directory
THERMAL_ROOT = "/sys/class/thermal"
# Config read by robotd: the fork uses --params /etc/robot/feetech-ft5/robotd.toml (fork packaging/runtime.py:28, 123); the official default is /etc/robot/robotd.toml
ROBOTD_CONFIGS = ("/etc/robot/feetech-ft5/robotd.toml", "/etc/robot/robotd.toml")
ROBOTD_CFG_S = 30.0       # how often to reread it
CPUFREQ_ROOT = "/sys/devices/system/cpu/cpufreq"
STAND = ("holding", "policy", "walking")
# What motion mode reports when stuck "waiting for the bus" (fork main.rs:1546-1552; feetech.rs:1011-1049): reported both when calibration and when IMU fails
CALIB_ERR = re.compile(r"calibrat|motion_enabled|calibration file|IMU mounting", re.I)

TIPS = {
    "servo": "两套零位会打架：用 Studio 的舵机页标（标完，主程序文件里 15 颗的 zero_raw 都要是 2048）",
    "imu": "装歪 8.5° 一走就往前冲（一号鸭 10-12）",
    "commit": "写的时候主程序会先卸力：扶好鸭子，别让它摔了",
    "pad": "G50 Pro 先拨到 S 档",
    "estop": "每次换手柄都测一次",
    "walk": None,
}
TITLES = {"servo": "舵机零位", "imu": "IMU 方向", "commit": "写进主程序", "pad": "配手柄", "estop": "测急停", "walk": "站起来、走几步"}
ORDER = ("servo", "imu", "commit", "pad", "estop", "walk")
GO = {"servo": "servos", "imu": "imu", "commit": "commit", "pad": "pad_wizard", "estop": "estop", "walk": "remote"}   # each step's "Go do it" / "Redo"
SKIP_CHANGED = {"servo": "舵机零位", "imu": "IMU 方向（或芯片）", "commit": "标定", "estop": "手柄（或主程序版本）", "walk": "标定"}
COMMIT_TEXT = "把舵机零位、方向、IMU 方向写进主程序。出厂镜像是标定模式；写完会切到运动模式并重启（约 20 秒），以后开机直接就能站、能走，不开网页也行。"

# "Done" / "Skip" (user on 10-20): page action → record key; the two are mutually exclusive
KINDS = {"done": "done", "skip": "skipped"}
OTHER = {"done": "skip", "skip": "done"}
MARKED_TEXT = {"done": "你标了已完成", "skip": "跳过了（先不做）"}
MARKED_WORD = {"done": "标了已完成", "skip": "点过跳过"}
CHANGED_WORD = {"done": "标了已完成", "skip": "跳过"}
# The sentence for the second of two clicks: {q} is replaced by "跳过" / "标成已完成" (skip / mark as done, as a question), {v} by "跳过了" / "标成已完成" (skipped / marked as done, as a consequence)
ASK_Q = {"done": "标成已完成", "skip": "跳过"}
ASK_V = {"done": "标成已完成", "skip": "跳过了"}
# Cases that previously couldn't be skipped (main program explicitly says no: hard; a problem was found: found): now all clickable, with the consequence written on the second button
HARD_SERVO = "主程序说标定没做完：{v}鸭子也站不起来"
HARD_IMU = "主程序没确认 IMU 方向：{v}鸭子也站不起来"
HARD_STUCK = "主程序不让上力（标定或 IMU 方向没过）：{v}鸭子也站不起来"
UNK_WHY = "这一步现在读不到（{text}）：Studio 核对不了，就按你说的算"
FP_WHY = "{what}：Studio 先记下，读到以后再核对"
FROZEN_ASK = "确定{q}？在调舵机：清单停在调之前的样子，{v}要等交还主程序以后才显示"
FROZEN_UNDO = "确定取消？在调舵机：清单停在调之前的样子，取消了要等交还主程序以后才显示"


def fill(text, kind):
    """Replace {q}, {v} in the question / consequence with this action's wording (using replace: the reason may contain braces)."""
    return text.replace("{q}", ASK_Q[kind]).replace("{v}", ASK_V[kind]) if text else text


# ---------------- Fingerprints ----------------

def _joints(calib):
    cal = (calib or {}).get("calibration") if isinstance((calib or {}).get("calibration"), dict) else None
    js = (cal or {}).get("joints")
    return [j for j in js if isinstance(j, dict)] if isinstance(js, list) else None


def _hash(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def joints_fp(calib):
    """Fingerprint of the 15 servos' zero_raw / direction; returns None if the calibration file can't be read."""
    js = _joints(calib)
    if not js:
        return None
    return _hash(sorted([j.get("id"), j.get("zero_raw"), j.get("direction")] for j in js))


def mount_fp(source, quat):
    """Fingerprint of chip + mount orientation (quaternion to 4 decimals: reading the same file twice is always identical)."""
    if not isinstance(quat, (list, tuple)) or len(quat) != 4:
        return None
    try:
        return _hash([source, [round(float(x), 4) for x in quat]])
    except (TypeError, ValueError):
        return None


def full_fp(bus, calib):
    """Calibration fingerprint: joints + the IMU orientation in use (stood up / walked records are bound to it: after the calibration changes, stand and walk again)."""
    j = joints_fp(calib)
    source, mount = mount_of(bus, calib)
    m = mount_fp(source, (mount or {}).get("quat"))
    if j is None or m is None:
        return None
    return _hash([j, m])


# ---------------- Studio's own servo calibration records (servo_ops.py:426-441, 612-656, 735) ----------------

def studio_servo_record(state_dir):
    """Union of targets minus bad in non-simulated, non-undone eeprom-*.json; returns {"ids": set, "time": time string of the latest one}.
    Undo renames the file to undone-… (doesn't start with eeprom-, so it's naturally skipped); simulation-mode backups are in a temp directory and not visible here."""
    d = os.path.join(state_dir or ".", "servo-calib")
    ids, latest = set(), None
    try:
        names = sorted(f for f in os.listdir(d) if f.startswith("eeprom-") and f.endswith(".json"))
    except OSError:
        return {"ids": ids, "time": None}
    for fn in names:
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("sim"):
            continue
        targets = rec.get("targets") if isinstance(rec.get("targets"), dict) else {}
        bad = rec.get("bad") if isinstance(rec.get("bad"), dict) else {}
        got = {int(k) for k in targets if str(k).isdigit()} - {int(k) for k in bad if str(k).isdigit()}
        if got:
            ids |= got
            latest = rec.get("time") or latest
    return {"ids": ids, "time": latest}


# ---------------- Board temperature: read by Studio itself (following the algorithm in fork robotd/src/soc.rs) ----------------

def _read_int(path):
    try:
        with open(path, encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def read_board(thermal_root=THERMAL_ROOT, cpufreq_root=CPUFREQ_ROOT):
    """Board temperature and throttling, same algorithm as robotd health's cpu_temp_c / cpu_throttle (fork soc.rs:25-170):
    temperature is the hottest of all thermal_zones (≤ 0 °C is skipped as a bad sensor); frequency is the most throttled policy's
    scaling_max_freq / cpuinfo_max_freq; level is the deepest among cooling devices whose type name contains cpufreq.
    Returns None if unreadable (not Linux, development on a computer)."""
    try:
        zones = [e for e in os.listdir(thermal_root)]
    except OSError:
        return None
    hot = None
    for name in zones:
        if not name.startswith("thermal_zone"):
            continue
        milli = _read_int(os.path.join(thermal_root, name, "temp"))
        if milli is None or milli <= 0:
            continue
        c = milli / 1000.0
        hot = c if hot is None or c > hot else hot
    thr = None
    try:
        pols = os.listdir(cpufreq_root)
    except OSError:
        pols = []
    for name in pols:
        if not name.startswith("policy"):
            continue
        khz = _read_int(os.path.join(cpufreq_root, name, "scaling_max_freq"))
        mx = _read_int(os.path.join(cpufreq_root, name, "cpuinfo_max_freq"))
        if khz is None or not mx:
            continue
        if thr is None or khz * thr["max_khz"] < thr["khz"] * mx:
            thr = {"khz": khz, "max_khz": mx, "level": 0, "max_level": 0}
    if thr is not None:
        for name in zones:
            if not name.startswith("cooling_device"):
                continue
            try:
                with open(os.path.join(thermal_root, name, "type"), encoding="ascii") as f:
                    kind = f.read().strip()
            except OSError:
                continue
            if "cpufreq" not in kind:
                continue
            lv, mx = _read_int(os.path.join(thermal_root, name, "cur_state")), _read_int(os.path.join(thermal_root, name, "max_state"))
            if lv is None or not mx:
                continue
            if thr["max_level"] == 0 or lv * thr["max_level"] > thr["level"] * mx:
                thr.update(level=lv, max_level=mx)
    if hot is None and thr is None:
        return None
    return {"c": hot, "throttle": thr}


def read_battery_shutdown(paths=ROBOTD_CONFIGS):
    """What [safety] battery_empty_shutdown says in the robotd config: True / False; returns None if the file can't be read or the item isn't set
    (when unset robotd defaults to on: fork robotd-params lib.rs:1804; but we treat it as "unreadable", and the page says "won't sit down by itself", erring on the conservative side).
    Looks for the first file that exists, in order (the fork's, the official default)."""
    import tomllib
    for path in paths:
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return None
        v = (data.get("safety") or {}).get("battery_empty_shutdown") if isinstance(data.get("safety"), dict) else None
        return v if isinstance(v, bool) else None
    return None


# ---------------- Judging a step ----------------

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _f1(x):
    """One decimal place; non-numbers are written as "?" (the record file may contain null: code review C1)."""
    return f"{x:.1f}" if _num(x) else "?"


def _row(key, state, text, when=None, actions=(), note=None, hard=None, found=None, ask=None):
    """hard: the main program explicitly says this step isn't OK (calibration not finished, IMU orientation not confirmed, torque not allowed) —— even if marked, the duck can't stand up; "Done" / "Skip" take two clicks.
    found: done / checked, but the result is bad (a problem was found, review D5) —— the first button says "Redo", and marking takes two clicks.
    hard / found are consequences with {v} (fill replaces it with "跳过了" / "标成已完成"). ask: the sentence on the second e-stop-test button (with {q}, {v}, worded per situation: review D11).
    mark: whether the "Done" / "Skip" buttons take two clicks and what the second says (filled by with_mark); marked: this row is currently user-marked (done / skip)."""
    return {"key": key, "n": ORDER.index(key) + 1, "title": TITLES[key], "tip": TIPS[key], "state": state,
            "text": text, "when": when, "note": note, "actions": [{"do": d, "label": lab} for d, lab in actions],
            "hard": hard, "found": found, "ask": ask, "go": GO[key], "mark": None, "marked": None}


def header_of(inp):
    """The "连上鸭子" (Connect to the duck) on the card header (unnumbered). kind: ok / absent / connecting / bench / servo / commissioning / stuck_calib / starting / other."""
    bus = inp.get("bus") if isinstance(inp.get("bus"), dict) else None
    if inp.get("bench"):
        return {"ok": False, "kind": "bench", "text": "台架模式：不连主程序，清单不检查"}
    if inp.get("servo_session"):
        return {"ok": False, "kind": "servo", "text": "在舵机页调舵机（主程序按计划停着）：清单先停在调之前的样子"}
    if inp.get("present") is False:
        return {"ok": False, "kind": "absent", "text": "主程序没在跑：连不上 robotd"}
    if bus is None:
        return {"ok": False, "kind": "connecting", "text": "正在连主程序…"}
    mode, phase, err = bus.get("mode"), bus.get("phase"), bus.get("error")
    if phase in STARTING_PHASES:
        if err and CALIB_ERR.search(str(err)):
            return {"ok": False, "kind": "stuck_calib", "text": "主程序不让上力：标定或 IMU 方向没过", "raw": str(err)}
        wait = startup_wait(bus)
        if wait:
            text = wait["text"]
        elif (inp.get("starting_s") or 0) >= STARTING_LONG_S:
            # Still reporting a startup phase after 30 seconds: stop saying "still starting" (10-20 real hardware: the old fork's commissioning mode always reports configuring_bus)
            text = f"主程序一直报「启动中」，超过 {STARTING_LONG_S:.0f} 秒了：{STILL_STARTING}"
        else:
            text = "主程序还在启动"
        return {"ok": False, "kind": "starting", "text": text, "raw": str(err) if err else None}
    if mode == "commissioning":
        # Commissioning mode's live snapshot (phase is ready / moving / read_error / stop_unconfirmed / power_pending): the main program is up.
        # read_error also counts as up, just that reading servos failed this tick: pass along the main program's original message as is
        if phase == "read_error":
            return {"ok": False, "kind": "commissioning", "text": "标定模式：主程序起来了，但读舵机出错（看舵机电源和线）",
                    "raw": str(bus.get("last_cycle_error") or err or "") or None}
        return {"ok": False, "kind": "commissioning", "text": "标定模式：做完 IMU 粗校，第 3 步写完会自动切运动模式"}
    if mode == "motion" and phase == "control":
        return {"ok": True, "kind": "ok", "text": "连上了"}
    return {"ok": False, "kind": "other", "text": f"主程序在 {mode or '?'} 模式、{phase or '?'} 阶段"}


def _imu_mount_unverified(bus, calib):
    """Does the main program explicitly say the IMU orientation isn't confirmed: busStatus's native.imu_mount_verified or the calibration file's mount.verified is False.
    Unknown also counts as False (only block when the main program explicitly says not confirmed)."""
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    _source, mount = mount_of(bus, calib)
    return native.get("imu_mount_verified") is False or (isinstance(mount, dict) and mount.get("verified") is False)


def servo_row(inp, rec, head):
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if head["kind"] in ("absent", "connecting", "bench"):
        return _row("servo", "unk", "连上主程序才判得出", actions=[("servos", "去舵机页")])
    uncal = (calib or {}).get("uncalibrated_joints")
    if head["kind"] == "stuck_calib":
        # Only when the IMU is explicitly not confirmed and all joints are calibrated (uncalibrated_joints is an empty list) is the cause in the IMU:
        # the servo row isn't hard and is judged by normal logic; otherwise hard as before.
        if not (_imu_mount_unverified(bus, calib) and isinstance(uncal, list) and not uncal):
            return _row("servo", "no", "主程序不让上力：标定或 IMU 方向没过（它报的是同一句话，分不出是哪个）",
                        actions=[("servos", "去舵机页")], hard=HARD_STUCK)
    js = _joints(calib)
    if isinstance(uncal, list) and uncal:
        names = "、".join(JOINT_CN.get(str(x), str(x)) for x in uncal[:4]) + ("…" if len(uncal) > 4 else "")
        return _row("servo", "no", f"主程序说 {len(uncal)} 颗还没标：{names}", actions=[("servos", "去舵机页")], hard=HARD_SERVO)
    if js and any(j.get("calibrated") is False for j in js):
        bad = [JOINT_CN.get(j.get("name"), j.get("name")) for j in js if j.get("calibrated") is False]
        return _row("servo", "no", f"主程序文件里 {len(bad)} 颗没标：{'、'.join(bad[:4])}", actions=[("servos", "去舵机页")],
                    hard=HARD_SERVO)
    if head["kind"] == "commissioning" and bus.get("calibrated") is False:
        return _row("servo", "no", "标定模式下主程序说标定没做完", actions=[("servos", "去舵机页")], hard=HARD_SERVO)
    if not js:
        return _row("servo", "unk", "这次连上以后还没读到主程序的标定文件（calibration-status）", actions=[("servos", "去舵机页")])
    off = [j for j in js if j.get("zero_raw") != 2048]
    if off:
        def one(j):
            z = j.get("zero_raw")
            d = f"（差 {(z - 2048) * 360 / 4096:+.1f}°）" if isinstance(z, (int, float)) else ""
            return f"{JOINT_CN.get(j.get('name'), j.get('name'))} {z}{d}"
        text = f"两套零位会打架：主程序文件里 {len(off)} 颗的 zero_raw 不是 2048——" + "、".join(one(j) for j in off[:3]) \
            + ("…" if len(off) > 3 else "") + "。多半是随包的一号鸭数值，在舵机页标一遍"
        return _row("servo", "todo", text, actions=[("servos", "去舵机页")],
                    found="两套零位会打架：{v}也会站歪、走偏（第 3 步按 2048 写零位）")
    st = inp.get("studio_servo") or {}
    fp = joints_fp(calib)
    if set(SERVO_IDS) <= set(st.get("ids") or ()):
        # Servo page calibrated all 15: record the joint fingerprint at first sight (servo_studio, recorded in _track); after that, if the fingerprint changes it must be checked again
        # (criteria table: "and the fingerprint hasn't changed", code review C9-3)
        ss = rec.get("servo_studio") if isinstance(rec.get("servo_studio"), dict) else None
        if ss and ss.get("src") == st.get("time") and ss.get("fp") == fp:
            return _row("servo", "ok", "舵机页标过；主程序文件里 15 颗都是 2048", when=st.get("time"))
        if ss and ss.get("src") == st.get("time"):
            return _row("servo", "todo", "舵机页标过以后，主程序的标定文件改过了：确实校过就点「已完成」，或者在舵机页再标一遍",
                        when=st.get("time"), actions=[("servos", "去舵机页")])
    c = rec.get("confirm_servo") if isinstance(rec.get("confirm_servo"), dict) else None
    if c and c.get("fp") == fp:
        return _row("servo", "ok", "核对过：主程序文件里 15 颗都是 2048", when=c.get("at"))
    if c:
        return _row("servo", "todo", "核对以后主程序的标定文件改过了：确实校过就点「已完成」，或者在舵机页标一遍",
                    actions=[("servos", "去舵机页")])
    # There used to be an "已经校过，核对一下" (Already calibrated, check it) here: now "Done" among the three buttons is that (user on 10-20: Go do it, Done, Skip)
    return _row("servo", "todo", "主程序文件里写着标过（可能是随包的一号鸭数值或手改的），Studio 这边没有记录："
                "以前用 Studio 的舵机页校过就点「已完成」", actions=[("servos", "去舵机页")])


def imu_row(inp, rec, head):
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if head["kind"] in ("absent", "connecting", "bench"):
        return _row("imu", "unk", "连上主程序才判得出", actions=[("imu", "去 IMU 页")])
    source, mount = mount_of(bus, calib)
    # stuck_calib isn't blocked here: the main program explicitly saying IMU not confirmed is blocked by the two HARD_IMU branches below, otherwise judged by normal logic (skippable)
    if head["kind"] == "commissioning" and bus.get("imu_mount_verified") is False:
        return _row("imu", "no", "标定模式下主程序说 IMU 方向没确认", actions=[("imu", "去 IMU 页")], hard=HARD_IMU)
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    if native.get("imu_mount_verified") is False:
        # busStatus explicitly says not confirmed: an unreadable calibration status is also "not done", not "?" (code review C4; so that to-do item shouldn't be hidden either)
        return _row("imu", "no", "主程序说 IMU 的安装方向还没确认：装歪了走路会往前冲", actions=[("imu", "去 IMU 页")],
                    hard=HARD_IMU)
    if mount and mount.get("verified") is False:
        return _row("imu", "no", "主程序存的 IMU 方向还没确认（verified 不是 true）：fork 上没确认连站都不让",
                    actions=[("imu", "去 IMU 页")], hard=HARD_IMU)
    mfp = mount_fp(source, (mount or {}).get("quat"))
    if mfp is None:
        return _row("imu", "unk", "这次连上以后还没读到主程序存的 IMU 方向（calibration-status）", actions=[("imu", "去 IMU 页")])
    chk = rec.get("imu_check") if isinstance(rec.get("imu_check"), dict) else None
    if chk and chk.get("source") == source and chk.get("mount_fp") == mfp:
        d, t = chk.get("diff_deg"), chk.get("tilt_deg")
        if chk.get("ok") is True and _num(d):
            return _row("imu", "ok", f"IMU 页站着核过：跟主程序用的方向差 {_f1(d)}°", when=chk.get("at"))
        return _row("imu", "todo", f"上次站着核对：主程序用的方向跟算出来的差 {_f1(d)}°、站姿倾斜 {_f1(t)}°"
                    "（要差 < 2°、倾斜 ≤ 5°）", when=chk.get("at"), actions=[("imu", "去 IMU 页")],
                    found=f"站着核过，方向差 {_f1(d)}°：{{v}}走路也会往前冲（一号鸭 10-12 就是装歪 8.5°）")
    if chk:
        return _row("imu", "todo", "核对以后 IMU 方向（或芯片）改过了：去 IMU 页站着再核一次", actions=[("imu", "去 IMU 页")])
    return _row("imu", "todo", "文件里写着已确认；装歪 8.5° 也会显示已确认：去 IMU 页站着核一次", actions=[("imu", "去 IMU 页")])


def _commit_complete(bus, calib):
    """The main program's completion criteria (task 11): motion_enabled = true, all 15 servos calibrated, and the IMU entry in use verified.
    Read from calibration-status / busStatus, using the same mount_of as imu_row."""
    cal = (calib or {}).get("calibration") if isinstance(calib, dict) else None
    cal = cal if isinstance(cal, dict) else (calib if isinstance(calib, dict) else {})
    js = _joints(calib)
    _source, mount = mount_of(bus, calib)
    return (cal.get("motion_enabled") is True and isinstance(js, list) and len(js) == len(SERVO_IDS)
            and all(j.get("calibrated") is True for j in js)
            and isinstance(mount, dict) and mount.get("verified") is True)


def commit_row(inp, rec, head):
    """Step 3 "write to the main program": completion is judged by the main program's file; when not done, bring out CommitService's readiness item by item."""
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    cv = inp.get("commit") if isinstance(inp.get("commit"), dict) else None

    def out(state, text, actions=()):
        row = _row("commit", state, text, actions=actions)
        row["desc"] = COMMIT_TEXT
        if cv is not None and cv.get("note"):
            row["desc"] += "\n" + cv["note"]
        if cv is not None:
            row["commit"] = cv
        return row

    if head["kind"] in ("absent", "connecting", "bench"):
        return out("unk", "连上主程序才判得出", [("commit", "去看看")])
    if cv is not None and cv.get("dirty") is True:
        why = "、".join(cv.get("dirty_why") or []) or "有新改动"
        return out("todo", f"有新改动还没写进主程序：{why}", [("commit", "去写进主程序")])
    if _commit_complete(bus, calib):
        return out("ok", "写进主程序了：15 颗都标好、IMU 方向也确认了，开机直接就能站、能走",
                   [("commit", "重新写")])
    js = _joints(calib)
    if (not isinstance(js, list) or not js) and not (cv is not None and cv.get("preview_ok") is True):
        return out("unk", "这次连上以后还没读到主程序的标定文件：等几秒再试", [("commit", "去看看")])
    if cv is None:
        return out("todo", "还没写进主程序：等 Studio 把准备情况读出来", [("commit", "去看看")])
    items = cv.get("items") if isinstance(cv.get("items"), list) else []
    bad = [i for i in items if isinstance(i, dict) and not i.get("ok")]
    if bad:
        labels = "、".join(str(i.get("label") or "?") for i in bad[:3]) + ("…" if len(bad) > 3 else "")
        return out("todo", f"还差{labels}：{bad[0].get('text') or '照下面的清单补齐'}", [("commit", "去写进主程序")])
    if cv.get("ready") is True:
        return out("todo", "准备齐了：点「写进主程序」一次写好，写完主程序重启", [("commit", "去写进主程序")])
    return out("todo", "还没写进主程序：照下面的清单补齐再来", [("commit", "去写进主程序")])

def _pad_names(pads):
    return "、".join(p.get("name") or p.get("mac") or "手柄" for p in pads[:2])


def pad_row(inp, rec, head):
    pad = inp.get("pad")
    if pad is None:
        return _row("pad", "unk", "这只鸭子没开手柄的后端（台架模式）")
    pads = [p for p in pad.get("pads") or [] if isinstance(p, dict)]
    good = [p for p in pads if p.get("paired") and p.get("trusted")]
    if good:
        on = next((p for p in good if p.get("connected")), None)
        return _row("pad", "ok", f"{on.get('name') or '手柄'} · 连着" if on else
                    f"配过 {_pad_names(good)} · 没连（打开手柄就会自己连上）")
    if any(p.get("paired") for p in pads):
        return _row("pad", "todo", "配上了但没「信任」：重启鸭子以后不会自己回连，点「修复」", actions=[("pad_known", "去修复")])
    dev = pad.get("device") or {}
    if pad.get("attached"):
        return _row("pad", "ok", f"padd 看到 {dev.get('name') or '手柄'} 连着" + ("" if pad.get("known") else "（configd 读不到）"))
    if pad.get("known"):
        return _row("pad", "no", "还没配手柄（也可以先用下面的网页手柄）", actions=[("pad_wizard", "配对手柄")])
    seen = rec.get("pads_seen") if isinstance(rec.get("pads_seen"), dict) else {}
    tail = f"；以前配过 {'、'.join(list(seen.values())[:2])}" if seen else ""
    return _row("pad", "unk", f"读不到 configd 的手柄状态（有的鸭子关着它）{tail}", actions=[("pad_wizard", "配对手柄")])


def _current_pad(pad):
    """The current gamepad (mac, name): the connected one; the one seen by the side channel; if neither, the only one ever paired. Returns (None, None) if unreadable."""
    if pad is None:
        return None, None
    a = pad.get("active") or {}
    if a.get("mac"):
        return str(a["mac"]).upper(), a.get("name")
    dev = pad.get("device") or {}
    if pad.get("attached") and dev.get("unique"):
        return str(dev["unique"]).upper(), dev.get("name")
    paired = [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired") and p.get("mac")]
    if pad.get("known") and len(paired) == 1:
        return str(paired[0]["mac"]).upper(), paired[0].get("name")
    return None, None


def _no_physical_pad(pad):
    """Definitely no physical gamepad (configd readable, none paired, side channel saw none either): only the web gamepad is used. configd unreadable doesn't count."""
    return bool(pad and pad.get("known") and not pad.get("attached")
                and not [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired")])


def _many_unconnected(pad):
    """More than one gamepad paired and none connected: can't tell which is "the current gamepad" (review D11: in this case say "connect a gamepad first, then test")."""
    if not pad or pad.get("attached") or (pad.get("active") or {}).get("mac"):
        return 0
    paired = [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired")]
    return len(paired) if len(paired) >= 2 and not any(p.get("connected") for p in paired) else 0


# Both "Done" and "Skip" for the e-stop test take two clicks (review D11); {q}, {v} are replaced by fill with this action's wording
ESTOP_ASK = {"never": "确定{q}？没测过：手柄 Select 能不能停住它没验过",
             "web": "确定{q}？只用网页的话急停是空格 / 顶上红按钮，以后配了手柄要再测",
             "pad": "确定{q}？换了手柄：这只手柄的 Select 没测过",
             "build": "确定{q}？主程序升级过：升级以后 Select 没测过",
             "bad": "确定{q}？急停现在不管用（{why}）：{v}也不会变好用"}


def estop_row(inp, rec, head):
    pad = inp.get("pad")
    r = rec.get("estop") if isinstance(rec.get("estop"), dict) else None
    es = (pad or {}).get("estop") or {}
    first_bad = next((c for c in es.get("checks") or [] if c.get("ok") is False), None)
    bad_why = f"{first_bad.get('label')}：{first_bad.get('why') or '×'}" if first_bad else None
    many = _many_unconnected(pad)
    if r is None:
        # No physical gamepad paired, web only: the web e-stop is space / the red button at the top (same path as the remote card's relax), doesn't go through a gamepad, no test needed (user on 10-18)
        web = _no_physical_pad(pad)
        web_only = "。只用网页的话：空格就是急停，跟顶上红按钮同一条路，不用测；可以跳过这步" if web else ""
        now = f"（配过 {many} 只手柄、现在都没连：先连上一只手柄再测）" if many else (f"（现在测不了：{bad_why}）" if bad_why else "")
        ask = ESTOP_ASK["web"] if web else (ESTOP_ASK["bad"].replace("{why}", bad_why) if es.get("state") == "bad" and bad_why
                                            else ESTOP_ASK["never"])
        return _row("estop", "no", "还没真按一次 Select 测过" + now + web_only, actions=[("estop", "去测急停")], ask=ask)
    mac, _ = _current_pad(pad)
    build = (inp.get("bus") or {}).get("build")
    if mac is None or not build:
        miss = (f"配过 {many} 只手柄、现在都没连：先连上一只手柄再测" if many else "读不到现在连的是哪只手柄") if mac is None \
            else "读不到主程序版本"
        return _row("estop", "unk", f"{r.get('name') or '手柄'} 测过，现在核对不了：{miss}", when=r.get("at"),
                    actions=[("estop", "去测急停")])
    if str(r.get("mac") or "").upper() != mac:
        return _row("estop", "todo", "换了手柄：再测一次", when=r.get("at"), actions=[("estop", "去测急停")], ask=ESTOP_ASK["pad"])
    if r.get("build") != build:
        return _row("estop", "todo", "主程序升级过：再测一次", when=r.get("at"), actions=[("estop", "去测急停")],
                    ask=ESTOP_ASK["build"])
    if es.get("state") == "bad":
        return _row("estop", "todo", f"测过，但现在急停不管用：{bad_why}", when=r.get("at"), actions=[("estop", "去看看")],
                    found=f"测过，但现在急停不管用（{bad_why}）：{{v}}也不会变好用，先把它弄好")
    ms = r.get("ms")
    return _row("estop", "ok", f"{r.get('name') or '手柄'} 测过：松开 Select 到卸力 {ms} ms" if _num(ms)
                else f"{r.get('name') or '手柄'} 测过", when=r.get("at"))


def walk_row(inp, rec, head):
    s = rec.get("stood") if isinstance(rec.get("stood"), dict) else None
    w = rec.get("walked") if isinstance(rec.get("walked"), dict) else None
    go = [("remote", "去遥控")]
    if s is None and w is None:
        return _row("walk", "no", "还没站起来过：托着它，点「站起来」，再点「开始走」、推左摇杆", actions=go)
    fp = inp.get("fp")
    last = (w if w is not None else s).get("at")
    if fp is None:
        return _row("walk", "unk", ("站起来过、走过" if w else "站起来过") + "；标定读不到，没法核对改没改过", when=last, actions=go)
    s_ok = s is not None and s.get("fp") == fp
    w_ok = w is not None and w.get("fp") == fp
    if w_ok:                                   # walked with the current calibration, so of course it has stood up too
        return _row("walk", "ok", "站起来过、走过", when=w.get("at"))
    if (s is not None and not s_ok) or w is not None:
        return _row("walk", "todo", "标定改过以后还没" + ("站过、走过" if not s_ok else "走过"), when=last, actions=go)
    return _row("walk", "todo", "站起来过，还没走过：点「开始走」，推左摇杆", when=s.get("at"), actions=go)


def step_fp(key, inp):
    """(whether this step's skip is bound to a fingerprint, the current fingerprint). Bound to the same things as the formal record; None if unreadable."""
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if key == "servo":
        return True, joints_fp(calib)
    if key == "imu":
        source, mount = mount_of(bus, calib)
        return True, mount_fp(source, (mount or {}).get("quat"))
    if key == "commit":
        return True, inp.get("fp")             # calibration (joints + IMU orientation) changed: skip is void, must rewrite
    if key == "estop":
        mac, _ = _current_pad(inp.get("pad"))
        if mac is None and _no_physical_pad(inp.get("pad")):
            mac = "无实体手柄"            # web only (string = "no physical gamepad"): once a gamepad is paired later, the fingerprint changes, the skip is void, and a test is needed
        build = bus.get("build")
        return True, (_hash([mac, build]) if mac and build else None)
    if key == "walk":
        return True, inp.get("fp")
    return False, None                          # pair gamepad: not bound


FP_WHAT = {"servo": "读不到主程序的标定文件", "imu": "读不到主程序存的 IMU 方向", "commit": "读不到标定",
           "estop": "读不到现在连的是哪只手柄（或主程序版本）", "walk": "读不到标定"}
BOUND = ("servo", "imu", "commit", "estop", "walk")      # steps whose marks are bound to a fingerprint (pair gamepad isn't)


def _marks(rec, key):
    """This step's "Done" / "Skip" records: {kind: record} (normally at most one; if both exist, "Done" takes priority)."""
    out = {}
    for kind, rk in KINDS.items():
        d = rec.get(rk) if isinstance(rec.get(rk), dict) else {}
        if isinstance(d.get(key), dict):
            out[kind] = d[key]
    return out


def mark_offer(row, bound, fp):
    """The two buttons "Done" and "Skip" (user on 10-20: every row can be clicked at any time): whether two clicks are needed and what the second button says.
    The cases that previously couldn't be skipped all take two clicks: a problem was found (found) > the main program explicitly says no (hard) > test e-stop (the situation-specific sentence, review D11) >
    unreadable (?) > fingerprint unreadable. ack is the kinds of problems this row has: stored in the record when marking, and a confirmed problem won't void it later."""
    key = row["key"]
    acks = [k for k in ("found", "hard") if row.get(k)]
    if row["state"] == "unk":
        acks.append("unk")
    if bound and fp is None:
        acks.append("fp")
    if row.get("found"):
        ask = "确定{q}？" + row["found"]
    elif row.get("hard"):
        ask = "确定{q}？" + row["hard"]
    elif key == "estop" and row.get("ask"):
        ask = row["ask"]
    elif row["state"] == "unk":
        ask = "确定{q}？" + UNK_WHY.replace("{text}", row["text"])
    elif key == "estop":
        ask = ESTOP_ASK["never"]
    elif bound and fp is None:
        ask = "确定{q}？" + FP_WHY.replace("{what}", FP_WHAT[key])
    else:
        ask = None
    out = {"ack": acks}
    for kind in KINDS:
        out[kind] = {"confirm": ask is not None, "ask": fill(ask, kind)}
    return out


def with_mark(row, inp, rec):
    """Apply the user's "Done" / "Skip" mark to a row. Rows backed by Studio's own record and judged ✓ stay unchanged (only offer "Redo").
    Marked, fingerprint unchanged → ✓ "你标了已完成" (you marked it done) / ↷ "跳过了" (skipped) (the real situation underneath goes in note); fingerprint changed → ● "标了已完成以后 xx 改过了" (xx changed after you marked it done).
    A problem not confirmed at marking time shows up later: main program explicitly says no (hard) → the mark doesn't help; a problem was found (found) → void (void: tick deletes it).
    Unmarked rows carry mark: whether the two buttons take two clicks, and the second sentence (mark_offer)."""
    key = row["key"]
    if row["state"] == "ok":
        return row
    bound, fp = step_fp(key, inp)
    for kind, m in _marks(rec, key).items():
        ack = m.get("ack") if isinstance(m.get("ack"), list) else []
        if row.get("found") and "found" not in ack:
            row["note"] = f"之前{MARKED_WORD[kind]}；测出了问题以后{'跳过' if kind == 'skip' else '标的'}不算了"
            row["void"] = row.get("void", []) + [kind]
            continue
        if row.get("hard") and "hard" not in ack:
            row["note"] = f"之前{MARKED_WORD[kind]}，但现在主程序明说这一步不行：{'跳过' if kind == 'skip' else '标的'}不管用"
            continue
        old = m.get("fp")
        if bound and fp is not None and old is not None and old != fp:
            row = dict(row, state="todo", text=f"{CHANGED_WORD[kind]}以后{SKIP_CHANGED[key]}改过了：{row['text']}")
            continue
        out = _row(key, "ok" if kind == "done" else "skip", MARKED_TEXT[kind], when=m.get("at"))
        out["note"] = row["text"] if row["state"] != "unk" else None   # the real situation underneath, shown in small print on the page
        out["marked"] = kind
        for k in ("desc", "commit"):                                  # step 3's card still shows readiness when expanded
            if k in row:
                out[k] = row[k]
        return out
    row["mark"] = mark_offer(row, bound, fp)
    return row


def evaluate(inp, rec):
    """Pure function: inp is the context collected by Onboarding._inputs(), rec is the records. Returns the whole card for the page."""
    head = header_of(inp)
    rows = [servo_row(inp, rec, head), imu_row(inp, rec, head), commit_row(inp, rec, head),
            pad_row(inp, rec, head), estop_row(inp, rec, head), walk_row(inp, rec, head)]
    rows = [with_mark(r, inp, rec) for r in rows]
    nxt = next((r["key"] for r in rows if r["state"] in ("todo", "no")), None)
    return {"header": head, "rows": rows, "next": nxt, "all_done": all(r["state"] in ("ok", "skip") for r in rows),
            "skipped_n": sum(1 for r in rows if r["state"] == "skip"),
            "marked_n": sum(1 for r in rows if r.get("marked") == "done"), "frozen": False}


# ---------------- Validate record file entries one by one (code review C1: valid JSON but one entry of the wrong type must not make the whole checklist error every 0.5 seconds) ----------------

def _opt(x, *types):
    return x is None or (isinstance(x, types) and not isinstance(x, bool))


def _at(d):
    return _opt(d.get("at"), int, float)


CHECKS = {
    "confirm_servo": lambda d: _at(d) and isinstance(d.get("fp"), str),
    "servo_studio": lambda d: _at(d) and isinstance(d.get("fp"), str) and _opt(d.get("src"), str),
    "imu_check": lambda d: (_at(d) and _opt(d.get("source"), str) and isinstance(d.get("mount_fp"), str)
                            and _num(d.get("diff_deg")) and _opt(d.get("tilt_deg"), int, float) and isinstance(d.get("ok"), bool)),
    "estop": lambda d: (_at(d) and _opt(d.get("ms"), int, float) and _opt(d.get("mac"), str) and _opt(d.get("name"), str)
                        and _opt(d.get("build"), str)),
    "stood": lambda d: _num(d.get("at")) and isinstance(d.get("fp"), str),
    "walked": lambda d: _num(d.get("at")) and isinstance(d.get("fp"), str),
}


def clean_records(data):
    """(usable records, dropped [(key, reason)]). Known keys are checked one by one per CHECKS; pads_seen keeps only string → string; unknown keys are kept as is (added by future versions)."""
    out, bad = {}, []
    for k, v in data.items():
        if k == "v":
            continue
        if k == "pads_seen":
            if isinstance(v, dict):
                out[k] = {str(m): n for m, n in v.items() if isinstance(n, str)}
            else:
                bad.append((k, f"不是对象（{type(v).__name__}）"))
            continue
        if k in KINDS.values():
            # skipped.<step> / done.<step>: at must be a number (review D10); fp is a string, or null (fingerprint unreadable when marking:
            # bound the first time tick reads it; once bound, a fingerprint change still voids it); ack is a list of strings (optional)
            if not isinstance(v, dict):
                bad.append((k, f"不是对象（{type(v).__name__}）"))
                continue
            good = {}
            for step, e in v.items():
                if (step in ORDER and isinstance(e, dict) and _num(e.get("at")) and _opt(e.get("by"), str)
                        and _opt(e.get("fp"), str)
                        and (e.get("ack") is None or (isinstance(e.get("ack"), list)
                                                      and all(isinstance(a, str) for a in e["ack"])))):
                    good[step] = e
                else:
                    bad.append((f"{k}.{step}", json.dumps(e, ensure_ascii=False, default=str)[:120]))
            out[k] = good
            continue
        chk = CHECKS.get(k)
        if chk is None:
            out[k] = v
            continue
        try:
            ok = isinstance(v, dict) and bool(chk(v))
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            out[k] = v
        else:
            bad.append((k, json.dumps(v, ensure_ascii=False, default=str)[:120]))
    return out, bad


def error_view(why):
    """Judging the whole checklist failed: all six rows show "?" and the reason (not "还在判…" (still judging…) forever, code review C1)."""
    rows = [_row(k, "unk", f"Studio 判这一步时出错：{why}") for k in ORDER]
    return {"header": {"ok": False, "kind": "error", "text": "清单判的时候出错（看日志里「系统」那几行）", "raw": why},
            "rows": rows, "next": None, "all_done": False, "skipped_n": 0, "marked_n": 0, "frozen": False}


# ---------------- Main ----------------

class Onboarding:
    def __init__(self, state_dir, log, clock=time.monotonic, wall=time.time):
        self.state_dir, self.log = state_dir, log
        self.clock, self.wall = clock, wall
        self._lk = threading.Lock()
        self._save_lk = threading.Lock()      # held through the whole disk write: when two saves happen at once, the old one can't land later and overwrite the new one (code review C9-2)
        self.rec = {}
        self._dirty = False
        self._view = None
        self._stand_since = None
        self._walk_acc = 0.0
        self._walk_last = None
        self._studio = {"ids": set(), "time": None}
        self._studio_at = -1e9
        self._studio_mtime = None             # mtime of the servo-calib directory: don't reread files if unchanged
        self._eval_err = None                 # reason the last checklist judgment failed (the same error is only logged once)
        self._servo = None                    # the most recently seen servo session (used to judge "checklist frozen" when cancel-skip isn't given one)
        self.commit_service = None            # CommitService from studio/commit.py (hooked up by app; step 3's readiness comes from here)
        self.battery_shutdown = None          # [safety] battery_empty_shutdown from the robotd config: True / False / None (unreadable)
        self._cfg_at = -1e9
        self.robotd_configs = ROBOTD_CONFIGS
        self.cpu_hot = False                  # board "a bit hot", with hysteresis (review O8)
        self.board = None                     # board temperature read by Studio itself (fallback when robotd doesn't report)
        self._board_ok = os.path.isdir(THERMAL_ROOT)
        self.load()

    # ---- Files ----

    def path(self):
        return os.path.join(self.state_dir or ".", ONBOARD_FILE)

    def load(self):
        """Read the records. If the file is broken: rename it to .bad and keep it (so it can be inspected later), treat as empty, log a warn —— the overview must not crash because of it (review O6)."""
        p = self.path()
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"顶层不是对象（{type(data).__name__}）")
        except FileNotFoundError:
            self.rec = {}
            return
        except (OSError, ValueError) as e:
            bad = p + ".bad"
            try:
                os.replace(p, bad)
            except OSError:
                bad = None
            self.log.warn("上手清单的记录文件读不出来，当成空的重新记", cat="系统", step=p, raw=f"{type(e).__name__}: {e}",
                          hint=(f"坏文件留在 {bad}" if bad else "坏文件改名也没成功，看看 state 目录的权限"))
            self.rec = {}
            return
        self.rec, bad = clean_records(data)
        for k, raw in bad:
            self.log.warn(f"上手清单的记录「{k}」格式不对，这一条不用了", cat="系统", step=p, raw=raw,
                          hint="多半是手改过或者旧版本写的；那一步会按「没做」重新判，做一次就会重新记")

    def save(self):
        """Write the whole thing back (write a temp file first, then rename, so a power loss halfway doesn't corrupt the old one). Called in a thread; errors are only logged, not raised."""
        with self._save_lk:
            return self._save_locked()

    def _save_locked(self):
        with self._lk:
            if not self._dirty:
                return False
            data = dict(self.rec, v=1)
            self._dirty = False
        d = self.state_dir or "."
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".onboarding-", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path())
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as e:
            with self._lk:
                self._dirty = True              # retry next tick
            self.log.warn("上手清单的记录没存进去", cat="系统", step=self.path(), raw=f"{type(e).__name__}: {e}",
                          hint="state 目录满了或者没权限；不影响站和走，下次再试")
            return False
        return True

    def _put(self, key, value, say=None, cat="系统"):
        with self._lk:
            if self.rec.get(key) == value:
                return False
            self.rec[key] = value
            self._dirty = True
        if say:
            self.log.info(say, cat=cat, dedup=False)
        return True

    # ---- Records coming from outside ----

    def note_estop(self, r):
        """E-stop test passed (called from the e-stop test thread in pad.py: only changes memory). r = {ms, mac, name, build}."""
        try:
            rec = {"at": self.wall(), "ms": r.get("ms"), "mac": (str(r["mac"]).upper() if r.get("mac") else None),
                   "name": r.get("name"), "build": r.get("build")}
            self._put("estop", rec, say=f"上手清单：记下「测急停过了」（{rec['name'] or rec['mac'] or '手柄'}，主程序 {rec['build']}）",
                      cat="安全")
            return True
        except Exception:  # noqa: BLE001 —— in the e-stop test thread, failing to record must not cause trouble
            return False

    def note_imu_check(self, c):
        """Complete standing calibration on the IMU page (called by imu.py _check): record the latest check, whether close enough or not (if not, the checklist says "差 x°" (off by x°))."""
        rec = {"at": self.wall(), "source": c.get("source"), "mount_fp": mount_fp(c.get("source"), c.get("quat")),
               "diff_deg": c.get("diff_deg"), "tilt_deg": c.get("tilt_deg"), "ok": bool(c.get("ok")), "by": c.get("by")}
        if rec["mount_fp"] is None:
            return False
        return self._put("imu_check", rec, say=f"上手清单：记下 IMU 核对（差 {rec['diff_deg']}°，{'够' if rec['ok'] else '不够'}近）",
                         cat="IMU") or True

    def confirm_servo(self, rd, by=None):
        """The "Already calibrated, check it" action: only recorded if all 15 servos are calibrated in the main program's file and zero_raw are all 2048 (fingerprint bound to joints). If it can't be recorded, return the reason."""
        calib = fresh_calib(rd)
        js = _joints(calib)
        if not js:
            return False, "这次连上以后还没读到主程序的标定文件：等几秒再点"
        if (calib or {}).get("uncalibrated_joints"):
            return False, "主程序说还有没标的关节：去舵机页标"
        off = [j for j in js if j.get("zero_raw") != 2048 or j.get("calibrated") is False]
        if off:
            return False, f"有 {len(off)} 颗的 zero_raw 不是 2048（或者没标）：两套零位会打架，去舵机页标"
        if len(js) < len(SERVO_IDS):
            return False, f"主程序文件里只有 {len(js)} 颗"
        fp = joints_fp(calib)
        self._put("confirm_servo", {"at": self.wall(), "fp": fp, "by": by},
                  say=f"上手清单：舵机零位「已经校过，核对一下」（{by or '页面'}；主程序文件里 15 颗都是 2048）", cat="校准")
        return True, None

    def mark(self, step, kind, rd, pad=None, servo=None, by=None, confirmed=False):
        """Mark "Done" (kind=done, records done.<step>) / "Skip" (kind=skip, records skipped.<step>). Rejudge against the current situation:
        cases needing two clicks (main program explicitly says no, unreadable, a problem was found, test e-stop, fingerprint unreadable, while tuning servos) without confirmed return (False, the second sentence) ——
        the page's two-step confirmation can't rely on the front end alone. Record {at, by, fp, ack}: ack is the kinds of problems confirmed by the second click; the two marks are mutually exclusive."""
        if step not in ORDER:
            return False, f"不认识的步骤：{step}"
        if kind not in KINDS:
            return False, f"不认识的标法：{kind}"
        if servo is not None:
            self._servo = servo
        inp = self._inputs(rd, pad, servo, self.clock())
        if inp["bench"]:
            return False, "台架模式：清单现在不判，也不用标"
        with self._lk:
            rec = dict(self.rec)
        row = next(r for r in evaluate(inp, rec)["rows"] if r["key"] == step)
        if row.get("marked") == kind:
            return True, "已经跳过了" if kind == "skip" else "已经标了已完成"
        if row.get("marked"):
            return False, "这一步已经跳过了：先点「取消跳过」" if row["marked"] == "skip" else "这一步标了已完成：先点「取消」"
        if row["state"] == "ok":
            return False, "这一步已经完成了（Studio 有记录），不用再标"
        offer = row.get("mark") or {}
        ask = (offer.get(kind) or {}).get("ask")
        if inp["servo_session"] and not ask:
            ask = fill(FROZEN_ASK, kind)             # checklist frozen while tuning servos: a mark only shows after handback (review D11's freeze, now clickable)
        if ask and confirmed is not True:
            return False, f"要点两次确认：{ask}"
        bound, fp = step_fp(step, inp)
        entry = {"at": self.wall(), "by": by, "fp": fp if bound else None}
        if offer.get("ack"):
            entry["ack"] = list(offer["ack"])
        with self._lk:
            mine = dict(self.rec.get(KINDS[kind]) or {})
            theirs = dict(self.rec.get(KINDS[OTHER[kind]]) or {})
        mine[step] = entry
        word = "跳过" if kind == "skip" else "标了已完成"
        self._put(KINDS[kind], mine, cat="校准",
                  say=f"上手清单：{TITLES[step]} {word}（{by or '页面'}）" + (f"；点了两次确认：{ask}" if ask else ""))
        if theirs.pop(step, None) is not None:
            self._put(KINDS[OTHER[kind]], theirs)
        return True, None

    def skip(self, step, rd, pad=None, servo=None, by=None, confirmed=False):
        return self.mark(step, "skip", rd, pad, servo, by, confirmed)

    def mark_done(self, step, rd, pad=None, servo=None, by=None, confirmed=False):
        return self.mark(step, "done", rd, pad, servo, by, confirmed)

    def unmark(self, step, kind, by=None, servo=None, confirmed=False):
        """The "取消跳过" (Cancel skip) / "Cancel" (for done): delete that record, and the row goes back to being judged by the real situation.
        Checklist frozen while tuning servos: takes two clicks (a cancel only shows after handback); without confirmed return (False, that sentence)."""
        if step not in ORDER:
            return False, f"不认识的步骤：{step}"
        if kind not in KINDS:
            return False, f"不认识的标法：{kind}"
        sv = servo if servo is not None else self._servo      # if not passed, use the servo session most recently seen by tick / mark
        if sv is not None and getattr(sv, "state", None) in ("open", "opening") and confirmed is not True:
            return False, f"要点两次确认：{FROZEN_UNDO}"
        with self._lk:
            mine = dict(self.rec.get(KINDS[kind]) or {})
        if step not in mine:
            return True, "本来就没跳过" if kind == "skip" else "本来就没标已完成"
        mine.pop(step)
        word = "取消跳过" if kind == "skip" else "取消已完成"
        self._put(KINDS[kind], mine, say=f"上手清单：{TITLES[step]} {word}（{by or '页面'}）", cat="校准")
        return True, None

    def unskip(self, step, by=None, servo=None, confirmed=False):
        return self.unmark(step, "skip", by, servo, confirmed)

    def user_mark(self, step):
        """Whether what currently counts for step `step` was marked by the user: done ("Done") / skip ("Skip") / None.
        Used by commit.py's readiness (step 1 marked → "servo zero positions" counts as satisfied); reads the cache judged on the previous tick (tick every 0.5 seconds)."""
        rows = (self._view or {}).get("rows") or []
        r = next((x for x in rows if isinstance(x, dict) and x.get("key") == step), None)
        return r.get("marked") if r else None

    # ---- File reading: in a thread (app calls it with asyncio.to_thread), tick only uses the cache (code review C9-1) ----

    def need_board(self, rd):
        """Studio only needs to read /sys/class/thermal itself when robotd doesn't report temperature (debug mode, waiting for bus, stale). Called in the event loop (only looks at memory)."""
        ha = rd.health.age()
        h = rd.health.value if ha is not None and ha <= MAX_AGE["health"] else None
        return self._board_ok and not (isinstance(h, dict) and _num(h.get("cpu_temp_c")))

    def io(self, board=False, now=None):
        """Called in a thread: servo-calib directory (reread only if mtime changed or 10 seconds passed), board temperature (only read if board=True). Doesn't raise."""
        now = self.clock() if now is None else now
        try:
            d = os.path.join(self.state_dir or ".", "servo-calib")
            try:
                mt = os.stat(d).st_mtime
            except OSError:
                mt = None
            if mt != self._studio_mtime or now - self._studio_at >= STUDIO_SCAN_S:
                self._studio = studio_servo_record(self.state_dir)
                self._studio_mtime, self._studio_at = mt, now
        except Exception:  # noqa: BLE001 —— if unreadable, treat as no records
            pass
        if board:
            try:
                self.board = read_board()
            except Exception:  # noqa: BLE001
                self.board = None
        else:
            self.board = None
        if now - self._cfg_at >= ROBOTD_CFG_S:
            self._cfg_at = now
            self.battery_shutdown = read_battery_shutdown(self.robotd_configs)

    # ---- Once every 0.5 seconds ----

    def _inputs(self, rd, pad, servo, now):
        bus = rd.bus.value if isinstance(rd.bus.value, dict) else None
        calib = fresh_calib(rd)
        pv = None
        if pad is not None:
            try:
                pv = pad.onboard_view()
            except Exception as e:  # noqa: BLE001 —— gamepad backend error: this row says "unreadable", don't make the whole card disappear
                pv = {"known": False, "error": f"{type(e).__name__}: {e}", "pads": []}
        return {"bench": getattr(rd, "addr", None) == "none", "present": rd.present, "bus": bus, "calib": calib,
                "servo_session": servo is not None and getattr(servo, "state", None) in ("open", "opening"),
                "pad": pv, "studio_servo": self._studio, "fp": full_fp(bus, calib),
                # starting_since is recorded by polling on the real clock: use the real clock here too (in tests tick's now is set manually)
                "commit": self._commit_view(rd, servo), "starting_s": starting_secs(rd, bus)}

    def _commit_view(self, rd, servo):
        """Step 3's readiness (CommitService.view). If it can't be read, only this step shows "?"; don't make the whole card disappear."""
        svc = self.commit_service
        if svc is None:
            return None
        try:
            return svc.view(rd, servo)
        except Exception as e:  # noqa: BLE001
            return {"ready": False, "items": [], "job": None, "error": f"{type(e).__name__}: {e}"}

    def tick(self, rd, pad=None, servo=None, now=None):
        """Judge once and record what should be recorded (only changes memory, doesn't read files). Returns True = records changed; the caller save()s in a thread.
        The board-temperature hysteresis is computed first, in its own try: a checklist judgment error must not leave it stuck at the old value (code review C1)."""
        now = self.clock() if now is None else now
        if servo is not None:
            self._servo = servo
        try:
            self._board_tick(rd)
        except Exception as e:  # noqa: BLE001
            self.log.error("算主板温度的回差时出错", cat="系统", raw=f"{type(e).__name__}: {e}", exc=True)
        try:
            inp = self._inputs(rd, pad, servo, now)
            if not inp["servo_session"]:
                self._track(rd, inp, now)
                self._bind_marks(inp)
            with self._lk:
                rec = dict(self.rec)
            v = evaluate(inp, rec)
            if not inp["servo_session"]:
                self._void_marks(v)
            if inp["servo_session"] and self._view is not None and self._view["header"].get("kind") != "error":
                # Tuning servos on the servo page: the main program is stopped as planned, each step keeps its last display, grayed out (the "tuning servos" row of the review criteria table).
                # "Done", "Skip", "Cancel" can still be clicked, but take two clicks: the second says "要等交还以后才显示" (only shows after handback) (frozen_ask)
                v = dict(self._view, header=v["header"], frozen=True,
                         frozen_ask={"done": fill(FROZEN_ASK, "done"), "skip": fill(FROZEN_ASK, "skip"), "undo": FROZEN_UNDO})
            self._eval_err = None
        except Exception as e:  # noqa: BLE001 —— checklist error: the rows show "?" and the reason, log one line (the same error only once)
            why = f"{type(e).__name__}: {e}"[:200]
            if why != self._eval_err:
                self._eval_err = why
                self.log.error("上手清单判的时候出错，清单先写「?」", cat="系统", raw=why, exc=True,
                               hint="这是 Studio 的问题，导出诊断包发出来；不影响站和走")
            v = error_view(why)
        self._view = v
        with self._lk:
            return self._dirty

    def _void_marks(self, v):
        """Rows where a problem was found (found): "Skip" / "Done" marks that didn't previously confirm this problem are voided: deleted from the records, one line logged (review D5).
        The page already shows the problem this tick. Marks whose second click confirmed this problem (found in ack) are left alone."""
        for kind, rk in KINDS.items():
            gone = [r for r in v["rows"] if kind in (r.get("void") or ())]
            if not gone:
                continue
            with self._lk:
                d = dict(self.rec.get(rk) or {})
            for r in gone:
                d.pop(r["key"], None)
            word = "跳过" if kind == "skip" else "「已完成」"
            self._put(rk, d, cat="校准",
                      say="上手清单：" + "、".join(f"{r['title']}的{word}作废（{fill(r['found'], kind)}）" for r in gone))

    def _bind_marks(self, inp):
        """Fingerprint was unreadable at marking time (recorded null): bind the current fingerprint the first time it's read; after that a change still voids it (per C2: unreadable doesn't void)."""
        for kind, rk in KINDS.items():
            with self._lk:
                d = dict(self.rec.get(rk) or {}) if isinstance(self.rec.get(rk), dict) else {}
            named = []
            for step, e in list(d.items()):
                if step not in BOUND or not isinstance(e, dict) or e.get("fp") is not None:
                    continue
                _bound, fp = step_fp(step, inp)
                if fp is not None:
                    d[step] = dict(e, fp=fp)
                    named.append(TITLES[step])
            if named:
                word = "跳过" if kind == "skip" else "「已完成」"
                self._put(rk, d, cat="校准", say=f"上手清单：{'、'.join(named)}的{word}标的时候读不到指纹，现在读到了、绑上")

    def _track(self, rd, inp, now):
        """Stood up, walked, which gamepads were paired (only from the state Studio itself receives: robot.state is only pushed while a page is watching)."""
        bus = inp["bus"] or {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        # Data freshness uses the real clock (Sample records monotonic); how long it stood / walked uses now (adjustable in tests). Freshness same as state.MAX_AGE
        pa, sa = rd.policies.age(), rd.state.age()
        pol = rd.policies.value if pa is not None and pa <= MAX_AGE["policies"] else None
        st = rd.state.value if sa is not None and sa <= MAX_AGE["state"] else None
        pose = posture(rd.present, inp["bus"], pol, st)
        # Fingerprint unreadable (robotd just restarted, just came up, calibration read failed and retrying): don't record, don't overwrite the old record that has a fingerprint —— otherwise once the calibration reads back
        # step 5 would become "standing not done since calibration changed" (code review C2). Standing time and walking accumulation still count, and it's recorded as soon as it's readable
        fp = inp["fp"]
        if pose in STAND and native.get("torque_state_confirmed") is True:
            if self._stand_since is None:
                self._stand_since = now
            elif now - self._stand_since >= STOOD_S and fp is not None:
                old = self.rec.get("stood") if isinstance(self.rec.get("stood"), dict) else None
                if old is None or old.get("fp") != fp:
                    self._put("stood", {"at": self.wall(), "fp": fp}, say="上手清单：记下「站起来过」", cat="手柄")
        else:
            self._stand_since = None
        if pose == "walking":
            if self._walk_last is not None:
                self._walk_acc += min(now - self._walk_last, 1.0)
            self._walk_last = now
            old = self.rec.get("walked") if isinstance(self.rec.get("walked"), dict) else None
            if self._walk_acc >= WALKED_S and fp is not None and (old is None or old.get("fp") != fp):
                self._walk_acc = 0.0
                self._put("walked", {"at": self.wall(), "fp": fp}, say="上手清单：记下「走过」", cat="手柄")
        else:
            self._walk_last = None
        # Servo page calibrated all 15 and the main program file is all 2048 too: record the joint fingerprint at this point; if it changes later it must be checked again (code review C9-3)
        stu = inp["studio_servo"] or {}
        js = _joints(inp["calib"])
        jfp = joints_fp(inp["calib"])
        if set(SERVO_IDS) <= set(stu.get("ids") or ()) and js and jfp and all(j.get("zero_raw") == 2048 for j in js):
            ss = self.rec.get("servo_studio") if isinstance(self.rec.get("servo_studio"), dict) else None
            if ss is None or ss.get("src") != stu.get("time"):
                self._put("servo_studio", {"at": self.wall(), "fp": jfp, "src": stu.get("time")},
                          say="上手清单：舵机页的标定记录跟主程序文件对上了（15 颗都是 2048）", cat="校准")
        pv = inp["pad"] or {}
        seen = dict(self.rec.get("pads_seen") or {}) if isinstance(self.rec.get("pads_seen"), dict) else {}
        changed = False
        for p in pv.get("pads") or []:
            if isinstance(p, dict) and p.get("paired") and p.get("mac") and seen.get(str(p["mac"]).upper()) != p.get("name"):
                seen[str(p["mac"]).upper()] = p.get("name") or p.get("mac")
                changed = True
        if changed:
            self._put("pads_seen", seen)

    def _board_tick(self, rd):
        """Board temperature: hysteresis (on at ≥ 80 °C, cleared only below 77 °C); when robotd doesn't report, use what Studio reads itself (io() reads it in a thread from
        /sys/class/thermal, only present on the duck)."""
        ha = rd.health.age()
        h = rd.health.value if ha is not None and ha <= MAX_AGE["health"] else None
        c = (h or {}).get("cpu_temp_c") if isinstance(h, dict) else None
        if not _num(c):
            c = (self.board or {}).get("c") if isinstance(self.board, dict) else None
        if not _num(c):
            self.cpu_hot = False
        elif c >= CPU_WARN_C:
            self.cpu_hot = True
        elif c < CPU_CLEAR_C:
            self.cpu_hot = False

    def view(self):
        return self._view
