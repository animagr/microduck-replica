# Web recording/playback and Lively: implementation and single-unit deployment acceptance

**English** · [简体中文](2026-10-25-web-motion-studio.md)

Date: 2026-10-25 (JST; device logs are +08:00). The user authorized "Go ahead... lively... build it in the web version first", and then explicitly chose the duck's existing control URL.

## Results and scope of this round

Runtime code commit: `c18783c9a2b2e2635124c6c4d53007e3fefb3ba6`, fast-forward merged into `studio-dev`. The existing uncommitted roadmap/voice notes were kept; the workspace was not reset and the voice source code was not changed.

The existing remote area gains record, pause/resume, finish/name and save, discard draft, select playback 1/3/5 times, pause/resume/stop, and rename/delete. The old servo page's Lively style now outputs through the normal `robot.head`/`robot.mouth` intents, and can be turned on on its own or during recording; generated targets are recorded, and playback no longer generates randomly.

The first version allows 60 seconds/6,000 events/1 MiB per clip, up to 20 clips. Content is saved in Studio state under `motion-recordings/` and survives refreshes and restarts. Recordings only contain accepted web movement, head/body/mouth and known sounds; they do not contain microphone audio, camera video, stand/sit/torque enable, settings or model skills. Because reliable readback of skill completion is missing, skills such as kick, roll and pick-up are rejected before sending during recording; "stopping sending commands" is not treated as the physical skill having stopped.

Recording/Lively/playback require the existing policy to be ready, fresh state and no physical gamepad conflict, and do not automatically stand up or enable torque. Each session has its own token, 100ms heartbeat, 500ms expiry; leaving the control area, background/focus loss, network loss, takeover, gamepad connection, torque off and state changes stop it, and reconnecting does not resume playback. Pause clears continuous targets; resume restores the head/body/mouth posture, and velocity waits for the next valid frame. Late targets are merged, and stale motion is not re-sent in a burst. Old recordings are rejected when the model file content/configuration fingerprint does not match.

## Software verification

Finally **351 software checks** passed: 203 motion/original gamepad backend items (44 + 159), 140 HTTP/original virtual gamepad/overview/sensor regression items, 7 Node heartbeat tests, and 1 new motion browser end-to-end test. Issues from the independent requirements and code reviews all have reproducing tests and were fixed, and the final review had no pending findings.

Run in `software/studio` (Windows Python 3.13, runtime dependencies from the existing `deps/`):

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio','tests.test_pad'])"
node --test tests/motion_heartbeat.test.mjs
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_http','tests.test_vpad_e2e','tests.test_overview_e2e','tests.test_sensors_ui','tests.test_sensors_http'])"
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio_e2e'])"
```

The browser test uses real Studio, fake robotd and Edge, and runs through Lively recording, pause/resume, name and save, playback pause/resume/stop, 3 finite loops, rename, persistence across refresh, stop on page switch, and delete. Valid motion frames actually sent: recording 30, ordinary playback 18, three-loop playback 82, with loops `[1,2,3]` seen and console errors `[]`. Playback merges late continuous frames, so it is not required that every stale sample be re-sent. Desktop 1440px and phone 390/320px screenshots were checked manually; after the final integration into `studio-dev`, the 44 motion tests passed again.

Evidence is in the workspace `artifacts/web-motion-20261025/`: `backend-final.log`, `regression.log`, `browser-final2/browser.json` and `browser-final2/shots/`. The final 203 and 140 items were all OK. An earlier round of the original pairing tests hit a file lock when Windows deleted a temporary log; its assertions completed, and the single item passed 5 times in a row as did the final full suite. The note is kept, and the pre-existing teardown resource race is not reported as a new pairing fix.

## duck-0de6 deployment readback

The deployment target is the user-chosen `http://duck-0de6:8000/#/pad`. First the device files were compared against the frozen Git bytes, confirming matching dependency versions, no out-of-bounds or symlinked install paths, and that Python compiles; an immediate readback of `motion/control`, `policy_enabled=false` and no servo session marker came before switching the program.

12 files updated:

```text
studio/motion_store.py       studio/motion_studio.py
studio/pad.py                studio/pad_drive.py
web/app.js                  web/pad.js
web/pad.css                 web/sensors.js
web/sensors.css              web/motion-heartbeat.js
web/motion-studio.js         web/motion-studio.css
```

The matching app/sensors/pad resources include the earlier local inline camera and pairing recovery versions, to avoid incomplete dependencies from replacing only the entry files. The real camera was not enabled, and the network, models, main program, padd, Bluetooth and voice service were not changed.

Only `microduck-studio` was stopped and restarted; PID went from 980 to 15333, currently active. Before and after deployment, `robotd=1105`, `padd=1138`, `duck-echo=1110` and their monotonic start times were the same; all three services active, voice enabled. All 12 installed files matched the manifest SHA-256.

`/`, `/healthz`, `/pad.js` and the three new static files all returned HTTP 200; the byte hashes of the served JS/CSS matched the installed files, with static assets `Cache-Control: no-cache`. The logs show Studio connected normally to the interface v40 main program, with no anomalies from this startup. The original 11 user data files were byte-for-byte identical to the backup taken when the service was stopped.

