# Firmware Dependencies and Build Tools

**English** · [简体中文](DEPENDENCIES.md)

This project keeps the chip and sensor driver source code needed for compilation inside the project directory. Day-to-day builds do not require downloading STM32CubeMX or HAL again, or fetching drivers over the network.

| Component | Pinned source | License and local changes |
| --- | --- | --- |
| CMSIS Core 6.2.0 | Installed `C:\Keil_v5\ARM\PACK\ARM\CMSIS\6.2.0`, corresponding to [ARM-software/CMSIS_6 v6.2.0](https://github.com/ARM-software/CMSIS_6/tree/v6.2.0) | Apache-2.0; only the headers needed for Cortex-M0+ and Arm Compiler 6 are copied, unmodified; license `Drivers/CMSIS/LICENSE` |
| STM32G0 CMSIS Device v1.4.5 | [STMicroelectronics/cmsis-device-g0](https://github.com/STMicroelectronics/cmsis-device-g0/tree/f576c24e123edf3332988ecd49512c0f35f85186), commit `f576c24e123edf3332988ecd49512c0f35f85186`, 2026-03-05 | Apache-2.0; device headers and system source files unmodified; license `Drivers/CMSIS/Device/ST/STM32G0xx/LICENSE.md` |
| STM32G031 startup code | `Source/Templates/arm/startup_stm32g031xx.s` from the same ST commit | Stack changed from 1024 to 2048 bytes; heap changed from 512 to 0 bytes, no dynamic memory is used. The vector table, Reset_Handler and weak IRQ names all keep the ST implementation |
| LSM6DSV16X PID driver | [STMicroelectronics/lsm6dsv16x-pid](https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07), commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07` | ST BSD-3-Clause; `Drivers/LSM6DSV16X/LICENSE`; the original driver files and the source record are kept in the same directory |
| Keil device family pack | Local `Keil.STM32G0xx_DFP.2.1.0` | Provides the device description, SVD and the `CMSIS/Flash/STM32G0xx_64.FLM` flash algorithm. This version no longer includes Device:Startup/HAL, so this project carries the official CMSIS startup file itself, avoiding duplicate additions by RTE |
| Arm Compiler for Embedded 6.24 | `C:\Keil_v5\ARM\ARMCLANG` | Local `Keil MDK STMicroelectronics Edition - Cortex-M0/M0+/M23` license. The project uses Arm Compiler 6, legacy-syntax armasm and MicroLIB; only the legacy assembler deprecation notice A1950W is suppressed, not code warnings |

## Build entry points

After opening the firmware directory, run in PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 `
  -ToolchainRoot 'C:\Keil_v5\ARM\ARMCLANG'
```

Or press `Ctrl+Shift+B` in VS Code. If the tools are installed elsewhere, pass `-ToolchainRoot '<install directory>\ARMCLANG'`.

In Keil, open `MDK-ARM/imu_to_dxl_dap.uvprojx` directly (the repo keeps only this one DAP project); Build outputs `Build/imu_to_dxl.axf`, `.hex`, `.bin` and `.map`. Both entry points use Cortex-M0+, C11, `-Oz`, software floating point, short enums, MicroLIB, `STM32G031xx` and `HSE_VALUE=16000000`. The build script additionally produces a detailed log and a SHA-256 manifest of the artifacts (`Build/imu_to_dxl.build.json`).

The linker file restricts Flash to `0x08000000..0x0800FFFF` and data RAM to `0x20000000..0x200017FF`; the last 2 KiB, `0x20001800..0x20001FFF`, are reserved for the stack, and the initial SP is `0x20002000`. If you change the stack size, you must change both the startup file and the scatter file.

The Keil project is configured for CMSIS-DAP (DAP-Link), SWD and the STM32G0 64 KiB Flash algorithm. **For command-line flashing, use OpenOCD** (`interface/cmsis-dap.cfg` + `target/stm32g0x.cfg`, 4MHz); the UV4 command line has a false-success problem where it "exits with code 0 but does not actually erase/write". Flashing on real hardware and shared-bus communication have been verified; see `VALIDATION.md` for the records.

The hardware-free host tests compile the C test cases with gcc (WinLibs `mingw64`, installed anywhere, MinGW-w64); the host-side tools depend on Python 3.8+ and pyserial (the plotting feature additionally needs matplotlib), listed in `Tools/requirements.txt`.

When the local Codex sandbox runs under a different user identity, the Arm license check reports "assigned to another user"; under the actual user identity the license check succeeds. This difference does not require regular users to change an already activated license, and it involves no cracking or replacement of tools.

## File integrity

`Drivers/CMSIS/dependency-hashes.json` records the SHA-256 of the CMSIS, startup code and sensor driver files currently included, so changes can be identified during future upgrades. The ST source commit metadata is in `Drivers/CMSIS/Device/ST/STM32G0xx/source-commit.json`.
