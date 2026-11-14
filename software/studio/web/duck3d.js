// The 3D duck on the stage. The model is servo-web's model/ (exported from the official CAD, see model/NOTICE.md).
//
// Rules (review-design-v3 V2, V7):
// - Show "now": joint angles come from the state stream, the body tilts by the IMU's gravity direction; no auto-rotation.
// - Can be dragged to rotate and stays wherever it's rotated to (user, Oct 18: don't spring back by itself); only clicking "reset view" (「回正」) returns to the default camera position.
// - Clicking a servo selects it (click to select, darkened, no zoom needed):
//   the 15 xl330 parts in the model are the housings of the 15 servos. Explicit bindings in the model are used first, the rest are matched one to one by distance;
//   if what was clicked isn't a servo (leg, shell), select the servo that drives that part. Moving 6 pixels or more between press and release counts as a drag, not a click.
// - Redraw only on change: the model has 400k+ faces, and drawing at 60 fps all the time spins up laptop fans and makes phones hot.
// - When data is stale, the outside adds .stale to the canvas (desaturated, translucent); not handled here.
import * as THREE from './vendor/three/three.module.js';
import { OrbitControls } from './vendor/three/addons/OrbitControls.js';
import { RoomEnvironment } from './vendor/three/addons/RoomEnvironment.js';
import { toCreasedNormals } from './vendor/three/addons/BufferGeometryUtils.js';

export const JOINT_NAMES = ['left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle',
  'neck_pitch', 'head_pitch', 'head_yaw', 'head_roll', 'mouth',
  'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle'];

const VIEWS = { front34: [-30, 12], back: [180, 12], back34: [205, 14], front: [0, 8] };

function materialFor(rgba) {
  const [r, g, b] = rgba;
  const near = (a, bb, c) => Math.abs(r - a) < 0.04 && Math.abs(g - bb) < 0.04 && Math.abs(b - c) < 0.04;
  let color, rough = 0.5;
  if (near(0.98, 0.71, 0.0)) { color = '#F5B400'; rough = 0.42; }            // yellow printed parts
  else if (near(0.29, 0.29, 0.29)) { color = '#5E6167'; rough = 0.58; }      // servos
  else if (near(0.35, 0.38, 0.40)) { color = '#4C5157'; rough = 0.55; }
  else if (near(0.26, 0.28, 0.30)) { color = '#2F3338'; rough = 0.4; }
  else if (near(0.54, 0.85, 0.83)) { color = '#86D3CC'; rough = 0.6; }       // soles
  else if (r > 0.75 && g > 0.75 && b > 0.75) { color = '#ECECE8'; rough = 0.5; } // white shell
  else color = new THREE.Color(r, g, b).getStyle();
  return new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: rough, metalness: 0, envMapIntensity: 0.55 });
}

