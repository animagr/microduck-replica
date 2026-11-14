// Servo labels on the 3D view: number + Chinese + English, with leader lines pointing to the actual servo housing center; shares the mapping with click-select/highlight.
// User, Oct 18: only shown on the servo page when the "zero position" (「零位」) reference pose is clicked; right leg red, left leg blue, head/neck yellow (following the split in the labeled photo of the real robot he provided).
// Hidden ones (behind the housing or other parts) are drawn with dashed lines and hollow dots: on the line from the camera to the servo center, hitting another part more than 3 cm before it counts as occluded.
import * as THREE from './vendor/three/three.module.js';

export const TAGS = {
  right_hip_yaw: [10, '右髋偏航', 'Right Hip Yaw', 'R'], right_hip_roll: [11, '右髋横滚', 'Right Hip Roll', 'R'],
  right_hip_pitch: [12, '右髋俯仰', 'Right Hip Pitch', 'R'], right_knee: [13, '右膝', 'Right Knee', 'R'],
  right_ankle: [14, '右踝', 'Right Ankle', 'R'],
  left_hip_yaw: [20, '左髋偏航', 'Left Hip Yaw', 'L'], left_hip_roll: [21, '左髋横滚', 'Left Hip Roll', 'L'],
  left_hip_pitch: [22, '左髋俯仰', 'Left Hip Pitch', 'L'], left_knee: [23, '左膝', 'Left Knee', 'L'],
  left_ankle: [24, '左踝', 'Left Ankle', 'L'],
  neck_pitch: [30, '颈部俯仰', 'Neck Pitch', 'H'], head_pitch: [31, '头部俯仰', 'Head Pitch', 'H'],
  head_yaw: [32, '头部偏航', 'Head Yaw', 'H'], head_roll: [33, '头部横滚', 'Head Roll', 'H'], mouth: [34, '嘴巴', 'Mouth', 'H'],
};
const COLOR = { R: '#E5484D', L: '#2F7CF6', H: '#F5B400' };

/** Draw labels in box (the stage element). duck is a fully loaded Duck3D. Returns a cleanup function. */
export function drawServoLabels(duck, box) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'sv-lines');
  box.appendChild(svg);
  const tags = [];
  const ray = new THREE.Raycaster();
  const hiddenCache = {};
  let dragging = false;

  function layout() {
    const W = box.clientWidth, H = box.clientHeight;
    if (!W || !H || !duck.ready) return;
    duck.scene.updateMatrixWorld(true);
    const meshes = [];
    if (!dragging) duck.content.traverse((o) => { if (o.isMesh) meshes.push(o); });
    const pts = [];
    for (const [name, [id, cn, en, side]] of Object.entries(TAGS)) {
      const servo = duck.servoOf[name];
      if (!servo) continue;
      const world = new THREE.Box3().setFromObject(servo).getCenter(new THREE.Vector3());
      // occlusion check (raycasting against 400k+ faces) only when not rotating; while rotating, reuse the previous result, otherwise dragging lags
      if (!dragging || !(id in hiddenCache)) {
        const dir = world.clone().sub(duck.camera.position);
        const dist = dir.length();
        ray.set(duck.camera.position, dir.normalize());
        const hit = ray.intersectObjects(meshes, false)[0];
        hiddenCache[id] = !!hit && hit.distance < dist - 0.03;
      }
      const v = world.clone().project(duck.camera);
      pts.push({ id, cn, en, side, hidden: hiddenCache[id], x: (v.x + 1) / 2 * W, y: (1 - v.y) / 2 * H });
    }
    // one column for the right leg, one for the left (which side is on the screen's left depends on the actual projection); head/neck split into the two columns by the head's center line;
    // head/neck on top, sorted by height (so lines don't cross); legs sorted by number (10, 11, 12…, easy to match)
    const avg = (s) => { const xs = pts.filter((p) => p.side === s).map((p) => p.x); return xs.reduce((a, b) => a + b, 0) / (xs.length || 1); };
    const rightOnLeft = avg('R') < avg('L'), headX = avg('H');
    const cols = [[], []];
    for (const p of pts) cols[(p.side === 'H' ? p.x < headX : (p.side === 'R') === rightOnLeft) ? 0 : 1].push(p);
    const gap = Math.min(46, (H - 60) / Math.max(cols[0].length, cols[1].length, 1));
    for (const col of cols) {
      col.sort((a, b) => ((a.side === 'H') !== (b.side === 'H') ? (a.side === 'H' ? -1 : 1) : a.side === 'H' ? a.y - b.y : a.id - b.id));
      let y = 34;
      for (const p of col) { p.ty = Math.max(y, Math.min(p.y, H - 26)); y = p.ty + gap; }
      let lim = H - 26;
      for (let i = col.length - 1; i >= 0; i--) { col[i].ty = Math.min(col[i].ty, lim); lim = col[i].ty - gap; }
    }
    tags.forEach((t) => t.remove());
    tags.length = 0;
    let lines = '';
    cols.forEach((col, ci) => {
      for (const p of col) {
        const el = document.createElement('div');
        el.className = `sv-tag ${p.side}`;
        el.innerHTML = `<span class="id">${p.id}</span><span><div class="cn">${p.cn}</div><div class="en">${p.en}</div></span>`;
        box.appendChild(el);
        tags.push(el);
        const w = el.offsetWidth;
        const lx = ci === 0 ? 14 : W - 14 - w;
        el.style.left = `${lx}px`;
        el.style.top = `${p.ty - 17}px`;
        const ax = ci === 0 ? lx + w : lx, mid = ci === 0 ? ax + 24 : ax - 24;
        lines += `<polyline points="${ax},${p.ty} ${mid},${p.ty} ${p.x},${p.y}" fill="none" stroke="${COLOR[p.side]}" stroke-width="2"${p.hidden ? ' stroke-dasharray="6 5"' : ''}/>`
          + `<circle cx="${p.x}" cy="${p.y}" r="4" fill="${p.hidden ? 'none' : '#fff'}" stroke="${COLOR[p.side]}" stroke-width="2"/>`;
      }
    });
    svg.innerHTML = lines;
  }

  let raf = 0;
  const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(layout); };
  const onStart = () => { dragging = true; };
  const onEnd = () => { dragging = false; schedule(); };
  duck.controls.addEventListener('change', schedule);
  duck.controls.addEventListener('start', onStart);
  duck.controls.addEventListener('end', onEnd);
  const ro = new ResizeObserver(schedule);
  ro.observe(box);
  schedule();
  return () => {
    cancelAnimationFrame(raf);
    duck.controls.removeEventListener('change', schedule);
    duck.controls.removeEventListener('start', onStart);
    duck.controls.removeEventListener('end', onEnd);
    ro.disconnect();
    tags.forEach((t) => t.remove());
    svg.remove();
  };
}
