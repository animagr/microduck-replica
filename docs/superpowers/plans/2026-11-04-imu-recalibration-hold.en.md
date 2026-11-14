# IMU recalibration standing-pose capture implementation plan

**English** · [简体中文](2026-11-04-imu-recalibration-hold.md)

> **For agentic workers:** Execute with the item-by-item verification approach of executing-plans; when done, do an independent review as required by requesting-code-review.

**Goal:** When redoing the initial IMU calibration, allow the robot to first enable torque in the standing pose and settle, then capture the still and lean-forward samples.

**Architecture:** Reuse commissioning hold-home and the existing sampling path. Only allow standing-hold capture for a valid redo session; mode switches still strictly require torque off. Use the existing operation-busy flag to prevent hold and session switches from interleaving.

**Tech Stack:** Python unittest, Preact/htm, Node, the existing local Edge browser tests.

- [x] Check the code actually deployed on the device against the baseline; the existing 60 backend/helper tests pass.
- [x] Write backend regression tests first: recalibration hold, standing-pose sampling/solving, rejection in invalid states, torque off before verification, concurrent busy check; run them and save the expected failures.
- [x] Minimal change to `studio/imu.py`: a valid session allows hold, settled sampling uses the existing gates, verification separately requires torque off beforehand, and standing-pose operations are mutually exclusive with session switches.
- [x] Change `web/imu.js` and verify the actual buttons and capture state in `tests/imu_bus_ui.mjs`: torque can be enabled, capture is disabled while rising, capture is allowed once settled, verification is disabled while holding torque, and results are kept after torque off.
- [x] Run the relevant backend/helper/IMU algorithm tests and the real browser tests, do an independent review and fix important issues.
- [x] Commit the fix, back up and deploy the two changed files, verify that the web service loads the new code and that the main controller/calibration are unchanged; do not send motions automatically.

Verification: 158 items across six related unittest groups passed (including real Edge page assertions); `git diff --check` and the JavaScript syntax check passed. The independent review found no P1/P2 issues introduced by this change. The browser tests actively close their own browser process, to avoid leftover child processes after the Windows Edge launcher exits interfering with temp directory cleanup.

The real-hardware install package contains only `studio/imu.py` and `web/imu.js`; old file hashes are pinned, a backup is taken before installation, and failure rolls back. The installer requires the model to be off, torque off confirmed, and no recalibration session in progress; the only restarted service is Studio. After installation, check that the main controller process, model, calibration, actuator parameters and helper are all unchanged.

Installed on duck-658d on 2026-11-04. Studio health check returned HTTP 200, and the hash of imu.js returned over HTTP matches the candidate file; main controller PID 7510 unchanged, new Studio PID 8513. The hashes of the main controller files, configuration, calibration, actuator parameters and helper are all unchanged, and the device still confirms torque off. The backup is at `/var/lib/microduck-imu-q4-bench-20261104/studio-stance-before-20261104-140519`. Enabling torque, sampling or writing calibration was not triggered remotely; the actual standing-pose sampling is left for the user to do.

## Completing the in-place HOME entry

The user's hardware test pointed out that the change above only fixed sampling inside commissioning; the entry from motion mode HOME was still blocked by "先卸力" (Turn torque off first). This change completes in-place read-only capture at HOME: it sends no motions and does not switch modes; it captures still, captures lean-forward, and computes the candidate. Finally the user turns torque off manually, and only after clicking verify does it enter the existing backup, verify, restore transaction. The torque-off check of the original root helper is kept.

- [x] Reproduce the grayed-out button using the actual browser entry from motion mode HOME, and add backend and browser regressions.
- [x] Check HOME joint error, policy off and IMU freshness, and capture body-frame gravity deduplicated by t_ns.
- [x] Bind the board, the old orientation and the main program connection generation at capture time; re-check them before and after solving and before verification.
- [x] Require manual torque off before the verification write, wait for the main program to reconnect, keep the candidate and reuse the original verify / finish transaction.
- [x] 168 related tests passed, including a delayed-reconnect test with present / hello / calib_valid_after; issues found by the independent review were all fixed.
- [x] Update the web console on the real robot and check the services, files and protected data.
- [x] Pushed to the GitHub main branch (3725b46).

Read-only real-hardware data check: before installation, duck-658d was in motion/HOME with the policy off, and HOME joint error was about 3.71°. Feeding this real readback to the candidate backend gave `coarse_sampling.available=true`, `reason=null`, meeting the gate for capturing still directly.

Installation was completed after the user turned torque off manually. Studio PID went from 8513 to 13613, main controller PID 7510 unchanged, health check HTTP 200, and the JavaScript returned over HTTP matches the digest of the tested file. The Python module digest was confirmed the same way; a read-only load of the installed module's view also reads back the in-place capture capability. The main controller, model, configuration, calibration and helper are all unchanged, and torque was not enabled, nothing was sampled and no calibration was written automatically. The backup is `/var/lib/microduck-imu-q4-bench-20261104/studio-home-entry-before-20261104-143119`. After refreshing the page, the user can go HOME and settle → recalibrate orientation → capture still → capture lean-forward; manual torque off is still required before the final write.
