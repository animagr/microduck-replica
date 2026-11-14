"""Backend of the gamepad page: gamepad status, visual pairing, live button input, e-stop test; the "make the duck move" part is in pad_drive.py (PadOps inherits from it).

The four things that deal with the system are all passed in through the constructor and can all be swapped for fakes (tests/test_pad.py uses only fakes, so it runs on a computer without Bluetooth):

| Port      | Real                                   | Does what |
|-----------|----------------------------------------|--------|
| configd   | ConfigdPort (unix:/run/configd.sock)   | pad.status reads status; pad.pair / pad.forget pair and forget (mutating, configd only accepts root and --allow-user, main.rs:112-131) |
| bluetooth | BluetoothCtl (bluetoothctl session)    | scan list (the official stack has no such API); fallback pairing when configd refuses |
| tap       | PaddTap (unix:/run/padd/pad.sock)      | padd tap pad.input: raw evdev buttons; only subscribed while someone is viewing the gamepad page (padd only opens the device when subscribed) |
| robot     | RobotPort (unix:/run/robotd.sock)      | robot.move / head / mouth (notifications); init / enable / do / sound / stop / busStatus (requests); pad.bindings |

robotd readback (torque, posture, how many times relax was pressed): fetched by app.py in the event loop with robot_view(robotd) and handed in via feed_robot()
(a 10 Hz small task in lifespan, whether or not a page is watching: review 13); this module doesn't read robotd's objects across threads.
The e-stop test separately asks robot.busStatus itself (new connection, recording "when it asked" itself: review 1).

Threads (like servo_ops): handle() runs in asyncio.to_thread. Scanning and pairing are slow, so they go into a background task thread and handle returns immediately,
with progress in snapshot() (fetched by the page at 10 Hz). Watcher thread: only alive while someone is viewing the gamepad page, a task is running, or the e-stop test is in progress; it polls pad.status
and toggles the tap; when none of those remain it exits by itself. The e-stop test and actions each have their own thread that exits when done.

Official facts (file:line) are all in scratchpad console/pad-page-plan.md; here they're only noted at key points.
"""
import codecs
import concurrent.futures
import json
import math
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import tomllib
from collections import deque

from . import helper as helper_api
from .estop import STARTING_PHASES, relaxed, torque_off
from .pad_combo import Refused
from .motion_studio import MotionStudio, _digest
from .pad_mapping import MappingClient, MappingError, PadMapping
from .pad_drive import (DRIVING, FAST_WORKERS, MAX_V, MAX_W, RELAX_CLEAR_DELAY_S, RELAX_GUARD_S,  # noqa: F401 —— MAX_V / MAX_W are imported elsewhere
                        DriveMixin, parse_speed_limits)
from .rpc import LINE_LIMIT, RpcError, Timeout, Unreachable, parse_addr
from .state import MAX_AGE
from .state import posture as _posture

SCAN_S, SCAN_MAX_S = 12, 30
PAIR_WINDOW_S = 20        # timeout_seconds for configd: with a MAC it stops as soon as it's seen (bluez.rs:593-628)
PAIR_CALL_MARGIN_S = 110  # configd worst case: window + 30 + 5 + 30 + 30 seconds (bluez.rs:212-223)
CONNECT_WAIT_S = 10
PADD_WAIT_S = 30          # on real hardware the kernel creates the input device about 15 seconds after pairing; double that as margin
PAD_PAIR_TIMEOUT_S = 60   # timeout for the helper running the official robotctl pad pair (10–120)
WATCH_LEASE_S = 6.0       # the page says "I'm watching" every 2 seconds; if it hasn't for 6 seconds, assume nobody is watching
KEYS_NEED = 4             # button test: 4 different buttons pressed and both sticks pushed counts as done
TEST_TORQUE_WAIT_S = 60
TEST_PRESS_WAIT_S = 90
TEST_READBACK_S = 6.0
SELECT_LONG_S = 1.5       # holding 1.5 seconds triggers a warning first
SHUTDOWN_HOLD_S = 2.0     # padd: holding Select for 2 seconds is sit down, relax, power off (robot.shutdown), not an e-stop (padd main.rs:192-193, 725-739)
TEST_PROBE_S = 0.25       # interval at which the e-stop test asks busStatus itself
BUS_FRESH_S = 3.0
STICK_ACTIVE = 0.15
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
WEIRD_BLE = "/var/lib/robot/weird-ble"     # on boards with this marker, the official robotctl stops btd and restarts the adapter before pairing (robotctl main.rs:2799-2945)
ROBOTD_TOML = "/etc/robot/robotd.toml"      # where padd reads [netpad] (robotd-params DEFAULT_PATH)
FINAL = ("idle", "passed", "failed")
_HELPER_OLD = object()      # old helper replies bad_verb: fall back to the backup path


class BtError(Exception):
    """Error on the Bluetooth side: code is a key in FAILS, raw is the original text."""

    def __init__(self, code, raw=""):
        super().__init__(raw or code)
        self.code, self.raw = code, raw


class NoPermission(Unreachable):
    """The socket exists, but Studio's user has no permission to connect (not "service missing": review 17)."""


# ---------------- Plain language: failure reason → explanation + what to do ----------------

NO_RESTART_BT = "不要 restart bluetooth：这块板会把蓝牙弄丢，要重启才回来（官方 pair-a-gamepad.md:142）"
ROBOT_GROUP = "把 Studio 的用户加进 robot 组：sudo usermod -aG robot <用户>，然后重启 Studio"
FAILS = {
    "no_adapter": ("鸭子的蓝牙还没准备好（找不到 hci0）",
                   f"刚开机 70 多秒内是正常的（这块板 hci0 大约开机 73 秒才出来），等一分钟再点「重试」。一直这样就重启鸭子。{NO_RESTART_BT}"),
    "rfkill": ("蓝牙被系统关掉了（rfkill）", "在鸭子上运行 sudo rfkill unblock bluetooth，再点「重试」"),
    "powered_off": ("鸭子的蓝牙关着", "点「重试」会再开一次；还不行就重启鸭子"),
    "bluez_down": ("鸭子上的蓝牙服务 bluetoothd 没在跑", f"重启鸭子。{NO_RESTART_BT}"),
    "configd_down": ("鸭子上的配置服务 configd 没在跑", "第一台鸭子平时关着它：在鸭子上运行 sudo systemctl start configd，再点「重试」"),
    "socket_perm": ("Studio 没权限连 configd（/run/configd.sock）", ROBOT_GROUP),
    "configd_busy": ("configd 上一次配对还没做完", "它停不了，最多一两分钟会自己结束：等页面上这句话消失再点"),
    "driving": ("鸭子在走 / 策略在跑", "搜索、配对会占蓝牙，正在用的手柄可能卡住不松、鸭子照旧走。先停下（点「停下（站好）」或手柄 Start），再搜索"),
    "no_btctl": ("鸭子上没有 bluetoothctl，列不出附近的设备", "点「直接配（自动挑）」，交给 configd 自己找"),
    "permission": ("Studio 没有配对的权限", "configd 只让 root 配手柄。现在先用 SSH 在鸭子上运行 sudo robotctl pad pair；以后装了「小助手」就能在网页上点"),
    "bt_permission": ("Studio 没有权限用蓝牙", "把 Studio 的用户加进 bluetooth 组，或者先用 SSH 在鸭子上运行 sudo robotctl pad pair"),
    "scan_failed": ("蓝牙搜索没启动", "可能别的程序正在搜索或配对；等几秒再点「重试」"),
    "not_found": ("没找到在配对状态的手柄", "手柄的灯要「快闪」（慢闪、常亮都不是配对状态）。照上面的方法进配对状态，进了以后马上点开始"),
    "not_found_pad": ("附近有蓝牙设备，但没有一个像手柄", "手柄的灯在快闪吗？如果列表里某一个就是你的手柄，点它旁边的「配这个」"),
    "ambiguous": ("同时有好几个手柄在配对状态", "只留一个在快闪；或者点「开始搜索」，在列表里点你要的那个"),
    "timeout": ("找到了手柄，但配对没做完", "手柄可能退出了配对状态：再按一下配对键，灯快闪时马上点「重试」"),
    "rejected": ("蓝牙拒绝了配对",
                 "多半是手柄已经退出配对状态：再按配对键、灯快闪时重试。每次都这样：看 /etc/bluetooth/main.conf 的 Privacy，"
                 "官方建议 Privacy = device（改完要重启鸭子）"),
    "auth_failed": ("手柄拒绝了配对（认证失败）",
                    "常见原因是手柄已经配给了别的设备：Xbox 手柄只记一个主机，先在电脑或手机上配一次再删掉；G50 这类只记最后配的那台。"
                    "然后让手柄重新进配对状态"),
    "pin": ("这个手柄要输 PIN 码，鸭子没法输", "把手柄切到 Switch 或 X-input 模式再试，或者换一个手柄"),
    "key_missing": ("两边存的钥匙对不上（PIN or Key Missing）",
                    "在「鸭子记着的手柄」里点「忘掉」，手柄重新进配对状态再配。还不行：官方说 Privacy = device 在有的板上会这样，先改回去、只暂停 btd 试"),
    "le_abort": ("连接被鸭子自己放弃了（le-connection-abort-by-local）", "官方说这通常是 /etc/bluetooth/main.conf 的 Privacy 不对，应为 Privacy = device，改完重启鸭子"),
    "dhkey": ("配对校验失败（DHKey check failed）", "官方说这是 Privacy 的另一种情况：试 Privacy = off，改完重启鸭子"),
    "not_bondable": ("鸭子的蓝牙「不可绑定」，钥匙存不下", "要 root：在鸭子上运行 sudo btmgmt bondable on，再点「重试」"),
    "agent": ("蓝牙配对代理没注册上", "多半是别的程序（配置服务、另一个 bluetoothctl）正占着。等一会儿再试；一直这样就重启鸭子"),
    "busy": ("另一个配对正在进行", "等它做完（最多一两分钟）再试"),
    "not_trusted": ("配上了，但没设成「信任」", "现在能用，重启鸭子以后不会自己回连：在「鸭子记着的手柄」里点「修复」"),
    "not_connected": ("配上了，但没连上", "按一下手柄的 Home / Xbox 键把它打开，它会自己连上"),
    "padd_down": ("手柄连上了，但 padd 没在跑", "padd 只在主程序 robotd 跑着时才起。先让主程序跑起来；还不行看日志里 padd 那几行"),
    "no_input": ("连上了，但 padd 没认到这个手柄（读不到按键）",
                 "先按 Home / Xbox 键唤醒手柄，网页会尝试恢复连接。仍读不到按键时检查手柄模式和日志；提示钥匙不匹配时再忘掉重配"),
    "wrong_input": ("padd 打开的是另一只手柄", "先断开另一只手柄，再唤醒这次选择的手柄；不会替你切断另一只正在用的手柄"),
    "no_robotctl": ("鸭子上没有官方 robotctl（/usr/local/bin/robotctl）",
                    "重装官方固件 / robotctl，确认它装着；或者在鸭子上运行 sudo robotctl pad pair。新版小助手靠它停 btd、重开蓝牙"),
    "weird_ble": ("这块板配新手柄前要先暂停 btd、重启一下蓝牙", "新版小助手会调官方 robotctl pad pair 做这件事。没有新版小助手就重装它，或者在鸭子上运行 sudo robotctl pad pair"),
    "cancelled": ("停下了", "要配的话点「从头来」"),
    "other": ("配对没成功", "看下面的原文；可以导出诊断包发群里"),
}

_CLASSIFY = [
    (r"org\.freedesktop\.DBus\.Error\.AccessDenied|Access denied", "bt_permission"),
    (r"Device [0-9A-Fa-f:]{17} not available", "not_found"),
    (r"ServiceUnknown|cannot reach bluetoothd|Waiting to connect to bluetoothd|org\.bluez was not provided", "bluez_down"),
    (r"No default controller|no Bluetooth adapter|Controller .* not available", "no_adapter"),
    (r"NotReady|not powered|Resource Not Ready", "powered_off"),
    (r"InProgress|In Progress|Operation already in progress|org\.bluez\.Error\.Busy", "busy"),
    (r"PIN or Key Missing|Key Missing", "key_missing"),
    (r"DHKey", "dhkey"),
    (r"le-connection-abort-by-local", "le_abort"),
    (r"cannot enter a PIN|cannot enter a passkey|Enter PIN code|Enter passkey|Confirm passkey|RequestPinCode", "pin"),
    (r"Authentication ?Failed|Authentication ?Rejected|Authentication ?Canceled", "auth_failed"),
    (r"AuthenticationTimeout|Page Timeout|page-timeout|ConnectionAttemptFailed|Host is down|did not finish pairing|timed out|Timeout", "timeout"),
    (r"No Bonding|not bondable", "not_bondable"),
    (r"Permission denied", "not_bondable"),     # 10-15: connecting HID without bonding, BlueZ returns Permission denied (13) (踩坑记录.md:272)
    (r"Failed to register agent|Agent is already registered|already registered", "agent"),
    (r"Failed to start discovery", "scan_failed"),
]


def classify(raw):
    """Original text from BlueZ / bluetoothctl / configd → a key in FAILS. Unrecognized is other."""
    text = str(raw or "")
    for pat, code in _CLASSIFY:
        if re.search(pat, text, re.I):
            return code
    return "other"


def explain(code, raw=None):
    msg, fix = FAILS.get(code, FAILS["other"])
    return {"code": code, "msg": msg, "fix": fix, "raw": (str(raw)[-600:] if raw else None)}


# ---------------- Recognizing gamepads: same rules as configd (configd/src/pad.rs:121-163) ----------------

def gamepad_evidence(name, icon=None, cls=None, appearance=None):
    """Returns "classified" (icon / device class / appearance says gamepad), "name" (only the name looks like one), or None (doesn't look like one)."""
    if icon == "input-gaming":
        return "classified"
    if isinstance(cls, int):
        if (cls >> 8) & 0x1F == 0x05 and ((cls >> 2) & 0x3F) & 0x0F in (0x01, 0x02):
            return "classified"
    if appearance == 0x03C4:
        return "classified"
    lower = (name or "").lower()
    if any(k in lower for k in ("controller", "gamepad", "joystick", "dualsense", "dualshock")):
        return "name"
    return None


def same_pad(a, b):
    """Two addresses with the same last three bytes = two faces of the same gamepad (Switch clones have both LE and classic, pad.rs:165-194)."""
    ta, tb = (a or "").upper().split(":")[-3:], (b or "").upper().split(":")[-3:]
    return len(ta) == 3 and ta == tb


def pad_kind(name, vendor=None):
    """xbox / ps / switch / generic: decides which shape the page draws and what the button names are."""
    n = (name or "").lower()
    if vendor == 0x045E or "xbox" in n:
        return "xbox"
    if vendor == 0x054C or any(k in n for k in ("dualsense", "dualshock", "playstation")) or n.strip() == "wireless controller":
        return "ps"
    if vendor == 0x057E or any(k in n for k in ("pro controller", "joy-con", "nintendo", "switch")):
        return "switch"
    return "generic"


KIND_LABEL = {"xbox": "Xbox", "ps": "PlayStation", "switch": "Switch Pro 类", "generic": ""}
ICON_CN = {"audio-headset": "耳机", "audio-headphones": "耳机", "audio-card": "音箱", "phone": "手机", "computer": "电脑",
           "input-keyboard": "键盘", "input-mouse": "鼠标", "input-tablet": "手写板", "video-display": "电视"}


# ---------------- Live buttons (the padd tap gives raw evdev, lib.rs:4205-4451) ----------------

BTN_ROLE = {0x130: "south", 0x131: "east", 0x133: "north", 0x134: "west", 0x136: "lb", 0x137: "rb",
            0x138: "lt", 0x139: "rt", 0x13A: "select", 0x13B: "start", 0x13C: "home", 0x13D: "l3", 0x13E: "r3",
            0x220: "du", 0x221: "dd", 0x222: "dl", 0x223: "dr", 158: "select", 172: "home"}
# Xbox (hid-generic over BLE, xpad over USB, the virtual 360 from the GameSir bridge): the button printed X reports BTN_X(0x133) and the one printed Y reports BTN_Y(0x134),
# which is the reverse of the "north / west" position definition; PS (hid-playstation) and Switch (hid-nintendo) report by position.
# **Speculation, not checked on the duck (E9)**: the page says "X / Y positions to be verified" for Xbox
XBOX_SWAP = {0x133: "west", 0x134: "north"}
XBOX_SWAP_VERIFIED = False
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_GAS, ABS_BRAKE, ABS_HAT0X, ABS_HAT0Y = 0, 1, 2, 3, 4, 5, 9, 10, 16, 17
EV_KEY, EV_ABS = 1, 3


