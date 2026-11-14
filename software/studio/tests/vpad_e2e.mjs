// End-to-end test of the web gamepad (gamepad page round 3: the buttons on the picture can be pressed): connects to a local headless Edge (CDP), opens Studio's gamepad page (the fake robotd replays duck #2's
// data), clicks buttons on the picture, drags the sticks, presses keyboard keys, drags with two fingers at once on a phone, then looks at what the fake robotd recorded as "received" (dev/fake_robotd.py --record).
// What was received at each step is printed as JSON to stdout, and tests/test_vpad_e2e.py judges whether it's right. Real page, real Studio backend; only robotd is fake.
//
// To run it alone (start the fake robotd, Studio and headless Edge first; don't let the ports clash with anyone else's):
//   node tests/vpad_e2e.mjs --url http://127.0.0.1:18090/#/pad --cdp 9343 --record <rd.jsonl> --fake 17022 [--shots <screenshot dir>]
// Node ≥ 22 (built-in WebSocket), no packages need to be installed.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import net from 'node:net';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const URL_ = arg('url');
const CDP = arg('cdp');
const REC = arg('record');
const FAKE = Number(arg('fake'));
const SHOTS = arg('shots', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stderr.write(`[vpad-e2e] ${a.join(' ')}\n`);

// ---------------- What the fake robotd recorded ----------------
// Things Studio keeps asking all the time (status, bindings, etc.) don't count: only look at "make the duck move / make a sound"
const POLL = new Set(['hello', 'robot.health', 'robot.busStatus', 'robot.policies', 'robot.busCommand', 'pad.status', 'system.info',
  'robot.subscribe', 'pad.bindings', 'fake.set']);
const recs = () => readFileSync(REC, 'utf-8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => !POLL.has(r.method));
let mark = 0;
const since = () => { const all = recs(); const out = all.slice(mark); mark = all.length; return out.map(({ method, params, notify }) => ({ method, params, notify })); };
const fakeSet = (params) => new Promise((resolve, reject) => {
  const s = net.connect(FAKE, '127.0.0.1', () => s.write(`${JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'fake.set', params })}\n`));
  let buf = '';
  s.on('data', (d) => { buf += d; if (buf.includes('\n')) { s.end(); resolve(JSON.parse(buf)); } });
  s.on('error', reject);
});

// ---------------- CDP ----------------
// Open our own tab (don't borrow another session's page: the viewports would change each other)
const page = await (await fetch(`http://127.0.0.1:${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const waiting = new Map();
const errors = [];
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
  if (m.method === 'Page.javascriptDialogOpening') { errors.push(`弹框：${m.params.message}`); send('Page.handleJavaScriptDialog', { accept: true }); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`页面里出错：${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const waitFor = async (expr, what, timeout = 6000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[document.visibilityState, document.hasFocus(), document.querySelector('.pd-vbar')?.textContent, document.querySelector('.pd-pose')?.textContent,
    [...document.querySelectorAll('.pd-big')].map((b) => b.textContent).join(' | ')].join(' ／ ').replace(/\\s+/g, ' ')`);
  let fk = null;
  try { fk = (await fakeSet({})).result?.posture; } catch { /* fake robotd not running */ }
  throw new Error(`${timeout / 1000} 秒没等到：${what}。页面上现在：${now}；假 robotd 的姿势：${fk}`);
};
const vbar = () => js(`document.querySelector('.pd-vbar')?.textContent?.replace(/\\s+/g, ' ') || ''`);
// Element center (scroll it to the middle of the screen first)
const box = (sel) => js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null;
  e.scrollIntoView({ block: 'center', inline: 'nearest' }); const r = e.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height }; })()`);
const key = (r) => `.pd-svg-live [data-role="${r}"]`;
const mouse = (type, x, y, buttons = 1) => send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons, clickCount: 1 });
async function hold(sel, ms, during) {
  const b = await box(sel);
  if (!b) throw new Error(`找不到 ${sel}`);
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  if (during) await during();
  await sleep(ms);
  await mouse('mouseReleased', b.x, b.y, 0);
}
// Drag a stick: press at (center + off), drag to +d in a few steps, pause ms, release
async function drag(sel, d, ms, { off = [0, 0], during } = {}) {
  const b = await box(sel);
  const x0 = b.x + off[0], y0 = b.y + off[1];
  await mouse('mouseMoved', x0, y0, 0);
  await mouse('mousePressed', x0, y0);
  for (let i = 1; i <= 5; i++) { await mouse('mouseMoved', x0 + (d[0] * i) / 5, y0 + (d[1] * i) / 5); await sleep(20); }
  if (during) await during();
  await sleep(ms);
  await mouse('mouseReleased', x0 + d[0], y0 + d[1], 0);
}
async function shot(name, sel, toSel) {
  if (!SHOTS) return;
  let clip;
  if (toSel) {                                     // crop from the top edge of sel to the bottom edge of toSel
    const r = await js(`(() => { const a = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
      const b = document.querySelector(${JSON.stringify(toSel)}).getBoundingClientRect();
      return { x: a.x + scrollX - 8, y: a.y + scrollY - 8, width: a.width + 16, height: b.bottom - a.y + 16 }; })()`);
    clip = { ...r, scale: 1 };
  } else if (sel === 'full') {
    const h = await js('Math.ceil(document.documentElement.scrollHeight)');
    const w = await js('document.documentElement.clientWidth');
    clip = { x: 0, y: 0, width: w, height: h, scale: 1 };
  } else if (sel) {
    const r = await js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); const r = e.getBoundingClientRect();
      return { x: r.x + scrollX - 8, y: r.y + scrollY - 8, width: r.width + 16, height: r.height + 16 }; })()`);
    clip = { ...r, scale: 1 };
  }
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: !!clip, ...(clip ? { clip } : {}) });
  writeFileSync(join(SHOTS, name), Buffer.from(r.result.data, 'base64'));
  log('截图', name);
}
async function open(w, h, mobile) {
  // A newly opened tab in headless Edge may be treated as "in the background": the page reports visible:false and Studio stops pushing status. Bring it to the front and emulate focus
  await send('Page.bringToFront');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: mobile ? 5 : 1 });
  await send('Page.navigate', { url: 'about:blank' });
  await sleep(300);
  await send('Page.navigate', { url: URL_ });
  await waitFor(`!!document.querySelector('.pd-svg-live [data-role="start"]')`, '手柄图出来');
  await waitFor(`/Start 现在会：[^—]/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '收到手柄页的状态');
  await sleep(600);
}

