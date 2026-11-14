# Pitfalls

**English** · [简体中文](踩坑记录.md)

Pitfalls we actually hit while building the replica, **three sentences each: symptom, cause, what to do**. Organized by stage; skim it before you start.

Analysis and evidence live in other documents; only the conclusions are recorded here. When you hit a new pitfall, add it to the relevant stage and write it plainly.

> The mechanical process is in the [build log](构建日志.md), the electrical and software process in the [debug log](调试记录.md). Recent additions: Oct 20–21, 2026, acceptance testing of the replica image on real hardware: the fork's calibration mode always shows "starting up", `.local` won't open while Clash is on, the image's SSH host keys were not generated, skipping every step won't enter motion mode, the robot can't stand up in calibration mode (added hold-home), the hotspot comes up slowly, and two items were added under Tools on GitHub releases and the front-page cards; evening of Oct 15, 2026, the root cause of "falls after two or three steps" was the BNO085's own orientation jumping erratically, fixed with gyro integration; when debugging, first check whether the data is self-consistent; the yardstick for detecting jumps must be aligned with the latency; weak turning (not solved yet); one item each added on full-robot reboots and G50 pairing; evening of Oct 14, 2026, kissqy's V167 now writes D=0 and torque 1000 when torque is enabled (if you use an IMU module, don't upgrade directly); Oct 14, 2026 daytime, servo parameters are written to RAM (they linger if robotd restarts while torque is on), the two feet aren't coplanar laterally because both hip rolls splay outward (presumably pushed by body weight), the mouth servo runs hot, the new "repair gamepad connection" only supports GameSir, don't click "install / upgrade firmware", TPU 95A soles are on the hard side, align scale, filtering and weight before comparing with simulation; night of Oct 13 – Oct 14, 2026, servo D makes walking jittery, V164 doesn't write D or torque limits, full-robot brownouts while walking are a power issue, the G50 Pro disconnects right after pairing on the new card, switching cards requires re-pairing the gamepad, the static IP got taken, Armbian logs are lost on power loss, the joint model's scale and filtering are not in robotd.toml, work out foot scuffing before tuning; Oct 13, 2026, kissqy's install package uses `packaging/padd.service`, cross-compiling padd needs arm64 libudev, the official and kissqy interface version numbers increment independently, the part number of Feetech's AMP2.0 board-side connector; night of Oct 12, 2026, the IMU being mounted 8.5° off is the real reason the model lurches as soon as it takes over (with a zero-calibration method), four layers of causes behind the web gamepad, the SSH welcome script, ToF reconnects, Bluetooth gamepad pairing, IMU wiring with a bad contact, knees collapsing, the power bank falling back to 5 V, TPU soles; afternoon of Oct 12, 2026, taking apart kissqy's one-click image R1 (won't boot on V1.12, only supports the bus IMU board, preinstalled prototype calibration), editing armbianEnv has no effect under the Radxa bootloader, addresses when connecting an IMU module to HAT J5, Python on Windows turning files into CRLF; Oct 12, 2026, switching to kissqy's full stack (pinning official install.sh to 0.15.1, the audio setup hangs when the sound card isn't enabled, R17 copies the prototype's calibration, mediad/tofd overheating the board, vent holes and airflow ducts, installing R17 releases torque, check IMU orientation after standing up, HOME rejected after another program enabled torque, `service.sh init` can't send HOME, overheating breaking the web joystick); Oct 11, 2026, kissqy's walking model on the robot (gait can't be tested while held by hand, undervoltage protection and full-body torque release, power headroom, soft start, board thermal throttling, Clash TUN blocking the board, freezing after boot); Sep 28, 2026, HAT power, USB ports, the camera ribbon cable and comparison with the official image.

---

## Buying parts

**Don't buy an NP-F970 battery; it's the NP-F550**
The upstream mesh file is named `np_f970.stl`, but it measures 39 × 21 × 71 mm, which is the F550's size. A real F970 is about 60 mm thick, **won't fit**, and its 300 g would eat a third of the robot's weight budget.
→ Buy an NP-F550 (2S, 6.6–8.4 V). See the [BOM](BOM.md).

**The Feetech HD-1910's cable is 2.0 mm, the Feetech debug board's port isn't; assigning IDs needs a jumper-wired cable**
The HD-1910's stock cable is AMP2.0-3P (2.0 mm pitch). The TTL port on the FE-URT-2 debug board is bigger, so it **won't plug in**, and the board has no 2.0 port.
→ If you need to assign IDs the same day, **cut a servo cable** (sacrifice one of the 15) and connect the three bare wires like this:

```
Servo cable             FE-URT-2
Pin 1  Signal    →   S    solder to the S-pin pad of the white port on the back of the board (temporarily you can also tin the wire and insert it directly into the S hole)
Pin 2  Vcc       →   V1   blue screw terminal
Pin 3  GND       →   G    blue screw terminal
```

**The middle wire is always V** (Feetech and Dynamixel agree on this); swapping S and G won't burn anything, it just won't communicate, swap them back.
**Only getting V wrong will burn something.** For ID assignment with no load, USB 5 V is enough (the HD-1910 works from 4 V); first check with a multimeter whether there's 5 V across G–V1 on the blue terminal; if not, flip that switch.
→ The proper way is to buy a few "PH2.0 3P terminal cables" plus a few terminal cables of the board's connector type and splice them into adapter cables. Check the servo packaging before buying; sometimes one is included.
→ This is worth telling Feetech directly: whether the retail version should include an adapter cable.

**Feetech's pin order is the exact opposite of Dynamixel's**
Feetech HD-1910: `1=Signal 2=Vcc 3=GND`. Dynamixel XL330: `1=GND 2=Vcc 3=Signal`.
→ Fortunately the two have different pitches (2.0 vs 2.5 mm), so they can't plug into each other. The only remaining risk is "crimping your own cable backwards"; after crimping, check it with a multimeter first.

**Don't use the HL-2915 as a reference**
The Feetech HL-2915-C002 is a 9–14 V servo; a 2S battery (max 8.4 V) **can't drive it**, and its pin order is again the opposite of the HD-1910's.
→ This design only supports the HD-1910-C001.

**A fully charged battery at 8.4 V is exactly the HD-1910's voltage limit**
The HD-1910's operating range is 4–8.4 V. A fully charged NP-F550 is 8.4 V, **zero margin**. Only when the voltage sags under load to 6.6–8.2 V is it back in the safe zone.
→ Don't do stall tests right after a full charge. For long-term storage, store at 3.8 V/cell. Enable the servos' overvoltage protection before assembly.

**The low-end Radxa Zero 3W is a bare board**
The 2 GB version without eMMC **has no pin header soldered and no storage**; it can only boot from microSD.
→ Buy your own 2×20 pin header (2.54 mm, vertical; colored ones make counting pins easier) and a **high-endurance** microSD (SanDisk High Endurance / Hikvision PLUS, 32 or 64 GB; buy two, one as a backup).

**Don't feed external power into the URT-2's V1 terminal**
The DIP switch on the board selects the TTL level (3.3 / 5 V); it is **not** a power selector. With USB plugged in, V1 has 5 V; how it connects to USB is unclear and it may be a direct connection. Feeding 7.4 V into V1 risks backfeeding into the PC or the Radxa.
→ Connect external power directly to the servos' V and G, connect the URT-2's G to the negative as well for a common ground, and leave V1 unconnected. The URT-2 only handles the signal.

