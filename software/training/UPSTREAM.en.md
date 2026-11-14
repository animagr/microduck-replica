# Training project sources and maintenance location

**English** · [简体中文](UPSTREAM.md)

This directory is a plain source directory that is cloned and downloaded together with `microduck-replica`; it is not a Git submodule.
Further HD1910 training work is maintained here; the HD1910 branch of the original `fanhao375/microduck_rl` is kept as a historical source.

## Imported version

On 2026-09-24, a complete snapshot of the tracked source was imported from the following pinned version:

- Source: [fanhao375/microduck_rl @ d9e1926](https://github.com/fanhao375/microduck_rl/tree/d9e1926c5220a0eb79fa5aab9df7b336f8e9a226)
- Full commit: `d9e1926c5220a0eb79fa5aab9df7b336f8e9a226`
- Pollen Robotics upstream baseline: `d424a0c899f6b33cbd3daeb279913134349c0b63`; on top of it, the HD1910 tasks, M6 parameter reference, initialization adaptation and tests were added.
- Import method: a `git archive` source snapshot of that commit; it does not include `.git`, virtual environments, training logs or checkpoints.
- The original README is kept verbatim as [README.upstream.md](README.upstream.md). The migration adjusted the docs and entry links in this directory,
  and fixed the HF Jobs packaging root so that the archive contains only the training project; a local packaging regression test was added.
  The training/actuator logic, dependency lock file, configuration, existing tests and geometry assets keep the content of that version.

The Microduck geometry, mass/inertia and joint conventions in this snapshot come from the training project and do not mean that measurements of the Feetech replica hardware have been completed.

## Authors and licenses

| Content | Source | License |
|---|---|---|
| Training framework, existing tasks, tools and docs | [Pollen Robotics / microduck_rl](https://github.com/pollen-robotics/microduck_rl) | [Apache-2.0](LICENSE) |
| Microduck 3D models and meshes | Same as above | The CC BY-SA-NC notice in the upstream README; this repo keeps the attribution, non-commercial and share-alike terms as CC BY-NC-SA 4.0, see [NOTICE](../../NOTICE.en.md) |
| `1910_m6.json` servo dynamics parameters and accompanying configuration reference | [LuwuDynamics / xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | [Copy of Apache-2.0](src/mjlab_microduck/robot/hd1910/LICENSE) |
| BAM actuator model and identification library (installed as a dependency) | [Rhoban / BAM](https://github.com/Rhoban/bam) | Apache-2.0; the lock file pins `62bd8ce12154340be97e06f7f41a0ca8f116d967` |
| HD1910 tasks, state-initialization adaptation, corresponding tests and docs added in this directory | This replica project | Apache-2.0 |

The root directory's CC license for this project's other docs does not cover the Apache-licensed docs in this training directory; the 3D model license is kept separately.
Dependencies continue to follow their own licenses.

## Original source of the parameters

- LuwuDynamics pinned commit: `326d77a1122870bdefa2c36403937502c958e69c`
- Original path: `src/mjlab_microduck/robot/xgoduck/params/1910_m6.json`
- Path in this directory: [`src/mjlab_microduck/robot/hd1910/1910_m6.json`](src/mjlab_microduck/robot/hd1910/1910_m6.json)
- SHA-256 of the original file: `ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb`

The parameters are kept as in the original file and were not identified by this project. For detailed references and configuration boundaries see
[Parameter source](src/mjlab_microduck/robot/hd1910/README.en.md). If you later train your own policies based on these parameters, keep the parameter authors' attribution.
