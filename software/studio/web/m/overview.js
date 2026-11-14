// Overview: only shows what the duck looks like right now (status panel).
// Actions are all on the "Gamepad" page and voice on the "Voice" page; the overview doesn't duplicate buttons (removed on 2026-11-02 at the user's request).
// The 3D view uses the same Duck3D as the desktop version (web/duck3d.js); joint angles come from WS state.joints[15],
// with pageScroll on: on phones one finger is left for page scrolling, and only two fingers rotate the view (the desktop overview is configured the same way).
import { html, useState, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { Duck3D } from '../duck3d.js';
import { postureCopy, readings } from './actions.js';

function Stage({ st, live, name }) {
  const canvasRef = useRef(null);
  const duckRef = useRef(null);
  const [msg, setMsg] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let d;
    try {
      d = new Duck3D(canvasRef.current, { view: 'front34', centerX: 0.5, centerY: 0.44, fill: 0.72, pageScroll: true });
    } catch (e) {
      setMsg(`3D 起不来：${e.message}`);     // old browsers without WebGL: don't white-screen the whole page; controls below still work
      return undefined;
    }
    duckRef.current = d;
    d.load('/model/').then(() => setReady(true)).catch((e) => setMsg(`3D 模型没加载：${e.message}`));
    return () => { try { d.dispose(); } catch { /* already gone */ } };
  }, []);

  useEffect(() => {
    const d = duckRef.current;
    if (!d || !st) return;
    d.setJoints(st.joints);
    d.setGravity(st.gravity);
  }, [st]);

  // joint data not updated for more than 1 s is treated as stale (don't pass off the default pose as live)
  const old = st?.joints_age_ms == null || st.joints_age_ms > 1000;
  const c = postureCopy(st, name);
  return html`<section class=${'m-stage' + (live && !old ? '' : ' stale')} aria-label="鸭子现在">
    <canvas ref=${canvasRef}></canvas>
    ${!ready && !msg ? html`<div class="m-stage-load">3D 模型加载中…</div>` : null}
    ${msg ? html`<div class="m-stage-load">${msg}</div>` : null}
    <div class="m-stage-badge"><b>${c.h}</b><span>${live && !old ? '实时' : '旧数据'}</span></div>
  </section>`;
}

function Cell({ label, big, unit, small, kind, stale }) {
  return html`<div class=${'m-card m-cell' + (kind ? ' ' + kind : '') + (stale ? ' stale' : '')}>
    <span class="label">${label}</span>
    <span class="big num">${big}</span>${unit ? html`<span class="unit">${unit}</span>` : null}
    <span class="small">${small}</span>
  </div>`;
}

export function Overview({ st, live, age, name }) {
  const r = readings(st);
  const c = postureCopy(st, name);
  const old = !live || age > 1000;

  const pctKind = r.pct == null ? null : r.pct <= 15 ? 'bad' : r.pct <= 30 ? 'warn' : null;

  return html`<div>
    <${Stage} st=${st} live=${live} name=${name} />
    <div class="m-caption">
      <h1>${c.h}</h1>
      <p>${c.sub}</p>
      ${st?.start_error ? html`<p class="deal">${st.start_error}</p>` : null}
    </div>

    <h2 class="m-h2">它现在怎么样</h2>
    <div class="m-cells">
      <${Cell} label="电量" big=${r.pct ?? '—'} unit=${r.pct != null ? '%' : ''} kind=${pctKind} stale=${old}
        small=${r.volts ? `${r.volts} V` : '读不到电压'} />
      <${Cell} label="舵机在线" big=${r.online ?? '—'} unit=${`/ ${r.total}`} stale=${old}
        small=${r.hottest ? `最热 ${r.hottest} °C` : '读不到温度'} />
      <${Cell} label="姿态传感器" big=${r.imu} stale=${old}
        small=${r.tilt != null ? `倾斜 ${r.tilt}°` : 'IMU 没有读数'} kind=${r.imuKind} />
      <${Cell} label="模式" big=${st?.mode || '—'}
        small=${st?.phase ? `阶段 ${st.phase}` : '主程序没报阶段'} stale=${old} />
    </div>

    ${st?.todo?.length ? html`<div class="m-card m-pad" style="margin-top:12px">
      <div class="m-sub" style="margin-bottom:6px">鸭子自己说要先处理这些</div>
      <ul class="m-log">${st.todo.slice(0, 4).map((t) => html`<li><span class="what">${typeof t === 'string' ? t : t.text || t.why || ''}</span></li>`)}</ul>
    </div>` : null}

    <p class="m-tip">想让它动，去<b>手柄</b>页点「站起来」「开始走」，或在<b>语音</b>页用手机麦克风说「<b>走一小步</b>」。
      任何时刻点右上角<b>卸力</b>，舵机会立刻松掉力气（鸭子会趴下去，这是正常的）。</p>
  </div>`;
}