class LiveInput:
    """Accumulate individual events into "what's pressed now, where the sticks are" using the device description from attached. When the gamepad is idle padd sends nothing,
    so the initial values must come from attached."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.device = None
        self.kind = None
        self.buttons = {}            # role -> bool
        self.other = {}              # buttons not in the table: name -> bool
        self.axes = {}               # role -> value (sticks -1..1, down / right positive; triggers 0..1)
        self.amap = {}               # evdev axis number -> (role, min, max)
        self.last_at = None
        self.activity_at = None      # last time someone was really moving it (button change, stick off center)
        self.seen = set()

    def _role(self, code):
        if self.kind == "xbox" and code in XBOX_SWAP:
            return XBOX_SWAP[code]
        return BTN_ROLE.get(code)

    def attach(self, device, now):
        self.reset()
        self.device = device if isinstance(device, dict) else {}
        self.kind = pad_kind(self.device.get("name"), self.device.get("vendor"))
        axes = {a.get("code"): a for a in self.device.get("axes") or [] if isinstance(a, dict)}
        amap = {ABS_X: "lx", ABS_Y: "ly", ABS_HAT0X: "hatx", ABS_HAT0Y: "haty"}
        if ABS_RX in axes:                     # xpad / hid-playstation / hid-nintendo: right stick is RX/RY
            amap.update({ABS_RX: "rx", ABS_RY: "ry"})
            if ABS_BRAKE in axes or ABS_GAS in axes:
                amap.update({ABS_BRAKE: "lt", ABS_GAS: "rt"})
            else:
                amap.update({ABS_Z: "lt", ABS_RZ: "rt"})
        else:                                  # Xbox via BLE hid-generic: right stick is Z/RZ, triggers are BRAKE/GAS
            amap.update({ABS_Z: "rx", ABS_RZ: "ry", ABS_BRAKE: "lt", ABS_GAS: "rt"})
        for code, role in amap.items():
            a = axes.get(code)
            if a is not None:
                self.amap[code] = (role, a.get("min", -32768), a.get("max", 32767))
                self._set_axis(code, a.get("value", 0))
        for b in self.device.get("buttons") or []:
            if isinstance(b, dict):
                self._set_key(b.get("code"), b.get("name"), bool(b.get("pressed")), track=False)
        self.last_at = now

    def _set_axis(self, code, raw):
        role, lo, hi = self.amap[code]
        if not isinstance(raw, (int, float)):
            return
        if role in ("hatx", "haty"):
            v = 0 if raw == 0 else (1 if raw > 0 else -1)
            neg, pos = ("dl", "dr") if role == "hatx" else ("du", "dd")
            self.buttons[neg], self.buttons[pos] = v < 0, v > 0
            return
        if hi == lo:
            return
        if role in ("lt", "rt"):
            v = (raw - lo) / (hi - lo)
            v = max(0.0, min(1.0, v))
        else:
            mid, half = (hi + lo) / 2, (hi - lo) / 2
            v = max(-1.0, min(1.0, (raw - mid) / half))
        self.axes[role] = v

    def _set_key(self, code, name, down, track=True):
        role = self._role(code)
        if role:
            self.buttons[role] = down
            if down and track:
                self.seen.add(role)
        else:
            self.other[name or f"键 0x{code or 0:03x}"] = down

    def frame(self, frame, now):
        """Returns Select's change in this frame: True pressed, False released, None unchanged."""
        select = None
        for ev in (frame or {}).get("events") or []:
            if not isinstance(ev, dict):
                continue
            kind, code, value = ev.get("kind"), ev.get("code"), ev.get("value", 0)
            if kind == EV_KEY:
                if value == 2:               # auto-repeat: not a release
                    continue
                was = self.buttons.get(self._role(code)) if self._role(code) else None
                self._set_key(code, ev.get("name"), value != 0)
                if self._role(code) == "select" and was != (value != 0):
                    select = value != 0
                self.activity_at = now
            elif kind == EV_ABS and code in self.amap:
                self._set_axis(code, value)
                role = self.amap[code][0]
                if role in ("hatx", "haty"):
                    if value:
                        self.seen.add({("hatx", True): "dr", ("hatx", False): "dl", ("haty", True): "dd",
                                       ("haty", False): "du"}[(role, value > 0)])
                    self.activity_at = now
        for stick, (x, y) in (("ls", ("lx", "ly")), ("rs", ("rx", "ry"))):
            mag = math.hypot(self.axes.get(x, 0.0), self.axes.get(y, 0.0))
            if mag > STICK_ACTIVE:
                self.activity_at = now
            if mag > 0.5:
                self.seen.add(stick)
        for t in ("lt", "rt"):
            if self.axes.get(t, 0.0) > 0.5:
                self.seen.add(t)
        self.last_at = now
        return select

    def view(self, now):
        d = self.device or {}
        return {"device": {"name": d.get("name"), "node": d.get("node"), "unique": d.get("unique"), "kind": self.kind,
                           "bus": "蓝牙" if d.get("bus") == 5 else "USB" if d.get("bus") == 3 else None,
                           "keys_unverified": self.kind == "xbox" and not XBOX_SWAP_VERIFIED} if self.device else None,
                "buttons": {k: True for k, v in self.buttons.items() if v},
                "axes": {k: round(v, 2) for k, v in self.axes.items()},
                "other": sorted(k for k, v in self.other.items() if v),
                "last_ms": None if self.last_at is None else int((now - self.last_at) * 1000)}


# ---------------- Main ----------------

PAIR_STEPS = [("pair", "配对"), ("trust", "信任：以后开机自己回连"), ("connect", "连接"),
              ("padd", "padd 认到手柄"), ("keys", "按键测试：每个键按一下、摇杆推一圈")]
SCAN_STEPS = [("ready", "鸭子的蓝牙准备好"), ("scan", "搜索附近的手柄（灯要快闪）"), ("pick", "选一个手柄")]


def _idle_wizard():
    return {"state": "idle", "phase": None, "steps": [], "devices": [], "picked": None, "error": None, "via": None,
            "started": None, "elapsed_s": None, "result_name": None, "seen": [], "retry": None, "mac": None,
            "helper_available": None}


def _torque_on(bus):
    """Does busStatus say torque is confirmed on (motion mode looks at native.torque_state_confirmed, debug mode at torque_state)."""
    if not isinstance(bus, dict):
        return False
    if bus.get("mode") == "commissioning":
        return bus.get("torque_state") == "on"
    native = bus.get("native")
    return isinstance(native, dict) and native.get("torque_state_confirmed") is True


