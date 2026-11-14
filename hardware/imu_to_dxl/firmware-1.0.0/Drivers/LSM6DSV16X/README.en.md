# LSM6DSV16X Official Driver

**English** · [简体中文](README.md)

`lsm6dsv16x_reg.c`, `lsm6dsv16x_reg.h` and `LICENSE` are copied verbatim from the official STMicroelectronics repository, pinned to commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07`. The original download record is kept in `source.json`; the paths in that record are the source paths at download time, not build dependencies.

- Driver source: https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07
- SFLP configuration reference: https://github.com/STMicroelectronics/STMems_Standard_C_drivers/blob/master/lsm6dsv16x_STdC/examples/lsm6dsv16x_sensor_fusion.c

The board-level SPI is in `Core/Src/board.c`; sampling, FIFO parsing and the recovery state machine are in `Core/Src/imu.c`. The driver copyright and the BSD-3-Clause license are unchanged.

This project uses an accelerometer range of ±4g and an angular rate range of ±500dps, with the accelerometer, gyroscope, FIFO and SFLP all at 120Hz. 120Hz is a standard rate supported by the device and gives the 50Hz main controller a fresher attitude; it is not the example's 30Hz copied over directly. The first real-board debugging keeps ST's default filter chain and adds no extra, unmeasured software low-pass.

The gyroscope and quaternion records in the FIFO update their timestamps separately; the two records are not assumed to always be adjacent. At most 16 records are fetched per round, polled once every 1ms. If any required record type is not updated for more than 100ms, ready is withdrawn, and after 1s the device is automatically reconfigured; at startup the first batch of data is awaited for at most 1.5s. Repeated data values while stationary are normal; only the absence of new FIFO records counts as frozen. SPI faults, FIFO overflow, wrong device ID and software reset timeouts can all be diagnosed and retried.

The quaternion keeps SFLP's x/y/z half-precision floats; w is taken as the non-negative square root, following the official example and the main controller convention, and no second mounting-orientation rotation is applied. Records with NaN/Inf or with x²+y²+z² > 1.02 are rejected. Slight overshoot caused by half-precision rounding is allowed; the main controller does the normalization. If a valid unit attitude already read from the FIFO happens to be three positive zeros, x is encoded as IEEE-754 negative zero `0x8000` (the value is still zero), so that the main controller does not mistake a legitimate unit attitude for the all-zero six-byte "not ready" marker. When not ready after power-up, on timeout or on fault, the output is still all zeros.

This module currently passes register/FIFO simulation tests on a PC; it has not yet been connected to a real board to verify sensor configuration, noise, mounting orientation, timing or temperature drift.

Each `imu_get_snapshot()` call also independently reads `board_millis()` to check the sample age. Even if a busy bus delays the acquisition polling, data older than 100ms returns `ready=0`, `error=STALE` and all-zero gyro/quaternion; in that case `configured` still indicates that the registers have been configured, the diagnostic counters and timestamps are unchanged, and recovery is carried out by the next `imu_poll()`.
