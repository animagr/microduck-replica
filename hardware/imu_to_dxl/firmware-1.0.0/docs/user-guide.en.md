# User Guide

**English** · [简体中文](使用说明.md)

Host-side operating manual for the Feetech FT-SCS bus firmware of the Microduck IMU board (STM32G031F8P6 + LSM6DSV16X).
The IMU board is fixed at **ID=200, 1Mbps**, shares the bus with Feetech SCS/STS servos, and is read together with them in a single SYNC READ.

---

## 1. System components and wiring

### 1.1 Bus topology

```
   USB half-duplex adapter (COM6)
        │ single-wire DATA + VDD_BUS + GND
        ├── J1/J2 or J4/J5 ── IMU board (ID=200)
        ├── Feetech servo (ID=2)
        └── Feetech servo (ID=3) ...
```

- The bus is **single-wire half-duplex**: all devices (IMU board + servos) hang on the same DATA line, 1Mbps, 8N1.
- The bus supply VDD_BUS powers the servos (measured 8.0V here); the IMU board itself powers up according to its own hardware power scheme.
- **Only one host** may send instructions at any time. Close Feetech FD.exe and any other bus software before running the tools.

### 1.1.1 J1/J2/J4/J5 bus connectors

| Connector | Pins |
|---|---|
| J1/J2 | 1=GND, 2=VDD_BUS, 3=DATA |
| J4/J5 | 1=DATA, 2=VDD_BUS, 3=GND |

You must connect a **single-wire half-duplex USB adapter** here; an ordinary USB-TTL serial adapter cannot drive the single-wire bus directly.

### 1.2 J3 debug log port (DAP-Link or USB-TTL)

| J3 pin | Signal | Connection |
|---|---|---|
| 1 | GND | Common ground |
| 2 | SWDCLK | Debugger SWCLK (flashing only) |
| 3 | SWDIO | Debugger SWDIO (flashing only) |
| 4 | UART_RX | USB-TTL TX, 3.3V (115200 log) |
| 5 | UART_TX | USB-TTL RX, 3.3V (115200 log) |
| 6 | 3.3V | Debugger voltage reference; **do not connect 5V** |

- Log serial port 115200, 8N1; at boot it should print:
  `imu_to_dxl 1.0.0 | STM32G031F8 | FT-SCS ID=200 1000000 8N1`
- After that it prints one status line per second: `ready=1 id=0x70 ... gyro=... q16=... ck=0`.
- **The DAP-Link CDC serial port only delivers data with DTR+RTS asserted** (tick both of these hardware handshake options in your serial terminal).
- The J3 log port **does not respond** to any bus protocol instruction; protocol operations must go through the COM6 bus adapter.

### 1.3 Local ports (Windows)

| Port | Purpose | Parameters |
|---|---|---|
| COM6 | Half-duplex bus adapter (protocol operations) | 1000000 8N1 |
| COM5 | DAP-Link CDC log port | 115200 8N1, needs DTR/RTS |

Use the port numbers that Device Manager actually enumerates; specify them in the tools with `--port`.

---

## 2. Software environment

### 2.1 Python host-side tools

Requires Python 3.8+ (verified here with 3.8.10 32-bit) and pyserial; `--plot` additionally requires matplotlib.

```powershell
python -m pip install -r Tools\requirements.txt
```

Any Python 3.8 or later works (check with `python --version`)
(make sure not to use the Windows Store `python.exe` placeholder).

### 2.2 Firmware build (only needed when modifying the firmware)

- Keil MDK (here C:\Keil_v5, Arm Compiler 6), or use the build script directly.
- The host C tests use gcc (WinLibs `mingw64\bin\gcc.exe`; add that directory to PATH when using it).

---

## 3. Firmware build and flashing

### 3.1 Build

Press **Ctrl+Shift+B** in VS Code, or:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 `
  -ToolchainRoot 'C:\Keil_v5\ARM\ARMCLANG'
```

On success the artifacts are in `Build/`: `imu_to_dxl.hex` (for flashing), `.bin`, `.axf` (for debugging), `.map`.
The current firmware uses about 10.9 KB Flash / 5 KB RAM.

### 3.2 Flashing (important: use OpenOCD, not the UV4 command line)

**Flashing from the UV4 command line reports "false success"**: exit code 0 and an empty log, but the chip is not actually erased/written (you can tell because the uptime in the log
does not reset). Use OpenOCD (DAP-Link/CMSIS-DAP):

```powershell
& 'openocd.exe' `   # replace with the OpenOCD path on your computer
  -f interface/cmsis-dap.cfg `
  -f target/stm32g0x.cfg `
  -c 'adapter speed 4000' `
  -c 'program Build/imu_to_dxl.hex verify reset exit'
```

