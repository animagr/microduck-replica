// Live console shell: preserve the installed transport, authentication and command safety.
import {html,render,useState,useEffect,useRef,useCallback} from './vendor/preact-htm.module.js';
import {HandBackButton} from './servo.js';
import {padActivity} from './pad.js';
import {ConsoleLayout} from './console-layout.js';
import {ConsoleOverview} from './console-overview.js';
import {ConsoleDevices} from './console-devices.js';
import {ConsoleRemote,ConsoleSensing} from './console-experience.js';
import {ConsoleModels,ConsoleSettings} from './console-system.js';
import {ConsoleLogs} from './console-logs.js';
import {useStartupFlow} from './console-startup.js';
import {applyStage,loadStage} from './console-preferences.js';
import {normalizeRoute,serverRoute,routeInfo} from './console-routes.js';

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
      if (this.ws !== ws) return;            // an old connection that has already been replaced: ignore what it pushes
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      this.lastAt = performance.now();
      // In a background tab setInterval only runs once a minute, but receiving messages is not throttled: answer each server heartbeat right away so we are not taken for disconnected
      if (m.t === 'hb') this.heartbeat();
      if (m.t === 'result' && this.pending.has(m.id)) {
        this.pending.get(m.id)(m);
        this.pending.delete(m.id);
      }
      this.emit(m);
    };
    ws.onclose = async (ev) => {
      if (this.ws !== ws) return;            // old connection (replaced by reconnect): do not touch the new connection's heartbeat
      clearInterval(this._hb);
      for (const done of this.pending.values()) done({ ok: false, error: '和 Studio 的连接断了' });
      this.pending.clear();
      if (ev.code === 4401) { this.setStatus('auth'); return; }   // login expired
      if (!opened) {
        // The handshake never succeeded: the login may have expired (older Studio versions reject during the handshake, and the browser only sees 1006)
        try { if ((await api('/api/session', undefined, 2000)).status === 401) { this.setStatus('auth'); return; } } catch { /* Studio not running */ }
        if (this.ws !== ws) return;          // the user clicked "reconnect" while we were waiting: leave it to the new connection
      }
      this.setStatus('closed');
      this._retry = setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 8000);
    };
  }

  /** Wait until the connection to Studio is up (on refresh the page appears first and the connection comes later: do not send commands before it is connected) */
  whenOpen() {
    if (this.status === 'open') return Promise.resolve();
    return new Promise((resolve) => { const off = this.on((m) => { if (m.t === '_status' && m.status === 'open') { off(); resolve(); } }); });
  }

  reconnect() { this.backoff = 1000; try { this.ws && this.ws.close(); } catch { /* already closed */ } this.connect(); }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  // pad_visible: whether the gamepad section is on screen right now (overview re-layout review O1). The backend uses only this to decide 10 Hz or 1 Hz gamepad snapshots;
  // #/pad is now an anchor on the overview, so the address does not mean it is visible (scroll back up to the stage and the address bar still says #/pad)
  heartbeat() {
    this.send({ t: 'hb', seq: ++this.seq, visible: document.visibilityState === 'visible', route: serverRoute(location.hash),
      pad_visible: padActivity.active || this.padCapture });
  }

  // Read-only side channel for model key remapping: request snapshots without changing padActivity and without taking over web remote control.
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
padActivity.bind(link);                  // send a heartbeat the moment the gamepad section is entered or left

let csrf = '';   // from /api/session; state-changing POSTs must carry it (X-CSRF), alongside the backend's Origin check
async function api(path, body, timeoutMs = 10000, signal) {
  const opt = body === undefined ? { credentials: 'same-origin' }
    : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf }, body: JSON.stringify(body) };
  const ctl = new AbortController();
  const abort = () => ctl.abort();
  if (signal?.aborted) ctl.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => ctl.abort(), timeoutMs);   // when phone Wi-Fi is flaky a request can hang for tens of seconds
  let r;
  let data = {};
  try {
    r = await fetch(path, { ...opt, signal: ctl.signal });
    try { data = await r.json(); } catch (error) { if (ctl.signal.aborted) throw error; }
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  return { status: r.status, ...data };
}


