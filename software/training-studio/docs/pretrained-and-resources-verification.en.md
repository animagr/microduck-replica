# Pretrained catalog and compute resources acceptance check · 2026-10-23

**English** · [简体中文](pretrained-and-resources-verification.md)

This round adds a source catalog of ready-made models to the Action Lab, and adds monitoring of the execution host's current resources to the training details. The training algorithm, robot policy and existing experiment state were not changed.

## Model sources

- Official [V8](https://huggingface.co/pollen-robotics/microduck-policies/blob/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json): pinned to `665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448`, 10 ONNX files, XL330, 61-dim observation, 14-dim action, 50 Hz. The V8 collection keeps the early separate walking/standing models; the default walking model is VelStand.
- [kissqy V167](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/firmware/verification/v167/arm64-models.json): pinned to `525a215a19397767a073b782f57e97cf53683761`, 10 HD1910 models, 4 of which need wheeled feet. The author's audit is QEMU ARM64 inference, `hardware_tested=false`, which does not mean this project has done a physical evaluation.
- The upstream byte-stream SHA-256 of all 15 standalone ONNX files match; the 10 ONNX files inside the 34,138,802-byte firmware package all match as well. No weights were copied into the product or executed. Among the package's 161 members there is no PT/PTH, and neither is there in the full Git tree; no inference is made about other packages that were not checked.
- All 20 entries have hardware, author, pinned version, SHA, actual byte size, usage license and download entry. In-package weights and single-file links are labeled separately, and restricted community weights are still distributed by the original publisher.
- Currently only source descriptions and upstream downloads are provided; local simulation, automatic installation or continued training of external models is not integrated. New recipe experiments train from scratch, and the existing checkpoint continued-training flow keeps its original constraints.

## Resources and interaction

- Windows Python tests, 93 tests: 90 passed, 3 Linux-only tests skipped; WSL Python 93/93; Node 26/26.
- The independent review found that comparing clocks across machines would falsely report stale data; in `7598562` this was changed to the sample age computed with the server-side monotonic clock, plus the local elapsed time after the browser receives it; regressions for remote clock skew and page suspension pass. The re-review has no remaining P1/P2.
- Browser acceptance checks on the isolated demo service and the original 8094 real service passed: 20 models, source/category/keyword filtering, the source URLs and SHAs in all details, the mobile details button, the original recipe entry, real resource sampling, keeping old readings/stale marker/recovery on disconnect, and stopping front-end polling after leaving the experiment. Zero page errors, and browsing and selecting do not send training POSTs.
- The real service reads the RTX 5060 Ti (16311 MiB total VRAM), i5-14600KF (20 logical cores), CPU utilization and WSL memory (16640778240 bytes total). The GPU temperature changes between samples; the CPU temperature is null because WSL does not expose the corresponding sensor. The resources are for the execution host as a whole and are not claimed as exclusive usage by this training.
- Checked at desktop 1440 and mobile 320 widths, with screenshots reviewed manually. The originally stopped experiment `9843544f2296` still keeps its 0/1000 iterations, 9 seconds and 0 checkpoints; the other three old experiments are also fully kept. The update restart happened only when the service had no active tasks, and the GPU environment is still ready.

## Evidence

The outer `本地记录/training-action-lab-20261023/` (`本地记录` = local records) holds `pretrained-source-package-audit.json`, `kiss-model-inventory.json`, the official refs/manifest/tree, and `models-resources-browser.mjs`. `models-resources-validation-stable/` holds the reports and screenshots for the original 8094 service, and `models-resources-validation/` holds the isolated acceptance check. `pretrained-ui-mock/` is a UI boundary test that explicitly uses mocked resources and is not evidence about real hardware.

This round did not start real GPU training, a paid cloud machine or any robot motion; only one synthetic training record was created on the isolated demo service to show the resource panel.
