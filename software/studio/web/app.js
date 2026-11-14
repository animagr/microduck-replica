// Microduck Studio frontend. No build step: Preact + htm (vendor/preact-htm.module.js) run directly in the browser.
//
// There are only two channels to the Studio backend:
// - HTTP: /api/session, /api/login, /api/logout, /api/password, /api/logs, /api/diag;
// - WebSocket /ws: the backend pushes hello / state / log / result, the frontend sends hb (heartbeat, with whether the page is visible) and cmd (commands).
// For the message format see software/studio/README.md "frontend/backend protocol" (「前后端协议」).
import { html, render, Component, useState, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { ServoPage, HandBackButton } from './servo.js';
import { ImuPage } from './imu.js';
import { PadPage, padActivity, padGo } from './pad.js';
import { BatteryCell } from './battery.js';
import { BatterySettings } from './settings-battery.js';
import { AiSettings } from './settings-ai.js';
import { UpdateSettings } from './settings-updates.js';
import { AccessGuide, AiSshEntry } from './settings-access.js';
import { TuneSection, ModelSettings } from './tune.js';
import { WifiCard, WifiSettings, DuckAddresses } from './wifi.js';
import { TwoStep } from './confirm.js';
import { ModelsPage } from './models.js';
import { CameraPage, TofPage, SensorBandCells } from './sensors.js';
import { imuDiagnosticCopy, startupStageCopy } from './startup-status.js';

const STALE_GRAY_MS = 1000;   // no new data for more than 1 s: values turn gray
const STALE_ALARM_MS = 3000;  // more than 3 s: banner; the torque-release button can still be pressed (as long as the connection to Studio is up)

// ---------------- Connection ----------------

class Link {
  constructor() {
    this.ws = null;
    this.seq = 0;
    this.pending = new Map();
    this.listeners = new Set();
    this.status = 'connecting';
    this.lastAt = 0;
    this.backoff = 1000;
    this._hb = null;
    this.padCapture = false;
    document.addEventListener('visibilitychange', () => this.heartbeat());
  }

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(m) { for (const fn of this.listeners) fn(m); }
  setStatus(s) { this.status = s; this.emit({ t: '_status', status: s }); }

  connect() {
    clearTimeout(this._retry);
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    let opened = false;
    this.setStatus('connecting');
    ws.onopen = () => {
      opened = true;
      this.backoff = 1000;
      this.setStatus('open');
      this.heartbeat();
      clearInterval(this._hb);
      this._hb = setInterval(() => this.heartbeat(), 1000);
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;            // an old connection that has been replaced: ignore what it pushes
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      this.lastAt = performance.now();
      // in background tabs setInterval only runs once a minute, but receiving messages isn't throttled: reply whenever a server heartbeat arrives, so we aren't treated as disconnected
      if (m.t === 'hb') this.heartbeat();
      if (m.t === 'result' && this.pending.has(m.id)) {
        this.pending.get(m.id)(m);
        this.pending.delete(m.id);
      }
      this.emit(m);
    };
    ws.onclose = async (ev) => {
      if (this.ws !== ws) return;            // old connection (replaced by reconnect): don't touch the new connection's heartbeat
      clearInterval(this._hb);
      for (const done of this.pending.values()) done({ ok: false, error: '和 Studio 的连接断了' });
      this.pending.clear();
      if (ev.code === 4401) { this.setStatus('auth'); return; }   // login expired
      if (!opened) {
        // the handshake never succeeded: login may have expired (older Studio versions reject during the handshake, and the browser only sees 1006)
        try { if ((await api('/api/session', undefined, 2000)).status === 401) { this.setStatus('auth'); return; } } catch { /* Studio not running */ }
        if (this.ws !== ws) return;          // the user clicked "reconnect" while we were waiting: leave it to the new connection
      }
      this.setStatus('closed');
      this._retry = setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 8000);
    };
  }

  /** Wait for the connection to Studio to be established (on refresh the page appears first and the connection after: don't send commands before connecting) */
  whenOpen() {
    if (this.status === 'open') return Promise.resolve();
    return new Promise((resolve) => { const off = this.on((m) => { if (m.t === '_status' && m.status === 'open') { off(); resolve(); } }); });
  }

  reconnect() { this.backoff = 1000; try { this.ws && this.ws.close(); } catch { /* already closed */ } this.connect(); }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  // pad_visible: whether the gamepad block is currently on screen (overview rearrangement review O1). The backend uses only this to decide 10 Hz or 1 Hz gamepad snapshots;
  // #/pad is now an anchor on the overview, so the address being #/pad doesn't mean it's visible (scroll back up to the stage and the address bar still says #/pad)
  heartbeat() {
    this.send({ t: 'hb', seq: ++this.seq, visible: document.visibilityState === 'visible', route: location.hash.replace(/^#/, '') || '/',
      pad_visible: padActivity.active || this.padCapture });
  }

  // read-only tap for model key remapping: requests snapshots, doesn't change padActivity, and doesn't take over web remote control.
  setPadCapture(active) { this.padCapture = Boolean(active); this.heartbeat(); }

  cmd(name, args = {}, timeoutMs = 15000) {
    const id = `c${++this.seq}`;
    return new Promise((resolve) => {
      if (!this.send({ t: 'cmd', id, name, args })) { resolve({ ok: false, error: '和 Studio 的连接断了' }); return; }
      this.pending.set(id, resolve);
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); resolve({ ok: false, error: '鸭子没回话（超时）' }); }
      }, timeoutMs);
    });
  }
}

const link = new Link();
padActivity.bind(link);                  // send a heartbeat immediately at the moment of entering/leaving the gamepad area

let csrf = '';   // given by /api/session; mutating POSTs must carry it (X-CSRF), together with the backend's Origin check
async function api(path, body, timeoutMs = 10000, signal) {
  const opt = body === undefined ? { credentials: 'same-origin' }
    : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf }, body: JSON.stringify(body) };
  const ctl = new AbortController();
  const abort = () => ctl.abort();
  if (signal?.aborted) ctl.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => ctl.abort(), timeoutMs);   // when phone WiFi is flaky a request may hang for tens of seconds
  let r;
  let data = {};
  try {
    r = await fetch(path, { ...opt, signal: ctl.signal });
    try { data = await r.json(); } catch (error) { if (ctl.signal.aborted) throw error; }
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  return { status: r.status, ...data };
}

// ---------------- Small utilities ----------------

const fmt1 = (v) => (typeof v === 'number' && isFinite(v) ? v.toFixed(1) : '—');

