# Onboard analysis scripts

**English** · [简体中文](README.md)

Scripts used to locate problems on the night of 2026-10-12 when the first robot was run on hardware (the recording service was updated on the night of 10-13). Gait analysis for walking runs on a PC; see [`tools/gait-analysis/`](../../gait-analysis/). All of them are **read-only**: they only subscribe to robotd's state and read logs, and send no control commands (`webpad_probe.py` is the exception: it only sends empty frames with "no buttons pressed, joysticks centered").
For how they were used step by step to find the root cause of "lunging hard as soon as the model takes over", see the [2026-10-12 night hardware test log](../../../docs/HD1910-20261012-夜-IMU校准与首次迈步.md).

Environment the scripts assume: the board runs kissqy's R17 (robotd socket `/run/robotd.sock`), recordings go in `/home/duck/r17/rec/`, and the scripts are in `/home/duck/tools/`.

## Record the data first

| File | Where it runs | What it does |
|---|---|---|
| `duck_rec.py` | Board | Subscribes to robotd's `robot.subscribe` and records joint angles, targets, joint velocities, IMU, safety state, joystick commands, and policy state at 50 Hz, saved as JSONL. `python3 duck_rec.py <seconds> <output file>`. Appends, **flushing to disk once per second**; when robotd restarts it logs a `rec_error` line and reconnects on its own |
| `duck_health_log.py` | Board | Records `robotctl health --json` every 0.5 seconds: servo voltage, hottest servo, CPU temperature and frequency, WiFi and Bluetooth status, saved as CSV |
| `duck-rec.service` | Board | Makes the two above start on boot and run independently (they do not stop with robotd); file names include the boot ID. Put it in `/etc/systemd/system/` and run `systemctl enable --now duck-rec` |
| `duck_journal.py`, `duck-journal.service` | Board | Copies this boot's system log to the card in real time, flushing to disk every second (Armbian keeps logs in RAM, so they are lost on power loss). Skips the log flood during the IMU stabilization phase at robotd startup |

Both service files hard-code the user `duck` and `/home/duck/...` paths (our own card); the user in kissqy's one-click image is `radxa`, so change them to `/home/radxa/...` before use.

Recordings take about 3 MB/minute. File names are `run-日期-时间-b开机编号前6位.jsonl` (run-date-time-b first 6 characters of the boot ID): the board has no RTC and the clock rolls back on every boot, so **find files by boot ID** (`cut -c1-6 /proc/sys/kernel/random/boot_id`). Since it flushes every second, a sudden power loss loses at most the last 1 second; the scripts below skip corrupted lines.

## How to investigate when something goes wrong

| File | Question it answers |
|---|---|
| `walk_now.py` | In the most recent stretch of model control (policy=walk): body tilt, angular velocity, how far the leg targets deviate from HOME, tracking error, joystick commands |
| `walk_report.py` | How many times the joystick was pushed in the last N minutes, and for each push whether the two legs stepped alternately (swing amplitude of the left-right knee angle difference and number of leg switches), and whether it fell over |
| `failure_onset.py` | The turning point from stable to out of control: around the first time a leg target deviates from HOME by more than 15°, frame by frame look at tilt, gravity, angular velocity, and which joint saturates first |
| `imu_consistency.py` | Whether the IMU gyro and gravity direction are self-consistent (dg/dt = −ω×g). An agreement close to 1 means the axes and signs are right; close to −1, or a better match with some other axis combination, means they are configured backward |
| `vel_consistency.py` | For each joint: compares the differentiated angle (true rotational speed) with the velocity reported by robotd, to check velocity sign and scale |
| `imu_fault_ctx.py` | Each time the IMU disconnects, what the robot was doing (stationary / returning to HOME / walking) and what the voltage was, to distinguish poor contact, supply droop, and driver timing |
| `webpad_probe.py` | Tests the web gamepad path locally on the board: how long webpad takes to cold-start, and whether padd can detect the virtual gamepad |
| `crash_scan.py` | Per recording: state transition timeline, joystick commands, and the safety state in the last few frames; with the health CSV for the same period you also see voltage and temperature. Used to determine what was happening right before a "whole-robot power loss" |
| `judge_block.py` | **Runs on a PC**. Stop rule for running BNO085 gyro fusion on the robot: whether the attitude seen by the model, during upright walking, has cases where "the gyro says no rotation but the attitude jumped by more than 5°", classified as hard / soft / exempt according to the fusion criteria; and how much fusion differs from the chip when standing still at HOME. In chip mode it also gives the jump count of the chip path as a baseline. Uses only the standard library. For the background, see the [10-15 log](../../../docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md) §5.5 |
| `ab_blocks.py` | **Runs on a PC**. For several recordings, counts falls (rising edges of `safety.fallen`; bouncing back and forth within 3 s counts as one), joystick-push time, falls per minute of joystick pushing, chip jumps, and body jitter; sums the two groups whose labels start with chip / gyro, and gives the rate ratio, 95% interval, and p-value. It detects on its own which mode a recording actually used, and reports an error if the labels are swapped |

