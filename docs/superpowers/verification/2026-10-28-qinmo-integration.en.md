# Qinmo IMU local integration verification

**English** · [简体中文](2026-10-28-qinmo-integration.md)

Report date: 2026-10-28, Asia/Tokyo. The user's final confirmation: by default the existing board is auto-detected; the IMU page offers an optional Qinmo configuration, which is kept across boots once saved; when the type is changed, the mounting orientation must be verified again.

## Frozen sources and delivery scope

- Studio/helper implementation: `058963af5a11b2ebfe6d84b4106d1435a22bbbc7`, passed independent spec and quality reviews; the local `studio-dev` was fast-forwarded from `9ff314c` to this implementation.
- Runtime: `bdf494ab3fd74898b5159419fbffe87113b4097c`, based on `0791fcd44f71c705dc8bb0fbcde405593b52d19b`; independent spec and quality reviews both passed. The local development ref `hd1910-v167-imu-dxl2` has been fast-forwarded to this commit; the original main worktree and untracked logs were not changed.
- Vendor protocol 1.2: QinmoTech/IMU-DXL commit `4644a9d19e07ac47f2c145c5e064c96683a5450b`. The vendor has not published the MCU firmware; the simulated peers are all spec models.
- helper is `0.7.2`. The official robotd version still shows `0.15.1`; the actual adaptation identity is `0791fcd-feetech-qinmo-control.45` from `deployment-info`, IPC API 40, model API 2. You cannot tell from `--version` alone that this adaptation is installed.

So far only the local code, the ARM64 main program and the deployment inputs are done; the device was not updated over SSH, no card was flashed, the duck was not moved, and the public release assets were not changed.

## Implemented behavior

The default `imu_profile=legacy` corresponds to "自动识别（现有板卡）" (auto-detect (existing board)) on the web page. Manually selecting Qinmo goes through the original IMU page with a controlled reconnect into calibration mode; the main/saved configs keep their other fields, and the original parameters and calibration are backed up byte for byte. A normal cancel restores the original state; cancelling a startup recovery stays in the factory calibration mode, where a selection can be made again. The gamepad and R3 voice (if enabled) are excluded during the transaction and restored to their original state afterwards; torque release and the actual global Space-key path remain available.

The first Qinmo version supports only the Feetech bus: PING/56/15, raw gyro value ÷16.4, explicitly ready unit quaternions, counter freshness, and a shared 20 ms time limit with the 15 servos. The original/I²C conversions are kept. Calibration is bound to the protocol and data type; unknown, contradictory or malformed metadata cannot be treated as old-board defaults. If a state change is observed during capture, computation or verification, the old asynchronous result is discarded even if the state later returns to the same value.

Identity descriptions and physical units are shown separately: FT6/homemade boards use their known identity, generic DXL2 only confirms a compatible layout, and Qinmo shows the configured type. None of this is used to claim automatic vendor authentication or automatic detection of arbitrary ranges.

## Actual verification and limitations

| Check | Actual result and source |
| --- | --- |
| Rust core/parameters | 261/111 passed; 10 Qinmo checks passed; 8 existing loop-model integration checks are still ignored |
| Focused runtime chain | Original/DXL2/Qinmo commissioning PTY, I²C, read-only, startup diagnostics, single instance and updater interface checks passed; see the runtime delivery record for details |
| Full isolated daemon comparison | On `1fb76af`, equivalent in production logic: 299 passed, 2 ignored, 17 failed; the failing test names are identical to the fixed old baseline. Later Rust changes only added tests and changed one diagnostic message. We do not claim the whole Rust workspace is green |
| Broad Windows regression | 1229 tests on `f071ed1`, 76 skipped, 244.110 s, OK. This run predates the later metadata/async-context fixes and cannot count as a complete broad regression of the final commit |
| Final focused Linux regression | 183 passed on `058963a`: 45 Qinmo, 37 backend, 46 commit, 23 old redo, 32 helper calibration; Python 3.12/POSIX checks file-permission logic and the like, the device target is still Python 3.13 |
| Final real browser | 1 Edge test passed on `058963a`, covering default/manual selection, units, error states, cancel/restore, Space-key torque release, and clearing capture results when the error message changes |
| Independent metadata matrix | 48/48 passed: native/top-level explicitly unknown or malformed protocol, type or configuration type rejects old calibration and old pending; genuinely missing old fields remain compatible |
| Real release config format | 4 tests passed on the actual 20261027 main/saved files × two types; other parsed values and nested model arrays stay the same, and repeated selections are byte-idempotent |
| Post-merge check | 45 Qinmo checks passed on the canonical `studio-dev`, with 1 POSIX skip on Windows; the training tree hash and the SHAs of 3 private untracked documents are unchanged |

The broad-regression log retains a Windows AF_UNIX audio thread exception and resource warnings; the test process finally exited with 0, and the log is not described as warning-free.

## ARM64 build

Built from a frozen Git archive, Rust 1.99, locked dependencies, target `aarch64-unknown-linux-gnu.2.31`. ELF check: AArch64, highest GLIBC reference 2.30. The actual ARM64 binary was run independently under QEMU and verified over PTY/IPC in five cases: normal, frozen, not ready, bad quaternion and bad checksum; all checks blocked motor writes.

`robotd-qinmo-arm64`: 5564672 bytes, SHA256:

```text
febf44e2e5d4e573f4513f25a1ae6480b976c3988dd3d5e7cdfcf84d2a2d5063
```

Frozen runtime source archive SHA256: `1ab2540c55fb0e22e688e52f15e55c4b7a7ee70f0d078275b6bc833faa32a0e6`.

## Local delivery and physical acceptance check

The local workspace `artifacts/qinmo-imu-20261027/` stores the build script, raw logs, spec sources, independent results and a list of protected files. After the source was frozen, `package-local-adaptation.py` generated versioned maintenance inputs; the actual file names, source commits and SHAs are recorded in `local-delivery.json`, and `files.json` inside the package verifies each file. The package contains the main program and the corresponding source, for controlled maintenance or for building the next image.

The current signed web updater covers Studio/helper/duck-echo and has not been extended to robotd. Maintainers need to install the matching main program and web/helper; reflashing the card is not required. After installation, select the type and calibrate following the [web guide](../../Qinmo-IMU-web-usage.en.md).

A real Qinmo board, long-term stability on the shared bus, the actual mounting orientation, standing and walking have not yet passed an acceptance check. The existing public 20261027 image and update package stay at their original version; the next release should create a new version and be re-verified.