function useNow(ms = 250) {
  const [now, setNow] = useState(performance.now());
  useEffect(() => { const t = setInterval(() => setNow(performance.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

function Badge({ kind }) {
  return html`<span class=${'badge ' + kind} aria-hidden="true">${kind === 'bad' ? '×' : '!'}</span>`;
}

// ---------------- Top safety bar ----------------

// Torque-release button: its state relies entirely on st.estop pushed by Studio (derived from the busStatus readback, not from "was it pressed").
// As long as the connection to Studio is up the button can be pressed, even if the state is stale or unreadable (code review #7: phones have no space bar,
// so if the button were disabled there'd be no way at all to release torque). It's only disabled when the connection is down.
// Space bar: both keydown and keyup are intercepted in the capture phase. If only keydown were intercepted, on keyup the browser would also "click" the focused button
// (e.g. a future "stand up"), standing right back up after releasing torque (review-impl-plan I6).
// Only not intercepted when focus is in a typing field (code review #8: space on checkboxes, radio buttons and dropdowns still releases torque).
const TEXT_TYPES = ['text', 'password', 'search', 'email', 'number', 'tel', 'url'];
const typing = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA'
  || (el.tagName === 'INPUT' && TEXT_TYPES.includes((el.type || 'text').toLowerCase())));
// Ctrl / Alt / Win + space are system shortcuts like switching input methods; not treated as torque release
const plainSpace = (e) => e.code === 'Space' && !e.ctrlKey && !e.altKey && !e.metaKey;

function EStop({ st, live, open }) {
  const [sentAt, setSentAt] = useState(0);
  const [err, setErr] = useState(null);
  const fire = useCallback(async () => {
    if (performance.now() - sentAt < 200) return;           // auto-repeat while holding space: at most 5 times per second
    setSentAt(performance.now()); setErr(null);
    const r = await link.cmd('relax', {}, 7000);       // backend worst case 3 + 0.1 + 3 s
    if (!r.ok) setErr(r.reason || r.error || '没发出去');
  }, [sentAt]);

  useEffect(() => {
    const down = (e) => {
      if (!plainSpace(e) || typing(e.target)) return;
      e.preventDefault(); e.stopPropagation();
      if (!e.repeat) fire();
    };
    const up = (e) => { if (plainSpace(e) && !typing(e.target)) { e.preventDefault(); e.stopPropagation(); } };
    window.addEventListener('keydown', down, true);
    window.addEventListener('keyup', up, true);
    return () => { window.removeEventListener('keydown', down, true); window.removeEventListener('keyup', up, true); };
  }, [fire]);

  const es = st?.estop || {};
  // torque release confirmed, so the earlier "not sent / timed out" message is outdated
  useEffect(() => { if (es.state === 'confirmed') setErr(null); }, [es.state]);
  const click = (e) => { e.currentTarget.blur(); fire(); };
  const note = (text) => (text ? html`<span class="why" role=${err ? 'alert' : undefined}>${text}</span>` : null);
  const fallback = st?.mode === 'commissioning' ? '只能关电源' : '用手柄 − 或关电源';
  if (!open) {
    // the connection to Studio is down: pressing it can't send anything
    return html`<span class="estop-wrap">${note(fallback)}
      <button class="estop unavailable" disabled>卸力 · 不可用</button></span>`;
  }
  if (st?.servo_orphan) {
    // the servo session was open when Studio last exited and wasn't taken over this time (review D1): robotd is absent and the bus isn't taken over, so pressing here can't send anything; take the user to the servo page to take over
    // (the servo page takes over the bus on entry, and after that torque release goes over the bus). Space still sends, and the backend replies "take over on the servo page first"
    return html`<span class="estop-wrap">${note(err || '可能还有舵机保持着')}
      <button class="estop unavailable" onClick=${(e) => { e.currentTarget.blur(); location.hash = '#/servos'; }}
        title="上次 Studio 退出时舵机会话开着、这次没接管上：先去舵机页接管总线，才能在总线上卸力">卸力 · 先去舵机页接管</button></span>`;
  }
  if (es.state === 'unavailable') {
    return html`<span class="estop-wrap">${note(err || es.why || fallback)}
      <button class="estop unavailable" onClick=${click}>卸力 · 不一定有效</button></span>`;
  }
  if (live && es.state === 'confirmed') {
    return html`<span class="estop-wrap">${note(err)}
      <button class="estop done" onClick=${click} title=${es.why}>已卸力 ✓</button></span>`;
  }
  // data stale (!live) still gets the red button: pressing it still sends, and Studio's dedicated torque-release path may be fine
  return html`<span class="estop-wrap">${note(err || (!live ? '状态不明，仍可按' : ''))}
    <button class="estop" onClick=${click} title="让 15 颗舵机全部卸力。鸭子会软下来，扶住。">
      ${es.state === 'pending' ? '卸力中…' : '卸力'}<span class="kbd">空格</span></button></span>`;
}

function TopBar({ duck, st, live, age, open, hideEStop }) {
  // the top bar first says the current mode (factory calibration mode / switch to motion mode after writing), then the pose; calibration mode has no policy, so don't call it "debugging".
  // reporting the startup phase continuously for more than 30 s (counted from when Studio connected this time): say "stuck reporting startup" (Oct 20 real hardware: the old fork's calibration mode always reports configuring_bus)
  const postureText = st ? ({ starting: st.start_wait?.text || (st.starting_long ? '一直报启动中' : '启动中'), absent: '主程序没在跑', homing: '在站起来',
    servo_session: '调舵机中' }[st.posture] || WAS[st.posture] || '状态不明') : null;
  const modeText = !st ? '连接中'
    : st.mode === 'commissioning' ? (st.posture === 'commissioning' ? '标定模式' : `标定模式 · ${postureText}`)
    : st.mode === 'motion' && st.posture !== 'absent' && st.posture !== 'servo_session' ? `运动模式 · ${postureText}`
    : postureText;
  const pct = st?.battery?.pct;
  // hovering the mouse over the name shows the current IP and a few addresses (the "More" page has a copyable block)
  const net = st?.net;
  const addrTitle = net?.known ? [`IP ${net.ip_now || '不知道'}`, ...(net.urls || []).map((u) => u.url)].join('\n') : undefined;
  return html`<header class="topbar">
    <div class="duckid">
      <span class="dot" style=${{ background: duck?.color || '#0F7C80' }}></span>
      <span class="name" title=${addrTitle}>${duck?.label || '鸭子'}</span>
      ${st?.servo_session ? html`<span class="sv-badge">调舵机中</span>` : null}
      <span class="meta num">${live ? '' : `${Math.round(age / 1000)} 秒前 · `}${modeText}${typeof pct === 'number' ? ` · ${Math.round(pct)}%` : ''}</span>
    </div>
    <span class=${hideEStop ? 'estop-hidden' : ''}><${EStop} st=${st} live=${live} open=${open} /></span>
  </header>`;
}

// ---------------- Servo session notice bar (below the top bar on every page; not repeated where the servo page's own header already has it) ----------------
// User, Oct 18: "leaving the servo page should keep torque enabled, it shouldn't go limp": while servos are holding, leaving the servo page doesn't hand back, and the session stays open;
// the main program is stopped then, so gamepad, remote, standing and walking all don't work, which is why every page must show it and offer a way back to the servo page or hand back. Page closed, network reconnect: the session is still there and still shown
// sticky (below the top bar, at all widths: review D6), so it's visible on phones even when scrolled to the gamepad area. The servo page's own header has the session text, so it isn't repeated there,
// but the two red ones, "main program was started manually" and "wasn't taken over at last exit", appear on every page
function ServoBar({ st, onServos }) {
  const ss = st?.servo_session;
  if (ss) {
    if (onServos) return null;
    const unk = ss.unknown ? ` · ${ss.unknown} 颗读不到扭矩（可能也在保持）` : '';
    return html`<div class="banner warn servo-bar" role="status">
      <b>调舵机中 · ${ss.holding ?? '?'} 颗保持着${unk} · 主程序停着（手柄、遥控、站走都不能用）</b>
      <span class="sb-acts"><a href="#/servos">回舵机页</a><${HandBackButton} link=${link} /></span>
      <span class="more sb-more">${ss.restored ? 'Studio 重启过，接着上次的会话管着。' : ''}急停用顶上红按钮或空格（手柄 Select 这时不管用）；别手动起 robotd，先点「交还主程序」</span>
      ${st.servo_marker_error ? html`<span class="more sb-more">${st.servo_marker_error}</span>` : null}</div>`;
  }
  // the main program was started manually during the session (review D9): when it starts it releases all servos and fights Studio for the serial port; Studio has already closed the bus (no servos written)
  if (st?.servo_conflict_s != null) {
    return html`<div class="banner bad servo-bar" role="alert"><b>主程序被手动起来了：它会把舵机全部松开、跟 Studio 抢串口</b>
      <span class="more sb-more">Studio 已经关掉舵机总线（没写舵机）。下次别手动起 robotd：先在页面上点「交还主程序」</span></div>`;
  }
  // the servo session was open when Studio last exited and wasn't taken over this time (review D1)
  if (st?.servo_orphan) {
    return html`<div class="banner bad servo-bar" role="alert"><b>上次退出时可能还有舵机保持着，去舵机页接管后才能卸力</b>
      ${onServos ? null : html`<a href="#/servos">去舵机页接管</a>`}
      <span class="more sb-more">Studio 重启时没接管上${st.servo_orphan.why ? `（${st.servo_orphan.why}）` : ''}；急的话关电源</span></div>`;
  }
  // handed back, main program not connected yet: keep the notice until the main program connects (the backend clears it once connected; it no longer disappears by itself after 10 minutes: review D12)
  if (st?.servo_handback_s != null) {
    if (st.servo_giveback_error) {
      return html`<div class="banner bad servo-bar" role="alert"><b>已交还，但主程序没起来</b>
        <span class="more sb-more">${st.servo_giveback_error}${st.servo_giveback_hint ? `：${st.servo_giveback_hint}` : ''}</span></div>`;
    }
    return html`<div class="banner warn servo-bar" role="status"><b>已交还。</b>
      ${st.servo_helper ? html`<span class="more">正在把主程序起回来…</span>`
        : html`<span class="more">主程序连上以后这条就收起。一直没连上（主程序是手动停的）就在鸭子上起来：<code>sudo systemctl start robotd</code></span>`}
      ${st.servo_handback_note ? html`<span class="more sb-more">${st.servo_handback_note}</span>` : null}</div>`;
  }
  return null;
}

// ---------------- Overview ----------------

// Stage text, per the state table in review-impl-plan I2. The stand, walk and sit buttons are in the gamepad block below (scroll down and you have the remote: overview rearrangement §1.2);
// torque release is in the top right (the top bar is sticky, always on screen), and there's another one at the top of the remote card.
const WAS = { holding: '站着', policy: '站着', walking: '在走', limp: '软着', sitting: '坐着', homing: '在站起来' };
function stageCopy(st, live, name, age) {
  if (!st) return { h: `正在连接${name}…`, sub: '鸭子开着、跟这台设备在同一个 WiFi 里就行。' };
  if (!live && st.posture !== 'absent') {
    return { h: `${name} ${Math.round(age / 1000)} 秒没响应`, sub: `断线前它${WAS[st.posture] || '的状态不清楚'}。软件现在管不到它。`, stale: true };
  }
  switch (st.posture) {
    case 'absent': return { h: '鸭子主程序没在跑', sub: '可能正在重启（约 2 秒）。注意：主程序停了不会卸力，舵机可能还顶着。', stale: true };
    case 'starting':
      if (startupStageCopy(st)) return startupStageCopy(st);
      // reporting the startup phase continuously for more than 30 s: stop saying "usually done within 10 s", offer "go to the log page" (Oct 20 real hardware: the old fork's calibration mode always reports configuring_bus)
      if (st.starting_long) {
        return { h: '主程序一直报「启动中」', act: { href: '#/logs', label: '去日志页' },
          sub: st.start_error ? `已经 ${st.starting_s} 秒了，卡在：${st.start_error}。去日志页看主程序最后说了什么。`
            : `已经 ${st.starting_s} 秒了。主程序可能其实起来了、只是状态没更新（旧版主程序的毛病），也可能卡在启动：去日志页看主程序最后说了什么。` };
      }
      return { h: '主程序正在启动', sub: st.start_error ? `卡在：${st.start_error}` : '通常 10 秒内完成。' };
    case 'commissioning': return { h: '标定模式', sub: '出厂第一次：先粗校 IMU、再一键中位，第 3 步写进主程序会自动切到运动模式。' };
    case 'limp': return { h: `${name}软着`, sub: '双手托起它，往下滑到「遥控」点「站起来」（或者按手柄 +）。' };
    case 'homing': return { h: '正在站起来…', sub: '扶着它，别松手。' };
    case 'holding': return { h: `${name}站好了`, sub: '往下滑到「遥控」点「开始走」（或者按手柄 +），再推摇杆。' };
    case 'policy': return { h: `${name}站着，准备好走了`, sub: '推摇杆就走（往下有网页手柄）；点「停下（站好）」或按手柄 + 回到站好。' };
    case 'walking': return { h: '正在走', sub: '松开摇杆它会停下、继续站着。' };
    case 'sitting': return { h: `${name}坐着`, sub: '点遥控里的「站起来」，或者按手柄十字键下。' };
    case 'servo_session': return { h: '正在调舵机', sub: '主程序停着（手柄、遥控、站走都不能用）。离开舵机页舵机照样保持，点顶上的「交还主程序」才交还。' };
    default: return { h: name, sub: '读不出它现在的姿势。' };
  }
}

// Stage: the wheel and single-finger touch on phones are left to the page (the overview is a home page you scroll down: review O2); Duck3D's pageScroll disables zoom and single-finger rotation;
// on desktop the mouse drags to rotate, on phones two fingers rotate. Shorter on phones (300 px), so the first screen shows the gauge strip and checklist (review O11).
// The disconnect banner overlays the stage instead of being inserted above it and pushing the controls below down (review O10)
function Stage({ st, live, age, name }) {
  const canvasRef = useRef(null);
  const duckRef = useRef(null);
  const [msg, setMsg] = useState(null);
  const [moved, setMoved] = useState(false);     // the user rotated the view: show "reset view" (「回正」)
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const phone = window.innerWidth < 700;   // phone: duck centered slightly high and a bit smaller, the space below left for text
    const d = new Duck3D(canvasRef.current, phone ? { view: 'front34', centerX: 0.5, centerY: 0.34, fill: 0.6, pageScroll: true }
      : { view: 'front34', centerX: 0.61, pageScroll: true });
    duckRef.current = d;
    d.onUserMove = () => setMoved(true);
    d.load('model/').then(() => setReady(true)).catch((e) => setMsg(`3D 模型没加载：${e.message}`));
    return () => d.dispose();
  }, []);

  useEffect(() => {
    if (!duckRef.current || !st) return;
    duckRef.current.setJoints(st.joints);
    duckRef.current.setGravity(st.gravity);
  }, [st]);

  const c = stageCopy(st, live, name, age);
  // no joint data (null) is also treated as stale: otherwise the default pose is shown in full color and looks live
  const jointsOld = st?.joints_age_ms == null || st.joints_age_ms > 1000;
  return html`<section class="stage stage-ov" aria-label="鸭子现在">
    ${/* graying uses a class: passing a style string to the canvas would completely override the touch-action:pan-y set by duck3d, and two fingers on phones would zoom the whole page (code review C6) */ ''}
    <canvas ref=${canvasRef} class=${c.stale || jointsOld ? 'stage-stale' : ''}></canvas>
    ${!live && st ? html`<div class="banner bad stage-banner" role="alert"><${Badge} kind="bad" />
      <b>连不上${name} · ${isFinite(age) ? Math.round(age / 1000) + ' 秒' : ''}</b><span class="more">站着的鸭子会停下、继续站着。</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); link.reconnect(); }}>重新连接</a></div>` : null}
    <div class="copy">
      <h1>${c.h}</h1>
      <p class="sub">${c.sub}</p>
      ${c.act ? html`<div class="btns"><button class="btn2 stage-act" onClick=${(e) => { e.currentTarget.blur(); location.hash = c.act.href; }}>${c.act.label}</button></div>` : null}
      ${msg ? html`<span class="tip" role="alert">${msg}</span>` : c.tip ? html`<span class="tip">${c.tip}</span>` : null}
    </div>
    ${c.stale && isFinite(age) ? html`<span class="age num">${Math.round(age / 1000)} 秒前</span>` : null}
    ${!ready ? html`<span class="sv-loading">3D 模型加载中…</span>` : null}
    ${moved ? html`<button class="reset-view" onClick=${(e) => { e.currentTarget.blur(); duckRef.current?.resetView(); setMoved(false); }}>回正</button>` : null}
  </section>`;
}

