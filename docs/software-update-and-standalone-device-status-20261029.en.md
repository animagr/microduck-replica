# 2026.10.29 Software Update: Separate Status for IMU and Servos

**English** · [简体中文](软件更新与独立设备状态说明-20261029.md)

This release updates existing cards via a software package; no need to reflash the image. Release page:
[2026.10.29 software update](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.29).

## What was fixed

While the main program waits for the IMU, it now keeps reporting the servo responses it has already received. The web console can show both
“舵机 15/15 在线” (Servos 15/15 online) and “等待 IMU 数据” (Waiting for IMU data) at the same time, and can distinguish per ID between “有应答、未应答、未知” (responding, not responding, unknown).
Raw position, voltage and temperature come from actual responses; once old data expires, the state reverts to unknown.

Startup checks in both motion mode and factory calibration mode support standalone device diagnostics.
IMU, calibration, torque-release confirmation and motion admission conditions remain in effect; the diagnostic readings are used to display device status.
When the IMU is missing, it no longer blanket-guesses “舵机没上电” (servos not powered).

## Cards that already have the web console "软件更新" (Software update) entry point

1. Open the duck's usual control URL, log in, and go to **设置 → 软件更新** (Settings → Software update).
2. Click **检查更新 → 下载更新** (Check for updates → Download update); if there is no network connection, download
   `2026.10.29.software-update.tar` from the release page on a computer and upload the complete offline package on the same page.
3. Complete the preparation checks as the page instructs: stop the policy, turn off voice and music, end recording, replay, servo and
   calibration sessions, and keep the power on. The first stage of the old updater still uses the original preparation conditions.
4. Click **立即更新** (Update now), wait for the web console to reconnect, and check that the web console version is `2026.10.29`.
5. To enable the full standalone diagnostics, find **主程序更新** (Main program update) on the same page. Support the duck and confirm torque is released,
   confirm explicitly as the page instructs to install the main program, and wait for verification of the actual running identity.
6. Refresh the overview and servo pages. The new main program identifier ends in **`.46`**, and the interface API is **41**.

The web console layer and the main program are updated in two separate steps. The web console showing the new version number only means the web console layer has been updated; only after the main program
update also completes will the new standalone device responses be available. Devices that already have `.46` installed do not need to reinstall the main program.

Native main programs that can be upgraded automatically include the `.44` and `.45` builds verified by this project. Unknown custom
binaries and startup methods still require the maintainer to check, and the page keeps the specific refusal reason. If an old version cannot complete the preparation check with the IMU
missing or in the first-calibration state, keep the on-site logs and let the maintainer handle it;
do not force the robot to stand just to pass the upgrade check.

Existing Wi-Fi, pairing, actions, models, API keys, parameters and calibration are kept.
IMU source and mounting orientation still follow the actual hardware configuration; after replacing the board, the IMU or the mounting method, recheck
this robot's calibration, and in particular do not use the original duck's orientation and zero positions directly as another duck's calibration result.

## Old cards without the update entry point

Use `microduck-bootstrap-20261029.tar.gz` and its checksum file from the same release page, follow
`bootstrap-README.txt` to install a compatible upgrade entry point once, and then use the web console flow above.
The bootstrap package keeps the original release public key; resource, signature and compatibility checks run as usual.

## Actual verification scope

This time, on a Radxa ZERO 3 with the selected I²C IMU kept in a no-data state, we confirmed that the web console still showed
fifteen servos online and obtained each servo's raw position, voltage and temperature; the main program kept waiting with the servos' torque released.
Standing, walking and the motion effect with different physical IMUs are outside the acceptance scope of this display fix.

For software checks and real-hardware records, see [fix verification](superpowers/verification/2026-10-29-startup-device-status.md).
