# Swapping Feetech servos into the official runtime · Architecture analysis and adaptation plan

**English** · [简体中文](飞特适配架构.md)

> Status: **first version of the code written** (2026-09-18), in the `feetech` branch of the fork [`fanhao375/microduck`](https://github.com/fanhao375/microduck), commit `b214486`, not yet verified on the board. See §10 at the end.
> Subject: Pollen's official runtime [`pollen-robotics/microduck`](https://github.com/pollen-robotics/microduck), reading `main` as of 2026-09-16 (`768e192`), with a local copy at `../microduck/`.
> Servo: Feetech HD-1910-C001, SMS/STS-series memory table; the official servo is the Dynamixel XL330-M288-T.

One-sentence conclusion: **the official runtime keeps "talking to the servos" behind a single Rust trait, so changing protocols only requires writing a new implementation; the control loop, policy, safety, IPC, and `robotctl` don't change by a single line. And the `rustypot` library it depends on already includes Feetech STS's protocol and register table, so we don't even have to write the packet format ourselves.** The two places that really need thought: the gain units don't match (and they live in EEPROM), and the IMU is not on the bus. REBOOT exists in newer Feetech firmware (0x08), see §3.4.

---

## 1. Existing architecture

### 1.1 Processes and crates

One Cargo workspace, 23 crates, one crate per service or tool (`docs/design/architecture.md` §1). Only three are related to the servos:

| crate             | Lines  | What it does                                 | Relation to the servos                         |
| ----------------- | ------ | -------------------------------------------- | ---------------------------------------------- |
| `duck-control`  | 4 224  | Control core: model, bus, observations, policy, safety, simulation | **The protocol lives here**, `bus.rs` is 708 lines |
| `robotd`        | 12 463 | Daemon: owns the serial port, 50 Hz control loop, IPC | Opens the bus, waits for servos to power up, starts calibration |
| `robotd-params` | 5 435  | Definition of `/etc/robot/robotd.toml`     | Just one field, `[bus] port`                 |
| `robotctl`      | 15 560 | Command-line tool                            | `health` shows bus status, `robot reboot-motors` |

The rest, `btd` (Bluetooth), `configd` (WiFi), `mediad` (camera), `padd` (gamepad), `tof`, and `updater`, don't touch the servos at all.

### 1.2 One seam: `RobotIo`

`duck-control/src/io.rs`. Between the control loop and the physical world there is **only this one interface**:

```rust
pub trait RobotIo {
    fn read(&mut self) -> Result<Sensors>;                 // One transaction: 15 joints + IMU
    fn write(&mut self, targets: &JointTargets) -> Result<()>;   // 15 goal positions
    fn set_gain(&mut self, kp: u16) -> Result<()>;         // One write per joint, not every tick
    fn set_torque(&mut self, on: bool) -> Result<()>;      // Same as above
    fn reboot(&mut self, id: u8) -> Result<()>;            // Protocol 2 REBOOT, clears hardware errors
    fn slow_sensors(&mut self) -> Result<SlowSensors>;     // Voltage + per-joint temperature, 1 Hz
    fn imu_stale(&self) -> ImuStale { .. }                 // Has a default implementation
    fn imu_ready(&self) -> bool { .. }                     // Has a default implementation
}
```

The data structures are all in SI units and protocol-independent:

```rust
Sensors { positions: [f64;15] /*rad*/, velocities: [f64;15] /*rad/s*/, currents_ma: [f64;15], imu: ImuData }
ImuData { gyro: [f64;3] /*rad/s, torso frame*/, gravity: [f64;3] /*unit vector, upright = [0,0,-1]*/, quat: [f64;4] }
JointTargets { positions: [f64;15] /*rad*/ }
SlowSensors { volts: f64 /*average of 15 servos*/, temps_c: [f64;15] }
```

There are already three implementations, proving this seam really is swappable:

| Implementation  | File       | When it is used                                |
| --------------- | ---------- | ---------------------------------------------- |
| `DynamixelIo` | `bus.rs` | Real robot, Linux                              |
| `FakeIo`      | `io.rs`  | `robotd --fake`; all tests run on it         |
| `RemoteIo`    | `sim.rs` | `robotd --sim`, the body lives in MuJoCo, TCP + JSON |

In the design doc's own words (`docs/design/simulation.md`): "six methods, and the only place a simulator is allowed to exist". **Our Feetech backend is simply the fourth implementation.**

### 1.3 What `DynamixelIo` does each tick

```text
  tick (20 ms)
    read()   One sync_read: IDs [200, 20..24, 30..34, 10..14], address 124, length 12
             ├ Slot 0 = IMU board (ID 200): gyro x/y/z i16 ×3 + SFLP quaternion x/y/z half-precision ×3 = 12 bytes
             └ Slots 1..15 = servos: present_pwm(2) · present_current(2) · present_velocity(4) · present_position(4)
    decide   Observations → ONNX policy → targets
    write()  One sync_write: goal_position, 15 of them
  Every 1 s
    slow_sensors()  One sync_read: address 144, length 3 → present_input_voltage(2) + present_temperature(1)
```

Unit conversions (`bus.rs`; the values were copied from the prototype `microduck_runtime`, and the comments say they were measured against the hardware):

| Quantity | XL330 register | Conversion                                        |
| ---- | ------------ | ----------------------------------------------------- |
| Position | 132, i32     | `rad = 2π·raw/4096 − π`, **2048 = 0 rad** |
| Velocity | 128, i32     | `rad/s = raw × 0.229 × 2π/60`                    |
| Current | 126, i16     | mA, absolute value                                  |
| Voltage | 144, u16     | 0.1 V                                                 |
| Temperature | 146, u8      | °C                                                   |

### 1.4 Startup and shutdown (`robotd/src/main.rs` `open_bus`)

```text
open_bus(port)
  ├ DynamixelIo::open           serialport 1 Mbps, timeout 30 ms, rustypot Xl330Controller + Protocol 2
  ├ missing_servos              ping the 15 IDs
  │    └ Exactly 1 missing → adopt_replacement: look for factory ID 1 (first at 1 Mbps, then 57600),
  │                     write ID, write baud rate, run the register check, REBOOT to clear hardware errors
  ├ check_registers             Assert and correct EEPROM: return_delay_time=0, baud_rate=3, pwm_slope=255, shutdown=52
  └ On failure → retry every second; `robotctl health` shows "no robot on the motor bus after N attempts"

robot.enable / init (moves only when a person presses it; process startup never touches torque)
  ├ set_torque(true)
  ├ set_gain(kp)                Writes P and also writes 0 to I and D (RAM registers, restored to factory values on power loss)
  └ interpolate_to(DEFAULT_POSITION, 2 s)   Linear interpolation, blocking
```

### 1.5 Constants tied to the protocol (`model.rs`)

```rust
JOINT_IDS = [20,21,22,23,24, 30,31,32,33,34, 10,11,12,13,14]   // Left leg, neck/head/mouth, right leg
IMU_DXL_ID = 200
BAUD_RATE = 1_000_000
FACTORY_ID = 1; FACTORY_BAUD_RATE = 57_600                       // XL330 factory values
EXPECTED_REGISTERS = [("return_delay_time",0),("baud_rate",3),("pwm_slope",255),("shutdown",52)]
DEFAULT_POSITION = [...]                                         // Standing pose, rad, training environment HOME_FRAME
```

`JOINT_IDS` and `DEFAULT_POSITION` are protocol-independent and are reused as is (we assigned our IDs exactly according to this table). The last four are XL330-specific.

### 1.6 Dependency: `rustypot`

`duck-control`'s Dynamixel implementation uses [`rustypot`](https://github.com/pollen-robotics/rustypot) 1.6.0 (Pollen's own library). Its structure:

