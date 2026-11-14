# Local smoke run

**English** · [简体中文](local-smoke.md)

First choose **HD1910 平地行走 (HD1910 flat-ground walking) → 64 environments → 5 iterations**. The page's “开始短试跑” (Start smoke run) automatically uses these parameters and saves once per iteration. The training engine samples 24 steps per environment per iteration, so there are `64 × 24 × 5 = 7,680` samples in total; log iterations start from 0, and the last file is `model_4.pt`.

## Operating in the UI

1. Start the real training service and open the address it shows. In “计算环境” (Compute environment), confirm that real mode, CUDA, the graphics backend and the task checks pass.
2. Click “新建训练” (New training), choose “HD1910 平地行走” (HD1910 flat-ground walking), enter an experiment name, and click “开始短试跑” (Start smoke run). Keep the default seed and learning rate for now.
3. Wait for the status to change to complete. There should be 5 metric points and `model_0.pt` through `model_4.pt`, with 7,680 cumulative steps in the log.
4. Select the last `model_4.pt` to evaluate it, and watch the 250-step, roughly 5-second policy replay. The CAD appearance in the training area serves a different purpose from the evaluation video.
5. Export the model package and confirm the download succeeds. Before deploying, check the model against the robot configuration and do independent simulation verification.

5 iterations only check loading, GPU simulation, optimizer updates and the artifact flow. A negative reward, the duck falling over or unstable motion are not enough to judge this short test as failed; what matters is exiting without errors, finite metrics, loadable checkpoints and a playable video. Pass this test first before scheduling long training.

## Using WSL2 on Windows

The real training service runs in Linux; Windows handles the browser UI. You need an NVIDIA driver that supports WSL CUDA, `nvidia-smi` inside WSL must see the GPU, and Python 3.12 and uv must be installed. Run the following commands in the project root directory inside WSL:

```sh
export PATH="$HOME/.local/bin:$PATH"
cd software/training
uv sync --frozen --python 3.12
cd ../training-studio
../training/.venv/bin/python run.py --port 8094
```

Then open <http://127.0.0.1:8094> in a Windows browser. 8094 distinguishes it from the demo service on the default 8093; do not add `--demo` when starting.

The default graphics backend is EGL, and the environment pre-check and training/evaluation use the same setting. If Ubuntu 22.04 is missing `libEGL.so.1`, install the system package `libegl1` and re-run the check. An explicitly set `MUJOCO_GL` is kept, and the system dependencies of the selected backend must also be in place. The pre-check only checks whether the graphics library can be loaded; actual rendering is verified through the policy evaluation video.

Registering all tasks for the first time may take tens of seconds; the pre-check allows up to 60 seconds. Closing the web page does not stop the service; closing the terminal running `run.py` ends the tasks it owns. Before changing the startup directory or records directory, make sure to keep both records: the training engine logs and the service state.

## This hardware test

2026-10-23, Windows + WSL Ubuntu 22.04, RTX 5060 Ti 16 GB, Python 3.12.14, torch 2.9.1+cu128, mjlab 1.3.0: the 5 iterations above finished in about 41 seconds (including startup loading), producing 5 PTs. Evaluation produced a 960×540, 50 FPS, 250-frame video. The ONNX checker and PT/ONNX inference checks on 32 sets of identical inputs passed. The time is from this measurement; first-time kernel compilation or other machines may differ.