// Only for the two mirroring screenshots: there's no padd tap on a computer, so the picture can't show what was pressed on the physical gamepad. When window.__fakeLive is set,
// replace live in the pushed {t:'pad'} with fake physical-gamepad key presses (only changes the page display; the Studio backend decides "physical gamepad connected" from the fake configd's pad.status, which is real)
const INJECT = `(() => {
  const NWS = window.WebSocket;
  class W extends NWS {
    set onmessage(fn) {
      super.onmessage = (ev) => {
        let d = ev.data;
        if (window.__fakeLive && typeof d === 'string' && d.startsWith('{"t":"pad"')) {
          try { const m = JSON.parse(d); m.live = window.__fakeLive; d = JSON.stringify(m); } catch (e) { /* 原样给 */ }
        }
        fn({ data: d });
      };
    }
    get onmessage() { return super.onmessage; }
  }
  window.WebSocket = W;
})();`;
const FAKE_LIVE = JSON.stringify({ state: 'attached', last_ms: 20, other: [], buttons: { south: true, lt: true },
  axes: { lx: 0.45, ly: -0.7, rx: -0.6, ry: 0, lt: 0.8, rt: 0 },
  device: { name: 'Xbox Wireless Controller', kind: 'xbox', bus: '蓝牙', keys_unverified: false } });
await send('Runtime.enable');
await send('Page.enable');
await send('Page.addScriptToEvaluateOnNewDocument', { source: INJECT });
const out = { steps: {}, errors };
async function step(name, fn, settle = 500) {
  since();
  const extra = (await fn()) || {};
  await sleep(settle);
  out.steps[name] = { recs: since(), ...extra };
  log(name, out.steps[name].recs.length, '条');
}

// ================= Computer width =================
await open(1280, 900, false);
await shot('desktop-1-idle.png');
out.start0 = await vbar();