Note: the target configuration file is named **stm32g0x.cfg** (not stm32g0x0.cfg).
Close Keil µVision before flashing (it holds the DAP-Link HID exclusively). If the SWD contact is poor, just reseat the Dupont wires.

### 3.3 Verification after flashing

1. The COM5 log shows the `FT-SCS ID=200` boot banner and `ready=1 ... ck=0`.
2. Run a scan (see 4.1); you should see IDs 2 and 3 (servos) and ID 200 (IMU board).

---

## 4. Host-side tools

All four tools are in the `Tools/` directory and all use `--port COM6`, 1Mbps.

### 4.1 servo_tool.py: servo/bus scan tool

```powershell
# Scan 1..253 and list all responding devices (servos + IMU board)
python Tools\servo_tool.py scan --port COM6

# Watch a single servo's status block (position/speed/load/voltage/temperature)
python Tools\servo_tool.py read 2 --port COM6 --watch

# Single-servo back-and-forth test (it moves! default 1024<->3072, 3 round trips, torque turned off automatically at the end)
python Tools\servo_tool.py test 2 --port COM6

# Raw register write (advanced; writes of ID/baud rate to the IMU board are ignored by the firmware)
python Tools\servo_tool.py write 200 84 90 --port COM6
```

In the scan output, ID 200 showing `model=0x4d44 fw=1` is the IMU board; the rest are servos.

### 4.2 imu_probe.py: read-only IMU acceptance probe

The strictest acceptance tool: PING → read identity → periodically read the 40-byte data block starting at 56 + the 96-byte diagnostic block starting at 90,
outputting JSON and optionally saving CSV. **It only ever sends read instructions and will not drive any servo.**

```powershell
# Sample for 30 seconds at 50Hz and save CSV
python Tools\imu_probe.py --port COM6 --seconds 30 --csv Build\imu.csv

# Additionally fetch the fast block via the "single-ID broadcast SYNC READ" path (verifies 0x82)
python Tools\imu_probe.py --port COM6 --seconds 30 --sync

# Custom sample rate (1~100Hz)
python Tools\imu_probe.py --port COM6 --seconds 10 --hz 100
```

Exit code 0 means no communication errors and all samples had ready=1; a non-zero code means you need to check wiring/power/baud rate.
Output fields include gyro_*_dps, q_x/q_y/q_z/q_w, ready, who_am_i (=112=0x70),
sample_count and all 23 diagnostic counters.

### 4.3 imu_monitor.py: real-time IMU monitor

At a fixed rate (default 50Hz) it sends a broadcast SYNC READ to ID 200 alone, reading the 12-byte fast block at address 56,
refreshes the gyroscope and quaternion in the terminal in real time, and can optionally plot with matplotlib or record CSV.

```powershell
python Tools\imu_monitor.py --port COM6                 # default 50Hz, terminal refresh
python Tools\imu_monitor.py --port COM6 --seconds 10    # exit after running 10 seconds
python Tools\imu_monitor.py --port COM6 --plot          # real-time plot window
python Tools\imu_monitor.py --port COM6 --csv imu.csv   # record valid samples
python Tools\imu_monitor.py --port COM6 --rate 100      # change sample rate
```

At the end it prints `ok/ck_err/timeout/hw_err` statistics; a healthy state should show ck=0 and timeout=0.

### 4.4 bus_monitor.py: combined IMU + multi-servo monitor (main tool)

**One broadcast SYNC READ (address 56, 12 bytes) reads the IMU and all servos at the same time**; the ID list is automatically ordered as
`[servo IDs..., 200]` (the IMU must be last, see section 6). By default it also moves the servos gently back and forth as a demo,
and on exit it automatically turns off all torque it enabled.

```powershell
# Scan the bus + dashboard + demo swing (default 1536<->2560, period 3s)
python Tools\bus_monitor.py --port COM6

# Monitor only, no swing (safe observation mode, recommended for first use)
python Tools\bus_monitor.py --port COM6 --no-demo

# Real-time plot (IMU gyroscope/quaternion)
python Tools\bus_monitor.py --port COM6 --plot

# Fixed run time
python Tools\bus_monitor.py --port COM6 --seconds 20

# Poll only the specified servos; --srv-id 0 means only the IMU is on the bus
python Tools\bus_monitor.py --port COM6 --srv-id 2,3 --no-demo
python Tools\bus_monitor.py --port COM6 --srv-id 0

# Adjust demo swing amplitude/speed/period
python Tools\bus_monitor.py --port COM6 --demo-lo 1024 --demo-hi 3072 `
  --demo-speed 300 --demo-period 2
