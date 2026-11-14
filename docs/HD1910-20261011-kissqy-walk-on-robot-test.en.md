# 2026-10-11: Running kissqy's walk model with our own runner

**English** · [简体中文](HD1910-20261011-kissqy-walk上机实测.md)

**In one sentence**: the HD1910 walking model that ships with kissqy's repo **can step** on our duck, provided it is on the ground and the body is not held up by hand. The several mid-run stops that night, where the whole body went limp, were all caused by our own runner and hardware conditions (protection thresholds, power supply headroom, board thermal throttling), not by his model. After ruling out timing, power supply, joint directions and servo parameters one by one, it still did not produce a continuous gait, so we **decided to switch to his Rust runtime**, keeping the IMU as an off-the-shelf module on the board's I²C; see section 9.

This document is written for both humans and AI: every conclusion states "why", and every number can be found in the log files.

---

## 1. Why not just install his whole stack

kissqy's deployment package (R17 upgrade package, robotd v1.0.146) is **an upgrade layered on top of the official Microduck 0.15.1 system**, and it only accepts one hardware configuration:

| What his program requires | State of our robot at the time |
|---|---|
| Official 0.15.1 installed on the card first, then R17 | The card had our own Armbian image + servo-web + Python runner, no official runtime |
| IMU on the **servo bus**, ID 200, 5 bytes read from address 0 must be `06 00 00 00 F2` | IMU is a **BNO085 on the board's I²C** (`/dev/i2c-4`, address 0x4B) |
| Servos are not powered if the IMU cannot be read (`Feetech torque-on requires a fresh converged IMU`) | — |
| First install writes his prototype's calibration and marks it as calibrated | Every assembly is different and must be recalibrated |

His code has **no I²C IMU path**, so to his program the BNO085 is the same as having no IMU. The identity bytes of our own imu_to_dxl board (option A) are `0.2 / 0x4D44`; changing them to the values he expects only requires changing three macros in `protocol.h`, but the board has never been on a real bus.

**So what we did that night**: used his model, but ran it with the runner we used for Luwu on 10-04 (`tools/servo-web/run_luwu_trial.py`), adding a `kissqy_walk` profile. The observation (61 dims), joint order and standing pose HOME all match his deployment contract, checked item by item.

For the overall strategy for the two IMU setups, see [Feetech adaptation architecture](../software/飞特适配架构.md): A, the bus board; B, a BNO085 connected directly to the board; one or the other via configuration.

## 2. The model

- File: `Microduck-kissqy/microduck-hd1910/firmware/policies/walk/policy.onnx`, SHA-256 `1cbf8730eadd75a5704332c9f3c10f60bfa9412135b907831c9dbd731ce1795f`
- Task `Mjlab-VelStand-Rough-Backlash-MicroDuck` (joint walking + zero-velocity standing + fall recovery), 9600 iterations, official microduck_rl `8d0db749`
- 61 inputs, 14 outputs, 50 Hz; training command range forward ±0.4 m/s; training BAM actuator `kp_fw = 5`
- His package says `deployment_verified: false`; the README has a video on real hardware

## 3. Runtime parameters: what each does and why there are two sets

Every 20 ms the model outputs 14 numbers: **how many more radians to rotate each joint on top of the standing pose**. Before sending them to the servos, a few processing steps can be applied:

| Parameter | What it does (plain terms) | In training | kissqy runtime | Our switch |
|---|---|---|---|---|
| Action scale | Multiply the output by a factor before sending; 0.9 = actions at 90% | 1.0 | 0.9 | Default 0.9; `--training-mapping` uses 1.0 |
| Target filter (head 0.5 / legs 0.7) | Take only 70% of the new target and keep 30% of the previous frame's; smoother but half a beat late | No | Yes | On by default; off with `--training-mapping` |
| Voltage compensation 7.4/V | Higher voltage makes servos stronger, so actions are scaled down proportionally; about ×0.93 at 8.0 V | No | Yes | On by default; off with `--training-mapping` |
| Gains P/D | Servo "stiffness", written to SRAM addresses 50/51, restored to the original 32/40 at the end | P5 | P5 / D20 | Default P5/D20; `--kp N` changes P (5–16) |