// Mainboard temperature cell (overview rearrangement §1.1, review O8): fields in studio/state.py cpu_view. Throttling is red (shows x / y MHz), frequency capping (not thermal) is reported as is,
// ≥ 80 °C is orange (with hysteresis, cleared only below 77 °C), unreadable shows "—" plus the reason. Our 80 °C is self-chosen, so it's only orange and not treated as an error
function boardCell(cpu) {
  const mhz = (k) => (typeof k === 'number' ? Math.round(k / 1000) : '?');
  if (typeof cpu?.c !== 'number') return { big: '—', small: cpu?.why || '读不到', kind: null };
  const studio = cpu.src === 'studio' ? ' · Studio 自己读的' : '';
  if (cpu.throttled) return { big: Math.round(cpu.c), small: `降频了：${mhz(cpu.khz)} / ${mhz(cpu.max_khz)} MHz${studio}`, kind: 'bad' };
  if (cpu.hot) return { big: Math.round(cpu.c), small: `有点热（80 °C 起提醒）${studio}`, kind: 'warn' };
  if (cpu.limited) return { big: Math.round(cpu.c), small: `被限频到 ${mhz(cpu.khz)} MHz（不是热的）${studio}`, kind: null };
  if (cpu.throttled == null) return { big: Math.round(cpu.c), small: `降频情况读不到${studio}`, kind: null };
  return { big: Math.round(cpu.c), small: `正常${studio}`, kind: null };
}