class PadOps(DriveMixin):
    def __init__(self, log, configd=None, bt=None, tap=None, robot=None, *, helper=None, clock=time.monotonic,
                 exists=os.path.exists, read_text=None, robotd_toml=ROBOTD_TOML, weird_ble=WEIRD_BLE, waits=None,
                 state_dir=None, audio=None, mapping_client=None):
        self.log = log
        self.configd, self.bt, self.tap, self.robot = configd, bt, tap, robot
        self.audio = audio
        self.helper = helper_api if helper is None else helper
        self._helper_pad_ok = None       # None not tried yet; True new helper accepts pad-pair; False old helper / no helper
        self.clock = clock
        self.exists = exists
        self.read_text = read_text or _read_text
        self.robotd_toml, self.weird_ble_path = robotd_toml, weird_ble
        w = {"poll": 0.1, "status_watch": 2.0, "status_job": 0.5, "padd": PADD_WAIT_S, "connect": CONNECT_WAIT_S,
             "readback": TEST_READBACK_S, "torque": TEST_TORQUE_WAIT_S, "press": TEST_PRESS_WAIT_S,
             "lease": WATCH_LEASE_S, "scan_tick": 0.5, "pair_window": PAIR_WINDOW_S, "scan_min": 3,
             "pad_timeout": PAD_PAIR_TIMEOUT_S,
             "reconnect_after": 2.0, "reconnect_interval": 4.0, "reconnect_timeout": 5.0,
             "probe": TEST_PROBE_S, "shutdown_hold": SHUTDOWN_HOLD_S, "select_long": SELECT_LONG_S,
             "relax_guard": RELAX_GUARD_S, "files": 10.0, "bindings": 10.0}
        w.update(waits or {})
        self.w = w
        self._lk = threading.RLock()
        self._wake = threading.Event()
        self._closing = False
        self._worker = None
        self._watch_until = 0.0
        self._status = None              # latest result of configd pad.status
        self._status_at = None
        self._status_error = None
        self._status_due = 0.0
        self._robot = {}                 # robotd readback handed in by app
        self._robot_at = None
        self._netpad = None
        self._netpad_why = None
        self._worker_error = None        # the watcher thread hit an exception: can't tell whether there's a physical gamepad (review 2, minor 3)
        self._snap_errors = set()
        self.live = LiveInput()
        self.tap_state, self.tap_why = "off", None
        self._tap_on = False
        self._attach_wait_since = None
        self._tap_err_said = False
        self.bindings = None
        self._bindings_at = -1e9
        self._bindings_err = None
        self.wiz = _idle_wizard()
        self._job = None                 # (id, thread)
        self._job_id = 0
        self._cancel = threading.Event()
        self._configd_thread = None      # configd's pad.pair can't be stopped: no new pairing allowed while the thread is still alive (review 10)
        self._configd_until = 0.0
        self.test = {"state": "idle"}
        self._test_evt = threading.Event()
        self.on_estop_passed = None          # who to hand a passed e-stop test to (app hooks up onboard.Onboarding.note_estop)
        self.battery_shutdown = None         # robotd's [safety] battery_empty_shutdown: the gamepad page's low-battery text follows it (task 1 addendum)
        self._attach_said = None             # tap attached only logs a line when the device changes (review O16: going out of range for 6 seconds and back is one line)
        self._pad_config = robotd_toml       # the file padd reads [netpad] and [pad_imu_head_control] from: padd.service's --config (_refresh_files)
        self._drive_init(state_dir)
        self.motion_studio = MotionStudio(self)
        self.mapping = PadMapping(mapping_client, guard=self._mapping_guard, clock=clock)
        # move / sticks / keys / stop use their own small thread pool, not crowded with slow calls like configd, Bluetooth, and one-off requests (review 2, minor 4);
        # round 3 added stick, button, and mode heartbeats, so it's 4 threads, and "stop" and re-centering don't have to queue (round 3 V13)
        self._fast_pool = concurrent.futures.ThreadPoolExecutor(max_workers=FAST_WORKERS, thread_name_prefix="pad-fast")
        # robotd.toml and padd.service are read in a background thread; snapshot only takes the cache (snapshot is called in the event loop: review 2, minor 9)
        self._files_stop = threading.Event()
        self._refresh_files()
        threading.Thread(target=self._files_loop, name="pad-files", daemon=True).start()
        self._drive_start()

    # ================= External API =================

    def _mapping_guard(self):
        with self._lk:
            reason = self._base_block(self.clock(), ignore_mapping=True)
            if reason:
                raise MappingError(reason)
            # robot.policies.enabled is the configured model-loading switch,
            # not the live controller state. BusDynamic is flattened on wire.
            bus=self._robot.get('bus') or {}
            pose=self._robot.get('posture')
            native=bus.get('native') or {}
            guard=bus.get('home_start_guard')
            stable=(pose=='limp' and native.get('torque_state_confirmed') is False) or (
                pose=='holding' and native.get('torque_state_confirmed') is True
                and bus.get('homed') is True and (guard is None or isinstance(guard,dict) and guard.get('ready') is True))
            if (bus.get('phase')!='control' or bus.get('policy_enabled') is not False
                    or bus.get('home_recovery') is not False or bus.get('torque_off_pending') is not False or not stable):
                raise MappingError('请先点“停下（站好）”，等策略停止并站稳，再开始映射')
            if self._cmd_busy or self._job_alive() or self.motion_studio.session is not None or self.test.get('state') not in FINAL:
                raise MappingError('请先结束配对、动作、录制回放和急停测试，再重新映射')
            if (self._lease_holder(self.clock()) is not None or self._action is not None
                    or self._modes or any(not item.get('end') and item.get('held') for item in self._keys.values())
                    or any(self._latch.values())):
                raise MappingError('网页遥控会话还在，请先松开按键并退出遥控，等头和身体回中后再重新映射')
            extra=getattr(self,'mapping_guard',None)
            if extra:extra()

    def mark_gone(self, conn):
        self.mapping.leave(conn)
        return super().mark_gone(conn)

    def handle(self, args, by=None, conn=None):
        from .updates import safe_during_update
        if self._update_blocked() and not safe_during_update('pad.op',args):
            raise Refused('软件 / 主程序更新保护仍在，急停和关闭语音仍可使用')
        with self.motion_studio.request():
            return self._handle_request(args, by=by, conn=conn)

    def _handle_request(self, args, by=None, conn=None):
        """Page commands (run in a thread). Returns a dict for the page; raises Refused if it can't be done (reason shown on the page).
        by: human-readable like "电脑 192.168.1.5" (computer 192.168.1.5); conn: which page connection (two tabs on the same computer can be told apart)."""
        op = args.get("op")
        if conn is not None and conn in self._gone and op not in ("watch", "stop", "action_stop", "drive"):
            raise Refused("这个页面已经断开了")      # commands arriving late from the thread pool (review 2 S1)
        if op == 'mapping':
            try:
                result = self.mapping.handle(args, conn)
            except MappingError as error:
                raise Refused(str(error)) from None
            self._watch_until = self.clock() + self.w['lease']
            self._ensure_worker()
            return result
        if self.mapping.blocked:
            safe = op in ('watch','refresh','stop','action_stop') or (op=='drive' and args.get('open') is False)
            safe = safe or (op=='keys' and not args.get('held')) or (op=='audio' and args.get('listening') is False)
            if not safe:
                raise Refused('手柄映射／回中确认中，动作输出已暂停；请先保存或取消并松开手柄，网页卸力仍可使用')
        if op == "motion":
            return self.motion_studio.handle(args, conn, by)
        if op == "audio":
            values = {key:value for key,value in args.items() if key != "op"}
            if not values or set(values)-{"listening","music"} or any(type(value) is not bool for value in values.values()):
                raise Refused("语音只支持监听和音乐两个开关")
            if conn is None or conn in self._gone or conn in self._closed:
                raise Refused("请先回到手柄遥控区操作语音")
            if self.audio is None:
                raise Refused("语音服务尚未配置，请检查 duck-echo")
            if values.get("listening") is False or values.get("music") is False:
                with self._lk:
                    if (self.motion_studio.session or {}).get("idle_kind") == "music":
                        self.motion_studio.invalidate("监听或音乐模式已关闭")
            try:
                return {"audio":self.audio.set(**values)}
            except (OSError,ValueError,TypeError):
                raise Refused("连接不到语音服务，请检查 duck-echo") from None
        if self.motion_studio.before(args, conn, by) is False:
            return {"dropped": "动作会话已经改变，旧请求已丢弃"}
        if op == "watch":
            self._watch()
            return {}
        if op == "refresh":
            self._poll_status()
            with self._lk:
                return {"status": self._status_view(self.clock())}
        if op == "scan":
            secs = args.get("seconds", SCAN_S)
            try:
                secs = max(self.w["scan_min"], min(SCAN_MAX_S, float(secs)))
            except (TypeError, ValueError):
                raise Refused("搜索时间要是数字（秒）") from None
            if not math.isfinite(secs):
                raise Refused("搜索时间要是数字（秒）")
            return self._start_job("scan", self._job_scan, secs)
        if op == "pair":
            mac = args.get("mac")
            if mac is not None and not MAC_RE.match(str(mac)):
                raise Refused("MAC 地址格式不对：要像 AA:BB:CC:DD:EE:FF")
            return self._start_job("pair", self._job_pair, (mac.upper() if mac else None, by))
        if op == "cancel":
            return self._cancel_job()
        if op == "forget":
            mac = str(args.get("mac") or "")
            if not MAC_RE.match(mac):
                raise Refused("MAC 地址格式不对：要像 AA:BB:CC:DD:EE:FF")
            return self._forget(mac.upper(), by)
        if op == "keys_done":
            return self._keys_done(manual=True)
        if op == "wizard_reset":
            with self._lk:
                if self._job_alive():
                    raise Refused("正在搜索 / 配对：先点「停下」")
                self.wiz = _idle_wizard()
            return {}
        if op == "estop_test":
            return self._estop_test(args.get("action"))
        # ---- Make the duck move (pad_drive.py) ----
        if op == "drive":
            return self._drive(args, conn, by)
        if op == "move":
            return self._move(args, conn, by)
        if op == "sticks":
            return self._sticks(args, conn, by)
        if op == "stop":
            return self._stop_move(args, conn, by)
        if op == "mode":
            return self._mode_op(args, conn, by)
        if op == "keys":
            return self._keys_op(args, conn, by)
        if op == "start":
            return self._start(args, conn, by)
        if op == "key":
            return self._key_press(args, conn, by)
        if op == "reboot":
            return self._reboot(args, conn, by)
        if op == "drive_mode":
            return self._drive_mode(args, conn, by)
        if op in ("stand", "walk", "walk_stop", "sit", "skill", "sound"):
            return self._motion_cmd(op, args, conn, by)
        if op == "action_start":
            return self._action_start(args, conn, by)
        if op == "action_hold":
            return self._action_hold(conn, args.get("press"))
        if op == "action_stop":
            return self._action_stop(conn, "页面点了停 / 松开了")
        if op == "combo_save":
            return self._combo_save(args)
        if op == "combo_delete":
            return self._combo_delete(args)
        raise Refused(f"不认识的指令：{op}")

    def watched(self):
        """Someone is viewing the gamepad page / pairing / testing the e-stop: app pushes snapshot at 10 Hz then; normally 1 Hz is enough."""
        with self._lk:
            return self._busy_reason(self.clock())

    def feed_robot(self, view):
        """robotd readback (fetched by app in the event loop with robot_view() and handed in). How many times relax was pressed also comes from here (review 1)."""
        if not isinstance(view, dict):
            return
        relax_new = False
        with self._lk:
            self._robot = view
            self._robot_at = self.clock()
            st = view.get("pad_status")
            at = view.get("pad_status_at")
            # robotd.py already asks pad.status every 5 seconds: when nobody is viewing the gamepad page, just use that instead of asking ourselves
            if isinstance(st, dict) and at is not None and (self._status_at is None or at > self._status_at):
                self._status, self._status_at, self._status_error = st, at, None
            elif view.get("pad_status_error") and self._status_at is None:
                self._status_error = view.get("pad_status_error")
            relax_new = self._relax_seen(view, self.clock())
            self._drive_feed(view)          # first sight of the main program, posture leaving "ready to walk" (only changes memory)
        if relax_new:
            self._action_stop(None, "卸力了")
            self._request_clear(None, "卸力了（回读看到的）", RELAX_CLEAR_DELAY_S)   # round 3 V1 item 5: only set the flag
            self._test_evt.set()

    def snapshot(self, robot=None, conn=None):
        if robot is not None:
            self.feed_robot(robot)
        now = self.clock()
        with self._lk:
            status = self._status_view(now)
            live = self.live.view(now)
            live.update(state=self.tap_state if self._tap_on else "off", why=self.tap_why)
            mapping = self.mapping.snapshot(conn)
            mapped = mapping.get('mapped')
            if (mapping.get('available') and mapping.get('profile') and mapped
                    and (mapping.get('device') or {}).get('node') == (live.get('device') or {}).get('node')):
                live.update(buttons=mapped['buttons'], axes=mapped['axes'], mapping_custom=True)
                if live.get('device'):
                    live['device']['keys_unverified'] = False
            wiz = dict(self.wiz)
            if wiz.get("started") is not None and wiz["state"] == "running":
                wiz["elapsed_s"] = now - wiz["started"]
            wiz.pop("started", None)
            wiz["seen"] = sorted(self.live.seen) if wiz.get("phase") == "keys" else []
            wiz["configd_busy_s"] = self._configd_busy_left(now)
            wiz["helper_available"] = self._helper_pad_ok
            test = {k: v for k, v in self.test.items() if not k.startswith("_")}
            if test.get("state") == "pressed" and self.test.get("_pressed_at") is not None:
                test["held_s"] = round(now - self.test["_pressed_at"], 1)
            attached, pad_why = self._pad_attached(now)
            d = self._lease_holder(now)
            ex = self._mode_exit.get(conn)
            ks = self._keys.get(conn)
            virtual = {"owner": self._owner(now), "last": self.virtual["last"],
                       "age_ms": None if self.virtual["at"] is None else int((now - self.virtual["at"]) * 1000),
                       "mirror": attached is True, "mirror_why": pad_why if attached else None,
                       "pad_unknown": pad_why if attached is None else None, "limits": self._speed_limits(),
                       "driver": None if d is None else {"by": d["by"], "mine": d["conn"] == conn,
                                                         "for_s": int(now - d["since"])},
                       # round 3: the mode this page has recorded in the backend (the page follows it), why the backend exited the mode for it, buttons held down
                       "mode": self._mode_of(conn), "mode_exit": None if ex is None or now - ex["at"] > 10 else
                       {"why": ex["why"], "age_s": round(now - ex["at"], 1)},
                       "keys": [] if ks is None or ks.get("end") else sorted(ks["held"]),
                       "inputs": self._inputs, "pad_imu_head": self._imu_head, "pad_imu_head_why": self._imu_head_why,
                       "latch": {k: v is not None for k, v in self._latch.items()}}
            return {"t": "pad", "status": status, "estop": self._estop_checks(now, status), "live": live,
                    "wizard": wiz, "estop_test": test, "virtual": virtual, "motion": self._motion_view(now),
                    "motion_studio": self.motion_studio.snapshot(conn, now),
                    "audio": self.audio.snapshot() if self.audio is not None else {"available":False,"why":"语音服务尚未配置"},
                    "bindings": self.bindings, "mapping": mapping}

    def safe_snapshot(self, conn=None):
        """For app's send loop: errors are logged only once (the same error once), returns None to skip this frame,
        and must not make the send loop exit (that would also gray out the relax button at the top: review 2 I3)."""
        try:
            return self.snapshot(conn=conn)
        except Exception as e:  # noqa: BLE001
            key = f"{type(e).__name__}: {e}"[:200]
            if key not in self._snap_errors:
                self._snap_errors.add(key)
                self.log.error("手柄页的状态算出错，跳过这一帧", cat="手柄", raw=key, exc=True,
                               hint="这是 Studio 的问题，导出诊断包发出来；同一种错只记这一次")
            return None

    def diag(self):
        """For the diagnostics bundle: snapshot, but nearby Bluetooth devices keep only the count and partial names / MACs (review 2, minor 8: the diagnostics bundle gets posted to the group)."""
        snap = self.safe_snapshot()
        if snap is None:
            return {"error": "snapshot 出错，见日志"}
        wiz = snap.get("wizard") or {}
        devs = wiz.get("devices") or []
        wiz["devices"] = {"count": len(devs), "pads": sum(1 for d in devs if d.get("pad")),
                          "items": [{"name": _mask_name(d.get("name")), "mac": _mask_mac(d.get("mac")), "pad": d.get("pad"),
                                     "rssi": d.get("rssi")} for d in devs[:20]]}
        for k in ("mac", "picked"):
            if wiz.get(k):
                wiz[k] = _mask_mac(wiz[k])
        dev = (snap.get("live") or {}).get("device") or {}
        if dev.get("unique"):
            dev["unique"] = _mask_mac(dev["unique"])
        mapping_dev=(snap.get('mapping') or {}).get('device') or {}
        if mapping_dev.get('unique'):
            mapping_dev['unique']=_mask_mac(mapping_dev['unique'])
        return snap

    def estop_ok(self):
        """Only the single conclusion "e-stop effective" (the overview's state.py will call it later, without computing a full snapshot every frame: review 23)."""
        now = self.clock()
        with self._lk:
            return self._estop_checks(now, self._status_view(now))["ok"]

    def onboard_view(self):
        """What the overview onboarding checklist's steps 3 and 4 need (onboard.py calls it every 0.5 seconds): the same status / estop as the gamepad snapshot (overview reshuffle review O7),
        plus devices seen by the tap (evidence of "a gamepad is connected" when configd is unreadable: review O5). No network, only reads memory under the lock."""
        now = self.clock()
        with self._lk:
            status = self._status_view(now)
            attached = self._tap_on and self.tap_state == "attached"
            dev = dict(self.live.device or {}) if attached else None
            es = self._estop_checks(now, status)
        return {"known": status["known"], "error": status["error"], "pads": status["pads"], "active": status["active"],
                "attached": attached, "device": {"name": (dev or {}).get("name"), "unique": (dev or {}).get("unique")} if dev else None,
                "estop": {"state": es["state"], "checks": es["checks"]}}

    def _estop_passed_record(self):
        """E-stop test passed: hand "which gamepad, which main program version it was tested with" to the onboarding checklist (review O6: a gamepad change or main program upgrade requires retesting).
        Called in the e-stop test thread without holding the lock; hook errors are only logged."""
        hook = getattr(self, "on_estop_passed", None)
        if hook is None:
            return
        now = self.clock()
        with self._lk:
            status = self._status_view(now)
            a = status["active"] or {}
            dev = self.live.device or {}
            mac = a.get("mac") or (dev.get("unique") if self.tap_state == "attached" else None)
            name = a.get("name") or dev.get("name")
            bus = (self._robot or {}).get("bus") if isinstance((self._robot or {}).get("bus"), dict) else {}
            rec = {"ms": self.test.get("ms"), "mac": mac, "name": name, "build": bus.get("build")}
        try:
            hook(rec)
        except Exception as e:  # noqa: BLE001
            self.log.error("记「测急停过了」时出错", cat="安全", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="这是 Studio 的问题；急停本身测过了，只是总览清单上没记下")

    def close(self):
        self._closing = True
        self.mapping.close()
        self._cancel.set()
        self._wake.set()
        self._test_evt.set()
        self._action_stop(None, "Studio 关了")
        self._drive_close()                 # head / body re-centered, held buttons released (round 3 V1 item 9, best effort)
        if self.audio is not None:
            self.audio.close()
        self._files_stop.set()
        try:
            self._fast_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass
        if self.tap is not None and self._tap_on:
            try:
                self.tap.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.bt is not None:
            try:
                self.bt.close()
            except Exception:  # noqa: BLE001
                pass

    # ================= Status =================

    def _status_view(self, now):
        st = self._status if isinstance(self._status, dict) else None
        pads = []
        for p in (st or {}).get("pads") or []:
            if isinstance(p, dict):
                pads.append({"mac": p.get("mac"), "name": p.get("name"), "paired": p.get("paired"),
                             "trusted": p.get("trusted"), "connected": p.get("connected"),
                             "kind": pad_kind(p.get("name"))})
        active = next((p for p in pads if p["connected"]), None)
        age = None if self._status_at is None else now - self._status_at
        known = st is not None and age is not None and age < 20
        return {"known": known, "error": None if known else self._status_error,
                "driver": (st or {}).get("driver") if known else None, "pads": pads if known else [],
                "active": active if known else None, "age_ms": None if age is None else int(age * 1000),
                "netpad": self._netpad_value(now), "netpad_why": self._netpad_why}

    def _netpad_value(self, now=None):
        """[netpad] enabled in /etc/robot/robotd.toml (cached; the file is read in _refresh_files). None if unreadable: Studio being unable to read it
        doesn't mean padd can't (review 7), so the "e-stop effective" side treats it as "not checked", not "off".
        Note padd only reads it once at startup: if the file was changed without restarting padd, this differs from reality."""
        return self._netpad

    def _refresh_files(self):
        """Read padd's unit file (full-stick speed, head / mouth amplitude, which config file it reads), then read that config file's [netpad] and
        [pad_imu_head_control] into the cache. Runs in a background thread (read once synchronously at construction).
        padd reads its config from its --config (default /etc/robot/robotd.toml; the fork's drop-in sets
        /etc/robot/feetech-ft5/robotd.toml: fork packaging/gamepad.py:94), and both [netpad] and [pad_imu_head_control] are read from there
        (fork padd main.rs:692, 776)."""
        try:
            texts = self._read_padd_texts()
            limits = parse_speed_limits(texts)
            inputs, cfg = self._read_inputs(texts)
        except Exception as e:  # noqa: BLE001 —— parsing itself doesn't raise; if something else fails, use the official defaults
            limits = dict(self._limits, src=f"官方默认（读 padd 配置出错：{type(e).__name__}）")
            inputs, cfg = self._inputs, None
        path = cfg or self.robotd_toml
        imu_head, imu_why = None, None
        config_text = None
        try:
            config_text = self.read_text(path)
            data = tomllib.loads(config_text)
            netpad, why = bool((data.get("netpad") or {}).get("enabled", False)), None
            ih = data.get("pad_imu_head_control") or {}
            imu_head = bool(ih.get("enabled", False)) if isinstance(ih, dict) else None
        except FileNotFoundError:
            # File missing: robotd uses all defaults, [netpad] defaults to off ([UDP] robotd-params lib.rs:107-121);
            # [pad_imu_head_control] defaults to off (fork robotd-params lib.rs:140-155)
            netpad, why = False, f"没有 {path}，按默认（关）"
            imu_head, imu_why = False, why
        except PermissionError as e:
            netpad, why = None, f"Studio 没权限读 {path}（{e.strerror or e}）"
            imu_why = why
        except Exception as e:  # noqa: BLE001 —— broken format, other read errors
            netpad, why = None, f"{path} 读不出来（{type(e).__name__}: {e}）"
            imu_why = why
        with self._lk:
            self._netpad, self._netpad_why, self._limits = netpad, why, limits
            self._inputs, self._pad_config = inputs, path
            self._imu_head, self._imu_head_why = imu_head, imu_why
            self._motion_config_digest = _digest({"padd": texts, "path": path, "config": config_text})

    def _files_loop(self):
        while not self._files_stop.wait(self.w["files"]):
            try:
                self._refresh_files()
            except Exception as e:  # noqa: BLE001
                self.log.error("后台读配置文件出错", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True)

    def _robot_ok(self, now):
        r = self._robot or {}
        bus = r.get("bus") if isinstance(r.get("bus"), dict) else None
        if r.get("paused"):
            return False, "在调舵机：主程序按计划停着"
        if r.get("present") is False:
            return False, "主程序 robotd 没在跑"
        if self._robot_at is None or now - self._robot_at > BUS_FRESH_S:
            return None, "Studio 没收到主程序的回读"
        if bus is None or r.get("bus_at") is None or now - r["bus_at"] > BUS_FRESH_S:
            return None, "读不到主程序的状态"
        if bus.get("phase") in STARTING_PHASES:
            return False, "主程序还在启动"
        if bus.get("mode") == "commissioning":
            return False, "调试模式：Select 不经过主程序"
        if bus.get("mode") != "motion":
            return None, f"主程序在 {bus.get('mode')} 模式"
        return True, None

    def _estop_checks(self, now, status):
        """The four conditions of "e-stop effective" (plan v3.1 §3): gamepad connected, padd running, main program running, netpad not enabled.
        With the tap on, one more check: padd really opened this gamepad (the case of connected but no input device, pair-a-gamepad.md:184-189).
        configd unreadable but the tap sees attached: use the tap as evidence (it's even more direct than configd: review 16).
        state: ok all ✓; unknown no × but some unchecked; bad has an ×."""
        checks = []
        tap_ok = self._tap_on and self.tap_state == "attached"
        dev = (self.live.device or {}).get("name") if tap_ok else None
        if not status["known"]:
            if tap_ok:
                checks.append({"key": "pad", "label": "手柄连着", "ok": True,
                               "why": f"{dev or '手柄'}（padd 旁路看到的；configd 读不到）"})
            else:
                checks.append({"key": "pad", "label": "手柄连着", "ok": None, "why": status["error"] or "读不到 configd 的手柄状态"})
        else:
            a = status["active"]
            checks.append({"key": "pad", "label": "手柄连着", "ok": bool(a),
                           "why": a["name"] if a else ("配过的手柄都没开" if status["pads"] else "还没配手柄")})
        drv = status["driver"]
        if drv is None and tap_ok:
            checks.append({"key": "padd", "label": "padd 在跑（它把手柄的键转给主程序）", "ok": True,
                           "why": "padd 旁路开着、在发按键（configd 读不到）"})
        else:
            checks.append({"key": "padd", "label": "padd 在跑（它把手柄的键转给主程序）",
                           "ok": None if drv is None else drv == "active", "why": None if drv in (None, "active") else f"padd 现在是 {drv}"})
        ok, why = self._robot_ok(now)
        checks.append({"key": "robotd", "label": "主程序在跑（运动模式）", "ok": ok, "why": why})
        np = status["netpad"]
        checks.append({"key": "netpad", "label": "没开 UDP 手柄（netpad）", "ok": None if np is None else not np,
                       "why": "开着 [netpad]：padd 只读 UDP，不读蓝牙手柄" if np else
                       (status.get("netpad_why") if np is False else
                        f"{status.get('netpad_why') or '读不到 robotd.toml'}：netpad 没核对。开着的话蓝牙手柄和它的急停都不管用")})
        if self._tap_on and (status["active"] or tap_ok):
            if self.tap_state == "attached":
                checks.append({"key": "input", "label": "padd 打开了这个手柄（读得到按键）", "ok": True, "why": None})
            elif self.tap_state == "waiting" and self._attach_wait_since is not None and now - self._attach_wait_since > 3:
                checks.append({"key": "input", "label": "padd 打开了这个手柄（读得到按键）", "ok": False,
                               "why": "连着，但 padd 没打开它：多半是没有输入设备。忘掉它、重新进配对状态再配"})
        vals = [c["ok"] for c in checks]
        good = all(v is True for v in vals)
        state = "ok" if good else ("bad" if any(v is False for v in vals) else "unknown")
        return {"ok": good, "state": state, "checks": checks}

    def _poll_status(self):
        if self.configd is None:
            with self._lk:
                self._status_error = "这只鸭子没配 configd"
            return None
        try:
            r = self.configd.call("pad.status", {}, 2.0)
            if not isinstance(r, dict):
                raise RpcError("pad.status", None, f"回的不是对象（{type(r).__name__}）")
        except NoPermission as e:
            with self._lk:
                if self._status_error is None:
                    self.log.warn("Studio 没权限读 configd 的手柄状态", cat="手柄", step="pad.status", raw=str(e), hint=ROBOT_GROUP)
                self._status_error = str(e)
            return None
        except (Unreachable, Timeout, RpcError) as e:
            with self._lk:
                if self._status_error is None:
                    self.log.warn("读不到 configd 的手柄状态", cat="手柄", step="pad.status", raw=str(e),
                                  hint="有的鸭子关着 configd（sudo systemctl start configd）；不影响站和走")
                self._status_error = str(e)
            return None
        with self._lk:
            if self._status_error is not None:
                self.log.info("configd 的手柄状态恢复了", cat="手柄")
            self._status, self._status_at, self._status_error = r, self.clock(), None
        return r

    def _pad_in_status(self, mac):
        st = self._status if isinstance(self._status, dict) else {}
        for p in st.get("pads") or []:
            if isinstance(p, dict) and (p.get("mac") or "").upper() == (mac or "").upper():
                return p
        return None

    # ================= Watcher thread: only alive while someone is watching, a task is running, or the e-stop test is on =================

    def _watch(self):
        """Someone is viewing the gamepad page. Only renews the "watch" lease, not the steering wheel (just having the page open doesn't count as driving: review 2 I1)."""
        now = self.clock()
        with self._lk:
            first = self._watch_until < now
            self._watch_until = now + self.w["lease"]
            if first:
                self._status_due = 0.0
                self._bindings_due = 0.0          # pad.bindings is fetched by the watcher thread (round 3 V13: watch is in the fast thread pool and can't wait 2 seconds)
        self._ensure_worker()

    def _fetch_bindings(self):
        """Ask robotd what the five buttons are currently bound to (pad.bindings: fork lib.rs:4478-4497; robotd rereads the config each time it's asked,
        padd rereads every second: padd:806-817). The watcher thread does it every 10 seconds; when a button on the diagram is pressed and the data is too old, fetch once first (round 3 V14). Doesn't raise."""
        if self.robot is None:
            return None
        try:
            r = self.robot.call("pad.bindings", {}, 2.0)
        except (Unreachable, Timeout, RpcError) as e:
            with self._lk:
                self._bindings_at = self.clock()       # unreadable still counts as asked: retry in 10 seconds, don't wait 2 seconds on every button press
                said = self._bindings_err is not None
                self._bindings_err = str(e)
            if not said:
                self.log.info("读不到手柄的按键绑定（用官方默认）", cat="手柄", step="pad.bindings", raw=str(e))
            return None
        rows = r.get("bindings") if isinstance(r, dict) else None
        rows = [b for b in rows if isinstance(b, dict)] if isinstance(rows, list) else None
        with self._lk:
            changed = rows != self.bindings
            self.bindings, self._bindings_at, self._bindings_err = rows, self.clock(), None
        if changed and rows is not None:
            text = "、".join(f"{b.get('button')}={b.get('skill') or '（关）'}" + (f"（{b['error']}）" if b.get("error") else "")
                            for b in rows)
            self.log.info(f"手柄按键绑定：{text}", cat="手柄", step="pad.bindings")
        return rows

    def _ensure_worker(self):
        with self._lk:
            if self._worker is not None and self._worker.is_alive():
                self._wake.set()
                return
            self._worker = threading.Thread(target=self._worker_loop, name="pad-watch", daemon=True)
            self._worker_error = None
            self._worker.start()

    def _busy_reason(self, now):
        return (self._watch_until > now or self._job_alive()
                or self.test.get("state") not in FINAL)

    def _worker_loop(self):
        try:
            while not self._closing:
                now = self.clock()
                with self._lk:
                    alive = self._busy_reason(now)
                    watching = self._watch_until > now or self.test.get("state") not in FINAL \
                        or self.wiz.get("phase") in ("padd", "keys")
                    if not alive:
                        self._worker = None
                if not alive:
                    break
                if now >= self._status_due:
                    self._status_due = now + (self.w["status_job"] if self._job_alive() else self.w["status_watch"])
                    self._poll_status()
                if now >= self._bindings_due and self._watch_until > now:
                    self._bindings_due = now + self.w["bindings"]
                    self._fetch_bindings()
                self._tap_lease(watching)
                self.mapping.poll()
                self._keys_tick()
                self._wake.wait(self.w["poll"])
                self._wake.clear()
        except Exception as e:  # noqa: BLE001 —— the watcher thread must not silently die
            self.log.error("手柄页的看守线程出错", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="这是 Studio 的问题，导出诊断包发出来；刷新手柄页会重新起一个")
            with self._lk:
                self._worker = None
                self._worker_error = f"{type(e).__name__}: {e}"
        finally:
            self._tap_lease(False)

    # ---- Tap ----

    def _tap_lease(self, want):
        if self.tap is None:
            return
        with self._lk:
            if want == self._tap_on:
                return
            self._tap_on = want
            if want:
                self.tap_state, self.tap_why = "connecting", None
                self._attach_wait_since = None
        if want:
            self.tap.start(self._on_tap_report, self._on_tap_state)
        else:
            self.tap.stop()
            with self._lk:
                self.live.reset()
                self.tap_state, self.tap_why = "off", None

    def _on_tap_state(self, state, why=None):
        with self._lk:
            if state == "waiting" and self.tap_state != "waiting":
                self._attach_wait_since = self.clock()
            if (state, why) != (self.tap_state, self.tap_why) and state in ("absent", "denied", "error"):
                self.log.warn(f"读不到手柄按键（padd 旁路）：{why}", cat="手柄", step="pad.input",
                              hint=ROBOT_GROUP if state == "denied" else "padd 只在主程序跑着时才在")
            self.tap_state, self.tap_why = state, why

    def _on_tap_report(self, rep):
        """Called from the tap thread: attached / frame / detached (the imu ones aren't used). Errors are only logged, not raised (review 15)."""
        if not isinstance(rep, dict):
            return
        try:
            self._tap_report(rep)
        except Exception as e:  # noqa: BLE001
            if not self._tap_err_said:
                self._tap_err_said = True
                self.log.error("处理手柄按键时 Studio 出错", cat="手柄", raw=f"{type(e).__name__}: {e}  ·  {json.dumps(rep)[:300]}",
                               exc=True, hint="这是 Studio 的问题，导出诊断包发出来")

    def _tap_report(self, rep):
        now = self.clock()
        kind = rep.get("report")
        with self._lk:
            if kind == "attached":
                self.live.attach(rep.get("device"), now)
                self.tap_state, self.tap_why = "attached", None
                d = self.live.device or {}
                key = (d.get("name"), d.get("unique"), d.get("node"))
                if key != self._attach_said:
                    self._attach_said = key
                    self.log.info(f"padd 打开了手柄：{d.get('name')}（{d.get('node')}）", cat="手柄", dedup=False)
            elif kind == "frame":
                sel = self.live.frame(rep, now)
                mapping = self.mapping.snapshot()
                bind = ((mapping.get('profile') or {}).get('bindings') or {}).get('select')
                if bind and (mapping.get('device') or {}).get('node') == (self.live.device or {}).get('node'):
                    sel = None
                    for event in rep.get('events') or []:
                        if event.get('code') != bind.get('code'):
                            continue
                        if bind.get('kind') == 'key' and event.get('kind') == EV_KEY and event.get('value') in (0,1):
                            sel = event['value'] == 1
                        elif bind.get('kind') == 'axis_button' and event.get('kind') == EV_ABS:
                            sel = event.get('value') == bind.get('value')
                if sel is not None and not mapping.get('output_blocked'):
                    self._on_select(sel, now)
            elif kind == "detached":
                self.live.reset()
                self.tap_state, self.tap_why = "waiting", rep.get("why")
                self._attach_wait_since = now
                self.log.info(f"手柄从 padd 那边断开了：{rep.get('why')}", cat="手柄")
        if kind == "attached":
            self._action_stop(None, "实体手柄连上了")
            self._request_clear(None, "实体手柄连上了")     # round 3 V1 item 6: also clear head / body mirroring set by the web page
            with self._lk:
                error = self.wiz.get("error") or {}
                if (self.wiz.get("state") == "failed" and error.get("code") in ("no_input", "not_connected")
                        and self._pair_input_matches(self.wiz.get("mac")) and self._mine(self._job_id)):
                    self._pair_keys_ready(self._job_id, self.wiz.get("mac"))

    # ================= Pairing wizard =================

    def _job_alive(self):
        # Only look at "still running": at the moment the thread has reported failure / is waiting for the user to choose, it hasn't exited yet, and clicking "Retry" then must not count as busy
        return self._job is not None and self._job[1].is_alive() and self.wiz.get("state") == "running"

    def _configd_busy_left(self, now):
        t = self._configd_thread
        if t is None or not t.is_alive():
            return None
        return max(1, int(self._configd_until - now))

    def _start_job(self, kind, fn, arg):
        now = self.clock()
        with self._lk:
            if self._job_alive():
                raise Refused("正在搜索 / 配对：等它做完，或者先点「停下」")
            if self.test.get("state") not in FINAL:
                raise Refused("正在测急停：先测完或者点「不测了」")
            left = self._configd_busy_left(now)
            if left is not None:
                raise Refused(f"configd 那边上一次配对还没做完（它停不了），大约还要 {left} 秒：等一下再点")
            # Review 8: scanning and pairing occupy the radio; the gamepad in use may stall without disconnecting, padd keeps sending the last stick values, and the deadman doesn't trigger
            bus = (self._robot or {}).get("bus")
            if self._posture() in DRIVING or (isinstance(bus, dict) and bus.get("policy_enabled") is True):
                msg, fix = FAILS["driving"]
                raise Refused(f"{msg}：{fix}")
            self._job_id += 1
            jid = self._job_id
            self._cancel = threading.Event()
            keep = kind == "pair" and self.wiz.get("phase") == "pick"
            if not keep:
                self.wiz = _idle_wizard()
            self.wiz.update(state="running", started=self.clock(), error=None, retry=None,
                            elapsed_s=None, result_name=None)
            t = threading.Thread(target=self._run_job, args=(jid, fn, arg), name=f"pad-{kind}", daemon=True)
            self._job = (jid, t)
            t.start()
        self._ensure_worker()
        return {"job": jid}

    def _run_job(self, jid, fn, arg):
        try:
            fn(jid, arg)
        except Exception as e:  # noqa: BLE001 —— shouldn't happen; if it does, the page must still see the reason
            self.log.error("配对向导出错", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="这是 Studio 自己的 bug，导出诊断包发出来")
            self._fail(jid, None, "other", f"Studio 出错：{type(e).__name__}: {e}")
        finally:
            with self._lk:
                if self.wiz.get("state") == "running" and jid == self._job_id:
                    self.wiz["elapsed_s"] = self.clock() - (self.wiz.get("started") or self.clock())
            self._wake.set()

    def _mine(self, jid):
        return jid == self._job_id and not self._cancel.is_set()

    def _step(self, jid, key, state, note=None):
        with self._lk:
            if jid != self._job_id:
                return
            for s in self.wiz["steps"]:
                if s["key"] == key:
                    if s["state"] == "ok" and state == "doing":
                        return               # already-ticked ones aren't rolled back
                    s["state"] = state
                    if note is not None:
                        s["note"] = note
            self.wiz["phase"] = key if state in ("doing", "fail") else self.wiz["phase"]

    def _note(self, jid, key, extra):
        with self._lk:
            for s in self.wiz["steps"]:
                if jid == self._job_id and s["key"] == key:
                    s["note"] = "；".join(x for x in (s.get("note"), extra) if x)

    def _fail(self, jid, key, code, raw=None, retry=None):
        with self._lk:
            if jid != self._job_id:
                return
            if key:
                self._step(jid, key, "fail")
            err = explain(code, raw)
            self.wiz.update(state="failed", error=err, retry=retry)
            if self.wiz.get("started") is not None:
                self.wiz["elapsed_s"] = self.clock() - self.wiz["started"]
        lvl = "info" if code == "cancelled" else "warn"
        self.log.write(f"手柄配对没成功：{err['msg']}", cat="手柄", level=lvl, step=key, raw=raw, hint=err["fix"])

    def _set_steps(self, jid, defs, keep=False):
        with self._lk:
            if jid != self._job_id:
                return
            have = {s["key"] for s in self.wiz["steps"]} if keep else set()
            if not keep:
                self.wiz["steps"] = []
            for k, label in defs:
                if k not in have:
                    self.wiz["steps"].append({"key": k, "label": label, "state": "todo", "note": None})

    def _sleep(self, s):
        """Sleep that can be interrupted by "stop". Returns True if interrupted."""
        return self._cancel.wait(s)

    # ---- Scanning ----

    def _job_scan(self, jid, seconds):
        self._set_steps(jid, SCAN_STEPS)
        if not self._prepare_adapter(jid, via_helper=self._helper_pad_ok):
            return
        bt = self.bt
        self._step(jid, "scan", "doing", f"最多 {seconds:g} 秒")
        self.log.info(f"开始搜索手柄（{seconds:g} 秒）", cat="手柄")
        devices = []
        try:
            try:
                bt.scan_start()
            except BtError as e:
                self._fail(jid, "scan", e.code if e.code != "other" else "scan_failed", e.raw, retry={"op": "scan", "seconds": seconds})
                return
            started = self.clock()
            try:
                while self.clock() - started < seconds:
                    devices = self._device_list(bt.devices(), started)
                    with self._lk:
                        if jid == self._job_id:
                            self.wiz["devices"] = devices
                            n = sum(1 for d in devices if d["pad"])
                            self._step(jid, "scan", "doing", f"还剩 {max(0, seconds - (self.clock() - started)):.0f} 秒 · 看到 {len(devices)} 个设备，{n} 个像手柄")
                    if self._sleep(self.w["scan_tick"]):
                        break
                devices = self._device_list(bt.devices(), started)
            finally:
                try:
                    bt.scan_stop()
                except BtError as e:
                    self.log.info("停止蓝牙搜索时出错（不影响）", cat="手柄", raw=e.raw)
        finally:
            # Review 5: close the bluetoothctl session once scanning is done, don't leave it hanging (pairing opens another one and registers the agent only within the pairing window)
            try:
                bt.close()
            except Exception:  # noqa: BLE001
                pass
        if self._cancel.is_set():
            self._fail(jid, "scan", "cancelled")
            return
        pads = [d for d in devices if d["pad"]]
        self.log.info(f"搜索完：看到 {len(devices)} 个蓝牙设备，{len(pads)} 个像手柄", cat="手柄",
                      raw=", ".join(f"{d['name'] or '?'} {d['mac']}" for d in pads[:6]) or None)
        with self._lk:
            if jid != self._job_id:
                return
            self.wiz["devices"] = devices
            self._step(jid, "scan", "ok", f"看到 {len(devices)} 个蓝牙设备，{len(pads)} 个像手柄")
            fresh = [d for d in pads if not d["paired"]]
            self.wiz["picked"] = fresh[0]["mac"] if len(fresh) == 1 else None
            self.wiz["phase"] = "pick"
            self.wiz["state"] = "waiting"
            for s in self.wiz["steps"]:
                if s["key"] == "pick":
                    s["state"] = "doing"
                    s["note"] = ("就是它吗？点「配这个」" if len(fresh) == 1 else
                                 "好几个在配对状态：点你要的那个" if len(fresh) > 1 else None)
            if not pads:
                self.wiz["error"] = explain("not_found_pad" if devices else "not_found")
                self.wiz["retry"] = {"op": "scan", "seconds": seconds}

    def _device_list(self, raw_devices, since):
        """bluetoothctl devices → the page's list: only those really seen in this scan (with signal), gamepads first, two faces of the same gamepad merged."""
        out = []
        for d in raw_devices or []:
            seen = d.get("seen_at")
            if not d.get("connected") and (seen is None or seen < since - 0.5):
                continue
            name = d.get("name") or d.get("alias")
            ev = gamepad_evidence(name, d.get("icon"), d.get("cls"), d.get("appearance"))
            kind = pad_kind(name)
            out.append({"mac": d.get("mac"), "name": name, "rssi": d.get("rssi"), "pad": ev is not None, "evidence": ev,
                        "classic": isinstance(d.get("cls"), int), "kind": kind if ev else None,
                        "kind_label": KIND_LABEL.get(kind) if ev else None,
                        "why_not": None if ev else (f"像是{ICON_CN[d.get('icon')]}" if d.get("icon") in ICON_CN else "不像手柄"),
                        "paired": bool(d.get("paired")), "connected": bool(d.get("connected"))})
        pads = [x for x in out if x["pad"]]
        drop = set()
        for a in pads:
            for b in pads:
                if a is not b and same_pad(a["mac"], b["mac"]) and a["classic"] and not b["classic"]:
                    drop.add(b["mac"])          # keep the classic face: HID goes through it (pad.rs:173-177)
        out = [x for x in out if x["mac"] not in drop]
        out.sort(key=lambda x: (not x["pad"], x["evidence"] != "classified", -(x["rssi"] if isinstance(x["rssi"], int) else -999)))
        return out

    def _prepare_adapter(self, jid, via_helper=None):
        """The ready step: adapter present, not rfkilled, powered on. Scanning doesn't need "bondable", only a reminder; it's only turned on temporarily when pairing (_ensure_pairable).
        via_helper=None not yet known which path; True uses the new helper; False no new helper (fallback path)."""
        self._step(jid, "ready", "doing")
        bt = self.bt
        if bt is None:
            self._fail(jid, "ready", "no_btctl", retry={"op": "pair"})
            return False
        a = bt.adapter()
        if a.get("missing"):
            self._fail(jid, "ready", "no_btctl", a.get("raw"), retry={"op": "pair"})
            return False
        if a.get("blocked"):
            self._fail(jid, "ready", "rfkill", a.get("raw"), retry={"op": "scan"})
            return False
        if a.get("error"):
            self._fail(jid, "ready", a.get("code") or classify(a["error"]), a["error"], retry={"op": "scan"})
            return False
        if not a.get("present"):
            self._fail(jid, "ready", "no_adapter", a.get("raw"), retry={"op": "scan"})
            return False
        notes = []
        if not a.get("powered"):
            try:
                bt.power_on()
                notes.append("刚把蓝牙打开")
            except BtError as e:
                self._fail(jid, "ready", e.code if e.code != "other" else "powered_off", e.raw, retry={"op": "scan"})
                return False
        if a.get("pairable") is False:
            notes.append("现在「不可绑定」：配对时会临时打开，配完改回去")
        if self.exists(self.weird_ble_path):
            if via_helper is True:
                notes.append("这块板配新手柄要先停 btd：新版小助手会停 btd、重开蓝牙，配完再起回来")
            elif via_helper is False:
                notes.append("这块板配新手柄要先停 btd，Studio 没有新版小助手做不了，可能配不上。"
                             "重装小助手，或者在鸭子上运行 sudo robotctl pad pair")
            else:
                notes.append("这块板配新手柄要先停 btd：新版小助手会做；没有新版小助手时可能配不上，"
                             "重装小助手，或者在鸭子上运行 sudo robotctl pad pair")
        self._step(jid, "ready", "ok", "；".join(notes) or None)
        return True

    def _ensure_pairable(self, jid):
        """Before pairing: if not bondable, temporarily turn it on (otherwise even if paired, the keys can't be stored: No Bonding). Returns True = we turned it on and must turn it back after pairing (review 5)."""
        bt = self.bt
        if bt is None:
            return False
        try:
            a = bt.adapter()
        except Exception:  # noqa: BLE001
            return False
        if a.get("pairable") is not False:
            return False
        try:
            bt.pairable_on()
        except BtError as e:
            self._note(jid, "ready", "没能打开「可绑定」（要 root），配上了也可能存不下钥匙")
            self.log.warn("没能打开蓝牙的「可绑定」", cat="手柄", step="pairable on", raw=e.raw, hint="sudo btmgmt bondable on")
            return False
        self._note(jid, "ready", "临时打开了「可绑定」")
        self.log.info("临时打开蓝牙的「可绑定」（配完改回去）", cat="手柄")
        return True

    # ---- Pairing ----

    def _job_pair(self, jid, arg):
        mac, by = arg if isinstance(arg, tuple) else (arg, None)
        from_pick = self.wiz.get("phase") == "pick"
        try:
            available = bool(self.helper.available())
        except Exception:  # noqa: BLE001 —— if probing the helper fails, treat it as absent
            available = False
        use_helper = self._helper_pad_ok is not False and available
        if not available:
            self._helper_pad_ok = False       # no helper: the wizard shows the fallback-path hint directly
        if from_pick:
            self._set_steps(jid, SCAN_STEPS + PAIR_STEPS, keep=True)
            self._step(jid, "pick", "ok", mac)
        else:
            self._set_steps(jid, SCAN_STEPS + PAIR_STEPS)
            if use_helper:
                self._step(jid, "ready", "skip", "交给小助手：官方 robotctl 会先停 btd、重开蓝牙")
            elif self.bt is not None:
                if not self._prepare_adapter(jid, via_helper=False):
                    return
            else:
                self._step(jid, "ready", "skip", "没有 bluetoothctl，跳过检查")
            note = ("交给小助手（官方 robotctl）自己找正在配对状态的手柄" if use_helper
                    else "交给 configd 自己找正在配对状态的手柄") if mac is None else mac
            self._step(jid, "scan", "skip", note)
            self._step(jid, "pick", "skip" if mac is None else "ok", None if mac is None else mac)
        if self.bt is not None:
            try:
                self.bt.close()       # the helper makes robotctl restart Bluetooth; close our session first (same for the configd fallback)
            except Exception:  # noqa: BLE001
                pass
        restore = False
        try:
            with self._lk:
                self.wiz.update(mac=mac, phase="pair", retry={"op": "pair", "mac": mac} if mac else {"op": "pair"})
            self._step(jid, "pair", "doing", "手柄的灯要一直快闪；可能要等十几秒")
            self.log.info(f"开始配对手柄 {mac or '（自动挑）'}", cat="手柄", dedup=False)
            pad = None
            if use_helper:
                got = self._pair_via_helper(jid, mac, by)
                if got is _HELPER_OLD:
                    use_helper = False
                    if self.bt is not None:
                        if not self._prepare_adapter(jid, via_helper=False):
                            return
                    else:
                        self._step(jid, "ready", "skip", "没有 bluetoothctl，跳过检查")
                else:
                    pad = got
            if not use_helper:
                restore = self._ensure_pairable(jid)      # only the fallback path temporarily turns on "bondable"
                pad = self._pair_via_configd(jid, mac)
            if pad is None:
                return
            if not self._mine(jid):
                self._fail(jid, None, "cancelled")
                return
        finally:
            if restore:
                try:
                    self.bt.pairable_off()
                    self.log.info("把蓝牙的「可绑定」改回原样（关）", cat="手柄")
                except Exception as e:  # noqa: BLE001
                    self.log.warn("没能把「可绑定」改回去", cat="手柄", step="pairable off", raw=str(e),
                                  hint="不要紧：只是别的设备也能来配对。重启鸭子会回到原样")
        self._after_pair(jid, pad)

    def _pair_via_helper(self, jid, mac, by):
        """Main path: the root helper runs the official robotctl pad pair. It stops btd and restarts Bluetooth first depending on the board marker.
        robotctl can't be stopped, so wait for it in a separate thread while ticking boxes with _tick_from_device (same as the configd path)."""
        with self._lk:
            self.wiz["via"] = "小助手（官方 robotctl pad pair：会先停 btd、重开蓝牙）"
        box = {}

        def call():
            try:
                box["r"] = self.helper.pad_pair(by or "Studio", mac=mac, timeout=self.w["pad_timeout"])
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=call, name="pad-helper-pair", daemon=True)
        t.start()
        while t.is_alive():
            t.join(self.w["status_job"])
            if self._cancel.is_set():
                self.log.info("页面点了停下；小助手那边的 robotctl 配对会自己做完（最多一两分钟），做完之前不能再配",
                              cat="手柄")
                self._fail(jid, "pair", "cancelled")
                return None
            if mac:
                self._tick_from_device(jid, mac)
        if "e" in box:
            e = box["e"]
            self._fail(jid, "pair", "other", f"{type(e).__name__}: {e}", retry=self.wiz.get("retry"))
            return None
        r = box.get("r")
        if not isinstance(r, tuple) or len(r) != 3:
            self._fail(jid, "pair", "other", f"小助手回的不是 (ok, result, detail)：{r!r}",
                       retry=self.wiz.get("retry"))
            return None
        ok, result, detail = r
        detail = detail if isinstance(detail, dict) else {}
        if result == "bad_verb":
            self.log.info("小助手是旧版，不认 pad-pair：改走后备配对", cat="手柄", raw=detail.get("msg"),
                          hint="重装新版小助手以后就能走官方 robotctl pad pair")
            self._helper_pad_ok = False
            with self._lk:
                self.wiz["via"] = None
            return _HELPER_OLD
        self._helper_pad_ok = True
        pair = detail.get("pair") if isinstance(detail.get("pair"), dict) else {}
        if ok and result == "paired" and pair.get("outcome") == "paired":
            pad = pair.get("pad") if isinstance(pair.get("pad"), dict) else {}
            self.log.info(f"小助手配好了：{pad.get('name')} {pad.get('mac')}", cat="手柄", dedup=False)
            return pad
        reason = detail.get("reason") or pair.get("reason") or "other"
        code = {"not_found": "not_found", "ambiguous": "ambiguous", "timeout": "timeout",
                "no_adapter": "no_adapter", "rejected": "rejected"}.get(reason, "other")
        if result == "timeout":
            code = "timeout"
        elif result == "no_robotctl":
            code = "no_robotctl"
        raw = "\n".join(str(x) for x in [detail.get("msg"), pair.get("detail")] +
                         list(detail.get("stderr") or []) if x)
        if reason == "rejected":
            sub = classify(raw)
            if sub in ("auth_failed", "key_missing", "le_abort", "dhkey", "pin", "not_bondable"):
                code = sub
        self._fail(jid, "pair", code, raw or result, retry=self.wiz.get("retry"))
        return None

    def _pair_via_configd(self, jid, mac):
        """The official pad.pair does it all at once: scan, agent, pair, trust (bluez.rs:853-1052). Blocking, with no progress,
        so wait for it in a separate thread while watching configd's pad.status and bluetoothctl's info, ticking each step as it succeeds."""
        if self.configd is None:
            return self._pair_via_bt(jid, mac, "configd_down", "这只鸭子没配 configd")
        with self._lk:
            self.wiz["via"] = "configd（官方 pad.pair）"
        params = {"timeout_seconds": int(self.w["pair_window"])}
        if mac:
            params["mac"] = mac
        box = {}
        limit = self.w["pair_window"] + PAIR_CALL_MARGIN_S

        def call():
            try:
                box["r"] = self.configd.call("pad.pair", params, limit)
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=call, name="pad-configd-pair", daemon=True)
        with self._lk:
            self._configd_thread, self._configd_until = t, self.clock() + limit
        t.start()
        while t.is_alive():
            t.join(self.w["status_job"])
            if self._cancel.is_set():
                self.log.info("页面点了停下；configd 那边的配对会自己做完（最多一两分钟），做完之前不能再配", cat="手柄")
                self._fail(jid, "pair", "cancelled")
                return None
            if mac:
                self._tick_from_device(jid, mac)
        if "e" in box:
            e = box["e"]
            if isinstance(e, RpcError) and e.code == 14:
                self.log.info("configd 不让 Studio 配对（只认 root），改用 bluetoothctl", cat="手柄", raw=str(e))
                return self._pair_via_bt(jid, mac, "permission", str(e))
            if isinstance(e, NoPermission):
                self.log.warn("Studio 没权限连 configd，改用 bluetoothctl", cat="手柄", raw=str(e), hint=ROBOT_GROUP)
                return self._pair_via_bt(jid, mac, "socket_perm", str(e))
            if isinstance(e, Unreachable):
                return self._pair_via_bt(jid, mac, "configd_down", str(e))
            if isinstance(e, Timeout):
                self._fail(jid, "pair", "timeout", str(e), retry=self.wiz.get("retry"))
                return None
            raw = getattr(e, "message", None) or str(e)
            self._fail(jid, "pair", classify(raw), raw, retry=self.wiz.get("retry"))
            return None
        r = box.get("r")
        if not isinstance(r, dict):
            self._fail(jid, "pair", "other", f"configd 回的不是对象：{r!r}")
            return None
        if r.get("outcome") == "paired":
            pad = r.get("pad") if isinstance(r.get("pad"), dict) else {}
            self.log.info(f"configd 配好了：{pad.get('name')} {pad.get('mac')}", cat="手柄", dedup=False)
            return pad
        reason, detail = r.get("reason"), r.get("detail")
        code = {"not_found": "not_found", "ambiguous": "ambiguous", "timeout": "timeout", "no_adapter": "no_adapter",
                "rejected": "rejected"}.get(reason, "other")
        if reason == "rejected":
            sub = classify(detail)          # the original rejection text often has a more specific reason (authentication failed, keys lost...)
            if sub in ("auth_failed", "key_missing", "le_abort", "dhkey", "pin", "not_bondable"):
                code = sub
        if reason == "not_found" and detail and "in range" in str(detail):
            code = "not_found_pad"
        self._fail(jid, "pair", code, f"{reason}：{detail}" if detail else reason, retry=self.wiz.get("retry"))
        return None

    def _pair_via_bt(self, jid, mac, why_code, why_raw):
        """configd refuses to pair (not root) or is missing: do it all ourselves in one bluetoothctl session (lesson from 10-15:
        typing separate commands gets rejected, it only works done in one go in the same session, 踩坑记录.md:272)."""
        bt = self.bt
        if bt is None or not mac:
            # Without a MAC we can't pair ourselves (don't know what to pair): report configd's reason
            self._fail(jid, "pair", why_code, why_raw, retry={"op": "scan", "seconds": SCAN_S} if not mac else self.wiz.get("retry"))
            return None
        with self._lk:
            self.wiz["via"] = "bluetoothctl（Studio 自己配：" + {"permission": "configd 不让 Studio 配",
                                                               "socket_perm": "Studio 连不上 configd（没权限）"}.get(why_code, "configd 不在") + "）"
        classic = next((d["classic"] for d in self.wiz.get("devices") or [] if d.get("mac") == mac), None)
        if classic is None:
            classic = isinstance(bt.info(mac).get("cls"), int)

        def step(key, state, note=None):
            if self._mine(jid):
                self._step(jid, key, state, note)

        try:
            try:
                bt.pair_device(mac, classic, self._cancel, step)
            except BtError as e:
                # 10-19 Duck #2: clicking "忘掉" (Forget) and immediately re-pairing, bluetoothctl 5.82 returned Failed to register agent object.
                # Close this session, open a new one, and try again (retry only once).
                if "Failed to register agent object" not in (e.raw or "") or self._cancel.is_set():
                    raise
                self.log.warn("bluetoothctl 注册代理失败：关掉会话，换一个新的再试一次", cat="手柄",
                              step="agent", raw=e.raw)
                try:
                    bt.close()
                except Exception:  # noqa: BLE001
                    pass
                bt.pair_device(mac, classic, self._cancel, step)
        except BtError as e:
            if self._cancel.is_set():
                self._fail(jid, "pair", "cancelled")
                return None
            key = next((s["key"] for s in self.wiz["steps"] if s["state"] == "doing"), "pair")
            self._fail(jid, key, e.code, e.raw, retry=self.wiz.get("retry"))
            return None
        finally:
            try:
                bt.close()
            except Exception:  # noqa: BLE001
                pass
        info = bt.info(mac)
        return {"mac": mac, "name": info.get("name"), "paired": info.get("paired", True),
                "trusted": info.get("trusted", True), "connected": info.get("connected", True)}

    def _tick_from_device(self, jid, mac):
        """While configd is pairing, watch whether Paired, Trusted, Connected changed in bluetoothctl info / pad.status."""
        info = {}
        if self.bt is not None:
            try:
                info = self.bt.info(mac) or {}
            except Exception:  # noqa: BLE001
                info = {}
        p = self._pad_in_status(mac) or {}
        if info.get("paired") or p.get("paired"):
            self._step(jid, "pair", "ok")
        if info.get("trusted") or p.get("trusted"):
            self._step(jid, "trust", "ok")
        if info.get("connected") or p.get("connected"):
            self._step(jid, "connect", "ok")

    def _after_pair(self, jid, pad):
        mac = (pad.get("mac") or "").upper()
        name = pad.get("name") or mac
        with self._lk:
            self.wiz.update(mac=mac or self.wiz.get("mac"), result_name=name)
        self._step(jid, "pair", "ok", name)
        if pad.get("trusted") is False:
            self._step(jid, "trust", "fail", FAILS["not_trusted"][0] + "：" + FAILS["not_trusted"][1])
        else:
            self._step(jid, "trust", "ok")
        # helper/configd may return a device that is bonded but whose Connect is still busy; reconnecting is limited in count and time, and doesn't delete keys or restart Bluetooth.
        tries, retry_at = 0, self.clock() + self.w["reconnect_after"]

        def reconnect(end):
            nonlocal tries, retry_at
            with self._lk:
                if not self._mine(jid):
                    self._fail(jid, None, "cancelled")
                    return False
                if self.tap_state == "attached" and not self._pair_input_matches(mac):
                    self._fail(jid, "padd", "wrong_input")
                    return False
                drv = (self._status or {}).get("driver") if isinstance(self._status, dict) else None
                if drv is not None and drv != "active":
                    self._fail(jid, "padd", "padd_down", f"padd 是 {drv}")
                    return False
                bus = (self._robot or {}).get("bus")
                if self._posture() in DRIVING or (isinstance(bus, dict) and bus.get("policy_enabled") is True):
                    self._fail(jid, None, "driving")
                    return False
                now = self.clock()
                if (tries >= 2 or now < retry_at or end <= now or not MAC_RE.fullmatch(mac)
                        or pad.get("trusted") is False or not callable(getattr(self.bt, "reconnect", None))):
                    return True
                tries += 1
                stage = self.wiz.get("phase")
            self._step(jid, stage, "doing", f"等待按键设备，尝试恢复连接（{tries}/2）…")
            try:
                self.bt.reconnect(mac, timeout=min(self.w["reconnect_timeout"], end - now))
            except BtError as e:
                self.log.info("手柄补连还未完成，继续等实际按键设备", cat="手柄", raw=e.raw)
            retry_at = self.clock() + self.w["reconnect_interval"]
            return True

        # Connection: when configd replies paired it may not be connected yet ("bonded; it will connect on its own", robotctl main.rs:4238-4247)
        self._step(jid, "connect", "doing", "等它连上…")
        with self._lk:
            connected = bool(pad.get("connected")) or self._pair_input_matches(mac)
        end = self.clock() + self.w["connect"]
        while not connected and self.clock() < end:
            if self._sleep(self.w["status_job"]):
                self._fail(jid, "connect", "cancelled")
                return
            self._poll_status()
            with self._lk:
                connected = bool((self._pad_in_status(mac) or {}).get("connected")) or self._pair_input_matches(mac)
            if not connected and not reconnect(end):
                return
            with self._lk:
                connected = connected or self._pair_input_matches(mac)
            if not self._mine(jid):
                self._fail(jid, "connect", "cancelled")
                return
        if not connected:
            self._fail(jid, "connect", "not_connected", f"{name} {mac}：pad.status 里 {self.w['connect']:g} 秒都没连上",
                       retry={"op": "pair", "mac": mac} if mac else None)
            return
        self._step(jid, "connect", "ok")
        # padd: only counts as recognized when configd says padd is active and the tap also sees it opened a gamepad
        self._step(jid, "padd", "doing", "等 padd 打开它…")
        with self._lk:
            self.wiz["phase"] = "padd"
        self._ensure_worker()
        end = self.clock() + self.w["padd"]
        while self.clock() < end:
            self._poll_status()
            drv = (self._status or {}).get("driver") if isinstance(self._status, dict) else None
            with self._lk:
                attached = self.tap_state == "attached"
                matching = self._pair_input_matches(mac)
                tap_dead = self.tap is None or self.tap_state in ("absent", "denied", "error")
            if drv is not None and drv != "active":
                self._fail(jid, "padd", "padd_down", f"padd 是 {drv}")
                return
            if attached:
                if not matching:
                    self._fail(jid, "padd", "wrong_input")
                    return
                break
            if tap_dead and drv == "active":
                self._step(jid, "padd", "ok", "padd 在跑；按键读不到（旁路没开），没法再核对")
                break
            if not reconnect(end):
                return
            if self._sleep(self.w["status_job"]):
                self._fail(jid, "padd", "cancelled")
                return
        else:
            # A real attached received during the last connect / sleep round is valid too, and must not be overwritten by a slightly later timer.
            with self._lk:
                matching = self._pair_input_matches(mac)
            if not matching:
                actual = self._pad_in_status(mac) or {}
                if not self._mine(jid):
                    code = "cancelled"
                else:
                    code = "not_connected" if actual.get("connected") is False else "no_input"
                self._fail(jid, "padd", code, f"{self.w['padd']:g} 秒里 padd 旁路没出现 attached（{self.tap_state}：{self.tap_why}）",
                           retry={"op": "pair", "mac": mac} if mac else None)
                return
            tap_dead = False
        self._pair_keys_ready(jid, mac, unverified=tap_dead)

    def _pair_input_matches(self, mac):
        """Only confirm success via the tap for this gamepad; another already-connected gamepad doesn't count. The caller holds _lk."""
        unique = str((self.live.device or {}).get("unique") or "").upper()
        return self.tap_state == "attached" and bool(mac) and unique == mac.upper()

    def _pair_keys_ready(self, jid, mac, *, unverified=False):
        with self._lk:
            if not self._mine(jid):
                self._fail(jid, None, "cancelled")
                return
            if self.tap_state == "attached":
                if not self._pair_input_matches(mac):
                    self._fail(jid, "padd", "wrong_input")
                    return
                unverified = False
            elif unverified and self.tap is not None and self.tap_state not in ("absent", "denied", "error"):
                self._fail(jid, "padd", "no_input")
                return
            if not unverified and not self._pair_input_matches(mac):
                self._fail(jid, "padd", "no_input")
                return
            dev = (self.live.device or {}).get("name")
            self._step(jid, "connect", "ok")
            if not unverified:
                self._step(jid, "padd", "ok", dev)
            self.live.seen = set()
            self.wiz.update(phase="keys", state="waiting", error=None, retry=None)
        self._step(jid, "keys", "doing")
        self.log.info(f"手柄配好、进入按键测试：{dev or mac}", cat="手柄", dedup=False)

    def _keys_tick(self):
        with self._lk:
            if self.wiz.get("phase") != "keys" or self.wiz.get("state") != "waiting":
                return
            seen = self.live.seen
            buttons = [r for r in seen if r not in ("ls", "rs")]
            enough = len(buttons) >= KEYS_NEED and "ls" in seen and "rs" in seen
        if enough:
            self._keys_done(manual=False)

    def _keys_done(self, manual):
        with self._lk:
            if self.wiz.get("phase") != "keys":
                raise Refused("现在不在按键测试这一步")
            n = len(self.live.seen)
            for s in self.wiz["steps"]:
                if s["key"] == "keys":
                    s["state"] = "ok"
                    s["note"] = f"按过 {n} 个" + ("（你点了完成）" if manual else "")
            self.wiz.update(state="done", error=None)
            if self.wiz.get("started") is not None:
                self.wiz["elapsed_s"] = self.clock() - self.wiz["started"]
        self.log.info(f"手柄按键测试完成（按过 {n} 个）", cat="手柄")
        return {}

    def _cancel_job(self):
        with self._lk:
            alive = self._job_alive()
            self._cancel.set()
        self._wake.set()
        if not alive and self.wiz.get("state") in ("waiting",):
            with self._lk:
                self._fail(self._job_id, None, "cancelled")
        return {}

    def _forget(self, mac, by=None):
        with self._lk:
            p = self._pad_in_status(mac) or {}
            if p.get("connected") and self._posture() in DRIVING:
                raise Refused("这个手柄正连着、鸭子在走：忘掉它，鸭子会马上停下（我们改过的 padd 还会坐下）。先点「停下（站好）」再忘掉")
        removed, via = None, None
        try:
            available = bool(self.helper.available())
        except Exception:  # noqa: BLE001
            available = False
        use_helper = self._helper_pad_ok is not False and available
        if not available:
            self._helper_pad_ok = False
        if use_helper:
            try:
                ok, result, detail = self.helper.pad_forget(by or "Studio", mac)
            except Exception as e:  # noqa: BLE001
                raise Refused(f"小助手没跑成：{type(e).__name__}: {e}") from None
            detail = detail if isinstance(detail, dict) else {}
            if result == "bad_verb":
                self.log.info("小助手是旧版，不认 pad-forget：改走 configd / bluetoothctl", cat="手柄",
                              raw=detail.get("msg"), hint="重装新版小助手以后就能走官方 robotctl pad forget")
                self._helper_pad_ok = False
            else:
                self._helper_pad_ok = True
                if not ok:
                    raise Refused(helper_api.friendly(result, detail, "pad-forget")) from None
                removed = detail.get("removed")
                if removed is None:
                    removed = True
                via = "小助手（官方 robotctl pad forget）"
        if removed is None and self.configd is not None:
            try:
                r = self.configd.call("pad.forget", {"mac": mac}, 5.0)
                removed, via = bool((r or {}).get("removed")), "configd"
            except RpcError as e:
                if e.code != 14:
                    raise Refused(f"configd 没删掉：{e.message}") from None
            except (Unreachable, Timeout):
                pass
        if removed is None and self.bt is not None:
            try:
                removed, via = self.bt.remove(mac), "bluetoothctl"
            except BtError as e:
                err = explain(e.code, e.raw)
                raise Refused(f"{err['msg']}：{err['fix']}") from None
        if removed is None:
            err = explain("permission")
            raise Refused(f"{err['msg']}：{err['fix']}（忘掉：sudo robotctl pad forget {mac}）")
        self.log.info(f"忘掉手柄 {mac}：{'删了' if removed else '鸭子本来就没记着'}（经 {via}）", cat="手柄", dedup=False,
                      hint="手柄自己还记着鸭子：要再配，先让手柄重新进配对状态")
        self._poll_status()
        return {"removed": removed}

    # ================= E-stop test =================
    #
    # Criteria (review 1):
    #   ① At the start, record how many times the "relax" at the top has been pressed (robotd.py's estop.press_count); passing requires it unchanged and no relax in progress;
    #   ② At the moment Select is pressed, ask busStatus ourselves once (recording "when asked" ourselves), requiring it was asked "after the press, before the release",
    #      and that torque is on (proving it wasn't already limp before: e.g. the top relax had already been confirmed, or an automatic relax after a fall);
    #   ③ Holding a full 2 seconds fails immediately: that's padd's "sit down and power off" (robot.shutdown), not an e-stop (padd main.rs:192-193, 725-739);
    #   ④ After release, ask busStatus ourselves every 0.25 seconds, and only accept torque confirmed OFF in a readback "asked after the release" (same criteria as the top relax: estop.py:43-61).

    def _estop_test(self, action):
        now = self.clock()
        if action == "cancel":
            with self._lk:
                if self.test.get("state") not in FINAL:
                    self.test = {"state": "idle"}
                    self.log.info("不测急停了（页面点了「不测了」）", cat="安全")
            self._test_evt.set()
            return {}
        if action != "start":
            raise Refused("测急停的指令只有 start / cancel")
        if self.robot is None:
            raise Refused("这只鸭子没配主程序的地址")
        with self._lk:
            if self._job_alive():
                raise Refused("正在配对：配完再测")
            if self.test.get("state") not in FINAL:
                raise Refused("已经在测了")
            checks = self._estop_checks(now, self._status_view(now))
            bad = next((c for c in checks["checks"] if c["ok"] is not True and c["key"] in ("pad", "padd", "robotd")), None)
            if bad or not checks["ok"]:
                c = bad or next(c for c in checks["checks"] if c["ok"] is not True)
                raise Refused(f"现在测不了：{c['label']} 这一条没通过（{c['why'] or '不知道'}）")
            if self.tap_state != "attached":
                raise Refused("读不到手柄按键（padd 旁路）：要先在这页看到手柄图跟着你按的键动")
            token = object()
            self.test = {"state": "need_torque", "started": now, "why": None, "fix": None, "ms": None,
                         "held_long": False, "failed_at": None, "_token": token, "_phase_at": now,
                         "_presses0": self._relax_presses, "_noted0": self._relax_noted, "_pressed_at": None, "_released_at": None,
                         "_on_while_pressed": None, "_press_err": None}
            self._test_evt.clear()
        self.log.info("开始测急停：先确认它上着力，再等你短按 Select", cat="安全", dedup=False,
                      ctx={"presses": self._relax_presses})
        threading.Thread(target=self._estop_runner, args=(token,), name="pad-estop-test", daemon=True).start()
        self._ensure_worker()
        return {}

    def _on_select(self, down, now):
        """Called from the tap thread holding the lock. Only changes state and wakes the e-stop test thread; doesn't ask robotd here."""
        t = self.test
        st = t.get("state")
        if down and st == "armed":
            t.update(state="pressed", _pressed_at=now, _on_while_pressed=None)
            self._test_evt.set()
        elif down and st == "need_torque":
            t["why"] = "还在确认它上着力：等第 2 步亮了再按 Select"
        elif not down and st == "pressed":
            t.update(state="released", _released_at=now)
            self.log.info(f"看到 Select 松开（按了 {now - t['_pressed_at']:.2f} 秒），等回读卸力", cat="安全")
            self._test_evt.set()

    def _probe_bus(self):
        """Ask busStatus ourselves once: (time asked, reply or None, error reason or None, time received)."""
        asked = self.clock()
        try:
            r = self.robot.call("robot.busStatus", {}, 2.0)
        except (Unreachable, Timeout, RpcError) as e:
            return asked, None, str(e), self.clock()
        return asked, (r if isinstance(r, dict) else None), (None if isinstance(r, dict) else "回的不是对象"), self.clock()

    def _test_fail(self, token, at, why, fix=None):
        with self._lk:
            t = self.test
            if t.get("_token") is not token or t.get("state") in FINAL:
                return
            t.update(state="failed", failed_at=at, why=why, fix=fix)
        self.log.warn(f"急停测试没通过：{why}", cat="安全", step=at, hint=fix)

    def _nap_test(self, s):
        """Wait a while; Select press / release and relax wake it up. self.test is the source of truth for state; events only wake it."""
        self._test_evt.wait(s)
        self._test_evt.clear()

    def _estop_runner(self, token):
        try:
            self._estop_loop(token)
        except Exception as e:  # noqa: BLE001
            self.log.error("测急停时 Studio 出错", cat="安全", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="这是 Studio 的问题，导出诊断包发出来；先用顶上的卸力或手柄 Select")
            self._test_fail(token, "studio", f"Studio 出错：{type(e).__name__}: {e}")

    def _estop_loop(self, token):  # noqa: C901
        w = self.w
        while not self._closing:
            with self._lk:
                t = self.test
                if t.get("_token") is not token or t.get("state") in FINAL:
                    return
                st, now = t["state"], self.clock()
                p0, pressed_at, released_at = t["_presses0"], t["_pressed_at"], t["_released_at"]
                relax_pressed = (self._relax_presses is not None and p0 is not None and self._relax_presses > p0) \
                    or self._relax_noted > t["_noted0"] or bool((self._robot or {}).get("estop_active"))
                if st == "pressed" and now - pressed_at > w["select_long"]:
                    t["held_long"] = True
            if relax_pressed:
                self._test_fail(token, "relax", "测的时候顶上的「卸力」（或别的页面的卸力）也按了：这次不算数",
                                "等它确认卸力后，按 Start 站起来，再点「再测一次」")
                return
            if st == "need_torque":
                if now - t["started"] > w["torque"]:
                    self._test_fail(token, "torque", f"{w['torque']:g} 秒没看到它上力", "按手柄 Start 让它站起来，再点「再测一次」")
                    return
                asked, bus, err, _ = self._probe_bus()
                if bus is not None and _torque_on(bus):
                    with self._lk:
                        if self.test is t and t["state"] == "need_torque":
                            t.update(state="armed", _phase_at=asked, why=None)
                    continue
                self._nap_test(w["probe"] * 2)
            elif st == "armed":
                if now - t["_phase_at"] > w["press"]:
                    self._test_fail(token, "press", f"{w['press']:g} 秒没看到 Select 按下",
                                    "按的是 Select 吗？Xbox 是「视图」键，Switch 是 −，PS 是 Create。按下时图上那颗键会变红")
                    return
                asked, bus, err, _ = self._probe_bus()
                with self._lk:
                    still = self.test is t and t["state"] == "armed"
                if still and bus is not None and (relaxed(bus) is True or torque_off(bus)):
                    self._test_fail(token, "early_off", "还没按 Select 扭矩就关了：可能是顶上的卸力、摔倒保护或别的程序",
                                    "按 Start 让它站起来，再点「再测一次」")
                    return
                self._nap_test(w["probe"] * 2)
            elif st == "pressed":
                if t["_on_while_pressed"] is None and t["_press_err"] is None:
                    asked, bus, err, _ = self._probe_bus()
                    with self._lk:
                        rel = t["_released_at"]
                        if asked >= pressed_at and (rel is None or asked <= rel):
                            if bus is None:
                                t["_press_err"] = err or "没回包"
                            else:
                                t["_on_while_pressed"] = _torque_on(bus)
                    continue
                if now - pressed_at >= w["shutdown_hold"]:
                    self._test_fail(token, "long", f"Select 按住满 {w['shutdown_hold']:g} 秒了：padd 发的是「坐下、卸力、关机」（robot.shutdown），"
                                    "不是急停。这次不算", "鸭子可能正在坐下关机：等它停稳（关机了就重新开机），再测一次，这回短按一下就松开")
                    return
                self._nap_test(0.05)
            elif st == "released":
                held = released_at - pressed_at
                if held >= w["shutdown_hold"]:
                    self._test_fail(token, "long", f"Select 按了 {held:.1f} 秒（满 {w['shutdown_hold']:g} 秒是「坐下关机」，不是急停）：这次不算",
                                    "再测一次：短按一下就松开")
                    return
                if t["_on_while_pressed"] is not True:
                    if t["_on_while_pressed"] is False:
                        self._test_fail(token, "pressed_off", "按着 Select 的时候扭矩已经关了：卸力不是松开 Select 触发的，这次不算",
                                        "按 Start 让它站起来，再点「再测一次」")
                    else:
                        self._test_fail(token, "pressed_unknown",
                                        f"按着 Select 的时候没读到扭矩（{t['_press_err'] or '按得太快，没来得及问'}）：这次不算",
                                        "再测一次：按下停半秒左右再松（别超过 1.5 秒）")
                    return
                if now - released_at > w["readback"]:
                    self._test_fail(token, "readback", f"松开 Select {w['readback']:g} 秒了，回读扭矩还没关",
                                    "padd 可能没把卸力转给主程序（看日志里 padd 那几行）。先用顶上的「卸力」或者关电源")
                    return
                asked, bus, err, got = self._probe_bus()
                if bus is not None and asked >= released_at and relaxed(bus) is True:
                    with self._lk:
                        if self.test is not t or t["state"] != "released":
                            return
                        relax_pressed = (self._relax_presses is not None and p0 is not None and self._relax_presses > p0) \
                            or self._relax_noted > t["_noted0"]
                        if not relax_pressed:
                            t.update(state="passed", ms=int((got - released_at) * 1000), why=None)
                    if relax_pressed:
                        continue
                    self.log.info(f"急停测过了：松开 Select 到回读卸力 {t['ms']} ms", cat="安全", dedup=False,
                                  ctx={"held_s": round(held, 2), "asked_after_release_ms": int((asked - released_at) * 1000)})
                    self._estop_passed_record()            # overview onboarding checklist step 4 (review O6: recorded at the moment passed is set)
                    return
                self._nap_test(w["probe"])
            else:
                return