**Why two sets**: kissqy's R17 notes state that 0.9 / 0.5 / 0.7 are **defaults he copied from the official duck runtime** (which the official team tuned for Dynamixel servos), while the model was actually trained with 1 / 1 / 1. Both sets are worth trying; the result on real hardware decides.

What his runtime (R17 robotd) does each frame, which we implemented the same way:

```
target = HOME + scale × raw_output × (7.4 / mean servo voltage)
target = α × target + (1−α) × previous target      # α: head 0.5, legs 0.7; no filtering on the first frame
"previous action" in the next frame's observation = raw output (not scaled, not filtered)
servo write: 6 bytes starting at address 42 [pos low, pos high, 0, 0, 0, 0], byte-for-byte the same as his
```

We also added a safeguard he does not have: targets are clamped to the training joint ranges (e.g. hip roll ±22°); it never triggered that night.

## 4. What happened that night

Preconditions: powered from an adjustable power supply, duck in the web console's "站" (stand) pose with torque on; before each run the program checks that all 14 joints are within 12° of the standing pose.

| # | Mode | vx (m/s) | P | Starting voltage | Result | Observations and cause |
|---|---|---|---|---|---|---|
| 1 | Read-only | 0 | — | 7.1 V | Completed | No servo writes. Period 20 ms, tilt < 4.3°, IMU orientation correct |
| 2 | Held by hand | 0 | 5 | 7.2 V | Completed, returned to standing normally | Changed pose once within 0.5 s, then did not move. **Velocity 0 = standing still, which is normal** |
| 3 | Held by hand | 0.05 | 5 | 7.1 V | Completed, returned to standing normally | Same as above, only a pose change |
| 4 | Held by hand | 0.15 | 5 | 7.1 V | Stopped at frame 2, whole body went limp | Servo 20 read 4.0 V. Only this one servo was logged; cause undetermined |
| 5 | Held by hand | 0.15 | 5 | 7.2 V | Ran the full 10 s, went limp at the end | Right knee bent 13° and right ankle 9°, then no movement; when returning to standing it sagged more than 1° at P5, was judged "not holding" and torque was released |
| 6 | **On the ground, unsupported** | 0.15 | 5 | 7.1 V | Stopped at 0.46 s, whole body went limp | **Within 0.4 s both legs started alternately bending and extending**; all 14 voltages dropped together to 6.5–6.6 V, below the 6.6 V protection line; after stopping, holding in place was also refused because of voltage, so torque was released |
| 7 | On the ground, unsupported | 0.15 | 5 | **7.7 V** (power supply raised) | **Ran the full 10 s, returned to standing normally** | Swayed back and forth for the first 3 s (the user described it as "wobbled a few times like it had polio"), then stayed in a half squat; minimum 7.6 V |
| 8 | On the ground, unsupported | 0.15 | **10** | 7.7 V | Stopped at 0.24 s, whole body went limp | Summed current readings about 26 A, voltage dropped to 5.4–5.8 V; after stopping the duck was still moving, the deviation exceeded 1° and it was judged not holding, so torque was released |
| 9 | On the ground, unsupported, exactly as in training | 0.15 | 5 | 7.7 V | Stopped at 0.28 s, **held in place** (the modified protection worked) | No filtering, the first action was big and violent; all 14 voltages dropped together to 4.6–5.2 V |
| 10 | Same + **1 s soft start** | 0.15 | 5 | 7.7 V | Ran the full 10 s, returned to standing normally | Minimum 7.5 V; the soft start suppressed the start-up current; right knee bent 14° and then basically did not move. **Median control period 25 ms** (board thermal throttling, see below) |
| 11 | Same + joint velocity one frame late, web service stopped | 0.15 | 5 | 7.6 V | Stopped at 2.3 s, held in place | Period back to an exact 20 ms; once actions reached full size the summed current readings were about 26 A and the voltage dropped to 4.6–5.5 V |
| 12 | — | — | — | — | Refused to start twice, no movement | Stuck in a half squat, left knee 12.7° from the standing pose, above the 12° threshold. Slowly returned to the standing pose with the new tool `stand_home.py` (error ≤ 0.9°) |
| 13 | On the ground, unsupported, his runtime parameters + soft start + velocity one frame late | 0.15 | 5 | 7.7 V | Ran the full 10 s, returned to standing normally | **The run with the best conditions that night**: period 20.2 ms, CPU 1.8 GHz, minimum 7.6 V. Still changed pose once and then stayed in a half squat (right knee 12.8°, left knee 6°), no continuous gait |

