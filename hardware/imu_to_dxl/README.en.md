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

> ⚠️ **The hole positions were changed on 2026-09-08.** The original design was MH1 (5.5, 3.5) / MH2 (39.5, 18.5), X 34 mm,
> deliberately matching the spacing of the two locating ears on the original `banana_pcb_locker` printed part.
> **When `J4`/`J5` were added, MH2's keep-out ring blocked exactly the only blank strip on the right where a through-hole part could go**,
> so both holes were moved toward the corners and the X spacing became 40 mm.
> **The cost is that it is no longer compatible with the original clip; the mechanical side changes its clamp bar accordingly.**
> In any case, the reverse-engineering document's claim that "the clip holds `imu_to_dxl`" was only an inference
> (see [Hardware reverse engineering](../../docs/硬件方案逆向.md)); the only hard constraint is "the IMU is rigidly fixed to `trunk_base`".

Board outline file: `imu_to_dxl-板框-45x22-R2.dxf` (units mm, 8 closed segments: 4 straight edges + 4 90° arcs).

> **Why a separate DXF**: the primitive API of this version of EasyEDA Pro (JLC EDA) only accepts copper layers;
> creating lines/arcs on the board outline layer (layer 11) always fails with "参数不正确" (invalid parameter), and changing the layer or the document source is blocked too,
> so the board outline goes in via DXF import (`文件 → 导入 → DXF` (File → Import → DXF), select the **board outline layer** as the target layer, units mm, origin aligned to 0,0).
> The two M2 holes are not in the DXF; they have already been created on the PCB as real NPTH pads.

## PCB: placement and routing

![imu_to_dxl PCB top assembly drawing](../../assets/hw/imu_to_dxl-PCB.png)

*Routing diagram, rendered from measured project data (top layer red / bottom layer blue / pads yellow / GND vias green / signal vias purple; the blue background is the bottom GND pour; purple boxes are `J4`/`J5`).*
*Status 2026-09-08: 29 components · 227 track segments · 31 vias · 172 teardrops, including `R7`, `J4`, `J5`; `X1`/`R3`/`C9` changed to populated.*
*The `.eprj2` / PCB PDF / schematic PDF / STEP in this directory and the two images under `assets/` have **all been updated to the final 2026-09-08 version**.*

**45 × 22 mm, 2-layer board, 1 oz copper**, R2 rounded corners, two diagonal non-plated M2 holes.
All SMD parts are on the top side; the 3 through-hole connectors are on two edges: `J1` `J2` (servo bus) on the bottom edge,
`J3` (SWD + serial) on the top edge.

### Zones

| Zone | Contents | Why |
|---|---|---|
| Bottom edge | `J1` `J2` bus connectors (JST EH 2.5 mm) | The harness is routed from the torso, so it exits nearby |
| Bottom right | **`J5` Feetech bus out** (2.0 mm) | Same side as `J1`/`J2`; the `VDD_BUS` of all four connectors is linked by one straight-through copper path |
| Right edge | **`J4` Feetech bus in** (2.0 mm) | The only blank strip on the whole board that can fit a through-hole part; MH2 was moved to make room for it |
| Right side | `F1` → `D1` → `C6`/`C8` → `U4` → `C7` | The power chain runs in one line, separated from the digital area |
| Center | `U3` buffer + `D2` clamp + `R6` series resistor | Sandwiched between the MCU and the bus connectors, for the shortest transmit/receive paths |
| Upper center | `U1` main MCU, `U2` IMU and their decoupling | |
| Left side | `X1` / `R3` / `C9` clock footprint | Now populated; placed in the corner so it does not take a good spot |
| Top edge | `J3` debug header | Plugging direction faces outward |

### Routing

| Item | Value |
|---|---|
| Components | **29** (including `R7` added 09-07 and `J4`/`J5` added 09-08) |
| Tracks | **227 segments** (top 197 / bottom 30) |
| Track width | Mostly 0.25 mm for signals; **0.76 mm for the bus pass-through** |
| Vias | **31, φ0.6 / hole 0.3 mm** |
| Teardrops | 172 |
| Copper pour | **Solid GND on the bottom layer**, none on top |

There are only 30 track segments on the bottom layer, so **the ground plane is essentially intact**; this is the return path left for SPI and the 1 Mbps half-duplex bus.
The GND pads on the top layer each drop to the ground plane through a nearby via.

### Review results · 2026-09-08

In addition to EasyEDA's built-in DRC, a script re-rasterized the board using the **actual pad shapes** (circle / obround / rectangle)
for an independent recheck:

