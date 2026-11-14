# Adding sit down and stand up to web recording: acceptance check and deployment

**English** · [简体中文](2026-10-25-web-posture-recording.md)

Date: 2026-10-25 (JST). The user pointed out that recording only sit down/stand up was reported as "没有有效动作" (No valid actions), then replied explicitly "Yes, record sit down and stand up too." This round corrects the original first version's scope, which excluded sit/stand; see the [design](../specs/2026-10-25-web-posture-recording-design.md) and [plan](../plans/2026-10-25-web-posture-recording.md).

**Result: the original control URL has been updated, and the user confirmed "It saves, and sit/stand playback works too."** This confirmation covers web sit/stand recording, saving and actual playback on this one duck; it does not extend to all model skills or long-duration motion having passed acceptance.

## Frozen version and behavior

The installed runtime code commit is `aa825fcf7ad153f959ed793e9ed871cabbc24e29`. It consists of 73c9a4f (backend/strict format/simulator), 396af04 (evidence loss and time boundaries), 75ce49d (web hints and full browser flow) and aa825fc (keeping manual sit/stand takeover). It was fast-forward merged into studio-dev, and the existing untracked voice source and UI notes were kept.

Now recording only "坐下→等待→站起→等待" (Sit down → Wait → Stand up → Wait) also produces a draft that can be saved, supported by both the remote buttons and the web D-pad down. Sit/stand is recorded as the whitelisted target `studio.posture {target: sit|stand}`, not by directly saving a toggle. Playback first checks the current posture and does not press again if already at the target; it continues only after confirmation via the fresh policy phase and consecutive actual/target joint readback. The sitting flag disappears as soon as rising starts, so neither it nor homed alone can determine that rising is complete.

The new module `motion_posture.py` is separate from the original session/timeline. It takes the policy, sample time and joints/targets from the existing robot.state and waits for three distinct new samples; the source evidence must be fresh and consistent with the bus/posture. A read-only measurement of eight standing samples showed a maximum static target deviation of about 0.1305–0.1318 rad, so a 0.18 rad tolerance is used together with requiring consecutive stability and the correct policy phase; this is not a guarantee of exact physical position. The wait is capped at 15 seconds, an unknown receipt does not retry the switch, and late receipts and frames captured before the receipt cannot lift the barrier of a new step.

Missing/stale phase or joint information, posture changes outside the target, the existing protections, physical gamepad connection, page switch/background/focus loss, disconnection and heartbeat timeout all cancel subsequent automated output. Recovery of evidence can only release the hold of the physical step and does not resume a canceled session. An ordinary pause/stop does not physically cancel a sit/stand already started, and the page explicitly states that the current sit/stand will still complete; continuous control is cleared and subsequent steps are frozen/terminated, without automatically returning to HOME or turning torque off, and the e-stop still uses the original channel. When the actual posture is known and consistent, the user is allowed to explicitly take over manually toward the opposite target, so that the strict automated playback check does not wrongly block an ordinary "stand up"; unknown retries toward the same target are still rejected.

Recordings containing sit/stand use v2; old v1 is still readable, and the original limits of 60 seconds/6,000 events/1 MiB/20 clips are kept. The recording duration limit also applies during the waiting phase; playback waiting extends the actual playback time. A recording ending in sitting can be played once; multiple loops require standing to be recorded at the end, otherwise it is explicitly rejected, and no implicit stand-up is added. Kick, roll, pick-up, torque on/off, policy start/stop, model switching and audio/video recording remain outside this round's scope.

## Software checks

The pinned runtime code passed **389 checks**, without double-counting independent reviews or integration retests:

| Scope | Final result | Evidence (workspace artifacts/web-posture-recording-20261025/) |
| --- | --- | --- |
| Sit/stand, motion and original gamepad backend | 241 items, 33.480 seconds, OK | backend-final2.log |
| HTTP, original virtual gamepad, overview and sensor regression | 140 items, 330.657 seconds, OK | regression-final.log |
| Page session/heartbeat | 7 items, OK | This round's Node tool output |
| Full flow with real Studio + fake robotd + Edge | 1 item, 64.262 seconds, OK | browser-final.log, browser-final/browser.json |

