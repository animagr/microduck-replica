// Connection layer between the phone web console and Studio.
//
// Why a separate copy instead of importing ../app.js: app.js is the desktop entry point and mounts the whole desktop UI when the module loads
// (with a pile of side effects: 3D, gamepad, sensors). The phone pages only need the same protocol without those side effects, so this
// rewrites the WebSocket client and fetch wrapper against the same contract, matching the desktop behavior point by point:
// - connection: ws(s)://<current host>/ws; a rejected handshake is 4401 (login expired);
// - heartbeat: once per second, with route and pad_visible (the backend uses them to decide between 10 Hz and 1 Hz pushes and whether to send gamepad snapshots);
// - commands: {t:'cmd', id, name, args} → ack {t:'result', id, ok, reason, data};
// - mutating POSTs must carry X-CSRF (value from /api/session), together with the backend's same-origin Origin check.

export const link = {
  ws: null,
  seq: 0,
  padSeq: 0,
  pending: new Map(),
  listeners: new Set(),
  status: 'idle',        // idle / connecting / open / closed / auth
  backoff: 1000,
  route: '/',
  padVisible: false,
  padCapture: false,      // read-only tap for model key remapping: only wants gamepad snapshots, doesn't take over remote control
  _hb: null,

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  emit(m) { for (const fn of this.listeners) fn(m); },
  setStatus(s) { this.status = s; this.emit({ t: '_status', status: s }); },

  connect() {
    clearTimeout(this._retry);
    clearInterval(this._hb);
    try { this.ws && this.ws.close(); } catch { /* already closed */ }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = this.ws = new WebSocket(`${proto}://${location.host}/ws`);
    let opened = false;
    this.setStatus('connecting');
    ws.onopen = () => {
      opened = true;
      this.backoff = 1000;
      this.setStatus('open');
      this.heartbeat();
      this._hb = setInterval(() => this.heartbeat(), 1000);
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.t === 'hb') this.heartbeat();          // timers are throttled in background tabs; reply to each server heartbeat received
      if (m.t === 'result' && this.pending.has(m.id)) {
        this.pending.get(m.id)(m);
        this.pending.delete(m.id);
      }
      this.emit(m);
    };
    ws.onclose = async (ev) => {
      if (this.ws !== ws) return;
      clearInterval(this._hb);
      for (const done of this.pending.values()) done({ ok: false, error: '和鸭子的连接断了' });
      this.pending.clear();
      if (ev.code === 4401) { this.setStatus('auth'); return; }
      if (!opened) {
        try {
          const r = await api('/api/session', undefined, 2000);
          if (r.status === 401) { this.setStatus('auth'); return; }
        } catch { /* Studio not running */ }
        if (this.ws !== ws) return;
      }
      this.setStatus('closed');
      this._retry = setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 8000);
    };
  },

  reconnect() { this.backoff = 1000; this.connect(); },

  whenOpen() {
    if (this.status === 'open') return Promise.resolve();
    return new Promise((resolve) => {
      const off = this.on((m) => { if (m.t === '_status' && m.status === 'open') { off(); resolve(); } });
      setTimeout(() => { off(); resolve(); }, 6000);      // not connected after 6 s: don't keep the caller waiting forever
    });
  },

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  },

  setRoute(route) { this.route = route; this.heartbeat(); },
  setPadVisible(v) { this.padVisible = Boolean(v); this.heartbeat(); },
  // The model key-remapping page borrows the 10 Hz gamepad snapshot to capture key presses, but doesn't change padVisible or take over remote control.
  setPadCapture(v) { this.padCapture = Boolean(v); this.heartbeat(); },
  nextPadSeq() { return ++this.padSeq; },

  heartbeat() {
    this.send({
      t: 'hb', seq: ++this.seq,
      visible: document.visibilityState === 'visible',
      route: this.route,
      pad_visible: this.padVisible || this.padCapture,
    });
  },

  cmd(name, args = {}, timeoutMs = 15000) {
    const id = `m${++this.seq}`;
    return new Promise((resolve) => {
      if (!this.send({ t: 'cmd', id, name, args })) { resolve({ ok: false, error: '和鸭子的连接断了' }); return; }
      this.pending.set(id, resolve);
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); resolve({ ok: false, error: '鸭子没回话（超时）' }); }
      }, timeoutMs);
    });
  },
};

let csrf = '';

export async function api(path, body, timeoutMs = 10000) {
  const opt = body === undefined
    ? { credentials: 'same-origin' }
    : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf }, body: JSON.stringify(body) };
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let r, data = {};
  try {
    r = await fetch(path, { ...opt, signal: ctl.signal });
    try { data = await r.json(); } catch { /* not JSON (e.g. 204) */ }
  } finally { clearTimeout(timer); }
  return { status: r.status, ...data };
}

export function setCsrf(value) { csrf = value || ''; }

/** Model import uploads directly via XHR and can't use the wrapped api: hand the current token to the caller to build its own headers */
export function csrfToken() { return csrf; }

/** Session: ducks without a password get an open session directly; with one set, login is required */
export async function session() {
  const r = await api('/api/session', undefined, 4000);
  if (r.status === 200) setCsrf(r.csrf);
  return r;
}

export async function login(password, remember = true) {
  const r = await api('/api/login', { password, remember }, 8000);
  if (r.status === 200 || r.ok) { const s = await session(); return s.status === 200 ? { ok: true } : { ok: false, error: '登录没生效' }; }
  return { ok: false, error: r.error || '密码不对' };
}
