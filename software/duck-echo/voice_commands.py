"""Exact Chinese posture commands over the existing robotd JSON-RPC contract."""
import json
import math
import re
import socket
import time
import os
import stat
import threading
from pathlib import Path
from contextlib import contextmanager
from pad_mapping import PAD_MAPPING

UPDATE_MARKER=Path('/run/microduck-updater/installing')
NATIVE_JOURNAL='/var/lib/microduck-helper/native-update/journal.json'
NATIVE_EXCLUSIONS=('/var/lib/microduck-helper/native-update/active',
    '/run/microduck-helper/native-update-restore', *(
    '/etc/systemd/system/'+unit+'.service.d/zzzzzzz-microduck-native-update.conf'
    for unit in ('robotd','padd','gamesir-xboxd','duck-echo')))


class NativeUpdateGuard:
    """Standalone mirror of helper.native_update_state's public busy contract.

    Never imports managed Studio code or runs sudo in the audio path. Metadata
    changes invalidate a bounded JSON cache, including atomic journal replacement.
    Contract tests compare every journal flag and exclusion with the helper.
    """
    def __init__(self, root='/'):
        self.root=Path(root)
        parts=NATIVE_JOURNAL.strip('/').split('/')
        self.parents=[self.root.joinpath(*parts[:i]) for i in range(1,len(parts))]
        self.path=self.root/NATIVE_JOURNAL.lstrip('/')
        self.exclusions=[self.root/p.lstrip('/') for p in NATIVE_EXCLUSIONS]
        self.key=None;self.busy=False;self.lock=threading.Lock()

    def active(self):
        with self.lock:
            try:
                metadata=[]
                for path in (*self.parents,self.path,*self.exclusions):
                    try:
                        st=path.lstat()
                        metadata.append((st.st_mode,st.st_uid,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns))
                    except FileNotFoundError: metadata.append(None)
                key=tuple(metadata)
                if key==self.key:return self.busy
                self.busy=self._read(metadata)
                self.key=key
                return self.busy
            except (OSError,ValueError,TypeError,AttributeError,RecursionError):
                self.key=None;self.busy=True;return True

    def _read(self, metadata):
        journal=metadata[len(self.parents)]
        exclusions=any(item is not None for item in metadata[len(self.parents)+1:])
        for index,entry in enumerate(metadata[:len(self.parents)+1]):
            if entry is None:continue
            mode,uid,*_=entry
            kind=stat.S_ISREG if index==len(self.parents) else stat.S_ISDIR
            if not kind(mode) or (self.root==Path('/') and os.name=='posix' and (uid!=0 or mode&0o022)):
                return True
        if journal is None:return exclusions
        if journal[3]>65536:return True
        descriptor=os.open(self.path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(descriptor,'rb') as stream:
            raw=stream.read(65537)
        if len(raw)>65536:return True
        value=json.loads(raw)
        if (not isinstance(value,dict) or value.get('schema')!='microduck-native-update/1'
            or type(value.get('active')) is not bool
            or type(value.get('restore_pending',False)) is not bool
            or type(value.get('cleanup_pending',False)) is not bool
            or not re.fullmatch(r'[0-9a-f]{32}',value.get('transaction_id',''))
            or value.get('phase') not in ('prepared','guarding','guarded','replacing','replaced','verified_commissioning',
                'restoring_normal','verified_motion','factory_handoff_pending','completed','rolled_back',
                'recovering','old_restored','recovery_required')
            or (value.get('reason') is not None and (not isinstance(value['reason'],str) or len(value['reason'])>300))):
            return True
        return value['active'] or value.get('restore_pending',False) or value.get('cleanup_pending',False) or exclusions


NATIVE_GUARD=NativeUpdateGuard()

class UpdateLocked(RuntimeError): pass

def updates_allowed(): return not UPDATE_MARKER.exists() and not NATIVE_GUARD.active() and not PAD_MAPPING.blocked()

@contextmanager
def motion_lease(marker=UPDATE_MARKER,lock=None):
    """Finish existing actions before root's EX preflight; reject new actions."""
    marker=Path(marker);lock=Path(lock) if lock else marker.parent/'motion.lock'
    if PAD_MAPPING.blocked():raise UpdateLocked('controller mapping in progress')
    if marker.exists() or NATIVE_GUARD.active():raise UpdateLocked('software / native update in progress')
    descriptor=None
    try:
        try:descriptor=os.open(lock,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        except FileNotFoundError:
            # Legacy installation without the updater has no update lease yet.
            if marker.exists() or NATIVE_GUARD.active():raise UpdateLocked('software / native update in progress')
        if descriptor is not None:
            import fcntl
            try:fcntl.flock(descriptor,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise UpdateLocked('software update in progress') from None
        if marker.exists() or NATIVE_GUARD.active():raise UpdateLocked('software / native update in progress')
        if PAD_MAPPING.blocked():raise UpdateLocked('controller mapping in progress')
        yield
    finally:
        if descriptor is not None:os.close(descriptor)


# ---------------- Actions voice can perform ----------------
# Names are kept consistent with the phone web console's web/m/actions.js: the onboard path's recognition result (audio.last.command)
# is directly a key here, and the page looks it up in CMD_CN to display the Chinese name.
SKILL_COMMANDS = {'roulade': 'roulade', 'ground_pick': 'ground_pick'}   # robot.do {skill}
SOUND_COMMANDS = {'chirp': 'chirp', 'greet': 'greet'}                   # robot.sound {tag}
HEAD_COMMANDS = ('nod', 'shake', 'tilt')                                # robot.head notifications
ALL_COMMANDS = ('sit', 'stand', 'walk', 'stop', 'roulade', 'ground_pick',
                'chirp', 'greet', 'nod', 'shake', 'tilt')

# Bare ONNX files the user uploaded on Studio's "Model" page: command name → robotd skill name (custom_xxxxxxxx).
# The model library is in this machine's state directory; if it cannot be read, treat it as absent rather than taking the whole voice pipeline down.
CUSTOM_MODELS = Path('/var/lib/microduck-studio/models')
_CUSTOM_TTL_S = 1.0
_custom_cache = {'at': -1e9, 'value': {}}
_custom_lock = threading.Lock()


def custom_skills():
    now = time.monotonic()
    with _custom_lock:
        if now - _custom_cache['at'] < _CUSTOM_TTL_S:
            return dict(_custom_cache['value'])
    found = {}
    try:
        for child in CUSTOM_MODELS.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            meta = child / '.studio-model.json'
            try:
                if meta.is_symlink() or meta.stat().st_size > 64 << 10:
                    continue
                record = json.loads(meta.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or record.get('kind') != 'custom':
                continue
            command, skill = record.get('command'), record.get('skill')
            if (isinstance(command, str) and command.strip() and len(command.strip()) <= 20
                    and isinstance(skill, str) and re.fullmatch(r'custom_[a-f0-9]{8}', skill)
                    and (child / 'policy.onnx').is_file()):
                found[command.strip()] = skill
    except OSError:
        found = {}
    with _custom_lock:
        _custom_cache['at'] = now
        _custom_cache['value'] = found
    return dict(found)

# Amplitude and speed of nod / shake / tilt: copied from the gamepad page's studio/pad_combo.py values (marked there as "guesses, to be checked on the robot").
# Head commands go into the policy's observations rather than writing to the servos directly, so the amplitude is an "intent", not an angle.
HEAD_TICK_S = 0.04                       # 25 Hz, same as pad_combo.TICK_S
NOD_AMP, NOD_PERIOD_S, NOD_TIMES = 0.5, 0.7, 2
SHAKE_AMP, SHAKE_PERIOD_S, SHAKE_TIMES = 0.6, 0.8, 2
TILT_AMP, TILT_S, TILT_RAMP_S = 0.4, 1.2, 0.25
HEAD_ZERO = {'neck_pitch': 0.0, 'head_pitch': 0.0, 'head_yaw': 0.0, 'head_roll': 0.0}

# robot.enable only accepts the "start policy" request: the fork robotd's own words are "the policy starts when it is ready",
# and the real start happens in the control loop. Right after standing up the IMU is still converging, and home_start_guard refuses several times in a row
# (不能进入保持：正在确认实际 HOME 和直立姿态… (cannot enter hold: confirming actual HOME and upright posture…); 舵机反馈不完整或不新鲜… (servo feedback incomplete or stale…)).
# So sending once is not enough: repeatedly confirm policy_enabled within a window, and on failure report the main program's reason verbatim.
POLICY_START_S = 3.0
POLICY_RETRY_S = 0.5
_POLICY_SETTLING = ('不能进入保持', '确认实际 HOME', '实际 HOME', '关节实际位置', '舵机反馈',
                    '反馈已过期', '直立姿态', '请回 HOME', '扶正', 'IMU')


def _policy_settling(reason):
    """Whether this refusal is "still waiting for posture / feedback to settle", worth retrying in a moment. Others (no policy installed, updating) are reported immediately."""
    return any(word in reason for word in _POLICY_SETTLING)


def _policy_refusal(bus):
    """Why the main program did not start the policy: busStatus's last_enable_refusal / home_start_guard.reason."""
    if not isinstance(bus, dict):
        return None
    why = bus.get('last_enable_refusal')
    if isinstance(why, str) and why:
        return why
    guard = bus.get('home_start_guard')
    if isinstance(guard, dict):
        why = guard.get('reason')
        if isinstance(why, str) and why:
            return why
    return None


def head_seconds(command):
    """How long this head action takes (seconds)."""
    if command == 'nod':
        return NOD_PERIOD_S * NOD_TIMES
    if command == 'shake':
        return SHAKE_PERIOD_S * SHAKE_TIMES
    if command == 'tilt':
        return TILT_S
    return 0.0


def head_frame(command, t):
    """Where the head should be at second t (per pad_combo.head_at). Returns None if not a head action."""
    if command == 'nod':
        pitch = NOD_AMP * math.sin(2 * math.pi * t / NOD_PERIOD_S)
        return {'neck_pitch': 0.0, 'head_pitch': pitch, 'head_yaw': 0.0, 'head_roll': 0.0}
    if command == 'shake':
        yaw = SHAKE_AMP * math.sin(2 * math.pi * t / SHAKE_PERIOD_S)
        return {'neck_pitch': 0.0, 'head_pitch': 0.0, 'head_yaw': yaw, 'head_roll': 0.0}
    if command == 'tilt':
        total = TILT_S
        ramp = min(TILT_RAMP_S, total / 3)
        k = min(1.0, t / ramp) if t < total - ramp else max(0.0, (total - t) / ramp)
        return {'neck_pitch': 0.0, 'head_pitch': 0.0, 'head_yaw': 0.0, 'head_roll': TILT_AMP * k}
    return None


# The same "站起来" (stand up) sometimes scores only 0.54 in hardware tests; actions still require a whole-segment match.
MIN_CONFIDENCE = 0.50

EXACT = {
    '坐下': 'sit', '坐下来': 'sit', '坐': 'sit',
    '站起来': 'stand', '站起': 'stand', '起立': 'stand', '起来': 'stand', '站': 'stand',
    # Recognize step commands and give a hint to use the phone or gamepad instead; onboard voice has no steering-wheel lease.
    '走一小步': 'walk', '走一步': 'walk', '向前走': 'walk', '往前走': 'walk', '走': 'walk',
    '停': 'stop', '停下': 'stop', '停下来': 'stop', '停住': 'stop', '站住': 'stop', '停步': 'stop',
    # Skills: robot.do {skill}. Only performed when standing properly with the policy running (the gamepad page's rule); if it cannot be done, the reason is reported verbatim
    '前滚翻': 'roulade', '翻跟头': 'roulade', '翻个跟头': 'roulade', '打个滚': 'roulade',
    '滚一个': 'roulade', '前翻': 'roulade', '滚翻': 'roulade', '翻身': 'roulade', '打滚': 'roulade',
    '低头捡东西': 'ground_pick', '捡东西': 'ground_pick', '低头捡': 'ground_pick',
    '捡个东西': 'ground_pick', '捡一下东西': 'ground_pick', '低头': 'ground_pick',
    # Quack: robot.sound {tag}. Moves no joints, so it works even when relaxed (robotd main.rs:4300-4307)
    # "叫一下" (quack once) gets stripped by "一下" down to "叫", so the single character must be recognized too
    '叫一声': 'chirp', '叫一下': 'chirp', '叫叫': 'chirp', '嘎一声': 'chirp',
    '嘎一下': 'chirp', '叫唤': 'chirp', '叫': 'chirp',
    '打招呼': 'greet', '打个招呼': 'greet', '问好': 'greet', '问个好': 'greet',
    # Nod / shake / tilt: robot.head notifications, sent in order and then recentered (the head is latched; without recentering it stays tilted)
    '点头': 'nod', '点点头': 'nod', '点一下头': 'nod', '点个头': 'nod',
    '摇头': 'shake', '摇摇头': 'shake', '摇一下头': 'shake', '摇个头': 'shake',
    '歪头': 'tilt', '歪歪头': 'tilt', '歪一下头': 'tilt', '歪个头': 'tilt', '歪脑袋': 'tilt',
}

NEGATIVE_WORDS = ('不', '别', '甭', '勿')
# "复读 坐下" (repeat: sit down) and "他说 站起来" (he said stand up) relay a command as speech; they are not commands
QUOTED_PREFIXES = ('复读', '他说', '她说', '我说', '你说')
SEQUENCE_WORDS = ('再', '然后', '接着', '之后')
ADDRESSES = ('小鸭子', '鸭子', '鸭鸭')
MAX_COMMANDS_PER_UTTERANCE = 3


def _squash(text):
    """Collapse "起立起立起立" into "起立" (stand). In hardware tests, saying it twice in a row gets merged into one sentence by endpoint detection."""
    while len(text) > 2:
        shrunk = False
        for cut in range(2, len(text) // 2 + 1):
            if len(text) % cut == 0:
                unit = text[:cut]
                if unit * (len(text) // cut) == text:
                    text, shrunk = unit, True
                    break
        if not shrunk:
            break
    return text


def _match_clause(text):
    text = text.removeprefix('请').removesuffix('吧')
    if text.startswith(QUOTED_PREFIXES):
        return None
    for phrase in (text, text.removesuffix('一下')):
        phrase = _squash(phrase)
        # A lone "鸭" (duck) is also a form of address. Only a complete built-in command may follow it.
        command = EXACT.get(phrase) or EXACT.get(phrase.removeprefix('鸭').removeprefix('请'))
        if command:
            return command
        if phrase in custom_skills():
            return phrase
    return None


def parse_command(text, confidence):
    """A piece of text → one action (returns None if not recognized)."""
    commands = parse_commands(text, confidence)
    return commands[0] if len(commands) == 1 else None


def parse_commands(text, confidence):
    """Allow complete commands to be separated by forms of address. If any segment is not recognized, nothing is executed."""
    if (not isinstance(text, str) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or confidence < MIN_CONFIDENCE):
        return []
    text = re.sub(r'[\s，。！、,.!]', '', text)
    if (any(word in text for word in NEGATIVE_WORDS + SEQUENCE_WORDS)
            or re.search(r'''unk|["'“”‘’「」『』?？]''', text, re.IGNORECASE)):
        return []
    clauses = re.split('|'.join(ADDRESSES), text)
    # A form of address may appear at the start or the end. Reject if there is no command between two forms of address.
    if not clauses[0]:
        clauses = clauses[1:]
    if clauses and not clauses[-1]:
        clauses = clauses[:-1]
    commands = []
    for clause in clauses:
        command = _match_clause(clause)
        if command is None:
            return []
        if not commands or commands[-1] != command:
            commands.append(command)
    if 'stop' in commands:
        return ['stop']
    return commands if len(commands) <= MAX_COMMANDS_PER_UTTERANCE else []


class RobotClient:
    """robotd JSON-RPC. Requests (init / enable / do / sound / stop / policies / busStatus) go through call,
    opening a new connection each time and waiting for the reply; notifications (head / move / mouth) go through notify, one persistent connection, write and go.

    Notifications carry no id and get no reply (duck-ipc-proto lib.rs:522-529); sending them via call would wait until timeout,
    stalling each nod frame for 1.5 seconds and making the whole action impossible. Same approach as Studio's RobotPort.
    """

    def __init__(self, path='/run/robotd.sock', timeout=1.5, opener=None):
        self.path, self.timeout = path, timeout
        self._opener = opener or (lambda: socket.socket(socket.AF_UNIX))
        self._notify_socket = None
        self._notify_lock = threading.Lock()

    def notify(self, method, params=None):
        """Send a notification: if the connection is broken, drop it and reconnect once; only raise if the second attempt also fails."""
        line = (json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params or {}},
                           separators=(',', ':')) + '\n').encode()
        with self._notify_lock:
            for attempt in (1, 2):
                try:
                    if self._notify_socket is None:
                        client = self._opener()
                        self._notify_socket = client   # attach first: so _close_notify can clean it up if the connection fails
                        client.settimeout(self.timeout)
                        client.connect(self.path)
                    self._notify_socket.sendall(line)
                    return
                except OSError:
                    self._close_notify()
                    if attempt == 2:
                        raise

    def _close_notify(self):
        if self._notify_socket is not None:
            try:
                self._notify_socket.close()
            except OSError:
                pass
            self._notify_socket = None

    def call(self, method, params=None):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(self.timeout)
            client.connect(self.path)
            client.sendall((json.dumps(request) + '\n').encode())
            with client.makefile('rb') as stream:
                response = stream.readline(1024 * 1024 + 1)
            if not response or len(response) > 1024 * 1024:
                raise RuntimeError('invalid or oversized robotd response')
            result = json.loads(response)
            if result.get('id') != 1 or 'error' in result:
                raise RuntimeError('robotd refused ' + method + ': ' + str(result.get('error')))
            data = result.get('result')
            if not isinstance(data, dict):
                raise RuntimeError('robotd returned an unexpected result for ' + method)
            return data


class PostureCommands:
    """Everything voice can do: sit / stand / take a small step / stop / forward roll / head down to pick up / quack / greet / nod / shake head / tilt head.

    The class keeps its old name to avoid touching imports and existing tests.
    """
    def __init__(self, robot, timeout=5, sleep=time.sleep,guard=updates_allowed,lease=motion_lease,
                 clock=time.monotonic):
        self.robot, self.timeout, self.sleep = robot, timeout, sleep
        self.guard,self.lease=guard,lease
        self.clock=clock

    def state(self):
        policies = self.robot.call('robot.policies')
        bus = self.robot.call('robot.busStatus')
        if not isinstance(policies.get('sitting'), bool):
            raise RuntimeError('cannot read current sitting state')
        if bus.get('phase') != 'control' or bus.get('mode') != 'motion':
            raise RuntimeError('robot is not in motion control mode')
        return policies, bus

    def _require_driving(self, policies, bus, request=None, allowed=None):
        """Preconditions for skills and head actions: standing, powered, centered, policy running.

        Consistent with the gamepad page's need_drive (studio/pad_drive.py:1592-1603); head commands go into the policy's observations,
        so sending them while the policy is not running does nothing (pad_combo.py file header).

        After standing, powering and centering, the policy is often still stopped; previously someone had to click "start walking policy" manually.
        Now the same stop → enable sequence as that button starts the policy automatically, and only reports an error if it cannot start,
        with the reason reported verbatim to the phone page. Sitting / not powered / not centered are still rejected outright.
        """
        torque = bus.get('native', {}).get('torque_state_confirmed') is True
        homed = policies.get('homed') is True or bus.get('homed') is True
        if not torque or not homed:
            raise RuntimeError('robot must be upright and homed with torque confirmed')
        if policies['sitting']:
            raise RuntimeError('robot is sitting; stand up first')
        if bus.get('policy_enabled') is not True:
            if request is None:
                raise RuntimeError('walking policy is not running; stand up and start it first')
            self._ensure_policy(request, allowed or (lambda: True))

    def _ensure_policy(self, request, allowed):
        """After standing up, start the "walking policy" automatically (equivalent to the phone page's "start walking policy" button).

        robot.enable's acknowledgment does not mean the policy actually started: the fork robotd accepts the request first and only
        starts it in the control loop after the IMU converges; while posture / feedback has not settled it refuses repeatedly (不能进入保持：… (cannot enter hold: …)). So here,
        within a window, repeat enable + read back policy_enabled, and wait a bit longer on recoverable refusals; if it still has not started when the window runs out,
        report the main program's reason (last_enable_refusal / home_start_guard.reason) verbatim,
        so the user knows to return to HOME and straighten it up.
        """
        deadline = self.clock() + POLICY_START_S
        next_try, last, bus = 0.0, None, None
        while True:
            _, bus = self.state()
            if bus.get('policy_enabled') is True:
                return
            if not allowed():
                raise RuntimeError('cancelled')
            now = self.clock()
            if now >= next_try:
                try:
                    request('robot.stop')
                    request('robot.enable', {'on': True, 'toggle': False})
                except RuntimeError as error:
                    last = str(error)
                    if not _policy_settling(last):
                        raise
                next_try = now + POLICY_RETRY_S
            if now >= deadline:
                raise RuntimeError(_policy_refusal(bus) or last or 'walking policy was not started')
            self.sleep(0.1)

    def _play_head(self, command, allowed):
        """Send a series of robot.head notifications to complete a nod / shake / tilt, always recentering at the end.

        robot.head is a notification (no reply) and goes through RobotClient.notify; its target never expires either
        (fork robotd intents.rs:569-588, the last value sent stays in place), so all three paths, "finished", "interrupted"
        and "error", must send all zeros once more, otherwise the head stays tilted.
        """
        total = max(0.2, float(head_seconds(command)))
        start = self.clock()
        try:
            while True:
                if not allowed():
                    return {'accepted': False, 'reason': 'cancelled'}
                elapsed = self.clock() - start
                if elapsed >= total:
                    break
                self.robot.notify('robot.head', head_frame(command, elapsed) or dict(HEAD_ZERO))
                left = total - (self.clock() - start)
                if left <= 1e-6:
                    # Time is up. Keep one microsecond of margin: when the remaining time is too small for floating-point addition to register, sleep(0) would leave
                    # elapsed forever slightly short and loop forever (both the real clock and the tests' fake clock do this).
                    break
                self.sleep(min(HEAD_TICK_S, left))
            return {'accepted': True, 'head': command}
        finally:
            # Recentering ignores allowed: the head has already moved and must be brought back
            try:
                self.robot.notify('robot.head', dict(HEAD_ZERO))
            except OSError:
                pass

    def execute(self, command, allowed=lambda: True):
        if command == 'walk':
            return {'accepted': False, 'reason': '板载语音不能控制步进，请用手机麦克风或手柄。'}
        try:
            if not self.guard():raise UpdateLocked('software update in progress')
            with self.lease():
                return self._execute(command,lambda:allowed() and self.guard())
        except UpdateLocked as error:return {'accepted':False,'reason':str(error)}

    def _execute(self,command,allowed):
        custom = custom_skills()
        if command not in ALL_COMMANDS and command not in custom:
            return {'accepted': False, 'reason': 'unknown command'}
        try:
            policies, bus = self.state()
            if not allowed():
                return {'accepted': False, 'reason': 'cancelled'}
            desired = command == 'sit'
            torque = bus.get('native', {}).get('torque_state_confirmed') is True
            homed = policies.get('homed') is True or bus.get('homed') is True
            initialized = False

            def request(method, params=None):
                if not allowed():
                    raise RuntimeError('cancelled')
                result = self.robot.call(method, params)
                if result.get('accepted') is not True:
                    raise RuntimeError(str(result.get('reason', method + ' was refused')))

            # Quack / greet: robot.sound moves no joints, so it works even when relaxed (robotd main.rs:4300-4307).
            # Marked quiet: no extra "got it" beep afterwards, otherwise a quack would sound twice in a row.
            if command in SOUND_COMMANDS:
                request('robot.sound', {'tag': SOUND_COMMANDS[command]})
                return {'accepted': True, 'sound': SOUND_COMMANDS[command], 'quiet': True}

            # Skills (forward roll / head down to pick something up): same rule as the gamepad page's skill buttons, only when standing properly with the policy running
            if command in SKILL_COMMANDS:
                self._require_driving(policies, bus, request, allowed)
                skill = SKILL_COMMANDS[command]
                request('robot.do', {'skill': skill})
                return {'accepted': True, 'skill': skill}

            # Custom ONNX skills: same rule as built-in skills (only when standing properly with the policy running)
            if command in custom:
                self._require_driving(policies, bus, request, allowed)
                skill = custom[command]
                request('robot.do', {'skill': skill})
                return {'accepted': True, 'skill': skill}

            # Nod / shake / tilt: send robot.head notifications all the way through, always recentering at the end (see _play_head)
            if command in HEAD_COMMANDS:
                self._require_driving(policies, bus, request, allowed)
                return self._play_head(command, allowed)

            if command == 'stop':
                if not torque or not homed:
                    raise RuntimeError('robot must be upright and homed with torque confirmed')
                if policies['sitting']:
                    raise RuntimeError('robot is sitting; stand up first')
                request('robot.stop')
                return {'accepted': True, 'changed': True, 'sitting': False, 'stopped': True}

            if policies['sitting'] == desired and (desired or (torque and homed)):
                if command == 'stand':
                    self._ensure_policy(request, allowed)
                return {'accepted': True, 'changed': False, 'sitting': desired}
            if command == 'stand' and not policies['sitting'] and not torque:
                request('robot.init')
                initialized = True
            else:
                if not torque or not homed:
                    raise RuntimeError('robot must be upright and homed with torque confirmed')
                if not any(isinstance(slot, dict) and slot.get('slot') == 'sitstand'
                           and slot.get('path') and not slot.get('error')
                           for slot in policies.get('slots', [])):
                    raise RuntimeError('sit/stand policy is not installed')
                if bus.get('policy_enabled') is not True:
                    if policies['sitting']:
                        raise RuntimeError('sitting with policy off; use the existing recovery procedure')
                    self._ensure_policy(request, allowed)
                # Refresh the toggle state immediately before using the toggle API.
                policies, _ = self.state()
                if policies['sitting'] != desired:
                    request('robot.do', {'skill': 'sit_toggle'})
            deadline = time.monotonic() + self.timeout
            while allowed():
                policies, bus = self.state()
                ready = policies['sitting'] == desired
                if initialized:
                    ready = ready and (policies.get('homed') is True or bus.get('homed') is True)
                    ready = ready and bus.get('native', {}).get('torque_state_confirmed') is True
                if ready:
                    if command == 'stand':
                        self._ensure_policy(request, allowed)
                    return {'accepted': True, 'changed': True, 'sitting': desired}
                if time.monotonic() >= deadline:
                    raise RuntimeError('posture request accepted but target state not confirmed')
                self.sleep(0.08)
            return {'accepted': False, 'reason': 'cancelled'}
        except (OSError, ValueError, RuntimeError) as error:
            return {'accepted': False, 'reason': str(error)}
