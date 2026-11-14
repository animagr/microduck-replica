# 2026-10-12, early morning: switching the first robot to kissqy's full stack (official 0.15.1 + R17 + I²C IMU)

**English** · [简体中文](HD1910-20261012-kissqy整套上机.md)

**In one sentence**: without reflashing the card on the first robot, we remotely installed official 0.15.1 and kissqy's R17 on the existing card and swapped in our robotd with "IMU on the board's I²C" support; the BNO085 was read successfully on the real robot, and all 15 servos answered at 50 Hz. Using his program, the duck **went to HOME in the official standing pose, and after the model took over it held in place for 10 seconds**, with body tilt reduced from 6.6° to 3.3°. The web joystick did not get it walking, because the board was overheating and the CPU was throttled to 408 MHz, so the Python path behind the web gamepad could not respond in time; the user shut it down to cool off, and walking is postponed until cooling is solved.

This document is written for both humans and AI: each step says why it was done that way, and the numbers all come from that night's logs. For the previous night (running the same model with our own Python runner), see [10-11 on-robot test](HD1910-20261011-kissqy-walk-on-robot-test.en.md).

---

## 1. Why switch to his full stack

On 10-11 we ran kissqy's model with our own Python runner; after ruling out timing, power supply, directions and servo parameters, it still could not produce a continuous gait, and the remaining differences were all in the runtime layer. kissqy had shown in the group chat that his full stack already walks smoothly, so we decided: **stop installing our own stack on the robot, use kissqy's full stack directly, and only add what it lacks**.

It lacks exactly one thing: his program only accepts an IMU board on the **servo bus** (ID 200), whereas our robot uses a **BNO085 module on the board's I²C** (`/dev/i2c-4`, address 0x4B). That code was written in the local branch `hd1910-trunk-imu-i2c` and went through two rounds of review; this was its first time on the real robot.

## 2. What was on the card and why we did not reflash

The original plan was to reflash a new card, but after looking remotely it turned out to be unnecessary:

| Item | Actual state |
|---|---|
| System | Armbian 26.2.1 trixie; only 2.2 GB of the 64 GB card used, no card read errors |
| Official runtime | None installed (no robotd, no updaterd) |
| Extras | `microduck-servo-web.service` (starts at boot) and servo-web, the Python runner and logs under `/home/duck` |
| Boot configuration | Radxa U-Boot + `extlinux.conf`; overlays already include `uart2-m0` (servo serial port), `dwc3-peripheral`, `i2c4-m0` (IMU) |

`i2c4-m0` was added at the end of September for the BNO085; reflashing would have meant adding it again. So we installed directly on this card. Before starting, `/home/duck`, `/etc` and `/boot/extlinux` were archived and backed up to the computer (`home-duck.tar.gz` 91.6 MB, `etc-boot.tar.gz` 0.4 MB), so they can be restored as is if something goes wrong.

## 3. Installation process (in order)

### 3.1 Stop servo-web

`systemctl disable --now microduck-servo-web`. It holds the servo serial port, and only one of it and robotd can be in use. The service file is still there; `systemctl start` it when needed, it just no longer starts at boot.

### 3.2 Official 0.15.1: pinned version, installed from local files

- **Why pin 0.15.1**: kissqy's R17 is a modification of the official `daemon-v0.15.1` (commit `1fa8438`). The official release was already at 0.16.1 (10-07), and the official `install.sh` only installs **the latest version**.
- **How to pin it**: download the 6 release files on the computer with `gh release download daemon-v0.15.1` and copy them to the board; copy `install.sh` to `install-local.sh` and change only two things: hard-code the release tag as `daemon-v0.15.1`, and add `--from <local directory>` to `updaterd install`. Signature verification runs as usual, and after installation it also checks that the bootstrap updaterd is the same file as the one in the release package. The exact changes:

  ```sh
  # 1. Change the updaterd install line to install from the local directory
  GITHUB_TOKEN="$TOKEN" "${tmp}/updaterd" install --from "${DUCK_LOCAL_RELEASE}" \
      --config "${CONFIG_DIR}/updater.toml" $force_flag
  # 2. At the end of the file, before main "$@", add: hard-coded release tag, bootstrap updaterd copied locally
  resolve_bootstrap_asset() {
      RELEASE_TAG="daemon-v0.15.1"
      BOOTSTRAP_URL="${DUCK_LOCAL_RELEASE}/updaterd-bootstrap-aarch64"
  }
  fetch_asset() { cp "$1" "$2"; }
  ```

  Run: `sudo env DUCK_REF=daemon-v0.15.1 DUCK_LOCAL_RELEASE=<directory with the release files> sh install-local.sh`.
