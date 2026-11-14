// Shell of the phone web console: session → connection → top bar (duck name + torque release) → page → bottom bar.
//
// Relation to the desktop version: same Studio process, same /ws, same set of pad.op commands, just a different shell made for portrait phones.
// This layer is responsible for only three things: dispatching state to the pages, guarding the always-pressable "torque release" (「卸力」) path, and bottom-bar routing.
import { html, render, useState, useEffect, useRef, useCallback } from '../vendor/preact-htm.module.js';
import { link, session, login, api, csrfToken } from './link.js';
import { Overview } from './overview.js';
import { VoicePage } from './voice.js';
import { GamepadPage } from './gamepad.js';
import { CameraPage } from './camera.js';
import { MorePage } from './more.js';
// The models page isn't written again: it embeds the desktop ModelsPage directly and only swaps the shell for the phone bottom bar.
import { ModelsPage } from '../models.js';

const STALE_MS = 1500;      // no state frame for more than 1.5 s: counts as "unreadable"
const GREY_MS = 1000;       // more than 1 s: values turn gray

const ICONS = {
  '/': html`<svg viewBox="0 0 24 24"><path d="M3 10.5 12 4l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/></svg>`,
  '/voice': html`<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="10" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/></svg>`,
  '/pad': html`<svg viewBox="0 0 24 24"><path d="M7 8h10a5 5 0 0 1 4.9 6l-.6 2.4A2.6 2.6 0 0 1 16 17.6L14.5 16h-5L8 17.6a2.6 2.6 0 0 1-5.3-1.2L2.1 14A5 5 0 0 1 7 8Z"/><path d="M7.5 12.5v2M6.5 13.5h2M16 12.5h.01M17.5 14h.01"/></svg>`,
  '/models': html`<svg viewBox="0 0 24 24"><path d="M12 3 3 7.5v9L12 21l9-4.5v-9z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>`,
  '/more': html`<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>`,
};

// camera now lives under "More" (#/more/camera); "Models" is also a full page inside the phone shell, embedding the desktop component.
// All five tabs are internal routes; the bottom bar always stays in place.
const TABS = [
  { href: '/', label: '总览' },
  { href: '/voice', label: '语音' },
  { href: '/pad', label: '手柄' },
  { href: '/models', label: '模型' },
  { href: '/more', label: '更多' },
];

const KNOWN = new Set([...TABS.map((t) => t.href), '/pad', '/more/camera']);
const routeOf = () => {
  const r = '/' + location.hash.replace(/^#\/?/, '');
  return KNOWN.has(r) ? r : '/';
};

// ---------------- Nickname ----------------
// By default use the label the duck reports (the hostname on the system image, e.g. duck-a1b2; DESKTOP-XXXX on a computer bench).
// A hostname doesn't look nice as a nickname, so anything that looks like a hostname is shown as "鸭鸭" (Ducky); names the user picks are stored on this phone.
const NICK_KEY = 'duck.nickname';
const hostish = (s) => /^duck-[0-9a-z]{4,}$/i.test(s) || /^[A-Z0-9][A-Z0-9-]{2,}$/.test(s);

function nickStored() {
  try { return localStorage.getItem(NICK_KEY) || ''; } catch { return ''; }
}

// ---------------- Top bar ----------------

function Head({ name, dot, onEstop, busy }) {
  return html`<header class="m-head">
    <div class="m-head-in">
      <div class="m-duck">
        <span class=${'m-dot ' + dot} aria-hidden="true"></span>
        <span class="m-duck-name">${name}</span>
      </div>
      <span class="m-head-gap"></span>
      <button class="m-estop" onClick=${onEstop} disabled=${busy}
        aria-label="卸力：让所有舵机松掉力气">卸力</button>
    </div>
  </header>`;
}

// ---------------- Login (only appears for ducks with a web password set) ----------------

function Login({ onDone }) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setErr(null);
    const r = await login(pw, true);
    setBusy(false);
    if (r.ok) onDone(); else setErr(r.error);
  };
  return html`<form class="m-login" onSubmit=${submit}>
    <h1>登录这只鸭子</h1>
    <p>它设了网页密码。输一次，这台手机会记 30 天。</p>
    <input type="password" inputmode="text" autocomplete="current-password" placeholder="网页密码"
      value=${pw} onInput=${(e) => setPw(e.currentTarget.value)} autoFocus />
    ${err ? html`<div class="m-banner bad" style="margin-top:12px">${err}</div>` : null}
    <button class="m-btn primary" type="submit" disabled=${busy || !pw}>${busy ? '正在登录…' : '登录'}</button>
  </form>`;
}

// ---------------- Shell ----------------