def robot_view(rd, posture=None):
    """Fetch robotd's readback in the event loop and hand it to PadOps (don't read changing objects across threads). rd is studio.robotd.Robotd.
    Posture is computed per state.posture (same table); stale policies / state / health aren't used (state.py MAX_AGE)."""
    now = time.monotonic()

    def fresh(sample, key):
        age = sample.age(now)
        return sample.value if age is not None and age <= MAX_AGE[key] else None

    pol, st, health = fresh(rd.policies, "policies"), fresh(rd.state, "state"), fresh(rd.health, "health")
    if posture is None:
        posture = _posture(rd.present, rd.bus.value, pol, st)
    applied = ((st or {}).get("move") or {}).get("applied") if isinstance(st, dict) else None
    batt = ((health or {}).get("battery") or {}).get("percent") if isinstance(health, dict) else None
    return {"present": rd.present, "bus": rd.bus.value, "bus_at": rd.bus.at, "posture": posture,
            "state": st if isinstance(st, dict) else None, "state_at": rd.state.at,
            "policies_at": rd.policies.at,
            "policies": pol if isinstance(pol, dict) else None, "applied": applied, "battery_pct": batt,
            "estop_active": rd.estop.active, "estop_presses": rd.estop.press_count, "paused": rd.paused,
            "pad_status": rd.pad.value, "pad_status_at": rd.pad.at, "pad_status_error": rd.pad.error}


