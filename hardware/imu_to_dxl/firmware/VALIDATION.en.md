# Firmware validation record

**English** · [简体中文](VALIDATION.md)

Subject: imu_to_dxl 0.2.0 (Feetech protocol), STM32G031F8P6 + LSM6DSV16X. The records for 0.1.0 (Dynamixel 2.0) are kept further down.
This page separates desktop test results from real hardware results.

## 0.2.0 · Feetech protocol (2026-09-22)

Only the protocol layer was changed (`protocol.c/.h`, `control_table.c/.h`, the `main.c` interface, `board_reboot`, the version number); the IMU, board-level initialization, startup file and Keil project are unchanged.

| Item | Result |
|---|---|
| Rebuild with Keil MDK 5.41 + Arm Compiler 6.22 | 0 errors, 0 warnings (`-Wall -Wextra`) |
| Flash | 10,724 / 65,536 bytes (0.1.0 was 11,612: CRC16 and byte stuffing are no longer needed) |
| RAM, including the 2 KiB stack | 4,664 / 8,192 bytes |
| SHA-256 of the image decoded from the HEX | `66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e` |
| MAP check | `sample=0x2000006C` (60 bytes, imu.o), `tick_ms=0x20000A34` (4 bytes, board.o); `tools/servo-web/imu_bridge.py` has been updated accordingly and rechecked with its own MAP verification logic |

