// Gamepad page: two virtual sticks + a row of action buttons.
//
// The protocol follows the description at the top of web/pad.js exactly, not a single item changed:
//   sticks {mode, lx, ly, rx, ry, seq}  -1..1, x right and y down positive; sent at 10 Hz while held
//   stop {seq}                        sent once on release; the backend returns to center / stops walking depending on mode
//   mode {mode, seq} / {mode, hb:true} switch mode + head/body mode reports "still here" once per second (the backend exits after 3 s of silence)
//   drive {open:true} / {on:false}     enter/leave the gamepad area
// Backend deadman: it stops by itself if no stick frame arrives for 0.5 s, so releasing / disconnecting never leaves the duck walking.
import { html, useState, useEffect, useRef, useCallback } from '../vendor/preact-htm.module.js';
import { link } from './link.js';
import { ACTION_GROUPS, actionLabel, runAction, nextAction } from './actions.js';

const SEND_MS = 100;
const MODE_HB_MS = 1000;
const AUTO_WALK_MS = 4000;   // cooldown for auto-sending "start walking" on the user's behalf when standing but the policy isn't running (backend enable takes a second or two)

// Only walk and head are kept: the body mode is for debugging fine-tuning and is easy to switch into by mistake in everyday play (raised by the user on Nov 2).
// The backend still accepts body; there's just no entry for it here.
const MODES = [
  { id: 'drive', label: '走路', hint: '左摇杆前后走、左右平移；右摇杆左右转身' },
  { id: 'head', label: '转头', hint: '左摇杆抬头低头，右摇杆左右歪头' },
];

// Posture → one sentence explaining "which step is missing now". This table is the answer to the user's "pushing the stick does nothing":
// standing is split into holding (policy not running, stick input dropped) and policy (ready to walk); what's missing is that one "start walking".
const TIPS = {
  walking: ['ok', '正在走：松开摇杆它会停下、继续站着'],
  policy: ['ok', '准备好走了：推左摇杆就走'],
  holding: ['warn', '站着，但还没「开始走」——摇杆推了不动。点摇杆下面黄色的「开始走 start 策略」（推一下左摇杆也会自动帮你开）'],
  sitting: ['warn', '坐着：先点「站起来」，再点「开始走 start 策略」，摇杆才有反应'],
  limp: ['bad', '舵机没劲儿：先点「站起来」'],
  starting: ['warn', '正在起来，等它站稳'],
  homing: ['warn', '正在回中，等它稳住'],
  servo_session: ['bad', '正在调舵机：站起和走路这会儿都用不了'],
  commissioning: ['bad', '还没标定：先去电脑上的 Studio 走一遍上手流程'],
  absent: ['bad', '主程序没连上，摇杆发了也没人接'],
};

function driveTip(st) {
  if (!st) return null;
  if (st.estop && st.estop.state === 'confirmed') return ['bad', '舵机卸力了：先点「站起来」上力，再走'];
  return TIPS[st.posture] || null;
}

/** In these postures the backend can't move even if the stick is pushed (policy not running / servos limp / servos being tuned); don't send frames for nothing, tell the user why first */
function blockedWhy(st) {
  if (!st) return null;
  if (st.estop && st.estop.state === 'confirmed') return '舵机卸力了：先点「站起来」上力';
  switch (st.posture) {
    case 'sitting': return '它坐着呢：先点「站起来」，再点「开始走」';
    case 'limp': return '舵机没劲儿：先点「站起来」上力';
    case 'servo_session': return '正在调舵机：这会儿摇杆用不了';
    case 'commissioning': return '还没标定：先去电脑上的 Studio 走一遍上手流程';
    case 'absent': return '主程序没连上，摇杆发了也没人接';
    default: return null;
  }
}

