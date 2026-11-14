"""Two things that need to be added once the phone uses https: camera signaling forwarding and phone voice recordings to text.

Why this module is needed:

1. Camera: mediad's signaling port 8443 is plaintext ws. Connecting directly from an http page is fine, but once the page switches to https,
   the browser blocks "https page connecting to plaintext ws" as mixed content, and the camera goes black.
   So we mount a same-origin, same-protocol /media-ws, which Studio forwards to the local 127.0.0.1:8443 —— same origin and protocol,
   so there's no mixed content, and the desktop http path still works as before.

2. Speaking on the phone: the browser's speech recognition (Web Speech API) goes through Google services on Android Chrome, which basically doesn't work in mainland China,
   and behavior on iOS varies between vendors too. Rather than rely on it, we send a clip of PCM recorded on the phone back,
   and recognize it with the same Vosk Chinese model duck-echo uses on the board —— the same model and vocabulary as talking to the duck directly.

Dependencies: vosk and websockets aren't in Studio's own deps but under duck-echo's asr-deps,
so we temporarily add them via sys.path here. Both are "imported only when used", so if either is missing it must not bring down the whole web page.

Two fixes from 11-03 (the phone spoke, the board returned an empty string, after waiting 12 seconds):

* **Use the command vocabulary (grammar)**. Previously it used general decoding with no grammar, and general decoding with the small Chinese model is slow and erratic:
  on the board, 1.2 seconds of audio took 6.3 seconds to process, 2 seconds took 12 seconds, and it often returned nothing.
  Switching to duck-echo's COMMAND_GRAMMAR, the same audio takes **0.3 seconds** with equally correct results.
  The vocabulary is borrowed directly from duck-echo's speech_control —— sharing one copy is the only way to avoid
  mysteries like "talking to the duck works, talking to the phone doesn't".
* **Volume normalization**. With the phone mic half a meter away, the peak is often only a few hundred (full scale 32767),
  and the small model just discards it as noise. When the peak is below TARGET_PEAK it's amplified linearly (up to 8x),
  and the peak/RMS/elapsed time are returned to the front end —— when recognition fails the user can immediately see "too quiet, or nothing said".
"""
import array
import asyncio
import json
import math
import os
import sys
import threading
import time

ASR_DEPS = '/opt/microduck/resources/asr-deps'
MODEL_DIR = '/opt/microduck/resources/models/vosk-model-small-cn-0.22'
ECHO_DIR = '/opt/microduck/software/current/duck-echo'   # duck-echo is right next door; borrow its vocabulary directly
MEDIA_UPSTREAM = 'ws://127.0.0.1:8443'
SAMPLE_RATE = 16000

MIN_PEAK = 120          # if the max amplitude of the whole clip is below this, treat it as nothing said (int16 full scale 32767)
MIN_CONF = 0.35         # below this confidence treat it as not heard clearly: better to do nothing than move randomly
TARGET_PEAK = 20000     # normalization target
MAX_GAIN = 8.0
CHUNK = 8000            # feed 0.25 seconds at a time

# Commands recognized by the phone web console (the same set as RULES in web/m/actions.js). duck-echo's vocabulary only has sit down / stand up,
# while the phone side can also nod, take a small step, do a forward roll... so we list our own here and merge it with duck-echo's.
# The model has a single-character vocabulary: entries must be single characters separated by spaces; whole words get filtered out by vosk_model_find_word.
MOBILE_COMMANDS = [
    '点头', '摇头', '歪头', '偏头', '前滚翻', '翻跟头', '翻身', '低头捡东西', '低头', '捡东西',
    '叫一声', '叫一下', '叫两声', '打招呼', '你好', '张嘴', '开口',
    '站起来', '站起', '起立', '起来', '起身', '坐下', '坐一坐',
    '停下', '站住',
    '走一小步', '走一步', '走两步', '迈一步', '走一下', '前进', '往前', '开步',
]
MOBILE_PREFIXES = ('', '鸭鸭', '鸭子', '请', '不要', '别')

