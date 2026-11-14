# Independent verification of the ID200 mounting orientation

**English** · [简体中文](2026-11-04-imu-bus-verification-design.md)

The user asked to move the fix forward based on the comparison results with KISSQY. This round only handles the confirmed issue "ID200 is marked verified without an independent upright/lean-forward verification" and the explanation of the calibration correction; it does not tune the model, zero positions, range, ODR, filtering or MCU.

The native source is `0d0e3e0dc833a59549e936b07b6b654bbcace60a`, keeping the currently paired full-quaternion capture. The Studio source is `835551a`. Both are modified in separate worktrees.

## Native contract

- API43; after installation, a version difference with existing clients is only logged, and service is not refused because of the version number.
- `calibration-status` adds `imu_verification_contract: "upright_nose_down_v1"`.
- Both bus and I²C use the latest accepted `SensorReading` in the sensor's raw coordinate frame. For the candidate mount, check that the upright residual is ≤5°, then within 20 seconds obtain 5 valid readings of at least 12° lean forward with a forward-direction error ≤20°; a wrong direction or timeout is not saved, and torque off / call cancellation abort according to the existing logic.
- Directly calling save_verified after ID200 confirmation is forbidden. The bus protocol binding is written only after verification succeeds, and a failure must not change any calibration field. A successful response keeps `imu_check`, containing upright/nose_down/residual_tilt_deg; `upright.imu_source` must be the actual source.
- Each complete capture cycle updates the latest raw reading passed to verification; any capture failure does not pass an old reading to verification. When the bus provides a sequence number, the same sequence number cannot be counted repeatedly in the lean-forward verification; generic protocols without sequence numbers still count actual transactions that passed the freshness gate.
- IMU data processing and model input in runtime mode stay unchanged. Firmware, configuration, the saved mount and servo calibration stay as they are until the user's later verification.

## Studio contract

- Keep in-place still/lean-forward capture at HOME. The coarse calibration result shows pitch, roll and the total change relative to the old orientation, and explains that the reference posture deviation is also folded into the mounting orientation; the solver math is not modified.
- Before saving, require the latest calibration-status to explicitly support the above contract; with the old main program, prompt that the matching API43 main program needs to be installed, and do not use the old confirm-only save path.
- A successful verify also requires checking `imu_check` in the response: consistent source, upright residual within the threshold, lean-forward angle reaching the threshold, direction error within the threshold; only then perform the existing readback/finish. Missing proof cannot be shown as independent verification passed.
- Do not automatically send stand, lean-forward, walk or similar actions. Before installation, prepare a backup and rollback; the model must be off and torque off confirmed, and all user calibration and parameters are kept.

## Boundaries

Orientation verification cannot prove that the gait or getting up after a fall is fixed, nor can it independently identify mechanical reference posture errors. After software verification is complete, the user alone performs one posture verification following the page prompts, and the motion performance is compared separately afterwards. The SFLP initialization and chip-epoch protocol are not changed for now.
