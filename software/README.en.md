# software · Software

**English** · [简体中文](README.md)

> This folder keeps the upstream simulation models needed for training. It is **not the print source for the latest physical structural parts**. All model downloads are consolidated in [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). Bringing in Feetech servo parameters does not mean the CAD geometry, mass and inertia have been updated.

The official runtime [`pollen-robotics/microduck`](https://github.com/pollen-robotics/microduck) is written for the Dynamixel XL330, while this repo's main line uses the Feetech HD-1910, so the main program has to be modified.

## Software currently in use

| Software | What it does | Where and how to use it | License |
|---|---|---|---|
| **Replica image** | The complete system that works as soon as you flash the card and boot: main program, models, Studio, first boot and network setup | [`image/`](image/): users read [Flashing and first use](image/flashing-and-first-use.en.md), image builders read [image/README.md](image/README.en.md). Published versions are on [Releases](https://github.com/fanhao375/microduck-replica/releases/latest) | Build scripts Apache-2.0; licenses of the parts inside the image are in `/usr/share/doc/microduck/` in the image |
| **Microduck Studio** | Web console installed on the duck: status, torque off, servo zero position, IMU orientation, write into the main program, gamepad, remote control, logs | [`studio/`](studio/). No separate install needed if you use the replica image | Code Apache-2.0 |
| **Web software update** | Signed component packages, standalone update service, offline upload, install and rollback | [`updater/`](updater/), preinstalled in the 20261027 image; older cards need a one-time SSH bootstrap, see the [instructions](../docs/software-update-and-voice-guide-20261027.en.md) | Apache-2.0 |
| **Local sit/stand voice** | Single-click R3 toggles listening, Chinese "sit down / stand up" commands, quack prompts | [`duck-echo/`](duck-echo/); the 20261027 image ships the Chinese model and ARM64 dependencies; no cloud key needed | Code Apache-2.0, models and dependencies under their own licenses |
| **Main program robotd / padd / mediad** | On top of official 0.15.1, adds the Feetech HD-1910 servo bus, I²C IMU module, gyro fusion and UDP gamepad | Already installed in the replica image. Builds, commit hashes and downloads for each version are in the [image notes](image/README.en.md) and on the [public releases page](https://github.com/fanhao375/microduck-replica/releases) | Apache-2.0 |
| **Walking and action models** | Walking, sit down / stand up, head-down pick-up, forward roll, left/right kick, roller skating: 4 in total | Included in the replica image. What each model does, which gamepad button it maps to and who trained it are in the [model notes](image/overlay/usr/share/doc/microduck/模型说明.txt) | The author's personal non-commercial license, **not an open-source license**: must not be distributed with paid products |
| **Training project** | HD-1910 simulation training | [`training/`](training/) | Code Apache-2.0, 3D meshes CC BY-NC-SA |
| **Microduck Training Studio** | Web training workbench on the computer: experiment management, curves, evaluation and model export | [`training-studio/`](training-studio/README.en.md), runs separately from the Studio on the duck | Code Apache-2.0; dependency and asset licenses are described in that folder |
| servo-web (old) | The September web servo debugging console, used before Studio existed | [`tools/servo-web/`](../tools/servo-web/) | Apache-2.0 |

Standalone servo testing, IMU checks and gait analysis are listed in the [tools index](../tools/README.en.md); circuit boards and firmware are listed under [hardware projects](../hardware/README.en.md).

## HD1910 simulation training

**[`training/`](training/)** contains the complete Python training project: models, LuwuDynamics' 1910 M6 parameters,
the HD1910 task configuration, the Feetech controller initialization adaptation, dependency lock files and tests. You get it by cloning this repo;
there is no need to download the `microduck_rl` branch anymore.

[Quick start](training/README.en.md) · [Running notes and explanation of the initialization issue](training/docs/hd1910-baseline.en.md) ·
[Sources and licenses](training/UPSTREAM.en.md). This is currently a simulation integration baseline; gait training tested on this robot's real hardware has not been completed yet.

## IMU bare-board debugging

The STM32G031 + LSM6DSV16X firmware and hardware materials are in [`hardware/imu_to_dxl/firmware/`](../hardware/imu_to_dxl/firmware/). The attitude display has been merged into [`tools/servo-web/`](../tools/servo-web/): use `python server.py --port COM5 --imu-jlink imu-jlink.json`, and the same model receives both the servo joint angles and the torso attitude from J-Link. With only the bare board, you can use `--fake` instead of the serial port argument.

**Scope: firmware and simulated verification, SWD bench observation.** The bundled 0.2.0 source already implements the Feetech SCS/STS protocol, ID 200, the 15-byte block at address 56 and sync-read queuing; host tests and simulated-bus acceptance check records are in [`VALIDATION.md`](../hardware/imu_to_dxl/firmware/VALIDATION.en.md). There are flashing and IMU observation records on the real board, but the acceptance checks for a real mixed bus, response/release timing and the full-robot runtime are still not done. The earlier statement that it was "still the Dynamixel baseline and the contract is not implemented yet" is outdated and must not be confused with "the real bus has not passed acceptance yet".

## History: the first Feetech backend from September (no longer used)

> The main program currently in use is the fork in the overview table above. Below is the first Feetech backend written in September on top of official 0.14.1. It never ran on a board and is kept for reference.
>
> [`fanhao375/microduck` · `feetech` branch](https://github.com/fanhao375/microduck/tree/feetech): caught up with official **0.14.1**, all tests in the three crates pass (duck-control 80 / robotd-params 151 / robotd 93).

| File | Lines | What it does |
|---|---|---|
| [`duck-control/src/bus_feetech.rs`](https://github.com/fanhao375/microduck/blob/feetech/duck-control/src/bus_feetech.rs) | 744 (new) | **The `FeetechIo` core**: one `sync_read` per tick at address 56, length 15; position conversion with a direction table; target writes with clamping; `set_gain` writes only P (Feetech has no I/D equivalent); `reboot` turns torque off first, then 0x08; boot checks END byte order / response level / operating mode / baud rate / phase; `imu_ready()` is always false. Includes 11 unit tests |
| [`duck-control/src/bus_select.rs`](https://github.com/fanhao375/microduck/blob/feetech/duck-control/src/bus_select.rs) | 149 (new) | `AnyBus` enum, choose one of the two backends (`Box<dyn RobotIo>` does not compile, see the [architecture doc](feetech-adaptation-architecture.en.md) §3.1 for why) |
| `robotd-params/` | +50 | `[bus] protocol = "dynamixel2" \| "feetech-sts"`, `[bus.feetech] p_scale / directions`, registered in the parameter table |
| `robotd/src/main.rs` | +63 | `BusIo` replaced by `AnyBus`, the protocol is passed when opening the bus; invalid parameters error out immediately with no retry |
| `duck-control/src/model.rs` | +8 | Expected value for the HD-1910 factory operating mode 4 |
| `deploy/robotd.toml` | — | Two new keys, with comments |

Build (requires Rust):

```bash
git clone -b feetech https://github.com/fanhao375/microduck.git
cd microduck && cargo test -p duck-control -p robotd-params -p robotd
```

**Why it lives in a fork rather than this repo**: `FeetechIo` is one file in the `duck-control` crate of the official Rust workspace,
and it uses the official `RobotIo` trait, the `Safety<T>` generic and the parameter system — copied out on its own, it will not compile.
On a fork branch, a `git rebase` keeps it up to date when upstream changes (on 2026-09-20 it followed 55 commits with zero conflicts),
and it can also be submitted to upstream as a PR directly in the future. Upstream is Apache-2.0, and keeping the changes in a fork also keeps their provenance clear.

| File | Contents |
|---|---|
| [`飞特适配架构.md`](feetech-adaptation-architecture.en.md) | Existing architecture of the official runtime (where the seams are, what happens each tick, boot sequence), item-by-item differences between the two servo brands, the adaptation plan, **`imu_to_dxl` small-board firmware architecture (§4)**, bench acceptance checks, open-questions list, build and deployment / policy relationship / failure modes, review records |

The interface contract of the small-board firmware (15-byte block, timing, queuing rules, acceptance checks) is written up separately: [`hardware/imu_to_dxl/总线协议.md`](../hardware/imu_to_dxl/bus-protocol.en.md), with the companion tool [`tools/imu200/`](../tools/imu200/) (fake small board + test vectors + real-board acceptance check).

How to flash the board and install the official runtime is in [No-HAT build](../docs/no-HAT-build.en.md) and [`tools/radxa/`](../tools/radxa/).

The original Feetech protocol and memory table documents (2026 snapshot) are in [`docs/飞特资料/`](../docs/飞特资料/).

Get the servos responding before touching the code: [`tools/servo-web/`](../tools/servo-web/) is a web debugging console connected to the serial port: drag sliders, read back values, export a register baseline, and watch a 3D duck move along. Bench checklist items 0–8 in the architecture doc all use it.
