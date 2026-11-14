# imu_to_dxl wiring table

**English** · [简体中文](imu_to_dxl-接线表.md)

> For manual wiring. Reference designators match `microduck-replica/BOM.md`.
> Status: draft design, not yet verified on physical hardware.

## Parts list (with LCSC part numbers)

| Ref | Part | Package | LCSC part no. |
|---|---|---|---|
| U1 | STM32G031F8P6 | TSSOP-20 | C529334 |
| U2 | LSM6DSV16XTR | LGA-14 | C5267406 |
| U3 | SN74LVC2G241DCUR | VSSOP-8 | C10430 |
| U4 | HT7533-1 (30V input, 100mA) | SOT-89 | C14289 |
| F1 | PPTC MF-NSMF020X-2 (24V / 200mA hold) | 1206 | C210358 |
| D1 | TVS SMF12A | SOD-123FL | C2943870 |
| R1, R2, R4, R5 | 10kΩ | **0603** | C25804 |
| R6 | 150Ω | **0603** | C22808 |
| D2 | BZT52C5V1 5.1V Zener diode | **SOD-123** | C151588 |
| C1–C4, C8 | 100nF 50V | **0603** | C14663 |
| C5 | 4.7µF / 16V X5R | 0603 | C19666 |
| C6 | 10µF / 25V X5R | 0805 | C15850 |
| C7 | 10µF / 10V | 0603 | C19702 |
| J1, J2 | B3B-EH-A (3P **2.5mm**, Dynamixel / official HAT cable) | Through-hole | C160259 |
| **J4, J5** | **B3B-PH-K-S (3P 2.0mm vertical, mates with Feetech `AMP2.0-3P`)** | Through-hole | TBD |
| J3 | SWD+UART 6P pin header PZ254V-11-06P | Through-hole | C492405 |

## Netlist (23 nets)

### VDD_BUS: raw servo bus voltage (2S Li-ion 6.0–8.4V)
J1.2 · J2.2 · **J4.2** · **J5.2** · F1.1

> The `VDD_BUS` of the four connectors runs on a **continuous copper pour**: `J1.2 → J2.2 → J5.2 → J4.2`, 0.76 mm all the way.

### VDD_F: after the fuse
F1.2 · D1 cathode · C6.1 · C8.1 · U4.2 (Vin)

### +3V3
U4.3 (Vout) · C7.1 · U1.4 (VDD/VDDA) · C4.1 · C5.1 · R2.2 ·
U2.5 (Vdd_IO) · U2.8 (Vdd) · C1.1 · C2.1 · R1.2 ·
U3.8 (VCC) · C3.1 · J3.6 · **R7.2**

### GND
D1 anode · C6.2 · C8.2 · U4.1 (GND) · C7.2 ·
U1.5 (VSS/VSSA) · C4.2 · C5.2 ·
U2.2 (SDx) · U2.3 (SCx) · U2.6 (GND) · U2.7 (GND) · C1.2 · C2.2 ·
U3.4 (GND) · C3.2 · J1.1 · J2.1 · J3.1 · **J4.3** · **J5.3** · C9.2 · X1.2

### Reset
| Net | Connection points |
|---|---|
| NRST | U1.6 (PF2-NRST) · R2.1 |

The other end of R2 (R2.2) goes to +3V3, forming a 10k pull-up.

### The four pull-up resistors (R1/R2/R4/R5, the other ends all go to +3V3)

| Ref | What it holds | Why |
|---|---|---|
| **R1** | `SPI_CS` | During power-up and reset PA4 is high-impedance; a floating CS may make the IMU think it is in I²C mode, or take bus noise as a command. **Required** |
| **R2** | `NRST` | The chip already has an internal ~40 kΩ weak pull-up; the external 10 kΩ improves noise immunity. Reinforcement |
| **R4** | `DE` | `1OE#` **enables transmission when low**. During reset PA1 is high-impedance; if this pin floats low, the transmit buffer opens and this board pushes data onto the bus, colliding with the 15 servos. **Required** |
| **R5** | `DXL_DATA` | When the bus is idle and nothing drives it, the floating `2A` CMOS input draws shoot-through current, and the UART may take noise as a start bit. This board defines its own idle level instead of relying on the host |

> R4 and R5 were added on 2026-09-06 following community review comments. Before that, only CS had a pull-up;
> **the same reasoning was not extended to DE, which was an omission**.