Log files are on the board at `/home/duck/policy-trial/kissqy-trial-*.json`; each frame has the observation, raw output, target, and position/voltage/current of all 14 servos. The current is the servos' self-reported reading; the sum is not the power supply's actual output and is only useful for relative magnitude.

## 5. Understanding (why this happens)

1. **A walking policy cannot be tested with the body held by hand.** The model's input has no "phase/clock"; stepping relies on body sway and weight shift, brought out through IMU and joint feedback. With the body held, it does not sway, and the output quickly converges to a static pose. Runs 2–5 were all like this; in run 6, once let go, it started alternating within 0.4 s. **Test walking models on the ground, with hands only loosely guarding.**
2. **"Goes limp as soon as it moves" was caused by our runner's protections.**
   - The 6.6 V undervoltage line was set for small motions on the test bench; walking draws a lot of current, and with a 7.4 V supply the servo side drops to 6.5 V and triggers it.
   - After holding in place, the position deviation is checked to be ≤ 1°, but a duck that is moving or sagging at P5 cannot meet that, so it ends up releasing torque on the whole body.
   - Changed: the hold and recovery phases no longer release torque due to low voltage; the hold check is relaxed to 5°. Whether the return to standing reached its target is still judged at 1°.
3. **Leave headroom in the power supply.** After raising it to about 8.0 V, run 7's minimum over the full 10 s was 7.6 V. The HD-1910's upper limit is 8.4 V, and kissqy's training power supply range is 7.4–8.0 V.
4. **Increasing the gain pulls the current up.** At P10 the current readings multiplied several times, the adjustable power supply could not cope and the voltage collapsed to 5.4 V. P cannot simply be increased; if you do, try 6–8 first.
5. **At P5 the legs cannot keep up.** When held by hand, target and actual were consistently 6–7° apart; on the ground in run 7 it swayed for the first 3 s and then squatted in place. This is currently the biggest unsolved problem. Possible causes: P5 not having enough force to overcome the load, a gap between the real servo and the servo model in the BAM simulation, the 0.9/0.5/0.7 runtime parameters, or differences in latency and noise between the BNO085 and his LSM6DSV16X. These have not been separated yet.

6. **The board throttled due to overheating, slowing the control rhythm.** That night the board CPU was at 84–87°C (throttling thresholds 75 / 85°C, shutdown at 115°C), and the frequency was locked at the lowest step of 408 MHz (max 1800). The main cause was the web service `server.py` permanently occupying a whole core (top showed 100%), with the board mounted inside the body. Consequence: when running on the ground, the median control period was 25 ms (about 40 Hz) and the slowest sensor read 20 ms, while the model was trained for 50 Hz. After stopping the web service, the period returned to 20.2 ms. The crash right after boot may also have been related to overheating.
7. **With the rhythm right and actions at full size, the adjustable power supply became the bottleneck again.** Exactly as in training (no scaling, no filtering) and with an accurate period, after about 2 seconds the summed current readings reached 26 A and the voltage dropped to 4.6 V. With his 0.9 / 0.5 / 0.7, it stayed above 7.6 V throughout. The soft start only solves the initial kick.
8. **Still does not walk after ruling out directions, servo parameters, rhythm and power supply.** The remaining differences are all in the runtime layer: the Python runner vs his Rust robotd, and a BNO085 read asynchronously over I²C vs an LSM6DSV16X read in the same bus transaction as the servos. The user decided to use his Rust program directly, removing the variable of "whether our runner is written correctly".

### 5.1 Suspicions ruled out

