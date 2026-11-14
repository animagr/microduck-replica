# Microduck Training Studio

**English** · [简体中文](README.md)

A visual training workbench for the little duck. It uses the recommended parameters by default, with advanced settings that can be expanded; it supports training curves, a 3D model, checkpoint evaluation replays, pause/resume, experiment comparison and exporting results.

The UI reuses the light-gray color scheme, duck logo, black buttons and mobile bottom navigation of the robot's Studio web console.

The Action Lab offers two tabs, “训练配方” (Training recipes) and “预训练模型” (Pretrained models). The ready-made model catalog contains a fixed set of the 10 XL330 models from the official V8 collection and the 10 HD1910 models from kissqy V167, showing source, hardware, version, license and the upstream download location. It does not automatically install, evaluate or continue training external ONNX models, nor does it record them as local experiments; new recipe experiments still train from scratch. Some community weights can only be obtained from the author's full firmware release package.

Training details include execution-host resources refreshed about every 3 seconds: GPU model/utilization/temperature/VRAM, CPU model/utilization/temperature, and memory. Linux/WSL uses `/proc`, available CPU temperature sensors and `nvidia-smi` with a timeout; Windows uses system counters and driver tools; no monitoring dependencies need to be installed. Missing fields are left empty with an explanation of why. The resources are overall readings of the current execution host; WSL CPU/memory reflect what the subsystem can see, and cannot be taken as usage exclusive to a single experiment or as historical usage.

The training engine lives in the neighboring [`../training`](../training/README.md), and the robot web console in [`../studio`](../studio/README.md). This directory is a standalone service that uses the existing training project; the robot's system image does not need to be updated.

## Try it locally first

Python 3.12 is required. The service itself uses only the standard library, the web page has no build step, and it does not load dependencies from a CDN. Keep the neighboring `studio/web`, which provides the web libraries and 3D model already distributed with the repo.

```console
cd software/training-studio
python run.py --demo --open
```

On Windows you can also double-click `start-demo.cmd`; on Linux/macOS run `sh start-demo.sh`. Default address: <http://127.0.0.1:8093>.

Demo mode starts a separate lightweight subprocess that generates **synthetic metrics, text checkpoints and clearly labeled SVG illustrative replays**, so you can try out the workflow. It does not run GPU policy training. The demo export package contains only records, not deployable ONNX/PT weights.

## Real training

On a prepared Linux NVIDIA GPU machine or in Windows WSL2, use this repo's training project and its locked dependencies. Real mode checks the MuJoCo graphics backend, mjlab 1.3.0, CUDA and the HD1910 task registration; it does not install packages automatically, request a cloud machine, or handle top-ups. For local operation see [Local smoke run](docs/local-smoke.md).

```sh
cd software/training
uv sync --frozen --python 3.12
cd ../training-studio
../training/.venv/bin/python run.py
```

Open another terminal on your local machine to forward the port (fill in the username and address of your cloud machine):

```sh
ssh -N -L 8093:127.0.0.1:8093 username@cloud-machine-address
```

Then open <http://127.0.0.1:8093>. Use `--training-root /path/software/training` to specify the engine location and `--state-dir /persistent-dir/training-studio` to specify the records directory. Closing the web page does not stop training; **shutting down the training studio service stops the subprocesses it owns**. For long runs, keep `run.py` running through a terminal session manager or service manager on the cloud machine.

By default the service listens only on the local machine. If you really need to use it through another network entry point, set `STUDIO_ACCESS_TOKEN` and start it with `--host 0.0.0.0`; the page will ask for the token. To access a cloud machine from your local machine, the SSH forwarding above is recommended; a direct LAN connection must use the listening address of the machine running the service. The token is stored only in the current browser session; the API and artifact downloads all require `X-Studio-Token`; Host/Origin checks stay enabled.

## A complete practice run

“动作实验室” (Action Lab) in the navigation is a standalone recipe library page (`#/actions`), with an entry kept on the home page. You can search, filter by category, view a model preview or text description, and then start training with a recipe. The existing flat-ground walking, rough terrain and single-leg balance recipes are each labeled with their verification status; for how community contributions are accepted see [Action recipe contribution guide](docs/recipe-contribution.md).

Among them, the experimental **HD1910 单脚平衡** (HD1910 single-leg balance) lets you choose the support foot, the foot lift height (0.5–2 cm) and the hold time (1–5 seconds) without changing code. A full cycle includes preparation, lifting the foot, holding, and putting the foot down to recover. The 3D target illustration does not represent physical balance or a training result. Jumping, precise turning in place and video imitation are not integrated yet.

For step-by-step operation for beginners, judging results, and the development steps for adding new actions, see the [Action Lab getting-started guide](web/custom-actions.md); it can also be opened from the sidebar or the new-training window.