// Gamepad cell: uses the gamepad snapshot's status / estop (the same data as the gamepad block header below and onboarding checklist steps 3 and 4: review O7);
// state.pad is only used when there's no gamepad backend (bench mode). Labeled "gamepad e-stop" (「手柄急停」), separate from the top bar's "torque release" (「卸力」)
function padCell(st, pd) {
  if (!pd) {
    const p = st?.pad || {};
    return { word: !p.known ? '不知道' : p.connected ? '已连' : '没连',
      small: !p.known ? '读不到手柄状态' : p.connected ? `${p.name || '手柄'}${p.estop_ok ? ' · 手柄急停有效' : ''}` : '去配对' };
  }
  const s = pd.status || {}, lv = pd.live || {}, es = pd.estop || {};
  const attached = lv.state === 'attached';
  const known = !!s.known || attached;
  const connected = !!s.active || attached;
  const name = s.active?.name || (attached ? lv.device?.name : null) || '手柄';
  const esw = { ok: '手柄急停有效 ✓', unknown: '手柄急停没核对完', bad: '手柄急停无效' }[es.state] || '';
  if (!known) return { word: '不知道', small: '读不到手柄状态（configd）' };
  if (connected) return { word: '已连', small: `${name}${esw ? ` · ${esw}` : ''}` };
  return { word: '没连', small: (s.pads || []).length ? '配过：打开手柄就会自己连上' : '去配对' };
}

// The sticky layers (user, Oct 19: when scrolling down, the sidebar and gauge strip stay put) measure their own height and write it to CSS variables on the root (--bar-h servo notice bar, --band-h gauge strip):
// the sticky gamepad 3D card below, the servo page's left column and the stop position when scrolling to the gamepad area all shift down. Not sticky (gauge strip on phones) or hidden (other pages) records 0
function useStickyHeight(name) {
  const ro = useRef(null);
  return useCallback((el) => {
    const root = document.documentElement.style;
    ro.current?.disconnect();
    ro.current = null;
    const put = () => root.setProperty(name, el && getComputedStyle(el).position === 'sticky' ? `${el.offsetHeight}px` : '0px');
    put();
    if (el && typeof ResizeObserver !== 'undefined') {
      ro.current = new ResizeObserver(put);
      ro.current.observe(el);
    }
  }, [name]);
}

function Band({ st, pd, gray, live, diagnosticElapsed = 0, onSame, sensorsActive }) {
  const bandRef = useStickyHeight('--band-h');
  const b = st?.battery || {}, s = st?.servos || {}, imu = st?.imu || {};
  const diagnostic = st?.posture === 'starting' && (imu.source == null || imu.source === 'bus')
    ? imuDiagnosticCopy(imu.diagnostic, live, diagnosticElapsed) : null;
  const imuWord = diagnostic?.word || { ok: '正常', unverified: '方向没确认', frozen: '读数冻住了', missing: '没读到' }[imu.status] || '—';
  const imuKind = diagnostic ? diagnostic.kind : { unverified: 'warn', frozen: 'bad', missing: 'bad' }[imu.status];
  const pct = typeof b.pct === 'number' ? Math.round(b.pct) : null;
  const cpu = boardCell(st?.cpu);
  const pad = padCell(st, pd);
  return html`<section class=${'band board' + (gray ? ' stale' : '')} aria-label="状态" ref=${bandRef}>
    <${BatteryCell} b=${b} />
    <div>
      <span class="label">舵机</span>
      <span class="num" style="display:flex;align-items:baseline;gap:4px"><span class="big">${s.online ?? '—'}</span><span class="unit">/ ${s.total ?? 15}</span></span>
      <span class="small">${s.hottest ? `最热 ${Math.round(s.hottest.c)} °C · ${s.hottest.name}` : '—'}</span>
    </div>
    <a href="#/imu">
      <span class="label">IMU</span>
      <span class="word">${imuKind ? html`<${Badge} kind=${imuKind} />` : null}${imuWord}</span>
      <span class="small">${diagnostic ? diagnostic.board || 'ID 200 · 只读诊断' : { unverified: '先只站着', ok: '方向已确认' }[imu.status] || '去校准'}</span>
    </a>
    <${SensorBandCells} api=${api} active=${sensorsActive} />
    <a href="#/pad" onClick=${(e) => onSame(e, '#/pad')}>
      <span class="label">手柄</span>
      <span class="word">${pad.word}</span>
      <span class="small">${pad.small}</span>
    </a>
    <div class=${'band-cpu' + (cpu.kind ? ` ${cpu.kind}` : '')}>
      <span class="label">主板</span>
      <span class="num" style="display:flex;align-items:baseline;gap:4px"><span class="big">${cpu.big}</span>${cpu.big !== '—' ? html`<span class="unit">°C</span>` : null}</span>
      <span class="small">${cpu.kind ? html`<${Badge} kind=${cpu.kind} /> ` : null}${cpu.small}</span>
    </div>
  </section>`;
}

// ---------------- Onboarding checklist (overview rearrangement §1.3, §5 O14: 6 rows + "connect to the duck" in the card header; task 11 added "write into the main program") ----------------
// All the judging is in the backend (studio/onboard.py, judged every 0.5 s); this only draws. Five states: ✓ done · ↷ skipped · ● to do / redo · ○ not done · ? unreadable.
// "Do now" = the first ● / ○ step (ob.next), whose first button is the dark "do it" (「去做」); later ones aren't locked and can still be clicked.
// Every row always has three buttons: "do it", "done", "skip" (「去做」「已完成」「跳过」) (user, Oct 20: "do it, done, skip, three is fine"; cases that used to be locked are clickable too).
// Those with consequences (main program says explicitly it's not done, unreadable, a problem was detected, e-stop test, while tuning servos) take two clicks: the second-click button states the consequence (mark.*.ask from the backend),
// only the page's second click carries confirmed, and the backend rejects it otherwise. ✓ rows have "redo" (i.e. that step's do-it); ✓ / ↷ marked by the user also have "cancel" / "cancel skip".
// When everything is done it collapses into one line that can be expanded to show the 6 rows (each redoable); whether it's expanded is stored in localStorage

const ONB_MARK = { ok: '✓', skip: '↷', todo: '●', no: '○', unk: '?' };
const ONB_WORD = { ok: '完成', skip: '跳过了', todo: '该做', no: '没做', unk: '读不到' };
const ONB_OPEN_KEY = 'studio.onb.open';
const ONB_FROZEN = '在调舵机：清单停在调之前的样子；这时标的「已完成」「跳过」要等交还主程序以后才显示';
function fmtWhen(w) {
  if (w == null || w === '') return null;
  let d = null;
  if (typeof w === 'number') d = new Date(w * 1000);
  else if (typeof w === 'string') { const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(w); if (m) d = new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]); }
  if (!d || isNaN(d.getTime())) return String(w);
  if (d.getFullYear() < 2024) return '时间不准（鸭子没联网）';    // when the duck boots without network the wall clock is stuck at 1970 (review O6)
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function loadOnbOpen() { try { return localStorage.getItem(ONB_OPEN_KEY) === '1'; } catch { return false; } }
function saveOnbOpen(v) { try { localStorage.setItem(ONB_OPEN_KEY, v ? '1' : '0'); } catch { /* private mode */ } }