| Desktop test (MSVC, no hardware) | Result | Coverage |
|---|---|---|
| Protocol C test `Tests/protocol_test.c` (rewritten) | 104 checks, 0 failures | Byte-by-byte comparison with the bus protocol §10 test vectors, replies to each instruction, sync_read queuing (waiting for the preceding reply / skipping offline devices / cancelled by other traffic / transaction timeout), list validation, checksum resynchronization, false headers in the payload, byte gaps, reply yielding and expiry, timestamp wraparound |
| Mutation testing | 9/9 deliberately planted bugs caught | ERROR byte, queuing, resynchronization, broadcast PING, yielding, length detection, T_resp, skipping gaps, mistaking a main controller instruction for a preceding reply |
| Register C test `Tests/control_table_test.c` (rewritten) | 32 checks passed | Block layout, all 0 when not ready, status bits BIT0–3, BIT3 counting across reads and IMU re-initialization, diagnostic area, out of range |
| IMU C simulation test | 16 scenarios passed | Unchanged |
| **Simulated bus running the real protocol code** `Tests/bus_sim_test.py` | **24/24** | protocol.c + control_table.c are compiled into a DLL and placed among the 15 simulated servos of `sim_bus`; all main controller criteria of `tools/imu200/imu200.py check` pass (count +2~3 per frame, the 12-byte window stays identical for at most 3~4 frames, about 75/80 frames would be accepted by the main controller, varying slightly from run to run); the firmware is polled microsecond by microsecond while other devices are talking and while the bus is idle, with **0 times talking out of turn**; a 16-device sync_read on the virtual bus has a p99 of about 3.9 ms (simulated servo T_resp taken as 30 µs; check's own "transaction time" measures Python wall-clock time and is not counted in the simulation); the protocol logic's T_resp is 50 µs (CPU time not counted); with 200 in the middle and a device ahead offline, the reply order is correct; the debug console's `--imu-bus` polling works live |

**Review (subagent, 2026-09-22)**: no problems were found in protocol.c that would send at the wrong moment or fail to answer when it should. Changes made after the review: (1) while queuing, a frame whose 5th byte is an instruction code does not count as a preceding reply (packets would collide when the main controller sends a same-length instruction to the servos ahead without waiting for this board; this only happens during debugging); (2) the `board.c` receive interrupt clears the buffer only on overrun, and noise/framing errors are only counted (previously a single noise flag dropped the whole tick). This is a register-level change, **not covered by the host tests, and must be verified on the real bus**; (3) the simulated bus test gained out-of-turn talking detection and now uses virtual bus time.

**Real board (original development board, ST-LINK/V2, 2026-09-22)**: flashing with CubeProgrammer and readback verification passed; after a power cycle, pyOCD read the RAM: WHO_AM_I=0x70, ready=1, about 121 Hz, SPI/FIFO/quaternion errors 0; the protocol context is idle and the send/receive counters are all 0 (no bus connected). **The real bus, servos, measured T_resp and DE release timing have not been tested yet.** Note: the board currently has the pre-review version of 0.2.0; to use the SWD/J-Link viewer you must first reflash the HEX from the repo (the viewer only accepts this version, by hash).

Note: after the first flash of a blank G0 chip, a software reset enters ST's built-in bootloader (`FLASH_ACR.EMPTY` is only updated at power-up), so you need one power cycle before the user program runs; see the repo's `踩坑记录` (pitfall log).

---

The following are the records for 0.1.0 (Dynamixel Protocol 2.0).

## Prebuilt baseline (2026-09-15)

| Item | Result |
|---|---|
| Rebuild with Keil µVision 5.43.1 + Arm Compiler 6.24 | 0 errors, 0 warnings |
| `Tools/build.ps1` CLI build | Succeeded; the BIN/HEX shipped with the project come from this entry point |
| Flash | 11,612 / 65,536 bytes |
| RAM, including the 2KiB stack | 5,096 / 8,192 bytes |
| Static data | 3,048 bytes |
| Initial stack pointer | `0x20002000` |
| SysTick / USART1 / USART2 vectors | Valid Flash Thumb entry points |

This directory keeps the corresponding source and one `Build/imu_to_dxl.hex`. The 11,612-byte Flash image starting at `0x08000000`, decoded from the HEX,
has this SHA-256 (identical to the original BIN):

`69bdaea7224900addd6eb5bd28001e26e07073c129383d9c1ece380d2bfce19a`

The review of the original MAP gave `sample=0x20000064`, size 60 bytes; `tick=0x20000BE0`, size 4 bytes.
This layout only applies to the image above. The J-Link viewer in `tools/servo-web` takes the Flash baseline from the HEX and verifies it strictly;
it does not depend on a committed BIN/MAP and does not accept arbitrary recompiled output.
During development you can still generate an `.axf` for breakpoint debugging and check symbols with a local `.map`; after changing the firmware, re-review the read layout and checksum.

## Desktop tests (2026-09-15)

| Test | Result | Coverage |
|---|---|---|
| Protocol C test | 106 checks, 0 failures | CRC, byte stuffing, corrupted packets, reply order, read-only fields, timeout/wraparound, boundary/noise recovery |
| IMU C simulation test | 16 scenarios passed | Identity error, missing part, configuration readback failure, FIFO, floating-point boundaries, frozen data, automatic recovery, stale snapshot |
| Register C test | 14 checks passed | Little-endian, signed boundaries, diagnostic mapping, out of range, read-only protection, limited commands |
| Python capture tool test | 4 checks passed | Known Ping frame, stuffing, diagnostic decoding, invalid attitude |

The host tests can be repeated with `Tools/test.ps1`; you need your own MSVC and Python. The SPI/FIFO tests use simulated registers and time and do not represent electrical acceptance of the bus and sensor.

After the release cleanup on 2026-09-21, the four test groups above were rerun with an explicitly passed MSVC environment; the results were still all passing: 106 protocol checks, 16 IMU scenarios, 14 register checks and 4 Python tests. The PowerShell/Python script syntax and the error message when the compiler is missing were also checked; the firmware was not recompiled and no hardware was connected. The HEX checksum matches the original shared package.

On the same day, after moving to `hardware/imu_to_dxl/firmware/` following the PR #32 review, `Tools/test.ps1` was run again from the new path,
and all four test groups above passed; the syntax of the two PowerShell scripts and the relative paths of the two Keil projects were checked and passed.
The move did not change Core, Drivers, Startup, tests, build tools or the HEX; nothing was recompiled and no real board was connected.

## Merged into the serial debug console (2026-09-21)

- After moving the firmware to this directory, `Tools/test.ps1` was rerun: 106 protocol checks, 16 IMU scenarios, 14 register checks and 4 Python tests all passed; the firmware was not recompiled or flashed.
- `tools/servo-web/selftest.py`: all passed; the existing protocol-level servo simulation tests are kept.
- `python -m pytest test_imu_bridge.py test_imu_server.py`: 45 tests and 59 sub-scenarios passed, including HEX parsing/verification, RAM and probe protection, sending servo and IMU data over the same WebSocket, IMU not enabled, lifecycle and unified logging.
- `node --test test_imu_attitude.cjs`: 13 tests passed, covering the default Y+90° mounting orientation, quaternion zeroing/raw attitude, stale data and disconnection.
- The same model was verified in the browser with `--fake --imu-demo`: simulated joint 30 was moved from 2048 to 2300, and when it read back 2297 the IMU torso attitude was still updating continuously; mounting orientation, raw attitude, zeroing and IMU category logging all worked. After stopping the server, it showed a disconnect and froze the attitude; after restarting without the IMU parameters, the panel was hidden and the original debug console showed 15/15 simulated servos online. No real servos or real board were used.
- The J-Link DLL calls, SWD speed and sensor sample decoding reuse the earlier implementation; under the new path, the Flash is decoded from the single HEX, the fixed hash binds the RAM layout from the original MAP review, and after connecting the real board's Flash is still compared.
- The above are hardware-free regression checks; running real servos and a real IMU together, the on-site mounting axes and full-robot balance have not been verified yet.

## Original development board validation (2026-09-20)

- J-Link 100kHz SWD connection, firmware flashing and readback verification passed; Keil can stop at `main`.
- The 64MHz system clock and IMU sampling were verified; WHO_AM_I=`0x70`, ready=1, SPI/FIFO error counts were 0.
- The browser can read the real attitude through J-Link, refreshing at about 20Hz. The reference voltage is about 3.29V; this is not a measurement of input current, ripple or temperature rise.
- It was observed that connecting with J-Link 9.78 restarts the program on the board; zeroing in the web page only changes the display reference and does not write calibration parameters.

The results above apply only to the original development board; other boards still need their own wiring and first power-up checks.

## Acceptance checks not yet completed

- The external single-wire half-duplex bus and servos have not been tested on real hardware: USART baud rate error, DE release timing, levels, noise immunity on the shared bus and worst-case reply latency all need on-site verification.
- 0.2.0 implements the 15-byte Feetech protocol contract at address 56, and the `tools/imu200` acceptance check passes on the simulated bus; on the real board you still need to run `imu200.py check --port`, and first measure the Feetech servos' own T_resp (bus protocol §5).
- Mounting coordinates, temperature drift, long-term SFLP convergence, stack high-water mark, watchdog recovery and long-term stability still need dedicated tests.
- Before real motion, the main controller must read the diagnostic status and handle stale data; the board returning an all-zero attitude does not mean the full robot already has automatic stopping capability.

No claim is made that full-robot standing, motion or the Feetech real-bus acceptance check has been completed.
