# Training studio acceptance record · 2026-10-22

**English** · [简体中文](verification.md)

## Verification that passed

| Environment | Check | Result |
|---|---|---|
| Windows / Python 3.12 | `python -m unittest discover -s tests -v` | 54 tests: 51 passed, 3 Linux-only tests skipped |
| WSL Ubuntu 22.04 / Python 3.11 | The same backend test command | 54/54 passed |
| Node.js | `node --test tests/state.test.mjs` | 11/11 passed |
| Edge / Playwright | `node dev/browser-check.mjs` | 1440×1000 desktop and 390×844 mobile flows passed, with no page errors or horizontal overflow |

The browser acceptance check starts an isolated demo service and actually calls the HTTP API, with no mocked endpoints and no CSP bypass. It covers the access token, shared CAD loading, the fixed 64-environment/5-iteration smoke run, advanced settings staying collapsed, full experiments, pausing after a checkpoint has been saved, the iteration count freezing, resuming after a refresh, stopping, evaluating an old checkpoint, authenticated downloads, the export package contents, creating continued training from a selected checkpoint, experiment comparison, search, the model list, re-running environment checks and the mobile drawer. Changing learning parameters requires a new smoke run, and the original full-training draft is still kept.

The Linux-only tests use real operating system signals and CPU subprocesses, without mocking `killpg` or `waitid`:

- After SIGSTOP, the counters of the main process and its descendants all freeze; after SIGCONT they keep increasing.
- Shutting down the service while paused cleans up the owned process groups.
- When the main process exits but descendants still hold stdout, both training and evaluation tasks can finish and clean up the descendants.

## Review and fixes

The front end and back end each went through an independent specification review and a code-quality review, and in the end neither had blocking items. Issues fixed during review: full training still possible with mismatched configuration, imprecise checkpoint matching, pause control wrongly carrying checkpoint parameters, the environment check cache not refreshing, an exit-cleanup race, incompletely written checkpoints, a log pipe preventing tasks from ending, overly long continued-training names, and exports missing evaluation evidence and provenance information.

## Verification boundaries

The 2026-10-22 verification above did not start NVIDIA GPU training. The local GPU hardware test below was added on 2026-10-23; the target cloud machine, long training and the real robot still need separate acceptance checks. The adaptation has been checked against the call interfaces of the pinned mjlab 1.3.0 and rsl-rl-lib 5.0.1; a short test does not prove that the robot has learned to walk.

The demo ZIP package does not contain PT/ONNX weights. Duck profiles are used for archiving and cross-checking and do not automatically rewrite the physics model. Pausing does not shut down the cloud machine or stop cloud platform billing.

## Web console style alignment review · 2026-10-23

- Adopted the web console's actual colors, fonts, duck logo, light sidebar, black pill buttons, white cards and gray 3D stage; mobile switched to a four-item bottom navigation.
- `node --test tests/state.test.mjs`: 11/11 passed. The full real demo browser flow after the changes passed, including authentication, CAD, task control, evaluation and export, comparison and the mobile drawer; no page errors or failed resources.
- The independent review checked the four routes at eight widths, 1440, 1024, 960, 840, 701, 700, 390 and 320 px: no horizontal page overflow, and the selected navigation item is correct. The mobile drawer's submit button is not covered by the bottom bar, and forward/backward Tab focus stays in the dialog.
- Fixed the mobile chart scaling found in review: the SVG is laid out by the container's actual width, and coordinates at 320/390 px stay at 12 px; empty data, a single point, multiple points and window width changes all pass.
- This style-alignment round only changed the front end and docs, not the training backend; what follows is real local verification added afterwards.

## Local GPU smoke run · 2026-10-23

Environment: Windows / WSL2 Ubuntu 22.04, NVIDIA GeForce RTX 5060 Ti 16 GB, driver 617.14, Python 3.12.14, actually installed torch 2.9.1+cu128, mjlab 1.3.0, rsl-rl-lib 5.0.1. Used the current `software/training` and lock file, prepared an isolated virtual environment from an offline cache, and did not change the training engine's parameter definitions or the lock file.

Operated the real-mode page through Edge / Playwright and created `caa6a1c5de10`: HD1910 flat ground, 64 environments, 5 iterations, saving every iteration, seed 42, learning rate 0.001. No API or training data was mocked.

