// Voice page: two **mutually independent** channels, unrelated to the gamepad page (the gamepad page has sticks, this page has speech; each handles its own).
//
// **Neither** path needs a wake word: what you say is what you get, and a correct command is executed (saying "鸭鸭" (Ducky) is still recognized and gets stripped).
//
//   board: the duck's own ears (duck-echo + local Vosk). Click "turn on onboard listening" (「开板载聆听」) and just talk to it.
//            The phone only opens/closes the listening window and shows what it recognized. Good for: quiet environments, person right next to the duck.
//   phone: the phone turns speech into a command and sends it over. **Recognition is done on the board**: the phone only records a clip and sends it back to Studio,
//            where /api/asr recognizes it with the same Vosk Chinese model duck-echo is using on the board.
//            Good for: noisy environments, onboard can't hear clearly, or far from the duck.
//            Why not the browser's built-in speech recognition (Web Speech): on Android Chrome it goes through Google services, which are basically unreachable in mainland China,
//            and iOS varies by vendor. Recognizing on the board uses the same model and the same vocabulary, so results match talking to the duck directly.
// When neither works there's "typing" as a fallback: same parser, same dispatch path.
//
// ⚠️ The phone microphone requires the page to run in a secure context (https or localhost). On http://192.168.x.x the browser simply disables
//    navigator.mediaDevices, and code can't get around that, so in that case state the reason,
//    and point to the path that really works: "dictation with the microphone key on the keyboard".
import { html, useState, useEffect, useRef, useCallback } from '../vendor/preact-htm.module.js';
import { link } from './link.js';
import { parseUtterance, runAction, CMD_CN, openPadArea, setAudio } from './actions.js';

const MODE_KEY = 'duck.voice.mode';
const SECURE = typeof window !== 'undefined' ? window.isSecureContext !== false : false;
// The phone path only needs "can record": recognition is left to the board, so check getUserMedia rather than SpeechRecognition
const CAN_RECORD = typeof navigator !== 'undefined'
  && Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
const RATE = 16000;          // sample rate required by the Vosk model on the board
const MIN_BYTES = 3200;      // 16 kHz × 2 bytes: 0.1 s; anything shorter can't be recognized

// Take PCM samples directly from AudioContext. AudioWorklet is used instead of MediaRecorder
// because MediaRecorder produces webm/opus and there's no ffmpeg on the board to transcode; this way we get raw PCM that can be fed straight to Vosk.
const PCM_WORKLET = `
class PcmTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice());
    return true;
  }
}
registerProcessor('pcm-tap', PcmTap);
`;
// A 20 ms silent wav. When the mute switch on the iPhone's side is flipped on, the system suspends AudioContext,
// and playing this silence through <audio> wakes it up (an old iOS problem).
const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

/**
 * Every long press synchronously creates a new AudioContext right at the moment of pressing, the same approach the self-test page (/diag) uses for its 2 s recording.
 * The key is that resume() must complete **before** getUserMedia (see the order in openRecorder):
 * waiting on the microphone and resume at the same time makes some Chromium-based phone browsers (Xiaomi, Quark) leave the context
 * stuck in suspended; the worklet's process never runs once, and on release it's "not a single sound captured".
 */
function makeCtx() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  let c = null;
  try { c = new Ctx({ sampleRate: RATE }); } catch { c = null; }
  if (!c) c = new Ctx();
  return c;
}

/**
 * Put a time limit on one step. When stuck, throw "which step it's stuck at";
 * much more useful than waiting 8 s and then giving a vague "microphone didn't start", and easier to diagnose remotely.
 */
function stepTimeout(p, ms, what, onStage) {
  if (onStage) onStage(`${what}…`);
  let t = null;
  const guard = new Promise((_, rej) => {
    t = setTimeout(() => {
      const e = Error(`卡在「${what}」这一步：${Math.round(ms / 1000)} 秒都没动。`);
      e.friendly = true;
      rej(e);
    }, ms);
  });
  return Promise.race([Promise.resolve(p), guard]).finally(() => clearTimeout(t));
}