```text
rustypot/src
  dynamixel_protocol/   v1.rs (FF FF header, 8-bit checksum)  v2.rs (FF FF FD 00, CRC16)
  servo/
    dynamixel/  xl330.rs  mx.rs ...
    feetech/    sts3215.rs  scs0009.rs  scs0043.rs      ← Feetech is already here
    servo_macro.rs   generate_servo! macro: generates read_x / write_x / sync_read_x / sync_write_x for each register
```

**Key facts**:

- `v1.rs` implements `SyncRead = 0x82` and `SyncWrite = 0x83`, which are exactly Feetech's instruction codes (Dynamixel 1.0 itself has no 0x82; it was added for Feetech). It also has `Reboot = 0x08` and `FactoryReset = 0x06`; `Sts3215Controller::reboot(id)` is ready-made, and returns `Ok(false)` rather than an error when the servo does not reply.
- `sts3215.rs` defines the complete STS memory table with `generate_servo!(STS3215, v1, ...)`, generating `Sts3215Controller`, used exactly like `Xl330Controller`: `.with_protocol_v1().with_serial_port(port)`, then `sync_read_present_position(&ids)`, `sync_write_goal_position(&ids, &rads)`, `sync_read_raw_data(&ids, addr, len)`.
- The position conversion `AnglePosition` is shared by both: `rad = 2π·raw/4096 − π`. **Feetech also uses 4096 steps per revolution with 2048 at center**, so the radian definition seen by the control loop does not change.

