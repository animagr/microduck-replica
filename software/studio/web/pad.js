// Gamepad block (merged into the overview, just scroll down: overview rearrangement plan §1.2): see the gamepad's current state, pair a new gamepad (visual wizard), test the e-stop,
// web gamepad (the keys on the picture can be pressed), web remote (stand up / start walking / sit down, sticks, skills, actions). #/pad is an anchor on the overview; opening it scrolls to this block.
//
// All data comes from {t:'pad', …} pushed by the backend studio/pad.py (10 Hz while this block is on screen, 1 Hz otherwise).
// Commands sent by the page are all link.cmd('pad.op', {op, …}):
//   watch                 I'm looking at the gamepad block (every 2 s after being on screen for 0.3 s continuously; if the backend hears nothing for 6 s it closes the padd tap and slows polling)
//   refresh / scan {seconds} / pair {mac?} / cancel / forget {mac} / keys_done / wizard_reset   pairing wizard
//   estop_test {action}   e-stop test: start / cancel
//   drive {open, seq}     entered the gamepad area (only clears "left", doesn't take the wheel); drive {on:false, seq} leave; drive {on:true, force} take over
//                         "in the gamepad area" = route is / or /pad ∧ page visible ∧ this block is in the viewport (review O1, see padActivity below)
//   sticks {mode,lx,ly,rx,ry,seq}  web gamepad sticks (the two on the picture): -1..1, x right and y down positive; the backend uses padd's formula
//                         to convert to robot.move / head / pose; only sent while held (10 Hz); seq is the page's incrementing sequence number
//   stop {seq}            release: walk mode sends 0 once, head mode returns the head to center, body mode returns the body to center. The backend drops any frame older than stop
//   mode {mode, seq}      Y / B on the picture: drive / head / body
//   mode {mode, hb:true}  in head/body mode report "still here" once per second (the backend exits after 3 s of silence); renews only, never enters: if the backend has already exited it replies dropped
//   keys {held, down, seq}   held keys LT / RT / X: sent on press and release, reported every 0.15 s while held (the backend treats 0.45 s of silence, 0.3 s for X, as release)
//   key {key, src:'svg'}  the moment A / X / LB / RB / D-pad down on the picture is pressed (acts per pad.bindings)
//   start {expect, src:'svg'}   Start on the picture: rejected if what the backend picks differs from expect (state just changed)
//   reboot {src:'svg'}    D-pad right on the picture: reboot all servos (as official: one press sends it, no confirmation; the main program first releases torque on the whole body)
//   drive_mode {expect, src:'svg'}   D-pad up on the picture held for 3 s (timed on the page): switch walk / roller; expect is the mode to switch to
//   stand / walk / walk_stop / sit         stand up / start walking / stop (stand) / sit down (the backend re-judges by posture)
//   skill {name} / sound {tag}             official skills (robot.do) / a chirp (robot.sound)
//   action_start {id, press} / action_hold {press} / action_stop   actions and combo actions: only performed while held (saying "still held" every 0.15 s), stop on release;
//                         press is this press's sequence number; the backend only accepts renewals for the same press (code review C7)
// Select on the picture takes the same path as the top torque release: link.cmd('relax'), sent on press and always pressable (round-3 review V3).
// Key functions follow the fork's padd on the duck (fork firmware padd/src/main.rs); key names follow what's printed on the gamepad.
// Virtual gamepad: the web page sends full frames and yields when a physical gamepad is connected; the code is our own.
import { html, useState, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { InlineCamera } from './sensors.js';
import { MotionStudio } from './motion-studio.js';
import { PadMapping } from './pad-mapping.js';
import { AudioInteraction } from './audio-interaction.js';

const SEND_MS = 100;        // while a stick is held, send 10 times per second; send 0 once on release; the duck also stops by itself if nothing arrives for 0.5 s (robotd's deadman)
const WATCH_MS = 2000;
const HOLD_MS = 150;        // actions / held keys say "still held" every 0.15 s; the backend stops after 0.45 s of silence
const MODE_HB_MS = 1000;    // head / body mode reports "still here" once per second
const MODE_GRACE_MS = 800;  // just pressed Y / B: within this long the page's own state wins (the backend's snapshot hasn't caught up yet)
const DRIVE_HOLD_MS = 3000; // D-pad up must be held this long to switch walk / roller (official padd:247-252: easy to lean on it while walking, so it needs a hold)
const KEY_STALE_MS = 1000;  // while a keyboard key is held the browser keeps repeating keydown; no keydown for more than 1 s counts as released (stuck key: review 12)
const BUSY_MS = 3000;       // after pressing stand / walk / sit the button grays out until the posture changes or 3 s pass
const DZ = 0.1;             // stick dead zone (same as padd, padd:184-187): each axis below this counts as 0
const STICK_TRAVEL = 40;    // sticks on the picture: dragging this far (picture coordinates, picture width 400) counts as full stick
const WATCH_SETTLE_MS = 300;   // the gamepad block must be on screen continuously this long before watch is sent (a quick scroll past shouldn't open the padd tap: review O1)
const TAP_MS = 120;         // touch: a press counts only if held this long without moving and not canceled by the browser (started scrolling the page) (review O2)
const TAP_MOVE_PX = 8;      // touch: moving this far after pressing counts as scrolling the page
const SCROLL_GUARD_MS = 500;   // touch: presses within this long after the page scrolled are ignored (a finger touch during inertial scrolling is exactly this: review O2)
const STICK_GRAB = 30;      // sticks on the picture: touch start area (radius, picture coordinates; cap 17). Enlarged to 30 it still doesn't touch the neighboring keys / D-pad
let SEQ = 0;
const nextSeq = () => ++SEQ;

// ---------------- "In the gamepad area": route is / or /pad ∧ page visible ∧ the gamepad block is in the viewport (overview rearrangement review O1) ----------------
// Since the gamepad was merged into the overview this block stays mounted (the overview is only hidden, not unmounted), so the cleanup that used to hang on "mount / unmount" (release everything, drive off,
// stop HoldButton, mode heartbeat) would never run. So all of it hangs on active: at the moment it goes from true to false, release everything, send drive {on:false},
// and send a heartbeat right away (pad_visible:false); from false to true send drive {open}. When the route changes, app.js calls setRoute synchronously first in hashchange,
// without waiting for IntersectionObserver (after hiding, IO reports "not intersecting" one frame late, and safety can't rely on it).
const ACT = { route: location.hash.replace(/^#/, '') || '/', visible: document.visibilityState === 'visible',
  inView: false, active: false, subs: new Set(), link: null };
function actRecompute(why) {
  const a = (ACT.route === '/' || ACT.route === '/pad') && ACT.visible && ACT.inView;
  const changed = a !== ACT.active;
  ACT.active = a;
  for (const fn of ACT.subs) {
    try { fn({ active: a, inView: ACT.inView, changed }, why); } catch (e) { console.error('手柄区的订阅出错', e); }
  }
  if (changed && ACT.link) ACT.link.heartbeat();   // the backend knows immediately: 10 Hz ↔ 1 Hz (app.py sender only looks at pad_visible)
}
export const padActivity = {
  get active() { return ACT.active; },
  get inView() { return ACT.inView; },
  bind(link) { ACT.link = link; },
  setRoute(route) { ACT.route = route || '/'; actRecompute(`切到了别的页（#${ACT.route}）`); },
  setInView(v) { if (v !== ACT.inView) { ACT.inView = v; actRecompute('滚出了手柄这一块'); } },
  subscribe(fn) { ACT.subs.add(fn); return () => ACT.subs.delete(fn); },
};
document.addEventListener('visibilitychange', () => { ACT.visible = document.visibilityState === 'visible'; actRecompute('页面转到后台'); });
window.__pad = padActivity;          // for debugging (e2e checks it too): whether it currently counts as "in the gamepad area"

// The onboarding checklist's "do it" should land right on target (review O17): the pairing wizard, e-stop test, paired gamepads and remote are inside this block while the checklist is outside, so this small event connects them
const GO = new Set();
export function padGo(what) { for (const fn of GO) fn(what); }

// Touch anti-mistap (review O2): the overview is a home page you scroll down, and along the way are controls that take effect on a single touch
let lastScrollAt = -1e9;
window.addEventListener('scroll', () => { lastScrollAt = performance.now(); }, { passive: true, capture: true });
const scrolledRecently = () => performance.now() - lastScrollAt < SCROLL_GUARD_MS;
const isTouch = (e) => e.pointerType === 'touch' || e.pointerType === 'pen';
// One press on touch: counts as a press only if it doesn't move (< TAP_MOVE_PX) within TAP_MS and isn't canceled by the browser; then release / cancel = release;
// released within TAP_MS = a tap (does nothing if tap isn't given); moved or canceled = does nothing (it was scrolling the page).
// No preventDefault: the browser can still use this touch to scroll the page (it sends pointercancel once it scrolls). Returns a "void" function
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

// Key functions: follow the fork's padd on the duck (round-3 review appendix 1). role is the position: south = the bottom one of the four right-hand buttons.
// does = physical gamepad; web = where pressing on the web gamepad picture differs from physical (same if not given); off = why this key is grayed out on the web picture
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
// Position-based keys on the picture → backend names
const ROLE_BIND = { south: 'a', west: 'x', lb: 'lb', rb: 'rb', dd: 'dpad_down' };
const ROLE_HELD = { lt: 'lt', rt: 'rt', west: 'x' };
const MODE_CN = { drive: '走路', head: '头模式', body: '身体模式' };
const DRIVE_CN = { walk: '走路', roller: '轮滑' };
const SKILL_CN = { ground_pick: '低头捡', roulade: '前滚翻', kick_left: '左脚踢', kick_right: '右脚踢', sit_toggle: '坐下 ↔ 站起', roller_stand: '轮滑起身' };
// Official default key bindings (fork robotd-params lib.rs:175-215, same as the backend's pad_drive.DEFAULT_BIND); if robotd's pad.bindings were changed, those win
const DEFAULT_BIND = { a: 'ground_pick', x: 'roulade', lb: 'kick_left', rb: 'kick_right', dpad_down: 'sit_toggle' };
const BIND_ROLE = { a: 'south', x: 'west', lb: 'lb', rb: 'rb', dpad_down: 'dd' };

const STEP_ICON = { ok: '✓', fail: '×', bad: '×', doing: '', todo: '', skip: '–', unk: '?' };
const fmtMs = (ms) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} 秒`);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const cx = (...xs) => xs.filter(Boolean).join(' ');

// ---------------- Gamepad diagram (drawn by us) ----------------

// Start / Select are spread apart a bit on the picture (round-3 review V3: if adjacent, clicking Start easily hits torque release), with hit areas larger than drawn (pd-hit)
const LAYOUT = {
  xbox: { ls: [120, 100], dpad: [158, 152], face: [282, 100], rs: [243, 152], select: [172, 98], start: [228, 98], home: [200, 70] },
  switch: { ls: [120, 100], dpad: [158, 152], face: [282, 100], rs: [243, 152], select: [170, 82], start: [230, 82], home: [214, 112] },
  ps: { ls: [158, 156], dpad: [118, 100], face: [282, 100], rs: [242, 156], select: [150, 64], start: [250, 64], home: [200, 118], touch: true },
};
// Small text outside each key on the picture: [x, y, text-anchor]. The three shapes are laid out separately so text doesn't overlap keys or other text (D-pad up "按住 3 秒·轮滑" (hold 3 s · roller) isn't written: only used with wheels installed, and crowded; it's in the key table);
// at phone width only Start / Select are kept (the rest hidden by CSS); those two are also positioned here.
const NOTES = {
  xbox: { select: [170, 119], start: [236, 119], x: [253, 85], dr: [185, 137, 'start'], dd: [158, 190] },
  switch: { select: [170, 64], start: [230, 64], x: [256, 85], dr: [185, 137, 'start'], dd: [158, 190] },
  ps: { select: [135, 68, 'end'], start: [250, 52], x: [250, 85], dr: [147, 104, 'start'], dd: [104, 134] },
};
const HIT_W = 34, HIT_H = 28;      // Start / Select hit areas (picture coordinates)
const BODY = 'M128 44C96 44 70 52 56 74C40 100 26 150 22 190C19 222 38 240 60 240C80 240 92 226 104 206C114 190 124 180 144 180L256 180C276 180 286 190 296 206C308 226 320 240 340 240C362 240 381 222 378 190C374 150 360 100 344 74C330 52 304 44 272 44C240 44 226 52 200 52C174 52 160 44 128 44Z';
// Two on each side at the top of the gamepad: the front row is the shoulder buttons (LB / RB, along the top edge of the housing), the back row is the triggers (LT / RT, higher and farther out), with a gap between
const SHOULDER = { l: { x: 80, w: 72 }, r: { x: 248, w: 72 } };            // y 26–50, the lower half covered by the housing
const TRIGGER = { l: { x: 62, w: 62 }, r: { x: 276, w: 62 } };             // y -10–18
const SH_Y = 26, SH_H = 24, TR_Y = -10, TR_H = 28;

// ctl: the web gamepad controller (from useVpad). With it the keys on the picture can be pressed (doing the same work as a physical gamepad); without it it's just a diagram.
// While mirroring (physical gamepad connected) live is the physical gamepad's keys and the picture just follows it; when not mirroring live is what's pressed on the web page.
function GamepadSvg({ kind, live, seen, ctl, keys, learn, mappingView }) {
  const k = kindOf(kind);
  const L = LAYOUT[k.layout] || LAYOUT.xbox;
  const b = live?.buttons || {};
  const ax = live?.axes || {};
  const on = (r) => !!b[r];
  const was = (r) => !!(seen && seen.includes(r));
  const N = NOTES[k.layout] || NOTES.xbox;
  // rebindable keys: go by does pushed in the backend's motion.keys (A / X / LB / RB / D-pad down); otherwise the official defaults
  const does = (role) => {
    const row = keys?.[ROLE_BIND[role]];
    if (row && typeof row.does === 'string' && row.does) return row.does;
    const skill = DEFAULT_BIND[ROLE_BIND[role]];
    return SKILL_CN[skill] || skill || '';
  };
  const noteAt = (text, [x, y, anchor = 'middle'], extra) => mappingView ? null : html`<text class=${cx('pd-key-note', extra)} x=${x} y=${y} text-anchor=${anchor} aria-hidden="true">${text}</text>`;
  // pressable keys: role=button + aria-label (key name + function), press / release handed to ctl; non-pressable ones get pd-key-off with the reason in <title> (visible on mouse hover)
  const act = (r) => {
    if (learn) return { info: { ok: true, does: '学习这个输入' }, say: `学习 ${k.names[r] || r}`, props: {
      role: 'button', tabIndex: 0, 'aria-label': `学习 ${k.names[r] || r}`, 'data-role': r,
      onClick: () => learn(r), onKeyDown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); learn(r); } },
    } };
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
  // while mirroring the picture shows the physical gamepad: don't draw it gray (presses on the web page just aren't accepted, as the title says)
  const offc = (a) => a.info && !a.info.ok && !ctl.mirror && 'pd-key-off';
  const cls = (r, a, extra) => cx('pd-key', on(r) && 'pd-on', was(r) && 'pd-seen', r === 'select' && 'pd-estop',
    a.info && 'pd-press', offc(a), extra);
  const scale = (e) => (e.currentTarget.ownerSVGElement || e.currentTarget).getBoundingClientRect().width / 400;
  const stick = (r, [x0, y0], x, y, press) => {
    const t = 12;
    const a = act(r);
    const side = r === 'ls' ? 'l' : 'r';
    // stick base on the picture: the mouse can press anywhere; touch only accepts the transparent HTML over the center cap (pd-ov, below), since a touch starting on the base is scrolling the page (review O2)
    const sp = learn ? a.props : ctl ? { role: 'button', 'aria-label': a.say, 'data-role': r, onContextMenu: (e) => e.preventDefault(),
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
  // triggers: fill from the bottom up as deep as it's pressed; digital triggers (Switch ZL / ZR) are full when pressed
  const trig = (r, side) => {
    const { x, w } = TRIGGER[side];
    const v = clamp(ax[r] ?? (on(r) ? 1 : 0), 0, 1);
    const pressed = on(r) || v > 0.5;
    const a = act(r);
    // text: black with a white outline when not fully pressed (readable on a half-black half-white background), white when fully pressed
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
  // Transparent HTML blocks laid over the picture (review O2): on phones the whole picture can scroll the page (touch-action: pan-y); only the two stick caps and Select's
  // hit area don't scroll (touch-action: none). Whether browsers honor touch-action on SVG child elements hasn't been verified, so HTML blocks take the touches.
  // positions converted from picture coordinates (viewBox 0 -16 400 266) to percentages; mouse clicks here work the same
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
    <svg class=${cx('pd-svg', ctl && 'pd-svg-live')} viewBox="0 -16 400 266" role=${ctl || learn ? 'group' : 'img'}
    aria-label=${learn ? '点击标准键学习实体手柄输入，只测试，不执行动作' : ctl ? `${k.label}：图上的键能按，跟实体手柄一样` : `${k.label}示意图，按下的键会变黑`} onContextMenu=${ctl ? (e) => e.preventDefault() : undefined}>
    ${trig('lt', 'l')}${trig('rt', 'r')}
    ${shoulder('lb', 'l')}${shoulder('rb', 'r')}
    <path class="pd-body" d=${BODY}></path>
    ${L.touch ? html`<rect class="pd-touch" x="168" y="54" width="64" height="40" rx="8"></rect>` : null}
    ${mode ? html`<g class="pd-modetag"><rect x="164" y="22" width="72" height="20" rx="10"></rect><text x="200" y="36">${mode}</text></g>` : null}
    ${stick('ls', L.ls, ax.lx, ax.ly, 'l3')}
    ${stick('rs', L.rs, ax.rx, ax.ry, 'r3')}
    ${dpad(L.dpad)}
    ${face(L.face)}
    ${small('select', L.select, mappingView ? 'SEL' : k.names.select.length > 2 ? '' : k.names.select)}
    ${small('start', L.start, mappingView ? 'START' : k.names.start.length > 2 ? '' : k.names.start)}
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

// ---------------- Key table (by the labels printed on this gamepad) ----------------

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
  // Y: when robotd.toml on the duck has [pad_imu_head_control] enabled and the gamepad has a gyro, the physical gamepad's Y is "head follows the gamepad's attitude" (fork padd:1044-1093).
  // Browsers don't have the gamepad's attitude: Y on the web page is always "sticks control the head" (round-3 review V18)
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

// ---------------- Header: model · connected · e-stop valid ----------------

function Summary({ pad }) {
  const s = pad?.status || {};
  const live = pad?.live || {};
  const act = s.active;
  const es = pad?.estop || {};
  const name = act ? act.name || '手柄' : live.state === 'attached' ? live.device?.name || '手柄' : null;
  const mark = es.state === 'ok' ? html`<span class="pd-ok">有效 ✓</span>`
    : es.state === 'unknown' ? html`<span class="pd-unk">没核对完 ?</span>` : html`<span class="pd-bad">无效 ×</span>`;
  // labeled "gamepad e-stop" (「手柄急停」), separate from the top bar's "torque release" (「卸力」) (review O7); uses the same status / estop as the gauge strip's gamepad cell and onboarding checklist steps 3 and 4
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

// ---------------- E-stop test: torque on while held + readback shows torque off after release; only both together count as ✓ ----------------

const TEST_STEPS = [
  ['torque', '托着鸭子（或者放在架子上），按手柄 Start 让它站起来'],
  ['press', '短按一下 Select（别按住：按住 2 秒会坐下并关机）'],
  ['readback', '等主程序回读：扭矩关了'],
];
const TEST_AT = { need_torque: 0, armed: 1, pressed: 1, released: 2 };              // which step we're at now
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

// ---------------- Web gamepad: one controller shared by the picture's keys, the two sticks and the keyboard ----------------

const TEXT_TYPES = ['text', 'password', 'search', 'email', 'number', 'tel', 'url'];
const typing = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'
  || (el.tagName === 'INPUT' && TEXT_TYPES.includes((el.type || 'text').toLowerCase())));
// The keyboard only handles walking (head / body modes don't respond: full head stick defaults to 2.5 rad, so one W press would slam the head to the limit, round-3 review V2). Arrow keys are dropped:
// with no on/off switch anymore, people pressing arrow keys to scroll the page would make the duck walk
const KEYMAP = { KeyW: ['ly', -1], KeyS: ['ly', 1], KeyA: ['lx', -1], KeyD: ['lx', 1], KeyQ: ['rx', -1], KeyE: ['rx', 1] };
const ZERO = { lx: 0, ly: 0, rx: 0, ry: 0 };
const dz = (v) => (Math.abs(v) < DZ ? 0 : v);
const MIRROR_WHY = '实体手柄连着：图只跟着它显示，网页上按的不收（Select 照样能卸力）';

// Readout: the same formula as the backend's pad_drive.sticks_to_intent (the backend is authoritative; this just shows people what's being sent now)
function readout(mode, f, lim, head) {
  const LX = dz(f.lx), LY = -dz(f.ly), RX = dz(f.rx), RY = -dz(f.ry);
  if (mode === 'head') return [['脖子', RY * head, 'rad'], ['低抬头', -LY * head, 'rad'], ['转头', -LX * head, 'rad'], ['歪头', RX * head, 'rad']];
  if (mode === 'body') {
    return [['高低', LY * (LY >= 0 ? 1.0 : 2.5), 'cm'], ['前后倾', clamp(RY * 0.2618, -0.26, 0.26), 'rad'],
      ['左右倾', clamp(RX * 0.2618, -0.26, 0.26), 'rad']];
  }
  return [['前后', LY * lim.v, 'm/s'], ['平移', -LX * lim.v, 'm/s'], ['转弯', -RX * lim.w, 'rad/s']];
}

// All web gamepad state lives here: sticks (tracked per pointerId, two can be dragged at once), keyboard, held keys (LT / RT / X), mode (walk / head / body).
// The keys on the picture (GamepadSvg), the two sticks on the picture and the keyboard all go through it, whichever moves. Rules (round-3 review):
// - Sticks are relative: the point pressed is the center (V2), 0.1 dead zone; only sent while held (10 Hz); returning to center sends stop once.
// - The keyboard only works while the remote area (gamepad picture) has focus; losing focus releases (V2).
// - Page switch, window blur, page to background, scrolled out of the gamepad block, physical gamepad connected, someone else takes over: release everything (sticks back to 0, keys released, exit head / body mode).
//   Leaving the gamepad area (padActivity.active from true to false) also sends drive {on:false}; coming back sends drive {open} (overview rearrangement review O1).
// - Touch anti-mistap (review O2): sticks only accept presses starting in the start area near the caps on the picture; presses within 0.5 s after the page scrolled are ignored; keys on the picture count as pressed only after 0.12 s without moving.
//   Select is the exception: releases torque on press, always pressable (round-3 V3).
// - The backend decides the mode (V6): when the backend exits a mode on this page's behalf (torque release, policy stopped, timeout…), the page follows back to walking, and held sticks must be released and pressed again.
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
  // with input: send a frame right away, then one every 100 ms (not at pointermove frequency while dragging); send stop once at the moment of returning to center
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
    // touch: only accept starts from the center cap (starts on the base are mostly page scrolling), ignore right after the page scrolled (review O2). No preventDefault: let it scroll
    if (isTouch(e) && (!center || scrolledRecently())) return;
    if (!ACT.active) return;                      // the gamepad block isn't on screen (switched away, scrolled away): ignore
    e.preventDefault(); focusZone(e);
    if (!S.usable) { say(whyNot(), false); return; }
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers don't have it */ }
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

  // ---- Held keys: LT / RT / X (keys channel, round-3 review V4) ----
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
    // follow the backend back to walking: reply "walk" once so the backend knows the page saw it; only after that can Y / B enter again (review R3: an "enter mode" arriving before that reply
    // is treated by the backend as a heartbeat that didn't see the exit, and is not accepted)
    if (serverMode === 'drive') cmd({ op: 'mode', mode: 'drive', seq: nextSeq() });
  }
  const setMode = async (next, why) => {
    if (next === S.mode) return;
    S.mode = next; S.modeAt = performance.now(); setModeView(next);
    voidSticks();                                   // mode change: held sticks are voided and must be released and pressed again (otherwise the hand pushing the head would turn into walking on a mode change)
    const r = await cmd({ op: 'mode', mode: next, seq: nextSeq() });
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || '没切过去'); if (S.mode === next && next !== 'drive') adopt('drive'); return; }
    if (r.data?.dropped && r.data.mode && r.data.mode !== S.mode) { adopt(r.data.mode, r.data.dropped); return; }
    if (r.data?.note) say(r.data.note, false);
    else if (why) say(`回到走路（${why}）`, false);
  };
  // the heartbeat carries hb:true: the backend only renews "still here" and won't reopen a mode it has already exited on the page's behalf (torque release, policy stopped, timeout…); if it differs, follow the backend back to walking (review R3)
  const beatMode = async () => {
    const r = await cmd({ op: 'mode', mode: S.mode, hb: true });
    if (S.alive && r.ok && r.data?.mode && r.data.mode !== S.mode && performance.now() - S.modeAt > MODE_GRACE_MS) adopt(r.data.mode, r.data.dropped);
  };

  // ---- Release everything ----
  function releaseAll(why, keep) {
    if (S.touchOff) { const f = S.touchOff; S.touchOff = null; f(); }     // a touch press not yet counted as pressed: void it
    if (S.driveTimer) { clearTimeout(S.driveTimer); S.driveTimer = null; }  // D-pad up not held for 3 s yet: don't switch
    S.kb.clear();
    for (const side of ['l', 'r']) { const s = S.sticks[side]; if (s.pid != null) s.void = true; s.x = 0; s.y = 0; }
    if (S.held.size) { S.held.clear(); setHeldView(new Set()); sendKeys(); }
    S.pressed.clear(); if (keep) S.pressed.add(keep); setPressedView(new Set(S.pressed));
    if (S.mode !== 'drive') setMode('drive', why);   // the backend clears head / body (round-3 V1 item 2)
    kick();
  }

  // ---- Keys on the picture pressed / released ----
  const estop = (fromCard) => {
    // Select on the picture = e-stop: sent on press (not on release: on touch, a finger moving makes the browser send pointercancel), same path as the top "torque release" (round-3 review V3).
    // The "torque release" button at the top of the remote card (review O3) also goes through here
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
  // D-pad right: as official, sent on one press (the main program first releases torque on the whole body); like Select, release everything here first
  const rebootKey = async () => {
    releaseAll('按了十字右（重启舵机：主程序会先卸力）', 'dr');
    const r = await cmd({ op: 'reboot', src: 'svg' }, 7000);
    if (S.alive) say(r.ok ? '✓ 重启舵机发出去了：鸭子会先软下来，扶住；好了按 Start 站回来' : (r.reason || r.error || '没成功'), !r.ok);
  };
  // D-pad up: sent only after a 3 s hold; releasing before 3 s (up) or releasing everything (releaseAll) doesn't switch
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
    if (role === 'dr') {                          // like Select, pressable even while someone else is driving (rescue: the backend ignores the wheel)
      const x = mm.reboot;
      if (!x || S.mirror) return { ok: false, why: whyNot() };
      return x.ok ? { ok: true, does: x.does } : { ok: false, why: x.why };
    }
    if (role === 'start') {
      const s = mm.start;
      if (!s || S.mirror) return { ok: false, why: whyNot() };
      if (S.locked && s.op !== 'walk_stop') return { ok: false, why: whyNot() };   // anyone can press "stop (stand)" (「停下（站好）」)
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
    if (!ACT.active) return;                      // the gamepad block isn't on screen: ignore (Select doesn't come through here)
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
      // Select on the picture = e-stop: releases torque on press, always pressable (round-3 V3); its hit area has its own touch-action:none (review O2)
      e.preventDefault();
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers don't have it */ }
      estop(); return;
    }
    if (isTouch(e)) {
      // touch: counts as pressed only after 0.12 s without moving and not canceled by the browser; released within 0.12 s = a tap (press then release). Ignored right after the page scrolled (review O2)
      if (scrolledRecently() || !ACT.active) return;
      if (S.touchOff) S.touchOff();
      S.touchOff = touchHold(e, { press: () => fire(role), release: () => up(role), tap: () => { fire(role); up(role); } });
      return;
    }
    e.preventDefault(); focusZone(e);
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers don't have it */ }
    fire(role);
  };
  const up = (role) => {
    if (!S.pressed.has(role)) return;
    unpress(role);
    if (ROLE_HELD[role]) releaseKey(ROLE_HELD[role]);
    if (role === 'du' && S.driveTimer) { clearTimeout(S.driveTimer); S.driveTimer = null; say('没按够 3 秒：没切（官方要按住 3 秒，防止误按）', false); }
  };

  // ---- Keyboard: only while the remote area has focus (round-3 review V2) ----
  const zoneProps = {
    tabIndex: 0,
    onKeyDown: (e) => {
      const km = KEYMAP[e.code];
      if (!km || typing(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
      // after the remote area is scrolled out with the wheel, focus stays inside: held keys were released long ago (left the gamepad area), and repeated keydowns from holding aren't accepted either (review O1)
      if (!ACT.active) return;
      e.preventDefault();
      // the browser's auto-repeat only renews "already held" keys: after any "release everything" (scrolled out of the gamepad area, blur, torque release…) a real press is required again,
      // so when scrolling back / switching back to the window with W still held, the repeated keydowns can't make the duck keep walking (code review C3; sticks also need release and re-press)
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
      if (to && to.closest && to.closest('.pd-zone')) return;        // switching between the two remote areas: doesn't count as blur
      setKbOn(false);
      if (S.kb.size) { S.kb.clear(); kick(); }
    },
  };

  useEffect(() => {
    S.alive = true;
    // entering the gamepad area (this block came on screen): only clears "left", doesn't take the wheel (round-3 review V5). Send once the connection is up; check once more that it's still there before sending
    const open = () => link.whenOpen().then(() => { if (S.alive && ACT.active) cmd({ op: 'drive', open: true, seq: nextSeq() }, 3000); });
    // leaving the gamepad area (page switch, scrolled away, to background): release everything, the backend records "left", late frames are all dropped (review O1)
    const leave = (why) => {
      releaseAll(why);
      link.cmd('pad.op', { op: 'drive', on: false, seq: nextSeq(), why }, 3000);
    };
    const offAct = padActivity.subscribe(({ active, changed }, why) => {
      if (!changed) return;
      if (active) open(); else leave(why);
    });
    if (ACT.active) open();
    // after a reconnect it's a new connection, which the backend by default treats as "not in the gamepad area" (review O1): if still there, open again
    const offLink = link.on((m) => { if (m.t === '_status' && m.status === 'open' && ACT.active) open(); });
    const blur = () => releaseAll('窗口失焦');
    const vis = () => { if (document.visibilityState !== 'visible') releaseAll('页面转到后台'); };
    // space is the top torque release (intercepted by app.js in the capture phase), Esc: release everything along the way
    const keyCap = (e) => { if (e.code === 'Space' || e.code === 'Escape') releaseAll(e.code === 'Space' ? '按了空格（卸力）' : '按了 Esc'); };
    // stuck keys: on Mac, a W released first while Cmd is held never gets its keyup; it can also be lost during dialogs. While held the browser keeps repeating keydown, so no keydown for 1 s counts as released
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
      link.cmd('pad.op', { op: 'drive', on: false, seq: nextSeq() }, 3000);   // leaving: the backend records "left", late frames are all dropped
    };
  }, []);
  // physical gamepad connected, someone else took the wheel, state unreadable: release everything
  useEffect(() => { if (!usable) releaseAll(mirror ? '实体手柄连上了' : locked ? '别的页面在遥控' : '读不到状态'); }, [usable]);
  // the backend decides the mode: when the backend exits on this page's behalf (torque release, policy stopped, heartbeat timeout…), the page follows back to walking
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
    estop: () => estop(true) };
}

// Buttons that act only while held: press sends action_start, action_hold every 0.15 s while held, and release / move away / blur / page to background / scrolled out of the gamepad block
// all send action_stop. On touch it counts as pressed only after 0.12 s without moving and not canceled by the browser (started scrolling), ignored right after the page scrolled (review O2:
// the first step of "kick left and right once each" is robot.do, and a finger starting here to scroll the page used to kick on touch); released within 0.12 s does nothing (acts only while held)
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
  // a sequence number per press (press): if released and pressed again before the ack returns, the first ack is void; otherwise an extra timer would be set and keep sending
  // action_hold until the page closes, defeating the backend's "stop if not renewed within 0.45 s" safeguard for this page (code review C7). The backend also accepts renewals by this number
  const start = async (e) => {
    if (e) { e.preventDefault(); try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* some browsers don't have it */ } }
    if (alive.current || !item.ok || locked || !ACT.active) return;
    const my = ++seq.current;
    alive.current = true; setHeld(true);
    const r = await link.cmd('pad.op', { op: 'action_start', id: item.id, press: my }, 4000);
    if (my !== seq.current) return;                       // pressed again while waiting for the ack: hand over to the new press, do nothing here
    if (!r.ok) { onErr(r.reason || r.error || '没做成'); alive.current = false; setHeld(false); return; }
    if (!alive.current) { link.cmd('pad.op', { op: 'action_stop' }, 3000); return; }      // released before the ack arrived
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
    // scrolled out of the gamepad block, switched to another page: stop right away (the overview stays mounted and isn't unmounted; hiding doesn't release pointer capture either: review O1)
    const offAct = padActivity.subscribe(({ active, changed }) => { if (changed && !active) stop(); });
    window.addEventListener('blur', stop);
    document.addEventListener('visibilitychange', vis);
    return () => { offAct(); window.removeEventListener('blur', stop); document.removeEventListener('visibilitychange', vis); stop(); };
  }, []);
  return html`<button class=${cx('pd-act', 'pd-hold', held && 'pd-held', lit && 'pd-lit')} disabled=${!item.ok || locked}
    title=${item.ok ? `按住才做，松手就停：${item.text}` : item.why}
    onPointerDown=${down} onPointerUp=${stop} onPointerCancel=${stop} onLostPointerCapture=${stop}
    onKeyDown=${(e) => { if (e.key === 'Enter' && !e.repeat) start(); }} onKeyUp=${(e) => { if (e.key === 'Enter') stop(); }}
    onContextMenu=${(e) => e.preventDefault()}>
    <b>${item.name}</b><small>${item.ok || quiet ? item.text : item.why}</small></button>`;
}

// One line under the picture: what Start will do now, what the sticks control, the result of the last press; plus a line of full explanation
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

function Remote({ st, pad, link, vp }) {
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
    // anyone can click "stop (stand)" (「停下（站好）」), no queuing (second review I1); other buttons gray out while someone else is pushing the stick or the previous request hasn't answered
    const off = !b.ok || (b.op !== 'walk_stop' && (locked || busy));
    return html`<button class=${cx('pd-big', extra, lit && 'pd-lit')} disabled=${off} onClick=${() => press(b)}
      title=${b.ok ? (b.call ? `发给主程序：${b.call}` : '') : b.why}>
      <b>${b.label}</b><small>${busy ? '等它回话…' : b.ok ? (b.note || (b.op === 'walk_stop' ? '停下来站好（不坐）' : '')) : b.why}</small></button>`;
  };
  const last = m.last;
  const la = m.last_action;
  // a group of buttons all unpressable for the same reason: write the reason only once, not repeated on each button
  const common = (items) => {
    const xs = items || [];
    return xs.length && xs.every((x) => !x.ok && x.why === xs[0].why) ? xs[0].why : null;
  };
  const skWhy = common(m.skills), actWhy = common(m.actions), comboWhy = common(m.combos);
  const why = (text) => (text ? html`<p class="pd-small-p pd-why">${text}</p>` : null);
  return html`<section class="board pd-card pd-remote" id="pd-remote" tabIndex="-1">
    <div class="pd-card-h">
      <h3>遥控</h3>
      <span class="pd-pose">现在：<b>${m.posture_cn || '—'}</b></span>
      <span class="sv-spacer"></span>
      ${d ? html`<span class=${cx('pd-tag', !d.mine && 'pd-warn')}>${d.mine ? '这个页面在遥控' : `${d.by || '另一个页面'}正在遥控`}</span>` : null}
      ${locked ? html`<button class="btn-light" onClick=${takeOver}>接管</button>` : null}
      ${/* the top bar's torque release is sticky; another one on the same path is placed here (review O3: right at hand on phones while pushing the sticks on the picture); always pressable */ ''}
      <button class="estop pd-relax" title="让 15 颗舵机全部卸力（跟顶上的「卸力」同一条路）。鸭子会软下来，扶住。"
        onClick=${(e) => { e.currentTarget.blur(); vp.estop(); }}>卸力</button>
    </div>
    <p class="pd-small-p pd-leave-note">滚出这一块、切到别的页，按着的摇杆和动作都会马上松开。</p>
    ${err ? html`<div class="banner bad" role="alert"><b>${err}</b><a href="#" onClick=${(e) => { e.preventDefault(); setErr(null); }}>知道了</a></div>` : null}
    ${locked ? html`<div class="banner warn" role="status"><b>${d.by || '另一个页面'}正在推摇杆 / 做动作</b><span class="more">同一时间只让一个页面开，免得两边抢。它松手 6 秒后这里就能用；急着用就点「接管」。「停下（站好）」、图上的 Select（卸力）随时能点。</span></div>` : null}
    ${v.pad_unknown ? html`<div class="banner warn" role="status"><b>认不出有没有实体手柄</b><span class="more">${v.pad_unknown}。如果手柄其实连着，图上的摇杆会被它盖掉。</span></div>` : null}
    ${mirror ? html`<div class="banner warn" role="status"><b>实体手柄连着：上面的手柄图跟着它动，只显示、不发指令</b><span class="more">这样不会跟手柄抢。站起来、开始走、坐下、技能、叫一声照常能点；图上的 Select 照样能卸力。</span></div>` : null}

    <div class="pd-sec">
      <div class="pd-sec-h">站、走、坐</div>
      ${m.posture === 'servo_session' || st?.posture === 'servo_session' ? html`<p class="pd-small-p pd-why">调舵机中：主程序停着，站走都不能用（点顶上的「交还主程序」才回来）。</p>` : null}
      <div class="pd-bigs">${mainBtn(B.stand)}${mainBtn(B.walk, B.walk?.op === 'walk_stop' ? 'pd-stopbtn' : '')}${mainBtn(B.sit)}</div>
      ${last ? html`<p class=${cx('pd-small-p', !last.ok && 'pd-bad-t')}>${last.ok ? '✓' : '×'} ${last.what}${last.by ? `（${last.by}）` : ''}：${last.ok ? (last.reason || '主程序收到了') : last.reason}</p>` : null}
    </div>

    <${AudioInteraction} pad=${pad} link=${link} activity=${padActivity} />
    <${MotionStudio} pad=${pad} link=${link} activity=${padActivity} />

    <div class="pd-sec">
      <div class="pd-sec-h">技能<small>点一下做一次（官方的动作）</small></div>
      ${why(skWhy)}
      <div class="pd-acts">
        ${(m.skills || []).map((s) => html`<button class=${cx('pd-act', physSkill(s.name) && 'pd-lit')} disabled=${!s.ok || locked}
          title=${s.ok ? `robot.do ${s.name}` : s.why} onClick=${() => op({ op: 'skill', name: s.name })}>
          <b>${s.label}</b><small>${s.ok || skWhy ? '' : s.why}</small></button>`)}
        ${!(m.skills || []).length ? html`<p class="pd-small-p">${m.skills_why || '这只鸭子没配技能'}</p>` : null}
      </div>
      <div class="pd-sec-h">叫一声</div>
      <div class="pd-acts pd-sounds">
        ${(m.sounds || []).map((s) => html`<button class=${cx('pd-act', 'pd-chipbtn', mirror && s.tag === 'chirp' && (lax.rt || 0) > 0.3 && 'pd-lit')} disabled=${!s.ok}
          title=${s.ok ? `robot.sound ${s.tag}` : s.why} onClick=${() => op({ op: 'sound', tag: s.tag })}>${s.label}</button>`)}
      </div>
      <div class="pd-sec-h">动作<small>按住才做，松手就停</small></div>
      ${why(actWhy)}
      <div class="pd-acts">
        ${(m.actions || []).map((a) => html`<${HoldButton} key=${a.id} item=${a} link=${link} onErr=${setErr} locked=${locked} quiet=${!!actWhy}
          lit=${mirror && a.id === 'mouth' && Math.max(lax.lt || 0, lax.rt || 0) > 0.1} />`)}
      </div>
      <div class="pd-sec-h">组合动作<small>几个动作连着做；按住才做，松手、卸力、点「停」都会马上停</small></div>
      ${comboWhy && comboWhy !== actWhy ? why(comboWhy) : null}
      <div class="pd-acts">
        ${(m.combos || []).map((a) => html`<${HoldButton} key=${a.id} item=${a} link=${link} onErr=${setErr} locked=${locked} quiet=${!!comboWhy} />`)}
      </div>
      ${m.running ? html`<p class="pd-small-p">正在做「${m.running.name}」：第 ${m.running.step + 1} / ${m.running.steps} 步${m.running.by ? `（${m.running.by}）` : ''}</p>`
        : la ? html`<p class=${cx('pd-small-p', !la.ok && 'pd-bad-t')}>「${la.name}」${la.result}</p>` : null}
      <p class="pd-small-p">自己编组合动作：下一版加编辑界面（编好的存在鸭子的 state 目录里）。</p>
    </div>
    <p class="pd-small-p">安全：按住才动。松手、滚出手柄这一块、切到别的页、窗口失焦、页面转到后台都会马上停（头、身体也回正）；网页断了，鸭子 0.5 秒收不到指令也会自己停。同一时间只有一个页面能遥控。手机上从手柄图的空白处、按钮上起手往下刷是在滚页面，不会让鸭子动。</p>
  </section>`;
}

// ---------------- 3D duck in the gamepad area (user, Oct 18: "to the left of the sticks there should be a 3D view, and stick control on the right, so you can see the duck's state while controlling") ----------------
// On wide screens the left side has the 3D and camera as two stacked cards, sticky below the gauge strip when there's room; on narrow screens they go above the remote in order.
// Same as the overview stage: live joints, no zoom, one finger scrolls the page and two rotate (duck3d's pageScroll, touch-action is also in the CSS), not drawn when out of the viewport (duck3d's IO);
// model geometry is a shared cache in the duck3d module, not loaded twice. Stale data is desaturated (via class, not a style string: code review C6).
// A line of small text below: posture · battery · current forward / strafe / turn (same formula and same stick state as the remote card's readout)
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

// ---------------- Gamepad block (in the overview, just scroll down) ----------------

const TOPBAR_PX = 56;       // sticky top bar (styles.css .topbar): subtracted when judging "on screen or not" (review O1, O3)
const TABBAR_PX = 83;       // phone bottom bar (styles.css .tabbar)

// Overview rearrangement (plan §1.2, review O11): order is header → gamepad picture (key table collapsed by default) + remote → pairing wizard / e-stop test / paired gamepads.
// There's no separate gamepad page anymore: #/pad is an anchor on the overview (app.js scrolls here on open, id="pad-block").
// This block stays mounted; "present or not" is determined by padActivity (route + page visible + block in the viewport): watch, drive open / off and release-everything all hang on it
export function PadPage({ st, pad, link, api, previewActive = false, live: duckLive = true }) {
  const [msg, setMsg] = useState(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [mappingOpen, setMappingOpen] = useState(false);
  const [kind, setKind] = useState('xbox');
  const [visualFits, setVisualFits] = useState(true);
  const rootRef = useRef(null);
  const s = pad?.status || {};
  const live = pad?.live || {};
  const w = pad?.wizard || { state: 'idle' };
  const showWizard = wizardOpen || w.state !== 'idle';
  // the detected model wins; before a gamepad is connected, draw the model chosen in the wizard (default Xbox)
  const activeKind = live.device?.kind || s.active?.kind || kind;
  const vp = useVpad({ pad, st, link });
  // what the picture shows: physical gamepad connected (mirroring) or key test during pairing → the physical gamepad's; otherwise → what's pressed on the web page
  const shown = vp.mirror || live.state === 'attached' ? live : vp.liveWeb;

  // when the top hint wraps, judge by the actual height too; if it doesn't fit, scroll with the page rather than pinning the camera off screen.
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

  // whether this block is in the viewport (subtracting the sticky top bar and phone bottom bar). When hidden (switched to another page) IO also reports "not intersecting", but one frame late:
  // on the routing side app.js already computed it synchronously first in hashchange (padActivity.setRoute)
  // looks at the original blocks: header, gamepad picture, remote, the pairing / e-stop test cards below; the 3D card doesn't count (just watching the duck doesn't count as being in the gamepad area: user, Oct 18, item 3)
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

  // tell the backend "someone is looking at the gamepad block": only then does the backend subscribe to the padd tap (padd only opens the gamepad device when subscribed, costing nothing otherwise).
  // only opens after being on screen continuously for 0.3 s (a quick scroll past shouldn't open the tap: review O1); resend right after a reconnect
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

  // the onboarding checklist's "do it" (review O17): open the pairing wizard, scroll to the e-stop test and focus "test the e-stop once", scroll to paired gamepads / remote
  useEffect(() => {
    const fn = (what) => {
      if (what === 'wizard') setWizardOpen(true);
      // wait for the wizard to render (two frames) before scrolling
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
  return html`<section class="pd-page" id="pad-block" ref=${rootRef} aria-label="手柄">
    <header class="pd-head">
      <h2>手柄</h2>
      <${Summary} pad=${pad} />
      <span class="sv-spacer"></span>
      <button class="btn-light" type="button" data-map-open onClick=${() => { setMappingOpen(true); requestAnimationFrame(() => document.querySelector('.pad-mapping')?.scrollIntoView({ block: 'start' })); }}>重新映射／校准</button>
      ${!showWizard ? html`<button class="btn-dark" onClick=${() => setWizardOpen(true)}>${connected ? '再配一个手柄' : '配对手柄'}</button>` : null}
    </header>
    ${mappingOpen ? html`<${PadMapping} mapping=${pad?.mapping} link=${link} active=${previewActive} Diagram=${GamepadSvg} onClose=${() => setMappingOpen(false)} />` : null}
    ${msg ? html`<div class="banner bad" role="alert"><b>${msg}</b><a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>知道了</a></div>` : null}
    ${s.error && live.state !== 'attached' ? html`<div class="banner warn" role="status"><b>读不到 configd 的手柄状态</b><span class="more">${s.error}</span></div>` : null}
    ${s.netpad ? html`<div class="banner warn" role="status"><b>开着 UDP 手柄（netpad）</b><span class="more">这时 padd 只读电脑发来的 UDP 手柄，蓝牙手柄不管用、急停也不走蓝牙手柄。要用蓝牙手柄，先在配置里关掉 [netpad]。</span></div>` : null}
    ${s.known && s.driver && s.driver !== 'active' ? html`<div class="banner bad" role="alert"><b>padd 没在跑（${s.driver}）</b><span class="more">手柄连着也不管用。padd 只在主程序 robotd 跑着时才起。</span></div>` : null}
    ${st?.posture === 'servo_session' ? html`<div class="banner warn" role="status"><b>正在调舵机</b><span class="more">主程序停着，手柄、遥控、站走都不能用；离开舵机页舵机照样保持，点顶上的「交还主程序」才交还。</span></div>` : null}
    <div class="pd-main">
      <section class="board pd-card pd-live">
        <div class="pd-card-h"><h3>${live.device?.name || s.active?.name || `${kindOf(activeKind).label}${vp.mirror ? '' : '（网页手柄）'}`}</h3>
          <span class="pd-livetag">${tapTag}${live.last_ms != null && live.state === 'attached' ? ` · ${fmtMs(live.last_ms)}前有输入` : ''}</span></div>
        <div class=${cx('pd-zone', 'pd-svgzone', vp.kbOn && 'pd-kb')} ...${vp.zoneProps} aria-label="网页手柄（点一下再用键盘 W/S/A/D/Q/E）">
          <${GamepadSvg} kind=${activeKind} live=${shown} seen=${w.phase === 'keys' ? w.seen : null} ctl=${vp} keys=${pad?.motion?.keys} />
        </div>
        <${VpadBar} vp=${vp} pad=${pad} />
        ${['error', 'absent', 'denied'].includes(live.state) ? html`<p class="pd-small-p">${live.why || '读不到按键'}</p>` : null}
        ${!connected && live.state !== 'attached' ? html`<p class="pd-small-p">还没连实体手柄：上面的图就是网页手柄，图上的键能按，跟实体手柄一样（按键作用照鸭子上的 padd）。图是${kindOf(activeKind).label}的样子。</p>` : null}
        <details class="pd-legend-box">
          <summary>按键表：每个键做什么</summary>
          <${Legend} kind=${activeKind} live=${shown} bindings=${pad?.bindings} imuHead=${pad?.virtual?.pad_imu_head} />
        </details>
      </section>
      <div class=${cx('pd-left', !visualFits && 'pd-left-overflow')}><${PadDuck} st=${st} pad=${pad} vp=${vp} live=${duckLive} />
        <${InlineCamera} api=${api} active=${previewActive} /></div>
      <${Remote} st=${st} pad=${pad} link=${link} vp=${vp} />
    </div>
    <div class="pd-more">
      ${showWizard ? html`<${Wizard} w=${w} op=${op} kind=${kind} setKind=${setKind} onClose=${() => { setWizardOpen(false); op({ op: 'wizard_reset' }); }} />` : null}
      <${EStopTest} pad=${pad} op=${op} />
      <${KnownPads} pad=${pad} op=${op} />
    </div>
  </section>`;
}
