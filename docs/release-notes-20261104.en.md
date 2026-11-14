# 20261104 test image and 2026.11.4 companion software

**English** · [简体中文](更新说明-20261104.md)

This release combines today's IMU calibration fix, the network setup hotspot recovery, and the software features added since the 20261027 image into one new image. Booting a newly flashed card with this image and its motion behavior still need an on-site acceptance check, so it is released as a test version.

## What was added and fixed today

| Item | Behavior in this release | Verification scope |
| --- | --- | --- |
| Re-capturing the IMU mounting orientation while standing | With the model off, standing steady at HOME and fresh feedback, it can stay standing while capturing the still and forward-lean poses; the candidate result is kept after torque release, then verified and saved as prompted | Web console, backend tests and read-back of the software install on the robot; the real orientation motion in this round still awaits an acceptance check |
| Real orientation verification for ID 200 | The main program checks the upright residual and the forward-lean direction, and saves only if they pass; wrong orientation, invalid posture, timeout and cancel do not save | Simulated bus, interface and fault regression; hardware test with a newly flashed image still awaits an acceptance check |
| Display of the calibration correction | The web console shows pitch, roll and the total change, and explains that the offset of the still reference posture is also folded into the mounting orientation | Browser and backend regression |
| IMU data checks | Checks for valid quaternions, data freshness, duplicate sequence numbers and counter continuity; provides raw data diagnostics | Protocol, simulated bus and regression tests |
| Hotspot recovery after changing Wi-Fi | Limits retries of the old network connection and explicitly loads the hotspot configuration used for recovery; independent of whether the servos and IMU are all present | Network setup automation; a real network change still awaits an acceptance check |

Capturing data while standing does not automatically start the motion model. Before saving the new orientation, still support the robot and release torque as the page prompts; this step keeps the candidate already captured.

## Existing features added compared with the full 20261027 image

- Gamepad button remapping, stick and trigger calibration, and saving the configuration.
- The camera card enlarges and restores in place, displayed in the actual picture's aspect ratio.
- SSH connection guide, explaining the difference between the web password and the board login password.
- Adding, selecting, deleting and independently playing music files; action control and music playback are managed separately.
- Local voice sit down and stand up, action recording and playback, and the existing voice configuration entry.
- Fixes to the illustrations, click selection and leader lines for mouth ID 34 and head yaw ID 32.
- Separate IMU and servo diagnostics, the manual Qinmo configuration adaptation, signed software updates and rollback.

These come from earlier software updates and are only now preinstalled together in the new full image; they were not all developed again today.

## Full quaternion and small-board firmware

The main program supports explicitly selecting the matching full quaternion path. The new image still uses the output format compatible with old small boards by default, does not flash the small board automatically, and does not assume that all boards have the same mounting orientation just because the address is ID 200.

The 1.1 experimental firmware and the PC-side flashing and board-test fixture tried today belong to a separate delivery chain. The fixture showing a matching flash read-back only means the Flash verification passed; it does not mean attitude, communication and motion have passed an acceptance check. The 1.2 compensation experiment is not the default firmware in this release.

Fixed mounting orientation presets, personal models and personal calibration are not put into the general-purpose image. Fixed presets are left for later, per this discussion; we also do not currently claim that the problems with walking forward/backward, rolling over or getting up after a fall are solved.

## How to use it

For a new card, download the [20261104 test image](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261104), check the SHA256 and flash it, then set up your own duck following the first boot, network setup, servo zero position and IMU orientation procedures.

Users who already have a working system card can download the complete `.software-update.tar` from the [2026.11.4 companion software release](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.11.4) and upload it under "设置 → 软件更新" (Settings → Software Update); the driver is handled separately as the page prompts, and models, calibration and personal data are kept. If you previously installed the version 31 companion driver, first go through the page's "恢复旧配套驱动" (Restore previous driver bundle) flow; see the [native component update notes](native-update-20261104.md) for details. Test versions may not appear in the default stable update list.

The companion software package updates the IMU, the main controller and the web console; this hotspot recovery patch comes with the new image, and uploading the software package must not be taken as having updated the system network setup components on an old card.

The factory image clears the maintainer's Wi-Fi, SSH identity, personal API Key, music, actions and calibration, and keeps each component's original license and model notes. Source code, build inputs, attachment hashes and test scope are provided with the release record; offline checks are not the same as an acceptance check of flashing the card and motion on real hardware.

For the completed build, automation and GitHub attachment read-back, see the [release acceptance record](发布验收-20261104.md).
