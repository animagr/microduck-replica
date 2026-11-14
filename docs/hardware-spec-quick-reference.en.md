# Microduck Hardware Spec Quick Reference

**English** · [简体中文](硬件规格速查.md)

> **The repo has four lists plus one printing guide, each with its own scope:**
>
> | Document | Covers | Does not cover |
> |---|---|---|
> | [BOM](../BOM.md) | **Master table**: all parts, quantities (counted from geom references in the MJCF), cost range, unresolved gaps | Which shop to buy from, how to print |
> | [Electronics purchase list](电控采购清单.md) | **Where to buy** the electronics: main controller / camera / ToF / power / the two PCBs / cables, real Taobao links + pitfalls | Basis for quantities, mechanical parts |
> | [Mechanical purchase list](机械采购清单.md) | **Where to buy** the mechanical parts: bearings / fasteners / consumables, real Taobao links | Electronics |
> | **Hardware spec quick reference** (this one) | **Parameters**: interfaces, voltages, protocols, values the software side must match | Prices and shops |
> | [print/README](../print/README.md) | **Printing entry point**: choose version, material and quantity in the CAD repo | Purchasing |
>
> The mapping between assembly part numbers and screws is in the [CAD repo](https://github.com/fanhao375/microduck-replica-cad#装配-bom).


> 📘 Newcomers should read the [hardware primer](硬件入门.md) first (explains one board at a time); for the full derivation see [hardware reverse engineering](硬件方案逆向.md).

> The one-page version. For the full derivation and evidence, see [硬件方案逆向.md](硬件方案逆向.md).
> All data comes from the source code, device trees and config files of `pollen-robotics/microduck` — **the code is the datasheet**.

**In one sentence**: a Radxa Zero 3W (RK3566) running Armbian + one 1 Mbps TTL serial bus carrying 15
Dynamixel XL330s + two custom boards.

---

## System block diagram

```
                ┌──────────────────────────────┐
                │   Radxa Zero 3W (RK3566)     │  65 × 30 mm
                │   Armbian · kernel 6.1.115   │  Pi Zero form factor
                └──┬────────┬─────────┬────────┘
      /dev/ttyS2   │        │ 40-pin  │ MIPI CSI
      1 Mbps TTL   │        │  I2C3   │
    ┌──────────────┘        │ 400kHz  └── IMX219 camera (rotated 90°)
    │                       │
    │              ┌────────▼─────────────────┐
    │              │  Pollen RPI Robot HAT    │  65×30mm custom board (open sourced)
    │              │   ├ TLV320AIC3104  0x18  │  audio codec
    │              │   ├ BMI088   0x19/0x68   │  soldered but unused
    │              │   └ Stemma J5 → ToF 0x29 │  VL53L5CX/L8CX
    │              │  battery power goes via this board │
    │              └──────────────────────────┘
    │
════╪══════════ Dynamixel bus · Protocol V2 · 1 Mbps ══════════
    │
    ├── 15 × XL330   IDs left leg 20-24 / neck-head-beak 30-34 / right leg 10-14
    └── imu_to_dxl v2 board   ID 200   ← LSM6DSV16X
```

**Core design**: one bus does everything. The IMU does not use I2C; it is made into a Dynamixel slave on the servo bus
and read in the **same `sync_read`** as the 15 servos. Battery voltage does not need a fuel gauge either;
it is read directly from the supply voltage the servos report.

---

## Main controller

| Item | Value |
|---|---|
| Module | **Radxa Zero 3W** — a commercially available module, **not a custom carrier board** |
| SoC | **RK3566** (4× Cortex-A55 + Mali-G52 + NPU) |
| Size | 65 × 30 mm, Pi Zero form factor, 40-pin Raspberry Pi compatible header |
| OS | **Armbian** (Debian-based), vendor kernel 6.1.115 |
| Policy inference | ONNX Runtime ≥1.23 (1.28.0 installed), loaded via `dlopen` |
| NPU inference | rknn-toolkit2 — **disabled by default in Armbian**, requires flashing an overlay and rebooting |

> Basis: device tree `compatible = "radxa,zero-3w", "rockchip,rk3566"`;
> "radxa" appears 182 times across the repo.

### Why the rumor says it is a Raspberry Pi

1. The custom board is **literally called "RPI Robot HAT"**
2. Pi Zero form factor + 40-pin Raspberry Pi compatible header
3. The camera is the **Raspberry Pi Camera v2** (IMX219)
4. **The prototype stage really did use a Raspberry Pi Zero 2W** — the comment in `robotd.toml` says the 50 Hz control loop
   *"is inherited from the prototype, where it was chosen on a Raspberry Pi Zero 2W"*

Its predecessor, Open Duck Mini v2, **still uses a Raspberry Pi Zero 2W**, because it does no vision or WebRTC streaming.

### Why it must be a Linux SoC rather than an MCU

It has to run all at once: ONNX policy inference @50Hz, 720p30 H.264 hardware encoding + WebRTC streaming,
NPU object detection, GStreamer congestion control (7.6% of one core), Bluetooth gamepad + phone app + WiFi.
**An STM32 / ESP32 cannot do this.**

---

## Actuators and bus

| Item | Value |
|---|---|
| Motors | **Dynamixel XL330 × 15** (about 18 g each) |
| Electrical layer | **Single-wire half-duplex TTL** (3 wires: data + VDD + GND), 3.3V |
| Protocol | **Dynamixel Protocol V2** |
| Rate | **1 Mbps** (EEPROM `baud_rate = 3`) |
| Port | `/dev/ttyS2` = RK3566 **UART2, M0 pinmux** |
| Devices on the bus | **16**: 15 servos + 1 IMU board |
| Control loop | **50 Hz**, one `sync_read` covers all 16, registers 124–136 |
| Rust library | [`rustypot`](https://github.com/pollen-robotics/rustypot) |

> ❗ **It is neither RS232 nor RS485.** RS485 is differential two-wire, used only by Dynamixel's XM/XH series.
> The XL330 is TTL single-wire half-duplex. Searching the whole repo for `rs485|rs232|direction pin` gives **zero hits** —
> there is no direction-control GPIO in the code; direction switching is done by an automatic hardware direction circuit (on the HAT board).

### Servo ID assignment

```
Left leg         20 21 22 23 24    hip_yaw / hip_roll / hip_pitch / knee / ankle
Neck-head-beak   30 31 32 33 34    neck_pitch / head_pitch / head_yaw / head_roll / mouth
Right leg        10 11 12 13 14    (mirror of the left leg)
IMU board        200
```

**The 15th servo is the beak (ID 34, index 9).** All policies are `obs[1,61] → act[1,14]`,
and the action vector **skips this index** — the beak is controlled by higher-level logic, not by the policy.

### Bus reliability (official measurements)

| Metric | Value | Source |
|---|---|---|
| Drop rate | **About 8 per minute ≈ 0.27%** | *"Measured on a bench robot at ~8 drops a minute"* |
| Official characterization | *"One dropped Dynamixel transaction is **ordinary**"* | `robotd/src/main.rs` |
| Symptom | Small random twitches (a dropped read makes the policy pause for a beat and return to the hold pose) | Same |
| Fault tolerance | `COAST_TICKS = 3` coasts for 60ms on the last good sample | Same |
| Tolerance limit | `max_consecutive_errors = 10` | `robotd.toml` |
| Loop stability | `missed=3` / 15022 ticks, holding 50.0 Hz | `roadmap.md` |
| Stale IMU data | There is a dedicated `StaleImuTracker`, with the comment *"Known to happen"* | `bus.rs` |

Estimated bus utilization is **about 25%** (about 500 bytes/tick ÷ 1 Mbps ÷ 20ms) —
**the bottleneck is not bandwidth but signal integrity and single points of failure**: single-ended 3.3V signaling, 15 servos daisy-chained,
the harness running through a dynamically flexing neck, right next to motor PWM noise sources.

---

## The two Pollen in-house boards (one open sourced, one you must draw yourself)

### ① `imu_to_dxl` v2 — very few parts, the easiest to make yourself

| Item | Value |
|---|---|
| IMU chip | **LSM6DSV16X** (ST 6-axis, with the SFLP hardware orientation-fusion block) |
| Interface | **Dynamixel bus** (not I2C) |
| Bus ID | **200** |
| Register address | **124** |
| Control loop read | 12 bytes |
| Full diagnostic block | 20 bytes (additionally raw acceleration, sample count, status flags) |

**12-byte block layout**

| Bytes | Content |
|---|---|
| `0..6` | gyro x/y/z, `i16` little-endian, ±500 dps, **17.5 mdps/LSB** |
| `6..12` | SFLP quaternion x/y/z, **IEEE fp16**; `w = √(1 − x² − y² − z²)` |

**To make it yourself you need**: an LSM6DSV16X + a small MCU acting as a Dynamixel V2 slave
(STM32G0/G4, CH32V203, ESP32 all work) + a half-duplex TTL transceiver, powered from the bus.

### ② Pollen RPI Robot HAT — officially open sourced, fabricate directly

**65.0 × 30.9 mm, 1.0 mm thick, 4-layer board** (from the official KiCad and Gerbers; see the [BOM](../BOM.md)). The 65.02 × 30.02 × 0.84 measured from the STL mesh is a simulation approximation; **do not use it for ordering**. Plugs onto the 40-pin header.

| Part | I2C address | Notes |
|---|---|---|
| **TLV320AIC3104** | `0x18` | TI audio codec, I2S data + I2C control |
| **BMI088** | `0x19` / `0x68` | **Soldered but unused** (comment verbatim: "dormant") |
| **ToF** | `0x29` | Not on the board; connected externally via **Stemma J5** |

- I2C: 40-pin **pin 3 / pin 5** (`GPIO1_A0`=SDA, `GPIO1_A1`=SCL), **400 kHz**
- Pull-ups: **a single pair of 10k, R12/R13**
- Audio clocks: MCLK **12 MHz**, I2S sysclk **12.288 MHz** (256×48kHz)
- Microphone on **Mic3R** (mono right PGA), all other inputs off
- **The robot's internal power goes through this board**

---

## Sensors

| Type | Model | Interface | Notes |
|---|---|---|---|
| IMU | **LSM6DSV16X** | Dynamixel bus ID 200 | On-chip SFLP outputs the quaternion; the host runs no fusion |
| ToF | **VL53L5CX / VL53L8CX** | I2C `0x29` @ i2c3 | 15 Hz, multizone ranging |
| Camera | **IMX219** (Raspberry Pi Camera v2) | MIPI CSI, I2C `0x10` | **Rotated 90°**, see [hardware reverse engineering](硬件方案逆向.md#七传感器) |

- The camera sensor is pinned to the 1920×1080@30 mode (avoiding the 21 fps cap of the default boot mode),
  with ISP-scaled output, default 720p30 @ 2 Mb/s
- Encoding uses the **Rockchip MPP hardware encoder** → WebRTC
- HFOV about 62°

---

## Power and battery

| Item | Value |
|---|---|
| Battery | **Sony NP-F550** (L-series camcorder battery). ⚠️ The upstream mesh name `np_f970` is misleading; the measured size is F550 |
| Configuration | **2S Li-ion**, nominal 7.2 V |
| Full (under load) | **8.2 V** |
| Empty (under load) | **6.6 V** |
| Fuel gauge | **None** |
| ADC | **None** |

> Comment verbatim: *"There is no fuel gauge and no ADC. The only measurement available is
> what the servos report as their own supply."*

**The voltage is read directly over the Dynamixel protocol from the servos' reported supply voltage** — i.e. "the battery as seen from the bus",
which sags under load and recovers at rest. So 6.6–8.2 V is the **usable range under load**, not the cell chemistry range.

When the battery EMA (about 10 s time constant) drops to 6.6 V → **it automatically sits down gracefully and shuts off**.

> 💡 Replica friendly: **no need to design any battery monitoring circuit.**

---

## All interfaces at a glance

| Interface | Purpose | Parameters |
|---|---|---|
| **UART2** (`ttyS2`) | 15 servos + IMU board | 1 Mbps, TTL half-duplex |
| **I2C3** (pin 3/5, M0) | Audio codec / ToF / (the unused BMI088) | 400 kHz |
| **I2S3** | Audio data | MCLK 12 MHz, sysclk 12.288 MHz |
| **MIPI CSI** | IMX219 camera | I2C control `0x10` |
| Bluetooth | Gamepad (`padd`), phone app (`btd`) | Onboard |
| WiFi | WebRTC streaming, network provisioning (`configd`) | Onboard |
| USB-C | Power + maskrom flashing | **PD negotiation sacrificed by the overlay** |

---

## Parameters the software side must match

| Parameter | Value | Notes |
|---|---|---|
| Control loop | **50 Hz** | Inherited from the Raspberry Pi prototype, **never re-validated on the Radxa** |
| Policy interface | `obs[1,61] → act[1,14]` | Checked at load time; the old 51-dim version is rejected |
| `action_scale` | 0.9 (walk) / 0.8 (roller) | |
| Position P gain | **200** | ×0.8 when standing |
| Action low-pass | head **0.5** / legs **0.7** | **Must match training**, otherwise transfer degrades |
| Voltage adaptation | Off by default | `scale × (7.4 / measured EMA)`, clamped to 6.0–9.5 V |

---

## Replica checklist: what you can buy vs what you must make

| Part | Status | Notes |
|---|---|---|
| Radxa Zero 3W | ✅ Buy directly | Commercially available module |
| Dynamixel XL330 × 15 | ✅ Buy directly | **The biggest cost, $359–€629** (huge price differences between channels, see the [BOM](../BOM.md)) |
| **NP-F550** battery + holder | ✅ Buy directly | Generic camcorder accessory. **Do not buy F970** |
| Raspberry Pi Camera v2 (IMX219) | ✅ Buy directly | |
| VL53L8CX module | ✅ Buy directly | Stemma/Qwiic, in stock |
| **`imu_to_dxl` board** | 🔧 **Draw it yourself** | Protocol fully reconstructed, only 3 parts |
| **HAT board** | ✅ Download the official Gerbers and fabricate | 4-layer. If you do not need recording/speaker it can be dropped entirely, but **the half-duplex direction circuit must then come from a separate adapter board**; see the [electronics purchase list](电控采购清单.md#六两块-pcb) |
| Control software | ✅ Official, Apache-2.0 | With the same controller it **runs as is** |
| Policies | ✅ 9 official ONNX files | Usable as long as the hardware is unchanged |

> 💰 **Cost reminder**: the 15 XL330s alone cost **$359–€629** (from $23.90 on the ROBOTIS international store, up to €41.95 incl. VAT in Europe),
> already far more than the complete robot's **$399** price. $399 is a price at scale.

---

## Three pitfalls you will hit

1. **Armbian runs a login console on UART2 by default** — the `agetty` of `serial-getty@ttyS2`
   holds the serial port. You must run `systemctl mask serial-getty@ttyS2`.
   The official team found it with `fuser -v /dev/ttyS2`.

2. **i2c3 fights the FUSB302 for pins** — in the stock DTB, the RK3566's i2c3 runs the M1 pinmux
   to serve the USB-C PD controller; using M0 on pins 3/5 means disabling fusb302 and **losing PD negotiation**.
   Fortunately the FUSB302 presents Rd on CC by default at power-up, so ordinary 5V charging still works.

3. **The NPU is disabled by default** — Armbian does not enable it out of the box; running rknn models requires flashing an overlay and rebooting.

---

## Conclusion

**Nothing in this hardware is impossible to replicate.** The main controller is a commercially available module; of the two Pollen in-house boards,
**the HAT board is fully open sourced by the official project** (KiCad + Gerber + BOM + pick-and-place, download and fabricate),
and the only one you really have to draw yourself is `imu_to_dxl` — which has very few parts and a fully reconstructed protocol.

The real barrier is **cost** (15 XL330s cost more than the complete robot), not technology.

> Data sources: `duck-control/src/{model,imu,bus}.rs`, `robotd/src/main.rs`,
> `deploy/robotd.toml`, `deploy/audio/*.dts`, `deploy/overlays/*.dts`,
> `tof/src/*.rs`, `mediad/src/*.rs`, `docs/design/robotd-design.md`,
> `docs/project/{media-bringup,roadmap}.md`

---

## Official specs vs this repo's reverse engineering (cross-check)

The official release on 2026-08-27 published some specs. The table below compares **what was officially published** with **what this repo reverse engineered from the source code**
item by item — the two sides corroborate each other, and each fills in information the other lacks.

| Item | Officially published | Reverse engineered by this repo | Verdict |
|---|---|---|---|
| SoC | RK3566, quad-core A55 @1.8GHz, Mali-G52, NPU **0.8 TOPS** | RK3566 (device tree `compatible`) | ✅ Consistent |
| **Main controller module** | **Not published** | **Radxa Zero 3W** | 🔍 **Only from reverse engineering** |
| RAM / storage | **1 GB RAM / 32 GB storage** (does not say eMMC) | No corroboration in the source code | 🆕 **Only from the official specs**.<br>For the replica, a 1G or 2G no-eMMC version + a 32 GB microSD is enough; see the [electronics purchase list](电控采购清单.md#该买哪个配置) (2026-10-12 correction) |
| Battery | **NP-F550, 2600 mAh, about 1 hour of runtime** | NP-F550, 2S, 8.2 V full / 6.6 V empty | ✅ Consistent |
| ToF | **8 × 8** LiDAR | VL53L5CX / VL53L8CX @ `0x29` | ✅ That series is exactly 8×8 |
| Camera | Front camera with indicator light | **IMX219** (Pi Cam v2), I2C `0x10`, **rotated 90°** | 🔍 Reverse engineering is more detailed |
| **IMU** | **2 (body + head)** | LSM6DSV16X **in use**; BMI088 marked **dormant / unused** in the source | ⚠️ **Contradiction, see below** |
| Motors | 15 DOF, articulated beak that can grasp | 15 × Dynamixel XL330, with the full ID table | ✅ Consistent |
| Size and weight | 25 cm tall, **14 cm** wide, < 800 g | Measured **144 × 141 × 264 mm**, **737.2 g** | ✅ Consistent |
| **NFC** | **Dual antennas** | **No mention at all** in the source | 🆕 **Only from the official specs** |
| Audio | Microphone + speaker | TLV320AIC3104 @ `0x18`, microphone on Mic3R | 🔍 Reverse engineering is more detailed |
| **Main bus** | **Not published** | TTL half-duplex 1 Mbps, `/dev/ttyS2`, Protocol V2 | 🔍 **Only from reverse engineering** |
| Connectivity | Wi-Fi, Bluetooth | Same (onboard the Radxa) | ✅ Consistent |

### ⚠️ That contradiction: officially 2 IMUs, the software uses only 1

The official specs say **"2× IMUs (body and head)"**, but in the source code:

- **Only the LSM6DSV16X is in use** — `imu.rs` opens with *"One IMU, one code path"*
- The **BMI088** on the HAT board is marked **"dormant"** and
  **"(unused but still connected)"** in the device tree comments

**Conclusion: the second IMU is physically soldered on the board, but the factory software does not use it.** A replica can simply leave it out.

---

## Open-source status: the official position (2026-08 update)

> CNX Software's report verbatim:
> *"While the Microduck's software stack is open source, nothing was said about the
> mechanical and hardware design files, and **Pollen Robotics told the press not to
> refer to the robot as 'open-source hardware' (for now)**."*

**Interpret this carefully.** What the official team declined is the **label** "open-source hardware" for the complete robot,
which does not mean no board was published at all — in fact the **RPI Robot HAT board is fully open source**
([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Apache-2.0,
with the KiCad project, Gerbers, BOM and pick-and-place). What really has not been published is the `imu_to_dxl` board,
editable mechanical CAD, the complete-robot BOM and assembly documentation.

That **"(for now)"** leaves the door open, without a timeline.

> Erratum 2026-09-03: this document previously said "not open sourcing the hardware is a line the official team drew deliberately"; that was too strong and has been corrected.

### External validation: someone independently reached the same controller conclusion

On 2026-08-31, [@tspy](https://x.com/tspy/status/2094249218735300630) on X posted a
"Microduck physical architecture breakdown" (169 likes), independently listing:

> Actuators 15 × Dynamixel XL330 · controller **Radxa ZERO 3W / Rockchip RK3566** ·
> 1 GB RAM + 32 GB · dual 6-axis IMU · 8×8 ToF · forward camera · 2× NFC antennas ·
> battery NP-F550 · control frequency 50 Hz

**Fully consistent with this repo's reverse-engineering conclusions**, including the most crucial point, the **Radxa Zero 3W** —
two independent paths reaching the same answer greatly increases confidence.

> 📌 **Note: as of 2026-08-31 there are no physical units on the market** (shipping only starts before Christmas).
> So every "teardown" so far is **inference from the public software and specs**, not a physical teardown.
> This repo's depth (I2C addresses, register layout, the 12-byte data block, bus protocol)
> goes one layer beyond the spec list, by reading the Rust source code as a datasheet.

In the same thread, when asked about cost, @tspy's answer also matched this repo: **"the cost seems higher than just buying it"**.

### Three issues the community is pressing (none answered officially as of 2026-08-31)

| Issue | Request |
|---|---|
| [#175](https://github.com/pollen-robotics/microduck/issues/175) | Wants **STEP files** — STLs have no normal information, so curved surfaces render as polygonal facets |
| [#173](https://github.com/pollen-robotics/microduck/issues/173) | Wants **3D printing source files** |
| [#174](https://github.com/pollen-robotics/microduck/issues/174) | Asks whether the battery can be charged in place, and asks directly **whether the power board schematic is in the open-source plans** |

We checked the last ~10 issues: **Pollen members have not replied to a single one**, yet the repo is still updated daily.

> This also shows the value of what this repo does: nobody in the community has reconstructed assembly drawings from the MJCF so far,
> and nobody has systematically extracted the electronics design from the Rust source code.
