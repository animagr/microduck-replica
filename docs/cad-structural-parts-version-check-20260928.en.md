# Main Repo Structural Parts vs CAD Version Check (2026-09-28)

**English** · [简体中文](CAD结构件版本核对-20260928.md)

**Conclusion of the check: they were not fully aligned before.** The main repo's print STLs, assembly previews and training geometry come from the upstream XL330 model; the CAD repo has released Feetech v2.1. The old files cannot be used directly as print exports of the latest Feetech CAD.

**Resolution as confirmed by the user: models now point directly to the companion CAD repo.** The main repo has removed the 45 old individual-part STLs in `print/`, the 16 assembly STLs in `cad/` and the old cross-reference table; these two directories now serve as download entry points, and the Chinese and English home pages, BOM, purchasing notes and attribution have been updated accordingly. The old files can be traced in Git history, and future versions of the models are maintained in [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).

The CAD repo's notes were corrected at the same time: the XL330 print entry no longer jumps back to the main repo's old STLs and now points to the v1.1 source files in that repo; the version boundary between the 09-15 3MF and the old BOM is also marked. This round only changed that repo's README and did not update the CAD, 3MF or workbook.

This round did not re-export or re-arrange the CAD / 3MF, and did not replace the training or web models or the physical parameters. The analysis export script writes by default to the ignored `analysis-output/cad-upstream/`, to avoid regenerating a set of main-repo download files. The check evidence from before the changes is kept below and was reviewed by an independent agent.

## Check baseline

