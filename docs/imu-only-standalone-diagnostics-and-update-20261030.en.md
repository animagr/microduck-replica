# View diagnostics in the web console even with only the IMU connected

**English** · [简体中文](仅接IMU的独立诊断与软件更新-20261030.md)

Software 2026.10.30 adds a standalone read-only diagnostic for the bus IMU. When only the IMU with ID 200 is connected and no servos, or only some of the servos are connected, the main program still tries to read the IMU while it waits for the complete set of devices. The web console's overview and IMU pages show the IMU and servo status separately.

This is diagnostic information: detecting the board, reading one sample, confirming the mounting orientation and the whole robot being allowed to move are different conditions. A detection result does not allow standing, walking, servo enabling or calibration writes, and is not used as the calibrated whole-robot attitude. When devices are missing, the main program keeps waiting and shows the original startup reason.

## How to update an existing device

Release page: [Software 2026.10.30](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.30).

1. In the existing web console → **设置 → 软件更新** (Settings → Software Update), check, download and install `2026.10.30` following the readiness checks.
   If there is no network, download the complete `2026.10.30.software-update.tar` from the release page and upload the offline package.
2. After the web console reconnects and you have confirmed the version, in **主程序更新** (Main program update) on the same page, support the robot and release torque as prompted, then
   explicitly confirm to install the main program **`.47` / API 42**. Updating only the web console does not yet give you the new device observation data.
3. Disconnect hardware power before changing the wiring. Connect the IMU following the instructions for your chosen board and interface, confirm the power supply, then power on.
4. Open the **总览** (Overview) or **IMU** page and look at "总线 IMU 只读诊断" (Bus IMU read-only diagnostics). You do not need to start a policy for this.

The update keeps your existing network, pairing, models, actions, API Key and personal calibration; no need to reflash the card.
The main program update supports the `.44`, `.45` and `.46` builds already verified by this project; unknown binaries and unfinished
old update transactions are still rejected with the specific reason, and you must not delete the protection records yourself.

The readiness checks of the original version still apply. If only the IMU is currently connected and the old version cannot enter the update
readiness state because devices are missing, first complete the update on a full set of devices following the procedure, or have a maintainer handle it through the controlled procedure; do not
force the robot to stand, fake the state or bypass the protections just to pass the check. For compatible old cards without an update entry point, use
`microduck-bootstrap-20261030.tar.gz` from the release page, and have a maintainer install the entry point following the attachment's instructions.

## How to read the results

| Web diagnostic | Meaning |
| --- | --- |
| 已识别／读到诊断样本 (Detected / diagnostic sample read) | A response from the current board and the corresponding information were obtained; this still does not mean the whole robot is ready |
| 有应答、类型或数据待确认 (Responding; type or data to be confirmed) | The board responded, but its identity, samples, status or continuity have not been fully confirmed |
| 无应答 (No response) | This diagnostic received no valid response; check power, wiring, baud rate and the selected configuration |
| 数据过期／未知 (Data stale / unknown) | The evidence has expired, the connection was interrupted, or the main program did not provide the standalone diagnostic fields |

The main program's capture time and the web service's receive time together determine whether the evidence is valid. After capture stops, reading the cache
repeatedly will not make old data "just read" again. An unrecognized identity will not pass itself off as this project's IMU.

The diagnostics follow the current actual configuration. When using a bus board, select the bus source; if the I²C module is still selected,
the system will not silently switch the source just because ID 200 is connected on the bus. The default legacy protocol supports the known Feetech
boards and compatible DXL2 layouts; Qinmo uses its own separate configuration and is not automatically interpreted with a different gyro range.
After changing the source, protocol, board or mounting, recheck the orientation and calibration against the actual hardware.

## Verification record

For the scope of native, web, signed update and real hardware verification, see the [release verification record](superpowers/verification/2026-10-30-independent-imu-software.md).
Automated serial port simulation and software tests cannot replace physical acceptance checks with different boards.
