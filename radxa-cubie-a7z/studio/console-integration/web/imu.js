// IMU page: see the current attitude, choose the chip, calibrate the mounting orientation while standing.
// User, 10-18: "Start capturing readings, collect left/right/forward/backward tilts in the official standing pose, let the code calibrate itself, and write and save it once calibration succeeds; with a 3D duck alongside";
// after integrating into Studio the flow was settled: "click start capture, capture begins, then click end capture, capture done, then calibrate automatically" "everyone assembles theirs differently, so the offset needs to be redone".
//
// - One big button with three states: Start capture → Capturing… (click here to finish) → Computing… → result.
// - While capturing: first hold still on the table for 3 seconds; then tilt forward, back, left and right once each (any order); for each step first hold level for half a second as the zero point, then tilt and hold for 1 second.
//   A curved arrow on the 3D view demonstrates which way to tilt next; once a direction is done, its dot lights up and a short beep plays (synthesized with Web Audio, can be muted).
//   Finishes automatically once all five steps are in; if the user clicks finish midway, say which steps are missing, then continue or start over.
// - After computing: the 3D view becomes two ducks side by side, "before calibration / after calibration", with a vertical reference line + large tilt angle, and below it how many degrees off; below that is writing (the backend currently refuses; only accepted on the duck).
//   After a full standing calibration with a difference < 2° from the orientation the main program uses now and a standing tilt ≤ 5°: the backend records a "checked" mark on the overview's getting-started checklist (res.check; record only,
//   nothing is written to the duck: overview re-layout review O4).
//   Not passed: write the reason and only let the user redo the steps that failed (the redo returned by the backend).
// - The two rules "has it held still" and "the level moment" correspond line by line to find_hold / find_ref in studio/imu_calib.py, with the same parameter names (top half of RULES);
//   the frontend is just stricter (tilt ≥12°, ≤30°, hold a full 1 second, direction within ≤35° of one of forward/back/left/right), so whatever the frontend lets through the backend will accept.
//   The orientation is computed by the backend: link.cmd('imu.op', {op:'solve', samples}), where samples is a flat list [{step, t, g}].
//   End-to-end tests: tests/imu_wizard_e2e.mjs feeds readings to the wizard here, and tests/test_imu_wizard_e2e.py hands what was captured to Python to compute.
// - The backend (studio/imu.py) handles solve / coarse-capture / verify: in factory calibration mode it uses busStatus.last_sample.imu
//   to capture "still + forward tilt", then hands the result to the main program's verify-imu (level ≤5°, nose down 15–30° within 20 seconds), which writes it into the calibration file.
//   The bus board is detected automatically when the main program starts; I²C chip detection still uses microduck-firstboot.
import { html, useState, useEffect, useRef } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { TwoStep } from './confirm.js';
import { imuDiagnosticCopy } from './startup-status.js';

const RULES = {
  // ---- Same names and values as imu_calib.py RULES (change one side and you must change the other; the end-to-end tests will catch it) ----
  still_min_n: 15,
  still_max_spread_deg: 1.5,
  level_deg: 5,              // level: within this much of resting on the table
  ref_min_n: 5,              // level for at least this many consecutive readings
  ref_spread_deg: 1.5,       // while level, it may wobble at most this much
  hold_band_deg: 1.8,        // hold segment: within this much of the last reading (single erratic readings are skipped)
  // ---- Frontend-only (stricter than the backend) ----
  still_s: 3.0,              // capture 3 seconds of stillness
  hold_min_n: 8,             // backend: 5
  hold_s: 1.0,               // holding a full 1 second counts as this direction done
  tilt_go_deg: 12,           // backend minimum is 10°
  tilt_target_deg: 15,
  tilt_max_deg: 30,          // backend maximum is 35°
  dir_max_deg: 35,           // the tilt direction must be within ≤ this much of one of forward/back/left/right (by the current orientation) to count
  stale_ms: 1000,
  dedupe_ms: 40,             // without state_t_ns: if two frames' "generation time" differs by this little, treat them as the same reading
  max_step_n: 600,           // keep at most this many readings per segment (1 minute at 10 Hz)
};

const STEPS = ['still', 'fwd', 'back', 'left', 'right'];
const TILTS = ['fwd', 'back', 'left', 'right'];
// dir: which way gravity shifts when tilting this way (by "the current orientation", counterclockwise from body +x, degrees). Only used to recognize the direction and draw the arrow, not in the computation
const STEP = {
  still: { cn: '静止站好', short: '静止' },
  fwd: { cn: '前倾', short: '前', dir: 0, how: '头那边往下' },
  back: { cn: '后倾', short: '后', dir: 180, how: '屁股那边往下' },
  left: { cn: '左倾', short: '左', dir: 90, how: '鸭子自己的左边往下（站在它后面看，就是你的左边）' },
  right: { cn: '右倾', short: '右', dir: -90, how: '鸭子自己的右边往下（站在它后面看，就是你的右边）' },
};
const DIRV = { fwd: [1, 0, 0], back: [-1, 0, 0], left: [0, 1, 0], right: [0, -1, 0] };   // body frame (= world frame of the 3D scene)

const CHIP_CN = { bus: '总线小板（ID 200）', bno08x: 'BNO085（I²C）', lsm6dsv16x: 'LSM6DSV16X（I²C）' };
const BUS_BOARD_CN = { ft6: 'FT6', imu_to_dxl: 'IMU-to-DXL', sflp_124_12: 'SFLP 124/12', qinmo: 'Qinmo（已配置）' };
const BUS_PROTOCOL_CN = { feetech: 'Feetech', dxl2: 'Dynamixel 2.0' };
const unsupportedProfile = info => info && info.profile !== undefined && !['legacy', 'qinmo'].includes(info.profile);
const unsupportedTransport = info => info && (!['feetech', 'dxl2'].includes(info.protocol) || unsupportedProfile(info));
function chipLabel(imu, live = true, diagnosticElapsed = 0) {
  if (imu?.source !== 'bus') return CHIP_CN[imu?.source] || imu?.source || '—';
  if (live === false) return CHIP_CN.bus;
  const diagnostic = imuDiagnosticCopy(imu?.diagnostic, live, diagnosticElapsed);
  if (diagnostic.board) return diagnostic.board;
  const info = imu.imu_bus;
  if (imu?.profile_error || unsupportedTransport(info)) return 'IMU 协议 / 类型待确认';
  return info ? `${BUS_BOARD_CN[info.board] || info.board || '总线小板'} · ${BUS_PROTOCOL_CN[info.protocol] || info.protocol}（ID 200）`
    : CHIP_CN.bus;
}
function imuContext(mode, imu) {
  return JSON.stringify([mode, imu?.source, imu?.source === 'bus' ? imu.imu_bus || null : null,
    imu?.configured_imu_profile ?? null, imu?.metadata_error ?? null, imu?.profile_error ?? null,
    imu?.redo?.session_id || null, !!imu?.redo?.active]);
}

// ---------------- Small arithmetic (same set as imu_calib.py) ----------------

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a) => Math.sqrt(dot(a, a));
const unit = (a) => { const n = len(a); return Number.isFinite(n) && n > 1e-9 ? [a[0] / n, a[1] / n, a[2] / n] : null; };
const deg = (r) => r * 180 / Math.PI;
const rad = (d) => d * Math.PI / 180;
const angle = (a, b) => { const ua = unit(a), ub = unit(b); return ua && ub ? deg(Math.acos(Math.max(-1, Math.min(1, dot(ua, ub))))) : null; };
const meanDir = (vs) => (vs.length ? unit(vs.reduce((s, v) => [s[0] + v[0], s[1] + v[1], s[2] + v[2]], [0, 0, 0])) : null);
const spread = (vs) => { const m = meanDir(vs); return m ? Math.max(0, ...vs.map((v) => angle(v, m) ?? 0)) : 0; };
// 90th percentile (imu_calib.spread_p90_deg): used for the still step, so one or two erratic frames do not count as wobble
const spreadP90 = (vs) => {
  const m = meanDir(vs);
  if (!m) return 0;
  const ds = vs.map((v) => angle(v, m) ?? 0).sort((a, b) => a - b);
  return ds[Math.floor(0.9 * (ds.length - 1))];
};
// imu_calib.trimmed_mean_dir: drop the 10% farthest from the mean, then average again (used in the still step to determine "up")
const trimmedMeanDir = (vs) => {
  const m = meanDir(vs);
  if (!m) return null;
  const lim = spreadP90(vs);
  return meanDir(vs.filter((v) => (angle(v, m) ?? 0) <= lim + 1e-9)) || m;
};
const okVec = (g) => Array.isArray(g) && g.length === 3 && g.every((x) => typeof x === 'number' && Number.isFinite(x));
const DOWN = [0, 0, -1];

/** How many degrees it tilted relative to g0, and which way (counterclockwise from +x in the horizontal plane defined by g0, degrees). Same as imu_calib.tilt_of. */
function tiltOf(g0, g) {
  const t = angle(g0, g);
  const up = [-g0[0], -g0[1], -g0[2]];
  const d = sub(g, g0);
  const h = sub(d, up.map((u) => u * dot(d, up)));
  const x0 = sub([1, 0, 0], up.map((u) => u * up[0]));
  if (!unit(h) || !unit(x0)) return { t, d: null };
  const a = unit(x0), b = unit(h);
  return { t, d: deg(Math.atan2(dot(cross(a, b), up), dot(a, b))) };
}

