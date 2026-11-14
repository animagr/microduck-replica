# HD-1910 M6 Parameter Sources and Usage

**English** · [简体中文](HD-1910-M6参数来源.md)

2026-09-24: this project adopts the **1910 BAM M6 dynamics parameters published by LuwuDynamics** as
the initial model for HD-1910 simulation training. Thanks to LuwuDynamics for sharing them. The parameters were not identified
or measured by this project; what this project currently does is integration and verification, and hardware testing will be done later by the maintainer.

## Citation and license

| Item | Pinned source |
|---|---|
| Author / publishing organization | [LuwuDynamics](https://github.com/LuwuDynamics) |
| Repo | [xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) |
| Version | `326d77a1122870bdefa2c36403937502c958e69c` |
| Parameters | [`src/mjlab_microduck/robot/xgoduck/params/1910_m6.json`](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck/params/1910_m6.json) |
| Training configuration | [`xgoduck_constants.py`](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck_constants.py) |
| License | [Apache-2.0](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/LICENSE) |
| SHA-256 of the original parameter file | `ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb` |

The model and identification framework come from [Rhoban/BAM](https://github.com/Rhoban/bam); the local training framework and the
Microduck geometry come from [Pollen Robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl).
The sources and licenses of these projects are each preserved. If you train your own policy with this parameter set, you still need to cite LuwuDynamics'
servo parameters; only new parameters obtained through independent identification in the future may be labeled as this project's identification results.

## How to use

Training code, parameters, models and integration fixes are all in this repo's **[`software/training/`](../software/training/)**;
clone or download this repo to get the complete project. The [usage notes and verification record](../software/training/docs/hd1910-baseline.en.md)
contain the commands, test results, and the cause and fix of the Feetech controller target-history initialization problem.

- The parameter file is kept unchanged, keeping `model: "m6"` and `actuator: "sts3215"`; the latter selects
  BAM's Feetech controller implementation. Upstream writes the model as HLS1910; the maintainer has confirmed it is the same 1910.
- Matching training settings: P=5, voltage randomization range 7.4–8.0 V, voltage-drop lower limit 7.0 V, latency 3–6
  simulation steps. `max_velocity=100` is used to lift the target slope limit and is not the servo's real no-load speed.
- Added separate `Mjlab-Velocity-{Flat,Rough}-MicroDuck-HD1910` training entry points for comparison with the
  original XL330 baseline. The current integration keeps the local Microduck geometry, joint order and default pose.
- Per-joint zero positions, directions and limits on the real robot still use this project's calibration results; the other team's full-robot encoder
  zero positions or ready-made ONNX are not copied as policies that can run directly on the robot.

## Current verification boundary

The public parameters let us start simulation integration, so building a complete identification test rig ourselves is no longer a prerequisite for starting simulation.
This project has not yet verified Luwu's parameter set on real hardware. Our own unit's gain, power supply, response latency, mass and inertia,
IMU and main controller communication timing still need checking; first compare simulation and hardware with small step responses, then decide whether to re-identify.

For other static and dynamic data requirements, see the [pre-training data checklist](HD-1910-pre-training-data-checklist.en.md).
The newly added training baseline uses the M6 parameters whose source is noted here.

## Feetech's official HD-1910 BAM

Added 2026-10-14. At the end of September, Feetech published [ftservo/ftservo-bam](https://gitee.com/ftservo/ftservo-bam) on Gitee, a fork of [Rhoban/BAM](https://github.com/Rhoban/bam), under Apache-2.0:

- **Parameters**: `bam/params/feetech_hd1910_7_4V/m1.json` to `m6.json`. The m6 file was last changed in commit `79eff6d` (09-26), SHA-256 `81a441fb921130bcc9bcfbd9ee0c77e3c38d9ab758bc7e0559fb029c436355ba`; when it was added here, the repo HEAD was `4f7c0b0` (09-30);
- **Control model**: `HD1910Actuator` in `bam/feetech/actuator.py`, pure P control: duty cycle = clip(0.163 × P × angle error, ±0.97), 7.4 V supply, no velocity limit, no D;
- **Identification**: a pendulum arm with a load, P set to 4, 8, 16, 32 and 64, running 4 excitation trajectories (`bam/feetech/all_record.py`).

**Compared with Luwu's 1910 M6** (the first five rows are computed from the BAM formulas, the rest are the raw values in the JSON; none are measurements):

| | Luwu 1910 M6 | Feetech HD-1910 m6 |
|---|---|---|
| Control model | Borrows STS3215 (0.166 × fitted gain factor 1.32) | Dedicated HD1910 (0.163) |
| Duty cycle per rad of error per unit of P | 0.219 | 0.163 |
| Error at which saturation starts at P=5 | 0.88 rad | 1.19 rad |
| Stall torque at 7.4 V | 0.91 N·m | 1.37 N·m |
| Small-error static stiffness (P=5) | 1.03 N·m/rad | 1.15 N·m/rad |
| Motor resistance R | 4.91 Ω | 2.97 Ω |
| Rotor inertia `armature` | 0.00178 | 0.00183 |
| Drive-side load friction `load_friction_motor` | 0.069 | 0.353 |
| External load friction `load_friction_external` | 0.158 | 0.043 |
| Command delay `command_delay` | 6.0 ms | 1.0 ms |

`command_delay` is only the value recorded during identification: the BAM version pinned in this repo does not read it during training; the latency is set separately by the training configuration's `delay_min_lag`/`delay_max_lag` (3 to 6 simulation steps).

**Things to watch out for when integrating**:
1. The official JSON says `"actuator": "hd1910"`, while the key in the registry is `"HD1910"`; the case does not match, so calling `load_model` directly raises a `KeyError`. When using it in Feetech's repo, changing `actuator` to `"HD1910"` makes it load; you could also open an issue with Feetech;
2. The conversion factor is different: Feetech uses 0.163 (at P=1, a 4000-count error corresponds to 100% PWM, i.e. 1 / (4000 × 2π / 4096) ≈ 0.163; from an early Feetech documentation file, historical commit `3c37f36`, later deleted), while Rhoban's original STS3215 uses 0.166. To put it into this repo's training project (pinned Rhoban BAM `62bd8ce`) and compute with the borrowed sts3215 control model, three changes are needed: change `actuator` to `"sts3215"`; set `error_gain_ratio` to 0.163 / 0.166 ≈ 0.98193; set `max_velocity` to 100 as in Luwu's file to lift the target velocity limit (if omitted, the default is about 5.2 rad/s, while Feetech's model has no velocity limit). With 100, each physics step can still jump at most 0.5 rad, the same as Luwu's file; this is an approximation;
3. The data recording script `record.py` only writes P (address 50 on the HD-1910), target speed 0 and target position; D, torque limit and acceleration are whatever values were already in the servo. If the factory D=40 was in place, the D damping was most likely fitted into the friction parameters (a guess, not verified). Before running a model trained with it on the robot, confirm D, ideally by asking Feetech;
4. Several friction parameters sit at the fitting bounds: `load_friction_external_quad` 0.0099999 (upper bound 0.01), `friction_stribeck` 0 (lower bound 0), and `load_friction_motor_stribeck` is only 1.7e-6, also at the lower bound. Being at a bound is not necessarily wrong, but these values should not be interpreted directly as physical quantities.

This repo's training project still uses Luwu's file for now. A plan to integrate the Feetech parameters into the training project has been through one round of review but has not been implemented; we have also not yet compared on the real robot which of the two is more accurate.
