// The overview's "Connect WiFi" card and the WiFi section in settings (task 10b).
// When the duck has its hotspot on, the phone joins the hotspot, opens Studio, picks the home WiFi and enters the password; Studio first turns off the hotspot, then has configd run net.connect.
// The hotspot switch and net.* are all in the backend (studio/net.py); this only handles choosing a network, confirming, and keeping the "still readable after disconnect" text on screen.
// The address after switching networks is written per device (openLines); the "More" page also has a copyable "This duck's addresses" block (DuckAddresses).
// After the connect request is sent and the page loses the duck, it looks for the duck's new address by itself (task 17, user, 10-21: "connecting WiFi took three tries"): every 2 s, new Image()
// loads probe.svg on duck-xxxx / duck-xxxx.local (cross-origin image loads need no CORS), and jumps to whichever loads first; searches for at most 3 minutes.
// The probe logic (findUrls / probeImage / startFind) doesn't touch the page; tests/wifi_find.mjs runs it in Node with a fake clock.
import { html, useState, useEffect } from './vendor/preact-htm.module.js';
import { ConfirmBox } from './confirm.js';

const CSS = `
.wifi-card { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.wifi-card h2 { margin: 0; font-size: 17px; font-weight: 600; }
.wifi-settings { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.wifi-settings h2 { margin: 0; font-size: 15px; font-weight: 600; }
.wifi-lead { margin: 0; font-size: 13px; line-height: 1.6; color: var(--text-2); }
.wifi-last-try { padding: 9px 12px; border-radius: 10px; background: #FFF1F1; box-shadow: inset 0 0 0 1px rgba(215, 0, 21, .18);
  color: var(--danger); font-size: 14px; line-height: 1.55; }
.wifi-list { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.wifi-net, .wifi-manual { border-radius: 12px; background: #F7F7FA; min-width: 0; overflow: hidden; }
.wifi-net.on { background: #EEF5FF; box-shadow: inset 0 0 0 1px rgba(0, 113, 227, .22); }
.wifi-net-head, .wifi-manual-head { width: 100%; min-height: 48px; padding: 8px 12px; border: 0; background: transparent;
  display: flex; align-items: center; gap: 10px; text-align: left; font-size: 16px; color: var(--text); }
.wifi-manual-head { color: var(--text-2); font-size: 14px; }
.wifi-name { flex: 1; min-width: 0; overflow-wrap: anywhere; line-height: 1.3; }
.wifi-name b { font-weight: 600; }
.wifi-sub { display: block; margin-top: 2px; font-size: 12px; color: var(--text-2); font-weight: 400; }
.wifi-badge { flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px; background: #E3F6EA; color: #1E7B3A; }
.wifi-lock { flex: none; font-size: 13px; opacity: .75; }
.wifi-bars { flex: none; width: 22px; height: 16px; display: inline-flex; align-items: flex-end; gap: 2px; }
.wifi-bars i { flex: 1; border-radius: 1px; background: #D5D5DB; height: 4px; }
.wifi-bars i:nth-child(2) { height: 7px; }
.wifi-bars i:nth-child(3) { height: 11px; }
.wifi-bars i:nth-child(4) { height: 15px; }
.wifi-bars i.on { background: var(--blue); }
.wifi-row-body { padding: 0 12px 12px; display: flex; flex-direction: column; gap: 8px; }
.wifi-psk-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.wifi-psk, .wifi-manual-name, .wifi-manual-psk { width: 100%; min-width: 0; height: 44px; padding: 0 12px;
  border: 1px solid #D2D2D7; border-radius: 10px; background: #FFF; color: var(--text); font: inherit; font-size: 16px; }
.wifi-show { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; color: var(--text-2); }
.wifi-btn { min-height: 40px; padding: 0 16px; border: 0; border-radius: 999px; background: #E5E5EA;
  color: var(--text); font: inherit; font-size: 14px; }
.wifi-btn.primary { background: var(--blue); color: #FFF; font-weight: 600; }
.wifi-btn:disabled { opacity: .45; }
.wifi-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.wifi-note { font-size: 13px; color: var(--text-2); line-height: 1.5; }
.wifi-msg { font-size: 13px; line-height: 1.5; color: var(--danger); }
.wifi-switching { padding: 12px 14px; border-radius: 12px; background: #FFF7EC; box-shadow: inset 0 0 0 1px #F5DDBF;
  font-size: 14px; line-height: 1.6; }
.wifi-switching b { display: block; margin-bottom: 4px; font-size: 15px; }
.wifi-switching p { margin: 2px 0 0; }
.wifi-now { display: flex; flex-direction: column; gap: 4px; font-size: 14px; line-height: 1.55; }
.wifi-now .big { font-size: 16px; font-weight: 600; }
.wifi-saved-row { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 4px 0; border-top: 1px solid var(--line); }
.wifi-saved-row .wifi-name { font-size: 15px; }
.wifi-flow { margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.wifi-open { margin: 4px 0 0; padding-left: 18px; font-size: 13px; line-height: 1.6; color: var(--text-2); }
.wifi-open li { overflow-wrap: anywhere; }
.wifi-finding .wifi-find-urls { font-size: 14px; color: var(--text); }
.wifi-finding .wifi-find-urls a { font-weight: 600; }
.duck-addr-row { display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 4px 0; border-top: 1px solid var(--line); }
.duck-addr-row .wifi-name { font-size: 15px; }
.duck-addr-row .wifi-name a { overflow-wrap: anywhere; }
@media (max-width: 700px) {
  .wifi-card, .wifi-settings { padding: 14px 14px; }
  .wifi-net-head { min-height: 52px; padding: 10px 12px; }
  .wifi-btn { min-height: 44px; }
  .wifi-psk, .wifi-manual-name, .wifi-manual-psk { height: 46px; }
}
`;
if (typeof document !== 'undefined' && !document.getElementById('wifi-css')) {   // no document when the probe-logic tests run in Node
  const s = document.createElement('style');
  s.id = 'wifi-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

const SEC = { open: '开放', wep: 'WEP', wpa_psk: 'WPA2', wpa3_sae: 'WPA3', enterprise: '企业认证' };
const secLabel = (sec) => SEC[sec] || (sec ? '加密' : '');
const pskFormatOk = (v) => v === '' || (v.length >= 8 && v.length <= 63) || /^[0-9a-fA-F]{64}$/.test(v);
const pskOk = (v) => v !== '' && pskFormatOk(v);

function Bars({ signal }) {
  const n = typeof signal === 'number' ? (signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1) : 0;
  return html`<span class="wifi-bars" title=${typeof signal === 'number' ? '信号 ' + signal : '信号不知道'}
    aria-label=${typeof signal === 'number' ? '信号 ' + signal : '信号不知道'}>
    ${[1, 2, 3, 4].map((i) => html`<i class=${i <= n ? 'on' : ''}></i>`)}</span>`;
}

function minutesSince(at) {
  if (typeof at !== 'number') return null;
  return Math.max(1, Math.round((Date.now() / 1000 - at) / 60));
}

// How to open Studio after switching networks, written per device (10-20 real hardware: Windows with the Clash system proxy on couldn't open duck-xxxx.local: it went through the proxy, 502;
// the dotless duck-xxxx resolves on Windows via LLMNR and the proxy bypasses it via <local>; the IP works everywhere)
export function openLines(net) {
  const host = net.hostname || 'duck-xxxx';
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'https' : 'http';
  return [
    `Windows 电脑：${net.url_host || `${proto}://${host}:8000/`}（开着代理也能打开）`,
    `苹果手机、Mac：${net.url_local || `${proto}://${host}.local:8000/`}`,
    `安卓手机，或者上面都打不开：去路由器的设备列表找 ${host}，用它的 IP 打开`,
    '电脑开着 Clash 的 TUN 模式还打不开：在 Clash 里把局域网（192.168.0.0/16）设成直连',
  ];
}

// ---------------- Finding the duck's new address after connecting WiFi (task 17) ----------------
export const FIND_EVERY_MS = 2000;           // one probe round every 2 s
export const FIND_GIVEUP_MS = 3 * 60 * 1000; // search for at most 3 minutes
export const FIND_PROBE_MS = 6000;           // max wait for one probe (an unreachable address may hang for tens of seconds before erroring)
export const FIND_SILENT_MS = 5000;          // no message from Studio for this long also counts as disconnected (WebSocket sometimes doesn't report the close right away)

/** Addresses to look for: <proto>://<hostname>:<port>/ and <proto>://<hostname>.local:<port>/ (hostname from net.json, port same as --listen).
 *  proto matches the current page: if Studio uses https, don't probe http (nobody answers on 80/8000). */
export function findUrls(net) {
  const host = (net && net.hostname) || 'duck-xxxx';
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'https' : 'http';
  const urls = [(net && net.url_host) || `${proto}://${host}:8000/`, (net && net.url_local) || `${proto}://${host}.local:8000/`];
  return urls.filter((u, i) => urls.indexOf(u) === i);
}

/** Probe one address with a small image: true on successful load, false on error / timeout. Cross-origin image loads need no CORS; ?t= defeats caching. */
export function probeImage(url, timeoutMs = FIND_PROBE_MS) {
  return new Promise((resolve) => {
    const img = new Image();
    let done = false;
    const end = (ok) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      img.onload = null; img.onerror = null;
      resolve(ok);
    };
    const timer = setTimeout(() => end(false), timeoutMs);
    img.onload = () => end(true);
    img.onerror = () => end(false);
    img.src = `${url}probe.svg?t=${Date.now()}`;
  });
}