### IMU (4-wire SPI + two interrupt lines)
| Net | U1 (STM32) | U2 (LSM6DSV16X) | Other |
|---|---|---|---|
| SPI_CS   | 11 · PA4 | 12 · CS       | R1.1 (R1.2 pulled up to +3V3) |
| SPI_SCK  | 12 · PA5 | 13 · SCL      | |
| SPI_MISO | 13 · PA6 | 1 · SDO/SA0   | |
| SPI_MOSI | 14 · PA7 | 14 · SDA      | |
| IMU_INT1 | 7 · PA0  | 4 · INT1      | |
| IMU_INT2 | 15 · PB0/PA8 | 9 · INT2  | |

### Half-duplex bus (U3 = SN74LVC2G241 dual buffer)
| Net | Connection points |
|---|---|
| MCU_TX   | U1.9 (PA2 · USART2_TX) · U3.2 (1A) |
| MCU_RX   | U1.10 (PA3 · USART2_RX) · U3.3 (2Y) |
| DE       | U1.8 (PA1 · USART2_DE) · U3.1 (1OE#) · **R4.1** |
| DXL_DATA | U3.6 (1Y) · U3.5 (2A) · **R5.1** · **R6.1** (buffer side) |
| **DXL_BUS** | **R6.2** · **D2 cathode** · J1.3 · J2.3 · **J4.1** · **J5.1** (connector side) |
| **RX_EN** | **U1.1 (PB7/PB8)** · **U3.7 (2OE)** · **R7.1** (receive buffer enable, added 2026-09-07) |

`U3.7 (2OE)` was originally tied directly to +3V3; on 2026-09-07 it was changed to the **`RX_EN` net**: pulled up to
+3V3 through **R7 10 kΩ**, with a trace also routed to **U1.1 (PB7/PB8)**.

**The default behavior is unchanged**: during MCU reset PB7 is high-impedance, R7 pulls `2OE` high, and the receive buffer stays open as before;
even without a single line of firmware, it behaves exactly as before the change. This is a **provision**: if you want to suppress the echo during transmission, configure PB7 as
a push-pull output driven low, and at the same time enable the internal pull-up on the `MCU_RX` pin so RX does not float while `2Y` is high-impedance.

### Debug port J3 (6P, `PZ254V-11-06P` / `C492405`)

| Pin | Net | Source |
|---|---|---|
| 1 | GND | |
| 2 | SWDCLK | U1.19 (PA14) |
| 3 | SWDIO | U1.18 (PA13) |
| 4 | **UART_RX** | **U1.17** `PA12[PA10]` → remapped to **PA10** = `USART1_RX`; connect to USB-TTL TX (3.3V level) |
| 5 | **UART_TX** | **U1.16** `PA11[PA9]` → remapped to **PA9** = `USART1_TX`; connect to USB-TTL RX (3.3V level) |
| 6 | +3V3 | Debugger VTref voltage reference; do not connect 5V |

**Erratum 2026-09-21:** rechecked against the 2026-09-08 [schematic PDF](imu_to_dxl-原理图.pdf) in this directory:
SWD uses pins **1, 2, 3, 6**; pins 4/5 are the UART. An old four-pin ribbon cable must not be plugged straight into pins 1–4,
and pin 4 must not be used as 3.3V or VTref. Before connecting, check the pin-1 marking on the real board and the debugger's connector pinout.

The remapping of pins 16/17 relies on `SYSCFG_CFGR1` (DS12992 Rev 3, Table 12 footnote 4).

**Why no USB**: the STM32G031 **has no USB peripheral** (a full-text search of the manual for USB gives zero hits; Development support
only says "serial wire debug (SWD)"). Adding USB would need an extra CH340/CP2102, which is not worth it on a 45×22 mm board.
SWD is enough for debugging:

| Method | What it needs | Notes |
|---|---|---|
| **RTT** (recommended) | J3 pins 1, 2, 3, 6 | `probe-rs` supports RTT over CMSIS-DAP and reads target RAM directly **without stopping the CPU**, with no effect on the 50 Hz control loop |
| UART printf | J3 pins 4/5 + any USB-TTL | Goes through USART1 |
| Semihosting | J3 only | Every printf stops the CPU and breaks the control loop; **do not use** |
| ~~SWO / ITM~~ | — | **Cortex-M0+ does not have it**; only M3 and above |

### Servo connectors: two sets side by side, ⚠️ **with opposite pin order**

The board has four servo bus connectors in two pairs; the three wires are paralleled one to one (the same electrical node),
**but the pin order of the two pairs is completely reversed**, because the two vendors' wire orders differ to begin with.

**`J1` / `J2`: `B3B-EH-A`, 2.5 mm, for Dynamixel / official HAT harnesses**

| Pin | Net |
|---|---|
| 1 | GND |
| 2 | VDD_BUS |
| 3 | **DXL_BUS** |

**`J4` / `J5`: `B3B-PH-K-S`, 2.0 mm, for Feetech HD-1910 harnesses**

| Pin | Net |
|---|---|
| 1 | **DXL_BUS** |
| 2 | VDD_BUS |
| 3 | **GND** |

> ⚠️ **Never copy the nets of `J1` onto `J4`.** Feetech's "HD-1910-C001 Serial Servo Specification" A/0,
> page 3/7, items 6-7, states that the cable end is `1=Signal / 2=Vcc / 3=GND`, reversed end to end relative to the Dynamixel side.
> Fortunately **2.0 mm and 2.5 mm connectors do not fit into each other**, which physically rules out plugging into the wrong one; the only remaining risk is "drawing it wrong".
> The pin order of all four connectors was rechecked on 2026-09-08 by reading back the PCB netlist, and all are correct.
>
> Also note that **`AMP2.0` is 2.0 mm and `JST EH` is 2.5 mm**; Feetech cables do not fit into `J1`/`J2`,
> ⚠️ First-board hardware test (2026-09-17): the **housing** of `B3B-PH-K-S` does not match the Feetech plug and it will not go in; cutting off the housing and keeping only the pins works. v2 switches to a connector that actually mates with the Feetech cable.
> and vice versa: plug into whichever pair matches the servos you use.

> 📌 **Pin 3 was previously misrecorded in this table as `DXL_DATA`**. After the `R6` 150 Ω series resistor was added on 2026-09-06,
> the buffer side (`DXL_DATA`) and the connector side (`DXL_BUS`) became two separate nets, and the connector carries `DXL_BUS`.
> Corrected 2026-09-08.

## Unconnected pins

- U1: **3 (PC15-OSC32_OUT), 20 (PB3/PB4/PB5/PB6)**
  - Pin 3 is routed to a pad and, together with pin 2, forms the reserved active oscillator footprint (not populated by default); see "Clock" below
  - Pin 20 is the only completely free GPIO (shared by the four ports PB3/PB4/PB5/PB6, the most flexible); kept for later use
  - Pin 1 (PB7/PB8) was originally free; since 2026-09-07 it is used as `RX_EN`
  - Pin 2 (PC14-OSC32_IN) connects to `OSC_IN`, pins 16/17 (PA9/PA10) connect to `UART_TX`/`UART_RX`
    (previously misreported in this table as unconnected; corrected 2026-09-07)
- U2: 10 (OCS_Aux), 11 (SDO_Aux): the auxiliary SPI is not used and ST DS13510 allows them to float; the conservative choice is to tie OCS_Aux to Vdd_IO

**U2.2 (SDx) and U2.3 (SCx) must be grounded** and must not float (ST DS13510 Rev 1, Table 1).

## Clock: internal HSI16, oscillator footprint reserved and not populated

**This package cannot use a passive crystal.** DS12992 Rev 3, Table 12 (p.36): the additional functions of TSSOP20 pin 2
(`PC14-OSC32_IN`) include `OSC_IN`, but pin 3 (`PC15-OSC32_OUT`) only has `OSC32_OUT`,
**not `OSC_OUT`**; `PF0`/`PF1` are not brought out at all in this package. A passive crystal needs two pins to oscillate.

| Option | Feasibility |
|---|---|
| Passive high-speed crystal | ❌ no `OSC_OUT` |
| Active oscillator via HSE bypass (fed into pin 2, pin 3 can serve as `OSC_EN`) | ✅ |
| 32.768 kHz LSE passive crystal | ✅ but it cannot clock the PLL; it can only calibrate HSI16 |

HSI16 accuracy (Table 41, p.64): factory −0.75%/+0.5%, temperature drift ±1% over 0–85 °C, voltage drift ±0.1%
→ worst case about **−1.85% / +1.55%**. Typical 1 Mbps UART tolerance is ±3%, which is enough but without much margin.

**Approach**: route pins 2 and 3 to pads and leave a 3225 active oscillator footprint + decoupling footprint. Initially not populated by default; since 2026-09-08, X1 / R3 / C9 are populated by default;
the firmware uses HSI16 first, and HSE bypass is enabled only if bit errors are measured at 1 Mbps.
Note: in the schematic, X1's `Tri-state` enable pin is **tied to 3.3 V**; the "pin 3 (PC15) can serve as `OSC_EN`" mentioned above was not drawn in, and PC15 is left unconnected. If the first board needs the MCU to control the oscillator, add a jumper wire PC15 → X1.1; see README "Review record · 2026-09-16".

## Enable polarity

`1OE#` low enables the transmit buffer; `2OE` tied high keeps the receive buffer always open.

- PA1 is USART2's hardware DE pin, configured with `CR3.DEP = 1` (DE active low); the transmit/receive switching is done in hardware
- An always-open receiver means the board receives its own echo on RX while transmitting; the firmware simply discards it based on the transmit length
- The alternative is to also connect `2OE` to DE (closing the receive buffer while transmitting), but then the MCU's RX pin floats during transmission and may produce a false start bit when re-enabled; not recommended
- **Improvement 2026-09-07**: `2OE` is no longer hard-tied to +3V3; instead it is pulled up through R7 10 kΩ and also routed to `U1.1 (PB7/PB8)`.
  The default is still always open (behavior unchanged), but the firmware gains an option: to close the receiver, drive PB7 low and enable the MCU RX pin's
  internal pull-up to deal with floating. This is more flexible than connecting it to DE: whether and when to close it is up to the firmware

## HD-1910-C001 measured parameters (Feetech official product page, pre-sale period)

Feetech made this one specifically for the little duck; the page title is literally "**Open-source duck servo**: serial bus servo, custom-developed for the little duck AI toy".
Marking on the servo body: **"3-pin interface · TTL serial bus"**.

| Item | Value |
|---|---|
| Voltage range | **5 V – 8.4 V** |
| Stall torque | **10 kg·cm = 0.98 N·m** |
| Rated load | **3.0 kg·cm = 0.294 N·m** |
| No-load speed | 0.09 s/60° (110 RPM) |
| **Standby current** | **21 mA** |
| **No-load current** | **140 mA** |
| **Rated current** | **500 mA** |
| **Stall current** | **1.8 A** |
| Dimensions | 34 × 20 × 23 mm |
| Weight | 22.5 ± 2 g |
| Housing | PA + Fiber |

Its size is in the same class as the XL330 (20×34×26 mm), so it is roughly a mechanical drop-in replacement; its torque is nearly twice that of the XL330-M288 (0.52 N·m).

> ⚠️ Do not apply the electrical parameters from the `HL-2915-C002` spec sheet to this servo; that is a 12 V (9–14 V) model.
> Only the connector definition and the protocol sections are shared.

### ⚠️ Overcurrent on the J1↔J2 pass-through path

The three wires of J1 / J2 are paralleled one to one, so **if this board sits in the middle of the chain, the current of every downstream servo flows through this board's connectors and copper traces**:

| Condition | Single | ×15 |
|---|---|---|
| Standby | 21 mA | 0.3 A |
| No-load motion | 140 mA | 2.1 A |
| **Rated load** | **500 mA** | **7.5 A** |
| Stall | 1.8 A | 27 A |

Yet the **JST EH is rated for only 3 A**.

> F1 (200 mA PPTC) **is not affected**: it sits only in series with this board's own supply path
> (`VDD_BUS → F1 → VDD_F → U4`), not on the J1→J2 pass-through path.

**Choose one:**

1. **Put this board at the end of the chain** (a leaf node), using only J1, with J2 left empty or connected to only 1 servo; only about 12 mA then flows through this board. **Recommended**
2. If it must sit in the middle of the chain, route `VDD_BUS` and `GND` from J1 to J2 on the PCB with **wide copper** (≥ 2 mm, or a copper pour),
   and check that the downstream servo count stays under 3 A

## Feetech connector definition (confirmed by the official spec sheet)

**Source**: Feetech "HL-2915-C002 Serial Servo Specification" A/0, 2026-02-27, page 4, items 6-7.

```
6-7  Connector and Cable
     Type             AMP-3
     Material         PP
     Length           15CM / 25CM
     Pin Definition   1  GND
                      2  Vcc
                      3  Signal/TTL
```

**`1=GND / 2=Vcc / 3=Signal`, exactly the same as Dynamixel → the current J1/J2 wiring is correct.**

Supporting evidence: in the `HD-1910-C001.stp` assembly the connector part is named **`AMP-3P`**, and the assembly contains
`HL-2915-C002-20260409_ASM`; the two models share a platform, so the connector definition is common.

### Other usable entries in the same spec sheet

| Item | Value | Significance |
|---|---|---|
| 7-2 Protocol type | Half Duplex Asynchronous, **8bit / 1stop / No Parity** | Same as this board |
| 7-4 Baud rate | 38400 ~ 1 Mbps, **factory default 1 Mbps** | Same speed as Dynamixel |
| 7-3 ID range | 0–253, **factory default ID 1** | The 15 servos need their IDs changed one by one; this board uses 200, no conflict |
| 12 **Signal high level** | **2 V ~ 5 V** | See below |
| 12 Signal low level | 0.0 V ~ 0.45 V | |
| 6-6 Angle sensor | 12 Bits magnetic encoder | Magnetic encoder ⇒ **little-endian byte order** |

**Signal levels must be checked in both directions**:

1. This board driving the bus: the `SN74LVC2G241` powered at 3.3 V outputs about 3.3 V, inside the 2–5 V high-level window the servo requires ✅
2. The servo driving the bus: it may output up to **5 V**; the 74LVC powered at 3.3 V has **5.5 V-tolerant inputs** ✅
   (choosing LVC rather than LV/HC is exactly what covers this)

> ⚠️ This spec sheet is for the **HL-2915-C002 (12 V, 9–14 V)**, not the HD-1910 (5–8.4 V).
> **Do not mix the electrical parameters**: supply range, stall current and overvoltage protection thresholds all differ.
> Only the **connector definition and protocol** sections are shared.

### Background: different Feetech series have different physical layers

Original text from the official memory table manuals of each series (<http://doc.feetech.cn>, endpoint `getQr/{q}`):

| Series | Signaling | Default baud rate |
|---|---|---|
| **STS** (magnetic encoder) | **TTL single-wire bus** | **1M** |
| SCS (potentiometer) | TTL single-wire bus | 1M / 500k |
| SMS (magnetic encoder) | **RS485** | 115200 |
| HLS (magnetic encoder) | Not stated | 1M |
| SHC | CANopen | 125k |

"Feetech = TTL single wire" **only holds for the STS/SCS/HL branch**; SMS is RS485. Check the manual before switching series.

## Automatic protocol detection (no jumpers, no DIP switches)

The two vendors' packet headers are naturally distinguishable; the deciding point is **bytes 3 and 4**:

| | Header | Following | Checksum |
|---|---|---|---|
| Dynamixel V2 | `FF FF` | **`FD 00`** | CRC-16 (poly 0x8005) |
| Feetech STS/SCS | `FF FF` | `ID` + `LENGTH` | `~(ID+LENGTH+INST+params)` |

No ambiguity: byte 3 of a Feetech packet is the ID (which can be 0xFD), but **byte 4, LENGTH, is never 0**
(the minimum is 2 = instruction + checksum). So `FF FF FD 00` can only be V2.

```
State: unknown / locked V1 / locked V2

While unknown, on receiving a packet starting with FF FF:
    if byte[2]==0xFD && byte[3]==0x00:
        parse as V2, compute CRC-16 → if it passes, one vote for V2
    else:
        parse as V1, compute ~sum   → if it passes, one vote for V1
    3 consecutive matching votes → lock

After locking: parse only with the locked protocol, and reply with the same one
Fallback: 100 consecutive packets all fail to parse → unlock and detect again
```

Everything below follows the **original text of Feetech's official "SCS Servo Communication Protocol"**:

- Frame format: **1 start bit + 8 data bits + no parity + 1 stop bit**, 10 bits in total
- Header: two consecutive `0xFF`
- ID range **0～253** (`0x00`～`0xFD`), **broadcast ID = 254 (`0xFE`)**
- Data length **Length = number of parameters N + 2**, so **the minimum is 2 and it is never 0** ← the basis for unambiguous detection
- Checksum = `~(ID + Length + Instruction + Param1 + … + ParamN)`; if it exceeds 255, take the low byte
- Sync read `0x82`, sync write `0x83`, PING `0x01`, read `0x02`, write `0x03`
- ⚠️ **Byte order of multi-byte parameters depends on servo type**: "potentiometer servos are **big-endian** (high byte first), magnetic encoder servos are **little-endian** (low byte first)"

Three key points:

1. **It must lock; do not decide packet by packet**: the bus has noise, and a packet corrupted to look like `FD 00` would make it flip back and forth
2. **Reply with the same protocol**: not only parsing needs to branch, packet building does too
3. **Fallback unlock**: switching servo brands does not require reflashing the firmware

The slave ID is **200** on both sides, which does not conflict with the 15 servos (usually numbered 1–15).

> Feetech STS's `Return Delay Time` defaults to 0, and the manual notes "Not functional on STS":
> the register has no effect, and the reply delay is entirely determined by the firmware.

## Package standard: all resistors and capacitors 0603

All resistors and capacitors use **0603** and D2 uses **SOD-123**; no 0402/SOD-323.

The reason is not hand soldering: the board has the LSM6DSV16X in LGA-14, which needs hot air anyway.
**The real reason is rework during debugging**: trying the series resistor from 150 Ω down to 33 Ω, removing a pull-up, adding a decoupling capacitor;
with 0603 a soldering iron does it in seconds. A first-revision board that has never been verified will certainly need a few changes.

Cost: 11 parts take about 16 mm² more, under 2% of the board area. And these 0603 values are all in the LCSC **basic library**
(10 kΩ `C25804` · 150 Ω `C22808` · 33 Ω `C23140` · 100 nF `C14663`), which saves more on feeder fees than 0402 parts from the extended library.

> C6 (10 µF/25 V) stays 0805; C5 (4.7 µF) and C7 (10 µF) are already 0603.

## Data line protection (following the HAT's approach)

```
U3.6 (1Y) ──┬─ DXL_DATA ─┬── R5 10k → 3.3V
U3.5 (2A) ──┘            │
                         └── R6 150Ω ──┬── DXL_BUS ── J1.3 / J2.3
                                       │
                                    D2 5V1
                                       ⏚
```

| Part | Function |
|---|---|
| **R6 150 Ω** | Source series resistor. Limits short-circuit current and softens edges to reduce EMI. At 1 Mbps the delay is about 3% of a bit time |
| **D2 5V1** | Clamp. Cathode to `DXL_BUS`, anode to ground |

**The pull-up stays on the buffer side** (R5 before R6): this way, even with no bus plugged in, the `U3.5 (2A)` CMOS input
has a defined level and does not float. This matches the position of `R32` on the HAT.

> The official HAT uses `R33 150R + TH1 100R` in series, 250 Ω in total, plus a `D4 5V1` clamp
> (`dynamixel.kicad_sch`). **D2 is the same part number as the HAT's D4 but a different package**: the HAT uses SOD-323 (`C151348`), this board uses SOD-123 (`C151588`) for easier rework.
> This board uses only 150 Ω because the HAT side already has 250 Ω, and too much series resistance on the bus would slow the edges.

## Three lines of overvoltage defense

1. **F1** PPTC 200mA hold / 24V: current limiting, protects against shorts
2. **D1** TVS SMF12A: clamping, protects against back-EMF spikes from the servos
3. **U4** HT7533-1 rated for 30V: even if the first two fail, the LDO itself can withstand it

## Layout notes

- 2-layer board, 45 × 22mm, all SMD parts on the top side
- The 3 connectors (J1/J2/J3) are lined up along the same edge, through-hole
- Two M2 mounting holes, 34mm apart (compatible with the original `banana_pcb_locker`)
- C1/C2 sit right next to U2's Vdd / Vdd_IO pins, with traces as short as possible
- C4 (100nF) and C5 (4.7µF) sit right next to U1 pin 4; ST DS12992 Fig.13 requires "as close as possible to the pin, or on the back of the PCB directly opposite the pin"
- Widen the DXL_DATA trace and keep it away from SPI
