# imu_to_dxl firmware 0.2.0

**English** · [简体中文](README.md)

For the **STM32G031F8P6 + LSM6DSV16X** board made by a teammate. The hardware baseline is
`a1f4979c425bd9228622be89f2bfa4d1de7fbde3` of `fanhao375/microduck-replica`
(2026-09-08, including J4/J5 and RX_EN). The first real-board bring-up was completed on 2026-09-20: J-Link SWD connection,
firmware flashing with readback verification, Keil stopping at `main`, the 64MHz clock and IMU sampling were all verified.
In a short test the IMU ID was `0x70`, ready=1, and SPI/FIFO errors were 0; the external bus and servos have not yet been tested on real hardware.

**0.2.0 (2026-09-22) switches the bus protocol to Feetech SCS/STS**, implemented item by item according to the [bus protocol](../总线协议.md): ID 200, a 15-byte block at address 56, sync_read queuing. The IMU, board-level code and Keil project are unchanged. The host tests on the PC and the acceptance check "on a simulated bus running the real protocol code" (`Tests/bus_sim_test.py`, using the `check` criteria from [`tools/imu200`](../../../tools/imu200)) all pass; it has been flashed to the original development board and the IMU works as before. **The real bus and servos have not yet been tested on real hardware.**
For the boundaries of the build, desktop tests and first real-board validation, see [VALIDATION.md](VALIDATION.md).

This directory sits next to the schematic and PCB and provides the source code, the Keil project and the only prebuilt output kept in the repo,
[`Build/imu_to_dxl.hex`](Build/imu_to_dxl.hex). The serial debug console [`tools/servo-web`](../../../tools/servo-web) can overlay servo joint angles and the IMU torso attitude in the same web page, with three ways to read the IMU: `--imu-bus` (servo bus, the same sync_read as the main controller), `--imu-swd` (ST-Link / DAPLink), `--imu-jlink` (J-Link).

The SWD / J-Link viewer decodes the **10,724-byte** Flash image starting at `0x08000000` from the HEX, checks SHA-256
`66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e`, and verifies the image on the board.
Only this baseline may use the reviewed RAM layout: `sample=0x2000006C` (60 bytes),
`tick=0x20000A34` (4 bytes), checked against the 0.2.0 MAP. If you only use the attitude web page, there is no need to recompile; after changing the firmware you must re-review
the Flash checksum and the addresses and sizes of these two symbols; old addresses must not be reused to read a new program.

Source-level breakpoint debugging requires rebuilding the `.axf` in your own environment; the build still generates `.map` and `.bin` for review during development.
These files and test output are excluded by `.gitignore` and are not committed to the repo.

Data flow: LSM6DSV16X → SPI1 → STM32 → USART2 + external buffer → single-wire half-duplex bus → Linux main controller.
It implements the **Feetech SCS/STS protocol, ID 200, 1Mbps**, posing as a servo on the servo bus (0.1.0 used Dynamixel Protocol 2.0).
The code does not drive servo motion, does not write MCU Option Bytes, and does not write firmware configuration to Flash.

**Real bus acceptance check**: connect a half-duplex adapter (URT-2) and run `python tools/imu200/imu200.py check --port COMx`. Its 13 criteria are written from the main controller source code, and the board must pass them before going into the full robot. Electrical checks (DE release, levels, measured T_resp) still require a logic analyzer.

## 1. Getting started

### Keil

1. When using a J-Link, open `MDK-ARM/imu_to_dxl_jlink.uvprojx`.
2. In your own Keil, select a legitimately installed Arm Compiler 6 (6.24 and 6.22 are verified; older versions such as MDK 5.24 bundled with 6.7 cannot compile it, because the CMSIS 6 headers require ≥ 6.10 and it reports that `cmsis_clang.h` cannot be found) and the `STM32G031F8Px` device pack.
3. Press **F7** to compile; `Build/imu_to_dxl.hex` is the file to flash, and the `.axf` is for source-level breakpoint debugging.
4. In Debug → Settings, select your J-Link and check SWD, the STM32G0xx 64KB Flash algorithm and Run to main.
   `JLinkSettings.JLinkScript` sets the transfer speed to **100kHz** after connecting and resetting; keep this file.
   The first board had data transfer failures when downloading at 4MHz, so use the verified 100kHz for the first connection.
