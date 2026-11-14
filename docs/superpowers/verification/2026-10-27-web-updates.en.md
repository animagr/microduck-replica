# Web software updates, local voice and new image: delivery record

**English** · [简体中文](2026-10-27-web-updates.md)

Date: 2026-10-27 (JST). The user asked for online updates through the web console and for the local voice commands "坐下／站起来" (sit down / stand up) to be included in the new image; they then confirmed "暂时关着，先完成本地软件和镜像" (keep it off for now, finish the local software and image first). Free-form AI voice conversation remains paused.

**The software, signed package, first-boot bootstrap package and matching image are complete. The user later authorized pushing and public release; the master source, the 20261027 Latest image and the 2026.10.27 software release are all done, see the [public release record](2026-10-27-web-updates-publication.md). Nothing was deployed to the powered-off duck and no card was flashed; first-boot bootstrapping of the old card and the physical acceptance check of the new image still have to be done after power-on.**

## Versions and artifacts

The runtime files are frozen at `e382f0741d7dfe4e972605e2843474df7219cade`; the later `1b7416e` only fixes the wait conditions of three existing browser regression tests, and the runtime files are identical. Software version `2026.10.27`. The final documentation commit is recorded separately in the Git history and does not change the runtime source inside the package.

`复刻镜像-20261027` (replica image 20261027) and `软件升级包-20261027` (software update package 20261027) in the workspace root are the local deliverables. Full file sizes/hashes are stored in `artifacts/software-updates-20261027/delivery.json`; the image, update package and bootstrap archive each come with a SHA256 file.

| Artifact | SHA256 |
| --- | --- |
| `microduck-replica-20261027.img.xz` | `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194` |
| `2026.10.27.software-update.tar` | `b6543c9f3a2ad6477106410dbed9753be9fa37c61b79ea0350767a18229d0e55` |
| `microduck-bootstrap-20261027.tar.gz` | `866f8d49e3097133ab911debda9c4fdc66b9f02b867a789aadfb9793b99b3610` |
| Release public key | `0878853a92b10c9196c5b63e02087664923c576e6bc2e064d3bbdcc1be056bf5` |
| Voice resource manifest | `2639f40cd196c7f64fd5adef2220c135b82186c5ebe22ff527c57fde7ae66b9c` |

Image 741,604,104 bytes, web update package 5,683,200 bytes, bootstrap archive 57,811,043 bytes. The bootstrap archive contains only the frozen public source, the original ARM64 engine, the public key, the signed package, ASR resources, licenses and instructions; it is not a web upload package and has not been run on the duck. Normal web uploads use the separate `.software-update.tar`. The new image has already gone through the same bootstrap, so no repeated initial installation is needed.

## Implementation and boundaries

- A new Software Update section at the top of Settings: version, check, download, offline upload, verify, install, task status, read-back after reconnect, and rollback. It reuses login, Host/Origin/CSRF and no-store; the allowlist does not accept arbitrary sources, paths or shell.
- One signed software component manages Studio, the matching helper and duck-echo. The executor/health check/public key, user data and ASR resources live outside the version tree. Allowlist of frozen Git runtime files, with no tests, logs, user state or private keys. The outer USTAR four-file layout is strictly validated, and the inner tar.zst is verified by the original engine.
- Uses the actual ARM64 updaterd 0.15.1 from the original image, source `1fa84386f07884e27866411bc1ba166977bced95`, IPC API 37, with a custom profile/from_dir/dry_run; no separate transactional switching engine was written. `auto_apply=off`, no periodic checks/automatic installs.
- A separate root controller exposes fixed verbs over IPC with peer permission checks; the release source is fixed to official `microduck-software-v` releases of `fanhao375/microduck-replica`. "No release", network error, successful download and successful install are each shown separately. The first 2026.10.27 software Release is public; when checking from the image of the same version, "no newer version" is the normal state.
- The original engine also tries to restart updaterd/btd with a delay; the stable service boundary rejects these and only allows the web and voice services. The offline build is forbidden from modifying any host service; the health check uses the real absolute systemctl path.
- Before switching it checks a fresh bus read-back, actual standing posture/policy off, the 15 joints/speeds/times, power supply, disk space, and whether recording/playback, calibration, servos or audio are busy. A marker plus a cross-process lock protect both the web console and the physical R3 button, late ASR results are cancelled, and races between the pre-check and sit/stand commands are avoided; e-stop, torque release and turning off listening remain available.
- The bootstrap checks the old service drop-ins, overrides the known 10-image.conf, and rejects unknown custom startup configuration. Old state is copied to a private staging area after checks for fixed UID, no-follow directory descriptors, type/link count/size, and then atomically migrated to an empty target; user-controllable trees are never recursively chown'ed. Existing non-empty new state is kept; on error the original service and program entry point are restored.
- Studio runs as a normal user with explicit external StateDirectory/LogsDirectory; the program tree is root-owned and not writable. Voice defaults to actions/toggle/duck and does not listen at startup, with an explicit shared ASR path, Mic3R startup preparation and audio/input permissions.

## Actual verification

