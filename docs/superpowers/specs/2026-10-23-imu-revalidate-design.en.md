# Repeatable IMU initial-orientation calibration

**English** · [简体中文](2026-10-23-imu-revalidate-design.md)

What the user re-authorized is "the initial orientation can be redone after it is saved, and the mounting quaternion can also be re-verified". The previously canceled capture-algorithm rework stays canceled: do not change the coarse calibration's still 3 seconds / lean forward 3 seconds / straighten up then verify-imu, and do not change the orientation capture algorithm of the standing-pose fine calibration. Only do a local implementation and simulated verification; do not connect to the board, and do not build or flash a new image.

## Confirmed problems and design choices

`CoarseCard` is hidden outright when mount.verified is not false; the backend coarse/verify only accepts commissioning. So users who already have a wrong configuration or changed the mounting cannot return to the initial coarse calibration through the web console. Merely showing the button still cannot complete the recovery. Writing the orientation directly in motion would bypass the original runtime verification; a full calib-commit would reset the joint zero positions. The approach adopted is a controlled temporary return to commissioning, keeping the original verify-imu flow.

## User flow

1. The IMU page always shows the "初始方向标定（可重新做）" (Initial orientation calibration (can be redone)) entry. When already confirmed, it does not start automatically; it is entered only after clicking "重新标定方向" (Recalibrate orientation) and explicitly confirming.
2. In motion mode, the user must first turn torque off, with a fresh readback confirming torque OFF, policy off, and no stand-up or temporary gain recovery in progress; keep holding it with both hands. The recalibrate button explains that the main program will restart, but the joint calibration and a backup of the original IMU orientation are kept.
3. Use the controlled helper to switch back to commissioning; with an existing factory commissioning, open the original coarse calibration directly without adding an override file.
4. Capture still and capture an actual lean forward exactly as before, compute the orientation, straighten up and click main-program verification, then lean forward as prompted. On verification failure, capture can be redone; the old IMU orientation is not changed before saving.
5. A recalibration session that started in motion restores the original motion mode, keeping torque off, after verification succeeds and the readback is consistent. A flow that was originally in factory commissioning does not switch modes on its own. After a successful coarse calibration, the entry can still be entered again.
6. The session survives web page refreshes, Studio restarts and board power loss; the UI shows "重标定未结束" (Recalibration not finished), and the user can continue verifying or explicitly cancel and restore the pre-entry backup.

## Implementation boundaries

- Add a fixed helper verb `imu-recalibrate` that only accepts enter/status/finish/cancel, with strictly validated parameters and no arbitrary paths, commands or service names. It shares a lock with bus-take / calib-commit and prevents those write operations from interfering with an ongoing recalibration session; torque off is not blocked by the lock.
- enter uses a fresh double-snapshot gate and saves the main program's current effective ExecStart, the main/saved calibration, control service state and source information. Only a direct robotd command is allowed; it generates a uniquely owned persistent commissioning drop-in, and first persists a manifest with a version and session ID. After restart it must read commissioning and torque off. It must not modify or delete the factory drop-in or anyone else's configuration.
- The original runtime verify writes motion_enabled as false and saves the main/saved files. finish must restore only the pre-entry motion_enabled and keep the newly verified current IMU orientation; compared item by item with the pre-entry state, apart from that source's mounting and motion_enabled, no joint zero position / direction / limit, other IMU or setting may change. Reuse atomic writes, file checks, full runtime readback and rollback. Before deleting the override file, check its content/ownership/original ExecStart; if the original state is unclear, refuse.
- A failed enter restores the pre-entry state; a failed finish restores the safe commissioning state of the recalibration and keeps a retryable session; cancel explicitly restores the pre-entry calibration and mode. The old orientation after a cancel is not called this session's new verification.
- The backend coarse calibration / verification keeps the original computation and firmware commands. Only when the backend confirms this verify succeeded and the readback of source, verified, quat is consistent does it request finish. Success must not be shown based only on helper or RPC accepted.
- The frontend does not hand-edit the quaternion, flip model signs, or change the recognition algorithm of the standing-pose fine calibration. It only adds the redo entry, progress, cancel and recovery hints.

## Verification and delivery

Add failing tests first, then implement. Cover the verified=true entry, two-step confirmation, redoing directly when already in commissioning, rejection in motion without torque off, original-flow success / failure / retry, reopening a persistent session, quaternion readback mismatch, finish restoring after runtime turns motion_enabled off, preservation of non-2048 zero positions and other parameters, rejection when the override file has been modified, rollback on restart failure, and rejection of conflicting operations. Run the original IMU computation / wizard, helper / HTTP and browser regressions. Deliver the local code and state that tomorrow it will first be deployed and verified on a test card, then packaged into an image; do not call a source update a finished image.