function qRotate(q, v) {
  const [w, x, y, z] = q;
  const r = [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
  return r.map((row) => dot(row, v));
}

const fmt = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—');
const sgn = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—');
const dirDiff = (a, b) => Math.abs(((a - b) % 360 + 540) % 360 - 180);
const names = (ks) => ks.map((k) => STEP[k].cn).join('、');

// ---------------- Hold segment, level reference (_run_back / find_hold / find_ref in imu_calib.py, corresponding line by line) ----------------

function runBack(gs, end, band) {
  const last = gs[end];
  const idx = [end];
  let skipped = 0, j = end - 1;
  while (j >= 0) {
    if (angle(gs[j], last) <= band) { idx.push(j); j--; }
    else if (j - 1 >= 0 && angle(gs[j - 1], last) <= band) { skipped++; j--; }   // single erratic reading: skip it
    else break;
  }
  return { idx: idx.sort((a, b) => a - b), skipped };
}

function findHold(gs) {
  if (!gs.length) return { idx: [], skipped: 0 };
  let best = runBack(gs, gs.length - 1, RULES.hold_band_deg);
  if (gs.length >= 2) {
    const alt = runBack(gs, gs.length - 2, RULES.hold_band_deg);
    if (alt.idx.length > best.idx.length + 1) best = alt;
  }
  return best;
}

function findRef(gs, g0, before) {
  const n = RULES.ref_min_n;
  for (let end = before; end >= n; end--) {
    const win = gs.slice(end - n, end);
    if (win.every((v) => (angle(g0, v) ?? 0) <= RULES.level_deg)) {
      const m = meanDir(win);
      if (m && spread(win) <= RULES.ref_spread_deg) return m;
    }
  }
  return null;
}

// ---------------- Capture (state lives in ref, fed once per incoming st frame) ----------------
// phase: idle → collect → (all in) solving → done / error; clicking finish midway with missing steps → short (continue / start over)

function freshWizard() {
  return { phase: 'idle', t0: 0, g0: null,
    buf: { still: [], fwd: [], back: [], left: [], right: [] },          // when a direction is done, that segment of readings (the backend finds the level and hold parts in it)
    done: { still: false, fwd: false, back: false, left: false, right: false },
    seg: [],                 // readings since the previous direction was done
    ref: null, level: 0, cand: null, inZone: false, repeat: null, needLevel: false,
    live: null, progress: 0, hold: 0, paused: null, moved: false, over: false,
    lastKey: null, lastBirth: null, events: [], missing: [], result: null, error: null };
}

const missingSteps = (W) => STEPS.filter((k) => !W.done[k]);
const nextTodo = (W) => TILTS.find((k) => !W.done[k]) || null;

/** Feed one frame. live: the page's "is the connection to the duck live" (same judgment as the overview); if not given, look at joints_age_ms. Returns true = needs a redraw.
 *  When a direction is done, push an entry into W.events ('still' / 'fwd' … / 'all'), which the page uses to beep. */
function feed(W, st, live) {
  if (W.phase !== 'collect') return false;
  const g = st?.gravity;
  const fresh = live !== false && st && st.joints_age_ms != null && st.joints_age_ms < RULES.stale_ms;
  if (!okVec(g) || !fresh) { const p = W.paused; W.paused = '读数断了，等它回来（已采的不丢）'; return p !== W.paused; }
  const gu = unit(g);
  if (!gu) return false;
  // Dedupe: Studio pushes state at 10 Hz and robot.state is also 10 Hz, so the same reading may be pushed twice (when robotd is stuck it keeps pushing the same one).
  // If there is state_t_ns (robot.state's t_ns), go by it; otherwise use "generation time" = time received − joints_age_ms
  const birth = performance.now() - st.joints_age_ms;
  if (st.state_t_ns != null) {
    if (st.state_t_ns === W.lastKey) return false;
    W.lastKey = st.state_t_ns;
  } else {
    if (W.lastBirth != null && Math.abs(birth - W.lastBirth) < RULES.dedupe_ms) return false;
    W.lastBirth = birth;
  }
  W.paused = null;
  const s = { t: +(birth / 1000 - W.t0).toFixed(3), g: gu.map((x) => +x.toFixed(6)) };
  if (!W.done.still) {
    const b = W.buf.still;
    b.push(s);
    if (spreadP90(b.map((x) => x.g)) > RULES.still_max_spread_deg) { W.buf.still = [s]; W.moved = true; }
    const b2 = W.buf.still;
    W.progress = Math.min(1, (b2[b2.length - 1].t - b2[0].t) / RULES.still_s);
    if (W.progress >= 1 && b2.length >= RULES.still_min_n) {
      W.g0 = trimmedMeanDir(b2.map((x) => x.g));
      W.done.still = true; W.moved = false; W.progress = 0; W.seg = []; W.ref = null;
      finishStep(W, 'still');
    }
    return true;
  }
  // Tilt steps: any order. Readings keep accumulating in seg; once it holds still, see which way it tilted and whether this direction is already done
  const b = W.seg;
  b.push(s);
  if (b.length > RULES.max_step_n) b.splice(0, b.length - RULES.max_step_n);
  const gs = b.map((x) => x.g);
  // Level: the last ref_min_n readings are within level_deg of resting on the table and wobble ≤ ref_spread_deg → zero point for the next tilt (the latest one wins)
  const n = RULES.ref_min_n;
  const tail = gs.slice(-n);
  const levelNow = tail.length === n && tail.every((v) => angle(W.g0, v) <= RULES.level_deg) && spread(tail) <= RULES.ref_spread_deg;
  if (levelNow) W.ref = meanDir(tail);
  let k = 0;
  for (let i = gs.length - 1; i >= 0 && k < n && angle(W.g0, gs[i]) <= RULES.level_deg; i--) k++;
  W.level = levelNow ? 1 : k / n;
  W.live = tiltOf(W.ref || W.g0, gu);
  W.over = W.live.t > RULES.tilt_max_deg;
  W.hold = 0; W.inZone = false; W.cand = null; W.repeat = null; W.needLevel = false;
  // Hold: same rules as the backend (hold segment + the last level before it); plus frontend-only rules: tilt 12–30°, within ≤35° of one of forward/back/left/right, hold a full 1 second
  const { idx } = findHold(gs);
  const hold = idx.map((i) => b[i]);
  const hm = meanDir(hold.map((x) => x.g));
  if (!hm) return true;
  const href = findRef(gs, W.g0, idx[0]);
  const ht = tiltOf(href || W.g0, hm);
  if (!(ht.t >= RULES.tilt_go_deg && ht.t <= RULES.tilt_max_deg) || ht.d == null) return true;
  const dirK = TILTS.find((x) => dirDiff(ht.d, STEP[x].dir) <= RULES.dir_max_deg) || null;
  W.cand = dirK;
  if (!dirK) return true;
  if (W.done[dirK]) { W.repeat = dirK; return true; }
  if (!href) { W.needLevel = true; return true; }
  W.inZone = true;
  const span = hold.length > 1 ? hold[hold.length - 1].t - hold[0].t : 0;
  W.hold = Math.min(1, (span + 1e-6) / RULES.hold_s);
  if (hold.length >= RULES.hold_min_n && W.hold >= 1) {
    W.buf[dirK] = b.slice();
    W.done[dirK] = true;
    W.seg = []; W.ref = null; W.hold = 0; W.inZone = false; W.cand = null;
    finishStep(W, dirK);
  }
  return true;
}

function finishStep(W, k) {
  if (!missingSteps(W).length) { W.phase = 'solving'; W.events.push('all'); }
  else W.events.push(k);
}

/** Start capture (a completely fresh run). */
function startCollect(W, now) {
  Object.assign(W, freshWizard(), { phase: 'collect', t0: now });
}

/** Click "finish": if everything is in, go compute; if steps are missing, stop at short and say which ones. */
function endCollect(W) {
  if (W.phase !== 'collect') return;
  const miss = missingSteps(W);
  if (!miss.length) { W.phase = 'solving'; return; }
  W.phase = 'short'; W.missing = miss;
}

/** Continue capturing (keep what is already done). */
function resumeCollect(W) {
  W.phase = 'collect'; W.seg = []; W.ref = null; W.paused = null; W.missing = []; W.result = null; W.error = null;
  if (!W.done.still) { W.buf.still = []; W.progress = 0; }
}

/** Redo only these steps (the redo returned by the backend): clear them and continue capturing. */
function redoSteps(W, steps) {
  for (const k of steps) { if (k in W.done) { W.done[k] = false; W.buf[k] = []; } }
  resumeCollect(W);
}

/** Readings handed to the backend: a flat list, each with a step (studio/imu.py wants a list) */
function payload(W) {
  return STEPS.flatMap((k) => W.buf[k].map((x) => ({ step: k, t: x.t, g: x.g })));
}

// ---------------- Beeps (synthesized with Web Audio, very short and quiet; mute is stored in localStorage) ----------------

const MUTE_KEY = 'studio.imu.mute';
function loadMute() { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } }
function saveMute(v) { try { localStorage.setItem(MUTE_KEY, v ? '1' : '0'); } catch { /* private mode: only applies to this page */ } }
let actx = null;
/** Browsers require "the user has clicked" before playing sound: call this once in the "Start capture" click. */
function audioUnlock() {
  try {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    actx = actx || new C();
    if (actx.state === 'suspended') actx.resume();
  } catch { actx = null; }
}
function beep(kind) {
  if (!actx) return;
  try {
    const t = actx.currentTime + 0.01;
    // A direction done: one 990 Hz beep; still: a bit lower at 660 Hz; all done: two rising beeps
    const tones = kind === 'all' ? [[880, 0], [1320, 0.13]] : [[kind === 'still' ? 660 : 990, 0]];
    for (const [f, dt] of tones) {
      const o = actx.createOscillator(), gn = actx.createGain();
      o.type = 'sine';
      o.frequency.value = f;
      gn.gain.setValueAtTime(0.0001, t + dt);
      gn.gain.exponentialRampToValueAtTime(0.06, t + dt + 0.012);
      gn.gain.exponentialRampToValueAtTime(0.0001, t + dt + 0.11);
      o.connect(gn); gn.connect(actx.destination);
      o.start(t + dt); o.stop(t + dt + 0.12);
    }
  } catch { /* if sound cannot play, never mind */ }
}