In other words, the packet format, checksum, sync read/write, and register naming are **all ready-made**. Feetech has no official Rust SDK (only C/C++, Python, and the FD host software); the community has a separate tokio-async [`DoraCN/feetech-servo-sdk`](https://github.com/DoraCN/feetech-servo-sdk) (MIT, 0.3.0), which we don't use: the main runtime already depends on rustypot, and a synchronous blocking model also fits the 50 Hz control loop better.

---

## 2. Differences between the two servos, item by item

The memory table was compared against the official SDK `FTServo_Linux/src/SMS_STS.h` (2025-09-27 version), `rustypot`'s `sts3215.rs`, and the 2026 materials on Feetech's official site doc.feetech.cn: "SCS 通信协议" (SCS Communication Protocol) v1.0 (2026-06-09) and "磁编码 STS 内存表手册" (Magnetic Encoder STS Memory Table Manual) v1.1 (2026-08-27); copies are in [`docs/飞特资料/`](../docs/飞特资料/). The addresses agree across all three; the new manual adds instructions 0x08/0x09 and the semantics of a few fields.

| Item          | XL330 (Protocol 2.0)                                                             | Feetech STS/SMS (HD-1910)                                                                                                                                                                                                                                                                                                                                                 | Impact on the adaptation                                                                   |
| ------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Packet format | `FF FF FD 00 ID LEN INSTR … CRC16`                                            | `FF FF ID LEN INSTR … CHK`, CHK = `~(ID+LEN+INSTR+params)`                                                                                                                                                                                                                                                                                                           | Already implemented in rustypot v1                                                         |
| Instructions  | PING 1 / READ 2 / WRITE 3 /**REBOOT 8** / SYNC_READ 0x82 / SYNC_WRITE 0x83 | PING 1 / READ 2 / WRITE 3 / REG_WRITE 4 / ACTION 5 /**0x06 parameter restore** (restores the parameters backed up by 0x09, except the ID; must unlock first; in the 2019 manual this was "factory reset") / **0x08 reboot** (about 800 ms, no response, turn torque off first) / **0x09 parameter backup** / **0x0A status reset** (clears the multi-turn count) / **0x0B position calibration** (can take a set value, STS firmware ≥ 3.10) / SYNC_READ 0x82 / SYNC_WRITE 0x83 | **REBOOT = 0x08 exists**, the same code as Dynamixel 2.0, see §3.4; 0x06 / 0x09 / 0x0A are not touched at runtime |
| Baud rate     | Register 8, `3` = 1 Mbps, factory 57600                                        | Register 6, `0` = 1 Mbps, **1 Mbps out of the factory**                                                                                                                                                                                                                                                                                                           | No need to switch baud rate when swapping in a new servo                                   |
| Factory ID    | 1                                                                                | 1                                                                                                                                                                                                                                                                                                                                                                         | Same, the adopt logic can be reused                                                        |
| Position      | 132 (read) / 116 (write), i32, 4096/rev                                          | 56 (read) / 42 (write), i16, 4096/rev, **bit 15 is the sign bit** (unused for 0–4095 in servo mode)                                                                                                                                                                                                                                                              | Same conversion                                                                            |
| Velocity      | 128, i32, 0.229 rpm/count                                                        | 58, u16, bit 15 sign; the unit is set by BIT2 of phase register 18: **0.0146 RPM (= 1 step/s) or 0.732 RPM (= 50 steps/s)**; the manual says the precision is 0.732 RPM either way                                                                                                                                                                              | Conversion: `rad/s = raw·2π/4096` (assuming 1 step/s); bench item 5 confirms the unit by measurement |
| Current       | 126, i16, mA                                                                     | 69, u16, **6.5 mA/unit** (STS manual); the manual doesn't specify a sign bit (the SDK uses bit 15), to be confirmed in the baseline data                                                                                                                                                                                                                              | Observations don't use current, it's only reported                                         |
| Load          | None                                                                             | 60, u16, 0.1 %, bit 10 sign                                                                                                                                                                                                                                                                                                                                               | Optionally reported                                                                        |
| Voltage / temperature | 144 (0.1 V) / 146 (°C)                                                  | 62 (0.1 V) / 63 (°C)                                                                                                                                                                                                                                                                                                                                                     | Brought back in the same read, **no separate slow transaction needed**                     |
| Torque switch | 64                                                                               | 40: 0 off / 1 on /**2 damping** (resistance set by torque limit 48) / 128 center calibration                                                                                                                                                                                                                                                                         | Same; for the trade-off on damping mode see §3.3                                           |
| Position loop gains | P 84 / I 82 / D 80, **u16, 0–16383**, RAM                             | P 21 / D 22 / I 23, **u8, 0–254**, **in the EEPROM area (5–39)**; factory P/D are marked "--" in the manual (commonly 32/32 on the STS3215), I=0; with lock=1, writes are "not saved on power loss" (original text for address 55 in the 2026-08 STS memory table); P is annotated "proportional coefficient (1/4)", D "derivative coefficient (1/8)"                 | **Different units, and in EEPROM**, see §3.3                                               |
| Operating mode | 11: 3 = position                                                                | 33: HD-1910 **factory 4 = pure position PD (Sim2Real)** ([pre-training data checklist](../docs/HD-1910-pre-training-data-checklist.en.md)); the generic STS manual lists only 0 position / 1 constant speed / 2 PWM / 3 stepper, but the row for 25 integral limit says "effective in position mode 0 and mode 4", so mode 4 is real; in the HD-1910 datasheet, 2/3 are "constant current / PWM" while the generic table says "PWM / stepper"; the baseline data is authoritative | **Assert = 4, don't write 0**; in mode 4 the scale of P/D must be calibrated separately  |
| Acceleration / speed | profile_velocity 112 / profile_acceleration 108, default 0 = unlimited  | goal_speed 46 / acc 41, **0 = maximum**                                                                                                                                                                                                                                                                                                                             | Write 0 at startup, equivalent behavior                                                    |
| Return delay  | 9, factory 250 (= 500 µs), **must be cleared to 0**                       | STS memory table: 7 is a **reserved address** (only on SMS is it the response return delay, 2 µs/unit, minimum 50)                                                                                                                                                                                                                                                 | Nothing to do                                                                              |
| Hardware errors | 70 hardware_error_status, `shutdown`=52 is the mask                          | 65 status: BIT0 voltage / BIT1 magnetic encoder / BIT2 temperature / BIT3 current / BIT5 load; 19 unload condition uses the same bit definitions = mask                                                                                                                                                                                                                    | See §3.4                                                                                   |
| EEPROM write protection | None                                                                   | **55 lock: write 0 to unlock, 1 to lock** (factory 1). Manual's original text: "writing 1 enables the write lock; values written to EPROM addresses are not saved on power loss"                                                                                                                                                                                       | Adopt and register correction need a wrapper; **writing while locked = RAM semantics**, §3.3 uses this |
| Protection parameters | shutdown mask                                                            | 19 unload condition, 28 protection current, 34 protection torque, 35 protection time, 36 overload torque                                                                                                                                                                                                                                                                  | We already set these in FD; at startup we only assert, never rewrite                       |
| Center offset | homing_offset 20                                                                 | 31 offset (bit 11 sign); or the CAL instruction                                                                                                                                                                                                                                                                                                                           | Zero calibration during assembly uses FD's "中位校准" (center calibration), consistent with [debug log step 9](../DEBUG-LOG.en.md) |
| Direction convention | Counterclockwise as seen from the horn increases the value                | **To be measured**, may be the opposite                                                                                                                                                                                                                                                                                                                             | If reversed, the backend flips the sign per the joint table                                |
| Endianness / version | None                                                                      | 2 END = 0 means little-endian; 0/1 firmware version, 3/4 servo version                                                                                                                                                                                                                                                                                                    | Read 0–4 at startup and log it, assert END = 0                                             |
| IMU           | `imu_to_dxl` board on the bus at ID 200, in the same sync_read                 | **No IMU on the bus**                                                                                                                                                                                                                                                                                                                                               | See §3.5                                                                                   |

---

## 3. Adaptation plan

### 3.1 Overall: add a backend, don't change the seam

```text
                 robotd control loop · policy · safety · IPC · robotctl      ← not a single line changed
                                    │
                            trait RobotIo (io.rs)
          ┌──────────────┬──────────┴─────────┬──────────────┐
      DynamixelIo     FeetechIo (new)        FakeIo        RemoteIo
      bus.rs          bus_feetech.rs        io.rs         sim.rs
      rustypot v2     rustypot v1 + STS3215
      XL330 + ID200   HD-1910 ×15 + ImuSource (new)
```

New files:

| File                                | Contents                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `duck-control/src/bus_feetech.rs` | `FeetechIo`: `RobotIo` implementation + `open` / `check_registers` / `missing_servos` / `adopt_replacement` / `present_positions` / `interpolate_to` (same names and signatures as `DynamixelIo`, so that `robotd`'s `open_bus` only changes the type, not the logic)                                                                                           |
| `duck-control/src/imu_source.rs`  | `trait ImuSource { fn latest(&self) -> Option<ImuData>; fn ready(&self) -> bool }` + a `Bno085I2c` implementation (its own thread reads I2C at 100 Hz; the control loop only takes the latest frame, without blocking)                                                                                                                                               |
| `duck-control/src/model.rs`       | Add `FEETECH_EXPECTED_REGISTERS`, `FEETECH_FACTORY_ID`; `JOINT_IDS` and `DEFAULT_POSITION` unchanged                                                                                                                                                                                                                                                             |
| `robotd-params/src/lib.rs`        | Add `protocol = "dynamixel2" \| "feetech-sts"` to `[bus]` (default dynamixel2, upstream behavior unchanged) and `[bus.feetech]` (`p_scale`, `direction` table, `imu = "bus" \| "bno085-i2c"`)                                                                                                                                                                 |
| `robotd/src/main.rs`              | `open_bus` picks `DynamixelIo` or `FeetechIo` based on `protocol`; `type BusIo = DynamixelIo` becomes `enum BusIo { Dynamixel(..), Feetech(..) }` with hand-written delegation. **`Box<dyn RobotIo>` can't be used**: `missing_servos`, `adopt_replacement`, `check_registers`, and `interpolate_to`, called by `open_bus` / adopt / `run_init`, are not in the trait, and `Safety<T>` is generic too |
| `robotctl`                        | `health` shows an extra line with the protocol name; `robot reboot-motors` unchanged (Feetech has 0x08, §3.4)                                                                                                                                                                                                                                                   |

Where it lives: a fork of `pollen-robotics/microduck`, branch `feetech`, with all changes confined to the places above and configuration defaults unchanged, so it **can be submitted back upstream as a PR in the future** (the design doc defines this seam as the only place where swapping implementations is allowed).

### 3.2 Mapping of each tick

```text
DynamixelIo                                   FeetechIo
sync_read [200,15 ID] @124 len 12      →      sync_read [15 ID] @56 len 15
  IMU block + pwm/current/vel/pos               56 pos(2) 58 speed(2) 60 load(2) 62 volt(1) 63 temp(1)
                                                64 (1) 65 status(1) 66 moving(1) 67-68 (2) 69 current(2)
                                              + imu_source.latest()  →  Sensors.imu
sync_write goal_position @116 len 4    →      sync_write goal_position @42 len 2
slow_sensors: sync_read @144 len 3     →      No new transaction; take 62/63 from the previous tick's block (cached)
```

One read brings back position, velocity, voltage, temperature, status, and current all together, so `slow_sensors` becomes free. Bus time: 15 servos × (6 + 15) bytes ≈ 315 bytes, about 3.2 ms at 1 Mbps plus response gaps; the write is 15 × 3 + 8 ≈ 53 bytes ≈ 0.5 ms. **That fits comfortably in a 20 ms tick**, and is even cheaper than the XL330 version (16 devices).

Conversions:

```rust
positions[j]  = 2π·(raw & 0x7FFF)/4096 − π        // Same as AnglePosition; the sign bit never appears in servo mode
velocities[j] = sign15(raw) · 2π/4096              // steps/s → rad/s
currents_ma[j]= sign15(raw) · CURRENT_MA_PER_UNIT   // HD-1910's unit still to be checked; use STS3215's 6.5 for now
volts         = average of the 15 servos' 0.1 V readings, discarding zeros (same as the XL330 version)
temps_c[j]    = raw
```

### 3.3 Gains: the only thing that needs calibration, and Feetech's gains are in EEPROM

The `kp` in `set_gain(kp: u16)` is the XL330's P. In `robotd-params`, `gain = 200` is the main parameter; when standing it is multiplied by `standing_gain_ratio = 0.8` → 160, and after a fall it is softened to `gain_limp = 50` (`limp_fall_pose_gain = 160`). `Safety` remembers the last value written and does not rewrite an unchanged value; but every transition walk ↔ stand ↔ fallen writes a round, 15 servos × 3 bytes.

Feetech's P is a single byte from 0–254 with a different physical meaning (how much PWM per unit of error), so it **cannot be written in directly**; worse, **21/22/23 are in the EEPROM area**, so following the XL330 approach would wear the EEPROM on every state change.

Plan:

- **Write while locked**. Original text for address 55 in the 2026-08 STS memory table: "writing 1 enables the write lock; values written to EPROM addresses are not saved on power loss", meaning the write is accepted but not persisted, which is exactly the XL330's RAM semantics → `set_gain` writes P directly without unlocking, with zero wear, and reverting to the EEPROM value after a restart is also consistent with the `reboot` contract. The manual doesn't explicitly say it "takes effect immediately"; **to-check item 3 takes a look on the bench**.
- **Damping mode is not a substitute for Limp**. Writing 2 to torque switch 40 = damped output with resistance set by 48, which looks like "going soft", but upstream defines `LimpFall::Limp` as "low gain, target position pinned to the current position, still holding posture", and the comments say explicitly it must not go fully slack, otherwise the head hits the ground and the next stage has no posture to ramp from. So `gain_limp` still works by changing P; damping mode could only be considered for "letting go completely" (`robot disable` and the like), and rustypot's `torque_enable` is a bool, so writing 2 needs `write_raw_data`; the SMS table doesn't have this value yet, and whether HD-1910 has it must be verified on the bench.
- Fallback if this does not hold up: set P only once with FD during assembly, and implement runtime "going soft" with the SRAM `torque_limit` (48) instead: `set_gain(50)` maps to lowering the torque limit by a proportion.
- Conversion: `p = clamp((kp × p_scale).round(), 1, 254)`, with `p_scale` in `[bus.feetech]`, calibrated on the bench: same joint, same step input, adjust Feetech's P until the response is close to XL330 at kP=200.
- **Don't zero D**. The XL330 version writes 0 to I and D because they are 0 from the factory; Feetech's factory D=32 is part of the manufacturer's tuning, and with a 320:1 gear ratio removing D may cause oscillation. Keep the factory D/I for now and only change P.
- In mode 4 (pure position PD) the scale of P/D is not necessarily the same as in mode 0; calibration must be done in the mode we actually run.

If this item is not calibrated accurately, the consequence is not that the robot can't move, but that **the gait differs from training**, so it belongs in the bench acceptance check; and the policy has to be retrained for HD-1910 anyway ([pre-training data checklist](../docs/HD-1910-pre-training-data-checklist.en.md)).

### 3.4 REBOOT: newer Feetech firmware has it, 0x08

On XL330, `RobotIo::reboot(id)` is the Protocol 2 REBOOT, used to clear hardware errors latched by the `shutdown` mask (overload, overheat). The contract for it in `io.rs`: **when the servo comes back, torque is off, RAM registers are back to their EEPROM defaults, and the caller rewrites the gains**; when `robotd` receives `reboot-motors` it first calls `set_torque(false)`, and when done puts the state machine into `Limp`.

Feetech's 2026-06 "SCS 通信协议" (SCS Communication Protocol) §4.12: **reboot instruction 0x08, "reboot the servo", no response frame, reboot time about 800 ms, with the remark "turn off the torque switch before rebooting"**. Same code and meaning as Dynamixel 2.0's REBOOT. Previously this document and two rounds of review said "Feetech has no REBOOT", based on the 2019 manual and the SDK header files, both outdated. A few others that are easy to confuse:

| Instruction       | 2026-06 manual                                                   | Conclusion                       |
| ----------------- | ---------------------------------------------------------------- | -------------------------------- |
| `0x06` parameter restore | Restores parameters backed up by 0x09, except the ID; unlock EEPROM first | Not touched at runtime    |
| `0x09` parameter backup | Backs up the current parameters                           | Worth doing once with FD after assembly and tuning |
| `0x0A` status reset | Resets the servo's turn count                                | Not touched at runtime           |
| `0x0B` position calibration | No parameter = calibrate current position as center; with parameter = calibrate to the set value; STS firmware ≥ 3.10 | Used for zero calibration during assembly. **HD-1910 can only use this**: writing 128 to the torque switch was tested and has no effect (2026-09-20; not even unlocked with torque off, the offset doesn't change), same as HLS ≥3.43 in the manual |

`FeetechIo::reboot(id)` is implemented as: torque 0 → `controller.reboot(id)` (rustypot v1's ready-made 0x08; when the servo doesn't reply it just returns `Ok(false)`, not an error) → **return immediately**. No waiting, no ping, no reading 65: `Safety::reboot_motors` calls it servo by servo inside a control loop tick, so waiting 1 s per servo would stall the control loop for 15 s across 15 servos; for 65, remaining set bits are only logged as errors, same as the XL330 version. Waiting and ping go into `adopt_replacement` (upstream `REBOOT_SETTLE` is 500 ms, Feetech about 800 ms, **so it needs to be set separately to ≥ 1 s**) and the bench. That torque is off on return is stated in the manual; that "P written while locked reverts to the EEPROM value" is an inference (the manual only says "not saved on power loss" and doesn't mention a soft reboot), to be verified together with to-check item 3; only once verified does it count as meeting the contract. `robotctl robot reboot-motors` is unchanged down to the letter. `adopt_replacement` keeps the reboot step, not because of the XL330 alert bit (Feetech doesn't have one), but to **verify that the newly written ID survives the reset**; if the lock wasn't released, this step exposes it.

Bench item 8 verifies: block one servo by hand to trigger overload (65 BIT5); after reboot, ping succeeds within 1 s, 65 is cleared, and the ID is retained. Record the HD-1910 firmware version (addresses 0/1) first; the manual doesn't say whether all versions support 0x08.

### 3.5 The IMU is not on the bus

In the XL330 version, the IMU is the `imu_to_dxl` board on the bus at ID 200, read back together with the servos. The Feetech line doesn't have it for now (the small board's firmware isn't written yet), so two routes for the torso IMU proceed in parallel ([debug log](../DEBUG-LOG.en.md)):

|                          | A · `imu_to_dxl` small board                                                                   | B · BNO085 wired directly to the board's I2C            |
| ------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| How it plugs into `FeetechIo` | The small board's firmware responds as ID 200 using the Feetech protocol, with a custom block read at 56 → added back into the same sync_read (200 inserted at the front of the ID list) | An `ImuSource` thread reads I2C at 100 Hz; `read()` takes the latest frame |
| What can be done now     | The STM32 firmware has to be written first                                                     | Buy a module; once `i2cdetect` on i2c3 shows 0x4A you can start |
| Code location            | A branch in `bus_feetech.rs`                                                                   | `imu_source.rs`                                       |

The definition of `ImuData` is unchanged: gyro (torso frame, rad/s), gravity (unit vector, upright `[0,0,-1]`), quat (torso → world). The BNO085 directly provides a fused quaternion and gyro; the mount rotation, median filter, and `ready()` threshold from `SflpDecoder` are copied as is into a `Bno085Decoder`. **Plan B goes first**; A waits for firmware.

The IMU part of `FeetechIo::read()`: if `imu_source.latest()` returns nothing, reuse the previous frame and count `imu_stale`, aligned with the XL330 version's semantics of "the board returned the same block"; `imu_ready()` is forwarded directly.

**Both routes are kept; the configuration picks one** (`[bus.feetech] imu = "bus" | "bno085-i2c"`), and the threading models differ:

```text
imu = "bus"          A · small board on the bus at ID 200
                     One thread. 200 is inserted at the front of the sync_read ID list, and the IMU block is read back together with the 15 servos;
                     the shape is exactly the same as the official XL330 version, only the packet format is Feetech's.

imu = "bno085-i2c"   B · BNO085 module wired directly to board pins 3/5
                     Two threads.
                       Control loop  50 Hz   sync_read servos → take latest IMU frame → policy → sync_write
                       IMU           100 Hz  read I2C (SH-2 reports) → convert to ImuData → write into a shared slot (Mutex or ArcSwap)
                     read() only takes the latest frame in the slot and doesn't wait for I2C; if nothing is there, reuse the previous frame and count imu_stale.
```
Why B gets its own thread: the IMU at 100 Hz and the control loop at 50 Hz run at different rhythms; an I2C stall (loose wire, power loss) must not hold up the servo tick; SH-2 reports need unpacking and sequence-number management, which shouldn't be crammed into a 20 ms tick. To the upper layers the two routes are identical: `Sensors.imu` is the same `ImuData` either way, and the policy can't tell the difference.

**Additions after review (2026-09-17)**

Plan B (BNO085 wired directly):

- Don't reuse the SFLP decoding for the quaternion: `SflpDecoder` only takes x/y/z, with `w = √(1−|v|²)` assuming w ≥ 0 by default; the BNO085 provides the real component directly, which can be negative, so use all four components directly and then convert per the main runtime's conventions (body→world, Z up, gravity = R⁻¹·[0,0,−1]). The Game Rotation Vector uses ENU and the Hamilton convention, consistent with the main runtime, but the mount quaternion has to be re-derived for the module's mounting orientation, with an acceptance check by resting in three poses (upright / tilted forward 90° / lying on its side).
- `imu_stale` returns empty by default in the trait; the byte-by-byte comparison is done by `StaleImuTracker` inside `DynamixelIo`, with 25 frames as the warning threshold. In route B the IMU thread has its own frame sequence number, so judge by "sequence number unchanged" instead; `imu_ready` should also look at the accuracy field reported by the BNO085.
- 100 Hz sampling / 50 Hz control loop: the control loop takes the latest frame each tick, and the IMU thread only does "write latest"; don't average quaternions from two frames.
- The Game RV has no magnetometer, so heading drifts; `odometry.update` in the main runtime uses the quaternion, so drift will get into the odometry. The official SFLP drifts the same way; it's not a new problem.
- I2C: on the official HAT, the board's i2c3 also carries the ToF, the audio codec, and the head BMI088, and `tofd` pushes firmware onto it at boot. We use the no-HAT build, so this bus is empty, but `tofd` will still probe it. The BNO085 holds SCL low heavily (clock stretching), and the RK3566's I2C controller isn't very friendly to that: **after connecting, first run 100 Hz reads for 10 minutes and log jitter and dropped frames**; if it doesn't work, switch the BNO085 to UART-RVC mode (fixed 100 Hz output, at the cost of one more serial port on the board).

Plan A (small board on the bus):

- rustypot's sync_read receives packets strictly in ID-list order and checks each ID; out-of-order replies invalidate the whole tick. The manual doesn't say whether Feetech servos in a sync_read "wait for the previous one to finish before answering" or answer on a timer: on the bench, first put a nonexistent ID at the very front of the list and see how the 15 servos react, then measure the small board's response latency with a logic analyzer (the < 100 µs in §4.2).
- Protocol detection in the firmware: lock on as soon as the first packet passes its checksum, and **never automatically unlock during operation**. The original draft's "re-detect after 100 consecutive failed packets" would leave the small board mute for 2 s under bus noise, and the main runtime holds after 3 ticks without readings.

### 3.6 Mapping of the startup sequence

```text
FeetechIo::open(port)        Sts3215Controller::new().with_protocol_v1().with_serial_port(1 Mbps, 30 ms)
missing_servos()             ping the 15 servos, same as the XL330 version
adopt_replacement(id)        Factory ID 1, 1 Mbps, no baud rate switch needed: unlock → write ID → lock → check_registers_of → 0x08 reboot → wait ≥ 1 s → ping the new ID (verify the ID survives the reset)
check_registers()            First read 0–4 (firmware version, END endianness) and 18 phase, log them, assert END 2 = 0; in phase, BIT2 sets the velocity unit, BIT3 sets the meaning of "speed 0", BIT0/BIT7 set direction
                             Assert: baud 6 = 0 · mode 33 = 4 · response level 8 = 1 (1 from the factory) · protection parameters (19/28/34/36) = the values set in FD
                             On mismatch: baud is written back after unlocking (same as the XL330 version's "correct and count");
                             mode, response level, and protection parameters only warn, never change: writing the wrong mode would break all 15 servos at once, so better to stop and let a person look
                             Response level must be 1: manual's original text "0: no response packet except for read instructions and PING"; rustypot's write() waits for a status packet, so at level 0 every write times out after 30 ms
init                         set_torque(true) → set_gain (§3.3, write P while locked) → interpolate_to as before
                             41 acceleration / 46 speed are SRAM, 0 / maximum at power-up, not written; "46 = 0 is maximum" also depends on phase BIT3, and writing it could actually turn it into "stop"
```

### 3.7 Direction and zero position

The XL330 version has no per-joint direction table; 2048 is zero, and direction relies on the servos being mounted in the same orientation as the original. For Feetech:

- Zero position: during assembly, use FD's "中位校准" (center calibration) to set the upright pose to 2048 ([debug log step 9](../DEBUG-LOG.en.md)), equivalent to XL330 homing.
- Direction: **verify each servo on the bench** by driving to +30° and seeing which way the joint moves. If STS's positive direction is opposite to XL330's, use `[bus.feetech] direction = [±1; 15]` and the backend multiplies by it on reads and writes; the default is all +1.

---

## 4. Small board firmware (Plan A · `imu_to_dxl`)

Plan A's board ([`hardware/imu_to_dxl/`](../hardware/imu_to_dxl/)) is currently a bare board that has been powered up, and **the firmware is written from scratch**. Its job comes down to one sentence: **impersonate a servo with ID 200 on the servo bus, and return IMU data when the main runtime reads it.** Everything the official runtime requires of this board is in `duck-control/src/imu.rs` and `bus.rs`, copied out here:

> 📄 **The firmware implementation spec is a separate document**: [`hardware/imu_to_dxl/总线协议.md`](../hardware/imu_to_dxl/bus-protocol.en.md)
> It covers the byte-by-byte block definition, timing values (including which come from the manual and which are inferred), multi-slave queuing rules, power-up timing,
> the main runtime's four validity criteria, the two firmware prohibitions arising from freeze detection, test vectors, and the acceptance checklist.
> Companion tool [`tools/imu200/`](../tools/imu200/): fake small board, vector generation, 13 checks for the real board.

### 4.1 Everything the main runtime requires of ID 200

| Item             | Official XL330 version (Dynamixel 2.0)                                                                                            | Our Feetech version                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| When it is queried | One `sync_read` per tick, ID list `[200, 20..24, 30..34, 10..14]`, address 124, length 12                                     | The same `sync_read`, with 200 inserted at the front of the ID list, **address 56, length 15** (the same address as the servos; the board maps the IMU data into this range itself) |
| What it returns  | 12 bytes: `gyro x/y/z` each i16 LE, ±500 dps range, 17.5 mdps/LSB; `quat x/y/z` each IEEE half precision, w computed by the main runtime | The same 12 bytes at the front, plus 3 bytes: sample count + status bits, to make 15                          |
| Consequence of not replying | `sync_read` waits for every ID; if one doesn't reply the whole transaction fails, and **the main runtime has no sensor data for that tick** | Same                                                                         |
| Other instructions | At runtime it only ever gets **sync_read**: `robotctl` doesn't touch the bus, and `missing_servos` / `check_registers` only check the 15 servo IDs, not 200 | Same; PING / READ are for the FD software and URT-2                     |
| Meaning of zero values | An all-zero quaternion = SFLP hasn't produced data yet; the main runtime reuses the previous frame and doesn't count it as ready | Same                                                                                                  |
| Mounting orientation | `SflpDecoder::DEFAULT_MOUNT` = +90° about Y, torso = `[+raw_z, +raw_y, −raw_x]`                                           | The board must be mounted in the same orientation as the original, otherwise change the main runtime's mount quaternion |
| How soon after power-up data is needed | The main runtime needs 25 frames of valid quaternions before it counts as `ready`; `decode` runs once per tick, i.e. **0.5 s @ 50 Hz** | Same                                                                    |

Key point: **the main runtime never writes to this board, nor configures it**, so the firmware can simply hard-code its own behavior.

### 4.2 Firmware modules

```text
imu_to_dxl firmware (STM32G031F8P6, 64 KB Flash / 8 KB RAM)
  ├ bus/        USART2 1 Mbps (PA2/PA3), hardware DE (PA1, CR3.DEP=1 active low), RX_EN (PB7)
  │   ├ rx      DMA ring buffer + idle interrupt for packet splitting
  │   ├ parser  Automatic detection of two protocols (design item 4 in the README):
  │   │           FF FF FD 00 … CRC16  → Dynamixel 2.0
  │   │           FF FF ID LEN … CHK   → Feetech (LEN is always ≥ 2, no ambiguity)
  │   │         Locks on as soon as the first packet passes its checksum, never automatically unlocks during operation (see §3.5 additions)
  │   ├ handler PING → status packet; READ / SYNC_READ → taken from the register table; WRITE → only the ID item is honored, everything else is ACKed without changes
  │   └ tx      Pull PB7 low during transmission to disable reception (or leave it on and discard the echo by transmit length), re-enable when done
  ├ imu/        LSM6DSV16X, 4-wire SPI (PA4–PA7) + INT1 (PA0)
  │   ├ init    Accelerometer ±4 g, gyro ±500 dps, ODR 480 Hz; SFLP game rotation vector at 120 Hz on
  │   ├ isr     INT1 data ready → read FIFO / read directly, take raw gyro values + SFLP quaternion (the chip already outputs half precision)
  │   └ block   Assemble the 12-byte block: gyro i16×3 + quat half precision ×3, replaced atomically (a bus interrupt may come to read at any time)
  ├ regs/       Register table: one 128-byte mirror
  │              Dynamixel view: 0 model (= custom), 6 firmware version, 7 ID (200), 8 baud rate, 124..135 IMU block, 136..143 diagnostics
  │              Feetech view:   3 model, 5 ID (200), 6 baud rate (0), 56..70 IMU block + count + status
  │              Both views point to the same memory, just at different addresses
  ├ clock/      HSI16 by default; X1 is actually populated, so after measuring the communication bit error rate it can switch to HSE bypass; or capture the host's bit period with a timer and trim HSITRIM back
  └ diag/       RTT logging (SWD on J3), counters: packets received / checksum errors / replies / timeouts
```

Timing requirements: at 1 Mbps one byte takes 10 µs; the board is first in the `sync_read`, and the time from finishing receipt of the instruction to starting the reply must be kept **< 100 µs** (Feetech servos themselves take roughly 20–50 µs); the reply of 15 data bytes + 6 bytes of header/trailer ≈ 210 µs. Done in interrupts; the main loop is not involved.
### 4.3 Toolchain and verification

| Item        | Choice                                                                                                                 | Reason                                                     |
| ----------- | ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Language    | Rust `embassy-stm32` (or C + STM32CubeG0 LL)                                                                         | Rust is the same language as the main runtime, and `rustypot`'s packet parsing code can be borrowed directly |
| Flashing / debugging | SWD on J3, `probe-rs` + CMSIS-DAP / ST-Link; logging via RTT, or printf over USART1 on J3 pins 4/5           | Neither halts the CPU; semihosting halts the CPU on every printf, so it's not used |
| Unit tests  | Packet parsing, both checksums, and register mapping run on a PC with `cargo test`                                  | No board needed                                            |
| Bench 1     | URT-2 + FD software: find ID 200, read 56–70 on the "编程" (Programming) page and watch the IMU numbers change      | FD is a ready-made Feetech host                            |
| Bench 2     | Board + 15 servos connected to the main controller together, `[bus] protocol = "feetech-sts"` in `robotd.toml`, the imu item in `robotctl health` is ready | Merged with §5 items 9 and 10                 |

### 4.4 Which to do first

Plan B (BNO085 wired directly) needs no firmware and works within a few days of the module arriving; Plan A's firmware takes one person two or three weeks from zero to running on the robot. **Get B working first so the duck can stand up, and do A slowly as the final version**: once A is ready, the main runtime side only changes one configuration item, and the code for both routes is kept.

---

## 5. Bench acceptance check (the adaptation is complete only when all of these pass)

Tool: [`tools/servo-web/`](../tools/servo-web/), a web debug console attached to the serial port; the operations for items 0–8 (scanning, dragging, exporting registers, timing tests, reboot) are all on the page; from 9 on it's `robotd`.

| #  | What is verified                                                                                                                                                     | How                                                               | Pass criterion                            |
| -- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------------- |
| 0  | Register baseline                                                                                                                                                    | Export all of 0–90 of one HD-1910 from FD's "编程" (Programming) page and store it in `docs/` | The table is in the repo and every row in §2 matches |
| 1  | Physical layer works                                                                                                                                                 | Python on the board pings IDs 10–34 with the Feetech SDK         | All 15 respond                            |
| 1b | Whether the adapter board echoes                                                                                                                                     | Logic analyzer or bare `cat /dev/ttyS2` to see whether sent instructions come back unchanged on RX | No echo; if there is, the backend must discard by transmit length |
| 2  | rustypot v1 works                                                                                                                                                    | `Sts3215Controller` ping + `sync_read_present_position` on 15 servos | One read returns all, no checksum errors |
| 3  | Write/read round trip                                                                                                                                                | Write 2048±200, read back                                        | Error ≤ 3 steps                           |
| 4  | Tick timing                                                                                                                                                          | 30 000 rounds of sync_read + sync_write                          | Each < 6 ms, timeout / checksum error count 0 |
| 4b | sync_read response order                                                                                                                                             | Put a nonexistent ID at the very front of the ID list            | Record whether the 15 servos wait for it to time out, answer anyway, or collide |
| 5  | Units                                                                                                                                                                | Time one revolution at constant speed against the velocity register; multimeter against voltage; temperature against touch | Velocity conversion error < 5 % |
| 6  | Direction                                                                                                                                                            | +30° on each servo, watch the direction of rotation              | Recorded in the `direction` table       |
| 7  | Gain calibration                                                                                                                                                     | First verify that writing P while locked takes effect; compare step response against XL330 kP=200 | Set `p_scale`, or switch to torque_limit |
| 8  | Overload recovery                                                                                                                                                    | Block one servo by hand to trigger protection (65 BIT5)          | After 0x08 reboot, ping succeeds within 1 s, 65 cleared, ID retained |
| 9  | `[bus] protocol = "feetech-sts"`, IMU initially the fake IMU from `FakeIo`; **prerequisite: a self-built robotd can already be installed on the board (§8.1), and bus voltage ≥ 7 V or `battery_empty_shutdown` turned off first** | `robotctl health`                                               | bus green, loop 50 Hz 0 missed            |
| 10 | IMU source                                                                                                                                                           | Connect the BNO085                                                | `imu ready`, gravity follows when the board is flipped |
| 11 | Standing on a hanging rig                                                                                                                                            | `robotctl robot init`                                           | Reaches DEFAULT_POSITION in 2 s, no jitter |

---

## 6. To-check list (to confirm before touching code, sorted by how decisive each is)

1. **Register baseline**: export all of 0–90 of one HD-1910 from FD's "编程" (Programming) page into the repo and check the §2 table row by row: 65 status bit definitions, 69 current unit, 41 acceleration unit, 8 response level factory value.
2. **Operating mode**: whether factory mode 4 is exactly what we want to run; the difference in P/D response between mode 4 and mode 0.
3. **Writing P while locked**: with lock=1, write 21 and see whether the response changes immediately and whether it reverts to the original value after reboot. Decides which path §3.3 takes.
4. **0x08 reboot**: send it to a spare servo; after 1 s, check that ping succeeds, ID and EEPROM are retained, 65 is cleared, torque is off, and whether P written while locked reverts to the EEPROM value; and whether the HD-1910 firmware version (addresses 0/1) supports it. 0x0A has been characterized by the manual as clearing the turn count, no need to test.
5. ~~Response level 8 factory value~~ Manual: initial value 1. All that remains is confirming HD-1910 wasn't changed by FD.
6. **sync_read response order**: behavior of the 15 servos when a nonexistent ID comes first.
7. Whether bit 15 of the position register is ever set in servo mode; sign bits of the velocity and current registers.
8. Direction convention (§3.7).
9. ~~Endianness~~ Manual: the magnetic encoder series is little-endian, and address 2 END = 0 can be asserted online.
10. Plan B: jitter and dropped frames of the BNO085 at 100 Hz on I2C.
11. **Half-duplex echo**: rustypot receives status packets with a fixed-length `read_exact`, without scanning for headers or discarding echo. The official HAT uses a tri-state buffer with automatic direction switching; we use a URT-2 or ST/SC adapter board, and if RX is always on, the first packet of every transaction is our own instruction, the whole bus "doesn't work", and the symptoms look like a wiring error. Verify with bench item 1b first.
12. Bench power: `battery_empty_shutdown` is on by default and sits down and shuts off when the bus voltage is ≤ 6.6 V; HD-1910 has a 6 V rating, so the bench supply should be ≥ 7 V, or turn this off first.
13. **Factory value of phase 18**: BIT2 (velocity unit 1 step/s or 50 steps/s), BIT3 (speed 0 means stop or fastest), BIT0/BIT7 (direction). The velocity coefficient in §3.2 is chosen based on it.

## 7. Effort estimate

| Block                                | Size                                       | Depends on    |
| ------------------------------------ | ------------------------------------------ | ------------- |
| `bus_feetech.rs`                   | About 500 lines, half copied from `bus.rs` with registers swapped | Already in rustypot |
| `imu_source.rs` + BNO085 (Plan B)  | About 300 lines, I2C via the `i2cdev` crate | Module arrives |
| Small board firmware (Plan A)        | About 2 000 lines, two or three weeks, a separate project | ST-Link, small board |
| params / robotd selection / robotctl text | About 100 lines                       | —            |
| Bench acceptance 1–8                | Two or three evenings                      | Servos connected to the board |
| Gain calibration + standing          | One or two evenings                        | All of the above |

Do 1–4 and 9 first, which turns `robotctl health` green; the IMU and standing come after.

---

## 8. Items added after review

### 8.1 Build and deployment

How the fork's build output gets onto the board: officially, `cargo board` / `xtask package` produce a `.deb`, and `updater` only installs packages signed by keys in `/etc/robot/trusted_keys/`. `scripts/dev-push.sh` takes the development path, but it needs the **private key** `~/.duck-keys/team.dev.key`; the repo only has the public key `deploy/dev-key/team.dev.pub`, and we can't get Pollen's private key. Approach: generate our own key pair, put the public key in `/etc/robot/trusted_keys/` on the board and enable `allow_dev_keys = true`, and point `DUCK_DEV_SECRET_KEY` at our own private key. Before writing code, first get "a self-built robotd can be installed and replace 0.13.0" working; this is the prerequisite for bench item 9.

### 8.2 Relationship to the policy / training

- Observation vector 20..34 holds joint velocities: if the velocity unit conversion is off by a constant, the policy won't report an error, it will just "walk badly". Bench item 5 must pass first.
- `voltage_adapt` scales actions according to the XL330's voltage-torque relationship; on Feetech, turn it off first or recalibrate it.
- The official ONNX was trained on XL330 (0.52 N·m); HD-1910 has a 320:1 gear ratio and 1.47 N·m, so the dynamics differ, and it **most likely can't walk with it directly**. Bench items 0–9 only verify communication and 11 verifies standing; "walking" has to wait for retraining.

### 8.3 What failure modes look like in `robotctl health`

| Fault               | Symptom                                   |
| ------------------- | ----------------------------------------- |
| One servo doesn't respond | The whole sync_read fails, bus red, missing N |
| Overload / overheat latched | Bits set in 65 status, position doesn't follow, recover per §3.4 |
| EEPROM correction fails while locked | Reports corrected on every boot but has no effect |
| Response level 0    | Every write times out after 30 ms, init takes over 1 s and reports errors |
| Wrong mode          | Communication works but position commands do nothing or behave strangely |
| IMU frozen          | 25 identical frames → imu stale, fall detection stops |
| I2C hang (Plan B)   | IMU thread read times out, sequence number doesn't advance → stale |

### 8.4 Testing strategy

- `FakeIo` is unchanged, and all upstream tests run as before.
- The block decoding in `bus_feetech.rs` (the three kinds of sign bits for position / velocity / current), `p_scale`, and voltage averaging are unit tested with recorded raw frames, no board needed.
- The firmware's packet parser and both checksums are tested on a PC with `cargo test`.
- Before enabling torque on all 15 servos together for the first time: lower `torque_limit` to 30 % in FD, enable overcurrent protection, and do it on a hanging rig.

### 8.5 Decisive risks (do these four first, then write code)

1. Mode 4 or 0 (to-check 2)
2. Gains are in EEPROM: does writing while locked work (to-check 3)
3. Whether the 0x08 reboot works on HD-1910 firmware (to-check 4)
4. Plan B's I2C jitter (to-check 10)

---

## 9. Review log

### 2026-09-17 · Independent review by a second model

Checked item by item against official source `768e192`, rustypot 1.6.0, the Feetech SDK 2025-09-27 (`INST.h` / `SCS.h` / `SMS_STS.h`), and protocol manual V1.01. Errors corrected: `gain` is 200, not 160; the factory operating mode is 4, not 0; the semantics of 0x06 / 0x0A were swapped; the gain registers are in EEPROM; `ready` is 0.5 s @ 50 Hz; 23 crates; `Box<dyn RobotIo>` doesn't compile, changed to an enum; the `imu` configuration values were inconsistent in two places; `robotctl` doesn't touch the bus. Added the notes on the two routes in §3.5, to-check items 5–10 in §6, and all of §8.

### 2026-09-17 · Second round of review

A new instance of the same model, looking only at whether the first round's changes were correct. Confirmed all of the first round's changes; further changes: per the 2024 magnetic encoder manual, 0x0A is "reset the servo's turn count", not REBOOT; the `reboot` implementation now ends with torque 0, consistent with the `io.rs` contract; the lock=1 semantics now cite only the manual's original wording "not saved on power loss"; the `--protocol` command-line option was unified into the `[bus] protocol` config key; §8.1 added self-signed keys; to-check items added for half-duplex echo (11) and bench power shutdown (12); wording of `imu_stale`, RK3566, the original quote in §1.2.

### 2026-09-17 · Checked against the latest materials on Feetech's official site

The user provided the entry point for the materials on doc.feetech.cn, and we pulled the 2026 materials from Feetech's official site doc.feetech.cn: "SCS 通信协议" (SCS Communication Protocol) v1.0 (2026-06-09) and "磁编码 STS 内存表手册" (Magnetic Encoder STS Memory Table Manual) v1.1 (2026-08-27); copies are in [`docs/飞特资料/`](../docs/飞特资料/). Corrected: **Feetech has REBOOT (0x08, about 800 ms, turn torque off first)**, the whole of §3.4 was rewritten, and `reboot-motors` doesn't need its text changed; 0x06 is "parameter restore" (paired with the 0x09 backup), not factory reset; lock=1 "not saved on power loss" now has the original text; response level factory value 1, little-endian byte order (END register), 65 status bit definitions, the 6.5 mA current unit, the velocity unit set by phase BIT2, torque switch 2 = damping mode, all confirmed from the manual; address 7 in the generic STS table is reserved and is no longer asserted. To-check items 4/5/9 were closed out accordingly.

### 2026-09-17 · Third round of review

Places not fully updated after the 0x08 change: the robotctl row in §3.1, the adopt row in §3.6. Corrections: 0x08 doesn't need "raw packet sending", since rustypot v1 already has `Reboot`; `reboot()` must not wait 1 s (called servo by servo in a control loop tick, it would stall for 15 s), so the wait moved to adopt, and `REBOOT_SETTLE` needs to be ≥ 1 s for Feetech; "P written while locked reverts to the EEPROM value after reboot" was downgraded to an inference. Added: phase 18 determines the velocity unit / meaning of speed 0 / direction, read at startup, to-check 13; 41/46 are no longer written at startup; damping mode cannot replace Limp; the EEPROM area is 5–39; the manual doesn't give factory values for P/D; the manual doesn't specify a sign bit for current.

---

## 10. Implementation progress

### 2026-09-18 · First version: `FeetechIo` + protocol selection

In the fork's [`feetech` branch](https://github.com/fanhao375/microduck/tree/feetech) (`8db8f00`, rebased onto upstream 0.14.1 on 2026-09-20), with changes confined to the places listed in §3.1 of the plan and defaults unchanged; a machine without `[bus] protocol` set behaves exactly as before.

| File | What was done |
|---|---|
| `duck-control/src/bus_feetech.rs` (new) | `FeetechIo`: one `sync_read` per tick at address 56, length 15 (position, velocity, load, voltage, temperature, status, current), caching voltage and temperature along the way, so `slow_sensors` no longer needs an extra transaction; goal positions are converted per joint direction and written to 42 as is, clamped to 0–4095; `set_gain` only writes P without unlocking (the write takes effect but isn't saved on power loss), keeping factory D/I; `reboot` turns torque off first and then sends 0x08, without waiting inside the control loop; startup checks END=0 and response level=1 (anything other than 1 is an error), a mode other than 4 only warns without changing it, and phase is read to determine the velocity unit; servo replacement flow: unlock, write ID, lock, reboot, ping the new ID |
| `duck-control/src/bus_select.rs` (new) | `AnyBus` enum choosing one of the two backends (the "`Box<dyn RobotIo>` doesn't compile" point from the plan) |
| `robotd-params` | `[bus] protocol = "dynamixel2" \| "feetech-sts"`, `[bus.feetech] p_scale / directions`; registered in the parameter table so `robotctl configure` can see them |
| `robotd/src/main.rs` | `BusIo` replaced with `AnyBus`, protocol passed when opening the bus; invalid parameters (direction not ±1, wrong count) are reported as errors immediately without retrying |
| `deploy/robotd.toml` | Two new keys, with status comments |

**Not done**: the IMU. This backend's `imu_ready()` is always false, so the daemon doesn't start the policy or fall detection, but `robot init` (interpolating to the standing pose in 2 seconds) still works normally, which is exactly what the first step needs to verify. `imu_source` will be added once the BNO085 arrives.

**Verification**: ran all the tests for the three crates in WSL, 80 for the control library, 150 for the parameter library, and 93 for the daemon, all passing; 11 new tests cover position conversion, direction mirroring, out-of-range clamping, the bit-15 sign, whole-block decoding, the velocity unit, gain mapping, and parameter validation. `cargo fmt --check` and `cargo clippy -D warnings` are clean. The whole set of 11 programs cross-compiles for aarch64 and has been signed with our own development key (`0.13.0-dev.local.1789718569.gb214486`).

### 2026-09-20 · Aligned with upstream 0.14.1

Upstream released 0.14.0 and 0.14.1 on 9/16–9/17, and our branch rebased onto them with **zero conflicts**: across these 55 upstream commits,
`duck-control/`, `robotd-params/`, and the protocol definitions were not touched at all; the only change was a `sitting` status bit added in `robotd/src/main.rs`
(because "standing up" comes in two kinds: from standing it uses `robot.init`, while from sitting in the seat it needs `robot.do sit_toggle`, so the client first has to know which one it is),
which doesn't conflict with our few lines swapping `BusIo`.

This upstream batch was mainly about the phone app (btd added routes for init / enable from the phone), the playground (a web page for kids, one card per trick),
and typed policy specs, and it deleted `fake_duck.py` ("simulation shouldn't be a separately written fake duck"; the robot's own code is now used as the digital twin instead).
All of this is outside our seam, but the `sitting` state will save effort when we build the host software later.

**Steps to put it on the board** (after the board boots):

1. Have the board trust our development public key: `/etc/robot/trusted_keys/replica.dev.pub`, and `allow_dev_keys = true` in `/etc/robot/updater.toml`. Updates don't overwrite this file, and it is off on production machines.
2. Install via the board's updater (`robotctl update apply daemon --from`), which has a health check and automatically rolls back to 0.13.0 if it doesn't come up. At this step `robotd.toml` is still `dynamixel2`; first prove the deployment path works.
3. Edit `robotd.toml`: `port = "/dev/ttyUSB0"` (URT-2 plugged into the board), `protocol = "feetech-sts"`, `[bus.feetech] directions` (checked servo by servo in the web debug console: all 15 are −1, since the direction in which HD-1910 readings increase is opposite to XL330's; the "复制 robotd 方向表" (Copy robotd direction table) button on the page generates this line directly), restart robotd, and check the bus item in `robotctl health`.
4. With the duck hanging, run `robotctl robot init`.
