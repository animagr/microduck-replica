"""The "make the duck move" part of the gamepad page: who is driving (the steering wheel), the web gamepad (buttons and sticks on the diagram), stand up / start walking / sit down, skills, sounds,
actions and combo actions.

PadOps (pad.py) inherits this class and shares the lock, robotd readback, and log. The rules here (safety first):
- **Steering wheel** (review 19, 25): the page that pushes the sticks, holds a trigger / X, or runs an action takes the wheel; other pages must click "接管" (Take over) to grab it. The holding page releases it automatically
  after 6 seconds without pushing the sticks or saying "still holding" (just having the gamepad page open doesn't count: watch and drive open don't renew the wheel, review 2 I1, round 3 V5). One-shot
  commands (stand, walk, sit, skill, quack) don't take the wheel; they can't be clicked while someone else is pushing the sticks (except "停下（站好）" (Stop (stand still)), which anyone can click without queuing).
- **Whether the page is in the gamepad area** (round 3 V5; overview reshuffle review O1: the gamepad was merged into the overview, "in" = route is / or /pad, page visible, and the gamepad block in
  the viewport): entering sends drive {open, seq}, leaving sends drive {on:false, seq}; seq is the page's increasing sequence number, the last one is recorded per connection, and older ones are dropped
  (the thread pool can reorder them). A leaving connection is recorded in closed: afterward, late sticks, buttons, and actions are all dropped; only another open unlocks it. **A new connection starts out in closed**
  (new_conn), and doesn't count as in until it has sent open. **A disconnected connection (gone) can never get it back**: open on a gone connection is rejected outright.
- **Sticks only move while held**: while held the page sends sticks (or the old move) at 10 Hz, and sends stop once on release; the server doesn't repeat sends on the page's behalf (if disconnected, robotd's
  deadman 500 ms takes over: duck-control safety.rs:226-237). Sequence numbers are stored per connection and not cleared when the wheel changes hands; frames older than this connection's last stop are all dropped
  (the barrier is shared by the three channels); "the latest frame" is per channel (move / head / body, round 3 V6). Checking and sending are done under the same lock.
- **Head and body are latched** (round 3 V1): robot.head and robot.pose never expire in robotd (fork robotd intents.rs:327-341),
  and pose's active:true makes the controller zero the velocity and force the standing network (fork control.rs:595-607) —— if the web page leaves one behind, neither the web page nor the physical gamepad
  can move the duck. So we record "head / body set by the web page" (_latch) and clear it on every path below (head all zeros, body {"active": false},
  **also when mirroring**: in body mode padd resends within at most 0.1 seconds, padd:1570, 1625-1631): switching back to walking, releasing and leaving the page, page disconnecting, being taken over,
  the wheel changing hands after 6 seconds, relax (four sources), physical gamepad connecting, clicking stop / Start stop, posture leaving "ready to walk", Studio shutting down.
  The relax entry points are in the event loop, so they only set a flag (_request_clear) and hand off to the background thread to send, ordered 0.1 seconds after the relax.
  **Pitfall**: PoseParams defaults to active:true (fork lib.rs:2320-2346), so sending robot.pose {} actually turns body mode on; exiting must always write active:false.
  The first time Studio sees the main program up it unconditionally sends robot.pose {"active": false} once (if Studio crashed and restarted, it doesn't know whether one was left behind last time).
- **Watchdog** (round 3 V11): if the last head / body frame is nonzero and no new frame comes for 0.6 seconds → head all zeros, body re-centered (still in body mode); if a mode hasn't reported "still here" for 3 seconds
  → exit the mode (send active:false). A held button not reported for 0.45 seconds (X: 0.3 seconds) is treated as released. All in the 25 Hz background thread (_tick_loop).
- **Held buttons** (round 3 V4): LT / RT / X go through the keys channel (the page reports press, release, and every 0.15 seconds while held), and the background sends at 25 Hz according to "what's held":
  mouth = LT or RT held × mouth_percent, LT continuously wheee (hold:true, release sends hold:false), RT quacks once on press, X held sends robot.do again every 40 ms
  (continuous rolling, padd:1182-1211). Doesn't reuse _run_action; mutually exclusive with head / mouth actions in progress.
- **Physical gamepad connected** (mirroring): padd sends zero velocity every 0.1 seconds even when nobody touches it (padd main.rs:962-977), and sends mouth every tick
  (padd main.rs:1351-1363) → web sticks, buttons, modes, and one-shot buttons on the diagram (src:"svg") are all ignored; drive on isn't accepted; if the web page isn't driving it doesn't send
  "stop" (doesn't interrupt the physical gamepad; clearing head / body is the exception, see above). The big buttons below (stand up / start walking / sit down / skill / quack) are one-shot
  requests that don't compete with padd and work as usual.
- **Within 2 seconds after relax**, stand, walk, sit, skill, sticks, and actions aren't accepted (enable torque, return to stance, and relax share one request slot, last write wins:
  robotd intents.rs:24-36, 149-157). Relax times come from three places: app's run_relax synchronously calls note_relax() (top button, space, Select on the diagram),
  robotd.py's relax counter changed, and readback seeing torque go from on to off (gamepad Select, robotctl, a fall, low battery: review 2 I2).
- **Whether it's sitting must be read from a fresh robot.policies.sitting** (review 2 S2): if unreadable, "坐下 / 站起来" (Sit down / Stand up) can't be clicked; no guessing
  (lib.rs:2362-2368: standing up is two different calls, and a wrong guess would make a sitting duck sit down on every second press). Same for Start, D-pad down, and buttons bound to sit_toggle.

API sources (official repo pollen-robotics/microduck; fork means the fork firmware):
| On the page      | Sent to robotd                                | Source |
|------------------|-----------------------------------------------|------|
| Stand up (when limp) | robot.init (request)                      | lib.rs:553-558; main.rs:4550-4563; fork main.rs:5898-5908 (rejected if the bus isn't ready) |
| Stand up (when sitting) | robot.do {"skill":"sit_toggle"}        | lib.rs:2362-2370 (sitting requires sit_toggle; init would fight the latch); main.rs:659-669 |
| Start walking    | robot.enable {"on":true,"toggle":false}       | lib.rs:2685-2704; main.rs:4518-4548; fork main.rs:5780-5850 (HOME/IMU/policy gates) |
| Stop (stand still) | robot.stop, then robot.enable {"on":false}  | lib.rs:537-540; main.rs:4513-4516 (stop only clears velocity) |
| Sit down         | robot.do {"skill":"sit_toggle"}               | main.rs:4223-4255 (rejected if the policy isn't running or HOME isn't reached); main.rs:4158-4168 |
| Skill            | robot.do {"skill":name}                       | lib.rs:2338-2346 (names from skills in robot.policies); main.rs:4136-4176 |
| Quack            | robot.sound {"tag":…} (request)               | lib.rs:590-600, 2094-2140; main.rs:4300-4319 |
| Sticks (walking) | robot.move notification {vx,vy,vyaw}          | lib.rs:2041-2051; main.rs:3589-3597, 3631-3636 |
| Sticks (head mode) | robot.head notification (conversion in sticks_to_intent) | fork padd:1427-1445 |
| Sticks (body mode) | robot.pose notification {z,roll,pitch,active} | fork padd:316-320, 1447-1460; fork lib.rs:2320-2346 |
| LT / RT / X held | robot.mouth / robot.sound / robot.do notification | fork padd:1182-1211, 1351-1396 |
| Nod, tilt head, open mouth | robot.head / robot.mouth notification | see the pad_combo.py file header |
| D-pad right (diagram) | robot.rebootMotors {"ids":[]} (request, empty = all) | official padd main.rs:530, 750-765; fork (handover version) main.rs:2731-2758 (relaxes the whole body first, then reboots, limp afterward), 6050-6056 (never rejects) |
| D-pad up held 3 s | robot.setMode {"mode":"roller" / "walk"} (request) | official padd main.rs:247-252, 766-806; fork (handover version) main.rs:5700-5736 (rejected if no roller model installed; same for the autodetect version), 2870-2930 |

D-pad right and D-pad up follow the official behavior (user decided on 10-19: keep the official scheme): D-pad right sends on a single press, no confirmation, ignores the wheel, and doesn't take the "previous one hasn't replied yet" slot
(it's an emergency path like relax); once the main program accepts it, a relax is recorded (note_relax: no torque enable for 2 seconds, stop actions, clear head / body). D-pad up must be held 3 seconds on the page
before sending (timed on the page), carrying expect (which mode to switch to); the backend judges again by robot.policies' mode and rejects if different.

The web gamepad's Start (round 3 V7, V8): the page computes what Start will do via motion.start and sends start {expect}; if what the backend picks differs from expect it rejects
("状态刚变了，再按一次" (state just changed, press again)). Differences between the physical gamepad's Start and the web one (fork padd:1113-1148, fork robotd:5795-5873): when sitting, the physical one does
robot.init straight back to HOME, the web one uses sit_toggle (sitstand network getting up, gentler); while walking the physical one toggles off (gradual return to HOME), the web one does
stop + enable off (gives the HOME target directly).
"""
import itertools
from contextlib import nullcontext
import json
import math
import os
import re
import threading

from . import pad_combo as C
from .estop import STARTING_PHASES, relaxed, torque_off
from .log import log_cmd
from .pad_combo import Refused
from .rpc import RpcError, Timeout, Unreachable
from .updates import neutral_robot_command

MAX_V = 0.3               # full stick m/s: padd default --max-linear 0.3 (padd main.rs:158-164), same number as the official web remote
MAX_W = 1.5               # full stick rad/s: padd default --max-angular 1.5 (padd main.rs:166-168)
V_CEIL, W_CEIL = 0.6, 3.0   # never exceed these no matter how large the config value (so a misread can't send it flying)
HEAD_RAD = 2.5            # head full stick rad: padd default --max-head 2.5 (fork padd:201-205, "the network itself decides how far")
HEAD_CEIL = 2.5           # however large the config value, use this
HEAD_CHOICES = (0.5, 1.0, 2.5)   # head_rad in the --input-settings file only accepts these three (fork padd/src/input_settings.rs:16-21)
BODY_Z_UP, BODY_Z_DOWN, BODY_ANGLE = 0.010, 0.025, 0.2618   # body mode full stick (fork padd:316-320)
BODY_TRAIN_ANGLE = 0.26   # training range roll / pitch ±0.26 rad, z −0.025..+0.010 m (fork lib.rs:2320-2325): clamp to this before sending
DEADZONE = 0.1            # stick deadzone, computed per axis, without rescaling (fork padd:184-187, 1342-1349)
LEASE_S = 6.0             # if the page holding the wheel hasn't pushed the sticks or said "still holding" for this long: release
RELAX_GUARD_S = 2.0
HOLD_S = 0.45             # while an action is held the page says "still holding" every 0.15 seconds; stop if not said for this long
KEYS_HOLD_S = 0.45        # held buttons (LT / RT): the page reports every 0.15 seconds; not reported for this long counts as released (round 3 V4)
X_HOLD_S = 0.3            # X alone is a bit shorter: the continuous-roll window is 0.15 seconds (fork control.rs:42-47), so a page dropout rolls at most one extra time
STICK_STALE_S = 0.6       # last head / body frame nonzero and no new frame for this long: re-center (round 3 V11)
MODE_HB_S = 3.0           # head / body mode hasn't reported "still here" for this long: exit the mode (round 3 V11)
TICK_S = 0.04             # background 25 Hz: held buttons, watchdog, cleanup
RELAX_CLEAR_DELAY_S = 0.1   # head / body cleanup caused by relax is ordered after the relax request (round 3 V1 item 5)
MOVE_MIN_GAP_S = 0.04     # at least this long between two frames on the same channel; frames arriving too densely aren't dropped, the latest is sent after a short wait (review 21)
WALK_STOP_WAIT_S = 1.0
WALK_VERIFY_S = 3.0       # after the "start walking" ack, read back for this long; it only counts as really started when policy_enabled is seen
WALK_VERIFY_POLL_S = 0.1
CMD_TIMEOUT_S = 3.0
BINDINGS_STALE_S = 10.0   # when pad.bindings is this old, fetch once before pressing a button on the diagram (round 3 V14; padd rereads its config every second, padd:806-817)
LOW_BATTERY = 10          # no longer used: low battery doesn't block "stand up" (user on 10-18: battery only warns, see studio/battery.py)
PADD_UNIT = "/etc/systemd/system/padd.service"        # the unit is installed here: official scripts/board-test.sh:800-806
PADD_DROPIN_DIR = "/etc/systemd/system/padd.service.d"
PADD_INPUT_ACK = "/run/padd/input-settings.json"      # the ack padd writes after applying the amplitude settings (fork padd/src/input_settings.rs:63-74)
# Uses its own small thread pool (4 threads: round 3 V13), not crowded with slow calls like pairing, Bluetooth, and one-off requests
FAST_OPS = ("move", "stop", "sticks", "keys", "mode", "action_hold", "action_stop", "drive", "watch")
FAST_WORKERS = 4
GONE_KEEP = 500           # how many disconnected / closed connections to remember
INF = float("inf")

POSTURE_CN = {"absent": "主程序没在跑", "starting": "主程序在启动", "commissioning": "调试模式", "sitting": "坐着",
              "limp": "软着", "walking": "在走", "policy": "站着（准备好走了）", "holding": "站着（保持）",
              "homing": "在站起来", "unknown": "姿势读不出来", "servo_session": "在调舵机"}
DRIVING = ("policy", "walking")
MODES = ("drive", "head", "body")
MODE_CN = {"drive": "走路", "head": "头模式", "body": "身体模式"}
DRIVE_MODE_CN = {"walk": "走路", "roller": "轮滑"}     # robot.setMode / robot.policies mode (switched by holding D-pad up for 3 seconds)
HELD_KEYS = ("lt", "rt", "x")
KEY_CN = {"a": "A", "x": "X", "lb": "LB", "rb": "RB", "dpad_down": "十字下", "lt": "LT", "rt": "RT"}
BIND_KEYS = ("a", "x", "lb", "rb", "dpad_down")
# Official default bindings (fork robotd-params lib.rs:175-215); used when pad.bindings can't be read
DEFAULT_BIND = {"a": "ground_pick", "x": "roulade", "lb": "kick_left", "rb": "kick_right", "dpad_down": "sit_toggle"}
HEAD_ZERO = {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}
POSE_OFF = {"active": False}                                   # always write active:false (the default is true)
POSE_CENTER = {"z": 0.0, "roll": 0.0, "pitch": 0.0, "active": True}
_FLAG = re.compile(r"--(max-linear-backward|max-linear|max-angular)(?:=|\s+)(\S+)")
_FLAG_HEAD = re.compile(r"--max-head(?:=|\s+)(\S+)")
_FLAG_PATH = re.compile(r"--(input-settings|config)(?:=|\s+)(\S+)")
NO_SIT_INFO = "读不到它是不是坐着（robot.policies 读不到或者太旧）：等几秒再点。猜错了会让坐着的鸭子站起来"
MIRROR_SVG = "实体手柄连着：图上只跟着它显示，网页上按的不收（跟实体手柄抢会被它每 0.1 秒发的指令盖掉）"
MODE_IDLE = "策略没在跑：摇杆不会让头 / 身体动（Y / B 照样能切；点「开始走」以后才管用）"


