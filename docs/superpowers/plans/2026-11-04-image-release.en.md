# 20261104 IMU and network-setup image release plan

**English** · [简体中文](2026-11-04-image-release.md)

> **For agentic workers:** Execute with executing-plans; native integration, the update manifest audit and the image input audit can run independently in parallel, while release and verification stay sequential.

**Goal:** Deliver a new system image and a matching signed software package containing standing-pose IMU recalibration, independent ID200 orientation verification, hotspot recovery and the existing features of 31-r1, with an update manifest that can be checked.

**Architecture:** Studio uses 1855a68 as the baseline and adds the independent hotspot patch 2fa4ec9; native uses the public 27d7921 source tree as the baseline and integrates today's 5 IMU commits, keeping Qinmo, independent servo/IMU status and the gamepad mapping. Pin the source/hash/API43 of the new main program and package it as a set with the previously verified mapping padd. Reuse the verified Armbian base image, model payload, voice resources and ARM upgrade executor, and build a factory-clean image from frozen Git sources.

**Tech Stack:** Rust1.99, Python3.12/3.13, WSL Ubuntu22.04, QEMU ARM64, minisign, ext4 image tools, GitHub CLI.

- [x] Review today's inventory of source/real-hardware/experimental items and the scope of old public features to keep; record it in artifacts/image-release-20261104/change-inventory.txt.
- [x] Native isolated worktree `.worktrees/native-image-release-20261104`: on top of public 27d7921, integrate 82aec98, 3f0dc0a, cdebd43, 0d0e3e0, 7036345; when resolving conflicts keep the existing Qinmo and independent status logic, and use API43 and the control.48 build identifier. First run the public baseline, then run the same tests after merging; build ARM64 and record the exact source and hashes.
- [x] Studio release worktree `.worktrees/image-release-20261104`: add 2fa4ec9, update the native source/API/hash/size in `software/studio/deploy/native_update.py` and `controller_bundle.py`, and keep the released padd mapping. Add and run regressions for consistency of the bundle declaration, upgradability from the old .47, and rejection of bad payloads.
- [x] Run the Studio, network setup, image, voice and updater suites; distinguish failures by name against the old public baseline, and do not record pre-existing failures as passes.
- [x] Export LF sources from frozen Git and sign the 2026.11.4 software package with the existing release private key. The private key is not copied into the sources, image or attachments. Verify installation/rollback on the old 27 engine and the new native bundle metadata.
- [x] Build `/root/microduck-build-20261104/` from the verified base image/payload/updaterd/resources in `/root/microduck-build-20261027/inputs/`. In the payload, update robotd and the verified padd, output the legacy protocol by default, and do not enable the experimental full_q4_v1 by default. Factory calibration remains uncalibrated with the default calibration mode; remove Wi-Fi, the maintainer's SSH keys, and personal API keys/music/actions/logs.
- [x] Check file hashes, partitions/ext4, startup services, first-boot cleanup, default configuration and dependencies of the final image; verify the compressed file and release attachments, and do not call offline checks a real flash-the-card test.
- [x] After independent review, push the exact sources and create the matching GitHub release, uploading the image/signed software/checksums/update manifest/license and provenance records; mark it as a beta, noting that the flash acceptance check of the new image and motion performance still await on-site verification.
- [x] Read back the sizes/hashes and accessible download links of the public GitHub attachments, and deliver a Chinese update summary, download addresses and the upgrade method for old cards.

Scope boundaries: do not change the model currently on the user's robot, the zero positions, saved IMU orientation or action parameters; a fixed mounting-orientation preset is left for later. The experimental MCU1.1 full quaternion and 1.2 compensation must not be flashed into the image by default, nor claimed to have fixed walking/standing up; the new image does not preinstall the maintainer's personal calibration and network data.
