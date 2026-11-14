# Debug Log

**English** · [简体中文](调试记录.md)

> **Current status: the HAT has arrived and is plugged onto the board; the board is currently running Radxa's official B1 image, Wi-Fi / SSH work, and after reseating the camera ribbon cable a 1920×1080 frame has been captured.**
> Last updated: 2026-09-28. The current official system is used for camera comparison; the project runtime has not been restored yet. The original Armbian has not been retested with the correct wiring.

The [build log](BUILD-LOG.en.md) covers the **mechanical** side: printing, test fitting, tolerances.
This document covers the **electrical and software** side: first a **step-by-step manual** (how to configure, wire and test the parts once they arrive), then a **dated log of the process** (what was done, what was observed, what comes next).

Conclusive pitfalls are collected separately in [Pitfalls](PITFALLS.en.md). What the boards and chips are, and why they were chosen, is in [Hardware primer](docs/hardware-primer.en.md).

---

## Progress

| Date | Stage | Status | Notes |
|---|---|---|---|
| 2026-09-10 | Servos + debug board arrived | ⚠️ Problem | Debug board TTL port does not match the servo's 2.0 mm cable |
| 2026-09-12 | Controller, ToF, battery, battery holder, SD card, pin headers, camera all arrived | ✅ Done | Pin headers soldered onto the Radxa |
| 2026-09-12 | Mounting servos into the mechanical parts | ✅ Done | **HD-1910 differs structurally from the XL330**; fits after modifying and reprinting parts |
| 2026-09-13 | Assigning IDs to all 15 | ✅ Done | Cut a servo cable and jumper-wired it to the URT-2, configured one at a time |
| 2026-09-13 | Bench bus bring-up (URT-2 ↔ Radxa) | 🔨 In progress | 7.4V power into the URT-2, USB into the Radxa host port |
| 2026-09-16 | Bare controller board power-on | ✅ Done | No anomalies |
| 2026-09-16 | Flashing the controller (2G board / microSD) | ❌→✅ | Official Armbian image won't boot on the V1.12 board (bootloader); booted on 09-17 after switching to the Radxa bootloader, see below |
| 2026-09-17 | Official scripts setup-board / migrate-network / install | ✅ Done | ttyS2, NetworkManager, ONNX Runtime, daemon 0.13.0 |
| 2026-09-17 | All 15 servos of the full robot on the bus (URT-2 ↔ PC) | ✅ Done | 0 timeouts, 0 checksum errors, sync read of 15 servos in 4.8 ms; the hour-long hold-up was the URT-2 power-up order |
| 2026-09-17 | Web debug console `tools/servo-web/` | ✅ Done | Sliders, poses, sequences, 3D follow, center-of-mass display, register export |
| 2026-09-18 | Zeroing, standing pose, tucked ↔ stand-up sequence | 🔨 In progress | Can stand up and sit down on its own ([video](assets/首次上电-2026-09-18.mp4)); 4 servos still need zero recalibration, the 4 with reversed direction are flipped with ± on the page |
| 2026-09-17 | `imu_to_dxl` board arrived, powered on | ✅ Done | 3.3 V OK. J4/J5 connector pitch is right but **the housing doesn't match the Feetech cable**; plugs in after shaving the housing, v2 will change the connector |
| 2026-09-22 | `imu_to_dxl` Feetech-protocol firmware 0.2.0 | ✅ Desk-verified / ⚠️ Real bus untested | Flashed to the dev board, IMU working; acceptance scope in the [firmware notes](hardware/imu_to_dxl/firmware/) |
| 2026-09-28 | HAT arrived, plugged in, board power-on debugging | 🔨 In progress | Checking board → camera item by item; this is not an acceptance check of HAT audio, the servo bus or load |
| 2026-09-28 | Replacing the broken ID 21 and centering it | ✅ User-confirmed | The former mouth servo ID 34 is now ID 21; user confirmed 2048 calibration succeeded in FD; mouth currently missing |
| 2026-09-28 | Comparison with the official B1 image | ✅ Done | Wi-Fi / SSH tested, Radxa Camera 8M overlay enabled |
| 2026-09-28 | Camera detection and image capture | ✅ Short capture passed | After reseating the ribbon cable, `0x0219` is read, 40 frames at 1920×1080; sustained frame rate and project integration untested |
| — | No-HAT build: jumper wires to the controller | 📋 Fallback plan | Going with the HAT that has already arrived for now; the jumper-wiring doc is kept |

Legend: 📋 Planned · 🔨 In progress · ✅ Done · ⚠️ Problem · ❌ Dead end

---

## What's on hand

| Item | Qty | Status |
|---|---|---|
| Feetech HD-1910-C001 | 15 originally bought | Original ID 21 broken, mouth ID 34 reassigned as ID 21; the mouth is currently missing, so "all 15 online" can no longer be assumed |
| Feetech FE-URT-2 debug board | 1 | ✅ Arrived 2026-09-10 |
| Radxa Zero 3W 2 GB (bare board, no eMMC) | 1 | ✅ Arrived 2026-09-12, **pin headers soldered** |
| Radxa Zero 3W 8 GB + 64 GB eMMC | 1 | 📦 End of month |
| NP-F550 battery + battery holder | — | ✅ Arrived 2026-09-12 |
| VL53L8CX ToF | 1 | ✅ Arrived 2026-09-12 |
| Radxa Camera 8M219 (IMX219) | 1 | ✅ Detected and producing images under official B1, 2026-09-28 |
| RPI Robot HAT | 1 | ✅ Arrived and plugged in; peripherals being debugged one by one |
| High-endurance microSD | — | ✅ Arrived 2026-09-12 |
| 2×20 pin header | — | ✅ Arrived and soldered |
| `imu_to_dxl` PCB + SMT | 5 | ✅ Arrived 2026-09-17, ¥629.72; 3.3 V OK at power-on, connector footprint has a problem |
| Card reader, 5 V buck module | — | ✅ Arrived 2026-09-16 |
| Adapter cables, half-duplex adapter board | — | 📋 To buy (URT-2 stands in on the bench for now) |

---

## Where to find Feetech resources

The local `飞特-HD1910/` folder only has the datasheet PDF, DWG and STP. **The software and manuals are on Gitee, not on the official website**:

| What you need | Where |
|---|---|
| **FD debug software** + **CH340 driver** | **Already in this repo: [`tools/飞特/`](tools/飞特/)** (FD 1.9.8.5 + driver, MIT, with sha256). Original source: [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug) |
| Example code / communication protocol / memory table | The repos under [gitee.com/ftservo](https://gitee.com/ftservo) |
| Official website software page (backup) | [feetech.cn/software.html](https://www.feetech.cn/software.html) |
| Getting-started tutorial PDF | [先看这里-入手教程 (Read this first: getting-started tutorial)](https://www.feetech.cn/Data/feetechrc/upload/file/20220618/%E5%85%88%E7%9C%8B%E8%BF%99%E9%87%8C-%E5%85%A5%E6%89%8B%E6%95%99%E7%A8%8B2-1.pdf) |

---

## Servo configuration · step by step once the parts arrive

**Goal**: give each of the 15 HD-1910s its ID, enable the protections and stick on a label, so that during assembly you know which joint a servo belongs to just by picking it up.

### What you need

| Item | Notes |
|---|---|
| HD-1910-C001 × 15 | Factory ID is **1 on all of them** |
| FE-URT-2 debug board + USB-C cable | Use the two white 3-pin ports on the left (silkscreen `TTL-Bus`, `G V1 S`). The 4-pin port on the right is RS485, not used |
| One cut servo cable | The debug board's ports **don't accept** the servo's 2.0 mm cable, so you have to jumper-wire it. Sacrifice one of the 15 cables |
| Power | Pick one of three, see Step 3. **For ID assignment only, USB is enough** |
| Software | [`tools/飞特/`](tools/飞特/): FD 1.9.8.5 + CH340 driver, Windows |
| Multimeter | Measure voltage, check pin order |
| Label paper + pen | Used in Step 7 |

### Step 1 · Install the software

```
1  Plug in the URT-2 → under "Ports" in Device Manager, USB-Enhanced-SERIAL CH343 (COMx) appears; note the number
   The URT-2 is a CH343; Win10/11 has a built-in driver, nothing to install. Only if it doesn't show up, install tools/飞特/CH340_URT.rar (for the older URT-1)
2  Extract tools/飞特/FD1.9.8.5(250729).7z → run it directly, no installation needed
```

### Step 2 · Jumper wiring

Cut a servo cable: one end has the 2.0 plug, the other end three bare wires. **Go by pin number, not by color**:

```
Servo cable                  URT-2
Pin 1  Signal / TTL    →    S     solder to the S-pin pad of the white port on the back of the board (temporary: tin the wire end and insert into the S hole of the white port)
Pin 2  Vcc             →    V1    blue screw terminal
Pin 3  GND             →    G     blue screw terminal
```

- **The middle wire is always V**; Feetech and Dynamixel agree on this. Only getting V wrong will burn something
- Swapping S and G **won't burn anything**, the servo just won't be found; swap them back
- Pin 1 is marked with a small triangle or notch on the plug, or see the silkscreen next to the connector on the servo body

### Step 3 · Power

**The DIP switch on the URT-2 selects the TTL signal level (3.3 / 5 V); it is not a power selector.** Set it to 5 V (the HD-1910 accepts 2–5 V, plenty of margin).
With USB plugged in, the V1 terminal carries 5 V (measured 2026-09-12). On 2026-09-17 I checked the manufacturer's documentation: the URT-2 has two screw terminals; **V1 is the external power input for the TTL bus, rated DC 4.8–12 V**; V2 is for RS485, DC 12–24 V. The wiring photo in the URT-1 manual shows USB and external power connected at the same time. Since the spec allows 12 V into V1, V1 cannot be directly connected to USB 5 V; there must be diode isolation, and 5 V is only fed to V1 when USB alone is plugged in. So both wiring options work:

| Source | How to wire | When to use |
|---|---|---|
| **USB 5 V** | Connect nothing, V1 has 5 V on its own | **Assigning IDs, changing parameters**. The HD-1910 works from 4 V, enough with no load |
| Adjustable switching supply / battery → **V1 terminal** | + to V1, − to G, plug the servo cable straight into the TTL-Bus port. The manufacturer's standard wiring | All 15 together, bench |
| Adjustable switching supply / battery → servos | + directly to servo V, − to servo G **and** URT-2 G (common ground), V1 left unconnected | When you don't want current through the URT-2's terminals and traces (15 stalled servos can reach over ten amps; the terminals are rated 6 A) |

⚠️ Don't exceed 8.4 V; that's the HD-1910's limit, not the URT-2's.

⚠️ **Power-up order: plug in USB first, then power the servos.** The other way round, the bus gets held at 2.1 V and not a single servo responds; see [Pitfalls · Tools](PITFALLS.en.md).

**Don't do stall tests on a fully charged 8.4 V battery**: that is the HD-1910's voltage limit, zero margin.

### Step 4 · Search for the servo

```
1  In FD, select the COM port noted in Step 1
2  Baud rate 1000000
3  Click “打开” (Open)
4  Connect only one servo (the one with the jumper-wired cable)
5  Click “搜索” (Search) → ID 1, model HD-1910 appears in the list
```

If it isn't found, check in this order: driver installed → correct COM port selected → baud rate is 1000000 → S wire making good contact (the temporary hole insertion is the most suspect) → S/G swapped.

### Step 5 · Change parameters

Switch to the “编程” (Programming) page (EPROM). **Change these items on every servo, leave everything else alone:**

| Parameter | Factory | Change to | Why |
|---|---|---|---|
| **ID** | 1 | **Per the table below** | The official runtime finds joints by this ID |
| **Overcurrent protection** | Off | **On** | Stalls are common once assembled; without it you burn servos |
| **Overvoltage protection** | Off | **On** | A full 8.4 V falls inside the 4–10 V window, so it won't trip falsely |
| Overheat protection | On (80 ℃) | Leave | — |
| Baud rate | 1 Mbps | Leave | Factory value is what the official code wants |
| Operating mode | Mode 4, pure position PD | Leave | Exactly what RL deployment needs |
| Return delay | 0 | Leave | Has no effect on the STS series |
| Center position | — | **Calibrate during assembly** | Once the robot is fully assembled, calibrate with the debug console using the official fold (see the section "Can the tucked pose serve as a calibration reference?" before Step 9). FD's “中位校准” (center calibration) just takes the current position as 2048, so only use it with the legs straight |

When done, click “保存” (Save).

**ID mapping table**: from upstream `duck-control/src/model.rs`; the comment says the values were "measured against the hardware":

| ID | Joint | ID | Joint | ID | Joint |
|---|---|---|---|---|---|
| **10** | Right hip yaw | **20** | Left hip yaw | **30** | Neck pitch |
| **11** | Right hip roll | **21** | Left hip roll | **31** | Head pitch |
| **12** | Right hip pitch | **22** | Left hip pitch | **32** | Head yaw |
| **13** | Right knee | **23** | Left knee | **33** | Head roll |
| **14** | Right ankle | **24** | Left ankle | **34** | Mouth |

**Mnemonic**: tens digit = body part (1 right leg · 2 left leg · 3 neck/head), ones digit = counted from the torso outward (0 hip yaw → 4 ankle).
ID 200 is the `imu_to_dxl` board; it is hard-coded in the firmware and not configured here.

> Temporary state of this robot (2026-09-28): the former mouth servo ID 34 has been moved to ID 21, and the user confirmed its FD center calibration to 2048; the mouth position is currently empty. The table above is still the designed ID assignment. Before bringing the bus back up, check which IDs are actually online; do not start motions assuming all 15 from the past are online.

### Step 6 · Verify

```
1  Power off (unplug USB or switch off the supply)
2  Power on again
3  Click “搜索” (Search) again → only if the new ID shows up was it actually written
```

Don't skip this step; EPROM parameters are only confirmed after a power cycle.

### Step 7 · Label it, next servo

Write **joint name + ID** on the label (e.g. "Left knee 23"), not just the number. All 15 look identical.
Unplug it, take the next one, back to Step 4. About two minutes per servo.

### Step 8 · Watch it turn (optional)

After the servo is found, click it on the main page and drag the position slider; it follows. On USB 5 V with no load it turns but has no strength; 7.4 V is the real operating condition.

### 2026-09-17 · Full robot on the bus for the first time, recording a "tucked" pose

URT-2 + the web debug console (`tools/servo-web/`) read all 15 servos of the assembled duck for the first time: 0 timeouts, 0 checksum errors, 7.2 V, 30–40 °C. After zeroing, with torque fully off and the duck lying down so the joints hang naturally to their limits, the readings are its "tucked" pose, saved in `tools/servo-web/poses/缩起来-2026-09-17.json`:

| ID | Joint | Servo value | Relative to zero |
|---|---|---|---|
| 20 | left_hip_yaw | 2084 | +3.2° |
| 21 | left_hip_roll | 1997 | -4.5° |
| 22 | left_hip_pitch | 772 | -112.1° |
| 23 | left_knee | 1058 | -87.0° |
| 24 | left_ankle | 2247 | +17.5° |
| 30 | neck_pitch | 1473 | -50.5° |
| 31 | head_pitch | 1094 | -83.8° |
| 32 | head_yaw | 2059 | +1.0° |
| 33 | head_roll | 2012 | -3.2° |
| 34 | mouth | 2047 | -0.1° |
| 10 | right_hip_yaw | 2018 | -2.6° |
| 11 | right_hip_roll | 2109 | +5.4° |
| 12 | right_hip_pitch | 3195 | +100.8° |
| 13 | right_knee | 3032 | +86.5° |
| 14 | right_ankle | 1782 | -23.4° |

Two things stand out: hip pitch and knee are mirrored between the left and right legs (left −112° / −87°, right +101° / +87°), consistent with the MJCF convention that the left and right legs have opposite positive directions; neck −50° and head −84° means the head is hanging down onto the chest. This set of values can later be sent directly as a "storage pose".

### 2026-09-18 · How to move from tucked to standing (forward kinematics on the official model)

Forward kinematics with `tools/servo-web/model/model.json` (the slightly tuned official MJCF), under these conditions: the sole has no fore-aft tilt, and the fore-aft position of the sole point matches the official standing pose. The result is a straight line: **hip = −26° + knee/2, ankle = +26° + knee/2** (left leg; for the right leg all signs are flipped, per the model convention). The legs are very short (thigh 42 mm, shank 49 mm); even with the knee bent to +60° the torso only drops 3 cm.

| Knee (model convention) | Hip | Ankle | Torso vs. standing pose |
|---|---|---|---|
| −60° | −56° | −4° | 10 mm higher |
| 0° | −26° | +26° | 0 (official standing pose) |
| +30° | −10° | +40° | 16 mm lower |
| +60° | +6° | +54° | 33 mm lower |

**Center of mass (using the masses from the official robot_walk.xml)**: the whole robot is 744 g; the sole extends 34 mm in front of and 20 mm behind the foot site. In the standing pose, the CoM projection is 34 mm from the toe and 20 mm from the heel; along the whole path from half-squat (knee +60) to standing, the margin stays above 17 mm; every 10° of head/neck moves the CoM by only 2.4 mm; every extra 5° of hip forward tilt (with the ankle counter-rotated 5° to keep the foot flat) moves the foot forward and adds +5 mm of toe margin. According to the model, standing up slowly shouldn't make it fall forward; if the real robot does fall, first check the zero-position errors (right hip 27°, left ankle 28°) and whether the battery is installed. The page's 3D view now draws the CoM projection in real time (green dot + dashed line) and the support area of both feet, turns red when the CoM leaves the support area, and reports the margin in four directions in the bottom-right corner.

**Joints whose real-robot direction differs from the model must be flipped with ± on the page**: on 2026-09-18, checked against the photo of the tucked pose, the knees (23, 13), neck pitch (30) and head pitch (31) are reversed; the ankles are still to be verified. Sequence files store relative angles in the model convention; the page converts them using ± before sending.

The order for standing up from tucked (hip −112 / knee −87 / ankle +17) has been made into the page sequence “站起来” (stand up) (`poses/站起来-序列.json`):

1. Raise the head, 1 s: neck and head pitch to +20°. The head is a third of the robot's weight, so put it in its standing position while the body is still sitting on the table.
2. Unfold the legs and flatten the feet, 3 s: relative to the real robot's standing pose, knee +60 / hip +30 / ankle +30 (model convention, left leg; right leg sign-flipped). The feet flip from behind the body to underneath it and press on the table, lifting the body by about 9 cm. This is the critical step; support it by hand the first time.
3. Straighten up, 2 s: follow the flat-foot line to the official standing pose. All three angles change linearly at the same time, the feet stay flat throughout, and the height rises by only 10 mm.

The page gained a "transition time": all poses, the standing pose and return-to-zero now interpolate linearly from the current actual position, sending sync writes at 20 Hz, instead of jumping instantly. This assumes the servo directions match the model (open item 8); first test servo 22 alone to see whether moving it in the negative direction lifts the thigh forward.

### 2026-09-22 · Can the tucked pose serve as a calibration reference? (exact mesh intersection on the official model)

A discussion in the group chat: the official zero position has the legs straight, and holding the robot in the air to pose it gives no reference point, so being off by a degree or two makes it fall; could the tucked pose be used as the reference instead? Using the official model, I rotated each leg joint in the folding direction until parts collided (fcl exact mesh, not convex hulls, [`tools/fold_contact`](tools/fold_contact/)):

- What stops the joints is **always the foot and ankle**, not the joint's own limit, so where it stops depends on the other joints: the knee makes contact at 70.7° with the hip at 0°, and at 89.6° with the hip at 90°
- **The ankle is not constrained when tucked**: with the knee and hip both fully folded it still has about 20° of play, so the ankle cannot be calibrated from the tucked pose
- In the official FOLD (hip, knee ±90°), the knee is almost exactly at the contact point; 1.57 rad (89.95°) would push the ankle about 0.36° into the thigh servo (contact at 89.59°); the left knee of the "tucked" pose saved on 9/20 converts to about 88°, which matches this contact point
- FOLD's neck / head pitch of 57° is **not a contact point**: with the legs folded, the neck has to turn to 66.6° before the neck servo touches the torso shell, and there is free space on both sides of 57°
- This is the original XL330 geometry; the Feetech version modified 8 parts, so it needs to be recomputed with a Feetech-version model or measured in SolidWorks

Analysis conclusion: the tucked pose can only serve as a reference for the hip and knee, and the way of posing it must be fixed exactly. The zero point is still the official 2048, and the official code and policy need no compensation: the tucked pose is only a reference point, not a new zero.

**The final method** (the reference “官方折叠（头颈摆正）” (official fold, head and neck straightened) in debug console 0.14.0 and later, revised after review in 0.15.0):

- Legs posed per the official FOLD: fold the knee until the ankle just touches the thigh servo (parts butt against each other, identical every time), set hip pitch perpendicular to the torso with a try square, hip yaw / roll and ankle at 0°
- Head and neck are not set to the official FOLD's 57° (not a contact point, can't be judged accurately by eye); instead they're straightened: neck vertical, head looking level, mouth closed
- **Calibrate all 15 at once**, with torque off, posing by hand. Target: with ± all −1, 22 / 23 = 1025, 12 / 13 = 3071, everything else 2048; written to the servo EEPROM (0x0B with a target value = "the current position is this reading"); the zero point remains the official 2048
- The knee is computed as the official 1.57 rad, but actually posed at the contact point of 89.59°; the zero difference of about 0.36° (4 steps) is ignored
- The confirmation dialog lists each servo as "now → write as, difference in degrees"; a difference over 30° asks for a second confirmation but **is not blocked**: if a servo horn was mounted half a turn off, the difference is 180° and calibration corrects it; but if the ± direction is set wrong, the difference is also around 180°, and calibrating that in is wrong, so first move the joint by hand and check the 3D rotation direction to verify ±
- After calibration torque is still off; unfolding by hand and then enabling torque won't make it jump (from 0.15.0, the target is aligned to the current position before torque is enabled)

### Step 9 · Assembly, zeroing, range-of-motion test

**What the zero point is**: the robot **standing perfectly straight**: legs straight like pillars, feet flat, neck vertical, head looking level. This is the position where all joints = 0 in the MJCF, corresponding to servo value **2048**.

**The standing pose is not the zero point.** The official standing pose (`DEFAULT_POSITION`) is an offset added to zero: hip pitch ±26°, ankle ∓26°, neck and head pitch +20°. That's handled in software; **don't calibrate the standing pose to 2048**.

**Procedure for each joint**:

```
1  In FD, first turn the servo to 2048, then mount the servo horn (if the horn splines don't line up, take the nearest; the error is handled in the next step)
2  Put the joint in its "straight" position and hold it by hand
3  FD Programming page → “中位校准” (center calibration) → current position is defined as 2048 (or the “中位校准” button in the web debug console `tools/servo-web/`; after assembly, hold the joint straight by hand and click it, same command)
4  Tighten the screws
5  In FD, slowly move from 2048 to the upper and lower limits in the table below; watch whether structural parts collide or cables get pulled
6  If it collides, note that servo's actual angle; being smaller than the software limit is normal, that's this robot's real range of motion
```

**Range table**: from the `range` values in the MJCF `robot_walk.xml`. These are **software limits**; whether they are mechanically reachable must be tested. The HD-1910 has 4096 steps / 360°, 1° ≈ 11.4 steps:

| ID | Joint | Range | Servo value (2048 = zero) |
|---|---|---|---|
| 10 / 20 | Hip yaw | Right −30 ~ +25° / Left −25 ~ +30° | Right 1707 ~ 2332 / Left 1764 ~ 2389 |
| 11 / 21 | Hip roll | ±22° | 1798 ~ 2298 |
| 12 / 22 | Hip pitch | ±90° | 1024 ~ 3072 |
| 13 / 23 | Knee | ±90° | 1024 ~ 3072 |
| 14 / 24 | Ankle | ±90° | 1024 ~ 3072 |
| 30 | Neck pitch | −90 ~ +60° | 1024 ~ 2731 |
| 31 | Head pitch | ±90° | 1024 ~ 3072 |
| 32 | Head yaw | ±170° | 114 ~ 3982 |
| 33 | Head roll | ±25° | 1764 ~ 2332 |
| 34 | Mouth | −5° (closed) ~ +30° (open) | 1991 ~ 2389 |

The left/right asymmetry of hip yaw is mirroring: both legs turn 30° outward and 25° inward. The mouth is not in the MJCF (the policy doesn't control it); its range comes from `MOUTH_CLOSED / MOUTH_OPEN` in `model.rs`.

⚠️ **Which side is positive depends on the orientation the servo is mounted in**; the official runtime has a direction and offset for each servo (`motor.rs`, whose comment says they were "measured against the hardware"). When testing for interference, just drive both directions to the end; don't worry about the sign.

---

---

## No-HAT build · jumper wires to the controller

**Now a separate document → [docs/不打HAT.md](docs/no-HAT-build.en.md)**. Many people find getting the HAT fabricated too expensive; that document is the alternative: ¥70 of modules, step-by-step wiring, and which steps can burn something.
This section only records what happened while doing it.

---

## 2026-09-10 · Servos and debug board arrived

**What arrived**: 15 HD-1910-C001 servos and one FE-URT-2 debug board (USB-C, with both TTL and RS485 ports).

**First problem**: the servos' stock cable is **2.0 mm 3P** (the datasheet says AMP2.0-3P), and the two white TTL ports on the left of the debug board are **bigger than that, so it won't plug in**. The board has no 2.0 port.

**What to do**: buy "servo adapter cable 2.0 to 2.5 3P". To get going while waiting for the cables, cut two cables and splice them.
The J4/J5 on the `imu_to_dxl` board are PH 2.0 mm, which match the servo cables, so it is **not affected**; only this debug board's ports are wrong.

**Next step**: once the adapter cables arrive, assign IDs one by one. **Connect only one servo at a time** (all factory IDs are 1), and label it after configuring.
While at it, enable overcurrent and overvoltage protection on each one (off by default from the factory). Baud rate and operating mode are correct from the factory; leave them.
Steps and the ID table are in [Servo configuration · step by step once the parts arrive](#舵机配置--拿到货一步一步做) above.

---

## 2026-09-12 · All parts arrived, controller pin headers soldered, servos going into the mechanical parts

**What arrived**: Radxa Zero 3W (2 GB bare board), ToF, battery, battery holder, microSD, pin headers, camera. Together with the servos and debug board from 09-10, **everything is here except the `imu_to_dxl` board (JLCPCB is still making it) and the jumper-wiring modules (buck converter, adapter board, adapter cables)**.

**What was done**:
- Soldered the 2×20 pin header onto the Radxa
- Started mounting the Feetech HD-1910s into the mechanical parts

**Problem found**: **the HD-1910 differs structurally from the original XL330** (at the spot where the leg is clamped). A colleague modified the structural parts and reprinted them; after the change they fit.
Exactly which part, what was changed and by how much: *to be added* (take photos, measure dimensions, write it into the [build log](BUILD-LOG.en.md), and add a line to the HD-1910 section of [Actuator selection](docs/actuator-selection.en.md): "mechanically not a drop-in replacement, parts must be modified").

**The algorithm side sent a pre-training data collection checklist** → the filled-in version is at [docs/HD-1910训练前数据清单.md](docs/HD-1910-pre-training-data-checklist.en.md); everything the repo already has is filled in, and bench items are marked with how to measure them.

**Next steps**:
- Continue mounting servos; after one leg is done, measure its range of motion once
- Assign IDs: the adapter cables haven't arrived yet, so first cut a servo cable and jumper-wire it per [Step 2 above](#第-2-步--飞线). **Do this first today**
  - ✅ Wire done, DIP switch set to the USB side, 5 V measured across G–V1
  - ✅ Plugged into the PC it shows up as **COM5**; the chip is a **CH343** (not CH340), recognized directly with the built-in Windows driver; Step 1 of the manual has been updated
- Flashing the controller: **no card reader, can't do it**. The card is microSD, and the board itself can't act as a card reader; if the laptop has no SD slot you need to buy one (USB 3.0). When it arrives, boot per [No-HAT build · Step 1](docs/no-HAT-build.en.md)

---

## 2026-09-13 · All 15 configured and mounted, starting bench work

**What was done**: all 15 HD-1910s have their IDs assigned, overcurrent and overvoltage protection enabled, and are mounted in the body.

**Bench wiring** (no buck module; the Radxa runs off a phone charger):
- Adjustable supply 7.4 V limited to 2 A → **directly to the servo bus V/G**; the URT-2's G also goes to the supply's negative for a common ground; **the V1 terminal is left unconnected**
- URT-2 DIP switch = signal level, set to 5 V (what I wrote earlier about an "external power side" was wrong; that board has no power selector)
- URT-2 USB-C → Radxa **host** port (not the power port)
- Radxa power port → 5V/2A charger (**don't use a PC USB port, 500 mA isn't enough**)

**Next step**: check `dmesg` for whether the CH343 shows up as `ttyACM0` → scan IDs 10–34 with Python → all 15 respond → official runtime.

---

## 2026-09-16 · Board power-on, flashing the card

**What was done**:
- Powered on the bare Radxa Zero 3W, OK. The pin header is 2.54 mm and matches the hole spacing in the DXF (two rows at y = 25.41 / 27.95 mm).
- The card reader and 5 V buck module arrived.
- Flashed Armbian 26.8.1 trixie minimal (sha256 verified). Rufus portable, accepts `.img.xz`, done writing in 2 minutes. Screenshots are in [`assets/flash/`](assets/flash/), and the steps are written up in [No-HAT build · Step 1](docs/no-HAT-build.en.md).

**Pitfall hit**: tried to use `wsl --mount` to write `.not_logged_in_yet` into the flashed card; it reported `ERROR_FILE_NOT_FOUND`, WSL can't mount a USB card reader. Switched to **putting the presets into the image before flashing**; the script is in [`tools/radxa/`](tools/radxa/) and needs no admin rights. Recorded in [Pitfalls](PITFALLS.en.md).

**Radxa resources**: downloaded the schematic / product brief / 2D DXF / 3D STP / component placement drawing, stored locally in `Radxa-Zero3W/`. **There are no PCB source files**, and neither the placement drawing nor the DXF marks pin 1. Identify pin 1 with a multimeter: power via the OTG port, measure the four corners of the header; the one with 3.3 V is pin 1, and the 5 V one next to it is pin 2.

**Next step**: insert the card and boot → find `radxa-zero3` in the router → `ssh duck@IP` → plug in the URT-2 and check `dmesg`.

---

## 2026-09-16 – 17 · Board boots, nine cards later

**Result**: Armbian 26.2.1 vendor runs on the board; WiFi connects automatically, ssh works, `/dev/ttyS2` exists, an extra USB serial port appears on the PC, Pollen's three official scripts have run, and daemon 0.13.0 is installed. One-step card preparation is in [`tools/radxa/`](tools/radxa/).

**Process** (chronological):
- Evening of 09-16: flashed Armbian 26.8.1 with Rufus, WiFi presets baked into the image. On boot the LED double-blinks, but it's not on the LAN. I assumed WiFi: the router's WPA3 mixed mode, AIC8800 not supporting GCMP-256, the 5G band, two drivers fighting; changed things version after version, flashed four times, nothing.
- Also tried the USB serial route: `g_serial` + `dwc3-peripheral`; the PC sees no device.
- Reading the card: copied the card's root partition out and mounted it to look; **not a single byte of the root partition had been written**, the first-boot marker was still there, and the partition hadn't been expanded. In other words, the kernel started its heartbeat but never mounted the system disk. All four WiFi revisions were wasted effort; the problem was further upstream.
- Switched the base to 26.2.1 (the officially specified version) and removed SDR104; neither helped. Built a "black box" initramfs (LED off on entering initramfs, solid when the disk is found, fast blink on failure, kernel log written to an area of the card outside the partitions); the LED kept double-blinking, so it never even reached initramfs.
- Just after midnight on 09-17: flashed Radxa's official image (b1, 2025-07); same card, same board, connected to WiFi in two minutes. SSHing in: the SD card runs SDR104 fine, WiFi is AIC8800D80/DS2, and the device tree compared item by item is basically the same as Armbian's. Board, card, power and device tree all ruled out.
- Comparing bootloaders: Armbian uses mainline U-Boot 2025.10 + DDR firmware v1.21 (2024-01); Radxa uses rk U-Boot 2017.09-51 + DDR v1.23 (2024-09) + BL31 v1.45. The board is a 2024-11 V1.12.
- Overwrote sectors 64–32767 (idbloader + u-boot.itb) of the Armbian card with those from the Radxa image and added a `/boot/extlinux/extlinux.conf`; **the ninth card booted**. LED: double blink → off → solid; on the LAN at `192.168.0.102`, and a COM5 appeared on the PC.
- Then followed the official `install-by-hand.md`: extlinux loads `uart2-m0` + `dwc3-peripheral`, console on tty1, mask the getty on ttyS2/ttyFIQ0; WiFi changed to the standard Armbian netplan form; `setup-board.sh` (aic3x codec DKMS, ONNX Runtime 1.28, ToF udev rules) → `migrate-network.sh` (NetworkManager) → reboot → run each once more → `install.sh` (daemon 0.13.0). The board downloads from GitHub through the PC's Clash proxy.

**Pitfalls hit** all went into [Pitfalls](PITFALLS.en.md): bootloader, GCMP-256, dwc3-peripheral, GitHub proxy, missing variables in the first-boot presets.

**Next step**: Step 4, connect the servo bus to the controller (URT-2 over USB, or jumper wires to pin 8/10 using `/dev/ttyS2`), and check the 15 servos with `robotctl health`.

**Two routes for the torso IMU** (decided on 2026-09-17 to pursue in parallel):

| | A · `imu_to_dxl` small board | B · GY-BNO085 module wired directly to the board |
|---|---|---|
| Hardware | Self-designed board, arrived, 3.3 V OK, connector footprint to be fixed | ¥66 off-the-shelf module, I2C on 40-pin header pins 3/5 (same i2c3 bus as the ToF), 3.3 V from pin 1 |
| Software work | STM32 firmware: ID 200 register protocol + IMU fusion; **no public firmware exists yet, written from scratch** | Add an I2C IMU source in robotd (Rust); the BNO085 does on-chip fusion and outputs quaternions directly |
| Effect on the official runtime | Protocol-compatible, robotd unchanged | robotd's IMU backend changes |
| Shared work | Port the Feetech servo protocol (robotd speaks Dynamixel) | Same as left |

The prototype era (the Raspberry Pi Zero 2 W version) used a BNO055 over I2C, so route B has precedent. Buy one first; seeing 0x4A in `i2cdetect -y 3` and reading quaternions from Python counts as working.

---

## 2026-09-28 · HAT arrived, ID 21 replaced, the camera finally produces an image

**Servos**: the user moved the former mouth servo ID 34 to ID 21 to replace the broken original 21, and completed the 2048 center calibration in FD. This item comes from the user's confirmation; this round of board/camera checks did not read back servo registers or run any motion. The mouth is currently missing; the designed ID table is unchanged.

**Board and power**: the HAT is plugged onto the board, and the user feeds 7.4V from an adjustable supply into the HAT and started checking item by item. The HAT's buck output supplies the board's 5V; once networked, the board is debugged over Wi-Fi / SSH. The board's `5V IN / USB_OTG` serves both as power input and gadget port, while USB 3.0 is the host port; when the HAT is powering the board, don't also connect it to a PC with an ordinary USB data cable, which would introduce a second 5V source. This records the wiring and debugging progress only; it does not mean load, voltage ripple, audio or the servo bus have passed acceptance.

**Camera process**:

1. Under the original Armbian, the camera did not respond, reading the IMX219 registers errored, and there was no sensor entity in the media topology.
2. Switched to Radxa's official Bookworm KDE B1 as a comparison; the image only had this robot's Wi-Fi / SSH preconfigured, with the kernel, drivers and system contents left stock. After boot, enabled `radxa-zero3-radxa-camera-8m.dtbo` through the official `rsetup` and rebooted.
3. The official system initially still reproduced `Error -5`; having `/dev/video0` alone does not prove the camera works. The double-blinking green LED is that system's `heartbeat`, not evidence of a boot failure.
4. The user checked and corrected the orientation of the ribbon cable and powered on again; `Model ID 0x0219` was read successfully, the `imx219` driver bound, and the media pipeline was complete.
5. A capped GStreamer capture of 40 frames reached a normal EOS after about 4.05 seconds with exit code 0; inspecting the last frame, the 1920×1080 JPEG shows the ceiling, a light and a monitor.

Wiring reference images, the full retest commands, versions and evidence are in the **[camera debug log](tools/radxa/camera-debug-log-20260928.en.md)**; a condensed reminder is in **[Pitfalls](PITFALLS.en.md)**.

**Next steps, in order**: the user has decided to switch back to the project's own Armbian, keep the working wiring, first retest detection and frame capture, then restore the project runtime and test sustained video, and after that verify the HAT peripherals and servo bus one by one. The earlier 09-20 base image with Wi-Fi has passed a read-only filesystem check; at the end of this session the board was shut down cleanly, waiting to be powered off so the card can be removed and flashed. That image is not a full backup of the running card from before the official image was flashed; camera enablement and the project software need to be restored. The original Armbian has not been retested with the correct wiring; the camera producing images does not mean the whole robot, the HAT power path or walking have passed acceptance. Whether the earlier suggestion to "remove the HAT and power the board alone over USB" was actually carried out is unconfirmed, and it is not counted as a completed test.

## 2026-10-11 · Running kissqy's walk model with our own runner

**Why**: kissqy's R17 deployment package sits on top of the official 0.15.1 system and only accepts an IMU on the servo bus (ID 200, identity `06 00 00 00 F2`); there's no I²C path in the code. Our robot uses a BNO085 on the board's I²C, and the card has no official runtime installed. So we used his model with the runner we used for Luwu on 10-04, adding a new `kissqy_walk` config whose execution parameters follow his robotd implementation.

**Result**: when the body is held by hand, it only shifts posture without stepping; put down on the floor without support, the legs start alternating within 0.4 seconds. Several mid-run stops with all joints going limp were all caused by the runner's protections (the 6.6 V undervoltage threshold, the 1° hold check after stopping); these have been fixed. With the supply raised to about 8.0 V, 0.15 m/s at P5 ran the full 10 seconds and returned to standing normally: it rocked back and forth for the first 3 seconds, then stayed in a half squat; no continuous gait yet. At P10 the current was too high and the adjustable supply's voltage collapsed to 5.4 V.

**Second half**: found the board was thermally throttling (84–87°C, CPU locked at 408 MHz, the resident web service saturating one core), stretching the control period to 25 ms; after stopping the web service it was back to 20 ms. Once the rhythm was right and the motions were full, the adjustable supply got pulled down to 4.6 V again, so a soft start was added. Joint directions checked one by one, all correct; parameters identical across all 15 servos. Even the best run (20 ms, 1.8 GHz, minimum 7.6 V) still only shifted posture without continuous stepping. **Decided to switch to kissqy's Rust runtime** and add an "IMU on the board's I²C" option to it (route B), keeping the native bus board (route A).

**Also hit that evening**: the PC couldn't reach the board while Clash TUN was on; the board froze once two minutes after boot (green LED solid), cause unknown.

Per-run data, what each parameter means, and how to run it yourself are in **[2026-10-11 kissqy hardware test](docs/HD1910-20261011-kissqy-walk-on-robot-test.en.md)**; conclusions have been added to [Pitfalls](PITFALLS.en.md).

## 2026-10-12 · First robot switched to kissqy's full stack: official 0.15.1 + R17 + I²C IMU

**Why**: after debugging with our own Python runner all the way through on 10-11, the remaining differences were all in the runtime layer. kissqy demonstrated in the group chat that his full stack already walks smoothly, so we decided not to install our own stack on the robot anymore and to use his full stack directly, only adding the "IMU on the board's I²C" he lacks (local branch `hd1910-trunk-imu-i2c`).

**What was done**: the original card was not reflashed (none of the official software had ever been installed, and the `i2c4-m0` overlay the IMU uses was already there); backed up `/home/duck` and installed remotely. The official `install.sh` only installs the latest version (0.16.1), so it was changed to install a pinned `daemon-v0.15.1` from local files, with auto-update disabled. Did not run the audio part of `setup-board.sh` (it replaces the kernel) or `migrate-network.sh`. First installed kissqy's original R17 as a baseline: it got stuck at `alsactl store aic3104` (the audio chip on the HAT isn't enabled, so the system has no such sound card; fixed in the branch); once installed it reported “ID 200 无应答” (ID 200 not responding) (he only supports the bus IMU), and it also copied his prototype's zero positions in as this robot's calibration. Then switched to our package and set `[trunk_imu] source = "bno08x"`.

**Result**: the BNO085 reads correctly on the real robot (firmware 2.6.6), all 15 servos respond at 50 Hz, and about 1.7% of cycles have stale IMU data (single frames; the control loop can reuse the previous frame). Calibration changed to our zero 2048, direction −1. With the duck brought to HOME via servo-web, the IMU measured: 4.95° from vertical while standing, 16.2° forward tilt, heading 3.9° off straight ahead; the default mounting orientation is correct. After switching to motion mode, it first goes limp, then HOME, standing to the official pose in 2 seconds; with the model taking over and holding in place for 10 seconds, body tilt went from 6.6° down to 3.3°, with no errors.

**Where it got stuck**: board overheating. With no camera connected, mediad kept crashing and restarting and GStreamer scanning saturated one core; the board was at 89°C. Even after disabling mediad and tofd it stayed at 85–92°C, with the CPU locked at 408 MHz the whole time. Pressing Start on the web console's virtual joystick did nothing: the web gamepad service takes 1.7 seconds to start, longer than the 0.6 seconds it waits for padd to acknowledge. The user shut it down to cool off; next step is adding cooling first (vent holes, an airflow duct), then trying the web joystick and walking again.

Commands, numbers and reasons for every step are in **[2026-10-12 kissqy full stack on the robot](docs/HD1910-20261012-kissqy-full-stack-on-robot.en.md)**; conclusions have been added to [Pitfalls](PITFALLS.en.md).

## 2026-10-12 afternoon · Taking apart kissqy's image R1 and making a card that boots on V1.12

**Why**: on 10-12 kissqy released a full-card image, “一键系统镜像 R1” (one-click system image R1) (official 0.15.1 + his firmware V164 / control.40, with a hotspot for network setup on first boot). Three things needed answering: whether boards like ours can boot it, whether it recognizes our IMU module, and what it preinstalls that would trip up newcomers. Where it doesn't work, modify his image rather than starting over.

**What was done**:

- Downloaded `microduck-zero3w-0.15.1-R1.img.xz`; its sha256 matches the `75da978b…a7bce5` he published.
- Took it apart with a read-only mount in WSL, without running a single program: checked the boot area, boot configuration, services started at boot, strings in the firmware, calibration and accounts, and scanned for tokens and private keys by signature.
- Copied out V164's install script and release notes and compared them with v146 file by file.
- Compared against the two HAT revisions (C1 production Gerber and BOM, D1 KiCad project) to check the pin order of J5–J8 and the chip addresses on the J5 bus.
- Wrote [`tools/radxa/kissqy-r1-v112.sh`](tools/radxa/kissqy-r1-v112.sh): on top of his image it swaps in the Radxa bootloader and writes extlinux (carrying his overlays over unchanged), and can optionally disable mediad / tofd and add overlays.

**Result**:

- Privacy is handled very cleanly: no tokens, private keys or WiFi credentials, accounts are locked, and SSH host keys are only generated on first boot.
- Three things don't match our hardware: the bootloader is Armbian mainline U-Boot 2025.10 + DDR v1.21 (exactly the combination our V1.12 board fails to boot with); it only accepts the bus IMU board (ID 200); and it preinstalls his prototype's calibration, with the IMU even marked “已确认” (confirmed). In addition, the camera and ranging services are enabled by default.
- V164 changed the web gamepad to go directly through robotd's IPC instead of webpad, so the path where the joystick didn't respond in the early hours of 10-12 has been replaced; but model import in the web console was also removed.
- Used the script to make a `--no-tof --overlay i2c4-m0` card and verified it offline: the boot area is byte-for-byte identical to Radxa's official package; sectors 0–63 (partition table) untouched; comparing the root partition file by file with the original, only the 5 expected changes (added `extlinux.conf` and a notes file, modified `armbianEnv.txt`, removed tofd autostart).
- On the C1 revision of the HAT, the J5 bus already carries audio (0x18) and a BMI088 (0x19 / 0x68); the D1 revision switches to an LSM6DSV16X (0x6A). On J6, removing R18/R19 and bridging R16/R17 turns it into I2C4.

**Next steps**: flash the modified image onto a blank card and try boot, hotspot network setup and SSH on the first robot (leave the current card alone); ask kissqy when he will publish the V164 source, so the I²C IMU patch can be ported over.

Full evidence is in **[kissqy image R1 analysis](docs/HD1910-20261012-kissqy-image-R1-analysis.en.md)**; conclusions have been added to [Pitfalls](PITFALLS.en.md).

## 2026-10-12 night · IMU mounted 8.5° off: after calibration it stands steadily for 70 seconds and starts alternating steps

**In one sentence**: as soon as the model took over, the robot lurched backward; the root cause was that the BNO085 module was mounted crooked, tilted about 8.5° forward and 1.75° to the right. During training the body is level when standing at HOME, but the IMU kept reporting "8.5° forward tilt", so the model kept trying hard to recover backward. After putting the real joint angles into the simulation to compute the "expected tilt", subtracting it to get the offset and folding that into the IMU mounting quaternion, the model held for 70 seconds without falling (average tilt +0.2°), and pushing the joystick to 0.14–0.21 m/s made both legs start stepping rhythmically in alternation. How far it moved forward hasn't been measured yet.

**Solved along the way**:
- The web gamepad didn't respond to presses: four layers of causes (SSH login wasting 3.8 seconds on a welcome script, the web console declaring data stale after 0.4 seconds, the virtual gamepad's cold start, the timing of padd opening a new device); in the end switched to a ThundeRobot G50 Pro connected directly over Bluetooth (switch on the back set to S);
- The power bank fell back to 5 V on overcurrent, so the servos lacked strength and couldn't reach the standing pose; switched to an adjustable supply at 8 V;
- The BNO085's wiring had a bad contact, I²C stopped responding, and robotd declared the IMU stale and went limp; after resoldering firmly and tying it down, it no longer drops out.

**Changes on the board**: SSH welcome script disabled (backed up), IMU mounting quaternion changed to `[0.454164155, 0.544101455, 0.527409117, 0.468538313]` (backed up), installed an autostart recording service `duck-rec`, Bluetooth gamepad paired. How to revert each is listed in §9 of the session record.

**Still unsolved**: cooling (10 minutes after the model starts running the CPU reaches 85°C and throttles), the mouth servo reaching 60–70°C just while standing, filter settings 1/1/1 vs. 0.9/0.5/0.7 not yet compared, TPU soles and forward distance.

Data for every step, the reasons, and how others can reproduce it: **[2026-10-12 night session record](docs/HD1910-20261012-night-IMU-calibration-and-first-steps.en.md)**; analysis scripts and IMU zero-calibration steps: [`tools/radxa/onboard-analysis/`](tools/radxa/onboard-analysis/).

## 2026-10-13 · Following official 0.17: UDP gamepad and automatic sit-down on gamepad disconnect (code complete, not yet on the robot)

**In one sentence**: on 10-12 the official project released robotd 0.16.2–0.17.1 in quick succession, mainly the "UDP gamepad": plug a gamepad into a PC and control the duck over the LAN. Our base is kissqy's 0.15.1; by 0.17.1 the official code has changed more than twenty thousand lines, and both sides have been bumping their interface version numbers independently so they no longer match. So instead of a full upgrade, only the UDP gamepad and "automatically sit down after 1 second of gamepad disconnect" were ported into kissqy's padd. This is done by adding a second input source to padd, keeping kissqy's button mapping; the wire protocol is byte-for-byte identical to the official one, so on the PC you can use the official `uvx duckctl@0.17.1 udp-pad <IP>` directly.

**Review**: after the changes, an independent review was run with a subagent, 6 rounds in total; the last round found no must-fix issues. Issues fixed include: the unit file actually used by the install package didn't allow AF_INET; a Select held down during reconnect was treated as an e-stop (8 out of 24 times); slow robotd replies were misjudged as a gamepad disconnect; after a stall, old joystick values and old long presses would still take effect (walking a short distance, accidental shutdown); a Select released and pressed again within the same tick turned into a shutdown. All were reproduced with scripts and retested to 0 after fixing.

**Result**: padd unit tests 79/79, all 14 end-to-end items pass, and the official 0.17.1 decoder can decode every packet we send. The padd and deploy script for the board are ready (the original is backed up first, one-command rollback). **Not yet on the robot**: on the robot, first confirm no regression with the Bluetooth gamepad, then manually try sit-down via D-pad down, then test sit-down on disconnect, and finally test the UDP gamepad.

Why it was done this way, how to use it, and the symptom and cause of every review item: **[2026-10-13 official update and UDP gamepad](docs/HD1910-20261013-official-update-and-UDP-gamepad.en.md)**.

## 2026-10-13 night – early 10-14 · New card on the robot, full-robot brownouts, servo D and jitter, foot-scuffing analysis

**In one sentence**: switched to a new card with kissqy's one-click image (V164 + our IMU patch); boot, network setup and the Bluetooth gamepad all work, but both the new and old cards suffer **full-robot brownouts** while walking (on the new card the last servo-side reading was about 3.9 V); this is a power problem, not software. The jitter while walking is related to **the servos' D (hardware damping)**: the servo model used in training has no D, while the real servos carry D=20/40. After setting D=0, jitter dropped from 51% to 4–8%; at P3 the body sway matches simulation. Currently using the old card with **P3 / D0 / torque 700**.

**Solved along the way**:
- On the new card the G50 Pro got disconnected right after pairing: on this card Bluetooth comes up non-bondable at boot (No Bonding), and `ClassicBondedOnly` rejects unbonded HID devices (after changing several things together it paired once; needs further verification);
- The comparisons made by changing scaling and filtering in `robotd.toml` were wasted: the joint model uses the `deployment-execution.json` in its own package;
- The P/D/torque boxes in the new card's web console don't take effect: V164 only writes P, and D stays at the factory 40;
- The IMU roll zero was still off by about 1.1°; compensated back by 1.14°;
- The recording service now writes to disk every second, file names include the boot number, and live copying of the system log was added, so the last second can be seen after a brownout.

**Still unsolved**:
- **Foot scuffing**: the feet only clear the ground by 3–6 mm, versus 11–12 mm in simulation. During stance the knee doesn't straighten; the model wants to extend it, but on the real robot it stays bent. The left foot appears to scuff more because the left toe points down during swing and the body pitches about 1.5° further forward when the right leg is in stance; both only appeared after D was changed to 0 (not present at D=20), so next try D=5–10 first. Also, according to servo readings the two feet differ by about 1.6°–2.6° in the lateral (roll) direction; not investigated (it was looked into during the day on 10-14, see the next section);
- **Power**: the 10 A supply arrives 10-16.

Data for every step, the reasons, and how to revert: **[2026-10-13 night session record](docs/HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md)**; gait analysis scripts: [`tools/gait-analysis/`](tools/gait-analysis/); recording service: [`tools/radxa/onboard-analysis/`](tools/radxa/onboard-analysis/).

## 2026-10-14 daytime · Simulation comparison to find the cause of foot scuffing, soles, new version unlocking P / D / torque (not yet on the robot)

**In one sentence**: the duck wasn't online during the day, so only analysis and code on the PC. Comparing kissqy's walking model in simulation with the real robot showed that the morning's simulation conditions weren't aligned with the real robot: on the real robot the joint model's action scale is actually about 0.83 with head/leg filtering, and the model kissqy trained with is 820 g; the simulation used scale 1.0, no filtering, 737 g. After aligning them (weight estimated at the 820 g of kissqy's training model), the simulated stance knee is already close to the real robot, and most of the "knee doesn't straighten" seen in simulation can be explained by these conditions; but that simulation set shows high-frequency jitter (96%) that the real robot doesn't have, cause not investigated. In addition, P / D / torque limits and head/leg filtering were unlocked on kissqy's new V164 (local, not yet on the robot, not published).

**Clarified along the way**:
- For a simulation comparison, first align scale, filtering, weight and speed; raising the scale from 0.83 to 1.0 gives about 3 mm more lift in simulation; on the real robot, setting the joint scale to 1.0 multiplied by the voltage compensation only adds 11%, so by linear estimate the effect is about half of the simulation's, still worth trying;
- Whether or not a 70% torque cap is set in simulation, the results are nearly the same; speed is not the cause of the gap;
- Overly slippery soles in simulation turn into shuffling steps plus jitter, but that doesn't match the real robot's behavior at D0; our soles are TPU 95A, and switching to 85A or anti-slip pads is worth trying;
- At HOME the two feet aren't coplanar laterally: both hip rolls splay outward, differently each time, as if pushed by body weight (a guess); whether the zero positions are off can't be determined by this method; of what was said verbally in the morning about "the outer edge lifting", 12 of 14 segments had it backwards;
- Servo parameters are written to RAM when torque is enabled and restored when it is released; if robotd was restarted while torque was on, the parameters stay in the servos, so before switching back to the original behavior (only writing P), power-cycle the servos once (on V164, restarting robotd makes the duck collapse on the spot);
- The “修复手柄连接” (repair gamepad connection) feature in kissqy's new version only supports the GameSir Nova 2 Lite; it does nothing for the G50 Pro.

**Not yet done**: install the adjustable version on the new card, check which foot lets light through underneath, weigh the robot, change soles, try scale 1.0; power (the 10 A supply arrives 10-16).

Data and reasons for every step: **[2026-10-14 daytime record](docs/HD1910-20261014-day-simulation-diagnosis-and-relaxed-params.en.md)**; new script [`tools/gait-analysis/home_roll.py`](tools/gait-analysis/home_roll.py).