function App() {
  const [phase, setPhase] = useState('boot');       // boot / login / ready
  const [hello, setHello] = useState(null);
  const [st, setSt] = useState(null);
  const [stAt, setStAt] = useState(0);
  const [pad, setPad] = useState(null);
  const [conn, setConn] = useState('connecting');
  const [route, setRoute] = useState(routeOf());
  const [now, setNow] = useState(performance.now());
  const [toast, setToast] = useState(null);
  const [estopBusy, setEstopBusy] = useState(false);
  const toastTimer = useRef(null);

  const say = useCallback((text, bad = false) => {
    setToast({ text, bad });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), bad ? 3600 : 2200);
  }, []);

  // session: 200 goes straight in; 401 logs in first
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const r = await session();
        if (dead) return;
        setPhase(r.status === 200 ? 'ready' : r.status === 401 ? 'login' : 'ready');
      } catch { if (!dead) setPhase('ready'); }        // Studio misbehaving: go in as open mode for now; the page itself will show it can't connect
    })();
    return () => { dead = true; };
  }, []);

  // connection + message dispatch
  useEffect(() => {
    if (phase !== 'ready') return;
    const off = link.on((m) => {
      if (m.t === '_status') { setConn(m.status); if (m.status === 'auth') setPhase('login'); return; }
      if (m.t === 'hello') { setHello(m); return; }
      if (m.t === 'state') { setSt(m); setStAt(performance.now()); return; }
      if (m.t === 'pad') { setPad(m); return; }
    });
    link.connect();
    const tick = setInterval(() => setNow(performance.now()), 500);
    return () => { off(); clearInterval(tick); };
  }, [phase]);

  // routing
  useEffect(() => {
    const onHash = () => setRoute(routeOf());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // tell the backend "which page I'm on": the gamepad / voice pages need the gamepad snapshot (the voice switch goes through pad.op's audio branch,
  // and the backend requires that this connection not be marked as "left"), so these two pages turn pad_visible on
  useEffect(() => {
    link.setRoute(route);
    link.setPadVisible(route === '/pad' || route === '/voice');
  }, [route]);

  const live = conn === 'open' && st && now - stAt < STALE_MS;
  const age = stAt ? now - stAt : Infinity;
  const [nick, setNick] = useState(nickStored());
  const label = hello?.duck?.label;
  const name = nick || (label && !hostish(label) ? label : '鸭鸭');
  const rename = useCallback((v) => {
    const clean = String(v || '').trim().slice(0, 12);
    setNick(clean);
    try { clean ? localStorage.setItem(NICK_KEY, clean) : localStorage.removeItem(NICK_KEY); } catch { /* private mode */ }
  }, []);
  const posture = st?.posture;

  const doEstop = useCallback(async () => {
    if (estopBusy) return;
    setEstopBusy(true);
    const r = await link.cmd('relax', {}, 7000);
    setEstopBusy(false);
    if (r.ok) say('已卸力，舵机松开了');
    else say(r.reason || r.error || '卸力没发出去', true);
  }, [estopBusy, say]);

  if (phase === 'boot') {
    return html`<div class="m-app"><div class="m-empty">正在连${'鸭子'}…</div></div>`;
  }
  if (phase === 'login') {
    return html`<div class="m-app"><${Login} onDone=${() => { setPhase('ready'); }} /></div>`;
  }

  let dot = 'warn';
  if (conn === 'open') dot = live ? 'on' : 'warn';
  else if (conn === 'closed' || conn === 'auth') dot = 'bad';

  let page = null;
  if (route === '/') page = html`<${Overview} st=${st} pad=${pad} live=${live} age=${age} name=${name} say=${say} />`;
  else if (route === '/voice') page = html`<${VoicePage} st=${st} pad=${pad} live=${live} name=${name} say=${say} />`;
  else if (route === '/pad') page = html`<${GamepadPage} st=${st} live=${live} say=${say} />`;
  else if (route === '/models') page = html`<${ModelsPage} api=${api} csrf=${csrfToken()} link=${link} live=${live} />`;
  else if (route === '/more/camera') page = html`<${CameraPage} live=${live} say=${say} />`;
  else page = html`<${MorePage} hello=${hello} st=${st} conn=${conn} say=${say} nick=${name} rename=${rename} />`;

  const go = (href) => { location.hash = '#' + href; };

  return html`<div class="m-app">
    <${Head} name=${name} dot=${dot} onEstop=${doEstop} busy=${estopBusy} />
    <main class="m-main">
      ${conn !== 'open' ? html`<div class="m-banner bad">
        <span>${conn === 'closed' ? '和鸭子的连接断了' : '正在连鸭子…'}</span>
        <button class="act" onClick=${() => link.reconnect()}>重新连接</button>
      </div>` : null}
      ${conn === 'open' && !live ? html`<div class="m-banner">
        <span>${isFinite(age) ? Math.round(age / 1000) + ' 秒没收到状态' : '还没收到状态'}，站着走的鸭子会自己停下。</span>
      </div>` : null}
      ${page}
    </main>
    <nav class="m-tabs" aria-label="页面">
      <div class="m-tabs-in">
        ${TABS.map((t) => {
          const on = t.href === route || (t.href === '/more' && route.startsWith('/more/'));
          return html`<a class="m-tab" href=${'#' + t.href} aria-current=${on ? 'page' : null}>
            ${ICONS[t.href]}<span>${t.label}</span>
          </a>`;
        })}
      </div>
    </nav>
    ${toast ? html`<div class=${'m-toast' + (toast.bad ? ' bad' : '')} role="status">${toast.text}</div>` : null}
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));

// pressing back on a phone changes the hash without reloading the page; nothing more to handle here
window.addEventListener('unhandledrejection', (e) => { console.warn('未处理的异步错误', e.reason); });