def _mask_mac(mac):
    """AA:BB:CC:DD:EE:FF → AA:BB:CC:… (the diagnostics bundle doesn't keep full addresses)."""
    m = str(mac or "")
    return (m[:8] + ":…") if len(m) >= 8 else m


def _mask_name(name):
    n = str(name or "")
    return (n[: max(1, len(n) // 2)] + "…") if len(n) > 2 else n


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------- Real ports: synchronous JSON-RPC (one object per line, lib.rs:9-12) ----------------

def _connect(addr, timeout):
    kind, *rest = parse_addr(addr)
    try:
        if kind == "unix":
            if not hasattr(socket, "AF_UNIX"):
                raise Unreachable("这台电脑的 Python 不支持 unix socket，地址改用 tcp:")
            path = rest[0]
            if not os.path.exists(path):
                raise Unreachable(f"{path} 不在")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.settimeout(timeout)
                s.connect(path)
            except BaseException:
                s.close()
                raise
            return s
        host, port = rest
        return socket.create_connection((host, port), timeout)
    except Unreachable:
        raise
    except PermissionError as e:
        raise NoPermission(f"没权限连 {addr}（{ROBOT_GROUP}）") from e
    except (ConnectionRefusedError, FileNotFoundError) as e:
        raise Unreachable(f"连不上 {addr}：拒绝连接") from e
    except socket.timeout:
        raise Timeout(f"{addr} {timeout:g} 秒没连上") from None
    except OSError as e:
        raise Unreachable(f"连不上 {addr}：{type(e).__name__}: {e}") from e


class _Lines:
    def __init__(self, sock):
        self.s, self.buf = sock, b""

    def readline(self, deadline):
        """One line (bytes); returns None if the other side closed; raises socket.timeout on timeout."""
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise socket.timeout()
            self.s.settimeout(left)
            chunk = self.s.recv(65536)
            if not chunk:
                return None
            self.buf += chunk
            if len(self.buf) > LINE_LIMIT:
                raise Unreachable(f"对方发来的一行太长（超过 {LINE_LIMIT} 字节）")
        line, _, self.buf = self.buf.partition(b"\n")
        return line


def rpc_call(addr, method, params=None, timeout=3.0):
    """Open a new connection, ask once, close it (pairing holds a connection for a minute or two, so it can't queue with other requests)."""
    deadline = time.monotonic() + timeout
    s = _connect(addr, timeout)
    try:
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        rd = _Lines(s)
        while True:
            line = rd.readline(deadline)
            if line is None:
                raise Unreachable("对方关了连接")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("id") != 1:
                continue
            if "error" in msg:
                err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                raise RpcError(method, err.get("code"), err.get("message", ""), err.get("data"))
            return msg.get("result")
    except socket.timeout:
        raise Timeout(f"{method} {timeout:g} 秒没回话") from None
    except (Unreachable, RpcError):
        raise
    except OSError as e:
        raise Unreachable(f"连接断了：{type(e).__name__}: {e}") from e
    finally:
        s.close()


class ConfigdPort:
    def __init__(self, addr="unix:/run/configd.sock"):
        self.addr = addr

    def call(self, method, params=None, timeout=3.0):
        return rpc_call(self.addr, method, params, timeout)


class RobotPort:
    """robot.move / head / mouth are notifications (no id, no reply, lib.rs:522-529), sent over one persistent connection; reconnect once if it drops.
    Ones that need a reply (init, enable, do, sound, busStatus...) open a new connection each time (rpc_call)."""

    def __init__(self, addr="unix:/run/robotd.sock"):
        self.addr = addr
        self._s = None
        self._lk = threading.Lock()

    def call(self, method, params=None, timeout=3.0):
        return rpc_call(self.addr, method, params, timeout)

    def notify(self, method, params):
        line = (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, separators=(",", ":")) + "\n").encode()
        with self._lk:
            for attempt in (1, 2):
                try:
                    if self._s is None:
                        self._s = _connect(self.addr, 1.0)
                    self._s.settimeout(1.0)
                    self._s.sendall(line)
                    return
                except (OSError, Unreachable, Timeout) as e:
                    self._close()
                    if attempt == 2:
                        raise e if isinstance(e, (Unreachable, Timeout)) else Unreachable(f"{type(e).__name__}: {e}")

    def _close(self):
        if self._s is not None:
            try:
                self._s.close()
            except OSError:
                pass
        self._s = None


class PaddTap:
    """padd tap: send pad.input once, then keep reading pad.report (tap.rs:536-599). Reconnect 2 seconds after a drop (same as robotctl monitor).
    Unexpected errors in the callback or parsing: log and reconnect; the thread must not silently exit (review 15)."""

    def __init__(self, addr="unix:/run/padd/pad.sock", reconnect_s=2.0, log=None):
        self.addr, self.reconnect_s, self.log = addr, reconnect_s, log
        self._stop = threading.Event()
        self._t = None
        self._s = None

    def start(self, on_report, on_state):
        self.stop()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, args=(on_report, on_state, self._stop), name="pad-tap", daemon=True)
        self._t.start()

    def alive(self):
        return self._t is not None and self._t.is_alive() and not self._stop.is_set()

    def stop(self):
        self._stop.set()
        s = self._s
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def _loop(self, on_report, on_state, stop):
        while not stop.is_set():
            try:
                self._once(on_report, on_state, stop)
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log.error("读手柄按键的线程出错，2 秒后重连", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True,
                                   hint="这是 Studio 的问题，导出诊断包发出来")
                try:
                    on_state("error", f"Studio 出错：{type(e).__name__}: {e}")
                except Exception:  # noqa: BLE001
                    pass
            stop.wait(self.reconnect_s)

    def _once(self, on_report, on_state, stop):
        try:
            s = _connect(self.addr, 2.0)
        except NoPermission as e:
            on_state("denied", str(e))
            return
        except Unreachable:
            on_state("absent", "连不上 padd 的按键旁路（/run/padd/pad.sock）：padd 可能没在跑，或者这版 padd 没开旁路；网页上看不到实时按键，手柄本身照常能用")
            return
        except Timeout as e:
            on_state("error", str(e))
            return
        self._s = s
        try:
            s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"pad.input","params":{}}\n')
            on_state("waiting", None)
            rd = _Lines(s)
            while not stop.is_set():
                try:
                    line = rd.readline(time.monotonic() + 1.0)
                except socket.timeout:
                    continue
                if line is None:
                    on_report({"report": "detached", "why": "padd 关了旁路"})
                    break
                # The gamepad's built-in IMU (like the G50 Pro): while someone is subscribed padd pushes every batch of IMU data (fork padd tap.rs:506-528),
                # which we don't need. Skip it by string before parsing (serde internal tag "report":"imu", lib.rs:4609-4635; imu_attached is unaffected):
                # dozens of lines per second, each json.loads'd and then thrown away, is wasted CPU (overview reshuffle review O12)
                if b'"report":"imu"' in line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("id") == 1 and "error" in msg:
                    err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                    on_state("error", f"padd 拒绝了订阅：{err.get('message')}")
                    break
                if msg.get("method") == "pad.report" and isinstance(msg.get("params"), dict):
                    on_report(msg["params"])
        except (OSError, Unreachable) as e:
            if not stop.is_set():
                on_state("error", f"旁路断了：{e}")
        finally:
            self._s = None
            try:
                s.close()
            except OSError:
                pass


