# Firmware dependencies and build tools

**English** · [简体中文](DEPENDENCIES.md)

The chip and sensor driver sources needed for compilation are stored in this directory. The drivers do not need to be downloaded at build time; Keil, Arm Compiler, the device support pack and the debugger tools must be installed legitimately by the user. Temporary build output goes to the project's `Build` directory.

| Component | Pinned source | License and local changes |
| --- | --- | --- |
| CMSIS Core 6.2.0 | [ARM-software/CMSIS_6 v6.2.0](https://github.com/ARM-software/CMSIS_6/tree/v6.2.0) | Apache-2.0; only the headers needed for Cortex-M0+ and Arm Compiler 6 are included, unmodified; license at `Drivers/CMSIS/LICENSE` |
| STM32G0 CMSIS Device v1.4.5 | [STMicroelectronics/cmsis-device-g0](https://github.com/STMicroelectronics/cmsis-device-g0/tree/f576c24e123edf3332988ecd49512c0f35f85186), commit `f576c24e123edf3332988ecd49512c0f35f85186` | Apache-2.0; device headers and system source files unmodified; license at `Drivers/CMSIS/Device/ST/STM32G0xx/LICENSE.md` |
| STM32G031 startup code | `Source/Templates/arm/startup_stm32g031xx.s` from the same ST commit | Stack changed from 1024 to 2048 bytes; heap changed from 512 to 0 bytes. The vector table, Reset_Handler and weak IRQ names keep the ST implementation |
| LSM6DSV16X PID driver | [STMicroelectronics/lsm6dsv16x-pid](https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07), commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07` | ST BSD-3-Clause; the license, original driver files and source record are in `Drivers/LSM6DSV16X/` |
| Keil device support pack | Verified version `Keil.STM32G0xx_DFP.2.1.0` | Provides the device description, SVD and `CMSIS/Flash/STM32G0xx_64.FLM`; this project includes the official CMSIS startup file separately, so RTE does not add it twice |
| Arm Compiler for Embedded | Verified versions 6.24 (0.1.0) and 6.22 (0.2.0, Keil MDK 5.41); ≥ 6.10 is needed to compile CMSIS 6 | Requires a valid tool license; uses Arm Compiler 6, legacy-syntax armasm and MicroLIB, and only suppresses the legacy assembler deprecation notice A1950W |

## Build entry points

You can edit the source in VS Code and run the following in a PowerShell terminal in the firmware directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 -ToolchainRoot 'E:\Keil_v5\ARM\ARMCLANG'
```

Replace the example path with your own Arm Compiler installation directory. The repo does not ship a VS Code task configuration.
A build replaces the firmware in `Build`; if you only use the attitude web page, keep the `Build/imu_to_dxl.hex` shipped with the project, and there is no need to recompile.
The repo keeps only this one prebuilt HEX; `.bin/.map/.axf`, build logs and test output all stay local and are excluded by `.gitignore`.

Keil can open `MDK-ARM/imu_to_dxl_jlink.uvprojx` (J-Link) or `imu_to_dxl.uvprojx` (ST-LINK). On first use, check your own compiler, device pack, probe and flash algorithm. The J-Link script sets the SWD speed to the verified 100kHz. The build outputs `.axf/.hex/.bin/.map`; the CLI script additionally generates a build log and a SHA-256 manifest of the outputs.

Both entry points use Cortex-M0+, C11, `-Oz`, software floating point, short enums, MicroLIB, `STM32G031xx` and `HSE_VALUE=16000000`.
Link layout: Flash `0x08000000..0x0800FFFF`, data RAM `0x20000000..0x200017FF`, the last 2KiB `0x20001800..0x20001FFF` is the stack, initial SP `0x20002000`. Changing the stack size requires changing both the startup file and the scatter file.

The SWD / J-Link viewer in `tools/servo-web` decodes the 10,724-byte image (0.2.0) from the HEX and uses SHA-256
`66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e`
to bind the verified `sample=0x2000006C` (60 bytes) and `tick=0x20000A34` (4 bytes), without relying on a MAP file committed to the repo.
After recompiling, recheck the symbols and sizes with your local MAP file, and review the new image hash before updating the viewer.

## Host tests and file integrity

The host C tests need MSVC; first launch the **x64 Native Tools Command Prompt / Developer PowerShell**, then run `Tools/test.ps1 -PythonExe '自己的Python路径'` (replace with your own Python path). The test entry point installs no software and does not connect to hardware.

`Drivers/CMSIS/dependency-hashes.json` records the SHA-256 of the included driver files; the ST source commit metadata is in `Drivers/CMSIS/Device/ST/STM32G0xx/source-commit.json`. The scope of build and real-board validation is described in [VALIDATION.md](VALIDATION.md).