The independent requirements review reproduced and fixed: wrongly resuming playback after step evidence was lost, an external sitting posture after having stood up still allowing movement to continue, and waiting bypassing the 60-second limit. The independent quality review reproduced and fixed: the strict convergence check wrongly blocking an ordinary manual stand up/recovery. After the fixes the review passed, and the quality review additionally ran 82 items, all passing; after merging into studio-dev, 82 items were run again, 7.189 seconds, OK.

Commands are run in the software/studio directory:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_posture','tests.test_motion_studio','tests.test_pad'])"
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_http','tests.test_vpad_e2e','tests.test_overview_e2e','tests.test_sensors_ui','tests.test_sensors_http'])"
node --test tests/motion_heartbeat.test.mjs
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio_e2e'])"
```

Sit/stand requests the browser actually sent to fake robotd: 2 during recording, 2 for single playback, 6 for triple playback; stopping right after sitting down sent only 1, and switching pages also sent only 1, with no subsequent stand-up. The saved JSON is v2 with target order sit, stand; console errors `[]`, and the desktop 1440px and phone 390/320px layouts and screenshots passed. The existing Lively, save/rename/refresh/delete and playback pause/resume checks are kept.

The earlier test first reproduced the original "sitting down ends the recording" before implementing. The long browser test once triggered a normal background cancellation because Windows hid the headless tab; diagnosis confirmed hidden, activity=false and a stop request, after which the test used focus simulation to keep the test page active, without changing the product's background/focus-loss protection. Another 241-item run hit WinError 145 in the original pairing test while cleaning up the temporary log directory; that single item passed five times in a row and the final full suite passed, and the unrelated pairing code was not modified. The old logs are kept, and it is not claimed that the original test resource race was fixed.

## Device switch and user confirmation

The user first replied explicitly "Stopped, standing still". The install script again confirmed motion/control, real-time policy_enabled=false and no servo session before switching Studio. After checking the frozen Git bytes and dependency versions, only seven files were updated:

```text
studio/motion_posture.py    studio/motion_store.py
studio/motion_studio.py    studio/pad.py
studio/pad_drive.py        web/motion-studio.js
web/motion-studio.css
```

Only microduck-studio was restarted; PID went from 21540 to 29493. The PIDs and monotonic start times of robotd=1105, padd=1138 and duck-echo=1110 were the same before and after; four services active, voice enabled. The seven installed files matched the manifest hashes, and the original 12 user data files were byte-for-byte identical to the backup taken when the web service was stopped. The root page, healthz, pad.js and the motion assets all returned 200, the hashes of the actually served JS/CSS matched the installed files, and static assets are no-cache.

The private backup is `/home/radxa/.microduck-backups/web-motion-20261025-aea50f88a1` (0700), containing the old runtime files and user-state. The workspace `artifacts/web-posture-recording-20261025/deployment/` keeps the pre-update programs, manifest, switch results and readback; the read-only real joint samples are in `actual-posture-samples.json` and are not included in the general delivery. The existing login protection stays, and the motion snapshot was not fetched by bypassing authentication. Automated tests do not actively send sit/stand or walk commands to the real duck.

After installation, the user tried "开始走→开始录制→坐下→等确认→站起→等确认→结束→命名保存→回放一次" (Start walking → Start recording → Sit down → Wait for confirmation → Stand up → Wait for confirmation → Finish → Name and save → Play once), and replied **"It saves, and sit/stand playback works too."** This is recorded as this round's real-hardware pass.

## Later delivery and rollback boundaries

The frozen source archive, version/hash manifest and acceptance copy are saved in the workspace `artifacts/web-posture-recording-20261025/release/`. They contain no personal passwords, SSH keys, home Wi-Fi, pairing or state. This round did not rebuild the image, enable updaterd or publish publicly; later unified packages/images must use the same frozen source and be accepted again.

When the single-unit switch fails, the script restores the old runtime files and restarts only Studio; this time it succeeded, and no failure injection was done on real hardware. Before a manual rollback, first stop the policy, confirm there is no servo session, stop Studio, restore the old files according to the backup manifest, delete only the new modules marked in the manifest as not previously existing, then start and check the web page. Actions saved later are kept and are not directly overwritten with the old state. Rolling back to code that only supports v1 skips v2, which must not be deleted or treated as a corrupted file because of this; restoring the new code can read them again.