# ---------------- Real Bluetooth: bluetoothctl ----------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x01\x02]")
_PROMPT = re.compile(r"^(?:\[[^\]\[]*\][#>]\s*)+")
_EVENT = re.compile(r"^\[(NEW|CHG|DEL)\]\s+Device\s+([0-9A-Fa-f:]{17})\s*(.*)$")
_PROP = re.compile(r"^\s*([A-Za-z][A-Za-z ]*?):\s*(.*)$")
_ASK_YES = re.compile(r"\(yes/no\)")
_ASK_KINDS = ("Accept pairing", "Authorize service", "Request authorization")
_ASK_PIN = re.compile(r"Enter PIN code|Enter passkey|Confirm passkey", re.I)
BT_FAIL = r"Failed|not available|No default controller|Invalid command|org\.bluez\.Error\.(?!AlreadyExists|AlreadyConnected)|Enter PIN code|Enter passkey|Confirm passkey"
BT_ENV = {**os.environ, "LC_ALL": "C", "TERM": "dumb"}


def clean_line(raw):
    """Strip colors, carriage returns, and prompts (bluetoothctl squeezes the prompt and output onto one line even in a pipe)."""
    line = _ANSI.sub("", raw or "").replace("\r", "").strip()
    return _PROMPT.sub("", line).strip()


