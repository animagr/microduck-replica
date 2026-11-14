# Gait analysis scripts (run on a PC)

**English** · [简体中文](README.md)

Scripts used on the night of 2026-10-13 into the early hours of 10-14 to analyze "jittery walking" and "foot scuffing". All of them are **read-only**: they only read recording files and do not connect to the duck.
For how they were used step by step to reach conclusions, see the [2026-10-13 night hardware test log](../../docs/HD1910-20261013-夜-掉电-舵机D与蹭地.md).

**Input**: 50 Hz JSONL recorded by [`duck_rec.py`](../radxa/onboard-analysis/duck_rec.py) on the board (joint angles, targets, IMU gravity and gyro, joystick commands, policy state). Copy it to the PC before running.
**Environment**: Python 3.10+, `numpy`, `scipy`; scripts that take an `MJCF` argument also need `mujoco` and `src/mjlab_microduck/robot/microduck/scene_backlash.xml` from the official `microduck_rl` repo (for forward kinematics).
`foot_clear.py`, `toe_decomp.py`, `stance_*.py`, and `roll_pitch_coupling.py` **only count frames where "the model is in control and the joystick is pushed"** (`policy=walk` and commanded speed > 0.02 m/s); frames standing at HOME are used for self-checking. `gait_quality.py` splits the data into three segments by itself: "standing at HOME / stepping in place / walking". `walk_transfer.py` uses all continuous `policy=walk` segments ≥3 seconds long. Where robotd restarted during a recording, these scripts all break the segment there. `home_roll.py` uses continuous "holding HOME" segments (`policy=held`, torque not released) and takes the last 150 frames of each segment.

| Script | Question it answers | Usage |
|---|---|---|
| `gait_quality.py` | Is the walk jittery or wobbly: target jitter and >4 Hz share, tracking error and lag, body gyro RMS and dominant frequency, step frequency | `python gait_quality.py recording.jsonl` |
| `walk_transfer.py` | Can the servos keep up: per-joint "target → actual" amplitude ratio, lag, coherence (Welch cross-spectrum); can be compared side by side with simulation recordings | `python walk_transfer.py name=recording.jsonl ...` |
| `foot_clear.py` | How high the swing foot lifts: after leveling with the IMU, swing foot lowest point minus stance foot lowest point; at peak height, whether the lowest point on the foot is the toe or the heel; splits into "model intent / swing leg keeps up / stance leg does not sag" | `python foot_clear.py MJCF name=recording.jsonl[@start_wall[@end_wall]] ...` |
| `toe_decomp.py` | At the swing peak, whether the toe points down or up, broken down by joint and body pitch | `python toe_decomp.py MJCF name=recording.jsonl ...` |
| `stance_pitch.py` | How far the body leans forward during stance, and where the stance leg's hip, knee, and ankle actually are versus where the model wants them | Same as above |
| `stance_height.py` | How high the stance leg holds the body, and how much it sags compared with what the model wants | Same as above |
| `home_roll.py` | When standing at HOME, how much the two soles differ in the left-right direction, which joint causes it, and which side is lower when the torso is level (relative to the simulation HOME; readings and targets share the same zero, so zero-position errors cannot be seen) | `python home_roll.py MJCF name=recording.jsonl ...` |
| `roll_pitch_coupling.py` | Are roll and pitch coupled: coupled in all frequency bands = IMU mounted rotated about the vertical axis; coupled only near the step frequency = the body is really nodding | `python roll_pitch_coupling.py name=recording.jsonl ...` |


**Notes**:
- The `@` syntax cuts out a section by the recording's `wall` (Unix time); use it when parameters were changed within one recording;
- `foot_clear.py` and others use the IMU's gravity direction to level the body. If the IMU zero is off by 1°, the two feet will differ by about 2 mm in the calculation (foot spacing is about 98 mm). First calibrate the zero following [IMU calibration](../radxa/onboard-analysis/README.md#imu-校准今晚手动做的流程), then compare left and right; the "self-check" row for standing at HOME should be within ±1 mm;
- Simulation recordings can also be fed in directly (same fields) as a reference.
