# Firmware Validation Records

**English** · [简体中文](VALIDATION.md)

Subject: **imu_to_dxl 1.0.0 (Feetech FT-SCS version) / STM32G031F8P6 + LSM6DSV16X**.
Validation date: 2026-09. Includes host tests, actual compilation and flashing, and shared-bus tests on real hardware.
This version has fully migrated from Dynamixel 2.0 to Feetech FT-SCS; the records of the old version no longer apply.

## 1. Compilation

| Item | Result |
|---|---|
| ArmClang (Keil MDK, C:\Keil_v5) CLI build `Tools/build.ps1` | Success, 0 errors |
| Keil project | Only the DAP project `MDK-ARM/imu_to_dxl_dap.uvprojx` is kept |
| Flash (Code + RO + RW) | **10,920 / 65,536 bytes** (10.66 KB) |
| RAM (RW + ZI, including 2 KiB stack) | **5,092 / 8,192 bytes** (4.97 KB) |
| Build artifacts | `Build/imu_to_dxl.hex/.bin/.axf/.map` + `imu_to_dxl.build.json` (with SHA256) |
| Flashing | OpenOCD + CMSIS-DAP, `program ... verify reset exit`, verify OK |

Note: flashing from the UV4 command line reports false success (exit code 0 but nothing actually erased/written); OpenOCD is the authoritative way to flash.

## 2. Hardware-free host tests

`Tools/test.ps1` (gcc, WinLibs mingw64) was actually run and passed:

| Test | Result | Main coverage |
|---|---|---|
| `Tests/protocol_test.c` | **93 checks, 0 failures** (proto_context 1104 bytes) | Feetech framing/checksum vectors (PING, READ 56/12), PING/READ/WRITE, silent broadcast PING, SYNC READ first slot answers immediately, non-first slot answers after sniffing the preceding slot's valid frame, 25ms timeout skip when the preceding slot is missing, new host frame invalidates, malformed/byte-timeout recovery, LEN boundaries and noise resync, read-only area protection |
| `Tests/control_table_test.c` | **18 passed** | Little-endian encoding, gyro/fp16/acceleration packing, flags/whoami, 24-word diagnostic block mapping, out of range, 0..9 read-only, 84 marker, 240=0xA5 |
| `Tests/imu_test.c` | **16 scenarios passed** | WHO_AM_I error, configuration readback failure, FIFO/SFLP, fp16 boundaries (negative-zero sentinel), frozen data judged stale, automatic recovery, snapshot expiry without poll |
| `Tests/probe_test.py` | **9/9 passed** | Probe frame construction, 56/40 + 90/96 block decoding, 24 diagnostic field names, invalid attitude handling |

## 3. Real-hardware communication tests

Setup: half-duplex adapter COM6 (1Mbps); IMU ID=200; Feetech servos ID 2, 3 (firmware 3.46, 8.0V).

| Tool / scenario | Result |
|---|---|
| `imu_probe.py` unicast polling (56/40 + 90/96 diagnostic block) | **249/250** (a single transient timeout, 0.4%), exit code 0 |
| `imu_probe.py --sync` (single-ID broadcast SYNC READ) | Normal, all ready=1 |
| `imu_monitor.py` 50Hz SYNC READ 56/12 (list [200]) | **251/251, zero checksum errors, zero timeouts** |
| `bus_monitor.py --no-demo` (one SYNC READ reads [2,3,200]) | **598/598 = 100%** |
| `bus_monitor.py` demo (SYNC READ + broadcast SYNC WRITE target position) | **741/741 = 100%, no per-write fallback** |
| `servo_tool.py scan/read/test/write` | Servos and ID200 identified correctly (model=0x4D44, fw=1) |
| Automatic torque off on exit | Normal (writes 40=0 to the servos enabled by the demo) |

## 4. SYNC READ slot order measurements (key conclusion)

30 rounds × several ID orderings (Feetech servo firmware 3.46, 1Mbps):

| SYNC READ list | IMU responses | Conclusion |
|---|---|---|
| `[200,2,3]` (IMU first) | **3/30** | The servo transmits at a predicted +180µs after the start of the preceding frame and collides with the IMU checksum byte |
| `[2,200,3]` (middle) | 30/30 | Answers after sniffing ID2's valid frame |
| `[2,3,200]` (last) | 30/30 | Answers after sniffing ID3's valid frame |
| `[200]` (alone) | 30/30 | No collision |

The conclusion is fixed as a hard rule: **the host must place 200 after the servos or in a group of its own, never first.**
The 50Hz period is 20ms, and the three-device bus occupancy is about 650µs (request ~110µs + ~180µs per response), i.e. 3.3% of the cycle;
the bottleneck is electrical collision, not the time budget.

## 5. Board-level observations

- Boot log banner `imu_to_dxl 1.0.0 | STM32G031F8 | FT-SCS ID=200 1000000 8N1`;
  periodic status line `ready=1 id=0x70 ... ck=0`; gyro/quaternion change as the board is rotated by hand.
- The DAP-Link CDC log (COM5, 115200) only produces output with DTR+RTS asserted.
- During long stable runs, the spi/fifo/uart/checksum and other diagnostic counters do not increase (see diagnostic block 90..185 for details).

## 6. Test limits

The host C tests use simulated registers/time stubs and are not equivalent to measurements on the chip; the real-hardware communication tests covered
shared-bus slot ordering, reads/writes and the demo interaction, but did not cover: long (hours-long) continuous operation, extreme temperature/voltage,
attitude integration under full-robot load, SFLP bias and temperature drift. Before formal motion integration, you should still run the full acceptance check per section 5 of the user guide,
and have the main controller combine ready/sample count/age to implement a fail-safe stop.
