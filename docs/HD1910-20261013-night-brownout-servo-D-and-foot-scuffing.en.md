# 2026-10-13 night to 10-14 early morning · New card on the robot, whole-robot brownout, servo D and jitter, foot scuffing analysis

**English** · [简体中文](HD1910-20261013-夜-掉电-舵机D与蹭地.md)

**Robot**: unit #1 (Feetech HD-1910 ×15, Radxa Zero 3W 2G without eMMC + microSD, official HAT revision C1, BNO085 on I²C). Powered by an 8.2 V bench supply.
**Two cards**:
- **Old card**: our own Armbian build running kissqy's R17 (v146) plus our I²C IMU patch; this is what it walked with on the night of 10-12;
- **New card**: kissqy's one-click image R1 (V164) plus our IMU patch (`microduck-zero3w-0.15.1-R1-V112-imu.img`).

**Walking model**: kissqy's "walking + fall recovery joint 9600 iterations" (all data in §5–§7 was from the old card).
**Background**: [10-12 night on-robot log](HD1910-20261012-夜-IMU校准与首次迈步.md); after IMU calibration it could stand and step with alternating legs, but the walk was jittery and the feet scuffed.

**One-line conclusions**:
1. **The whole-robot brownout is a power supply problem, not software**: it happened on both the new and old cards; recordings and logs cut off at the same moment with no shutdown sequence; on the new card the last servo-side reading was about 3.9 V.
2. **The jittery walk is related to the servos' D (hardware damping)**: the servo model used in training has no D term, but the real servos have D=20 or D=40. After setting D to 0, the high-frequency jitter share of the body sway dropped from 51% to 4–8%. We now use **P3 / D0 / torque limit 700**.
3. **Foot scuffing is because both feet lift only half as high as in simulation**: the stance knee can't straighten; the model wants it straight but on the real robot it stays bent. The left foot looks like it scuffs more because its toe points down when it steps; this and "the body pitches further forward when the right leg is in stance" **only appeared after D was set to 0** (not with D=20). The IMU roll zero has been corrected; joint zero positions agree left and right in the fore-aft direction, but in the lateral (roll) direction the two feet computed about 1.6°–2.6° apart, cause not yet found (§6). **Addendum (10-14 daytime)**: we looked into the feet not being coplanar; the difference comes from both hip roll joints splaying outward, differently each time, apparently pressed by body weight (a guess). After aligning the simulation with the real robot's action scale and filtering, and estimating mass from kissqy's training model, the stance knee in simulation is now close to the real robot (and that simulation set jitters). See the [10-14 daytime log](HD1910-20261014-白天-仿真找原因与新版放开参数.md).

