# HD-1910 Pre-Training Data Checklist · Filled-In Version

**English** · [简体中文](HD-1910训练前数据清单.md)

> The collection checklist from the algorithm side (2026-09-11, single-servo version). This version **fills in all the numbers that already exist in the repo and states their sources**; whatever really needs a test rig is marked **to be measured**.
> The algorithm side should not receive an empty table: geometry, mass, inertia, joints, servo specs and IMU mounting have long been in the repo.

**Tags**: [MJCF] upstream `robot_walk.xml` · [Spec sheet] Feetech "HD-1910-C001 Serial Type Specification" rev. A/0 · [Source] upstream `duck-control/src/model.rs` · [Reverse eng.] [Hardware reverse engineering](hardware-teardown.en.md) · [STL] measured from the repo STLs · **to be measured**

> ⚠️ **All geometry, mass and inertia values are simulation values for the XL330 version.** After switching to Feetech, at least four things differ:
>
> | | XL330 | HD-1910 | Impact |
> |---|---|---|---|
> | Mass per unit | 18 g | **21 g** | +45 g for 15 servos, center of mass of each rigid body shifts |
> | Outer dimensions | 20 × 34 × 26 | **34 × 20 × 23** | 3 mm thinner; structural parts at the leg clamps have been modified |
> | Stall torque @7.4V | 0.6 N·m | **1.47 N·m** | Re-identify the BAM model |
> | Gear ratio / backlash | Not published | **320:1 / ≤0.5°** | Re-measure friction and backlash models |
>
> **After assembly, overwrite the numbers here with actual weighed and measured values**: the size of the differences is the reason for retraining.

---

## 1. Static data

### 1. Robot geometry: zero-position pose, trunk frame (X forward · Y left · Z up), mm

| Item | Value | Source |
|---|---|---|
| **Distance between hip centers** | Hip **yaw** axis spacing **35.0**; hip **pitch** axis spacing **85.0** (use this one for leg kinematics) | [MJCF] forward kinematics |
| **Left / right thigh** (hip pitch → knee) | **42.2** / **42.2** | [MJCF] |
| **Left / right shank** (knee → ankle) | **49.4** / **49.4** | [MJCF] |
| Hip yaw → roll / roll → pitch | 20.7 / 31.1 | [MJCF] |
| **Sole dimensions** (`sole_left`, printed part bounding box) | Length **54.0** × width **41.1** × thickness **12.9** | [STL] left/right symmetric; the actual contact surface is the bottom of the foot + sole assembly |
| **Trunk dimensions** (`01_躯干主体` assembly bounding box) | Length **86.1** × width **81.3** × height **64.0** | [STL] includes shell and hip servos |
| Battery (NP-F550) position | X −55.3 … −16.7, Y ±10.3, Z −39.3 … +31.6 → center **(−36, 0, −4)**, 39 × 21 × 71 | [Reverse eng.] measured after MJCF transforms |
| `imu_to_dxl` board position | At the `banana_pcb_locker` clip, X −32.3 … −28.5, Y ±27, Z +31.5 … +38.1, **mounted vertically** | [Reverse eng.] |
| Main controller Radxa + adapter board | *Measure after assembly*: in a no-HAT build the position is up to you | **to be measured** |

**Joint axis positions and directions** (zero-position pose, trunk frame):

| Joint | Center X / Y / Z | Axis | Joint | Center X / Y / Z | Axis |
|---|---|---|---|---|---|
| `left_hip_yaw` | 6.0 / 17.5 / −5.0 | −Z | `right_hip_yaw` | 6.0 / −17.5 / −5.0 | −Z |
| `left_hip_roll` | 22.5 / 17.5 / −17.5 | +X | `right_hip_roll` | 22.5 / −17.5 / −17.5 | +X |
| `left_hip_pitch` | 4.0 / 42.5 / −17.5 | +Y | `right_hip_pitch` | 4.0 / −42.5 / −17.5 | −Y |
| `left_knee` | −31.8 / 38.5 / −39.5 | −Y | `right_knee` | −31.8 / −38.5 / −39.5 | +Y |
| `left_ankle` | −31.8 / 64.5 / −81.5 | +Y | `right_ankle` | −31.8 / −64.5 / −81.5 | −Y |
| `neck_pitch` | 26.0 / 14.5 / 32.4 | −Y | `head_yaw` | 26.0 / 0.0 / 101.1 | +Z |
| `head_pitch` | 26.0 / 14.5 / 82.4 | +Y | `head_roll` | 8.1 / 0.0 / 115.6 | −X |

