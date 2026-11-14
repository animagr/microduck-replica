# How a system on the Oct 27 image gets the new features

**English** · [简体中文](功能软件升级-20261030.md)

This delivery is the **2026.10.31 software update**, which uses the update mechanism already present in the 20261027 image. Existing cards only need a software update; no reflashing is needed. The original 20261027 image and its download files stay unchanged.

[Software package, checksums and bootstrap attachments](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.31) · [Exact source and acceptance scope](https://github.com/fanhao375/microduck-replica/releases/download/microduck-software-v2026.10.31/runtime-provenance.json). The software package has been signed and has passed the acceptance check with the original Oct 27 updater; the new gamepad driver in this release still awaits an installation acceptance check on real hardware, so a finished source or release must not be taken to mean the device has been updated.

| Name | What it covers |
|---|---|
| 20261027 image | Installing the whole system on a new card for the first time |
| 2026.10.31 software package | Updates the web console, voice service and matching helper |
| Companion driver update | Installs the matching main program, gamepad program and service settings |

## Already using the Oct 27 image

1. Keep the board online. Stop the policy, voice listening, music, action recording/playback, servo and calibration sessions, and follow the page's readiness checks.
2. Open **设置 → 软件更新** (Settings → Software Update) in the existing web console, then check, download and install the new software package; if there is no network, upload the complete `2026.10.31.software-update.tar`.
3. Wait for the web console to reconnect automatically and check the software version. If the page says the companion driver has not been updated yet, follow the prompts in that area to steady the robot, release torque and explicitly confirm, completing the second stage.
4. Only use gamepad remapping after the actual driver check passes. A new button appearing in the web console does not mean the companion driver is installed; even devices whose main program is already `.47` may still need the gamepad program updated.

Oct 27 devices that already have the update entry point should not rerun the bootstrap, and should not upload the bootstrap archive through the web console.

## Older cards or hand-built development cards

If there is no software update entry point, or the services still run from `/home/radxa/studio-dev`, a maintainer needs to do a one-time compatibility check, backup and bootstrap over SSH. The bootstrap installs the update service, public key and voice resources; after that, the same web update flow is used.

If the readiness checks do not pass, keep the current state and the specific reason; do not fake the device count, stopped state or torque-release confirmation, and do not force the robot to stand up to solve an update problem. The bootstrap is not a step that every Oct 27 user should repeat.

## Where the new features are

### Gamepad button remapping/calibration

Go to **重新映射／校准** (Remap / Calibrate) in the gamepad area:

1. Connect the physical gamepad and put the duck in a stopped state that allows learning, as the page requires.
2. Start button learning. Click A on the web page, then press the button on the physical gamepad you want to use as A; do the same for the other buttons.
3. Following the prompts, move the sticks to both ends of their travel and back to center; you can set direction and dead zone, and calibrate analog or digital triggers.
4. Check the preview mapping, name and save it, release all buttons and let the sticks return to center before resuming control. Then verify the e-stop again.

While learning, gamepad motion and voice actions are not executed. After saving, the web display, actual control and the R3/Select voice buttons use the same mapping. It cannot be saved while required items are unset; you can cancel to keep the old configuration, or restore the device's default detection.

Configurations are saved per identifiable device. Some receivers present different connection modes as the same device, so there is no guarantee that each upstream USB/Bluetooth mode gets a separate identity. Real gamepads of different models still need to be checked one by one.

### In-place camera zoom

The camera card below the duck model shows the full picture in its actual aspect ratio. **放大** (Enlarge) enlarges the current card and **还原** (Restore) returns it to the original size; this does not jump to another page or re-establish the video connection.

This only changes the display size; it does not add camera detail or correct exposure. The current camera source setting is kept; a device originally configured with the test picture will not automatically switch to a real camera because of the software update. Hardware, wiring and actual image output need to be confirmed separately.

### SSH guide and music playback

The SSH guide in Settings explains the difference between the web password and the board's SSH password, and provides connection information you can hand to AI tools. The connection instructions do not contain the password in plain text.

The music player can add, play and delete your own music files, and action control is independent of playback. User music, actions, network, models, calibration and API Key are not replaced along with the program version tree; release packages do not contain the maintainer's personal audio or songs.

## Rollback and recovery

A failed software update and a failed companion driver update are two separate transactions, each showing its actual state. If a driver update is interrupted, first follow the recovery flow on the current page; do not delete the protection files and force a start.

Before going back to old software that does not support mapping, first use the new helper to fully restore the matching old gamepad program and service settings. You cannot roll back only the web console and keep letting the old voice service read the new gamepad mapping; the compatibility protection will reject that combination.

The web upload package `2026.10.31.software-update.tar` is 9,287,680 bytes, SHA256 `5f6a597abe27d9c4af8e137841c9dcab4b6c4b378f44c8f88f4c7b4f6ae09204`, and uses the Oct 27 release public key. The software source is frozen at `26150eb61407d3498dc2e2c5d1f9dc3ea130acde`; later documentation commits do not change the programs in the package.

165 Linux control and mapping tests, 13 voice mapping tests, 322 cross-language real socket state checks, and the install/rollback/fault-recovery checks with the original Oct 27 ARM updater have passed. There are also checks with real systemd of users, groups, persistent directories, network permissions and the old-voice rollback protection; in these, the service principal, native file recovery and hardware input use test fixtures, which is not the same as running the complete driver update transaction on real ARM hardware. For the full scope see the [Linux verification record](superpowers/verification/2026-10-31-controller-linux.md).

For a device that has not actually been installed and confirmed by read-back, you cannot infer from the software package version that it has the new features. Gamepads of different models, the e-stop on real servos, and the bootstrap of old development cards still each need an acceptance check on the device.