def _yes(v):
    return None if v is None else str(v).strip().lower().startswith("yes")


def _num(v):
    if v is None:
        return None
    m = re.search(r"\((-?\d+)\)", str(v)) or re.search(r"(-?0x[0-9a-fA-F]+|-?\d+)", str(v))
    if not m:
        return None
    s = m.group(1)
    try:
        n = int(s, 16) if "0x" in s.lower() else int(s)
    except ValueError:
        return None
    return n


def parse_props(text):
    """`bluetoothctl info / show` "key: value" lines → dict (keys lowercased). UUIDs collected into a list."""
    out = {"uuids": []}
    for raw in (text or "").splitlines():
        line = clean_line(raw)
        m = _PROP.match(line)
        if not m:
            continue
        k, v = m.group(1).strip().lower(), m.group(2).strip()
        if k == "uuid":
            out["uuids"].append(v)
        elif k not in out:
            out[k] = v
    return out


def device_from_props(mac, p):
    rssi = _num(p.get("rssi"))
    if isinstance(rssi, int) and rssi > 0x7FFFFFFF:
        rssi -= 1 << 32
    return {"mac": mac.upper(), "name": p.get("name"), "alias": p.get("alias"), "icon": p.get("icon"),
            "cls": _num(p.get("class")), "appearance": _num(p.get("appearance")), "rssi": rssi,
            "paired": _yes(p.get("paired")), "trusted": _yes(p.get("trusted")), "connected": _yes(p.get("connected"))}


def _rfkill_blocked(base):
    """True: Bluetooth is turned off by rfkill; False: there's a Bluetooth rfkill and it's not off; None: not found."""
    try:
        names = os.listdir(base)
    except OSError:
        return None
    found = None
    for n in names:
        try:
            if _read_text(os.path.join(base, n, "type")).strip() != "bluetooth":
                continue
            soft = _read_text(os.path.join(base, n, "soft")).strip()
            hard = _read_text(os.path.join(base, n, "hard")).strip()
        except OSError:
            continue
        found = bool(found) or soft == "1" or hard == "1"
    return found


def _run(argv, timeout=8.0):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=BT_ENV, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, f"没有这个命令：{argv[0]}"
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        return 124, f"{' '.join(argv)} {timeout:g} 秒没结束：{out[-300:]}"


def _spawn(argv):
    # Binary pipe, unbuffered: read in chunks and split lines ourselves (the agent's questions are prompts without newlines, so reading by line would hang: review 4)
    return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            bufsize=0, env=BT_ENV)


