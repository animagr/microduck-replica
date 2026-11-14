# imu_to_dxl Schematic + PCB · Review Wanted

**English** · [简体中文](README.md)

> ⚠️ **This is a third-party replica part, not the official design.**
> The official team has never published this board's schematic, Gerbers or outline (zero hits anywhere online; see
> [Hardware reverse engineering](../../docs/硬件方案逆向.md)). This directory is the result of reverse-engineering from the MJCF model, the official runtime source code
> and the open-source HAT project, plus my own component choices. **It has not been prototyped or verified on real hardware.**
> If you find a problem, please open an [issue](https://github.com/fanhao375/microduck-replica/issues).

![imu_to_dxl schematic](../../assets/hw/imu_to_dxl-原理图.png)

| File | Description |
|---|---|
| [`imu_to_dxl-原理图.pdf`](imu_to_dxl-原理图.pdf) | Vector PDF (schematic); zoom in for details |
| [**`imu_to_dxl-交互式BOM.html`**](imu_to_dxl-交互式BOM.html) | **For soldering**: interactive BOM exported from EasyEDA (JLC EDA); download it and open it directly in a browser (works offline). Click a part number and the matching reference designators are highlighted on the board view, so you can tick off each part type as you solder it. Clicking it on the GitHub page only shows the source |
| [**`firmware/`**](firmware/) | STM32G031 + LSM6DSV16X firmware, Keil project, host tests and a prebuilt HEX; from 0.2.0 on it uses the Feetech SCS/STS protocol (ID 200); not yet tested on a real bus |
| [**`firmware-1.0.0/`**](firmware-1.0.0/) | Another Feetech protocol firmware, 1.0.0: branched off from 0.1.0 (the Dynamixel version), **tested on a shared bus with real Feetech servos** (slot ordering, reads/writes), with host-side tools for scanning / bus monitoring / IMU plots and a Chinese user guide. Same 15-byte block and model number (0x4D44) as 0.2.0; the main program from replica image 20261021b on recognizes both versions |
| [**`总线协议.md`**](总线协议.md) | **For firmware writers** (bus protocol): byte-by-byte definition of the 15-byte block, timing requirements, queuing rules, the main controller's acceptance criteria, test vectors, acceptance check method |
| [`imu_to_dxl-接线表.md`](imu_to_dxl-接线表.md) | Wiring table listing every pin net by net; you can check against it directly |
| [`imu_to_dxl.eprj2`](imu_to_dxl.eprj2) | EasyEDA Pro (JLC EDA) project; open and edit it directly |
| [`../../BOM.md`](../../BOM.md) | Full BOM, including LCSC part numbers and the selection rationale for every component |

**Firmware and attitude viewing entry point:** [`firmware/README.md`](firmware/README.md) documents single-board bring-up, IMU sampling and the validation scope.

**Which of the two firmware versions to choose**: either works when connected to the duck and used with the fork's main program. The main program (from replica image 20261021b on) recognizes this board and, when reading the whole body at once, places it **after the servos**: in testing, with 1.0.0 placed first it answered only 3 times out of 30 (the following servos rush to talk on their own timing and overwrite its checksum byte); placed in the middle or last it scored 30/30. To view the attitude with servo-web over SWD / J-Link, you can only use the 0.2.0 HEX in `firmware/`: the observer checks against its hash and memory addresses and will refuse to read if you switch to 1.0.0. Neither version has run for a long time on the complete robot yet.
Through [`tools/servo-web`](../../tools/servo-web), the small board's attitude can be overlaid on the 3D duck in the servo debug console: joint angles come from the servos, and the torso quaternion comes from the IMU.
Three ways to read it: `--imu-bus` (over the servo bus, in the same sync_read as the main controller, reading the 15-byte block at address 56 of ID 200), `--imu-swd` (ST-Link / DAPLink), `--imu-jlink` (J-Link).
The `imu200.py check` acceptance check on a real bus has not been done yet.

---

## What this board does

The 15 servos of the official Microduck hang on one Dynamixel half-duplex bus. This small board
**hangs on the same bus as the 16th device** and presents itself externally as a Dynamixel slave (ID 200);
the main controller requests attitude data from it by reading registers.

The IMU on the board is the **LSM6DSV16X**, which has an on-chip **SFLP hardware fusion block**
that directly outputs a game rotation quaternion, so attitude estimation uses neither main controller compute nor bus bandwidth.

```
Main controller (Raspberry Pi / TaishanPi)
      │  1 Mbps half-duplex single wire
      ├── servos ×15
      └── imu_to_dxl (this board, ID 200)
             ├── LSM6DSV16X   4-wire SPI + two interrupts
             ├── STM32G031F8P6 receive packets / build packets / read IMU
             └── SN74LVC2G241 half-duplex transceiver buffer
```

## Core component choices and rationale

| Ref | Part | Why it was chosen |
|---|---|---|
| **U1** | STM32G031F8P6 | ① The USART has **hardware DE** (RS485 Driver Enable): at 1 Mbps one bit is only 1 µs, and the jitter of toggling a direction pin in software is of that order. For comparison: **the STM32F401 manual does not mention "Driver Enable" anywhere**, so it can only switch in software<br>② Same vendor as the IMU; ST's `lsm6dsv16x-pid` driver and SFLP examples are ready to use |
| **U2** | LSM6DSV16XTR | On-chip SFLP fusion, outputs quaternions directly |
| **U3** | SN74LVC2G241DCUR | Dual buffer used for single-wire half-duplex. Channel 1 goes left-in right-out, channel 2 right-in left-out, which matches the routing exactly. With a 3.3 V supply its **inputs tolerate 5.5 V**, so it can handle the servos' 5 V signals |
| **U4** | HT7533-1 | **Rated for 30 V**: it survives on its own even if the first two protection stages fail |
| **F1** | PPTC MF-NSMF020X-2 | **24 V / 200 mA hold**. If this board fails, it disconnects itself first instead of taking down the whole servo bus |
| **D1** | TVS SMF12A | Standoff 12 V > fully charged 8.4 V, clamping 19.9 V < C6's 25 V rating |
| **C6** | 10 µF / **25 V** | Sits on the 8.4 V bus. MLCCs lose capacitance under DC bias; a 6.3 V/10 V part does not have enough margin |
| **C5** | 4.7 µF | Forms the combination ST requires together with C4's 100 nF: **DS12992 Rev 3, Figure 13** explicitly specifies `1 × 100 nF + 1 × 4.7 μF` for `VDD/VDDA` |

## A few possibly controversial decisions

### 1. `2OE` tied high, so the board hears its own echo when transmitting

`U3.1 (1OE#)` is connected to DE to control the transmit buffer; `U3.7 (2OE)` is **tied directly to 3.3 V, so the receive buffer is always on**.

- Cost: while transmitting, the MCU receives its own bytes on RX; the firmware discards them based on the transmit length
- Benefit: PA3 is always driven and **never floats**

The alternative is to connect `2OE` to DE as well (turning off receive while transmitting), but then RX floats during transmission,
and a false start bit may be generated when it is re-enabled. I chose the former; **counterarguments are welcome**.

### 2. No crystal, only pads

The TSSOP-20 package **does not bring out `OSC_OUT`** (DS12992 Rev 3, Table 12: the alternate functions of pin 2 `PC14` include
`OSC_IN`, while pin 3 `PC15` only has `OSC32_OUT`), so **a passive crystal simply cannot be connected**.

HSI16 accuracy (Table 41): factory −0.75%/+0.5%, temperature drift ±1% over 0–85 °C → worst case about **−1.85%/+1.55%**.
The typical tolerance of 1 Mbps asynchronous UART is ±3%, which is enough but without much margin.

The board has **X1 (16 MHz active oscillator, HSE bypass) + C9 + R3**, originally not populated by default; since 2026-09-08 they are **populated by default** (the firmware still starts on HSI16 and switches to HSE bypass only if bit errors are measured at 1 Mbps). X1's enable pin is tied to 3.3 V and PC15 is not connected to it, so the MCU cannot turn off the oscillator; see "Review log · 2026-09-16".
In addition, the firmware can use timer input capture to measure the bit period coming from the host and adjust `HSITRIM` accordingly (step 0.2–0.4% per step),
bringing the error down to within 0.3% at no cost.

### 3. Keep both J1 / J2, handle the overcurrent with copper pour

The three lines of J1 and J2 are paralleled one to one. **If this board is in the middle of the chain, the current of all downstream servos flows through this board's connectors and copper.**

Official Feetech HD-1910-C001 specs: rated **500 mA** / stall **1.8 A**.

But this constraint **is not unique to this board**: the servos are daisy-chained anyway, and their own connectors carry the same current.
The HAT has **4 servo ports**; the 15 servos are split across 4 branches with at most 4 per branch, so one branch is rated at about **2 A**,
within 3 A. The official design accepts this, and this board, using the same connector, is no worse.

**So both connectors are kept**: if you want to put it at the end, don't fit J2; if you want it in the middle, fit it. The flexibility costs almost nothing.
On the PCB, just route `VDD_BUS` and `GND` from J1 to J2 with **wide copper** (≥ 2 mm or a direct pour).

> A reviewer once suggested "keep only one 3P connector". That holds if this board is definitely a leaf node,
> but **if it is the first node in the chain** (out of the HAT into this board first, then out to the servos), it must have two.
> The official topology cannot be confirmed, so keeping two is safer.

### 4. Protocol auto-detected in software, no jumper/DIP switch

Feetech and Dynamixel have exactly the same physical layer (half-duplex single wire / 1 Mbps / 3 wires / GND-VCC-DATA);
the only difference is the packet format:

| | Header | Following bytes | Checksum |
|---|---|---|---|
| Dynamixel V2 | `FF FF` | **`FD 00`** | CRC-16 |
| Feetech SCS | `FF FF` | `ID` + `LENGTH` | `~(ID+LEN+INST+parameters)` |

The official Feetech protocol document states **Length = number of parameters N + 2**, so the minimum is 2 and it is **never 0**;
the ID range is 0–253. → `FF FF FD 00` can only be V2, so **the detection is unambiguous**.

The firmware locks the protocol when the first packet passes its checksum, and from then on receives and sends according to the locked protocol; **it does not unlock automatically during operation** (the original idea was to "redetect after 100 consecutive failed packets", but a 2026-09-17 review pointed out that bus noise would make the small board go silent for 2 s and the main controller would hold after 3 ticks without readings, so this was changed; see [`software/飞特适配架构.md` §3.5](../../software/飞特适配架构.md)).
More reliable than a DIP switch (in a walking robot, DIP switch contacts are a vibration failure point).

### 5. J3 uses 6P to also bring out the serial printf

According to the 2026-09-08 schematic PDF, the pin order is
`1=GND 2=SWDCLK 3=SWDIO 4=UART_RX 5=UART_TX 6=+3V3`.
SWD uses pins **1, 2, 3, 6**; pin 6 provides the debugger's voltage reference. **An old 4-pin ribbon cable must not be plugged as a whole onto pins 1–4**:
pin 4 is the serial input and cannot be used as 3.3V. Before wiring, check the pin 1 marking on the actual board against the debugger's pin definition.

The UART comes from U1 pins 16/17 (`PA11[PA9]` / `PA12[PA10]`), remapped via `SYSCFG_CFGR1` to
`USART1_TX/RX`.

**No USB**: the G031 has no USB peripheral (the manual's Development support section only says "serial wire debug (SWD)");
adding USB would need an extra CH340/CP2102, which is not worth it on a 45 × 22 mm board.
Debugging goes through SWD + RTT (`probe-rs` supports running RTT over CMSIS-DAP without halting the CPU).

> The Cortex-M0+ **has no SWO/ITM**, so don't count on SWO printf.

---

## Board outline and mounting holes

| Item | Value |
|---|---|
| Board outline | **45 × 22 mm**, 2-layer board |
| Corners | **R2 rounded** |
| Mounting holes | **2 × M2 non-plated holes φ2.2 mm**, diagonal |
| Hole positions (origin at the board's bottom-left corner) | MH1 (2.667, 2.413), MH2 (42.672, 19.685) mm |
| Hole spacing | X 40.00 mm / Y 17.27 mm / diagonal 43.57 mm |
| Hole to board edge | MH1 **1.31 mm** / MH2 **1.22 mm** (JLCPCB requires ≥0.4 mm) |

The midpoint of the two holes (22.67, 11.05) differs from the board center (22.50, 11.00) by 0.17 mm, so **mounting it rotated 180° still basically lines up** (offset 0.34 mm).