5. Press **Ctrl+F5** to start debugging and stop at `main`; **F10** steps over, **F11** steps into, **F5** runs.
   Pausing changes the sampling and bus timing, so run at full speed for continuous communication tests.

The ST-LINK configuration of the original `MDK-ARM/imu_to_dxl.uvprojx` is kept. When switching to a J-Link, reselect the probe in Debug → Settings.

### VS Code

Open this folder in VS Code to edit the source and run the build command below in the integrated terminal.
This route uses VS Code for editing and Keil for compiling and hardware debugging; you do not need to install CubeMX, CubeIDE or GCC to build.
The source includes the required CMSIS headers and the ST IMU driver, so the first build needs no dependency downloads.

You can also run this in a PowerShell terminal in this directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1
```

The default compiler path `E:\Keil_v5\ARM\ARMCLANG` is only an example. On other computers, use `-ToolchainRoot` to point to a legitimately installed Arm Compiler.
The temporary build directory is under this project's `Build`; the operating system and license caches of existing tools are still managed by each piece of software.
A build replaces the prebuilt firmware in `Build`; if you need to keep the verified baseline for the web page, save the original output first.

## 2. Project contents

| File | Content |
|---|---|
| `Core/Inc/board_config.h` | Centralized board-level switches, clock, baud rate, SPI speed |
| `Core/Src/board.c` | Clock, GPIO, SPI, USART, SWD kept, millisecond/microsecond time base, watchdog |
| `Core/Src/imu.c` | Identity check, initialization readback, FIFO, raw accelerometer/gyro, SFLP, fault retry |
| `Core/Src/protocol.c` | Feetech SCS/STS slave: frame parsing (resynchronizing by checksum), replies to each instruction, sync_read queuing, reply timing |
| `Core/Src/control_table.c` | 15-byte block at address 56, status bits, diagnostic registers |
| `Core/Src/main.c` | Main loop scheduling, serial commands and status logging |
| `Drivers/` | Pinned versions of ST/CMSIS sources and licenses |
| `MDK-ARM/` | Keil project, link layout and the J-Link low-speed connection script |
| `Tests/` | Protocol, simulated sensor and register tests that run without a board; `bus_sim_test.py` compiles the real protocol code into a DLL and runs the acceptance check on a simulated bus |

No dynamic memory, no RTOS, no HAL dependency. The board-level code uses ST's official CMSIS register definitions; the sensor uses the official platform-independent driver.
External bus reception on the STM32 uses an interrupt-driven ring queue that saves the receive time of each byte; the protocol, sampling and log formatting run in the main loop.
Log transmission uses a separate interrupt queue and does not block bus reception.

## 3. Default hardware configuration

| Function | Chip pin / configuration |
|---|---|
| MCU | STM32G031F8P6, TSSOP20, 64KB Flash / 8KB RAM |
| System clock | HSI16 → PLL, M=1, N=8, R=2, 64MHz, Flash 2 wait states |
| External clock option | `BOARD_USE_HSE_BYPASS=1`, X1 16MHz active oscillator on package pin 2; on startup failure it falls back to the HSI route and records the status |
| IMU SPI | SPI1 mode3, 8bit, software CS; 2MHz at 64MHz; PA4=CS, PA5=SCK, PA6=MISO, PA7=MOSI |
| IMU INT | The first version polls the FIFO; the PA0/package pin 15 interrupt signal is not used yet |
| Bus UART | USART2, PA2=TX, PA3=RX, AF1, 1Mbps, 8N1; USART single-pin HDSEL not enabled |
| Bus DE | PA1 → U3.1 `1OE#`, **active low**; GPIO-controlled, released only after USART TC |
| Bus RX_EN | PB7 → U3.7 `2OE`, **active high**; off while sending, PA3 pulled up; PB8 on the same package pin is kept as an analog input |
| Debug UART | USART1, PA9/PA10 remapped through SYSCFG to package pins 16/17, 115200, 8N1; `BOARD_LOG_UART_SWAP=0` |
| SWD | PA13=SWDIO, PA14=SWCLK, the default debug function after reset is kept |
| Watchdog | On by default, about 2 seconds (LSI tolerance affects the actual duration); frozen while the debugger is paused |

If the PLL fails to start, the board keeps running on HSI16, and the UART BRR and timers are computed from the actual core clock. In that case SPI also drops to 0.5MHz
and service latency increases. This is a fault-diagnosis mode: check the clock status, and do not use it as a configuration for performance acceptance.