| Check | Result |
|---|---|
| EasyEDA DRC | **0 violations** |
| **Connector pin order** | **All four correct**: `J1`/`J2` = `GND`/`VDD_BUS`/`DXL_BUS`; `J4`/`J5` = `DXL_BUS`/`VDD_BUS`/`GND` (**reversed**; see the pin order section below) |
| Net connectivity | **All 23 nets connected** (raster connected components + vias/through-holes across layers, including the bottom pour) |
| Minimum clearance between different nets | **0.152 mm = 5.98 mil** (exact geometry, not raster). JLCPCB's double-sided minimum is 0.127 mm, 20% margin |
| Copper to board edge | Minimum **0.37 mm** |
| Hole to hole (wall to wall) | Minimum **0.751 mm**, requirement ≥0.4 mm |
| Hole to board edge | MH1 **1.31 mm** / MH2 **1.22 mm** |
| M2 keep-out | Within MH1's 2.5 mm keep-out ring there is only one **GND** via (1.81 mm); a screw touching ground is still ground, harmless; nearest to MH2 is 4.59 mm |
| Via spec | φ0.6 / hole 0.3 mm, meets JLCPCB's double-sided minimum |
| Decoupling distance | `U1.4`→`C4` 2.27, `U2.8`→`C1` 2.00, `U2.5`→`C2` 2.01, `U3.8`→`C3` 1.96, `X1.1`→`C9` 2.39 mm, all <2.4 mm; `U4.3`→`C7` 2.94 mm. ⚠️ The 100nF `C8` on the `U4.2` LDO input side is **6.64 mm** (on the loose side, but the 10µF `C6` that handles transients is at 4.29 mm, and the LDO is linear with no switching) |

**Current capacity check**: the `VDD_BUS` pass-through chain between the four connectors,
`J1.2 → J2.2 → J5.2 → J4.2`, is **0.76 mm all the way**; with 1 oz copper that is about 2.0 A at ΔT=10K and about 3.2 A at ΔT=30K.
A single JST EH contact is rated at 3 A, so **the tracks and the connectors are essentially of the same order**; widening would not raise the limit of the whole chain.
There is also a 4.7 mm long 0.51 mm segment on the `J1.2 → F1.1` branch that **feeds only this board itself**,
preceded by a 200 mA hold PPTC, which is enough.

> **One issue caught and fixed on 2026-09-08**: when routing `DXL_BUS` to `J4`/`J5`, a φ0.3 via
> landed right on top of `J2.3`'s φ1.0 through-hole (center distance 0.001 mm). EasyEDA DRC reported
> `Hole to Hole (DXL_BUS): J2_3 ↔ e75`: drilling is a mechanical process, so overlap is not allowed even on the same net.
> `J2.3` itself is a through-hole that already connects top and bottom, so the via was purely redundant; after deleting it, connectivity is unchanged and DRC is back to zero.

**Still unverified**: **not prototyped, no physical board**. All of the above are geometry- and rule-level checks
and cannot replace measurements.

### To do

- Run **component standardization** once before ordering (schematic DRC reported "元件属性与供应商编号不匹配" (component attributes do not match the supplier part number))
- Silkscreen review: whether reference designators overlap pads, and whether the `U1` pin 1 / `D1` `D2` cathode / `J1` pin 1 markings are all present
- **Connector height**: `J1`/`J2`/`J3` are JST EH / 2.54 header through-hole parts, with bodies about **8 mm** tall. If the torso cavity
  really has only 6.65 mm, they need to be swapped for the right-angle `S3B-EH-A`, and the footprint and BOM must change accordingly; comparing the exported STEP in
  the assembly will settle it.
  **`J4`/`J5` are actually not a concern**: the `B3B-PH-K-S` body is about **6.0 mm**, which fits in the 6.65 mm cavity
- **Board-side connector model to be confirmed**: the Feetech datasheet only gives the cable side as `AMP2.0-3P`; **the board-side model is not given**.
  This board uses `B3B-PH-K-S` (JST PH, 2.0 mm vertical) for now. The pad array is three holes at 2.0 mm pitch,
  common to other 2.0 mm series, so **switching series later only changes the footprint, not the pads or the routing**
- **Re-export the production files before ordering**: the component count went from 27 to 29, so the Gerber / BOM / pick-and-place coordinates on the JLCPCB side all need to be re-uploaded

## Please look closely at these points

