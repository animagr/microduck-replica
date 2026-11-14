"""Local Mandarin recognition and one cancellable, bounded command queue."""
import array
from collections import deque
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time

from voice_commands import parse_commands,updates_allowed

LOG = logging.getLogger('duck-echo')

# Only enable while troubleshooting: logs the phrase recognized this time. Off by default to avoid leaving conversation content in the logs.
DEBUG_TEXT = os.environ.get('ECHO_DEBUG_TEXT') == '1'

# Keep an unknown-speech alternative and negative/quoted forms. A grammar
# containing only positive commands would force unrelated speech into commands.
COMMAND_GRAMMAR = [
    '坐下', '坐下 来', '站起来', '起立', '起来',
    '鸭子 坐下', '鸭子 坐下 来', '鸭子 站起来', '鸭子 起立',
    '小 鸭子 坐下', '小 鸭子 站起来', '请 坐下', '请 站起来',
    '坐下 吧', '站起来 吧',
    # "鸭鸭" (Duckie): the wake word agreed on with the phone web console. It is written as "鸭 鸭" because the vocabulary has the single character "鸭";
    # as a whole word it would drop out on its own when filtered by model.vosk_model_find_word below, without breaking the whole grammar
    '鸭 鸭 坐下', '鸭 鸭 站起来', '鸭 鸭 走 一小步', '鸭 鸭 停', '鸭 鸭 停 下',
    # "走一小步" (take a small step) is still recognized so the user can be told to use the phone or gamepad instead. Explicit stop commands are executed onboard.
    '走 一小步', '走 一步', '往 前 走', '往 前 走 一步', '停', '停 下', '停 下来',
    '不要 坐下', '不要 站起来', '不要 起来', '不要 起立',
    '别 坐下', '别 站起来', '别 起来', '别 起立',
    '不 坐下', '不 站起来', '不想 坐下', '不想 站起来',
    '不用 坐下', '不用 站起来', '不能 坐下', '不能 站起来',
    '复读 坐下', '复读 站起来', '他说 坐下', '我说 坐下',
    '[unk]',
]

# Besides taking a small step / stop, these actions are recognized: forward roll, head down to pick something up, quack, greet, nod, shake head, tilt head.
# Each phrasing is given both as whole words and split into single characters: small models mostly have single-character vocabularies, and whole words
# would drop out on their own when filtered by model.vosk_model_find_word, without breaking the whole grammar.
ACTION_PHRASES = {
    # In hardware tests "前 滚 翻" (forward roll) is often heard as "前 捡 前 滚 翻" or "翻". Adding one entry "滚 翻" is enough:
    # the longer the grammar, the easier short words get misrecognized (the "翻 要 歪头" at 09:24 was exactly an extra "翻").
    'roulade': ['前滚翻', '前 滚 翻', '翻跟头', '翻 跟 头', '滚 翻'],
    'ground_pick': ['低头捡东西', '低头', '捡东西', '捡 东 西'],
    'chirp': ['叫一声', '叫 一 声', '叫一下', '叫 一 下'],
    'greet': ['打招呼', '打 招 呼', '问好', '问 好'],
    'nod': ['点头', '点 头', '点点头', '点 点 头'],
    'shake': ['摇头', '摇 头', '摇摇头', '摇 摇 头'],
    'tilt': ['歪头', '歪 头', '歪歪头', '歪 歪 头'],
}


def _grammar_entries(phrases):
    """Phrasings for one action → the entries the grammar needs.

    Besides the plain phrase, also provide: the wake word "鸭 鸭" and the form of address "鸭子" (duck) as prefixes, the polite "请" (please),
    and both negative forms "不要 / 别" (don't): without negative forms in the grammar, saying "不要点头" (don't nod) would be forced into "点头" (nod) and actually executed.
    """
    out = []
    for phrase in phrases:
        out.extend([phrase, '鸭 鸭 ' + phrase, '鸭子 ' + phrase, '请 ' + phrase,
                    '不 要 ' + phrase, '别 ' + phrase])
    return out