The pitch / knee / ankle axes of the left and right legs have **opposite signs**: mirrored assembly, defined this way in the MJCF. Use this table when checking directions with a +5° move on the real robot.

### 2. Mass, center of mass and inertia: [MJCF] XL330 version simulation values

| Rigid body | Mass g | Center of mass (trunk frame mm) | Corresponds to in the algorithm checklist |
|---|---|---|---|
| `trunk_base` | **199.2** | −22.6 / 0.0 / 2.8 | Trunk |
| `yaw2roll` ×2 | 23.0 | 7.0 / ±17.5 / −21.9 | Hip yaw part (including servo) |
| `hip_l` ×2 | 6.2 | 14.2 / ±32.3 / −17.5 | Hip roll part |
| `upper_leg_left/right` | **48.2** | −18.9 / ±56.0 / −24.3 | **Thigh** |
| `leg` / `leg_2` | **21.6** | −31.8 / ±48.0 / −71.4 | **Shank** |
| `ankle_left/right` | **30.0** | −25.6 / ±48.8 / −95.2 | **Foot** |
| `neck` | 36.8 | 26.0 / 0.3 / 57.4 | Head and neck ┐ |
| `neck_pitch` | 5.7 | 26.0 / 0.0 / 94.1 | Head and neck │ total **279.9** |
| `yaw_roll_motion` | 48.6 | 25.8 / −5.0 / 118.9 | Head and neck │ |
| `jaw_soft` | 188.8 | 40.6 / 1.2 / 120.2 | Head and neck ┘ (includes head shell, camera, and the BMI088 on the HAT) |
| **Whole robot** | **737.1** | | Consistent with the 737 g in [actuator selection](actuator-selection.en.md) |
| Battery NP-F550 | *To be weighed* (typically ~100 g; whether it is already included in trunk_base is **to be checked**) | | |