- **First failure**: the pre-install preparation step downloads ONNX Runtime 1.28.0 (Microsoft's inference library for running the model) from GitHub, and the board's direct connection timed out after 90 seconds. We temporarily pointed root's curl at the computer's proxy (`proxy = "http://192.168.0.100:7890"` in `/root/.curlrc`), and the 8.1 MB downloaded in two seconds; removed after installation.
- **What was slow**: the preparation step also installs system packages such as GStreamer and camera libraries via apt, which took 8.5 minutes.
- **Result**: updaterd, robotd, configd, btd, padd and mediad are all 0.15.1 and running. robotd reports "no robot on the servo bus", because the official original only accepts Dynamixel servos and cannot read Feetech; this is expected.
- **Disable automatic upgrades**: change `auto_apply` in `/etc/robot/updater.toml` from `"mandatory"` to `"off"`, so it does not upgrade 0.15.1 to 0.16 by itself some day and replace the foundation kissqy depends on.

**Two official scripts deliberately not run:**

- `setup-board.sh`: its audio step apt-installs Armbian's vendor kernel package and points `/boot/Image`, `dtb` and `uInitrd` at the new kernel. This board needs Radxa's U-Boot to boot (see [pitfall log · board](../PITFALLS.en.md)), and changing the kernel remotely risks a board that will not boot. Although this robot's HAT has an audio chip, using it requires switching to the vendor kernel and building the driver, and walking does not need sound, so it is left off for now; the other things it does (servo serial port overlay, freeing the serial console) are already done on the card.
- `migrate-network.sh`: switches networking from netplan to NetworkManager, only needed for Bluetooth network setup. Switching networking remotely could drop the WiFi and leave us unable to reconnect, so it is not switched for now.

### 3.3 kissqy's original R17: install the original first to confirm a baseline

Rather than installing the modified version directly, we first installed his original `Microduck-Robotd-FT6-R17.tar.gz` (extracted from `Microduck-Firmware-R17-v1.0.146-Public.zip`; all entries in the bundled `SHA256SUMS` verified), so that if something went wrong we could tell whether it was his problem or ours. The installation method is the same as "系统维护 → 升级" (System maintenance → Upgrade) in his web console: after extracting, run `sudo bash Microduck-Robotd-FT6-R17/service.sh upgrade`.

1. **Stuck at audio setup**: `alsactl store aic3104` exited with code 19. The system has no aic3104 sound card: the audio chip on the HAT can only be enabled by the audio step of the official `setup-board.sh` (vendor kernel + driver), which we did not run, so there is only the HDMI sound card; boards without a HAT are the same. His install script assumes this sound card is always present. Fixed in the branch (commit `790b45d`): if the sound card is absent, skip audio setup and leave everything else alone, with tests added.
2. **After installing, stuck at "Feetech ID 200 no response"**: his program must read the IMU board on the bus before proceeding. The first robot has no such board, which is exactly what we needed to add.
3. **He copied his own prototype's calibration onto this robot**: when the robot has no calibration file, the install script writes **his prototype's zero positions** from the package as this robot's calibration, marks it "calibrated", and even shows "motion ready". His prototype's zero positions range from 1372 to 2176 with mixed signs for direction (e.g. head ID 33 has zero position 1599); our robot was calibrated with servo-web, with all zero positions at 2048 and all directions −1. Powering up with his values would rotate the joints to wrong angles.

### 3.4 Switch to our version + configure the IMU

**Install package**: unpack his original package in WSL, replace 6 files, recompute `SHA256SUMS` and repack (`Microduck-Robotd-FT6-R17-imu.tar.gz`, sha256 `6c4de6db…`). The replaced files are robotd (`618028ac…`), robotctl (`f1bfc8e4…`), and `calibration-config.py`, `rebuild-config.py`, `runtime.py` and `voice-setup.py`. All other files, models and ONNX Runtime are byte-for-byte identical to the original.

**Configuration**: append the following to `/etc/robot/feetech-ft5/robotd.toml`, then install with the same `service.sh upgrade`:

```toml
[trunk_imu]
source = "bno08x"
i2c_device = "/dev/i2c-4"
i2c_address = 0x4B
```

**Result** (debug mode, no torque):

- `trunk IMU: BNO08x identified part=10003676 version=(2, 6, 6) build=193`: the BNO085 was read successfully on the real robot; this was the first time our reader code touched a real chip;
- All 15 servos answered, control loop at 49.99 Hz;
- About 1.7% of cycles had "stale" IMU data (48 of 2878 frames older than 50 ms). All were single frames; on a read failure the official control loop reuses the previous frame for up to 3 frames (60 ms), so by design this does not affect walking. The cause has not been investigated yet; it may also be related to throttling.

**Calibration**: kissqy's formula for joint angles is `angle = (reading − zero) × direction × 2π/4096`, exactly the same as servo-web. So all 15 joints were set to zero 2048 and direction −1 and written with his `calibration-config.py copy` (his prototype file is backed up on the board at `/home/duck/r17/`). After writing, the joint angles converted with the new calibration were left/right symmetric, most joints near HOME, both knees bent around 83°, consistent with the duck slumped down with torque off.

### 3.5 Confirming the IMU mounting orientation

His program does not allow torque-on or HOME until the IMU orientation is confirmed; we set this gate following his rules when writing the I²C support. Confirmation has two steps: with the body upright, no more than 5° from vertical; then pitch forward 15–30°, and the tilt direction must point straight ahead.

- **Not achievable while holding a limp duck by hand**: the first reading was 15.2° from vertical (about 13° pitched forward, about 8° leaning left). A duck without torque has limp legs and is hard to hold upright and steady.
- **Changed to standing it up first and then measuring**: click "站姿" (standing pose) in the servo-web page. These angles are exactly the same as the official HOME (hips ±26.2°, ankles ±26°, neck and head 20°, checked one by one after converting to servo readings). Once the duck was standing on its own, the BNO085 acceleration was read from servo-web and computed with the default mounting orientation (`[0.5, 0.5, 0.5, 0.5]`, sensor X to the left, Y up, Z forward):

| Pose | From vertical | Pitched forward | Left/right | Notes |
|---|---:|---:|---:|---|
| Standing on its own at HOME | 4.95° | 4.81° | 1.15° to the right | 46 frames, jitter 0.41°, acceleration magnitude 1.017 g |
| User tilts the whole duck forward | 21.07° | 20.94° | 2.22° to the right | Change relative to standing 16.2°, direction 3.9° off straight ahead |

Both meet his criteria (standing ≤5°; forward tilt ≥12°, direction within 20° of straight ahead), showing the module is mounted correctly in the default orientation. **Because robotd was not running at the time, `[imu_mounts.bno08x] quat = [0.5,0.5,0.5,0.5], verified = true` was written into the calibration file by hand, not via robotd's `verify-imu` command.** The criteria are the same as verify-imu, but this step was done by bypassing the program, so it is recorded here. Later, verify-imu should support "confirming in the HOME standing pose" (see section 6).

### 3.6 Switching to motion mode, HOME, hold

1. `service.sh enable`: switches to motion mode (his script marks the calibration as motion-capable and makes robotd start in motion mode). robotd came up, but his readiness check failed, because it requires the servos to be torque-off at startup, and the servos were still holding the torque applied by servo-web's standing pose. **Starting in motion mode does not release torque** (starting in debug mode does).
2. `service.sh init` could not send HOME: this subcommand needs exclusive ownership of robotd's lock, and while robotd is running it only reports `another robotd owns this socket`. His web console sends `robot.init` over the IPC socket (`/run/robotd.sock`, one JSON-RPC per line), so we did the same.
3. **HOME refused**: the first time was a torque-on readback timeout; the next 4 times were all `ID 20: temporary P/D readback mismatch; torque-on refused`. Cause: if his program finds the servos **already under torque**, it assumes it applied that torque itself earlier and only checks that P/D are P5/D20, without rewriting them. But that torque came from servo-web, with P/D still at 32/40, so of course the check failed.
4. **Release torque first, then HOME**: with the user holding the duck, send `robot.relax`, then `robot.init` 1.5 seconds later. The log shows P5/D20 written and confirmed by readback, torque on, and a move to HOME in 2 seconds (`at the home pose`).
5. **Hold for 10 seconds**: with the body at 6.6°, send `robot.enable on=true`; the model takes over and stands in place at zero velocity. Body tilt dropped to 3.2–3.6° and stayed steady, joints at most 6.2° from HOME (the model adjusting its own pose), no errors. After 10 seconds, send `on=false` to return to the HOME standing pose.

### 3.7 Web console and web joystick

- The web console was started from the source in the branch (`microduck-hd1910/firmware/console/`, `py -3 console.py --dashboard --feetech --open`, open `http://127.0.0.1:8090` in a browser), with SSH set to `duck@192.168.0.102`. This version includes the IMU panel changes and matches the program on the board. With Clash TUN on on the computer, the system's built-in ssh could still connect.
- Once connected, everything looked right: stable 50.0 Hz, joints 15/15, calibrated 15/15, motion mode, torque ON, IMU online with mounting confirmed, voltage 7.60 V.
- **Pressing Start did nothing**: on the board, the web gamepad path is "web console → webpad (Python, started on demand) → virtual Xbox gamepad → padd → robotd". webpad waits for padd to confirm it has attached the virtual gamepad before sending buttons, for at most 0.6 seconds; with the CPU at 408 MHz, webpad alone takes 1.7 seconds just to start. Without the confirmation, the button press is discarded and the virtual gamepad is removed, so when padd then tries to open it the device is already gone (`Failed to open "/dev/input/event4"`). robotd never received the enable request. kissqy's board runs at 1.8 GHz and does not hit this timing gap.

## 4. Board overheating (the biggest problem that night)

| Moment | CPU temperature | Frequency | Running at the time |
|---|---:|---:|---|
| After installing official + R17 | 89–90°C | 408 MHz | mediad's `gst-plugin-scanner` saturating a core (99.5%), robotd 35% |
| 2 minutes after stopping mediad and tofd | 85°C | 408 MHz | robotd |
| Web console connected, duck standing | 86.9°C | 408 MHz | robotd, web console channel |
| While investigating the web joystick | 92.5°C | 408 MHz | Same as above |

- **Why mediad used so much CPU**: with no camera connected, the camera service mediad crashes on startup and keeps restarting, running a full GStreamer plugin scan every time. The ranging service tofd, with no sensor installed, was also restarting repeatedly. Both were `systemctl disable --now`'d; re-enable them when a camera or ToF is connected later. People in the group chat also said that turning off unused services brings the temperature down.
- **Still hot after turning them off**: the board is inside the body with no heatsink and no airflow, and robotd keeps running, so the temperature slowly climbed back to 92°C. 408 MHz is the lowest step, and everything slows down: torque-on readback timeouts, the web gamepad unable to respond in time, and the occasional IMU gaps may also be related.
- **Servos**: holding from standing to HOME continuously for about an hour, the hottest servo rose from 40°C to 63°C.

The user shut it down that night to cool off. Cooling must be solved before the next session on the robot. The user's thinking: the simplest step is drilling some holes in the head shell or body, which can dissipate some of the heat; to really get the heat out, the key is an **airflow path** with an inlet and an outlet, and the fan does not necessarily have to sit on the board. Later, when camera, ToF and other features are all enabled, there will be even more heat, and cooling will be upgraded together then.

## 5. For others following along (IMU is a BNO085 module, HAT audio not enabled or no HAT installed)

1. The card has a bootable Armbian (this V1.12 board needs Radxa U-Boot, see [no-HAT build](no-HAT-build.en.md)), and both `/dev/ttyS2` (servos) and `/dev/i2c-4` (IMU) exist.
2. Stop anything holding the serial port (e.g. servo-web).
3. Install official `daemon-v0.15.1` from local files (section 3.2); if ONNX Runtime will not download, temporarily give root's curl a proxy; set `auto_apply` to `"off"`. Do not run the audio part of `setup-board.sh` or `migrate-network.sh`.
4. `systemctl disable --now mediad tofd` (when there is no camera or ToF).
5. Add `[trunk_imu]` to `/etc/robot/feetech-ft5/robotd.toml` and install the R17 package with I²C IMU support (`service.sh upgrade`).
6. **Replace the calibration immediately**: installation treats kissqy's prototype zero positions as this robot's calibration. Write `hd1910-calibration.toml` with your own zero positions and directions, compute the joint angles once, and only continue when they match the physical robot.
7. Get the duck standing at HOME (you can use servo-web's standing pose) and confirm the IMU orientation: standing ≤5° from vertical, and after a 15–30° forward tilt the change points forward.
8. `service.sh enable` to switch to motion mode. If the servos are still holding torque applied by another program, first `robot.relax`, then `robot.init` (HOME); at HOME the body must be within 10° of vertical.
9. After the web console connects, press Start to enable the policy (hold), then walk with the joystick. **Do not let the board overheat**: when it overheats, the web joystick stops working.

## 6. Unresolved / next steps

1. **Cooling**: solve this first (holes, then an airflow path with inlet and outlet), then test the web joystick and walking. Once the temperature is down, see whether the CPU can stay above 1 GHz.
2. **Web joystick**: retest after cooling is solved; if it still fails, consider keeping webpad resident, or switch to a physical gamepad (GameSir Nova 2 Lite), which does not go through this Python path.
3. **IMU 1.7% stale frames**: investigate the BNO085 reader thread to see whether it is caused by throttling or by the reading approach itself.
4. **verify-imu must work while standing**: currently debug mode releases torque as soon as it starts, so the orientation cannot be confirmed with the duck standing. Either let verify-imu work while holding HOME in motion mode, or add a "keep torque on" option to debug mode. This time it was written by hand (section 3.5).
5. **`service.sh init/enable-policy` cannot be used while robotd is running** (it takes a different path from his web console); confirm with kissqy whether this is intentional.
6. **Walking**: not walking yet.
7. The second robot will be set up once the first one works. Whether to publish the branch to our repo and whether to send kissqy a PR is up to the user.

## 7. Current state of the board (for the next boot)

- robotd is the R17 + I²C IMU version, starts in **motion mode** at boot with servos torque-off; the calibration is ours (2048 / −1), the BNO085 mounting orientation is confirmed, `motion_enabled = true`.
- servo-web, mediad and tofd do not start at boot; official automatic upgrades are off.
- Order for next time: power on → connect the web console → hold the duck with the body upright → HOME → Start (hold) → joystick.

The raw records from that night are on the board at `/home/duck/r17/`: the two install logs, `status-*.json`, `report-*.json`, `imu-samples.jsonl`, `hold-*.jsonl`, and backups from before and after calibration. The official install log is in `/home/duck/official-0.15.1/`. Copy them back to the computer at the next boot and put them in `software/training/artifacts/hd1910_bench_20261012/`.

## 8. How to connect the IMU module and handle cooling in the future (ideas, not yet verified on the robot)

### 8.1 No more jumper wires for the IMU module: ready-made ports on the HAT

The first robot's BNO085 is currently jumper-wired to pins 1/6/27/28 of the board's 40-pin header (I2C4, `/dev/i2c-4`). The HAT actually has ready-made 4-pin ports (JST-SH 1.0 mm, order 1 GND, 2 3V3, 3 SDA, 4 SCL, same as Qwiic). The table below was checked against the official KiCad project (`hardware-official/elec_RPI_Robot_HAT`, `4478fdf`) and the C1 revision BOM we used for our boards:

| Port | Connects to 40-pin header | Usable as I²C? |
|---|---|---|
| J5 | 3 / 5 (I2C3) | Yes, hardware I²C. Officially intended for the ToF (0x29). The same bus also has on-board chips: the audio aic3104 (0x18) on both revisions; C1 (the one we have) also has a BMI088 (0x19 / 0x68), which D1 replaces with an LSM6DSV16X (0x6A). The BNO085 (0x4A/0x4B) does not conflict on either revision; an external LSM6DSV16X on D1 must use 0x6B. Requires enabling the official `i2c3-pihat` overlay, at the cost of USB-C no longer negotiating PD (see the pitfall log); change `i2c_device` in robotd to the actual `/dev/i2c-N`. |
| J6 | By default via R18/R19 (0Ω) to 7 / 29; the board has R16/R17 (0Ω, not populated by default) reserved to reroute to 27 / 28 | Yes. 27/28 is the I2C4 currently used by the BNO085. **Remove R18 and R19, and fit 0Ω on R16 and R17 (or bridge them)**, and J6 becomes `/dev/i2c-4` directly; the board already has 10k pull-ups (R20/R21), and not a single line of software needs to change. The "short a few components and it works as I²C" mentioned online most likely refers to this port. |
| J7 | 24 / 21 | These are SPI pins with 10k pull-ups, not hardware I²C. Can only emulate I²C with the `i2c-gpio` overlay; CPU overhead and timing are worse than the first two. |
| J8 | 19 / 23 | Same as J7. |

On the first robot, J5 is actually unused (no ToF connected). Recommendations:

- **Modify J6** (remove 2 and bridge 2 0402 resistors): no software changes, the IMU plugs in as the current `/dev/i2c-4`, and J5 stays free for the ToF later.
- **If you do not want to pick up a soldering iron, use J5**: requires changing the overlay and accepting that USB-C will not negotiate PD; later the ToF and IMU can share the same bus.

Both options are only derived from the schematic; the first time you make the change, use `i2cdetect -y 4` (or the corresponding bus number) to confirm 0x4B is visible before starting robotd.

For a pad-by-pad comparison of the C1 and D1 revisions (on-board chip addresses, J6 jumper resistors, mounting the IMU module on the trunk), see [kissqy image R1 analysis §9](HD1910-20261012-kissqy-image-R1-analysis.en.md).

### 8.2 Cooling: holes + airflow path; the fan does not have to be on the board

The HAT and the board are stacked together and already packed full, with no room for a fan. The user's thinking:

1. **Holes first**: drill some holes at the top of the head shell and the lower part of the body; hot air rises, so air comes in at the bottom and goes out at the top, carrying away some heat even without a fan.
2. **Then an airflow path**: put the fan anywhere convenient in the airflow path (e.g. at the head shell outlet), as long as air can flow past the board with a way in and out; it does not need to be attached to the board.
3. A small heatsink on the main chip works even better together with the airflow path.
4. Power the fan from 5 V (pins 2 and 4 of the 40-pin header plus GND), not the 3V3 on the HAT's JST ports: that 3.3 V comes from the board, has limited current, and is shared with the sensors, so fan noise would couple into them.

Before and after the change, in the same state (robotd running, duck standing), read `/sys/class/thermal/thermal_zone0/temp` and `/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq`, and see whether the temperature can stay below 80°C and the frequency can leave 408 MHz.