/** Every `every` ms, probe each of urls once (skip one whose previous probe hasn't answered yet); on the first success call onFound(that address) and stop;
 *  if nothing is found after giveUp ms, call onGiveUp() and stop. Returns {stop}: call it when the page reconnects to the original address (hotspot came back); after stopping, no more callbacks. */
export function startFind({ urls, onFound, onGiveUp, probe = probeImage, every = FIND_EVERY_MS, giveUp = FIND_GIVEUP_MS,
  now = () => Date.now(), timers = { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t) } }) {
  const t0 = now();
  const inFlight = new Set();
  let stopped = false;
  let timer = null;
  const stop = () => {
    stopped = true;
    if (timer != null) timers.clearTimeout(timer);
    timer = null;
  };
  const tick = () => {
    timer = null;
    if (stopped) return;
    if (now() - t0 >= giveUp) { stop(); if (onGiveUp) onGiveUp(); return; }
    for (const url of urls) {
      if (inFlight.has(url)) continue;
      inFlight.add(url);
      Promise.resolve().then(() => probe(url)).then((ok) => {
        inFlight.delete(url);
        if (ok === true && !stopped) { stop(); if (onFound) onFound(url); }
      }, () => { inFlight.delete(url); });
    }
    timer = timers.setTimeout(tick, every);
  };
  tick();
  return { stop, get stopped() { return stopped; } };
}