/** A single stick: press and drag, springs back to center on release. Normalized to -1..1 (x right, y down positive, same as the backend) */
function Stick({ cap, onChange, onEnd }) {
  const boxRef = useRef(null);
  const knobRef = useRef(null);
  const [active, setActive] = useState(false);
  const idRef = useRef(null);

  const move = (e) => {
    const box = boxRef.current;
    if (!box) return;
    const r = box.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const max = Math.min(r.width, r.height) / 2 * 0.68;      // the stick can be pushed to at most 68% of the radius
    let dx = e.clientX - cx;
    let dy = e.clientY - cy;
    const len = Math.hypot(dx, dy);
    if (len > max) { dx = dx / len * max; dy = dy / len * max; }
    if (knobRef.current) knobRef.current.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
    onChange(dx / max, dy / max);
  };

  const end = () => {
    idRef.current = null;
    setActive(false);
    if (knobRef.current) knobRef.current.style.transform = 'translate(-50%, -50%)';
    onEnd();
  };

  const down = (e) => {
    e.preventDefault();
    idRef.current = e.pointerId;
    setActive(true);
    try { boxRef.current.setPointerCapture(e.pointerId); } catch { /* old browsers */ }
    move(e);
  };

  const up = (e) => {
    if (idRef.current != null && e.pointerId !== idRef.current) return;
    end();
  };

  return html`<div class="m-stick-box">
    <div class=${'m-stick' + (active ? ' active' : '')} ref=${boxRef}
      onPointerDown=${down} onPointerMove=${(e) => { if (idRef.current != null) move(e); }}
      onPointerUp=${up} onPointerCancel=${up} onLostPointerCapture=${up}
      role="application" aria-label=${cap}>
      <div class="m-knob" ref=${knobRef}><i></i></div>
    </div>
    <div class="cap">${cap}</div>
  </div>`;
}