// ---------------- 3D ----------------

const reduceMotion = () => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };

/** Draw on top of the 3D view: vertical reference line and the demonstration arrow (curving from the top of the head toward the direction to tilt, swinging back and forth). Uses the duck's own camera projection, so it follows when the view rotates. */
function drawOverlay(d, canvas, svg, arrow, plumb, now) {
  if (!svg) return;
  if (!d || !d.ready || !d.home || !d.blob) { svg.innerHTML = ''; return; }
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const V = d.camera.position.constructor;           // three.js Vector3 (no separate import of three needed)
  d.camera.updateMatrixWorld();
  const P = d.blob.position;                          // center under the feet (ground)
  const H = 2 * (d.home.target.z - P.z);              // duck height
  const pr = (x, y, z) => { const v = new V(x, y, z).project(d.camera); return [(v.x + 1) / 2 * w, (1 - v.y) / 2 * h]; };
  let out = '';
  if (plumb) {
    const [x1, y1] = pr(P.x, P.y, P.z), [x2, y2] = pr(P.x, P.y, P.z + H * 1.12);
    out += `<line class="plumb" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
  }
  if (arrow && DIRV[arrow]) {
    const u = DIRV[arrow], R = H * 1.08;
    const swing = reduceMotion() ? 1 : 0.55 + 0.45 * Math.sin(now / 260);
    const end = 6 + 20 * swing;                        // the arc swings from the top of the head (0°) to 6–26°
    const pts = [];
    for (let a = 0; a <= end + 1e-6; a += 2) {
      const s = Math.sin(rad(a)), c = Math.cos(rad(a));
      pts.push(pr(P.x + R * s * u[0], P.y + R * s * u[1], P.z + R * c));
    }
    if (pts.length >= 2) {
      const [ex, ey] = pts[pts.length - 1], [px, py] = pts[pts.length - 2];
      const dx = ex - px, dy = ey - py, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, sz = Math.max(12, h * 0.03);
      const head = `${ex + ux * sz},${ey + uy * sz} ${ex - uy * sz * 0.6},${ey + ux * sz * 0.6} ${ex + uy * sz * 0.6},${ey - ux * sz * 0.6}`;
      // Demonstration "tilted duck": a dashed line from the feet to the arrow tip (the body centerline leaning that way)
      const [gx, gy] = pr(P.x, P.y, P.z);
      out += `<line class="ghost" x1="${gx}" y1="${gy}" x2="${ex}" y2="${ey}"/>`;
      out += `<polyline class="arc" points="${pts.map((p) => p.join(',')).join(' ')}"/><polygon class="head" points="${head}"/>`;
      // Put the text a little below the arrow tip; do not cover the large tilt angle in the top-left corner and do not go out of frame
      const lx = Math.min(w - 50, Math.max(50, ex)), ly = Math.min(h - 50, Math.max(120, ey + sz + 26));
      out += `<text class="lbl" x="${lx}" y="${ly}">往${STEP[arrow].short}倾</text>`;
    }
  }
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.innerHTML = out;
}

/** Change the camera position. Strings use Duck3D's built-ins (front34 / front / back34 / back); {az, el} is a custom angle (degrees, same algorithm as Duck3D's VIEWS:
 *  az 0 = straight ahead, −90 = the duck's right side); first compute the distance and look-at point as for front, then move the camera there ("reset view" also returns here). */
function applyView(d, view) {
  if (typeof view === 'string') { d.setView(view); return; }
  d.setView('front');
  const h = d.home;
  if (!h) return;
  const t = h.target, dist = h.pos.distanceTo(t), az = rad(view.az), el = rad(view.el);
  h.pos.set(t.x + dist * Math.cos(el) * Math.cos(az), t.y + dist * Math.cos(el) * Math.sin(az), t.z + dist * Math.sin(el));
  d.camera.position.copy(h.pos);
  d.controls.target.copy(t);
  d.controls.update();
  d.dirty = true;
}

function DuckView({ g, joints, stale, arrow, plumb, view = 'front34', children }) {
  const canvasRef = useRef(null), duckRef = useRef(null), svgRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [moved, setMoved] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    const d = new Duck3D(canvasRef.current, { view: 'front34', centerX: 0.5, centerY: 0.56, fill: 0.7 });
    duckRef.current = d;
    d.onUserMove = () => setMoved(true);
    d.load('model/').then(() => setReady(true)).catch((e) => setErr(`3D 模型没加载：${e.message}`));
    return () => d.dispose();
  }, []);

  useEffect(() => {
    const d = duckRef.current;
    if (!d || !ready) return;
    if (Array.isArray(joints)) d.setJoints(joints);
    d.setGravity(g);
  }, [g, joints, ready]);

  const viewKey = JSON.stringify(view);
  useEffect(() => {
    if (!ready || !duckRef.current) return;
    applyView(duckRef.current, view);
    setMoved(false);
  }, [ready, viewKey]);

  useEffect(() => {
    if (!ready) return undefined;
    if (!arrow && !plumb) { if (svgRef.current) svgRef.current.innerHTML = ''; return undefined; }
    let raf = 0;
    const tick = (now) => { drawOverlay(duckRef.current, canvasRef.current, svgRef.current, arrow, plumb, now || 0); raf = requestAnimationFrame(tick); };
    tick(performance.now());
    return () => cancelAnimationFrame(raf);
  }, [ready, arrow, plumb]);

  return html`<div class="imu-view">
    <canvas ref=${canvasRef} class=${stale ? 'stale' : ''}></canvas>
    <svg class="imu-overlay" ref=${svgRef} aria-hidden="true"></svg>
    ${err ? html`<span class="imu-note" role="alert">${err}</span>` : children}
    ${moved ? html`<button class="reset-view" onClick=${(e) => { e.currentTarget.blur(); duckRef.current?.resetView(); setMoved(false); }}>回正</button>` : null}
  </div>`;
}

/** Normally one duck (with the demonstration arrow while capturing); after computing, "before calibration / after calibration" left and right. The first one is always the same instance (key unchanged), so switching does not reload.
 *  Camera: while capturing, view from behind (the duck's left = screen left = the steering wheel's left = the left of a person standing behind it);
 *  when comparing, view from the side if the correction is mainly forward/back (forward and backward tilt cannot be seen from the front), and from the front if it is mainly left/right. */
function ImuStage({ st, stale, corr, parts, collecting, arrow, cue }) {
  const g = okVec(st?.gravity) ? st.gravity : null;
  const joints = st?.joints;
  const after = g && corr ? qRotate(corr, g) : null;
  const tb = g ? angle(g, DOWN) : null, ta = after ? angle(after, DOWN) : null;
  const old = stale || !g;
  const sideways = corr && Math.abs(parts?.pitch_deg ?? 0) >= Math.abs(parts?.roll_deg ?? 0);
  const view = corr ? (sideways ? { az: -80, el: 6 } : 'front') : collecting ? 'back34' : 'front34';
  const noteLive = old ? html`<span class="imu-note">${g ? '读数旧了，不是现在的样子' : '没有姿态数据'} · 主程序在运动模式时才有</span>`
    : html`<span class="imu-note">实时 · 机身跟着 IMU 倾</span>`;
  return html`<div class="imu-stage-wrap">
    <div class=${'imu-stage' + (corr ? ' duo' : '')}>
      <${DuckView} key="before" g=${g} joints=${joints} stale=${old} arrow=${corr ? null : arrow} plumb=${!!corr} view=${view}>
        <div class="imu-stage-read num"><span>${corr ? '校准前' : '机身倾角（跟竖直比）'}</span><b>${fmt(tb)}°</b></div>
        ${!corr && cue ? html`<span class="imu-cue">${cue}</span>` : null}
        ${corr ? html`<span class="imu-note">现在存的方向</span>` : noteLive}
      <//>
      ${corr ? html`<${DuckView} key="after" g=${after} joints=${joints} stale=${old} plumb=${true} view=${view}>
        <div class="imu-stage-read num after"><span>校准后</span><b>${fmt(ta)}°</b></div>
        <span class="imu-note">按新方向 · 还没写</span>
      <//>` : null}
    </div>
    ${corr ? html`<p class="imu-diff num">站着的时候：校准前倾 <b>${fmt(tb)}°</b> → 校准后 <b>${fmt(ta)}°</b>，差 <b>${fmt(g && after ? angle(g, after) : null)}°</b>。
      两只鸭子都是现在的实时读数，虚线是竖直方向；${sideways ? '从侧面看（这次主要是前后歪）' : '从正面看（这次主要是左右歪）'}。</p>` : null}
  </div>`;
}

// ---------------- Steering wheel: four dots for forward/back/left/right + still in the middle; finished ones light up, the next one blinks, the blue dot is where it is tilting now ----------------

function DirPad({ W }) {
  const C = 100, R = 80, MAX = 32;
  const r = (t) => Math.min(t, MAX) / MAX * R;
  const pt = (t, d) => [C - r(t) * Math.sin(rad(d)), C - r(t) * Math.cos(rad(d))];   // head up: forward → up, the duck's left → left
  const collecting = W.phase === 'collect';
  const next = collecting && W.done.still ? nextTodo(W) : null;
  const L = collecting && W.done.still ? W.live : null;
  const p = L && L.t != null ? pt(L.t, L.d ?? 0) : [C, C];
  const ring = (t) => html`<circle cx=${C} cy=${C} r=${r(t)} class="pad-ring" />`;
  return html`<svg class="imu-pad" viewBox="0 0 200 200" role="img"
    aria-label=${`已做：${names(STEPS.filter((k) => W.done[k])) || '还没有'}`}>
    <circle cx=${C} cy=${C} r=${R + 6} class="pad-bg" />
    ${ring(RULES.tilt_go_deg)}${ring(RULES.tilt_max_deg)}
    ${TILTS.map((k) => {
      const [x, y] = pt(20, STEP[k].dir), [lx, ly] = pt(33, STEP[k].dir);
      const cls = W.done[k] ? 'done' : k === next ? 'next' : (k === W.cand && W.inZone ? 'hot' : '');
      return html`<g class=${'pad-dot ' + cls}><circle cx=${x} cy=${y} r="13" />
        ${W.done[k] ? html`<path d=${`M${x - 5.5},${y} l4,4 l7,-8`} class="tick" />` : null}
        <text x=${lx} y=${ly + 4} class="pad-lbl">${STEP[k].short}</text></g>`;
    })}
    <g class=${'pad-dot center ' + (W.done.still ? 'done' : collecting ? 'next' : '')}>
      <circle cx=${C} cy=${C} r="11" />
      ${W.done.still ? html`<path d=${`M${C - 5},${C} l3.5,3.5 l6.5,-7.5`} class="tick" />` : null}
    </g>
    ${L && W.hold > 0 ? html`<circle cx=${p[0]} cy=${p[1]} r="12" class="pad-hold"
      style=${`stroke-dasharray:${(W.hold * 75.4).toFixed(1)} 76`} transform=${`rotate(-90 ${p[0]} ${p[1]})`} />` : null}
    ${L ? html`<circle cx=${p[0]} cy=${p[1]} r="6" class=${'pad-live' + (W.over ? ' over' : W.inZone ? ' on' : '')} />` : null}
  </svg>`;
}

// ---------------- The blocks on the right ----------------

// Whether the orientation is confirmed: only trust mount.verified in the imu message (read back from calibration-status, the view in studio/imu.py).
// Do not look at robotd's raw message when it fails to start: when joints are uncalibrated it also reports "…and verified IMU mounting" (feetech.rs:1018-1029).
// The main program only has two states, "confirmed / not confirmed"; a "temporary orientation" is something Studio may add later (decision 3, option ②), shown only if the backend sends imu.temporary.
function statusOf(st, imu, live) {
  const s = st?.imu?.status;
  const v = imu?.mount?.verified;
  if (imu?.profile_error) return { word: 'IMU 类型无法确认', kind: 'bad', hint: imu.profile_error };
  if (imu?.mount_protocol_mismatch) return { word: '方向需重新标定', kind: 'warn',
    hint: '当前总线协议 / 类型与已存的安装方向不匹配：在下面重新标定，并交给主程序验证' };
  if (v === false) {
    return { word: '方向没确认', kind: 'warn',
      hint: st?.posture === 'starting' ? '主程序不让进运动模式（站不起来）：先粗校一次' : '装歪了走路会往前冲：先校准' };
  }
  if (imu?.temporary) return { word: '临时方向', kind: 'warn', hint: '只认了哪边朝上，朝前没验过：能站，别走' };
  if (live !== false && s === 'missing') return { word: '读不到 IMU', kind: 'bad', hint: '检查模块接线，或者在下面重新识别芯片' };
  if (live !== false && s === 'frozen') return { word: '读数冻住了', kind: 'bad', hint: '姿态不更新，别走路' };
  // Before the imu message arrives: in motion mode, a working IMU means the orientation was confirmed (robotd cannot enter motion mode without confirmation)
  if (v === true || (v == null && s === 'ok' && st?.mode === 'motion')) {
    const when = imu?.stand_calib_at;
    return { word: '方向已确认', kind: 'ok', hint: when ? `上次站着校准：${when}` : '主程序验过「哪边朝上、哪边朝前」；还没站着校过站姿' };
  }
  return { word: '不知道', kind: null, hint: '还没读到主程序存的安装方向' };
}

function freshText(st, live, age) {
  if (live === false) return { live: false, text: Number.isFinite(age) ? `${Math.round(age / 1000)} 秒没更新` : '连不上鸭子' };
  const a = st?.joints_age_ms;
  if (a == null) return { live: false, text: '没有' };
  if (a >= RULES.stale_ms) return { live: false, text: `${Math.round(a / 1000)} 秒没更新` };
  return { live: true, text: `实时 · ${(a / 1000).toFixed(1)} 秒前` };
}

function StatusCard({ st, imu, live, age, diagnosticElapsed }) {
  const S = statusOf(st, imu, live);
  const F = freshText(st, live, age);
  const src = imu?.source;
  const guard = st?.guard;
  return html`<section class=${'board imu-card' + (F.live ? '' : ' imu-stale')}>
    <h3>控制与安装方向${F.live ? '' : html` <span class="sv-small">（姿态读数：${F.text}）</span>`}</h3>
    <div class="imu-kv">
      <span>方向</span><b class=${'imu-word ' + (S.kind || '')}>${S.kind === 'warn' || S.kind === 'bad' ? html`<span class=${'badge ' + S.kind}>${S.kind === 'bad' ? '×' : '!'}</span>` : S.kind === 'ok' ? '✓ ' : ''}${S.word}</b>
      <span></span><span class="sv-small">${S.hint}</span>
      <span>芯片</span><b>${chipLabel(imu, live, diagnosticElapsed)}</b>
      ${src === 'bus' ? html`<span>配置类型</span><b>${imu?.configured_imu_profile === 'qinmo' ? 'Qinmo（已配置）'
        : imu?.configured_imu_profile === 'legacy' ? '现有板卡自动识别'
        : imu?.metadata_error || unsupportedTransport(imu?.imu_bus) ? '待确认（诊断数据不受支持）'
        : imu?.configured_imu_profile != null ? '不支持的类型（需确认）' : '现有板卡（旧版主程序）'}</b>
        <span>实际连接</span><b>${imuDiagnosticCopy(imu?.diagnostic, live, diagnosticElapsed).board || (imu?.imu_bus ? chipLabel(imu, live, diagnosticElapsed) : '尚未连接')}</b>
        <span>角速度单位</span><b class="num">${imu?.profile_error || unsupportedTransport(imu?.imu_bus) ? '待确认（诊断数据不受支持）'
          : imu?.imu_bus?.profile === 'qinmo' ? '原始值 ÷ 16.4 °/s'
          : imu?.imu_bus ? '原始值 × 0.0175 °/s' : '连接后显示'}</b>` : null}
      <span>倾角</span><b class="num">${fmt(st?.tilt_deg)}°<small> 跟竖直比；主程序 ${guard?.tilt_tolerance_deg ?? 10}° 以内才让走</small></b>
      <span>站姿</span><b class="num">${st?.hold ? html`离 HOME 最多差 ${fmt(st.hold.max_error_deg)}°<small> 标定模式站姿使能${st.hold.stage === 'holding' ? '：站住了' : '：正在站起来'}</small>`
        : guard?.max_joint_error_deg != null ? html`离 HOME 最多差 ${fmt(guard.max_joint_error_deg)}°<small> ${guard.joint_tolerance_deg ?? 5}° 以内算站好</small>` : '—'}</b>
      <span>读数</span><b class=${'num' + (F.live ? '' : ' imu-dim')}>${F.text}${imu?.reader?.errors ? html`<small> 读错 ${imu.reader.errors} 次</small>` : null}</b>
    </div>
    ${src === 'bus' && imu?.imu_bus?.protocol === 'dxl2' ? html`<p class="sv-small">这类板卡不提供采样序号、状态位和传感器读数年龄；主程序按主机接收新鲜度和原始字节是否冻结检查读数。</p>` : null}
    ${imu?.mount?.quat ? html`<details class="imu-details"><summary>安装方向（四元数 w, x, y, z）</summary>
      <code class="num">${imu.mount.quat.map((x) => fmt(x, 4)).join(', ')}</code>${imu.mount.verified ? ' · 已验证' : ' · 没验证'}
      <p class="sv-small">装法改了或上次没调对，可以在下面「IMU 安装方向」重新标定、重新验证。</p></details>` : null}
  </section>`;
}

export function DiagnosticCard({ st, imu, live, diagnosticElapsed }) {
  const diagnostic = imu?.diagnostic || st?.imu?.diagnostic;
  if ((imu?.source ?? st?.imu?.source) !== 'bus' || (st?.posture !== 'starting' && !diagnostic?.age_ms
      && diagnostic?.responding == null)) return null;
  const d = imuDiagnosticCopy(diagnostic, live, diagnosticElapsed);
  return html`<section class="board imu-card imu-diagnostic" aria-label="总线 IMU 只读诊断">
    <h3>总线 IMU 只读诊断</h3>
    <p class=${'imu-word ' + d.kind}>${d.word}</p>
    ${d.board ? html`<p>${d.board}</p>` : null}
    <p class="sv-small">${d.hint}</p>
    ${live !== false && diagnostic?.error ? html`<p class="sv-small">原文：${diagnostic.error}</p>` : null}
    <p class="sv-small">板卡应答独立于舵机；不代表已确认安装方向、可采集标定或可运动。姿态和标定仍使用主程序的控制读数。</p>
  </section>`;
}

function ChipCard({ imu, link, live, diagnosticElapsed }) {
  const [profile, setProfile] = useState(imu?.configured_imu_profile || 'legacy');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  useEffect(() => { setProfile(imu?.configured_imu_profile || 'legacy'); }, [imu?.configured_imu_profile]);
  const selection = imu?.profile_selection;
  const reason = live === false || link.status !== 'open' ? '连不上鸭子：等它回来'
    : imu?.metadata_error || unsupportedTransport(imu?.imu_bus) ? imu?.metadata_error || imu?.profile_error || '主程序报告了不支持的 IMU 类型'
    : !selection?.can_start ? selection?.reason || '主程序尚不支持网页选择类型：请先由维护者更新主程序' : null;
  const select = async () => {
    setBusy(true); setMessage(null);
    try {
      const reply = await link.cmd('imu.op', { op: 'profile-select', profile, confirmed: true }, 180000);
      setMessage(reply.ok ? '类型已保存，正在重连标定模式。双手扶稳并保持卸力，完成上面的安装方向采集与主程序验证。'
        : reply.reason || reply.error || '类型选择未完成：查看会话状态，可取消并恢复原参数');
    } finally { setBusy(false); }
  };
  return html`<section class="board imu-card">
    <h3>芯片 <span class="sv-small">正在用：${chipLabel(imu, live, diagnosticElapsed)}</span></h3>
    <p class="sv-small">现有自动识别支持 FT6、IMU-to-DXL（Feetech）；SFLP 124/12（Dynamixel 2.0）。FT6 和自家小板按已知身份识别；通用 DXL2 只确认兼容布局。</p>
    <p class="sv-small">Qinmo 没有文档可验证的唯一身份，需在这里选择一次。保存后以后开机会沿用此类型与单位；页面显示「已配置」，不会把兼容布局当成厂商认证。换板或装法改变后，必须重新验证安装方向。</p>
    ${imu?.source === 'bus' || imu?.source == null ? html`<label class="sv-small">总线 IMU 类型
      <select aria-label="总线 IMU 类型" value=${profile} disabled=${busy || !!imu?.redo?.active}
        onChange=${e => { setProfile(e.target.value); setMessage(null); }}>
        <option value="legacy">自动识别（现有板卡）</option><option value="qinmo">Qinmo · Feetech · 原始值 ÷ 16.4 °/s</option>
      </select></label>
      <div class="imu-actions"><${TwoStep} key=${profile} label="保存类型并重新连接"
        ask="已扶稳，确认重连并重新标定" onConfirm=${select} disabled=${busy || !!reason}
        title=${reason} busyLabel="正在保存类型并重连…" /></div>
      <p class="sv-small">先扶稳并卸力。保存后主程序会重启进入标定模式，旧安装方向失效；验证通过后才完成。取消可恢复原参数；启动失败恢复时会停留标定模式。</p>
      ${reason ? html`<p class="sv-warn">${reason}</p>` : null}
      ${message ? html`<p role="status" class="sv-small">${message}</p>` : null}` : null}
    <p class="sv-small">I²C 模块要在第一次开机前接好。之后才接的，用 SSH 在鸭子上运行</p>
    <p><code class="num">sudo microduck-firstboot --detect-imu-only --force</code></p>
    <p class="sv-small">它会重新检测 IMU 并补上启动配置；跑完重启一次主程序。</p>
  </section>`;
}

function blockReason(st, imu, live) {
  if (!st) return '还没连上鸭子';
  if (live === false) return '连不上鸭子：等它回来';
  if (imu?.profile_error) return imu.profile_error;
  if (imu?.redo?.active) return '正在重新标定安装方向：先完成主程序验证，或取消并恢复原参数';
  if (st.posture === 'servo_session') return '舵机页还占着总线（有舵机保持着时不会自动交还）：点顶上的「交还主程序」';
  if (st.posture === 'absent') return '鸭子主程序没在跑';
  if (st.posture === 'starting') return `主程序还在启动${st.start_error ? `：${st.start_error}` : ''}`;
  if (st.mode === 'commissioning') {
    // Calibration mode can also stand (fork hold-home, user 10-21): once standing it can be calibrated standing, even if the orientation was never confirmed (it computes a whole new orientation, written in step 3)
    if (!st.hold) return '标定模式软着：先点上面的「站姿使能」让它站起来（双手扶着）';
    if (st.hold.stage !== 'holding') return '正在站起来：等它站稳';
    if (!okVec(st.gravity) || st.joints_age_ms == null || st.joints_age_ms > RULES.stale_ms) return '没有实时姿态数据';
    return null;
  }
  if (imu?.mount?.verified === false) return '方向还没确认过：先做上面的「粗校」';
  // Standing pose not enabled: prompt to click "Enable standing" above first (task 17)
  if (st.posture === 'limp') return '软着：先点上面的「站姿使能」让它站起来（双手托着）';
  if (st.posture === 'homing') return '正在站起来：等它站稳';
  if (st.posture === 'walking') return '正在走：先停下';
  if (st.posture === 'policy') return '策略在跑，一提起来它会迈腿：按一下手柄 +，回到「站好」再做';
  if (st.posture === 'sitting') return '坐着：先点上面的「站姿使能」让它站起来';
  if (st.posture !== 'holding') return '读不出它现在的姿势';
  if (!okVec(st.gravity) || st.joints_age_ms == null || st.joints_age_ms > RULES.stale_ms) return '没有实时姿态数据';
  if (st.imu?.status === 'missing' || st.imu?.status === 'frozen') return 'IMU 读数不正常，先查线';
  return null;
}

// ---------------- Enable / disable standing (task 17, user 10-21: "there has to be a button to enable and disable standing") ----------------
// "Enable standing" takes the same path as the remote-control card's "Stand up": link.cmd('pad.op', {op: 'stand'}), and the backend re-checks by posture (limp → robot.init, sitting → sit_toggle);
// whether it can be pressed follows the judgment for the remote-control card's "Stand up" button in the gamepad snapshot (pd.motion.buttons.stand). "Disable (relax)" takes the same path as "Relax" at the top: link.cmd('relax').
// Calibration mode can also stand (user 10-21: "wouldn't it be fine if calibration could also do the standing pose? Why must we switch to motion mode"): "Enable standing" sends imu.op hold →
// hold-home in fork calibration mode, all 15 servos move to HOME together over 3 seconds and lock (no balancing, hold onto it), the IMU reads as usual, and standing calibration is done in calibration mode;
// "Disable" likewise goes through "Relax" at the top (in calibration mode robot.relax is just a bus relax).
const POSE_CN = { holding: '站着', policy: '站着（策略在跑）', walking: '在走', limp: '软着', homing: '正在站起来',
  sitting: '坐着', commissioning: '标定模式（软着）', starting: '主程序在启动', absent: '主程序没在跑', servo_session: '调舵机中' };
const HOLD_CN = { holding: '标定模式（站着）', ramping: '标定模式（正在站起来）' };
const HOLD_CONFIRM = '标定模式站姿使能：15 颗舵机会在 3 秒内一起转到站姿并锁住。\n'
  + '标定模式不管平衡，站起来以后要扶着点；方向用舵机页设的（没设过的沿用主程序文件里的）。\n双手扶好鸭子，确定吗？';

function StanceCard({ st, imu, pd, link, live }) {
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const commissioning = (st?.mode || imu?.mode) === 'commissioning';
  const hold = st?.hold || imu?.hold || null;
  const now = !st ? '还没连上' : live === false ? '连不上鸭子' : st.posture === 'servo_session' ? POSE_CN.servo_session
    : commissioning && hold ? HOLD_CN[hold.stage] || '标定模式（站着）' : (POSE_CN[st.posture] || '读不出');
  const sb = pd?.motion?.buttons?.stand;              // the remote-control card's "Stand up" judgment (the gamepad snapshot pushed by the backend; 1 Hz is enough)
  const standWhy = !st || live === false ? '连不上鸭子：等它回来'
    : imu?.redo?.active ? '重新标定方向期间保持卸力：双手托住，完成或取消后再站起来'
    : st.posture === 'servo_session' ? '舵机页还占着总线：点顶上的「交还主程序」'
      : st.posture === 'starting' ? '主程序还在启动：等它起来'
        : commissioning ? (hold ? (hold.stage === 'holding' ? '已经站着了' : '正在站起来') : null)
          : sb && !sb.ok ? sb.why : null;
  const stand = async () => {
    if (commissioning) {
      if (!window.confirm(HOLD_CONFIRM)) return;
      setBusy(true); setMsg(null);
      const r = await link.cmd('imu.op', { op: 'hold' }, 25000);
      setBusy(false);
      setMsg(r.ok ? { ok: true, text: '站姿已保持。校准期间持续扶稳，结束后点右上角「全局卸力」。' }
        : { ok: false, text: r.reason || r.error || '没站起来' });
      return;
    }
    if (typeof st?.tilt_deg === 'number' && st.tilt_deg > 30
      && !window.confirm(`它现在是躺着的（倾斜 ${Math.round(st.tilt_deg)}°）。站起来时腿会突然用力：确定托好了吗？`)) return;
    setBusy(true); setMsg(null);
    const r = await link.cmd('pad.op', { op: 'stand' }, 10000);
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: '站起来发出去了：双手托着它，站稳了再开始站着校准' } : { ok: false, text: r.reason || r.error || '没站起来' });
  };
  return html`<section class="board imu-card imu-stance">
    <h3>站姿 <span class="sv-small">站着校准要它先站住</span></h3>
    <div class="imu-actions">
      <button class="btn-dark imu-stand" disabled=${!!standWhy || busy} onClick=${stand}
        title=${standWhy || '跟遥控卡上的「站起来」同一条路'}>${busy ? '等它回话…' : '站姿使能'}</button>
      <span class="sv-small imu-stance-now">现在：<b>${now}</b></span>
    </div>
    ${standWhy ? html`<p class="sv-small imu-stance-why">${standWhy}</p>` : null}
    ${imu?.redo?.active ? null : commissioning
      ? html`<p class="sv-small">15 颗舵机转到站姿并锁住，不提供平衡。持续扶稳，结束后点右上角「全局卸力」。</p>`
      : standWhy ? null
        : html`<p class="sv-small">站姿使能与遥控「站起来」相同。持续扶稳，结束后点右上角「全局卸力」。</p>`}
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span></div>` : null}
  </section>`;
}

/** What to tell the person at this moment during capture (large text) + one supplementary line (small text). */
function collectWords(W) {
  if (W.paused) return [W.paused, ''];
  if (!W.done.still) {
    return [W.moved ? '动了一下，重新数' : '放在平桌上，松手，别碰它',
      `鸭子自己站着的这 3 秒就是「官方站姿」的参照 · 还要 ${Math.max(0, RULES.still_s * (1 - W.progress)).toFixed(1)} 秒`];
  }
  const next = nextTodo(W);
  const n = next ? STEP[next] : null;
  const tip = n ? `双手捏住躯干两侧提起来一点（脚离桌 2–3 cm），端平停半秒，再往${n.short}倾（${n.how}）15° 左右，停 1 秒。顺序随便` : '';
  if (W.over) return ['太多了，回一点', tip];
  if (W.repeat) return [`${STEP[W.repeat].cn}已经记下了`, `放回端平，做${next ? STEP[next].cn : '下一个'}`];
  if (W.needLevel) return ['先端平停一下', '零点没记上：每次倾之前，端平停半秒'];
  if (W.inZone && W.cand) return [`${STEP[W.cand].cn}：停住…`, '再停一下就记下了'];
  return [n ? `下一个：${n.cn}` : '都齐了', tip];
}

function CollectCard({ st, imu, live, W, act, muted, setMuted }) {
  const block = blockReason(st, imu, live);
  const ph = W.phase;
  const guardErr = st?.guard?.max_joint_error_deg;
  const res = W.result;
  const mute = html`<label class="imu-mute" title="做够一个方向时响一声"><input type="checkbox" checked=${muted}
    onChange=${(e) => setMuted(e.target.checked)} /> 静音</label>`;
  let button;
  if (ph === 'collect') button = html`<button class="imu-big rec" onClick=${act.end}><span class="rec-dot"></span>采集中…（点这里结束）</button>`;
  else if (ph === 'solving') button = html`<button class="imu-big" disabled>正在算…</button>`;
  else if (ph === 'short') button = html`<button class="imu-big" onClick=${act.resume}>接着采</button>`;
  else button = html`<button class="imu-big" disabled=${!!block} onClick=${act.start}>${ph === 'idle' ? '开始采集' : '重新采集'}</button>`;
  const [say, sub] = ph === 'collect' ? collectWords(W) : ['', ''];
  return html`<section class="board imu-card imu-collect">
    <h3>站着校准 <span class="sv-small">约 1 分钟 · 两只手</span>${mute}</h3>
    ${ph === 'idle' ? html`<details class="imu-instructions"><summary>采集步骤</summary><ol class="imu-howto">
      <li>鸭子站好（点上面的「站姿使能」或者按手柄 +，别开走路），点「开始采集」。</li>
      <li>放在平桌上，<b>别碰它 3 秒</b>。</li>
      <li>站到鸭子后面（跟它朝一个方向，它的左就是你的左），双手捏住躯干两侧提起来，<b>前、后、左、右各倾一次</b>：
        每次先端平停半秒，再倾 15° 左右停 1 秒。顺序随便，3D 上的箭头会示范。</li>
      <li>做够一个方向那个点就亮、响一声；四个都亮了自动结束、自动算。</li>
    </ol></details>` : null}
    ${ph === 'collect' || ph === 'solving' || ph === 'short' ? html`<div class="imu-live">
      <${DirPad} W=${W} />
      <div class="imu-live-txt">
        ${ph === 'collect' ? html`<p class="imu-say"><b>${say}</b><br /><span class="sv-small">${sub}</span></p>
          ${!W.done.still ? html`<div class="imu-bar" aria-label="静止进度"><span style=${{ width: `${Math.round(W.progress * 100)}%` }}></span></div>`
            : html`<p class="imu-tilt num"><b>${fmt(W.live?.t)}°</b><span>离端平那一下</span></p>`}`
        : ph === 'solving' ? html`<p class="imu-say"><b>采完了，正在算…</b></p>`
          : html`<p class="imu-say"><b>还差：${names(W.missing)}</b><br />
            <span class="sv-small">做过的都留着。点「接着采」把${names(W.missing)}补上；不想要这一遍就「重来」。</span></p>`}
      </div>
    </div>` : null}
    ${ph === 'error' ? html`<div class="banner bad" role="alert"><b>没算成</b><span class="more">${W.error}</span></div>` : null}
    ${ph === 'done' && res && !res.ok ? html`<p class="sv-warn">没校成，原因和要补做哪步在下面「结果」里。</p>` : null}
    ${block && ph !== 'solving' ? html`<p class="sv-warn">${block}</p>`
      : ph === 'idle' && guardErr != null && guardErr > 5 ? html`<p class="sv-warn">腿离 HOME 还差 ${fmt(guardErr)}°：站姿不准，补偿也会跟着不准。先把舵机零位校好</p>` : null}
    <div class="imu-actions">${button}
      ${ph === 'short' || ph === 'collect' ? html`<button class="btn-light" onClick=${act.start} disabled=${!!block && ph !== 'collect'}>重来</button>` : null}</div>
  </section>`;
}

const GRADE = { good: ['好', 'ok'], ok: ['能用', 'warn'], coarse: ['粗校', 'warn'] };

function ResultCard({ res, imu, link, onRedo }) {
  const [checks, setChecks] = useState({});
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);
  useEffect(() => { setChecks({}); setOut(null); }, [res]);
  if (!res) return null;
  const P = res.parts || {}, Q = res.quality || {}, R = res.rules || {};
  const confirms = res.confirm || [];
  const allChecked = confirms.every((_, i) => checks[i]);
  const [gw, gk] = GRADE[Q.grade] || ['—', ''];
  const redo = (res.redo || []).filter((k) => STEP[k]);
  const save = () => {
    // The backend keeps this result pending; only the shared commit dialog writes it.
    setOut({ ok: true, text: '校准结果已记录，请预览后统一写进主程序。' });
    window.dispatchEvent(new Event('console:commit'));
  };
  const detail = html`<table class="imu-table num">
      <thead><tr><th>步骤</th><th class="r">倾了</th><th class="r">斜了</th><th class="r">晃</th><th></th></tr></thead>
      <tbody>${STEPS.map((k) => { const s = (res.steps || {})[k] || {}; return html`<tr class=${s.ok === false ? 'bad' : ''}
        title=${s.ref ? `零点：${s.ref}${s.ref_offset_deg != null ? `（离桌上静止 ${fmt(s.ref_offset_deg)}°）` : ''}` : ''}>
        <td>${STEP[k].cn}</td><td class="r">${k === 'still' ? '—' : `${fmt(s.tilt_deg, 0)}°`}</td>
        <td class="r">${s.skew_deg != null ? `${fmt(s.skew_deg, 0)}°` : '—'}</td><td class="r">${s.spread_deg != null ? `${fmt(s.spread_deg)}°` : '—'}</td>
        <td>${s.ok ? '✓' : s.msg || (s.ok === false ? '×' : '')}</td></tr>`; })}</tbody>
    </table>
    ${res.ok && Q.grade !== 'coarse' ? html`<p class="sv-small">自检：前后两次差 ${fmt(Q.fb_pair_deg)}°、左右两次差 ${fmt(Q.lr_pair_deg)}°、前后和左右差 ${fmt(Q.cross_deg)}°、
      最斜的一步 ${fmt(Q.max_skew_deg)}°（越小越好；每步斜 ≤${R.good_skew_deg ?? 10}°、两对差 ≤${R.good_cross_deg ?? 6}° 评「好」，
      斜 >${R.skew_max_deg ?? 20}° 或两对差 >${R.cross_max_deg ?? 12}° 判失败）</p>` : null}
    ${res.standard ? html`<p class="sv-small">新方向：${res.standard.text}${res.standard.off_deg > 0.5 ? `（再偏 ${fmt(res.standard.off_deg)}°）` : ''}</p>` : null}
    ${res.mount ? html`<details class="imu-details"><summary>新安装方向（四元数 w, x, y, z）</summary><code class="num">${res.mount.map((x) => fmt(x, 6)).join(', ')}</code></details>` : null}`;
  return html`<section class="board imu-card">
    <h3>结果 ${res.ok ? html`<span class=${'imu-grade ' + gk}>${gw}</span>` : html`<span class="imu-grade bad">没过</span>`}</h3>
    ${!res.ok ? html`<p class="sv-warn">${res.reason}</p>
      ${redo.length ? html`<div class="imu-actions"><button class="btn-dark" onClick=${() => onRedo(redo)}>补做${names(redo)}</button>
        <span class="sv-small">别的几步留着，只重做这${redo.length > 1 ? '几' : '一'}步</span></div>` : null}` : html`
      <div class="imu-parts num">
        <div><span>前后</span><b>${sgn(P.pitch_deg)}°</b><small>+ = 站着时读数前倾</small></div>
        <div><span>左右</span><b>${sgn(P.roll_deg)}°</b><small>+ = 左倾</small></div>
        <div><span>朝向</span><b>${sgn(P.yaw_deg)}°</b><small>绕竖直轴，站着看不出</small></div>
        <div><span>一共</span><b>${fmt(P.total_deg)}°</b><small>相对现在的方向</small></div>
      </div>`}
    ${res.check ? html`<p class=${res.check.ok ? 'sv-small imu-check' : 'sv-warn imu-check'}>${res.check.ok
      ? `✓ 跟主程序现在用的方向只差 ${fmt(res.check.diff_deg)}°、站姿倾斜 ${fmt(res.check.tilt_deg)}°：${res.check.recorded ? '记下了「核对过」（总览上手清单第 2 步）' : '够近，但没记上（看日志）'}`
      : `这次不算「核对过」：${res.check.why}`}</p>` : null}
    ${(res.notes || []).map((n) => html`<p class="sv-small">· ${n}</p>`)}
    ${res.ok ? html`<details class="imu-details"><summary>详细数据</summary>${detail}</details>` : detail}
    ${confirms.map((c, i) => html`<label class="imu-confirm"><input type="checkbox" checked=${!!checks[i]} onChange=${(e) => setChecks({ ...checks, [i]: e.target.checked })} /> ${c}</label>`)}
    ${res.ok ? html`<div class="imu-save">
      <button class="btn-dark" disabled=${!res.mount} onClick=${save}>去上手清单第 3 步</button>
      <span class="sv-small">这里只记下方向；第 3 步「写进主程序」才会重启主程序、切到运动模式</span>
    </div>` : null}
    ${!res.mount && res.ok ? html`<p class="sv-warn">算不出新方向（不知道现在的方向），不能写</p>` : null}
    ${out ? html`<div class=${'banner ' + (out.ok ? 'warn' : 'bad')} role="status"><b>${out.ok ? '写好了' : '没写成'}</b><span class="more">${out.text}</span></div>` : null}
  </section>`;
}

