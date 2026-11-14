# HAT hold-pose state readback: 3000 rounds

**English** · [简体中文](50Hz保持姿势读状态-20260928.md)

Test start time: 2026-09-28 23:49:17 (recorded by the debug PC). Board running Armbian + HAT, `/dev/ttyS2`, web debug console 0.15.4, readback target 50 Hz; joint IDs `10–14`, `20–24`, `30–33`, 14 servos in total, mouth not included.

| Metric | Result |
|---|---:|
| Valid samples per servo | 3000 / 3000 |
| Total valid states | 42000 |
| First-to-last time span | 63.9904 seconds |
| Actual rate computed over 2999 intervals | 46.8664 Hz |
| timeout / bad_checksum / bad_id increments within the window | 0 / 0 / 0 |

Before and after the test, the torque register of all 14 servos was 1. Goal position, torque limit, speed, acceleration, mode, and phase were unchanged before vs. after. The robot held its existing pose; this run did not require everything to return to 2048, and no actions, calibration, or configuration writes were performed.

0.15.3 fixed a problem where sync read consumed reply packets in the expected ID order; it now files each reply by the ID actually in the packet, so one missing packet no longer corrupts the valid replies after it. 0.15.4 changed the web console's state readback target to 50 Hz. The 38 related local tests for this fix and the protocol simulation self-check passed. What it fixes is data parsing; it does not prove that wiring, electrical, or servo response problems are all gone.

This result covers only the roughly 64-second window above. Later runtime logs still showed occasional missing responses from a single servo, so this cannot be described as "zero missed reads over the whole run" or "the communication root cause is fully resolved". This round had no IMU acquisition, policy inference, or goal position writes, and **does not constitute a full 50 Hz robot control loop, loaded motion, or gait acceptance check**.

The camera has so far only been confirmed to produce images on the official B1; the Armbian retest, mixed IMU bus, full-robot integration of the Rust runtime, protection configuration, and gait still need to be verified separately. The debug console is a separate deployment on the board and is not included in the public Armbian base image.

The raw data is saved on the debug PC at `Radxa-Zero3W/调试记录/50Hz使能保持只读3000轮-20260928-234917.json`; this page publishes only the summary, and the roughly 13 MB raw log was not uploaded. The raw record was re-checked on 2026-09-29.
