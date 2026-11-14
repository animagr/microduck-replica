# Online software update flow for existing ducks

**English** · [简体中文](在线升级流程方案-20261027.md)

Date: 2026-10-27 (JST). Prompted by the community discussion "add incremental updates to the image so people do not have to reflash repeatedly", the user first had the online update flow reviewed, then authorized implementing it. This document keeps the initial design; on the same day the local software, signed package and matching image were completed, see the [delivery verification](superpowers/verification/2026-10-27-web-updates.md) and the [usage instructions](软件更新与语音使用说明-20261027.md) for the actual results. Later, following the user's instructions, the source was pushed and the image/software package published, see the [release record](superpowers/verification/2026-10-27-web-updates-publication.md); the duck was off, and nothing was deployed or flashed. The "current/future" descriptions below reflect the state at design time and do not override the delivery record.

## Recommended approach

Use **software update packages released per component**: when the web console or voice has an update, only that software is updated, and models are updated independently; the system image is used for the first installation on a new card and for system recovery. In the first version, "incremental" means not rewriting the whole card and downloading only the components that changed; inside a component, a complete reproducible version package is used first, to avoid generating binary-diff patches for every old version. If download size really becomes a problem later, content addressing or differential transfer can be added; the install and rollback flow does not depend on diffs.

The first batch covers only the Studio web frontend/backend, the matching helper and the duck-echo voice program; the speech recognition model resources can be reused by hash and need not be re-downloaded every time. The helper is handled as an associated component that is restarted/replaced only when needed. The Feetech robotd/padd, motion models and the system base each have their own update contract and are not mixed into the web update for now. The user interface can still present one "whole software suite version", while each component's version and dependencies are tracked internally.

## The complete flow the user sees

| Step | Page and actual behavior |
| --- | --- |
| 1. View version | Settings gets a new "软件更新" (Software Update) section listing the current suite version, component versions and the result of the most recent update; the version is determined from the actual running bytes and the install record, not just the existing generic `0.1.0-dev`. |
| 2. Check for updates | The duck fetches a trusted version manifest from the maintainer's release address, and shows new features/fixes, download size, supported hardware and systems, which services will be restarted, and the rollback scope. No update, no internet access and version mismatch are each explained separately. |
| 3. Download to the device | Downloads into a separate temporary directory, retryable; limited by the declared size and free disk space; verifies the signature, package hash, unpacking manifest and compatibility. If the download fails the current software is kept, and installation must not be shown as successful. |
| 4. Click "立即更新" (Update now) | Right before actually switching, it checks battery/power supply, disk, busy operations and the latest robot state again. Web/voice packages use the already verified precondition "stopped and standing, policy off"; it cannot be judged from the sticks being centered alone. Runtime/model packages each need their own confirmation of the install posture and cannot reuse "restart robotd while standing". When the preconditions are not met, the specific reason is shown and the current version is kept. |
| 5. Back up and switch | A single update task holds a lock, backs up the data that needs migrating and the previous version, and writes a persistent transaction record. A separate update service stops the necessary services, switches to the complete new version, then starts it; the web backend that is being updated cannot also be the sole executor. |
| 6. Verify and restore the page | Verifies the new version's actual files/runtime identity, service interfaces, static resources and key configuration. While the web console is briefly disconnected it shows "正在更新，等待重新连接" (Updating, waiting to reconnect); after recovery it reads the real result by task ID, rather than relying on a countdown in the old page to declare success. On success, the current version is recorded and the previous version is kept. |
| 7. Automatic rollback on failure | If startup or checks fail, the previous version and a compatible data snapshot are restored, and the old version is verified to run. Without a network, rollback can use the package already on the device. A manual "退回上一版" (Roll back to previous version) goes through the same execution path; an update with an irreversible data migration must say so before release and provide a verifiable recovery plan. |

By default, day to day, **installation happens only when the user clicks update**. Detecting a new version does not restart or switch software by itself; the upstream default policy of automatically applying a mandatory minimum version is not copied. The first version does not need any new scheduled task.

## First onboarding and later updates

The current duck's web console has no update entry point yet, so the compatible update service, trusted public key and web entry point need to be installed once over SSH, and the existing component baseline registered; this is a one-time bootstrap and does not require reflashing the card. The bootstrap itself must also back up and verify. After that, clicking update in the web console is enough.

A newly made baseline image comes with the same updater and version manifest preinstalled. New image installs and old card upgrades use the same set of signed component packages and install rules, so that "newly flashed card" and "upgraded old card" end up at the same software version. With an old image, the model, runtime, install paths and actual file hashes are identified first, then a supported migration entry point is used; unknown or modified states are reported explicitly rather than blindly overwritten.

Online download requires **the duck itself to be able to reach the release address**. The computer/phone only opens the web console and triggers the task; if the phone has mobile data but the duck cannot get online, the duck still cannot download by itself. "Upload an already downloaded update package from the web console" is kept in parallel as an offline entry point, using exactly the same signature, compatibility checks and installer; it is not the browser uploading an arbitrary script to execute.

The release address is GitHub Releases or an HTTPS file site reachable from the target network. Network conditions determine the download experience, but wherever it is downloaded from, the signature is verified with the built-in public key; verification must never be turned off because some address is unreachable, nor may the user's credentials be carried along to an unfamiliar address on redirect.

## Update package and data boundaries

