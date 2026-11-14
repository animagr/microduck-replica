# Microduck replica image: build scripts

**English** · [简体中文](README.md)

> **20261104 beta:** This round integrates standing-pose IMU recalibration, real-direction verification for ID200, hotspot recovery, and the 31-r1 software features; it still ships uncalibrated from the factory and by default stays compatible with the old small-board output. The full quaternion requires an explicit matching setting, and the small board is not flashed automatically. For the acceptance check boundaries of flashing the new image / changing networks / motion, and the scope of software upgrades for old cards, see [this round's release notes](../../docs/更新说明-20261104.md). The existing release records below are kept as history.

> Users read this one: [Flashing and first use](烧录和第一次使用.md). What follows is for people who build the image.

> If the hotspot does not appear, first confirm whether the board is a **Zero 3W or a 3E without onboard Wi-Fi**. The hotspot does not depend on servo IDs; this image has not been verified on the 3E yet. See [Hotspot and board model troubleshooting](../../docs/热点与主板型号排查.md).

> **2026-10-27 release:** The [20261027 Latest image](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) and the [2026.10.27 software package](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) are public. They come preinstalled with signed web updates/rollback, the matching helper, and local R3 sit/stand voice, including the Chinese ASR model and ARM64 dependencies. Runtime source is e382f074, and the signed package and the image use the same installer. The sizes/hashes of all server-side attachments and the public download links have been verified. The duck is temporarily powered off, the card has not been flashed / tested on the robot, and the physical acceptance check for this version is still pending; see [artifact hashes and verification boundaries](../../docs/superpowers/verification/2026-10-27-web-updates.md) and [software update and voice usage](../../docs/软件更新与语音使用说明-20261027.md). The 10-25 notes below are kept as historical status.

> 2026-10-25: The [software features and upgrade ledger](../../docs/软件功能与升级总账.md) records the differences between source, the current robot and the image, as well as the future upgrade direction for shared component packages. Today's standalone voice service and the pinned band are still not integrated into the generic image build; online upgrade is still to be implemented.

> Later the same day: web recording/playback and Lively were implemented in c18783c and deployed over SSH to the current duck; the inline camera preview and paired-input recovery were also synced to matching versions. The existing image was not rebuilt; a frozen source package and a single-robot deployment cannot be treated as a generic online upgrade. See [this round's acceptance check](../../docs/superpowers/verification/2026-10-25-web-motion-studio.md).

> Update: aa825fc further adds sit-down/stand-up recording, which has been deployed, and the user confirmed that saving and actual playback work normally; for v2 record compatibility and rollback scope, see the [sit/stand acceptance check](../../docs/superpowers/verification/2026-10-25-web-posture-recording.md). This version still has not been rebuilt into an image.

The replica image is an SD card that works as soon as you flash it: our forked main program, walking and action models, Microduck Studio,
first boot (naming, detecting the IMU, creating the hotspot) and network setup (opens a hotspot if WiFi cannot connect) are all installed.
This folder contains the scripts that make this card: they pull the main program and models read-only from a tuned duck, install them into the base image,
wipe the machine identity, logs and anything left behind by others, then shrink and compress it.

The image is a free download, for personal non-commercial replicas only, and is **not distributed with any paid product**: the models in it are under the author's personal non-commercial license,
see [`overlay/usr/share/doc/microduck/模型说明.txt`](overlay/usr/share/doc/microduck/模型说明.txt).

## What is in the image

| Component | Location in the image | Source | License |
|---|---|---|---|
| System base | `/` | Armbian 26.2.1 (Debian 13), kernel 6.1.115-vendor-rk35xx, Radxa's U-Boot | Per package, `/usr/share/doc/<package>/copyright` |
| Official runtime 0.15.1 | `/opt/robot/daemon/`, `/usr/local/bin/robotctl` | Pollen Robotics, source commit 1fa8438, included in the base image | Apache-2.0 |
| Main program robotd, padd, mediad | `/opt/robot/feetech-ft5-r5/` | Our fork (official 0.15.1 + Feetech bus, I²C IMU module, gyro fusion, UDP gamepad), pulled from a tuned duck | Apache-2.0 |
| ONNX Runtime 1.28.0 | `/opt/robot/feetech-ft5-r5/onnxruntime/` | Microsoft, unmodified | MIT |
| 10 walking and action models | `/opt/robot/feetech-ft5-r5/models/`, `roller/` | Trained by community authors, pulled from a tuned duck, with training archives removed | Personal non-commercial |
| Microduck Studio | From 20261027 on, `/opt/microduck/software/current/studio/`, service `microduck-studio`, port 8000; in early images `/home/radxa/studio-dev/` | [`../studio/`](../studio/), signed runtime files | Apache-2.0 |
| Local sit/stand voice | `/opt/microduck/software/current/duck-echo/`; resources in `/opt/microduck/resources/`, default single-click R3 toggle, quack confirmation | [`../duck-echo/`](../duck-echo/), Vosk small-cn0.22 and ARM64/cp313 dependencies | Apache-2.0 and each dependency's own license |
| Software update executor | `/usr/local/lib/microduck-updater/`, standalone root service; version tree `/opt/microduck/software/releases/` | [`../updater/`](../updater/), originally ARM updaterd0.15.1; has its own built-in release public key, auto-apply off | Apache-2.0 |
| First boot, network setup, root helper | `/usr/local/sbin/microduck-firstboot`, `microduck-netcheck`, `microduck-helper` | [`overlay/`](overlay/), Studio's `deploy/` | Apache-2.0 |
| Factory calibration | `/etc/robot/feetech-ft5/hd1910-calibration.toml` | [`calib/hd1910-calibration.option-a.toml`](calib/hd1910-calibration.option-a.toml): all 15 are 2048 / −1 / uncalibrated | — |

The full license text for each part is in `/usr/share/doc/microduck/` in the image, and is also copied to the output folder at build time to be published with the release.

A few factory defaults that differ from Duck No. 2:

- **The main program runs in commissioning mode** (`robotd.service.d/zzzz-zz-microduck-commissioning.conf` adds `--commissioning` to it).
  An uncalibrated duck can only read the IMU, do the coarse IMU calibration and see the calibration of all 15 servos in commissioning mode; after step 3 of the getting-started checklist,
  “写进主程序” (Write into main program), succeeds, the root helper deletes this file and the main program returns to motion mode.
- **The camera uses a test pattern by default** (`[media] source = "test"` in the official configuration `/etc/robot/robotd.toml`),
  so mediad will not crash repeatedly on a duck without a camera.
- **The radxa default password is `microduck`**, root is locked, and SSH only accepts keys.
- Gamepad button mapping and walking parameters follow Duck No. 2's `robotd.toml` (action amplitude 0.7, no automatic torque off after a fall, no automatic shutdown on a dead battery).

## Preparing inputs

### 1. Base image

`microduck-zero3w-0.15.1-R1-V112.img`: made from the community's public R1 image using the R1 conversion script in `tools/radxa/`
(arguments `--no-tof --overlay i2c4-m0`): swaps in Radxa's U-Boot and the B1 device tree, and enables I²C4 (pins 27/28)
for the IMU module. The base image already contains official runtime 0.15.1. The base image used by both the 20261020 and 20261021 versions has
sha256 `652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`.

The plan is to switch later to a clean Armbian + the official installer as the base image, so it no longer depends on someone else's image.

### 2. Payload (pulled from a tuned duck)

This duck must have our forked main program installed and already be able to walk:

- `/opt/robot/feetech-ft5-r5/` contains `robotd`, `padd`, `mediad`, `onnxruntime/`, `models/`, `roller/`;
- `/etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf` (the main program's startup arguments; must not include `--commissioning`);
- `/etc/robot/feetech-ft5/robotd.toml` (when pulled, this unit's IMU wiring is removed automatically and the sound pack is pointed back to the official one).

What gets pulled is a whitelist, read-only, and no file on the duck is changed:

```sh
# On the computer: copy the script over
scp capture-payload.sh radxa@<duck IP>:/tmp/
# On the duck
sudo sh /tmp/capture-payload.sh /tmp/microduck-payload.tgz
# On the computer: pull it back
scp radxa@<duck IP>:/tmp/microduck-payload.tgz .
```

The 20261020 version was pulled from Duck No. 2, payload sha256 `9e1e64b8…`. The robotd in it (sha256 `9b734239…`)
was built on 10-15 in the fork's working tree and **does not exactly match** any single commit (this used to say `a844db6`, which was wrong).

The 20261021 version still used this payload, only replacing robotd with an arm64 build of commit `f4bbe53` on the fork's `hd1910-v167-imu-autodetect` branch
(sha256 `0a6a86b2…`; the fork's address is in the "Software" section of the home page),
with the robotd entry's sha256 in `payload.json` updated accordingly; the payload sha256 after the swap is `26252fbc…`.
From now on robotd is always built from a commit, so it matches the source.

The robotd of the [20261023c image](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261023c) comes from the `hd1910-v167-imu-dxl2` branch,
commit `0791fcd44f71c705dc8bb0fbcde405593b52d19b`, build identifier `4734cbb-feetech-imu-auto-control.44`.
Built with Rust 1.99.0, `cargo zigbuild --locked --release --target aarch64-unknown-linux-gnu.2.31 -p robotd --bin robotd`,
`CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1`; robotd sha256 is
`edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`.
Only the robotd in the verified payload is replaced, and `[bus] imu_protocol = "auto"` is set explicitly in both the runtime and saved configuration;
the other daemons, models and ONNX Runtime keep their original files. Each file's size and hash are re-verified at repackaging,
and `payload.json` stores the source commit, build arguments and a pointer to the provenance notes; the delivered image manifest is authoritative for the full payload hash.
For the supported scope, a comparison with old-version test failures, and the real-board acceptance check boundaries, see [this version's record](../../docs/HD1910-20261023-总线IMU自动识别.md).

### 3. Build machine

Ubuntu 22.04 under WSL or any Linux, with root (for loop devices):

```sh
sudo apt install fdisk e2fsprogs xz-utils openssl python3.11
```

The scripts need Python 3.11 or later (they use `tomllib`). Ubuntu 22.04's bundled `python3` is 3.10;
after installing python3.11, make `python3` point to it, for example by creating a folder containing only that one link and putting it at the front of `PATH`.

## Building

The full-feature 20261027 image also needs four matching inputs; if any one is missing, the build refuses before modifying the rootfs. First generate the signed package from a frozen Git commit, and use `voice_resources.py` to prepare and verify the official Chinese model and the ARM64/cp313 wheel resources; the development machine's Python dependencies or any personal voice data/keys must not be mixed in. The release private key is only for signing on the build machine and is not an image input.

```sh
export SOFTWARE_UPDATE_PACKAGE=/path/to/2026.10.27.software-update.tar
export SOFTWARE_UPDATE_PUBLIC_KEY=/path/to/software/updater/release.pub
export SOFTWARE_UPDATE_ENGINE=/path/to/verified-arm64-updaterd
export VOICE_RESOURCES_DIR=/path/to/verified-resources
# An x86 build machine also needs qemu-user and the root folder of the verified ARM64 loader/libs; leave it empty on a native ARM build machine.
export SOFTWARE_UPDATE_ENGINE_COMMAND_JSON='["qemu-aarch64","-L","/path/to/arm64-libs"]'
```

When running the following commands in a root build shell, keep the environment above; when invoking through sudo, pass these fixed inputs explicitly so that sudo clearing the environment does not fall back to the old build. Without the full set of component inputs, only the old image build behavior is kept, without the new upgrade/voice suite. In the final image, check `/usr/share/doc/microduck/software-components.json`, the voice resource notes, and the actual version files.

When the signed software package contains a controller companion bundle, after the shared installer finishes, `controller_factory.py` reads and checks the frozen main program, padd, the two native manifests and the voice dependencies from the verified version tree. Only if the two binaries in the image payload are byte-for-byte identical does it install the four declared service drop-ins, the root-owned voice compatibility gate and the compatibility marker, all files 0644; a manifest with missing parts, a hash mismatch or a symlinked target is refused. The sources and hashes of supporting files are recorded in `controller_bundle` in `software-components.json`. Old software packages without a companion bundle keep the original build behavior. This step only operates on the offline ROOT; it does not start services, copy personal state, change models, calibration or the legacy protocol default, or flash the MCU.

```sh
sudo STUDIO_VERSION=<Studio commit hash> IMAGE_VERSION=<commit hash of this folder> \
    sh build-image.sh /path/to/microduck-zero3w-0.15.1-R1-V112.img \
    /path/to/microduck-payload.tgz ../studio ~/microduck-out
```

- `OUT_DIR` must not be under `/mnt`: loop devices on WSL's Windows drives are very slow and the permissions are wrong; use `~/microduck-out`.
- For your own acceptance-check card only: `DEV_AUTHORIZED_KEY="$(cat some-key.pub)"` writes that public key into radxa's
  `authorized_keys`, so you can fix problems remotely without reflashing the card; the image manifest will note it. **Never set it for an official release**:
  that would leave a back door into every user's duck.
- If version numbers are not given, the script uses `git rev-parse` itself (adding `-dirty` if there are uncommitted changes), and writes “未知” (unknown) if it cannot get one.
  Under WSL, reading a git worktree on a Windows drive often fails, so pass them yourself for releases.
- The image file name defaults to `microduck-replica-<date>.img.xz`; for a second version on the same day, pass a name such as `IMAGE_TAG=20261021b` (digits and lowercase letters only).
- About 10 minutes. Outputs:
  - `microduck-replica-YYYYMMDD.img.xz` and a `.sha256` with the same name;
  - `镜像清单.txt` (image manifest): sha256 of the base image and payload, what was removed, what was added;
  - `开源许可.txt` (open-source licenses), `第三方.txt` (third party), `模型说明.txt` (model notes);
  - `work.img`: always kept; delete it manually once everything is confirmed.

Standalone check entry points (no root needed):

```sh
sh build-image.sh --selftest                 # GPT / MBR partition line rewriting
sh capture-payload.sh --clean-toml IN OUT    # robotd.toml cleanup function
sh apply-rootfs.sh ROOT PAYLOAD ../studio ./overlay   # trial install on a fake directory tree (ROOT must not be /)
```

## Testing

```sh
# Run everything as root under WSL (a few tests need root to verify ownership and permissions)
python3 -I -m unittest discover -s tests -v
sh -n apply-rootfs.sh && sh -n build-image.sh && sh -n capture-payload.sh
```

On Windows, `py -3.13 -I -m unittest discover -s tests -v` also works (with Git Bash's sh); the permission test is skipped.

## What the scripts stop on their own

During the build, if any of the following is not satisfied, the build stops and states clearly which step it stopped at and what to do:

- the sha256 of any file in the payload does not match the manifest, there are files not in the manifest, or there are symlinks;
- overlay, Studio's `deploy/` or `run.py` contain Windows line endings (CR):
  cloning on Windows with `core.autocrlf=true` turns scripts without an extension into CRLF, and they will not run at boot.
  The repo's `.gitattributes` already sets LF for these folders;
- other files in the image (including binaries) still contain the old image author's identifier; the fixed attribution in `模型说明.txt` and the source provenance record in `payload.json` are kept;
- `etc/systemd`, `udev` or `cron` contain dangling links, or still reference deleted files;
- `opt/robot/feetech-ft5-r5` still contains training archives (`export-data.zip`, `training-*.json`, `upstream-params`, `*.pt`);
- “待人工确认” (pending manual confirmation) still contains regular files (first confirm they contain no personal data, then allow them through with `ALLOW_UNCONFIRMED=1`; the manifest will note it);
- the official sound card initialization (`aic3104-init`) is incomplete.

In addition: every deletion is printed before it happens; every write goes through `safe_dir` / `safe_file`, so a symlink inside ROOT pointing outside makes the script fail
instead of damaging the host; `apply-rootfs.sh` does not touch loop devices and does not chroot.

## Pre-release check

1. All tests pass (WSL root).
2. Build from committed code, with commit hashes in `STUDIO_VERSION` and `IMAGE_VERSION`, and no `ALLOW_UNCONFIRMED` overrides in the log.
3. Decompress the delivered `.img.xz`, mount it read-only, and at least check: the sha256 matches; `e2fsck -fn` reports no errors;
   the sha256 of the main program and models matches the payload, and all models referenced by `robotd.toml` are present;
   the commissioning-mode drop-in is present; `machine-id` is empty and there are no SSH host keys; SSH only accepts keys;
   the old author identifier is only allowed in the fixed attribution in `模型说明.txt` and the provenance list in `payload.json`.
4. Record the physical acceptance check scope for a fresh card of this version going through [Flashing and first use](烧录和第一次使用.md) from scratch: hotspot → network setup → the 6 steps of the getting-started checklist → stand up and walk. If it is not completed, mark that clearly in the release notes; the real-hardware pass result of an older version must not be carried over. For 20261027, the user authorized publishing the verified software/image first, and the physical acceptance check for this version will happen after the robot is powered on.
5. The fork commit corresponding to the main program in the image has been pushed to the fork.
6. Publish: put the `.img.xz`, `.sha256`, `镜像清单.txt` and the three txt files on GitHub Releases;
   the first paragraph of the release notes says “free, for personal non-commercial replicas only, not distributed with paid products”.
