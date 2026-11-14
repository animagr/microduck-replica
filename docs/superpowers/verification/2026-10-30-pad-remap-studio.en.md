# Gamepad remapping/calibration: Studio, voice and cross-language verification

**English** · [简体中文](2026-10-30-pad-remap-studio.md)

This record covers `feat/pad-remap-studio-20261030`, design baseline `6dc40ce`, with the matching native commit `b5b91c4`. Local implementation and isolated verification only; nothing was released, pushed, deployed to the board, or run on the physical duck.

## Implementation scope

- Studio's `PadMapping` calls the length- and time-limited socket only from a worker, and snapshots read only memory; an exclusive token is held per page connection, and the status/diagnostics bundle does not expose the token. When it starts waiting for the driver ACK it first closes the local action gate; if the ACK is lost it conservatively stays paused until a fresh status confirms. The five-second native lease takes effect independently.
- Buttons, four-direction hat axes, the four stick axes and analog/digital LT/RT are learned from a fresh raw cursor; supports travel at both ends, center, inversion, per-axis dead zone and conflict rejection. There are regression tests for holding a control before entering, input history loss, SYN_DROPPED and device replacement.
- When editing a saved configuration, the in-memory draft of any role may be cleared, so Select/Start or stick axes can be swapped; `skip` is still limited to optional roles, incomplete drafts still cannot be saved, and the original persisted configuration stays unchanged until a complete save.
- The page shows native `mapped`/`preview`, and saving is judged by the driver's persisted read-back; covers skip, clear, re-record, cancel-and-keep, restore defaults, disconnect/reconnect and multi-page ownership. Switching pages and going to the background cancel; in the background the lease is no longer renewed, and a refresh does not automatically resume the session.
- Web actions, pairing, recording/playback, servos, IMU/calibration, software updates and REST model writes/uploads are mutually exclusive with mapping. The model transaction lock and upload lock in turn block starting a mapping; begin/servo.open within the same WebSocket packet are mutually exclusive. Web torque release is kept.
- duck-echo listens on the native target node with the same raw R3/Select bindings and supports controllers without the default 318; when a custom configuration omits R3, it does not fall back to the default. Pausing cancels listening/recognition/pending actions/playback, and configuration or device changes re-read the baseline; `updates_allowed` and `motion_lease` check the pause again.
- A corrupted runtime state, a process exit, or the state file disappearing after the new-format state has already been read all conservatively block voice. A cross-UID `kill(pid,0)` returning EPERM means the process is alive and does not wrongly disable voice; ESRCH still blocks. The duck-echo service from both the standalone install and the bundle bootstrap is added to the `robot` supplementary group, and the install/software package manifests include the shared reader module.
- `mapping.device.unique` in the diagnostics bundle reuses the existing MAC redaction rule.

## Verification entry points and evidence

Local evidence directory: `F:/chengshenzhilu/Robot/Microduck/artifacts/pad-remap-20261030/`. These are local test artifacts; the whole directory, which contains browser profiles/temporary state, is not committed.

### Python and interface regression

The Studio working directory is `software/studio`:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','-q','tests.test_pad_mapping','tests.test_pad_mapping_integration','tests.test_pad','tests.test_http','tests.test_models_http'])"
```

Finally **all 300 tests passed** (147.878 s); output in `studio-edit-swap-final.log`. The list includes input history loss, ACK loss, two-way model HTTP mutual exclusion, and swapping required inputs while editing an existing configuration. The pre-existing Windows background audio-status warning about `AF_UNIX` not existing and the temporary socket/file ResourceWarnings are recorded separately from unittest assertion failures; real Unix sockets and the voice subprocess were verified separately on Linux.

Additionally, WSL Python 3.13 ran mapping/PadOps/models HTTP and two WebSocket/servo mutual-exclusion tests, **all 42 passed** (`studio-edit-swap-linux.log`). A predicate in the new HTTP test that briefly saw `None` while waiting for policies was fixed and re-verified on Linux.

Full duck-echo tests: Windows Python 3.13 **172 tests in total, 153 passed, 19 platform/hardware tests skipped, 0 failures**; WSL Ubuntu 22.04 Python 3.10 **all 172 passed** (`voice-final-windows.log`, `voice-final-linux.log`). Linux includes a real ALSA stand-in subprocess and a read test under a different UID; that test calls setuid/setgid 65534 only in the subprocess and reads a temporary file, without changing any account or real service.

Full software updater: **21 tests in total, 17 passed, 4 platform tests skipped, 0 failures**. The runtime manifest of `install.py` and the updater whitelist already cover `duck-echo/pad_mapping.py`. `install_speech.py` has no separate source copy manifest; it reuses the standalone install directory and `install.py`.

### Real browser

`tests.test_pad_mapping_e2e` starts an isolated fake robotd, the real Studio/authentication/WebSocket and headless Edge; only the native raw input boundary is simulated. In the final `edit-swap-final/browser.json`, all scenarios passed (19.48 s), with zero runtime exceptions:

- A/B swap, duplicate conflicts not overwriting, four-direction hat, analog LT and digital RT, axis swap, direction calibration and dead zone.
- Native preview, save read-back, saved configuration after refresh, no automatic resume, cancel-and-keep, disconnect/reconnect, restore defaults.
- When a saved required stick axis is cleared, the Save button is disabled; after completing the swap it saves again, and on re-entering, the native preview updates according to the swapped real axes.
- A second connection can read but cannot modify or obtain the token; switching pages cancels, the background receives the native cancel ACK, and the UI converges when visible again.
- `robot.jsonl` contains no `robot.init/enable/do/head/mouth/move` requests. The existing neutral cleanup `robot.pose {active:false}` when Studio connects is kept.
- No horizontal overflow at 1440/390/320 pixels; six screenshots of the main panel and footer were inspected visually. On desktop the panel avoids the sticky gauge strip; at 320 pixels the per-axis configuration wraps onto separate lines.

Set a new `PAD_MAPPING_E2E_DIR` when running; do not reuse old browser state. A real-protocol review before release found that the original test wrongly changed `robot.policies.enabled` to false; it is actually the model-loading switch in the configuration, not the running state. That change and the corresponding wrong gating were removed, and `policies.enabled=true` together with the top-level `busStatus.policy_enabled=false` from the original recording are kept as is. File replacement in the Windows fixture retries for at most 500 ms against brief NTFS sharing locks, while remaining an atomic replacement.

### Python × Rust production socket contract

`tests/pad_mapping_native_contract.py` starts native's test-only synthetic evdev fixture on Linux and uses Studio's `MappingClient`/`PadMapping` through the actual production `mapping.sock` handler. No input-injection switch was added to the production program. The final native binary comes from `b5b91c4`:

```text
python3 software/studio/tests/pad_mapping_native_contract.py \
  --fixture /root/target-v167-autodetect-dxl2-board/debug/deps/padd-1ee51bf31d9dcfb2 \
  --dir /tmp/<new isolated directory>
