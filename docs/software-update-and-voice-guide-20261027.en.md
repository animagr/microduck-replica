# Software Update and Local Sit/Stand Voice

**English** · [简体中文](软件更新与语音使用说明-20261027.md)

This delivery manages the web console, the matching helper and local voice as one signed software package; the new image uses the same package. Local voice does not need an AI account or API key. For the build, deployment and the physical acceptance check scope of this release, the [verification record](superpowers/verification/2026-10-27-web-updates.en.md) is authoritative.

## Release entry points

The software version is `2026.10.27`, with the matching image `20261027`: [software package and first bootstrap attachments](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) · [image and SHA256](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027). The new image already has the same software version installed, so it is normal for "check for updates" to report that you are on the latest version.

## Existing ducks and new cards

Existing cards do not need to be reflashed for everyday software updates. The first time, a compatible upgrade entry point and resources need to be installed once; after that, update from the web console. The new image comes preinstalled with the entry point, release public key, Chinese voice model and ARM64 dependencies; new cards still first need Wi-Fi provisioning, servo/IMU calibration and the getting-started checks.

The install package keeps your own Wi-Fi, pairing, calibration, model selection, recorded actions and AI keys; the public image has this personal information cleared. A new image cannot be flashed directly over an existing card's personal data as a substitute for upgrading.

## Web console update

Open "设置" (Settings) at the usual control address; "软件更新" (Software update) at the top shows the package version and task results. First set and log in with the web console password.

1. Click "检查更新" (Check for updates) to see the new version and its notes. No software package on the release source yet, network failure, and already on the latest version are each shown separately; for the first release, having no higher version is normal.
2. Click "下载更新" (Download update). When offline, you can also download the same `.software-update.tar` file on a computer and then click "上传离线包" (Upload offline package).
3. Turn off voice listening, music, recording/replay and servo/calibration sessions, stop and stand the robot up following the original procedure, turn off the locomotion policy, and make sure the battery is sufficiently charged. If the preparation conditions are not met, the downloaded package is kept and the page shows the specific reason.
4. The upgrade engine verifies the signature, file hashes and installation requirements; once it shows the package can be installed, click "立即更新" (Update now). During the update, new web console actions and voice sit/stand are paused, while the stop and torque-release controls remain available.
5. The web console service restarts briefly, and the page reconnects automatically and reads back the task result. Refreshing the web console does not cancel the background installation; do not keep submitting new tasks because of a temporary disconnect.
6. If the new service check fails, the previous version is restored automatically. When an old version exists, you can also click "退回上一版" (Roll back to the previous version), which uses the version already on the robot without downloading again.

Online checking and downloading require the duck itself to be able to reach the release address; your phone having mobile data does not mean the duck can get online. Software releases and image releases are identified separately, and an image file will not be installed as a web console update package. Only packages verified against the built-in release public key can be installed; you cannot rename an ordinary archive and upload it.

## Voice "坐下 / 站起来" (sit down / stand up)

The existing R3 operation is kept: press the right stick button once to turn it on, and after the short prompt sound say “坐下” (sit down) or “站起来” (stand up); press R3 again to turn it off, with a different prompt sound. Listening can also be toggled under "语音与音乐互动" (Voice and music interaction) in the web console. Once turned on, you can say several sentences in a row; each is processed after you pause.

This is local recognition of explicit commands: no cloud is needed and recordings are not uploaded; negated, mixed-action or low-confidence commands should not be executed. First complete normal calibration and the standing preparation; when the current posture does not allow it, follow the original recovery flow. In music mode, sit/stand commands are not executed; exit music mode first. During an update, voice actions are blocked; after the update finishes, turn listening on again the usual way.

By default actions are confirmed with a quack, and ordinary speech is not automatically repeated back. Free-form AI voice conversation is not yet integrated; the user's chosen requirement of "spoken answers + text in the web console" is kept separately, and the current text model configuration must not be treated as a completed microphone conversation.

## How the software package and image relate

The everyday upgrade package only contains the web console/backend, the matching helper and the voice program; the fixed upgrade executor and model resources live outside the version directory. Changing the gait model, runtime, kernel or bootloader involves different installation conditions and cannot reuse this release's web console update flow. The physical effect of following the music beat still awaits a fix per the original record; this release does not mark it as solved.

The new image ships with the same signed package, resource checksum manifest and version provenance; upgrading old cards and installing new cards use the same set of components. The current updater does not install automatically in the background or switch versions on its own; the user triggers it in the web console.

## For maintainers to keep

The release private key is only in a private directory on the build machine; the source code and image contain only the release public key. Keep the private key separately; the public key cannot be used to sign new versions. Update packages must be generated from a frozen Git commit, keeping the package hash, source commit, image hash, rollback tests and actual acceptance check records; a personal SD card under development must not be used as a public image.