/** Prefer the real file; only fall back to blob as a last resort, since iOS Safari often can't load the blob version of AudioWorklet */
let tapLoadedOn = null;      // repeating registerProcessor in the same context throws, so remember whether it has been loaded
async function loadTap(ctx, onStage) {
  if (!ctx.audioWorklet) return false;
  if (tapLoadedOn === ctx) return 'worklet';
  // try the same-origin real file first (the self-test page verified this path works), each with a time limit, so a slow network doesn't stall the whole chain
  for (const u of ['/m/pcm-tap.js', './pcm-tap.js']) {
    try {
      await stepTimeout(ctx.audioWorklet.addModule(u), 2500, '加载录音脚本', onStage);
      tapLoadedOn = ctx;
      return 'worklet';
    } catch { /* try the next one */ }
  }
  let url = null;
  try {
    url = URL.createObjectURL(new Blob([PCM_WORKLET], { type: 'application/javascript' }));
    await stepTimeout(ctx.audioWorklet.addModule(url), 2000, '加载录音脚本', onStage);
    tapLoadedOn = ctx;
    return 'worklet';
  } catch { return false; }
  finally { if (url) URL.revokeObjectURL(url); }
}

/** When the device sample rate isn't 16 kHz (most phones are 48 kHz, iPhones often 48k too), downsample with linear interpolation */
function resample(f32, inRate) {
  if (!inRate || inRate === RATE || f32.length === 0) return f32;
  const ratio = inRate / RATE;
  const out = new Float32Array(Math.max(1, Math.floor(f32.length / ratio)));
  for (let i = 0; i < out.length; i++) {
    const p = i * ratio;
    const i0 = Math.floor(p);
    const i1 = Math.min(i0 + 1, f32.length - 1);
    const t = p - i0;
    out[i] = f32[i0] * (1 - t) + f32[i1] * t;
  }
  return out;
}

/**
 * Start a recording. After stop(), the returned object gives raw PCM (16 kHz / 16 bit / mono / little-endian).
 *
 * The order matters: AudioContext must be **created synchronously at the moment of pressing** (after await getUserMedia it's detached from
 * the user gesture, and iOS keeps it suspended so process never runs once, which shows up as "long press does nothing").
 */
