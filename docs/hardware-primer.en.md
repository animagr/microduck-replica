# Hardware Primer: One Board at a Time

**English** · [简体中文](硬件入门.md)

> This document answers one question: **how many boards are actually in a Microduck, and what does each one do.**
>
> How it divides the work with the other two:
> [Hardware reverse engineering](hardware-teardown.en.md) is the **derivation process and sources of evidence** (for people who want to verify),
> [Hardware spec quick reference](hardware-spec-quick-reference.en.md) is the **one-page spec sheet** (for people who already know and want to look things up).
> This document is the **introductory explanation**, assuming you are new to the project.
>
> Every conclusion can be checked yourself — the last section, [How to check it yourself](#九怎么自己核对复刻前必做的五件事),
> explains how.

---

## 1. The big picture first: five modules, only two you have to make yourself

```
                    ┌─────────────────────────────────────────┐
                    │  Head (the jaw_soft rigid body in MJCF)  │
                    │                                          │
   MIPI CSI ────────┤  ④ IMX219 camera + M12 lens              │
   (about 13mm,     │        ↕ same rigid body, no joint between│
    not via neck)   │  ① Radxa Zero 3W    main controller      │
                    │        ↕ 7.3mm stack gap, 40-pin header   │
                    │  ② RPI Robot HAT    power / audio / bus   │
                    │        └─ Stemma port ──► ⑤ ToF module    │
                    │  Speaker                                  │
                    └──────────────┬──────────────────────────┘
                                   │
                    ═══════════════╪══════ through the 3-DOF neck ══════
                     servo bus (1 pair) │ battery supply line (+BATT)
                                   │
                    ┌──────────────┴──────────────────────────┐
                    │  Torso (trunk_base)                       │
                    │   two hip_yaw XL330 — cavity nearly full  │
                    │   ③ imu_to_dxl board (on the servo bus)   │
                    └──────────────┬──────────────────────────┘
                                   │
                     NP-F550 battery ─┘ mounted externally at the lower rear
                     of its 71mm length about 40mm hangs outside the shell,
                     clamped from the outside by two power_support pieces
```

| # | Module | In one sentence | Where it comes from |
|---|---|---|---|
| ① | **Radxa Zero 3W** | The brain. Runs Linux, the neural network policy, vision | 🛒 Buy |
| ② | **RPI Robot HAT** | Power distribution + sound card + servo bus interface | 🏭 **Officially open source, fabricate it yourself** |
| ③ | **imu_to_dxl** | Disguises the IMU as a fake servo | ✏️ **You have to draw it yourself** |
| ④ | **IMX219 camera** | The eyes | 🛒 Buy |
| ⑤ | **ToF module** | 8×8-zone ranging, not lidar | 🛒 Buy |

> ⚠️ **Three common misconceptions**
> 1. **There is no lidar.** The ToF is a multizone ranging module (4×4 or 8×8 zones), not a lidar.
> 2. **Audio is not a separate module.** The codec, amplifier and microphone are all on the HAT.
> 3. **The main controller is not in the torso, it is in the head.** This is the easiest one to get wrong, and it directly affects how long a ribbon cable you buy.

---

## 2. ① Main controller · Radxa Zero 3W

**What it does**: runs Armbian Linux, runs the Rust runtime `robotd`, runs ONNX policy inference, runs vision.
In one sentence — **apart from driving the motors, it does everything**.

| Item | Value |
|---|---|
| SoC | Rockchip **RK3566**, quad-core Cortex-A55 @1.6GHz |
| NPU | 0.8–1 TOPS INT8, node `npu@fde40000`, **disabled by default in Armbian**, needs an overlay |
| Form factor | **65 × 30 mm**, Raspberry Pi Zero form factor, 40-pin header |
| OS | Armbian **headless** image |

**Why this board and not a Raspberry Pi**: it is a **commercially available module**, not a custom carrier board — this is important,
because it means the replica does not need to make a controller board. The device tree hardcodes `compatible = "radxa,zero-3w"`.

**Which 40-pin pins it uses** (extracted from the official HAT schematic):

| Pin | Purpose | Linux device |
|---|---|---|
| **GPIO14 / GPIO15** | **Dynamixel UART Tx / Rx** | `/dev/ttyS2` @ 1 Mbps |
| **GPIO02 / GPIO03** | I²C — IMU + audio + Stemma | `i2c3` @ 400 kHz |
| GPIO18 / 19 / 20 / 21 | Audio PCM Clk / FS / Din / Dout | `i2s3_2ch` |
| GPIO06 | Shutdown detection (Switch off detection) | |
| GPIO22 | Interrupt pin of the BMI088 on the HAT (**not used by software**) | |
| GPIO00 / 01 | HAT identification I²C (reserved) | ⚠️ See the HAT section |
| GPIO04/05, 08/09, 10/11 | Extra Stemma/QT I²C | |
| MIPI CSI | Camera | |

**Which configuration to buy**: a 1G or 2G bare board **without eMMC**, plus a 32 GB microSD card, only from official channels. For the hardware test and reasoning, see the [electronics purchase list](electronics-purchase-list.en.md).
The official material says 1 GB RAM, 32 GB storage (without saying eMMC). (2026-10-12 correction: the "2G / 16G eMMC" written previously is unnecessary.)

---

## 3. ② RPI Robot HAT — one board doing four jobs

**This is the only board that is fully open sourced by the official project** ([`pollen-robotics/elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT),
Apache-2.0, including the KiCad project + Gerber + BOM + pick-and-place).

**Specs** (measured from the Gerbers): 4-layer board, **65.0 × 30.9 mm**, corner radius R3.5, BOM 47 lines / 123 parts,
of which 5 lines / 9 parts are DNP, **113 placements** actually populated.

### Function block 1: power distribution

```
NP-F550 battery ──► +BATT ──┬──► servos (direct, no step-down)
  2S, 6.6–8.2V              │
                            └──► U9 AP63205 + L4 6.8µH ──► Q2 / U10 LM5050-1 ──► +5V
                                   buck, 2A, Fsw 1.1MHz      ideal diode + shutdown detection │
                                                                                        ├─► controller 40-pin
                                                                                        ├─► PAM8406D amplifier
                                                                                        └─► U3 XC6206P182 → +1V8 (codec)
```

**There is a counterintuitive fact here: the servos get raw battery voltage, not 5V.**

The XL330's official rating is **3.7–6.0 V, 5.0 V recommended**, yet here it gets **6.6–8.2 V**.
This is not a guess; the schematic says so directly: the power pins of all four Dynamixel connectors J13/J14/J3/J11 go to `+BATT`,
with the note "3A max". And **the whole board has only one buck (U9) and one inductor (L4)**; that 5V rail is for the controller
— the 2A AP63205 could not drive 15 XL330s anyway (about 1.5A each at stall).

See [the voltage truth](actuator-selection.en.md) for details.

> `+3V3`, conversely, is **supplied to the HAT by the controller via the 40-pin header**; the HAT does not generate it itself.

### Function block 2: servo bus (half-duplex TTL)

Bus servos like Dynamixel / Feetech are all **single-wire half-duplex** — one wire both sends and receives, switched by direction control.

| Part | Role |
|---|---|
| **U6 `SN74LVC1G125`** | Tri-state buffer, transmit direction |
| **U7 `SN74LVC1G126`** | Tri-state buffer, receive direction |
| **U5 `74LVC1G08`** | AND gate, part of the direction logic |
| **U8 `SIT3088E`** | RS-485 transceiver (for the two 4P ports) |
| **TH1 100R** | Thermistor, overcurrent protection |

Direction is controlled by `Dynamixel_dir`; the official note says **"Dynamixel_dir is based on Tx"** — the direction is derived automatically from the transmit signal.

**Four connectors, two kinds**:

| Ref | Type | Used by |
|---|---|---|
| **J13 / J14** | **JST EH 3P** (TTL) | **Microduck's XL330s use these two**, to `+BATT` via TH1 |
| J3 / J11 | JST EH 4P (RS-485) | Driven by U8, directly on `+BATT` |

> 💡 **JST EH is 2.5 mm pitch**, and Feetech servo cables are labeled **5264 terminals**, also 2.5 mm.
> On the Chinese market "5264" is basically the generic name for 2.5mm 3P — it will most likely plug straight in, but the housing latch details
> should be confirmed with the real parts.

### Function block 3: audio

| Part | Role | Address |
|---|---|---|
| **U2 `TLV320AIC3104`** | Audio codec, I²S data + I²C control | i2c3 `0x18` |
| **U1 `PAM8406D`** | Class-D amplifier | |
| **MK1** | Onboard MEMS microphone (LCSC `C7587901`, model not given officially) | |
| J1 | Wago screwless terminal for the **5W speaker** | |
| J2 / J9 | Wago terminals for an external microphone | |

Audio clocks: MCLK from a fixed 12 MHz oscillator, I²S sysclk 12.288 MHz (256 × 48 kHz).

> **If you do not need recording or the speaker, this whole block can be left out.**

### Function block 4: sensor expansion

- **J5–J8**: JST SH 1.0 mm 4P (Qwiic / Stemma QT) — the ToF connects here
- **U11 `BMI088`**: ⚠️ **populated, but the software does not use it at all**. The device tree comments say `dormant`,
  `unused but still connected`. When people say Microduck "has two IMUs", this is the one they mean
- **U4 `CAT24C32`** EEPROM: ⚠️ **DNP, not populated** — so this board is **not a self-identifying HAT**,
  even though the schematic says "HAT Identification: I2C add. 0x50 / Standard Class HAT+"

### This board cannot be bought; what to do

**Pollen does not sell it separately**, only the complete robot. Two options:

1. **Faithful fabrication** — take the official Gerber + BOM + pick-and-place and order from JLCPCB. 4-layer + SMT, from several hundred yuan, with minimum order quantities.
2. **Replace it with ready-made modules** — a ¥22 ST/SC half-duplex adapter board + a UBEC replaces both required functions, "servo bus" and
   "power distribution", and the ToF hangs directly on i2c3. The cost is losing the onboard audio. See the [electronics purchase list](electronics-purchase-list.en.md).

---

## 4. ③ imu_to_dxl — the cleverest trick in the whole electronics design

**This board does only one thing: disguise the IMU as a fake servo.**

It is an **STM32G031F8P6 + LSM6DSV16X** (ST 6-axis IMU) + half-duplex buffer,
presenting itself externally as a slave on the servo bus with **ID = 200**.

### Why the roundabout approach

The intuitive approach is to connect the IMU directly to the controller via I²C or SPI. But that has a problem:

**IMU data and servo data take two different paths, and their sampling instants do not line up.**

The policy runs at 50 Hz, and each tick needs both "body orientation" and "15 joint angles" at the same time.
If the IMU goes over I²C and the servos over UART, there will be a few milliseconds of jitter between them — and jitter directly pollutes the policy input.

Pollen's approach is to **make the IMU speak the servo language too**, so the host sends **just one `sync_read`** per tick
and gets back the IMU orientation + 15 servo positions together, **with timestamps naturally aligned**.

### Protocol and registers

| Item | Value |
|---|---|
| Protocol | Dynamixel **Protocol V2** |
| ID | **200** |
| Baud rate | **1 Mbps** (EEPROM register `baud_rate = 3`) |
| Start register | **124** |
| Length | **12 bytes** |

Layout of the 12 bytes:

| Offset | Content |
|---|---|
| `0..6` | gyro x/y/z, `i16` little-endian raw counts, range **±500 dps**, **17.5 mdps/LSB** |
| `6..12` | SFLP quaternion x/y/z, **IEEE half-precision fp16**; `w = √(1 − x² − y² − z²)` |

**Note that `w` is not transmitted** — it is recomputed on the host from the unit-quaternion constraint, saving 2 bytes.

**SFLP** is the **hardware sensor-fusion block** inside the LSM6DSV16X chip; it outputs a game rotation quaternion directly
— the host does not need to run its own orientation fusion.

### 16 devices on the bus in total

```
ID  10 11 12 13 14   right leg
ID  20 21 22 23 24   left leg
ID  30 31 32 33 34   neck / head / beak
ID  200              imu_to_dxl board
```

15 servos + 1 IMU board = **16 devices, all read back with a single `sync_read`**.

### Notes for the replica

- **The protocol and register layout have been fully reconstructed**; just implement it as described ([hardware reverse engineering](hardware-teardown.en.md))
- **Use a 2.5 mm pitch 3P connector** (JST EH / 5264)
- **Input capacitor voltage rating ≥25 V** — the bus is 8.4 V fully charged; a 10 V rating is not enough margin (and MLCCs also lose capacitance under DC bias)
- **Add a pull-up on the CS pin** — see the real case in the next section
- **Add a TVS on the DATA line** — hot-plugging servos is normal

---

## 5. ④ IMX219 camera

MIPI CSI interface, 8 megapixels. The device tree overlay is `radxa-zero3-rpi-camera-v2`,
and the ISP config has `SENSOR = imx219`.

**Two pitfalls:**

1. **It is rotated 90°, not flipped 180°.** The code says
   `/// 90, because the head camera is mounted a quarter turn off, and this is the one place
   that fact is written down.` Some early material says 180; that is data from the **alpha unit**.
2. **Buy the shortest ribbon cable.** The camera and controller are **on the same rigid body, about 13 mm apart, with no joint in between** —
   the MIPI cable does not pass through the neck. 4–15 cm is enough; do not buy 30 cm.

> ⚠️ Radxa's official documentation only says "1x4-lane MIPI CSI" and **gives no pin count or pitch**.
> But the board is a Pi Zero form factor with the CSI connector on the same edge as the Micro HDMI, so it is **very likely the narrow 22-pin 0.5 mm type**,
> whereas generic IMX219 modules come with the standard 15-pin cable — keep an adapter cable on hand (a few yuan).

---

## 6. ⑤ ToF module

**It is not a lidar.** It is an ST FlightSense multizone ranging chip that outputs an **8×8 distance matrix**.

| Item | Value |
|---|---|
| Model | **VL53L5CX or VL53L8CX**, auto-detected by the firmware from the revision ID (`0x02` = L5cx, `0x0C` = L8cx) |
| Interface | I²C, on **i2c3 @ 400 kHz** |
| Address | **`0x29` or `0x52`** (both candidates are tried) |
| Physical connection | **JST SH 1.0 mm 4P** on the HAT (Qwiic / Stemma QT) |
| Frame rate | 15 Hz |

> ⚠️ **Do not end up with a VL53L0X** — that is **single-point** ranging, and the firmware does not recognize it.
> **The VL53L7CX is not an L8CX either** (the L7 is a different chip with a 90° field of view).

---

## 7. What happens in one tick

The policy runs at 50 Hz, i.e. **one round every 20 ms**:

```
   ① One sync_read                    ttyS2 @ 1 Mbps
      ├─ ID 200  → gyro + quaternion   ┐
      ├─ ID 10~14 → 5 right-leg angles  ├ 12 bytes × 16 devices
      ├─ ID 20~24 → 5 left-leg angles   │  timestamps naturally aligned
      └─ ID 30~34 → 5 neck/head/beak    ┘

   ② Assemble the 61-dim observation vector

   ③ ONNX policy inference (a small 775 KiB network) → 14-dim action

   ④ Voltage adaptation: scale × (7.4 / measured battery voltage EMA)
      — as the battery drops from 8.4V to 6.5V, the same PWM gives very different torque; without compensation the policy drifts

   ⑤ One sync_write sending the 14 target positions
```

Running alongside: the ToF (15 Hz) and audio codec on **i2c3**, and the camera on **MIPI CSI**.

> ⚠️ **The 20 ms budget is tight, and it is not only a Feetech problem.**
> The official source code says: the XL330 ships with `return_delay_time = 250`, i.e. **a 500 µs turnaround delay per device**,
> "Across 16 devices that is **8 ms per tick — 40% of a 20 ms budget**".
> The official fix is to **write 0** to this register.
> Whatever servo you switch to, this step has to be redone and tested on real hardware.

---

## 8. What changes on the Feetech route

Many people (including this repo) are evaluating Feetech servos as a replacement for the XL330. Impacts by severity:

| Impact | Notes |
|---|---|
| 🔴 **The 9 official ONNX policies will most likely stop working** | With different servos, the torque curves, masses and possibly even the gear ratios differ. **Retraining is required** (needs a CUDA GPU or HF jobs) |
| 🟡 **Bus timing must be measured on real hardware** | Feetech uses its own STS/SCS instruction set (including `0x82 SYNC READ`) with a different packet format. **But do not assume it must be slower** — the official Dynamixel path also has a per-device turnaround delay (see above). The first thing to do on arrival is run a benchmark, with an **FE-URT-1 debug board** |
| 🟡 **`imu_to_dxl` needs to be repositioned** | The bus protocol changes, so this board either becomes an emulated Feetech slave, or the "on the bus" design is dropped and the IMU connects directly via SPI. **Recommendation: same hardware, dual-protocol firmware** — the physical layers are identical (half-duplex single-wire TTL / 1 Mbps / 3 wires); the differences are in the **packet format** and **factory defaults**; see "Feetech STS/SCS protocol comparison" in [hardware reverse engineering](hardware-teardown.en.md) |
| 🟢 **The voltage actually fits better** | The Feetech HD-1910 natively takes 5–8.4 V, so it does not have to run overvolted like the XL330 |

---

## 9. How to check it yourself: five things to do before building a replica

**This section is more important than everything above.**

Open-source project material goes out of date and contains errors, and AI-generated schematics even more so. Below are the checks this repo
has distilled from practice — each one corresponds to a real failure.

### 1. Pin definitions: open the datasheet's pin table and check one by one

**Real case:** this repo received a schematic PR for `imu_to_dxl`. The drawing was very complete, but it wired the
LSM6DSV16X pins wrong — checking against **ST DS13510 Rev 1 Table 1** (page 10) showed:

| Pin | Datasheet definition | Drawn in the PR |
|---|---|---|
| **12** | **CS** (chip select) | ❌ Misplaced |
| **13** | **SCL** (SPI clock) | ❌ Misplaced |
| **14** | **SDA** (SPI data) | ❌ Misplaced |
| **2 / 3** | **SDx / SCx auxiliary interface**; when unused the datasheet requires **tying to GND** | ❌ Treated as the main interface |

A board built from that would **not work**. And finding it took only one thing: **open the datasheet, go to the pin table, check line by line**.

> **Drawing a schematic without reading the datasheet is as good as not drawing it.** No exceptions.

### 2. Voltage margin: each capacitor's rating vs the actual bus voltage

In the same PR, the input capacitor was rated **10 V**, while the bus is **8.4 V** fully charged. That looks like margin, but:
- MLCCs have a **DC bias effect**; with 8.4 V on a 10 V-rated MLCC, the actual capacitance may drop by more than half
- The battery and motor back-EMF produce spikes

**Rule: the voltage rating should be at least 2× the working voltage.** For an 8.4 V bus, use 25 V.

### 3. Power-up state: what level the mode-select pin is at the instant of power-up

The level of the LSM6DSV16X's CS pin **at power-up decides whether it uses SPI or I²C**. If CS is floating,
the state at power-up is undefined — sometimes it works, sometimes it does not, the hardest kind of bug to track down.

**Add a 10 kΩ pull-up to 3V3** to lock it into SPI mode.

### 4. Run ERC, and get it to 0 errors, 0 warnings

You can run it from the KiCad command line:

```bash
kicad-cli sch erc --output erc.rpt your.kicad_sch
```

Common real problems: power pins with no driving source (missing `PWR_FLAG`), two power outputs tied together,
pin coordinates off the connection grid (looks connected but actually is not).

### 5. Cross-check: addresses and registers in the software source vs the hardware

Microduck's software is open source, and **the code is the datasheet**. Every address on the hardware has a counterpart in the code:

| Hardware | Evidence in the software |
|---|---|
| Audio codec `0x18` | `deploy/audio/i2c3-pihat.dts` |
| ToF `0x29` / `0x52` | `ADDRESS_CANDIDATES` in `tof/src/main.rs` |
| IMU board ID 200 | `IMU_DXL_ID` in `duck-control/src/model.rs` |
| Servo ID assignment | Same file, `JOINT_IDS` |
| i2c3 400 kHz | `clock-frequency` in `i2c3-pihat.dts` |
| BMI088 unused | `i2c3-pihat.dts` comments: `dormant`, `unused but still connected` |

**If they do not match, one side is wrong.**

---

## Appendix: sources for every conclusion in this document

| Conclusion | Source |
|---|---|
| Where the boards are mounted | `robot_walk.xml:235` (HAT), `:247` (controller), both in the `jaw_soft` body |
| 40-pin allocation | GPIO table in `ASE01187-C1_elec_RPI_Robot_HAT_SCH.pdf` |
| HAT board specs | Measured from Gerber `Edge_Cuts.gm1`; BOM.csv 47 lines / POS.csv 117 lines |
| Servos on `+BATT` | Schematic Dynamixel page (4/6), note "3A max" |
| Only one buck | The whole BOM.csv has only one inductor, L4 (FB1/2/3 are ferrite beads) |
| 12-byte register layout | `robotd` source, see [hardware reverse engineering](hardware-teardown.en.md) |
| Camera rotated 90° | `mediad/src/main.rs:82` |
| 8 ms turnaround delay | `duck-control/src/model.rs:84-86` |
| LSM6DSV16X pins | **ST DS13510 Rev 1, Table 1, page 10** |

> This document is derived from the officially published MJCF model, STL meshes, open-source hardware projects and runtime source code,
> and **has not been verified on physical hardware**. If you find an error, please open an issue.
