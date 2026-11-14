# 2026-11-09 integration and installation verification

**English** · [简体中文](VERIFICATION.md)

The prototype layout has been connected to the original Studio's Preact, HTTP/CSRF and single WebSocket, and frontend `20261109-console1` has been installed. The production page does not use the prototype's simulated success states.

## Verification scope

- Local real Studio backend with isolated simulated hardware: the browser verified explicit takeover, single-servo center preview/confirm, servo details and two-step hand-back; IMU static sampling, lean-forward guidance and resuming an interrupted capture; saving the machine profile.
- Dragging the dual joysticks in the browser left `vx=0.0375` in the simulated RPC, and `vx=0` after releasing; after verification, a simulated global torque-off was run.
- 10 HTTP/WS checks covering Origin, routing/visibility, motion leases and recording ownership, plus 8 PTT state machine checks, passed. The redacted results are in `artifacts/experience-verification.json`.
- 18 first-boot contract tests, 14 A7Z adaptation tests and the original Studio Node regression tests for models, settings, WiFi, Stepper and recording lifecycle passed. Syntax and required static imports of the 24 changed JS files passed.
- 43 installer tests using temporary files passed both locally and on the main controller's Python 3.13, covering atomic swap, failure recovery, rollback retry, link rejection and Linux FD metadata compatibility.
- All 32 changes in the on-robot manifest matched the original file SHAs; after installation the complete web manifest is correct, and the content and modification times of the 4 original model resources are preserved.
- The browser on the real robot verified the overview, the servo read-only entry, the model/settings categories and the not-ready state; checked at 1440px and 390px with screenshots saved, no horizontal page overflow on the phone, and no JS errors during the checks.

## Release evidence

- Device: `cubie-XXXX`, `BOARD_IP:8000`.
- Method: `--apply --static-startup`; phase `motion / waiting_for_bus`, with no claim that the hardware or torque-off has been confirmed.
- robotd PID `477` and Studio PID `444`, unchanged before and after the release; no services were restarted.
- Binary SHA256: `1e46542006209b10a1e1d4d07bceb66bd492e6057138b7a4491dce47d9f940dc`.
- Calibration SHA256: `6d5d0677676ff185193a2aabd48d7d56efc588650ba41e6a97de2c89634c0ba0`.
- The transaction journal is `installed`, and the guards before and after match; the three backend digests still match the README baseline.
- Backup: `/opt/microduck-studio/console-backups/20261109T024849766301Z-c5f27ff2b853/`.
- Frontend package SHA256: `60f1adfded3671169a21dc646053c34c8bf9a38a964a9ec3222e0d7dadd3c263`.
- Final installer SHA256: `dea2f36d7795593bf0c18d8776c145b599b3f3ccb1a4dacc8f9bbb0976c3d0c5`.

The first release attempt hit, in staging, Linux Python's lack of support for `follow_symlinks=False` with path chmod; the web page was not changed. This was fixed by opening with `O_NOFOLLOW` and then updating metadata through the FD; after running the 43 tests on the main controller, the retry succeeded. The failed transaction was kept and did not overwrite the successful backup.

## Pending acceptance or enablement

The user confirmed that no servos were connected; no standing, walking or calibration was performed on the real robot. Servo/IMU readback, zero position/standing pose calibration, model execution and the physical effect of recording playback still need on-site acceptance checks once the hardware is connected.

The main controller startup arguments are `--configd none`, `--tof none` and `--camera-socket none`. The gamepad/provisioning, ToF and camera need the corresponding board-side services enabled; the joint tracking backend is not installed. Voice still needs the corresponding service, configuration and microphone permission. The page keeps the real entry points along with the reasons they are unavailable.

To roll back, re-upload the installer of the same version, preview the backup above first, then run `--apply`. Use `--static-startup` only while the state is still `motion / waiting_for_bus`; once the hardware is connected and the state is `control`, roll back with the default strict gate. A production rollback has not yet been run on the real robot; transaction regression tests have been completed in a temporary directory on the main controller.