// The lines in the confirm box: the hotspot card and "Switch WiFi" in settings differ only in the first sentence
function confirmLines(net, ssid, variant) {
  const back = variant === 'switch'
    ? '没连上：这个页面会断开；热点马上就回来，手机重新连鸭子热点就能看到原因。'
    : `没连上：热点马上就回来，手机重新连 ${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '鸭子自己的热点'} 就能看到原因。`;
  const first = variant === 'switch'
    ? `鸭子会断开现在的 WiFi 去连「${ssid}」，这个页面会断开。`
    : `鸭子会关掉热点，去连「${ssid}」。你的手机会断开。`;
  return [first, '连上以后，手机（或电脑）连回家里的 WiFi，按设备打开：', ...openLines(net).map((l) => `· ${l}`), back];
}

// Copy an address. The duck's LAN address is http, not a secure context, so navigator.clipboard is unavailable: fall back to the old way (select an invisible input and copy)
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall back below */ }
  try {
    const t = document.createElement('textarea');
    t.value = text;
    t.setAttribute('readonly', '');
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(t);
    return ok;
  } catch { return false; }
}

function LastTry({ net }) {
  const lt = net.last_try;
  if (!lt || lt.ok !== false) return null;
  const why = lt.reason_text || '没连上';
  const ssid = net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '鸭子热点';
  return html`<div class="wifi-last-try" role="alert">上次连「${lt.ssid || '这个 WiFi'}」没成功：${why}
    ${net.mode === 'hotspot' ? html`<div>热点马上就回来，手机重新连 ${ssid} 就能看到原因。</div>` : null}</div>`;
}

function Switching({ net, ssid, variant }) {
  return html`<div class="wifi-switching" role="status">
    <b>正在切换……手机马上会断开</b>
    ${confirmLines(net, ssid || '这个 WiFi', variant).map((line) => html`<p>${line}</p>`)}
  </div>`;
}

// "Disconnected" = the connection to Studio is gone, or no message for 5 s (Main re-renders every 250 ms and WifiFlow recomputes along with it)
const linkGone = (link) => link.status !== 'open' || (link.lastAt > 0 && performance.now() - link.lastAt > FIND_SILENT_MS);