// Model decoding (dequantizing vertices + creased normals) takes several hundred ms on phones: done only once per page load, reused directly when switching back to the page.
// The geometry is shared by all Duck3D instances and is not freed when any one of them is disposed.
let modelCache = null;
// Decode and compute creased normals in a background thread (model-worker.js) first so the page doesn't freeze; only compute on the main thread if the browser doesn't support workers (the old way)
function loadInWorker(base) {
  return new Promise((resolve, reject) => {
    let w;
    try { w = new Worker(new URL('./model-worker.js', import.meta.url)); } catch (e) { reject(e); return; }
    w.onmessage = (e) => {
      w.terminate();
      if (!e.data.ok) { reject(new Error(e.data.error)); return; }
      const geoms = {};
      for (const [name, m] of Object.entries(e.data.meshes)) {
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(m.position, 3));
        g.setAttribute('normal', new THREE.BufferAttribute(m.normal, 3));
        if (m.index) g.setIndex(new THREE.BufferAttribute(m.index, 1));
        geoms[name] = g;
      }
      window.__model = { cached: !!e.data.cached, at: performance.now() };   // for debugging: when the model was ready, and whether it was read from cache
      resolve({ mj: e.data.mj, geoms });
    };
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || 'worker 出错')); };
    w.postMessage({ base: new URL(base, location.href).href });
  });
}
async function loadModel(base) {
  if (!modelCache) {
    modelCache = loadInWorker(base).catch(() => (async () => {
      const mj = await (await fetch(base + 'model.json', { cache: 'no-cache' })).json();
      const bin = await (await fetch(base + 'meshes.bin')).arrayBuffer();
      const geoms = {};
      for (const [name, m] of Object.entries(mj.meshes)) {
        const q = new Int16Array(bin, m.voff, m.nverts * 3);
        const pos = new Float32Array(m.nverts * 3);
        for (let i = 0; i < m.nverts; i++) for (let k = 0; k < 3; k++) {
          const span = m.bbox_max[k] - m.bbox_min[k] || 1;
          pos[i * 3 + k] = m.bbox_min[k] + (q[i * 3 + k] + 32768) / 65535 * span;
        }
        const idx = m.index_bytes === 2 ? new Uint16Array(bin, m.ioff, m.ntris * 3) : new Uint32Array(bin, m.ioff, m.ntris * 3);
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        g.setIndex(new THREE.BufferAttribute(idx, 1));
        geoms[name] = toCreasedNormals(g, Math.PI / 6);     // remove the faceted look
      }
      return { mj, geoms };
    })()).catch((e) => { modelCache = null; throw e; });
  }
  return modelCache;
}

const same = (a, b, eps) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < eps);