export function GamepadPage({ st, live, say }) {
  const [mode, setMode] = useState('drive');
  const [busy, setBusy] = useState(null);
  const left = useRef({ x: 0, y: 0, on: false });
  const right = useRef({ x: 0, y: 0, on: false });
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const stRef = useRef(st);
  stRef.current = st;
  const poseRef = useRef(null);
  poseRef.current = live ? st?.posture : null;
  const sayRef = useRef(say);
  sayRef.current = say;
  const autoAt = useRef(0);                // when "start walking" was last auto-sent for the user: with cooldown, don't hit the backend every frame
  const nagged = useRef(false);            // pushing the stick while sitting / torque released: say it only once, don't spam at 10 Hz
  // live posture for actions.js: wait for the policy by the real state instead of guessing seconds
  const ctxRef = useRef({ getPosture: () => poseRef.current });

  // entering the gamepad area: tell the backend "I'm here", and "I'm leaving" on exit
  useEffect(() => {
    link.cmd('pad.op', { op: 'drive', open: true }, 8000);
    autoAt.current = 0;
    return () => {
      poseRef.current = null;
      link.cmd('pad.op', { op: 'drive', on: false }, 8000);
    };
  }, []);

  // sticks: send full frames at 10 Hz while held; send stop once when all are released
  useEffect(() => {
    let wasOn = false;
    const t = setInterval(() => {
      const on = left.current.on || right.current.on;
      if (on) {
        // sitting / limp / tuning servos etc.: the backend receives it but can't move (policy not running, robot.move ignored by robotd).
        // Rather than silently doing nothing, say so right away; don't send frames then, so the backend doesn't log a pile of dropped at 10 Hz.
        const why = blockedWhy(stRef.current);
        if (why) {
          if (!nagged.current) { nagged.current = true; sayRef.current(why, true); }
          return;
        }
        nagged.current = false;
        // standing but the policy isn't running (holding): this frame will be ignored by robotd. Auto-send "start walking" once for the user,
        // so they don't just see "pushed and nothing happened". Don't auto-stand while sitting: that clearly moves the body, so it's left for the user to click.
        if (poseRef.current === 'holding' && performance.now() - autoAt.current > AUTO_WALK_MS) {
          autoAt.current = performance.now();
          link.cmd('pad.op', { op: 'walk' }, 20000);
        }
        wasOn = true;
        link.cmd('pad.op', {
          op: 'sticks', mode: modeRef.current,
          lx: left.current.x, ly: left.current.y,
          rx: right.current.x, ry: right.current.y,
          seq: link.nextPadSeq(),
        }, 5000);
      } else if (wasOn) {
        wasOn = false;
        link.cmd('pad.op', { op: 'stop', seq: link.nextPadSeq() }, 5000);
      }
    }, SEND_MS);
    return () => { clearInterval(t); link.cmd('pad.op', { op: 'stop', seq: link.nextPadSeq() }, 5000); };
  }, []);

  // head / body mode: renew once per second (the backend returns to walk mode after 3 s of silence)
  useEffect(() => {
    link.cmd('pad.op', { op: 'mode', mode, seq: link.nextPadSeq() }, 6000);
    if (mode === 'drive') return undefined;
    const t = setInterval(() => { link.cmd('pad.op', { op: 'mode', mode, hb: true, seq: link.nextPadSeq() }, 6000); }, MODE_HB_MS);
    return () => clearInterval(t);
  }, [mode]);

  const fire = useCallback(async (key) => {
    if (busy) return;
    setBusy(key);
    const out = await runAction(link, key, ctxRef.current);
    setBusy(null);
    autoAt.current = 0;                     // a button was clicked manually: allow auto-sending once more on the next stick push
    if (out.ok) say(out.note || `已发送：${out.cn}`); else say(out.error || `${out.cn}没发出去`, true);
  }, [busy, say]);

  const m = MODES.find((x) => x.id === mode) || MODES[0];
  const tip = driveTip(st);
  const hot = nextAction(st);               // the button that most needs pressing now: draw a green outline around it
  const key = (k) => html`<button
    class=${'m-key' + (k === hot ? ' hot' : '') + (busy === k ? ' on' : '')}
    disabled=${Boolean(busy)} onClick=${() => fire(k)}>
    ${actionLabel(k)}
  </button>`;

  // "Start walking" (「开始走」) = master switch that turns on the walk policy, "stop policy" (「停止策略」) = stop and turn off the policy. Both sit side by side below the sticks:
  // the only fix for "pushing the stick does nothing" is "start walking", and mixed into the action grid it's easiest to miss (raised by the user on Nov 2).

  return html`<div>
    ${!live ? html`<div class="m-banner">还没收到鸭子的状态，摇杆可以推，但可能不动。</div>` : null}
    ${tip ? html`<div class=${'m-banner ' + tip[0]}>${tip[1]}</div>` : null}

    <h2 class="m-h2">怎么动</h2>
    <div class="m-seg" role="group" aria-label="摇杆模式">
      ${MODES.map((x) => html`<button aria-pressed=${mode === x.id ? 'true' : 'false'} onClick=${() => setMode(x.id)}>${x.label}</button>`)}
    </div>
    <p class="m-tip">${m.hint}</p>

    <div class="m-sticks">
      <${Stick} cap=${mode === 'drive' ? '左摇杆 · 走' : '左摇杆 · 抬头低头'}
        onChange=${(x, y) => { left.current = { x, y, on: true }; }}
        onEnd=${() => { left.current = { x: 0, y: 0, on: false }; }} />
      <${Stick} cap=${mode === 'drive' ? '右摇杆 · 转身' : '右摇杆 · 歪头'}
        onChange=${(x, y) => { right.current = { x, y, on: true }; }}
        onEnd=${() => { right.current = { x: 0, y: 0, on: false }; }} />
    </div>

    <div class="m-start-row">
      <button
        class=${'m-key start' + (hot === 'walk' ? ' hot' : '') + (busy === 'walk' ? ' on' : '')}
        disabled=${Boolean(busy)} onClick=${() => fire('walk')}>
        开始走<small>start 策略</small>
      </button>
      <button
        class=${'m-key start stop' + (busy === 'stop' ? ' on' : '')}
        disabled=${Boolean(busy)} onClick=${() => fire('stop')}>
        停止策略<small>stop 策略</small>
      </button>
    </div>

    ${ACTION_GROUPS.map((g) => html`<div>
      <h2 class="m-h2">${g.title}</h2>
      <div class="m-keys">${g.keys.map(key)}</div>
    </div>`)}

    <p class="m-tip">
      <b>绿框那个键</b>是按它现在的姿势、下一步最该按的。
      <b>黄色「开始走 start 策略」只是把走路策略打开</b>，鸭子不会自己迈步——要迈步就推左摇杆，
      或者点「走一小步」（它会自动先开策略再走一步）。
      走完了点旁边的<b>「停止策略 stop 策略」</b>，它会站住并关掉策略，之后推摇杆也没反应，再点「开始走」才行。
      松手就停，断线也停（后端 0.5 秒收不到摇杆帧会自己刹车）。按住摇杆的时候别切模式，松手再切。
    </p>
  </div>`;
}