def plain_refusal(reason):
    """robotd's original rejection text → plain language (the fork's Chinese reasons are passed through as is)."""
    r = str(reason or "")
    low = r.lower()
    if "policy is not driving" in low:
        return "策略没在跑：先点「开始走」（或者按手柄 Start 两次）"
    if "home pose" in low and "still" in low:
        return "它还在回站姿，等一秒再点"
    if "no skill named" in low:
        return f"这只鸭子没有这个技能（原文：{r}）"
    if "no skills configured" in low:
        return "这只鸭子没配技能"
    if "no voice" in low:
        return "这只鸭子没有声音：音频关了，或者声音包是空的（在鸭子上运行 sounds ensure-bank）"
    if "read-only" in low:
        return "主程序现在是只读的（调试模式），动作都不接受"
    if "roller onnx models are not installed" in low:
        return "这只鸭子没装轮滑模型：切不了，还是走路"
    if "nothing to switch between" in low:
        return "这只鸭子没装走路的策略：没有可切的"
    if "requires stationary home" in low:
        return "要站好不动（回到站姿、没在做技能）才能切"
    return f"主程序没接受：{r}" if r else "主程序没接受（没说原因）"


def _exec_line(texts):
    """The last effective ExecStart across padd's unit file and drop-ins [(path, text)] (an empty ExecStart= means "clear the previous ones")."""
    exec_line, exec_src = None, None
    for path, text in texts:
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if line.startswith("ExecStart="):
                val = line[len("ExecStart="):].strip()
                exec_line, exec_src = (val or None), (path if val else None)
    return exec_line, exec_src


def parse_speed_limits(texts):
    """Text of padd's unit file and drop-ins [(path, text)] → {"v", "w", "src"}. Malformed numbers (like 1.2.3) are skipped, not raised (review 2 I3)."""
    exec_line, exec_src = _exec_line(texts)
    found, bad = {}, []
    for k, v in _FLAG.findall(exec_line or ""):
        try:
            x = float(v)
        except ValueError:
            bad.append(f"--{k} {v}")
            continue
        if math.isfinite(x) and x > 0:
            found[k] = x
        else:
            bad.append(f"--{k} {v}")
    v = min([found[k] for k in ("max-linear", "max-linear-backward") if k in found] or [MAX_V])
    w = found.get("max-angular", MAX_W)
    if found:
        src = f"padd 的配置（{exec_src}）"
    elif texts:
        src = "官方默认（padd.service 里没改）"
    else:
        src = "官方默认（读不到 padd 的配置）"
    if bad:
        src += f"；看不懂的参数没用：{'、'.join(bad)}"
    capped = v > V_CEIL or w > W_CEIL
    return {"v": min(v, V_CEIL), "w": min(w, W_CEIL), "src": src + ("，超过上限的按上限算" if capped else "")}


def parse_padd_inputs(texts):
    """--max-head, --input-settings, --config in ExecStart (round 3 V9, V18). The fork's drop-in looks like this
    (fork packaging/gamepad.py:94): startup_gate.py … --exec …/padd --socket … --config /etc/robot/feetech-ft5/robotd.toml
    --max-head 2.5 --input-settings /etc/robot/feetech-ft5/pad-settings.json. Malformed numbers are skipped, not raised."""
    exec_line, exec_src = _exec_line(texts)
    out = {"max_head": None, "input_settings": None, "config": None, "bad": [], "src": exec_src}
    for v in _FLAG_HEAD.findall(exec_line or ""):
        try:
            x = float(v)
        except ValueError:
            out["bad"].append(f"--max-head {v}")
            continue
        if math.isfinite(x) and x > 0:
            out["max_head"] = x
        else:
            out["bad"].append(f"--max-head {v}")
    for k, v in _FLAG_PATH.findall(exec_line or ""):
        out["input_settings" if k == "input-settings" else "config"] = v
    return out


def _padd_settings(d):
    """Whether padd accepts these amplitude settings (fork padd/src/input_settings.rs:7-21): only the two fields mouth_percent and head_rad are allowed
    (deny_unknown_fields: one extra field rejects the whole thing, review R10), mouth 0–100, head only 0.5 / 1.0 / 2.5. Accepted → (head, mouth), rejected → None."""
    if not isinstance(d, dict) or set(d) != {"mouth_percent", "head_rad"}:
        return None
    m, h = d["mouth_percent"], d["head_rad"]
    if not (isinstance(m, (int, float)) and not isinstance(m, bool) and math.isfinite(m) and 0 <= m <= 100):
        return None
    if not (isinstance(h, (int, float)) and not isinstance(h, bool) and float(h) in HEAD_CHOICES):
        return None
    return float(h), float(m)


def input_limits(inputs, settings_text=None, settings_error=None, ack=None):
    """Compute head and mouth amplitude the same way padd does (fork padd/src/input_settings.rs:9-27, 36-46, 63-80): first mouth 100%, head --max-head (2.5 if unset);
    if padd accepts the --input-settings file (_padd_settings), both come from the file, otherwise keep the previous values.
    ack: the settings in the ack padd wrote itself (_read_inputs checked that the padd that wrote the ack is still alive and the file matches) —— those are the numbers padd is actually using, so they win.
    → {"head", "mouth" (percent), "src"}."""
    head = inputs.get("max_head") or HEAD_RAD
    src = f"--max-head {head:g}" if inputs.get("max_head") else "官方默认（头 2.5 rad、嘴 100%）"
    mouth = 100.0
    path = inputs.get("input_settings")
    got = _padd_settings(ack) if path and ack is not None else None
    if got is not None:
        head, mouth = got
        src = f"padd 正在用的（它的回执 {PADD_INPUT_ACK}）"
    elif path:
        if settings_error is not None:
            src += f"；{path} 读不出来（{settings_error}），按前面的"
        else:
            try:
                got = _padd_settings(json.loads(settings_text or ""))
            except ValueError:
                got = None
            if got is not None:
                head, mouth = got
                src = f"padd 的幅度设置（{path}）"
            else:
                src += f"；{path} 里的 padd 不认（只能有 mouth_percent、head_rad 两项，头只认 0.5 / 1.0 / 2.5，嘴 0–100），按前面的"
    if inputs.get("bad"):
        src += f"；看不懂的参数没用：{'、'.join(inputs['bad'])}"
    if head > HEAD_CEIL:
        head, src = HEAD_CEIL, src + f"，头超过 {HEAD_CEIL:g} rad 的按 {HEAD_CEIL:g} 算"
    return {"head": head, "mouth": mouth, "src": src}


def _dz(v):
    return 0.0 if abs(v) < DEADZONE else v


def sticks_to_intent(mode, lx, ly, rx, ry, lim, head_rad):
    """Web sticks (-1..1, x right and y down positive, same as TouchStick) → the frame sent to robotd (review 3 addendum 2, exactly as fork padd,
    signs copied too: padd:1437-1439 "the prototype's alpha mapping, signs included … verified on hardware there").
    padd's coordinates have y up positive: LX = dz(lx), LY = −dz(ly), RX = dz(rx), RY = −dz(ry). Returns (method, params)."""
    LX, LY, RX, RY = _dz(lx), -_dz(ly), _dz(rx), -_dz(ry)
    r = lambda x: round(x, 4) + 0.0    # noqa: E731 —— +0.0 removes -0.0
    if mode == "head":                  # padd:1427-1445
        return "robot.head", {"neck_pitch": r(RY * head_rad), "head_pitch": r(-LY * head_rad),
                              "head_yaw": r(-LX * head_rad), "head_roll": r(RX * head_rad)}
    if mode == "body":                  # padd:1447-1460, then clamp to the training range (fork lib.rs:2320-2325)
        z = LY * (BODY_Z_UP if LY >= 0 else BODY_Z_DOWN)
        clampa = lambda a: max(-BODY_TRAIN_ANGLE, min(BODY_TRAIN_ANGLE, a))   # noqa: E731
        return "robot.pose", {"z": r(max(-BODY_Z_DOWN, min(BODY_Z_UP, z))), "roll": r(clampa(RX * BODY_ANGLE)),
                              "pitch": r(clampa(RY * BODY_ANGLE)), "active": True}
    v, w = lim["v"], lim["w"]           # padd:1415-1426: vx = LY×0.3, vy = −LX×0.3, vyaw = −RX×1.5; the right stick's Y isn't used
    return "robot.move", {"vx": r(LY * v), "vy": r(-LX * v), "vyaw": r(-RX * w)}


class _Abort(Exception):
    pass


