# Bus IMU auto-detection · 20261023c

**English** · [简体中文](HD1910-20261023-总线IMU自动识别.md)

This release wires DXL 2.0 IMU compatibility into the actual robotd runtime, the calibration flow and Studio, and the image auto-detects it by default.
The fact that the original servo web debugging tool supported DXL2 did not mean the motion runtime supported it; this release updates the handoff information for both layers.

## Supported configurations

| Connection | What is supported | How it is selected |
|---|---|---|
| Feetech servo bus, ID 200 | FT6 and Feetech firmware compatible with IMU-to-DXL, 56/15 data block | Identity and reply order auto-detected |
| Same Feetech servo bus, ID 200 | DXL 2.0 protocol, 124/12 SFLP data layout | Identity detected read-only and data layout checked, then polled separately from the Feetech servos |
| Board I²C | Existing BNO08x / LSM6DSV16X | Same first-boot detection and explicit configuration as before |

In `[bus]` you can set `imu_protocol = "auto"` (default), `"feetech"` or `"dxl2"`.
With a fixed protocol, failure is reported as an error directly; the runtime never silently switches protocols. Unsupported register formats, other IDs or baud rates need adaptation;
not everything is interchangeable just because it's all called an IMU. Probing does not modify the chip's firmware, ID, baud rate or EEPROM.

Studio shows the actual protocol and layout reported by the runtime. Changing protocol invalidates earlier capture/computation results;
a successfully verified mounting orientation is saved bound to its protocol. Bus calibrations from older versions with no recorded binding are treated as Feetech
and cannot directly authorize torque-on under DXL2; the page still lets you enter recalibration. Replacing the physical module or changing how it's mounted also requires recalibration.
Chip counters, status bits and chip-side data age that aren't present in DXL2 data are left at their defaults; the page does not make up these diagnostic values.

### Verified ScrapMeta bus firmware