1. **The trade-off of keeping `2OE` always on** (item 1 above): echo vs. floating RX, which is worse
2. **J1/J2 overcurrent and copper width** (item 3): is 2 mm enough
3. **Margin of HSI16 running 1 Mbps** (item 2): if you have measured experience, please say so
4. **Are three layers of overvoltage defense enough**: 8.4 V bus + servo back-EMF
5. **Connectors**: see "⚠️ Feetech pin order differs by model, and is reversed" below. The two 2.0 mm connectors `J4`/`J5`
   have been placed on the schematic and PCB (2026-09-08), but **the exact series of the board-side connector has not been compared against the real part**;
   the Feetech datasheet only gives the cable side as `AMP2.0-3P`, and the board-side model awaits confirmation from the manufacturer

## ⚠️ Feetech pin order differs by model, and is reversed

**This is the most potentially fatal point on this board. Neither of the two manufacturer datasheets is wrong; the two models really are opposite.**

| | Connector | Pin 1 | Pin 2 | Pin 3 |
|---|---|---|---|---|
| **`HD-1910-C001`** (chosen in this repo) | **`AMP2.0-3P`** (2.0 mm) | **Signal/TTL** | Vcc | **GND** |
| `HL-2915-C002` (another model, do not copy) | `AMP-3` | **GND** | Vcc | **Signal/TTL** |
| This board's `J1`/`J2` (JST EH 2.5 mm, same as the official HAT) | `B3B-EH-A` | GND | VDD_BUS | DXL_BUS |
| This board's `J4`/`J5` (2.0 mm, mating with Feetech) | `B3B-PH-K-S` | **DXL_BUS** | VDD_BUS | **GND** |

The pin order of all four connectors has been re-read from the PCB netlist and verified; all are correct (2026-09-08).
**The two pitches cannot plug into each other (2.0 vs 2.5 mm), which physically rules out mis-plugging and leaves only "drawn wrong" as a possibility.**

Sources: Feetech "HD-1910-C001 串型规格书" (serial-type datasheet) **A/0, 2026-09-07**, page 3/7, items 6-7;
Feetech "HL-2915-C002 串型规格书" A/0, 2026-02-27, page 4/8, items 6-7.
Both are datasheets the manufacturer sends to customers for confirmation; **by convention this repo does not redistribute the PDFs**; please request them from Feetech if needed.

> This repo previously recorded only the `HL-2915` row while recommending the `HD-1910` as an alternative model, **which was a pitfall**;
> corrected on 2026-09-08 based on the new A/0 datasheet.
>
> ⚠️ **The `HL-2915-C002` is a 9–14 V (typically 12 V) servo and cannot be used on this design's 2S bus (6.6–8.2 V)**;
> it only starts working at 9 V. Using it as a sample of the "Feetech connector convention" was a stopgap; don't choose parts based on it.
>
> ⚠️ **The pitch doesn't match either**: `AMP2.0` is 2.0 mm and `JST EH` is 2.5 mm, so **they cannot plug into each other**.
> Fortunately this is actually a safeguard: it physically rules out mis-plugging, leaving only "drawn wrong" as a possibility.

## Confirmed / unverified

**Confirmed (primary sources)**

- **HD-1910-C001** connector `1=Signal/TTL · 2=Vcc · 3=GND`, connector `AMP2.0-3P`, cable length 15±0.5 cm
  (Feetech "HD-1910-C001 串型规格书" A/0 (2026-09-07), page 3/7, items 6-7)
- The HD-1910-C001 uses a **TTL three-pin bus**, **4–8.4 V**, stall torque 9/12/15 kg·cm @4.8/6/7.4 V,
  rated current **500/690/900 mA**, stall current **1.2/1.6/2.0 A**, quiescent 20 mA, 12-bit magnetic encoder,
  gear ratio 1/320 (same datasheet, pages 2/7 and 3/7)
- **The motor has three built-in electronic protections** (same datasheet, page 4/7, 7-11):
  **overcurrent** (output off after >0.5 A for 2 s; threshold and duration customizable, **off by factory default**) ·
  **overvoltage** (protection at >10 V or <4 V; range customizable, **off by factory default**) ·
  **overheat** (torque output off at >80 ℃, **on by factory default**).
  **The first two should be enabled before assembly**: fault detection is done in the motor, so the host does not need to poll
- All six feedback values are available: input voltage / load / operating current / operating speed / operating temperature / position (same, 7-10).
  The official runtime really uses them: `present_current` is read every tick together with position, voltage + temperature about once per second,
  and **voltage is the robot's only means of battery metering** (`duck-control/src/{bus,model}.rs`)
