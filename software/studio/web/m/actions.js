// Action dictionary + one-sentence parsing. Shared by the overview, voice and gamepad pages; don't write a separate one for each.
//
// Commands all go through Studio's existing pad.op (software/studio/README.md "frontend/backend protocol" (「前后端协议」), the header comment of web/pad.js):
//   stand / sit / walk / walk_stop / skill {name} / sound {tag} / action_start·hold·stop
// No new HTTP endpoints: gestures, voice and buttons all end up at the same _motion_cmd, and mutual exclusion and the watchdog already exist there.

export const ACTIONS = {
  stand: { label: '站起来', op: { op: 'stand' }, cn: '站起来' },
  walk: { label: '开始走', op: { op: 'walk' }, cn: '开始走' },
  // the backend has no step op: taking a small step = make sure the policy is running, then push forward for 0.8 s and stop (see stepOnce)
  step: { label: '走一小步', special: 'step', cn: '走一小步' },
  stop: { label: '停下', op: { op: 'walk_stop' }, cn: '停下，站好' },
  sit: { label: '坐下', op: { op: 'sit' }, cn: '坐下' },
  roulade: { label: '前滚翻', op: { op: 'skill', name: 'roulade' }, cn: '前滚翻' },
  ground_pick: { label: '低头捡东西', op: { op: 'skill', name: 'ground_pick' }, cn: '低头捡东西' },
  chirp: { label: '叫一声', op: { op: 'sound', tag: 'chirp' }, cn: '叫一声' },
  greet: { label: '打招呼', op: { op: 'sound', tag: 'greet' }, cn: '打招呼' },
};

// "Press and hold" actions like a nod / two head shakes: send one press, hold for duration ms, then release
const HELD = {
  nod: { id: 'nod', label: '点头', cn: '点点头', ms: 1100 },
  shake: { id: 'shake', label: '摇头', cn: '摇摇头', ms: 1100 },
  tilt: { id: 'tilt', label: '歪头', cn: '歪歪头', ms: 900 },
  mouth: { id: 'mouth', label: '张嘴', cn: '张嘴', ms: 900 },
};

// Head commands go into the policy's observations, so if the policy isn't running they're sent but nothing moves (pad_combo.py file header, NEEDS_POLICY).
// The mouth isn't subject to this: fork robotd moves it as long as it's standing (including holding and sitting), so mouth isn't in here.
const HELD_NEEDS_POLICY = new Set(['nod', 'shake', 'tilt']);

// Action groups on the gamepad page. Standing and walking are a separate group: users most easily get stuck on "standing still / stick does nothing"
// "Start walking" (「开始走」) isn't in a group: it's the master switch that turns on the walk policy, so the gamepad page pulls it out below the sticks
// with the brand-yellow background (m-start-row in gamepad.js), so it doesn't get lost among the ordinary action buttons.
export const ACTION_GROUPS = [
  { title: '站住与走路', keys: ['stand', 'step', 'stop'] },
  { title: '坐下与技能', keys: ['sit', 'roulade', 'ground_pick'] },
  { title: '声音', keys: ['chirp', 'greet'] },
  { title: '转头', keys: ['nod', 'shake', 'tilt'] },
];

/** Any action key → the text on the button (ACTIONS and HELD share the same lookup) */
export function actionLabel(key) {
  const hit = ACTIONS[key] || HELD[key];
  return (hit && hit.label) || key;
}

/**
 * The button that most needs clicking right now (the gamepad page draws a green outline around it). Each case corresponds to a real admission condition in the backend:
 * holding = standing but the policy isn't running → pushing the stick does nothing, missing "start walking"; sitting / limp → missing "stand up".
 * Users most easily get stuck on "pushed it and nothing happened", so they should see at a glance which one to press next.
 */