The [imu_to_dxl firmware from ScrapMeta/microduck-diy](https://github.com/ScrapMeta/microduck-diy/tree/db04d323caa053ae0c96629268392cdbe7dc8b4f/imu_to_dxl/firmware)
was checked against the pinned commit `db04d323caa053ae0c96629268392cdbe7dc8b4f`. Its default contract is DXL 2.0,
ID 200, 1 Mbps, a 12-byte block at address 124; identity bytes `d8 27 01` (model 10200, firmware 1).
The gyro is little-endian i16 at 17.5 mdps/LSB; quaternion xyz is little-endian binary16, with w reconstructed by the board.
These formats are already supported in the **20261023c release image**; there is no need to replace robotd or rebuild an image with the same contents for this.

This time we compiled the upstream's unmodified `dxl_slave.c`, `dxl_crc.c`, `control_table.c` and `imu_pack.c` into a host-side
test peer, communicating over a pseudo-serial port with the actual Rust `Bus`, decoder and freshness checks used by the release robotd.
7 cross-implementation cases passed: auto-detection, fixed DXL2, data containing escape bytes, all-zero not ready, frozen, invalid quaternion
and bad CRC; normal reading includes 15 simulated Feetech servos on the same serial port. The 21 assertions in the upstream's existing host tests
also passed. We did not write a separate DXL2 responder simulator to stand in for the upstream's protocol implementation.

This release only reads the common 124/12 core block; the upstream's 8-byte custom diagnostics at `@136` are not wired in, and Feetech's
or other firmware's status bit definitions cannot be applied to them. Probing only confirms the protocol/data layout and does not constitute vendor or physical module authentication.
Once a matching module is connected, select the bus IMU in the web console, keep `imu_protocol = "auto"`, then complete servo and IMU calibration.
After replacing the module or changing how it's mounted, redo the mounting orientation confirmation.

The IMU daughterboard must be pre-flashed with firmware matching its hardware. The upstream code targets its v0.3 STM32G031F8P6 + LSM6DSV16X
reference board; the board image does not flash the daughterboard automatically, and this doesn't imply that other boards with the same chip share pinouts and buffers.
That subdirectory has its own [MIT license](https://github.com/ScrapMeta/microduck-diy/blob/db04d323caa053ae0c96629268392cdbe7dc8b4f/imu_to_dxl/LICENSE).
This time we only verified board-side compatibility; we did not build, distribute or flash the upstream's MCU firmware files. Sustained bus reading,
calibration, standing and motion with a real daughterboard still await acceptance checks on real hardware.

The runtime commit is `0791fcd44f71c705dc8bb0fbcde405593b52d19b`. For the corresponding build, test scope and image manifest, see the [20261023c release page](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261023c).

## Software verification

- Full test run of the final Studio feature commit `a5546a4161a9b70bd2b4aed57a9b3eef8bc112dd`: 1,037 tests, 4 skipped, the rest passed; of these, 151 protocol-related backend, helper and real-browser flow tests passed.
- Control core 251 tests and parameters 110 tests passed; including 19 tests for DXL2 encoding/decoding, mixed serial port, error replies, shared timeouts, freeze detection, calibration binding and diagnostic counters.
- robotd unit tests run individually: the new version has 296 passed, 2 skipped, 17 failed; the original commit under the same conditions has 295 passed, 2 skipped and the same 17 failed, so no new failures. The pre-existing failures involve model/control test expectations, startup report assertions and control loop timeouts, and were not worked around by changing production logic or weakening assertions.
- The new DXL2 calibration serial-port simulation flow passes, and the original Feetech flow passes; 18 single-instance and update health-gate integration tests pass.
- `cargo clippy` completes, with the pre-existing style/large-enum/test warnings still present; we do not claim the full Rust test suite has zero failures or zero warnings.
- The 117 image build script tests pass as Linux root; fixed an issue where the test tool didn't explicitly invoke sh under a umask, so 0644 scripts extracted from a Git archive couldn't run.

The runtime source commit is `0791fcd44f71c705dc8bb0fbcde405593b52d19b`, and the ARM64 binary's
SHA256 is `edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`.
Release file hashes and the frozen image source commit are on the release page and in the image manifest.

## Release image verification

The image was built from the frozen commit `dd7a753026c40b0bf385374a896e7253cff42720`; the release file
`microduck-replica-20261023c.img.xz` is 712,068,864 bytes with SHA256
`10009c0a4aa963900719649836f5544036ad52cc15e3a0228eef05f6b747dab5`.

After an independent re-extraction, the partition check and read-only ext4 check passed. 337 Studio files match the frozen source,
39 runtime/model file digests match, and all 9 model config references exist; helper 0.7.1, `imu_protocol = "auto"`,
15 uncalibrated factory zero positions and calibration mode were all checked. Machine identity, SSH host and developer keys, Wi-Fi configuration and private
recalibration state were not carried over. The actual ARM64 robotd completed `--version` and `--help` startup checks under QEMU;
this only verifies that the program loads and its command entry points work, not that real serial ports, sensors or motion have been verified.

The [20261023c official release page](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261023c)
is set as Latest, `draft=false`, `prerelease=false`. Server-side sizes and SHA256 of all six attachments match;
the public image download link returns HTTP 200, and the re-downloaded checksum file has identical contents. The old 20261023b / 20261021b release pages
have had links to the new version added, and the old image attachments are kept. After merging back into the local development branch, the 151 targeted regression tests passed again; unreleased training
changes and private notes stay local.

## Pending acceptance checks on real hardware

This time we used software serial-port simulation and offline image checks, without connecting a real duck. Real wiring of FT6, DXL2 and I²C modules,
first calibration on a new card, recalibration, standing and walking still need acceptance checks on real hardware. The camera still defaults to the test source, and automatically starting/stopping
camera / ToF services based on hardware was not implemented this time.