// After the page loses the duck: looking for the duck's new address (probe every 2 s, jump there when found); if not found within 3 minutes, switch back to the original explanation
function Finding({ net, find, variant }) {
  const ssid = find.ssid || '这个 WiFi';
  if (find.phase === 'timeout') {
    return html`<div class="wifi-switching wifi-finding" role="status" data-phase="timeout">
      <b>找了 3 分钟还没找到鸭子：自己打开吧</b>
      ${confirmLines(net, ssid, variant).slice(1).map((line) => html`<p>${line}</p>`)}
    </div>`;
  }
  return html`<div class="wifi-switching wifi-finding" role="status" data-phase="finding">
    <b>鸭子正在连「${ssid}」……</b>
    <p>请把这台设备连回「${ssid}」（电脑插着网线的不用管），找到鸭子会自动打开。</p>
    <ul class="wifi-open wifi-find-urls">${find.urls.map((u) => html`<li><a href=${u}>${u}</a>${/\.local[:/]/.test(u) ? '（苹果手机、Mac）' : '（Windows 电脑）'}</li>`)}</ul>
    <p>找不到时：去路由器设备列表找 ${net.hostname || 'duck-xxxx'} 的 IP。</p>
  </div>`;
}

export function WifiFlow({ net, link, variant = 'card' }) {
  const [scan, setScan] = useState({ networks: [], loading: true, error: null, cached: false, scan_at: null });
  const [sel, setSel] = useState(null);
  const [psk, setPsk] = useState('');
  const [show, setShow] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualName, setManualName] = useState('');
  const [manualPsk, setManualPsk] = useState('');
  const [manualShow, setManualShow] = useState(false);
  const [confirm, setConfirm] = useState(null);        // {ssid, psk}
  const [trying, setTrying] = useState(null);
  const [switching, setSwitching] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [msg, setMsg] = useState(null);
  // The duck's new address to look for after the connect request: {ssid, urls, phase}. phase: wait (still connected) → finding (disconnected, probing) → timeout (not found within 3 minutes)
  const [find, setFind] = useState(null);
  const [linkUp, setLinkUp] = useState(link.status === 'open');
  useEffect(() => link.on((m) => { if (m.t === '_status') setLinkUp(m.status === 'open'); }), []);
  const gone = !linkUp || linkGone(link);

  const rescan = async () => {
    setScan((s) => ({ ...s, loading: true, error: null }));
    const r = await link.cmd('net.op', { op: 'scan' }, 25000);
    if (!r.ok) {
      setScan({ networks: [], loading: false, error: r.reason || r.error || '读不到 WiFi 列表', cached: false, scan_at: null });
      return;
    }
    const d = r.data || {};
    setScan({ networks: Array.isArray(d.networks) ? d.networks : [], loading: false, error: null,
      cached: !!d.cached, scan_at: d.scan_at || null });
  };
  useEffect(() => {
    let alive = true;
    (async () => {
      await link.whenOpen();
      if (alive) await rescan();
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!switching && !find) return;
    const lt = net.last_try;
    // While still connected, this attempt has a result (or has long stopped being busy): no need to search
    if ((lt && typeof lt.at === 'number' && startedAt && lt.at * 1000 >= startedAt - 2000)
      || (!net.busy && startedAt && Date.now() - startedAt > 12000)) { setSwitching(false); setFind(null); }
  }, [net.busy, net.last_try ? net.last_try.at : null]);

  // Disconnected: start looking for the duck. If it reconnected to the original address (hotspot came back, meaning the connect failed): stop probing and go back to "waiting for result";
  // the effect above closes as soon as it receives this attempt's last_try, and LastTry still shows the failure reason (if the phone just slept a few seconds and never really disconnected, the duck search isn't lost either)
  useEffect(() => {
    if (!find) return;
    if (gone && find.phase === 'wait') setFind({ ...find, phase: 'finding' });
    else if (!gone && find.phase !== 'wait') setFind({ ...find, phase: 'wait' });
  }, [gone, find]);
  useEffect(() => {
    if (!find || find.phase !== 'finding') return undefined;
    const f = startFind({
      urls: find.urls,
      onFound: (url) => { if (linkGone(link)) location.href = url; },     // the original address just reconnected: don't jump, let the code above stop it
      onGiveUp: () => setFind((x) => (x ? { ...x, phase: 'timeout' } : x)),
    });
    return () => f.stop();
  }, [find ? find.phase : null]);

  // The confirm box is at the bottom of the card: on phones, after tapping "Connect" it would be out of view, so scroll to it when it pops up
  useEffect(() => {
    if (!confirm) return;
    const e = document.querySelector('.wifi-confirm-wrap');
    if (e && e.scrollIntoView) e.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [confirm]);

  const pick = (n) => {
    if (sel === n.ssid) { setSel(null); setPsk(''); return; }
    setSel(n.ssid); setPsk(''); setShow(false); setMsg(null);
  };
  const ask = (ssid, pass, locked = false) => {
    if (!ssid) { setMsg('先填 WiFi 名字'); return; }
    if (locked && !pass) { setMsg('这个 WiFi 加密了，要填密码'); return; }
    if (!pskFormatOk(pass)) { setMsg('WiFi 密码要 8–63 个字符，或者 64 位十六进制'); return; }
    setMsg(null);
    setConfirm({ ssid, psk: pass });
  };
  const start = async () => {
    if (!confirm) return;
    const { ssid, psk: pass } = confirm;
    setConfirm(null); setTrying(ssid); setStartedAt(Date.now()); setSwitching(true); setMsg(null);
    const wasOpen = link.status === 'open';
    setFind({ ssid, urls: findUrls(net), phase: 'wait' });
    const r = await link.cmd('net.op', { op: 'connect', ssid, psk: pass }, 20000);
    // Studio explicitly refused, wasn't connected to begin with, or was connected but didn't reply: not sent. Connection dropped while the receipt was in flight: most likely switching has started, go on looking for the duck
    if (!r.ok && (r.reason || !wasOpen || link.status === 'open')) {
      setSwitching(false); setFind(null); setMsg(r.reason || r.error || '没发出去');
    }
  };

  const nets = scan.networks || [];
  const ago = scan.cached ? minutesSince(scan.scan_at) : null;
  const busy = switching || net.busy === 'connecting' || (!!find && find.phase !== 'wait');
  return html`<div class="wifi-flow">
    ${find && find.phase !== 'wait' ? html`<${Finding} net=${net} find=${find} variant=${variant} />`
      : busy ? html`<${Switching} net=${net} ssid=${trying || (net.last_try && net.last_try.ssid)} variant=${variant} />` : null}
    ${scan.error ? html`<div class="wifi-msg">${scan.error}</div>` : null}
    <div class="wifi-list">
      ${nets.map((n) => {
        const on = sel === n.ssid;
        const open = n.security === 'open';
        const needs = !open;
        const can = open || pskOk(psk);
        return html`<div class=${'wifi-net' + (on ? ' on' : '')} data-ssid=${n.ssid}>
          <button class="wifi-net-head" type="button" aria-expanded=${on ? 'true' : 'false'} onClick=${() => pick(n)}>
            <${Bars} signal=${n.signal} />
            <span class="wifi-name"><b>${n.ssid}</b><span class="wifi-sub">${secLabel(n.security)}${n.saved ? ' · 已保存' : ''}</span></span>
            ${n.saved ? html`<span class="wifi-badge">已保存</span>` : null}
            ${open ? null : html`<span class="wifi-lock" title="${secLabel(n.security)}">🔒</span>`}
          </button>
          ${on ? html`<div class="wifi-row-body">
            ${needs ? html`<div class="wifi-psk-row">
              <input class="wifi-psk" type=${show ? 'text' : 'password'} value=${psk} autocomplete="new-password"
                placeholder="家里 WiFi 的密码" onInput=${(e) => setPsk(e.target.value)} />
              <label class="wifi-show"><input type="checkbox" checked=${show} onChange=${(e) => setShow(e.target.checked)} /> 显示密码</label>
            </div>${n.saved ? html`<div class="wifi-note">已保存；鸭子每次连都要密码（官方配网程序的规矩）。</div>` : null}`
              : html`<div class="wifi-note">这是开放网络，不用密码。</div>`}
            <div class="wifi-actions"><button class="wifi-btn primary wifi-connect" type="button" disabled=${!can || busy}
              onClick=${() => ask(n.ssid, needs ? psk : '', needs)}>连接</button></div>
          </div>` : null}
        </div>`;
      })}
    </div>
    <div class="wifi-manual">
      <button class="wifi-manual-head" type="button" aria-expanded=${manual ? 'true' : 'false'} onClick=${() => setManual(!manual)}>
        ${manual ? '收起' : '其他网络（手动输入名字）'}
      </button>
      ${manual ? html`<div class="wifi-row-body">
        <input class="wifi-manual-name" value=${manualName} placeholder="WiFi 名字" onInput=${(e) => setManualName(e.target.value)} />
        <input class="wifi-manual-psk" type=${manualShow ? 'text' : 'password'} value=${manualPsk}
          placeholder="密码（开放网络留空）" autocomplete="new-password" onInput=${(e) => setManualPsk(e.target.value)} />
        <label class="wifi-show"><input type="checkbox" checked=${manualShow} onChange=${(e) => setManualShow(e.target.checked)} /> 显示密码</label>
        <div class="wifi-actions"><button class="wifi-btn primary wifi-manual-connect" type="button" disabled=${busy || !manualName}
          onClick=${() => ask(manualName, manualPsk)}>连接</button></div>
      </div>` : null}
    </div>
    <div class="wifi-actions">
      <button class="wifi-btn wifi-rescan" type="button" disabled=${scan.loading || busy} onClick=${rescan}>
        ${scan.loading ? '正在扫描…' : '重新扫描'}</button>
      ${ago ? html`<span class="wifi-note">这是 ${ago} 分钟前扫的</span>` : null}
    </div>
    ${msg ? html`<div class="wifi-msg">${msg}</div>` : null}
    ${confirm ? html`<div class="wifi-confirm-wrap"><${ConfirmBox} cls="wifi-confirm" lines=${confirmLines(net, confirm.ssid, variant)}
      confirmLabel=${'断开去连「' + confirm.ssid + '」'} onCancel=${() => setConfirm(null)} onConfirm=${start} /></div>` : null}
  </div>`;
}

export function WifiCard({ net, link, secure }) {
  if (!net || !net.known || net.mode !== 'hotspot') return null;
  return html`<section class="board wifi-card" aria-label="连 WiFi">
    <h2>连 WiFi</h2>
    <p class="wifi-lead">现在是鸭子自己的热点（${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : 'Microduck'}）。
      选家里的 WiFi、填密码，鸭子就连过去；连上以后手机（或电脑）连回家里的 WiFi，按设备打开：</p>
    <ul class="wifi-open">${openLines(net).map((l) => html`<li>${l}</li>`)}</ul>
    <${LastTry} net=${net} />
    <${WifiFlow} net=${net} link=${link} />
    ${secure === false ? html`<div class="wifi-note" role="note">热点密码大家都知道，附近的人也能连上控制鸭子；在外面演示前，去「更多」设个登录密码</div>` : null}
  </section>`;
}

export function WifiSettings({ net, link }) {
  const [flow, setFlow] = useState(false);
  const [scan, setScan] = useState(null);
  const [forget, setForget] = useState(null);
  const [msg, setMsg] = useState(null);
  const load = async () => {
    const r = await link.cmd('net.op', { op: 'scan' }, 25000);
    setScan(r.ok ? (r.data || { networks: [] }) : { networks: [], error: r.reason || r.error });
  };
  useEffect(() => {
    if (!net || !net.known) return undefined;
    let alive = true;
    (async () => { await link.whenOpen(); if (alive) await load(); })();
    return () => { alive = false; };
  }, [net && net.known]);
  if (!net || !net.known) return null;
  const saved = (scan && scan.networks ? scan.networks : []).filter((n) => n.saved);
  const doForget = async (ssid) => {
    setForget(null); setMsg(null);
    const r = await link.cmd('net.op', { op: 'forget', ssid }, 15000);
    if (!r.ok) { setMsg(r.reason || r.error || '没忘掉'); return; }
    setMsg(r.data && r.data.removed === false ? `鸭子本来就没记着「${ssid}」` : `忘掉了「${ssid}」`);
    load();
  };
  const current = net.mode === 'hotspot' ? '鸭子自己的热点' : (net.ssid || '没连着 WiFi');
  return html`<div class="board wifi-settings" aria-label="WiFi 设置">
    <h2>WiFi</h2>
    <${LastTry} net=${net} />
    <div class="wifi-now">
      <div class="big">现在：${current}</div>
      ${net.mode === 'hotspot' ? html`<div>热点 ${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '—'} · 密码 ${net.hotspot && net.hotspot.psk ? net.hotspot.psk : '—'}</div>`
        : net.mode === 'wifi' ? html`<div class="wifi-actions"><${Bars} signal=${net.signal} /><span>信号 ${net.signal ?? '—'}</span><span>IP ${net.ip4 || '—'}</span></div>`
          : html`<div>现在没连着 WiFi。</div>`}
      <div class="wifi-note">打开 Studio 的地址见上面「这只鸭子的地址」（按设备挑一个，能复制）。</div>
    </div>
    <div class="wifi-actions"><button class="wifi-btn primary" type="button" onClick=${() => setFlow(!flow)}>
      ${flow ? '收起' : '换一个 WiFi'}</button></div>
    ${flow ? html`<div class="wifi-flow"><${WifiFlow} net=${net} link=${link} variant="switch" /></div>` : null}
    <div>
      <div class="wifi-note">已保存的网络</div>
      ${scan && scan.error ? html`<div class="wifi-msg">${scan.error}</div>` : null}
      ${saved.length ? saved.map((n) => html`<div class="wifi-saved-row">
        <span class="wifi-name">${n.ssid}</span>
        ${n.ssid === net.ssid ? html`<span class="wifi-badge">正在用</span>` : null}
        <button class="wifi-btn wifi-forget" type="button" data-ssid=${n.ssid}
          onClick=${() => n.ssid === net.ssid ? setForget(n.ssid) : doForget(n.ssid)}>忘掉</button>
      </div>`) : html`<div class="wifi-note">${scan ? '还没有已保存的 WiFi。' : '读取中…'}</div>`}
    </div>
    ${msg ? html`<div class="wifi-note">${msg}</div>` : null}
    ${forget ? html`<div class="wifi-confirm-wrap"><${ConfirmBox} cls="wifi-confirm"
      lines=${[`忘掉「${forget}」以后鸭子会断开；没有别的 WiFi 可连的话，1 分钟后开热点。`]}
      confirmLabel="忘掉" onCancel=${() => setForget(null)} onConfirm=${() => doForget(forget)} /></div>` : null}
  </div>`;
}

// "This duck's addresses" on the "More" page (10-20 real-hardware acceptance check: a computer running Clash couldn't open .local): backend net.urls lists the ones usable now
// HTTP can list the DHCP address; HTTPS lists the hostname and the fixed IPs covered by the certificate.
export function DuckAddresses({ net }) {
  const [copied, setCopied] = useState(null);       // {url, ok}
  useEffect(() => {
    if (!copied) return undefined;
    const t = setTimeout(() => setCopied(null), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  if (!net || !net.known) return null;
  const urls = net.urls || [];
  const hasIp = urls.some((u) => u.kind === 'ip');
  const https = net.url_local?.startsWith('https:');
  const copy = async (url) => setCopied({ url, ok: await copyText(url) });
  return html`<div class="board wifi-settings duck-addr" aria-label="这只鸭子的地址">
    <h2>这只鸭子的地址</h2>
    <p class="wifi-lead">${net.mode === 'hotspot' ? '现在是鸭子自己的热点：连着热点的手机用 IP 那一个。'
      : '跟鸭子在同一个 WiFi 里，按设备挑一个。'}</p>
    ${urls.map((u) => html`<div class="duck-addr-row" data-kind=${u.kind}>
      <span class="wifi-name"><a href=${u.url}>${u.url}</a><span class="wifi-sub">${u.note}</span></span>
      <button class="wifi-btn duck-addr-copy" type="button" onClick=${() => copy(u.url)}>
        ${copied && copied.url === u.url ? (copied.ok ? '已复制' : '复制不了，长按地址复制') : '复制'}</button>
    </div>`)}
    ${hasIp || https ? null
      : html`<div class="wifi-note">现在不知道 IP（没连上 WiFi，或者读不到配网程序）：去路由器的设备列表找 ${net.hostname || 'duck-xxxx'}。</div>`}
    <div class="wifi-note">${https && !hasIp
      ? 'HTTPS 请使用上方的主机名。手机无法解析主机名时，可以连接鸭子热点，再用热点地址。'
      : '安卓手机打不开带名字的地址就用 IP。'} 电脑开着 Clash 的 TUN 模式还打不开：在 Clash 里把局域网（192.168.0.0/16）设成直连。</div>
  </div>`;
}
