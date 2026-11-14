// Two-step confirmation (third code review D4): every "takes two clicks" button shares this one: hand back to the main program, skipping the e-stop test, and future ones too.
// Previously the button itself turned into "Sure...?" in place, so a double click went straight through (the second click landed right on the changed button). Now:
// - first click: the original button stays put, and a new confirm button appears next to it (the second click of a double click lands on the original button);
// - any click within 700 ms after it appears is ignored (double clicks, quick hands, or the confirm button popping up right under the pointer can't trigger it by accident);
// - if confirm isn't clicked within 3 s it reverts; clicking the original button again after 700 ms also dismisses it.
// The browser's confirm dialog isn't used (it blocks the whole page, and on phones it also covers the torque-release button at the top).
import { html, useState, useEffect, useRef } from './vendor/preact-htm.module.js';

export const ARM_GUARD_MS = 700;
export const ARM_TIMEOUT_MS = 3000;

export function ConfirmBox({ lines = [], confirmLabel = '确定', cancelLabel = '先不', onConfirm, onCancel, busy = false, cls = '' }) {
  return html`<div class=${('confirm-box ' + cls).trim()} role="alertdialog" aria-live="polite">
    <div class="confirm-lines">${lines.map((line) => html`<p>${line}</p>`)}</div>
    <div class="confirm-acts">
      <button class="btn-light" type="button" disabled=${busy} onClick=${() => onCancel && onCancel()}>${cancelLabel}</button>
      <button class="btn-danger" type="button" disabled=${busy} onClick=${() => onConfirm && onConfirm()}>${confirmLabel}</button>
    </div>
  </div>`;
}

export function TwoStep({ label, ask, onConfirm, cls = 'btn-light', askCls = 'btn-danger', disabled = false, title, busyLabel }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const at = useRef(0);
  useEffect(() => {
    if (!armed) return undefined;
    const t = setTimeout(() => setArmed(false), ARM_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [armed]);
  const early = () => performance.now() - at.current < ARM_GUARD_MS;
  const first = (e) => {
    e.currentTarget.blur();
    if (armed) { if (!early()) setArmed(false); return; }
    at.current = performance.now();
    setArmed(true);
  };
  const second = async (e) => {
    e.currentTarget.blur();
    if (!armed || early()) return;
    setArmed(false);
    setBusy(true);
    try { await onConfirm(); } finally { setBusy(false); }
  };
  return html`<span class="two-step">
    <button class=${cls} disabled=${disabled || busy} title=${title || undefined} aria-expanded=${armed ? 'true' : 'false'}
      onClick=${first}>${busy && busyLabel ? busyLabel : label}</button>
    ${armed ? html`<button class=${`${askCls} two-step-ask`} onClick=${second}>${ask}</button>` : null}</span>`;
}