// Sticks are relative: the point where you press is the center; pressing without moving doesn't walk (round-3 review V2)
await step('stick_press_only', () => drag(key('ls'), [0, 0], 300, { off: [12, 0] }));
// Drag the left stick on the picture up: walk (vx > 0), release sends 0 once
await step('stick_drag', () => drag(key('ls'), [0, -40], 600));
// A: lower head to pick up (robot.do request)
await step('key_a', () => hold(key('south'), 80), 700);
// X held: one request first, then continuous notifications (roll)
await step('x_hold', () => hold(key('west'), 800), 600);
// LT held: open mouth, continuous wheee; release closes mouth, wheee stops (take a "key held" screenshot)
await step('lt_hold', () => hold(key('lt'), 600, async () => {
  await sleep(250);
  const b = await box(key('ls'));
  await shot('desktop-2-pressed.png', '.pd-live', '.pd-vbar');
  return b;
}), 700);
// RT tap: a quack
await step('rt_tap', () => hold(key('rt'), 120), 600);
// Y: head mode; right stick up = neck (neck_pitch positive); release returns head to center; press Y again to return to walking
await step('head', async () => {
  await hold(key('north'), 80);
  await waitFor(`/摇杆管：头模式/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '进了头模式');
  await drag(key('rs'), [0, -40], 500, { during: () => shot('desktop-3-head.png', '.pd-live', '.pd-vbar') });
  await sleep(300);
  await hold(key('north'), 80);
  await waitFor(`/摇杆管：走路/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '回到走路');
  return { bar: await vbar() };
});
// B: body mode; left stick down = crouch (z < 0); release returns to center (still in body mode); press B again to exit (active:false)
await step('body', async () => {
  await hold(key('east'), 80);
  await waitFor(`/摇杆管：身体模式/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '进了身体模式');
  await drag(key('ls'), [0, 40], 400);
  await sleep(300);
  await hold(key('east'), 80);
  await waitFor(`/摇杆管：走路/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '回到走路');
});
// Keyboard: W doesn't walk if the picture hasn't been clicked; after clicking the picture (remote area gets focus) W walks; arrow keys don't walk (round-3 review V2)
await step('keyboard_unfocused', async () => {
  await js('document.activeElement && document.activeElement.blur()');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(300);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
});
await step('keyboard', async () => {
  const b = await box('.pd-svgzone');
  await mouse('mousePressed', b.x, b.y - b.h * 0.42);               // click the blank area at the top edge of the picture (not a button)
  await mouse('mouseReleased', b.x, b.y - b.h * 0.42, 0);
  const focused = await js(`document.activeElement?.classList.contains('pd-zone')`);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(200);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87, autoRepeat: true });
  await sleep(250);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(300);
  const n = since();
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'ArrowUp', key: 'ArrowUp', windowsVirtualKeyCode: 38 });
  await sleep(300);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'ArrowUp', key: 'ArrowUp', windowsVirtualKeyCode: 38 });
  return { focused, w_recs: n };
});
// Window loses focus while the stick is held: stop immediately, and send nothing more even though the finger is still down
await step('blur', async () => {
  const b = await box(key('ls'));
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  for (let i = 1; i <= 5; i++) { await mouse('mouseMoved', b.x, b.y - 8 * i); await sleep(20); }
  await sleep(400);
  const before = since();
  await js(`window.dispatchEvent(new Event('blur'))`);
  await sleep(150);
  const atBlur = since();
  await mouse('mouseMoved', b.x, b.y - 45);
  await sleep(500);
  const after = since();
  await mouse('mouseReleased', b.x, b.y - 45, 0);
  return { before, atBlur, after };
});
// Start: walking (ready to walk) → stop (stand); after the fake robotd becomes "standing and holding", press again → start walking
await step('start_stop', () => hold(key('start'), 80), 900);
await waitFor(`/Start 现在会：开始走/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'Start 变成「开始走」');
await step('start_walk', () => hold(key('start'), 80), 900);
await waitFor(`/Start 现在会：停下/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'Start 变回「停下」');
// Select on the picture = e-stop: releases torque on press (doesn't wait for release)
await step('select', async () => {
  const b = await box(key('select'));
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  await sleep(250);
  const whilePressed = since();
  await mouse('mouseReleased', b.x, b.y, 0);
  await waitFor(`!!document.querySelector('.estop.done')`, '卸力确认');
  return { whilePressed };
}, 400);
await fakeSet({ posture: 'policy' });
await sleep(2600);                                                     // the 2 s guard after torque release has passed
// D-pad up (follows official): a press under 3 s doesn't switch; a full 3 s sends robot.setMode. The fake robotd first has no roller model installed (rejected, the page shows the reason); after installing it, pressing again switches, and pressing again switches back to walking
const vmsg = () => js(`document.querySelector('.pd-vmsg')?.textContent || ''`);
const duSays = (word) => `(document.querySelector('${key('du')} title')?.textContent || '').includes(${JSON.stringify(word)})`;
await step('dpad_up_short', () => hold(key('du'), 1000), 300);
out.du_short = await vmsg();
await step('dpad_up_refused', async () => {
  await hold(key('du'), 3400);
  await waitFor(`/没装轮滑模型/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, '页面说没装轮滑模型');
}, 300);
await fakeSet({ roller_models: true });
await step('dpad_up_hold', async () => {
  await hold(key('du'), 3400);
  await waitFor(`/切到轮滑/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, '页面说切到轮滑');
}, 300);
await waitFor(duSays('切到走路'), '十字上变成「切到走路」（robot.policies 2 秒问一次）');
await step('dpad_up_back', async () => {
  await hold(key('du'), 3400);
  await waitFor(`/切到走路/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, '页面说切到走路');
}, 300);
await fakeSet({ roller_models: false });
// D-pad right (follows official): one press sends robot.rebootMotors, no confirmation; afterwards it goes limp just like a torque release
await step('dpad_right', async () => {
  await hold(key('dr'), 80);
  await waitFor(`/重启舵机发出去了/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, '页面说重启舵机发出去了');
}, 300);
await fakeSet({ posture: 'policy' });
await sleep(2600);
// Leaving the gamepad area (with body mode on): body exits (active:false). Since the gamepad was merged into the overview, #/ is the same page (the gamepad block may still be visible),
// so switching to the log page is what counts as "leaving" (overview rearrangement review O1; the scrolled-out-of-viewport case is tested in tests/overview_e2e.mjs)
await step('leave_page', async () => {
  await hold(key('east'), 80);
  await waitFor(`/摇杆管：身体模式/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '进了身体模式');
  await drag(key('ls'), [0, -30], 300);
  await js(`location.hash = '#/logs'`);
  await sleep(600);
  await js(`location.hash = '#/pad'`);
  await waitFor(`/Start 现在会：[^—]/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '回到手柄页');
  await sleep(500);
});
// After returning to the gamepad page the sticks still work (drive open lifted the "left" state)
await step('back_again', () => drag(key('ls'), [0, -40], 400));
// Physical gamepad connected (mirroring): presses and drags on the picture aren't sent; Select still releases torque
await fakeSet({ pad_connected: true });
await waitFor(`!!document.querySelector('.pd-remote .banner') && /实体手柄连着/.test(document.querySelector('.pd-remote')?.textContent || '')`, '镜像', 8000);
await step('mirror', async () => {
  await hold(key('south'), 80);
  await drag(key('ls'), [0, -40], 400);
  await hold(key('north'), 80);
  await hold(key('lt'), 300);
  const bar = await vbar();
  await js(`window.__fakeLive = ${FAKE_LIVE}`);
  await sleep(400);
  await shot('desktop-4-mirror.png', '.pd-live', '.pd-vbar');
  await js('window.__fakeLive = null');
  return { bar };
});
await step('mirror_select', async () => {
  await hold(key('select'), 100);
  await waitFor(`!!document.querySelector('.estop.done')`, '镜像时卸力确认');
}, 400);
await fakeSet({ pad_connected: false, posture: 'policy' });
await waitFor(`!/实体手柄连着/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '镜像结束', 8000);
await sleep(2600);

// ================= Phone width 390 =================
await open(390, 844, true);
out.phone = await js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await shot('phone-1-idle.png', 'full');
// Two fingers drag both sticks on the gamepad picture at once (on touch, the press must start in the transparent start area .pd-ov-stick): left up (forward), right to the right (turn right)
await step('two_fingers', async () => {
  const [L, Rr] = await js(`(() => {
    const ls = document.querySelector('.pd-svgbox .pd-ov-stick[data-ov="ls"]');
    const rs = document.querySelector('.pd-svgbox .pd-ov-stick[data-ov="rs"]');
    ls.scrollIntoView({ block: 'center', inline: 'nearest' });
    const a = ls.getBoundingClientRect(), b = rs.getBoundingClientRect();
    return [{ x: a.x + a.width / 2, y: a.y + a.height / 2 }, { x: b.x + b.width / 2, y: b.y + b.height / 2 }];
  })()`);
  await sleep(650);                    // touches within 0.5 s after the page scrolled are ignored (prevents accidental taps during inertial scrolling: overview rearrangement review O2)
  const pts = (dy, dx) => [{ x: L.x, y: L.y - dy, id: 1 }, { x: Rr.x + dx, y: Rr.y, id: 2 }];
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts(0, 0) });
  for (let i = 1; i <= 5; i++) { await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pts(9 * i, 9 * i) }); await sleep(30); }
  await sleep(500);
  await shot('phone-2-two-sticks.png', '.pd-svgzone');
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
});
// Tap Y on the picture on the phone: head mode
await step('phone_head', async () => {
  const b = await box(key('north'));
  await sleep(650);                    // same as above: tap 0.5 s after scrolling ends
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: b.x, y: b.y, id: 3 }] });
  await sleep(80);
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitFor(`/摇杆管：头模式/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '手机上进了头模式');
  await shot('phone-3-head.png', '.pd-live', '.pd-vbar');
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: b.x, y: b.y, id: 4 }] });
  await sleep(80);
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitFor(`/摇杆管：走路/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '手机上回到走路');
});
await fakeSet({ pad_connected: true });
await waitFor(`/实体手柄连着/.test(document.querySelector('.pd-vbar')?.textContent || '')`, '手机上镜像', 8000);
await js(`window.__fakeLive = ${FAKE_LIVE}`);
await sleep(400);
await shot('phone-4-mirror.png', '.pd-live', '.pd-vbar');
await js('window.__fakeLive = null');
out.phone_mirror = await js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await fakeSet({ pad_connected: false });

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