```

All ten categories in `cross-language-edit-swap.json` passed: ownership, duplicate conflicts, A/B / all hat directions / axis swap, inversion and dead zone / analog triggers with both release directions / preview and save, duck-echo reading the real runtime, disk re-read and disconnect/reconnect, cancel-and-keep, digital triggers, swapping the saved Select/Start and both axes, restore defaults, and the five-second lease. The corresponding fixture log is in WSL at `/tmp/pad-remap-cross-studio-edit-swap/native.log`.

Native's Rust unit tests, ARM64 build and QEMU version/help are recorded by the native branch; that branch reports a final 112 Rust tests passing. This Studio test directly runs its final production socket handler and does not treat two separate mocks as contract verification.

## Independent review and limitations

The issues found in the independent spec/quality reviews (fallback when the modern state file is lost, REST model entry mutual exclusion, lost begin ACK, and cross-UID EPERM) all had red tests added, were fixed and regression-tested. The final independent reviews gave: **spec compliance passed, quality/security passed; in the new code, Critical 0, Important 0, Minor 0**.

The first round of independent re-verification included 39 mapping/PadOps/model HTTP tests, two Linux Python 3.13 WebSocket/servo tests, 12 Linux voice mapping tests (including a real different UID), nine contract categories of Rust production socket × Python, and one complete real-browser test. The reproduction of the original model select bypass now returns 409 and the handler is not executed; in the lost begin-receipt reproduction, both the native and Studio gates stay blocked. The independent browser artifacts are in `C:/Users/12440/AppData/Local/Temp/pad-mapping-e2e-gw4miziq`, and the independent contract fixture is in WSL at `/tmp/pad-remap-independent-contract-1793364239399`.

The independent incremental review of the later small fix for `clear`/swap of required role drafts also passed, with Critical/Important/Minor all 0. 22 independent unit/PadOps tests, the ten-category real Rust socket contract and the complete browser test (19.244 s) all passed; it was also confirmed that non-owner clear, skipping a required item and incomplete saves are all rejected, native does not write the save, and output stays blocked. This increment is also included in the final full 300-test run and the 42-test Linux regression.

Independent incremental artifacts: WSL `/tmp/pad-remap-clear-review-1793365335413`; browser `C:/Users/12440/AppData/Local/Temp/pad-mapping-e2e-plcff9dj`.

### Pre-release real-wire fix

The previously passing learning/mapping tests did not prove the runtime semantics of `policies.enabled`, and the browser fixture's wrong rewrite had masked the problem that a real stopped state was still being rejected. After the fix, Studio's start gating reads fresh, flat bus runtime fields: `phase=control`, `policy_enabled=false`, `home_recovery=false`, `torque_off_pending=false`, and confirms evidence of HOME/torque for holding or of disablement for limp. The configuration `policies.enabled=true` no longer blocks learning; unknown, old nested shapes, stale and transitional states are still rejected, and native's independent proof of stopping is unchanged.

Besides the original real-hardware recording, the regression also uses the actual serialized output of the current robotd's Rust `Bus::report()`/`PoliciesResult`/`RobotState`, stored verbatim in `software/studio/tests/fixtures/robotd-stopped-wire.json`, SHA256 `aa9036954c808aa251fb3f560a302340538235abf52dc9faf66e93eb6b95e5b3`; see the note in the same directory for its source. For the current fix, 46 targeted Linux tests passed, and the complete browser test without tampering with the configuration switch passed in 19.926 s; evidence is in `artifacts/software-features-20261030/mapping-wire-browser`. The independent re-review checked the Rust production serialization and the export test source; 9 Linux integration/same-package HTTP tests and the complete browser test (18.926 s) passed, and the limited fix has Critical/Important/Minor all 0. This does not mean that the not-yet-implemented companion update bundle has passed an acceptance check.

Still awaiting physical acceptance checks: gamepads from different vendors, USB/Bluetooth modes, real evdev disconnects and SYN_DROPPED, gamepad firmware event combinations, neutral gating on the real robot, and the R3 microphone/audio. The browser background path was verified with the real page's visibilitychange event handler and native receipts, but does not pretend to reproduce the freeze/kill-page behavior of every mobile OS; the native five-second lease was verified separately by the real Rust contract test. The matching padd/Studio/duck-echo/systemd need to be updated together; this round does no deployment.
