"""The gamepad page's "actions" and "combo actions": data, validation, storage, and expansion into a timeline. Everything here is a pure function and doesn't touch robotd.

A combo action = a name + several steps, done one after another (the next step waits for the previous to finish). Each step is one of the kinds below, with parameters clamped to safe ranges:

| Step             | Sent to robotd                                     | Source (official repo microduck/) |
|------------------|---------------------------------------------------|-----------------------------|
| nod   nod        | robot.head notification, head_pitch back and forth, 25 Hz | duck-ipc-proto lib.rs:533, 2058-2065; robotd main.rs:3637-3640 |
| shake shake head | robot.head notification, head_yaw back and forth   | same as above |
| tilt  tilt head  | robot.head notification, head_roll, hold a moment, then re-center | same as above |
| mouth open mouth | robot.mouth notification {open}, hold a moment, then close | lib.rs:589, 2269-2275; main.rs:3648-3651 |
| chatter talk     | robot.mouth open and close repeatedly              | same as above |
| sound quack      | robot.sound request {tag} (has a reply: rejected if there's no sound) | lib.rs:590-600, 2094-2140; main.rs:4300-4319 |
| skill official skill | robot.do request {skill} (has a reply)         | lib.rs:579-581, 2212-2239; main.rs:4219-4255 |
| wait  pause      | sends nothing                                      | — |

No "walk": combo actions don't include robot.move. "Walk only while held" is guaranteed by the sticks alone; holding a combo action only ever does in-place actions.
No sit_toggle: it changes posture (sit down / stand up); use the dedicated "坐下" (Sit down) button.

A few facts about the head and mouth (which mean the end must always "re-center, close mouth"):
- robot.head targets don't expire: the last value sent stays (robotd intents.rs:569-588 only ages twist);
  the default is all zeros (intents.rs:271-274), so "re-center" = send all zeros once.
- robot.mouth has no timestamp: if the client dies the mouth stays open (intents.rs:144-146 verbatim: "a mouth left open by a dead client
  is exactly what the prototype does"), so an interruption midway must also send open=0.
- Head commands go into the policy's observation and don't write servos directly (lib.rs:2053-2057; padd main.rs:170-174 "the network itself decides how
  far the head actually goes"), so head-moving steps require "policy running". In the official version the mouth only moves while the policy is running (robotd main.rs:3093-3099);
  the fork on our duck (R17) moves it as long as it's set up standing (including holding and sitting) (fork robotd main.rs:3897-3909, 4779-4787), and the physical gamepad also sends mouth every tick
  regardless of mode and policy (fork padd:1351-1363). Round 3 (pad-vpad-plan §8 V10) switched to the fork's behavior: mouth-only steps (open mouth, talk) don't require the policy running;
  when limp robotd doesn't move the mouth by itself; the end still closes the mouth.
- Amplitudes and speeds are guesses, not tried on the robot: nod 0.5 rad, shake 0.6 rad, tilt 0.4 rad; to be tuned while watching the duck.
"""
import json
import math
import os
import re
import tempfile

TICK_S = 0.04                 # head and mouth notifications at 25 Hz (padd is 50 Hz: padd main.rs:150-151)
NOD_AMP, SHAKE_AMP, TILT_AMP = 0.5, 0.6, 0.4     # rad, guesses, to be checked on the robot
NOD_PERIOD_S, SHAKE_PERIOD_S = 0.7, 0.8
CHATTER_PERIOD_S = 0.32
MAX_STEPS = 12
MAX_TOTAL_S = 20.0
MAX_USER_COMBOS = 20
NAME_MAX = 16
COMBO_FILE = "pad-combos.json"

# robot.sound tags (lib.rs:2094-2113). wheee has to be sent continuously while held (hold), so it isn't made into a one-shot button
SOUNDS = {
    "chirp": "嘎（叫一声）",
    "greet": "打招呼",
    "inquire": "疑问",
    "coo": "咕咕（撒娇）",
    "alarm": "大叫",
    "peck": "告别",
}

# robot.do skill names → Chinese. Which ones robotd actually has: see skills in robot.policies (lib.rs:2338-2346);
# ground_pick and sit_toggle aren't in skills; check whether the sitstand / ground_pick slots are installed (robotd main.rs:4136-4156)
SKILL_CN = {
    "ground_pick": "低头捡",
    "roulade": "前滚翻",
    "kick_left": "左脚踢",
    "kick_right": "右脚踢",
    "roller_stand": "轮滑起身",
    "sit_toggle": "坐下 ↔ 站起",
}
# How long a skill takes (the next step in a combo waits for it): default duration in robotd-params lib.rs:1311-1341 (kick 0.5 s, roll 1 s),
# pick-up-from-ground is a phase action with a 2.8 s window (from the original training recipe notes); unknown ones wait 2 seconds
SKILL_HOLD_S = {"kick_left": 0.8, "kick_right": 0.8, "roulade": 1.3, "ground_pick": 3.0}
SKILL_HOLD_DEFAULT_S = 2.0
NO_COMBO_SKILLS = {"sit_toggle"}
SKILL_RE = re.compile(r"^[a-z0-9_]{1,32}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")