- The factory default operating mode is **mode 4 "pure position PD (Sim2Real)"**, which is exactly what reinforcement learning deployment needs (same, 7-12)
- Packet format, `Length = N+2`, checksum algorithm, synchronous read `0x82` (official Feetech "舵机SCS通信协议" (servo SCS communication protocol))
- Packet format, `Length = N+2`, checksum algorithm, synchronous read `0x82` (official Feetech "舵机SCS通信协议" (servo SCS communication protocol))
- STM32G031 has no HSE pins, HSI16 accuracy, `100 nF + 4.7 µF` decoupling requirement (ST DS12992 Rev 3)
- Schematic connectivity: checked net by net with a script; no floating pins, no shorts, no duplicate net names

**Unverified**

- **The whole board has never been prototyped**; there is no physical board
- The 45 × 22 mm board outline and the 34 mm X spacing of the M2 holes were reverse-engineered from the printed part `banana_pcb_locker`; they are not official dimensions
- The MCU model is this repo's suggested choice, **not something obtained by reverse engineering**; what MCU the official board uses cannot be recovered

---

## Review log

### 2026-09-16 · Eight external review points + self-check finds X1's enable pin not connected

The board is already in production at JLCPCB, so these all count as "what to verify when the first boards come back".

| Review comment | Conclusion | Basis |
|---|---|---|
| ① Connecting X1 to PC14/OSC32_IN is wrong; PC14 is only the LSE pin | **Not accepted; the review is wrong** | DS12992 Rev 3 Table 12 (p.36): the alternate functions of TSSOP20 pin 2 are `OSC32_IN, OSC_IN`, both of them; p.60: in HSE bypass mode the oscillator is off and the input pin receives the external clock as a normal GPIO level. The small package does not bring out PF0/PF1, so the HSE external clock input is assigned to pin 2. That a passive crystal cannot be connected (no OSC_OUT) has always been stated in this directory |
| ② Leaving U2's OCS_Aux / SDO_Aux floating is a missed connection | **Not accepted**; documentation wording unified | DS13510 p.10 / p.48: both pins "connect to Vdd_IO or leave floating", with internal pull-up by default (PIN_CTRL.OIS_PU_DIS = 0). Floating is the datasheet's standard practice. v2 can leave a 0 Ω footprint |
| ③ Always-on 2OE causes echo; suggest turning off receive during transmit by default | Hardware already supports both; firmware decides | On Sep 7 `2OE` was changed to the `RX_EN` net connected to PB7; see the record below |
| ④ Logic branch protection is not the same as whole-robot overvoltage protection | Agreed; that is what was written all along | The TVS handles spikes, the PPTC is slow, the LDO protects only the logic branch; see "Re-review against the official HAT" |
| ⑤ The J1/J2 pass-through current is a system-level limit | Agreed; already stated | This board sits at the end of the chain; EH connector 3 A |
| ⑥ The J4/J5 board-side connectors have not been verified with real parts | **Agreed; this should be done before the first boards** | Feetech has only confirmed the cable side as AMP2.0-3P; whether `B3B-PH-K-S` fits, the latch direction and the pin order: buy a few connectors and try them with servo cables |
| ⑦ Layout suggestions (IMU centered, LDO far away, test points, NRST on J3) | Adopted for v2 | — |
| ⑧ First-board verification checklist, 8 items | Adopted as the acceptance check | Bus high-impedance during reset, 1 Mbps transmit/receive of 00/FF/55/AA, CRC/timeout/overrun statistics over 30 000 transactions, IMU zero offset vs. temperature, polarity measured pin by pin, PC14 not driven when X1 is not fitted |