class DriveMixin:
    # ================= Initialization =================

    def _drive_init(self, state_dir):
        self.state_dir = state_dir
        self._send_lk = threading.Lock()      # "check + send" to robotd happens under this lock: the order is the order things land (take this first, then _lk)
        self._seqs = {}                       # connection → {"hi", "stop", "life", "mode", "latest":{channel}, "sent":{channel}}: not cleared when the wheel changes hands
        self._gone = {}                       # disconnected connections (mark_gone) → True; can never get the wheel back
        self._closed = {}                     # connections that left the gamepad page (drive off) → True; only drive open / on unlocks them
        self._halt_after_gone = {}
        self._conn_ids = itertools.count(1)
        self._last_sent_at = {}               # channel → last send time (at least 40 ms apart on the same channel)
        self._web_driving = False
        self.virtual = {"owner": None, "last": [0.0, 0.0, 0.0], "at": None}
        self._driver = None                   # {"conn", "by", "since", "seen"}
        self._cmd_busy = False
        self._last_cmd = None                 # result of the latest stand / walk / sit / skill / sound (pushed to all pages)
        self._relax_presses = None
        self._relax_noted = 0                 # how many times note_relax was called (for the e-stop test: pressing the top relax during the test invalidates it)
        self._relax_at = -1e9
        self._torque_was = None
        self._action = None                   # the action / combo action in progress
        self._last_action = None
        self._pad_said = False                # "physical gamepad connected, web page yields" is only logged once
        self._limits = parse_speed_limits([])
        self._inputs = input_limits({})       # head / mouth amplitude (round 3 V9)
        self._imu_head, self._imu_head_why = None, None   # [pad_imu_head_control] enabled (round 3 V18)
        self.list_dir = os.listdir
        self._user_combos = C.load_user_combos(state_dir, self.log)
        # ---- Round 3: web gamepad ----
        self._latch = {"head": None, "body": None}   # head / body set by the web page: {"conn", "nonzero", "at"}; None = never set or cleared
        self._modes = {}                      # connection → {"mode": "head" / "body", "hb"}; absent = walking
        self._mode_exit = {}                  # connection → {"why", "at"}: the backend exited the mode on its behalf (pushed to that page)
        self._clears = []                     # pending cleanups [{"conn", "why", "due", "tries"}] (_request_clear only changes this)
        self._keys = {}                       # connection → held buttons (see _keys_op)
        # connection → {"skill", "x_down"}: this X press's (press time x_down) request was accepted and X is still held; continuous rolling only while held (review R5)
        self._x_armed = {}
        self._was_driving = False
        self._pose_reset = "pending"          # the first time Studio sees the main program up: send robot.pose {"active": false} once
        self._pose_reset_tries = 0
        self._bindings_due = 0.0
        self._tick_evt = threading.Event()
        self._tick_stop = threading.Event()
        self._tick_said = set()               # the background thread logs each kind of send failure only once
        self._tick_thread = None

    def _drive_start(self):
        """Called at the end of PadOps.__init__: start the 25 Hz background thread (sleeps when idle, wakes when there's work). Keep the handle: on close we must wait for it to stop (review R8)."""
        self._tick_thread = threading.Thread(target=self._tick_loop, name="pad-tick", daemon=True)
        self._tick_thread.start()

    def new_conn(self):
        """Name a page connection (globally increasing, not id(ws): Python reuses the ids of collected objects, review 2 I4).
        **New connections default to "not in the gamepad area"** (overview reshuffle review O1): after the gamepad was merged into the overview, the page only sends
        drive {open} when the gamepad block is really on screen; for connections that haven't sent open, sticks, held buttons, head / body, and modes are all dropped (one-shot commands still ignore this: round 3 V5)."""
        conn = f"ws{next(self._conn_ids)}"
        with self._lk:
            self._remember(self._closed, conn)
        return conn

    def executor_for(self, args):
        """For app: fast ones like move / sticks / keys use a separate small thread pool (review 2, minor 4; round 3 V13); None = default thread pool."""
        fast_motion = (args or {}).get("op") == "motion" and (args or {}).get("action") in ("heartbeat", "stop", "pause", "record_pause", "idle_stop")
        return self._fast_pool if (args or {}).get("op") in FAST_OPS or fast_motion else None

    # ================= Who is driving =================

    def _pad_attached(self, now):
        """Is a physical gamepad connected: (True / False / None, explanation). None = can't tell (review 2, minor 3).
        The tap seeing attached is the most direct; otherwise look at configd's pad.status within 15 seconds (connected + padd running)."""
        if self.tap is not None and self._tap_on and self.tap_state == "attached":
            alive = getattr(self.tap, "alive", None)
            if alive is None or alive():
                return True, "padd 旁路看到实体手柄"
        st = self._status if isinstance(self._status, dict) else None
        fresh = st is not None and self._status_at is not None and now - self._status_at < 15
        if fresh:
            if any(isinstance(p, dict) and p.get("connected") for p in st.get("pads") or []) and st.get("driver") == "active":
                return True, "configd 说手柄连着、padd 在跑"
            return False, None
        if self._worker_error:
            return None, f"看手柄的后台线程出错了（{self._worker_error}），刷新手柄页会重来"
        if self.tap is not None and self._tap_on and self.tap_state in ("denied", "error"):
            return None, f"configd 读不到，按键也读不到（{self.tap_why or self.tap_state}）"
        return False, None

    def _owner(self, now):
        if self._pad_attached(now)[0]:
            return "pad"
        if self.virtual["at"] is not None and now - self.virtual["at"] < 0.6 and self._web_driving:
            return "web"
        return None

    def _lease_holder(self, now):
        d = self._driver
        return d if d is not None and now - d["seen"] < LEASE_S else None

    def _seq_of(self, conn):
        q = self._seqs.get(conn)
        if q is None:
            # keys: the last sequence number of held buttons. Kept here, not in _keys[conn]: that entry is deleted after release,
            # and after deletion a "press" older than the "release" arriving late would press it again (review R4)
            q = self._seqs[conn] = {"hi": -1, "stop": -1, "life": -1, "mode": -1, "keys": -1, "latest": {}, "sent": {}}
            if len(self._seqs) > GONE_KEEP * 2:
                for k in list(self._seqs)[:GONE_KEEP]:
                    if k != conn and (self._driver or {}).get("conn") != k:
                        self._seqs.pop(k, None)
        return q

    def _remember(self, table, conn):
        table[conn] = True
        while len(table) > GONE_KEEP:
            table.pop(next(iter(table)))

    def _take_lease(self, conn, by, now, force=False, reopen=False):
        """Take the wheel (called within _lk). Disconnected connections never get it; ones that left the gamepad page (closed) only get it via drive on (reopen) ——
        the old loophole "pressing an action also unlocks" was removed (round 3 V5: pressing an action and immediately switching pages, off arrives first and action_start later, and the action still started);
        if someone else holds it and it's fresh: refused, unless force (the page clicked "Take over"). When the wheel changes hands automatically after 6 seconds of inactivity, the head / body set by the previous page,
        its held buttons, and modes are all cleared (round 3 V1 item 4), handed off to the background thread to send."""
        if conn in self._gone:
            raise Refused("这个页面已经断开了")
        if conn in self._closed and not reopen:
            raise Refused("这个页面不在手柄这一块（滚走了、切到别的页，或者还没滚到）：滚到手柄那里再按")
        d = self._driver
        if d is not None and d["conn"] == conn:
            d["seen"] = now
            if by:
                d["by"] = by
            if reopen:
                self._closed.pop(conn, None)
            return None
        held = self._lease_holder(now)
        if held is not None and not force:
            raise Refused(f"{held['by'] or '另一个页面'}正在遥控（{now - held['since']:.0f} 秒了）。要接管就点「接管」")
        if reopen:
            self._closed.pop(conn, None)
        self._driver = {"conn": conn, "by": by, "since": now, "seen": now}
        if d is not None and d["conn"] != conn and held is None:
            self.log.info(f"网页遥控换人：{by or '页面'}（原来的 {d['by'] or '页面'} {now - d['seen']:.0f} 秒没动静，已自动松开）",
                          cat="安全", dedup=False)
            self._request_clear(d["conn"], "方向盘 6 秒没动静，换了人")
        return held or d

    def _touch_lease(self, conn, now):
        d = self._driver
        if d is not None and d["conn"] == conn:
            d["seen"] = now

    def _drive(self, args, conn, by):
        """The page enters the gamepad page (open), leaves (on:false), clicks "Take over" (on:true, force). open / off carry the page's increasing sequence number,
        the last one is recorded per connection, and older ones are dropped (round 3 V5: in the fast thread pool, an off immediately followed by open may arrive reversed)."""
        now = self.clock()
        seq = self._seq(args)
        if args.get("open"):
            with self._lk:
                if conn in self._gone:
                    raise Refused("这个页面已经断开了")
                q = self._seq_of(conn)
                if seq is not None and seq <= q["life"]:
                    return {"dropped": "旧的（这个页面后来又离开 / 回来过）"}
                if seq is not None:
                    q["life"] = seq
                self._closed.pop(conn, None)            # only unlock closed: don't take the wheel or stop (merely having the page open doesn't block others)
            return {"open": True}
        if args.get("on"):
            with self._lk:
                attached, _ = self._pad_attached(now)
                if attached:
                    raise Refused("实体手柄连着：网页摇杆只跟着它动、只显示，打不开（打开了也会被它每 0.1 秒发的「停」盖掉）")
                q = self._seq_of(conn)
                if seq is not None and seq <= q["life"]:
                    return {"dropped": "旧的（这个页面后来又离开过手柄页）"}
                if seq is not None:
                    q["life"] = seq
                prev = self._take_lease(conn, by, now, force=bool(args.get("force")), reopen=True)
            if prev is not None and prev.get("conn") != conn:
                self.log.warn(f"{by or '一个页面'}接管了遥控（原来是 {prev.get('by') or '另一个页面'}）", cat="安全",
                              hint="原来那个页面的摇杆、按键、动作马上就不管用了", dedup=False)
                self._halt(f"被 {by or '另一个页面'} 接管了", prev.get("conn"))
            return {"driver": by}
        with self._lk:
            q = self._seq_of(conn)
            if seq is not None and seq <= q["life"]:
                return {"dropped": "旧的（这个页面后来又回到了手柄页）"}
            if seq is not None:
                q["life"] = seq
            if conn not in self._gone:
                self._remember(self._closed, conn)
            top = max(q["hi"], seq if seq is not None else -1)
            q["stop"] = max(q["stop"], top)                  # stick frames sent before leaving are all void
            q["hi"] = max(q["hi"], top)
            mine = self._driver is not None and self._driver["conn"] == conn
            background_music = self.motion_studio.background_music(conn)
            if mine and not background_music:
                self._driver = None
        if background_music:
            # The drive area closes and late manual frames stay fenced, while
            # standalone music remains owned by this still-connected socket.
            pass
        elif mine:
            self._halt("离开了手柄区", conn)            # queues cleanup and sends inside
        else:
            self._request_clear(conn, "离开了手柄区")
            self._flush_clears(force=True)
        # The page says why it left (switched to another page / scrolled out of the gamepad block / went to background: overview reshuffle review O1). The same sentence is logged only once per minute (log dedup),
        # so scrolling back and forth won't spam; the reason comes from the page, truncated and used only for logging
        why = str(args.get("why") or "")[:40]
        self.log.info(f"{by or '页面'}离开了手柄区：{why or '没说原因'}", cat="手柄")
        return {}

    def mark_gone(self, conn):
        """The page's WebSocket disconnected: app calls this **synchronously** in the event loop (only takes the lock, no network). Afterward, late commands from this connection are all dropped,
        and it can't get the wheel back; its action in progress is stopped immediately, and the head / body it set are handed to the background thread to clear. The actual "stop" is sent in drop_client (in the thread pool)."""
        if conn is None:
            return False
        with self._lk:
            if conn in self._gone:
                return False
            self._remember(self._gone, conn)
            self.motion_studio.invalidate("页面断开了", conn)
            self._closed.pop(conn, None)
            self._seq_of(conn)["stop"] = INF
            mine = self._driver is not None and self._driver["conn"] == conn
            if mine:
                self._driver = None
            a = self._action
            act = a is not None and a["conn"] == conn
            if act:
                a["why"] = a["why"] or "页面断了"
                a["stop"].set()
            self._request_clear(conn, "页面断了")
            self._mode_exit.pop(conn, None)         # the page is gone: no need to tell it anymore (review R9)
            need = (mine and self._web_driving) or act
            self._halt_after_gone[conn] = need
        return need

    def drop_client(self, conn, by=None):
        """The page disconnected (app calls this in the thread pool, after mark_gone): if it was driving, send "stop" once; clear the head / body it set. Works even if mark_gone wasn't called first."""
        with self._lk:
            need = self._halt_after_gone.pop(conn, None)
        if need is None:
            self.mark_gone(conn)
            with self._lk:
                need = self._halt_after_gone.pop(conn, False)
        if need:
            self.log.info(f"页面断了（{by or conn}）：网页遥控松开、发一次「停」", cat="安全", dedup=False)
            self._halt("页面断了", conn)
        else:
            self._flush_clears(force=True)

    def _halt(self, why, conn=None, clear_all=False):
        """Stop the web side: interrupt conn's action, release held buttons, clear head / body, exit the mode, void frames up to its sequence number, and send a 0 once.
        clear_all: clear head / body, held buttons, and modes no matter which page set them (clicking "停下（站好）" (Stop (stand still)): round 3 V1 item 7).
        When mirroring (physical gamepad connected) and the web page isn't driving, don't send move 0, so as not to interrupt the physical gamepad (review 2, minor 2); head / body cleanup is sent even when mirroring (round 3 V1).
        It's fine if sending fails: robotd stops by itself after 0.5 seconds without input."""
        self.motion_studio.invalidate(why, None if clear_all else conn)
        self.motion_studio.tick()
        self._action_stop(conn, why)
        self._request_clear(None if clear_all else conn, why)
        if self.robot is None:
            return
        with self._send_lk:
            with self._lk:
                now = self.clock()
                if conn is not None:
                    q = self._seq_of(conn)
                    q["stop"] = max(q["stop"], q["hi"])     # no +1: the page's very next frame goes through as usual (review 2, minor 1)
                was = self._web_driving
                self._web_driving = False
                attached, _ = self._pad_attached(now)
                send = was or not attached
                if send:
                    self.virtual.update(last=[0.0, 0.0, 0.0], at=now)
            if send:
                try:
                    self._notify_output("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
                except (Unreachable, Timeout) as e:
                    self.log.warn("「停」没发出去", cat="安全", step="robot.move", raw=str(e),
                                  hint="鸭子 0.5 秒收不到指令也会自己停（robotd 的 deadman）")
        self._flush_clears(force=True)
        if was:
            self.log.info(f"网页遥控松开了（{why}）", cat="手柄")

    # ================= Head / body cleanup (round 3 V1), modes =================

    def _mode_of(self, conn):
        m = self._modes.get(conn)
        return m["mode"] if m else "drive"

    def _request_clear(self, conn, why, delay=0.0, say=True):
        """Clear the head / body set by conn (conn=None: clear whoever set them), and also exit its head / body mode and release its held buttons.
        **Only changes memory, no network, never raises**: can be called from the event loop too (note_relax, feed_robot, mark_gone). The actual sending is in _flush_clears.
        A cleanup is **always queued**, regardless of whether _latch currently has a record (review R1): the first head / body frame may be in flight (passed the check, _latch not written yet).
        That frame holds _send_lk from the second check until writing _latch, and _flush_clears only looks at _latch inside _send_lk, so it's always ordered after it
        and sees what it wrote; entries with really no record are simply dropped at flush. say=False: the caller logs the exit-mode line itself (one line per event)."""
        try:
            with self._lk:
                now = self.clock()
                self._clears.append({"conn": conn, "why": why, "due": now + delay, "tries": 0})
                for c in [c for c, x in self._mode_exit.items() if now - x["at"] > 10]:
                    self._mode_exit.pop(c, None)          # only shown to the page for 10 seconds: delete expired ones so it doesn't keep growing (review R9)
                for c in list(self._modes):
                    if conn is None or c == conn:
                        m = self._modes.pop(c)
                        self._mode_exit[c] = {"why": why, "at": now}
                        if say:
                            self.log.info(f"退出{MODE_CN[m['mode']]}（{why}）", cat="手柄", dedup=False)
                for c, st in self._keys.items():
                    if conn is None or c == conn:
                        st["end"] = st.get("end") or why
                if conn is None:
                    self._x_armed.clear()
                else:
                    self._x_armed.pop(conn, None)
            self._tick_evt.set()
        except Exception:  # noqa: BLE001 —— the relax / disconnect path must not fail because of this
            pass

    def _flush_clears(self, force=False):
        """Send due cleanups (called in a thread: background thread, _halt, drive off, drop_client). Head sends all zeros, body sends {"active": false};
        only those the web page really set (recorded in _latch). Deciding and sending are both inside _send_lk: they won't interleave with stick frames' "check + send"."""
        if self.robot is None:
            with self._lk:
                self._clears.clear()
            return
        with self._send_lk:
            with self._lk:
                now = self.clock()
                due = [c for c in self._clears if force or c["due"] <= now]
                if not due:
                    return
                ids = {id(c) for c in due}
                self._clears = [c for c in self._clears if id(c) not in ids]
                sends = []
                for kind, method, params in (("head", "robot.head", HEAD_ZERO), ("body", "robot.pose", POSE_OFF)):
                    lat = self._latch[kind]
                    if lat is None:
                        continue
                    hit = next((c for c in due if c["conn"] is None or c["conn"] == lat["conn"]), None)
                    if hit is not None:
                        self._latch[kind] = None
                        sends.append((kind, method, params, hit, lat))
            for kind, method, params, req, lat in sends:
                try:
                    self._notify_output(method, dict(params))
                    self.log.info(("头回正" if kind == "head" else "身体回到标称、退出身体模式") + f"（{req['why']}）",
                                  cat="手柄", raw=f"{method} {json.dumps(params)}", dedup=False)
                except (Unreachable, Timeout) as e:
                    with self._lk:
                        if self._latch[kind] is None:
                            self._latch[kind] = lat                 # still counts as set by the web page: retry in 1 second, at most 3 times
                        if req["tries"] < 2:
                            self._clears.append(dict(req, due=self.clock() + 1.0, tries=req["tries"] + 1))
                    self.log.warn("头 / 身体没能回正", cat="安全", step=method, raw=str(e),
                                  hint=("1 秒后再试" if req["tries"] < 2 else "试了 3 次都没发出去：") +
                                  "身体模式留着的话鸭子推不走，按一下手柄 B 两次、或者卸力再站起来")

    def _mode_op(self, args, conn, by):
        """The page pressed Y / B on the diagram (switch to head mode / body mode / back to walking), or reports "still here" every second while in head / body mode (round 3 V6, V11).
        Entering a mode sends nothing (same as padd); if the web page is walking, send a stop first. Leaving a mode clears the head / body this page set.
        Switching works even when the policy isn't running (padd allows it too); stick frames just get dropped (round 3 V12)."""
        mode = args.get("mode")
        if mode not in MODES:
            raise Refused(f"不认识的模式：{mode}")
        seq = self._seq(args)
        now = self.clock()
        stop_first = False
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "动作会话已经改变，旧模式请求已丢弃", "mode": self._mode_of(conn)}
            if conn in self._gone:
                raise Refused("这个页面已经断开了")
            cur = self._mode_of(conn)
            if mode != "drive":
                if conn in self._closed:
                    return {"dropped": "这个页面不在手柄区", "mode": cur}
                if self._pad_attached(now)[0]:
                    raise Refused(MIRROR_SVG)
            if args.get("hb"):
                # The heartbeat (once per second while the page is in head / body mode) only renews "still here" and **doesn't enter the mode**: the backend has already exited it for the page (relax, policy stopped,
                # no heartbeat for 3 seconds, taken over, physical gamepad connected), the heartbeat can't bring it back, and the backend is the source of truth for the mode (review R3, round 3 V6).
                # The heartbeat doesn't touch the mode's sequence number: it doesn't change the mode, and a late old heartbeat just gets rejected
                if mode == cur:
                    if mode != "drive":
                        self._modes[conn]["hb"] = now
                    return {"mode": cur}
                why = (self._mode_exit.get(conn) or {}).get("why")
                return {"mode": cur, "dropped": f"后端已经退出了{MODE_CN.get(mode, mode)}" + (f"（{why}）" if why else "")}
            q = self._seq_of(conn)
            if seq is not None:
                if seq <= q["mode"]:
                    return {"dropped": "旧的", "mode": cur}
                q["mode"] = seq
            ex = self._mode_exit.get(conn)
            if mode == "drive":
                self._mode_exit.pop(conn, None)         # page back to walking = it knows the backend exited (the front end sends this when following the backend back to walking)
            elif cur == "drive" and ex is not None:
                # The backend just exited the mode for this page and the page hasn't gone back to "walking" yet: an "enter head / body mode" arriving now most likely means the page hasn't seen the exit yet
                # (heartbeat, snapshot not caught up), and it can't bring it back (review R3, round 3 V6). Once the page follows back to walking, pressing again will enter
                return {"dropped": f"后端已经退出了{MODE_CN[mode]}（{ex['why']}）：先回到走路，再按一次", "mode": cur}
            note = MODE_IDLE if mode != "drive" and self._posture() not in DRIVING else None
            if mode == cur:
                if mode != "drive":
                    self._modes[conn]["hb"] = now
                return {"mode": cur, "note": note}
            if cur != "drive":
                self._modes.pop(conn, None)
                # Always queue (review R1): this page's first head / body frame may still be in flight; _flush_clears inside _send_lk will wait for it to finish writing _latch
                self._clears.append({"conn": conn, "why": f"退出{MODE_CN[cur]}", "due": now, "tries": 0})
            if mode != "drive":
                self._modes[conn] = {"mode": mode, "hb": now}
                d = self._driver
                stop_first = self._web_driving and d is not None and d["conn"] == conn
            q["stop"] = max(q["stop"], q["hi"])            # stick frames from before the mode switch are void
        self.log.info(f"网页手柄 {'Y' if 'head' in (mode, cur) else 'B'} → {MODE_CN[mode]}（{by or '页面'}）"
                      + (f"：{note}" if note else ""), cat="手柄", dedup=False)
        if stop_first:
            self._stop_move({}, conn, by)                  # padd sends move 0 every tick in head / body mode (padd:1427-1448)
        self._flush_clears(force=True)
        return {"mode": mode, "note": note}

    # ================= Relax (review 2 I2) =================

    def note_relax(self, by=None, why="卸力了"):
        """The moment the top "relax", space, or Select on the diagram is pressed: app's run_relax calls this synchronously in the event loop (only takes the lock, no network, never raises).
        Record the relax time (no torque enable for 2 seconds), stop the action in progress, and queue head / body cleanup after the relax (round 3 V1 item 5).
        Also called once D-pad right on the diagram (reboot servos; the main program relaxes the whole body first) is accepted, with why describing it."""
        try:
            with self._lk:
                self._relax_at = self.clock()
                self._relax_noted += 1
                self.motion_studio.invalidate(why)
                a = self._action
                if a is not None:
                    a["why"] = a["why"] or why
                    a["stop"].set()
            self._request_clear(None, why, RELAX_CLEAR_DELAY_S)
            self._test_evt.set()
        except Exception:  # noqa: BLE001 —— the relax path must not fail because of the gamepad page
            pass

    def _relax_seen(self, view, now):
        """Called in feed_robot (holding the lock): the relax counter changed, or readback torque went from on to off (gamepad Select, robotctl, a fall, low battery), all recorded as relax.
        Returns True = this is a new relax."""
        new = False
        presses = view.get("estop_presses")
        if isinstance(presses, int) and not isinstance(presses, bool):
            if self._relax_presses is not None and presses > self._relax_presses:
                new = True
            self._relax_presses = presses
        bus = view.get("bus")
        if isinstance(bus, dict) and bus.get("mode") in ("motion", "commissioning"):
            on = bool((bus.get("native") or {}).get("torque_state_confirmed") is True) if bus.get("mode") == "motion" \
                else bus.get("torque_state") == "on"
            off = torque_off(bus) or relaxed(bus) is True
            if self._torque_was is True and off:
                new = True
            self._torque_was = True if on else (False if off else self._torque_was)
        if new:
            self._relax_at = now
        return new

    def _drive_feed(self, view):
        """Called in feed_robot (holding the lock, in the event loop: only changes memory): the first time Studio sees the main program up → queue a pose reset once;
        posture leaves "ready to walk" → exit modes and clear head / body (round 3 V1 item 8, V12)."""
        self.motion_studio.policy_feed(view)
        if self._pose_reset == "pending" and view.get("present") is True:
            self._pose_reset = "due"
            self._tick_evt.set()
        drv = self._posture() in DRIVING
        if not drv and not self.motion_studio.posture_allowed():
            self.motion_studio.invalidate("策略离开准备好走的状态")
        left = self._was_driving and not drv
        self._was_driving = drv
        if left and (self._modes or self._latch["head"] is not None or self._latch["body"] is not None):
            self._request_clear(None, f"策略停了（现在{POSTURE_CN.get(self._posture(), self._posture())}）")

    def _relax_block(self, now):
        r = self._robot or {}
        if r.get("estop_active"):
            return "正在卸力，等它确认完再说"
        guard = self.w.get("relax_guard", RELAX_GUARD_S)
        if now - self._relax_at < guard:
            return f"刚卸了力：{guard:g} 秒内不接受让它动的指令（防止刚卸力又被顶起来）"
        return None

    # ================= Speed limits (review 24), head / mouth amplitude (round 3 V9) =================

    def _speed_limits(self, now=None):
        """padd's full-stick speed is a command-line argument (padd main.rs:158-168); if padd.service's ExecStart has no arguments (padd/systemd/padd.service:36)
        it's the official default. The file is read in a background thread (_refresh_files); here we only take the cache (review 2, minor 9)."""
        return self._limits

    def _read_padd_texts(self):
        texts = []
        try:
            texts.append((PADD_UNIT, self.read_text(PADD_UNIT)))
        except Exception:  # noqa: BLE001 —— no such file / no permission: use the official default
            pass
        try:
            for name in sorted(self.list_dir(PADD_DROPIN_DIR)):
                if name.endswith(".conf"):
                    p = os.path.join(PADD_DROPIN_DIR, name)
                    texts.append((p, self.read_text(p)))
        except Exception:  # noqa: BLE001
            pass
        return texts

    def _read_inputs(self, texts):
        """Head / mouth amplitude (round 3 V9) + where padd reads its config (--config; if unset, robotd.toml's default path: Args in fork padd/src/main.rs).
        First look at padd's own ack /run/padd/input-settings.json (fork input_settings.rs:63-74: only written once really applied, containing the numbers it's using),
        and if the padd that wrote the ack is still alive and the file path matches, it wins (review R10); otherwise read the file ourselves by padd's rules."""
        inputs = parse_padd_inputs(texts)
        text, err, ack = None, None, None
        if inputs["input_settings"]:
            try:
                text = self.read_text(inputs["input_settings"])
            except FileNotFoundError:
                err = "文件不在"
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            try:
                a = json.loads(self.read_text(PADD_INPUT_ACK))
                pid = a.get("pid") if isinstance(a, dict) else None
                alive = isinstance(pid, int) and not isinstance(pid, bool) and self.exists(f"/proc/{pid}")
                if alive and a.get("path") == inputs["input_settings"]:
                    ack = a.get("settings")
            except Exception:  # noqa: BLE001 —— no ack (padd hasn't read this file, or on a computer): read it ourselves
                pass
        return input_limits(inputs, text, err, ack), inputs["config"]

    # ================= Web sticks =================

    def _seq(self, args):
        seq = args.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            return None
        return seq

    def _gate(self, conn, now):
        """Common gate for continuous commands (stick move / head / pose, held buttons) (called within _lk).
        Returns None = allowed; returns a dict = silently dropped (the page has left); raises Refused if it can't be done (reason shown on the page)."""
        if conn in self._gone:
            return {"dropped": "页面已经断开"}
        if conn in self._closed:
            return {"dropped": "这个页面不在手柄区"}
        attached, _ = self._pad_attached(now)
        if attached:
            if not self._pad_said:
                self._pad_said = True
                self.log.info("实体手柄连着，网页摇杆只跟着它动、不发指令", cat="手柄")
            raise Refused("实体手柄连着：网页摇杆现在只跟着它动、不发指令（padd 哪怕没人碰也每 0.1 秒发一次「停」，"
                          "网页的会被盖掉）。要用网页遥控，先把手柄关掉")
        self._pad_said = False
        ok, why = self._robot_ok(now)
        if ok is not True:           # review 14: if it's unknown whether the main program is in motion mode, don't allow either
            raise Refused(f"现在不能遥控：{why or '读不到主程序的状态'}")
        block = self._relax_block(now)
        if block:
            raise Refused(block)
        return None

    def _send_intent(self, chan, method, params, conn, by, seq, mode=None):
        """Send one frame of a continuous command (move / head / pose notification): pass _gate, block old ones by sequence number, take the wheel, and only send the latest within 40 ms per channel.
        Checking and sending are inside _send_lk, so the order robotd receives is the order decided here. mode: before sending a head / body frame, check once more that the mode hasn't changed (round 3 V6).
        Returns (result dict, whether it was sent)."""
        now = self.clock()
        motion_epoch = self.motion_studio.epoch
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "动作会话已经改变，旧指令已丢弃"}, False
            g = self._gate(conn, now)
            if g:
                return g, False
            if mode is not None and self._mode_of(conn) != mode:
                return {"dropped": f"模式对不上：后端现在是「{MODE_CN[self._mode_of(conn)]}」", "mode": self._mode_of(conn)}, False
            q = self._seq_of(conn)
            if seq is None:
                seq = q["hi"] + 1        # the page gave no sequence number: order by arrival
            if seq <= q["stop"] or seq <= q["sent"].get(chan, -1):
                return {"dropped": "旧的指令（已经松手了）"}, False
            self._take_lease(conn, by, now)
            q["hi"] = max(q["hi"], seq)
            q["latest"][chan] = max(q["latest"].get(chan, -1), seq)
            gap = MOVE_MIN_GAP_S - (now - self._last_sent_at.get(chan, -1e9))
        if self.robot is None:
            raise Refused("这只鸭子没配主程序的地址")
        if self._clears:
            self._flush_clears()         # the wheel just changed hands: clear the previous page's head / body first
        if gap > 0:
            self._cancel_wait(gap)
        with self._send_lk:
            with self._lk:
                d, q = self._driver, self._seq_of(conn)
                if (not self.motion_studio.request_current() or motion_epoch != self.motion_studio.epoch or conn in self._gone or conn in self._closed or seq != q["latest"].get(chan) or seq <= q["stop"]
                        or d is None or d["conn"] != conn or (mode is not None and self._mode_of(conn) != mode)):
                    return {"dropped": "被更新的指令替掉了，或者已经松手"}, False
                q["sent"][chan] = seq
                self._last_sent_at[chan] = self.clock()
            try:
                self._notify_output(method, params)
            except (Unreachable, Timeout) as e:
                raise Refused(f"没发出去：{e}") from None
            with self._lk:
                if chan in ("head", "body"):
                    nonzero = any(abs(v) > 1e-9 for k, v in params.items() if k != "active")
                    self._latch[chan] = {"conn": conn, "nonzero": nonzero, "at": self.clock()}
                    self._tick_evt.set()
        return {"merged": gap > 0}, True

    def _move(self, args, conn=None, by=None, mode="drive"):
        """One walking frame (both the old move channel and sticks' walking mode go through here). mode: which mode this frame belongs to; dropped if the backend's mode isn't that ——
        even if it switches to head / body mode between checking the mode and sending, no velocity is sent in head / body mode (review R6, round 3 V6)."""
        try:
            vals = [float(args.get(k, 0) or 0) for k in ("vx", "vy", "vyaw")]
        except (TypeError, ValueError):
            raise Refused("速度要是数字") from None
        if not all(math.isfinite(v) for v in vals):
            raise Refused("速度不是有限的数")
        lim = self._speed_limits()
        vx = max(-lim["v"], min(lim["v"], vals[0]))
        vy = max(-lim["v"], min(lim["v"], vals[1]))
        vyaw = max(-lim["w"], min(lim["w"], vals[2]))
        with self._lk:
            start = not self._web_driving and any((vx, vy, vyaw))
        r, sent = self._send_intent("move", "robot.move", {"vx": vx, "vy": vy, "vyaw": vyaw}, conn, by, self._seq(args),
                                    mode=mode)
        if not sent:
            return r
        with self._lk:
            self._web_driving = any((vx, vy, vyaw))
            self.virtual.update(last=[vx, vy, vyaw], at=self.clock())
        if start:
            self.log.info(f"网页遥控开始开（{by or '页面'}，robot.move）", cat="手柄")
        return {"sent": [vx, vy, vyaw], "merged": r["merged"]}

    def _sticks(self, args, conn=None, by=None):
        """The web gamepad's sticks (the two on the diagram and the two big ones below share this one channel, round 3 V6, V20): {mode, lx, ly, rx, ry, seq},
        -1..1, x right and y down positive. The backend converts using padd's formula (sticks_to_intent), and the mode recorded by the backend wins: on mismatch drop it and tell the page."""
        mode = args.get("mode", "drive")
        if mode not in MODES:
            raise Refused(f"不认识的模式：{mode}")
        try:
            vals = [float(args.get(k, 0) or 0) for k in ("lx", "ly", "rx", "ry")]
        except (TypeError, ValueError):
            raise Refused("摇杆要是数字") from None
        if not all(math.isfinite(v) for v in vals):
            raise Refused("摇杆不是有限的数")
        lx, ly, rx, ry = (max(-1.0, min(1.0, v)) for v in vals)
        now = self.clock()
        with self._lk:
            cur = self._mode_of(conn)
            if not self.motion_studio.request_current():
                return {"dropped": "动作会话已经改变，旧摇杆请求已丢弃", "mode": cur}
            if conn in self._gone or conn in self._closed:
                return {"dropped": "页面已经离开", "mode": cur}
            if mode != cur:
                why = (self._mode_exit.get(conn) or {}).get("why")
                return {"dropped": f"模式对不上：后端现在是「{MODE_CN[cur]}」" + (f"（{why}）" if why else ""), "mode": cur}
            if cur != "drive":
                self._modes[conn]["hb"] = now
                if self._posture() not in DRIVING:
                    self._gate(conn, now)           # mirroring, relax, and the like are still reported first
                    return {"dropped": MODE_IDLE, "mode": cur}
                a = self._action
                if cur == "head" and a is not None and any(C.head_at(s, 0.0) is not None for s in a["steps"]):
                    raise Refused(f"正在做「{a['name']}」（也在动头）：等它做完或者先松开")
        method, params = sticks_to_intent(cur, lx, ly, rx, ry, self._speed_limits(), self._inputs["head"])
        if cur == "drive":
            r = self._move(dict(params, seq=args.get("seq")), conn, by, mode="drive")
            return dict(r, mode=self._mode_of(conn))
        r, sent = self._send_intent(cur, method, params, conn, by, self._seq(args), mode=cur)
        if sent:
            return {"sent": params, "mode": cur, "merged": r["merged"]}
        return dict(r, mode=cur)

    def _cancel_wait(self, s):
        threading.Event().wait(s)

    def _stop_move(self, args=None, conn=None, by=None):
        """Release: in walking mode send move 0 once; in head mode re-center the head, in body mode re-center the body (still in body mode: {0,0,0,active:true}, round 3 addendum 2).
        The server doesn't repeat sends: if the browser disconnects, robotd's deadman zeros it after 500 ms (safety.rs:226-237), and head / body rely on the watchdog.
        When mirroring and the web page isn't driving, don't send move 0 (don't interrupt the physical gamepad); otherwise an extra 0 isn't dangerous, so send it."""
        if self.robot is None:
            return {}
        args = args or {}
        with self._send_lk:
            with self._lk:
                if not self.motion_studio.request_current():
                    return {"dropped": "动作会话已经改变，旧停止请求已丢弃"}
                now = self.clock()
                q = self._seq_of(conn)
                seq = self._seq(args)
                if seq is None:
                    seq = q["hi"] + 1
                q["stop"] = max(q["stop"], seq)
                q["hi"] = max(q["hi"], seq)
                d = self._driver
                mine = d is None or d["conn"] == conn
                attached, _ = self._pad_attached(now)
                if args.get("owned_only") is True and (d is None or not mine or attached or self._mode_of(conn) != "drive"):
                    return {"dropped": "当前页面没有走路控制权，未发送停止帧"}
                if d is not None and d["conn"] == conn:
                    d["seen"] = now
                send = self._web_driving or not attached
                center = None
                mode = self._mode_of(conn)
                lat = self._latch.get(mode) if mode != "drive" else None
                if lat is not None and lat["conn"] == conn and lat["nonzero"]:
                    center = ("robot.head", HEAD_ZERO) if mode == "head" else ("robot.pose", POSE_CENTER)
                    lat.update(nonzero=False, at=now)
            if send:
                try:
                    self._notify_output("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
                except (Unreachable, Timeout) as e:
                    raise Refused(f"「停」没发出去（鸭子 0.5 秒收不到也会自己停）：{e}") from None
            if center is not None:
                try:
                    self._notify_output(center[0], dict(center[1]))
                except (Unreachable, Timeout) as e:
                    with self._lk:
                        lat.update(nonzero=True)            # the watchdog retries after 0.6 seconds
                    raise Refused(f"回正没发出去（0.6 秒后再试一次）：{e}") from None
            with self._lk:
                was = self._web_driving and mine
                if mine and send:
                    self._web_driving = False
                    self.virtual.update(last=[0.0, 0.0, 0.0], at=self.clock())
        if was:
            self.log.info("网页遥控松开了", cat="手柄")
        return {"sent": send, **({"centered": True} if center is not None else {})}

    # ================= Held buttons: LT / RT / X (round 3 V4) =================

    def _keys_op(self, args, conn, by):
        """{held:[held ones], down:[just pressed this time], seq}. Sent by the page on press and release, and every 0.15 seconds while held.
        Only accepts "already recorded by the backend" and "just pressed this time": if the backend stopped it midway (relax, taken over...), the page's heartbeat reporting it won't renew it by itself;
        it must be released and pressed again (returns ended to the page). What's actually sent to robotd is in the background thread (_keys_plan)."""
        held, down = args.get("held"), args.get("down") or []
        if not isinstance(held, list) or not isinstance(down, list) or any(k not in HELD_KEYS for k in held + down):
            raise Refused("held / down 只能是 lt、rt、x")
        seq = self._seq(args)
        now = self.clock()
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "动作会话已经改变，旧按键请求已丢弃", "held": []}
            if conn in self._gone or conn in self._closed:
                return {"dropped": "页面已经离开", "held": []}
            st = self._keys.get(conn)
            q = self._seq_of(conn)
            if seq is not None:
                if seq <= q["keys"]:
                    return {"dropped": "旧的", "held": sorted(st["held"]) if st is not None and not st.get("end") else []}
                q["keys"] = seq
            had = set(st["held"]) if st is not None and not st.get("end") else set()
            want = set(held)
            pressed = (set(down) & want) - had
            keep = (want & had) | pressed
            ended = sorted(want - keep)
            if pressed:
                attached, _ = self._pad_attached(now)
                if attached:
                    raise Refused(MIRROR_SVG)
                base = self._base_block(now)
                if base:
                    raise Refused(base)
                a = self._action
                if pressed & {"lt", "rt"} and a is not None and any(C.mouth_at(s, 0.0) is not None for s in a["steps"]):
                    raise Refused(f"正在做「{a['name']}」（也在动嘴）：等它做完或者先松开")
                self._take_lease(conn, by, now)
            if st is None or st.get("end"):
                if not keep:
                    return {"held": [], "ended": ended}
                st = self._keys[conn] = {"held": {}, "started": now, "by": by, "mouth": False, "rt": False,
                                         "wheee": False, "x_down": None, "end": None,
                                         **({k: st[k] for k in ("mouth", "wheee")} if st is not None else {})}
            released = set(st["held"]) - keep
            for k in released:
                st["held"].pop(k, None)
                if k == "x":
                    self._x_armed.pop(conn, None)
            for k in keep:
                st["held"][k] = now
            if "x" in pressed:
                st["x_down"] = now
                self._x_armed.pop(conn, None)     # a new press: the previous X press's arm is void (review R5)
            if keep:
                self._touch_lease(conn, now)
        for k in sorted(pressed):
            self.log.info(f"网页手柄 {KEY_CN[k]} 按下（{by or '页面'}）", cat="手柄", dedup=False)
        for k in sorted(released):
            self.log.info(f"网页手柄 {KEY_CN[k]} 松开了", cat="手柄", dedup=False)
        self._tick_evt.set()
        return {"held": sorted(keep), "ended": ended}

    def _keys_abort(self, conn, st, now):
        """Whether held buttons should be stopped midway (called within _lk): reasons copied from _abort_reason."""
        if conn in self._gone or conn in self._closed:
            return "页面离开了"
        if self._pad_attached(now)[0]:
            return "实体手柄连上了"
        d = self._driver
        if d is None or d["conn"] != conn:
            return "被别的页面接管了"
        if self._relax_at >= st["started"] or (self._robot or {}).get("estop_active"):
            return "卸力了"
        return self._base_block(now)

    def _keys_plan(self, now, sends, logs):
        """Called by the background thread every tick (within _lk): plan what to send this tick according to "which buttons are held" (fork padd:1351-1396, 1182-1211)."""
        for conn, st in list(self._keys.items()):
            why = st.get("end") or self._keys_abort(conn, st, now)
            if why:
                fresh = set()
            else:
                fresh = {k for k, at in st["held"].items() if now - at < (X_HOLD_S if k == "x" else KEYS_HOLD_S)}
            lt, rt, x = "lt" in fresh, "rt" in fresh, "x" in fresh
            mouth = (lt or rt) and self._relax_block(now) is None       # just relaxed: only sound, no mouth
            if mouth or st["mouth"]:
                sends.append(("robot.mouth", {"open": round(self._inputs["mouth"] / 100.0, 3) if mouth else 0.0}, None))
                st["mouth"] = mouth
            if rt and not st["rt"]:
                sends.append(("robot.sound", {"tag": "chirp"}, None))        # the moment RT is pressed (in padd it's the rising edge past 0.3)
            st["rt"] = rt
            if lt:
                sends.append(("robot.sound", {"tag": "wheee", "hold": True}, None))
                st["wheee"] = True
            elif st["wheee"]:
                sends.append(("robot.sound", {"tag": "wheee", "hold": False}, None))   # no hold means true (intents.rs:443-452)
                st["wheee"] = False
            arm = self._x_armed.get(conn)
            if x and arm is not None and arm["x_down"] == st.get("x_down") \
                    and self._posture() in DRIVING and self._relax_block(now) is None:
                sends.append(("robot.do", {"skill": arm["skill"]}, None))   # continuous rolling: robotd only refreshes a 0.15-second window (control.rs:429-434)
            gone = set(st["held"]) - fresh
            if gone:
                reason = why or "页面 0.45 秒没说还按着（松手、切页或断网）"
                logs.append(("安全" if why in (None, "卸力了") else "手柄",
                             f"网页手柄 {'、'.join(KEY_CN[k] for k in sorted(gone))} 停了：{reason}"))
                for k in gone:
                    st["held"].pop(k, None)
                if "x" in gone:
                    self._x_armed.pop(conn, None)
            if why:
                st["end"] = why
            if not st["held"] and not st["mouth"] and not st["wheee"]:
                del self._keys[conn]

    def _key_press(self, args, conn, by):
        """One-shot buttons on the web gamepad diagram: A / X / LB / RB / D-pad down (round 3 V14, V16). Acts per pad.bindings (official defaults if unreadable):
        bound to sit_toggle → "stand up / sit down" depending on whether it's sitting; empty = disabled; with error = this duck doesn't have it. Once the request for this X press is accepted,
        continuous rolling only while held (_keys_plan sends notifications every tick, plan C)."""
        key = args.get("key")
        if key not in BIND_KEYS:
            raise Refused(f"不认识的键：{key}")
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        if self.robot is not None and now - self._bindings_at > BINDINGS_STALE_S:
            self._fetch_bindings()
        with self._lk:
            mv = self._motion_view(self.clock())
        row = mv["keys"][key]
        name = KEY_CN[key]
        if not row["ok"]:
            self.log.info(f"网页手柄 {name}：不能按（{row['why']}）", cat="手柄")
            raise Refused(row["why"])
        self.log.info(f"网页手柄 {name} → {row['does']}（{by or '页面'}）", cat="手柄", dedup=False)
        label = f"网页手柄 {name} → {row['does']}"
        if row["op"] == "skill":
            with self._lk:
                st = self._keys.get(conn)
                x_down0 = st.get("x_down") if st is not None else None    # which X press this is (the keys channel may not have arrived yet: None)
            r = self._motion_cmd("skill", {"name": row["skill"]}, conn, by, label=label)
            if key == "x":
                # arm is bound to the X press that sent the request (review R5): _keys_plan only rolls continuously when the x_down of "the press currently held" matches it.
                # A quick tap where the request replies after release: what's recorded is the previous press's x_down; when X is pressed anew, _keys_op discards it first, so it doesn't match,
                # and if the next press's request is rejected it won't keep rolling based on it. If the keys channel arrives later than the request (x_down0 is None): if X is still held, use the current press
                with self._lk:
                    st = self._keys.get(conn)
                    if x_down0 is None and st is not None and not st.get("end") and "x" in st["held"]:
                        x_down0 = st.get("x_down")
                    if x_down0 is not None:
                        self._x_armed[conn] = {"skill": row["skill"], "x_down": x_down0}
                self._tick_evt.set()
            return r
        return self._motion_cmd(row["op"], {}, conn, by, label=label)

    def _start(self, args, conn, by):
        """Start on the web gamepad diagram (round 3 V7, V8): pick "Stop (stand still) / Start walking / Stand up" based on the current posture, and reject if it differs from what the page saw (expect)."""
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        with self._lk:
            st = self._motion_view(now)["start"]
        expect = args.get("expect")
        if expect is not None and expect != st["op"]:
            self.log.info(f"网页手柄 Start：页面以为是「{expect}」，后端判的是「{st['label']}」，没发", cat="手柄")
            raise Refused(f"状态刚变了，再按一次（现在按 Start 会「{st['label']}」）")
        if not st["ok"]:
            self.log.info(f"网页手柄 Start：不能按（{st['why']}）", cat="手柄")
            raise Refused(st["why"])
        self.log.info(f"网页手柄 Start → {st['label']}（{by or '页面'}）", cat="手柄", dedup=False)
        return self._motion_cmd(st["op"], {}, conn, by, label=f"网页手柄 Start → {st['label']}")

    def _reboot(self, args, conn, by):
        """D-pad right on the web gamepad diagram: reboot all servos (as official: sends on a single press, no confirmation). Ignores the wheel and doesn't take the "previous one hasn't replied yet" slot:
        it's an emergency path like relax. The main program relaxes the whole body first and then reboots (fork handover version main.rs:2731-2758); once accepted, a relax is recorded here."""
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        with self._lk:
            mv = self._motion_view(now)
        row = mv["reboot"]
        what = "网页手柄 十字右 → 重启全部舵机"
        if not row["ok"]:
            self.log.info(f"网页手柄 十字右：不能按（{row['why']}）", cat="手柄")
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": row["why"], "at": now}
            raise Refused(row["why"])
        self.log.info(f"{what}（{by or '页面'}）", cat="手柄", dedup=False)
        try:
            r = self._call(what, "robot.rebootMotors", {"ids": []}, by, {"posture": mv["posture"]})
        except Refused as e:
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": str(e), "at": self.clock()}
            raise
        self.note_relax(by, "重启舵机（主程序先全身卸力）")
        note = r.get("reason") if isinstance(r, dict) else None
        with self._lk:
            self._last_cmd = {"what": what, "by": by, "ok": True, "reason": note, "at": self.clock()}
        return {"accepted": True, "reason": note, "did": "reboot"}

    def _drive_mode(self, args, conn, by):
        """D-pad up held 3 seconds on the web gamepad diagram: walking ⇄ roller (as official padd:766-806). The 3 seconds are timed on the page; when reached it sends {expect: target mode};
        rejected if it differs from the backend's judgment (state just changed). Once accepted the main program quacks once (walking) / twice (roller), returns to stance, and switches to that mode's policy
        (fork handover version main.rs:2870-2930); it rejects if no roller model is installed."""
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        with self._lk:
            mv = self._motion_view(now)
            row = mv["drive_mode"]
            target = row["target"]
            what = f"网页手柄 十字上（按住 3 秒）→ 切到{DRIVE_MODE_CN.get(target, '另一个模式')}"
            why = row["why"]
            expect = args.get("expect")
            if why is None and expect is not None and expect != target:
                why = f"状态刚变了，再按住一次（现在会{row['does'].replace('按住 3 秒：', '')}）"
            if why is None and self._cmd_busy:
                why = "上一个指令还没回话，等一下"
            if why is None:
                held = self._lease_holder(now)
                if held is not None and held["conn"] != conn:
                    why = f"{held['by'] or '另一个页面'}正在推摇杆：等它松手，或者点「接管」"
            if why is not None:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": why, "at": now}
            else:
                self._cmd_busy = True
        if why is not None:
            self.log.info(f"网页手柄 十字上：不能切（{why}）", cat="手柄")
            raise Refused(why)
        self.log.info(f"{what}（{by or '页面'}）", cat="手柄", dedup=False)
        try:
            r = self._call(what, "robot.setMode", {"mode": target}, by, {"posture": mv["posture"], "mode": row["current"]})
        except Refused as e:
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": str(e), "at": self.clock()}
            raise
        finally:
            with self._lk:
                self._cmd_busy = False
        note = r.get("reason") if isinstance(r, dict) else None
        if note and "already" in note.lower():
            note = f"已经是{DRIVE_MODE_CN[target]}了"
        with self._lk:
            self._last_cmd = {"what": what, "by": by, "ok": True, "reason": note, "at": self.clock()}
        return {"accepted": True, "reason": note, "did": "drive_mode", "target": target}

    # ================= Background thread: held buttons, watchdog, cleanup (25 Hz, sleeps when idle) =================

    def _tick_work(self):
        return bool(self.motion_studio.session or self.motion_studio._pending_cleanup or self._keys or self._clears or self._modes or self._pose_reset == "due"
                    or (self._latch["head"] or {}).get("nonzero") or (self._latch["body"] or {}).get("nonzero"))

    def _tick_loop(self):
        while not self._tick_stop.is_set():
            try:
                self._tick_once()
            except Exception as e:  # noqa: BLE001 —— this thread must not silently die: held buttons and the watchdog depend on it
                key = f"{type(e).__name__}: {e}"[:200]
                if key not in self._tick_said:
                    self._tick_said.add(key)
                    self.log.error("手柄页的后台线程出错（按住的键、看门狗）", cat="手柄", raw=key, exc=True,
                                   hint="这是 Studio 的问题，导出诊断包发出来；线程会接着跑")
            with self._lk:
                busy = self._tick_work()
            if busy:
                self._tick_stop.wait(TICK_S)
            else:
                self._tick_evt.wait(1.0)
                self._tick_evt.clear()

    def _tick_once(self):
        if self._update_blocked():
            with self._lk:
                held=bool(self._modes or self._keys or self._latch['head'] or self._latch['body'])
            if held:self._request_clear(None,'软件 / 主程序更新保护仍在',say=False)
        self.motion_studio.tick()
        self._flush_clears()                       # it takes _send_lk itself: placed before the lock below (Lock isn't reentrant)
        sends, logs = [], []                       # sends: (method, params, marker None / "pose_reset" / "watchdog")
        # Deciding and sending happen under the same _send_lk (review R2, same pattern as _flush_clears and _stop_move): after the watchdog decides "re-center (active:true)"
        # and before it's sent, no other thread may cut in to send exit (active:false) first only to have it reopened by this re-center —— then _latch would already be cleared and nobody would ever clear it
        with self._send_lk:
            with self._lk:
                now = self.clock()
                if self._pose_reset == "due":
                    self._pose_reset = "sending"
                    sends.append(("robot.pose", dict(POSE_OFF), "pose_reset"))
                if self._pad_attached(now)[0] and (self._modes or self._keys or self._latch["head"] or self._latch["body"]):
                    self._request_clear(None, "实体手柄连上了")               # round 3 V1 item 6 (the configd path counts too)
                for kind, center in (("head", HEAD_ZERO), ("body", POSE_CENTER)):
                    lat = self._latch[kind]
                    if lat is not None and lat["nonzero"] and now - lat["at"] > STICK_STALE_S:
                        lat.update(nonzero=False, at=now)
                        sends.append(("robot.head" if kind == "head" else "robot.pose", dict(center), "watchdog"))
                        logs.append(("安全", f"{'头' if kind == 'head' else '身体'}的摇杆 {STICK_STALE_S:g} 秒没有新的一帧（页面卡住了？）："
                                           f"{'头回正' if kind == 'head' else '身体回中'}"))
                for c, m in list(self._modes.items()):
                    if now - m["hb"] > MODE_HB_S:
                        why = f"页面 {MODE_HB_S:g} 秒没报还在{MODE_CN[m['mode']]}"
                        logs.append(("安全", f"{why}：退出"))
                        self._request_clear(c, why, say=False)          # the same event only logs the "safety" line (V19)
                self._keys_plan(now, sends, logs)
            for method, params, tag in (sends if self.robot is not None else []):
                try:
                    self._notify_output(method, params)
                except (Unreachable, Timeout) as e:
                    if tag == "pose_reset":
                        with self._lk:
                            self._pose_reset_tries += 1
                            self._pose_reset = "pending" if self._pose_reset_tries < 3 else "failed"
                    if method not in self._tick_said:
                        self._tick_said.add(method)
                        self.log.warn(f"网页手柄的 {method} 没发出去", cat="手柄", step=method, raw=str(e),
                                      hint="主程序 robotd 不在？嘴、头没收到也不危险：robotd 自己不动")
                    continue
                self._tick_said.discard(method)
                if tag == "pose_reset":
                    with self._lk:
                        self._pose_reset = "done"
                    self.log.info("Studio 连上主程序：发了一次 robot.pose {\"active\": false}（清掉上一次可能留下的身体模式）",
                                  cat="手柄")
        for cat, msg in logs:
            self.log.write(msg, cat=cat, level="info", dedup=False)

    def _drive_close(self):
        """Studio shutting down (called in pad.close, in a thread): first stop the background thread and wait for it, then do our best to clear head / body and release held buttons (round 3 V1 item 9)."""
        self._tick_stop.set()
        self._tick_evt.set()
        t = self._tick_thread
        if t is not None and t is not threading.current_thread():
            t.join(0.5)       # wait for it to finish this tick's sends: otherwise its queued "open mouth" might land after the "close mouth" below, leaving the mouth open (review R8)
        self.motion_studio.close()
        try:
            self._request_clear(None, "Studio 关了")
            self._flush_clears(force=True)
            sends = []
            with self._lk:
                for st in self._keys.values():
                    if st["mouth"]:
                        sends.append(("robot.mouth", {"open": 0.0}))
                    if st["wheee"]:
                        sends.append(("robot.sound", {"tag": "wheee", "hold": False}))
                self._keys.clear()
            if self.robot is not None:
                with self._send_lk:
                    for method, params in sends:
                        try:
                            self._notify_output(method, params)
                        except (Unreachable, Timeout):
                            pass
        except Exception:  # noqa: BLE001 —— best effort on the shutdown path
            pass

    # ================= Stand up / start walking / sit down / skills / sounds: whether they can be pressed =================

    def _update_blocked(self):
        try:return getattr(self,'update_guard',lambda:False)() is True
        except Exception:return True

    def _base_block(self, now, *, ignore_mapping=False):
        """Cases unrelated to posture where no action at all can be done (sounds are blocked too: in debug mode the main program is read-only, fork main.rs:5379-5396)."""
        if self._update_blocked():return '软件 / 主程序更新保护仍在'
        mapping = getattr(self, 'mapping', None)
        if not ignore_mapping and mapping is not None and mapping.blocked:
            return '手柄映射／回中确认中，动作输出已暂停，网页卸力仍可使用'
        r = self._robot or {}
        if self._robot_at is None or now - self._robot_at > 3:
            return "Studio 还没收到主程序的状态"
        if r.get("paused"):
            return "正在调舵机：主程序停着（舵机页的会话还开着）。点页面顶上的「交还主程序」才交还"
        if r.get("present") is False:
            return "主程序 robotd 没在跑"
        bus = r.get("bus") if isinstance(r.get("bus"), dict) else None
        if bus is None or r.get("bus_at") is None or now - r["bus_at"] > 3:
            return "读不到主程序的状态"
        if bus.get("phase") in STARTING_PHASES:
            return "主程序还在启动"
        if bus.get("mode") == "commissioning":
            return "调试模式：主程序这时只读，动作都不接受"
        if bus.get("mode") != "motion":
            return f"主程序在 {bus.get('mode')} 模式"
        return None

    def _policies(self):
        p = (self._robot or {}).get("policies")
        return p if isinstance(p, dict) else None

    def _known_skills(self):
        """Names robot.do accepts: ground_pick (if that slot is installed) + sit_toggle (if sitstand is installed) + skills (robotd main.rs:4136-4156).
        Returns None if robot.policies can't be read."""
        p = self._policies()
        if p is None:
            return None
        slots = {s.get("slot"): s for s in p.get("slots") or [] if isinstance(s, dict)}
        names = []
        if (slots.get("ground_pick") or {}).get("path"):
            names.append("ground_pick")
        if (slots.get("sitstand") or {}).get("path"):
            names.append("sit_toggle")
        names += [s for s in p.get("skills") or [] if isinstance(s, str)]
        return names

    def _posture(self):
        r = self._robot or {}
        return "servo_session" if r.get("paused") else (r.get("posture") or "unknown")

    def _skill_why(self, name, need_drive, known, pol):
        """Whether a skill can be done now (used by skill buttons, skills in combo actions, and when a combo reaches that step: review 2, minor 6)."""
        if known is None:
            return "读不到这只鸭子有哪些技能（robot.policies 只在运动模式下问）"
        if name not in known:
            return f"这只鸭子没有「{C.SKILL_CN.get(name, name)}」"
        if need_drive:
            return need_drive
        if name == "roller_stand" and pol.get("mode") != "roller":
            return "装了滑轮、切到轮滑模式才用（手柄十字上按住 3 秒切换）"
        return None

    def _bind_map(self):
        """What each of the five bindable buttons is currently bound to (round 3 V14): {button: {"skill", "error", "overridden", "src"}}. If pad.bindings can't be read,
        or the list doesn't have this button, use the official defaults (robotd-params lib.rs:175-215)."""
        rows = {b.get("button"): b for b in self.bindings or [] if isinstance(b, dict)}
        out = {}
        for k in BIND_KEYS:
            b = rows.get(k)
            if b is not None and isinstance(b.get("skill"), str):
                out[k] = {"skill": b["skill"], "error": b.get("error") or None, "overridden": bool(b.get("overridden")),
                          "src": "pad.bindings"}
            else:
                out[k] = {"skill": DEFAULT_BIND[k], "error": None, "overridden": False,
                          "src": "官方默认" + ("（读不到 pad.bindings）" if self.bindings is None else "")}
        return out

    def _key_rows(self, buttons, sitting, skills, skills_why, known, need_drive, pol):
        """What A / X / LB / RB / D-pad down on the web gamepad diagram each do and whether they can be pressed now (pushed to the page for drawing; _key_press uses the same data when pressed)."""
        out = {}
        for k, b in self._bind_map().items():
            skill = b["skill"]
            row = {"key": k, "skill": skill, "src": b["src"], "overridden": b["overridden"], "op": None,
                   "does": C.SKILL_CN.get(skill, skill) if skill else "（关掉了）"}
            if b["error"]:
                row.update(ok=False, why=f"绑的「{skill}」这只鸭子用不了：{b['error']}")
            elif not skill:
                row.update(ok=False, why="这个键被关掉了（robotd.toml 的 [pad] 里设成了空）")
            elif skill == "sit_toggle":
                # Don't send robot.do sit_toggle directly: go "stand up / sit down" depending on whether it's sitting (review 2 S2, round 3 V14)
                if sitting is None:
                    row.update(ok=False, why=NO_SIT_INFO, op="sit")
                else:
                    btn = buttons["stand" if sitting else "sit"]
                    row.update(ok=btn["ok"], why=btn["why"], op=btn["op"], does=btn["label"])
            else:
                s = next((x for x in skills if x["name"] == skill), None)
                why = s["why"] if s is not None else (skills_why or self._skill_why(skill, need_drive, known, pol))
                row.update(ok=why is None, why=why, op="skill")
            out[k] = row
        return out

    def _motion_view(self, now):  # noqa: C901
        """Pushed to the page: whether each button can be pressed, and why not. The server also rejudges with this when a button is pressed."""
        base = self._base_block(now)
        relax = self._relax_block(now)
        block = base or relax
        pose = self._posture()
        pol = self._policies() or {}
        sit_raw = pol.get("sitting")
        sitting = sit_raw if isinstance(sit_raw, bool) else None      # None = unreadable (review 2 S2: no guessing)
        homed = pol.get("homed") if isinstance(pol.get("homed"), bool) else None
        r = self._robot or {}
        bus = r.get("bus") if isinstance(r.get("bus"), dict) else {}
        policy_on = bus.get("policy_enabled") is True
        torque_on = (bus.get("native") or {}).get("torque_state_confirmed") is True
        batt = r.get("battery_pct")
        job = self._job_alive()
        # Not steady yet (state.posture judges homing): if the main program's home_start_guard gave a reason, include it (e.g. "机身未直立" (body not upright)), otherwise people don't know what it's waiting for
        guard = bus.get("home_start_guard") if isinstance(bus.get("home_start_guard"), dict) else {}
        unsteady = "还在站起来，站稳了再点" + (f"（{guard['reason']}）" if guard.get("ready") is False
                                             and isinstance(guard.get("reason"), str) and guard["reason"] else "")

        def b(op, label, call, why):
            return {"op": op, "label": label, "call": call, "ok": why is None, "why": why}

        # Stand up: when sitting it needs sit_toggle (also needs policy running and HOME reached), init only when not sitting; if sitting status is unreadable it can't be clicked
        stuck = None
        if block:
            stand = b("stand", "站起来", None, block)
        elif sitting is None:
            stand = b("stand", "站起来", None, NO_SIT_INFO)
        elif sitting:
            if policy_on and torque_on and (homed is True or bus.get("homed") is True):
                stand = b("stand", "站起来", "robot.do sit_toggle",
                          None if "sit_toggle" in (self._known_skills() or []) else "这只鸭子没装坐下 / 站起的模型")
            else:
                stuck = ("坐着、但策略没在跑（多半是坐着时卸了力）：网页现在站不起来——发 init 会跟坐下的锁存打架，"
                         "发 sit_toggle 主程序又要策略在跑才收。先把它扶起来放平再点「站起来」，或者用手柄 Start")
                stand = b("stand", "站起来", None, stuck)
        elif pose == "limp":
            # Low battery doesn't block (user on 10-18: battery only warns): only a hint below the button, still clickable.
            # The old sentence "stands up and soon sits back down and shuts off" isn't true on our duck: say it per robotd's [safety] battery_empty_shutdown config (task 1 addendum)
            stand = b("stand", "站起来", "robot.init", None)
            if isinstance(batt, (int, float)) and not isinstance(batt, bool) and batt < 15:
                if self.battery_shutdown is True:
                    stand["note"] = f"电量只剩 {batt:.0f}%，先充电再玩；没电它到 6.6 V 会自己坐下关机"
                else:
                    stand["note"] = f"电量只剩 {batt:.0f}%，先充电再玩；没电它不会自己坐下"
        elif pose == "homing":
            stand = b("stand", "站起来", None, unsteady)
        elif pose in ("holding", "policy", "walking"):
            stand = b("stand", "站起来", None, "已经站着了")
        else:
            stand = b("stand", "站起来", None, f"读不出它现在的姿势（{POSTURE_CN.get(pose, pose)}）")
        # Start walking / stop (anyone can click stop, also after relax)
        if pose in DRIVING and not base:
            walk = b("walk_stop", "停下（站好）", "robot.stop → robot.enable {on:false}", None)
        elif block:
            walk = b("walk", "开始走", None, block)
        elif job:
            walk = b("walk", "开始走", None, "正在搜索 / 配对手柄（会占蓝牙）：等它做完再开始走")
        elif stuck:
            walk = b("walk", "开始走", None, "坐着又没在跑策略：看「站起来」那里的说明")
        elif sitting is None:
            walk = b("walk", "开始走", None, NO_SIT_INFO)
        elif sitting:
            walk = b("walk", "开始走", None, "坐着：先点「站起来」")
        elif pose == "holding":
            walk = b("walk", "开始走", "robot.enable {on:true}", None)
        elif pose == "limp":
            walk = b("walk", "开始走", None, "软着：先点「站起来」")
        elif pose == "homing":
            walk = b("walk", "开始走", None, unsteady)
        else:
            walk = b("walk", "开始走", None, f"读不出它现在的姿势（{POSTURE_CN.get(pose, pose)}）")
        # Sit down: not sitting (readable), policy running, HOME reached, not walking
        known = self._known_skills()
        if block:
            sit = b("sit", "坐下", None, block)
        elif sitting is None:
            sit = b("sit", "坐下", None, NO_SIT_INFO)
        elif sitting:
            sit = b("sit", "坐下", None, "已经坐着了")
        elif known is not None and "sit_toggle" not in known:
            sit = b("sit", "坐下", None, "这只鸭子没装坐下的模型（sitstand）")
        elif pose == "policy" and policy_on:
            sit = b("sit", "坐下", "robot.do sit_toggle", None if homed is not False else "它还在回站姿，等一秒")
        elif pose == "walking":
            sit = b("sit", "坐下", None, "在走：先松开摇杆，等它停下")
        elif pose == "holding":
            sit = b("sit", "坐下", None, "坐下要策略在跑（官方规定）：先点「开始走」，再点坐下")
        elif pose == "limp":
            sit = b("sit", "坐下", None, "软着：先点「站起来」")
        else:
            sit = b("sit", "坐下", None, f"现在{POSTURE_CN.get(pose, pose)}，坐不了")
        # Web gamepad Start: walking / ready to walk → stop; standing and holding → start walking; otherwise → stand up (round 3 V7, addendum 1 first row)
        if walk["op"] == "walk_stop":
            pick = walk
        elif pose == "holding":
            pick = walk
        else:
            pick = stand
        start = {"op": pick["op"], "label": pick["label"], "ok": pick["ok"], "why": pick["why"], "call": pick["call"]}
        # D-pad right: reboot all servos. Official sends on a single press and robotd never rejects (a duck whose overload protection tripped needs exactly this), so it can be pressed after relax too
        reboot = {"ok": base is None, "why": base, "does": "重启全部舵机：鸭子先软下来（扶住），之后按 Start 站回来"}
        # D-pad up held 3 seconds: walking ⇄ roller. Which one is current comes from robot.policies' mode (the official padd asks robot.mode once at boot)
        cur = pol.get("mode") if pol.get("mode") in DRIVE_MODE_CN else None
        target = {"walk": "roller", "roller": "walk"}.get(cur)
        mode_why = block or (None if target else "读不到现在是走路还是轮滑（robot.policies 读不到）")
        drive_mode = {"ok": mode_why is None, "why": mode_why, "current": cur, "target": target,
                      "does": f"按住 3 秒：切到{DRIVE_MODE_CN[target]}" if target else "按住 3 秒：走路 ⇄ 轮滑"}
        # Skills
        need_drive = None
        if block:
            need_drive = block
        elif pose not in DRIVING:
            need_drive = "要「准备好走」（策略在跑）才能做：先点「开始走」" if pose == "holding" else \
                f"现在{POSTURE_CN.get(pose, pose)}：先站起来、点「开始走」"
        elif sitting is None:
            need_drive = NO_SIT_INFO
        elif sitting:
            need_drive = "坐着：先站起来"
        elif homed is False:
            need_drive = "它还在回站姿，等一秒"
        skills = []
        for name in [n for n in (known or []) if n != "sit_toggle"]:
            why = self._skill_why(name, need_drive, known, pol)
            skills.append({"name": name, "label": C.SKILL_CN.get(name, name), "ok": why is None, "why": why})
        skills_why = None if known is not None else "读不到这只鸭子有哪些技能（robot.policies 只在运动模式下问）"
        # Sounds (quacking doesn't move joints, so it works after relax too: main.rs:4300-4307)
        sounds = [{"tag": t, "label": lab, "ok": base is None, "why": base} for t, lab in C.SOUNDS.items()]
        # Actions, combo actions
        attached, _ = self._pad_attached(now)
        held_mouth = any({"lt", "rt"} & set(st["held"]) for st in self._keys.values() if not st.get("end"))
        head_mode = any(m["mode"] == "head" for m in self._modes.values()) or bool((self._latch["head"] or {}).get("nonzero"))
        limp = pose == "limp" or relaxed(bus) is True

        def combo_row(c, builtin):
            why = None
            if C.needs_policy(c["steps"]):
                why = need_drive
            if why is None and attached:
                why = "实体手柄连着：它每一拍都发一次嘴和速度，会盖掉动作。先把手柄关掉"
            if why is None:
                why = base or relax
            if why is None:
                for s in c["steps"]:
                    if s["do"] == "skill":
                        why = self._skill_why(s["name"], need_drive, known, pol)
                        if why:
                            break
            if why is None and held_mouth and any(C.mouth_at(s, 0.0) is not None for s in c["steps"]):
                why = "正在按着 LT / RT 张嘴：先松开"
            if why is None and head_mode and any(C.head_at(s, 0.0) is not None for s in c["steps"]):
                why = "头模式开着、摇杆在管头：先按 Y 回到走路"
            text = C.describe(c["steps"])
            if why is None and limp and not C.needs_policy(c["steps"]):
                text += "（软着：嘴不会动，站好了才动）"
            return {"id": c["id"], "name": c["name"], "builtin": builtin, "text": text,
                    "seconds": round(C.duration(c["steps"]), 1), "ok": why is None, "why": why}

        actions = [combo_row(c, True) for c in C.ACTIONS]
        combos = [combo_row(c, True) for c in C.BUILTIN_COMBOS] + [combo_row(c, False) for c in self._user_combos]
        a = self._action
        running = None if a is None else {"id": a["id"], "name": a["name"], "by": a["by"], "step": a["step"],
                                          "steps": len(a["steps"]), "elapsed_s": round(now - a["started"], 1)}
        # LT / RT: mouth follows the fork's rules (round 3 V10) —— pressable as long as the main program is in motion mode; when limp or just relaxed, sound only
        trig_why = base
        if trig_why is None and a is not None and any(C.mouth_at(s, 0.0) is not None for s in a["steps"]):
            trig_why = f"正在做「{a['name']}」（也在动嘴）：等它做完"
        triggers = {"ok": trig_why is None, "why": trig_why, "mouth_pct": self._inputs["mouth"],
                    "note": "软着：只有声音，嘴不会动（站好了才动嘴）" if trig_why is None and (limp or relax) else None}
        last = None
        if self._last_cmd is not None and now - self._last_cmd["at"] < 15:
            last = {k: v for k, v in self._last_cmd.items() if k != "at"}
            last["age_s"] = round(now - self._last_cmd["at"], 1)
        last_action = None
        if self._last_action is not None and now - self._last_action["at"] < 15:
            last_action = {k: v for k, v in self._last_action.items() if k != "at"}
        buttons = {"stand": stand, "walk": walk, "sit": sit}
        return {"posture": pose, "posture_cn": POSTURE_CN.get(pose, pose), "block": block, "sitting": sitting,
                "buttons": buttons, "start": start, "reboot": reboot, "drive_mode": drive_mode,
                "keys": self._key_rows(buttons, sitting, skills, skills_why, known, need_drive, pol),
                "triggers": triggers, "driving": pose in DRIVING,
                "skills": skills, "skills_why": skills_why,
                "sounds": sounds, "actions": actions, "combos": combos, "running": running, "last": last,
                "last_action": last_action, "busy": self._cmd_busy}

    # ================= Stand up / start walking / sit down / skills / sounds: pressing =================

    def _call(self, what, method, params, by, ctx=None, posture_target=None, ordered=False, verify=None):
        if posture_target is None:
            return self._call_rpc(what, method, params, by, ctx, verify=verify)
        motion = self.motion_studio
        with (nullcontext() if ordered else self._send_lk):
            with self._lk:
                if not motion.request_current():
                    raise Refused("动作会话已经改变，旧命令请求已丢弃")
                recording = motion.session and motion.state == "recording"
                # Old robotd/manual fixtures without state evidence retain their
                # original control path. Automation always requires complete data.
                legacy = (not recording and not ordered and not motion.posture.pending
                          and "state" not in (self._robot or {}))
                if recording:
                    motion._boundary(record=True)
                    motion._refresh_request()
            if legacy:
                return self._call_rpc(what, method, params, by, ctx)
            if recording:
                motion._flush_outputs()
            with self._lk:
                if recording and (not motion.session or motion.session.get("invalid")):
                    raise Refused("动作会话已经结束，坐站请求已取消")
                token = motion.begin_posture(posture_target, manual=not recording and not ordered)
                origin = motion.recording_origin()
            if not token["command"]:
                with self._lk:
                    motion.posture.accepted(token, self.clock())
                return {"accepted": True, "reason": "已经达到目标姿态"}
            return self._call_rpc(what, method, params, by, ctx, posture_token=token, record_origin=origin)

    def _call_rpc(self, what, method, params, by, ctx=None, posture_token=None, record_origin=None,
                  verify=None):
        """A request that needs a reply: log "sent → ack · duration" (log_cmd, category "命令" (command)), and translate the rejection reason into plain language and raise Refused.

        verify: check the real state once more after the ack; if it returns a reason, log as failure and raise Refused. Used for things like "start walking" where
        the ack is accepted but the main program may not really start the command (see _verify_policy_started), so we don't falsely write "success".
        """
        if self.robot is None:
            raise Refused("这只鸭子没配主程序的地址")
        if self._update_blocked() and not neutral_robot_command(method,params):
            raise Refused('软件 / 主程序更新保护仍在，旧动作请求已取消')
        with self._lk:
            if not self.motion_studio.request_current():
                raise Refused("动作会话已经改变，旧命令请求已丢弃")
        if method == "robot.sound":
            record_origin = self.motion_studio.recording_origin()
        skill_fence = self.motion_studio.note_skill() if method == "robot.do" and posture_token is None else None
        with log_cmd(self.log, what, method, who=by, args=params or None, ctx=ctx) as t:
            try:
                r = self.robot.call(method, params, CMD_TIMEOUT_S)
            except Unreachable as e:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, None, reason="连接中断")
                t.fail(f"没发出去：{e}", hint="主程序 robotd 不在？看总览页")
                raise Refused(f"没发出去：{e}") from None
            except Timeout:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, None, reason="回执超时")
                t.fail(f"主程序 {CMD_TIMEOUT_S:g} 秒没回话", hint="它可能卡住了：看日志里 robotd 那几行，必要时卸力")
                raise Refused(f"主程序 {CMD_TIMEOUT_S:g} 秒没回话：它可能卡住了") from None
            except RpcError as e:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, False)
                why = plain_refusal(e.message)
                t.fail(f"主程序报错：{e.message}", raw={"code": e.code, "message": e.message}, hint=why)
                raise Refused(why) from None
            if isinstance(r, dict) and r.get("accepted") is False:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, False)
                self.motion_studio.rejected_skill(skill_fence)
                why = plain_refusal(r.get("reason"))
                t.fail(f"主程序没接受：{r.get('reason')}", raw=r, hint=why)
                raise Refused(why)
            if verify is not None:
                why = verify()
                if why:
                    t.fail(f"主程序收下了，但没真的执行：{why}", raw=r, hint=why)
                    raise Refused(why)
            if posture_token:
                if not isinstance(r, dict) or r.get("accepted") is not True:
                    self.motion_studio.posture_reply(posture_token, None, reason="回执格式不明确")
                    raise Refused(self.motion_studio.posture.error)
                self.motion_studio.posture_reply(posture_token, True, origin=record_origin)
            t.ok(r, note=(r.get("reason") or "") if isinstance(r, dict) else "")
        if method == "robot.sound":
            self.motion_studio.accepted_from(record_origin, method, params)
        return r

    @staticmethod
    def _policy_refusal(bus):
        """The reason robotd gives when it didn't start the policy: busStatus's last_enable_refusal / home_start_guard.reason."""
        if not isinstance(bus, dict):
            return None
        why = bus.get("last_enable_refusal")
        if isinstance(why, str) and why:
            return why
        guard = bus.get("home_start_guard")
        if isinstance(guard, dict):
            why = guard.get("reason")
            if isinstance(why, str) and why:
                return why
        return None

    def _verify_policy_started(self):
        """robot.enable only accepts the request (fork robotd: "the policy starts when it is ready"); the real start happens in
        the control loop, and is rejected by home_start_guard if stance / IMU isn't stable (不能进入保持：… (can't enter hold: …)). So read back
        busStatus and only count it as success when policy_enabled is seen; if it doesn't come, return the main program's original message to the page.

        Wait by count, not by the injected clock: even if the clock stops (tests, or some other problem) it won't hang here.
        """
        step = max(0.01, float(self.w.get("walk_verify_poll", WALK_VERIFY_POLL_S)))
        span = max(step, float(self.w.get("walk_verify", WALK_VERIFY_S)))
        bus = None
        for _ in range(int(span / step) + 1):
            try:
                r = self.robot.call("robot.busStatus", {}, CMD_TIMEOUT_S)
            except (Unreachable, Timeout):
                r = None
            if isinstance(r, dict):
                bus = r
                if r.get("policy_enabled") is True:
                    return None
            self._cancel_wait(step)
        return self._policy_refusal(bus) or "主程序没把走路策略开起来（可能还在回中或者没扶正）"

    def _motion_cmd(self, op, args, conn, by, label=None):  # noqa: C901
        """One-shot command: doesn't take the wheel (review 2 I1). Can't be clicked while someone else is pushing the sticks (except stop and quack); only one is sent at a time
        (except stop and quack: sound doesn't move joints and doesn't take the "previous one hasn't replied yet" slot, round 3 V15). label: what was pressed on the web gamepad diagram; the log says "网页手柄 A → …" (web gamepad A → …)."""
        now = self.clock()
        what = {"stand": "站起来", "walk": "开始走", "walk_stop": "停下（站好）", "sit": "坐下"}.get(op)
        urgent = op == "walk_stop"
        exclusive = op not in ("walk_stop", "sound")
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "动作会话已经改变，旧命令请求已丢弃"}
            if self._cmd_busy and exclusive:
                raise Refused("上一个指令还没回话，等一下")
            mv = self._motion_view(now)
            if op == "skill":
                name = args.get("name")
                row = next((s for s in mv["skills"] if s["name"] == name), None)
                if row is None:
                    raise Refused(mv["skills_why"] or f"这只鸭子没有「{C.SKILL_CN.get(name, name)}」")
                what = f"技能：{row['label']}"
                ok, why = row["ok"], row["why"]
            elif op == "sound":
                tag = args.get("tag")
                row = next((s for s in mv["sounds"] if s["tag"] == tag), None)
                if row is None:
                    raise Refused(f"不认识的声音：{tag}")
                what = f"叫一声：{row['label']}"
                ok, why = row["ok"], row["why"]
            else:
                btn = next((x for x in mv["buttons"].values() if x["op"] == op), None)
                if btn is None:
                    pose = mv["posture_cn"]
                    msg = {"walk": "已经「准备好走」了：推摇杆就走" if mv["posture"] in DRIVING else f"现在{pose}，「开始走」用不了",
                           "walk_stop": f"现在{pose}，没在走"}.get(op, "现在不能按这个")
                    self._last_cmd = {"what": label or what, "by": by, "ok": False, "reason": msg, "at": now}
                    raise Refused(msg)
                ok, why = btn["ok"], btn["why"]
            what = label or what
            if ok and op not in ("sound", "walk_stop"):
                held = self._lease_holder(now)
                if held is not None and held["conn"] != conn:
                    ok, why = False, f"{held['by'] or '另一个页面'}正在推摇杆：等它松手，或者点「接管」"
            if not ok:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": why, "at": now}
                raise Refused(why)
            if exclusive:
                self._cmd_busy = True
            pose = mv["posture"]
            stand_call = mv["buttons"]["stand"]["call"]
        try:
            ctx = {"posture": pose}
            if op == "stand":
                if stand_call == "robot.init":
                    r = self._call(what, "robot.init", {}, by, ctx)
                else:
                    r = self._call(what + "（坐着：sit_toggle）", "robot.do", {"skill": "sit_toggle"}, by, ctx, posture_target="stand")
            elif op == "walk":
                # An accepted ack doesn't mean the policy really started: read back busStatus within the same log entry to confirm,
                # and if it didn't start, report the main program's real reason (no more writing "success")
                r = self._call(what, "robot.enable", {"on": True, "toggle": False}, by, ctx,
                               verify=self._verify_policy_started)
            elif op == "walk_stop":
                with self._lk:
                    d = self._driver
                self._halt("点了停下", d["conn"] if d else None, clear_all=True)   # round 3 V1 item 7: clear head / body whoever set them
                self._call("停下：先把速度清零", "robot.stop", {}, by, ctx)
                # While walking, first wait for velocity to reach zero (at most 1 second), then return to stance (review-impl-plan I2, "walking" row).
                # Wait by count, not by the injected clock: even if the clock stops (tests, or some other problem) it won't hang here
                for _ in range(int(WALK_STOP_WAIT_S / 0.05)):
                    applied = (self._robot or {}).get("applied")
                    if not (isinstance(applied, list) and any(abs(v) > 0.01 for v in applied if isinstance(v, (int, float)))):
                        break
                    self._cancel_wait(0.05)
                r = self._call(what, "robot.enable", {"on": False, "toggle": False}, by, ctx)
            elif op == "sit":
                r = self._call(what, "robot.do", {"skill": "sit_toggle"}, by, ctx, posture_target="sit")
            elif op == "skill":
                r = self._call(what, "robot.do", {"skill": args.get("name")}, by, ctx)
            else:
                r = self._call(what, "robot.sound", {"tag": args.get("tag")}, by, ctx)
        except Refused as e:
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": str(e), "at": self.clock()}
            raise
        finally:
            if exclusive:
                with self._lk:
                    self._cmd_busy = False
        note = r.get("reason") if isinstance(r, dict) else None
        with self._lk:
            self._last_cmd = {"what": what, "by": by, "ok": True, "reason": note, "at": self.clock()}
        return {"accepted": True, "reason": note, "did": op}

    # ================= Actions, combo actions (done while held, stop on release) =================

    def _find_combo(self, cid):
        for c in C.ACTIONS + C.BUILTIN_COMBOS + self._user_combos:
            if c["id"] == cid:
                return c
        return None

    def _action_start(self, args, conn, by):
        """press: the sequence number of this page press (code review C7). Later action_hold calls only renew it if they carry the same sequence number: a timer left over from the page's previous press
        (released and pressed again before the ack came back) can't renew this one."""
        cid = args.get("id")
        combo = self._find_combo(cid)
        if combo is None:
            raise Refused(f"不认识的动作：{cid}")
        press = self._seq({"seq": args.get("press")})
        now = self.clock()
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "动作会话已经改变，旧动作请求已丢弃"}
            a = self._action
            if a is not None:
                if a["conn"] == conn and a["id"] == cid:
                    a["hold"] = now
                    a["press"] = press
                    return {"running": cid}
                raise Refused(f"正在做「{a['name']}」（{a['by'] or '页面'}）：等它做完或者先松开")
            mv = self._motion_view(now)
            row = next((x for x in mv["actions"] + mv["combos"] if x["id"] == cid), None)
            if row is None or not row["ok"]:
                raise Refused((row or {}).get("why") or "现在做不了")
            self._take_lease(conn, by, now)          # connections that left the gamepad page can't get it (round 3 V5: no more loophole for action)
            a = {"id": cid, "name": combo["name"], "conn": conn, "by": by, "started": now, "hold": now, "press": press,
                 "stop": threading.Event(), "why": None, "step": 0, "steps": list(combo["steps"]),
                 "motion_epoch": self.motion_studio.epoch}
            self._action = a
        self.log.info(f"开始做动作「{combo['name']}」（{by or '页面'}）", cat="手柄", raw=C.describe(combo["steps"]), dedup=False)
        threading.Thread(target=self._run_action, args=(a,), name="pad-action", daemon=True).start()
        return {"started": cid, "seconds": round(C.duration(combo["steps"]), 1)}

    def _action_hold(self, conn, press=None):
        """The page says "still holding". If it carries a sequence number different from the one at the start of this action: it's left over from the previous press, don't renew (code review C7)."""
        press = self._seq({"seq": press})
        with self._lk:
            a = self._action
            if (a is not None and a["conn"] == conn and conn not in self._gone
                    and (press is None or a.get("press") is None or press == a["press"])):
                a["hold"] = self.clock()
                self._touch_lease(conn, a["hold"])
                return {"running": a["id"]}
        return {"running": None}

    def _action_stop(self, conn, why="松开了"):
        with self._lk:
            a = self._action
            if a is None or (conn is not None and a["conn"] != conn):
                return {}
            a["why"] = a["why"] or why
            a["stop"].set()
        return {}

    def _abort_reason(self, a, needs_policy):
        now = self.clock()
        with self._lk:
            if a["stop"].is_set():
                return a["why"] or "停了"
            if now - a["hold"] > HOLD_S:
                return f"页面 {HOLD_S:g} 秒没说「还按着」（松手、切页或断网）"
            if self._relax_at >= a["started"]:
                return "卸力了"
            r = self._robot or {}
            if r.get("estop_active"):
                return "卸力了"
            if needs_policy and relaxed(r.get("bus")) is True:     # mouth-only ones (round 3 V10) still run when limp: robotd itself doesn't move
                return "扭矩关了（软了）"
            if self._pad_attached(now)[0]:
                return "实体手柄连上了"
            d = self._driver
            if d is None or d["conn"] != a["conn"]:
                return "被别的页面接管了"
            base = self._base_block(now)
            if base:
                return base
            if needs_policy and self._posture() not in DRIVING:
                return "策略停了"
        return None

    def _notify_output(self, method, params):
        if self._update_blocked() and not neutral_robot_command(method,params):return False
        if method == "robot.do":
            self.motion_studio.note_skill()
        self.robot.notify(method, params)
        self.motion_studio.accepted(method, params)
        return True

    def _notify_quiet(self, method, params, action=None, cleanup=False):
        with self._send_lk:
            with self._lk:
                if action is not None and (self._action is not action
                        or action.get("motion_epoch") != self.motion_studio.epoch
                        or (action["stop"].is_set() and not cleanup)):
                    return False
            return self._notify_output(method, params)

    def _run_action(self, a):  # noqa: C901
        steps, needs = a["steps"], C.needs_policy(a["steps"])
        moves_head = any(C.head_at(s, 0.0) is not None for s in steps)
        moves_mouth = any(C.mouth_at(s, 0.0) is not None for s in steps)
        result, level = "做完了", "info"
        try:
            if self.robot is None:
                raise _Abort("这只鸭子没配主程序的地址")
            for i, step in enumerate(steps):
                with self._lk:
                    a["step"] = i
                why = self._abort_reason(a, needs)
                if why:
                    raise _Abort(why)
                if step["do"] == "sound":
                    self._call(f"动作「{a['name']}」：叫一声", "robot.sound", {"tag": step["tag"]}, a["by"])
                elif step["do"] == "skill":
                    with self._lk:
                        mv = self._motion_view(self.clock())
                    row = next((s for s in mv["skills"] if s["name"] == step["name"]), None)
                    why = (row or {}).get("why") if row else f"这只鸭子没有「{C.SKILL_CN.get(step['name'], step['name'])}」"
                    if why:
                        raise _Abort(why)
                    if self._abort_reason(a, needs):     # a relax may happen between checking and sending: check once more before sending
                        raise _Abort(self._abort_reason(a, needs))
                    self._call(f"动作「{a['name']}」：{C.SKILL_CN.get(step['name'], step['name'])}", "robot.do",
                               {"skill": step["name"]}, a["by"])
                t0 = self.clock()
                dur = C.step_seconds(step)
                while True:
                    why = self._abort_reason(a, needs)
                    if why:
                        raise _Abort(why)
                    t = self.clock() - t0
                    if t >= dur:
                        break
                    h, m = C.head_at(step, t), C.mouth_at(step, t)
                    if h is not None:
                        self._notify_quiet("robot.head", dict(zip(("neck_pitch", "head_pitch", "head_yaw", "head_roll"), h)), action=a)
                    if m is not None:
                        self._notify_quiet("robot.mouth", {"open": m}, action=a)
                    a["stop"].wait(C.TICK_S)
        except _Abort as e:
            result, level = f"停了：{e}", "info"
        except Refused as e:
            result, level = f"没做完：{e}", "warn"
        except (Unreachable, Timeout) as e:
            result, level = f"没做完：发不出去（{e}）", "warn"
        except Exception as e:  # noqa: BLE001 —— shouldn't happen; if it does, still re-center, close the mouth, and explain clearly
            result, level = f"Studio 出错：{type(e).__name__}: {e}", "error"
            self.log.error(f"动作「{a['name']}」出错", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="这是 Studio 的问题，导出诊断包发出来")
        finally:
            # Head targets don't expire and the mouth has no timestamp: without re-centering and closing, they'd stay forever (pad_combo.py file header).
            # If this action has any head / mouth steps, send both once (regardless of which step it reached); after an interruption, no more robot.do / robot.sound
            for used, method, params in ((moves_head, "robot.head", {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}),
                                         (moves_mouth, "robot.mouth", {"open": 0.0})):
                if used and self.robot is not None:
                    try:
                        self._notify_quiet(method, params, action=a, cleanup=True)
                    except (Unreachable, Timeout) as e:
                        self.log.warn("动作结束时没能回正 / 合嘴", cat="手柄", step=method, raw=str(e),
                                      hint="头可能还歪着、嘴可能还张着：再按一次那个动作，或者让它坐下再站起来")
            with self._lk:
                if self._action is a:
                    self._action = None
                self._last_action = {"id": a["id"], "name": a["name"], "by": a["by"], "result": result,
                                     "ok": result == "做完了", "at": self.clock()}
            cat = "安全" if ("卸力" in result or "没说" in result or "软了" in result) else "手柄"
            self.log.write(f"动作「{a['name']}」{result}", cat=cat, level=level, step=f"第 {a['step'] + 1}/{len(steps)} 步",
                           dedup=False)

    # ================= User-made combo actions: save, delete (editing UI comes next round) =================

    def _combo_save(self, args):
        builtin = {c["id"] for c in C.ACTIONS + C.BUILTIN_COMBOS}
        combo = C.clean_combo(args.get("combo"), builtin)
        with self._lk:
            others = [c for c in self._user_combos if c["id"] != combo["id"]]
            if len(others) >= C.MAX_USER_COMBOS:
                raise Refused(f"最多存 {C.MAX_USER_COMBOS} 个，先删掉几个")
            new = others + [combo]
        path = C.save_user_combos(self.state_dir, new)
        with self._lk:
            self._user_combos = new
        self.log.info(f"存了组合动作「{combo['name']}」", cat="手柄", step=path, raw=C.describe(combo["steps"]))
        return {"saved": combo["id"]}

    def _combo_delete(self, args):
        cid = args.get("id")
        with self._lk:
            if not any(c["id"] == cid for c in self._user_combos):
                raise Refused("没有这个自己编的组合动作（内置的删不了）")
            new = [c for c in self._user_combos if c["id"] != cid]
        C.save_user_combos(self.state_dir, new)
        with self._lk:
            self._user_combos = new
        self.log.info(f"删了组合动作 {cid}", cat="手柄")
        return {"deleted": cid}
