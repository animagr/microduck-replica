# Cubie A7Z full duck image

**English** · [简体中文](README.md)

This image targets the **Radxa Cubie A7Z + this project's HD1910 servo/bus IMU assembly** and delivers the system, network provisioning, Studio, the A7Z main controller program and the action models together. The candidate files are:

```text
artifacts/cubie-a7z-duck-20261109-preview1.img.xz
artifacts/cubie-a7z-duck-20261109-preview1.img.xz.sha256
artifacts/cubie-a7z-duck-20261109-preview1.img.xz.manifest.json
```

For the image download and checksum attachments, see the [A7Z preview1 Release](https://github.com/Liangjin5437/microduck-replica/releases/tag/a7z-duck-image-20261109-preview1); the source is maintained in `radxa-cubie-a7z/` of [Liangjin5437/microduck-replica](https://github.com/Liangjin5437/microduck-replica). The complete image is distributed as a release attachment and is not put into the Git source.

The published preview1 is a historical preview image built before the fixes. The read-only installer, image directory permission and Wi-Fi provisioning fixes in the current source still need to be repackaged and verified on real hardware. During the build, the connection to the original board at `BOARD_IP` timed out, so flashing and booting the historical image, real-world networking, actions and sound are also still awaiting acceptance checks.

## Flashing and first use

1. Check the `.sha256` file of the same name, then use a flashing tool that supports `.img.xz` to write it to a microSD card of at least 8 GB (6,776,878,080 bytes after decompression). Writing erases the data on the target card. **Do not use the Zero 3W image instead.**
2. Put the card in the A7Z, connect the corresponding hardware and power it on. The first boot completes system initialization, partition expansion, and generation of the device identity and sound files; wait for the provisioning hotspot to appear.
3. Connect your phone to the open hotspot `qiqilong_XXXX`, and stay connected when it says "No internet". Open [http://10.42.0.1/](http://10.42.0.1/) and enter your own Wi-Fi name and password. After submitting, the hotspot closes temporarily; if the connection fails, the hotspot comes back and the page shows the reason.
4. Put your phone back on the same Wi-Fi and open `http://cubie-XXXX.local:8000/`. If your phone does not support `.local` resolution, look up the duck's address on your router and open `http://设备IP:8000/` (设备IP = the device's IP). The provisioning page uses port **80**, and Studio uses port **8000**.
5. Enter Studio and complete, in order, servo zero position/direction, IMU mounting orientation and submission of the main program calibration. A new assembly must be recalibrated; the image does not carry over another duck's motion authorization. The initial Studio can be opened directly on the same network, and an admin password can be set in the settings. The system keeps the base distribution's default login credentials; change the `radxa` user's password after your first login.
6. Once calibration passes and the page confirms it is ready, have an on-site operator support the robot and check the range of motion, then explicitly run stand up, walk and other actions. Booting the image does not make the robot stand up or walk automatically.

The device's machine-id, hotspot/hostname suffix and SSH host keys are generated when a new device boots; the original board's Wi-Fi password, Studio login state and SSH host keys are not copied to anyone else. Once Wi-Fi is saved, later boots try to reconnect; if no network is available, the provisioning hotspot comes back.

## Packaged features

- Studio debugging, servo and IMU calibration, the web virtual gamepad and the current web console frontend `20261109-console1`.
- Walk/hold, sit down/stand up, head-down pick-up, forward roll and left/right ball-kicking models; the packaged roller-skating model resources are also kept.
- The duck quack synthesizer and first-boot sound library generation; the main controller plays sound through ALSA. The configuration uses the `default` sound card; the A7Z's actual speaker/amplifier output still has to be confirmed on the board, and packaging the sound program does not prove that the quack can actually be heard.
- Automatic provisioning, A7Z UART adaptation and the existing thermal policy.

The first boot is in **commissioning calibration mode**: none of the 15 joints or the IMU are authorized for motion. After Studio submits a new calibration, it switches to normal mode, and a person then enables actions. Calibration mode turns off main controller audio, so check the normal quack after calibration is done.

The physical gamepad, configd provisioning inside Studio, the camera, ToF, continuous speech recognition and the joint tracking backend are not enabled in this version. First-time networking uses the standalone provisioning page; the web virtual gamepad does not depend on the physical gamepad service. Previous installations have hardware step feedback, and also records of unresolved intermittent bus read failures; this package does not fix that root cause. Sustained gait, pick-up and rolling still need on-site verification.

## Maintainer rebuild

The build requires the pinned external inputs listed below; a plain source checkout does not include the complete dependencies and cannot be rebuilt directly with one command. The scripts keep defaults from the original build directory layout; maintainers must prepare inputs with matching versions, digests and directory locations, or explicitly configure the input parameters of the corresponding scripts. The `create_image.py` entry point currently only offers `--base`, `--output` and `--release`.

Run this in this directory; use a brand-new output path, as the build program refuses to overwrite existing output:

```sh
python3 create_image.py \
  --base ../os/radxa-a733_bullseye_kde_r6.output_512.img.xz \
  --output artifacts/cubie-a7z-duck-local-rebuild.img.xz \
  --release a7z-duck-local-rebuild
```

Requires Python 3.13 (3.13.6 was used this time), `xz`, `debugfs` and `e2fsck`; keep enough temporary disk space for the decompressed image, a copy of the root partition and the compressed output. The build works on local file copies; it does not connect to the board or write to physical disks.

The source files and versions are pinned as follows:

- Base system: `../os/radxa-a733_bullseye_kde_r6.output_512.img.xz`.
- Actions, sound and inference library: external runtime archive `Microduck-Robotd-FT6-R17.tar.gz` (the script's default layout is the neighboring `10fanhao_duck/runtime/microduck-hd1910/firmware/console/updates/`); SHA256 `bcfd5c183c697b9c4e0fdbd563d995eda6a48331a7c49b9e76d20bd156c65cce`. Each file is additionally checked against the `SHA256SUMS` in the archive.
- A7Z robotd: `../control/artifacts/robotd`; SHA256 `1e46542006209b10a1e1d4d07bceb66bd492e6057138b7a4491dce47d9f940dc`; the build record is in `../control/runtime-build.json`.
- Studio standalone Python and dependencies: `../studio/artifacts/cubie-studio.tar.gz`; SHA256 `db8bcde8d9823c3e10abce1a015cd2422b81c25b279ac4f6a516d51c1fd10590`. The latest app is rebuilt from pinned commit `f682b7bd30d1ef4e6f931db16406b340d4d54fec` of the external Studio source repo (the script's default layout is the neighboring `10fanhao_duck/studio-replica`), this repo's A7Z patches and `../studio/console-integration/web/`, with the digests of three key backend files verified separately.

`prepare_runtime.py` generates the new-assembly configuration and the runtime overlay; `prepare_image.py` adds the latest Studio, first boot, provisioning and service configuration; `build_image.py` applies the overlay to the original system's root partition. The old R17 `service.sh` and the generic upgrade flow are not suitable as the A7Z upgrade entry point for this image. When distributing, keep the packaged licenses, model sources and third-party notices.

## Historical preview1 verification record

99 related tests passed locally: 17 image tool tests, 12 provisioning tests, 9 thermal tests, 43 frontend installer tests and 18 first-boot contract tests. All action model paths, inference library dependencies and the Studio calibration build/verification flow were also checked statically; `units_verified=false` does not block a normal calibration submission, it means the current conversion has not been confirmed yet.

This image has been generated: 1,191,047,044 bytes compressed, 6,776,878,080 bytes decompressed, SHA256 `5ff1112d37f843f6da3335a0e1f56f741945acd639515a3b840967c2146a9e25`. Readback of the content, permissions and ownership of 5,364 files/directories/links passed, the primary and backup GPT checks passed, `e2fsck -fn` exited 0, and `xz -t` passed; the full manifest is in the `.manifest.json` of the same name. This record does not replace actual boot and action acceptance checks after flashing.

To troubleshoot the first boot, check:

```sh
systemctl status cubie-duck-firstboot robotd microduck-studio cubie-provision --no-pager
journalctl -u cubie-duck-firstboot -b --no-pager
cat /var/lib/cubie-duck/firstboot.done
cat /var/lib/cubie-duck/audio-devices.txt
```

The release information inside the image is at `/usr/share/cubie-duck/image-release.json`; the runtime digest is at `/usr/share/cubie-duck/runtime-manifest.json`. If the initial calibration is not complete or a servo/IMU is missing, deal with the problems reported on the page first, then verify the actions.
