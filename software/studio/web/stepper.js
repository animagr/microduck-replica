// Shared numeric stepper control: a "−" input "+" row. Used by the servo page, Settings › Battery, and the weights in Settings › Model.
// Depends only on CSS variables already on the page, follows the light/dark theme; the pure computation parts are exported separately so tests/stepper.test.mjs can test them directly.
import { html, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';

export const HOLD_DELAY_MS = 400;      // after pressing and holding, wait this long first
export const HOLD_INTERVAL_MS = 80;    // then step once every this long

const finite = (v) => typeof v === 'number' && Number.isFinite(v);

// Number of decimal places in step (0.5 → 1, 0.01 → 2)
export function stepperDecimals(step) {
  const s = String(step == null ? 1 : step);
  const m = /^[-+]?(\d+)(?:\.(\d+))?(?:[eE]([-+]?\d+))?$/.exec(s);
  if (!m) return 0;
  const frac = m[2] ? m[2].length : 0;
  const exp = m[3] ? Number(m[3]) : 0;
  return Math.max(0, frac - exp);
}

// Turn the input box string into a number; empty strings and non-numbers return null
export function stepperNumber(raw) {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  if (typeof raw !== 'string') return null;
  const s = raw.trim();
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function stepperClamp(v, min, max) {
  let n = v;
  if (finite(min) && n < min) n = min;
  if (finite(max) && n > max) n = max;
  return n;
}

// When value is empty, start from min (or 0 if there is no min); round only to step's decimal places, to avoid 0.30000000000000004
export function stepperStep(value, delta, { min, max, step = 1 } = {}) {
  const st = finite(step) && step > 0 ? step : 1;
  const base = finite(value) ? value : finite(min) ? min : 0;
  const raw = base + (finite(delta) ? delta : 0) * st;
  return stepperClamp(Number(raw.toFixed(stepperDecimals(st))), min, max);
}

export function stepperText(v) {
  if (v === '' || v == null) return '';
  const n = stepperNumber(v);
  return n === null ? '' : String(n);
}

// Press-and-hold repeat increment/decrement: after start(), wait delay, then call fire every `every` ms; stop() stops at any time.
// timers can be swapped for a fake clock, for tests.
export function createHoldRepeater(fire, { delay = HOLD_DELAY_MS, every = HOLD_INTERVAL_MS, timers = globalThis } = {}) {
  let timeoutId = null;
  let intervalId = null;
  const stop = () => {
    if (timeoutId !== null) { timers.clearTimeout(timeoutId); timeoutId = null; }
    if (intervalId !== null) { timers.clearInterval(intervalId); intervalId = null; }
  };
  const start = () => {
    stop();
    timeoutId = timers.setTimeout(() => {
      timeoutId = null;
      fire();
      intervalId = timers.setInterval(fire, every);
    }, delay);
  };
  return { start, stop };
}

const CSS = `
.md-stepper { display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; font-size: 15px; color: var(--text); }
.md-stepper .md-stepper-btn {
  width: 32px; height: 32px; min-width: 32px; flex: none; padding: 0;
  border: 1px solid var(--line, #D1D1D6);
  border: 1px solid color-mix(in srgb, var(--text) 22%, transparent);
  border-radius: 8px;
  background: var(--board, #FFF);
  background: color-mix(in srgb, var(--text) 7%, var(--board, #FFF));
  color: var(--text); font: inherit; font-size: 19px; line-height: 1;
  display: inline-flex; align-items: center; justify-content: center;
  user-select: none; -webkit-user-select: none; touch-action: none; cursor: pointer;
}
.md-stepper .md-stepper-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--text) 13%, var(--board, #FFF)); }
.md-stepper .md-stepper-btn:active:not(:disabled) { background: color-mix(in srgb, var(--text) 19%, var(--board, #FFF)); }
.md-stepper .md-stepper-btn:disabled { opacity: .32; cursor: default; }
.md-stepper input.md-stepper-input[type=text] {
  width: 92px; min-width: 92px; height: 32px; padding: 0 8px;
  border: 1.5px solid var(--line, #D1D1D6);
  border: 1.5px solid color-mix(in srgb, var(--text) 28%, transparent);
  border-radius: 8px; background: var(--board, #FFF); color: var(--text);
  font: inherit; font-size: 15px; font-variant-numeric: tabular-nums; text-align: center;
  outline: none; -moz-appearance: textfield; appearance: textfield;
}
.md-stepper input.md-stepper-input[type=text]:focus {
  border-color: var(--blue);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 20%, transparent);
}
.md-stepper input.md-stepper-input::-webkit-outer-spin-button,
.md-stepper input.md-stepper-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.md-stepper .md-stepper-unit { color: var(--text-2); white-space: nowrap; }
@media (max-width: 560px), (pointer: coarse) {
  .md-stepper .md-stepper-btn { width: 40px; height: 40px; min-width: 40px; }
  .md-stepper input.md-stepper-input[type=text] { height: 40px; }
}
`;

function ensureCss() {
  if (typeof document === 'undefined') return;
  let s = document.getElementById('md-stepper-css');
  if (!s) {
    s = document.createElement('style');
    s.id = 'md-stepper-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }
}

export function Stepper({ value, min, max, step = 1, onChange, disabled = false, unit, 'aria-label': ariaLabel, placeholder, title, className = '' }) {
  ensureCss();
  const inputRef = useRef(null);
  const editingRef = useRef(false);
  const valueRef = useRef(stepperNumber(value) ?? '');
  const propsRef = useRef({ min, max, step, onChange, disabled });
  propsRef.current = { min, max, step, onChange, disabled };
  const repeaterRef = useRef(null);
  const holdDirRef = useRef(1);
  const stopHold = useCallback(() => { repeaterRef.current?.stop(); }, []);

  const nudgeRef = useRef(null);
  nudgeRef.current = (dir) => {
    const p = propsRef.current;
    if (p.disabled) return false;
    const before = valueRef.current;
    const next = stepperStep(before, dir, p);
    if (next === before) return false;
    valueRef.current = next;
    if (inputRef.current) inputRef.current.value = stepperText(next);
    p.onChange?.(next);
    return true;
  };

  const commitInput = (notify) => {
    const before = valueRef.current;
    const raw = inputRef.current ? inputRef.current.value : '';
    let next;
    if (raw.trim() === '') next = '';
    else {
      const n = stepperNumber(raw);
      next = n === null ? before : stepperClamp(n, propsRef.current.min, propsRef.current.max);
    }
    valueRef.current = next;
    if (inputRef.current) inputRef.current.value = stepperText(next);
    if (notify && next !== before) propsRef.current.onChange?.(next);
    return next;
  };

  useEffect(() => {
    const n = stepperNumber(value) ?? '';
    valueRef.current = n;
    if (!editingRef.current && inputRef.current) inputRef.current.value = stepperText(n);
  }, [value]);

  useEffect(() => {
    const stop = () => stopHold();
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    window.addEventListener('blur', stop);
    return () => {
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      window.removeEventListener('blur', stop);
      stop();
    };
  }, [stopHold]);

  const startHold = (dir) => (e) => {
    if (propsRef.current.disabled) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    if (editingRef.current && inputRef.current) inputRef.current.blur();
    stopHold();
    const changed = nudgeRef.current(dir);
    if (!changed) return;
    holdDirRef.current = dir;
    if (!repeaterRef.current) {
      repeaterRef.current = createHoldRepeater(() => {
        if (!nudgeRef.current(holdDirRef.current)) stopHold();
      });
    }
    repeaterRef.current.start();
  };

  const stepOnce = (dir) => (e) => {
    if (e.detail !== 0) return;        // mouse/touch is already handled by pointerdown; this only handles keyboard and assistive technology
    if (editingRef.current && inputRef.current) inputRef.current.blur();
    nudgeRef.current(dir);
  };

  const val = stepperNumber(value);
  const atMin = disabled || (finite(min) && finite(val) && val <= min);
  const atMax = disabled || (finite(max) && finite(val) && val >= max);

  return html`<span class=${'md-stepper ' + className}>
    <button type="button" class="md-stepper-btn" disabled=${atMin} aria-label=${(ariaLabel || '数值') + ' 减'}
      onPointerDown=${startHold(-1)} onPointerUp=${stopHold} onPointerLeave=${stopHold} onPointerCancel=${stopHold}
      onBlur=${stopHold} onClick=${stepOnce(-1)}>−</button>
    <input ref=${inputRef} class="md-stepper-input" type="text" inputmode="decimal" autocomplete="off" spellcheck="false"
      defaultValue=${stepperText(val)} disabled=${disabled} placeholder=${placeholder} title=${title}
      aria-label=${ariaLabel}
      onFocus=${() => { editingRef.current = true; stopHold(); }}
      onBlur=${() => { if (!editingRef.current) { stopHold(); return; } editingRef.current = false; commitInput(true); stopHold(); }}
      onKeyDown=${(e) => {
        if (e.key === 'Enter') { e.preventDefault(); if (editingRef.current) { editingRef.current = false; commitInput(true); } e.currentTarget.blur(); }
        else if (e.key === 'Escape') { e.preventDefault(); if (inputRef.current) inputRef.current.value = stepperText(valueRef.current); e.currentTarget.blur(); }
      }} />
    <button type="button" class="md-stepper-btn" disabled=${atMax} aria-label=${(ariaLabel || '数值') + ' 加'}
      onPointerDown=${startHold(1)} onPointerUp=${stopHold} onPointerLeave=${stopHold} onPointerCancel=${stopHold}
      onBlur=${stopHold} onClick=${stepOnce(1)}>+</button>
    ${unit ? html`<span class="md-stepper-unit">${unit}</span>` : null}
  </span>`;
}
