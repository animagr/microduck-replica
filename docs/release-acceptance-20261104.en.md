# Acceptance check of the 20261104 test image and the 2026.11.4 software package

**English** · [简体中文](发布验收-20261104.md)

The image and the signed package use source `f215b658a4f24b669cf664b6381a559c61472009`; this document records the scope of their build, automated and delivery checks.

## Downloads and sources

- [20261104 full test image](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261104)
- [2026.11.4 companion software test release](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.11.4)
- [User update checklist](更新说明-20261104.md), [companion driver update procedure for old cards](native-update-20261104.md)
- Native main program commit `eecac1878136d3188370a5f6460b7d0521cf845d` ([release build record](https://github.com/fanhao375/microduck-replica/releases/download/microduck-replica-image-20261104/runtime-provenance.json))

| Attachment | Bytes | SHA256 |
| --- | ---: | --- |
| `microduck-replica-20261104.img.xz` | 755670732 | `f9970ec551bcddbeeae9748b0ce38f36450fa1497618c07920723849f975aa78` |
| `2026.11.4.software-update.tar` | 9676800 | `b6e8d90896fd1aaeb4a6288e226ba7228a1fe7d738a79c9dcde7407dfadad211` |

The main program is `replica-imu-verify-control.48` / API 43, SHA256 `e5ff7fb429fd0dfb762eb4da1bcc5a26b48b6d2dfdae4bb4904213e37e022ed0`. The already released mapping gamepad program is kept, SHA256 `dc1c7043a108964583fc09a11e3d6f87a25e259c346f7ce9154e77500a0881ec`; its historical source is `665613a`, and the public native tree of this release keeps the equivalent padd subtree `4fd36a1eafa1aa0f66ecc4ad8d8cf38a3a4a286d`.

The build uses the verified Oct 27 base image, model payload, ARM update executor and 304 voice resources, exports Linux LF source from a frozen Git tree, and the signed package, image components and main program match exactly. The provenance manifest and model attributions are kept. The release private key does not go into the image or the attachments.

## Automated results

| Scope | Result |
| --- | --- |
| Studio | 1525 tests, 97 skipped due to browser/platform environment, the rest passed |
| Image build and cleanup | 157 tests passed |
| Updater | 35 tests passed |
| Voice | 173 tests passed |
| Signed publisher | 17 tests passed |
| Companion driver recovery, old .47 / new .48 | 24 interruption points each passed |
| ARM64 | Frozen source compiles; dynamic dependencies and `robotd --help` inside the delivered image pass |

Between the tested commit and the frozen commit, the corresponding Git subtrees for Studio, the updater and voice are identical; the image tests include the final provenance manifest regression. The full regression does not treat browser skips as an acceptance check on real hardware. The native delegated acceptance, startup, full quaternion, parameter and read-only diagnostics suites passed.

The extended native suite still has the following failures, reproducible on the public baseline, which are not recorded as passing:

- `nonfive_model_contract_p_is_used_with_fixed_d_and_limit`: public baseline 91 passed / 1 failed, after merging 100 passed / the same test failed.
- `lazy_bus_rpc` and `acquisition_counts` in `raw_stream`: baseline 6 passed / 2 failed, after merging 7 passed / the same 2 failed.

The release attachments `validation-report.json` and `runtime-provenance.json` provide structured records.

## GitHub delivery read-back

On 2026-11-04 two prereleases were published: the image with 13 attachments and the software package with 15 attachments. The size and SHA256 of every attachment returned by GitHub match the local delivery manifest; both release pages and their main attachments passed a public HTTP 200 check, and both tags point to the frozen commit `f215b65`.

GitHub rewrites Chinese attachment names, so the update checklist uses `update-summary.txt`; the README, release notes and `SHA256SUMS.txt` have been made consistent. `microduck-replica-image-20261027` is kept as the latest stable image.

## Final image re-check

The actually delivered `.img.xz` passed compression integrity and SHA256 checks, was decompressed again, mounted read-only, and checked for:

- Hashes of the signed runtime files, native program, gamepad, service configuration, trusted public key and all voice resources.
- Factory calibration not done, model motion not enabled, default legacy small-board compatible format, I²C and the experimental full quaternion not forcibly enabled.
- First boot, network setup, web and voice services enabled, with the hotspot scripts matching the frozen source.
- No leftover maintainer Wi-Fi configuration, SSH identity/history, personal calibration, API Key, actions or update transactions.
- Licenses and model notes complete; the old model export instructions removed according to the build rules.
- `e2fsck -f -n` passes, and the read-only mount and loop used for checking have been cleaned up.

See the image release attachment `microduck-replica-20261104-verification.json` for the detailed items.

## Real-hardware boundaries

This release is a **prerelease test version**, and the latest tag stays on the 20261027 stable image. Flashing and booting a new card from scratch, actual hotspot recovery after changing Wi-Fi, real orientation sampling and the motion acceptance check have not been done. Walking, rolling over and getting up after a fall still have to be compared on site; passing offline checks cannot be used to claim they are solved.

The full quaternion requires explicitly matching small-board firmware; the image does not flash the MCU automatically, does not enable the 1.1 experimental path or the 1.2 compensation by default, and does not include a personal fixed mounting orientation. The hotspot patch comes with the full image; uploading `.software-update.tar` does not update the system network setup scripts on old cards.