| Check | Result and scope |
| --- | --- |
| Full Studio non-browser regression | `STUDIO_E2E=0 py -3.13 -I run_tests.py`: 1201 tests, 268.296 s, OK, 75 skipped. The Windows AF_UNIX voice status thread produces a known environment notice; we do not claim the native Windows audio chain passes. |
| Local voice | 155 tests, OK, 18 skipped; plus 12 targeted checks in WSL (real flock, late ASR cancellation, etc.) passed. |
| Updater on Linux | 18 independent quality-review items passed, including real UID 65534 authentication/log writing and rejection of symlink and migration races. |
| Image side | 128 tests passed, 49.590 s, including wrong hash/unknown path, complete component inputs, shared signed bootstrap, and failures not recorded as success. |
| Original ARM updater/QEMU | All 10 checks true: signed first install, dry-run, rejection of wrong hash/manifest signature, 27→28 switch, manual rollback, automatic rollback on health failure, recovery after killing and restarting the engine following a persistent switch, service scope. No motion commands were sent to the actual robotd. |
| Final real Edge | Actual Studio/controller at e382f07, 1 test passed in 17.394 s; 1440/390/320 layouts, no release, download waiting for the robot to settle, verify, install, refresh task, rollback, upload, rejection of bad package and extra root fields; console errors empty. The engine/device pre-checks were explicit test doubles; the original engine's transactions were tested separately, and the doubles are not called a real-robot update. |
| Independent spec re-review | Passed at 503b7cf: 9 controller + 4 voice checks; R3 mutual exclusion P2 closed. |
| Independent quality re-review | Passed at e382f074: external state/logs and no-follow migration of old state issues closed, no remaining P1/P2. |
| Actual ARM Python in the image | Python 3.13.5/Vosk in the read-only image loaded the Chinese model successfully, and silence was recognized as empty; ARM Python under QEMU as UID 65534 started Studio from non-writable source, healthz succeeded, and external state/logs were writable. All robot endpoints were off. |

One full run including the old browser test cases once gave 1200 tests, 3 failures, 5 skipped. Compared against the 18cd3 baseline, this was traced to test races: the battery value was locked by the filter before Edge started, and the servo-off state came before the asynchronous bookkeeping finished. 1b7416e only fixes test synchronization; it does not change the product or weaken the original assertions. The three original failures passed on rerun in 35.020 s, and the full 1201-test non-browser regression above then passed; the full old browser suite was not run again.

Reports are in `artifacts/software-updates-20261027`: studio-unit-regression.log, image-tests.log, engine-acceptance.log, browser-final/browser.json and screenshots, image-verification.json, native-voice-check.json, unprivileged-startup.json, build-image.log, verify-image.log and delivery.json.

## Image build and read-only acceptance check

Reuses the already verified base image and runtime payload, without changing the gait model:

- Base image SHA256: `652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`.
- Payload SHA256: `370f64af5c690eeebab429f4c59d9c5d00883b5cf1e7f0d0e2c18d4afe45998d`.
- robotd SHA256: `edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`; source `0791fcd44f71c705dc8bb0fbcde405593b52d19b`.
- Original updaterd SHA256: `d5f9086bae5c2ec10ba75fc2d41c27578236a12d9a6364bffa8d9315fda97fa6`.
- Vosk small-cn 0.22 ZIP SHA256: `3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba`; 11 ARM64/cp313 wheels, 304 resource files, 80,414,834 bytes. The model is Apache-2.0; dependency licenses are retained.

The signed package is built from a frozen Git archive, and the existing WSL image script calls the same shared bootstrap. The delivered xz was decompressed independently; SHA/xz/partition/e2fsck read-only checks passed, then it was mounted ro,noload for the acceptance check and unmounted:

- 39 hashes of the original runtime/model and 9 model references match; all 15 servos remain uncalibrated, and the IMU commissioning defaults are correct.
- All 350 software runtime files match hash by hash, the current relative link is root-owned and not writable; source e382f07 and the package hash match.
- Separate updater/public key/config, automatic apply off, stable services, State/Logs permissions and the 90 override are correct, and the sudoers syntax passes.
- All 304 voice resource file hashes match; Mic3R preparation, explicit ASR path and actions/toggle/duck defaults are consistent, and the actual ARM model load passes.
- No personal Wi-Fi, SSH host/developer keys, machine ID, web user data, AI key or release private key. The camera is still the test source.

The release private key exists only in a private directory on the build machine; Git/the image/the delivery packages contain only the public key. Artifacts were copied to the Windows directory and their sizes/hashes rechecked. Following the user's later instructions, the source was pushed and the image/software attachments were published; for the public status and anonymous download verification see the [release record](2026-10-27-web-updates-publication.md).

## Still awaiting physical verification

The duck is off; first-boot bootstrapping of the old card, actual web update/rollback, physical power-loss recovery, real human acoustics, and the complete first-use flow with a new card have not been done. The user previously confirmed the original sit/stand voice commands worked; this image combination still has to be verified on the robot. The QEMU kill/restart recovery does not replace an acceptance check with a real power interruption.

The problem with the head/body actually moving when following the music beat is still to be fixed, and free-form AI voice conversation is not integrated; this release does not count them as done. For usage steps see [Software updates and voice](../../软件更新与语音使用说明-20261027.md).