## IMU calibration (the manual procedure done tonight)

**Step 1: direction check** (do this the first time the IMU is installed, or after removing and reinstalling it)

Hold the duck upright and tilt it about 20° forward, backward, left (the duck's own left), and right, holding each direction for 3 seconds and then returning to upright. Then:

```
python3 imu_tilt_check.py 120        # Last 120 seconds, one line every 0.5 s; lines deviating more than 8° from the start are marked ←
```

The four segments should read, in order, "forward tilt +", "forward tilt − (leaning back)", "right tilt − (leaning left)", "right tilt +", and the gyro rotation direction must match accordingly. If one segment has the wrong sign, the axis for the mounting orientation is configured wrong.

**Step 2: zero calibration** (do this after a hard fall, after the IMU has been bumped, or after rewiring)

During model training, the duck stands in the official HOME pose with its feet flat on the ground, and **the body is level** (the `STAND` keyframe in the MJCF; the body quaternion is the identity quaternion and the IMU reads 0°). So when the real robot stands at HOME, the IMU should also read close to 0°; however far off it is, that is how crooked the IMU module is mounted. It does not matter if the knees sag a bit; the calculation below uses the real joint angles.

1. Place the duck on a flat floor, press Start to stand up at HOME, take your hands off, and keep it still for 3 seconds;
2. On the board: `python3 capture_home.py home-capture.json` (takes the average joint angles and gravity over the last 100 frames);
3. Copy the JSON to a PC with mujoco and the official `microduck_rl` installed:
   `python sim_home_tilt.py <microduck_rl>/src/mjlab_microduck/robot/microduck/scene_backlash.xml home-capture.json`
   It outputs "how much the body should lean forward given the real robot's joint angles" and "IMU mounting error (measured − expected)";
4. `python imu_mount_fix.py <forward-tilt error> <right-tilt error> <current mounting quaternion w x y z>` computes the new mounting quaternion;
5. After the duck's **torque is released**, back up `/etc/robot/feetech-ft5/hd1910-calibration.toml`, replace `"quat"` under `["imu_mounts"."bno08x"]` with the new value, and run `sudo systemctl restart robotd`;
6. Stand at HOME again and repeat 2–3; the error should be within 1°.

2026-10-12, first robot: the errors computed from two standing poses were forward tilt 8.2° / 8.9° and right tilt 1.7° / 1.8°; after compensating 8.54° / 1.78°, the retest left −0.55° / −0.47°. The quaternion written in was `[0.454164155, 0.544101455, 0.527409117, 0.468538313]` (at the time a least-squares fit over the two data sets was used; the value computed by `imu_mount_fix.py 8.54 1.78` differs from it by less than 0.01°).

The plan is to turn this into a button-driven manual calibration tool later (no automatic changes, and every calibration is logged); see the "Next steps" section of the hardware test log.