// Results of the fine standing calibration are first recorded in Studio (imu-pending.json); writing them into the main program is done uniformly in step 3 of the getting-started checklist.

// ---------------- Orientation not confirmed, cannot stand: coarse calibration first ----------------

function CoarseCard({ st, imu, link, live }) {
  const [opened, setOpened] = useState(false);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const mode = st?.mode || imu?.mode;
  const redo = imu?.redo || {};
  const context = imuContext(mode, imu);
  useEffect(() => { setOpened(false); setMsg(null); }, [context]);
  const open = link.status === 'open' && live !== false;
  const commissioning = mode === 'commissioning';
  const verified = imu?.mount?.verified === true;
  const working = !!(imu?.job && !imu.job.done && !imu.job.failed);
  const canCollect = commissioning && !imu?.profile_error && (!redo.active || ['commissioning', 'finish_failed'].includes(redo.phase));
  const showSteps = canCollect && (!verified || opened || redo.active);
  const startWhy = !open ? '连不上鸭子：等它回来' : imu?.profile_error ? imu.profile_error : working ? '上一项操作还没结束'
    : commissioning ? null : !redo.can_start ? redo.reason || '暂时不能返回标定模式：先卸力并等待读数更新' : null;
  const run = async (op) => {
    setBusy(true); setMsg(null);
    const r = await link.cmd('imu.op', { op, confirmed: true }, 90000);
    setBusy(false);
    setMsg({ ok: r.ok, text: r.ok ? r.data?.note || (op === 'redo-start'
      ? '已回到标定模式，保持卸力，双手托住鸭子开始采集。' : '已取消，原来的安装方向和模式已恢复。')
      : r.reason || r.error || '操作没完成：查看当前状态后重试' });
  };
  const start = async () => {
    if (startWhy || busy) return;
    if (commissioning) { setMsg(null); setOpened(true); }
    else await run('redo-start');
  };
  return html`<section class="board imu-card imu-coarse">
    <h3>IMU 安装方向 <span class="sv-small">${redo.active ? '重标定未结束' : verified ? '已保存，可重新校验' : '第一次标定'}</span></h3>
    <p class="sv-small">先采静止和前倾，计算安装方向（四元数），再由主程序验证。装法改了或上次没调对，都可以重新做。</p>
    ${imu?.mount_protocol_mismatch ? html`<p class="sv-warn">总线协议与已存安装方向不匹配：需要重新标定；主程序验证通过后才确认这份方向。</p>` : null}
    ${redo.active ? html`<p class="sv-warn">${canCollect
      ? '本次重标定还没完成：双手托住鸭子，保持卸力。验证通过后会恢复原模式；也可以取消并恢复原参数。'
      : '正在切换或恢复标定会话，请等当前操作结束；如未能恢复，可以取消并恢复原参数。'}</p>
      <div class="imu-actions"><${TwoStep} label="取消并恢复原参数" ask="扶好鸭子，确认恢复原方向和模式？"
        disabled=${!open || busy || working}
        onConfirm=${() => run('redo-cancel')} busyLabel="正在恢复…" /></div>` : null}
    ${!showSteps && !redo.active ? html`<div class="imu-actions"><${TwoStep}
      label="重新标定方向" ask=${commissioning ? '扶好鸭子，确认重新采集？' : '扶好并已卸力，确认重启并进入标定模式？'}
      cls="btn-dark" disabled=${!!startWhy || busy} title=${startWhy} onConfirm=${start} busyLabel="正在进入标定模式…" /></div>
      <p class="sv-small">${commissioning
        ? '双手扶稳，可卸力托住，也可站姿使能后等站稳，再重新采集。'
        : '重新标定前先扶稳鸭子，点右上角「全局卸力」。进入和完成时会重启主程序，并备份原 IMU 方向。'}保留舵机零位、方向和限位；验证通过才采用新方向。</p>
      ${startWhy ? html`<p class="sv-warn">${startWhy}</p>` : null}` : null}
    ${showSteps ? html`<${CoarseSteps} key=${context} link=${link} disabled=${!open || busy || working} unloadedOnly=${!!redo.active}
      onBegin=${() => setOpened(true)} onDone=${(text) => setMsg({ ok: true, text })} />` : null}
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span></div>` : null}
  </section>`;
}

function CoarseSteps({ link, disabled, unloadedOnly, onBegin, onDone }) {
  const [step, setStep] = useState('idle');       // idle / still / fwd / confirm / verifying / done / failed
  const [still, setStill] = useState(null);
  const [res, setRes] = useState(null);
  const [checks, setChecks] = useState({});
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const grab = async (phase, seconds) => {
    if (disabled || busy) return null;
    onBegin();
    setBusy(true); setOut(null);
    const r = await link.cmd('imu.op', { op: 'coarse-capture', phase, seconds }, 15000);
    if (!alive.current) return null;
    setBusy(false);
    if (!r.ok) { setOut({ ok: false, text: r.reason || r.error || '没采到读数' }); return null; }
    return r.data || {};
  };
  const takeStill = async () => {
    const d = await grab('still', 3);
    if (!d) return;
    setStill(d); setStep('fwd');
    setOut({ ok: true, text: `静止采到 ${d.n} 个读数。现在往前低头 15–30°，停住再点下一步。` });
  };
  const takeFwd = async () => {
    const d = await grab('fwd', 3);
    if (!d) return;
    const samples = [...((still && still.samples) || []), ...(d.samples || [])];
    setBusy(true);
    const r = await link.cmd('imu.op', { op: 'solve', mode: 'coarse', frame: 'body', samples }, 20000);
    if (!alive.current) return;
    setBusy(false);
    if (!r.ok || !r.data || r.data.ok !== true) {
      setStep('failed');
      setOut({ ok: false, text: r.reason || (r.data && r.data.reason) || r.error || '算不出方向' });
      return;
    }
    setRes(r.data); setStep('confirm');
    setOut({ ok: true, text: '方向算出来了：对照模块实际装法勾一下，再交给主程序验证。' });
  };
  const reset = () => { setStep('idle'); setStill(null); setRes(null); setChecks({}); setOut(null); };
  const verify = async () => {
    if (disabled || busy || !res?.mount) return;
    setBusy(true); setStep('verifying'); setOut(null);
    const r = await link.cmd('imu.op', { op: 'verify', confirmed: true, mount_wxyz: res.mount }, 90000);
    if (!alive.current) return;
    if (r.ok) onDone(r.data?.note || '主程序验证通过，安装方向已经保存。');
    setBusy(false);
    if (r.ok) { setStep('done'); setOut({ ok: true, text: (r.data && r.data.note) || '主程序验证通过，安装方向已经写进标定文件' }); }
    else { setStep('failed'); setOut({ ok: false, text: r.reason || r.error || '主程序没通过验证' }); }
  };
  const confirms = (res && res.confirm) || [];
  const allChecked = confirms.every((_, i) => checks[i]);
  const nowStep = step === 'idle' ? 'still' : step;
  return html`<div class="imu-coarse-steps">
    <p class="sv-small">${unloadedOnly
      ? '本次重标定会话要恢复原来的运行模式：保持失能（卸力），双手托住鸭子。'
      : '粗校在标定模式做：可先点「站姿使能」，等站稳后双手扶住；也可失能（卸力）后双手托住。站姿使能只锁住关节，需要一直扶稳。'}
      先把整个鸭子摆正、别动，采 3 秒；再让整个躯干前倾 15–30° 停住，采 3 秒；电脑算出方向，再交给主程序自己验一遍。</p>
    ${nowStep === 'still' ? html`<div class="imu-coarse-step">
      <p class="imu-say"><b>① 扶住鸭子，摆正，别动</b></p>
      <p class="sv-small">双手扶住躯干，让实物站直、脚朝下，保持不动；已站姿使能的先等站稳。屏幕仍按旧方向显示，先以实物摆正为准。</p>
      <button class="btn-dark" disabled=${busy || disabled} onClick=${takeStill}>${busy ? '采集中…' : '采静止（3 秒）'}</button>
    </div>` : null}
    ${nowStep === 'fwd' ? html`<div class="imu-coarse-step">
      <p class="imu-say"><b>② 往前低头 15–30°，停住</b></p>
      <p class="sv-small">托住整个躯干往前倾，头那边往下，慢慢低到 15–30°，保持不动 3 秒。不要只转头，也不要往左右歪。</p>
      <div class="imu-actions">
        <button class="btn-dark" disabled=${busy || disabled} onClick=${takeFwd}>${busy ? '采集 / 计算中…' : '采前倾（3 秒）'}</button>
        <button class="btn-light" disabled=${busy || disabled} onClick=${takeStill}>重采静止</button>
      </div>
    </div>` : null}
    ${nowStep === 'confirm' && res ? html`<div class="imu-coarse-step">
      <p class="sv-small">粗校算出来：${res.standard ? `${res.standard.text}${res.standard.off_deg > 0.5 ? `（再偏 ${fmt(res.standard.off_deg)}°）` : ''}` : '方向已算出'}。
        这次只采静止和前倾，左右还没验；之后再做下面的「站着校准」精校一次。</p>
      ${(res.notes || []).map((n) => html`<p class="sv-small">· ${n}</p>`)}
      ${confirms.map((c, i) => html`<label class="imu-confirm"><input type="checkbox" checked=${!!checks[i]}
        onChange=${(e) => setChecks({ ...checks, [i]: e.target.checked })} /> ${c}</label>`)}
      <div class="imu-actions">
        <button class="btn-dark" disabled=${busy || disabled || !res.mount || !allChecked} onClick=${verify}>交给主程序验证</button>
        <button class="btn-light" disabled=${busy} onClick=${reset}>重做</button>
      </div>
      <p class="sv-small"><b>点击验证前，先把实物回正并停住。</b>点了以后，再按提示在 20 秒内往前倾 15–30° 并停住。</p>
    </div>` : null}
    ${nowStep === 'verifying' ? html`<div class="imu-coarse-step">
      <p class="imu-say"><b>按主程序提示，在 20 秒内往前倾 15–30°</b></p>
      <p class="sv-small">保持双手托住。主程序会先检查摆正，再检查前倾；验证成功后会保存，重标定会话还需等原模式恢复完毕。</p>
    </div>` : null}
    ${nowStep === 'done' ? html`<p class="sv-small">主程序验证通过，方向已经写进标定文件。下面「站着校准」还可以再精校一次。</p>` : null}
    ${nowStep === 'failed' ? html`<div class="imu-actions">
      <button class="btn-dark" onClick=${reset}>重做</button>
      <span class="sv-small">按下面的具体原因处理；重标定会话可以取消并恢复原参数。</span>
    </div>` : null}
    ${out ? html`<div class=${'banner ' + (out.ok ? 'warn' : 'bad')} role="status"><span>${out.text}</span></div>` : null}
  </div>`;
}

// ---------------- What the backend is doing (coarse calibration, writing, switching chips): reported step by step to the page ----------------
// imu.job = { kind: 'coarse'|'save'|'set_chip'|'detect', title, msg, tilt_deg?, target_deg?, hold?, failed?, done? }
// The steps where the duck is held by hand (level ≤5°, nose down 15–30°) need to watch the tilt angle, so tilt_deg is shown large

function JobBanner({ job }) {
  if (!job) return null;
  const kind = job.failed ? 'bad' : 'warn';
  return html`<div class=${'banner imu-job ' + kind} role="status" aria-live="polite">
    <b>${job.title || '在做'}</b><span class="more">${job.msg || ''}</span>
    ${job.tilt_deg != null ? html`<span class="imu-job-tilt num">${fmt(job.tilt_deg)}°${job.target_deg ? html`<small> / ${job.target_deg}</small>` : null}</span>` : null}
    ${job.hold != null && !job.done ? html`<span class="imu-bar small"><span style=${{ width: `${Math.round(Math.min(1, job.hold) * 100)}%` }}></span></span>` : null}
  </div>`;
}

// For tests (feed a series of readings without a browser to see how capture proceeds)
export const _test = { RULES, STEPS, TILTS, feed, freshWizard, startCollect, endCollect, resumeCollect, redoSteps,
  missingSteps, payload, findHold, findRef, spreadP90, tiltOf, qRotate };

// ---------------- Page ----------------

/** live / age: same judgment as the overview (computed in app.js's Main and passed in); if not passed, only look at st.joints_age_ms. */
export function ImuPage({ st, imu, link, live, age, diagnosticElapsed = 0, pd }) {
  const W = useRef(freshWizard());
  const [, bump] = useState(0);
  const redraw = () => bump((n) => n + 1);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [muted, setMutedState] = useState(loadMute);
  const mutedRef = useRef(muted);
  const setMuted = (v) => { mutedRef.current = v; setMutedState(v); saveMute(v); };
  const context = imuContext(st?.mode || imu?.mode, imu);

  useEffect(() => {
    W.current = freshWizard(); setRes(null); setMsg(null); redraw();
  }, [context]);

  useEffect(() => {
    if (!feed(W.current, st, live)) return;
    for (const e of W.current.events.splice(0)) if (!mutedRef.current) beep(e);
    redraw();
  }, [st, live]);

  // Capture finished: hand it to the backend to compute (the backend gets the old orientation itself from calibration-status; the page does not need to pass it)
  const phase = W.current.phase;
  useEffect(() => {
    if (phase !== 'solving') return undefined;
    let dead = false;
    const w = W.current;
    link.cmd('imu.op', { op: 'solve', frame: 'body', mode: 'full', samples: payload(w) }, 15000).then((r) => {
      if (dead || W.current !== w) return;
      if (r.ok && r.data) { w.phase = 'done'; w.result = r.data; setRes(r.data); }
      else { w.phase = 'error'; w.error = r.reason || r.error || '没算出来'; }
      redraw();
    });
    return () => { dead = true; };
  }, [phase, context]);

  const act = {
    start: () => { audioUnlock(); startCollect(W.current, performance.now() / 1000); setRes(null); redraw(); },
    end: () => { endCollect(W.current); redraw(); },
    resume: () => { audioUnlock(); resumeCollect(W.current); redraw(); },
  };
  const onRedo = (steps) => { audioUnlock(); redoSteps(W.current, steps); setRes(null); redraw(); };

  const run = async (args, what, timeout = 15000) => {
    setBusy(true); setMsg(null);
    const r = await link.cmd('imu.op', args, timeout);
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: `${what}：${r.data?.note || '好了'}` } : { ok: false, text: `${what}没成：${r.reason || r.error || '没说原因'}` });
    return r;
  };
  const w = W.current;
  const F = freshText(st, live, age);
  const arrow = w.phase === 'collect' && w.done.still ? nextTodo(w) : null;
  const cue = w.phase === 'collect' ? (!w.done.still ? '静止 3 秒：别碰它' : arrow ? `下一个：${STEP[arrow].cn}（顺序随便）` : null) : null;
  return html`<div class="imu-page">
    <details class="console-imu-explanation"><summary>标定与采集说明</summary><p>IMU 告诉策略机身往哪边倾斜。安装方向验证、站姿精校与写入主程序分别完成；以采集质量和主程序回读结果为准。</p></details>
    <${JobBanner} job=${imu?.job} />
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>知道了</a></div>` : null}
    <div class="imu-grid">
      <${ImuStage} st=${st} stale=${!F.live} corr=${res?.ok ? res.correction : null} parts=${res?.parts}
        collecting=${w.phase === 'collect'} arrow=${arrow} cue=${cue} />
      <div class="imu-side">
        <${StatusCard} st=${st} imu=${imu} live=${live} age=${age} diagnosticElapsed=${diagnosticElapsed} />
        <${DiagnosticCard} st=${st} imu=${imu} live=${live} diagnosticElapsed=${diagnosticElapsed} />
        <${CoarseCard} st=${st} imu=${imu} link=${link} live=${live} />
        <${StanceCard} st=${st} imu=${imu} pd=${pd} link=${link} live=${live} />
        <${CollectCard} st=${st} imu=${imu} live=${live} W=${w} act=${act} muted=${muted} setMuted=${setMuted} />
        <${ResultCard} res=${w.phase === 'done' ? res || w.result : null} imu=${imu} link=${link} onRedo=${onRedo} />
        <details class="board console-imu-chip" open=${!!imu?.profile_error || !!imu?.redo?.active}><summary>芯片配置与连接诊断</summary><${ChipCard} imu=${imu} link=${link} live=${live} diagnosticElapsed=${diagnosticElapsed} /></details>
      </div>
    </div>
  </div>`;
}