### J3 wiring must follow the [schematic PDF](../imu_to_dxl-原理图.pdf) and the real board nets

| J3 pin | Signal in the latest schematic | Connection |
|---|---|---|
| 1 | GND | Common ground with J-Link/ST-LINK/USB-TTL |
| 2 | SWDCLK | J-Link/ST-LINK SWCLK |
| 3 | SWDIO | J-Link/ST-LINK SWDIO |
| 4 | UART_RX, U1 package pin 17 | USB-TTL TX, 3.3V level |
| 5 | UART_TX, U1 package pin 16 | USB-TTL RX, 3.3V level |
| 6 | 3.3V | Debugger voltage reference; do not connect 5V here |

The four SWD wires on J3 use pins **1, 2, 3, 6**; do not plug an old four-pin ribbon cable straight into pins 1–4.
Pin 4 is the UART input and cannot be used as power or a voltage reference. Before the first power-up, verify against the pads/EDA nets.
J3 does not break out NRST; for an under-reset connection, wire to the actual NRST test point separately.
If the debugger has a power output, do not blindly parallel it with another supply; first confirm whether it is a VTref input or a power output.

J1/J2: 1=GND, 2=VDD_BUS, 3=DATA; J4/J5: 1=DATA, 2=VDD_BUS, 3=GND.
Bus tests require a single-wire half-duplex USB adapter; an ordinary USB-TTL is only for the J3 log.

## 4. IMU behavior

- WHO_AM_I should be `0x70`. After a software reset it is configured step by step, and the ODR, range and SFLP enable are read back.
- Accelerometer ±4g, 0.122mg/LSB; gyro ±500dps, 17.5mdps/LSB.
- Accelerometer, gyro, SFLP and FIFO batching are all at 120Hz, read by the 50Hz main controller.
- The FIFO distinguishes accelerometer, gyro and quaternion by tag; up to 16 records per round, without assuming all three are in the same record.
- `ready=0` during initialization, on SPI failure, FIFO overflow or stale data; it retries automatically after about 1 second.
- If either gyro or quaternion has not been updated for more than 100ms, the data is invalid. Even if the main loop is busy and has not run the sampling poll, reading a snapshot checks the age again.
- The read interface keeps a consistent snapshot; the attitude is not updated inside interrupts. The sensor mounting rotation is left to the main controller to avoid duplicating the official coordinate transform.
- This version does not store measured biases; SFLP starts estimating from the power-up default state. A six-axis attitude provides no absolute heading reference.

The legitimate unit attitude `xyz=0,0,0` coincides with the upstream all-zero "not ready" sentinel. When a valid FIFO attitude has been received, only the half-precision
encoding of x is set to IEEE negative zero `0x8000`, while the mathematical value is still 0; a genuinely not-ready state always returns all zeros. See the driver notes and regression tests for details.

**Boundary of runtime fault handling:** the official main controller that was checked may keep the previous attitude after receiving an all-zero attitude, and its `ready()` is not automatically cleared as a result.
Before formal standing/motion integration testing, the main controller should additionally read this version's diagnostic `ready`, sample count and age, and handle failures.
This version's PC capture script already reads these fields; "the board returns all zeros" must not be taken to mean the full robot already has automatic stopping behavior.

## 5. Communication and registers