export class Duck3D {
  // pageScroll (used by the overview stage, overview rearrangement review O2): the overview is a home page you scroll down, so the stage must not swallow the wheel and fingers:
  // disable zoom (wheel left to the page: OrbitControls doesn't preventDefault when enableZoom=false); on phones one finger is left for page scrolling
  // (canvas touch-action set back to pan-y, one finger doesn't rotate), two fingers rotate the view; on desktop the mouse still drags to rotate. Files in vendor aren't modified; settings are changed after construction
  constructor(canvas, { view = 'front34', centerX = 0.61, centerY = 0.5, fill = 0.92, pageScroll = false } = {}) {
    this.canvas = canvas;
    canvas.__duck3d = this;   // for debugging (e2e also checks frames: not drawn when out of the viewport)
    this.frames = 0;          // how many frames were actually drawn
    this.view = view;
    this.centerX = centerX;   // where in the frame width the duck's horizontal center goes (making room for text on the left)
    this.centerY = centerY;   // vertical (on phones the text is below, so the duck goes higher)
    this.fill = fill;
    this.joints = {};         // joint name -> { pivot, axis } (names match robotd's JOINT_NAMES)
    this.dirty = true;
    this.ready = false;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    // 400k faces at full high-DPI resolution make rotation laggy and phones hot: at most 1.5x (user, Oct 18: rotating and zooming were a bit laggy)
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.01, 20);
    this.camera.up.set(0, 0, 1);
    this.trunk = new THREE.Group();    // the layer that tilts with the IMU
    this.content = new THREE.Group();
    this.trunk.add(this.content);
    this.scene.add(this.trunk);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.addEventListener('change', () => { this.dirty = true; });
    this.controls.addEventListener('start', () => { this._snapAt = null; this.onUserMove && this.onUserMove(); });
    this.controls.addEventListener('end', () => { if (this._sel) this._seeThrough(); });
    if (pageScroll) {
      this.controls.enableZoom = false;
      this.controls.touches = { ONE: null, TWO: THREE.TOUCH.DOLLY_ROTATE };   // ONE is neither ROTATE nor PAN: one finger does nothing
      canvas.style.touchAction = 'pan-y';          // OrbitControls sets it to none in its constructor (OrbitControls.js:36)
    }
    // not drawn when off screen (review O9): while on #/pad the stage is scrolled out, but the 10-per-second status still makes it dirty; dirty is kept and it redraws when back
    this._onScreen = true;
    if (typeof IntersectionObserver !== 'undefined') {
      this._io = new IntersectionObserver((es) => { for (const e of es) this._onScreen = e.isIntersecting; if (this._onScreen) this.dirty = true; });
      this._io.observe(canvas);
    }
    let down = null;
    canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    canvas.addEventListener('pointerup', (e) => {
      if (!down || !this.onPick || !this.ready) return;
      const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
      down = null;
      if (moved < 6) { const j = this.pick(e.clientX, e.clientY); if (j) this.onPick(j); }
    });
    this.servoOf = {};        // joint name -> that servo's housing part
    this._resize = new ResizeObserver(() => this.resize());
    this._resize.observe(canvas);
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  async load(base = 'model/') {
    const { mj, geoms } = await loadModel(base);
    if (this._dead) return;
    const mjq = (q) => new THREE.Quaternion(q[1], q[2], q[3], q[0]);
    const objs = [];
    const jointOf = [];       // which joint drives each body (itself if it has a joint, otherwise follows the parent body)
    const root = mj.bodies.find((b) => b.parent < 0);
    if (root) { this.trunk.position.set(...root.pos); this.content.position.copy(this.trunk.position).negate(); }
    for (const b of mj.bodies) {
      const node = new THREE.Group();
      node.position.set(...b.pos); node.quaternion.copy(mjq(b.quat));
      let inner = node;
      if (b.joint) {
        const pivot = new THREE.Group(); node.add(pivot); inner = pivot;
        this.joints[b.joint.name] = { pivot, axis: new THREE.Vector3(...b.joint.axis).normalize() };
      }
      jointOf.push(b.joint ? b.joint.name : (b.parent >= 0 ? jointOf[b.parent] : null));
      for (const g of b.geoms) {
        const mesh = new THREE.Mesh(geoms[g.mesh], materialFor(g.rgba));
        mesh.userData.jointOf = jointOf[jointOf.length - 1];
        mesh.userData.servo = g.mesh === 'xl330';
        if (mesh.userData.servo && g.servo_joint) mesh.userData.servoJoint = g.servo_joint;
        mesh.position.set(...g.pos); mesh.quaternion.copy(mjq(g.quat)); inner.add(mesh);
      }
      objs.push({ inner });
      if (b.parent < 0) this.content.add(node); else objs[b.parent].inner.add(node);
    }
    this._lights();
    this._mapServos();
    this.ready = true;
    this._frame();
    this.dirty = true;
  }

