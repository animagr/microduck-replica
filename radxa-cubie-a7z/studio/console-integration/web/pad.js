// Gamepad section (merged into the overview, just scroll down: overview re-layout plan §1.2): see how the gamepad is doing now, pair a new gamepad (visual wizard), test the e-stop,
// web gamepad (the keys on the picture can be pressed), web remote control (stand up / start walking / sit down, sticks, skills, actions). #/pad is an anchor on the overview; opening it scrolls to this section.
//
// All data comes from {t:'pad', …} pushed by the backend studio/pad.py (10 Hz while this section is on screen, 1 Hz otherwise).
// Commands sent by the page are all link.cmd('pad.op', {op, …}):
//   watch                 I am looking at the gamepad section (once it has been on screen for 0.3 s, every 2 s; if the backend hears nothing for 6 s it closes the padd side channel and slows polling)
//   refresh / scan {seconds} / pair {mac?} / cancel / forget {mac} / keys_done / wizard_reset   pairing wizard
//   estop_test {action}   e-stop test: start / cancel
//   drive {open, seq}     entered the gamepad section (only clears "left", does not take the wheel); drive {on:false, seq} leave; drive {on:true, force} take over
//                         "in the gamepad section" = route is / or /pad ∧ page visible ∧ this section in the viewport (review O1, see padActivity below)
//   sticks {mode,lx,ly,rx,ry,seq}  web gamepad sticks (the two on the picture): -1..1, x positive right, y positive down; the backend uses padd's formulas
//                         to convert them into robot.move / head / pose; sent only while held (10 Hz), seq is the page's incrementing sequence number
//   stop {seq}            released: in walk mode send 0 once, in head mode the head recenters, in body mode the body recenters. The backend drops any frame older than the stop
//   mode {mode, seq}      Y / B on the picture: drive / head / body
//   mode {mode, hb:true}  in head and body modes report "still here" every second (the backend exits after 3 s of silence); renew only, never enter: if the backend has already exited it replies dropped
//   keys {held, down, seq}   held keys LT / RT / X: sent on press and release, reported every 0.15 s while held (the backend treats 0.45 s of silence, 0.3 s for X, as released)
//   key {key, src:'svg'}  the moment A / X / LB / RB / D-pad down on the picture is pressed (handled per pad.bindings)
//   start {expect, src:'svg'}   Start on the picture: the backend rejects it if its choice differs from expect (the state just changed)
//   reboot {src:'svg'}    D-pad right on the picture: reboot all servos (as in the official version: sent on one press, no confirmation; the main program relaxes the whole body first)
//   drive_mode {expect, src:'svg'}   D-pad up on the picture held for 3 s (timed in the page): switch walking / roller skating, expect is the mode to switch to
//   stand / walk / walk_stop / sit         stand up / start walking / stop (stand still) / sit down (the backend re-checks by posture)
//   skill {name} / sound {tag}             official skills (robot.do) / make a sound (robot.sound)
//   action_start {id, press} / action_hold {press} / action_stop   actions and combo actions: only performed while held (say "still holding" every 0.15 s), stop on release;
//                         press is the sequence number of this press; the backend only accepts keepalives from the same press (code review C7)
// Select on the picture takes the same path as Relax at the top: link.cmd('relax'), sent on press, can be pressed at any time (review 3 V3).
// Key functions follow the fork's padd on the duck (fork firmware padd/src/main.rs); key names follow what is printed on the gamepad.
// Virtual gamepad: the web page sends whole frames and yields when a physical gamepad is connected; the code is our own.
import { html, useState, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { InlineCamera } from './sensors.js';
import { MotionStudio } from './motion-studio.js';
import { AudioInteraction } from './audio-interaction.js';

const SEND_MS = 100;        // while a stick is held send 10 times per second; send 0 once on release, and the duck stops on its own if it gets nothing for 0.5 s (robotd's deadman)
const WATCH_MS = 2000;
const HOLD_MS = 150;        // actions / held keys say "still holding" every 0.15 s; the backend stops after 0.45 s of silence
const MODE_HB_MS = 1000;    // head / body mode reports "still here" every second
const MODE_GRACE_MS = 800;  // Y / B just pressed: within this long the page's own state wins (the backend snapshot has not caught up yet)
const DRIVE_HOLD_MS = 3000; // D-pad up must be held this long to switch walking / roller skating (official padd:247-252: easy to brush while walking, hence the hold)
const KEY_STALE_MS = 1000;  // while a keyboard key is held the browser keeps repeating keydown; no keydown for over 1 s is treated as released (stuck key: review 12)
const BUSY_MS = 3000;       // after stand / walk / sit is pressed, the buttons gray out until the posture changes or 3 s pass
const DZ = 0.1;             // stick dead zone (same as padd, padd:184-187): any axis below this counts as 0
const STICK_TRAVEL = 40;    // sticks on the picture: dragging the finger this far (picture coordinates, picture width 400) counts as full deflection
const WATCH_SETTLE_MS = 300;   // only send watch once the gamepad section has been on screen continuously this long (do not open the padd side channel on a quick scroll past: review O1)
const TAP_MS = 120;         // touch: only counts as pressed after being held this long without moving and without the browser canceling it (starting a page scroll) (review O2)
const TAP_MOVE_PX = 8;      // touch: moving this much after pressing is treated as scrolling the page
const SCROLL_GUARD_MS = 500;   // touch: presses within this long after the page scrolls are ignored (that is what a finger touch during inertial scrolling looks like: review O2)
const STICK_GRAB = 30;      // sticks on the picture: touch grab area (radius, picture coordinates; the cap is 17). Enlarging it to 30 still does not touch the neighboring keys / D-pad
let SEQ = 0;
const nextSeq = () => ++SEQ;

// ---------------- "In the gamepad section": old overview /pad or standalone /remote/* ∧ page visible ∧ control section in the viewport ----------------
// Since the gamepad was merged into the overview this section stays mounted (the overview is only hidden, not unmounted), so the cleanup that used to hang on "mount / unmount" (release everything, drive off,
// stop HoldButton, mode heartbeat) would never run. So all of it hangs on active: the moment it goes from true to false, release everything, send drive {on:false},
// and send a heartbeat right away (pad_visible:false); from false to true send drive {open}. When the route changes, app.js synchronously calls setRoute first in hashchange,
// without waiting for the IntersectionObserver (after hiding, IO reports "not intersecting" one frame late, and safety must not depend on it).
const ACT = { route: location.hash.replace(/^#/, '') || '/', visible: document.visibilityState === 'visible',
  inView: false, active: false, standalone: false, subs: new Set(), link: null };
function actRecompute(why, routeChanged = false) {
  const legacyRoute = !ACT.standalone && (ACT.route === '/' || ACT.route === '/pad');
  const remoteRoute = legacyRoute || /^\/remote\/(control|recording|gamepad)$/.test(ACT.route);
  const a = remoteRoute && ACT.visible && ACT.inView;
  const changed = a !== ACT.active;
  ACT.active = a;
  for (const fn of ACT.subs) {
    try { fn({ active: a, inView: ACT.inView, changed, routeChanged }, why); } catch (e) { console.error('手柄区的订阅出错', e); }
  }
  if (changed && ACT.link) ACT.link.heartbeat();   // the backend learns right away: 10 Hz ↔ 1 Hz (the app.py sender only looks at pad_visible)
}
export const padActivity = {
  get active() { return ACT.active; },
  get inView() { return ACT.inView; },
  bind(link) { ACT.link = link; },
  useStandaloneRoutes() { if (!ACT.standalone) { ACT.standalone = true; actRecompute('启用独立遥控页'); } },
  setRoute(route) { const next = route || '/'; const changed = next !== ACT.route; ACT.route = next; actRecompute(`切换页面（#${ACT.route}）`, changed); },
  setInView(v) { if (v !== ACT.inView) { ACT.inView = v; actRecompute('滚出了手柄这一块'); } },
  subscribe(fn) { ACT.subs.add(fn); return () => ACT.subs.delete(fn); },
};
document.addEventListener('visibilitychange', () => { ACT.visible = document.visibilityState === 'visible'; actRecompute('页面转到后台'); });
window.__pad = padActivity;          // for troubleshooting (the e2e tests look at it too): whether we currently count as "in the gamepad section"

// The getting-started checklist's "Do it" must land right on target (review O17): the pairing wizard, e-stop test, paired gamepads and remote control live in this section while the checklist is outside, so a small event does it
const GO = new Set();
export function padGo(what) { for (const fn of GO) fn(what); }

// Touch mis-tap protection (review O2): the overview is a scroll-down home page, and the way down is full of controls that act on a single touch
let lastScrollAt = -1e9;
window.addEventListener('scroll', () => { lastScrollAt = performance.now(); }, { passive: true, capture: true });
const scrolledRecently = () => performance.now() - lastScrollAt < SCROLL_GUARD_MS;
const isTouch = (e) => e.pointerType === 'touch' || e.pointerType === 'pen';
// One press on a touch screen: only counts as a press if it has not moved (< TAP_MOVE_PX) within TAP_MS and has not been canceled by the browser; releasing / being canceled afterwards = release;
// releasing within TAP_MS = a tap (does nothing if no tap handler is given); moved or canceled = do nothing (it is a page scroll).
// No preventDefault: the browser can still use this touch to scroll the page (as soon as it scrolls it fires pointercancel). Returns a "cancel" function
function touchHold(e, { press, release, tap }) {
  const pid = e.pointerId, x0 = e.clientX, y0 = e.clientY;
  let phase = 'pending';
  const off = () => {
    clearTimeout(timer);
    window.removeEventListener('pointermove', mv, true);
    window.removeEventListener('pointerup', up, true);
    window.removeEventListener('pointercancel', cc, true);
  };
  const mv = (ev) => {
    if (ev.pointerId !== pid || phase !== 'pending') return;
    if (Math.hypot(ev.clientX - x0, ev.clientY - y0) >= TAP_MOVE_PX) { phase = 'gone'; off(); }
  };
  const up = (ev) => {
    if (ev.pointerId !== pid) return;
    const was = phase; phase = 'gone'; off();
    if (was === 'pending' && tap) tap(); else if (was === 'held' && release) release();
  };
  const cc = (ev) => {
    if (ev.pointerId !== pid) return;
    const was = phase; phase = 'gone'; off();
    if (was === 'held' && release) release();
  };
  const timer = setTimeout(() => { if (phase !== 'pending') return; phase = 'held'; window.removeEventListener('pointermove', mv, true); press(); }, TAP_MS);
  window.addEventListener('pointermove', mv, true);
  window.addEventListener('pointerup', up, true);
  window.addEventListener('pointercancel', cc, true);
  return () => { if (phase === 'held' && release) release(); phase = 'gone'; off(); };
}

// ---------------- Per model: key names, shape, how to enter pairing mode ----------------

const KINDS = {
  xbox: {
    label: 'Xbox 手柄', layout: 'xbox',
    names: { south: 'A', east: 'B', west: 'X', north: 'Y', lb: 'LB', rb: 'RB', lt: 'LT', rt: 'RT', select: '视图', start: '菜单', home: 'Xbox', l3: '左摇杆按下', r3: '右摇杆按下' },
    how: ['短按 Xbox 键开机（别按住：按住是关机）。', '再按顶上 USB-C 口旁边的小配对键，直到 Xbox 灯「快闪」。慢闪是开着、但没在配对。', 'Xbox 手柄只记一个主机：配过电脑或手机的，配不上时先去那边删掉它。'],
  },
  ps: {
    label: 'PS5 / PS4 手柄', layout: 'ps',
    names: { south: '×', east: '○', west: '□', north: '△', lb: 'L1', rb: 'R1', lt: 'L2', rt: 'R2', select: 'Create', start: 'Options', home: 'PS', l3: 'L3', r3: 'R3' },
    how: ['同时按住 Create 和 PS 键，直到灯条快闪。', 'PS 手柄官方没在鸭子上实测过，配上以后先在下面把每个键按一遍看对不对。'],
  },
  switch: {
    label: 'Switch Pro 类（含 G50 Pro）', layout: 'switch',
    names: { south: 'B', east: 'A', west: 'Y', north: 'X', lb: 'L', rb: 'R', lt: 'ZL', rt: 'ZR', select: '−', start: '+', home: 'Home', l3: '左摇杆按下', r3: '右摇杆按下' },
    how: ['G50 Pro：先把背后的模式拨到 S 档（Switch 模式）。', '按住顶上 USB-C 口旁边的小 Sync 键，直到几个小灯来回跑。'],
  },
  generic: {
    label: '其他手柄', layout: 'xbox',
    names: { south: '下', east: '右', west: '左', north: '上', lb: 'L1', rb: 'R1', lt: 'L2', rt: 'R2', select: 'Select', start: 'Start', home: 'Home', l3: 'L3', r3: 'R3' },
    how: ['照说明书进配对状态（灯一般会快闪）。', '有模式开关的（安卓 / iOS / Switch / X-input），先选 Switch 或 X-input：安卓模式常常认不准键。'],
  },
};
const kindOf = (k) => KINDS[k] || KINDS.generic;

// Key functions: follow the fork's padd on the duck (review 3, appendix 1). role is the position: south = the bottom one of the four right-hand keys.
// does = physical gamepad; web = where pressing on the web gamepad picture differs from the physical one (same if not given); off = why this key is grayed out on the web picture
const ROLLER_NOTE = '（轮滑模式另有作用）';
const FUNCS = [
  { role: 'ls', group: 'main', name: () => '左摇杆', does: '走路：前后、左右平移 · 头模式：头转向、抬低头 · 身体模式：起伏下蹲',
    web: '网页上：以按下的那一点为中心拖（不是按哪儿就到哪儿），松手回中' },
  { role: 'rs', group: 'main', name: () => '右摇杆', does: '走路：转弯 · 头模式：脖子俯仰、头歪 · 身体模式：前后左右倾' },
  { role: 'start', group: 'main', does: '软着 / 坐着：上力、直线回站姿；站着保持：开始走（策略开）；在走：停下回站姿（策略关）',
    web: '网页上：按现在的姿势挑一样做（图下面写着现在按会做什么）；坐着时走「站起来」（sitstand 起身，更柔和——实体手柄是直线回站姿）；在走时是先停再回站姿（不渐变）' },
  { role: 'select', group: 'main', does: '短按（松手时）：卸力 = 急停，鸭子会软下来，扶住；再按 Start 站回来', danger: '按住 2 秒：坐下、卸力、关机',
    web: '网页上：按下就卸力（跟顶上「卸力」同一条路，什么时候都能按）；网页上不做关机' },
  { role: 'dd', group: 'main', name: () => '十字下', does: '坐下 ↔ 站起', bind: 'dpad_down', web: '网页上：按坐没坐着走「坐下」或「站起来」' },
  { role: 'south', group: 'skill', does: '低头捡（ground pick）', bind: 'a' },
  { role: 'west', group: 'skill', does: '前滚翻；按住连着滚', bind: 'x' },
  { role: 'lb', group: 'skill', does: '左脚踢', bind: 'lb' },
  { role: 'rb', group: 'skill', does: '右脚踢', bind: 'rb' },
  { role: 'rt', group: 'skill', does: '张嘴，同时嘎一声（站好了就能动嘴，不用在走）' },
  { role: 'lt', group: 'skill', does: '张嘴；按住时一直「wheee」' },
  { role: 'north', group: 'mode', does: '头模式：摇杆改成管头，身体不动；再按回到走路', imu: true },
  { role: 'east', group: 'mode', does: '身体模式：摇杆让站着的身体倾斜、下蹲；再按回到走路' },
  { role: 'dr', group: 'other', name: () => '十字右', does: '重启全部舵机（过载保护跳了用）：先全身卸力再重启，之后按 Start 站回来',
    web: '网页上：一样，按一下就重启、不用确认（照官方）。鸭子会先软下来，扶住' },
  { role: 'du', group: 'other', name: () => '十字上', does: '按住 3 秒：切换走路 / 轮滑（装了轮子才用）。叫一声是走路、两声是轮滑；先回站姿再换',
    web: '网页上：也要按住 3 秒，没到 3 秒松手不切；没装轮滑模型主程序会拒' },
  { role: 'dl', group: 'other', name: () => '十字左', does: '走路模式没作用（轮滑模式：按住 2 秒切换 A 键是蹲还是转）', off: `走路模式没作用${ROLLER_NOTE}` },
  { role: 'home', group: 'other', does: '鸭子上没有作用（手柄自己的开关机键）', off: '没有作用' },
  { role: 'l3', group: 'other', does: '走路模式没作用（轮滑模式：倒地时轮滑起身测试）', off: `走路模式没作用${ROLLER_NOTE}` },
  { role: 'r3', group: 'other', does: '没有作用', off: '没有作用' },
];
const FUNC = Object.fromEntries(FUNCS.map((f) => [f.role, f]));
// Keys on the picture by position → backend names
const ROLE_BIND = { south: 'a', west: 'x', lb: 'lb', rb: 'rb', dd: 'dpad_down' };
const ROLE_HELD = { lt: 'lt', rt: 'rt', west: 'x' };
const MODE_CN = { drive: '走路', head: '头模式', body: '身体模式' };
const DRIVE_CN = { walk: '走路', roller: '轮滑' };
const SKILL_CN = { ground_pick: '低头捡', roulade: '前滚翻', kick_left: '左脚踢', kick_right: '右脚踢', sit_toggle: '坐下 ↔ 站起', roller_stand: '轮滑起身' };
// Official default key bindings (fork robotd-params lib.rs:175-215, same as the backend's pad_drive.DEFAULT_BIND); robotd's pad.bindings wins if it has been changed
const DEFAULT_BIND = { a: 'ground_pick', x: 'roulade', lb: 'kick_left', rb: 'kick_right', dpad_down: 'sit_toggle' };
const BIND_ROLE = { a: 'south', x: 'west', lb: 'lb', rb: 'rb', dpad_down: 'dd' };

const STEP_ICON = { ok: '✓', fail: '×', bad: '×', doing: '', todo: '', skip: '–', unk: '?' };
const fmtMs = (ms) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} 秒`);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const cx = (...xs) => xs.filter(Boolean).join(' ');

// ---------------- Gamepad diagram (our own drawing) ----------------

// Start / Select are spread a bit apart on the picture (review 3 V3: when adjacent, tapping Start easily hits Relax), and the click area is larger than what is drawn (pd-hit)
const LAYOUT = {
  xbox: { ls: [120, 100], dpad: [158, 152], face: [282, 100], rs: [243, 152], select: [172, 98], start: [228, 98], home: [200, 70] },
  switch: { ls: [120, 100], dpad: [158, 152], face: [282, 100], rs: [243, 152], select: [170, 82], start: [230, 82], home: [214, 112] },
  ps: { ls: [158, 156], dpad: [118, 100], face: [282, 100], rs: [242, 156], select: [150, 64], start: [250, 64], home: [200, 118], touch: true },
};
// Small labels outside each key on the picture: [x, y, text-anchor]. The three shapes are laid out separately so labels do not cover keys or other labels ("hold 3 s · roller skating" on D-pad up is left out: only used with wheels fitted, it is crowded, and the key table has it);
// at phone width only Start / Select are kept (CSS hides the rest), and these two are positioned here as well.
const NOTES = {
  xbox: { select: [170, 119], start: [236, 119], x: [253, 85], dr: [185, 137, 'start'], dd: [158, 190] },
  switch: { select: [170, 64], start: [230, 64], x: [256, 85], dr: [185, 137, 'start'], dd: [158, 190] },
  ps: { select: [135, 68, 'end'], start: [250, 52], x: [250, 85], dr: [147, 104, 'start'], dd: [104, 134] },
};
const HIT_W = 34, HIT_H = 28;      // click area of Start / Select (picture coordinates)
const BODY = 'M128 44C96 44 70 52 56 74C40 100 26 150 22 190C19 222 38 240 60 240C80 240 92 226 104 206C114 190 124 180 144 180L256 180C276 180 286 190 296 206C308 226 320 240 340 240C362 240 381 222 378 190C374 150 360 100 344 74C330 52 304 44 272 44C240 44 226 52 200 52C174 52 160 44 128 44Z';
// Two on each side at the top of the gamepad: the front row are shoulder buttons (LB / RB, against the top edge of the shell), the back row are triggers (LT / RT, higher and further out), with a gap in between
const SHOULDER = { l: { x: 80, w: 72 }, r: { x: 248, w: 72 } };            // y 26–50, the lower half is covered by the shell
const TRIGGER = { l: { x: 62, w: 62 }, r: { x: 276, w: 62 } };             // y -10–18
const SH_Y = 26, SH_H = 24, TR_Y = -10, TR_H = 28;

// ctl: web gamepad controller (from useVpad). With it, keys on the picture can be pressed (doing the same job as the physical gamepad); without it this is only a diagram.
// When mirroring (physical gamepad connected) live holds the physical gamepad's keys and the picture just follows it; when not mirroring, live holds what is pressed on the web page.
function GamepadSvg({ kind, live, seen, ctl, keys }) {
  const k = kindOf(kind);
  const L = LAYOUT[k.layout] || LAYOUT.xbox;
  const b = live?.buttons || {};
  const ax = live?.axes || {};
  const on = (r) => !!b[r];
  const was = (r) => !!(seen && seen.includes(r));
  const N = NOTES[k.layout] || NOTES.xbox;
  // Remappable keys: go by the does pushed in the backend's motion.keys (A / X / LB / RB / D-pad down); fall back to the official defaults if absent
  const does = (role) => {
    const row = keys?.[ROLE_BIND[role]];
    if (row && typeof row.does === 'string' && row.does) return row.does;
    const skill = DEFAULT_BIND[ROLE_BIND[role]];
    return SKILL_CN[skill] || skill || '';
  };
  const noteAt = (text, [x, y, anchor = 'middle'], extra) => html`<text class=${cx('pd-key-note', extra)} x=${x} y=${y} text-anchor=${anchor} aria-hidden="true">${text}</text>`;
  // Pressable keys: role=button + aria-label (key name + function), press / release handed to ctl; unpressable ones get pd-key-off, with the reason in <title> (visible on mouse hover)
  const act = (r) => {
    if (!ctl) return { info: null, props: {} };
    const info = ctl.info(r);
    const f = FUNC[r];
    const name = f?.name ? f.name() : k.names[r] || r;
    const say = `${name}：${info.ok ? info.does : info.why}`;
    return { info, say, props: {
      role: 'button', 'aria-label': say, 'aria-disabled': info.ok ? 'false' : 'true', 'data-role': r,
      onPointerDown: (e) => ctl.down(r, e), onPointerUp: (e) => ctl.up(r, e), onPointerCancel: (e) => ctl.up(r, e),
      onLostPointerCapture: (e) => ctl.up(r, e), onContextMenu: (e) => e.preventDefault(),
    } };
  };
  const tip = (a) => (a.info ? html`<title>${a.say}</title>` : null);
  // When mirroring, the picture shows the physical gamepad: do not draw it gray (presses on the web page are just not accepted, as the title says)
  const offc = (a) => a.info && !a.info.ok && !ctl.mirror && 'pd-key-off';
  const cls = (r, a, extra) => cx('pd-key', on(r) && 'pd-on', was(r) && 'pd-seen', r === 'select' && 'pd-estop',
    a.info && 'pd-press', offc(a), extra);
  const scale = (e) => (e.currentTarget.ownerSVGElement || e.currentTarget).getBoundingClientRect().width / 400;
  const stick = (r, [x0, y0], x, y, press) => {
    const t = 12;
    const a = act(r);
    const side = r === 'ls' ? 'l' : 'r';
    // Stick bases on the picture: a mouse can press anywhere; touch only accepts the transparent HTML over the center cap (pd-ov, below), since touches starting on the base are page scrolls (review O2)
    const sp = ctl ? { role: 'button', 'aria-label': a.say, 'data-role': r, onContextMenu: (e) => e.preventDefault(),
      onPointerDown: (e) => ctl.stickDown(side, e, scale(e) * STICK_TRAVEL, false), onPointerMove: (e) => ctl.stickMove(side, e),
      onPointerUp: (e) => ctl.stickUp(side, e), onPointerCancel: (e) => ctl.stickUp(side, e),
      onLostPointerCapture: (e) => ctl.stickUp(side, e) } : {};
    return html`<g class=${cx('pd-stick', on(press) && 'pd-on', was(r) && 'pd-seen', a.info && 'pd-press', offc(a))} ...${sp}>
      <circle class="pd-stick-base" cx=${x0} cy=${y0} r="27"></circle>
      <circle class="pd-stick-cap" cx=${x0 + clamp(x || 0, -1, 1) * t} cy=${y0 + clamp(y || 0, -1, 1) * t} r="17"></circle>
      <text x=${x0} y=${y0 + 44} class="pd-cap">${r === 'ls' ? 'L' : 'R'}</text>
      ${ctl ? html`<circle class="pd-hit" cx=${x0} cy=${y0} r="34"></circle>` : null}${tip(a)}
    </g>`;
  };
  const face = ([x0, y0]) => [['north', 0, -23], ['south', 0, 23], ['west', -23, 0], ['east', 23, 0]].map(([r, dx, dy]) => {
    const a = act(r);
    return html`<g class=${cls(r, a)} ...${a.props}>
      <circle cx=${x0 + dx} cy=${y0 + dy} r="11.5"></circle>
      <text x=${x0 + dx} y=${y0 + dy + 4}>${k.names[r]}</text>${tip(a)}</g>`;
  });
  const dkey = (r, x, y, w, h) => {
    const a = act(r);
    return html`<g class=${cls(r, a)} ...${a.props}><rect x=${x} y=${y} width=${w} height=${h} rx="3"></rect>${tip(a)}</g>`;
  };
  const dpad = ([x0, y0]) => html`<g>
    ${dkey('du', x0 - 7, y0 - 25, 14, 18)}${dkey('dd', x0 - 7, y0 + 7, 14, 18)}
    ${dkey('dl', x0 - 25, y0 - 7, 18, 14)}${dkey('dr', x0 + 7, y0 - 7, 18, 14)}
    <rect class="pd-dpad-mid" x=${x0 - 7} y=${y0 - 7} width="14" height="14"></rect></g>`;
  // Triggers: fill from the bottom up as deep as pressed; digital triggers (Switch ZL / ZR) are full when pressed
  const trig = (r, side) => {
    const { x, w } = TRIGGER[side];
    const v = clamp(ax[r] ?? (on(r) ? 1 : 0), 0, 1);
    const pressed = on(r) || v > 0.5;
    const a = act(r);
    // Labels: black text with a white outline when not fully pressed (readable on a half-black, half-white background), switching to white text when fully pressed
    return html`<g class=${cx('pd-key', 'pd-trig', pressed && 'pd-on', was(r) && 'pd-seen', v > 0.95 && 'pd-trig-hi', a.info && 'pd-press', offc(a))} ...${a.props}>
      <rect x=${x} y=${TR_Y} width=${w} height=${TR_H} rx="9"></rect>
      ${v > 0.02 ? html`<rect class="pd-fill" x=${x} y=${TR_Y + TR_H * (1 - v)} width=${w} height=${TR_H * v} rx=${v > 0.3 ? 9 : 3}></rect>` : null}
      <text x=${x + w / 2} y=${TR_Y + 18}>${k.names[r]}</text>${tip(a)}</g>`;
  };
  const shoulder = (r, side) => {
    const { x, w } = SHOULDER[side];
    const a = act(r);
    return html`<g class=${cls(r, a, 'pd-shoulder')} ...${a.props}>
      <rect x=${x} y=${SH_Y} width=${w} height=${SH_H} rx="10"></rect>
      <text x=${x + w / 2} y=${SH_Y + 12.5}>${k.names[r]}</text>${tip(a)}</g>`;
  };
  const small = (r, [x0, y0], text) => {
    const a = act(r);
    return html`<g class=${cls(r, a)} ...${a.props}><rect x=${x0 - 13} y=${y0 - 7} width="26" height="14" rx="7"></rect>
      <text x=${x0} y=${y0 + 3.5} class="pd-small">${text}</text>
      ${ctl ? html`<rect class="pd-hit" x=${x0 - HIT_W / 2} y=${y0 - HIT_H / 2} width=${HIT_W} height=${HIT_H} rx="8"></rect>` : null}${tip(a)}</g>`;
  };
  const home = () => {
    const a = act('home');
    return html`<g class=${cls('home', a)} ...${a.props}><circle cx=${L.home[0]} cy=${L.home[1]} r="10"></circle>${tip(a)}</g>`;
  };
  const mode = ctl?.mode && ctl.mode !== 'drive' ? MODE_CN[ctl.mode] : null;
  // Transparent HTML blocks over the picture (review O2): on a phone the whole picture can be used to scroll the page (touch-action: pan-y); only the two stick caps and Select's
  // click area block scrolling (touch-action: none). Whether browsers honor touch-action on SVG child elements has not been verified, so HTML blocks take the touches.
  // Positions are picture coordinates (viewBox 0 -16 400 266) converted to percentages; mouse clicks here work the same
  const pct = (x, y, w, h) => ({ left: `${(x / 400) * 100}%`, top: `${((y + 16) / 266) * 100}%`, width: `${(w / 400) * 100}%`, height: `${(h / 266) * 100}%` });
  const travel = (e) => (e.currentTarget.parentElement.getBoundingClientRect().width / 400) * STICK_TRAVEL;
  const ovStick = (r, [x0, y0]) => {
    const side = r === 'ls' ? 'l' : 'r';
    return html`<span class="pd-ov pd-ov-stick" data-ov=${r} aria-hidden="true" style=${pct(x0 - STICK_GRAB, y0 - STICK_GRAB, STICK_GRAB * 2, STICK_GRAB * 2)}
      onContextMenu=${(e) => e.preventDefault()}
      onPointerDown=${(e) => ctl.stickDown(side, e, travel(e), true)} onPointerMove=${(e) => ctl.stickMove(side, e)}
      onPointerUp=${(e) => ctl.stickUp(side, e)} onPointerCancel=${(e) => ctl.stickUp(side, e)}
      onLostPointerCapture=${(e) => ctl.stickUp(side, e)}></span>`;
  };
  const [sx, sy] = L.select;
  return html`<div class="pd-svgbox">
    <svg class=${cx('pd-svg', ctl && 'pd-svg-live')} viewBox="0 -16 400 266" role=${ctl ? 'group' : 'img'}
    aria-label=${ctl ? `${k.label}：图上的键能按，跟实体手柄一样` : `${k.label}示意图，按下的键会变黑`} onContextMenu=${ctl ? (e) => e.preventDefault() : undefined}>
    ${trig('lt', 'l')}${trig('rt', 'r')}
    ${shoulder('lb', 'l')}${shoulder('rb', 'r')}
    <path class="pd-body" d=${BODY}></path>
    ${L.touch ? html`<rect class="pd-touch" x="168" y="54" width="64" height="40" rx="8"></rect>` : null}
    ${mode ? html`<g class="pd-modetag"><rect x="164" y="22" width="72" height="20" rx="10"></rect><text x="200" y="36">${mode}</text></g>` : null}
    ${stick('ls', L.ls, ax.lx, ax.ly, 'l3')}
    ${stick('rs', L.rs, ax.rx, ax.ry, 'r3')}
    ${dpad(L.dpad)}
    ${face(L.face)}
    ${small('select', L.select, k.names.select.length > 2 ? '' : k.names.select)}
    ${small('start', L.start, k.names.start.length > 2 ? '' : k.names.start)}
    ${home()}
    ${noteAt('张嘴', [56, 7, 'end'])}
    ${noteAt('张嘴·嘎', [344, 7, 'start'])}
    ${noteAt(does('lb'), [74, 41, 'end'])}
    ${noteAt(does('rb'), [326, 41, 'start'])}
    ${noteAt('头模式', [282, 60])}
    ${noteAt('身体模式', [321, 104, 'start'])}
    ${noteAt(does('south'), [321, 129, 'start'])}
    ${noteAt(does('west'), N.x)}
    ${noteAt(`站立 / 模型接管`, N.start, 'pd-key-note-main')}
    ${noteAt('卸力（急停）', N.select, 'pd-key-note-main pd-note-danger')}
    ${noteAt('重启舵机', N.dr)}
    ${noteAt(does('dd'), N.dd)}
    </svg>
    ${ctl ? html`${ovStick('ls', L.ls)}${ovStick('rs', L.rs)}
      <span class="pd-ov pd-ov-select" data-ov="select" aria-hidden="true" style=${pct(sx - HIT_W / 2, sy - HIT_H / 2, HIT_W, HIT_H)}
        onContextMenu=${(e) => e.preventDefault()} onPointerDown=${(e) => ctl.down('select', e)}
        onPointerUp=${(e) => ctl.up('select', e)} onPointerCancel=${(e) => ctl.up('select', e)}></span>` : null}
  </div>`;
}

// ---------------- Key table (by what is printed on this gamepad) ----------------

function KeyName({ f, k }) {
  const n = f.name ? f.name() : k.names[f.role];
  return html`<span class="pd-chip">${n}</span>`;
}

function Legend({ kind, live, bindings, imuHead }) {
  const k = kindOf(kind);
  const b = live?.buttons || {};
  const ax = live?.axes || {};
  const moved = (r) => (r === 'ls' ? Math.hypot(ax.lx || 0, ax.ly || 0) > 0.25 : r === 'rs' ? Math.hypot(ax.rx || 0, ax.ry || 0) > 0.25
    : r === 'lt' || r === 'rt' ? (ax[r] || 0) > 0.3 : false);
  const bound = (f) => {
    const x = f.bind && (bindings || []).find((y) => y.button === f.bind);
    if (!x || !x.overridden) return null;
    return x.skill ? `改成了：${SKILL_CN[x.skill] || x.skill}${x.error ? `（${x.error}）` : ''}` : '这个键被关掉了';
  };
  // Y: when robotd.toml on the duck enables [pad_imu_head_control] and the gamepad has a gyro, the physical gamepad's Y means "the head follows the gamepad's orientation" (fork padd:1044-1093).
  // The browser does not have the gamepad's orientation: Y on the web page is always "stick controls the head" (review 3 V18)
  const does = (f) => {
    if (f.imu && imuHead) return '实体手柄：头跟着手柄的姿态走（手柄要有陀螺仪），摇杆照常走路；再按一下头停在那里';
    return bound(f) || f.does;
  };
  const web = (f) => (f.imu ? (imuHead ? '网页上：摇杆管头（浏览器拿不到手柄的姿态）' : imuHead == null ? '网页上：摇杆管头（实体手柄开没开「陀螺仪管头」没读到）' : null)
    : f.off ? `网页上：灰着（${f.off}）` : f.web);
  const row = (f) => html`<div class=${cx('pd-row', (b[f.role] || moved(f.role)) && 'pd-on')}>
    <${KeyName} f=${f} k=${k} />
    <span class="pd-does">${does(f)}${f.danger ? html`<br /><b class="pd-danger">${f.danger}</b>` : null}
      ${web(f) ? html`<small class="pd-web">${web(f)}</small>` : null}</span>
  </div>`;
  const group = (g) => FUNCS.filter((f) => f.group === g).map(row);
  return html`<div class="pd-legend">
    <div class="pd-legend-h">常用</div>${group('main')}
    <div class="pd-legend-h">技能</div>${group('skill')}
    <div class="pd-legend-h">切换摇杆管什么</div>${group('mode')}
    <details class="pd-other"><summary>其他按键</summary>${group('other')}</details>
    ${k.layout === 'switch' ? html`<p class="pd-note">Switch 类手柄 A 和 B 的位置跟 Xbox 是反的。表里按位置算：右边四个键「最下面那颗」干「A」的活，手柄上印的是 ${k.names.south}。上鸭子还要再核对一次。</p>` : null}
    ${live?.device?.keys_unverified ? html`<p class="pd-note">Xbox 手柄 X、Y 两颗键的位置是推测的，还没在鸭子上核对：按 X 时图上亮的如果是 Y，告诉我们。</p>` : null}
    ${live?.other?.length ? html`<p class="pd-note">还按着表里没有的键：${live.other.join('、')}（padd 不一定认；多半是这款手柄的额外键）</p>` : null}
  </div>`;
}

// ---------------- Page header: model · connected · e-stop active ----------------

function Summary({ pad }) {
  const s = pad?.status || {};
  const live = pad?.live || {};
  const act = s.active;
  const es = pad?.estop || {};
  const name = act ? act.name || '手柄' : live.state === 'attached' ? live.device?.name || '手柄' : null;
  const mark = es.state === 'ok' ? html`<span class="pd-ok">有效 ✓</span>`
    : es.state === 'unknown' ? html`<span class="pd-unk">没核对完 ?</span>` : html`<span class="pd-bad">无效 ×</span>`;
  // Say "gamepad e-stop", kept separate from the top bar's "Relax" (review O7); uses the same status / estop as the gamepad cell in the instrument strip and steps 3 and 4 of the getting-started checklist
  if (!s.known && live.state !== 'attached') return html`<span class="pd-sum">${s.error ? '读不到手柄状态' : '正在读手柄状态…'}${' · 手柄急停'}${mark}</span>`;
  const tail = name ? ' · 已连' : (s.pads || []).length ? ` · 配过 ${(s.pads || []).length} 个，都没连着` : '';
  return html`<span class="pd-sum"><b>${name || '没连手柄'}</b>${tail}${' · 手柄急停'}${mark}</span>`;
}

function EStopChecks({ pad }) {
  const checks = pad?.estop?.checks || [];
  return html`<ul class="pd-checks">${checks.map((c) => {
    const s = c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'unk';
    return html`<li class=${'pd-s-' + s}>
      <span class="pd-mark">${STEP_ICON[s]}</span>
      <span>${c.label}${c.why ? html`<small>${c.why}</small>` : null}</span></li>`;
  })}</ul>`;
}

// ---------------- E-stop test: torque on while held + torque read back as off after release; only both together count as ✓ ----------------

const TEST_STEPS = [
  ['torque', '托着鸭子（或者放在架子上），按手柄 Start 让它站起来'],
  ['press', '短按一下 Select（别按住：按住 2 秒会坐下并关机）'],
  ['readback', '等主程序回读：扭矩关了'],
];
const TEST_AT = { need_torque: 0, armed: 1, pressed: 1, released: 2 };              // which step we are on now
const FAIL_AT = { torque: 0, press: 1, early_off: 1, long: 1, pressed_off: 1, pressed_unknown: 1, readback: 2, relax: 2, studio: 2 };
function testStepState(t, i) {
  if (t.state === 'passed') return 'ok';
  if (t.state === 'failed') {
    const f = FAIL_AT[t.failed_at] ?? 2;
    return i < f ? 'ok' : i === f ? 'fail' : 'todo';
  }
  const at = TEST_AT[t.state];
  if (at === undefined) return 'todo';
  return i < at ? 'ok' : i === at ? 'doing' : 'todo';            // while Select is still held, step 2 is still "in progress" (review 18b)
}

function EStopTest({ pad, op }) {
  const t = pad?.estop_test || { state: 'idle' };
  const ok = pad?.estop?.ok;
  const running = !['idle', 'passed', 'failed'].includes(t.state);
  return html`<section class="board pd-card" id="pd-estop" tabIndex="-1">
    <h3>手柄急停有效吗</h3>
    <${EStopChecks} pad=${pad} />
    <div class="pd-test">
      ${t.state === 'idle' ? html`<p class="pd-small-p">上面几条都 ✓ 只说明「路是通的」。真按一次 Select、看到舵机真卸力了，才算测过。</p>` : null}
      ${t.state !== 'idle' ? html`<ol class="pd-steps">${TEST_STEPS.map(([key, text], i) => {
        const s = testStepState(t, i);
        return html`<li class=${'pd-s-' + s}><span class="pd-mark">${STEP_ICON[s] || ''}</span><span>${text}
          ${key === 'press' && t.state === 'pressed' ? html`<small>按着 ${t.held_s ?? 0} 秒…松开</small>` : null}</span></li>`;
      })}</ol>` : null}
      ${t.why && running ? html`<p class="pd-small-p">${t.why}</p>` : null}
      ${t.held_long && running ? html`<div class="banner warn" role="status"><b>Select 按住太久了，快松开</b><span class="more">按满 2 秒鸭子会坐下并关机，这次也不算。</span></div>` : null}
      ${t.state === 'passed' ? html`<div class="pd-result pd-good">✓ 急停测过了：松开 Select 到回读卸力 ${fmtMs(t.ms)}。<br />再按 Start 让它站回来。</div>` : null}
      ${t.state === 'failed' ? html`<div class="pd-result pd-fail"><b>× 没通过：${t.why || '原因不明'}</b>${t.fix ? html`<br />${t.fix}` : null}</div>` : null}
      <div class="pd-btns">
        ${running
          ? html`<button class="btn-light" onClick=${() => op({ op: 'estop_test', action: 'cancel' })}>不测了</button>`
          : html`<button class="btn-dark" id="pd-estop-btn" disabled=${!ok} title=${ok ? '' : '上面几条都 ✓ 才能测'} onClick=${() => op({ op: 'estop_test', action: 'start' })}>${t.state === 'idle' ? '测一次急停' : '再测一次'}</button>`}
      </div>
    </div>
  </section>`;
}

// ---------------- Pairing wizard ----------------

function bars(rssi) {
  if (typeof rssi !== 'number') return html`<span class="pd-bars" title="这次搜索没看到它的信号（以前配过、记在鸭子上）">—</span>`;
  const n = rssi >= -60 ? 3 : rssi >= -75 ? 2 : 1;
  return html`<span class="pd-bars" title=${`信号 ${rssi} dBm`}>${[1, 2, 3].map((i) => html`<i class=${i <= n ? 'pd-on' : ''} style=${{ height: `${4 + i * 3}px` }}></i>`)}</span>`;
}

function DeviceList({ devices, picked, busy, op }) {
  const [showAll, setShowAll] = useState(false);
  const pads = devices.filter((d) => d.pad);
  const others = devices.filter((d) => !d.pad);
  const row = (d) => html`<div class=${cx('pd-dev', picked === d.mac && 'pd-sel')} key=${d.mac}>
    ${bars(d.rssi)}
    <span class="pd-dev-name"><b>${d.name || '（还没拿到名字）'}</b><small class="num">${d.mac}${d.kind_label ? ` · ${d.kind_label}` : ''}</small></span>
    <span class="pd-tags">
      ${d.pad ? html`<span class="pd-tag">手柄</span>` : html`<span class="pd-tag pd-gray">${d.why_not || '不像手柄'}</span>`}
      ${d.paired ? html`<span class="pd-tag pd-gray">配过</span>` : null}
      ${d.connected ? html`<span class="pd-tag pd-gray">连着</span>` : null}
    </span>
    <button class=${d.pad ? 'btn-dark' : 'btn-light'} disabled=${busy} title=${busy ? '还在搜索：等它搜完再点' : ''} onClick=${() => op({ op: 'pair', mac: d.mac }, 180000)}>配这个</button>
  </div>`;
  return html`<div class="pd-devs">
    ${pads.length ? pads.map(row) : html`<div class="pd-empty">还没搜到手柄。手柄的灯在快闪吗？</div>`}
    ${others.length ? html`<button class="pd-link" onClick=${() => setShowAll(!showAll)}>${showAll ? '收起' : `还有 ${others.length} 个不像手柄的蓝牙设备`}</button>` : null}
    ${showAll ? others.map(row) : null}
  </div>`;
}

function Wizard({ w, op, kind, setKind, onClose }) {
  const st = w?.state || 'idle';
  const busy = st === 'running';
  const k = kindOf(kind);
  const steps = w?.steps || [];
  const err = w?.error;
  const cfgBusy = w?.configd_busy_s;
  return html`<section class="board pd-card pd-wizard" id="pd-wizard" tabIndex="-1">
    <div class="pd-card-h"><h3>配对新手柄</h3>
      ${!busy ? html`<button class="pd-link" onClick=${onClose}>关掉</button>` : null}</div>
    ${cfgBusy ? html`<div class="banner warn" role="status"><b>configd 上一次配对还没做完</b><span class="more">它停不了，大约还要 ${cfgBusy} 秒，做完之前不能再配。</span></div>` : null}
    ${st === 'idle' ? html`
      <div class="pd-kinds" role="radiogroup" aria-label="手柄类型">
        ${Object.entries(KINDS).map(([key, x]) => html`<button role="radio" aria-checked=${kind === key} class=${kind === key ? 'pd-on' : ''} onClick=${() => setKind(key)}>${x.label}</button>`)}
      </div>
      <ol class="pd-how">${k.how.map((s) => html`<li>${s}</li>`)}</ol>
      <div class="pd-btns">
        <button class="btn-dark" disabled=${!!cfgBusy} onClick=${() => op({ op: 'scan', seconds: 12 }, 30000)}>灯在快闪了，开始搜索</button>
        <button class="btn-light" disabled=${!!cfgBusy} title="照官方 robotctl pad pair：不列清单，自动挑正在配对状态的那个" onClick=${() => op({ op: 'pair' }, 180000)}>直接配（自动挑）</button>
      </div>
      <p class="pd-small-p">搜索大约 12 秒。搜索时鸭子的 WiFi 可能会卡一下（蓝牙和 WiFi 是同一颗芯片）。鸭子在走的时候不能搜。</p>
      ${w.helper_available === false ? html`<p class="pd-small-p"><b>没有新版小助手</b>：这块板配新手柄要先停 btd，Studio 做不了，可能配不上。重装小助手，或者在鸭子上运行 <code>sudo robotctl pad pair</code>。</p>`
        : w.helper_available === true ? html`<p class="pd-small-p">配对走新版小助手：官方 <code>robotctl pad pair</code>，会先停 btd、重开蓝牙。</p>`
        : html`<p class="pd-small-p">新版小助手会用官方 <code>robotctl pad pair</code>（先停 btd、重开蓝牙）。这块板没有它时可能配不上：重装小助手，或者在鸭子上运行 <code>sudo robotctl pad pair</code>。</p>`}
      ` : html`
      <ol class="pd-steps">${steps.map((s) => html`<li class=${'pd-s-' + s.state}>
        <span class="pd-mark">${STEP_ICON[s.state] || ''}</span>
        <span>${s.label}${s.note ? html`<small>${s.note}</small>` : null}</span></li>`)}</ol>
      ${w.phase === 'scan' || w.phase === 'pick' ? html`<${DeviceList} devices=${w.devices || []} picked=${w.picked} busy=${busy} op=${op} />` : null}
      ${err ? html`<div class="pd-err" role="alert">
        <b>${err.msg}</b>
        ${err.fix ? html`<div>怎么办：${err.fix}</div>` : null}
        ${err.raw ? html`<details><summary>原文</summary><code>${err.raw}</code></details>` : null}
      </div>` : null}
      ${w.phase === 'keys' && st !== 'done' ? html`<p class="pd-small-p">把每个键按一遍、两个摇杆各推一圈。上面手柄图上按过的键会变成浅色描边。</p>` : null}
      ${st === 'done' ? html`<div class="pd-result pd-good">✓ 配好了：${w.result_name || '手柄'}。重启鸭子以后它会自己回连（开手柄就行）。</div>` : null}
      <div class="pd-btns">
        ${busy ? html`<button class="btn-light" onClick=${() => op({ op: 'cancel' })}>停下</button>` : null}
        ${w.phase === 'pick' && !busy ? html`<button class="btn-light" disabled=${!!cfgBusy} onClick=${() => op({ op: 'scan', seconds: 12 }, 30000)}>再搜一次</button>` : null}
        ${w.phase === 'keys' && st !== 'done' ? html`<button class="btn-dark" onClick=${() => op({ op: 'keys_done' })}>按键都对，完成</button>` : null}
        ${st === 'failed' ? html`<button class="btn-dark" disabled=${!!cfgBusy} onClick=${() => op(w.retry || { op: 'scan', seconds: 12 }, 180000)}>重试</button>` : null}
        ${!busy ? html`<button class="btn-light" onClick=${() => op({ op: 'wizard_reset' })}>${st === 'done' ? '好的' : '从头来'}</button>` : null}
      </div>
      ${w.via ? html`<p class="pd-small-p">配对走的是：${w.via}${w.elapsed_s != null ? ` · 用了 ${w.elapsed_s.toFixed(0)} 秒` : ''}</p>` : null}`}
  </section>`;
}

// ---------------- Paired gamepads ----------------

function KnownPads({ pad, op }) {
  const pads = pad?.status?.pads || [];
  if (!pads.length) return null;
  const forget = (p) => {
    const lines = [`忘掉 ${p.name || p.mac}？`, ''];
    if (p.connected) lines.push('它现在正连着：忘掉以后它马上断开，鸭子会立刻停下（我们改过的 padd 还会让它坐下）。先扶好鸭子。', '');
    lines.push('只删鸭子这边。手柄自己还记着鸭子，以后要再配，得先让手柄重新进配对状态。');
    if (window.confirm(lines.join('\n'))) op({ op: 'forget', mac: p.mac });
  };
  return html`<section class="board pd-card" id="pd-known" tabIndex="-1">
    <h3>鸭子记着的手柄</h3>
    ${pads.map((p) => html`<div class="pd-dev" key=${p.mac}>
      <span class=${cx('pd-dot', p.connected && 'pd-on')}></span>
      <span class="pd-dev-name"><b>${p.name || '（没名字）'}</b><small class="num">${p.mac}</small></span>
      <span class="pd-tags">
        <span class="pd-tag pd-gray">${p.connected ? '连着' : '没连'}</span>
        ${p.trusted ? null : html`<span class="pd-tag pd-warn" title="现在能用，但重启鸭子以后不会自己回连">没信任</span>`}
      </span>
      ${p.trusted ? null : html`<button class="btn-light" onClick=${() => op({ op: 'pair', mac: p.mac }, 180000)}>修复</button>`}
      <button class="btn-light" onClick=${() => forget(p)}>忘掉</button>
    </div>`)}
    <p class="pd-small-p">「没连」的：打开手柄就会自己连上（不用再配）。</p>
  </section>`;
}

// ---------------- Web gamepad: one controller shared by the keys on the picture, the two stick areas and the keyboard ----------------

const TEXT_TYPES = ['text', 'password', 'search', 'email', 'number', 'tel', 'url'];
const typing = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'
  || (el.tagName === 'INPUT' && TEXT_TYPES.includes((el.type || 'text').toLowerCase())));
// The keyboard only drives walking (head / body modes do not respond: full head deflection is 2.5 rad by default, so one press of W would slam the head to its limit, review 3 V2). Arrow keys were dropped:
// without a toggle, someone pressing the arrow keys to scroll the page would make the duck walk
const KEYMAP = { KeyW: ['ly', -1], KeyS: ['ly', 1], KeyA: ['lx', -1], KeyD: ['lx', 1], KeyQ: ['rx', -1], KeyE: ['rx', 1] };
const ZERO = { lx: 0, ly: 0, rx: 0, ry: 0 };
const dz = (v) => (Math.abs(v) < DZ ? 0 : v);
const MIRROR_WHY = '实体手柄连着：图只跟着它显示，网页上按的不收（Select 照样能卸力）';

// Readout: the same formulas as the backend's pad_drive.sticks_to_intent (the backend is authoritative; this only shows people what is being sent now)
function readout(mode, f, lim, head) {
  const LX = dz(f.lx), LY = -dz(f.ly), RX = dz(f.rx), RY = -dz(f.ry);
  if (mode === 'head') return [['脖子', RY * head, 'rad'], ['低抬头', -LY * head, 'rad'], ['转头', -LX * head, 'rad'], ['歪头', RX * head, 'rad']];
  if (mode === 'body') {
    return [['高低', LY * (LY >= 0 ? 1.0 : 2.5), 'cm'], ['前后倾', clamp(RY * 0.2618, -0.26, 0.26), 'rad'],
      ['左右倾', clamp(RX * 0.2618, -0.26, 0.26), 'rad']];
  }
  return [['前后', LY * lim.v, 'm/s'], ['平移', -LX * lim.v, 'm/s'], ['转弯', -RX * lim.w, 'rad/s']];
}

// All web gamepad state lives here: sticks (tracked separately by pointerId so two can be dragged at once), keyboard, held keys (LT / RT / X), mode (walk / head / body).
// The keys on the picture (GamepadSvg), the two sticks on the picture and the keyboard all go through it, and behave the same whichever is used. Rules (review 3):
// - Sticks are relative: centered on the point where pressed (V2), 0.1 dead zone; sent only while held (10 Hz), and one stop is sent on returning to center.
// - The keyboard only works while the remote-control area (gamepad picture) has focus; losing focus releases everything (V2).
// - Switching pages, window losing focus, page going to the background, scrolling out of the gamepad section, a physical gamepad connecting, someone else taking over: release everything (sticks to 0, keys released, exit head / body mode).
//   Leaving the gamepad section (padActivity.active going from true to false) also sends drive {on:false}, and coming back sends drive {open} (overview re-layout review O1).
// - Touch mis-tap protection (review O2): sticks only accept presses that start in the grab area near the cap on the picture; presses within 0.5 s of a page scroll are ignored; keys on the picture only count as pressed after 0.12 s without moving.
//   Select is the exception: it relaxes on press and can be pressed at any time (3 V3).
// - The backend is authoritative for the mode (V6): when the backend exits the mode on this page's behalf (relax, policy stopped, timeout…), the page goes back to walking, and a held stick must be released and pressed again.
function useVpad({ pad, st, link }) {
  const v = pad?.virtual || {};
  const m = pad?.motion || {};
  const mirror = !!v.mirror;
  const d = v.driver;
  const locked = !!(d && !d.mine);
  const usable = !!pad?.motion && !mirror && !locked;
  const [axes, setAxes] = useState(ZERO);
  const [pressedView, setPressedView] = useState(() => new Set());
  const [heldView, setHeldView] = useState(() => new Set());
  const [mode, setModeView] = useState('drive');
  const [msg, setMsg] = useState(null);
  const [kbOn, setKbOn] = useState(false);
  const R = useRef(null);
  if (!R.current) {
    R.current = { sticks: { l: { pid: null, x: 0, y: 0 }, r: { pid: null, x: 0, y: 0 } }, kb: new Map(), held: new Set(),
      pressed: new Set(), mode: 'drive', modeAt: 0, lastNonZero: false, timer: null, keysTimer: null, alive: true };
  }
  const S = R.current;
  Object.assign(S, { usable, pad, st, mirror, locked, d });

  const say = (text, bad = true) => setMsg(text ? { text, bad, at: performance.now() } : null);
  const cmd = (args, t = 2000) => link.cmd('pad.op', args, t);
  const whyNot = () => (S.mirror ? MIRROR_WHY : S.locked ? `${S.d?.by || '另一个页面'}正在遥控：等它松手，或者点下面的「接管」`
    : '还没收到鸭子的状态');
  const press = (role) => { S.pressed.add(role); setPressedView(new Set(S.pressed)); };
  const unpress = (role) => { if (S.pressed.delete(role)) setPressedView(new Set(S.pressed)); };

  // ---- Sticks ----
  const frame = () => {
    const f = { lx: S.sticks.l.x, ly: S.sticks.l.y, rx: S.sticks.r.x, ry: S.sticks.r.y };
    if (S.mode === 'drive') for (const code of S.kb.keys()) { const [axis, val] = KEYMAP[code]; f[axis] = val; }
    return f;
  };
  const isZero = (f) => Math.max(Math.abs(f.lx), Math.abs(f.ly), Math.abs(f.rx), Math.abs(f.ry)) < DZ;
  const r3 = (x) => Math.round(x * 1000) / 1000 || 0;
  const send = async () => {
    const f = frame();
    if (isZero(f) || !S.usable) { kick(); return; }
    S.lastNonZero = true;
    const sentMode = S.mode;
    const r = await cmd({ op: 'sticks', mode: sentMode, lx: r3(f.lx), ly: r3(f.ly), rx: r3(f.rx), ry: r3(f.ry), seq: nextSeq() });
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || '没发出去'); return; }
    const dd = r.data || {};
    if (dd.dropped && dd.mode && dd.mode !== S.mode && sentMode === S.mode && performance.now() - S.modeAt > MODE_GRACE_MS) adopt(dd.mode, dd.dropped);
    else if (dd.dropped && S.mode !== 'drive') say(dd.dropped, false);
  };
  // With input: send a frame immediately, then one every 100 ms (not at the pointermove rate while dragging); send one stop at the moment it returns to center
  function kick() {
    const f = frame();
    setAxes(f);
    if (isZero(f) || !S.usable) {
      if (S.timer) { clearInterval(S.timer); S.timer = null; }
      if (S.lastNonZero) { S.lastNonZero = false; cmd({ op: 'stop', seq: nextSeq() }); }
      return;
    }
    if (!S.timer) { S.timer = setInterval(send, SEND_MS); send(); }
  }
  const voidSticks = () => {
    for (const side of ['l', 'r']) { const s = S.sticks[side]; if (s.pid != null) s.void = true; s.x = 0; s.y = 0; }
    S.kb.clear();
    kick();
  };
  const focusZone = (e) => {
    const z = e.currentTarget?.closest && e.currentTarget.closest('.pd-zone');
    if (z && document.activeElement !== z) z.focus({ preventScroll: true });
  };
  const stickDown = (side, e, k, center = true) => {
    if (e.button > 0) return;
    // Touch: only accept presses starting at the center cap (presses starting on the base are mostly page scrolls), and ignore presses right after a page scroll (review O2). No preventDefault: let it scroll
    if (isTouch(e) && (!center || scrolledRecently())) return;
    if (!ACT.active) return;                      // the gamepad section is not on screen (switched away, scrolled away): ignore
    e.preventDefault(); focusZone(e);
    if (!S.usable) { say(whyNot(), false); return; }
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers lack it */ }
    S.sticks[side] = { pid: e.pointerId, ox: e.clientX, oy: e.clientY, k: Math.max(8, k), x: 0, y: 0, void: false };
  };
  const stickMove = (side, e) => {
    const s = S.sticks[side];
    if (s.pid !== e.pointerId || s.void) return;
    let x = (e.clientX - s.ox) / s.k, y = (e.clientY - s.oy) / s.k;
    const n = Math.hypot(x, y);
    if (n > 1) { x /= n; y /= n; }
    s.x = x; s.y = y;
    kick();
  };
  const stickUp = (side, e) => {
    if (S.sticks[side].pid !== e.pointerId) return;
    S.sticks[side] = { pid: null, x: 0, y: 0 };
    kick();
  };

  // ---- Held keys: LT / RT / X (keys channel, review 3 V4) ----
  const sendKeys = async (down = []) => {
    const r = await cmd({ op: 'keys', held: [...S.held], down, seq: nextSeq() });
    if (!S.alive) return;
    const drop = (k) => { S.held.delete(k); unpress(k === 'x' ? 'west' : k); };
    if (!r.ok) { down.forEach(drop); say(r.reason || r.error || '没按上'); }
    else if (r.data?.ended?.length) { r.data.ended.forEach(drop); say('后端把按着的键停了（卸力、被接管或者断了一下）：松开再按', false); }
    setHeldView(new Set(S.held));
    if (!S.held.size && S.keysTimer) { clearInterval(S.keysTimer); S.keysTimer = null; }
  };
  const holdKey = (k) => {
    if (!ACT.active) return;
    S.held.add(k); setHeldView(new Set(S.held));
    sendKeys([k]);
    if (!S.keysTimer) S.keysTimer = setInterval(() => { if (S.held.size) sendKeys(); }, HOLD_MS);
  };
  const releaseKey = (k) => { if (!S.held.delete(k)) return; setHeldView(new Set(S.held)); sendKeys(); };

  // ---- Mode: Y / B ----
  function adopt(serverMode, why) {
    S.mode = serverMode; S.modeAt = performance.now(); setModeView(serverMode);
    voidSticks();
    if (why) say(why, false);
    // Follow the backend back to walking: reply "walking" so the backend knows the page saw it, and only then can Y / B enter again (review R3: an "enter mode" arriving before that reply
    // is treated by the backend as a heartbeat that has not seen the exit, and is not accepted)
    if (serverMode === 'drive') cmd({ op: 'mode', mode: 'drive', seq: nextSeq() });
  }
  const setMode = async (next, why) => {
    if (next === S.mode) return;
    S.mode = next; S.modeAt = performance.now(); setModeView(next);
    voidSticks();                                   // mode change: held sticks are voided and must be released and pressed again (otherwise a hand pushing the head would turn into walking on a mode change)
    const r = await cmd({ op: 'mode', mode: next, seq: nextSeq() });
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || '没切过去'); if (S.mode === next && next !== 'drive') adopt('drive'); return; }
    if (r.data?.dropped && r.data.mode && r.data.mode !== S.mode) { adopt(r.data.mode, r.data.dropped); return; }
    if (r.data?.note) say(r.data.note, false);
    else if (why) say(`回到走路（${why}）`, false);
  };
  // Heartbeats carry hb:true: the backend only renews "still here" and will not reopen a mode it already exited on the page's behalf (relax, policy stopped, timeout…); if they differ, follow the backend back to walking (review R3)
  const beatMode = async () => {
    const r = await cmd({ op: 'mode', mode: S.mode, hb: true });
    if (S.alive && r.ok && r.data?.mode && r.data.mode !== S.mode && performance.now() - S.modeAt > MODE_GRACE_MS) adopt(r.data.mode, r.data.dropped);
  };

  // ---- Release everything ----
  function releaseAll(why, keep) {
    if (S.touchOff) { const f = S.touchOff; S.touchOff = null; f(); }     // a touch that has not yet counted as a press: void it
    if (S.driveTimer) { clearTimeout(S.driveTimer); S.driveTimer = null; }  // D-pad up not yet held for 3 s: do not switch
    S.kb.clear();
    for (const side of ['l', 'r']) { const s = S.sticks[side]; if (s.pid != null) s.void = true; s.x = 0; s.y = 0; }
    if (S.held.size) { S.held.clear(); setHeldView(new Set()); sendKeys(); }
    S.pressed.clear(); if (keep) S.pressed.add(keep); setPressedView(new Set(S.pressed));
    if (S.mode !== 'drive') setMode('drive', why);   // the backend clears head / body (3 V1, item 2)
    kick();
  }

  // ---- Keys on the picture pressed / released ----
  const estop = (fromCard) => {
    // Select on the picture = e-stop: sent on press (do not wait for release: on touch, the browser fires pointercancel as soon as the finger moves), same path as "Relax" at the top (review 3 V3).
    // The "Relax" button at the top of the remote-control card (review O3) also goes through here
    const p = link.cmd('relax', {}, 7000);
    if (fromCard === true) releaseAll('按了遥控卡上的「卸力」');
    else releaseAll('按了图上的 Select（卸力）', 'select');
    p.then((r) => { if (S.alive) say(r.ok ? '✓ 卸力发出去了：鸭子会软下来，扶住' : (r.reason || r.error || '卸力没发出去：用手柄 − 或关电源'), !r.ok); });
  };
  const startKey = async () => {
    const s = S.pad?.motion?.start;
    if (!s) return;
    const tilt = S.st?.tilt_deg;
    if (s.op === 'stand' && typeof tilt === 'number' && tilt > 30
      && !window.confirm(`它现在是躺着的（倾斜 ${Math.round(tilt)}°）。站起来时腿会突然用力：确定托好了吗？`)) { unpress('start'); return; }
    const r = await cmd({ op: 'start', expect: s.op, src: 'svg' }, 10000);
    if (S.alive) say(r.ok ? `✓ Start → ${s.label}${r.data?.reason ? `：${r.data.reason}` : ''}` : (r.reason || r.error || '没成功'), !r.ok);
  };
  // D-pad right: as in the official version, sent on one press (the main program relaxes the whole body first); like Select, release everything here first
  const rebootKey = async () => {
    releaseAll('按了十字右（重启舵机：主程序会先卸力）', 'dr');
    const r = await cmd({ op: 'reboot', src: 'svg' }, 7000);
    if (S.alive) say(r.ok ? '✓ 重启舵机发出去了：鸭子会先软下来，扶住；好了按 Start 站回来' : (r.reason || r.error || '没成功'), !r.ok);
  };
  // D-pad up: sent only after being held for 3 s; releasing before 3 s (up) or releasing everything (releaseAll) means no switch
  const driveHold = () => {
    const target = S.pad?.motion?.drive_mode?.target;
    clearTimeout(S.driveTimer);
    say(`按住 3 秒切到${DRIVE_CN[target] || '另一个模式'}…`, false);
    S.driveTimer = setTimeout(async () => {
      S.driveTimer = null;
      if (!S.pressed.has('du')) return;
      const r = await cmd({ op: 'drive_mode', expect: target, src: 'svg' }, 10000);
      if (!S.alive) return;
      if (!r.ok) { say(r.reason || r.error || '没成功'); return; }
      say(r.data?.reason ? `✓ ${r.data.reason}` : `✓ 切到${DRIVE_CN[target]}：它会叫${target === 'roller' ? '两' : '一'}声、回站姿再换`, false);
    }, DRIVE_HOLD_MS);
  };
  const oneShot = async (role) => {
    const key = ROLE_BIND[role];
    const row = S.pad?.motion?.keys?.[key];
    const r = await cmd({ op: 'key', key, src: 'svg' }, 10000);
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || '没成功'); if (key === 'x') { releaseKey('x'); unpress('west'); } } else say(`✓ ${row ? row.does : key}`, false);
  };
  const info = (role) => {
    if (role === 'select') return { ok: true, does: '卸力（急停）：按下就卸，鸭子会软下来，扶住' };
    const f = FUNC[role];
    if (f?.off) return { ok: false, why: f.off };
    const mm = S.pad?.motion || {};
    if (role === 'dr') {                          // like Select, can be pressed even while someone else is remote controlling (emergency: the backend ignores who has the wheel)
      const x = mm.reboot;
      if (!x || S.mirror) return { ok: false, why: whyNot() };
      return x.ok ? { ok: true, does: x.does } : { ok: false, why: x.why };
    }
    if (role === 'start') {
      const s = mm.start;
      if (!s || S.mirror) return { ok: false, why: whyNot() };
      if (S.locked && s.op !== 'walk_stop') return { ok: false, why: whyNot() };   // anyone can press "Stop (stand still)"
      return s.ok ? { ok: true, does: `现在按：${s.label}` } : { ok: false, why: s.why };
    }
    if (!S.usable) return { ok: false, why: whyNot() };
    if (role === 'du') {
      const x = mm.drive_mode;
      if (!x) return { ok: false, why: '还没收到现在是走路还是轮滑' };
      return x.ok ? { ok: true, does: x.does } : { ok: false, why: x.why };
    }
    if (role === 'north') return { ok: true, does: S.mode === 'head' ? '回到走路' : '头模式：摇杆管头（网页上没有手柄的姿态）' };
    if (role === 'east') return { ok: true, does: S.mode === 'body' ? '回到走路' : '身体模式：摇杆让身体倾斜、下蹲' };
    if (role === 'ls' || role === 'rs') {
      const t = { drive: ['走路：前后、平移', '转弯'], head: ['转头、低抬头', '脖子俯仰、歪头'], body: ['起伏、下蹲', '前后左右倾'] }[S.mode];
      return { ok: true, does: `拖动：${t[role === 'ls' ? 0 : 1]}` };
    }
    if (role === 'lt' || role === 'rt') {
      const t = mm.triggers || {};
      if (!t.ok) return { ok: false, why: t.why || '现在不能按' };
      return { ok: true, does: (role === 'lt' ? '按住：张嘴、一直 wheee' : '按住：张嘴；按下嘎一声') + (t.note ? `（${t.note}）` : '') };
    }
    const bk = ROLE_BIND[role];
    if (bk) {
      const row = mm.keys?.[bk];
      if (!row) return { ok: false, why: '还没收到这个键绑了什么' };
      return row.ok ? { ok: true, does: row.does + (role === 'west' ? '（按住连着滚）' : '') } : { ok: false, why: row.why };
    }
    return { ok: false, why: '没有作用' };
  };
  const fire = (role) => {
    if (!ACT.active) return;                      // the gamepad section is not on screen: ignore (Select does not come through here)
    const x = info(role);
    if (!x.ok) { say(x.why, false); return; }
    press(role);
    if (role === 'start') { startKey(); return; }
    if (role === 'dr') { rebootKey(); return; }
    if (role === 'du') { driveHold(); return; }
    if (role === 'north' || role === 'east') { const want = role === 'north' ? 'head' : 'body'; setMode(S.mode === want ? 'drive' : want); return; }
    if (ROLE_HELD[role]) holdKey(ROLE_HELD[role]);
    if (ROLE_BIND[role]) oneShot(role);
  };
  const down = (role, e) => {
    if (e.button > 0) return;
    if (role === 'select') {
      // Select on the picture = e-stop: relaxes on press, can be pressed at any time (3 V3); its click area has its own touch-action:none (review O2)
      e.preventDefault();
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers lack it */ }
      estop(); return;
    }
    if (isTouch(e)) {
      // Touch: only counts as pressed after 0.12 s without moving and without the browser canceling; releasing within 0.12 s = a tap (press then release). Ignored right after a page scroll (review O2)
      if (scrolledRecently() || !ACT.active) return;
      if (S.touchOff) S.touchOff();
      S.touchOff = touchHold(e, { press: () => fire(role), release: () => up(role), tap: () => { fire(role); up(role); } });
      return;
    }
    e.preventDefault(); focusZone(e);
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers lack it */ }
    fire(role);
  };
  const up = (role) => {
    if (!S.pressed.has(role)) return;
    unpress(role);
    if (ROLE_HELD[role]) releaseKey(ROLE_HELD[role]);
    if (role === 'du' && S.driveTimer) { clearTimeout(S.driveTimer); S.driveTimer = null; say('没按够 3 秒：没切（官方要按住 3 秒，防止误按）', false); }
  };

  // ---- Keyboard: only while the remote-control area has focus (review 3 V2) ----
  const zoneProps = {
    tabIndex: 0,
    onKeyDown: (e) => {
      const km = KEYMAP[e.code];
      if (!km || typing(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
      // Focus stays inside after the remote-control area is scrolled out with the wheel: keys held then were released long ago (left the gamepad section), and repeated keydowns from holding are not accepted either (review O1)
      if (!ACT.active) return;
      e.preventDefault();
      // The browser's auto-repeat only renews "already held" keys: after any "release everything" (scrolling out of the gamepad section, losing focus, relax…) a real press is required;
      // if the hand is still holding W when scrolling back or switching back to the window, repeated keydowns must not keep the duck walking (code review C3; sticks also require release and re-press)
      if (e.repeat && !S.kb.has(e.code)) return;
      if (S.mode !== 'drive') { say('头 / 身体模式下键盘不管用，用摇杆（按一下 W 头就会打到底）', false); return; }
      if (!S.usable) { say(whyNot(), false); return; }
      const had = S.kb.has(e.code);
      S.kb.set(e.code, performance.now());
      if (!had) kick();
    },
    onKeyUp: (e) => { if (S.kb.delete(e.code)) kick(); },
    onFocus: () => setKbOn(true),
    onBlur: (e) => {
      const to = e.relatedTarget;
      if (to && to.closest && to.closest('.pd-zone')) return;        // moving between the two remote-control areas: not a loss of focus
      setKbOn(false);
      if (S.kb.size) { S.kb.clear(); kick(); }
    },
  };

  useEffect(() => {
    S.alive = true;
    // Entering the gamepad section (this section came on screen): only clears "left", does not take the wheel (review 3 V5). Send once the connection is up; check again right before sending that we are still here
    const open = () => link.whenOpen().then(() => { if (S.alive && ACT.active) cmd({ op: 'drive', open: true, seq: nextSeq() }, 3000); });
    // Leaving the gamepad section (switching pages, scrolling away, going to the background): release everything, the backend records "left", and late frames are all dropped (review O1)
    const leave = (why) => {
      releaseAll(why);
      link.cmd('pad.op', { op: 'drive', on: false, seq: nextSeq(), why }, 3000);
    };
    const offAct = padActivity.subscribe(({ active, changed, routeChanged }, why) => {
      // A remote subpage keeps the recording lease, but never a held stick or key.
      if (routeChanged && !changed) releaseAll(why);
      if (!changed) return;
      if (active) open(); else leave(why);
    });
    if (ACT.active) open();
    // After a reconnect it is a new connection, which the backend assumes is "not in the gamepad section" (review O1): if still here, open again
    const offLink = link.on((m) => { if (m.t === '_status' && m.status === 'open' && ACT.active) open(); });
    const blur = () => releaseAll('窗口失焦');
    const vis = () => { if (document.visibilityState !== 'visible') releaseAll('页面转到后台'); };
    // Space is Relax at the top (intercepted by app.js in the capture phase), Esc: release everything while at it
    const keyCap = (e) => { if (e.code === 'Space' || e.code === 'Escape') releaseAll(e.code === 'Space' ? '按了空格（卸力）' : '按了 Esc'); };
    // Stuck keys: on a Mac, a W released while Cmd is held never gets its keyup; it can also be lost while a dialog is open. While held the browser keeps repeating keydown, so 1 s without one counts as released
    const stale = setInterval(() => {
      const now = performance.now();
      let changed = false;
      for (const [c, at] of S.kb) if (now - at > KEY_STALE_MS) { S.kb.delete(c); changed = true; }
      if (changed) kick();
    }, 200);
    const beat = setInterval(() => { if (S.mode !== 'drive' && document.visibilityState === 'visible') beatMode(); }, MODE_HB_MS);
    window.addEventListener('blur', blur);
    document.addEventListener('visibilitychange', vis);
    window.addEventListener('keydown', keyCap, true);
    return () => {
      releaseAll('手柄这一块卸载了');
      S.alive = false;
      offAct(); offLink();
      clearInterval(stale); clearInterval(beat); clearInterval(S.timer); clearInterval(S.keysTimer);
      S.timer = S.keysTimer = null;
      window.removeEventListener('blur', blur);
      document.removeEventListener('visibilitychange', vis);
      window.removeEventListener('keydown', keyCap, true);
      link.cmd('pad.op', { op: 'drive', on: false, seq: nextSeq() }, 3000);   // leaving: the backend records "left" and drops all late frames
    };
  }, []);
  // A physical gamepad connected, someone else took the wheel, state cannot be read: release everything
  useEffect(() => { if (!usable) releaseAll(mirror ? '实体手柄连上了' : locked ? '别的页面在遥控' : '读不到状态'); }, [usable]);
  // The backend is authoritative for the mode: when the backend exits on this page's behalf (relax, policy stopped, heartbeat timeout…), the page goes back to walking
  useEffect(() => {
    const sm = v.mode;
    if (!sm || sm === S.mode || performance.now() - S.modeAt < MODE_GRACE_MS) return;
    adopt(sm, v.mode_exit ? `退出了${MODE_CN[S.mode]}：${v.mode_exit.why}` : null);
  });
  useEffect(() => {
    if (!msg) return undefined;
    const t = setTimeout(() => setMsg(null), msg.bad ? 8000 : 4000);
    return () => clearTimeout(t);
  }, [msg]);

  const liveWeb = { buttons: Object.fromEntries([...pressedView].map((r) => [r, true])),
    axes: { ...axes, lt: heldView.has('lt') ? 1 : 0, rt: heldView.has('rt') ? 1 : 0 } };
  return { mode, axes, msg, kbOn, mirror, locked, usable, liveWeb, zoneProps, info, down, up, stickDown, stickMove, stickUp, say,
    chooseMode: next => { if (ACT.active && S.usable && ['drive','head','body'].includes(next)) setMode(next); },
    release: () => releaseAll('点了摇杆归中'),
    estop: () => estop(true) };
}

// A hold-to-act button: send action_start on press, action_hold every 0.15 s while held, and on release / pointer leaving / losing focus / page going to the background / scrolling out of the gamepad section
// send action_stop. On touch, it only counts as pressed after 0.12 s without moving and without the browser canceling (starting a page scroll), and is ignored right after a page scroll (review O2:
// the first step of "kick once with each foot" is robot.do, and a finger starting here to scroll down the page used to trigger a kick on contact); releasing within 0.12 s does nothing (hold to act)
function HoldButton({ item, link, onErr, lit, locked, quiet }) {
  const [held, setHeld] = useState(false);
  const timer = useRef(null);
  const alive = useRef(false);
  const pend = useRef(null);
  const seq = useRef(0);
  const stop = useCallback(() => {
    if (pend.current) { const f = pend.current; pend.current = null; f(); }
    if (!alive.current) return;
    alive.current = false; setHeld(false);
    clearInterval(timer.current); timer.current = null;
    link.cmd('pad.op', { op: 'action_stop' }, 3000);
  }, []);
  const down = (e) => {
    if (e.button > 0) return;
    if (isTouch(e)) {
      if (scrolledRecently() || !ACT.active || !item.ok || locked) return;
      if (pend.current) pend.current();
      pend.current = touchHold(e, { press: () => { pend.current = null; start(); }, release: stop });
      return;
    }
    start(e);
  };
  // Each press gets a sequence number (press): if it is released and pressed again before the acknowledgment comes back, the first acknowledgment is void; otherwise an extra timer would be set and keep sending
  // action_hold until the page closes, and the backend's "stop after 0.45 s without renewal" safeguard would no longer work for this page (code review C7). The backend also uses this number to accept keepalives
  const start = async (e) => {
    if (e) { e.preventDefault(); try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers lack it */ } }
    if (alive.current || !item.ok || locked || !ACT.active) return;
    const my = ++seq.current;
    alive.current = true; setHeld(true);
    const r = await link.cmd('pad.op', { op: 'action_start', id: item.id, press: my }, 4000);
    if (my !== seq.current) return;                       // pressed again while waiting for the acknowledgment: leave it to the newer press, do nothing here
    if (!r.ok) { onErr(r.reason || r.error || '没做成'); alive.current = false; setHeld(false); return; }
    if (!alive.current) { link.cmd('pad.op', { op: 'action_stop' }, 3000); return; }      // released before the acknowledgment arrived
    clearInterval(timer.current);
    const iv = setInterval(async () => {
      if (my !== seq.current || !alive.current) { clearInterval(iv); return; }
      const h = await link.cmd('pad.op', { op: 'action_hold', press: my }, 2000);
      if (my === seq.current && alive.current && h.ok && h.data && h.data.running === null) {
        alive.current = false; setHeld(false); clearInterval(iv);
      }
    }, HOLD_MS);
    timer.current = iv;
  };
  useEffect(() => {
    const vis = () => { if (document.visibilityState !== 'visible') stop(); };
    // Scrolled out of the gamepad section or switched to another page: stop immediately (the overview stays mounted and is never unmounted; hiding does not release pointer capture either: review O1)
    const offAct = padActivity.subscribe(({ active, changed, routeChanged }) => { if (routeChanged || changed && !active) stop(); });
    window.addEventListener('blur', stop);
    document.addEventListener('visibilitychange', vis);
    return () => { offAct(); window.removeEventListener('blur', stop); document.removeEventListener('visibilitychange', vis); stop(); };
  }, []);
  return html`<button class=${cx('pd-act', 'pd-hold', held && 'pd-held', lit && 'pd-lit')} disabled=${!item.ok || locked}
    title=${item.ok ? `按住才做，松手就停：${item.text}` : item.why}
    onPointerDown=${down} onPointerUp=${stop} onPointerCancel=${stop} onLostPointerCapture=${stop}
    onKeyDown=${(e) => { if (e.key === 'Enter' && !e.repeat) start(); }} onKeyUp=${(e) => { if (e.key === 'Enter') stop(); }}
    onContextMenu=${(e) => e.preventDefault()}>
    <b>${item.name}</b><small>${quiet ? '' : item.ok ? item.text : item.why}</small></button>`;
}

// The line under the picture: what Start would do now, what the sticks control, the result of the last press; plus one line of full explanation
function VpadBar({ vp, pad }) {
  const m = pad?.motion || {};
  const v = pad?.virtual || {};
  const lim = v.limits || {};
  const s = m.start;
  if (vp.mirror) return html`<p class="pd-small-p pd-vbar">${MIRROR_WHY}。</p>`;
  return html`<div class="pd-vbar">
    <span>Start 现在会：<b>${s ? (s.ok ? s.label : '不能按') : '—'}</b>${s && !s.ok ? html`<small>（${s.why}）</small>` : null}</span>
    <span>摇杆管：<b>${MODE_CN[vp.mode]}</b>${vp.mode !== 'drive' && pad?.motion && !m.driving ? html`<small>（策略没在跑，摇杆不会让它动）</small>` : null}</span>
    <span class="pd-kbhint">${vp.kbOn ? '键盘已接上' : '点一下图才接键盘'}</span>
    ${vp.msg ? html`<span class=${cx('pd-vmsg', vp.msg.bad && 'pd-bad-t')} role=${vp.msg.bad ? 'alert' : 'status'}>${vp.msg.text}</span>` : null}
  </div>
  <p class="pd-small-p pd-vbar-hint">键盘：点一下手柄图，W / S 前后、A / D 平移、Q / E 转弯（头 / 身体模式下键盘不管用）；空格 = 卸力（急停，整页都管用）· Esc = 全部松开（停下但不卸力）。满杆 ${(lim.v ?? 0.3).toFixed(2)} 米/秒、${(lim.w ?? 1.5).toFixed(1)} 弧度/秒（${lim.src || '官方默认'}），头满杆 ${(v.inputs?.head ?? 2.5).toFixed(1)} rad（${v.inputs?.src || '官方默认'}）。鸭子还没「准备好走」时摇杆不动：先点「站起来」、再点「开始走」（或者按图上的 Start）。</p>`;
}

function Remote({ st, pad, link, vp, section }) {
  const [err, setErr] = useState(null);
  const [busyUntil, setBusyUntil] = useState(0);
  const [busyPose, setBusyPose] = useState(null);
  const v = pad?.virtual || {};
  const m = pad?.motion || {};
  const live = pad?.live || {};
  const d = v.driver;
  const locked = !!(d && !d.mine);
  const mirror = !!v.mirror;
  const lb = live.buttons || {};
  const lax = live.axes || {};
  const binds = Object.fromEntries((pad?.bindings || []).map((b) => [b.button, b.skill]));
  const bindOf = (btn) => (btn in binds ? binds[btn] : DEFAULT_BIND[btn]);
  const physSkill = (name) => mirror && Object.entries(BIND_ROLE).some(([btn, role]) => bindOf(btn) === name && lb[role]);
  const now = performance.now();
  const busy = now < busyUntil && m.posture === busyPose;
  useEffect(() => { if (busyUntil) { const t = setTimeout(() => setBusyUntil(0), Math.max(0, busyUntil - performance.now())); return () => clearTimeout(t); } return undefined; }, [busyUntil]);

  const op = async (args, timeout = 8000) => {
    setErr(null);
    const r = await link.cmd('pad.op', args, timeout);
    if (!r.ok) setErr(r.reason || r.error || '没成功');
    return r;
  };
  const takeOver = async () => {
    if (!window.confirm(`现在是 ${d?.by || '另一个页面'} 在遥控。接管以后，那边的摇杆和动作马上就不管用了。接管吗？`)) return;
    await op({ op: 'drive', on: true, force: true, seq: nextSeq() });
  };

  const press = async (b) => {
    if (b.op === 'stand' && typeof st?.tilt_deg === 'number' && st.tilt_deg > 30
      && !window.confirm(`它现在是躺着的（倾斜 ${Math.round(st.tilt_deg)}°）。站起来时腿会突然用力：确定托好了吗？`)) return;
    setBusyUntil(performance.now() + BUSY_MS); setBusyPose(m.posture);
    const r = await op({ op: b.op }, 10000);
    if (!r.ok) setBusyUntil(0);
  };
  const B = m.buttons || {};
  const mainBtn = (b, extra) => {
    if (!b) return null;
    const lit = mirror && ((b.op === 'stand' || b.op === 'walk' || b.op === 'walk_stop') ? lb.start : b.op === 'sit' ? (bindOf('dpad_down') === 'sit_toggle' && lb.dd) : false);
    // Anyone can click "Stop (stand still)", without queueing (review 2 I1); the other buttons gray out while someone else is pushing the sticks or the previous one has not replied yet
    const off = !b.ok || (b.op !== 'walk_stop' && (locked || busy));
    return html`<button class=${cx('pd-big', extra, lit && 'pd-lit')} disabled=${off} onClick=${() => press(b)}
      title=${b.ok ? (b.call ? `发给主程序：${b.call}` : '') : b.why}>
      <b>${b.label}</b><small>${busy ? '等它回话…' : b.ok ? (b.note || '') : section ? '' : b.why}</small></button>`;
  };
  const last = m.last;
  const la = m.last_action;
  // When a whole group of buttons is disabled for the same reason: state the reason once instead of repeating it on every button
  const common = (items) => {
    const xs = items || [];
    return xs.length && xs.every((x) => !x.ok && x.why === xs[0].why) ? xs[0].why : null;
  };
  const skWhy = common(m.skills), actWhy = common(m.actions), comboWhy = common(m.combos);
  const why = (text) => (text ? html`<p class="pd-small-p pd-why">${text}</p>` : null);
  return html`<section class="board pd-card pd-remote" id="pd-remote" tabIndex="-1" hidden=${section === 'gamepad'}>
    <div class="pd-card-h">
      <h3>遥控</h3>
      <span class="pd-pose">现在：<b>${m.posture_cn || '—'}</b></span>
      <span class="sv-spacer"></span>
      ${d ? html`<span class=${cx('pd-tag', !d.mine && 'pd-warn')}>${d.mine ? '这个页面在遥控' : `${d.by || '另一个页面'}正在遥控`}</span>` : null}
      ${locked ? html`<button class="btn-light" onClick=${takeOver}>接管</button>` : null}
      ${!section ? html`<button class="estop pd-relax" title="全部卸力，请扶住。" onClick=${(e) => { e.currentTarget.blur(); vp.estop(); }}>卸力</button>` : null}
    </div>
    ${!section ? html`<p class="pd-small-p pd-leave-note">滚出这一块、切到别的页，按着的摇杆和动作都会马上松开。</p>` : null}
    ${err ? html`<div class="banner bad" role="alert"><b>${err}</b><a href="#" onClick=${(e) => { e.preventDefault(); setErr(null); }}>知道了</a></div>` : null}
    ${locked ? html`<div class="banner warn" role="status"><b>${d.by || '另一个页面'}正在推摇杆 / 做动作</b><span class="more">同一时间只让一个页面开，免得两边抢。它松手 6 秒后这里就能用；急着用就点「接管」。「停下（站好）」、图上的 Select（卸力）随时能点。</span></div>` : null}
    ${v.pad_unknown ? html`<div class="banner warn" role="status"><b>认不出有没有实体手柄</b><span class="more">${v.pad_unknown}。如果手柄其实连着，图上的摇杆会被它盖掉。</span></div>` : null}
    ${mirror ? html`<div class="banner warn" role="status"><b>实体手柄已连接，网页摇杆只显示。</b><span class="more">站、走、坐、技能与叫声仍可使用。</span></div>` : null}

    <div class="pd-sec">
      <div class="pd-sec-h">站、走、坐</div>
      ${m.posture === 'servo_session' || st?.posture === 'servo_session' ? html`<p class="pd-small-p pd-why">调舵机中：主程序停着，站走都不能用（点顶上的「交还主程序」才回来）。</p>` : null}
      <div class="pd-bigs">${mainBtn(B.stand)}${mainBtn(B.walk, B.walk?.op === 'walk_stop' ? 'pd-stopbtn' : '')}${mainBtn(B.sit)}</div>
      ${last ? html`<p class=${cx('pd-small-p', !last.ok && 'pd-bad-t')}>${last.ok ? '✓' : '×'} ${last.what}${last.by ? `（${last.by}）` : ''}：${last.ok ? (last.reason || '主程序收到了') : last.reason}</p>` : null}
    </div>

    ${section ? html`<a class="pd-audio-link" href="#/sensing/audio">监听与音乐 ›</a>` : html`<${AudioInteraction} pad=${pad} link=${link} activity=${padActivity} />`}
    <${MotionStudio} pad=${pad} link=${link} activity=${padActivity} view=${section === 'control' ? 'compact' : 'full'} />

    <div class="pd-sec" hidden=${section === 'recording'}>
      <div class="pd-sec-h">技能<small>点一下做一次（官方的动作）</small></div>
      ${why(skWhy || actWhy || comboWhy)}
      <div class="pd-acts">
        ${(m.skills || []).map((s) => html`<button class=${cx('pd-act', physSkill(s.name) && 'pd-lit')} disabled=${!s.ok || locked}
          title=${s.ok ? `robot.do ${s.name}` : s.why} onClick=${() => op({ op: 'skill', name: s.name })}>
          <b>${s.label}</b><small>${section || s.ok || skWhy ? '' : s.why}</small></button>`)}
        ${!(m.skills || []).length ? html`<p class="pd-small-p">${m.skills_why || '这只鸭子没配技能'}</p>` : null}
      </div>
      <div class="pd-sec-h">叫一声</div>
      <div class="pd-acts pd-sounds">
        ${(section ? (m.sounds || []).slice(0,1) : m.sounds || []).map((s) => html`<button class=${cx('pd-act', 'pd-chipbtn', mirror && s.tag === 'chirp' && (lax.rt || 0) > 0.3 && 'pd-lit')} disabled=${!s.ok}
          title=${s.ok ? `robot.sound ${s.tag}` : s.why} onClick=${() => op({ op: 'sound', tag: s.tag })}>${s.label}</button>`)}
      </div>
      <div class="pd-sec-h">动作<small>按住才做，松手就停</small></div>
      ${section ? null : why(actWhy)}
      <div class="pd-acts">
        ${(m.actions || []).map((a) => html`<${HoldButton} key=${a.id} item=${a} link=${link} onErr=${setErr} locked=${locked} quiet=${!!section || !!actWhy}
          lit=${mirror && a.id === 'mouth' && Math.max(lax.lt || 0, lax.rt || 0) > 0.1} />`)}
      </div>
      <details class="pd-other-actions"><summary>组合动作与其他声音</summary>
      <div class="pd-sec-h">组合动作<small>按住才做，松手停止</small></div>
      ${!section && comboWhy && comboWhy !== actWhy ? why(comboWhy) : null}
      <div class="pd-acts">
        ${(m.combos || []).map((a) => html`<${HoldButton} key=${a.id} item=${a} link=${link} onErr=${setErr} locked=${locked} quiet=${!!section || !!comboWhy} />`)}
      </div>
      ${section ? html`<div class="pd-acts pd-sounds">${(m.sounds || []).slice(1).map(s => html`<button class="pd-act pd-chipbtn" disabled=${!s.ok} title=${s.why || s.label} onClick=${() => op({op:'sound',tag:s.tag})}>${s.label}</button>`)}</div>` : null}
      </details>
      ${m.running ? html`<p class="pd-small-p">正在做「${m.running.name}」：第 ${m.running.step + 1} / ${m.running.steps} 步${m.running.by ? `（${m.running.by}）` : ''}</p>`
        : la ? html`<p class=${cx('pd-small-p', !la.ok && 'pd-bad-t')}>「${la.name}」${la.result}</p>` : null}
    </div>
    <details class="pd-control-help"><summary>操作与停止方式</summary><p class="pd-small-p">松手会归中；“停下（站好）”关闭行走策略；“卸力”关闭舵机扭矩。离开遥控区、失焦或转后台会松开输入，头与身体回正。断线后由后端超时停止，不自动续动。</p><p class="pd-small-p">触屏从空白处滑动可滚页；按住动作后松手停止。空格卸力，Esc 全部松开。</p></details>
  </section>`;
}

// ---------------- 3D duck in the gamepad section (user, 10-18: "left of the sticks there should be a 3D view and on the right the stick controls, so you can see the duck's state while controlling it") ----------------
// On wide screens the left side has two cards, 3D and camera, stacked, and the whole column sticks below the instrument strip when there is room; on narrow screens they come in order above the remote control.
// Same as the overview stage: live joints, no zoom, one finger scrolls the page and two fingers rotate (duck3d's pageScroll, touch-action is also set in CSS), no drawing when out of the viewport (duck3d's IO);
// the model geometry is a cache shared within the duck3d module and is never loaded twice. Stale data is desaturated (via class, not a style string: code review C6).
// A line of small text below: posture · battery · current forward-back / strafe / turn (same formulas and same stick state as the remote-control card's readout)
function PadDuck({ st, pad, vp, live }) {
  const canvasRef = useRef(null);
  const duckRef = useRef(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const d = new Duck3D(canvasRef.current, { view: 'front34', centerX: 0.5, centerY: 0.5, fill: 0.86, pageScroll: true });
    duckRef.current = d;
    d.load('model/').catch((e) => setErr(`3D 模型没加载：${e.message}`));
    return () => d.dispose();
  }, []);
  useEffect(() => {
    if (!duckRef.current || !st) return;
    duckRef.current.setJoints(st.joints);
    duckRef.current.setGravity(st.gravity);
  }, [st]);
  const v = pad?.virtual || {};
  const ax = pad?.live?.axes || {};
  const mirror = vp.mirror;
  const f = mirror ? { lx: ax.lx || 0, ly: ax.ly || 0, rx: ax.rx || 0, ry: ax.ry || 0 } : vp.axes;
  const rows = readout(mirror ? 'drive' : vp.mode, f, v.limits || { v: 0.3, w: 1.5 }, v.inputs?.head ?? 2.5);
  const pct = st?.battery?.pct;
  const old = !live || st?.joints_age_ms == null || st.joints_age_ms > 1000;
  return html`<section class="board pd-card pd-3d" aria-label="鸭子现在的姿态">
    <div class="pd-3d-stage"><canvas ref=${canvasRef} class=${old ? 'stage-stale' : ''}></canvas>
      ${err ? html`<span class="sv-loading">${err}</span>` : null}</div>
    <p class="pd-small-p pd-3d-line num">${pad?.motion?.posture_cn || '—'} · 电量 ${typeof pct === 'number' ? `${Math.round(pct)}%` : '—'}
      ${rows.map(([n, val, u]) => ` · ${n} ${(Math.round(val * 100) / 100 || 0).toFixed(2)} ${u}`).join('')}${old ? ' · 数据旧了' : ''}</p>
  </section>`;
}

// ---------------- Gamepad section (inside the overview, just scroll down) ----------------

const TOPBAR_PX = 56;       // sticky top bar (styles.css .topbar): subtracted when checking "is it on screen" (review O1, O3)
const TABBAR_PX = 83;       // phone bottom tab bar (styles.css .tabbar)

function ConsoleSticks({ vp, pad, shown, kind }) {
  const axes = shown?.axes || vp.axes;
  const labels = {drive:[['左右平移','前后移动'],['左右转向','—']],head:[['转头','低抬头'],['歪头','脖子俯仰']],body:[['—','起伏下蹲'],['左右倾','前后倾']]}[vp.mode];
  const lim = {v:.3,w:1.5,...pad?.virtual?.limits};
  const output = readout(vp.mode, axes, lim, pad?.virtual?.inputs?.head ?? 2.5);
  return html`<div class=${cx('pd-zone','console-drive-zone',vp.kbOn && 'pd-kb')} ...${vp.zoneProps} aria-label="网页遥控区，W S A D Q E 控制行走">
    <div class="console-mode-tabs">${[['drive','走路'],['head','头部'],['body','身体']].map(([mode,label]) => html`<button type="button" class=${vp.mode === mode ? 'active' : ''} aria-pressed=${vp.mode === mode} disabled=${!vp.usable} onClick=${() => vp.chooseMode(mode)}>${label}</button>`)}</div>
    <div class="console-sticks">${['l','r'].map((side,index) => html`<div class="console-stick-unit"><strong>${index ? '右摇杆' : '左摇杆'}</strong><span>${labels[index].filter(v=>v!=='—').join(' · ')}</span><div class="console-stick-well"><i class="console-stick-cross"></i><button type="button" class="console-stick-thumb" aria-label=${`${index ? '右':'左'}摇杆，按住并拖动`} disabled=${!vp.usable}
      style=${{transform:`translate(${(axes[side+'x'] || 0)*32}px,${(axes[side+'y'] || 0)*32}px)`}}
      onPointerDown=${e=>vp.stickDown(side,e,40,true)} onPointerMove=${e=>vp.stickMove(side,e)} onPointerUp=${e=>vp.stickUp(side,e)} onPointerCancel=${e=>vp.stickUp(side,e)} onLostPointerCapture=${e=>vp.stickUp(side,e)} onContextMenu=${e=>e.preventDefault()}>${index ? '↻' : '✥'}</button></div></div>`)}</div>
    <p class="console-stick-hint">按住圆心拖动，松手归中</p><div class="console-stick-output">${output.map(([name,value,unit])=>html`<span>${name} <b>${value.toFixed(2)}</b> ${unit}</span>`)}</div>
    <div class="console-stick-footer"><button type="button" class="btn-light" onClick=${()=>vp.release()}>摇杆归中</button>${vp.msg ? html`<span class=${vp.msg.bad ? 'pd-bad-t' : ''} role="status">${vp.msg.text}</span>` : null}</div>
    <details class="pd-control-help"><summary>键盘、全部按键与控制幅度</summary><${VpadBar} vp=${vp} pad=${pad} /><${GamepadSvg} kind=${kind} live=${shown} ctl=${vp} keys=${pad?.motion?.keys} /></details>
  </div>`;
}

// Overview re-layout (plan §1.2, review O11): the order is page header → gamepad picture (key table collapsed by default) + remote control → pairing wizard / e-stop test / paired gamepads.
// There is no separate gamepad page anymore: #/pad is an anchor on the overview (app.js scrolls here on open, id="pad-block").
// This section stays mounted, and "present or not" comes from padActivity (route + page visible + this section in the viewport): watch, drive open / off and release-everything all hang on it
export function PadPage({ st, pad, link, api, previewActive = false, live: duckLive = true, section = null }) {
  const [msg, setMsg] = useState(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [kind, setKind] = useState('xbox');
  const [visualFits, setVisualFits] = useState(true);
  const rootRef = useRef(null);
  const s = pad?.status || {};
  const live = pad?.live || {};
  const w = pad?.wizard || { state: 'idle' };
  const showWizard = wizardOpen || w.state !== 'idle';
  // A recognized model takes priority; with no gamepad connected yet, draw the model chosen in the wizard (Xbox by default)
  const activeKind = live.device?.kind || s.active?.kind || kind;
  const vp = useVpad({ pad, st, link });
  // What the picture shows: physical gamepad connected (mirroring) or the key test during pairing → the physical gamepad's; otherwise → what is pressed on the web page
  const shown = vp.mirror || live.state === 'attached' ? live : vp.liveWeb;

  // When the top hint wraps, judge by its actual height too; if it does not fit, scroll with the page rather than pinning the camera off screen.
  useEffect(() => {
    const left = rootRef.current?.querySelector('.pd-left');
    if (!left) return;
    let frame = null;
    const measure = () => {
      frame = null;
      const height = left.getBoundingClientRect().height;
      const top = parseFloat(getComputedStyle(left).top);
      if (height > 0 && Number.isFinite(top)) setVisualFits(height + top + 16 <= innerHeight);
    };
    const schedule = () => { if (frame == null) frame = requestAnimationFrame(measure); };
    const observer = new ResizeObserver(schedule);
    for (const el of [left, document.querySelector('.band'), document.querySelector('.sticky-bar')]) {
      if (el) observer.observe(el);
    }
    window.addEventListener('resize', schedule);
    schedule();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); window.removeEventListener('resize', schedule); };
  }, []);

  const op = useCallback(async (args, timeout = 15000) => {
    const r = await link.cmd('pad.op', args, timeout);
    if (!r.ok) setMsg(r.reason || r.error || '没成功'); else setMsg(null);
    return r;
  }, []);

  // Whether this section is in the viewport (minus the sticky top bar and the phone bottom bar). When hidden (switched to another page) IO also reports "not intersecting", but one frame late:
  // on the route side, app.js has already computed it synchronously in hashchange (padActivity.setRoute)
  // Watch the original blocks: page header, gamepad picture, remote control, and the pairing / e-stop test cards below; the 3D card does not count (just watching the duck is not being in the gamepad section: user 10-18, item three)
  useEffect(() => {
    let io = null;
    const mq = window.matchMedia('(max-width: 700px)');
    const seen = new Map();
    const build = () => {
      if (io) io.disconnect();
      seen.clear();
      io = new IntersectionObserver((es) => {
        for (const e of es) seen.set(e.target, e.isIntersecting);
        padActivity.setInView([...seen.values()].some(Boolean));
      }, { rootMargin: `-${TOPBAR_PX}px 0px -${mq.matches ? TABBAR_PX : 0}px 0px`, threshold: 0 });
      const root = rootRef.current;
      if (root) for (const el of root.querySelectorAll(':scope > .pd-head, .pd-live, #pd-remote, :scope > .pd-more')) io.observe(el);
    };
    build();
    if (mq.addEventListener) mq.addEventListener('change', build);
    return () => {
      if (io) io.disconnect();
      if (mq.removeEventListener) mq.removeEventListener('change', build);
      padActivity.setInView(false);
    };
  }, []);

  // Tell the backend "someone is looking at the gamepad section": only then does the backend subscribe to the padd side channel (padd only opens the gamepad device once subscribed, so it costs nothing normally).
  // Only opened after 0.3 s continuously on screen (do not open the side channel on a quick scroll past: review O1); resent immediately after a reconnect
  useEffect(() => {
    let since = ACT.active ? performance.now() : null;
    let t0 = null;
    const tick = () => {
      if (ACT.active && since != null && performance.now() - since >= WATCH_SETTLE_MS) link.cmd('pad.op', { op: 'watch' }, 3000);
    };
    const arm = () => { clearTimeout(t0); t0 = setTimeout(tick, WATCH_SETTLE_MS + 20); };
    const offAct = padActivity.subscribe(({ active, changed }) => {
      if (!changed) return;
      if (active) { since = performance.now(); arm(); } else { since = null; clearTimeout(t0); }
    });
    if (since != null) arm();
    const iv = setInterval(tick, WATCH_MS);
    const offLink = link.on((m) => { if (m.t === '_status' && m.status === 'open') arm(); });
    return () => { offAct(); offLink(); clearInterval(iv); clearTimeout(t0); };
  }, []);

  // The getting-started checklist's "Do it" (review O17): open the pairing wizard, scroll to the e-stop test and focus "Test the e-stop once", scroll to paired gamepads / remote control
  useEffect(() => {
    const fn = (what) => {
      if (what === 'wizard') setWizardOpen(true);
      // Wait for the wizard to render (two frames) before scrolling
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const el = document.getElementById({ wizard: 'pd-wizard', estop: 'pd-estop', known: 'pd-known', remote: 'pd-remote' }[what]);
        if (!el) return;
        el.scrollIntoView({ block: 'center' });
        const btn = what === 'estop' ? document.getElementById('pd-estop-btn') : null;
        try { (btn && !btn.disabled ? btn : el).focus({ preventScroll: true }); } catch { /* old browsers */ }
      }));
    };
    GO.add(fn);
    return () => GO.delete(fn);
  }, []);
  useEffect(() => { if (w.state === 'idle' && !wizardOpen) setMsg(null); }, [w.state]);

  const connected = !!s.active || live.state === 'attached';
  const tapTag = { attached: '实时', waiting: '等手柄', absent: '看不到按键', denied: '没权限读按键', error: '读不到按键', connecting: '连接中', off: '' }[live.state] || '';
  return html`<section class=${cx('pd-page', section && 'pd-console')} data-section=${section} id="pad-block" ref=${rootRef} aria-label="手柄">
    ${!section || section === 'gamepad' ? html`<header class="pd-head">
      <h2>${section ? {control:'网页遥控',recording:'录制与动作库',gamepad:'实体手柄'}[section] : '手柄'}</h2>
      ${!section || section === 'gamepad' ? html`<${Summary} pad=${pad} />` : null}
      <span class="sv-spacer"></span>
      ${!showWizard && (!section || section === 'gamepad') ? html`<button class="btn-dark" onClick=${() => setWizardOpen(true)}>${connected ? '再配一个手柄' : '配对手柄'}</button>` : null}
    </header>` : null}
    ${msg ? html`<div class="banner bad" role="alert"><b>${msg}</b><a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>知道了</a></div>` : null}
    ${s.error && live.state !== 'attached' ? html`<div class="banner warn" role="status"><b>读不到 configd 的手柄状态</b><span class="more">${s.error}</span></div>` : null}
    ${s.netpad ? html`<div class="banner warn" role="status"><b>开着 UDP 手柄（netpad）</b><span class="more">这时 padd 只读电脑发来的 UDP 手柄，蓝牙手柄不管用、急停也不走蓝牙手柄。要用蓝牙手柄，先在配置里关掉 [netpad]。</span></div>` : null}
    ${s.known && s.driver && s.driver !== 'active' ? html`<div class="banner bad" role="alert"><b>padd 没在跑（${s.driver}）</b><span class="more">手柄连着也不管用。padd 只在主程序 robotd 跑着时才起。</span></div>` : null}
    ${st?.posture === 'servo_session' ? html`<div class="banner warn" role="status"><b>正在调舵机</b><span class="more">主程序停着，手柄、遥控、站走都不能用；离开舵机页舵机照样保持，点顶上的「交还主程序」才交还。</span></div>` : null}
    <div class="pd-main">
      <section class="board pd-card pd-live">
        <div class="pd-card-h"><h3>${section && section !== 'gamepad' ? '网页摇杆' : live.device?.name || s.active?.name || `${kindOf(activeKind).label}${vp.mirror ? '' : '（网页手柄）'}`}</h3>
          ${!section || section === 'gamepad' ? html`<span class="pd-livetag">${tapTag}${live.last_ms != null && live.state === 'attached' ? ` · ${fmtMs(live.last_ms)}前有输入` : ''}</span>` : null}</div>
        ${section && section !== 'gamepad' ? html`<${ConsoleSticks} vp=${vp} pad=${pad} shown=${shown} kind=${activeKind} />` : html`<div class=${cx('pd-zone', 'pd-svgzone', vp.kbOn && 'pd-kb')} ...${section === 'gamepad' ? {} : vp.zoneProps} aria-label=${section === 'gamepad' ? '实体手柄按键读回，Select 可卸力' : '网页手柄'}>
          <${GamepadSvg} kind=${activeKind} live=${section === 'gamepad' ? live : shown} seen=${w.phase === 'keys' ? w.seen : null} ctl=${section === 'gamepad' ? {...vp,info:role=>role === 'select' ? vp.info(role) : {ok:false,why:'实体输入读回'},down:(role,event)=>{if(role === 'select')vp.down(role,event);},up:role=>{if(role === 'select')vp.up(role);},stickDown:()=>{},stickMove:()=>{},stickUp:()=>{}} : vp} keys=${pad?.motion?.keys} />
        </div>
        ${!section ? html`<${VpadBar} vp=${vp} pad=${pad} />` : null}`}
        ${(!section || section === 'gamepad') && ['error', 'absent', 'denied'].includes(live.state) ? html`<p class="pd-small-p">${live.why || '读不到按键'}</p>` : null}
        ${section === 'gamepad' && !connected && live.state !== 'attached' ? html`<p class="pd-small-p">连接后，按键与摇杆输入将在图中亮起。</p>` : null}
        <details class="pd-legend-box" hidden=${!!section && section !== 'gamepad'}>
          <summary>按键表：每个键做什么</summary>
          <${Legend} kind=${activeKind} live=${shown} bindings=${pad?.bindings} imuHead=${pad?.virtual?.pad_imu_head} />
        </details>
      </section>
      <div class=${cx('pd-left', !visualFits && 'pd-left-overflow')} hidden=${!!section}>${!section ? html`<${PadDuck} st=${st} pad=${pad} vp=${vp} live=${duckLive} />
        <${InlineCamera} api=${api} active=${previewActive} />` : null}</div>
      <${Remote} st=${st} pad=${pad} link=${link} vp=${vp} section=${section} />
    </div>
    <div class="pd-more" hidden=${!!section && section !== 'gamepad'}>
      ${showWizard ? html`<${Wizard} w=${w} op=${op} kind=${kind} setKind=${setKind} onClose=${() => { setWizardOpen(false); op({ op: 'wizard_reset' }); }} />` : null}
      <${EStopTest} pad=${pad} op=${op} />
      <${KnownPads} pad=${pad} op=${op} />
    </div>
  </section>`;
}