**Feetech servos all ship with ID 1**
Connect all 15 at once and they all respond; you can't tell which is which.
→ **When setting IDs, connect only one at a time.** After changing it, stick on a label (joint name + ID), unplug it, take the next one. Steps and the ID table are in [Debug log · Servo configuration](调试记录.md#舵机配置--拿到货一步一步做).

---

**ToF module: the L8CX board won't fit in the face shell, and the firmware doesn't support the L7CX**
Symptom: we first bought a VL53L8CX; the board commonly sold in China is **33.4 × 10.2 mm** and won't fit in the face shell (`face_part`);
to get something shorter we switched to an L7CX (26 mm), but the firmware errors out and quits on startup. Both purchases were wasted.
Cause: the L7CX is **a different chip** with a 90° wide field of view, and its revision ID doesn't match. The official `tof` firmware only accepts `0x02` (L5CX)
and `0x0C` (L8CX); anything else gets `neither a VL53L5CX nor a VL53L8CX` and the firmware exits.
Only those two ULD drivers are compiled into the firmware; it's not something you can get around by changing an ID.
→ Buy a **VL53L5CX (VL53L5X V2 module)**: the firmware supports it, **its 20 mm hole spacing matches the printed part exactly** (a colleague measured the printed part's holes at 20 mm;
the L8CX board is 28 mm and simply can't be mounted), and the board is also the smallest (**15.8 × 10 mm** board body / 24.7 mm including mounting ears),
and it's 25 yuan cheaper. **The selection order is: first check whether the firmware supports the chip (only L5CX / L8CX), then whether the board fits**;
picking by size first is how this happened. The L8CX chip itself is fine; it's that board that's too long.
If you can find a short L8CX board, it will work too; measure the hole spacing and lens position from the actual part.
A size comparison of the three board types is in the [electronics purchase list](docs/电控采购清单.md#四tof-测距--vl53l5cx-或-vl53l8cx8×8-多区).

## PCB design / fabrication

**"Replace" on the JLCPCB order page doesn't write back to the project**
Clicking 「替换」 (Replace) on the order page to swap a part number only applies to that order. The component in the EasyEDA project still has the old part number, so **the next BOM export reverts it**, and you get "private stock 0" again.
→ Replace the component in the EasyEDA project (delete it and re-place it at the same coordinates), not just on the order page.

**Active oscillators and passive crystals in 3225 4-pin packages look exactly the same**
On a passive crystal, pins 2 and 4 are the same metal lid and are shorted internally. X1 on this board is drawn as an active oscillator (2=GND, 4=VDD), so fitting a passive one **shorts 3.3 V to ground the moment it powers up**. Searching JLCPCB for "3225" mostly returns passive parts, and `C13738` (basic library, no part-change fee) is the easiest one to click by mistake.
→ Only accept parts labeled 「有源晶振 / OSC」 (active oscillator / OSC). This board uses `C5917307`.

**Xingtong Shipin C387369 isn't in JLCPCB's SMT assembly stock**
At ordering it was classed under 「使用私有库存的元器件」 (components using private stock), with private stock 0.
→ Switch to `C5917307` (Yajingxin, 5 mA, same package).

**After adding components, the Gerber / BOM / pick-and-place files all have to be re-exported**
After changing the schematic (e.g. adding J4/J5), all three files change. If you fabricate with the old Gerber, the board won't have holes for those two connectors.
→ Export the full set after every change, with a timestamp in the file names, and go by the latest one.

**The PH2.0 connectors chosen for J4/J5 have the right pitch, but the housing doesn't match the Feetech cable plug, so it won't plug in**
The Feetech HD-1910's cable has an AMP2.0-3P plug; the 2.0 mm pitch is right, but the plug's shape doesn't match the housing of a JST PH connector (`B3B-PH-K-S`). Someone warned during review that "the board-side connector hasn't been verified with a real part", and sure enough.
→ First board: shave off the connector housing, leaving just the pins; it plugs in and works. v2: match the connector against a real Feetech cable (ask Feetech for the board-side connector part number, or buy a few kinds of 2.0 mm 3P connectors and test-fit them); **test-fit with real parts before sending the board out**.
→ Addendum (2026-10-13): Feetech's datasheet only gives the cable-side `AMP2.0-3P`; the board-side part number is not public, and we found no verified right-angle part number online; another replica project simply lists it as "PH2.0", likewise untested. But Feetech's dimension drawing shows **two of the same connector right on the bottom of the servo body**, which means Feetech itself uses the matching board-side connector; the fastest route is to ask Feetech directly for the part number, whether it can be bought separately, and whether a right-angle version exists.

**Chinese characters in GitHub Release asset names get stripped**
Uploading `SolidWorks图纸.zip` stored it as `SolidWorks.zip`. The download link in the README no longer matched.
→ Use English names for Release assets.

---

## Jumper wiring (no-HAT build)

> The full wiring is in [No-HAT build](docs/不打HAT.md); only the parts that bite are listed here.

**The adapter board's logic supply must be taken from 3.3 V**
The half-duplex adapter board has a VCC on the MCU side. If you take it from 5 V, its TX drives 5 V levels into the controller's 3.3 V RX pin.
→ Take it from 40-pin header pin 1 (3.3 V). The ToF takes power from pin 17, so the two don't compete.

**Feeding 5 V into the 40-pin header is unprotected**
Feeding 5 V via pins 2/4 bypasses the board's own USB input protection. **Reverse it and the board burns on the spot.**
→ Measure the polarity and voltage of the buck module's output before plugging in.

**Don't use Dupont wires for the servo power trunk**
15 servos peak at several amps; 24–28 AWG Dupont wires only handle about 1 A and will get hot or even melt their insulation.
→ Use 18–20 AWG silicone wire for the trunk.

**Put a fuse and a switch in series between the battery and the servos**
A shorted lithium battery can spit fire. The official HAT's path has a thermistor and a "3A max" marking; the jumper-wire build connected bare has none of that.
→ Put a 5 A fuse + power switch in series.

**There's no shutdown signal**
On the HAT, the LM5050-1 gives the controller a shutdown signal; the jumper-wire build has none. Every power-off is a hard pull, **which is hardest on the microSD**.
→ First run `make shutdown` or use the gamepad shutdown gesture, wait for the system to shut down cleanly, then cut power.


---

## Servos / calibration

**Feetech FD debug software: install the driver first, use the latest version, select 1 Mbps baud rate**
Symptoms, three in a row: with the URT-2 plugged in, not a single servo is found; after installing the driver it connects, but the servo model reads as `unknown`; or it connects but the scan finds nothing.
Cause: ① the URT-2's USB-to-serial chip needs a driver; if Device Manager shows no COM port, it isn't installed; ② the old FD version's model table doesn't include custom models like the HD-1910, so it can't identify it and shows unknown, **but register reads and writes work perfectly**; ③ the HD-1910's factory baud rate is 1 Mbps (register 6 = 0), and if FD's baud rate isn't set to 1000000 the scan finds nothing.
→ Order: install the driver → confirm a COM port in Device Manager → set FD's baud rate to 1000000 → use the latest FD from [Feetech's official site](http://doc.feetech.cn/). Ignore the unknown model display; don't assume the servo is broken.

**The HD-1910's position counting direction is opposite to the official XL330's, on all 15 servos**
Symptom: when dragging a slider, the 3D model moves opposite to the real robot; sending the angles of the official standing pose bends the legs the wrong way.
Cause: the direction in which the HD-1910's reading increases is opposite to the XL330's, and the mechanical assembly copies the official one, so every joint is flipped as a whole: all of them are reversed, not just a few mounted backwards.
→ Set the direction of all 15 to −1: [`tools/servo-web/directions.json`](tools/servo-web/directions.json); in robotd it's `[bus.feetech] directions`. Each servo was checked individually with the ± button next to it on the web page.

**The HD-1910 doesn't support center calibration by "writing 128 to the torque switch"**
Symptom: the memory table clearly says "write 128: correct any current position to 2048"; doing so, the servo replies "success", but not a single offset register (31) changes. If the code then writes the target position as 2048, the joint actually gets pulled back to the old zero. Tested on 2026-09-20 over 4 rounds on all 15 servos; same result unlocked and with torque off.
Cause: firmware 3.46 doesn't support this command. The support table in section 4.9 of the protocol manual says: SMS ≤2.54 and STS ≥3.10 support writing 128, **HLS ≥3.43 does not**, only 0x0B; the HD-1910 behaves like the HLS row.
→ Use the **0x0B position calibration command** (no parameter = calibrate to 2048, with a parameter = calibrate to the given reading). After calibration always read back the position and offset to confirm; don't trust the "success" in the reply: Feetech replies success to many operations it doesn't support.

**Don't wait with torque off during calibration**
Symptom: after turning torque off and waiting a few tens of milliseconds before reading the position, the neck (30) reading dropped 80 steps (7°), and the calibrated zero was off.
Cause: as soon as torque is off, gravity pulls the joint down, and the longer you wait the further it drops.
→ Don't sleep between turning torque off and finishing calibration; a few milliseconds is enough. Right after calibration, write the target position as the new reading and then enable torque.


**The servos' D (derivative, damping) is related to jitter while walking**
Symptom: on 2026-10-13 with R17's default P5/D20, half of the body sway while walking was jitter above 4 Hz (51%), and the step rhythm was erratic. The new card's V164 uses the factory D=40.
Cause: the BAM servo model used in training (parameters are Luwu's published 1910 M6, `kp_fw=5`, i.e. firmware P=5) has no hardware D term, while the real servos carry D. After changing D to 0 (and torque 1000→850), jitter dropped to 4–8%. Why D causes jitter, "damping eats the corrective motion", is only a hypothesis; the tracking data doesn't confirm it.
→ First set D to 0 to remove the jitter. But with D=0 the stance knee straightens even less, and the body started nodding fore-aft with the left toe pointing down (not present at D=20); intermediate values D=5–10 are worth trying. With D=0, the higher P, the more sway: P5 sways 56°/s, P4 44°/s, P3 30°/s (simulation 31°/s). We currently use P3 / D0 / torque 700, at the cost of lower foot lift. Data in [10-13 night session record §5](docs/HD1910-20261013-夜-掉电-舵机D与蹭地.md#5-走路发颤跟舵机的-d-有关).

**kissqy's V164 (one-click image) doesn't write D or torque limits; changing the P/D/torque boxes in the web console does nothing**
Symptom: changing P, D and torque limit under 「高级参数」 (Advanced parameters) in the new card's web console, the servo registers are unchanged after enabling torque.
Cause: V164 only writes the P agreed in the model package (5; kissqy calls it the "deployment contract"); D (register 51) and torque limit (register 48) stay at the servo's factory values (D=40, 1000). This is his intentional design (his design doc says "keep the device's current values"); the "test parameters" path from R17 was removed. The HD-1910's factory EEPROM is P32 / D40 / I0.
→ To tune, use R17; or, with robotd stopped and all 15 servos limp, write the servo RAM (restored on power loss; 「重启舵机」 (restart servos) on gamepad D-pad right also restores it); or change D in EEPROM to 0 (a one-time change; only effective with V164, which doesn't write D; R17 writes its own D when enabling torque, so pair it with kd in the test parameters). The values in the servos before torque is enabled are in `robot.busStatus` → `native.hd1910.registers_before_arm`.
**Addendum (10-14)**: the web console 1.0.164 that ships with V164 never had the P / D / torque boxes (the ones with those boxes are the older console 1.0.146 that ships with R17; connecting the old console to a V164 board, changes don't take effect either). We unlocked these on V164 locally (not on the robot yet, not published); see [10-14 daytime record §8](docs/HD1910-20261014-白天-仿真找原因与新版放开参数.md#8-新版v164放开-p--d--转矩限制和头腿滤波本地未上机).
**Addendum (10-14 evening)**: on 10-14 kissqy released V167 / control.43 (web console 1.0.167), described as "fixing duck body shaking": on every HOME torque enable it writes D=0 and torque limit 1000 into the RAM of all 15 servos, with P still the model's 5; these two values are fixed and can't be adjusted in the web console; on torque release only P is restored, and D stays at 0 until the servos lose power. This matches our conclusion from the night of 10-13 (same tabletop: jitter was 51% at D20, 4–8% after D0). Note: if your duck uses an IMU module (BNO085 etc.), don't directly click 「安装 / 升级固件」 (Install / upgrade firmware) in his web console: his install package carries his own robotd, which doesn't support IMU modules, and after the upgrade the IMU can't be read and torque can't be enabled (see "If you installed your own modified robotd, don't click 'Install / upgrade firmware' in kissqy's web console" under "Software").

**Servo P / D / torque limits are written to RAM: written on every torque enable, restored on release, back to factory values after power loss**
Symptom: on 2026-10-14 the user asked: are the P / D / torque set in the web console permanent, or rewritten every time? After the servos lose power once, or after pressing gamepad D-pad right (restart servos), reading the registers shows the factory D40 / 1000 again.
Cause: R17 and the adjustable version we built on V164 write torque limit, P and D into servo **RAM** (registers 48–51) on every HOME torque enable, recording the original values first and writing them back on release; stock V164 only writes P (register 50) to RAM. Neither touches EEPROM. Once a servo loses power, RAM is reloaded from EEPROM (HD-1910 factory P32 / D40 / I0, torque limit 1000). The configured values are stored in a file on the board (`/etc/robot/feetech-ft5/servo-test-parameters.json`) and automatically rewritten at the next torque enable, so setting them once keeps them in effect; no need to reset them each time.
→ To confirm they took effect, look at `robot.busStatus` → `native.hd1910.servo_parameters` (the values robotd loaded) and `temporary_gains_applied: true` (written and verified by readback); `registers_before_arm` is the original values read before torque was enabled, not the values set. One pitfall: **if robotd was restarted while torque was on** (crash, manual restart, installing software with torque on), the recorded original values are lost. V164 and the adjustable version's robotd release torque on all servos as soon as they start (the duck collapses on the spot, hold it), and at the next HOME record the test values lingering in the servos as the originals; R17 doesn't release torque on startup, it only checks whether the values match the file (if not, it refuses HOME; see "HOME is rejected if another program enabled torque before switching to kissqy" below). Either way, the test values stay in RAM. Continuing with this parameter set is harmless; but after switching back to the original behavior of only writing P (deleting the parameter file, or 「恢复默认」 (Restore defaults) in the web console), D and torque stay at the test values. In that case, power-cycle the servos once. Details in [10-14 daytime record §8.3, §8.4](docs/HD1910-20261014-白天-仿真找原因与新版放开参数.md#83-舵机参数是怎么生效的写-ram不写-eeprom).

**Standing at HOME, the two feet aren't coplanar laterally: both hip rolls splay outward, differently each time (presumably pushed by body weight)**
Symptom: doing forward kinematics from servo readings, when standing at HOME (or stopping after walking), the two soles are not in the same plane in the lateral direction. On 2026-10-14 all 14 segments were computed; relative to HOME the difference was 0.6°–13°, different every segment. At first we suspected the hip roll zero positions were off.
Cause: broken down by joint ([`tools/gait-analysis/home_roll.py`](tools/gait-analysis/home_roll.py)), the difference comes entirely from the left and right hip rolls not tracking the HOME target, always left +, right − (legs splaying outward), with a different magnitude each time (0.2°–6.9°). Per the simulation geometry, the ground reaction force on the foot acts about 23 mm outside the hip roll axis, which is exactly what pries the leg outward, as if pushed by body weight (a guess; the data doesn't show how the offset relates to P). The policy standing in simulation also has errors in the same direction (left +1.6°, right −1.8°), and the real robot is mostly of the same magnitude.
→ The part that changes every time is not the zero position; don't change the zero for it. But be aware: this method compares "reading − target", and both share the same zero, so **it cannot tell whether the zero itself is off**. In the simulation model standing at HOME, both feet already have the outer edge about 2.3 mm lower; splaying out a little actually flattens them, and splaying out too much makes the inner edge lower. To see which edge lifts on the real duck, look from straight ahead along the tabletop at HOME for light underneath, and trust the real thing. On the morning of 10-14 we said verbally that "the outer edge lifts"; for 12 of the 14 segments that was exactly backwards, so go by this entry. Details in [10-14 daytime record §7](docs/HD1910-20261014-白天-仿真找原因与新版放开参数.md#7-站-home-两只脚左右方向不共面两个髋横滚往外劈每次不一样).

**The mouth servo runs hot: it keeps pushing against the closed position and sits next to the board (kissqy's explanation)**
Symptom: the mouth servo is hot to the touch. We measured on the night of 2026-10-12 that the mouth servo is at 60–70°C just while the duck is standing.
Cause: kissqy explained in the group chat: the mouth position is set to −5° (closed), so after closing it keeps pushing and is constantly exerting force; and the mouth is closest to the board, so it's baked by the board's heat. He said "even biting shut all the time it's only around 40-something degrees", so the servo isn't broken. His temperature is lower than what we measured; the reason hasn't been investigated.
→ Don't rush to replace the servo. For board cooling see "The board has no airflow path inside the body" below. Whether to back the mouth's closed position off a little so it doesn't push hard, we haven't tried yet.

**Installing kissqy's R17 takes his prototype's zero positions as your calibration**
Symptom: on 2026-10-12, the first R17 install; this robot had no calibration file, and after installation `hd1910-calibration.toml` showed all 15 joints as "calibrated", with the status even showing "motion ready". But the zeros ranged from 1372 to 2176 with directions both positive and negative (head ID 33 zero 1599), which doesn't match our robot: we calibrated with servo-web, all zeros are 2048 and all directions −1.
Cause: when there's no local calibration, his install script fills it in with the prototype calibration from the package and marks it as calibrated. His notes do say 「包内标定为样机参考，每台需核对」 (the calibration in the package is a prototype reference; check it on each robot), but the installer doesn't stop to ask.
→ After installation, first open `/etc/robot/feetech-ft5/hd1910-calibration.toml`, replace it with your own zeros and directions, then compute each joint angle with `角度 = (读数 − 零位) × 方向 × 2π/4096` (angle = (reading − zero) × direction × 2π/4096; the same formula as servo-web), and only enable torque once they match the physical pose. Don't press HOME before checking.

**kissqy's one-click image R1 also preinstalls his prototype's calibration, with the IMU marked "confirmed"**
Symptom: taking apart his image on 2026-10-12, the zeros in `hd1910-calibration.toml` were from his duck (2281, 2176…), directions all −1, `imu_mount_verified = true`; only `motion_enabled = false` stands in the way.
Cause: the image was made from his prototype. The IMU being "confirmed" refers to the mounting orientation of his bus board; it doesn't hold for a different duck or a different IMU.
→ After flashing, first replace the zeros and directions with your own as in the previous entry, reconfirm the IMU mounting orientation, and only then touch HOME and the motion switch. Details in [kissqy image R1 analysis](docs/HD1910-20261012-kissqy镜像R1分析.md).

---

## Board / HAT / camera

**Check the contact side at both ends of the camera ribbon cable; plugged in doesn't mean connected correctly**
Symptom: the Radxa Camera 8M219 (IMX219) couldn't be read under either Armbian or official B1, reporting `Reading register 100 from 10 failed`, `Error -5`; on 2026-09-28 the user found the ribbon cable might be flipped, and after adjusting it `Model ID 0x0219` was read and 40 frames of 1920×1080 were captured successfully.
Cause: the fault disappeared after adjusting the cable orientation/contact this time; whether the contacts are connected cannot be confirmed just from the plug being inserted or the cable's color.
→ **Shut down properly, cut all power, then check that the exposed metal contacts at both ends line up with the metal springs inside the connectors, insert straight and lock.** ZERO 3W with the Radxa 8M219 uses a **22 pin / 0.5 mm → 15 pin / 1.0 mm, same-side contact** cable; "same side" means that when laid flat, the exposed contact areas at both ends are on the same side, not the copper traces visible under the coating.

<p align="center"><img src="assets/hw/radxa-camera-cable-reference-20260928.png" alt="User-provided camera ribbon cable wiring reference: lens side on the left, back of the board on the right, cable in a U shape" width="380"></p>

*User-provided wiring reference image: the lens is visible on the left, and the Radxa / UKCA markings on the back of the board on the right. After checking the overall relative orientation, still check the contacts inside each connector; for other modules, don't go only by the lens orientation or the printed side of the cable. This image is a wiring reminder, not a frame captured in this session.*

**Seeing `/dev/video0` doesn't mean the camera has been detected**
Symptom: while the camera wasn't responding, the board still had `/dev/media0` and `/dev/video0..9`.
Cause: these may only be Rockchip ISP receiver nodes, with no sensor bound.
→ Confirm in order: the chip ID, the `imx219` driver binding, the sensor entity in `media-ctl -p`, and finally actually capture frames; [full commands and results from this session](tools/radxa/摄像头调试记录-20260928.md).

**Don't guess the two Type-C ports as "one for power, one for the PC"**
Symptom: connected the PC to the USB 3.0 Host port, expecting the board's USB serial port to appear.
Cause: `5V IN / USB_OTG` is the power-plus-USB 2.0 gadget port; USB 3.0 Host is for peripherals like the URT-2 or a USB stick; whether a COM port appears also depends on whether the system has a gadget serial port configured.
→ **When the HAT is powering the board, debug over Wi-Fi + SSH**; on V1.12 the 40-pin 5V and the OTG VBUS are the same net, so you must not introduce a second 5V from the PC through an ordinary USB data cable. To switch to USB power, shut down first and disconnect the HAT input. 7.4V may only go into the HAT's corresponding input, never directly into the board's 5V or USB-C; see the [image usage guide](tools/radxa/镜像使用说明.md#3-第一次开机).

**A double-blinking green LED can be a normal heartbeat, not a fault code on its own**
Symptom: this time on official B1 the green LED double-blinked, but Wi-Fi, SSH and the camera were all fine.
Cause: the LED is configured as `heartbeat`; double blinking was also seen during earlier boot failures, but the accompanying symptom back then can't be used as a general diagnosis.
→ Judge whether the system is up from the network, SSH and boot logs; don't reflash the card based on LED behavior alone.

**When switching to the official image for comparison, if the wiring also changed, you can't attribute the result to the image alone**
Symptom: official B1 also couldn't read the camera at first; it only produced images after the ribbon cable was adjusted.
Cause: the image and the wiring weren't retested together under the same conditions; this session only confirms that camera detection and a short capture pass under the official configuration.
→ Keep the wiring that worked, then retest the original Armbian as needed; don't declare the original image broken, and don't treat a 40-frame short test as acceptance of 30 fps, long-term stability or full HAT functionality.


**Board thermal throttling: a resident web service saturating one core slows the control rhythm**
Symptom: on 2026-10-11 while running the policy, the control period went from 20 ms to 25 ms, with sensor reads taking up to 20 ms; the board CPU was at 84–87°C and `scaling_max_freq` was pushed down to the lowest step of 408 MHz (max 1800).
Cause: while `servo-web/server.py` is resident, top shows it saturating one core (100%), and the board inside the body can't shed heat; the RK3566 throttles at 85°C.
→ Stop the web service before running the policy (`systemctl stop microduck-servo-web`), open up the shell around the board or add a fan; before a run, check `/sys/class/thermal/thermal_zone0/temp` and `/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq`. Why the web service saturates the CPU hasn't been investigated.

**The board freezes a minute or two after boot, green LED solid instead of blinking**
Symptom: on 2026-10-11, after power-on SSH connected, then after about 2 minutes the board vanished from the network, the router couldn't find it either, and the green LED went from blinking to solid. After a power cycle it was fine and didn't happen again for the rest of the night.
Cause: unknown. A solid green LED means the kernel heartbeat stopped (a freeze), not a WiFi drop. The logs from that boot weren't written to the card, so there's nothing to check. A 7.4 V adjustable supply was in use at the time.
→ If it happens again, first note the voltage and current on the supply's meter, then power-cycle; don't keep power-cycling repeatedly.

**Without a camera and ToF connected, the official mediad and tofd keep restarting and overheat the board**
Symptom: on 2026-10-12 after installing official 0.15.1, the board was at 89–90°C with the CPU locked at the lowest step of 408 MHz. In top, mediad's `gst-plugin-scanner` saturated one core (99.5%), and tofd kept restarting too.
Cause: with no camera connected, the camera service crashes on startup, systemd keeps relaunching it, and each time it rescans all GStreamer plugins; tofd does the same when it can't find the ranging sensor. People in the group chat also said that disabling unused services brings the temperature down.
→ If those two aren't connected, `sudo systemctl disable --now mediad tofd`, and `enable --now` once you connect them later. After disabling, it dropped to 85°C within 2 minutes, but that's still at the throttling threshold, so more cooling is needed (see the next entry).

**The board has no airflow path inside the body; even with the services off it heats up to 92°C**
Symptom: after disabling mediad and tofd, running only robotd with the duck standing, the temperature slowly climbed back to 92.5°C, with the CPU at 408 MHz the whole time. Readback timeouts on torque enable were caused by the CPU being too slow; the web joystick not responding was also made worse by it (the root cause isn't just overheating, see [Software](#软件)). On the night of 2026-10-12, with the services all off and the SSH reconnects removed, about 10 minutes after the model started the CPU still reached 85°C and throttled to 408–600 MHz (robotd running the model uses 30%–46% of one core).
Cause: the board has no heatsink inside the body and no path for air in or out. The RK3566 throttles at 85°C, and once at the lowest step every program slows down.
→ Start by drilling a few holes in the head shell or body; that's the simplest and dissipates some heat. To really get it cool, the key is an **airflow path**: somewhere for air to come in and somewhere for it to go out; the fan doesn't have to sit right on the board. Before a session, check `/sys/class/thermal/thermal_zone0/temp` and `/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq`; a frequency of 408000 means it's throttling.

**Full-robot brownout and reboot while walking or standing up: it's power, not software**
Symptom: on 2026-10-13 both the new and old cards suddenly lost power and rebooted while walking or standing up; the recording and system log both cut off at the same time, with no shutdown sequence. The new card (D=40) went down 13 seconds after the model took over, with the servos last reading about 3.9 V; the old card (D=20) lasted 42 seconds after takeover, fell and got back up once in between, and lost power about 11 seconds after getting up, with the joystick at 0 at the time.
Cause: the current surge from a dozen-plus servos exerting force together is more than the supply and wiring can handle; the board's 5 V is stepped down by the HAT from the same supply, so it drops too. The larger D, the more often the model corrects, possibly causing more surges (the new card also had sound on, so one run against one run is inconclusive). robotd reports voltage only every 0.5–1 seconds, so dips of a few tens of milliseconds aren't visible.
→ Use a battery or a high-current supply (10 A), 16–18 AWG wire kept as short as possible, XT30/XT60 connectors, and 1000–2200 µF of capacitance across the input. To tell whether it's the main supply or the HAT's feed to the board: power the board's USB-C separately from a power bank and walk again. kissqy's repo once said 「LM5050 余量不足导致重启」 (insufficient LM5050 headroom causes reboots); he deleted that on 10-12 (author correction), so don't cite it. Details in [10-13 night session record §2](docs/HD1910-20261013-夜-掉电-舵机D与蹭地.md#2-整机掉电是供电不是软件).
**Addendum (10-15 evening)**: the new card rebooted once more (19:31:42), this time with the duck standing still in walk mode without the joystick being pushed; just before, the battery was at 7.59 V and the CPU at 78°C, and the recording file ended with a run of null bytes. It didn't go down during a big motion, so "just a force surge" doesn't necessarily explain it; cause still undetermined; compare once the 10 A supply arrives. See [10-15 record §6.2](docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md#62-整机重启193142).

**Connecting an external IMU module to the HAT's J5: first check which on-board chips already occupy addresses**
Symptom: the J5 bus (40-pin pins 3/5, I2C3) already has on-board chips: both revisions have the aic3104 audio codec (0x18); the C1 revision (the one we have) also has a BMI088, accelerometer 0x19 and gyro 0x68; the D1 revision (latest official) switches to an LSM6DSV16X at 0x6A.
Cause: I²C distinguishes devices by address; two chips at the same address fight each other and neither reads correctly. An external BNO085 (0x4A/0x4B) doesn't conflict on either revision; an external LSM6DSV16X on D1 also at 0x6A would collide with the on-board one.
→ Before connecting, run `i2cdetect -y 3` to see which addresses are taken; for an external LSM6DSV16X on D1 use 0x6B (SA0 tied high), and set `i2c_address = 0x6B` explicitly in robotd. The on-board IMU is in the head, so it can only serve as a head IMU; the external module must be mounted on the torso. If you don't want to use J5, J6 can be converted to I2C4 (remove R18/R19, bridge R16/R17). A pad-by-pad comparison of C1/D1 is in [kissqy image R1 analysis §9](docs/HD1910-20261012-kissqy镜像R1分析.md#9-hat-上接-imu-模块c1旧版咱们手上这块和-d1官方最新版对照).

**IMU module with a bad contact: robotd declares the IMU stale and the duck goes limp immediately**
Symptom: on the night of 2026-10-12 the duck suddenly went limp; pressing Start returned `nothing to bring up state=Limp`, `robotctl health` showed `orientation frozen`, and the robotd log had `trunk IMU reader fault … No such device or address (os error 6)`.
Cause: the BNO085 stopped responding on I²C (nothing answering at the address). During all 77 dropouts the servo voltage was 7.3–7.5 V, so it wasn't power; most happened while swaying during walking, but a few happened while completely still, meaning some point had already come loose. robotd treats a non-updating IMU as a read failure and, after consecutive failures, releases torque as protection, which is itself correct; once the IMU recovers, the driver re-detects it on its own.
→ Solder the wires securely or use a locking connector, fix both ends with hot glue, and leave slack where it passes through the neck; after soldering, recheck with the zero calibration below. [`imu_fault_ctx.py`](tools/radxa/onboard-analysis/) matches each dropout to what the robot was doing at the time and the voltage.


---

## Software

**With Clash's TUN mode on the PC, ping, SSH and the web page all fail to reach the board**
Symptom: on 2026-10-11 the board was clearly online (a port scan showed 22 open), but the PC couldn't ping it, SSH reported `Error reading SSH protocol banner`, and opening `http://192.168.0.102:8080` in the browser gave 502.
Cause: Clash Verge's TUN virtual adapter (Meta) took over all routes including the LAN (`Find-NetRoute` shows traffic going via Meta), so connections to the board were intercepted.
→ Temporarily turn off TUN, or set `192.168.0.0/16` to direct in Clash. If you don't want to touch Clash, binding the connection in your program to the wired adapter's local address (Python `socket.bind(('192.168.0.100', 0))` before connecting to the board) gets around it; for the web page you can set up a local port forward, or open it on a phone.

**On kissqy's one-click image, the G50 Pro gets disconnected a few seconds after pairing successfully**
Symptom: on 2026-10-13 with the new card (kissqy R1 image), gamepad set to S, `bluetoothctl pair` reported success, then it disconnected and padd couldn't read it. The same gamepad worked fine with the old card.
Cause: on this card Bluetooth comes up non-bondable at boot (reason not fully determined), so pairing returns No Bonding and the keys can't be stored; BlueZ's default `ClassicBondedOnly=true` only accepts bonded HID devices, so it's rejected. The official setup-board intentionally sets `UserspaceHID` in `/etc/bluetooth/input.conf` to false (the gamepad goes through the kernel, saving about 16% of one core's CPU; pairing works fine on the official board); whether that played a role wasn't verified.
→ Before pairing run `btmgmt bondable on`, then `pair` → `trust` → immediately `connect`; on success you'll see `Nintendo Switch Pro Controller` and `hid_nintendo`. At the time we also changed `input.conf` to `UserspaceHID=true`, `ClassicBondedOnly=false`, changing several things together; **it only succeeded once, and the next two attempts failed to pair**; `UserspaceHID=true` uses more CPU, so next time try only enabling bondable first.
**Addendum (10-15 evening, same card)**: typing `pair`, `trust` and `connect` as three separate commands, pairing succeeded but the connection was refused by the gamepad (`control_connect_cb() … Permission denied (13)`); pressing HOME on the gamepad to make it reconnect, it connected for 10 seconds and then dropped again, and the gamepad never appeared in the system. What worked: first `btmgmt bondable on`, `btmgmt connectable on`, `bluetoothctl remove <gamepad address>` to delete the old record, then do everything in one go in the **same** `bluetoothctl` session (`agent NoInputNoOutput` → `default-agent` → `scan on` → wait for the gamepad to appear → `pair` → `trust` → immediately `connect`); the padd log showed `pad connected — driving pad=Nintendo Switch Pro Controller`, and WiFi didn't drop. This time `input.conf` was still as modified on 10-13 (`UserspaceHID=true`, `ClassicBondedOnly=false`); which item is actually required wasn't verified separately.

**The G50 Pro only remembers the last card it paired with; switching cards requires re-pairing**
Symptom: after the gamepad was paired with the new card, switching back to the old card, the gamepad can't connect to the old card.
Cause: the gamepad only stores the key from the most recent pairing, while the old card still holds the previous key, so they don't match.
→ Every time you switch cards, pair again on the current card (using the procedure in the previous entry).

**The duck's static IP was taken by another device on the LAN; the PC connects only intermittently**
Symptom: on 2026-10-13 the old card used a static 192.168.0.102, and at the same time another device on the LAN (judging by the MAC address, a phone) also got .102; the PC's connection to the duck kept coming and going.
Cause: the router's DHCP didn't know the duck had manually claimed that address and handed it out to someone else.
→ Set up a 「静态地址分配」 (static address assignment, bound by MAC) for the duck in the router, or set the duck's static IP outside the DHCP range. Temporary workaround: turn off WiFi on the device occupying the address, or, as administrator on the PC, statically bind that IP to the duck's MAC (`netsh interface ip add neighbors`; lost when the PC reboots).

**No logs at all after a full-robot brownout: Armbian's logs are in RAM**
Symptom: after a brownout and reboot, `journalctl` only shows the current boot; the last few seconds of our own recording weren't written to the card either. The board has no RTC and the clock goes back every boot, so you can't even find the right file by time.
Cause: Armbian keeps logs in zram (memory) by default, intentionally not writing to disk to protect the SD card; Python's file buffering only flushes every few seconds.
→ Run one service each for recording and the system log, **fsync once per second**, with the boot number in the file name (first 6 characters of `/proc/sys/kernel/random/boot_id`). Scripts: `duck_rec.py`, `duck_journal.py` and two services in [`tools/radxa/onboard-analysis/`](tools/radxa/onboard-analysis/). Don't disable zram (see "Don't disable armbian-zram-config" below).

**Armbian ships with `overlay_prefix=rk35xx`, but the RK3566's overlays are named `rk3568-*`**
With the wrong prefix the loader finds nothing and fails silently; the board boots normally, **but there's no `/dev/ttyS2`**. You'll think the wiring is wrong. An `apt upgrade` that replaces the kernel may revert it.
→ In `/boot/armbianEnv.txt` change it to `overlay_prefix=rk3568`, add `overlays=uart2-m0`, and reboot. The official `setup-board.sh` does exactly this.

**The kernel console is also on ttyS2 by default**
UART2 is the RK3566's debug serial port, and Armbian sends kernel logs there, which means onto the servo bus.
→ Remove `console=ttyS2,1500000` from `extraargs` in `/boot/armbianEnv.txt`.

**Armbian runs a login console on UART2 by default**
`agetty` holds `/dev/ttyS2`, and the servos never respond. If the wiring is right and it still doesn't work, it's most likely this.
→ `systemctl mask serial-getty@ttyS2`, then `fuser -v /dev/ttyS2` to confirm no other process has it.

**Don't disable armbian-zram-config**
Armbian keeps logs in zram (memory) by default without writing them to disk, which protects the SD card. Some people disable it to make reading logs easier, multiplying the write volume several times.
→ Keep it. The official `deploy/README.md` says verbatim that not writing to disk is "an intentional arrangement", and disabling it is "each board's own decision, not the default".

**Using i2c3 on pins 3/5 loses USB-C PD negotiation**
The RK3566's i2c3 originally runs on the M1 pinmux serving the FUSB302 (USB-C PD). The official overlay muxes it to M0 (pins 3/5) and disables the fusb302.
→ Accept the trade-off: USB-C still supplies 5 V, it just doesn't negotiate. The robot is powered from the battery, so this doesn't matter.

---

**`wsl --mount` can't mount a USB card reader; don't count on it to write files into a flashed card**
Trying to use WSL2 to write Armbian's first-boot preset `.not_logged_in_yet` into the card's ext4 root partition, `wsl --mount \\.\PHYSICALDRIVE2 --partition 1` immediately reports `Wsl/Service/AttachDisk/MountDisk/HCS/ERROR_FILE_NOT_FOUND`. This is a WSL limitation for USB removable disks, unrelated to whether the card was flashed correctly.
→ Do it the other way round: put the file into the image first, then flash. In WSL, extract the `.img.xz` to a local disk (not under `/mnt/`, loop mounting won't work there), mount the root partition with `mount -o loop,offset=$((32768*512))`, write the file, then flash the resulting `.img`. The script is in [`tools/radxa/`](tools/radxa/).

**The Armbian images tested earlier hang at boot on the Zero 3W V1.12 (AIC8800 WiFi version): judge from logs and the system disk**
Zero 3Ws shipped after 2024-11 are V1.12; flashing the Armbian 26.2.1 / 26.8.1 vendor images, the LED shows a heartbeat double blink (the kernel started), but it never even reaches initramfs, not a single byte of the system disk is touched, and it never shows up on the LAN.
Radxa's official image boots first time on the same card and board. After ruling things out one by one (card, SDR104 high-speed mode, power, device tree all identical), the only difference left is the bootloader:
for zero3, Armbian uses mainline U-Boot 2025.10 + the 2024-01 memory init firmware v1.21; Radxa's own is rk U-Boot 2017.09 + DDR v1.23 (2024-09) + BL31 v1.45.
→ Write `idbloader.img` / `u-boot.itb` from Radxa's `u-boot-rk2410` package to sectors 64 / 16384 of the card, then write a `/boot/extlinux/extlinux.conf` for Armbian (Radxa's U-Boot uses extlinux and doesn't read boot.scr); with the kernel and system unchanged, it boots immediately.
The script is in [`tools/radxa/`](tools/radxa/) and makes the card in one step. Ways to locate this kind of problem without a serial console: read the card to see whether the root partition has been written, and put LED signals and black-box logs into the initramfs.

**On V1.12J (the 2026-09 batch), swapping the bootloader isn't enough; the device tree has to be swapped too**
Symptom: after swapping in the Radxa bootloader per the previous entry, Armbian still won't boot; Radxa's official B1 image does. Someone also found that a cold boot with HDMI plugged in won't start.
Cause: this batch of boards switched WiFi to the AIC8800DS2, which Armbian's bundled `rk3566-radxa-zero3.dtb` doesn't support; the one in Radxa's B1 image does.
→ Take **both the bootloader and the DTB from the B1 image**, point extlinux's `fdt` at the copied one, and keep Armbian's kernel and root filesystem
(both sides are 6.1 vendor kernels, so they can be mixed). A group chat member got it working on 2026-09-20. After swapping the DTB, remember to check that `/dev/ttyS2` and the USB serial port are still there;
the overlays are Armbian's, and their nodes may not match. Commands are in the [image usage guide](tools/radxa/镜像使用说明.md#6-如果你的板子不是这一批).

**After switching to the Radxa bootloader, editing `armbianEnv.txt` has no effect**
Symptom: added an overlay (e.g. `i2c3-pihat`) to `overlays=` in `/boot/armbianEnv.txt`, but after rebooting there's still no `/dev/i2c-3`; the same happens when the official `setup-board.sh` edits it, though the script's own check says it's configured.
Cause: Radxa's U-Boot only reads `/boot/extlinux/extlinux.conf` and doesn't run Armbian's `boot.scr`, and it's `boot.scr` that reads `armbianEnv.txt`.
→ Overlays must go on the `fdtoverlays` line of `extlinux.conf`, with the full dtbo path (`/boot/dtb/rockchip/overlay/rk3568-xxx.dtbo`); confirm the file exists before rebooting.

**The AIC8800 doesn't support GCMP-256; with the router in WPA3 mixed mode it can't connect**
The Zero 3W V1.12's AIC8800D80/DS2 only has CCMP-128. Home routers (TP-LINK and the like) default to WPA2/WPA3 mixed, and the WPA3 half uses GCMP-256, so the handshake fails.
→ Force `key_mgmt=WPA-PSK`, `pairwise=CCMP`, `ieee80211w=0` in wpa_supplicant (the card-making script already does this), or switch the router to pure WPA2. Both 5 GHz and 2.4 GHz work.

**No USB serial port when the board is plugged into a PC: you need the `dwc3-peripheral` overlay**
The Zero 3W's OTG port is `dr_mode = otg` in the device tree; under the Armbian vendor kernel it won't automatically switch to device mode when plugged into a PC, and even with `g_serial` loaded the PC sees nothing.
→ Load `rk3568-dwc3-peripheral.dtbo` (bundled with Armbian) in extlinux, then `g_serial` + `serial-getty@ttyGS0`; plug into the PC and an extra COM port appears with direct root login, a lifesaver in emergencies. The card-making script already does this.

**Running the official scripts on the board, GitHub downloads stall**
`setup-board.sh` / `install.sh` both download from raw.githubusercontent.com, api.github.com and objects.githubusercontent.com; direct connections from China basically hang (IPv6-first makes it worse).
→ Turn on 「允许局域网」 (Allow LAN) in Clash on the PC and write `http_proxy=http://<PC IP>:7890` into the board's `/etc/environment` (in the card-making script, just fill in `HTTP_PROXY=` in `card.conf`). apt uses Debian mirrors and needs no proxy.
Note: the official installation has updaterd invoke the install hooks, and curl in the hooks doesn't read `/etc/environment`. On 2026-10-12 downloading ONNX Runtime directly timed out after 90 seconds; after writing `/root/.curlrc` for root (one line: `proxy = "http://<PC IP>:7890"`), it downloaded in two seconds. Remember to delete it after installing.

**The official install.sh only installs the latest version, but kissqy's R17 needs 0.15.1**
Symptom: kissqy's R17 sits on top of official `daemon-v0.15.1`; by 10-07 the official release was already at 0.16.1, `install.sh` always installs the latest, and there's no switch to pick a version.
Cause: the script has updaterd look up latest on GitHub by itself.
→ First download the `daemon-v0.15.1` release files locally, copy `install.sh`, hard-code the release tag as `daemon-v0.15.1`, and add `--from <local directory>` to `updaterd install`. Signature verification still happens. The modified script is at `Radxa-Zero3W/official-daemon-v0.15.1/scripts/install-local.sh`. After installing, change `auto_apply` in `/etc/robot/updater.toml` to `"off"` so it doesn't upgrade itself.

**If you don't need sound, don't run the audio part of the official setup-board.sh, and don't run migrate-network.sh remotely**
Symptom: the audio step of `setup-board.sh` apt-installs the Armbian vendor kernel and points `/boot/Image`, `dtb` and `uInitrd` at the new kernel; `migrate-network.sh` switches WiFi from netplan to NetworkManager.
Cause: the V1.12 board relies on Radxa's U-Boot and `extlinux.conf` to boot, so swapping the kernel remotely risks a board that won't boot. That step only enables the audio chip on the HAT, and walking doesn't need sound; without a HAT it's even less useful. If WiFi drops while switching networking, you can't connect back remotely.
→ If you don't need sound, neither needs to run: the servo serial overlay and moving the serial console out of the way were already handled when making the card. Walking only needs the services installed by the official `install.sh`.

**Installing kissqy's R17 without an aic3104 sound card in the system hangs at audio setup**
Symptom: `service.sh upgrade` stops at `alsactl store aic3104` with exit code 19 and the message 「安装未完成；阶段：audio-setup」 (installation incomplete; stage: audio-setup).
Cause: his install script assumes this sound card is always present. Without a HAT, or with a HAT but without running the audio step of the official `setup-board.sh` (as was the case for the first robot on 2026-10-12), the system only has the HDMI sound card.
→ Our branch has fixed this (skips audio setup when the sound card is absent; walking is unaffected). With his original package, you can first modify `voice-setup.py` in his package and then recompute `SHA256SUMS`.

**kissqy's one-click image R1 uses Armbian's stock bootloader; V1.12 boards may not boot**
Symptom: taking apart his image R1 on 2026-10-12, the boot area is Armbian mainline U-Boot 2025.10 + memory init firmware v1.21, using `boot.scr`; our first robot (V1.12, AIC8800) got stuck on exactly this combination in September.
Cause: his board boots, so his batch gets along with this bootloader; whether all V1.12 boards fail can't be generalized, but ours definitely does.
→ Use [`tools/radxa/kissqy-r1-v112.sh`](tools/radxa/kissqy-r1-v112.sh) to swap in the Radxa bootloader on his image and write extlinux (carrying his overlays over unchanged), leaving everything else alone. Verified offline: the boot area is byte-for-byte identical to Radxa's package, the partition table is untouched, and only the expected few changes were made to the root partition. **Not yet tested on the robot**; try it on a blank card first, don't flash the card you're currently using. V1.12J may also need the device tree swapped per the entry above.

**kissqy's one-click image R1 only supports the IMU board on the bus; IMU modules don't work**
Symptom: the robotd in the image (control.40) only has code for reading ID 200, requiring the board identity `06 00 00 00 F2` (his FT6 firmware), with no code for reading an I²C IMU; the boot configuration doesn't enable I2C4 either. Ducks with BNO085 or LSM6DSV16X modules flashed with it get stuck at 「Feetech ID 200 无应答」 (Feetech ID 200 not responding).
Cause: his full stack was built for his own hardware. The I²C IMU support we added to robotd (branch `hd1910-trunk-imu-i2c`) was written on the v146 source, and his V164 source hasn't been published yet.
→ If you use an IMU module, keep using the v146 + I²C IMU stack you installed yourself (see the [10-12 session record](docs/HD1910-20261012-kissqy整套上机.md)); once he publishes the V164 source, port the patch over, or ask him to merge it into the image.

**`service.sh init` can't send HOME while robotd is running**
Symptom: in motion mode, `sudo bash service.sh init` reports `cannot claim robot IPC socket … another robotd owns this socket`.
Cause: the `robotd init` subcommand needs exclusive robotd lock and is only meant for when robotd isn't running. His web console sends JSON-RPC over `/run/robotd.sock` (one per line, `{"jsonrpc":"2.0","id":1,"method":"robot.init","params":{}}`).
→ Use HOME in the web console, or send `robot.init` to the socket yourself. Use `robot.enable` (`{"on":true}` / `{"on":false}`) to enable/stop the policy, and `robot.relax` to release torque.

**The web joystick doesn't respond: four layers of causes stacked together, not just overheating**
Symptom: on 2026-10-12 kissqy's web console (R17 v1.0.146) connected and all the data was normal, but clicking HOME or Start on the web gamepad did nothing. The console log said 「输入已过期，未发送」 (input expired, not sent) or "timed out", and padd occasionally reported `Failed to open "/dev/input/event4"`.
Cause: every button press opens a new SSH connection, starts webpad on demand, creates a virtual gamepad and waits for padd to recognize it; all four layers are slow. ① Armbian wastes 3.8 seconds on a welcome script on every SSH login; ② the web console discards the input if the channel isn't open within 0.4 seconds; ③ webpad's cold start plus padd recognizing the gamepad takes 1–2 seconds, so a quick click-and-release loses the press; ④ padd tries to open the new device before the system has finished registering it, and doesn't retry on failure (same when running padd as root, so it's not a permissions issue). In the early hours we thought it was just overheating; overheating only makes every layer slower.
→ Use a physical Bluetooth gamepad (next entry), which bypasses the whole path. If you still want the web gamepad, first disable the SSH welcome script (the entry after next) and hold buttons for 1–2 seconds before releasing. kissqy has already changed the web gamepad in V164 to go directly through robotd. Layer-by-layer measurements are in the [10-12 night session record](docs/HD1910-20261012-夜-IMU校准与首次迈步.md#1-网页手柄按了没反应四层原因叠在一起).

**ThundeRobot G50 Pro as a physical gamepad: set the switch on the back to S and pair it directly with the duck over Bluetooth**
Symptom: the gamepad's 2.4G receiver plugged into the PC is useless for the duck: the web console doesn't read gamepads on the PC, and the receiver can't be plugged into the board inside the head.
Cause: both the official and kissqy designs pair a Bluetooth gamepad directly with the board, and padd reads it. The X / S / T / D switch on the back of the G50 Pro selects the platform, not wired vs. wireless; in S mode it presents itself as a Switch Pro Controller, which the board's kernel supports out of the box and the official pairing tool also supports.
→ Unplug the receiver from the PC, set the back switch to S, and with the gamepad off hold HOME until the light blinks fast; on the board run `sudo systemctl start configd`, then `sudo robotctl pad pair`. If it isn't found, use `bluetoothctl` to scan for the `Pro Controller` address and run `robotctl pad pair <address>`. Once paired it reconnects automatically. "≡" is Start (first press HOME, second press model takeover), "⧉" is Select (release torque). In the board config, X is bound to a forward roll, so don't press letter buttons at random.
**Addendum (10-21, replica image 20261021b, third duck): on our image, set the switch to X; S doesn't work.** Pairing in S mode from the Studio gamepad page: the helper (official `robotctl pad pair`) reported paired, but the kernel never showed an input device for the gamepad, padd never saw it, and the gamepad switched itself off after a few tens of seconds; in X mode (Xbox) it connected right away, and e-stop and walking worked normally. Cause not yet determined: at the time the duck's Bluetooth was "non-bondable, non-connectable", and no pairing record was left in `/var/lib/bluetooth` (but 「忘掉」 (Forget) was clicked twice in between, which may be why the records were gone). Next time, capture with `btmon` while pairing in S mode.

**Armbian wastes 3.8 seconds on a welcome script on every SSH login**
Symptom: SSH logins are slow; tools that open SSH frequently (kissqy's web console gamepad, ToF channel) time out as soon as they're used, and the board CPU stays busy.
Cause: `pam_motd.so motd=/run/motd.dynamic` in `/etc/pam.d/sshd` makes every login run `/etc/update-motd.d/`, of which `20-ip-info` alone takes 2.9 seconds, 3.8 seconds in total.
→ Back it up first, then comment out that line (keep the `pam_motd.so noupdate` line). After the change, a request-response over SSH went from 3–4 seconds to 0.7 seconds.

**Without ToF connected, kissqy's web console reconnects over SSH every 5 seconds**
Symptom: in 10 minutes the board got 112 SSH logins, each also running the welcome script from the previous entry.
Cause: tofd is disabled (no ToF connected), and after the web console fails to subscribe to ToF it retries forever, each retry being a full SSH login.
→ If no ToF is connected, don't let the web console subscribe to it; the web console in our branch added `--tofd-socket ""`.

**Gamepad Start needs two presses: the first is HOME, only the second is model takeover**
Symptom: after standing up, pushing the joystick does nothing, with the log saying `the policy is not driving — press Start on the pad`; sometimes pressing a second time makes it go back to HOME once more.
Cause: the first press only locks the joints in the standing pose without starting the model; the model takes over on the second press, and only then does the joystick work. Before takeover robotd also checks the standing pose: every joint within ≤5° of HOME and body tilt ≤10° for 3 consecutive frames; if it fails, it goes back to HOME again.
→ After it stands up, take your hands away, wait until it's steady on its own, then press the second time. If rejected, look at which check failed: knees collapsed, IMU off, or body tilted.

**If the Armbian first-boot preset is missing two variables, it stops at a prompt waiting for keyboard input**
Without `PRESET_DEFAULT_REALNAME` in `/root/.not_logged_in_yet` it stops at "Please provide your real name"; without `PRESET_CONNECT_WIRELESS` and no network, it stops at "Connect via wireless? [Y/n]". A headless board gets stuck right there, and the password stays the factory root / 1234 forever.
→ Write both (the card-making script already does).

**kissqy's source has two copies of `padd.service`; the install package installs the one in `packaging/`**
Changing padd's systemd settings (e.g. allowing `AF_INET` for the UDP gamepad) only in `padd/systemd/padd.service` has no effect on the robot. kissqy's install script (`packaging/gamepad.py`) copies `packaging/padd.service` into `/etc/systemd/system/`; the copy in `padd/systemd/` is for upstream development.
→ Change both, then update that line in `packaging/SHA256SUMS`. For boards already installed, don't reinstall; patch with a drop-in: put a `.conf` under `/etc/systemd/system/padd.service.d/`.

**Cross-compiling padd fails with a `libudev-sys` build error**
The gilrs crate padd uses to read the gamepad links against libudev, and `cargo board` cross-compilation can't find an aarch64 libudev (robotd and robotctl don't depend on it, so this didn't come up before).
→ Use the repo's own `scripts/cross-sysroot.sh` to fetch arm64 packages from Debian and unpack them into a sysroot; in China set `DUCK_DEBIAN_MIRROR=https://mirrors.ustc.edu.cn/debian`; when it finishes, copy the `export` lines it prints into the current shell, then run `cargo board -p padd`.

**The official new versions and kissqy's version each bump the interface version number independently; the same number means different things**
When porting features from the new official version onto kissqy's base, it's easy to assume "similar version numbers mean compatible". kissqy went from official 0.15.1's 37 up to 40 on his own, while official went from 37 to 41 in 0.17.1, and the interfaces added on each side differ.
→ When porting features, check one by one that each interface you call exists in kissqy's robotd (this time `sit_toggle`, `robot.policies.sitting` and both sound calls were checked); don't drop in the official client code wholesale.

**The "repair gamepad connection" in kissqy's new web console only supports the GameSir Nova 2 Lite; it does nothing for the G50 Pro**
Symptom: on the evening of 2026-10-13, after switching to kissqy's new version (web console R17 V164 1.0.164), the ThundeRobot G50 Pro couldn't connect; kissqy suggested clicking 「修复手柄连接」 (repair gamepad connection) in the web console.
Cause: this feature (`console/gamepad_repair.py`) was written specifically for the GameSir Nova 2 Lite: the gamepad name is hard-coded, and the repair clears the current connection, re-pairs, then goes through gamesir-xboxd to turn it into a virtual Xbox controller (kissqy's explanation: the official stack only accepts Xbox controllers; other gamepads connect over Bluetooth but fail authentication and get stuck). For any other gamepad it just refuses and doesn't delete the G50 Pro's pairing, so it does nothing for the G50 Pro. The cause we found for the G50 Pro failing on the new card is something else: Bluetooth is "non-bondable" and pairing returns No Bonding (see "On kissqy's one-click image, the G50 Pro gets disconnected a few seconds after pairing successfully" above).
→ Pair the G50 Pro manually per [10-13 night §1.2](docs/HD1910-20261013-夜-掉电-舵机D与蹭地.md#12-g50-pro-配对上又被断开) (`btmgmt bondable on` → `pair` → `trust` → immediately `connect`), or use the new version's web gamepad for now (kissqy says it now keeps a persistent SSH connection). If you want his "repair" feature, buy the Nova 2 Lite he pairs it with.

**If you installed your own modified robotd, don't click "Install / upgrade firmware" in kissqy's web console**
Symptom: this button replaces the robotd on the board. The I²C IMU support we added to robotd and the P / D / torque set by the local adjustable version would all be wiped (determined by reading the code; never actually clicked).
Cause: it reinstalls the robotd bundled in kissqy's install package; his install script also deletes `servo-test-parameters.json` (intentionally, to clear manual parameters from older versions).
→ Our local web console blocks this button when connected to our adjustable board; but connecting with kissqy's original web console, or connecting to an old card (R17 plus the I²C IMU patch) with the old web console, nothing blocks it, so don't click it. If you really want to go back to the original, install with kissqy's original web console, and then power-cycle the servos once (see "Servo P / D / torque limits are written to RAM").

**In the fork's calibration mode, Studio always shows "main program starting"**
Symptom: on 2026-10-20 with a new card, the main program was running in calibration mode (`--commissioning`) and the servos and IMU were being read, but Studio kept showing 「主程序启动中」 (main program starting) with no readings at all, so the first two steps of the onboarding checklist couldn't be done.
Cause: during startup `robot.busStatus` returns a startup report (`phase: configuring_bus`). Motion mode clears it after the first successful read, but calibration mode never does, so it always returns `configuring_bus` and the live snapshot (`ready`, `last_sample`) is never provided. It wasn't caught on the PC because our mock main program was written according to "assumed behavior" and returned snapshots as soon as calibration mode started.
→ Fork `341b68f`: calibration mode also clears it after the first successful read. On older fork builds, the telltale sign is `phase` stuck at `configuring_bus` while `total_success` keeps increasing. Mock main programs and test data must reproduce replies exactly as recorded on the real robot.

**With Clash on the PC (system proxy), `http://duck-xxxx.local:8000` gives 502**
Symptom: on 2026-10-21 the duck joined the home WiFi; opening `duck-0de6.local:8000` in the browser gave 502, while the IP and `duck-0de6:8000` both worked.
Cause: Clash's system proxy bypass list is `localhost;127.*;192.168.*;10.*;172.16-31.*;<local>`. `<local>` only covers names without a dot; `.local` has a dot, so it's treated as an external domain and sent to the proxy.
→ On Windows use `http://duck-xxxx:8000/` without `.local` (goes through LLMNR, which is in the bypass list), or just use the IP; on Apple devices use `.local`; if you use TUN mode, set the LAN to direct in your proxy software. Studio and the manual already give addresses per device.

**Self-made image, SSH port 22 refuses connections: not a single host key was generated**
Symptom: on 2026-10-21 with version 2 of the acceptance card, the duck responds to ping and the web page opens, but SSH port 22 refuses connections outright.
Cause: Debian's `sshd-keygen` only runs on "first boot" (`ConditionFirstBoot`). When making the image, `/etc/machine-id` was emptied to an empty file, which systemd doesn't treat as first boot, so the keys weren't generated, `sshd -t` failed, and ssh couldn't start.
→ Add a drop-in to `ssh.service` that runs `ssh-keygen -A` (leaves existing keys alone) and then `sshd -t` before every start. When making images, don't count on "first boot" to do things automatically; write what needs doing into a service yourself.

**Skipping both steps 1 and 2 of the onboarding checklist, after writing to the main program it's still in calibration mode**
Symptom: on 2026-10-21 with a new card, the servo zeros had been calibrated before and we didn't want to recalibrate the IMU, so the first two steps were skipped; after step 3 wrote the config, the main program came up and still didn't enter motion mode.
Cause: the fork only enters motion mode when "the orientation of the IMU in use has been confirmed". Skipping step 2 means the orientation was never confirmed.
→ Studio step 3: if step 2 is marked done or skipped and the orientation hasn't been confirmed, it writes the default mounting and marks it confirmed (official mounting for the bus board, the fork default for the BNO085, x down and z forward for the LSM6DSV16X module). If yours is mounted differently, calibrate once while standing before writing.

**In calibration mode the duck can't stand up; it can only move one servo at a time, releasing torque after each move**
Symptom: we wanted to calibrate the IMU while standing first, then write to the main program. Studio's 「站姿使能」 (enable standing pose) is grayed out in calibration mode, so the only way was to first write a calibration with the IMU in its default mounting, switch to motion mode, then stand.
Cause: the fork's calibration mode only has single-servo moves (release torque once in position), centering and recording zeros; there's no "hold the whole body standing".
→ Fork `f4bbe53` added `hold-home`: all 15 servos move to HOME together over 3 seconds and lock, the IMU keeps reading and e-stop works as usual. In calibration mode Studio's 「站姿使能」 calls it directly. It doesn't balance, though, so hold the robot. Written on 10-21, not yet tested on the real robot.

**On a new card's first power-up, the duck's hotspot takes about 2 minutes to appear** (changed in 20261021b)
Symptom: on 2026-10-21, on the first boot after flashing, the phone searched for two minutes before `Microduck-xxxx` showed up.
Cause: first boot itself has to expand the partition, set the name and detect the IMU; the network setup program also first has to confirm that it "can't connect to any WiFi" for a full 45 seconds before opening the hotspot. A new card has no WiFi saved at all, so those 45 seconds are wasted.
→ From 20261021b: when there are no saved WiFi networks at all, the hotspot opens at the first tick without a connection; if it can't determine whether WiFi networks are saved, it still waits 45 seconds as before. With older images, just wait a bit longer.