_model = None
_error = None
_lock = threading.Lock()
_grammar = None
_grammar_ready = False


def _deps_on_path():
    if os.path.isdir(ASR_DEPS) and ASR_DEPS not in sys.path:
        sys.path.insert(0, ASR_DEPS)


def _load_model():
    """Loaded on first use and kept afterward (the model isn't big, but don't read the disk on every request)."""
    global _model, _error
    with _lock:
        if _model is not None or _error is not None:
            return _model, _error
        try:
            _deps_on_path()
            from vosk import Model, SetLogLevel
            # If not turned off, every recognized sentence would dump the whole vocabulary (200+ entries) into the Studio log
            SetLogLevel(-1)
            _model = Model(MODEL_DIR)
        except Exception as exc:                       # not installed / model missing: just this feature is unavailable
            _error = '%s: %s' % (type(exc).__name__, exc)
    return _model, _error


def _mobile_grammar():
    """Phone command → single-character-separated entries, with common prefixes and suffixes."""
    out = []
    for phrase in MOBILE_COMMANDS:
        body = ' '.join(phrase)
        for prefix in MOBILE_PREFIXES:
            out.append((' '.join(prefix) + ' ' + body) if prefix else body)
    return out


def _grammar_json(model):
    """Phone commands + duck-echo's command vocabulary. Returns None if nothing survives filtering (falls back to general decoding: slow but works)."""
    global _grammar, _grammar_ready
    if _grammar_ready:
        return _grammar
    entries = list(_mobile_grammar())
    try:
        if ECHO_DIR not in sys.path:
            sys.path.insert(0, ECHO_DIR)
        from speech_control import COMMAND_GRAMMAR
        entries.extend(COMMAND_GRAMMAR)
    except Exception:
        pass
    try:
        # Only keep phrasings that really exist in the vocabulary: the small model has a single-character vocabulary, and entries written as whole words get dropped entirely
        kept, seen = [], set()
        for phrase in entries:
            if phrase in seen:
                continue
            seen.add(phrase)
            if all(model.vosk_model_find_word(w) >= 0 for w in phrase.split()):
                kept.append(phrase)
        if kept and '[unk]' not in kept:
            kept.append('[unk]')
        _grammar = json.dumps(kept, ensure_ascii=False) if kept else None
    except Exception:
        _grammar = None
    _grammar_ready = True
    return _grammar


def _normalize(pcm):
    """PCM → normalized PCM + a health check of this audio clip."""
    samples = array.array('h')
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    if not samples:
        return b'', {'sec': 0.0, 'peak': 0, 'rms': 0, 'gain': 1.0}
    peak = max(max(samples), -min(samples))
    rms = int(math.sqrt(sum(x * x for x in samples) / len(samples)))
    gain = 1.0
    if 0 < peak < TARGET_PEAK:
        gain = min(MAX_GAIN, TARGET_PEAK / float(peak))
        if gain > 1.05:
            samples = array.array('h', [max(-32768, min(32767, int(x * gain))) for x in samples])
        else:
            gain = 1.0
    return samples.tobytes(), {'sec': round(len(samples) / float(SAMPLE_RATE), 2),
                               'peak': int(peak), 'rms': int(rms), 'gain': round(gain, 2)}