| Check | Measured result |
|---|---|
| CUDA simulation and PPO updates | 5 iterations completed, 7,680 samples, 40.54 seconds including startup loading |
| Metrics and checkpoints | 5 metric points, `model_0.pt` through `model_4.pt`; the last file was loaded successfully with `torch.load(weights_only=True)`, and a recursive check found all 76 tensors finite |
| Policy evaluation | The last checkpoint completed 250 steps, producing an H.264, 960×540, 50 FPS, 250-frame, 5-second video; decoding of the first and last frames passed |
| Export and inference | The engine exported the ONNX and model package normally; ONNX checker passed, CPU Runtime with 61-dim input and 14-dim output |
| PT/ONNX consistency | Strictly loaded all actor weights and normalization with the installed rsl-rl MLPModel; compared a zero input + 31 sets of random inputs with a fixed seed, maximum absolute difference `1.9073486328125e-6`, passing `atol=1e-5, rtol=1e-4` |
| Browser after restart | Real mode ready; the saved experiment reloaded, the evaluation video actually played, the model package downloaded successfully, no page errors |
| Regression verification | Windows Python 3.12: 53 of 56 passed, 3 skipped; WSL Python 3.12: 56/56 passed; independent code review had no blocking items |

Actual operation found and fixed two environment issues: a cold import of the tasks takes about 24 seconds, so the original 20-second pre-check gave false failures, and it is now 60 seconds; the pre-check and training used different GL environments, so it still showed ready when EGL was missing, and now the runtime environment is unified and the selected graphics backend is actually imported. After installing `libegl1` on Ubuntu, the real video was generated successfully. An explicitly set `MUJOCO_GL` is kept. The fixed service has been restarted, the actual EGL/CUDA/task pre-checks pass, and the original experiment and artifacts are still readable.

Provenance boundary: the run baseline is Windows Git commit `adfb878cf944853aaa720dff4554fdab2dcaadb8` plus this pre-check fix. The `.git` path of this Windows worktree cannot be resolved directly by WSL Git, so the run record's `git_commit` is null; the file SHA-256s are kept. The `dependency_versions` in the record is a summary of the multi-platform lock file, in which torch shows cu129; the cu128 above comes from what the actual interpreter reads. That summary cannot serve as proof of the installed version.

The local evidence is stored in the outer `本地记录/training-local-20261023/` (`本地记录` = local records) outside the workspace: raw logs, run snapshots, screenshots, the artifact-check scripts and `artifact-verification.json`. Large logs and models are not added to Git. SHA-256 of the representative artifacts:

- `model_4.pt`: `0caa0e69f38533d1694960aaa4e7d260625bc6dc803852b15f1e3df82015f9ac`
- `policy.onnx`: `673bc7e787a084df1f3a8593a43ce987d2a05472ee12097b393e1ddb7311da57`
- `rl-video-step-0.mp4`: `e967b6d33b4debc28a10a88fe026dbb2250f3cf51bae44b6c197aa1cc2119f3d`

This result covers one flat-ground smoke run. PT/ONNX consistency is an independent acceptance check for this run and has not yet been added automatically to every export; it does not include hardware tests of GPU long-training pause/resume, rough-terrain training, cloud platforms or real-robot verification. For the steps see [Local smoke run](local-smoke.md).

## Custom action guide entry · 2026-10-23

- Added a Chinese custom action guide, covering the official development flow, the boundaries of existing capabilities, a single-leg standing requirement example, jump feasibility and spin acceptance checks. The source is `web/custom-actions.md`, and the static reading page is `web/guide.html`.
- The sidebar and the new-training window provide entries that open it in a new tab. An independent source review checked the upstream XL330 vs. local HD1910, the Spin roller-skating model, new tasks not yet implemented, existing commands, and the integration constraints of the fixed experiment directories, and found no clear issues.
- Acceptance check with Edge on the current real service at 1440×1000 and 390×844: the entry opens successfully, the original form name is kept, all table-of-contents anchors exist, returning to the training studio and accessing the source file work, no page errors or horizontal overflow.
- This round only added docs, static styles, the doc generation tool and reading links; it did not start new training or change engine or server logic. Screenshots and acceptance records are in `本地记录/training-custom-guide-20261023/`.
