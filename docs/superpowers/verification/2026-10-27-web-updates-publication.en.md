# 20261027 image and software package public release

**English** · [简体中文](2026-10-27-web-updates-publication.md)

Date: 2026-10-27 (JST). After the local delivery and the IMU code review, the user explicitly asked to "push it, use the latest, and make an image." This authorization covers pushing the source and publishing the corresponding software package and image; it does not authorize flashing a card or making the powered-off duck move.

**Public release complete: the source has been pushed to master, image 20261027 is set as Latest, and software 2026.10.27 is released separately; the server-side sizes/SHA256 of the 8 image attachments and 10 software attachments all match. The actual anonymous update catalog, software package download/signatures, and the image checksum file/XZ file header checks passed. Both Releases are draft=false, prerelease=false; physical acceptance of this version is still pending.**

## Versions and sources

- Source integration push: `762b0d44b784104aeb73c7b6bad10a25713daa44`, keeping 16 new remote documentation commits; only README had a conflict, where the latest project introduction was kept and the new software entry added.
- Software/image runtime source: `e382f0741d7dfe4e972605e2843474df7219cade`. The Studio, duck-echo, updater and image install scripts in the release tree match this commit path by path, so there is no need to rebuild an image with the same content.
- Both release tags are annotated tags that dereference to e382f074; later documentation commits are not passed off as the image build source.
- The runtime source `0791fcd44f71c705dc8bb0fbcde405593b52d19b` was confirmed publicly present via the GitHub commit API, and robotd/gait model/bus ID200 IMU support stay at the 20261023c version.
- The previously local training recipe changes did not go into this public release tree; `software/training` and `software/training-studio` are identical to origin/master before the release. The original local branches and the user's untracked documents were kept.

## Release entries and files

| Release | Entry | Attachments and checks |
| --- | --- | --- |
| Image 20261027 | [Image release page](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) | 8: xz, SHA256, manifest, license, model, third-party, voice notes and README; all server-side digests match, and Latest reads back correctly. |
| Software 2026.10.27 | [Software release page](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) | 10: signed software package/checksum, manifest/signature, first-time bootstrap package/checksum, public key, Apache license, voice notes and README; all server-side digests match. |

| Core artifact | Bytes | SHA256 |
| --- | --- | --- |
| `microduck-replica-20261027.img.xz` | 741604104 | `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194` |
| `2026.10.27.software-update.tar` | 5683200 | `b6543c9f3a2ad6477106410dbed9753be9fa37c61b79ea0350767a18229d0e55` |
| `microduck-bootstrap-20261027.tar.gz` | 57811043 | `866f8d49e3097133ab911debda9c4fdc66b9f02b867a789aadfb9793b99b3610` |

All assets were uploaded explicitly one by one, without workspace wildcards. The release private key is not among the attachments; Git contains only the release public key. The Chinese voice notes file was automatically normalized by GitHub to default.txt, so during the draft stage its content hash was checked and it was renamed to the explicit ASCII file name `microduck-software-20261027-voice.txt`, then verified again before publishing.

## Release checks

- The local delivery files were re-checked for size/hash, inner and outer package signatures, and the 319 manifest files of the bootstrap archive; passed.
- The original complete local verification and independent review are in [build verification](2026-10-27-web-updates.en.md). The release merge changed only documentation; the runtime files match the accepted frozen source. After the merge, the 18 Linux updater items and the 5 Studio update HTTP items were run again, all passing.
- The GitHub tag targets of both releases, and the uploaded state, size and SHA256 of the 10 software attachments, were checked item by item and passed. Draft asset URLs contain a temporary untagged path, so the stable tag download URLs were checked only after the official public release.
- All 18 attachments and both tag sources passed, and Latest points to image 20261027; the anonymous catalog client of the actually released code correctly distinguishes image from software, recognizes 2026.10.27 and downloads the 5,683,200-byte software package, with the hash and both minisign signatures passing. The public image SHA256 file matches the local one, and a Range read returns the correct XZ file header.
- The public acceptance snapshot is in [release-assets.json](2026-10-27-release-assets.json). Image integrity is verified jointly by an independent extraction/per-file read-only acceptance and GitHub's server-side full-file digests; physical acceptance is recorded separately.

Evidence is in the workspace `artifacts/software-updates-20261027`: publication-assets.json, the staged draft/public publication-verification.json, and the release notes files. The original delivery.json's local_only=true is kept as the history of the first local delivery and does not overwrite this public state.

## Physical boundaries

The duck was off; this round had no SSH installation, card flashing, robot motion or cloud requests. Old-card first-time bootstrap/upgrade/rollback, first use of a new card, real power loss and real-person acoustics still await acceptance; the release page titles and bodies state this explicitly. The software release is not applied automatically by default, and the image and the component package are identified separately.

Actual head/body movement to music is not yet fixed, and free-form AI voice conversation is not connected; the earlier physical sit/stand/recording-playback success cannot substitute for the physical acceptance of this combined image. The first paragraph of the release notes keeps the boundaries of the free, personal, non-commercial replica and the model license.
