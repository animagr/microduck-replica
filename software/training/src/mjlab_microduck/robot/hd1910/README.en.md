# 1910 M6 parameter provenance

**English** · [简体中文](README.md)

The `1910_m6.json` in this directory **uses the 1910 BAM M6 parameters published by LuwuDynamics**;
it is not the result of identification or measurement by this project. Thanks to LuwuDynamics for sharing them publicly.
Even if you later train your own walking policy with these parameters, the servo model parameters should still credit this source.

## Pinned source

- Project: [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl)
- Version: `326d77a1122870bdefa2c36403937502c958e69c`
- [Original parameter file](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck/params/1910_m6.json)
- [Accompanying training configuration](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck_constants.py)
- SHA-256 of the original file: `ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb`
- Retrieved: 2026-09-24; the JSON is stored as in the original file, with no parameters changed.
- License: the upstream repository is **Apache-2.0**; a copy is in `LICENSE` in this directory.

Upstream calls the servo HLS1910. The JSON's `actuator: "sts3215"` selects the
Feetech controller implementation in BAM; it does not swap the parameters for the factory STS3215 model. The replica project maintainer has confirmed
that this project uses the same 1910 model; that confirmation does not mean we have reproduced the upstream identification experiments.

## Current use

`Mjlab-Velocity-{Flat,Rough}-MicroDuck-HD1910` uses these parameters with the upstream training settings:
`kp_fw=5`, `vin_range=(7.4, 8.0)`, `vin_min=7.0`, load voltage-drop gain `(0.0, 0.2)`,
and a command delay of `3–6` simulation steps. The local Microduck geometry and joint conventions are kept.

`max_velocity=100` is the upstream setting used to approximately disable the slope speed limit on the target position; it does not claim
that the servo's no-load speed is 100 rad/s. The model still limits speed through the power supply and back-EMF.
`q_offset` is an identification offset in the parameter file and should not be copied into the real robot's per-joint zero-position table.
The JSON's `command_delay` keeps the source value; mjlab's command-queue delay is controlled by the lag configuration above,
and the two cannot simply be added together and claimed as the real robot's total delay.

The raw identification data, test voltage and firmware version were not provided with the parameter records consulted this time.
Upstream training uses P=5, while its Arduino runtime temporarily stores gains of P=6, D=20; the two cannot be directly
treated as one verified real-hardware configuration. No servo registers are modified in this work.

## Upstream projects

- LuwuDynamics: 1910 parameters and the XgoDuck accompanying configuration, Apache-2.0.
- [Pollen Robotics / microduck_rl](https://github.com/pollen-robotics/microduck_rl):
  the local training framework and task code are Apache-2.0; the Microduck 3D models and meshes keep the upstream
  CC BY-NC-SA notice (the upstream README writes it as BY-SA-NC).
- [Rhoban / BAM](https://github.com/Rhoban/bam): actuator model and identification framework, Apache-2.0.

`1910_m6.json` is redistributed unchanged from LuwuDynamics/xgoduck_rl at the
revision above under Apache-2.0. It is not an independently identified model by
this replica project. Local integration changes are the additional HD1910 task
configuration and documentation; original attribution is retained.
