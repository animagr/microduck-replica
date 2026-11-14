# IMU recalibration session supports standing-hold capture

**English** · [简体中文](2026-11-04-imu-recalibration-hold-design.md)

The user has explicitly asked for a direct fix, with no further confirmation questions for this flow.

## Scope

After a recalibration session enters commissioning, allow holding the standing pose through the existing hold-home, then capturing still and lean-forward and solving. This is only allowed when standing steadily (holding, all servos enabled, HOME error no more than 5°) with no policy/recovery/single-joint motion; all existing sample-validity and stillness checks continue to apply. First-time calibration behavior is unchanged, coarse calibration in motion mode is not opened up, and torque is not enabled nor actions sent automatically.

The session must be in commissioning or finish_failed, and the IMU source must match the session. While hold-home is in progress, repeated standing-pose enabling, coarse sampling and mode switching are blocked; the check must be kept across the asynchronous precheck.

Entering, finishing or canceling a recalibration session still requires torque off, because these steps restart the main controller. After standing-hold capture, the solved result is kept, and the page prompts to turn torque off first before verifying or canceling. The backend rejects a torque-on state again before the verification RPC; it does not turn torque off automatically.

## Change boundaries

Only Studio's `studio/imu.py` and `web/imu.js` are modified, with backend and real-browser regression tests added. The root helper, main controller, models, calibration files and servo parameters are not changed. The baseline is the code currently deployed on the device (matching e6f0e44 after line-ending normalization); before deploying, verify the old file hashes and running state, save a backup, and restore the files if installation fails.

## Verification

Tests first reproduce hold and capture being rejected in a redo session, then verify that settled capture is allowed, that movement/source change/invalid sessions are rejected, that torque off is enforced before verification, that concurrent operations are mutually exclusive, and that the frontend keeps the capture result after torque off. After the related existing tests and browser tests pass, do an independent review. On the real robot, only deploy and check the loaded state; do not click standing-pose enable or start calibration.
# 11-04 addendum: in-place mounting orientation capture at motion mode HOME

The user pointed out that the previous version only handled sampling after entering commissioning, and the "重新标定方向" (Recalibrate orientation) entry at motion mode HOME still required torque off. This change completes the real entry: stay in motion mode and at HOME, no restart, no automatic torque off, and only read the current body-frame gravity to capture still and lean-forward. The model must be off, HOME joint error no more than 5°, and the IMU and state stream must be fresh; capture is rejected while rising, while the policy has taken over, and when data is frozen.

Keep the original coarse calibration solver's body frame and the old mounting orientation saved by the main program. The candidate result is stored in the web backend and is not cleared by torque off. When the user finally clicks verify, torque must already have been turned off manually; only then does the backend call the existing helper with backup to enter commissioning, keep this candidate and check the source, board, old mounting orientation and process connection generation, and then verify, save and restore runtime mode following the original verify-imu and finish flow. The root helper's torque-off gate is not relaxed, and no action is sent from the capture entry.