  _lights() {
    const key = new THREE.DirectionalLight(0xfff0dc, 2.4); key.position.set(0.35, 0.3, 1.4);
    const fill = new THREE.DirectionalLight(0xe4ecff, 0.8); fill.position.set(0.3, -0.8, 0.35);
    const rim = new THREE.DirectionalLight(0xcfe0ff, 1.8); rim.position.set(-0.7, -0.5, 0.6);
    this.scene.add(key, fill, rim, new THREE.HemisphereLight(0xffffff, 0x2a2b2f, 0.35));
    // Soft contact shadow under the feet: a radial gradient texture instead of real-time shadows (saves GPU, no hard edges)
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const ctx = c.getContext('2d');
    const grd = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
    grd.addColorStop(0, 'rgba(0,0,0,0.55)'); grd.addColorStop(0.5, 'rgba(0,0,0,0.2)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grd; ctx.fillRect(0, 0, 256, 256);
    this.blob = new THREE.Mesh(new THREE.PlaneGeometry(0.3, 0.26),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
    this.scene.add(this.blob);
  }

  /** Joint angles: robotd's robot.state.joints (radians, in JOINT_NAMES order, already calibrated; used as is, not multiplied by direction).
   *  Mapping per review-impl-plan I13: joints[i] → the joint named JOINT_NAMES[i] in the model. */
  setJoints(arr) {
    if (!this.ready || !Array.isArray(arr)) return;
    // while the duck stands still the data is nearly identical every frame: don't redraw if unchanged (400k faces; drawing constantly makes phones hot)
    if (this._lastJoints && same(arr, this._lastJoints, 1e-4)) return;
    this._lastJoints = arr.slice();
    arr.forEach((rad, i) => {
      const j = this.joints[JOINT_NAMES[i]];
      if (j && typeof rad === 'number' && isFinite(rad)) j.pivot.quaternion.setFromAxisAngle(j.axis, rad);
    });
    this.dirty = true;
  }

  /** Gravity direction in the body frame (robot.state.safety.gravity, about [0, 0, -1] when upright); null means no data, stay upright.
   *  setFromUnitVectors gives the shortest rotation, only pitch and roll, yaw is always 0 (it never spins). */
  setGravity(g) {
    if (!this.ready) return;
    if (!g) { if (this._lastGravity) { this._lastGravity = null; this.trunk.quaternion.identity(); this.dirty = true; } return; }
    if (this._lastGravity && same(g, this._lastGravity, 1e-4)) return;
    this._lastGravity = g.slice();
    const v = new THREE.Vector3(...g);
    if (v.lengthSq() < 1e-6) return;
    this.trunk.quaternion.setFromUnitVectors(v.normalize(), new THREE.Vector3(0, 0, -1));
    this.dirty = true;
  }

  setView(view) { this.view = view; this._frame(); }

  // Explicit CAD bindings take precedence, so the mouth housing isn't mismatched because it is near the yaw axis origin; the rest keep the existing pairing.
  _mapServos() {
    this.scene.updateMatrixWorld(true);
    const servos = [];
    this.content.traverse((o) => { if (o.isMesh && o.userData.servo) servos.push(o); });
    const usedM = new Set(), usedJ = new Set();
    const bind = (m, name) => {
      usedM.add(m); usedJ.add(name);
      m.userData.joint = name;
      m.userData.baseColor = m.material.color.clone();
      this.servoOf[name] = m;
    };
    this.servoOf = {};
    for (const m of servos) {
      const name = m.userData.servoJoint;
      if (!name) continue;
      if (!this.joints[name] || usedJ.has(name)) throw new Error(`模型舵机绑定无效或重复：${name}`);
      bind(m, name);
    }
    const pairs = [];
    for (const m of servos) {
      const c = new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3());
      for (const [name, j] of Object.entries(this.joints)) {
        pairs.push([c.distanceTo(j.pivot.getWorldPosition(new THREE.Vector3())), m, name]);
      }
    }
    pairs.sort((a, b) => a[0] - b[0]);
    for (const [, m, name] of pairs) {
      if (usedM.has(m) || usedJ.has(name)) continue;
      bind(m, name);
    }
  }

  /** Which joint a screen point hit. First compare only against the 15 servos (the shell doesn't block: the ones inside the head shell can be hit too);
   *  if no servo was hit, look at which part was hit and take the joint that drives it. */
  pick(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2((clientX - r.left) / r.width * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const servo = ray.intersectObjects(Object.values(this.servoOf), false)[0];
    if (servo) return servo.object.userData.joint;
    const meshes = [];
    this.content.traverse((o) => { if (o.isMesh) meshes.push(o); });
    const hit = ray.intersectObjects(meshes, false)[0];
    return hit ? hit.object.userData.jointOf || null : null;
  }

  // The selected servo is hidden behind the shell (the ones in the head): parts in front become translucent so it's visible. Recomputed after changing the view and releasing
  _seeThrough() {
    for (const m of this._ghosted || []) {
      m.material.transparent = false; m.material.opacity = 1; m.material.depthWrite = true; m.material.needsUpdate = true;
    }
    this._ghosted = [];
    if (!this._sel) return;
    this.scene.updateMatrixWorld(true);
    const c = new THREE.Box3().setFromObject(this._sel).getCenter(new THREE.Vector3());
    const dir = c.clone().sub(this.camera.position);
    const dist = dir.length();
    const ray = new THREE.Raycaster(this.camera.position, dir.normalize(), 0, dist);
    const meshes = [];
    this.content.traverse((o) => { if (o.isMesh && o !== this._sel) meshes.push(o); });
    for (const h of ray.intersectObjects(meshes, false)) {
      if (h.distance < dist - 0.004 && !this._ghosted.includes(h.object)) {
        const m = h.object;
        m.material.transparent = true; m.material.opacity = 0.22; m.material.depthWrite = false; m.material.needsUpdate = true;
        this._ghosted.push(m);
      }
    }
    this.dirty = true;
  }

  /** Select a servo: its housing changes to color (the group color), the previous one is restored. name null restores all. */
  select(name, color) {
    if (this._sel && this._sel.userData.baseColor) this._sel.material.color.copy(this._sel.userData.baseColor);
    this._sel = name ? this.servoOf[name] || null : null;
    if (this._sel) this._sel.material.color.set(color || '#2F7CF6');
    this._seeThrough();
    this.dirty = true;
  }

  /** Slowly rotate back to the default camera position (the stage's "reset view" button). */
  resetView() { this._snapAt = performance.now(); this.dirty = true; }

  _frame() {
    if (!this.ready) return;
    this.scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.trunk);
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    this.blob.position.set(center.x, center.y, box.min.z + 0.0008);
    const [azDeg, elDeg] = VIEWS[this.view] || VIEWS.front34;
    const az = THREE.MathUtils.degToRad(azDeg), el = THREE.MathUtils.degToRad(elDeg);
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const dist = (size.z / this.fill) / (2 * Math.tan(fov / 2));
    const look = new THREE.Vector3(center.x, center.y, box.min.z + size.z * 0.5);
    this.home = { pos: new THREE.Vector3(look.x + dist * Math.cos(el) * Math.cos(az), look.y + dist * Math.cos(el) * Math.sin(az), look.z + dist * Math.sin(el)), target: look };
    this.camera.position.copy(this.home.pos);
    this.controls.target.copy(look);
    this.controls.update();
    this._applyOffset();
    this.dirty = true;
  }

  // Place the duck at (centerX, centerY) in the frame (making room for text): shift the camera's view frustum, without moving the camera
  _applyOffset() {
    const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1;
    this.camera.aspect = w / h;
    this.camera.setViewOffset(w, h, (0.5 - this.centerX) * w, (0.5 - this.centerY) * h, w, h);
    this.camera.updateProjectionMatrix();
  }

  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this._applyOffset();
    this.dirty = true;
  }