Frame format `FF FF ID LEN INSTR params… CHK`, `CHK = ~(ID+LEN+INSTR+Σparams)`. There is no byte stuffing, so `FF FF` can also appear in the payload: the receiver collects the frame by length and then checks the checksum; on a checksum error it drops one byte and searches for the header again, so it is not thrown off by false headers in the payload. For the behavior of each instruction, see [bus protocol §8](../总线协议.md#8-其它指令怎么应答):

| Instruction | Behavior |
|---|---|
| `SYNC_READ 0x82` (broadcast) | If it is at position k in the list: k=0 sends 50 µs after receiving the instruction; k>0 waits for the reply frames of the k devices before it (ID earlier in the list, correct length, 5th byte is not an instruction code); if a device ahead stays silent for 1 ms, it is treated as offline and skipped |
| `PING` / `READ` (unicast) | Returns a status frame / data, ERROR always 0; broadcast PING is not answered |
| `WRITE` / `REG_WRITE` (unicast) | Returns ACK, content always ignored (the main controller never writes to this board) |
| `ACTION` `0x06` `0x09` `0x0A` `0x0B` (unicast) | ACK, no action |
| `REBOOT 0x08` | No reply, actually reboots |
| `SYNC_WRITE`, other broadcasts | No reply |

Timing (all inferred values, to be measured; see bus protocol §5/§12; 50 µs is the number in the protocol logic, and the real value including CPU time for parsing and packing has to be measured with a logic analyzer): T_resp 50 µs; a partial frame is discarded if the gap between bytes within a frame exceeds 500 µs; while queuing, 1 ms of bus silence means the previous device is offline; if its turn does not come within 25 ms it gives up; if it still cannot send 2 ms after its slot, it gives up, to avoid grabbing the bus during the next transaction. Before sending, it atomically checks again for newly arrived RX data, USART BUSY and fault flags; if the bus is busy, it abandons this reply.
In the receive interrupt, only **overrun (ORE)** is treated as a bus fault that clears the received packet; noise / framing error flags are only counted, the byte is still accepted, and errors are discarded by the checksum. In 0.1.0 every such flag cleared the buffer, so one byte with a noise flag would throw away the whole sync_read, and the 15 servos would be lost for that tick along with it (changed after the 0.2.0 review).

**Put ID200 first in the Sync Read list**, the same as the official `bus.rs`. It can also answer in the middle (queuing rules), but if a device ahead is absent, parsing on the main controller side gets misaligned; see bus protocol §2.

All multi-byte fields are little-endian.

| Address | Bytes | Content / access |
|---|---:|---|
| 0 / 1 | 1 each | Firmware version 0.2 (major.minor), does not pose as the servos' 3.46 |
| 2 | 1 | END = 0 (little-endian) |
| 3 | 2 | Custom model `0x4D44` |
| 5 / 6 / 8 | 1 each | ID 200 / baud rate 0 (1Mbps) / response status level 1 |
| **56** | **15** | **Block read by the main controller every tick**: gyro XYZ (int16, 17.5 mdps/LSB), quaternion XYZ (binary16), sample count (u8), status bits, reserved 0. Raw axis order, no coordinate transform |
| 124 | 6 | gyro XYZ, three int16, ±500dps (diagnostic, same data as in the block) |
| 130 | 6 | quaternion XYZ, three IEEE binary16; W reconstructed by the main controller |
| 136 | 6 | Raw acceleration XYZ, three int16, ±4g |
| 142 | 1 | Low 8 bits of the attitude sample count |
| 143 | 1 | bit0=ready, bit1=configured, bit2=error |
| 144 / 145 | 1 each | WHO_AM_I / error code |
| 146 / 147 | 1 each | Clock status / watchdog switch |
| 148 / 152 / 156 | 4 each | Attitude / gyro / accel sample counts |
| 160 / 164 / 168 | 4 each | uptime_ms / gyro age ms / attitude age ms |
| 172 / 176 / 180 / 184 | 4 each | SPI errors / FIFO overflows / invalid quaternions / recovery count |
| 188 / 192 / 196 / 200 | 4 each | RX queue overflows / UART errors (noise/framing/overrun all counted) / checksum errors / invalid packets |
| 204 / 208 / 212 / 216 | 4 each | Receive timeouts / valid packets received / packets actually sent / cancelled replies |
| 220 / 224 / 228 / 232 | 4 each | Raw RCC reset cause / core clock Hz / TX timeouts / dropped log lines |
| 236 | 1 | This project's diagnostic register table version 2 (Feetech protocol, block at 56) |
| 240 | 4 | Number of times a device ahead was judged offline and skipped during sync_read queuing |
| 244 | 4 | Number of replies abandoned because the bus was detected busy before sending |

All other addresses in 0~255 read as 0; writes are always ACKed but have no effect (to re-initialize the IMU, use the `r` command on the J3 log UART instead). 56~70 is the main controller interface; 124 and above are **this project's custom diagnostic extension**, with no claim of compatibility with the servos' voltage/temperature registers.

Status bits in the block (byte 13): BIT0 fusion not ready (quaternion all 0); BIT1 communication with the IMU failed (SPI/reset timeout/configuration/stale data/FIFO); BIT2 self-test failed (wrong WHO_AM_I); BIT3 more than 4 refreshes between two block reads (with 120 Hz sampling and 50 Hz reading, normally 2~3 each time).
Error codes are in `imu.h`: 0 normal, 1 startup, 2 SPI, 3 identity, 4 reset timeout, 5 configuration, 6 stale, 7 FIFO, 8 quaternion.
Clock status: 0=HSI PLL, 1=HSE PLL, 2=HSE failed, fell back to HSI PLL, 3=PLL failed, HSI16, 4=switch failed, fell back.

## 6. Steps once the board arrives

1. Verify the hardware version, J3 orientation and power; power up the single board with current limiting first, and check 3.3V, shorts, heating and reset.
2. Identify the STM32 over SWD, download the HEX, and confirm that a breakpoint in main works and that it boots after reset and after a power cycle.
3. Connect the J3 log UART at 115200/8N1. There should be version information, and ready, id, errors and data are printed every second.
   `s` prints the status, `l` toggles the periodic log, `r` re-initializes the IMU, `?` shows help.
4. Check WHO_AM_I=0x70, ready=1 and that the sample count increases; flip and rotate the board on all three axes to check the acceleration and attitude directions.
5. Connect the bus with only the IMU (a half-duplex adapter such as URT-2) and run `python tools/imu200/imu200.py check --port COMx --only-imu` (asks only 200), then connect the servos and run the full `check`.
6. Use a logic analyzer to check 1Mbps, DE polarity, release after the last stop bit, RX recovery and the worst-case reply latency.
7. Connect one servo, then the full bus; put ID200 first. Record errors, packet loss, FIFO and sample age.
8. Only after the main controller's failure handling and the mounting orientation have been checked, do full-robot integration testing in a supported state.

### PC acceptance tool

For the bus acceptance check, use [`tools/imu200/imu200.py`](../../../tools/imu200/imu200.py) (0.1.0's `Tools/imu_probe.py` spoke the Dynamixel protocol and was deleted along with the protocol switch). It needs Python 3.10+ and pyserial:

```powershell
python tools/imu200/imu200.py check --port COM5   # 13 items, each PASS/FAIL; criteria follow the main controller source
python tools/imu200/imu200.py demo                # no hardware needed; see how a fake board answers
```

Replace COM5 with the **half-duplex bus adapter** port; the J3 log port cannot respond to these protocol instructions. Logs are written to `tools/imu200/logs/` (raw send/receive hex + one JSONL line per frame).
You need a working Python installation; the Windows Store placeholder cannot run these scripts. Compiling the firmware itself does not need Python.

## 7. Validation and known limitations

The test code runs with a real C compiler; the SPI/FIFO tests use simulated registers and time and are not equivalent to measurements on the chip.
After installing MSVC, run `Tools/test.ps1` in its **x64 Native Tools Command Prompt / Developer PowerShell** to repeat the host tests.
This entry point requires `cl` on PATH; you can pass `-PythonExe` to specify your own Python. When running the two C test `.cmd` files on their own,
you can also pass the full path of your own `vcvars64.bat` as the first argument. The test scripts do not install a compiler and do not connect to hardware.
The current validation record is in `VALIDATION.md`; third-party source versions are in `DEPENDENCIES.md`.

Still to be confirmed on a real board: power and assembly, HSI baud rate error, SPI mode/edge/chip-select timing, TX enable timing, bus electrical levels,
the actual FIFO update rate, initial SFLP convergence and coordinate directions, temperature drift, watchdog recovery and long-term operation on the shared bus.
Passing software tests cannot replace these acceptance checks.

## 8. References

- [This board's hardware](https://github.com/fanhao375/microduck-replica/tree/a1f4979c425bd9228622be89f2bfa4d1de7fbde3/hardware/imu_to_dxl)
- [STM32G031 datasheet](https://www.st.com/resource/en/datasheet/stm32g031f8.pdf)
- [LSM6DSV16X datasheet](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [ST IMU driver](https://github.com/STMicroelectronics/lsm6dsv16x-pid)
- Feetech "SCS Communication Protocol" and memory table: [`docs/飞特资料/`](../../../docs/飞特资料/) in the repo
- [This board's bus protocol (interface contract)](../总线协议.md)
- [The upstream main controller interface that was checked](https://github.com/pollen-robotics/microduck/blob/5984efb770855432b03dafd3d879e9929981e45b/duck-control/src/bus.rs)

New code written for this project is provided under the MIT license; third-party files keep their own copyrights and licenses, see each Drivers directory.
