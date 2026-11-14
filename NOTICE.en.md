# Attribution and Sources

**English** · [简体中文](NOTICE.md)

This repo is a **third-party replica research project of Microduck**. It is not affiliated with or endorsed by Pollen Robotics.

## Upstream sources

| Source | Author | License |
|---|---|---|
| [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl) | Pollen Robotics | Code Apache-2.0; **3D models CC BY-NC-SA** (the upstream README writes it as "BY-SA-NC") |
| [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) | Pollen Robotics | Apache-2.0 |
| 1910 M6 parameters and matching configuration reference from [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | LuwuDynamics | Apache-2.0 |
| [Rhoban/BAM](https://github.com/Rhoban/bam) actuator model and identification library (training dependency) | Rhoban | Apache-2.0 |

Microduck is a commercial product of Pollen Robotics, and its hardware is **partially open source**:

- **The RPI Robot HAT board has been fully open-sourced by Pollen** ([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Apache-2.0, including the KiCad project and production files)
- **The `imu_to_dxl` board, the editable CAD of the mechanical parts, the full-robot BOM and the assembly documentation** have not been published

All geometric information in this repo comes from the **MJCF simulation model and STL meshes** publicly
released in the upstream `microduck_rl` repo; conclusions about the electronics come from the source code, device tree and configuration files in the `microduck` repo.

> Erratum (2026-09-03): this file previously said "its hardware is not open source". That was wrong: the HAT board is open source.

## Derived content in this repo

The following content was generated or compiled by this project from the MJCF + STL publicly released upstream. It is a **derivative work under CC BY-NC-SA**
and is therefore released under the same license:

| Path | Content | Relation to upstream |
|---|---|---|
| `assembly-drawings/` | All renders and exploded views | Rendered from upstream MJCF + STL |
| 3D meshes in `software/training/` | Simulation geometry used for training | Upstream model source and license kept; not meant as files for physical printing |
| `tools/servo-web/model/` | Display model for the web debugging tool | Converted from upstream MJCF / STL; not the latest physical CAD |
| `software/studio/web/model/` | The 3D duck in the Studio web console | Converted from the upstream simulation model, outer shape only; not the latest physical CAD |
| `docs/hole_analysis.json` | Hole position geometry analysis data | Computed from upstream STL |

> **Model download migration (2026-09-28)**: `print/` and `cad/` now contain pointer notes to the [CAD repo](https://github.com/fanhao375/microduck-replica-cad). The old individual-part STLs, assembly STLs and cross-reference tables have been removed from the current version so they are not mistaken for the latest printed parts. The old models in Git history remain derivative works of the upstream STLs (renamed, categorized or assembly-transformed) and remain under CC BY-NC-SA; removing the download copies does not change the authorship or license of the historical files.

**Original content of this project:**

| Path | Content | License |
|---|---|---|
| `scripts/` | Scripts for rendering, export, hole position analysis, etc. | **Apache-2.0** |
| `tools/stl_viewer.html` | Zero-dependency WebGL STL viewer | **Apache-2.0** |
| Code in `software/studio/` | Microduck Studio web console (excluding `web/vendor/`, `deps/`, `web/model/`) | **Apache-2.0** |
| `software/image/` | Build scripts, first-boot and network setup scripts for the replica system image | **Apache-2.0** |
| `software/updater/` | Signed component bundle build, adaptation of the original update engine, web upgrade coordination and first-boot bootstrap tool | **Apache-2.0**; the original updaterd comes from Pollen Robotics, source 1fa8438 |
| Code in `software/duck-echo/` | Local R3 voice, recording and music interaction; does not include the build machine's private key or user recordings | **Apache-2.0**; the external Vosk model and ARM64 dependencies are under their own licenses, and the manifest keeps their sources and hashes |
| `docs/*.md`, `*.md` | All documentation and reverse-engineering analysis text | **CC BY-NC-SA 4.0** |
| `build-log/` photos | Photos of the physical build | **CC BY-NC-SA 4.0**, taken and licensed by project participants |
| Original project assets in `assets/` | Cover, community group QR code and project preview images; excludes the official board images below | Same as above |

## Official board images

The following two images are used as is and keep their own authors and original licenses; they are not covered by the CC BY-NC-SA license of this project's documentation or original assets:

| Path | Source and author | License |
|---|---|---|
| `assets/hw/radxa-zero3w-official.webp` | [Radxa ZERO 3 official documentation](https://docs.radxa.com/en/zero/zero3), Radxa Computer (Shenzhen) Co., Ltd. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `assets/hw/rpi-robot-hat-official.png` | [Pollen Robotics official HAT repo](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Pollen Robotics | [Apache-2.0](https://github.com/pollen-robotics/elec_RPI_Robot_HAT/blob/main/LICENSE) |

For the original image URLs, pinned versions and checksums, see the [image source record](assets/hw/official-board-images.en.md).

## Bundled training project

[`software/training/`](software/training/) contains the complete training project, so replica builders get
the code, parameters and simulation models in one download. For the pinned import version and scope of changes, see [UPSTREAM.md](software/training/UPSTREAM.en.md).

- Pollen Robotics' training code, tools and original documentation remain **Apache-2.0**; the HD1910
  tasks, initialization adaptations, tests and notes added in this directory are also Apache-2.0. The full license text is in
  [`software/training/LICENSE`](software/training/LICENSE).
- **The 3D models and meshes in the training directory keep the upstream CC BY-NC-SA notice** and are not covered by the code's Apache license.
- LuwuDynamics' `1910_m6.json` is kept unchanged; its pinned source, checksum and a copy of its license are in
  [`software/training/src/mjlab_microduck/robot/hd1910/`](software/training/src/mjlab_microduck/robot/hd1910/).
  This project did not identify these parameters itself; policies trained with it in the future will still keep the parameter attribution.
- Rhoban/BAM is installed as a version-pinned dependency, keeping its source and license.

The CC BY-NC-SA license for this project's documentation in the table above does not cover the Apache documentation in the training directory.

## Other third-party software

**Third-party software redistributed unchanged:**

| Path | Content | Source | License |
|---|---|---|---|
| `tools/飞特/` | Feetech FD debugging software 1.9.8.5 + CH340 driver | [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug), copied 2026-09-11 | **MIT** (FTServo 2024, LICENSE in the same directory) |
| `tools/rufus/` | Rufus 4.15 Windows x64 portable edition and source code of the same version | [pbatard/rufus v4.15](https://github.com/pbatard/rufus/releases/tag/v4.15), downloaded unchanged on 2026-10-25 | **GPL-3.0-or-later**; the license, source archive, checksums and source record are in that directory |
| `software/studio/web/vendor/` | Studio frontend libraries: Preact, htm 3.1.1, three.js 0.160.0 | Respective official releases | Preact, three.js **MIT**, htm **Apache-2.0** (licenses in `web/vendor/licenses/`) |
| `software/studio/deps/` | Studio's Python dependencies (anyio, click, h11, idna, pyserial, sniffio, starlette, typing_extensions, uvicorn, wsproto) | Original wheels from pypi.org; versions and checksums in `deps/VERSIONS.txt` | MIT / BSD-3-Clause / PSF-2.0, etc.; each package's license is in its own `*.dist-info` |

> Upstream source snippets quoted in the documentation (comments, constants, register definitions) come from `pollen-robotics/microduck`
> and follow its **Apache-2.0** license; the file path is noted wherever they are quoted.

## Companion repo: SolidWorks 3D drawings

[**fanhao375/microduck-replica-cad**](https://github.com/fanhao375/microduck-replica-cad)
maintains the editable SolidWorks / STEP files, print files and the 21-page assembly and installation manual in one place. Feetech and XL330 versions are provided separately, and the file list is defined by the corresponding release of that repo; the main repo no longer maintains its own separate copy of the print models.

| Content | Author | License |
|---|---|---|
| SolidWorks drawings, assembly and installation manual, component drawings | **机械行者Robo** (Xiaohongshu 270594280 / Douyin 1852366168) | **CC BY-NC-SA 4.0** |

Those drawings are **editable parametric models rebuilt from the STL meshes published upstream**. They are derivative works under CC BY-NC-SA
and are therefore released under the same license. **The copyright belongs to the author**; please keep the attribution when reposting or redistributing.
The drawings live in a separate repo instead of being merged into this one because the SolidWorks source files are about 340 MB when unpacked,
and merging them would make every clone of this repo carry that size.

## About the license name

The canonical name is **CC BY-NC-SA 4.0** (Attribution - NonCommercial - ShareAlike).
The upstream README writes it as "BY-SA-NC"; where this repo follows that spelling, it refers to the same license.

> Note: the `LICENSE` file of the upstream `microduck_rl` repo itself contains only Apache-2.0;
> **the CC terms appear only in one line of its README**. This repo applies the stricter CC BY-NC-SA to the 3D models
> as a conservative choice; if upstream clarifies that they are pure Apache-2.0, this repo will relax accordingly.

## Compliance statement

All conclusions in this repo come from:

- **Source code and device trees** publicly released by Pollen Robotics (`pollen-robotics/microduck`, Apache-2.0)
- Publicly released **simulation models and meshes** (`pollen-robotics/microduck_rl`)
- The publicly released **KiCad project** (`pollen-robotics/elec_RPI_Robot_HAT`, Apache-2.0)
- The **1910 M6 parameters and matching configuration** publicly released by LuwuDynamics (`LuwuDynamics/xgoduck_rl`, Apache-2.0)
- Component manuals and specification pages published by the vendors

**No non-public material was used, no physical unit was disassembled, and no unpublished design files were ever accessed.**
The firmware of the `imu_to_dxl` board is not in any open-source repo; this repo only reproduces its observable behavior on the bus side.

## Non-commercial notice

The upstream 3D models are licensed under **CC BY-NC-SA**, and derivative works **may not be used for commercial purposes**.
This repo is for learning, research and personal replica builds only.

## How to attribute

> Based on the Microduck model by Pollen Robotics (CC BY-NC-SA)
> https://github.com/pollen-robotics/microduck_rl