def transcribe_detail(pcm, use_grammar=True):
    """16 kHz / 16 bit / mono / little-endian raw PCM → {'text', 'error', 'info'}.

    info carries this run's health-check data (seconds, peak, gain, recognition time, confidence, reason for not recognizing),
    so the front end can explain in plain language: "声音太小" (too quiet), "听清了但不确定" (heard but not sure).

    use_grammar=False uses general decoding: much slower (6~12 seconds for 2 seconds of audio), but not limited by the command vocabulary;
    the self-check page uses it to see "what the board actually heard", and to tell whether [unk] means "not heard clearly" or "word not in vocabulary".
    """
    out = {'text': '', 'error': None, 'info': {}}
    model, err = _load_model()
    if err:
        out['error'] = err
        return out

    pcm, info = _normalize(pcm)
    out['info'] = info
    if info['peak'] < MIN_PEAK:
        info['reason'] = 'silent'
        return out

    started = time.time()
    try:
        _deps_on_path()
        from vosk import KaldiRecognizer
        grammar = _grammar_json(model) if use_grammar else None
        rec = (KaldiRecognizer(model, SAMPLE_RATE, grammar) if grammar
               else KaldiRecognizer(model, SAMPLE_RATE))
        rec.SetWords(True)
        parts = []
        for i in range(0, len(pcm), CHUNK):
            if rec.AcceptWaveform(pcm[i:i + CHUNK]):
                parts.append(json.loads(rec.Result()))
        parts.append(json.loads(rec.FinalResult()))
    except Exception as exc:
        out['error'] = '%s: %s' % (type(exc).__name__, exc)
        return out

    text = ''.join(p.get('text', '') for p in parts).replace(' ', '')
    # When decoding with a vocabulary, speech that doesn't match any entry yields [unk] (unknown word).
    # It isn't a "word" and can't be passed on as a recognition result —— otherwise the front end would look for an action called [unk].
    unknown = '[unk]' in text
    text = text.replace('[unk]', '').strip()
    confs = [w.get('conf', 0.0) for p in parts for w in p.get('result', [])]
    conf = min(confs, default=0.0)
    info.update({'ms': int((time.time() - started) * 1000), 'conf': round(conf, 2),
                 'grammar': bool(grammar)})
    if not text:
        info['reason'] = 'unknown' if unknown else 'unclear'
        return out
    if unknown:
    # Cases like "点头 [unk]" (nod [unk]): half recognized, with a part not understood. Treating it as unrecognized is safer.
        info['reason'] = 'unknown'
        info['heard'] = text
        return out
    if conf < MIN_CONF:
        # Recognized but not trustworthy: keep the original text in info so the diag page can see it; the front end only says "没听清" (didn't catch that)
        info['reason'] = 'unclear'
        info['heard'] = text
        return out
    out['text'] = text
    return out


def transcribe(pcm):
    """Old API: only text and error."""
    detail = transcribe_detail(pcm)
    return detail['text'], detail['error']


def warmup():
    """Load the model and vocabulary in the background at startup, so the user's first sentence doesn't have to wait for it.

    Cold loading on the Zero 3W measured 2~5 seconds, longer while the CPU is busy right after boot (the user hit it once on 11-03:
    after uploading it took 25 seconds to come back). During that time nothing on the page changes, and it looks like "long press does nothing",
    so have Studio load it as soon as it starts.
    """
    model, err = _load_model()
    if model is not None:
        _grammar_json(model)          # the vocabulary also needs compiling once, so the first sentence doesn't get stuck here again
    return (model is not None), err


async def pump_media(ws, upstream=MEDIA_UPSTREAM):
    """Forward in both directions between starlette's WebSocket and the local mediad.

    The two APIs differ (starlette receives dicts, the websockets library gives str/bytes directly), so we write a pump for each direction,
    and whichever finishes first shuts down the other one too.
    """
    _deps_on_path()
    import websockets

    async with websockets.connect(upstream, max_size=None, ping_interval=None) as up:

        async def down_to_up():
            """browser → mediad"""
            try:
                while True:
                    message = await ws.receive()
                    kind = message.get('type')
                    if kind == 'websocket.disconnect':
                        return
                    if kind == 'websocket.receive':
                        data = message.get('bytes')
                        await up.send(data if data is not None else (message.get('text') or ''))
            except Exception:
                return

        async def up_to_down():
            """mediad → browser"""
            try:
                async for data in up:
                    if isinstance(data, bytes):
                        await ws.send_bytes(data)
                    else:
                        await ws.send_text(data)
            except Exception:
                return

        tasks = [asyncio.create_task(down_to_up()), asyncio.create_task(up_to_down())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