async function openRecorder(onStage) {
  const stage = (s) => { try { onStage && onStage(s); } catch { /* UI issues must not affect recording */ } };
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) throw Error('这个浏览器不支持网页录音（AudioContext 都没有）。');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw Error('这个页面拿不到麦克风接口：确认地址是 https 开头，且不是微信/QQ 内置浏览器。');
  }

  // 1) **create the context and wake it synchronously at the instant of pressing** (can't wait until after getUserMedia to create it).
  const ctx = makeCtx();

  // 1.5) resume() must **complete** before getUserMedia; don't wait on the microphone and on it at the same time.
  //   The self-test page works precisely because its order is "create context → await resume → request microphone";
  //   here getUserMedia and resume used to run in parallel, and browsers like Xiaomi/Quark stayed stuck in suspended,
  //   the worklet's process never ran once, and on release there wasn't a single sample ("not a single sound captured").
  let wakeP = null;
  try { wakeP = ctx.resume(); } catch { wakeP = null; }
  // another kick: play one frame of silent buffer; some implementations don't really open the audio path on resume alone
  let kick = null;
  try {
    kick = ctx.createBufferSource();
    kick.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
    kick.connect(ctx.destination);
    kick.start(0);
  } catch { kick = null; }

  let stream = null, node = null, src = null, mute = null, closed = false, lastState = '';
  const chunks = [];
  let total = 0;
  const push = (f) => { if (f && f.length) { chunks.push(f); total += f.length; } };

  const teardown = () => {
    closed = true;
    lastState = ctx.state;            // after closing we can no longer see the engine state at that time, so record it first for error reporting
    try { src && src.disconnect(); } catch { /* not connected */ }
    try { node && node.disconnect(); } catch { /* not connected */ }
    try { mute && mute.disconnect(); } catch { /* not connected */ }
    try { kick && kick.disconnect(); } catch { /* already disconnected */ }
    try { if (stream) stream.getTracks().forEach((t) => t.stop()); } catch { /* already stopped */ }
    // this context only serves this one long press; close it when done, and create a new one on the next press (same as the self-test page)
    try { if (ctx.state !== 'closed') ctx.close(); } catch { /* already closed */ }
  };

  try {
    // 2) first wait for the resume started in the gesture to land (with a limit, don't wait forever), **then** request the microphone.
    //    The order can't be reversed: waiting on getUserMedia and resume at the same time makes these browsers leave the context in suspended.
    if (wakeP) {
      try { await stepTimeout(wakeP, 1500, '唤醒音频', stage); } catch { /* continue even if it doesn't settle */ }
    }
    if (ctx.state !== 'running') {
      try { await stepTimeout(ctx.resume(), 1200, '唤醒音频', stage); } catch { /* accept it, connect first and see */ }
    }
    if (isIOS) {
      // the iOS side mute switch cuts off recording; playing 20 ms of silence wakes it up.
      // **deliberately not awaited**: in some browsers the play() promise never settles, and awaiting it would deadlock the whole chain.
      try {
        const el = new Audio(SILENT_WAV);
        el.volume = 0;
        el.play().then(() => el.pause(), () => { /* doesn't matter if it can't play */ });
      } catch { /* doesn't matter if it can't play */ }
    }

    // 3) only now that the audio engine is running, request the microphone. The constraint is just audio:true, exactly as the self-test page does;
    //    with the echoCancellation set of constraints, getUserMedia in this version of the MIUI browser never resolves.
    const micP = navigator.mediaDevices.getUserMedia({ audio: true });
    // a stream that arrives late after the timeout must be cleaned up by us: otherwise we keep holding the microphone,
    // the system's "recording" icon stays lit, and the next long press is even less likely to start.
    micP.then((s) => {
      if (closed) { try { s.getTracks().forEach((t) => t.stop()); } catch { /* already stopped */ } }
    }, () => { /* errors are handled uniformly by the await below */ });
    stream = await stepTimeout(micP, 10000, '打开麦克风', stage);

    // 4) capture node: AudioWorklet first; if it can't load, fall back to the old way (ScriptProcessor needs no network, never waits in vain)
    const kind = await loadTap(ctx, stage);
    if (kind === 'worklet') {
      node = new AudioWorkletNode(ctx, 'pcm-tap');
      node.port.onmessage = (e) => push(e.data);
    } else if (ctx.createScriptProcessor) {
      stage('准备录音（兼容模式）…');
      node = ctx.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (e) => push(e.inputBuffer.getChannelData(0).slice());
    } else {
      throw Error('这个浏览器既没有 AudioWorklet 也没有 ScriptProcessor，录不了。');
    }

    src = ctx.createMediaStreamSource(stream);
    // if it isn't connected to destination, Chrome never pulls this node and process never runs once
    mute = ctx.createGain();
    mute.gain.value = 0;
    src.connect(node);
    node.connect(mute);
    mute.connect(ctx.destination);

    const inRate = ctx.sampleRate || RATE;
    const tapKind = kind === 'worklet' ? 'AudioWorklet' : 'ScriptProcessor';
    stage('');
    return {
      cancel: teardown,
      /* seconds captured so far (at the device sample rate), used to tell the user "only 0.1 s recorded" */
      seconds: () => total / (inRate || RATE),
      /* two clues shown to the user when no sound is captured, rather than just saying "not a single sound captured" */
      diag: () => `音频引擎=${lastState || ctx.state}，采集=${tapKind}，采样率=${inRate}`,
      state: () => ctx.state,
      async stop() {
        if (closed) return new ArrayBuffer(0);
        teardown();

        // concatenate into one buffer, then downsample from the actual rate to 16 kHz
        const flat = new Float32Array(total);
        let o = 0;
        for (const c of chunks) { flat.set(c, o); o += c.length; }
        const pcm16 = resample(flat, inRate);
        const out = new Int16Array(pcm16.length);
        for (let i = 0; i < pcm16.length; i++) {
          const v = Math.max(-1, Math.min(1, pcm16[i]));
          out[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
        }
        return out.buffer;
      },
    };
  } catch (e) {
    // on failure always give the microphone back: otherwise the system's "recording" icon stays lit,
    // and the next getUserMedia fails because the device is busy, getting worse with each attempt.
    teardown();
    throw e;
  }
}