STEP_CN = {"nod": "点头", "shake": "摇头", "tilt": "歪头", "mouth": "张嘴", "chatter": "说话（嘴一张一合）",
           "sound": "叫一声", "skill": "技能", "wait": "停一下"}
# Steps that only work with "policy running" (see the file header). Open mouth and talk (mouth only) don't need it, per the fork's rules (round 3 V10)
NEEDS_POLICY = {"nod", "shake", "tilt", "skill"}


class Refused(Exception):
    """This operation can't be done right now. The reason goes straight to the page (shared by pad.py and pad_drive.py)."""


# ---------------- Built-in ----------------

# Single actions (on the page, done once while held, stops on release)
ACTIONS = [
    {"id": "nod", "name": "点头", "steps": [{"do": "nod", "times": 2}]},
    {"id": "shake", "name": "摇头", "steps": [{"do": "shake", "times": 2}]},
    {"id": "tilt", "name": "歪头", "steps": [{"do": "tilt", "side": "right", "ms": 1200}]},
    {"id": "mouth", "name": "张嘴", "steps": [{"do": "mouth", "open": 0.9, "ms": 900}]},
]
# Combo actions (these built-in ones for now; user-made ones are stored in pad-combos.json in the state directory, the editing UI comes next round)
BUILTIN_COMBOS = [
    {"id": "hello", "name": "打招呼", "steps": [{"do": "sound", "tag": "greet"}, {"do": "nod", "times": 2},
                                              {"do": "mouth", "open": 0.8, "ms": 500}]},
    {"id": "happy", "name": "开心", "steps": [{"do": "sound", "tag": "chirp"}, {"do": "chatter", "times": 3},
                                            {"do": "nod", "times": 1}]},
    {"id": "ask", "name": "疑问", "steps": [{"do": "sound", "tag": "inquire"}, {"do": "tilt", "side": "right", "ms": 1000}]},
    {"id": "no", "name": "不要", "steps": [{"do": "shake", "times": 3}, {"do": "sound", "tag": "coo"}]},
    {"id": "kicks", "name": "左右各踢一脚", "steps": [{"do": "skill", "name": "kick_left"}, {"do": "wait", "ms": 600},
                                                 {"do": "skill", "name": "kick_right"}]},
]


# ---------------- Validation ----------------

def _num(v, lo, hi, default, what):
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise Refused(f"{what}要是数字")
    return max(lo, min(hi, v))


def clean_step(raw):
    """One step → a clean step (unknown fields dropped, numbers clamped to range). Raises Refused if invalid."""
    if not isinstance(raw, dict):
        raise Refused("每一步要是 {\"do\": …} 这样的对象")
    do = raw.get("do")
    if do == "nod" or do == "shake":
        return {"do": do, "times": int(_num(raw.get("times"), 1, 4, 2, "次数"))}
    if do == "tilt":
        side = raw.get("side", "right")
        if side not in ("left", "right"):
            raise Refused("歪头只能 left / right")
        return {"do": "tilt", "side": side, "ms": int(_num(raw.get("ms"), 300, 2000, 1000, "歪头的时间"))}
    if do == "mouth":
        return {"do": "mouth", "open": round(_num(raw.get("open"), 0.1, 1.0, 0.8, "张嘴的大小"), 2),
                "ms": int(_num(raw.get("ms"), 100, 2000, 600, "张嘴的时间"))}
    if do == "chatter":
        return {"do": "chatter", "times": int(_num(raw.get("times"), 1, 6, 3, "次数"))}
    if do == "sound":
        tag = raw.get("tag")
        if tag not in SOUNDS:
            raise Refused(f"不认识的声音：{tag}（只有 {'、'.join(SOUNDS)}）")
        return {"do": "sound", "tag": tag}
    if do == "skill":
        name = raw.get("name")
        if not isinstance(name, str) or not SKILL_RE.match(name):
            raise Refused("技能名只能是小写字母、数字、下划线")
        if name in NO_COMBO_SKILLS:
            raise Refused("坐下 / 站起会改变姿势，不能放进组合动作：用「坐下」按钮")
        return {"do": "skill", "name": name}
    if do == "wait":
        return {"do": "wait", "ms": int(_num(raw.get("ms"), 0, 3000, 300, "停的时间"))}
    raise Refused(f"不认识的一步：{do}（只能是 {'、'.join(STEP_CN)}）")