| | Current state |
|---|---|
| Which card | Old card (R17 can set P/D/torque); new card kept aside until power is sorted out |
| Servo parameters | P3 / D0 / torque limit 700 (set in the web console's "高级参数" (Advanced parameters), takes effect on the next HOME) |
| IMU | On 10-12 corrected 8.54° forward pitch and 1.78° right roll; on 10-14 corrected roll back by 1.14° (§6) |
| Walking | Step frequency 2.8–2.9 Hz (simulation 3.2 Hz); body roll sway 30–36°/s, same as simulation's 31°/s; no high-frequency jitter |
| Still unresolved | Foot scuffing (both feet lift 3–6 mm, simulation 11–12 mm); power (10 A supply arriving 10-16) |

---

## 0. Issues at a glance

| # | Symptom | Root cause | Fix | Details |
|---|---|---|---|---|
| 1 | On the new card the G50 Pro pairs successfully, then disconnects a few seconds later | At boot this card's Bluetooth is "not bondable", pairing returns No Bonding, and BlueZ's default `ClassicBondedOnly=true` rejects unbonded HID devices; whether the official setup-board's `UserspaceHID=false` played a part was not verified | Run `btmgmt bondable on` before pairing and connect immediately after pairing; at the time we also changed `UserspaceHID=true` and `ClassicBondedOnly=false`. Several changes at once, and it only worked once | §1.2 |
| 2 | Both old and new cards brown out entirely while walking or standing up | The power supply can't handle the servos' current surges (on the new card the last servo-side reading was about 3.9 V) | Battery or 10 A supply, short thick leads, large capacitor across the input | §2 |
| 3 | Changing scale and filtering in `robotd.toml`: the before/after comparisons were wasted | The joint model uses the `deployment-execution.json` in its own package; those toml values don't apply to it | Change the joint model's execution parameters (§4.1) | §4 |
| 4 | Changing P/D/torque limit in the web console on the new card has no effect | V164 only writes P (the P=5 agreed in the model package, which kissqy calls the "deployment contract"); D and torque limit stay at the servos' factory values (D=40, 1000); R17's test parameter feature was removed | Use the old card, or write servo RAM after every power-up (§4.2); on 10-14 we added it back to V164 locally (not yet on the robot, [10-14 §8](HD1910-20261014-白天-仿真找原因与新版放开参数.md#8-新版v164放开-p--d--转矩限制和头腿滤波本地未上机)) | §4 |
| 5 | Jittery walk, 4 Hz shuffling steps, irregular rhythm | Related to the servos' hardware D (the servo model used in training has no D); with D=0 the jitter drops noticeably, mechanism not proven | D=0, P3 (costs in §7) | §5 |
| 6 | Body constantly leans about 2° to the left | Partly because P3 is too soft and the legs get compressed when standing; partly because the IMU roll zero is about 1.1° off | Corrected IMU roll back by 1.14° | §6 |
| 7 | Feet scuff while walking, especially the left | The stance knee can't straighten, so both feet lift only half as high as in simulation; after D=0 the left toe points down when stepping | To be investigated; first try an intermediate D (§7.5); for the 10-14 simulation comparison see [10-14 §2](HD1910-20261014-白天-仿真找原因与新版放开参数.md#2-对齐条件以后撑地膝盖接近了但仿真多出了颤) | §7 |

---

## 1. New card on the robot

### 1.1 Booting and network setup

- After switching the V1.12 board to Radxa's bootloader, **the real robot booted successfully** (method in [kissqy image R1 analysis](HD1910-20261012-kissqy镜像R1分析.md)).
- On first boot, the duck opens its own hotspot. Connect to the hotspot with a PC's wireless adapter, open the network setup page and enter your home WiFi. **The setup page requires a login password of at least 12 characters**; shorter ones are rejected.
- The new card manages WiFi with NetworkManager (the old card used wpa_supplicant), and the login user is `radxa`.

### 1.2 G50 Pro pairs, then gets disconnected

**Symptom**: with the gamepad in S mode, `bluetoothctl pair` reports success, but it disconnects a few seconds later and padd can't read the gamepad. The same gamepad works fine on the old card.

**Cause** (not verified item by item):
1. At boot our card's Bluetooth is "not bondable" (bondable off; we didn't find out why), so the gamepad's pairing returns **No Bonding** and the keys can't be stored; BlueZ's `ClassicBondedOnly=true` (the default) only accepts bonded HID devices, so it's rejected as soon as it connects;
2. The official `scripts/setup-board.sh` **deliberately** sets `UserspaceHID` to `false` in `/etc/bluetooth/input.conf`: the Pro Controller sends about 200 packets per second, and routing them through bluetoothd (the Bluetooth daemon) eats about 16% of one core's CPU, versus 0 through the kernel (measured by the official team; pairing and reconnecting are unaffected). kissqy's image keeps this step. Whether it played a part in this problem was **not verified**.

**What we did**:
- `/etc/bluetooth/input.conf`: `UserspaceHID=true`, `ClassicBondedOnly=false` (original backed up as `.bak-20261013`), then restarted bluetooth. **These two and bondable were changed together; we didn't test which one is actually required**. Per the official measurements, `UserspaceHID=true` makes bluetoothd use about 16% more CPU, and the board already runs hot, so next time first try "only bondable on, keeping the official `UserspaceHID=false`";
- Pairing order: `btmgmt bondable on` → `bluetoothctl pair <MAC>` → `trust <MAC>` → **immediately** `connect <MAC>`. On success you'll see `Nintendo Switch Pro Controller` and the `hid_nintendo` driver;
- We keep kissqy's `configd` off with duck-quiet, so run `systemctl start configd` before re-pairing.

Following this procedure it paired once on the new card (after which we ran into the WiFi dropout in §1.3 and the brownout in §2). We later tried re-pairing twice without success and switched back to the old card before finding out why, so **this procedure still needs to be run through completely on the new card again**.

### 1.3 Other changes (all reversible)

| What changed | Why |
|---|---|
| WiFi switched to 5G, PMF (Protected Management Frames) disabled on both WiFi connection profiles in NetworkManager | On the new card WiFi dropped about 10 seconds after the gamepad connected (`ssid-not-found`, signal −19 dBm, so not a weak signal). The old card's WiFi setup had PMF disabled. Not retested on its own after the change |
| Watchdog 15 s, `kernel.panic=5`, `panic_on_oops=1` | If the system hangs, it reboots by itself in about 15 seconds without pulling power; after reboot, check `/sys/fs/pstore` for kernel crash logs |
| Black box: `duck-rec` (50 Hz state + voltage and temperature every 0.5 s), `duck-journal` (system log copied to the card in real time) | Armbian's logs live in RAM and are lost on power loss. Changed to write to disk once per second, with the boot number in the file name (the board has no RTC, so the clock rolls back on every boot and files can't be found by time). Scripts in [`tools/radxa/onboard-analysis/`](../tools/radxa/onboard-analysis/) |

---

## 2. Whole-robot brownout: it's the power supply, not software

**Symptom**: while walking or standing up, the whole duck suddenly loses power and reboots. Recordings, system logs and health records cut off at the same moment, **with no shutdown sequence at all**. It happened on both the new and old cards:
- New card (P5 / D40 / torque 1000, V164, sound on, joint scale 1.0): browned out after 13 seconds of walking under the model; at the last moment the servos read about **3.9 V**;
- Old card (P5 / D20 / torque 1000): 42 seconds under the model, during which it fell and got up by itself once (log `LB recovery started`); about 11 seconds after getting up it lost power, with the stick at 0. The last health record point was 7.33 V (there's only one point every 0.5 s, so the drop itself wasn't captured).

**Cause**: when the servos exert force together, the current surge is more than the supply and leads can handle, and the voltage collapses. The board's 5 V is stepped down by the HAT from the same rail, so it goes down too. The larger D is, the more often the model corrects, and possibly the more current surges; the new card browning out faster **may** be related to D=40, but that's just one run against one run, and the new card also had sound on (the amplifier draws from the same rail), so no conclusion can be drawn.

**Other voltage figures**: on the boot on the afternoon of 10-13 (`bc840bb`), median 7.45 V standing with torque on and 7.39 V walking; even standing was only 7.45 V (supply set to 8.2 V), cause not found. On subsequent boots both standing and walking were 7.9–8.1 V; walking in the early morning of 10-14 had a median of 8.00 V and a minimum of 7.93 V. robotd reports voltage only once every 0.5–1 s and smooths it, so momentary drops lasting tens of milliseconds aren't visible.

**What to do**:
- Use a battery (an RC battery with a sufficient discharge rating, fully charged), or a high-current supply (our 10 A supply arrives 10-16);
- Use 16–18 AWG silicone wire, as short as possible, with XT30 / XT60 connectors, not alligator clips;
- Put a 1000–2200 µF electrolytic capacitor across the duck's power input;
- To tell whether "the main supply collapsed" or "the HAT's rail feeding the board is too weak": power the board's USB-C separately from a power bank and walk again (the HAT has an LM5050 ideal diode, and the design allows this). If you have an oscilloscope, trigger on the falling edge and watch BATT_IN, 5V_PRE_IDEAL and the board's 5V at the same time.

**A correction**: kissqy's repo once had a passage saying "the ZERO reboots after a few steps, suspected insufficient VS supply margin on the HAT's LM5050". **He deleted it on 10-12**, with the commit message "author correction, earlier tests were inaccurate". Don't take it as kissqy's conclusion. Our C1 HAT does have the same BOM (R8 100Ω, U10 LM5050-1, U9 AP63205), but our evidence this time points to the main supply.

---

## 3. Comparing the old and new cards

After the new card browned out, we read out the old card with a read-only ext4 reader (run as administrator on the PC, since `wsl --mount` couldn't mount the USB card reader) and compared item by item:

| | Old card | New card |
|---|---|---|
| Kernel, device tree, aic8800 WiFi/Bluetooth driver and firmware | 99 files identical | ← |
| bluez, wpa_supplicant versions | Same | ← |
| WiFi management | wpa_supplicant, 2.4G preferred, PMF off, `country=CN`, static IP | NetworkManager |
| Device tree overlays | — | Compared to the old card adds i2c3-pihat, aic3104 (sound card), camera, NPU |
| robotd / padd | kissqy R17 | kissqy V164 |
| Servo parameters | Web console can set P / D / torque limit | Only writes P=5 (§4.2) |
| Sound | Off | On (`[audio] enabled = true`); the amplifier on the HAT shares a rail with the servos |

So the brownout has nothing to do with the card (both cards brown out). The G50 Pro only remembers the last card it paired with, so **switching cards requires re-pairing**. The difference in walking behavior comes mainly from different robotd versions and different servo D.

---

## 4. Where parameters actually take effect (tonight's biggest pitfall)

### 4.1 The joint model's scale and filtering: in the model package, not in robotd.toml

**Symptom**: we changed `action_scale` to 1.0 and 0.8 and the head/leg filters to 0.5 and 1.0 in `robotd.toml`, and ran several comparison sets. We later found that these comparisons **were all wasted**, and the conclusions we drew from them were wrong; they have been corrected.

**Cause**: kissqy's joint model (`scale_use = joint_uniform`) carries its own `deployment-execution.json`. The version installed in R17 has scale 0.9, head filter 0.5, leg filter 0.7 (in V164, which kissqy released after 10-12, the same model specifies scale 1.0, head 0.5, leg 0.7), and robotd also multiplies by a voltage compensation (about 7.4 / voltage, about 0.92 at 8 V). **`action_scale` and the filters in the toml don't apply to the joint model**, only to other models.

**How to confirm what's in effect**: look at robotd's `robot.busStatus` → `loaded_models.walk.runtime_execution_profile`; that holds the values robotd is actually using. The "联合基础缩放 0.90" (joint base scale 0.90) field on the web console's "高级参数" (Advanced parameters) page is also read from there.

**To change them**: edit the three numbers in that `deployment-execution.json` in the model directory, then restart robotd with torque off. We locally added three input fields, "联合缩放 / 头部滤波 / 腿部滤波" (joint scale / head filter / leg filter), to kissqy's web console that can do this (§8); not yet released. Addendum (10-14): this was later done on V164 instead; see [10-14 daytime log §8](HD1910-20261014-白天-仿真找原因与新版放开参数.md#8-新版v164放开-p--d--转矩限制和头腿滤波本地未上机).

### 4.2 Servo P / D / torque limit: settable on R17, not on V164

First, the servo itself. The HD-1910's factory EEPROM has **P=32, D=40, I=0**, torque limit 1000, acceleration 0. To read it: robotd's `robot.busStatus` → `native.hd1910.registers_before_arm`.

| | What is written at torque-on | P / D / torque fields in the web console's "高级参数" (Advanced parameters) |
|---|---|---|
| R17 (old card) | Writes P=5, D=20 by default; uses the values in `/etc/robot/feetech-ft5/servo-test-parameters.json` if present | **Takes effect**, written at the next HOME torque-on |
| V164 (new card) | Only writes P (`kp_fw=5` from the model contract); **D and torque limit are not written**, staying at factory D=40, 1000 | **No effect**. kissqy's notes say "torque limit at registers 48–49 and D at register 51 are not explicitly written", and R17's test-parameter branch was also removed |

**Addendum (10-14 evening)**: on 10-14 kissqy released V167 / control.43 (web console 1.0.167), described as "fixing body shaking": at every HOME torque-on, D in the RAM of all 15 servos is written to 0 and the torque limit to 1000, while P still uses the model's 5. These two values are fixed and can't be adjusted in the web console; at torque-off only P is restored, and D stays at 0 until the servo loses power. This matches the conclusion in §5 of this page.

**Temporary workaround on the new card**: after stopping robotd and turning off torque on all 15 servos, write D (register 51) and torque limit (register 48) directly into the servos' **RAM**. RAM reverts on power loss; EEPROM is untouched. We used a small script to write D=0, torque 681. Note: **D-pad right on the gamepad (restart servos) also resets RAM to factory values**. Long-term, either add this setting back into V164, or change D to 0 in the EEPROM of all 15 servos (only effective with V164, which doesn't write D; R17 writes its own D at torque-on, so it must be paired with kd in the test parameters). **Addendum (10-14)**: the code adding it back into V164 is written locally (P / D / torque limit and head/leg filters are all settable in the web console; not yet on the robot, not public); see [10-14 daytime log §8](HD1910-20261014-白天-仿真找原因与新版放开参数.md#8-新版v164放开-p--d--转矩限制和头腿滤波本地未上机).

---

## 5. Jittery walk: related to the servos' D

### 5.1 How we found it

1. The servo model used in training (BAM: a physical model of the servo, including the motor and various friction terms; its parameters are Luwu's published 1910 M6, i.e. this very servo; `kp_fw=5` means P=5 in the servo firmware) **has no hardware D term** (kissqy's audit document says the same); but the real servos have D=20 (R17) or D=40 (V164). D is the derivative term in the servo, acting as damping: the faster it moves, the harder it resists;
2. We computed "target → actual" tracking from walking data (Welch cross-spectrum: take the target the model gives each tick as input and the servo's actual angle as output, and compute what fraction is tracked at each frequency). In the P5 / D20 recording (`run-20261013-135146-b3409a0`), at 3–4 Hz around the step frequency: hips and knees track 0.33–0.46, about the same as simulation's 0.41–0.48; only the ankles are clearly worse (0.36–0.39 vs. simulation's 0.69). Another recording only 21 seconds long (`132505-b70520d`) gave 0.26–0.45;
3. **Hypothesis**: the model assumes the legs are nimble; the real damping eats part of each correction, so the model has to correct faster and harder over and over, producing 4 Hz shuffling steps plus jitter. But after setting D to 0 (P5 / D0 / 850), hip roll tracking was 0.27–0.28 and knee 0.35–0.36, no better; only the ankles rose to 0.53. **This mechanism is not confirmed by the data**.

What is certain are the measurements in the table below: setting D to 0 noticeably reduces jitter.

### 5.2 Comparison of several parameter sets (8–42 seconds of walking each)

Same duck, old card, joint model, joint scale fixed at 0.9. Scripts in [`tools/gait-analysis/`](../tools/gait-analysis/): `gait_quality.py` (step frequency, sway) and `foot_clear.py` (foot clearance, §7):

| Set | Walked | Step frequency | Body roll sway | Of which >4 Hz (jitter) | Mean lateral tilt | Swing foot clearance left / right |
|---|---|---|---|---|---|---|
| Simulation (training servo model, P5) | 19.8 s | 3.22 Hz | 31°/s | 14% | −1.1° | 11.4 / 11.8 mm |
| P5 / D20 / 1000 | 42.3 s | 2.89 Hz, irregular rhythm | 33°/s | **51%** | −1.9° | 6.9 / 6.5 mm\* |
| P5 / D0 / 850 | 13.0 s | 3.47 Hz | **56°/s** | 6% | −1.5° | 5.5 / 8.5 mm\* |
| P3 / D0 / 681 | 22.8 s | 2.91 Hz | **30°/s** | 8% | −2.4° | 2.2 / 6.5 mm\* |
| P3 / D0 / 681 (second run) | 8.2 s | 2.80 Hz | 36°/s | 4% | −1.8° | 3.1 / 5.9 mm\* |
| P4 / D0 / 681, IMU roll corrected | 12.0 s | 3.01 Hz | 44°/s | 6% | −0.8° | 4.8 / 5.8 mm |

\* Recorded before the IMU roll correction (§6). At that time the IMU read about 1.1° too much left tilt, which when transformed to the ground made the left foot come out about 2 mm too low: the left numbers are too small and the right too large, by about 2 mm each; the left/right segmentation was also biased (too much time attributed to left-leg stance). The P4 set is the cleanest.

**Note this is not strictly "change one thing at a time"**: P5 / D20 / 1000 → P5 / D0 / 850 changed both D and the torque limit; the P5 set had torque 850 while P3 and P4 had 681; the P4 set also had the IMU correction applied.

**How to read it**:
- With D=20, half the body sway is jitter above 4 Hz; **with D set to 0 (and torque 1000 → 850), jitter drops from 51% to 4–8%**;
- With D=0, the larger P is, the worse the sway: P5 sways 56°/s, P4 44°/s, P3 30°/s, the same as simulation (torque limit and IMU not exactly the same, see above);
- By feel, P3 is also the most stable for us. kissqy's web console defaults happen to be P3 / D0 / 681 too;
- The cost is that the smaller P is, the lower the foot clearance (§7);
- **D=20 has upsides too**: in stance the right knee can extend to +1.6° (−2.6° to −5.3° with D=0), and the body doesn't nod forward and back (§7.3, §7.4). So D=0 isn't necessarily best; an intermediate value of D=5–10 is worth trying.

**Does a torque limit of 681 clip motions?** In simulated walking, the two knees need more than 68.1% of force 3.4% and 11% of the time respectively (peaks 76–81%), and all other joints stay below 50%. So 681 mainly clips the knee peaks. We later changed it to 700.

---

## 6. Correcting the IMU roll zero back by 1.14°

**Symptom**: at P3, standing at HOME the IMU reads 2.6° left tilt, and while walking the mean also stays at 1.8°–2.4° left.

**Method**: same as on the night of 10-12: take the real joint angles while standing at HOME, put them into simulation to compute how much the body "should" tilt, and compare with the IMU reading. Across 5 HOME stances tonight, the IMU always **read 0.65°–1.69° more to the left than expected, averaging 1.14°**, always in the same direction. On the night of 10-12 we corrected 8.54° forward pitch and 1.78° right roll; this time roll was corrected back by 1.14° (opposite direction to 10-12). The "expected value" is the average of two calculations, left foot flat and right foot flat, which themselves differ by 0.4°–2.6° (see the end of this section), so the uncertainty of this 1.14° is about as large as the value itself.

**What we did**: with the duck at torque off, ran `imu_mount_fix.py 0 -1.14 <current quaternion>` to compute the new quaternion, wrote it into both calibration files (`hd1910-calibration.toml` and `hd1910-calibration.saved.toml`, backups `.bak-20261014-imuroll`), and restarted robotd with torque off. New value `[0.459554518, 0.539556409, 0.532044137, 0.463268349]`.

**Result**: in the retest the lateral offset dropped from −1.31° to −0.47°; the mean lateral tilt while walking went from −2.4° back to −0.8°.

**Remaining**: the fore-aft offset jumped between −0.2° and −1.8° across several runs, unstable; left as is.

Also, at P3 standing at HOME the left knee was bent 7.6° and the right 2.8°; at P4 it was 2.2° and 1.2°. The smaller P is, the more easily the legs get compressed by body weight while standing, and the left/right difference grows too.

**The two feet aren't coplanar in roll (not investigated)**: across 6 HOME stances, doing forward kinematics from the servo readings, the body roll obtained from "left foot flat" and "right foot flat" differs by 0.4°–2.6°, 5 of those times in 1.6°–2.6°, always in the same direction. In other words, according to the servo readings the two soles aren't in the same plane laterally, even though both feet are clearly standing on flat ground. Possible causes: a 1–2° hip roll zero offset, one edge of a sole not touching the ground, or mechanical play the servos can't measure. Fore-aft, the two feet agree (sole pitch left −3.0°, right −2.9°). **Addendum (10-14 daytime)**: broken down joint by joint, the difference comes entirely from the two hip roll joints not reaching the HOME target, always left + and right − (legs splaying outward), by a different amount each time, apparently pressed by body weight (a guess). Whether the zero position itself is off can't be told by that method. See [10-14 daytime log §7](HD1910-20261014-白天-仿真找原因与新版放开参数.md#7-站-home-两只脚左右方向不共面两个髋横滚往外劈每次不一样).

---

## 7. Foot scuffing: both feet lift only half as high as in simulation

### 7.1 First, compute "how high off the ground" correctly

The previous foot-lift calculation was relative to the body and didn't account for the body's lateral sway (not committed to the repo). The new [`foot_clear.py`](../tools/gait-analysis/foot_clear.py): for every frame, do forward kinematics from the servo readings to get the positions of the 8 corners of the two feet, then rotate upright using the body orientation measured by the IMU; the lower foot counts as stance and the other as swing, and **the swing foot's lowest point minus the stance foot's lowest point** is the foot clearance. Self-check: standing at HOME with both feet on the ground, both feet's lowest points should be at the same height; after IMU compensation they differ by 0.8 mm.

Results are in the table in §5.2: **simulation 11–12 mm, the best real-robot set only 6–7 mm, P3 only 3–6 mm**. During swing, 18%–82% of the time the clearance is under 2 mm (simulation 9%–14%).

### 7.2 Why you see the left foot scuffing: its toe points down when it steps

At the peak of the swing, how many degrees the sole has rotated relative to stance (positive = toe down), and which point on the foot is lowest at that moment (scripts `toe_decomp.py`, `foot_clear.py`):

| | Left foot | Right foot |
|---|---|---|
| Simulation | −7.8° (toe up), lowest point is the heel | −6.0°, lowest point is the heel |
| P3 / D0 / 681 | **+2.0°**, lowest point is the **toe** (16 of 27 steps) | −1.5°, lowest point is the heel |
| P3 / D0 / 681 (second run) | **+2.4°**, toe (14 of 17 steps) | −1.3°, heel |
| P4 / D0, IMU corrected | **+2.9°**, toe (20 of 31 steps) | −0.1°, heel |
| P5 / D0 / 850 | **+2.5°**, toe (18 of 35 steps) | +0.3°, heel |
| P5 / D20 / 1000 | +0.5°, heel (36 of 56 steps) | +0.1°, heel |

In simulation the toe tilts up 6–8° during swing. On the real robot the right foot is basically flat; the left foot points toe-down in **every D=0 set**, but **not in the D=20 set**. The D=20 and D=0 sets were recorded in the same boot session with the same mechanical state, so this is related to D, not to how P is set. A toe pointing down while swinging forward catches the ground; the right foot's lowest point is the heel, dragging behind, which is less noticeable.

### 7.3 The cause common to both feet: the stance knee can't straighten

Knee angle in stance relative to HOME (positive = toward straightening), with what the model commands in parentheses:

| | Left leg stance | Right leg stance | How high the stance leg holds the body |
|---|---|---|---|
| Simulation | +5.4° (commands +18.5°) | +9.4° (commands +26.4°) | 124 mm |
| P3 / D0 / 681 | −6.2° (commands +4.3°) | −5.3° (commands +30.5°) | 117–120 mm |
| P4 / D0, IMU corrected | −4.5° (commands +15.4°) | −2.6° (commands +23.1°) | 119 mm |
| P5 / D0 / 850 | −2.8° (commands +10.5°) | −3.4° (commands +22.0°) | 119–121 mm |
| P5 / D20 / 1000 | −4.1° (commands −1.6°) | +1.6° (commands +13.7°) | 121 mm |

In stance the model keeps commanding the knee to straighten; the simulated servo extends partway, but **the real knee stays bent**: −2.6° to −6.2° in the D=0 sets, and with D=20 the right leg reaches +1.6°, slightly better. As a result:
- The body is about 5 mm lower than in simulation, leaving less room for the swing foot to clear the ground;
- With the knee already bent in stance, it doesn't bend much further during swing. In simulation, the "knee bends more in swing than in stance" component rotates the sole by −14° to −16° (toe up); on the real robot this component is nearly 0, so the toe can't tilt up.

**Voltage ruled out**: while walking in the early morning of 10-14 the servo voltage had a median of 8.00 V and a minimum of 7.93 V, with no sag.
**The difference is "same servo, different conditions"**: the servo parameters used in training are Luwu's published 1910 M6, i.e. this very servo, and the parameters themselves are fine. Simulation and the real robot may still differ in:
1. We run P3, training used P5 (P3 is inherently softer);
2. Our torque limit is 681–850, while simulation has no cap that low (but P5 / D20 / 1000 can't straighten either, so it's not only the torque limit);
3. The whole duck's mass and center of mass differ from simulation (we haven't weighed it);
4. The conditions under which Luwu did the identification (P, D, voltage, load) differ from ours; whether the STS-series control algorithm used in BAM exactly matches the HD-1910 firmware hasn't been checked either;
5. Unit-to-unit servo variation and mechanical friction in the joints.

P5 / D0 / 850 also can't straighten the stance knee (−2.8° / −3.4°), so it's not only a matter of P. To separate these factors: first run a set **closest to training conditions, P5 / D0 / 1000**, walk for 10 seconds, and see whether the stance knee can extend; if it still can't, the difference is mass or identification conditions, so weigh it and run single-joint step responses to compare with simulation.

**Addendum (10-14 daytime)**: checked further in simulation. Item 2, torque limit: with or without a 70% cap in simulation, the results are nearly identical (with Luwu's parameters only peaks are clipped, and with Feetech's parameters it was never triggered; only compared at P5 and 737 g, not verified on the real robot). Item 3, mass: the model kissqy trained with is 820 g, our simulation is 737 g. We also missed a bigger one: the real robot's joint model has an action scale of about 0.83 with filtering, while simulation used 1.0 without filtering. After aligning scale and filtering and estimating the mass at 820 g, the simulated stance knee is −3.4° / −3.5°, now close to the real robot (but that simulation set jitters). See [10-14 daytime log §2](HD1910-20261014-白天-仿真找原因与新版放开参数.md#2-对齐条件以后撑地膝盖接近了但仿真多出了颤).

### 7.4 Why only the left foot suffers: the body nods forward and back

Body forward pitch in stance (IMU) and the stance foot's angle relative to the body:

| | Left leg stance, body forward pitch | Right leg stance, body forward pitch | Stance foot relative to body, left / right |
|---|---|---|---|
| Simulation | +0.5° | +0.7° | — |
| P3 / D0 / 681 | +2.8° | **+4.7°** | −3.9° / −3.9° |
| P4 / D0, IMU corrected | +1.1° | **+2.4°** | −2.9° / −2.2° |
| P5 / D0 / 850 | +0.3° | **+1.9°** | −2.4° / −2.4° |
| P5 / D20 / 1000 | +0.2° | +0.3° | −2.5° / −2.0° |

When the right leg is in stance (which is exactly when the left foot is swinging), the body **pitches forward 1.3°–1.9° more** than in left-leg stance; **with D=20 there's no such difference**, and in simulation both sides are the same too. When the body pitches forward, the swinging left foot's toe gets pushed down.

- **It's not a crooked IMU mount**: if the IMU were mounted off around the vertical axis, roll and pitch would be tied together at the same ratio at all frequencies. Measured, there's almost no coupling at 6–20 Hz (slope −0.04 to +0.15), only near the step frequency (2–4.5 Hz slope +0.10 to +0.16, correlation 0.4–0.5). So the body really is nodding (script `roll_pitch_coupling.py`).
- **It's not the fore-aft zero position**: the pitch of the two stance feet relative to the body is nearly the same (last column of the table above), and standing at HOME the soles' pitch is left −3.0°, right −2.9°. In the lateral (roll) direction the two feet aren't coplanar, see the end of §6 (checked on 10-14: the two hip roll joints splay outward, apparently pressed by body weight (a guess); see [10-14 daytime log §7](HD1910-20261014-白天-仿真找原因与新版放开参数.md#7-站-home-两只脚左右方向不共面两个髋横滚往外劈每次不一样)).
- **Where the extra 1.5° comes from**: the stance foot's pitch relative to the body is the same on both sides, yet the body pitches further; and it's absent with D=20 and only appears with D=0. **Guesses** (none confirmed):
  1. With D=0 there's no damping at right-leg touchdown, so the body sways forward (dynamic, related to D);
  2. The right foot isn't flat in stance: the heel lifts and it bears on the forefoot, or the foot pad is uneven or slipping;
  3. The right leg has mechanical play or deformation the servos can't measure (servo horn screws, brackets, printed parts). A servo only measures its own output shaft angle and can't see these.

  Item 1 fits "only appears with D=0" best, and can be tested with an intermediate D (§7.5).

### 7.5 Next steps (one change at a time)

1. **Try an intermediate D**: P3 or P4, D=5–10, torque 700, walk for 20 seconds. See whether the jitter comes back, whether the left toe pointing down and the body nodding go away, and whether the stance knee extends further;
2. **Look first, don't change anything**: film from the side at floor level in phone slow motion (240 fps): one clip of whether the right heel lifts in stance, one of whether the left toe catches the ground. Standing at HOME, look from the front to see whether either sole has an edge lifted (shine a flashlight from behind to see gaps), corresponding to the last item in §6. With torque on at HOME, gently push both feet (fore-aft, up-down) to compare which side has play; check the right leg's servo horn screws;
3. **Joint scale 0.9 → 1.0** (the version on R17 is 0.9; V164 already defaults to 1.0): the model's actions all get 11% bigger, so the knees can extend and bend a bit more, benefiting both feet; it can be changed back any time;
4. **The fundamental fix is training our own model**: measure the servo response under our own conditions (P, D, torque limit, voltage, whole-duck mass), align simulation to it, then train; set the foot lift target at 25–30 mm. The current model only clears 11–12 mm even in simulation (foot lift target 20 mm with weight −2 during training, air time 0.125–0.3 s), and with the softer real servos only half of that survives on the real robot;
5. **Feetech's official HD-1910 BAM**: [gitee.com/ftservo/ftservo-bam](https://gitee.com/ftservo/ftservo-bam) (Apache-2.0, released 2026-09), containing `feetech_hd1910_7_4V/m1～m6.json` and a dedicated HD-1910 control model, measured with a loaded swing arm, P from 4 to 64, at 7.4 V. kissqy's model uses Luwu's version (borrowing the STS3215 control model and fitting a gain factor of 1.32), and the two parameter sets differ quite a bit: resistance 2.97 Ω vs. 4.91 Ω, load-dependent friction 0.35 vs. 0.07, command latency 1 ms vs. 6 ms. Next, swap the servo parameters in simulation for the official ones and see whether simulation also shows "the stance knee can't straighten". Note that when the official data was recorded only P was written, not D, so the servos very likely had the factory D=40, and the effect of D got folded into the friction parameters; when training with it, the real robot's D needs to be checked accordingly. **Addendum (10-14 daytime)**: compared in simulation after switching to Feetech's parameters (an approximate integration): at scale 1.0 Feetech's look more like the real robot; after aligning scale and filtering the two are about the same, and simulation can't tell which better matches our servos. See [10-14 daytime log §3](HD1910-20261014-白天-仿真找原因与新版放开参数.md#3-两份舵机参数陆吾的和飞特官方的).

---

## 8. Local web console experiment: making joint scale and head/leg filters adjustable (not released)

Every duck is a bit different and always needs some tuning. Locally, we added three input fields, "联合缩放 / 头部滤波 / 腿部滤波" (joint scale / head filter / leg filter), and an "应用联合参数" (Apply joint parameters) button to kissqy's web console (1.0.146 + R17 install package):
- Ranges: scale 0.10–1.20, filters 0.10–1.00, two decimal places; validated first by the same validator kissqy uses when importing models, and if invalid it doesn't turn off torque or stop robotd;
- Apply: validate → torque off → stop robotd → change only the three numbers in `deployment-execution.json` → restart → read back from `runtime_execution_profile` to confirm; on the first change the original is saved as `.orig`;
- Tests: 4 new and 32 existing related tests all pass. Independent review (a separate AI session doing a read-only review) concluded: **1 issue must be fixed** (in calibration mode robotd doesn't report model info, so the readback always fails and the page reports a false error); the other checks passed. The fix has been outlined and will be made after confirmation; use in motion mode isn't affected by this issue.

kissqy's web console is under a personal non-commercial license, so these changes are only used locally and are not put into this repo.

**Addendum (10-14)**: this experiment on 1.0.146 was not continued (the must-fix issue wasn't fixed either); it was redone on kissqy's new V164 with P / D / torque limit added; see [10-14 daytime log §8](HD1910-20261014-白天-仿真找原因与新版放开参数.md#8-新版v164放开-p--d--转矩限制和头腿滤波本地未上机).

---

## 9. What changed on the board, and how to revert

**Old card** (user `duck`):

| What changed | Backup / how to revert |
|---|---|
| `servo-test-parameters.json` = P3 / D0 / 700 | Change it back in the web console's "高级参数" (Advanced parameters) |
| IMU mount quaternion roll corrected back by 1.14° | `hd1910-calibration*.toml.bak-20261014-imuroll` |
| `action_scale` and head/leg filters in `robotd.toml` (no effect on the joint model) | `robotd.toml.bak-20261013-lowpass`; should be changed back to the original 0.7 and the two filter lines removed |
| Removed `PartOf=robotd.service` from `duck-rec.service` so recording runs independently | `.bak-20261013-partof` |
| Recording script replaced with the new version that writes to disk every second; added `duck-journal` | Just delete the services |
| Install package `runtime.py`, `service.sh` (for the web console experiment) | `.bak-20261014-joint` |

**New card** (user `radxa`): Bluetooth `input.conf` (`.bak-20261013`), the two gamepad-related services in kissqy's image (btd and gamesir-xboxd) disabled, duck-quiet, WiFi 5G and PMF, watchdog and panic, black box, motion mode (`/home/radxa/backup-20261013-*`). D=0 / 681 in servo RAM is gone after power loss.

---

## 10. Next steps

1. Power: switch to the 10 A supply on 10-16 (short thick leads + large capacitor), or use a battery; run one comparison with the board powered separately from a power bank;
2. Foot scuffing: first try an intermediate D, then film in slow motion and feel for play, then try joint scale 1.0 (§7.5);
3. New card: add the P / D / torque settings back into V164 (or change D in the servo EEPROM), then use the new card; pair the G50 Pro on the new card fully per §1.2 (10-14: the code adding it back is written locally, not yet on the robot);
4. ~~File an Issue with kissqy~~ (10-14 evening: in V167 he already writes D=0 and torque 1000 at torque-on, so no need): V164 **deliberately** doesn't write D or torque limit (his design document says registers 48/51 keep the device's current values), so the servos use factory D=40, inconsistent with the training servo model (no D). Request an option so one-click image users can set D, with the data from §5 of this page attached. We'll review it ourselves before sending;
5. Train our own: measured HD-1910 servo parameters, foot lift target 25–30 mm, step frequency constraint.