/** Hand a PCM clip to the board for recognition. Returns the recognized text */
async function asrOnBoard(pcm, signal) {
  const res = await fetch('/api/asr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: pcm,
    signal,
  });
  if (res.status === 401) throw Error('登录过期了，回上一页重新登录。');
  if (res.status === 413) throw Error('这段太长了，说短一点。');
  let body = null;
  try { body = await res.json(); } catch { throw Error(`板子没认出来（HTTP ${res.status}）`); }
  if (!body || body.ok !== true) throw Error((body && body.error) || '板子没认出来，再说一次？');
  return (body.data && body.data.text) || '';
}

export async function recognizePhoneRecording(pcm, signal, transcribe, onText) {
  if (signal.aborted) return false;
  const text = await transcribe(pcm, signal);
  if (signal.aborted || !text) return false;
  await onText(text);
  return true;
}

const micWhy = (e) => {
  // messages we throw ourselves (with the friendly flag) are already written; don't wrap them in another "microphone won't start:" (「麦克风起不来：」)
  if (e && e.friendly && e.message) return e.message;
  const n = e && e.name;
  const m = (e && e.message) ? `（${e.name || ''} ${e.message}）` : '';
  if (n === 'NotAllowedError' || n === 'SecurityError') {
    return `麦克风没给权限${m}。安卓 Chrome：点地址栏左边的锁 → 权限 → 麦克风 → 允许，再回来长按。`
      + '要是地址栏写着「不安全」，说明是自签证书被浏览器当可疑站点，先按页面里的提示装一下证书。';
  }
  if (n === 'NotFoundError' || n === 'OverconstrainedError') return '这台手机没找到可用的麦克风。';
  if (n === 'NotReadableError') return `麦克风被别的程序占着${m}：关掉录音机、微信语音这些再试。`;
  return `麦克风起不来：${(e && e.message) || e}${m}`;
};

// Show the permission state right on the page, so when "long press does nothing" you can tell whether permission wasn't granted or no sound was captured
const PERM_CN = { granted: '已经允许', prompt: '还没问过（第一次长按会弹）', denied: '被拒绝了', unknown: '不知道' };

const modeOf = () => {
  try { return localStorage.getItem(MODE_KEY) === 'phone' ? 'phone' : 'board'; } catch { return 'board'; }
};

function MicIcon() {
  return html`<svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="9" y="2.6" width="6" height="10.4" rx="3"/><path d="M5.6 11a6.4 6.4 0 0 0 12.8 0M12 17.4V21M8.6 21h6.8"/>
  </svg>`;
}

const BOARD_WORDS = '站起来 · 坐下 · 停下 · 前滚翻 · 低头捡东西 · 叫一声 · 打招呼 · 点头 · 摇头 · 歪头';
const KNOWN_WORDS = `走一小步 · ${BOARD_WORDS}`;

