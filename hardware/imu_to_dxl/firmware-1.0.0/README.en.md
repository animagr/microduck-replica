# imu_to_dxl Firmware 1.0.0 (FT-SCS)

**English** · [简体中文](README.md)

> This version was branched off from 0.1.0 (Dynamixel 2.0) and converted to the Feetech protocol. It is a separate implementation from 0.2.0 in [`../firmware/`](../firmware/) next to it: the 15-byte block and model number 0x4D44 are the same, but the diagnostic area differs (90..185 in this version, 124..247 in 0.2.0). To use it on Microduck, the main program must be fork 4734cbb or later (replica image 20261021b or later), which places this board after the servos. For how to choose between the two versions, see [`../README.md`](../README.en.md).

Firmware for the **STM32G031F8P6 + LSM6DSV16X** IMU board used on Microduck. Hardware baseline
`fanhao375/microduck-replica` @ `a1f4979c` (including J4/J5, RX_EN).

The firmware speaks the **Feetech FT-SCS protocol** (migrated from Dynamixel 2.0): the IMU board is fixed at **ID=200, 1Mbps, 8N1**,
shares the same single-wire half-duplex bus with Feetech SCS/STS servos, and one SYNC READ reads the IMU and all servos at the same time.
The data content matches the duck-control contract of GitHub `pollen-robotics/microduck`
(gyroscope i16×3 + SFLP fp16 quaternion x/y/z, w recovered by the host, 50Hz).

Data flow: LSM6DSV16X → SPI1 → STM32 → USART2 + external buffer → single-wire half-duplex bus → main controller.
Bare metal, no RTOS, no dynamic memory, no HAL; ID/baud rate are fixed, and no Option Bytes / Flash configuration is written.

## Quick start

```powershell
# 1) Build the firmware (equivalent to Ctrl+Shift+B)
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 `
  -ToolchainRoot 'C:\Keil_v5\ARM\ARMCLANG'

# 2) Flash (always use OpenOCD; the UV4 command line reports false success)
& 'openocd.exe' -f interface/cmsis-dap.cfg `   # replace with the OpenOCD path on your computer
  -f target/stm32g0x.cfg -c 'adapter speed 4000' `
  -c 'program Build/imu_to_dxl.hex verify reset exit'

# 3) Install the host-side dependencies and use the tools (COM6 = half-duplex bus adapter)
python -m pip install -r Tools\requirements.txt
python Tools\servo_tool.py scan --port COM6       # scan IMU(200)+servos
python Tools\bus_monitor.py --port COM6 --no-demo # combined IMU+servo monitor (no motion)
python Tools\imu_monitor.py --port COM6 --plot    # IMU 50Hz plot
python Tools\imu_probe.py --port COM6 --seconds 30 # read-only acceptance check (exit code 0 = pass)
```

**The only hard bus rule**: in the host's SYNC READ ID list, 200 must come after the servos (last/middle position);
it must not be first, and it may also form a group of its own. See section 6 of the [user guide](docs/user-guide.en.md) for details.

## Document index

| Document | Contents |
|---|---|
| [docs/使用说明.md](docs/user-guide.en.md) | Wiring (J1/J2/J4/J5/J3), environment, building and flashing, full usage of the four Python tools, first board bring-up procedure, troubleshooting table, hardware-free tests |
| [docs/实现原理.md](docs/how-it-works.en.md) | FT-SCS frame state machine and checksum, register/diagnostic mapping, SYNC READ slot collision-avoidance state machine, half-duplex DE timing, 50Hz time budget, IMU sampling chain and host contract |
| [VALIDATION.md](VALIDATION.en.md) | Host test and real-hardware acceptance records |
| [DEPENDENCIES.md](DEPENDENCIES.en.md) | Third-party source/toolchain versions and licenses |

## Directory structure

```
Core/Inc, Core/Src   firmware source (board / imu / protocol / control_table / main)
Drivers/             pinned CMSIS and ST LSM6DSV16X drivers (with licenses)
MDK-ARM/             Keil project (DAP only: imu_to_dxl_dap.uvprojx + linker script)
Tools/               build.ps1, test.ps1 and 4 Python tools
Tests/               hardware-free C/Python tests (protocol 93 checks, control_table 18, imu 16 scenarios, probe 9)
Build/               build artifacts (git-ignored; hex/bin/axf/map)
.vscode/             VS Code build tasks
```

## Key facts at a glance

- Frame: `FF FF ID LEN INST P... CK`; `LEN=number of parameters+2`, total length `4+LEN`; checksum `~(ID+LEN+INST+ΣP)&0xFF`.
- Instructions: PING(0x01) / READ(0x02) / WRITE(0x03) / SYNC READ(0x82) / SYNC WRITE(0x83);
  broadcast PING is silent; no response delay.
- Fast block at address 56 (same address as the servo status block): 56..61 gyro i16×3 (±500dps, 17.5mdps/LSB),
  62..67 qx/qy/qz fp16; 68..73 acceleration; 75 flags; 76 WHO_AM_I=0x70;
  84 user_marker read/write; 90..185 diagnostic block 24×u32; writing 240=0xA5 reinitializes the IMU.
- Sampling: IMU 120Hz (FIFO+SFLP), host 50Hz; when not ready, gyro/quat return all zeros,
  and the host must combine ready/sample count/age to handle invalid data.
- Local ports: COM6 half-duplex bus 1Mbps; COM5 DAP-Link log 115200 (DTR/RTS must be asserted).

## References

- [This board's hardware](https://github.com/fanhao375/microduck-replica/tree/a1f4979c425bd9228622be89f2bfa4d1de7fbde3/hardware/imu_to_dxl)
- [STM32G031 datasheet](https://www.st.com/resource/en/datasheet/stm32g031f8.pdf)
- [LSM6DSV16X datasheet](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [Upstream main controller interface duck-control](https://github.com/pollen-robotics/microduck/blob/5984efb770855432b03dafd3d879e9929981e45b/duck-control/src/bus.rs)
- [Feetech FT-SCS protocol](https://www.feetechrc.com/)

Newly written code is provided under the MIT license; third-party files keep their own copyrights and licenses (see the Drivers directory).