- **Joint directions**: for the 8 joints whose standing angle is close to 0 (left and right hip yaw, left and right hip roll, left and right knee, head yaw, head roll), a reversed direction cannot be seen from the standing pose. With the new tool `joint_direction_check.py`, each was rotated +8° in turn, and the user visually confirmed that all 8 match the MJCF axes. The other joints have non-zero standing angles, so a correct standing pose already shows their directions are correct.
- **Servo parameters** (read-only health check with `servo_report.py`, 15/15 online, report saved at `software/training/artifacts/hd1910_bench_20261011/kissqy-walk/体检-20261011-130324.md`): all 15 have identical settings: firmware 3.46, mode 4, EEPROM and SRAM P/D/I all 32/40/0, max torque and torque limit 1000, dead band ±1, minimum startup torque 12, acceleration 0, running speed 3000, angle limits fully open 0–4095, voltage protection 4.0–10.0 V. None is force- or speed-limited, so "the legs cannot keep up" is not due to a wrong parameter on some servo.
- The two items flagged red in the health check do not affect tonight's test but need to be dealt with: the unload conditions only enable overheating (19 = 4), with overcurrent and voltage protection off (this is how servo 21 burned out); the large offsets are spline tooth misalignment from mounting the servo horns, already absorbed by calibration, not a fault.

## 6. How to run it yourself

Preconditions: power supply at about 8.0 V; web console in "站" (stand); duck on the ground with hands loosely guarding. Log in to the board:

```sh
sudo python3 /home/duck/policy-trial/run_luwu_trial.py --profile kissqy_walk --execute --supported --vx 0.15 --seconds 10
```

| Add | Effect |
|---|---|
| `--vx 0.1` | Forward speed 0–0.15 (the Luwu profile is still limited to 0.05) |
| `--seconds 10` | Duration, at most 10 |
| `--training-mapping` | Exactly as in training: scale 1.0, no filtering, no voltage compensation |
| `--kp 8` | Temporary P, 5–16; P10 already brought the adjustable power supply down |
| Without `--execute --supported` | Read-only, no servo writes |
| `--inspect-model` | Only checks the model, does not touch the hardware |

Note: when Clash's TUN mode is on on your computer, neither `ssh` nor the web console can reach the board; see the [pitfall log](../踩坑记录.md#软件).

## 7. Next steps (decided: switch to his Rust runtime)

- **Add an "IMU on the board's I²C" option to his robotd** (option B, BNO085 first, then the LSM6DSV16X module), selected by configuration; his native bus board (option A) stays the untouched default. Document and categorize both so replica builders can use whichever they have
- Cross-compile his robotd in WSL (`cargo board`), first building it unchanged, then the version with the I²C IMU
- New card with official 0.15.1 → upgrade to R17 via his web console → swap in the robotd with I²C IMU → calibrate the 15 joints and the IMU orientation with his procedure → Start walking
- Hardware: board cooling (open shell or a fan); power the servos from a 2S lithium battery, or use short thick power wires plus a larger capacitor
- Keep this card (servo-web + Python runner) as a backup; after testing, enable overcurrent and voltage protection on all servos

## 8. Code changes in this session (local, not pushed)

All in `tools/servo-web/`; 60 offline tests pass; uploaded to the board and checksums verified:

- `run_luwu_trial.py`: added the `kissqy_walk` profile (model hash, HOME, execution parameters, joint ranges), `--kp`, `--training-mapping`; kissqy's speed limit raised to 0.15; log file name `kissqy-trial-*.json`
- `luwu_policy_trial.py`: scaling, separate head/leg filtering, first-frame passthrough, voltage compensation, joint clamping and temporary gains are now all driven by the profile; on abnormal voltage, the readings of all 14 servos are logged; the hold/recovery phases no longer release torque on low voltage; hold check at 5°
- `joint_direction_check.py` (new): rotates each joint +N° (default 8°) in the model frame and back, with the log stating which direction you should see; only writes target positions, does not touch gains/EEPROM/torque
- `luwu_policy_trial.py` additionally gained: soft start (`ramp_seconds`, kissqy default 1 s, adjustable with `--ramp`) and joint velocity one frame late (following his robotd's `delay_velocity`)
- `stand_home.py` (new): slowly returns from the current pose to the policy standing pose HOME at 20°/s, for when the program refuses to start because it is "too far from the standing pose"; the web service must be stopped first
- All run logs and health check reports from that night: `software/training/artifacts/hd1910_bench_20261011/kissqy-walk/` (about 22 MB, kept locally, not yet uploaded to the repo)
- On-robot package: `Microduck/上机包-kissqy-walk/` (not in the repo)