1. In “计算环境” (Compute environment), confirm that the checks pass; after installing dependencies you can re-run the checks.
2. Create a new experiment and pick **HD1910 平地行走** (HD1910 flat-ground walking) first. The first run is a fixed short smoke run with **64 environments and 5 iterations** that checks loading, simulation stepping and the saving pipeline. A smoke run is not a training result.
3. After the smoke run succeeds, proceed to full training. You can expand the number of parallel environments, training iterations, save interval, seed and learning rate; when collapsed, a summary of the changes is still shown. After changing the action target, learning rate, random seed or imported profile, you need to complete a smoke run with matching settings again; the number of environments and iterations can be scaled up for full training.
4. View the raw training metrics, iteration count and logs. The percentage shows progress through the planned iterations, not how well the action has been mastered. The 3D model can be rotated; **the CAD model and demo motions cannot be used to judge policy performance**.
5. Pause, resume or stop the task. Select a checkpoint to evaluate: walking tasks generate a 250-step replay; balance tasks run 8 full-cycle attempts with recorded seeds, and early failures still keep the video and the failure reason. The page shows the number of successes and how the hold and foot-down went. The replay corresponds to the selected checkpoint; it is not a continuous live view of training.
6. Compare full experiments of the same task and mode; after confirming the checkpoint you need, export the model package, and then go through the existing simulation and real-robot verification process.

| Operation | Behavior |
|---|---|
| Pause | On Linux, uses SIGSTOP on the process group, keeping the policy, optimizer and VRAM; the demo subprocess only updates the UI after the pause is confirmed |
| Resume | From the paused state, continues with the original process; from the stopped/completed state, creates a new experiment from the selected checkpoint and records its origin |
| Stop | Ends the owned training process and keeps checkpoints that have finished writing; iterations not yet written are not guaranteed to be saved |
| Evaluate | After training stops, runs step-limited inference on the selected checkpoint and generates a video |
| Export | Calls the engine's `scripts/export.py`, keeping its built-in observation normalization, and packages the ONNX, checkpoint, configuration and source record |

Pausing still occupies VRAM and **does not automatically shut down the cloud machine or stop platform billing**. One service runs only one training, evaluation or export operation at a time. Restarting the service marks unfinished old tasks as interrupted, and does not act on other processes based on the PIDs in the records.

## Profiles and results

Importing `microduck-studio-duck-profile/v1` JSON (up to 64 KiB) is supported. The profile is saved with the experiment for cross-checking and **does not automatically override the mass, inertia, joint zero positions or servo configuration used in training**. The current HD1910 recipe is a simulation baseline; you still need to verify your own physical robot independently.

Service records are in `state/runs/<id>/` by default, and the engine's raw logs and PT checkpoints remain in `../training/logs/rsl_rl/`. Keep both locations when backing up or migrating; the UI records reference the engine checkpoints by their original paths. The exported ZIP can be saved on its own, but this version has no "upload a ZIP to resume training" entry.

The balance task uses a separate `microduck_hd1910_balance` experiment directory and uses `skill.json` for training, continued training, evaluation and export. The export package includes the command convention. Although the policy is still 61-dim observation, 14-dim action, 50 Hz, the meaning of its command slots has changed, so the existing walking deployment side needs to be adapted for phase scheduling; single-leg balance has not been verified on the real robot yet.

Single-leg balance has completed real GPU smoke runs for both the left and right sides, 8-attempt evaluations and ONNX consistency checks. The current 5-iteration policy has a success rate of 0/8, which only proves the pipeline works. See [Action Lab acceptance check](docs/action-lab-verification.md). For the positioning and contribution process of the community action recipe library see the [design notes](docs/action-lab-design.md#后续定位社区动作配方库); sharing and automatic installation are not implemented yet.

The HD1910 flat-ground task has completed real 64-environment, 5-iteration training, PT saving, 250-step video evaluation and ONNX export on WSL2 / RTX 5060 Ti, with an independent check of PT/ONNX inference consistency. See the [acceptance record](docs/verification.md). Rough terrain, long training, the target cloud machine and real-robot deployment still need separate acceptance checks; a smoke run does not prove that the action is fully trained.

## Development verification

```console
python -m unittest discover -s tests -v
node --test tests/state.test.mjs
```

The browser acceptance check uses Playwright; the script starts its own isolated demo service, sets a test token, actually calls the API and saves screenshots. Set `PLAYWRIGHT_MODULE_ROOT` to an existing `node_modules` path to reuse an installed Playwright; you can also install Playwright in the development environment. `BROWSER_EXECUTABLE` can specify a Chrome/Edge executable, and `PYTHON` can specify Python 3.12. The unit tests above can be run without installing browser dependencies.

```console
node dev/browser-check.mjs
```

The acceptance output is written to the system temp directory by default; use `BROWSER_CHECK_OUTPUT` to specify a directory. The tests do not connect to cloud platforms, GPUs or robots. For the design and API conventions see [design.md](docs/design.md), for the implementation acceptance checklist see [implementation-plan.md](docs/implementation-plan.md), and for the test and review results of this round see [verification.md](docs/verification.md).

The action guide uses `web/custom-actions.md` as its source file. After editing it, run `python dev/build-guide.py` in a documentation editing environment with Python-Markdown installed, and commit the generated `web/guide.html` together with it. The web page uses the generated file directly; running the training studio does not require installing Markdown or running a build.

## Attribution

The original code in this directory uses the repo's Apache-2.0 license; documentation follows the repo's corresponding documentation license. Shared models, web libraries and the training engine follow their own licenses; see [NOTICE.md](NOTICE.md).

For a comparison with similar projects and next-step priorities see [Comparison with the kissqy training console](docs/reference-comparison-2026-10-23.md).