| Item | Version / result |
|---|---|
| Main repo remote `fanhao375/microduck-replica` | `a23f4c18a4741a3cde5257e639960ea37bbadd8d` |
| CAD remote `fanhao375/microduck-replica-cad` | `749fcefb404a0750777d7cc8badfe30700df2f9b` |
| Latest Feetech release | [v2.1, 2026-09-25](https://github.com/fanhao375/microduck-replica-cad/releases/tag/v2.1) |
| Latest XL330 release | [v1.1, 2026-09-15](https://github.com/fanhao375/microduck-replica-cad/releases/tag/v1.1) |
| Local CAD working directory at the start of the check | `1623d34`; the check used the fetched remote `749fcefb`. Before the later README fixes, it was fast-forwarded to that remote version |

The independent review compared the Git blobs of all 65 files in the main repo's `print/` and `cad/` one by one, and local matched the main repo remote. So the differences below are not just a matter of the local copy being out of date; they also exist in the online version of the main repo.

## What was not in sync

| Content | Status before changes | Actual impact |
|---|---|---|
| [Old main-repo printed parts](https://github.com/fanhao375/microduck-replica/tree/a23f4c18a4741a3cde5257e639960ea37bbadd8d/print) | The SHA256 of all 30 walking STLs match the local upstream `microduck_rl` original meshes, and also the corresponding meshes in the main repo's training directory | Not replaced with the Feetech CAD modified parts; cannot be used as "the latest full set of Feetech printed parts" |
| [Old main-repo assembly previews](https://github.com/fanhao375/microduck-replica/tree/a23f4c18a4741a3cde5257e639960ea37bbadd8d/cad) | 15 component STLs + 1 full-robot STL, exported from upstream MJCF/mesh transforms; the [generator script](../scripts/export_assembly_stl.py) reads `robot_allcollisions.xml` | An assembly preview of the upstream model, not an export of the new SolidWorks assembly |
| [Main repo home page](../README.md) / [CAD directory notes](../cad/README.md) | The Chinese and English home pages still pointed to Feetech v2.0; the CAD directory notes still listed XL330 as v1.0 | Download entry points and version notes out of date |
| CAD repo 3MF | Still the original ~4.9 MB project released on 09-15; the v2.1 commit only changed the README, not the 3MF | Already contains some Feetech STEP modified parts, but not this v2.1's combined tire |
| [Training meshes](../software/training/src/mjlab_microduck/robot/microduck/assets/) | Keeps the original Microduck geometry; the [HD1910 notes](../software/training/src/mjlab_microduck/robot/hd1910/README.md) explicitly keep the local geometry and joint conventions | Plugging in the Feetech servo model parameters is not the same as plugging in the new physical structure; mass and inertia also need to be checked separately |
| [Web debugging model](../tools/servo-web/model/model.json) | Source still labeled `apirrone/microduck_rl robot_allcollisions.xml`, contains XL330 meshes; the masses in the notes come from the official model | Can be used for the existing debugging display, but its appearance and center of mass cannot be considered calibrated against the latest Feetech CAD |

## Confirmed geometric differences

The table below compares the main repo's individual-part STLs with the corresponding STEP-sourced meshes in the CAD repo's existing 3MF; the metric (meter) coordinates of the old STLs were first converted to millimeters. The independent review confirmed that all listed meshes are closed, valid volumes; these differences show it is not merely a rename or a different export format.

| Part | Main repo STL | Corresponding part in the CAD repo's existing 3MF |
|---|---|---|
| Upper leg rigidity plate | 1 mm thick, volume about 747.79 mm³ | 2 mm thick, volume about 1678.08 mm³ |
| `bearing_roll` roll bearing cap | 3 mm thick, volume about 625.28 mm³ | 3.5 mm thick, volume about 929.25 mm³ |
| Left ankle | Volume about 7877.82 mm³ | Volume about 6349.67 mm³ |
| Right ankle | Volume about 7877.81 mm³ | Volume about 6188.97 mm³ |

This is a direct comparison of **the main repo STLs with the existing 3MF**; it does not claim to be a result of re-exporting from all the v2.1 SolidWorks source files in this round. The Feetech version's left and right upper legs, lower legs, yaw2roll and others also have CAD change records and STEP sources, and a version mapping should be built for all of them rather than judging by file name alone.

## Two more things to keep apart between v2.1 and the print package

1. **The combined tire belongs to the roller-skating variant.** The v2.1 release notes say the separate `rim` and `tire` were merged into a TPU combined tire; this cannot be taken to mean that every part of the walking robot was changed on 09-25.
2. **The CAD repo 3MF has not caught up with this change.** The Git blob of both the remote and local 3MF is `796b092c754e8c7041a4ca5495d01757c56c5266`; `Metadata/model_settings.config` still has 4 rims and 4 tires and no combined tire. This 3MF cannot be called a complete v2.1 print package. This round did not separately verify whether the MakerWorld online project has been updated.

In addition, the v2.1 10-part STEP package was downloaded and verified: its SHA256 is `57dd4a2a191bedbf01a4916bc4df34bba6c175793b532ebecc7a1e1aed8c2ca0`, matching the GitHub attachment digest. Compared file by file with the v2.0 9-part package:

- **7 parts with identical content**: rigidity plate, `99-yaw_roll_motion`, bearing cap, left and right upper legs, Feetech lower leg, `yaw2roll`.
- **3 new files**: Feetech left ankle, right ankle, combined tire.
- **2 parts no longer in the package**: the lower leg without the `-FT` suffix and `trunk_base_躯干底座-FT.STEP`.

So "9 STEPs plus a tire" does not fully describe the change in attachments; the missing trunk base STEP should not be understood as that physical part having been dropped. This round did not open and verify each reference in the complete SolidWorks v2.1 assembly; this should be checked during later exports.

## Things to check when the models are actually modified later

This time the user chose to consolidate maintenance in the CAD repo and not create a separate print package in the main repo. If the CAD repo or the training models are updated later, the following still need to be checked:

1. Clearly distinguish the XL330 and Feetech versions in the CAD repo to avoid mixing mating parts for the two servo types; the main repo keeps the link entry points.
2. Build a part mapping based on the full set of CAD v2.1 source files; first check the walking ankles, lower legs, rigidity plates, bearing caps, left and right upper legs and trunk mounting parts, then handle the roller-skating combined tire separately.
3. Export STLs from the confirmed CAD and check units, left/right parts, hole positions and quantities, then update the 3MF, BOM and download entry points. Simply renaming the old STLs or changing the links to v2.1 does not count as done.
4. Finally update the assembly previews and the web model; on the training side, separately calibrate joint frames, collision bodies, mass/center of mass/inertia, and only train after the model check is complete; do not simply overwrite with the print meshes.

The original check files are saved in the local temporary directory `microduck-cad-audit-20260928`, including release metadata, the main repo STL hash match table and the file-by-file comparison of the two STEP packages.