This device has existing web login protection; unauthenticated `/api/session` returns 401; authentication was not modified or bypassed to fetch the motion snapshot. The app's request to open the control page was queued and the existing Edge was minimized, so it is not claimed that the entry was seen on the real logged-in page or that a motion trial was done. The user was asked to refresh/log in and try Lively; **the real-hardware motion effect still awaits the user's confirmation**. This round did not actively send stand up, walk, Lively or playback commands to the real duck.

Private backup: `/home/radxa/.microduck-backups/web-motion-20261025-e6610b5e21`, directory permissions 0700, containing the pre-update runtime files, user state, manifest and success receipt. Local `artifacts/web-motion-20261025/device-before/full-runtime/` keeps the related pre-update programs, and `deployment-manifest.json`, `deployment-result.json`, `device-verification.json` keep the full check results; they are not included in the public package.

The single-unit switch script restores the old files and restarts Studio when installation/service health checks fail. No failure rollback was triggered this time; the automatic rollback branch was not fault-injected on real hardware and cannot be called a verified general OTA rollback. For manual recovery, first make sure the duck is stopped with no servo session, then stop Studio; restore the original files according to the backup manifest, delete new files from the manifest that did not exist before, restart only Studio and verify HTTP. The original state is kept; the user state in the backup is only for recovery from corruption and does not overwrite recordings saved later.

## Frozen delivery and follow-up

Local delivery directory: workspace `artifacts/web-motion-20261025/release/`, containing the Studio source archive generated from the Git commit, a version/hash manifest and a copy of this acceptance record. The package contains no device state, personal passwords, SSH keys, home Wi-Fi, pairing or recording data; it is a traceable input for maintenance and later component releases, and not yet a one-click web upgrader.

No new image was built, updaterd was not enabled, and nothing was published remotely. The existing image stays at its original version. Next, complete the user's motion trial first, then package voice and Studio into a unified versioned component, and design general install/migration/rollback plus two acceptance paths for new cards/old systems; gamepad/voice bindings for saved playbacks remain a later requirement.

## State judgment fix after the user's screenshot

The user then provided a real web screenshot, confirming the "动作录制与回放" (Motion recording and playback) and "灵动" (Lively) entries had appeared; the buttons were gray and the posture was "站着（保持）" (Standing (holding)), yet it still showed "上个模型技能没有可验证的完成状态，先手动停下策略" (The last model skill has no verifiable completion state; stop the policy manually first). The logs show the user had already performed sit/stand and "停下（站好）" (Stop (stand still)).

Read-only readback found: `robot.policies.enabled=true`, `homed=true`, `sitting=false`, while `robot.busStatus.policy_enabled=false`, `mode=motion`, `phase=control`, `homed=true`. The main program source makes clear that the former comes from the startup configuration `[policy] enabled` and is not the runtime switch. The first version's `policy_feed` wrongly required both the configuration switch and the runtime switch to be false, so after the real robot stopped the policy it still could not record the stop boundary. The original test artificially set both switches to false and did not cover the real robot's case where the configuration stays true.

Fix commit: `db970dd470f7cc1586b1ce3a4ed6a2792b1f71ce`. It uses a fresh `bus.policy_enabled=false` to confirm the robot actually stopped; after that it still must observe the runtime switch true, configuration allowing it, homed on both sides and the existing readiness conditions, and a successful RPC receipt alone does not lift the block. The hint after confirmed stop changed to "点击上方「开始走」，等新鲜回读确认「准备好走」" (Click "Start walking" above and wait for a fresh readback to confirm "Ready to walk"). The skill barrier was not removed, and the state requirements for ordinary start actions were not relaxed.

Two backend regressions were added: with the configuration continuously enabled, stop → re-enable → fresh ready can resume recording/Lively; configuration disabled alone while the runtime switch is still on cannot substitute for stop evidence. The tests first reproduced the failure and then passed with the change; finally **205 motion/original gamepad backend items passed**, and the independent review also reran the 205 items with all passing and no pending findings. The browser additionally ran through "model skill → stop and stand still → gray with a hint to start walking → start walking → buttons restored", then executed the full record/playback/save/page-switch flow; 1 browser test passed, `skill_gate_recovered=true`, console errors `[]`, and 1440/390/320px all passed. The other 140 regression items and 7 Node tests from the first round were not rerun after this narrow fix, and are not claimed as a full retest of the new version.

db970dd was deployed via SSH, updating only `studio/motion_studio.py` and restarting only Studio (15333→21540). The original robot, gamepad and voice processes are still 1105/1138/1110 with unchanged start times; four services active, voice enabled. The installed file's SHA-256 is `966c16c1f833baef6d314af899a0ad166a9c0ef8bda0ea2f60b9a015dd4f676b`; HTTP and static asset checks passed, and the original 12 user data files are preserved byte for byte.

This private backup is `/home/radxa/.microduck-backups/web-motion-20261025-8ac5417e9b` (0700). The device readback evidence is in the workspace `artifacts/web-motion-20261025/live-skill-gate-readback.json`, and the browser evidence in `skill-gate-browser/` in the same directory; the single-unit update manifest, success receipt, service/file readback and the new frozen source delivery are in `artifacts/web-motion-20261025-skill-gate/`, and the original first-round records are kept.

The user was told to refresh, click "开始走" (Start walking), wait for "准备好走" (Ready to walk), and then turn on "灵动" (Lively). The web entry has been confirmed by the user's screenshot; the real head/mouth motion effect after the fix still awaits the user's reply. This round's scripts did not actively send motion commands, did not update the image, and did not enable general online upgrades.