export function VoicePage({ st, pad, live, name, say }) {
  const [mode, setMode] = useState(modeOf());      // board | phone
  const [listening, setListening] = useState(false);  // phone microphone is recording
  const [boardBusy, setBoardBusy] = useState(false);
  const [heard, setHeard] = useState('');
  const [isInterim, setIsInterim] = useState(false);
  const [sent, setSent] = useState(null);          // {cn, ok}
  const [history, setHistory] = useState([]);      // [{cn, ok, at}]
  const [typed, setTyped] = useState('');
  const [err, setErr] = useState(null);
  const [ask, setAsk] = useState(null);            // reserved: there's no wake word now, always null
  const [perm, setPerm] = useState('unknown');     // microphone permission: granted / prompt / denied
  const [asrSec, setAsrSec] = useState(0);         // which second of recognition the board is on (so people know it's running)
  const [stage, setStage] = useState('');          // which step of opening the microphone it has reached (opening microphone… / loading recording script…)
  const pointerRef = useRef(null);
  const postureRef = useRef(null);
  postureRef.current = live ? st?.posture : null;
  useEffect(() => () => { postureRef.current = null; }, []);

  const audio = pad?.audio || {};
  const boardOk = audio.available === true;
  const boardOn = audio.listening === true;
  const phoneOk = SECURE && CAN_RECORD;
  // when the phone can't get the microphone, give one sentence explaining "why + what to do", so people don't think it's broken
  const phoneWhy = phoneOk ? null
    : !SECURE ? '这个页面是 http 打开的，手机浏览器不给网页用麦克风（要 https 才行）。'
      : '这台手机的浏览器不给网页用麦克风。';

  useEffect(() => { try { localStorage.setItem(MODE_KEY, mode); } catch { /* private mode */ } }, [mode]);

  // on entering the page: first put this connection back into the "in the gamepad area" state, otherwise all the audio commands below are rejected
  useEffect(() => {
    link.setPadVisible(true);
    openPadArea(link);
  }, []);

  // check the microphone permission once, and keep up with later changes (changes the user makes in settings show up immediately)
  useEffect(() => {
    const q = navigator.permissions && navigator.permissions.query;
    if (!q) return undefined;
    let p = null;
    navigator.permissions.query({ name: 'microphone' })
      .then((r) => { p = r; setPerm(r.state); r.onchange = () => setPerm(r.state); })
      .catch(() => { /* some browsers don't allow querying it; treat it as unknown */ });
    return () => { if (p) p.onchange = null; };
  }, []);

  /** Request permission explicitly once: if the system doesn't show a prompt on long press, use this button to trigger it */
  const askMic = useCallback(async () => {
    if (!CAN_RECORD) { setErr('这个浏览器压根没给网页录音的接口。'); return; }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach((t) => t.stop());      // only to get permission; give it back right away
      setPerm('granted');
      setErr(null);
    } catch (e) {
      setPerm('denied');
      setErr(micWhy(e));
    }
  }, []);

  const remember = useCallback((cn, ok) => {
    setHistory((h) => [{ cn, ok, at: Date.now() }, ...h].slice(0, 6));
  }, []);

  const dispatch = useCallback(async (cmd, said) => {
    setHeard(said);
    setIsInterim(false);
    setAsk(null);
    // ctx: pass in the live posture so "take a small step" and "sit down" start the policy themselves, without first saying "start walking"
    const out = await runAction(link, cmd, { getPosture: () => postureRef.current });
    const cn = CMD_CN[cmd] || out.cn;
    setSent({ cn, ok: out.ok, why: out.ok ? null : (out.error || null) });
    remember(cn, out.ok);
    if (!out.ok) { setErr(out.error || '发指令没成功'); return; }
    setErr(null);
    if (out.note) say(out.note);
  }, [remember, say]);

  /**
   * One sentence → action. Both paths are treated the same: what you say is what you get, **no need to say "鸭鸭" (Ducky)**.
   * (Saying "鸭鸭" is still recognized; parseUtterance strips it.)
   */
  const handleText = useCallback(async (text) => {
    const { cmd, said } = parseUtterance(text, { requireWake: false });
    if (cmd) { await dispatch(cmd, said); return; }
    setHeard(said || text);
    setIsInterim(false);
    setSent(null);
    setAsk(null);
    setErr(said ? `「${said}」还不会做。试试：${KNOWN_WORDS}` : '没听清，再说一遍？');
  }, [dispatch]);

  // ---- Phone microphone: press to start recording, release to send it back to the board for recognition ----
  const recRef = useRef(null);
  const turnRef = useRef(null);
  const discardPhone = useCallback(() => {
    pointerRef.current = null;
    turnRef.current?.abort();
    turnRef.current = null;
    recRef.current?.cancel();
    recRef.current = null;
  }, []);
  useEffect(() => discardPhone, [discardPhone]);

  const cancelPhone = useCallback(() => {
    discardPhone();
    setListening(false);
    setStage('');
    setIsInterim(false);
  }, [discardPhone]);

  const startPhone = useCallback(async (turn) => {
    setErr(null); setHeard(''); setIsInterim(false); setSent(null); setAsk(null);
    setListening(true);
    setStage('打开麦克风…');
    let timeout;
    const opening = openRecorder((message) => {
      if (!turn.signal.aborted) setStage(message);
    }).then((rec) => {
      if (turn.signal.aborted) { rec.cancel(); return; }
      recRef.current = rec;
      setStage('');
    });
    try {
      // every step has its own timeout (the error says which step it got stuck at);
      // this 18 s one is only the last-resort fallback, in case some step's promise never settles at all.
      await Promise.race([
        opening,
        new Promise((_, rej) => {
          const e = Error('麦克风一直没起来（18 秒）。先点上面的「允许麦克风」再长按；'
            + '还是不行就打开 /diag 做一次自检。');
          e.friendly = true;
          timeout = setTimeout(() => rej(e), 18000);
        }),
      ]);
    } catch (e) {
      if (turn.signal.aborted) return;
      cancelPhone();
      setErr(micWhy(e));
    } finally {
      clearTimeout(timeout);
    }
  }, [cancelPhone]);

  const stopPhone = useCallback(async (turn) => {
    const rec = recRef.current;
    recRef.current = null;
    setListening(false);
    setStage('');
    if (!rec) {
      turn.abort();                              // recording hadn't started yet when released
      return;
    }
    let pcm = null;
    try { pcm = await rec.stop(); }
    catch (e) {
      if (!turn.signal.aborted) setErr(`录音收尾失败：${(e && e.message) || e}`);
      return;
    }
    if (turn.signal.aborted) return;
    if (!pcm || pcm.byteLength < MIN_BYTES) {
      const s = typeof rec.seconds === 'function' ? rec.seconds() : 0;
      // include where exactly it got stuck: whether the audio engine wasn't running and which capture method was used, visible at a glance
      const why = typeof rec.diag === 'function' ? `（${rec.diag()}）` : '';
      if (s >= 0.05) {
        setErr(`只录到 ${s.toFixed(2)} 秒：按住的时候说话，说完整句再松开。${why}`);
      } else if (pcm && pcm.byteLength > 0) {
        setErr(`录到的声音太小了${why}：离手机近一点，按住的时候再说。`);
      } else {
        setErr(`一个音都没采到${why}：麦克风给了但音频引擎没跑起来。`
          + '先把这个标签页关掉重开，**第一次长按稍微按久一点**（要按满一秒）；'
          + '还这样的话就用系统 Chrome 打开这个地址，小米浏览器对网页录音支持不稳。');
      }
      return;
    }
    // recognition on the board takes a few seconds (the first sentence also has to load the model first); the page must "move" during this time, otherwise it looks like "nothing happened"
    setHeard('正在认…'); setIsInterim(true);
    setAsrSec(0);
    const tick = setInterval(() => {
      if (!turn.signal.aborted) setAsrSec((n) => n + 1);
    }, 1000);
    try {
      const recognized = await recognizePhoneRecording(pcm, turn.signal, asrOnBoard, handleText);
      if (!recognized && !turn.signal.aborted) {
        setIsInterim(false);
        setErr(`传回去了 ${(pcm.byteLength / 32000).toFixed(1)} 秒声音，板子没认出词。`
          + '离手机近一点、说慢一点，一次只说一个口令（比如「点头」）。');
        return;
      }
    } catch (e) {
      if (turn.signal.aborted) return;
      setHeard(''); setIsInterim(false);
      setErr((e && e.message) || '没认出来，再说一次？');
    } finally {
      clearInterval(tick);
    }
  }, [handleText]);

  const onDown = useCallback((event) => {
    if (!event.isPrimary || event.button !== 0 || pointerRef.current !== null) return;
    event.preventDefault();
    if (!phoneOk) { setErr(`${phoneWhy}用输入法上的话筒键听写，或者开板载麦克风。`); return; }
    discardPhone();
    pointerRef.current = event.pointerId;
    const turn = new AbortController();
    turnRef.current = turn;
    startPhone(turn);
  }, [discardPhone, phoneOk, phoneWhy, startPhone]);

  const onUp = useCallback((event) => {
    if (pointerRef.current !== event.pointerId) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right
        || event.clientY < bounds.top || event.clientY > bounds.bottom) {
      cancelPhone();
      return;
    }
    pointerRef.current = null;
    stopPhone(turnRef.current);
  }, [cancelPhone, stopPhone]);

  const onCancel = useCallback((event) => {
    if (pointerRef.current === event.pointerId) cancelPhone();
  }, [cancelPhone]);

  // ---- Onboard microphone: toggle duck-echo's listening ----
  const toggleBoard = useCallback(async (on) => {
    if (boardBusy) return;
    setErr(null);
    setBoardBusy(true);
    const r = await setAudio(link, { listening: Boolean(on) });
    setBoardBusy(false);
    if (r.ok === false) setErr(r.reason || r.error || '板载语音没切换成功');
    else say(on ? '板载麦克风开了：直接对它说话' : '板载麦克风关了');
  }, [boardBusy, say]);

  // results recognized by duck-echo (only newer duck-echo includes the last field; its absence doesn't affect other features).
  // seq is an auto-increment number on the board: saying the same command twice gives two different seqs, so deduplicate by it rather than by text.
  const last = audio.last;
  const lastSeq = useRef(-1);
  useEffect(() => {
    if (!boardOn || !last || !last.command) return;
    if (typeof last.seq === 'number' && last.seq === lastSeq.current) return;
    lastSeq.current = typeof last.seq === 'number' ? last.seq : lastSeq.current;
    const cn = CMD_CN[last.command] || last.command;
    setHeard(cn);
    setIsInterim(false);
    const failed = last.accepted === false;
    setSent({ cn, ok: !failed, why: failed ? (last.reason || null) : null });
    remember(cn, !failed);
  }, [boardOn, last, remember]);

  const submitTyped = (e) => {
    e.preventDefault();
    const v = typed.trim();
    if (!v) return;
    setTyped('');
    cancelPhone();
    handleText(v);
  };

  return html`<div class="m-voice-hero">
    <h1 class="m-voice-title">${name}，听我说</h1>
    <p class="m-voice-lede">${mode === 'board'
      ? html`直接对着${name}说话就行，说什么就是什么。`
      : html`按住对着手机说话，她说完松手就发过去。跟板载一样，直接说口令就行。`}</p>

    <div class="m-seg" role="group" aria-label="语音通道" style="margin:14px 0 0">
      <button aria-pressed=${mode === 'board' ? 'true' : 'false'} onClick=${() => { if (mode !== 'board') cancelPhone(); setMode('board'); setErr(null); setAsk(null); }}>
        板载麦克风${boardOn ? ' · 听' : ''}
      </button>
      <button aria-pressed=${mode === 'phone' ? 'true' : 'false'} onClick=${() => { setMode('phone'); setErr(null); setAsk(null); }}>
        手机说话
      </button>
    </div>

    ${mode === 'board' ? html`<div>
      <div class=${'m-mic-wrap' + (boardOn ? ' live' : '')}>
        <span class="m-halo" aria-hidden="true"></span>
        <button class=${'m-mic' + (boardOn ? ' live' : '')}
          onClick=${() => toggleBoard(!boardOn)} disabled=${boardBusy}
          aria-label=${boardOn ? '关闭板载聆听' : '打开板载聆听'}>
          <${MicIcon} />
          <span class="t1">${boardBusy ? '切换中…' : boardOn ? '板载在听' : '开板载聆听'}</span>
          <span class="t2">${boardOn ? '再点一下关掉' : '点了之后直接说话'}</span>
        </button>
      </div>
      <p class="m-tip">
        ${boardOn
          ? html`它在听：<b>直接说</b>「站起来」「点头」「停下」。说完点一下关掉，省电。`
          : html`用的是鸭子身上的麦克风。安静的时候最准，吵起来就换「手机说话」。`}
      </p>
      ${!boardOk ? html`<div class="m-banner bad" style="text-align:left">
        板载语音没连上：${audio.why || audio.error || 'duck-echo 没在跑'}。先用「手机说话」或打字。
      </div>` : audio.voice_ready === false ? html`<div class="m-banner bad" style="text-align:left">
        板载麦克风连上了，但语音识别还没准备好${audio.error ? `：${audio.error}` : '（模型加载中，稍等十几秒；一直这样就看一眼 duck-echo 日志）'}。
      </div>` : audio.error ? html`<div class="m-banner bad" style="text-align:left">
        板载语音报错：${audio.error}
      </div>` : null}
    </div>` : html`<div>
      <div class=${'m-mic-wrap' + (listening ? ' live' : '')}>
        <span class="m-halo" aria-hidden="true"></span>
        <button class=${'m-mic m-mic-talk' + (listening ? ' live' : '')}
          onPointerDown=${onDown} onPointerUp=${onUp} onPointerCancel=${onCancel} onPointerLeave=${onCancel} onLostPointerCapture=${onCancel}
          onContextMenu=${(e) => e.preventDefault()}
          aria-label="按住说话，松开发送">
          <${MicIcon} />
          <span class="t1">${listening ? (stage || '现在说') : '按住说话'}</span>
          ${listening ? html`<span class="t2">${stage ? '先别说话' : '说完松开'}</span>` : null}
        </button>
      </div>
      ${perm === 'denied' ? html`<div class="m-banner bad" style="text-align:left">
        <span>麦克风被浏览器拒绝了：地址栏左边的锁 → 权限 → 麦克风 → 允许。改完点右边再要一次。</span>
        <button class="act" onClick=${askMic}>再要一次</button>
      </div>` : null}
      ${perm !== 'granted' && perm !== 'denied' ? html`<div class="m-banner" style="text-align:left">
        <span>麦克风权限：${PERM_CN[perm]}。先点右边给它，长按才录得到声音。</span>
        <button class="act" onClick=${askMic}>允许麦克风</button>
      </div>` : null}
      <p class="m-tip">
        ${phoneOk
          ? html`按住<b>别松手</b>，等按钮变成「<b>现在说</b>」再开口，说完松开（识别在板子上做，不联网）。`
          : html`${phoneWhy}这条路暂时走不通，但下面的输入框（配上<b>输入法的话筒键</b>听写）和板载麦克风都能用。`}
      </p>
      <p class="m-tip"><a href="/diag">长按还是没反应？点这里做一次自检 →</a></p>
      ${boardOn ? html`<div class="m-banner" style="text-align:left">
        <span>板载麦克风还开着：两路一起听，同一句话可能执行两次。</span>
        <button class="act" onClick=${() => toggleBoard(false)}>关掉板载</button>
      </div>` : null}
    </div>`}

    <div class="m-sent">
      ${sent ? html`已发送：<b>${sent.cn}</b>${sent.ok ? '' : (sent.why ? `（没成功：${sent.why}）` : '（没成功）')}` : html`<span style="color:var(--text-3)">还没有指令</span>`}
    </div>

    <div class="m-heard">${mode === 'board' ? '它听到' : '听到你说'}</div>
    <div class=${'m-heard-text' + (isInterim ? ' interim' : '')}>${heard ? `「${heard}」` : '—'}</div>
    ${isInterim ? html`<div class="m-tip" style="margin-top:2px">
      板子在认… 已经 ${asrSec} 秒${asrSec >= 4 ? '（第一次要先把模型读进内存，慢一次，之后快）' : ''}
    </div>` : null}

    ${err ? html`<div class="m-banner bad" style="text-align:left">${err}</div>` : null}

    <form class="m-type" onSubmit=${submitTyped}>
      <input id="m-type" placeholder="也可以打字：站起来" value=${typed} enterkeyhint="send"
        onInput=${(e) => setTyped(e.currentTarget.value)} />
      <button class="m-btn primary" type="submit" disabled=${!typed.trim()}>发送</button>
    </form>

    <div class="m-policy-row">
      <button class="m-key pol-start" onClick=${() => dispatch('walk', '')}>开始走<small>start 策略</small></button>
      <button class="m-key pol-stop" onClick=${() => dispatch('stop', '')}>停止策略<small>stop 策略</small></button>
    </div>

    <h2 class="m-h2" style="text-align:left">它认这些</h2>
    <div class="m-card m-pad" style="text-align:left">
      <div class="m-sub">${mode === 'board' ? BOARD_WORDS : KNOWN_WORDS}</div>
      <div class="m-tip" style="margin-bottom:0">
        ${mode === 'board'
          ? html`板载识别只认这几个口令，说话时离鸭子近一点、慢一点；它动着的时候噪声大，先让它站好再说。`
          : html`按住别松手，说完再松。中间有错字也能认出来（「站起」= 站起来）。`}
      </div>
    </div>

    ${history.length ? html`<h2 class="m-h2" style="text-align:left">刚刚</h2>
      <div class="m-card m-pad" style="text-align:left">
        <ul class="m-log">
          ${history.map((h) => html`<li class=${h.ok ? '' : 'bad'}>
            <span class="who">${h.ok ? '✓' : '×'}</span><span class="what">${h.cn}</span>
            <span class="when">${new Date(h.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
          </li>`)}
        </ul>
      </div>` : null}

    <p class="m-tip">
      语音只在你说完那一刻下发一次指令；识别不到就什么都不做，不会让鸭子乱动。
      <b>卸力</b>永远在右上角。
    </p>
  </div>`;
}
