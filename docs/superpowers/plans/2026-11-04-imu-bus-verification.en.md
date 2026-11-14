# ID200 mounting-orientation verification implementation plan

**English** · [简体中文](2026-11-04-imu-bus-verification.md)

> **For agentic workers:** Execute item by item following executing-plans; native and Studio are implemented independently against the frozen contract; do an independent review when done.

**Goal:** ID200 saves a verified orientation only after a real upright/lean-forward verification passes, and the web console exposes the attitude correction.

**Architecture:** Native reuses PendingVerify without changing the runtime-mode data path; Studio uses an explicit capability contract and the returned attitude proof to decide whether a write is allowed and whether it succeeded.

**Tech Stack:** Rust1.99, Python unittest, Preact, real Edge tests, ARM64 cross-build.

- [x] Save the native targeted baseline: `cargo +1.99.0 test -p robotd feetech_commissioning -- --test-threads=1`; the 21 failures in the existing full baseline are compared by name and are not part of this round's fixes.
- [x] Add failing tests first: ID200 with no reading/wrong attitude is rejected, and confirm it is not written to disk directly; a correct upright pose enters waiting and only a successful lean-forward writes; wrong direction/timeout/cancel do not write; repeated sequence numbers do not accumulate.
- [x] Feed raw bus readings into the existing verification state machine, add API43 and capability fields, and update the mechanism docs.
- [x] In Studio, first add regressions for rejecting writes with the old main program and for rejecting missing/wrong proof, plus real-browser assertions for the coarse calibration correction.
- [x] Implement the capability requirement, response proof check and correction hint, keeping HOME capture and the post-torque-off candidate.
- [x] Run the relevant tests and review alignment differences; build ARM64 and check the source/hashes.
- [x] Prepare the exact backup/install/rollback, confirm installation happens after torque off, restart only the necessary services, and verify that parameters, calibration and the model keep their original bytes.
- [ ] Deliver a single upright/lean-forward verification procedure to the user and record the actual results; keep software tests and the real motion acceptance check separate.


Execution record (2026-11-04):

- Native commit `7036345`: 18 baseline items passed; after the change 23 items passed, including a negative-w full-quaternion PTY bus regression, wrong-direction rejection, sequence-number deduplication, and timeout and invalid-quaternion rejection.
- Studio commit `dff4bd9`: 153 related items passed (including real Edge); 4 proof/contract tests in the independent review passed.
- ARM64 build completed, SHA256 `eea47ce2ce02f0ca39f7be61c392a18342bb9e5b63a490417447f804f065188a`.
- The issues raised by the independent review (timeout, default attitude without a quaternion, install interlock, and web stop-timeout recovery) have all been fixed.
- Read-only check on real hardware: the main program was stopped and the Studio servo-tuning session held the UART. The first installation exited before any service change/file replacement; waiting for the user to turn torque off.
- The installer added a confirmation from the current operator that torque is off, and a read-only confirmation of exclusive torque after the web page is closed; 3 protocol-level items passed, confirming that only sync reads of register 40/1 are sent and no motion/torque write commands.
- The matching install package, exact backup and failure rollback are prepared; not yet installed, and no real orientation verification or walking motion has been triggered.


Installation and readback completed (2026-11-04):

- After the user confirmed torque was off, the real robot was handed back from the servo-tuning session to the main program. The install wrapper first confirmed the model was off and all 15 servos had torque off, then stopped services, installed, and restored the original running services.
- On the board, systemctl displayed Conditions as [unprintable]; the actual install interlock was instead verified by reading the D-Bus a(sbbsi) structure, and the real return value was added to the regressions. 10 items related to the install protocol/state gates passed.
- The real robot runs `fullq4-bus-verify.1`; an independent readback confirmed the orientation-verification contract, IMU ready, fresh feedback from all 15 servos, model off, and torque-off confirmed.
- The main program, Studio, padd and voice service are running again; the hash of the imu.js actually served by the web console matches the build artifact, and all temporary install interlocks were removed.
- The original model, 0.5/0.7 filter parameters, configuration and current servo/IMU calibration were all preserved. Backup path: `/var/lib/microduck-imu-q4-bench-20261104/bus-verification-before-20261104-154530`.
- The fixed mounting-orientation preset is left for later at the user's request; real upright/lean-forward verification and walking improvements still await on-site testing, and no motion was triggered this time.