def clean_combo(raw, builtin_ids=()):
    """A combo action the page wants to save → a clean one. Name, step count, and total duration are all capped; the id must not collide with a built-in one."""
    if not isinstance(raw, dict):
        raise Refused("组合动作要是对象")
    cid = raw.get("id")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise Refused("编号只能是小写字母、数字、- 和 _（最多 24 个）")
    if cid in builtin_ids:
        raise Refused(f"「{cid}」是内置的，换个编号")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise Refused("要起个名字")
    name = name.strip()[:NAME_MAX]
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise Refused("至少要有一步")
    if len(steps) > MAX_STEPS:
        raise Refused(f"最多 {MAX_STEPS} 步")
    clean = [clean_step(s) for s in steps]
    total = duration(clean)
    if total > MAX_TOTAL_S:
        raise Refused(f"太长了：大约 {total:.0f} 秒，最多 {MAX_TOTAL_S:.0f} 秒")
    return {"id": cid, "name": name, "steps": clean}


# ---------------- Expansion into a timeline ----------------

def step_seconds(step):
    do = step["do"]
    if do == "nod":
        return step["times"] * NOD_PERIOD_S
    if do == "shake":
        return step["times"] * SHAKE_PERIOD_S
    if do in ("tilt", "mouth", "wait"):
        return step["ms"] / 1000
    if do == "chatter":
        return step["times"] * CHATTER_PERIOD_S
    if do == "sound":
        return 0.25            # the sound plays by itself; pause briefly before the next step so it sounds like quack first, then move
    if do == "skill":
        return SKILL_HOLD_S.get(step["name"], SKILL_HOLD_DEFAULT_S)
    return 0.0


def duration(steps):
    return sum(step_seconds(s) for s in steps)


def head_at(step, t):
    """Where the head should be at second t of this step: (neck_pitch, head_pitch, head_yaw, head_roll); returns None for steps that don't involve the head."""
    do = step["do"]
    if do == "nod":
        return (0.0, NOD_AMP * math.sin(2 * math.pi * t / NOD_PERIOD_S), 0.0, 0.0)
    if do == "shake":
        return (0.0, 0.0, SHAKE_AMP * math.sin(2 * math.pi * t / SHAKE_PERIOD_S), 0.0)
    if do == "tilt":
        total = step["ms"] / 1000
        ramp = min(0.25, total / 3)
        k = min(1.0, t / ramp) if t < total - ramp else max(0.0, (total - t) / ramp)
        return (0.0, 0.0, 0.0, (TILT_AMP if step["side"] == "right" else -TILT_AMP) * k)
    return None


def mouth_at(step, t):
    """How wide the mouth is open at second t of this step (0..1); returns None for steps that don't involve the mouth."""
    do = step["do"]
    if do == "mouth":
        return step["open"] if t < step["ms"] / 1000 - TICK_S else 0.0
    if do == "chatter":
        return 0.85 if (t % CHATTER_PERIOD_S) < CHATTER_PERIOD_S / 2 else 0.05
    return None


def needs_policy(steps):
    return any(s["do"] in NEEDS_POLICY for s in steps)


def describe(steps):
    """A sentence for the page, e.g.: 点头 2 次 → 张嘴 → 叫一声（打招呼） (nod 2 times → open mouth → quack (greeting))"""
    out = []
    for s in steps:
        do = s["do"]
        if do in ("nod", "shake", "chatter"):
            out.append(f"{STEP_CN[do]} {s['times']} 次")
        elif do == "tilt":
            out.append("歪头" + ("（右）" if s["side"] == "right" else "（左）"))
        elif do == "mouth":
            out.append("张嘴")
        elif do == "sound":
            out.append(f"叫一声（{SOUNDS.get(s['tag'], s['tag'])}）")
        elif do == "skill":
            out.append(SKILL_CN.get(s["name"], s["name"]))
        elif do == "wait":
            out.append(f"停 {s['ms'] / 1000:g} 秒")
    return " → ".join(out)


# ---------------- Storage (pad-combos.json in the state directory) ----------------

def load_user_combos(state_dir, log=None):
    """Read the user's own combo actions. If the file is broken or an entry is invalid: skip that entry, log it, don't block the others."""
    if not state_dir:
        return []
    path = os.path.join(state_dir, COMBO_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        if log:
            log.warn("自己编的组合动作读不出来，先不用", cat="手柄", step=path, raw=f"{type(e).__name__}: {e}",
                     hint="文件坏了的话删掉它，重新编")
        return []
    builtin = {c["id"] for c in BUILTIN_COMBOS + ACTIONS}
    out = []
    for raw in (data.get("combos") if isinstance(data, dict) else None) or []:
        try:
            out.append(clean_combo(raw, builtin))
        except Refused as e:
            if log:
                log.warn("跳过一条不对的组合动作", cat="手柄", step=path, raw=f"{raw!r:.200}：{e}")
    return out[:MAX_USER_COMBOS]


def save_user_combos(state_dir, combos):
    """Write the whole thing back (write a temp file first, then rename, so a power loss halfway doesn't corrupt the old one)."""
    if not state_dir:
        raise Refused("这只鸭子没配 state 目录，存不了")
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, COMBO_FILE)
    fd, tmp = tempfile.mkstemp(prefix=".pad-combos-", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "combos": combos}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise Refused(f"存不进去：{type(e).__name__}: {e}") from None
    return path