function useNow(ms = 250) {
  const [now, setNow] = useState(performance.now());
  useEffect(() => { const t = setInterval(() => setNow(performance.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}


const TEXT_TYPES = ['text', 'password', 'search', 'email', 'number', 'tel', 'url'];
const typing = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA'
  || (el.tagName === 'INPUT' && TEXT_TYPES.includes((el.type || 'text').toLowerCase())));
// Ctrl / Alt / Win + Space are system shortcuts such as switching input methods; do not treat them as relax (torque off)
const plainSpace = (e) => e.code === 'Space' && !e.ctrlKey && !e.altKey && !e.metaKey;

function EStop({ st, live, open }) {
  const [sentAt, setSentAt] = useState(0);
  const [err, setErr] = useState(null);
  const fire = useCallback(async () => {
    if (performance.now() - sentAt < 200) return;           // holding Space auto-repeats: at most 5 times per second
    setSentAt(performance.now()); setErr(null);
    const r = await link.cmd('relax', {}, 7000);       // backend worst case 3 + 0.1 + 3 seconds
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
  // Relax is confirmed, so the earlier "not sent / timed out" message is stale
  useEffect(() => { if (es.state === 'confirmed') setErr(null); }, [es.state]);
  const click = (e) => { e.currentTarget.blur(); fire(); };
  const note = (text) => (text ? html`<span class="why" role=${err ? 'alert' : undefined}>${text}</span>` : null);
  const fallback = st?.mode === 'commissioning' ? '只能关电源' : '用手柄 − 或关电源';
  if (!open) {
    // The connection to Studio is down: pressing it would not get sent anyway
    return html`<span class="estop-wrap">${note(fallback)}
      <button class="estop unavailable" disabled>卸力 · 不可用</button></span>`;
  }
  if (st?.servo_orphan) {
    // The servo session was open when Studio last exited and was not taken over this time (review D1): robotd is not running and the bus is not taken over, so pressing here cannot send anything; send the user to the servo page to take over
    // (the servo page takes over the bus as soon as it opens, and after that relax goes over the bus). Space still sends, and the backend replies "take over on the servo page first"
    return html`<span class="estop-wrap">${note(err || '可能还有舵机保持着')}
      <button class="estop unavailable" onClick=${(e) => { e.currentTarget.blur(); location.hash = '#/devices/servos'; }}
        title="上次 Studio 退出时舵机会话开着、这次没接管上：先去舵机页接管总线，才能在总线上卸力">卸力 · 先去舵机页接管</button></span>`;
  }
  if (es.state === 'unavailable') {
    return html`<span class="estop-wrap">${note(err || es.why || fallback)}
      <button class="estop unavailable" onClick=${click}>卸力 · 不一定有效</button></span>`;
  }
  if (live && es.state === 'confirmed') {
    return html`<span class="estop-wrap">${note(err)}
      <button class="estop done" onClick=${click} title=${es.why}>全局卸力 · 已卸力</button></span>`;
  }
  // Stale data (!live) still gets the red button: pressing it still sends, since Studio's dedicated relax path may be fine
  return html`<span class="estop-wrap">${note(err || (!live ? '状态不明，仍可按' : ''))}
    <button class="estop" onClick=${click} title="让 15 颗舵机全部卸力。鸭子会软下来，扶住。">
      ${es.state === 'pending' ? '卸力中…' : '全局卸力'}<span class="kbd">空格</span></button></span>`;
}


function ServoBar({ st, onServos }) {
  const ss = st?.servo_session;
  if (ss) {
    if (onServos) return null;
    const unk = ss.unknown ? ` · ${ss.unknown} 颗读不到扭矩（可能也在保持）` : '';
    return html`<div class="banner warn servo-bar" role="status">
      <b>调舵机中 · ${ss.holding ?? '?'} 颗保持着${unk} · 主程序停着（手柄、遥控、站走都不能用）</b>
      <span class="sb-acts"><a href="#/devices/servos">回舵机页</a><${HandBackButton} link=${link} /></span>
      <span class="more sb-more">${ss.restored ? 'Studio 重启过，接着上次的会话管着。' : ''}急停用顶上红按钮或空格（手柄 Select 这时不管用）；别手动起 robotd，先点「交还主程序」</span>
      ${st.servo_marker_error ? html`<span class="more sb-more">${st.servo_marker_error}</span>` : null}</div>`;
  }
  // The main program was started manually during the session (review D9): as soon as it starts it releases all servos and fights Studio for the serial port; Studio has already closed the bus (without writing to the servos)
  if (st?.servo_conflict_s != null) {
    return html`<div class="banner bad servo-bar" role="alert"><b>主程序被手动起来了：它会把舵机全部松开、跟 Studio 抢串口</b>
      <span class="more sb-more">Studio 已经关掉舵机总线（没写舵机）。下次别手动起 robotd：先在页面上点「交还主程序」</span></div>`;
  }
  // The servo session was open when Studio last exited and was not taken over this time (review D1)
  if (st?.servo_orphan) {
    return html`<div class="banner bad servo-bar" role="alert"><b>上次退出时可能还有舵机保持着，去舵机页接管后才能卸力</b>
      ${onServos ? null : html`<a href="#/devices/servos">去舵机页接管</a>`}
      <span class="more sb-more">Studio 重启时没接管上${st.servo_orphan.why ? `（${st.servo_orphan.why}）` : ''}；急的话关电源</span></div>`;
  }
  // Handed back, and the main program has not connected yet: keep showing the hint until it connects (the backend clears it once connected; it no longer disappears by itself after 10 minutes: review D12)
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


export const leaveGuards = {};
function useRoute() {
  const get = () => normalizeRoute(location.hash);
  const [r, setR] = useState(get());
  const cur = useRef(r);
  useEffect(() => {
    const f = () => {
      const next = get();
      const guard = leaveGuards[cur.current];
      if (next !== cur.current && guard && !guard()) { history.replaceState(null, '', '#' + cur.current); return; }
      cur.current = next;
      // First compute "in the gamepad section or not" synchronously (review O1): the moment we switch to another page, release everything and send drive off, without waiting for a redraw or the IntersectionObserver
      padActivity.setRoute(next);
      setR(next);
      link.heartbeat();                   // tell Studio right away that the page changed (hand back / take over need not wait for the next heartbeat)
    };
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  return r;
}

// Where to scroll when changing pages or clicking navigation: #/pad scrolls to the gamepad section (scroll-margin-top subtracts the sticky top bar), everything else goes back to the top

const PAD_HEAVY = ['skills','actions','combos','sounds'];
function Main({duck}) {
  const route=useRoute(), info=routeInfo(route);
  const [st,setSt]=useState(null),[sv,setSv]=useState(null),[imu,setImu]=useState(null),[tune,setTune]=useState(null),[pd,setPd]=useState(null);
  const [stAt,setStAt]=useState(0),[imuAt,setImuAt]=useState(0),[status,setStatus]=useState(link.status);
  const imuContext=useRef(null), now=useNow(250);
  useEffect(()=>{
    const off=link.on(m=>{
      if(m.t==='_status'){setStatus(m.status);if(m.status!=='open'){setImu(null);setImuAt(0);}}
      else if(m.t==='state'){
        const context=JSON.stringify([m.mode,m.build,m.imu?.source,m.imu?.configured_imu_profile,m.posture==='starting',m.imu?.context_current,m.imu?.generation]);
        if(imuContext.current!==null&&imuContext.current!==context){setImu(null);setImuAt(0);}
        imuContext.current=context;
        setSt(prev=>m.onboarding_same&&prev?{...m,onboarding:prev.onboarding}:m);setStAt(performance.now());
      } else if(m.t==='servo')setSv(m);
      else if(m.t==='imu'){setImu(m);setImuAt(performance.now());}
      else if(m.t==='tune')setTune(m);
      else if(m.t==='pad')setPd(prev=>{
        if(!m.lists_same||!prev?.motion)return m;
        const keep=Object.fromEntries(PAD_HEAVY.filter(key=>key in prev.motion).map(key=>[key,prev.motion[key]]));
        return {...m,motion:{...m.motion,...keep}};
      });
    });
    link.connect();return off;
  },[]);
  useEffect(()=>{window.scrollTo(0,0);},[route]);
  const age=st?(now-stAt)+(st.robotd_age_ms||0):Infinity;
  const live=status==='open'&&age<3000&&st?.robotd_ok!==false;
  const startup=useStartupFlow({st,sv,imu,tune,pad:pd,live,open:status==='open',link});
  if(status==='auth'){location.reload();return null;}
  let page=null;
  if(info.page==='devices')page=html`<${ConsoleDevices} section=${info.section} sv=${sv} st=${st} imu=${imu&&st?.imu?.diagnostic?{...imu,diagnostic:st.imu.diagnostic}:imu} link=${link} live=${live} age=${age} diagnosticElapsed=${now-(st?.imu?.diagnostic?stAt:imuAt)} pd=${pd} leaveGuards=${leaveGuards}/>`;
  else if(info.page==='remote')page=html`<${ConsoleRemote} section=${info.section} st=${st} pad=${pd} link=${link} api=${api} live=${live}/>`;
  else if(info.page==='sensing')page=html`<${ConsoleSensing} section=${info.section} st=${st} pad=${pd} link=${link} api=${api} live=${live} open=${status==='open'}/>`;
  else if(info.page==='models')page=html`<${ConsoleModels} section=${info.section} api=${api} csrf=${csrf} link=${link} live=${live} tune=${tune}/>`;
  else if(info.page==='settings')page=html`<${ConsoleSettings} section=${info.section} api=${api} csrf=${csrf} link=${link} st=${st} tune=${tune}/>`;
  else if(info.page==='logs')page=html`<${ConsoleLogs} api=${api} link=${link}/>`;
  document.title=`${info.title} · ${duck?.label||'智能鸭'}`;
  return html`<${ConsoleLayout} route=${route} duck=${duck} st=${st} live=${live} open=${status==='open'} emergency=${html`<${EStop} st=${st} live=${live} open=${status==='open'}/>`}>
    <${ServoBar} st=${st} onServos=${route==='/devices/servos'||route==='/overview'}/>
    <div hidden=${info.page!=='overview'}><${ConsoleOverview} st=${st} pad=${pd} tune=${tune} live=${live} guide=${startup.card}/></div>
    ${startup.context(route)}${page}${startup.dialogs}
  <//>`;
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
    .catch(() => { setDown(true); setTimeout(load, 2000); });   // Studio is restarting: ask again in 2 seconds
  useEffect(() => { applyStage(loadStage()); load(); }, []);
  if (sess === undefined) {
    return down ? html`<div class="login board"><h1>Microduck Studio</h1><p>连不上鸭子上的 Studio，正在重试…</p></div>` : null;
  }
  if (!sess) return html`<${Login} onDone=${load} duck=${null} noPassword=${noPw} />`;
  return html`<${Main} duck=${sess.duck} />`;
}

render(html`<${App} />`, document.getElementById('app'));