**Self-check (2026-09-16)**: checked pin by pin against the vector line segments of the schematic PDF; the only unconnected pins are the four that are supposed to be free: U1.3 (PC15), U1.20 (PB3–PB6), U2.10 (OCS_Aux), U2.11 (SDO_Aux). X1 pin 1 `Tri-state` is tied to 3.3 V, always enabled (the small red circle on the symbol is EasyEDA's pin 1 marker, not an unconnected mark). The wiring table's statement that "pin 3 (PC15) can be used as `OSC_EN`" **was never drawn into the schematic**: PC15 is free, so X1 cannot be turned off. If the first board needs MCU control of the oscillator, run a bodge wire from PC15 → X1.1 and remove the 3.3 V connection, or don't fit X1 and use HSI16.

### 2026-09-17 · First boards arrived, hardware test

- 5 boards arrived; on power-up the **3.3 V output is normal** (the F1 → D1 → U4 chain is fine).
- **The J4/J5 (`B3B-PH-K-S`) housing does not mate with the Feetech cable plug**: the 2.0 mm pitch is right, but the plug's shape does not fit into the PH connector's housing. Review point ⑥ was spot on. On the first boards the connector housing was shaved off, leaving only the pins, which can be plugged into and work. **v2 changes the connector**: match it against a real Feetech cable (ask Feetech for the board-side connector model, or buy several 2.0 mm 3P right-angle connectors and test-fit them).
- The X1 clock, NRST, IMU supply and SWD continuity have not been measured yet; what the firmware needs to do and all of the main controller's requirements for it are in [`software/飞特适配架构.md` §4](../../software/飞特适配架构.md#4-小板固件方案-a--imu_to_dxl).

### 2026-09-22 · Firmware is running (ST-LINK/V2)

- The firmware is in [`firmware/`](firmware/) (base written by a fellow contributor, PR #32; Feetech protocol from 0.2.0 on). Flashed with ST-LINK/V2 via J3 pins 1/2/3/6 and read-back verification passed; IMU measurements: WHO_AM_I=0x70, about 121 Hz, combined acceleration 1.007 g at rest, error count 0.
- **G0 blank-chip pitfall**: after the first flash and a software reset, the program did not run and stayed in ST's built-in bootloader (PC=0x1FFF…), because `FLASH_ACR.EMPTY` is only updated at power-up. **Power-cycling once** fixes it. Pressing the reset button (NRST) does not recheck it, so it does not solve this.
- **To add in v2** (missing during first-board debugging):
  - **Reset button + NRST brought out to J3**: done together with review point ⑦. When the program runs away and SWD can't connect, you can hold reset and then connect (under-reset) to recover the board, and it also makes it easy to rerun the firmware.
  - **Run indicator LED**: on **U1.20** (PB3–PB6, currently the only fully free GPIO) + current-limiting resistor. The firmware adds a heartbeat: slow blink when normal, fast blink on IMU error, so you can tell at a glance whether the board is running without a debugger attached.

### 2026-09-07 · Three layout/component suggestions (none accepted, reasons recorded)

A reviewer looked at the drawings and made three suggestions: switch the resistors and capacitors to 0402, put the IMU at the board center, move the LDO away from the IMU. I measured the data for each one;
**the conclusion is to keep the current design**, but the reasons for each are worth recording, especially since the second and third actually point to the same thing.

**① Switch the passives to 0402: no, and the reason is not "can it be hand-soldered"**

The reviewer added "don't bother soldering yourself, just get JLCPCB to assemble it, it's less hassle". That advice is right in itself, but it is not the criterion for whether to switch
to 0402: the very first sentence of the 2026-09-06 entry in this directory says "**the reason is not that 0402 can't be hand-soldered**":
the board has the LSM6DSV16X in LGA-14 (bottom pad 3×2.5 mm), which requires hot air anyway.

The real reason is **rework during debugging**: the `R6` series resistor needs to be tried from 150 Ω down to 33 Ω, pull-ups may need to be removed, decoupling may need to be added.
**An unverified first board will inevitably be modified several times**, and that does not change by having JLCPCB assemble it: the assembly house only does
the first pass; changes still need your own soldering iron.

On the cost side: switching the 16 passives to 0402 saves **12.5 mm², 1.3% of the board area**, while this board **only uses 36%
of its area**, so space is not short at all. 0402 10k/100nF are also basic parts at JLCPCB, so saving on part fees applies to both options
and is not a reason.

**② IMU at the board center · ③ LDO away from the IMU: both point the right way, but the magnitudes differ**

First, the measurements:

```
Board center (22.5, 11.0) = midpoint of the two M2 holes (designed that way from the start)
U2 (IMU)    7.47 mm from the board center, 3.00 mm from the line between the two screws
U3 (buffer) 0.41 mm from the board center      ← the stiffest spot is taken by a logic chip
U2 ↔ U4 (LDO) center distance 6.37 mm
```

**Thermal magnitude**: total board current is about 5–10 mA (G031 about 3 mA + LSM6DSV16X about 0.65 mA + buffer about 1 mA
+ pull-ups); the LDO drop is 8.4 − 3.3 = 5.1 V → **about 51 mW dissipated** (worst case at full charge). SOT-89 on small copper has
θJA of about 100–160 °C/W → junction temperature rise of **5–7 °C**; 6.4 mm away, with a full bottom ground pour in between spreading heat, the temperature difference reaching the IMU
is **about 1–3 °C**. The LSM6DSV16X gyro zero-rate drift is about 0.05 °/s/°C → **about 0.1 °/s of bias**.
While walking, the gyro sees tens of °/s, and the 15 servos in the torso draw amperes of current, so those heat sources are two to three orders of magnitude larger than 51 mW.
**The direction is right, but it is not the dominant term.**

**What is really worth acting on is the other side of point ②**: the board center is exactly the midpoint between the two screws, the least deformable spot on the board,
and what sits there now is `U3`, which doesn't care where it is. Swapping `U2`/`U3` kills three birds with one stone:
the IMU goes from 7.47 → 0.4 mm from the board center, and its distance from the LDO goes from 6.37 → **11.3 mm** (doubled).

**Why it still isn't changed this time**: the board already has 0 DRC violations and is fully routed; swapping means rearranging the center area + rerouting
4 SPI lines, 2 interrupts, and the buffer's DE/TX/RX/DXL_DATA. Based on the magnitudes above, the benefit is "more conservative" rather than
"fixes a known problem". **This is left until after prototyping, to decide with measured data**: if the measured gyro zero offset drifts noticeably with LDO load,
or vibration noise is high, it will be changed together in v2.

**A more important reminder**: the IMU's position and orientation **in the robot** are fixed by the trained model, and that matters far more than a 7 mm offset
on the board. That is determined by how the board is mounted in the torso, which has been researched and recorded in
[`docs/硬件方案逆向.md`](../../docs/硬件方案逆向.md): `trunk = [+raw_z, +raw_y, −raw_x]`,
rotated +90° about the Y axis. Moving parts on the board does not affect this.

### 2026-09-07 · Leave a control line for `2OE` (R7 + RX_EN)

Someone suggested routing "that EN pin" to the MCU as a reserved line. It refers to `U3.7 (2OE)`, the output enable of the receive buffer,
which was previously hard-wired to +3V3 so receive was always on. **Adopted.**

**Changes**

| | |
|---|---|
| Disconnected | The direct connection between `U3.7 (2OE)` and `+3V3` |
| Added | **R7 = 10 kΩ 0603** (`C25804`, the same part as R1/R2/R4/R5, no new part number) |
| New net | **`RX_EN` = `U1.1 (PB7/PB8)` · `U3.7 (2OE)` · `R7.1`** |
| Kept | `R7.2 → +3V3` (pull-up) |

**Why U1.1**: the free pins on U1 are pin 1 (PB7/PB8), pin 3 (PC15) and pin 20 (PB3/PB4/PB5/PB6).
Pin 3 is PC15, which on the G0 is shared with LSE and has limited drive strength; pin 20 combines four ports and is the most flexible, so it is kept free.
Pin 1 is an ordinary GPIO and is on the bottom row together with `DE`/`MCU_TX`/`MCU_RX`, so it uses the same routing channel.

**Default behavior is completely unchanged**: during MCU reset PB7 is high-impedance and R7 pulls `2OE` high, so the receive buffer stays on as before.
Without a single line of firmware, it behaves exactly as before the change. This is a **reservation**: when you want to eliminate the echo during transmission, configure PB7 as a push-pull
output driven low, and at the same time enable the internal pull-up on the `MCU_RX` pin so that RX does not float while `2Y` is high-impedance;
this was exactly the concern that led to rejecting the "`2OE` connected to DE" option earlier, and a separate GPIO + internal pull-up solves it.

**Post-change recheck**: components 26→27, nets 23→24, `RX_EN` = 3 pins, `U3.7` removed from `+3V3`,
with `R7.2` in its place. EasyEDA DRC **0 violations**, minimum clearance between different nets **0.160 mm** (0.153 before the change);
everything else is consistent with the first recheck on 2026-09-07.

**Also corrected**: the "floating pins" list in this directory's `imu_to_dxl-接线表.md` (wiring table) previously listed pins 2, 16 and 17 by mistake
(they connect to `OSC_IN`, `UART_TX` and `UART_RX` respectively); this has been fixed. The only truly free pins now are pin 3 and pin 20.

### 2026-09-07 · Three questions about the U3 buffer (two not accepted, one changes the drawing)

A reviewer checked the SN74LVC2G241 datasheet and raised three points about how U3 is connected. Each was checked; the netlist was read directly from
the PCB (the PCB nets are exported from the schematic, so they are equivalent to the schematic connections):

```
U3 pin1  1OE#  → DE          pin5  2A   → DXL_DATA
U3 pin2  1A    → MCU_TX      pin6  1Y   → DXL_DATA
U3 pin3  2Y    → MCU_RX      pin7  2OE  → 3.3V
U3 pin4  GND   → GND         pin8  VCC  → 3.3V

DXL_DATA  4 pins: R5.2 R6.1 U3.5 U3.6     ← does not include U3.7
DE        3 pins: R4.2 U1.8 U3.1
MCU_TX    2 pins: U1.9 U3.2
MCU_RX    2 pins: U1.10 U3.3
```

**① "A is the input and Y is the output, so pin 3 should go to DXL_DATA and pin 5 to MCU_RX": the premise is right, the conclusion is backwards**

The datasheet is right: the device is two independently enabled 1-bit line drivers, and the data direction is always **A → Y**.
But swapping the wires based on that is wrong:

- `MCU_RX` is the net that **must be driven by the buffer** (it goes into the MCU's receive pin), so it must be on **output pin Y**
  → it is currently on pin 3 (2Y) ✅
- `DXL_DATA` is the net that **must be read in** (sent by the servos on the bus), so it must be on **input pin A**
  → it is currently on pin 5 (2A) ✅

After the suggested swap, channel 2 would become `MCU_RX(2A) → DXL_DATA(2Y)`, which amounts to sending data onto the bus from the MCU's receive pin;
RX is an input pin and outputs no level; moreover, `1Y` and `2Y` would both drive
`DXL_DATA`, with the two drivers fighting each other directly.

The current split is the standard half-duplex connection: **channel 1 = transmit** (`MCU_TX → bus`, controlled by DE),
**channel 2 = receive** (`bus → MCU_RX`, always on). **Not accepted.**

**② "2OE should have a series pull-up resistor, otherwise the pull-up is too strong": electrically unfounded, but the drawing should change**

`2OE` is a CMOS logic input with input current on the order of ±1 µA; connecting it directly to VCC is the datasheet's standard usage.
A series resistor brings no benefit and instead introduces noise coupling into a high-impedance input.

The worry that "the pull-up is too strong" only applies if the node is a **data line**, and it is not:
the `DXL_DATA` net has only 4 pins (`R5.2` `R6.1` `U3.5` `U3.6`) and **does not include `U3.7`**.
The bus pull-up is `R5 = 10 kΩ`, and that value is appropriate.

**But this reminder is valuable**: the misunderstanding arose because the "3.3V symbol on 2OE" in the drawing sits right on top of
the `DXL_DATA` node and visually looks like they are joined. **Listed as a to-do: move that 3.3V symbol away and
route the wire around it** to remove the ambiguity. This is a drawing issue; the electrical connections do not change.

**③ "If it should conduct by default, 1OE# should be tied low": not conducting by default is intentional; not accepted**

`1OE#` is active low and `R4` **pulls it high**, which means channel 1 (`MCU_TX → bus`)
is **off by default**. This is deliberate:

- From power-up until the firmware is running, and while the MCU is hung / in reset, this board **must never drive the bus**.
  The bus is shared by 15 servos; once it is pinned, communication on the whole chain is dead.
- If `1OE#` were tied low permanently, `MCU_TX` would keep driving the bus, and the idle high level would hold the bus hostage,
  so the servos could never send their replies; half-duplex would no longer work.

When transmitting, the MCU pulls `DE` **low**. The STM32 USART hardware Driver Enable supports this polarity;
a single `CR3.DEP = 1` bit does it, with no external inverter needed.

> This is consistent with item ① of 2026-09-06 (community feedback requiring a DE pull-up):
> R4 was added then precisely to guarantee "does not drive the bus by default", and that must not be reversed here.

**To do**: on the schematic, move the 3.3V symbol on `U3.7` away so it does not visually connect to the `DXL_DATA` node.

### 2026-09-06 · Community feedback (three points, two changed)

**① The DE pin needs a pull-up: changed; this was an omission**

`U3.1 (1OE#)` enables transmit when low. During power-up and reset the MCU's **PA1 is high-impedance**, so this pin floats;
**if it floats low, the transmit buffer opens and this board pumps data onto the bus, colliding with all 15 servos.**

Added **R4 10 kΩ, DE → 3.3 V**.

The R1 pull-up added earlier on `SPI_CS` was for exactly the same reason, **but it was not extended to DE**, which was indeed an oversight.

**② The two `DXL_DATA` should be joined and pulled up: changed**

Electrically they were always the same net (`U3.5 2A` / `U3.6 1Y` / `J1.3` / `J2.3`),
but the drawing showed two short wires each with its own label, **which looked unconnected**; the drawing was not clear enough. It now uses an explicit junction.

The pull-up point is also right: when the bus is idle and nobody is driving it, the `2A` CMOS input floats and draws shoot-through current,
and the UART may also mistake noise for a start bit; this board should define its own idle level rather than rely on the host.
Added **R5 10 kΩ, DXL_DATA → 3.3 V**.

**③ Keep only one 3P connector: not adopted; see item 3 above for the reasons**

The suggestion holds if this board is definitely a leaf node; but if it is the first node in the chain it must have two connectors,
and the official topology cannot be confirmed. Both are kept, and overcurrent is handled with copper width.

Recheck after the changes: `DE` went from 2 pins to 3, `DXL_DATA` from 4 pins to 5;
no floating pins, no shorts and no duplicate net names in the whole schematic.

### 2026-09-06 · Re-review against the official HAT (two protections added)

Read the `dynamixel.kicad_sch` of [`pollen-robotics/elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT)
component by component and compared it with this board.

**The HAT's TTL half-duplex circuit**

```
                        ┌── R31 10k ── +3V3
   IO_15 (RX) ◄── U6 ───┘                    ┌── R32 10k ── +3V3
              (1G125, OE# active low)        │
                        ▲                     ▼
   IO_14 (TX) ──┬── U7 ──────────────────────► ● ── R33 150R ──┬── TH1 100R ── J13.3 / J14.3
                │  (1G126, OE active high)                  D4 5V1
                └── R27 10k ── Q1 (PNP) ── Dynamixel_dir        ⏚
```

**Item-by-item comparison**

| | Official HAT | This board | |
|---|---|---|---|
| Transceiver buffer | Two chips, 1G125 + 1G126 | One SN74LVC2G241 | Same logic |
| Direction control | Derived automatically from TX (Q1 + RC) | **USART2 hardware DE** | This board is better, see below |
| Bus pull-up | R32 10 kΩ | R5 10 kΩ | Same |
| **Data line series resistance** | R33 150 Ω + TH1 100 Ω | ❌ none → **R6 150 Ω added** | |
| **Data line clamp** | D4 5V1 | ❌ none → **D2 5V1 added (same part number `C151348`)** | |
| Power protection | None (`+BATT` goes straight to the connectors) | F1 PPTC + D1 TVS | This board is better |

**Why this board's direction control is better**: the HAT derives direction from TX and relies on RC timing to return to receive;
**releasing too early truncates the last stop bit**, a common flaw of TX-derived schemes.
This board uses `USART2`'s hardware DE, where `DEAT`/`DEDT` can be fine-tuned in 1/16-bit steps, so the problem does not exist.

**Data line topology after the additions** (same structure as the HAT):

```
U3.6 (1Y) ──┬─ DXL_DATA ─┬── R5 10k → 3.3V
U3.5 (2A) ──┘            │
                         └── R6 150Ω ──┬── DXL_BUS ── J1.3 / J2.3
                                       │
                                    D2 5V1
                                       ⏚
```

The pull-up stays on the **buffer side** (R5 before R6), matching the position of the HAT's R32;
this way, even with no bus plugged in, the `2A` CMOS input has a defined level.

This board adds only 150 Ω in series (the HAT has 250 Ω), because the HAT side already has 250 Ω,
and too much series resistance on the bus would slow the edges.

Recheck: `DXL_DATA` (buffer side) 4 pins, `DXL_BUS` (connector side) 4 pins;
no floating pins, no shorts and no duplicate net names in the whole schematic.

**Also correcting an earlier error in this document**: the HAT's `TH1 100R thermistor` is in series with the **data line**,
not the power line. `+BATT` to pin 2 of J13/J14 is a **thick straight-through trace with no current limiting**.

### 2026-09-06 · All passive packages changed to 0603

All 0402 resistors and capacitors changed to **0603**, and D2 changed from SOD-323 to **SOD-123**.

The reason is not "0402 can't be hand-soldered": the board has the **LSM6DSV16X in LGA-14** (bottom pad 3 × 2.5 mm),
which requires hot air or reflow anyway, and with that equipment 0402 is not hard either.

**The real reason is rework during debugging**: the series resistor needs to be tried from 150 Ω down to 33 Ω, some pull-up needs to be removed,
a decoupling cap needs to be added; on 0603 these take a few seconds with a soldering iron, while 0402 means setting up hot air again.
A board that has not been verified by prototyping will inevitably be modified several times in its first version.

The cost is small: the 11 parts take about 16 mm² more, less than 2% of the 45 × 22 mm board area.
Moreover, all of these 0603 values are **in JLCPCB's basic library** (10 kΩ `C25804` · 150 Ω `C22808` ·
33 Ω `C23140` · 100 nF `C14663`), which saves even more on loading fees than the extended-library 0402 parts used before.

> C6 (10 µF/25 V) stays 0805; C5 (4.7 µF) and C7 (10 µF) were already 0603.

When changing packages, parts were re-placed at the same coordinates and angles; measured: **pin coordinates unchanged, not a single connection broken**.
One pitfall: the `SOD-123` symbol's pin order is the reverse of `SOD-323`, so after the swap **D2's polarity was flipped**
(cathode on the ground side, which in normal operation would clamp the bus to 0.7 V); it was checked by pin name and corrected.
The `rotation` parameter of `create()` has the opposite sign in this API: passing 90 stores 270.
