# HD1910 M6 simulation training baseline

**English** · [简体中文](hd1910-baseline.md)

This baseline uses **the 1910 BAM M6 dynamics parameters published by [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl)**;
it is not data identified by this project.
The [source record](../src/mjlab_microduck/robot/hd1910/README.en.md) contains the pinned commit, the original file's
SHA-256, the accompanying configuration and a copy of the Apache-2.0 license. Thanks to LuwuDynamics,
[Pollen Robotics](https://github.com/pollen-robotics/microduck_rl) and
[Rhoban/BAM](https://github.com/Rhoban/bam) for their open-source work.

## What has been integrated

| Item | Current configuration |
|---|---|
| Flat-ground entry point | `Mjlab-Velocity-Flat-MicroDuck-HD1910` |
| Rough-terrain entry point | `Mjlab-Velocity-Rough-MicroDuck-HD1910` |
| Servo parameters | LuwuDynamics' `1910_m6.json`, kept as is |
| Gain / voltage | `kp_fw=5`, randomized voltage of 7.4–8.0 V, voltage-drop floor of 7.0 V |
| Control delay | 3–6 simulation steps; the current simulation step is 5 ms, i.e. 15–30 ms |
| Policy interface | 50 Hz, 61-dim observation, 14-dim action; the original Microduck ordering is kept |
| Model | Local Microduck geometry, mass, inertia and default standing pose |
| Logs | Separate `microduck_hd1910_velocity` directory, local TensorBoard logging by default |

The original XL330 training entry points still work. The HD1910 factory copies the robot configuration and then replaces the actuators, without affecting
other tasks. XgoDuck's 0.8 kg model, encoder zero positions, directions and ONNX were not carried over to this robot.
The existing Microduck mass and inertia are still the original simulation values and need to be corrected later against data from the real Feetech hardware.

### Local compatibility fix

What is fixed here is the initialization of the simulated controller's runtime state; it is not re-initializing the neural network, and the servo parameters were not
refitted. The Feetech model uses `q_target_smooth` to store the previous target angle in order to limit
how much the target can change per step; this history must exist before the next step is computed.

In the pinned BAM `62bd8ce`, the Feetech controller's `q_target_smooth` is only created when reading identification logs,
and mjlab training does not go through that path. The actual GPU simulation reproduced the missing-field error on the first reset.

```text
AttributeError: 'STS3215Actuator' object has no attribute 'q_target_smooth'
```

`actuator/feetech_bam.py` adds the missing state initialization, and on the first computation after each environment reset,
restarts the target speed limiting from that environment's current joint positions, so the previous episode's history does not affect the new pose.
When one environment is reset, only its own history is cleared; the other parallel environments keep their own state.
The current joint positions are chosen as the starting point to avoid carrying the previous target or a uniform zero angle into the new episode.
This adaptation does not change the LuwuDynamics parameters and does not modify the system-installed BAM.

The issue was reproduced with the BAM/mjlab combination pinned by this project; we do not infer from it that their real-robot runtime
has the same issue. The regression checks cover first startup, consecutive computations and history isolation after a single-environment reset.

## Getting the code

The training code, models and parameters are all in [software/training of microduck-replica](../README.en.md).
Use a Linux CUDA machine or WSL2 with a GPU configured, and run in its terminal:

```bash
git clone https://github.com/fanhao375/microduck-replica.git
cd microduck-replica/software/training
uv sync --frozen --python 3.12
```

If you have already cloned or downloaded this repo, just go into `software/training/`; no submodule or separate training repository is needed.
For the pinned imported version and licenses see [UPSTREAM.md](../UPSTREAM.en.md).

## How to run

All of the following commands are run in the `software/training/` directory; logs are saved under that directory by default:

```bash
# List registered tasks
uv run --frozen list-envs

# Do a short training first to check the training and saving pipeline
uv run --frozen train Mjlab-Velocity-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.logger tensorboard --agent.run-name hd1910_m6_smoke

# Integration and regression checks (including actual GPU stepping)
uv run --frozen --with pytest python -m pytest -q \
  tests/test_hd1910_cfg.py tests/test_hd1910_rollout.py \
  tests/test_ground_pick_cfg.py tests/test_nan_guard.py tests/test_obs_nan_guard.py \
  tests/test_hf_source_snapshot.py
```

By default uv creates the environment in `software/training/.venv/`. If the source is on a Windows disk,
you can set `UV_PROJECT_ENVIRONMENT` before the first `uv sync` to put the virtual environment on WSL's Linux
file system; subsequent commands use the same environment path. The Feetech version uses the HD1910 tasks above;
the default task in the [original README](../README.upstream.md) targets the XL330.

The optional `--hf-jobs` cloud submission feature requires a Git checkout; a ZIP download is only for local training.
After the migration, packaging uses the training project as the root and does not include hardware files, photos or other directories from the replica repo.
This time only the local packaging behavior was verified; no paid cloud job was submitted.

## Verification records

On 2026-09-24, before the migration, on WSL Ubuntu-22.04, Python 3.12.14 and an RTX 5060 Ti,
a short PPO training with 64 environments and 5 iterations was completed, for a total of 7,680 environment steps;
`Episode_Termination/nan_state` in the training log was 0 for every iteration. The model log confirms loading of
`kt=0.6238`, `R=4.9102` and 14 HD1910 actuators.

- 26 configuration, regression and GPU stepping tests passed, including a target-history check when only one environment is reset.
- The short-training checkpoint was exported to ONNX with the project's standard export script, with observation normalization included in the graph.
- ONNX checks and CPU inference passed: input `[1, 61]`, output `[1, 14]`, outputs are finite values,
  and the joint metadata matches the local Microduck ordering.
- mjlab emits a notice that the broad joint-matching regex matched a site; the actual actuator count check is
  14, and no site actuators were added. This regex follows the upstream `^(?!passive_).*` convention.
- An independent code review checked the reset order, target-history isolation, isolation of the original XL330 configuration and source verification,
  and raised no correctness issues needing a fix; this does not replace consistency verification on real hardware.
- Default standing-pose measurement: 4 environments, fixed 7.4 V, no pushes, no automatic reset; initial perturbations of the joints and the torso
  roll/pitch were all ±0.01 rad, held continuously for 3 seconds. The maximum tilt angles were
  4.47° / 6.17° / 5.94° / 5.03°, and the final torso height was about 0.1153–0.1156 m;
  this limited sample did not fall over, which does not mean it is stable at all voltages, perturbations or on real hardware.

The measurement scripts, JSON, logs and export artifacts above are kept in the ignored directory
`artifacts/hd1910/` of the pre-migration local workspace, and the short-training checkpoint is in that workspace's
`logs/rsl_rl/microduck_hd1910_velocity/2026-09-24_20-40-50_hd1910_m6_smoke/`.
These local verification artifacts were not released with the source snapshot. The short-training checkpoint is only an integration-test artifact;
it has not learned to walk yet and cannot be used as a gait on the real robot.

### Re-verification after moving into microduck-replica

On the same day, a separate environment was created from the lock file under `software/training/` and installed successfully; the 26
tests above passed again. In addition, 4 offline source-packaging tests passed, covering the standalone training repo / subdirectory layouts,
current uncommitted changes, new source files and ignored artifacts. The post-migration 64-environment, 5-iteration PPO short training was completed again,
for a total of 7,680 environment steps, with `nan_state` at 0 for all 5 iterations; the loaded parameters were still `kt=0.6238`, `R=4.9102`.
The SHA-256 of the original parameter file matches the cited source.

The HF Jobs packaging path and geometry license wording issues found by the independent review were fixed after confirmation by a second reviewer,
and the final re-review found no new actionable issues. This round did not repeat the standing-pose measurement or ONNX export; the related data above
belong to the pre-migration records. The re-verification logs and checkpoints are still kept only in the local ignored directory.

## Once the real hardware arrives

First check the status of the 15 servos and complete the per-joint zero position, direction and limits, then connect the main controller's IMU.
Record the actual P/D, operating mode, power supply and bus timing, and run small step-response experiments to compare against the model.
The baseline's P=5 is the upstream training setting; the upstream Arduino runtime uses P=6, D=20, and the two cannot be directly
treated as the same verified set of real-hardware parameters. This work did not connect to or control the real robot, and did not write EEPROM.

A policy you train yourself and the servo model it uses are two separate layers of sources: as long as you still use these M6 parameters,
keep the LuwuDynamics citation when publishing models or training results.