function Onboard({ st, live }) {
  const ob = st?.onboarding;
  const [msg, setMsg] = useState(null);
  const [open, setOpen] = useState(loadOnbOpen);
  const [cprev, setCprev] = useState(null);       // result of "preview what will be written" (each servo's direction, limits, IMU orientation, TOML)
  const [cmsg, setCmsg] = useState(null);         // message for this click of the preview / write button
  const [cbusy, setCbusy] = useState(false);
  const [copen, setCopen] = useState(false);      // the "write into the main program" card: collapsed when done / undeterminable; expands only on "take a look" or "redo"
  const job = st?.commit?.job;                   // write progress / result (pushed by Studio; st.commit is only used in step 3)
  // once the progress card appears, the local temporary "started writing" ack gives way: failure reasons are shown only by job, and on success the card can collapse by itself after 2 minutes.
  useEffect(() => {
    if (job) setCmsg(null);
  }, [job?.phase, job?.ok, job?.finished]);
  // Writing restarts the main program, during which the page counts as "not connected". Step 3's progress / failure reason must not be hidden by "don't check while disconnected":
  // if there's a job, show a separate card (the backend stops pushing a successful one after 2 minutes, so the card collapses naturally).
  if (!live && job) {
    const title = job.phase === 'running' ? '写进主程序' : (job.ok ? '写进主程序：好了' : '写进主程序：没成');
    return html`<section class="onb board" data-step="commit" aria-label="写进主程序进度">
      <div class="onb-h"><b>${title}</b><span class="quiet">主程序在重启，页面暂时没连着</span></div>
      <div class="onb-commit">
        ${job.phase === 'running'
          ? html`<div class="onb-commit-job" role="status"><span class="onb-spin">⋯</span>${job.msg || '在写…'}</div>`
          : html`<div class=${'onb-commit-msg ' + (job.ok ? 'ok' : 'bad')}>${job.reason || job.msg || ''}</div>`}
        ${job.phase !== 'running' && !job.ok ? html`<p class="onb-tip">小助手会把原来的标定文件和模式换回去；等主程序回来再看第 3 步。</p>` : null}
      </div>
    </section>`;
  }
  if (!live) return html`<section class="onb board"><div class="onb-h"><b>上手清单</b><span class="quiet">断线时不检查</span></div></section>`;
  if (!ob) return html`<section class="onb board"><div class="onb-h"><b>上手清单</b><span class="quiet">还在判…</span></div></section>`;
  const head = ob.header || {};
  if (head.kind === 'bench') return html`<section class="onb board"><div class="onb-h"><b>上手清单</b><span class="quiet">${head.text}</span></div></section>`;
  const done = ob.all_done && head.ok;
  const n = ob.skipped_n || 0;
  const m = ob.marked_n || 0;
  const counts = [n ? `跳过 ${n} 步` : '', m ? `标了已完成 ${m} 步` : ''].filter(Boolean).join('、');
  const doneText = `上手 6 步都完成了${counts ? `（${counts}）` : ''}`;
  const toggle = () => { const v = !open; setOpen(v); saveOnbOpen(v); };
  if (done && !open) {
    return html`<section class="onb board onb-done" aria-label="上手清单">
      <button class="onb-fold" aria-expanded="false" onClick=${toggle}><span class="onb-mark onb-ok">✓</span><b>${doneText}</b>
        <span class="onb-more">展开</span></button></section>`;
  }
  const op = async (args, okText) => {
    const r = await link.cmd('onboard.op', args, 8000);
    setMsg(r.ok ? (okText ? { ok: true, text: okText } : null) : { ok: false, text: r.reason || r.error || '没记成' });
  };
  const go = async (a, row) => {
    setMsg(null);
    if (a.do === 'servos') location.hash = '#/servos';
    else if (a.do === 'imu') location.hash = '#/imu';
    else if (a.do === 'commit') {
      setCopen(true);
      setTimeout(() => document.querySelector('[data-step="commit"] .onb-commit')?.scrollIntoView({ block: 'center' }), 50);
    }
    else if (a.do === 'pad_wizard') padGo('wizard');
    else if (a.do === 'pad_known') padGo('known');
    else if (a.do === 'estop') padGo('estop');
    else if (a.do === 'remote') padGo('remote');
    else if (a.do === 'robotd' || a.do === 'logs') location.hash = '#/logs';   // "go to the log page" for the "main program mode" item in step 3
  };
  // Step 3: preview (helper dry_run / Studio computes directly on a computer) and the real write. Writing starts once the ack returns; progress is in st.commit.job.
  const commitPreview = async () => {
    if (cprev) { setCprev(null); return; }
    setCmsg(null);
    const r = await link.cmd('calib.op', { op: 'preview' }, 20000);
    if (r.ok) setCprev(r.data || {});
    else setCmsg({ ok: false, text: r.reason || r.error || '算不出来' });
  };
  const commitRun = async () => {
    setCmsg(null);
    setCbusy(true);
    try {
      const r = await link.cmd('calib.op', { op: 'commit' }, 20000);
      if (!r.ok) setCmsg({ ok: false, text: r.reason || r.error || '没开始写' });
      else setCmsg({ ok: true, text: '开始写了：主程序会重启，等它回来' });
    } finally {
      setCbusy(false);
    }
  };
  const btn = (a, row, dark) => html`<button class=${dark ? 'btn-dark' : 'btn-light'} onClick=${() => go(a, row)}>${a.label}</button>`;
  const frozen = !!ob.frozen;               // the checklist is frozen while tuning servos: marking and canceling both take two clicks (marks only show after handing back)
  const fa = ob.frozen_ask || {};
  // "done" (done) / "skip" (skip): if the backend says two clicks are needed (mark.*.ask) or it's frozen, use TwoStep; only the second click carries confirmed
  const markBtn = (row, kind, label, cls) => {
    const ask = (row.mark || {})[kind]?.ask || (frozen ? fa[kind] : null);
    const args = { op: kind, step: row.key };
    return ask ? html`<${TwoStep} label=${label} ask=${ask} cls=${'btn-light ' + cls} askCls="btn-light onb-skip-arm"
        onConfirm=${() => op({ ...args, confirmed: true })} />`
      : html`<button class=${'btn-light ' + cls} onClick=${() => op(args)}>${label}</button>`;
  };
  const undoBtn = (row) => {
    const args = { op: row.marked === 'skip' ? 'unskip' : 'undone', step: row.key };
    const label = row.marked === 'skip' ? '取消跳过' : '取消';
    return frozen ? html`<${TwoStep} label=${label} ask=${fa.undo || '确定取消？'} cls="btn-light onb-unskip" askCls="btn-light onb-skip-arm"
        onConfirm=${() => op({ ...args, confirmed: true })} />`
      : html`<button class="btn-light onb-unskip" onClick=${() => op(args)}>${label}</button>`;
  };
  return html`<section class=${'onb board' + (ob.frozen ? ' onb-frozen' : '')} aria-label="上手清单">
    <div class="onb-h">
      <b>上手清单</b>
      ${done ? html`<button class="onb-fold onb-fold-h" aria-expanded="true" onClick=${toggle}><span class="onb-mark onb-ok">✓</span>${doneText}
        <span class="onb-more">收起</span></button>`
        : head.ok ? html`<span class="onb-conn"><span class="onb-mark onb-ok">✓</span>连上鸭子</span>`
        : html`<span class="onb-conn onb-conn-bad"><${Badge} kind=${head.kind === 'servo' || head.kind === 'connecting' || head.kind === 'bench' ? 'warn' : 'bad'} />
          ${head.text}${head.raw ? html`<small>原文：${head.raw}</small>` : null}</span>`}
      ${ob.frozen ? html`<span class="onb-tip onb-noskip">${ONB_FROZEN}</span>` : null}
    </div>
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>知道了</a></div>` : null}
    <ol class="onb-rows">
      ${(ob.rows || []).map((r) => {
        const now = ob.next === r.key;
        const when = fmtWhen(r.when);
        const goA = { do: r.go, label: '去做' };
        // the step 3 card only expands inside the "write into the main program" row: not done yet (● / ○), writing / just written, or "take a look" / "redo" clicked;
        // collapsed when done (✓), skipped, or undeterminable (?)
        const isCommit = r.key === 'commit' && (r.state === 'todo' || r.state === 'no' || copen || !!job || !!cmsg || !!cprev);
        let acts;
        if (r.marked) {
          // ✓ / ↷ marked by the user: "redo" (i.e. that step's do-it) + "cancel" / "cancel skip" (review D12)
          acts = html`<button class="btn-light onb-redo" onClick=${() => go(goA, r)}>重新做</button>${undoBtn(r)}`;
        } else if (r.state === 'ok') acts = html`<button class="btn-light onb-redo" onClick=${() => go(goA, r)}>重新做</button>`;
        else {
          // three buttons: do it (this row's own action, or go to the GO page if none), done, skip. Rows where a problem was detected (found: review D5) label the first one "redo"
          const first = (r.actions || []).length ? r.actions : [goA];
          acts = html`${first.map((a, i) => btn(r.found && i === 0 ? { ...a, label: '重新做' }
            : now && i === 0 ? { ...a, label: '去做' } : a, r, now && i === 0))}${markBtn(r, 'done', '已完成', 'onb-donebtn')}${markBtn(r, 'skip', '跳过', 'onb-skip')}`;
        }
        return html`<li class=${'onb-row onb-' + r.state + (now ? ' onb-now' : '')} key=${r.key} data-step=${r.key}>
          <span class=${'onb-mark onb-' + r.state} aria-label=${ONB_WORD[r.state] || '读不到'}>${ONB_MARK[r.state] || '?'}</span>
          <span class="onb-body">
            <span class="onb-title"><b>${r.n} ${r.title}</b>${now ? html`<span class="onb-tag">现在该做</span>` : null}${when && !r.marked ? html`<span class="onb-when num">${when}</span>` : null}</span>
            <span class="onb-text">${r.text}${r.marked ? `（${when || '时间不知道'}）` : ''}</span>
            ${r.note ? html`<span class="onb-tip">${r.marked ? `现在：${r.note}` : r.note}</span>` : null}
            ${r.tip && r.state !== 'ok' && r.state !== 'skip' ? html`<span class="onb-tip">坑：${r.tip}</span>` : null}
            ${isCommit ? html`<div class="onb-commit">
              <div class="onb-commit-desc">${r.desc || ''}</div>
              ${(r.commit?.items || []).length ? html`<ul class="onb-checks">
                ${r.commit.items.map((it) => html`<li class=${it.ok ? 'ok' : 'bad'}>
                  <span class="onb-check-mark" aria-label=${it.ok ? '好' : '还不行'}>${it.ok ? '✓' : '×'}</span>
                  <span class="onb-check-body"><b>${it.label}</b><span>${it.text}</span></span>
                  ${!it.ok && it.action ? html`<button class="btn-light onb-check-go" onClick=${() => go(it.action, r)}>${it.action.label || '去做'}</button>` : null}
                </li>`)}
              </ul>` : null}
              <div class="onb-commit-acts">
                <button class="btn-light" disabled=${cbusy} onClick=${commitPreview}>${cprev ? '收起要写的内容' : '先看看要写什么'}</button>
                ${/* step 2 marked and IMU written with the default mounting (task 17): spell it out on the second click */ ''}
                <${TwoStep} label="写进主程序" ask=${r.commit?.imu_default ? '确定？IMU 按默认装法写' : '会重启主程序，鸭子会先卸力，扶好鸭子'}
                  cls="btn-dark" disabled=${!r.commit?.ready || cbusy}
                  title=${!r.commit?.ready ? '准备情况还没全绿：照上面的清单补齐' : ''} onConfirm=${commitRun} />
              </div>
              ${cmsg ? html`<div class=${'onb-commit-msg ' + (cmsg.ok ? 'ok' : 'bad')}>${cmsg.text}</div>` : null}
              ${job && job.phase === 'running' ? html`<div class="onb-commit-job" role="status"><span class="onb-spin">⋯</span>${job.msg || '在写…'}</div>` : null}
              ${job && job.phase !== 'running' && job.reason ? html`<div class=${'onb-commit-msg ' + (job.ok ? 'ok' : 'bad')}>${job.reason}</div>` : null}
              ${cprev ? html`<div class="onb-preview">
                <div class="onb-preview-imu"><b>IMU</b> ${cprev.imu?.label || ''} · ${cprev.imu?.text || ''}${cprev.imu?.default ? `（按默认装法写：${cprev.imu.default}）` : ''}</div>
                <table class="onb-preview-table"><thead><tr><th>关节</th><th>方向</th><th>限位</th></tr></thead><tbody>
                  ${(cprev.joints || []).map((j) => html`<tr><td>${j.cn || j.name}</td><td>${j.direction > 0 ? '+1' : '−1'}</td><td class="num">${j.min_deg}° ~ ${j.max_deg}°</td></tr>`)}
                </tbody></table>
                <details class="onb-preview-toml"><summary>要写的文件</summary><pre>${cprev.toml || ''}</pre></details>
              </div>` : null}
            </div>` : null}
          </span>
          <span class="onb-acts">${acts}</span>
        </li>`;
      })}
    </ol>
  </section>`;
}

// To-do: the onboarding checklist already explains the same thing, so it isn't repeated in the to-do list (review O15). Only dedupe when the checklist row / card header is really saying the same thing:
// when the checklist shows "?" (unreadable), the to-do item is still kept (code review C4)
const TODO_IN_ONB = {
  starting: (ob) => ['starting', 'stuck_calib'].includes(ob.header?.kind),
  absent: (ob) => ob.header?.kind === 'absent',
  servo_session: (ob) => ob.header?.kind === 'servo',
  imu_unverified: (ob) => ['todo', 'no'].includes((ob.rows || []).find((r) => r.key === 'imu')?.state),
};
function Todo({ st, live }) {
  const ob = st?.onboarding;
  const all = (st?.todo || []).filter((it) => !(ob && TODO_IN_ONB[it.key] && TODO_IN_ONB[it.key](ob)));
  const items = all.slice(0, 2);
  const more = all.length - items.length;
  if (!live) return html`<section class="todo board"><span class="quiet">断线时不检查</span></section>`;
  if (!items.length) {
    return html`<section class="todo board"><span class="quiet">没有要处理的事</span>
      <span class="when num">${st?.health_age_ms != null ? `${Math.round(st.health_age_ms / 1000)} 秒前查过` : ''}</span></section>`;
  }
  return html`<section class="todo board list">
    ${items.map((it) => html`<div class="item">
      <${Badge} kind=${it.level === 'error' ? 'bad' : 'warn'} />
      <span class="msg">${it.msg}</span>
      <span class="hint">${it.hint || ''}</span>
    </div>`)}
    ${more > 0 ? html`<a href="#/logs" style="font-size:13px">还有 ${more} 条 ›</a>` : null}
  </section>`;
}

// Overview: ("Join WiFi" on top when the hotspot is on) → stage → gauge strip (5 cells) → onboarding checklist → to-do → scroll down for the gamepad (overview rearrangement §1)
function Overview({ st, live, age, diagnosticElapsed, duck, pd, onSame, tune, sensorsActive }) {
  // English names like hostnames get a space before the Chinese that follows: "duck-c51b 站好了" (duck-c51b is standing)
  const short = duck?.short || '鸭子';
  const name = /[A-Za-z0-9]$/.test(short) ? short + ' ' : short;
  return html`<div class="overview">
    ${st?.net?.known && st.net.mode === 'hotspot'
      ? html`<${WifiCard} net=${st.net} link=${link} secure=${st?.auth?.has_password} />` : null}
    <${Stage} st=${st} live=${live} age=${age} name=${name} />
    <${Band} st=${st} pd=${pd} live=${live} diagnosticElapsed=${diagnosticElapsed} gray=${age > STALE_GRAY_MS} onSame=${onSame} sensorsActive=${sensorsActive} />
    <${AiSshEntry} />
    <${Onboard} st=${st} live=${live} />
    <${Todo} st=${st} live=${live} />
    <${PadPage} st=${st} pad=${pd} link=${link} api=${api} previewActive=${sensorsActive} live=${live} />
    <${TuneSection} tune=${tune} />
  </div>`;
}

// ---------------- Logs ----------------

function Logs() {
  const [items, setItems] = useState([]);
  const [onlyBad, setOnlyBad] = useState(false);
  const [cat, setCat] = useState('');
  useEffect(() => {
    api('/api/logs?limit=300').then((r) => setItems(r.items || []));
    return link.on((m) => { if (m.t === 'log') setItems((xs) => [...xs.slice(-499), m.entry]); });
  }, []);
  const shown = items.filter((e) => (!onlyBad || e.level !== 'info') && (!cat || e.cat === cat));
  const cats = [...new Set(items.map((e) => e.cat))];
  const copy = () => navigator.clipboard && navigator.clipboard.writeText(shown.map((e) =>
    `${e.t} [${e.cat}]${e.level === 'info' ? '' : `[${e.level}]`} ${e.msg}${e.step ? ` · ${e.level === 'info' ? '步骤' : '卡在'}：${e.step}` : ''}${e.raw ? ` · 原文：${e.raw}` : ''}${e.hint ? ` · 建议：${e.hint}` : ''}`).join('\n'));
  return html`<div style="display:flex;flex-direction:column;gap:12px">
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px">
      <h1 style="margin:0;font-size:28px;font-weight:600;flex:1">日志</h1>
      <select value=${cat} onChange=${(e) => setCat(e.target.value)} aria-label="按分类看">
        <option value="">全部分类</option>${cats.map((c) => html`<option value=${c}>${c}</option>`)}
      </select>
      <label style="font-size:14px"><input type="checkbox" checked=${onlyBad} onChange=${(e) => setOnlyBad(e.target.checked)} /> 只看警告和错误</label>
      <button onClick=${copy} style="height:34px;padding:0 14px;border:0;border-radius:999px;background:#E5E5EA">复制</button>
      <a class="logs-export" href="/api/diag" style="font-size:14px" title="含鸭子的序列号和局域网 IP">导出诊断包（发群里求助用）</a>
    </div>
    <div class="board" style="padding:8px 16px;font-size:14px;line-height:1.7">
      ${shown.length ? shown.slice().reverse().map((e) => html`<div key=${e.n} style="padding:4px 0;border-top:1px solid var(--line)">
        <span class="num" style="color:var(--text-2)">${e.t}</span> <span style="color:var(--text-2)">[${e.cat}]</span>
        ${e.level === 'warn' ? html` <${Badge} kind="warn" />` : e.level === 'error' ? html` <${Badge} kind="bad" />` : ''} ${e.msg}
        ${e.step || e.raw || e.hint ? html`<div style="font-size:13px;color:var(--text-2)">
          ${e.step ? html`${e.level === 'info' ? '步骤' : '卡在'}：${e.step}　` : ''}${e.raw ? html`原文：${e.raw}　` : ''}${e.hint ? html`建议：${e.hint}` : ''}</div>` : null}
      </div>`) : html`<div style="color:var(--text-2)">还没有日志。</div>`}
    </div>
  </div>`;
}

// the page receives state 10 times a second and Main redraws along with it; the log page doesn't depend on state, so don't redraw 500 lines with it (code review #20)
class LogsPage extends Component {
  shouldComponentUpdate() { return false; }
  render() { return html`<${Logs} />`; }
}

// ---------------- Settings (the first slice only has the stage background) ----------------

const STAGES = [['mid', '中灰（推荐）'], ['graphite', '石墨'], ['light', '浅灰']];
function applyStage(v) {
  if (v === 'mid') document.documentElement.removeAttribute('data-stage');
  else document.documentElement.setAttribute('data-stage', v);
}
function loadStage() { try { return localStorage.getItem('studio.stage') || 'mid'; } catch { return 'mid'; } }

// Setting the first web password replaces the anonymous cookie/CSRF session.
// Refresh it before the next SSH POST and reconnect the status stream with that cookie.
async function refreshAccessSession() {
  const session = await api('/api/session');
  if (session.status !== 200 || !session.csrf) throw new Error('session unavailable');
  csrf = session.csrf;
  link.reconnect();
}

function Settings({ st, tune }) {
  const [v, setV] = useState(loadStage());
  const pick = (x) => { setV(x); applyStage(x); try { localStorage.setItem('studio.stage', x); } catch { /* private mode */ } };
  return html`<div style="display:flex;flex-direction:column;gap:16px;max-width:640px">
    <h1 style="margin:0;font-size:28px;font-weight:600">设置</h1>
    <${AiSshEntry} />
    <${UpdateSettings} api=${api} csrf=${csrf} />
    <${AiSettings} api=${api} />
    <div class="board" style="padding:16px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center">
      <span style="font-size:15px;font-weight:600;flex:1">日志和诊断</span>
      <a class="settings-logs" href="#/logs" style="font-size:15px">日志</a>
      <a class="settings-diag" href="/api/diag" style="font-size:15px" title="含鸭子的序列号和局域网 IP">导出诊断包</a>
    </div>
    <${DuckAddresses} net=${st?.net} />
    <${WifiSettings} net=${st?.net} link=${link} />
    <${AccessGuide} api=${api} hasPassword=${st?.auth?.has_password} net=${st?.net} refreshSession=${refreshAccessSession} />
    <${BatterySettings} link=${link} st=${st} />
    <${ModelSettings} tune=${tune} link=${link} />
    <div class="board" style="padding:16px 20px">
      <div style="font-size:15px;font-weight:600;margin-bottom:10px">舞台背景</div>
      ${STAGES.map(([k, label]) => html`<label style="display:flex;align-items:center;gap:10px;height:40px">
        <input type="radio" name="stage" checked=${v === k} onChange=${() => pick(k)} /> ${label}</label>`)}
      <div style="font-size:13px;color:var(--text-2)">只影响这台电脑或手机上的显示。</div>
    </div>
    <button onClick=${async () => { await api('/api/logout', {}); location.reload(); }}
      style="align-self:flex-start;height:40px;padding:0 18px;border:0;border-radius:999px;background:#E5E5EA">退出登录</button>
  </div>`;
}

function Later({ what }) {
  return html`<div class="board" style="padding:24px"><h1 style="margin:0 0 8px;font-size:28px;font-weight:600">${what}</h1>
    <p style="margin:0;color:var(--text-2)">这一页在后面的切片里做。</p></div>`;
}

// ---------------- Shell ----------------

// #/ and #/pad are the same page (overview): "Gamepad" is an anchor on the overview (review O13). Highlight: "Gamepad" when the gamepad block is on screen, otherwise "Overview".
// When the address doesn't change (clicking the same one again) there's no hashchange, so onSame scrolls itself
const OVERVIEW = (r) => r === '/' || r === '/pad';
function navCur(route, padInView) {
  return (r) => {
    if (r === '/settings') return route === '/settings' || route === '/settings/ssh' ? 'page' : undefined;
    if (r === '/pad') return OVERVIEW(route) && padInView ? 'page' : undefined;
    if (r === '/') return OVERVIEW(route) && !padInView ? 'page' : undefined;
    return route === r ? 'page' : undefined;
  };
}

function Nav({ route, padInView, onSame }) {
  const cur = navCur(route, padInView);
  const a = (href, r, text) => html`<a href=${href} aria-current=${cur(r)} onClick=${(e) => onSame(e, href)}>${text}</a>`;
  return html`<nav class="nav" aria-label="页面">
    <div class="nav-logo"><svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="7" fill="#1D1D1F"></rect><path d="M6 14.5a7 6 0 0 1 14 0z" fill="#FFFFFF"></path><rect x="6" y="14.5" width="14" height="2.6" rx="1.3" fill="#F5B400"></rect><circle cx="16.2" cy="11.4" r="1.3" fill="#1D1D1F"></circle></svg>Studio</div>
    ${a('#/', '/', '总览')}
    ${a('#/pad', '/pad', '手柄')}
    ${a('#/camera', '/camera', '摄像头')}
    ${a('#/tof', '/tof', 'ToF')}
    ${a('#/servos', '/servos', '舵机')}
    ${a('#/imu', '/imu', 'IMU')}
    ${a('#/models', '/models', '模型')}
    ${a('#/logs', '/logs', '日志')}
    <span class="spacer"></span>
    ${a('#/settings', '/settings', '设置')}
  </nav>`;
}

// Model management can also be opened directly from the phone bottom bar; order matches the sidebar.
function TabBar({ route, padInView, onSame }) {
  const cur = navCur(route, padInView);
  const a = (href, r, text) => html`<a href=${href} aria-current=${cur(r)} onClick=${(e) => onSame(e, href)}>${text}</a>`;
  return html`<nav class="tabbar" aria-label="主导航">
    ${a('#/', '/', '总览')}${a('#/pad', '/pad', '手柄')}${a('#/camera', '/camera', '摄像头')}${a('#/tof', '/tof', 'ToF')}${a('#/servos', '/servos', '舵机')}${a('#/imu', '/imu', 'IMU')}${a('#/models', '/models', '模型')}${a('#/settings', '/settings', '更多')}
  </nav>`;
}

// Ask before leaving certain pages (servo page: when servos are holding, leaving hands back to the main program and all servos go limp)
export const leaveGuards = {};
function useRoute() {
  const get = () => (location.hash.replace(/^#/, '') || '/');
  const [r, setR] = useState(get());
  const cur = useRef(r);
  useEffect(() => {
    const f = () => {
      const next = get();
      const guard = leaveGuards[cur.current];
      if (next !== cur.current && guard && !guard()) { history.replaceState(null, '', '#' + cur.current); return; }
      cur.current = next;
      // first compute "in the gamepad area or not" synchronously (review O1): at the moment of switching to another page, release everything and send drive off, without waiting for a redraw or IntersectionObserver
      padActivity.setRoute(next);
      setR(next);
      link.heartbeat();                   // tell Studio about the page change right away (hand-back / takeover doesn't wait for the next heartbeat)
    };
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  return r;
}

// Where to scroll on page change / nav click: #/pad scrolls to the gamepad block (scroll-margin-top subtracts the sticky top bar), everything else goes back to the top
function scrollFor(route) {
  if (route === '/settings/ssh') {
    requestAnimationFrame(() => {
      const guide = document.getElementById('ssh-guide');
      guide?.scrollIntoView({ block: 'start' });
      guide?.focus({ preventScroll: true });
    });
    return;
  }
  if (route === '/pad') {
    const el = document.getElementById('pad-block');
    if (el) { el.scrollIntoView({ block: 'start' }); return; }
  }
  window.scrollTo(0, 0);
}

const PAD_HEAVY = ['skills', 'actions', 'combos', 'sounds'];

function Main({ duck }) {
  const route = useRoute();
  const [st, setSt] = useState(null);
  const [sv, setSv] = useState(null);
  const [imu, setImu] = useState(null);
  const [tune, setTune] = useState(null);
  const [pd, setPd] = useState(null);
  const [stAt, setStAt] = useState(0);
  const [imuAt, setImuAt] = useState(0);
  const imuContext = useRef(null);
  const [status, setStatus] = useState(link.status);
  const [padInView, setPadInView] = useState(padActivity.inView);
  const [navTick, setNavTick] = useState(0);
  const firstScroll = useRef(route === '/pad');       // opening #/pad: scroll once more after the first state and pad both arrive (the heights above still change)
  const now = useNow(250);
  const barRef = useStickyHeight('--bar-h');

  useEffect(() => {
    const off = link.on((m) => {
      if (m.t === '_status') {
        setStatus(m.status);
        if (m.status !== 'open') { setImu(null); setImuAt(0); }
      }
      else if (m.t === 'state') {
        const context = JSON.stringify([m.mode, m.build, m.imu?.source, m.imu?.configured_imu_profile,
          m.posture === 'starting', m.imu?.context_current, m.imu?.generation]);
        if (imuContext.current !== null && imuContext.current !== context) { setImu(null); setImuAt(0); }
        imuContext.current = context;
        // when the onboarding checklist hasn't changed the backend doesn't send it every frame (onboarding_same, code review C5): reuse the previous one
        setSt((prev) => (m.onboarding_same && prev ? { ...m, onboarding: prev.onboarding } : m));
        setStAt(performance.now());
      }
      else if (m.t === 'servo') setSv(m);
      else if (m.t === 'imu') { setImu(m); setImuAt(performance.now()); }
      else if (m.t === 'tune') setTune(m);
      else if (m.t === 'pad') {
        // when the long lists (actions, combo actions, skills, sounds) haven't changed the backend no longer pushes them every frame (review O12): if missing, reuse the previous one
        setPd((prev) => {
          if (!m.lists_same || !prev?.motion) return m;
          const keep = Object.fromEntries(PAD_HEAVY.filter((k) => k in prev.motion).map((k) => [k, prev.motion[k]]));
          return { ...m, motion: { ...m.motion, ...keep } };
        });
      }
    });
    const offAct = padActivity.subscribe(({ inView }) => setPadInView(inView));
    // the user moved it themselves (wheel, finger, keyboard): don't scroll for them even when the first data arrives
    const stop = () => { firstScroll.current = false; };
    window.addEventListener('wheel', stop, { passive: true, once: true });
    window.addEventListener('touchstart', stop, { passive: true, once: true });
    window.addEventListener('keydown', stop, { once: true });
    link.connect();
    return () => { off(); offAct(); };
  }, []);

  // page change, or clicked the item already being viewed (navTick): scroll to where it should go
  useEffect(() => { scrollFor(route); }, [route, navTick]);
  useEffect(() => {
    if (firstScroll.current && st && pd && route === '/pad') {
      firstScroll.current = false;
      requestAnimationFrame(() => scrollFor('/pad'));
    }
  }, [!!st, !!pd]);
  // clicking the same address again: the browser doesn't fire hashchange, so scroll ourselves (review O13)
  const onSame = (e, href) => {
    if ((location.hash || '#/') === href) { e.preventDefault(); setNavTick((n) => n + 1); }
  };

  if (status === 'auth') { location.reload(); return null; }
  // freshness = how long since the browser received state, plus how long since Studio itself got data from robotd
  const age = st ? (now - stAt) + (st.robotd_age_ms || 0) : Infinity;
  const live = status === 'open' && age < STALE_ALARM_MS && st?.robotd_ok !== false;
  // the overview stays mounted, just hidden: the 3D duck isn't destroyed and rebuilt on page switches (three.js leaves internal objects behind on every build,
  // and browsers limit how many WebGL contexts can be open at once). The gamepad block is also in the overview (#/pad is its anchor) and stays mounted:
  // "in the gamepad area or not" is determined by padActivity, not by whether it's mounted (review O1)
  const overview = html`<div hidden=${!OVERVIEW(route)}><${Overview} st=${st} live=${live} age=${age} diagnosticElapsed=${now - stAt} duck=${duck} pd=${pd} onSame=${onSame} tune=${tune} sensorsActive=${OVERVIEW(route)} /></div>`;
  let page = null;
  if (OVERVIEW(route)) page = null;
  else if (route === '/logs') page = html`<${LogsPage} />`;
  else if (route === '/camera') page = html`<${CameraPage} api=${api} />`;
  else if (route === '/tof') page = html`<${TofPage} api=${api} />`;
  else if (route === '/servos') page = html`<${ServoPage} sv=${sv} link=${link} leaveGuards=${leaveGuards} />`;
  else if (route === '/settings' || route === '/settings/ssh') page = html`<${Settings} st=${st} tune=${tune} />`;
  else if (route === '/models') page = html`<${ModelsPage} api=${api} csrf=${csrf} link=${link} live=${live} />`;
  else if (route === '/imu') page = html`<${ImuPage} st=${st}
    imu=${imu && st?.imu?.diagnostic ? { ...imu, diagnostic: st.imu.diagnostic } : imu}
    link=${link} live=${live} age=${age} diagnosticElapsed=${now - (st?.imu?.diagnostic ? stAt : imuAt)} pd=${pd} />`;
  else page = html`<${Later} what="这一页" />`;

  document.title = `${duck?.label || '鸭子'} · Microduck Studio`;
  return html`<div class="shell">
    <${Nav} route=${route} padInView=${padInView} onSame=${onSame} />
    <main class="main">
      <${TopBar} duck=${duck} st=${st} live=${live} age=${age} open=${status === 'open'}
        hideEStop=${route === '/servos' && sv?.state === 'open'} />
      <div class="sticky-bar" ref=${barRef}><${ServoBar} st=${st} onServos=${route === '/servos'} /></div>
      ${overview}${page}
    </main>
    <${TabBar} route=${route} padInView=${padInView} onSame=${onSame} />
  </div>`;
}

function Login({ onDone, duck, noPassword }) {
  const [pw, setPw] = useState('');
  const [remember, setRemember] = useState(true);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    let r;
    try { r = await api('/api/login', { password: pw, remember }); } catch { r = { error: '连不上鸭子，检查网络后再试' }; }
    setBusy(false);
    if (r.ok) onDone(); else setErr(r.error || '登录没成功');
  };
  return html`<form class="login board" onSubmit=${submit} autocomplete="on">
    <h1>${duck?.label || 'Microduck Studio'}</h1>
    <input type="text" name="username" autocomplete="username" value="admin" hidden readOnly />
    <label>管理员密码
      <input type="password" name="password" autocomplete="current-password" value=${pw} onInput=${(e) => setPw(e.target.value)} required autoFocus />
    </label>
    <label class="row"><input type="checkbox" checked=${remember} onChange=${(e) => setRemember(e.target.checked)} /> 记住我（30 天）</label>
    ${noPassword ? html`<div class="err">还没设管理员密码。在鸭子上运行：<code>python3 -I run.py set-password</code></div>` : null}
    ${err ? html`<div class="err" role="alert">${err}</div>` : null}
    <button type="submit" disabled=${busy || !pw}>登录</button>
  </form>`;
}

function App() {
  const [sess, setSess] = useState(undefined);
  const [noPw, setNoPw] = useState(false);
  const [down, setDown] = useState(false);
  const load = () => api('/api/session')
    .then((r) => { setDown(false); csrf = r.csrf || ''; setNoPw(r.has_password === false); setSess(r.status === 200 ? r : null); })
    .catch(() => { setDown(true); setTimeout(load, 2000); });   // Studio is restarting: ask again in 2 s
  useEffect(() => { applyStage(loadStage()); load(); }, []);
  if (sess === undefined) {
    return down ? html`<div class="login board"><h1>Microduck Studio</h1><p>连不上鸭子上的 Studio，正在重试…</p></div>` : null;
  }
  if (!sess) return html`<${Login} onDone=${load} duck=${null} noPassword=${noPw} />`;
  return html`<${Main} duck=${sess.duck} />`;
}

render(html`<${App} />`, document.getElementById('app'));