  _loop(now) {
    if (this._dead) return;
    if (this._snapAt && now > this._snapAt && this.home) {
      // "reset view" was clicked: slowly rotate back to the default camera position
      this.camera.position.lerp(this.home.pos, 0.18);
      this.controls.target.lerp(this.home.target, 0.18);
      if (this.camera.position.distanceTo(this.home.pos) < 1e-4) this._snapAt = null;
      this.dirty = true;
    }
    if (this.controls.update()) this.dirty = true;
    // don't draw when the page is in the background, the overview is hidden (switched to another page), or the stage is scrolled off screen (dirty is kept, redraws when back)
    if (this.dirty && this.ready && !document.hidden && this._onScreen && this.canvas.offsetParent !== null) {
      this.renderer.render(this.scene, this.camera); this.dirty = false; this.frames++;
    }
    requestAnimationFrame(this._loop);
  }

  dispose() {
    this._dead = true;
    this._resize.disconnect();
    if (this._io) this._io.disconnect();
    this.controls.dispose();
    // materials and textures belong to this instance, free them; geometry is a shared cache, leave it
    this.scene.traverse((o) => {
      if (o.material) { o.material.map?.dispose(); o.material.dispose(); }
    });
    this.scene.environment?.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();     // browsers limit how many WebGL contexts can be open at once; switching pages a few times would use them up
  }
}
