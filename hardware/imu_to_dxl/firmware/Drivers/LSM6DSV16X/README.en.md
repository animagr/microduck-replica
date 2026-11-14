# LSM6DSV16X official driver

**English** · [简体中文](README.md)

`lsm6dsv16x_reg.c`, `lsm6dsv16x_reg.h` and `LICENSE` are copied verbatim from the official STMicroelectronics repo, pinned to commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07`. The original download record is kept in `source.json`; the paths in that record are the source paths at download time, not build dependencies.

- Driver source: https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07
- SFLP configuration reference: https://github.com/STMicroelectronics/STMems_Standard_C_drivers/blob/master/lsm6dsv16x_STdC/examples/lsm6dsv16x_sensor_fusion.c

Board-level SPI is in `Core/Src/board.c`; sampling, FIFO parsing and the recovery state machine are in `Core/Src/imu.c`. The driver copyright and BSD-3-Clause license are unchanged.

This project uses an accelerometer range of ±4g and an angular rate range of ±500dps, with the accelerometer, gyro, FIFO and SFLP all at 120Hz. 120Hz is a standard rate supported by the device and gives the 50Hz main controller a fresher attitude; it is not the example's 30Hz carried over as-is. For the first real-board debugging, ST's default filter chain is kept, and no unmeasured extra software low-pass filter is added.

The gyro and quaternion records in the FIFO update their timestamps separately; the code does not assume the two records are always adjacent. Up to 16 records are taken per round, polled every 1ms. If any required record has not been updated for more than 100ms, ready is cleared, and the device is automatically reconfigured after 1s; at startup, the first batch of data is waited for at most 1.5s. Repeated data values while stationary are normal; data counts as frozen only when there are no new FIFO records. SPI faults, FIFO overflow, a wrong device ID and software reset timeouts can all be diagnosed and retried.

The quaternion keeps SFLP's x/y/z half-precision floats; w is taken as the non-negative square root, following the official example and the main controller convention, and no second mounting rotation is applied. Records with NaN/Inf or x²+y²+z² > 1.02 are rejected. Slight overshoot caused by half-precision rounding is allowed, and the main controller does the normalization. If a valid unit attitude already read from the FIFO happens to be three positive zeros, x is encoded as IEEE-754 negative zero `0x8000` (the value is still zero), so the main controller does not mistake a legitimate unit attitude for the six-bytes-all-zero "not ready" marker. At power-up before ready, on timeout or on fault, the output is still all zeros.

This module has so far passed register/FIFO simulation tests on a PC; it has not yet been connected to a real board to verify the sensor configuration, noise, mounting orientation, timing or temperature drift.

Each `imu_get_snapshot()` call also reads `board_millis()` independently to check the sample age. Even if a busy bus delays the acquisition polling, data older than 100ms returns `ready=0`, `error=STALE` and all-zero gyro/quaternion; in that case `configured` still means the registers have been configured, the diagnostic counters and timestamps are unchanged, and recovery is carried out by the next `imu_poll()`.