**Moments of inertia** (kg·m², about each rigid body's own center of mass, MJCF `fullinertia` order Ixx Iyy Izz Ixy Ixz Iyz):

```
trunk_base       1.240e-4  1.459e-4  1.154e-4   7.2e-8  -2.07e-5   1.3e-7
upper_leg_left   1.688e-5  1.037e-5  1.983e-5  -4.42e-6  2.28e-7   3.89e-7
leg              5.251e-6  2.155e-6  4.339e-6   0        0         7.65e-7
ankle_left       5.915e-6  1.115e-5  7.740e-6  -2.05e-7  8.2e-8    5.7e-8
yaw2roll         4.196e-6  3.418e-6  2.327e-6   0        0        -5.1e-8
hip_l            8.606e-7  1.158e-6  6.516e-7   0        3.90e-7   0
neck             1.729e-5  3.127e-6  1.637e-5   0        0         0
neck_pitch       1.092e-6  9.669e-7  5.121e-7   0        0         0
yaw_roll_motion  6.979e-6  8.103e-6  9.579e-6   3.22e-7 -3.5e-8    3.43e-7
jaw_soft         3.208e-4  2.541e-4  1.499e-4  -6.3e-7   6.57e-6   4.18e-6
```

Right-side rigid bodies are symmetric (Ixy and Iyz change sign). **After the HD-1910 assembly**: scale by the actual weighed masses, or recompute the mass properties using our colleague's SolidWorks assembly ([microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad)).

### 3. Calibration of the 14 policy joints

Action index = index into the policy's 14-dimensional output ([Source] `JOINT_NAMES` order; the mouth is not included). Default standing angle = [Source] `DEFAULT_POSITION`. Safety limits = [MJCF] `range`.

| Index | Joint | Servo ID | Positive direction | Encoder zero | Software offset | Default standing angle | Mechanical min | Mechanical max | Safety min | Safety max |
|---:|---|---|---|---|---|---|---|---|---|---|
| 0 | `left_hip_yaw` | **20** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+0.0°** | *To measure* | *To measure* | -25° | 30° |
| 1 | `left_hip_roll` | **21** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **-5.0°** | *To measure* | *To measure* | -22° | 22° |
| 2 | `left_hip_pitch` | **22** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **-26.2°** | *To measure* | *To measure* | -90° | 90° |
| 3 | `left_knee` | **23** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **-0.3°** | *To measure* | *To measure* | -90° | 90° |
| 4 | `left_ankle` | **24** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+26.0°** | *To measure* | *To measure* | -90° | 90° |
| 5 | `neck_pitch` | **30** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+20.0°** | *To measure* | *To measure* | -90° | 60° |
| 6 | `head_pitch` | **31** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+20.0°** | *To measure* | *To measure* | -90° | 90° |
| 7 | `head_yaw` | **32** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+0.0°** | *To measure* | *To measure* | -170° | 170° |
| 8 | `head_roll` | **33** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+0.0°** | *To measure* | *To measure* | -25° | 25° |
| 9 | `right_hip_yaw` | **10** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+0.0°** | *To measure* | *To measure* | -30° | 25° |
| 10 | `right_hip_roll` | **11** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+5.0°** | *To measure* | *To measure* | -22° | 22° |
| 11 | `right_hip_pitch` | **12** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+26.2°** | *To measure* | *To measure* | -90° | 90° |
| 12 | `right_knee` | **13** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **+0.3°** | *To measure* | *To measure* | -90° | 90° |
| 13 | `right_ankle` | **14** | *To calibrate (+5° check)* | 2048 (after center calibration) | 0 (after calibration) / official `motor.rs` to be read | **-26.0°** | *To measure* | *To measure* | -90° | 90° |

**Zero position definition**: the robot standing straight (legs as straight columns, feet flat, neck vertical, head looking level) = all joints 0 = servo 2048. The standing angles are offsets added to the zero position, **not the zero position**. For the calibration steps, see [debug log · step 9](../DEBUG-LOG.en.md).

The mouth (ID 34) is not part of the policy: closed −5° / open +30° ([Source] `MOUTH_CLOSED / MOUTH_OPEN`).

### 4. HD-1910 basic parameters: [Spec sheet] A/0, 7.4 V rating (6 V in parentheses)

| Item | Value |
|---|---|
| Exact model | **HD-1910-C001** (the mechanical drawing says HD-1910M-C001, 2026-09-02) |
| Operating voltage | **4 – 8.4 V** ⚠️ a fully charged NP-F550 at 8.4 V is right at the limit |
| Encoder resolution | **4096** counts/rev (12-bit magnetic encoder, 0.088°/step) |
| Gear ratio | **320 : 1** |
| Gear backlash | ≤ 0.5° (vendor value; for measured backlash see 2.5) |
| Communication protocol | Feetech SCS/STS serial bus, half-duplex TTL single wire, 8N1, frame header `FF FF` |
| Baud rate | **1,000,000** bps (factory default; range 38400 – 1M) |
| Control mode | **Mode 4 "pure position PD (Sim2Real)"** (factory default); also 0 angle servo / 1 constant speed / 2 constant current / 3 PWM (as written in the spec sheet; the generic STS memory table has 2 PWM / 3 stepper; the values read back from the actual servo take precedence) |
| P / I / D gains | Registers **21 / 23 / 22** (generic STS). Default values **to be read from the servo**; official XL330 firmware kp = 200, for reference |
| Maximum speed | No-load **113 RPM = 11.8 rad/s** @7.4V (92 RPM @6V); firmware speed-limit register 46 (target speed) **to be read** |
| Maximum PWM / output | Register 16 "max torque", in 0.1% units, default 1000 = 100% **to be read** |
| Maximum current | Overcurrent protection **off by default**, threshold default 0.5 A / 2 s, configurable; stall **2.0 A** @7.4V (1.6 A @6V); rated 900 mA (690 mA) |
| Kt | 7.5 kg·cm/A (0.74 N·m/A) |
| Stall torque | **15 kg·cm = 1.47 N·m** @7.4V (12 kg·cm @6V); rated 3.7 kg·cm = 0.363 N·m |

**Conversions** (STS series memory table conventions; **for the HD-1910, each item still to be checked against spec sheet section 7-x or by reading the servo**):

| Quantity | Register | Conversion |
|---|---|---|
| Position | 56 (current) / 42 (target) | rad = (raw − 2048) × 2π / 4096 |
| Speed | 58 (current) / 46 (target) | raw is steps/s, bit 15 is direction → rad/s = raw × 2π / 4096 |
| Load | 60 | **Dimensionless**, 0.1% of full torque, bit 10 is direction (0–1000 → 0–100%) |
| Current | 69 | **6.5 mA/unit** on the STS3215; **HD-1910 to be checked** |
| Voltage | 62 | **0.1 V** /unit |
| Temperature | 63 | **1 ℃** /unit |
| Enable | 40 | 1 on, 0 off. The memory table says "write 128 = center calibration", but **the HD-1910 (firmware 3.46) does not accept it in testing**: on 2026-09-20, four rounds on 15 servos, writing 128 while unlocked with torque off did not change a single offset, yet the servos still replied success. The table in protocol manual section 4.9 also says HLS ≥3.43 "does not support writing 128". Zero calibration uses the **0x0B position calibration instruction** (optionally with a set value); see [servo-web](../tools/servo-web/) |

### 5. IMU and soles

| Item | Value | Source |
|---|---|---|
| IMU model | **LSM6DSV16X** (custom `imu_to_dxl` board, bus ID 200, quaternion from SFLP hardware fusion) | [Reverse eng.] |
| Mounting orientation | Chip **+Z → trunk +X**, chip +Y → trunk +Y, chip −X → trunk +Z (+90° about Y); board mounted vertically, component side facing forward | [Reverse eng.] upstream `SflpDecoder` mount |
| Mounting position | MJCF `imu` site in the trunk frame **(−21.0, 0.1, −14.7)**; the physical board is at the clip, X ≈ −30, **measure after assembly** | [MJCF] [Reverse eng.] |
| Sole material | Printed parts `sole_left/right`, **material per the print settings** (not specified officially; only jaw / mouth are TPU) | [BOM] |

---

## 2. Dynamic data: all **to be measured**; test rigs and prerequisites below

### 1. BAM single-servo pendulum identification

The four trajectories (`sin_time_square` / `lift_and_drop` / `up_and_down` / `sin_sin`) are the standard excitations of the [BAM](https://github.com/Rhoban/bam) tool. The official XL330 uses the BAM **M6** model, with parameters ([Reverse eng.] `microduck_constants.py`): `kp_fw=200`, `vin_range=(6.5, 8.2)`, `vin_min=6.0`, `delay 3–6 steps`.

**Recommended combinations** (based on the 2S battery operating range and the official conventions):

| | Value | Rationale |
|---|---|---|
| Voltage ×3 | **6.6 / 7.4 / 8.2 V** | Battery empty / nominal / full (avoiding the 8.4 limit) |
| P ×4 | Servo default / 100 / **200** / 300 | 200 matches the official XL330 firmware |
| Pendulum length ×2 | 0.10 / 0.15 m | Same order of magnitude as the leg length (42 + 49 mm) |
| Load ×3 | 0 / 0.05 / 0.10 kg | One leg ~100 g |
| Sampling | **50 Hz** (same as the control period), 20 s per segment | |

**Test rig**: URT-2 + adjustable power supply (7.4 V, 2 A limit) + pendulum arm + recording script. For each sample record `timestamp / goal_position / position / speed / load / input_volts / torque_enable / temperature`: registers 42 / 56 / 58 / 60 / 62 / 40 / 63, reading 56–63 as one consecutive 8-byte read.

### 2. Step response · 3. Voltage response · 4. Low speed · 5. Backlash · 6. Repeatability

Same test rig. **Backlash** needs an external angle reference: a phone spirit-level app taped to the pendulum arm, or a protractor; the encoder is on the gear output side and cannot measure its own clearance.

**Do these two first, they are the cheapest**:
- Step ±10°, repeated 5 times → command latency, rise time, overshoot
- Backlash ±1° / ±2°, repeated 5 times → compare against the vendor's ≤0.5°

### 7. Control and communication timing

Needs the main controller running: the official `robotd` prints a summary every 5 minutes (achieved frequency, jitter, bus occupancy, error counts), and `bench_dynamixel_bus` tests the bus on its own. **In a no-HAT build with a third-party adapter board, this is the first number to look at**: a non-zero error rate means the adapter board's direction switching cannot keep up with 1 Mbps.

### 8. Power and voltage drop

Five-condition table; requires a shunt or clamp meter on the battery positive. **Record at both the battery terminals and the servo bus at the same time**; the difference is the voltage drop across wiring + fuse + connectors.

### 9. IMU data

Requires the `imu_to_dxl` board to arrive and its firmware to be written. Stationary for 60 s, read ID 200 registers 124–136 (gyro 3 × i16 + quaternion 3 × fp16). For the orientation check, use the mount quaternion from section 5, tilt 10° forward, backward, left and right, and look at the sign of the projected gravity.

### 10. Sole friction

**Can be done right now**: the printed feet are already in hand. Inclined-plane method: put the foot on the floor and slowly raise it, measure the angle at the moment it slides, μ ≈ tan θ. 5 times each on wood floor / tile / carpet.

---

**Change log**: 2026-09-12 first version, filled in starting from the algorithm side's empty table. Overwrite item by item after hardware measurements on the assembled robot; when overwriting, change [MJCF] to [Measured] and record the date.
