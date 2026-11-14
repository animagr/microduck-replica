# Beak 34 / Yaw 32 Diagram Fix and Group 14 QR Code

**English** · [简体中文](软件修订-20261031-r1.md)

The software version is **2026.10.3101**: the 01st revision on October 31, 2026. It keeps the three-part numeric format supported by the original updater, so devices that already have 2026.10.31 installed can discover the new version. It is a software package, not a new system image; the original 31 package is kept for rollback.

[Software package and checksum attachments](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.3101)

## Devices that already have the update entry point from the 27 release

1. Follow the page's preparation checks to stop the policy, voice, music and action / servo / calibration sessions.
2. Open **设置 → 软件更新 → 检查更新** (Settings → Software update → Check for updates) and install **2026.10.3101**.
3. Wait for the web console to reconnect, check the version, then refresh the servo page: clicking the beak servo should select **34 "嘴巴"** (34 "Beak") on the right; the yaw servo corresponds to **32 "头部偏航"** (32 "Head yaw").

If there is no network connection, download the complete `2026.10.3101.software-update.tar` and upload it on the software update page; do not unpack it first. File size 9,287,680 bytes, SHA256:

```text
0502c452e7062aa29286f6a82c046ed4ceaaf8beecaa6d98958341a80c95ea77
```

## What was fixed

The original 3D code assigned IDs by the distance from each servo housing center to the joint axis origin, so the beak and yaw servos were swapped. Now the model binds these two explicitly, and clicking, highlighting and the ID leader lines all use the same mapping. The actual joint IDs, directions, motion commands and servo data were not swapped.

The model manifest now revalidates the HTTP cache before choosing the corresponding IndexedDB record, so the old mapping cached for a day is not kept after the update. The large meshes are still cached and do not have to be downloaded every time.

The bundled robotd / padd are identical to the 31 release. Components already verified as complete by the page do not need to be reinstalled; devices that have not completed it still follow the original procedure: hold the robot steady, release torque and explicitly confirm the bundled update. Do not judge that the bundled drivers are complete just from the main program version `.47` or from seeing a new button.

Compatible old cards / development cards that have no software update entry point, or that still run from `/home/radxa/studio-dev`, require the maintainer to check the layout over SSH, make a backup and do a one-time first bootstrap. The bootstrap attachment cannot be uploaded through the web console; users on the 27 release who already have the entry point should not repeat this step.

## Group QR code

The README has been updated with the original image of **鸭子复刻群14** (Duck replica group 14) provided by the user, marked **valid until November 7, 2026**. The QR code file was copied byte for byte, without redrawing or compression; see the [original image](../assets/wechat-group-14.png). It belongs to the repo material and is not put into the device runtime package.

## Verification scope

23 real CAD / Three and cache regression tests and 32 related Python regression tests passed; a real browser verified the 32 / 34 rows, highlighting and label mapping after mouse clicks. The original 27 ARM updater, in an isolated directory, ran install, rollback, bad signature / hash rejection, health failure and interruption recovery checks from both the original 27 and the 31 software packages. Service operations used recorded fixtures, which is not the same as a physical deployment.

Source frozen at `3952471a8394c8b720817d2160ffd95ce5a54456`; later documentation updates do not change the programs in the package. The release public key is the same as for the 27 release. The package contains no private songs, recordings, camera images or keys; network, model, calibration, action and personal music data are stored outside the program version directory.

For the exact binaries and the inherited 31-release bundled verification scope, see the release attachment `runtime-provenance.json`. In this round no software was installed on a physical duck, and no image was reflashed.