```

Each device line in the terminal shows:

- **IMU**: three-axis gyroscope (dps), quaternion x/y/z/w, success/request counts.
- **Servo**: raw position (0~4095), angle (0~360°), speed, load, voltage (0.1V), temperature, moving flag.

Demo mechanism:
- At startup it writes to each servo individually: torque enable (40)=1, acceleration (41)=30, target speed (46), initial target position (42).
- After that, each period it sends the target positions to all servos with **one broadcast SYNC WRITE (0x83, address 42, 2 bytes)**.
- If a servo does not react to SYNC WRITE (does not move toward the new target), it automatically falls back to individual WRITEs for that servo and shows a notice in the terminal.
- On exit with Ctrl+C or when `--seconds` ends, it automatically writes torque=0 to all servos it enabled.

> **Safety note**: without `--no-demo` the servos really move. For first use, run without load on a current-limited power supply,
> and make sure nothing interferes within the servo horn's range of motion.

---

## 5. First board bring-up checklist

1. Check the hardware version and power supply; first **power the single board with current limiting**, and check 3.3V, no shorts, no heating.
2. Flash the hex over SWD with OpenOCD (section 3.2); confirm verify OK and that it starts after reset.
3. Connect the J3 log (COM5, 115200, DTR+RTS): you should see the boot banner, `ready=1`, WHO_AM_I=`0x70`.
   - Log commands: `s` print status immediately, `l` toggle the periodic log, `r` request IMU reinitialization, `?` help.
4. Rotate/tilt the board and watch the gyro and q16 data change with the attitude.
5. Connect only the IMU board to the bus and run `imu_probe.py`: exit code 0, ck/uart/spi/fifo errors do not increase.
6. Connect one Feetech servo, then run `servo_tool.py scan` and `bus_monitor.py --no-demo`,
   and confirm that reading the IMU+servo in the same frame is stable (success rate should be close to 100%).
7. After confirming without load that the servo horn has no interference, use `bus_monitor.py` (demo) to do the combined swing while the robot is supported.

---

## 6. Hard rule for SYNC READ ID order

**In the host's SYNC READ ID list, ID 200 (IMU) must not be first; it must come after all servos
(middle or last), or form a group of its own.**

- Measured (Feetech servo firmware 3.46, 1Mbps, 30 rounds × several orderings):
  - `[200,2,3]` (IMU first): only 3/30 succeeded;
  - `[2,200,3]` (middle): 30/30; `[2,3,200]` (last): 30/30; `[200]` (alone): 30/30.
- Cause: the Feetech servo firmware "predicts" its own time slot and starts transmitting early, about 180µs after the start of the preceding device's response;
  when the IMU is first, this transmission from the servo collides exactly with the checksum byte at the end of the IMU's response frame.
- The tools in this project already follow this automatically: `bus_monitor.py` always uses `[servo IDs..., 200]`;
  `imu_monitor.py` lists only `[200]`. **Any host you write yourself (including the port on the RK3566 side) must use this ordering.**

---

## 7. Troubleshooting

| Symptom | What to check |
|---|---|
| scan sees no devices at all | Whether the port is the bus adapter (COM6) rather than the log port; half-duplex direction; VDD_BUS/GND; 1Mbps; whether other bus software is holding the port |
| Only the servos / only the IMU are visible | Power; loose wiring; baud rate; whether the IMU board has been flashed with the Feetech firmware (the old DXL2 firmware does not respond to Feetech frames) |
| Dropped frames or checksum errors in combined reads | Whether 200 was placed first in the SYNC READ list (it must be last/middle); whether the leads are too long; add a termination resistor |
| COM5 opens but no log is received | DAP-Link CDC needs DTR+RTS asserted; baud rate 115200; whether J3.4/3.5 TX/RX are swapped |
| Tool reports no response | Only one host is allowed on the bus; close FD.exe/other scripts; power-cycle |
| OpenOCD reports cannot read IDR | Close Keil µVision (it holds DAP-Link exclusively); reseat the SWD Dupont wires; reduce the speed to 100kHz |
| Behavior unchanged after flashing with UV4 | False success from the UV4 command line; use OpenOCD instead (section 3.2) |
| Servos do not move during the demo | Check whether the terminal shows "回退到逐写" (falling back to per-servo writes); check the mode/torque/speed registers; run `servo_tool.py test` first |
| Servo keeps holding torque after exit | A normal exit (Ctrl+C) turns torque off automatically; after an abnormal power loss, turn it off manually with `servo_tool.py write <id> 40 0` |

---

## 8. Automated tests (no hardware)

```powershell
# Put gcc on the path first (for the C tests)
$env:Path = '<WinLibs directory>\mingw64\bin;' + $env:Path
python Tools\test.ps1
```

Coverage: Feetech protocol C tests (93 checks: framing/checksum/ordered responses/timeout recovery), IMU simulation tests (16 scenarios),
register mapping tests (18 checks), Python probe offline tests (9 checks). These tests do not require connected hardware.
