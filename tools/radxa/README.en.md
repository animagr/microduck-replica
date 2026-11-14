# Radxa Zero 3W · Making an Armbian card that boots out of the box

**English** · [简体中文](README.md)

> **2026-10-21: the two September base images (20260920, 20260929) have been withdrawn from Releases**; they are too old. If you want a ready-made card, use the [replica image](https://github.com/fanhao375/microduck-replica/releases/latest): flash it and it works, with the main program, the walking model, and Studio included. The card-making scripts in this directory are kept and still work for making your own card; the places below that mention those two Releases are only a historical record.

Use together with [No-HAT build · Step 1](../../docs/不打HAT.md#第-1-步--主控点亮什么都别接).
Previously, our own V1.12 board (AIC8800 Wi-Fi) failed to boot with the stock Armbian image we tested; this was solved after comparing and replacing the bootloader. For different board batches, see the image guide. **The double blink is not an error code in itself**; on 2026-09-28 the official B1 also used the `heartbeat` double blink while networking and capturing normally.
Earlier debugging pointed to a compatibility issue between the mainline U-Boot / memory initialization firmware used by Armbian and our board; after switching to the Radxa bootloader it boots.
This directory bakes the bootloader swap, WiFi credentials, DHCP configuration, serial port enablement, and USB console enablement into the image, for networking on first boot.

On 2026-09-28 a bug was fixed where the card-making script omitted `wlan0` DHCP; the image and checksum in the Sep 20 Release are still the old files and do not include this fix. Users who have already flashed the old image can just add the configuration following the [networking steps](镜像使用说明.md#4-连-wifi); there is no need to reflash just for this. The old networking hints on the card are also superseded by that guide. Our own personal image with the fix has been tested to obtain a DHCP address and log in over SSH; this does not mean all boards and routers have been verified, see the [test log](联网与HAT调试记录-20260928.md).

**Don't want to make the card yourself?** Use the [replica image](https://github.com/fanhao375/microduck-replica/releases/latest) (flash it and it works, with the main program and Studio included). The section below is the historical description of the late-September base image (no WiFi; plug in USB and connect via serial),
and for first-time configuration and differences between board batches see the [image guide](镜像使用说明.md). Changing PCs does not affect the system; changing WiFi requires re-entering the connection details, with no need to reflash.

**First-login erratum (2026-09-29): `root / 1234`.** Only after completing the Armbian wizard is `duck / duck1234` created and the root password changed; the username and password in `card.conf` are wizard presets, not the first-login credentials. Change the default passwords right away. The new 20260929 candidate image presets DHCP, updates the on-card instructions, and removes the pre-generated SSH host keys; it has passed offline checks but has not yet been flashed and tested on hardware. Old cards do not need to be reflashed; just fix DHCP and regenerate the SSH host keys following the guide.

| File | What it does |
|---|---|
| `card.conf` | Change the WiFi name / password; after the first `root / 1234` login, the wizard creates `duck` / `duck1234` by default. An HTTP proxy can be set if you need to install the official software from within China. **Leaving the two WiFi lines empty = public image mode**: no WiFi credentials are written, DHCP is still preset |
| `镜像使用说明.md` | For the image in the release: flashing the card, USB serial login, connecting to WiFi, swapping the bootloader to rescue boards from other batches |
| [摄像头调试记录-20260928.md](摄像头调试记录-20260928.md) | Ribbon cable wiring reference diagram, official B1 comparison results, IMX219 detection and limited frame-capture commands; retest of correct wiring on stock Armbian still pending |
| [联网与HAT调试记录-20260928.md](联网与HAT调试记录-20260928.md) | Board login after the DHCP fix, HAT servo read-only communication results, and open items to investigate |
| `1-做卡.ps1` | On Windows, right-click → "Run with PowerShell", pick the downloaded `.img.xz`, and it outputs an `xxx-鸭子卡.img` (duck card image); flash that with Rufus |
| `build-armbian-card.sh` | The script that does the actual work; on Linux / WSL: `sudo bash build-armbian-card.sh xxx.img.xz card.conf` |
| `kissqy-r1-v112.sh` | On kissqy's "一键系统镜像 R1" (one-click system image R1), swaps in the Radxa bootloader and writes extlinux so that V1.12 boards can boot; his firmware, model, and first-boot network setup are kept as is. Optional `--no-camera`, `--no-tof`, `--overlay i2c4-m0`. `sudo bash kissqy-r1-v112.sh microduck-zero3w-0.15.1-R1.img.xz [options]`. For why the changes are needed and the offline verification results, see [kissqy image R1 analysis](../../docs/HD1910-20261012-kissqy镜像R1分析.md); **not yet tested on the robot** |

Both scripts first look for the Radxa bootloader package `u-boot-rk2410_2017.09-64-39cd993_arm64.deb` in the same directory, and only download it from radxa-repo.github.io if it is not there. Downloading from this site with curl in WSL occasionally breaks with SSL interruptions; in that case download it on Windows first and put it in the script's directory (the script verifies the checksum). Delete it afterward; do not commit this .deb to the repo.

The image uses **Armbian 26.2.1 trixie vendor 6.1.115 minimal** (specified by Pollen; mirror sites in China only have 26.8.1 left,
26.2.1 is at `https://fi.mirror.armbian.de/archive/radxa-zero3/archive/`). The Radxa bootloader is downloaded automatically from the
`u-boot-rk2410` package on `radxa-repo.github.io`; the version and sha256 are pinned in the script.

The five things the script does:

1. Writes `idbloader.img` at sector 64 and `u-boot.itb` at sector 16384 (Radxa u-boot-rk2410 2017.09-64, DDR v1.25, BL31 v1.46)
2. `/boot/extlinux/extlinux.conf`: Radxa's U-Boot reads extlinux, not Armbian's boot.scr; loads two overlays, `uart2-m0` (servo serial port `/dev/ttyS2`) and `dwc3-peripheral` (OTG port as a USB serial port), and puts the kernel console on tty1
3. Presets `/root/.not_logged_in_yet` for the first-login wizard (user, password, time zone, locale), applied only after authentication; `wpa_supplicant-wlan0.conf` configures WiFi authentication and `/etc/systemd/network/25-wlan0.network` configures wireless DHCP; removes the SSH host keys pre-generated in the base image, keeping the original system's first-boot generation service
4. `g_serial` + `serial-getty@ttyGS0`: when the board is plugged into a PC, an extra COM port appears, 115200, root can log in
5. Masks `serial-getty@ttyS2` / `ttyFIQ0`, so the login console does not occupy the servo serial port

After completing the first-login wizard and network configuration, find `radxa-zero3` in your router and log in with `ssh duck@IP`. The base image does not contain the full robot control environment; being on the network alone does not mean the web console or servo control is usable.

For further installation you can refer to Pollen's official [install-dev.md](https://github.com/pollen-robotics/microduck/blob/main/docs/robot/install-dev.md), but **with this image you cannot directly follow the `migrate-network.sh` → reboot steps**. The upstream migration script as currently checked imports wireless credentials from netplan; it will not read this image's `wpa_supplicant-wlan0.conf`, nor will it automatically retire the separate `wpa_supplicant@wlan0` / `25-wlan0.network` configuration. Keep the existing networking setup first, and migrate only after credential import, retirement of the old service, and recovery from lost connectivity have been adapted, to avoid losing the connection after reboot.

The install script's changes to `armbianEnv.txt` also need to be checked against the `extlinux.conf` actually used at boot; you cannot judge that the hardware is fully configured based only on the script's own check results.

## Onboard analysis scripts

[`onboard-analysis/`](onboard-analysis/): scripts used on the night of 2026-10-12 to investigate "the robot lunges hard as soon as the model takes over", all read-only. They include 50 Hz recording (a service that starts on boot), voltage and temperature logging, IMU self-consistency checks, four-direction checks, **IMU zero calibration** (stand at HOME → simulation computes the expected tilt → new mounting quaternion), the point where it goes out of control, joystick-driven stepping statistics, and IMU disconnect analysis.
