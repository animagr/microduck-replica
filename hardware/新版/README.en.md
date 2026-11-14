# New hardware (2026-10)

**English** · [简体中文](README.md)

Three boards, all EasyEDA Pro projects (`.eprj2`, with the schematic and PCB in the same file). One folder per board:

| Folder | What it is | Status (2026-10-20) |
|---|---|---|
| [`imu_to_dxl_1V0A/`](imu_to_dxl_1V0A/) | Bus IMU board v2. The old version and the firmware are in [`../imu_to_dxl/`](../imu_to_dxl/) | Routing done; DRC has only 12 duplicate mounting-hole definitions left (no effect on manufacturing); not yet received and tested |
| [`wire_hub_1V0A/`](wire_hub_1V0A/) | Servo bus HUB: battery input + bus breakout | Not yet prototyped; CN1 height needs a different part |
| [`POGO_PIN_1V0A/`](POGO_PIN_1V0A/) | Battery connection board: two banana sockets + wire solder pads | Holes, pads and traces all revised to match the reference board; not yet prototyped |

In each folder:

- `<board name>.eprj2`: the project
- `<board name>-PCB.step`: 3D model of the whole board, for mechanical fit checks
- `<board name>-原理图.pdf` (schematic): currently only the IMU board has one

Gerbers, BOM and wiring tables are not out yet; see [`../imu_to_dxl/`](../imu_to_dxl/) for what the old version looks like.

## imu_to_dxl_1V0A: bus IMU board v2

Same function as the old version: an LSM6DSV16X on an STM32G031, with the MCU acting as a slave on the bus, sharing the same single-wire half-duplex bus with the servos. For the protocol and firmware, see [`../imu_to_dxl/`](../imu_to_dxl/). The circuit follows the old version, with a new layout and new connectors.

| Ref | Part | Function |
|---|---|---|
| U1 | STM32G031F8P6 | MCU |
| U2 | LSM6DSV16XTR | IMU |
| U3 | SN74LVC2G241DCUR | Half-duplex bus transceiver |
| U4 | HT7533-1 | 3.3 V LDO |
| F1 / D1 | MF-NSMF020X-2 / SMF12A | Resettable fuse / TVS |
| D2 | BZT52C5V1 | 5.1 V clamp on the bus data line |
| R6 | 0 Ω (C21189) | Bus series resistor; 150 Ω on the first board |
| J1 | A2007WR-3P | Servo bus, 2.0 mm 3P right-angle through-hole. 1 = DXL_BUS, 2 = VDD_BUS, 3 = GND |
| J2 | BM03B-ACHSS-GAN-ETF | 1.2 mm ACH 3P horizontal SMD. 1 = GND, 2 = VDD_BUS, 3 = DXL_BUS |
| J3 | PZ254V-11-06P | 2.54 mm 6P debug port: 1 = GND, 2 = SWDCLK, 3 = SWDIO, 4 = UART_RX, 5 = UART_TX, 6 = 3.3V |

Plus a number of 0402/0603 resistors and capacitors, 24 components in total.

Compared with the old version:

- The old servo connector `B3B-PH-K-S` would not accept the Feetech cable plug (recorded in the old README); this version switches to A2007WR-3P
- The external oscillator X1 is removed (the firmware already used the internal HSI16), so firmware 0.2.0 can be flashed without changes
- R6 changed from 150 Ω to 0 Ω: every servo on the bus has a pull-up, and with them in parallel a series resistor raises the low level. When the boards arrive, first measure the bus low level during reply packets
- U2 is rotated 180° and the board outline has changed, so once it is installed in the duck the IMU axis mapping must be redone. The firmware outputs the chip's raw attitude without rotation, so only the host-side mounting rotation changes; do an acceptance check with the robot at rest in three orientations
- Of the v2 to-do items recorded in the old README, **this version has no reset button and no run indicator LED**
- J3 has no 3D model in the PCB, so this pin header is missing from the exported STEP

## wire_hub_1V0A: bus HUB

No active components, only connectors. All connectors carry only the three nets `Battery`, `DXL_BUS` and `GND`.

| Ref | Part | Spec |
|---|---|---|
| J1 | HC-1.2-3PWT | 1.2 mm 3P horizontal SMD (Pico-EZmate compatible), 1.5 A |
| J2 | BM03B-ACHSS-GAN-ETF | 1.2 mm ACH 3P horizontal SMD, 2 A |
| J3, J4 | A2007WR-3P | 2.0 mm 3P right-angle through-hole, 4 A |
| J5, J6 | A2007WV-3P | 2.0 mm 3P vertical through-hole, 4 A |
| CN1 | DB125-2.54-2P-GN-S | Battery input, green screw terminal, 7 A, **8.4 mm tall above the board** |

The pin order matches the IMU board: HUB J1 and J2 and IMU board J2 are all 1 = GND, 2 = power, 3 = DXL_BUS, connected directly with a same-direction cable; HUB J3–J6 and IMU board J1 are all 1 = DXL_BUS, 2 = power, 3 = GND.

To do:

- CN1 is too tall and interferes with the structure; that spot can only take something about 5 mm tall. Candidates: an SMD push-in terminal with 4 mm pitch (the WAGO 2060 type, 4.5 mm tall), or no terminal at all and solder the wires directly

## POGO_PIN_1V0A: battery connection board

The outline and holes are adapted from the reference board banana_pcb (a KiCad project, Gerbers only). The board is 39.19 × 6.79 mm.

| Position | Net | Size |
|---|---|---|
| U2 (left) | GND | Banana socket hole Ø1.7 mm plated, pad Ø3.2 mm |
| U1 (right) | Battery | Same as above; the two holes are 33.8 mm apart center to center |
| Two pads in the middle | Left GND, right Battery | Top-layer SMD pads 2.4 × 4.4 mm, 4.0 mm pitch, no holes, for soldering wires |

The positions of the two pads also follow the reference board: the GND pad is 10.98 mm from the left hole and the Battery pad 14.98 mm from the left hole, both 0.59 mm below the line joining the two holes. The 4.0 mm pitch also happens to fit a 4 mm pitch push-in terminal directly.

The project is named POGO_PIN, but the board no longer has spring pins; it is just wire solder pads.