export function nextAction(st) {
  if (!st) return null;
  if (st.estop && st.estop.state === 'confirmed') return 'stand';
  switch (st.posture) {
    case 'holding': return 'walk';
    case 'sitting': return 'stand';
    case 'limp': return 'stand';
    case 'walking': return 'stop';
    default: return null;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** One stick frame. -1..1, y up is negative = forward (LY = -ly in pad_drive.sticks_to_intent). The backend brakes by itself if nothing arrives for 0.5 s */
function pushStick(link, { x = 0, y = 0 } = {}, timeout) {
  return link.cmd('pad.op', {
    op: 'sticks', mode: 'drive', lx: x, ly: y, rx: 0, ry: 0, seq: link.nextPadSeq(),
  }, timeout);
}

const whyOf = (r) => String((r && (r.reason || r.error || r.data?.dropped)) || '');
const good = (r) => Boolean(r) && r.ok !== false;
// The backend also replies "already walking" as a failure (by then the button has already changed to "stop"); for the caller this is success
const isReady = (r) => !r?.data?.dropped && (good(r) || /准备好走|已经在走/.test(whyOf(r)));
// The backend only sends one exclusive command at a time; if the previous one hasn't answered, the next is bounced back; standing up / returning to center also take a few ticks.
// robotd's home_start_guard also requires "several consecutive frames at HOME + upright" before starting the policy ("不能进入保持：…" (cannot enter hold: …)),
// so it rejects several times right after standing up; sending again after a moment gets through, so this kind of reason is also retried as "busy".
const BUSY_WHY = /还没回话|等一下|等一秒|还在回站姿|还在站起来|正在起来|站稳了再点|不能进入保持|确认实际 HOME|关节实际位置|舵机反馈|反馈已过期|直立姿态|扶正/;
// The two standing postures in which the policy is really running (pad_drive.DRIVING). holding = standing but the policy isn't running; pushing the stick does nothing
const DRIVING = new Set(['policy', 'walking']);

/**
 * Wait for "the policy is running". If ctx.getPosture is given, watch the state; if not (e.g. the overview page has no live state), just wait a little while.
 * Between sending robot.enable and posture becoming policy there are a second or two; pushing the stick / clicking sit down during that time gets bounced back.
 */
async function waitDriving(ctx, ms, check) {
  const get = ctx && ctx.getPosture;
  if (typeof get !== 'function') { await sleep(Math.min(ms, 1800)); return null; }
  const t0 = performance.now();
  while (performance.now() - t0 < ms) {
    check?.();
    if (DRIVING.has(get())) return true;
    await sleep(150);
  }
  return false;
}

/**
 * Get the walk policy running, i.e. "start walking".
 * Official rule: there are two standing postures: holding (standing but the policy isn't running, the stick does nothing) and policy (ready to walk).
 * So "sit down", "take a small step" and "push the stick" all have to get through this first; otherwise the user just sees "nothing happened".
 */
async function ensurePolicy(link, ctx, tries = 4, check) {
  for (let i = 0; i < tries; i++) {
    check?.();
    const r = await link.cmd('pad.op', { op: 'walk' }, 20000);
    check?.();
    if (isReady(r)) return { ok: true, already: !good(r) };
    const why = whyOf(r);
    if (BUSY_WHY.test(why)) { await sleep(900); continue; }
    if (/坐/.test(why)) {
      // sitting: stand up first (via sit_toggle), and start the policy once steady. When the backend refuses to stand while sitting (policy not running and torque released)
      // it throws back the original message "first lift it up and set it level"; report that message to the user verbatim, don't make up instructions on its behalf.
      const s = await link.cmd('pad.op', { op: 'stand' }, 25000);
      check?.();
      if (!good(s) && !/已经站着/.test(whyOf(s))) return { ok: false, error: whyOf(s) || '站不起来' };
      await waitDriving(ctx, 15000, check);
      const p = await ensurePolicy(link, ctx, tries - i - 1, check);
      return p.ok ? { ...p, stood: true } : p;
    }
    return { ok: false, error: why || '开始走没成功' };
  }
  return { ok: false, error: '开始走一直没排上队，等一下再点' };
}

const activeSteps = new WeakMap();

function forgetStep(link, step) {
  if (activeSteps.get(link) === step) activeSteps.delete(link);
}

function startStep(link, ctx) {
  const previous = activeSteps.get(link);
  if (previous) previous.cancelled = 'replaced';
  const step = { cancelled: null };
  activeSteps.set(link, step);
  const run = async () => {
    // the old stepping is zeroed first, then the new stepping takes the wheel, so a stale stop frame doesn't interrupt the new action.
    if (previous) await previous.done;
    return stepOnce(link, ctx, step);
  };
  step.done = run().finally(() => forgetStep(link, step));
  return step.done;
}

function stopAction(link, op) {
  const previous = activeSteps.get(link);
  if (previous) previous.cancelled = 'stop';
  const result = Promise.resolve().then(() => link.cmd('pad.op', op, 20000));
  const stop = { done: Promise.allSettled([previous?.done, result]) };
  activeSteps.set(link, stop);
  stop.done.then(() => forgetStep(link, stop));
  return result;
}

/** The phone's short-step action reuses Studio's stick channel: policy → 0.85 s forward → stop. */
async function stepOnce(link, ctx, step, power = 0.55) {
  const poseError = '还没确认走路策略在运行，等站稳后再试。';
  const cancelled = '短步已取消。';
  const check = () => {
    if (step.cancelled) throw new Error(cancelled);
    if (ctx?.getPosture?.() == null) throw new Error(poseError);
  };
  let error = null;
  let attempted = false;
  let moved = false;
  let stood = false;
  try {
    check();
    const policy = await ensurePolicy(link, ctx, 4, check);
    check();
    if (!policy.ok) throw new Error(policy.error);
    stood = policy.stood === true;
    if (await waitDriving(ctx, 5000, check) !== true) throw new Error(poseError);
    check();
    await sleep(stood ? 150 : 220);
    check();
    const deadline = performance.now() + 850;
    while (performance.now() < deadline) {
      check();
      if (!DRIVING.has(ctx.getPosture())) throw new Error(poseError);
      const remaining = deadline - performance.now();
      if (remaining <= 0) break;
      attempted = true;
      const frame = await pushStick(link, { y: -power }, Math.min(500, Math.ceil(remaining)));
      check();
      if (frame?.ok !== true || frame.data?.dropped || !(frame.data?.sent?.[0] > 0)) {
        throw new Error(whyOf(frame) || '前进指令没发出去。');
      }
      moved = true;
      const pause = Math.min(95, deadline - performance.now());
      if (pause > 0) await sleep(pause);
    }
    check();
    if (!moved) throw new Error('前进指令没发出去。');
  } catch (err) {
    error = err?.message || '前进指令没发出去。';
  } finally {
    if (attempted && step.cancelled !== 'stop') {
      try {
        const stop = await link.cmd('pad.op', { op: 'stop', seq: link.nextPadSeq(), owned_only: true }, 5000);
        if (stop?.ok !== true || stop.data?.dropped || stop.data?.sent !== true) {
          error ||= whyOf(stop) || '没确认停止指令发出。';
        }
      } catch (err) {
        error ||= err?.message || '没确认停止指令发出。';
      }
    }
  }
  if (step.cancelled) error ||= cancelled;
  return { ok: !error, cn: '走一小步', error, note: !error && stood ? '已站起来，并发送短步指令' : null };
}

/**
 * Sit down. Official requires the policy to be running before sitting, so in holding it replies "sitting requires the policy running: click start walking first".
 * That message sends the user to click a button they think doesn't exist, so just fill it in for them here: start walking first, then sit again.
 */
async function sitSmart(link, ctx) {
  for (let i = 0; i < 4; i++) {
    const r = await link.cmd('pad.op', { op: 'sit' }, 25000);
    const why = whyOf(r);
    if (good(r) || /已经坐着/.test(why)) {
      return { ok: true, cn: '坐下', error: null, note: /已经坐着/.test(why) ? '已经坐着了' : null };
    }
    if (BUSY_WHY.test(why)) { await sleep(900); continue; }        // the previous command hasn't answered yet
    if (!/策略/.test(why)) return { ok: false, cn: '坐下', error: why };
    const p = await ensurePolicy(link, ctx);
    if (!p.ok) return { ok: false, cn: '坐下', error: p.error };
    await waitDriving(ctx, 6000);          // after starting the policy, wait until it's really steady, otherwise sitting gets a reply of "wait a second"
  }
  return { ok: false, cn: '坐下', error: '坐下一直没排上队，再点一次试试' };
}

let press = 0;

/**
 * Run an action name (a key in ACTIONS or HELD). Returns {ok, cn, error, note}
 * @param ctx optional: {getPosture()}, when live posture is readable, waits follow the state instead of guessing times
 */
export async function runAction(link, key, ctx) {
  const hit = ACTIONS[key];
  if (hit) {
    if (hit.special === 'step') return startStep(link, ctx);
    if (key === 'sit') return sitSmart(link, ctx);
    if (key === 'walk') {
      const p = await ensurePolicy(link, ctx);
      if (!p.ok) return { ok: false, cn: '开始走', error: p.error };
      return { ok: true, cn: '开始走', error: null,
        note: p.already ? '已经在走着了，推左摇杆就会动' : (p.stood ? '先站起来，现在开始走：推左摇杆' : '开始走了：推左摇杆就会动') };
    }
    const r = key === 'stop' ? await stopAction(link, hit.op) : await link.cmd('pad.op', hit.op, 20000);
    const ok = good(r) && !r.data?.dropped;
    return { ok, cn: hit.cn, error: ok ? null : whyOf(r) };
  }
  const held = HELD[key];
  if (!held) return { ok: false, cn: key, error: '不认识这个动作' };
  // nod / shake / tilt head only feed the policy observations: if the policy isn't running, sending them moves nothing (NEEDS_POLICY).
  // "nodding does nothing after standing up / make me click start walking first" gets stuck right here, so start the walk policy for them first.
  if (HELD_NEEDS_POLICY.has(key)) {
    const p = await ensurePolicy(link, ctx);
    if (!p.ok) return { ok: false, cn: held.cn, error: p.error };
  }
  const tag = ++press;
  const tries = HELD_NEEDS_POLICY.has(key) ? 3 : 1;      // the mouth doesn't wait for the policy, once is enough
  for (let i = 0; i < tries; i++) {
    const start = await link.cmd('pad.op', { op: 'action_start', id: held.id, press: tag }, 8000);
    if (start.ok !== false) break;
    const why = whyOf(start);
    // the backend may take a tick longer to consider the posture "walking": wait a moment and retry; other reasons (real rejections) are reported directly
    if (i < tries - 1 && (BUSY_WHY.test(why) || /准备好走|开始走|策略/.test(why))) {
      await waitDriving(ctx, 2000);
      continue;
    }
    return { ok: false, cn: held.cn, error: why };
  }
  const t0 = performance.now();
  const hb = setInterval(() => { link.cmd('pad.op', { op: 'action_hold', press: tag }, 8000); }, 150);
  await new Promise((r) => setTimeout(r, held.ms));
  clearInterval(hb);
  await link.cmd('pad.op', { op: 'action_stop' }, 8000);
  return { ok: true, cn: held.cn, error: null, ms: performance.now() - t0 };
}

// ---------------- Voice switch (pad.op's audio branch) ----------------

// The backend (pad.py's audio branch) requires that "this connection is not marked as having left the gamepad area", otherwise it replies "请先回到手柄遥控区操作语音" (please return to the gamepad remote area to operate voice).
// The phone page is a single-page app, one ws across all five tabs: when switching from the gamepad, unmounting the gamepad page sends drive {on:false},
// which marks exactly this connection as left, and the voice switch can no longer be clicked. So entering the voice page first sends drive {open:true}
// (the backend only clears the mark, doesn't take the wheel or touch the servos), and if it really hits that, retry once more.
export const PAD_AREA_WHY = /回到手柄|不在手柄|已经断开/;

export function openPadArea(link) {
  return link.cmd('pad.op', { op: 'drive', open: true }, 8000);
}

/** Turn onboard listening on / off. If rejected with "return to the gamepad area", send open once and retry once */
export async function setAudio(link, values, tries = 2) {
  for (let i = 0; i < tries; i++) {
    const r = await link.cmd('pad.op', { op: 'audio', ...values }, 12000);
    if (r.ok !== false) return r;
    if (!PAD_AREA_WHY.test(String(r.reason || r.error || '')) || i === tries - 1) return r;
    await openPadArea(link);
  }
  return { ok: false, reason: '板载语音没切换成功' };
}

// ---------------- One sentence → action ----------------

// Prefix word. Saying "鸭鸭" (Ducky) is **no longer required** (both voice channels take commands directly), but if it's still there it's stripped,
// so "鸭鸭站起来" (Ducky stand up) isn't treated as an unknown phrase. Common misrecognitions (呀呀, 丫丫) are included too.
const ADDRESS = /^(鸭鸭鸭|鸭鸭|呀呀|丫丫|小鸭鸭|鸭子|小鸭子)[，,、。.!！?？\s]*/;

// Each rule matches the whole command. An explicit "别走" / "不要走" (don't walk) only means stop.
const RULES = [
  ['stop', /^(?:停(?:下(?:来)?|住|步)?|别走|不要走|站住|站好|不走了)$/],
  ['stand', /^(?:站起(?:来)?|起立|起来|起身|站)$/],
  ['sit', /^(?:坐下(?:来)?|坐一坐|坐|坐着)$/],
  ['roulade', /^(?:前?滚翻|翻(?:个)?跟头|翻身|打(?:个)?滚)$/],
  ['ground_pick', /^(?:低头(?:捡东西)?|捡(?:个|一下)?东西)$/],
  ['step', /^(?:走一小步|走一步|走两步|迈一步|走一下)$/],
  ['walk', /^(?:走|前进|往前(?:走)?|开步)$/],
  ['nod', /^(?:点头|点点头|点一下头|点个头)$/],
  ['shake', /^(?:摇头|摇摇头|摇一下头|摇个头)$/],
  ['tilt', /^(?:歪头|歪歪头|歪一下头|歪个头|歪脑袋|偏头)$/],
  ['mouth', /^(?:张嘴|开口)$/],
  ['chirp', /^(?:叫一声|叫一下|叫两声|嘎(?:一声|一下)?|叫唤)$/],
  ['greet', /^(?:打(?:个)?招呼|问好|你好|嗨)$/],
];

export const CMD_CN = {
  stand: '站起来', sit: '坐下', walk: '开始走', step: '走一小步', stop: '停下，站好', roulade: '前滚翻',
  ground_pick: '低头捡东西', nod: '点点头', shake: '摇摇头', tilt: '歪歪头', mouth: '张嘴',
  chirp: '叫一声', greet: '打招呼',
};

/** Strip whitespace and punctuation to make matching easier */
function tidy(text) {
  return String(text || '').replace(/[\s，。！、,.!]/g, '');
}

/**
 * Parse one sentence.
 * @param {string} text the recognized text
 * @param {{requireWake?: boolean}} opt with requireWake=true, anything not starting with "鸭鸭" (Ducky) is treated as chit-chat
 * @returns {{cmd: string|null, wake: boolean, said: string}}
 */
export function parseUtterance(text, { requireWake = false } = {}) {
  const raw = tidy(text);
  const m = raw.match(ADDRESS);
  const wake = Boolean(m);
  const body = wake ? raw.slice(m[0].length) : raw;
  const said = body || raw;
  if (!body) return { cmd: null, wake, said };
  if (requireWake && !wake) return { cmd: null, wake, said };
  const phrase = body.replace(/^请/, '').replace(/吧$/, '');
  for (const [cmd, re] of RULES) {
    if (re.test(phrase)) return { cmd, wake, said };
  }
  return { cmd: null, wake, said };
}

// ---------------- Posture text ----------------

export function postureCopy(st, name) {
  const p = st?.posture;
  const sleepy = st?.estop?.state === 'confirmed';
  if (!st) return { h: name, sub: '还没收到鸭子的状态。' };
  if (sleepy) return { h: `${name}松着劲儿`, sub: '舵机卸力了。想让它动，先点「站起来」。' };
  switch (p) {
    case 'walking': return { h: '正在走', sub: '松开摇杆它会停下、继续站着。' };
    case 'policy': return { h: `${name}站着，随时能走`, sub: '按「走一小步」，或者去手柄页推摇杆。' };
    case 'sitting': return { h: `${name}坐着`, sub: '按「站起来」，或者说一句「站起来」。' };
    case 'starting': return { h: `${name}正在起来`, sub: '别碰它，等它站稳。' };
    case 'limp': return { h: `${name}软着`, sub: '舵机没劲儿，先站起来。' };
    case 'homing': return { h: `${name}正在回中`, sub: '等它回中完成。' };
    case 'servo_session': return { h: '正在调舵机', sub: '主程序停着，站走用不了。' };
    case 'commissioning': return { h: `${name}还没标定`, sub: '去桌面版 Studio 走一遍上手流程。' };
    case 'absent': return { h: `没找到${name}`, sub: '主程序没连上，去桌面版看看。' };
    default: return { h: name, sub: '读不出它现在的姿势。' };
  }
}

/** Numbers for the three small cells battery / servo / IMU; anything unreadable is uniformly null, don't make up values */
export function readings(st) {
  const b = st?.battery || {};
  const s = st?.servos || {};
  const imu = st?.imu || {};
  return {
    pct: typeof b.pct === 'number' ? Math.round(b.pct) : null,
    volts: typeof b.volts === 'number' ? b.volts.toFixed(2) : null,
    online: typeof s.online === 'number' ? s.online : null,
    total: typeof s.total === 'number' ? s.total : 15,
    hottest: s.hottest && typeof s.hottest.c === 'number' ? Math.round(s.hottest.c) : null,
    imu: { ok: '正常', unverified: '方向没确认', frozen: '读数冻住了', missing: '没读到' }[imu.status] || '—',
    imuKind: { unverified: 'warn', frozen: 'bad', missing: 'bad' }[imu.status] || null,
    tilt: typeof st?.tilt_deg === 'number' ? Math.round(st.tilt_deg) : null,
  };
}