class BtSession:
    """A persistent bluetoothctl: scanning, or pairing, trusting, and connecting all in the same client (the approach of the original board-side tool;
    on 10-15 typing separate commands was rejected, 踩坑记录.md:272).

    Agent (review 5): bluetoothctl may register a default agent by itself as soon as it starts, so the session starts with agent off; scanning needs no agent;
    only during pair_device register NoInputNoOutput, take the default agent, auto-answer yes, and agent off to hand it back after pairing (configd also only takes it within the pairing window:
    configd bluez.rs:995-1013)."""

    def __init__(self, argv, spawn=None):
        self.p = (spawn or _spawn)(argv)
        self.cv = threading.Condition()
        self.lines = deque(maxlen=4000)
        self.seq = 0
        self.devices = {}
        self.closed = False
        self.discovering = False     # as soon as bluetoothctl opens it [NEW]s all cached devices: those before the scan starts don't count as "seen"
        self.answer_yes = False      # only auto-answer yes within the pairing window
        self.asked = []              # what the agent asked and how it was answered (written to the log on error)
        self._tail_answered = False
        self._quit = False
        self._t = threading.Thread(target=self._reader, name="bt-session", daemon=True)
        self._t.start()

    def _chunks(self):
        out = self.p.stdout
        try:
            fd = out.fileno()
        except (AttributeError, OSError, ValueError):
            fd = None
        if fd is not None:
            dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while True:
                try:
                    b = os.read(fd, 4096)
                except OSError:
                    return
                if not b:
                    tail = dec.decode(b"", final=True)
                    if tail:
                        yield tail
                    return
                yield dec.decode(b)
        else:
            for x in out:                         # fake process in tests: strings in chunks (not necessarily by line)
                yield x.decode("utf-8", "replace") if isinstance(x, bytes) else x

    def _reader(self):
        buf = ""
        try:
            for chunk in self._chunks():
                buf += chunk
                parts = buf.split("\n")
                buf = parts.pop()
                with self.cv:
                    for raw in parts:
                        line = clean_line(raw)
                        answered, self._tail_answered = self._tail_answered, False
                        if line:
                            self._add(line, prompt_done=answered)
                    tail = clean_line(buf)
                    if tail and not self._tail_answered and (_ASK_YES.search(tail) or _ASK_PIN.search(tail)):
                        # no newline after the prompt: we can't wait for this line to end, answer now (review 4)
                        self._tail_answered = True
                        self._add(tail, prompt_done=False)
                    self.cv.notify_all()
                if len(buf) > 65536:
                    buf = buf[-4096:]
        except (OSError, ValueError):
            pass
        with self.cv:
            self.closed = True
            self.cv.notify_all()

    def _add(self, line, prompt_done):
        self.seq += 1
        self.lines.append((self.seq, line))
        if not prompt_done:
            self._event(line)

    def _event(self, line):
        if re.search(r"Discovery started|Controller .*Discovering: yes", line):
            self.discovering = True
        elif re.search(r"Discovery stopped|Controller .*Discovering: no", line):
            self.discovering = False
        m = _EVENT.match(line)
        if m:
            what, mac, rest = m.group(1), m.group(2).upper(), m.group(3)
            if what == "DEL":
                self.devices.pop(mac, None)
                return
            d = self.devices.setdefault(mac, {"mac": mac})
            pm = _PROP.match(rest)
            if self.discovering or (pm and pm.group(1).strip().lower() == "rssi"):
                d["seen_at"] = time.monotonic()
            if what == "CHG" and pm:
                k, v = pm.group(1).strip().lower(), pm.group(2).strip()
                if k == "rssi":
                    n = _num(v)
                    d["rssi"] = n - (1 << 32) if isinstance(n, int) and n > 0x7FFFFFFF else n
                elif k == "class":
                    d["cls"] = _num(v)
                elif k == "appearance":
                    d["appearance"] = _num(v)
                elif k in ("paired", "trusted", "connected", "bonded"):
                    d[k] = _yes(v)
                elif k in ("name", "alias", "icon"):
                    d[k] = v
            elif what == "NEW" and rest and not re.match(r"^[0-9A-Fa-f]{2}[-:]", rest):
                d.setdefault("name", rest)
            return
        # Agent questions: only within the pairing window agree to pairing and authorize services; otherwise always answer no. Ones needing a PIN are treated as failure by expect (pin)
        if _ASK_YES.search(line) and any(k in line for k in _ASK_KINDS):
            ans = "yes" if self.answer_yes else "no"
            self.asked.append(f"{line} → {ans}")
            try:
                self.send(ans)
            except BtError:
                pass
        elif _ASK_YES.search(line) and _ASK_PIN.search(line):
            self.asked.append(f"{line} → no")
            try:
                self.send("no")
            except BtError:
                pass

    def send(self, cmd):
        try:
            self.p.stdin.write((cmd + "\n").encode("utf-8"))
            self.p.stdin.flush()
        except (OSError, ValueError, AttributeError) as e:
            raise BtError("bluez_down", f"bluetoothctl 已经退出：{e}") from None

    def expect(self, ok, fail=BT_FAIL, timeout=8.0, since=None, cancel=None):
        since = self.seq if since is None else since
        end = time.monotonic() + timeout
        ok_re, fail_re = re.compile(ok, re.I), re.compile(fail, re.I) if fail else None
        with self.cv:
            while True:
                for n, line in list(self.lines):
                    if n <= since:
                        continue
                    since = n
                    if ok_re.search(line):
                        return line
                    if fail_re and fail_re.search(line):
                        raise BtError(classify(line), line)
                if self.closed:
                    raise BtError("bluez_down", "bluetoothctl 退出了")
                if cancel is not None and cancel.is_set():
                    raise BtError("cancelled", "页面点了停下")
                left = end - time.monotonic()
                if left <= 0:
                    raise BtError("timeout", f"{timeout:g} 秒没等到：{ok}")
                self.cv.wait(min(left, 0.2))

    def cmd(self, text, ok, fail=BT_FAIL, timeout=8.0, cancel=None):
        since = self.seq
        self.send(text)
        return self.expect(ok, fail, timeout, since, cancel)

    def _wait(self, t):
        try:
            self.p.wait(t)
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:  # noqa: BLE001
            return True

    def close(self):
        """quit → close stdin → wait 2 seconds → terminate (sudo forwards SIGTERM to bluetoothctl, but not SIGKILL: review 6) → wait 1 second → kill → wait."""
        if self._quit:
            return
        self._quit = True
        try:
            self.send("quit")
        except BtError:
            pass
        try:
            self.p.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        if self._wait(2.0):
            return
        for fn in ("terminate", "kill"):
            try:
                getattr(self.p, fn)()
            except Exception:  # noqa: BLE001
                pass
            if self._wait(1.0):
                return


class BluetoothCtl:
    """The real implementation of BluetoothPort: bluetoothctl (ships with BlueZ) + /sys/class/rfkill. prefix can be ("sudo", "-n"):
    then the session is sudo -n stdbuf -oL bluetoothctl (stdbuf goes after sudo: before it doesn't take effect on setuid sudo, review 6)."""

    def __init__(self, run=_run, spawn=None, prefix=(), rfkill_dir="/sys/class/rfkill", exe="bluetoothctl", stdbuf=None):
        self.run, self.spawn, self.prefix, self.rfkill_dir, self.exe = run, spawn, tuple(prefix), rfkill_dir, exe
        self.stdbuf = bool(shutil.which("stdbuf")) if stdbuf is None else stdbuf
        self.t = {"pair": 30.0, "connect": 20.0, "trust": 8.0, "find": 15.0, "settle": 8.0}    # max wait for each step (shortened in tests)
        self._session = None
        self._lk = threading.Lock()

    def _argv(self, *a):
        return [*self.prefix, self.exe, *a]

    def _session_argv(self):
        return [*self.prefix, *(("stdbuf", "-oL") if self.stdbuf else ()), self.exe]

    def adapter(self):
        blocked = _rfkill_blocked(self.rfkill_dir)
        rc, out = self.run(self._argv("show"), 6.0)
        text = "\n".join(clean_line(x) for x in out.splitlines())
        if rc == 127:
            return {"present": False, "error": None, "blocked": blocked, "raw": text, "missing": True}
        if re.search(r"AccessDenied|Access denied", text):
            return {"present": None, "error": text, "code": "bt_permission", "blocked": blocked, "raw": text}
        # bluetoothd isn't running: bluetoothctl keeps saying "Waiting to connect to bluetoothd..." until timeout (review 17: not a missing adapter)
        if re.search(r"Waiting to connect to bluetoothd|org\.bluez was not provided|ServiceUnknown", text):
            return {"present": None, "error": text[-400:], "code": "bluez_down", "blocked": blocked, "raw": text[-400:]}
        if "No default controller" in text or "Controller" not in text:
            return {"present": False, "blocked": blocked, "raw": text[-400:]}
        p = parse_props(text)
        return {"present": True, "powered": _yes(p.get("powered")), "pairable": _yes(p.get("pairable")),
                "discovering": _yes(p.get("discovering")), "blocked": blocked, "raw": text[-400:]}

    def _simple(self, ok, *a, timeout=8.0):
        rc, out = self.run(self._argv(*a), timeout)
        text = clean_line(out.replace("\n", " "))
        if re.search(ok, out, re.I):
            return out
        raise BtError(classify(out) if rc != 124 else "timeout", text[-400:])

    def power_on(self):
        return self._simple(r"Changing power on succeeded|Powered: yes", "power", "on")

    def pairable_on(self):
        return self._simple(r"Changing pairable on succeeded|Pairable: yes", "pairable", "on")

    def pairable_off(self):
        return self._simple(r"Changing pairable off succeeded|Pairable: no", "pairable", "off")

    def info(self, mac):
        rc, out = self.run(self._argv("info", mac), 5.0)
        if rc != 0 or "not available" in out:
            return {}
        return device_from_props(mac, parse_props(out))

    def reconnect(self, mac, timeout=5.0):
        """Only restore the connection of an already-paired target; doesn't register a pairing agent, scan, or delete existing bonds."""
        if not isinstance(mac, str) or not MAC_RE.fullmatch(mac):
            raise BtError("other", "手柄地址不对")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise BtError("timeout", "没有剩余的重连时间")
        return self._simple(rf"Connection successful|AlreadyConnected|Device {re.escape(mac)} Connected: yes",
                            "connect", mac, timeout=min(timeout, self.t["connect"]))

    def _open(self):
        with self._lk:
            if self._session is None or self._session.closed:
                s = BtSession(self._session_argv(), self.spawn)
                self._session = s
                try:
                    # It may have registered a default agent by itself at startup: remove it first (scanning needs no agent)
                    s.cmd("agent off", r"Agent unregistered|No agent is registered|Agent is not registered|not registered",
                          fail=None, timeout=2.0)
                except BtError:
                    pass
            return self._session

    def scan_start(self):
        s = self._open()
        try:
            s.cmd("scan on", r"Discovery started|Discovering: yes", timeout=8.0)
        except BtError:
            self.close()          # if it can't start, close this session and open a new one next time (review 6)
            raise

    def scan_stop(self):
        s = self._session
        if s is not None and not s.closed:
            try:
                s.cmd("scan off", r"Discovery stopped|Discovering: no", fail=None, timeout=5.0)
            except BtError:
                pass

    def devices(self):
        """Devices seen in the session; name, class, etc. are queried via info once on first sight."""
        s = self._session
        if s is None:
            return []
        with s.cv:
            snap = {k: dict(v) for k, v in s.devices.items()}
        out = []
        for mac, d in snap.items():
            if "_info" not in s.devices.get(mac, {}):
                info = self.info(mac)
                with s.cv:
                    if mac in s.devices:
                        s.devices[mac]["_info"] = info
            info = s.devices.get(mac, {}).get("_info") or {}
            merged = {**info, **{k: v for k, v in d.items() if v is not None and not k.startswith("_")}}
            out.append(merged)
        return out

    def pair_device(self, mac, classic, cancel, step):
        """Do it all in one session. Classic Bluetooth (Switch Pro style): pair → trust → connect (the order that worked for the G50 on 10-15);
        LE (Xbox): connect first (connecting bonds by itself, wait at most 5 seconds) → if not bonded, pair → trust → connect again (bluez.rs:713-795).
        The success indicators are all locked to this MAC (review 11): Paired / Connected of other devices don't count."""
        s = self._open()
        m = re.escape(mac)
        try:
            try:
                try:
                    s.cmd("agent NoInputNoOutput", r"Agent registered", fail=BT_FAIL + r"|already registered", timeout=5.0)
                except BtError as e:
                    # bluetoothctl 5.82 only registers its default agent after connecting to bluetoothd: the agent off at session start came too early (it replied "No agent is
                    # registered", and only then did its own agent get registered), so here we hit "Agent is already registered" (10-19 Duck #2). Remove it and register again
                    if "already registered" not in (e.raw or ""):
                        raise
                    s.cmd("agent off", r"Agent unregistered", timeout=3.0)
                    s.cmd("agent NoInputNoOutput", r"Agent registered", fail=BT_FAIL + r"|already registered", timeout=5.0)
                s.cmd("default-agent", r"Default agent request successful", timeout=5.0)
            except BtError as e:
                raise BtError("agent" if e.code in ("other", "timeout") else e.code, e.raw) from None
            s.answer_yes = True
            if mac not in s.devices:
                s.cmd("scan on", r"Discovery started|Discovering: yes", timeout=8.0)
                try:
                    s.expect(rf"Device {m}", fail=None, timeout=self.t["find"], since=0, cancel=cancel)
                except BtError as e:
                    if e.code == "timeout":
                        raise BtError("not_found", f"搜了 {self.t['find']:g} 秒没看到 {mac}：手柄退出配对状态了？") from None
                    raise
            try:
                s.cmd("scan off", r"Discovery stopped|Discovering: no", fail=None, timeout=5.0)
            except BtError:
                pass
            ok_pair = rf"Pairing successful|AlreadyExists|Device {m} (Paired|Bonded): yes"
            if not classic:
                step("connect", "doing", "Xbox 这类先连接，连上会自己配对")
                try:
                    s.cmd(f"connect {mac}", rf"Connection successful|AlreadyConnected|Device {m} Connected: yes",
                          timeout=self.t["connect"], cancel=cancel)
                except BtError as e:
                    if e.code == "cancelled":
                        raise
                try:
                    s.expect(rf"Device {m} (Paired|Bonded): yes", fail=None, timeout=5.0, since=0, cancel=cancel)
                    step("pair", "ok")
                except BtError as e:
                    if e.code == "cancelled":
                        raise
            if not (s.devices.get(mac, {}).get("paired")):
                step("pair", "doing")
                s.cmd(f"pair {mac}", ok_pair, timeout=self.t["pair"], cancel=cancel)
            step("pair", "ok")
            step("trust", "doing")
            s.cmd(f"trust {mac}", rf"{m} trust succeeded|Device {m} Trusted: yes", timeout=self.t["trust"], cancel=cancel)
            step("trust", "ok")
            step("connect", "doing")
            ok_conn = rf"Connection successful|AlreadyConnected|Device {m} Connected: yes"
            mark = s.seq
            try:
                s.cmd(f"connect {mac}", ok_conn, timeout=self.t["connect"], cancel=cancel)
            except BtError as e:
                # Just paired, and the classic Bluetooth gamepad is also connecting to the duck on its own: BlueZ returns InProgress (br-connection-busy, 10-19 Duck #2 G50 Pro).
                # Wait for it to connect by itself first; if that doesn't happen, connect once more
                if e.code != "busy":
                    raise
                step("connect", "doing", "手柄自己也在连，等它一下")
                try:
                    s.expect(rf"Device {m} Connected: yes", fail=None, timeout=self.t["settle"], since=mark, cancel=cancel)
                except BtError as e2:
                    if e2.code != "timeout":
                        raise
                    s.cmd(f"connect {mac}", ok_conn, timeout=self.t["connect"], cancel=cancel)
            step("connect", "ok")
        finally:
            s.answer_yes = False
            try:
                s.cmd("agent off", r"Agent unregistered|No agent is registered|not registered", fail=None, timeout=3.0)
            except BtError:
                pass

    def remove(self, mac):
        rc, out = self.run(self._argv("remove", mac), 8.0)
        if "Device has been removed" in out:
            return True
        if "not available" in out:
            return False
        raise BtError(classify(out), clean_line(out.replace("\n", " "))[-400:])

    def close(self):
        with self._lk:
            s, self._session = self._session, None
        if s is not None:
            s.close()


def default_pad(log, configd_addr="unix:/run/configd.sock", robotd_addr="unix:/run/robotd.sock",
                tap_addr="unix:/run/padd/pad.sock", bt_prefix=(), state_dir=None):
    """Default wiring on the duck (used by app.py / __main__.py). Machines without bluetoothctl (computers) get no Bluetooth port."""
    bt = BluetoothCtl(prefix=bt_prefix) if shutil.which("bluetoothctl") else None
    from .audio_interaction import AudioClient
    return PadOps(log, configd=ConfigdPort(configd_addr), bt=bt, tap=PaddTap(tap_addr, log=log),
                  robot=RobotPort(robotd_addr), state_dir=state_dir, audio=AudioClient(),
                  mapping_client=MappingClient())
