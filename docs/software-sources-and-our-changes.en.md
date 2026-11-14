# Where the Software Comes From, What We Changed, and Problems We Hit in Upstream Repos

**English** · [简体中文](软件来源与我们的改动.md)

As of 2026-10-14. Most of the software running on the duck comes from Pollen (official) and kissqy; we patch it, change configuration on top, and add some tools of our own. This page makes three things clear: **whose software we use**, **what we changed, where the changes live and whether they have been pushed**, and **the problems we hit in other people's repos and whether they have been handled**. It is for whoever takes over and for their AI. Details for each item link to the on-robot log of that day or to the [pitfall log](../PITFALLS.en.md).

---

## 1. What is running on the first duck now

| Layer | What is used | Source | Did we change it? |
|---|---|---|---|
| Board OS | Old card: an Armbian card we made ourselves; new card: kissqy one-click image R1 | Card-making scripts [`tools/radxa/`](../tools/radxa/); image [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy) | The V1.12 board needs Radxa's bootloader swapped in to boot (`kissqy-r1-v112.sh`) |
| Onboard runtime (robotd, padd) | kissqy's R17 (old card) / V164 (new card), based on official 0.15.1 | Official [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) → kissqy added Feetech HD-1910 adaptation | **Added I²C IMU support** (BNO085 module), see §3 |
| Servo parameters | P3 / D0 / torque limit 700 | R17's `servo-test-parameters.json` | Values we measured ourselves (R17 defaults are P5 / D20), see [Oct 13 night §5](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md) |
| Joint calibration, IMU mounting quaternion | Calibrated by us | — | All zero positions 2048, all directions −1; IMU on Oct 12 compensated 8.54° forward tilt and 1.78° right tilt, on Oct 14 roll compensated back by 1.14° |
| Walking model | kissqy's "walk + fall joint 9600 iterations" | kissqy training | Model unchanged; only servo parameters changed |
| Web console on the computer | Old card uses kissqy web console 1.0.146; new card uses 1.0.164 (matching V164) | kissqy (personal non-commercial license) | Local patches, not published, see §3; the tunable version on 1.0.164 is not yet on the robot |
| Gamepad | 雷神 (ThundeRobot) G50 Pro, S mode (Switch Pro mode) | — | For the pairing procedure see [Oct 13 night §1.2](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md) |
| Training | Official [microduck_rl](https://github.com/pollen-robotics/microduck_rl); kissqy's training console | — | The HD-1910 training project lives in this repo at [`software/training/`](../software/training/) (the former `codex/hd1910-m6` branch of `fanhao375/microduck_rl` is kept as the historical source, see its `UPSTREAM.md`) |
| Debugging and analysis tools | Written by us | This repo's [`tools/`](../tools/) | servo-web, on-robot recording, gait analysis, duck-quiet |

---

## 2. Upstream repos and licenses

| Repo | License | What we use it for |
|---|---|---|
| [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) | Apache-2.0 | The origin of the onboard runtime. On Sep 18 we built a Feetech bus backend in our own fork (`fanhao375/microduck`, `feetech` branch, 1 commit, pushed), later switching to kissqy's more complete adaptation |
| [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl) | Code Apache-2.0; **3D models CC BY-NC-SA** (see [NOTICE](../NOTICE.en.md)) | Training environment and MJCF. We use its `scene_backlash.xml` for simulation comparison and forward kinematics (IMU zero calibration and ground clearance both rely on it) |
| [pollen-robotics/elec_RPI_Robot_HAT](https://github.com/pollen-robotics/elec_RPI_Robot_HAT) | Apache-2.0 | The HAT board; we fabricated version C1 |
| `duckctl` (official, `uvx duckctl@0.17.1`) | Apache-2.0 | PC-side UDP gamepad |
| `1910_m6.json` from [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | Apache-2.0 | BAM parameters for the 1910 servo (borrowing the STS3215 control model). Both kissqy's walking model and our training baseline use it; for its origin see [HD-1910 M6 parameter sources](HD-1910-M6-parameter-sources.en.md) |
| Feetech official [ftservo/ftservo-bam](https://gitee.com/ftservo/ftservo-bam) (Gitee) | Apache-2.0 | HD-1910 BAM parameters identified by Feetech themselves and a dedicated control model (7.4 V, P 4–64). **Not yet integrated into the training project**; the next step is to compare it with the Luwu set in simulation (for the comparison and caveats see the [parameter sources note](HD-1910-M6-parameter-sources.en.md); for the plan see [Oct 13 night §7.5](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md)) |
| [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy) | **Source-available, with per-component licensing**: the Rust workspace and upstream code under `firmware/` (robotd, padd, etc.) are Apache-2.0; the web console `firmware/console/`, his self-trained models in `firmware/policies/`, the training console, and the docs and tools he newly wrote are under a **personal non-commercial license** — company or organizational use, product sales and paid services all require his prior written permission | R17 / V164 runtime, web console, joint walking model, one-click image R1, HD-1910 deployment contract |

**Our agreement regarding kissqy (decided by us on Oct 12)**:
- We do not send PRs to kissqy. Our patches stay on our side: based on his latest version, with our patches stacked on top, following his updates;
- Keep his license and attribution, mark which parts we changed, do not rename, no commercial use;
- His web console is bound by non-commercial terms, so **changes to the web console are not put in this repo**. When we later build a "foolproof" page, we will write our own guide page that calls his programs and interfaces, without modifying his web console; since Oct 14 we maintain changes to the Apache-licensed parts such as robotd via a fork, keeping the upstream web console as is at that time. Build information for the replica versions is on the [public releases page](https://github.com/fanhao375/microduck-replica/releases);
- If we find problems on his side we can open an issue, **but organize the data first, and both of us review it before posting**.

---

## 3. Our changes

### 3.1 Code (all on local branches of the kissqy repo, not pushed anywhere yet)

| Change | Why | Local branch | Status |
|---|---|---|---|
| robotd supports I²C IMUs (BNO085 / LSM6DSV16X), switched by one line `[trunk_imu] source` in the config; read in a background thread, bad packets discarded, reconnect on disconnect; mounting orientation stored separately per model, and torque is not enabled until the orientation is confirmed | kissqy's robotd only recognizes his bus IMU daughterboard, while we use a BNO085 module | `hd1910-trunk-imu-i2c` (based on R17, 36 commits ahead of kissqy main, including the web console patch in the next row); the one merged into V164 is `hd1910-v164-trunk-imu-i2c` | **Running on both the old and new cards**. The new card image `R1-V112-imu` is just kissqy R1 + this patch. Ported to his V167 on Oct 14, historical branch `hd1910-v167-trunk-imu-i2c`. For wiring and IMU confirmation with the replica image see the [getting-started guide](../software/image/flashing-and-first-use.en.md); the V167 version is not yet on real hardware |
| Web console test patch: web gamepad timeout 0.4 s → 3 s, warm up first after connecting, `--tofd-socket ""` to not connect to ToF | Web gamepad presses did nothing, and with no ToF connected it reconnected over SSH every 5 seconds ([Oct 12 night §1](HD1910-20261012-night-IMU-calibration-and-first-steps.en.md)) | Same as above, commit `881c810` | Used locally; we later switched to a Bluetooth gamepad, so this path is basically no longer used |
| padd adds the UDP gamepad and automatic sit down 1 second after gamepad disconnect (ported from official 0.17) | Keep up with new official features without a full upgrade (official 0.17 changed over twenty thousand lines, and the interface version numbers do not match either) | `hd1910-v164-udp-pad` (42 commits = 36 IMU patches + 6 UDP gamepad) | Passed 6 rounds of review, **not yet on the robot** ([Oct 13 record](HD1910-20261013-official-update-and-UDP-gamepad.en.md)) |
| Web console "高级参数" (Advanced parameters) gains three fields: joint scaling, head and leg filtering | These three numbers for the joint model are in the model package, and the web console could not change them; every duck needs fine tuning | `hd1910-trunk-imu-i2c` working tree, **uncommitted** | **Superseded by the next row**, not continued (and the thing that had to be fixed there was not fixed either) ([Oct 13 night §8](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md)) |
| V164 opens up servo P / D / torque limit and head/leg filtering: robotd on the board reconnects to the parameter file (writes RAM when enabling torque, restores when releasing torque), `service.sh` gains three commands, and web console 1.0.164 "高级参数" (Advanced parameters) gains two panels | V164 only writes P, leaving D at the factory 40, and it cannot be changed in the web console either; every duck needs tuning | `hd1910-v164-tunable` (2 commits on top of `hd1910-v164-trunk-imu-i2c`) | Tested and reviewed, **not yet on the robot** ([Oct 14 daytime §8](HD1910-20261014-day-simulation-diagnosis-and-relaxed-params.en.md)) |

### 3.2 Configuration on the board (not code; a backup was kept every time)

Where each item was changed, what the backup is called, and how to revert it are all in the last section of that day's on-robot log:
- [Oct 12 night §9](HD1910-20261012-night-IMU-calibration-and-first-steps.en.md): SSH welcome script, IMU mounting quaternion, recording service, Bluetooth gamepad;
- [Oct 13 night §9](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md): servo parameters, IMU roll compensation, revised recording service; on the new card, Bluetooth, WiFi, watchdog and black box.

### 3.3 Our own tools in this repo

| Directory | What it is |
|---|---|
| [`tools/servo-web/`](../tools/servo-web/) | Web servo debugging console: sliders, poses, sequences, 3D follow, register export |
| [`tools/radxa/`](../tools/radxa/) | Card-making scripts, V1.12 boot fix (`kissqy-r1-v112.sh`), `duck-quiet.sh` (turns off unused services) |
| [`tools/radxa/onboard-analysis/`](../tools/radxa/onboard-analysis/) | On-board recording service (writes to disk every second), system log copying, brownout troubleshooting, IMU zero calibration |
| [`tools/gait-analysis/`](../tools/gait-analysis/) | Gait analysis on the computer: shaking, tracking, ground clearance, toe direction, stance posture |
| [`software/training/`](../software/training/) | HD-1910 training project (mjlab + BAM), can be cloned and trained directly; for parameter sources see [HD-1910 M6 parameter sources](HD-1910-M6-parameter-sources.en.md) |

---

## 4. Problems we hit in upstream repos

"Feedback" column: as of Oct 14, **none of these have been reported upstream yet**.

### 4.1 kissqy

| Problem | Impact | How we handle it | Details |
|---|---|---|---|
| **V164 intentionally does not write servo D (register 51) or torque limit (register 48)** (his design doc: 48/51 keep the device's current values), so the servos use the factory D=40 and 1000; the servo model used in training has no D | Shaky walking, and it is easier to drag the power supply down; the web console 1.0.164 that ships with V164 has no P/D/torque fields (the old web console 1.0.146 has the fields, but they have no effect on V164), so one-click image users **cannot tune it** | Set P3/D0/700 with R17; write servo RAM manually on the new card; local tunable version (Oct 14, not on the robot) | [Oct 13 night §4.2, §5](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md); **~~planning to open an issue~~**: on the evening of Oct 14 he released V167, which writes D=0 and torque 1000 (fixed values) when enabling torque, so no need to report it |
| When installing R17 without a local calibration, it fills in with his prototype's calibration and marks it as "已标定" (calibrated) | All zero positions are wrong; going straight to HOME drives the joints to the wrong positions | Replace it with your own calibration right after installing | Pitfall log, "Servos / calibration" |
| One-click image R1 comes preloaded with the prototype calibration, and the IMU is marked "已确认" (confirmed) | Same as above; the IMU orientation may not be right either | After flashing, first change the calibration and reconfirm the IMU | Same as above |
| One-click image R1 uses the stock Armbian bootloader, so V1.12 boards do not boot | Cannot boot | Swap in the Radxa bootloader (`tools/radxa/kissqy-r1-v112.sh`) | [R1 analysis](HD1910-20261012-kissqy-image-R1-analysis.en.md) |
| robotd only recognizes his bus IMU daughterboard | IMU modules cannot be used | Our I²C IMU patch (§3.1) | Pitfall log, "Software" |
| R17's web gamepad path has several 0.4–0.6 s timeouts along the way, so button presses are often dropped | Web gamepad presses do nothing | Switched to a Bluetooth gamepad; V164 already goes directly through robotd | [Oct 12 night §1](HD1910-20261012-night-IMU-calibration-and-first-steps.en.md) |
| When the web console has no ToF connected, it reconnects over SSH every 5 seconds | Wastes board CPU and generates heat | `--tofd-socket ""` (local patch) | Pitfall log, "Software" |
| The source has two copies of `padd.service`; the install package uses the one in `packaging/` | Editing the wrong file has no effect | Change both, then sync `packaging/SHA256SUMS` | Pitfall log, "Software" |
| `service.sh init` cannot send HOME while robotd is running | Returning to HOME from the command line does not work | Use the web console or `robot.init` | Pitfall log, "Software" |
| The joint model's scaling and filtering are in the model package; the same-named settings in `robotd.toml` have no effect on it | By design, but it is easy to edit the toml by mistake and do a pointless comparison | Check `runtime_execution_profile` to confirm the actual values | [Oct 13 night §4.1](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md) |
| He once wrote "ZERO reboots after a few steps, suspect insufficient LM5050 margin" | Not a problem: **he deleted it on Oct 12** (author's correction) | Do not cite it again | [Oct 13 night §2](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md) |

### 4.2 Official

| Problem | Impact | How we handle it | Details |
|---|---|---|---|
| `install.sh` only installs the latest version, while kissqy's R17 needs 0.15.1 | The installed version does not match | Use kissqy's installation procedure to pin 0.15.1 | Pitfall log, "Software" |
| With no camera or ToF connected, mediad and tofd keep restarting | The board heats up | Turn off these two services (`duck-quiet.sh`) | Pitfall log, "Board / HAT" |
| setup-board intentionally sets `UserspaceHID=false` (saves CPU, fine on the official board) | On our card, which is "not bondable" right from boot, the Pro Controller gets disconnected as soon as it pairs | Run `btmgmt bondable on` before pairing; we also changed `input.conf`, but did not test separately which change is required | [Oct 13 night §1.2](HD1910-20261013-night-brownout-servo-D-and-foot-scuffing.en.md) |
| The new official version and kissqy each increment their interface version numbers independently, so the same number means different things | When mixing old and new components, judging by version number gives the wrong answer | Do not upgrade wholesale; port only the features needed | Pitfall log, "Software" |

---

## 5. How to proceed from here

The latest official versions, development branches and PR status are recorded together in [official update tracking](official-update-tracking.en.md), to be used alongside the adaptation principles below.

- **Use what upstream already provides whenever possible**, and fill in only what is missing. If you write your own separate runtime, every detail becomes an invisible variable (the first item under "Policy training and sim-to-real transfer" in the pitfall log);
- **Keep patches small and branches clear**: one branch per patch, with commit messages explaining why, so it is easy to follow upstream updates and to attach them directly if we ever open an issue;
- **First confirm where a parameter takes effect, then change it**: the same name may exist in several places (toml, model package, servo EEPROM, RAM); before changing anything, find where "the value actually used at runtime" is read from;
- **When upstream updates**: first look at what changed and whether it conflicts with our patches, then decide between a full upgrade and porting only parts ([how we handled official 0.17 on Oct 13](HD1910-20261013-official-update-and-UDP-gamepad.en.md)).
