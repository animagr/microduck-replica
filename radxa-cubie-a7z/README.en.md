# Radxa Cubie A7Z port (preview)

**English** · [简体中文](README.md)

This directory provides the source for Wi-Fi provisioning, control, Studio, thermal management and full-system image preparation for the **Radxa Cubie A7Z + Feetech HD-1910 servo/bus IMU assembly**. The main repo's default image still targets the Zero 3W; the A7Z uses its own image and hardware port.

[Download the A7Z preview1 historical image and checksum attachments](https://github.com/Liangjin5437/microduck-replica/releases/tag/a7z-duck-image-20261109-preview1) · [Image flashing, first use and build instructions](image/README.md) · [Maintenance branch source](https://github.com/Liangjin5437/microduck-replica/tree/codex/cubie-a7z-preview/radxa-cubie-a7z)

The release's `cubie-a7z-duck-20261109-preview1.img.xz` is a historical preview published before the fixes. The read-only installer, image directory permission and Wi-Fi provisioning fixes in the current source still need to be repackaged and verified on real hardware. The historical image has records of its file structure, digests, file system and compression checks, but the acceptance checks after flashing (real hardware boot, networking, full actions and sound) have not been completed. The existing intermittent bus read failures are still being investigated.

## Source directories

- `provision/`: standalone hotspot provisioning service, install script and decision tests; the provisioning page uses port 80, and Studio uses port 8000.
- [control/](control/README.md): A7Z UART and grouped sync read adaptation, pinned-version runtime patches, read-only install/monitoring tools, diagnostics and tests.
- [studio/](studio/README.md): A7Z Studio patches, install tools and tracking/debugging source; [console-integration/](studio/console-integration/README.md) contains the changed web console frontend files, packaging and installer, and the verification record.
- [thermal/](thermal/README.md): thermal policy, systemd service and tests.
- [image/](image/README.md): new-assembly configuration, first boot, cleanup and image preparation/build tools, plus local contract tests.

The source does not include a complete system image, external upstream checkouts, model/runtime install archives, a complete Python distribution or local runtime state. Downloads are in the release attachments; `artifacts/`, `workspace/` and the board-side `evidence/` are not committed as PR source.

## Maintainer rebuild boundaries

These tools record the build steps and pinned digests of this image, but a plain source checkout cannot rebuild it completely with one command. You also need the official A7Z base system, the pinned R17 action/sound/inference library archives, the A7Z `robotd`, the standalone Python install archive for Studio and the Studio source at a pinned commit; the exact names, commits, SHA256 values, tool versions and default directory layout are in the [image notes](image/README.md). Some scripts still use default paths to neighboring external projects from the original build layout; check the actual inputs before rebuilding, and do not substitute unknown versions and skip the digest checks.

`BOARD_IP` and `cubie-XXXX` in the docs are placeholders for the board's LAN address and device name; replace them with the actual values. `10.42.0.1` is the fixed address of the provisioning hotspot.

## Usage and verification scope

The image boots for the first time in the new-assembly commissioning calibration mode and does not carry over the original device's motion authorization; first complete servo and IMU calibration on this robot, and then have an on-site operator verify the range of motion and the actions. The camera, ToF, physical gamepad, continuous voice and joint tracking backend are not enabled in this image.

Each subdirectory keeps the actual scope of its source tests, installation and browser verification, along with the pending acceptance items. For web console frontend verification see [console-integration/VERIFICATION.md](studio/console-integration/VERIFICATION.md), and for image build checks see [image/README.md](image/README.md); these records do not replace real hardware boot, bus stability and motion acceptance checks for this image.