The publisher builds a version package once, containing: the suite and component versions, source commits, target hardware/ARM64/system and Python requirements, component interface dependencies, file list and hashes, compressed/expanded sizes, required services, data migration/rollback notes, health checks and change notes. It is signed with the maintainer's private key, and the duck only holds the public key. Configuration and execution verbs are controlled by the device updater's allowlist; the web console cannot send arbitrary shell commands or replace the update source.

User data is kept separate from program version directories, and an update must not overwrite the user's device with the configuration from the publisher's machine:

- Keep servo zero positions, directions, limits, IMU calibration/mounting orientation and existing tuning.
- Keep Wi-Fi, gamepad pairing, device identity, SSH and web login settings.
- Keep imported models, the current model selection/key bindings, device profiles, saved actions and voice preferences.
- Keep saved AI connections and API Keys. Data backups containing keys keep private permissions and do not go into release packages, logs or diagnostics.

Program version directories use complete snapshots and atomic pointer switching; a directory that has not finished downloading or whose unpacking has not been verified cannot be run. Transaction steps are persisted and verified before and after the switch, so that after an abnormal exit of the update process or a device reboot it can tell whether to continue verifying or to roll back. Power-loss recovery is an acceptance check item; one cannot claim recovery is guaranteed after a brownout just because of `os.replace` or "there is a backup".

## Local review results and reuse decisions

| Existing asset | Verified facts | How to use it |
| --- | --- | --- |
| Original updaterd source | The local Rust updater includes manifests, signature verification, download, version directories/switching, health checks, rollback, UNIX IPC and a local source; the configuration has component install directories, service actions and custom-command health checks. | Prefer using the existing engine for compatibility verification before deciding the scope of adaptation, to avoid reimplementing a complete update transaction. |
| Original deployment configuration | The default daemon directory is `/opt/robot/daemon`, the update source/signatures belong to upstream, and periodic checks plus mandatory automatic apply are configured. | The current Feetech runtime and Studio directories differ, so the original configuration cannot be enabled directly. The replica stack needs its own component configuration, trusted release source and public key, with a user-clicks-install policy. |
| Current Studio | Runs from `/home/radxa/studio-dev`, and the web console has no online update route; user state defaults to `/var/lib/microduck-studio` or state in the source directory. | First migrate to a program version directory that can be rolled back, with state kept outside the version; existing URLs/login are preserved. |
| duck-echo | Runs separately from `/opt/duck-echo`; the install script only restarts itself, and there is already a fixed runtime file list and install rollback. | Separate component; recognition dependencies/model resources managed separately, keeping user defaults. |
| Recent single-device SSH update | Already did a frozen commit, hashes of changed files, read-back after the robot settled, private backup, failure recovery, and post-deployment HTTP/hash/12 original user files/core process identity checks. | These are the practical basis for the updater's acceptance checks, and do not mean a public general-purpose OTA already exists. |
| Image scripts | The existing build checks files against the payload manifest, writes image/Studio provenance information, and cleans out personal configuration. | In future, switch to consuming the same set of signed component version packages, rather than copying an in-development SD card into a public image. |

On the current device, updaterd was inactive/disabled in the previous inventory; this round did not recheck the service or enable it. Features present in the source cannot be treated as capabilities already installed on the current device. First verify in a fake root/temporary directory that the existing engine can manage Studio and duck-echo and their recovery, then build it into the first bootstrap package. If the old engine on the device lacks a necessary interface, explicitly upgrade the bootstrap component; do not let the web console bypass signatures or execute arbitrary root scripts.

## Implementation order and acceptance

1. Freeze the currently deployed Studio 991bb50, voice 2f24a6a and the actual dependency/runtime information as the **first baseline package to be made**; first verify all running bytes, and do not include the paused AI voice draft. Add a unified component version registry. This is not an announcement that a package has been built and released.
2. Build local package install, verification, rollback and logging with the same installer, prioritizing verification of the existing updaterd adaptation. Fake-root tests cover wrong signature/wrong hardware/version gaps, unpacking outside bounds, insufficient space, failed configuration migration, concurrent installs, services failing to start, executor crashes and power-loss recovery.
3. Add the "软件更新" (Software Update) page behind web login and a minimal restricted proxy, reusing login/Origin/CSRF; upload/check/download, install, rollback and status are each explicit, and checking for updates is not merged with installing into one step.
4. Install the bootstrap package once on the current duck; physically verify failure rollback, user data retention, web reconnect and restarting services only as actually needed. Specifically confirm that the separate update service can still recover when Studio fails.
5. Put the same set of packages into a new image; verify that an old-card upgrade and a new-card first install reach the same program hashes, and that the public image has no personal network/keys/recording data.
6. Only after the above pass, extend to Feetech runtime and model updates, and separately verify the main program's stop posture, the model execution contract and rollback. A/B upgrades of the general OS/kernel/bootloader are not a prerequisite for this round of everyday software updates.

## References

- [Feature and update ledger F21](软件功能与升级总账.md)
- [Image build and existing distribution flow](../software/image/README.md)
- [Upstream updater design](../../Microduck-kissqy/microduck-hd1910/firmware/docs/design/updater-design.md)
- [Actual updater deployment configuration](../../Microduck-kissqy/microduck-hd1910/firmware/deploy/updater.toml)
- [Latest single-device web deployment record](superpowers/verification/2026-10-27-ai-provider-settings.md)

In the initial design stage only the flow was produced, and the device was not modified. Following the user's later authorization, the local implementation is done: the signing private key stays only on the build machine, and the public key goes into the package/image; the bootstrap input package is prepared, and the device services are still unchanged. The AI voice preference "spoken reply + web text" is kept on a separate draft branch, to be continued later.
