# Microduck HD1910 simulation training

**English** · [简体中文](README.md)

The training code, models, parameters, dependency lock file and tests for the Feetech HD-1910 are all maintained in this directory.
Download or clone `microduck-replica` to get the complete project; there is no need to pull a training branch or initialize submodules.

It uses **[the 1910 BAM M6 parameters published by LuwuDynamics](src/mjlab_microduck/robot/hd1910/README.md)**;
the training framework and the Microduck geometry come from [Pollen Robotics](https://github.com/pollen-robotics/microduck_rl),
and the actuator model comes from [Rhoban/BAM](https://github.com/Rhoban/bam). The parameters were not identified by this project.
This project adds the HD1910 task configuration, the state-initialization adaptation for the Feetech controller, and regression checks.

## Quick start

Use Linux with an NVIDIA CUDA GPU, or WSL2 with a GPU configured; Git and [uv](https://docs.astral.sh/uv/) are required.
Run in a Linux / WSL terminal:

```bash
git clone https://github.com/fanhao375/microduck-replica.git
cd microduck-replica/software/training
uv sync --frozen --python 3.12

# First check the training pipeline with 64 environments and 5 iterations
uv run --frozen train Mjlab-Velocity-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.logger tensorboard
```

If you have already downloaded this repo, just go into `software/training/` to install and run.
The optional HF Jobs cloud submission feature requires a Git clone, so that the source can be packaged according to the Git ignore rules;
a downloaded ZIP works for the local training above.
Logs and checkpoints are saved in `logs/rsl_rl/microduck_hd1910_velocity/` in this directory and are not released with the source.
The 5-iteration short training checks loading, stepping and saving; it is not enough to learn to walk.

| Entry point | Purpose |
|---|---|
| `Mjlab-Velocity-Flat-MicroDuck-HD1910` | HD1910 flat-ground velocity task |
| `Mjlab-Velocity-Rough-MicroDuck-HD1910` | HD1910 rough-terrain velocity task |

This is currently a simulation integration baseline; there is no walking policy yet that has passed a hardware test on our own robot. Mass and inertia still use the original Microduck
simulation values; they need to be corrected later against the real Feetech hardware, and the zero positions, directions, limits, power supply, IMU and communication timing need to be checked.

## Docs and tests

- [Usage, verification records and explanation of the initialization issue](docs/hd1910-baseline.md): what was missing is the Feetech controller's target-angle history; the fix does not change the borrowed M6 parameters.
- [Sources, pinned versions and license scope](UPSTREAM.md).
- [Original training project README](README.upstream.md): keeps the upstream task and tool descriptions; its default task targets the XL330, while the Feetech version uses the HD1910 entry points in the table above.

Run the integration and regression checks in this directory (including GPU stepping):

```bash
uv run --frozen --with pytest python -m pytest -q \
  tests/test_hd1910_cfg.py tests/test_hd1910_rollout.py \
  tests/test_ground_pick_cfg.py tests/test_nan_guard.py tests/test_obs_nan_guard.py \
  tests/test_hf_source_snapshot.py
```

Policy export uses `scripts/export.py` as before, with observation normalization included in the ONNX. Short-training checkpoints are only for
verifying the pipeline and are not released as gaits for the real robot.

## License

The code, configuration, parameters and documentation in this training directory are licensed under [Apache-2.0](LICENSE), keeping third-party attribution.
**The 3D models and meshes follow the upstream CC BY-NC-SA notice** and do not become Apache-2.0 because they were merged into this repo;
see [UPSTREAM.md](UPSTREAM.md) and the root [NOTICE.md](../../NOTICE.md).