COMMAND_GRAMMAR += [entry for phrases in ACTION_PHRASES.values()
                    for entry in _grammar_entries(phrases)]


class MandarinRecognizer:
    def __init__(self, model_path, dependencies=None):
        if dependencies:
            sys.path.insert(0, str(dependencies))
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        if not (Path(model_path) / 'am/final.mdl').is_file():
            raise RuntimeError('Chinese speech model is not installed')
        self.model = Model(str(model_path))
        self.recognizer_type = KaldiRecognizer
        self._grammar_key = ()
        self.grammar = self._make_grammar(self._custom_key() or ())

    @staticmethod
    def _custom_key():
        """Custom commands uploaded in Studio. Returns None if they cannot be read, keeping the current grammar."""
        try:
            from voice_commands import custom_skills
            return tuple(sorted(custom_skills().items()))
        except Exception:
            return None

    def _make_grammar(self, key):
        phrases = list(COMMAND_GRAMMAR)
        for command, _skill in key:
            # Small models have single-character vocabularies: whole-word filtering would drop it, so add another entry split into single characters
            phrases.extend(_grammar_entries([command, ' '.join(command)]))
        grammar = [phrase for phrase in dict.fromkeys(phrases)
                   if all(self.model.vosk_model_find_word(word) >= 0 for word in phrase.split())]
        self._grammar_key = key
        return json.dumps(grammar, ensure_ascii=False)

    def _grammar_for(self):
        key = self._custom_key()
        if key is not None and key != self._grammar_key:
            self.grammar = self._make_grammar(key)
        return self.grammar

    def recognize(self, stereo, rate=48000):
        samples = array.array('h')
        samples.frombytes(stereo[:len(stereo) // 4 * 4])
        # Input is already the selected microphone duplicated into stereo by
        # prepare_audio. Keep one channel; Kaldi's model config resamples 48k.
        mono = samples[::2].tobytes()
        recognizer = self.recognizer_type(self.model, rate, self._grammar_for())
        recognizer.SetWords(True)
        parts = []
        for offset in range(0, len(mono), 8000):
            if recognizer.AcceptWaveform(mono[offset:offset + 8000]):
                parts.append(json.loads(recognizer.Result()))
        parts.append(json.loads(recognizer.FinalResult()))
        scores = [word.get('conf', 0) for part in parts for word in part.get('result', [])]
        return {'text': ' '.join(part.get('text', '') for part in parts).strip(),
                'confidence': min(scores, default=0)}


class VoiceControl:
    def __init__(self, recognizer_factory, executor, fallback, execute_commands=True,
                 cue=None, ttl=6, clock=time.monotonic, recognize_speech=True,guard=updates_allowed):
        self.factory, self.executor, self.fallback = recognizer_factory, executor, fallback
        self.execute_commands, self.cue = execute_commands, cue
        self.recognize_speech = recognize_speech
        self.guard=guard
        self._recognizer = None
        self.ttl, self.clock = ttl, clock
        self.condition = threading.Condition()
        self.queue = deque(maxlen=1)
        self.generation, self.closed = 0, False
        self.ready, self.idle = threading.Event(), threading.Event()
        self.idle.set()
        self.last_result = None
        self.last_at = 0.
        self.last_seq = 0
        self.thread = threading.Thread(target=self._run, name='local-speech', daemon=True)
        self.thread.start()

    def _record(self, result):
        """Record "the most recently recognized command". Keep only the command name and whether it succeeded, not the whole sentence:
        the raw phrase may contain unrelated content, and the phone page only needs to know what it understood."""
        with self.condition:
            self.last_result = result
            self.last_at = self.clock()
            self.last_seq += 1

    def last_view(self):
        """Read-only view for the control port / phone page: command name, success or not, how long ago, which attempt, failure reason."""
        with self.condition:
            item, at, seq = self.last_result, self.last_at, self.last_seq
        if not isinstance(item, dict):
            return None
        command = item.get('command')
        if command is None:
            return None
        accepted = item.get('accepted')
        view = {'command': str(command)[:32],
                'accepted': accepted if type(accepted) is bool else None,
                'age': round(max(0., self.clock() - at), 2),
                'seq': seq}
        # Only carry the public reason given by robotd / the executor (e.g. "the robot is sitting", "servo feedback incomplete"),
        # never the recognized raw phrase; the frontend uses it to explain "why it was not done".
        reason = item.get('reason')
        if isinstance(reason, str) and reason:
            view['reason'] = reason[:160]
        return view

    @property
    def recognizer(self):
        """Ready shared Model owner; consumers create their own Kaldi decoder."""
        return self._recognizer if self.ready.is_set() else None

    def submit(self, pcm):
        with self.condition:
            if not self.guard():
                self.cancel();return
            if self.closed:
                return
            self.queue.append((self.generation, self.clock(), pcm))
            self.idle.clear()
            self.condition.notify()

    def cancel(self):
        with self.condition:
            self.generation += 1
            self.queue.clear()

    def valid(self, job):
        with self.condition:
            if not self.guard():
                self.cancel();return False
            return not self.closed and job[0] == self.generation and self.clock() - job[1] <= self.ttl

    def _echo(self, job):
        # Hold the short generation check through starting playback so a new
        # R3 press can always cancel first, then stop any already-started echo.
        with self.condition:
            if self.valid(job):
                self.fallback(job[2])

    def _run(self):
        try:
            recognizer = self.factory()
            self._recognizer = recognizer
            LOG.info('local Chinese speech recognition ready; mode=%s',
                     'actions' if self.execute_commands else 'shadow')
        except Exception:
            recognizer = None
            LOG.exception('speech model unavailable; ordinary echo remains available')
        finally:
            self.ready.set()
        while True:
            with self.condition:
                while not self.queue and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                job = self.queue.popleft()
            try:
                if not self.valid(job):
                    continue
                if recognizer is None or not self.recognize_speech:
                    self._echo(job)
                    continue
                result = recognizer.recognize(job[2])
                # One segment may merge several commands; execute them one by one in the order spoken (see voice_commands.parse_commands)
                commands = parse_commands(result.get('text', ''), result.get('confidence', 0))
                if not self.valid(job):
                    continue
                # Do not retain arbitrary conversation transcriptions in logs.
                # Only enable when troubleshooting "heard but not recognized": ECHO_DEBUG_TEXT=1, logging only the text recognized this time.
                if DEBUG_TEXT:
                    LOG.info('speech text=%r', str(result.get('text', ''))[:120])
                LOG.info('speech command=%s confidence=%.2f',
                         ' '.join(commands) or 'none', result.get('confidence', 0))
                if not commands or not self.execute_commands:
                    self._echo(job)
                    self._record({'command': commands[-1] if commands else None,
                                  'shadow': not self.execute_commands})
                    continue
                outcome, command = None, None
                for command in commands:
                    outcome = self.executor.execute(command, allowed=lambda: self.valid(job))
                    LOG.info('voice action: %s',
                             json.dumps({'command': command, **outcome}, ensure_ascii=False))
                    if outcome.get('accepted') is not True:
                        break
                self._record({'command': command, **outcome})
                if self.cue is not None and self.valid(job) and not outcome.get('quiet'):
                    try:
                        self.cue(outcome.get('accepted') is True)
                    except Exception:
                        LOG.exception('voice acknowledgement sound unavailable')
            except Exception:
                LOG.exception('speech processing failed; preserving ordinary echo')
                self._echo(job)
            finally:
                with self.condition:
                    if not self.queue:
                        self.idle.set()

    def close(self):
        with self.condition:
            self.closed = True
            self.generation += 1
            self.queue.clear()
            self.condition.notify_all()
        self.thread.join(timeout=2)
