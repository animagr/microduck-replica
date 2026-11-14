# Project Progress

**English** · [简体中文](PROGRESS.md)

**Project**: Microduck replica
**Started**: 2026-08-28
**Historical progress baseline**: 2026-09-03 (erratum on hardware open-source status: the HAT board has been officially open-sourced)
**Repo**: https://github.com/fanhao375/microduck-replica (public)

> **Model entry point update (2026-09-28)**: structural parts, CAD and print projects are now all downloaded from [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). The old `print/` and `cad/` STLs in the main repo have been removed, and those directories only keep pointer notes. The analysis batches and counts below are historical records; for the latest physical build progress see the [build log](BUILD-LOG.en.md), and for version checks see the [CAD record](docs/cad-structural-parts-version-check-20260928.en.md).

---

## Goal

Replicate Pollen Robotics' **Microduck** (a 25 cm bipedal robot duck, $399, on sale Christmas 2026).
The official software is open source; the hardware is **partially open source**: **the HAT board has a complete KiCad project and production files**
([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Apache-2.0),
but the `imu_to_dxl` board, editable mechanical CAD, full-robot BOM and assembly documentation have not been published.

> **Erratum 2026-09-03**: this was previously recorded as "hardware not open source, no PCB schematics", which **was wrong**.
> The cause was that only the `microduck` main repo was searched, missing the hardware repos with the `elec_` prefix in the same organization.

This project derives all the information needed for a mechanical replica from the official public **MJCF simulation model + 47 STLs**.

---

## Current status (2026-09-29)

| Area | Confirmed | Still missing |
|---|---|---|
| Feetech mechanics | Full robot assembled; stand up / sit down demo completed on 09-18; models consolidated in the CAD repo | This round tested 14 joints; mouth ID 29 excluded at the user's request and not acceptance-checked; assembly zero positions and ranges still need joint-by-joint checking |
| Armbian and HAT | Personal image with the DHCP fix is online; HAT reads joints via `/dev/ttyS2`; debug console 0.15.4 deployed | Acceptance check of long-duration communication, communication during motion, and protection configuration |
| 50 Hz readback target | 3000 rounds, 14 servos, 42000 states total, zero errors in this window, actual 46.8664 Hz; original pose and settings held | Does not include IMU, inference or action writes; cannot be equated with a full-robot 50 Hz control loop; occasional missing responses still occur in other windows |
| Camera | With the correct ribbon cable, the official B1 captured 40 frames at 1920×1080 | Retest under this project's Armbian configuration and sustained frame rate |
| IMU and Rust | Software/simulated test records exist for the Feetech interface of firmware 0.2.0; the Rust `feetech` fork has an adapted implementation | Real mixed bus, response timing and on-board acceptance check on the full robot not done |
| Training | HD1910 project, M6 parameters and short training checks integrated into `software/training` | Calibration of this unit, model checks and gait on real hardware |
| Public image | Old first-login instructions changed to `root / 1234`, duck is only created after the wizard; new DHCP-fix candidate added | Candidate image only verified offline, not yet flashed to a card and tested; base image does not include the robot runtime |

Sources: [3000-round test summary](tools/radxa/50Hz-hold-pose-read-state-20260928.en.md), [image usage instructions](tools/radxa/image-user-guide.en.md), [camera record](tools/radxa/camera-debug-log-20260928.en.md). The next step is small-range joint-by-joint verification with the robot physically supported, then completing protection, IMU and runtime integration. The early analysis process is kept below; its completed items and to-dos do not replace the current acceptance status on real hardware.

## Historical analysis baseline (2026-09-03)

| Area | Status | Notes |
|---|---|---|
| Part geometry | ✅ Done | 47 STLs |
| Assembly relationships | ✅ Done | Accurate to 0.1mm, exploded views produced |
| CAD assembly | ✅ Done | World transforms applied, can be imported directly |
| Joint parameters | ✅ Done | Axes and ranges of 14 controlled joints |
| Mass and inertia | ✅ Done | 15 rigid bodies |
| Fastener list | ✅ Done | Derived from hole features, M2 system |
| Actuator selection | ✅ Done | XL330 ×15, BAM M6 parameters |
| Bearing specs | ✅ Done | Ø22×16×4, Ø15×10×3 |
| **Electronics** | ✅ Done | Fully reconstructed from the Rust source, see "Batch 6" |
| Main controller selection | ✅ Done | **Off-the-shelf Radxa Zero 3W module**, not a custom carrier board |
| **HAT board** | ✅ Officially open-sourced | KiCad + Gerber + BOM + pick-and-place coordinates, ready for fabrication (4-layer board) |
| **`imu_to_dxl` board** | ✅ Designed in-house (not fabricated) | No public project anywhere; chip/address/protocol fully reconstructed; this repo provides schematic + PCB |
| **Cable routing** | ❌ Missing | No official material at all |
| **Control software** | ✅ Usable | With the same main controller, the official Rust runtime runs directly; porting is only needed for a different controller |
| **Policy retraining** | ✅ Not required | With identical hardware, the 9 official ONNX models work directly; retraining is only needed if the body/electronics change |

---

## Completed

### Batch 1 · Initial survey of materials

- ~~Confirmed that **Microduck hardware is not open source**~~: the `microduck` repo is all Rust software,
  the 5 subdirectories under `docs/` are all software documentation, and no `.stl/.step/.f3d/bom` files can be found anywhere in the repo
  — **this conclusion was wrong** (corrected 2026-09-03). Only the main repo was checked, not the hardware repos with the `elec_` prefix
  in the same organization; **the HAT board is fully open-sourced in [`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT)**
  (Apache-2.0, including KiCad + Gerber + BOM + pick-and-place coordinates).
  Lesson: when judging "whether a project has open-sourced some part", you must search **the whole organization**, not just the main repo.
- Confirmed that **`microduck_rl` contains 47 STLs + a complete MJCF**; this is the only source of geometry
- Confirmed that **the 3D model license is CC BY-NC-SA** (non-commercial) and the code is Apache-2.0
- Ruled out the Open Duck Mini v2 route (see "Decision record")

### Batch 2 · Assembly drawings

- MuJoCo offscreen rendering, white skybox, 1600×2100
- 4 standard views + 2 exploded views + 1 color-coded reference view
- Exploded views offset step by step along the kinematic chain (48mm per level), so parts further down the chain are pushed further out
- Implemented world-coordinate-to-pixel projection myself, used for drawing callout leaders and avoiding label overlaps
- Output: `assembly-drawings/` (7 images), script `scripts/render_assembly.py`

### Batch 3 · CAD assembly

- All 47 upstream STLs are in **each part's own coordinate frame**; imported directly into CAD they would all pile up at the origin
- Took each geom's world transform from the MJCF, applied it, and exported grouped by rigid body
- Output: `cad/`: full robot in a single file (796792 triangles) + 15 components, units in mm
- Measured overall dimensions of the full robot: **144 × 141 × 264 mm** (consistent with the official nominal 25cm)
- Script `scripts/export_assembly_stl.py`

### Batch 4 · Fastener reconstruction

- Wrote hole feature detection: weld vertices → build face adjacency graph → split into smooth surface patches at a 35° dihedral angle
  → fit a cylinder to each patch (axis = eigenvector of the smallest eigenvalue of the normal covariance) → project and fit a circle to get the diameter
  → classify hole vs boss by normal orientation
- Scanning all 47 parts took 2.5 seconds
- Output: `docs/紧固件反推.md` (fastener reconstruction), `docs/hole_analysis.json`, `scripts/analyze_holes.py`

### Batch 10 · English documentation

- Background: when listed in an awesome list it was specifically marked "In Chinese"; traffic data showed only 5 visits from Google
  versus 132 from Bing, so the English-speaking community had basically not found it
- Prioritized by page views, starting with `硬件方案逆向.md` (hardware reverse engineering; 2nd most visited on the site, 84 visits),
  because it is **content found nowhere else**: the 3D anatomy page by HF employee @mishig25 (36,000 views)
  already covers the "what the whole robot looks like" layer, and the spec-type documents overlap with it, whereas chip addresses, bus protocol and
  the 12-byte data block layout exist only in this repo
- Output: `docs/hardware-teardown.en.md` (426 lines) + `docs/actuator-selection.en.md` (459 lines),
  both cross-linked with the Chinese versions
- The documentation index of the English README now marks which documents have English versions with 🇬🇧

### Batch 9 · Actuator selection analysis

- Answers two frequently asked questions: why servos instead of closed-loop steppers; whether you can switch to the cheap STS3215 without changing the mechanical parts
- **Hard data comparison**: both are 15-rigid-body bipedal ducks, the XL330 version is **737.2 g** vs **2107.1 g** for the STS3215 version,
  a factor of 2.86; Open Duck Mini v2 is effectively "the STS3215 answer" (42cm / 2.1kg)
- **Actuator parameter comparison**: kp differs 32×, forcerange 3.5×, damping and frictionloss 11× each,
  armature 15.5×; every one differs by an order of magnitude
- Counterintuitive finding: the XL330 model actually has larger backlash (±1.0° vs ±0.5°)
- Conclusion: **there is no middle route**: either keep the XL330 (servos ¥4500) or switch to the STS3215
  (which amounts to building an Open Duck Mini v2)
- **Added a side-by-side comparison of servos in the same class**: the Feetech STS3032 (20 g / 23.2×12.1×28.5 mm / 0.44 N·m /
  4.8–6 V) is even smaller than the XL330 and similar in weight, but has about 85% of the torque (at the same voltage) and a 6 V voltage limit;
  the SCS0009 is only 11 g but only 0.23 N·m (Pollen itself uses it in the Amazing Hand)
- Conclusion: the gap is clearly "18–20 g / ≥0.9 N·m / 7.4 V / bus", and currently only Robotis meets it
- **In-depth evaluation of the Unitree S288** (read the official 11-page manual in full): 19.5 g / 34×20×23 mm /
  **gear ratio 288.35:1, exactly the same as the XL330** / M2 mounting / single-wire half-duplex; mechanically it is almost a drop-in replacement
- Two substantive upgrades of the S288: **impedance control** (τ = τ_ff + k_p·Δp + k_d·Δω) and
  an **output-side encoder** (OutPos 13 bits); the latter could eliminate the entire complexity of backlash modeling
- Three hard constraints of the S288: voltage 12.6 V (3S) vs Microduck's 7.4 V (2S);
  bus address space only 0~14, which cannot fit a 16th device (the IMU would need to go over SPI separately);
  **the torque rating is questionable** (neither the rotor-side nor the output-side interpretation makes sense); four questions to verify with the vendor have been listed
- Output: rewrote `docs/执行器选型.md` (actuator selection; 106 → 424 lines)

### Batch 8 · X community intelligence and external validation ⭐

- Read public X posts using opencli's twitter read commands (search / thread)
- **Key result: the reverse-engineering conclusions were independently validated externally**: @tspy's hardware teardown (169 likes)
  independently lists the Radxa ZERO 3W / RK3566, fully consistent with this repo
- Recorded popularity data: the three official posts totaled about 8.6 million views; GitHub grew 3.7× in three days
- Recorded derivative work already made by the community (R2D2 speech synthesis, laser pointer tracking, somersaults, breakdancing)
- **Identified and flagged noise**: lots of meme coins riding the hype; "Microdino" replies on inspection were
  full of scam accusations and vague about the CAD questions, so it was **judged untrustworthy and not cited**
- Made one premise explicit: **as of 8/31 there were no physical units on the market**, so all public teardowns are inference rather than physical disassembly
- Output: `docs/社区动态.md` (community updates; 150 lines)

### Batch 7 · Cross-validation against official specs + community updates

- Officially released on 2026-08-27 with some specs published; **compared item by item** with this repo's reverse-engineering results
- Mutually confirmed: RK3566 / NP-F550 / 8×8 ToF / width 140mm all match
- Filled in by official info: 1GB RAM + 32GB eMMC (**exactly a Radxa Zero 3W SKU, which corroborates the main controller conclusion in reverse**; not evidenced in the source code; 2G/16G recommended for the replica),
  NPU 0.8 TOPS, dual NFC antennas
- Unique to the reverse engineering: main controller model, main bus design, all chip addresses and protocols
- **Found one contradiction**: officially 2 IMUs are listed, but only 1 is in use in the source code (the BMI088 is marked dormant)
- Recorded the official open-source stance: Pollen explicitly asked the media **not** to call it "open hardware" (but added "for now")
- Recorded three community issues with no reply (#175 STEP / #173 print source files / #174 power board schematic)

### Batch 6 · Hardware reverse engineering ⭐

- Approach: **for the runtime to drive real hardware, it must hard-code device paths, I2C addresses, register offsets,
  baud rates and protocols; the code is the spec sheet**
- Dug out the complete electronics design item by item from `duck-control/src/{model,imu,bus}.rs`, `deploy/*.dts`, `deploy/robotd.toml`,
  `tof/` and `mediad/`
- Output: `docs/硬件方案逆向.md` (hardware reverse engineering; 394 lines, full derivation) + `docs/硬件规格速查.md` (hardware spec quick reference; 270 lines, one-page cheat sheet)

### Batch 5 · Actuator selection

- Compiled the BAM M6 configuration, three domain randomization ranges, and backlash encoder modeling
- Extracted the native PD parameters of the 5 BAM-measured calibration sets from `joints_properties.xml`
- Output: `docs/执行器选型.md` (actuator selection)

---

## Key findings

1. **The whole robot uses an M2 screw system.**
   Ø2.2 through holes ×77, Ø4.4 counterbores ×28, Ø1.6 tap drill holes ×20.
   Ø2.2 and Ø4.4 appear in pairs = the through hole + counterbore combination for M2 socket head cap screws.
   Cross-check: `xl330.stl` itself has Ø2.0×4 + Ø1.6×8, matching the XL330's M2 mounting holes.
   About **146** through holes in structural parts.

2. **There are 15 servos, not 14.**
   The `xl330` mesh is referenced **15 times** in the full-robot MJCF. 14 are in the policy action space
   (left leg 5 + neck/head 4 + right leg 5); the 15th drives the beak/lower jaw via the `passive_*` linkage.
   This matches the "15 servos" in the official README; counting only the joint list misses it.

3. **The head accounts for a quarter of the robot's weight.**
   Trunk 199g, head assembly 189g, whole robot 737g. The center of mass is very high,
   which explains why its walking policy is hard to train.

4. **Backlash modeling is a key sim2real detail.**
   The real servo's magnetic encoder is on the **output side** of the gear backlash, and the firmware position loop closes on
   `main joint angle + backlash angle`; while the servo idles inside the dead zone, the measured position does not change, and neither does the PD error.

5. **Building it yourself costs more than buying.**
   15 XL330s range from $359 (ROBOTIS international store) to €629 (MyBotShop) depending on the channel,
   i.e. from slightly below to far above the robot's $399 price. See BOM.md for the price check.

6. **⭐ The main controller is an off-the-shelf module, not a custom carrier board; the earlier judgment was wrong.**
   (Added 2026-08-31: this conclusion has been independently validated by @tspy's teardown on X)
   The device tree hard-codes `compatible = "radxa,zero-3w", "rockchip,rk3566"`,
   which is the commercially available **Radxa Zero 3W** (Pi Zero form factor, 65×30mm, matching the STL).
   This directly overturns the conclusion that "the electronics are a hard wall".

7. **The IMU sits on the Dynamixel bus, not on I2C.**
   Custom `imu_to_dxl` v2 board: LSM6DSV16X, bus ID 200, register 124, 12-byte block
   (gyro 6 bytes + SFLP quaternion fp16 6 bytes). It is read back in **the same sync_read** as the 15 servos,
   with zero extra bus overhead, and the host does not need to run attitude fusion.

8. **No fuel gauge, no ADC.**
   The battery voltage is read directly from the servos' own supply voltage reported over Dynamixel.
   So 6.6–8.2V is the "usable range under load" rather than the cell range. For the replica **no battery monitoring circuit needs to be designed**.

---

## Decision record

| Decision | Conclusion | Rationale |
|---|---|---|
| Build Microduck or Open Duck Mini v2 | **Build Microduck** | The user explicitly wants Microduck itself. Open Duck Mini v2 is fully open source (BOM/CAD/STL/assembly guide all available), but it is a different robot |
| Public or private repo | **Public** | The user's choice. CC BY-NC-SA allows redistribution; attribution, same-license and non-commercial notices are in place |
| Whether to bundle the 6 upstream repos | **Do not bundle** | Analysis scripts use `scripts/fetch_upstream.sh` to fetch upstream. On 2026-09-04 a copy of the `print/` STLs was provided; on 2026-09-28 it was removed to avoid mistaken prints, and model downloads now all point to the CAD repo. For the source and license of the training project, see `software/training/UPSTREAM.md`. |
| License | **Dual license** | Original `scripts/` → Apache-2.0; `assembly-drawings/` and `cad/` are CC BY-SA-NC derivative works → same license per ShareAlike |
| What to do about the PCB wall | **Copy the mechanics + build the electronics ourselves** | A 100% replica is impossible. The user said they can make PCBs themselves, so this route is feasible |

---

## Archive of early to-dos (historical status below)

### High priority
- [x] **Design the `imu_to_dxl` board**: **both schematic and PCB are done** (2026-09-07).
      STM32G031F8P6 + LSM6DSV16X + SN74LVC2G241 half-duplex buffer;
      45 × 22 mm two-layer board, solid GND pour on the bottom layer, all 22 nets connected, 0 DRC violations.
      **Not fabricated, no physical verification** → [project files and review results](hardware/imu_to_dxl/)
- [ ] **Fabricate and verify `imu_to_dxl`**: before ordering, run component standardization and recheck the silkscreen;
      connector height (8 mm through-hole vs the trunk cavity) needs to be confirmed in the assembly using the STEP
- [x] ~~**Derive the PCB outline**~~: **obsolete**: the official KiCad project and Gerbers directly provide the exact board outline,
      hole positions and connector cutouts, so there is no need to derive them from the STL
- [ ] **Decide whether to build the HAT board**: if you do not need recording/speaker it can be omitted entirely,
      with the ToF connected directly to i2c3 and power from an off-the-shelf UBEC

### Medium priority
- [x] ~~English translation~~ **Done**: hardware reverse engineering / actuator selection / fastener reconstruction are all translated into English,
      plus the README, for 4 bilingual documents in total. `社区动态.md` (community updates) and `PROGRESS.md` are not translated:
      the former is time-sensitive and will go stale, the latter is internal progress
- [ ] `硬件规格速查.md` (hardware spec quick reference) not translated for now: it overlaps heavily with @mishig25's 3D anatomy Space
- [ ] **STL printability check**: verify whether the 47 meshes are watertight and whether they have non-manifold edges,
      to judge whether they can be sliced directly
- [ ] **Printing process evaluation**: simulation meshes have no fit tolerances; evaluate which holes need clearance added
      and which faces need supports
- [ ] **Cable routing channel analysis**: derive feasible cable routes from the internal cavities of the assembly

### Low priority
- [ ] **Control software plan**: the Rust runtime is tied to the RK3566; evaluate the porting cost
      vs rewriting the control loop in Python
- [ ] **Policy retraining**: the official ONNX models no longer work after changing the electronics and must be retrained with `microduck_rl`
      (requires a CUDA GPU, or use `--hf-jobs` to run on HuggingFace)

---

## Risks and known limitations

1. **Simulation STL ≠ printable engineering part.** Simulation only guarantees outer shape and inertia, not fit tolerances,
   threaded holes, heat-set insert seats or cable routing space. Printing directly will most likely not assemble.
2. **Fasteners are reverse-derived, not from drawings.** Screw lengths are estimated from hole depths and are ranges, not measured values.
   Print shrinkage also changes the actual hole diameter (on FDM, Ø2.2 usually comes out 0.1–0.3mm small).
3. **The `imu_to_dxl` board has to be designed in-house.** There is no public project anywhere, so it can only be designed from the reconstructed protocol.
   (The HAT board is officially open source, including Gerbers, so it is **not a blocker**.)
4. **The official policies cannot be transferred.** After changing the electronics, all 9 ONNX models stop working and must be retrained.
5. **Non-commercial restriction.** All geometry-derived content is bound by CC BY-SA-NC and may not be used in commercial products.

---

## File index

| Path | Content |
|---|---|
| `README.md` | Project overview, assembly structure, joint parameters, feasibility analysis |
| `PROGRESS.md` | This document |
| `NOTICE.md` | Attribution and sources |
| `assembly-drawings/` | 7 assembly drawings |
| `cad/`, `print/` | Download entry points to the CAD repo; old STLs and cross-reference tables removed; historical analysis outputs can be traced in Git history |
| `docs/紧固件反推.md` | M2 screw system, purchase quantities, bearing specs |
| `docs/执行器选型.md` | XL330 parameters, BAM M6, 5 sets of calibrated PD, backlash modeling |
| `docs/硬件规格速查.md` | One-page hardware spec table |
| `docs/硬件方案逆向.md` | Full derivation and evidence for the electronics design |
| `docs/社区动态.md` | X / GitHub intelligence, external validation, noise and risks |
| `docs/hole_analysis.json` | Raw hole scan data |
| `scripts/` | Fetch upstream / render / export CAD / scan holes, 4 scripts |
