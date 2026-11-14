# 2026-10-12 night · An IMU mounted 8.5° off was the root cause of "lunges as soon as the policy takes over": after calibration it stood steady for 70 seconds and began stepping with alternating legs

**English** · [简体中文](HD1910-20261012-夜-IMU校准与首次迈步.md)

**Robot**: unit #1 (Feetech HD-1910 ×15, Radxa Zero 3W 2G without eMMC + microSD, official HAT revision C1). Software is kissqy's full stack (official 0.15.1 + R17 v146). The IMU is a BNO085 module on I²C (40-pin header pins 1/6/27/28, `/dev/i2c-4`, 0x4B). The walking model is kissqy's "walking + fall recovery joint 9600 iterations" (`Mjlab-VelStand-Rough-Backlash-MicroDuck`).
**Background**: in the early hours of the same day we installed kissqy's full stack; it could go HOME and hold, see the [10-12 on-robot log](HD1910-20261012-kissqy整套上机.md).

**One-line conclusion**: the robot falling backward the moment the model takes over is not the model's fault, nor button latency. The **IMU module is mounted about 8.5° off**. The duck is standing upright, but the IMU says "leaning forward 8.5°", so the model keeps trying to save it backward, harder and harder. After calibrating those 8.5° away (using simulation), the model held it standing steadily for 70 seconds, and pushing the stick made both legs start stepping rhythmically in alternation.

| | Before calibration | After calibration |
|---|---|---|
| How long it stands after the model takes over | Falls in 0.6 s at worst, 21 s at best | 70 s without falling, ended manually |
| Body tilt | Swings between 2° and 10°, going all the way to 60°–90° before falling | Mean +0.2°, range −0.9° to +2.6° |
| Body angular velocity | 0.3–0.5 rad/s, up to 9 rad/s before falling | 0.03–0.39 rad/s |
| Stick pushed to 0.14–0.21 m/s | Leg moves once and freezes | Knees alternate with 21°–39° swing; at 0.21 m/s about 26 leg switches in 6 s |

Not yet confirmed: **how far it actually moved forward** while stepping (robotd's odometry field has always been 0; it isn't being computed).

---

## 0. Tonight's issues at a glance

| # | Symptom | Root cause | Fix | Details |
|---|---|---|---|---|
| 1 | HOME and Start on the web gamepad do nothing | Four layers: every SSH login runs a 3.8 s welcome script; the web console declares input stale after 0.4 s; every button press cold-starts a virtual gamepad; padd opens the new device before the system has finished registering it and doesn't retry on failure | Switched to a physical Bluetooth gamepad; fixed one thing each in the web console and the system | §1 |
| 2 | The web joystick only starts moving after you've pushed and released it | Long request/response chain (browser → PC → WiFi/SSH → Python on the board → virtual gamepad → padd); any WiFi hiccup queues things up | Thunderobot G50 Pro switched to S mode, Bluetooth directly to the board | §2 |
| 3 | Voltage drops to 5 V | Power bank (PD trigger) falls back to 5 V on overcurrent; bench supply leads are thin, 8 V leaves only 7 V at the servos | Bench supply at 8 V with current limit maxed; leads short and thick | §3 |
| 4 | Lunges backward and falls as soon as the model takes over | **IMU mounting offset: 8.5° forward pitch, 1.75° right roll** | Computed the offset from simulation, changed the IMU mount quaternion | §4 |
| 5 | Duck suddenly goes limp, Start won't bring it back | Poor contact on the BNO085 wiring; I²C stops responding, robotd marks the IMU stale and enters protection | Resoldered and strapped down | §5 |
| 6 | Body leans forward at HOME, Start is rejected | Knees bent 5°–9° by body weight at P5 gain | Press after it settles; long-term see §6 | §6 |

---

## 1. Web gamepad presses do nothing: four causes stacked together

**Symptom**: the kissqy web console (R17 v1.0.146) connected and all data looked normal, but clicking HOME or Start on the web gamepad did nothing. The web console log said "输入已过期，未发送" (input stale, not sent) or "timed out", and the padd log occasionally had `Failed to open "/dev/input/event4"`. In the early morning we thought the board was just overheating; tonight we measured each stage and found four layers:

**How the path works**: browser → web console (Python on the PC) → **a new SSH connection per button press** to forward it → `webpad.py` on the board (started on demand by systemd, exits after 2 s idle) → creates a virtual Xbox gamepad (uinput) → padd discovers the new gamepad and opens it → padd translates buttons into robotd commands.

| Layer | Measured | Why it stalls |
|---|---|---|
| ① SSH login | Every login waits an extra **3.8 s** | Armbian's `pam_motd` runs the welcome scripts in `/etc/update-motd.d/` on every SSH login; `20-ip-info` alone takes 2.9 s |
| ② Web console timeout | If opening the channel takes more than **0.4 s**, the press is discarded | Opening a new SSH connection alone takes 1–1.6 s, so it can never succeed |
| ③ Virtual gamepad cold start | webpad starts in 0.43–1.6 s, then padd needs about 1 s more to see the new gamepad | You press and release, the virtual gamepad's 0.6 s lease expires before padd sees it, and the press is dropped |
| ④ padd opening the new device | padd tries to open it 80–280 ms after the new gamepad appears, and sometimes fails | The system (udev) hasn't finished registering the new device; padd doesn't retry after a failure. **Not a permissions issue**: running padd as root fails the same way |

A side effect: we had turned off tofd (no ToF connected), so after failing to subscribe to ToF the web console **reconnected every 5 seconds, each time with a full SSH login**. In 10 minutes the board was logged into 112 times, each running the 3.8 s script, so most of a core was wasted constantly. That was also a heat source.

**What we did**:
- Board: commented out the `pam_motd.so motd=/run/motd.dynamic` line in `/etc/pam.d/sshd` (backup `sshd.bak-20261012`). Round-trip time for one query over SSH dropped from 3.2–4.3 s to 0.65–0.73 s.
- Web console on the PC (local patch on our branch): timeout relaxed to 3 s; on connect it sends an empty input frame first to set up the channel and virtual gamepad in advance; added `--tofd-socket ""` to skip ToF.
- We tried making webpad's virtual gamepad persistent (on lease expiry it only returns to neutral instead of being destroyed). The behavior tests passed, but running kissqy's existing tests revealed that it **fabricates a "button released" event out of nowhere**, and padd's Select triggers torque-off **on release**, which is a safety hazard. We reverted it and put the original `webpad.py` back on the board.
- **In the end we switched to a physical Bluetooth gamepad**, bypassing the whole path (§2). kissqy also changed the web gamepad to go directly to robotd in V164.

**Lessons for building a "foolproof web page" later**: the browser connects directly to the board without relaying through a PC; stream at a fixed rate instead of request/response; keep the connection persistent; don't emulate a gamepad, hand "speed and turning" directly to robotd.

## 2. Switching to a physical Bluetooth gamepad (Thunderobot G50 Pro)

Both the official and kissqy designs **pair a Bluetooth gamepad directly with the duck's board** (the Zero 3W has onboard Bluetooth), and that's what padd reads. Gamepad → board Bluetooth → kernel driver → padd → robotd, all on one machine, with no WiFi or PC involved.

- Plugging a receiver into the board isn't practical: the board is in the head and there's nowhere to plug it in.
- The Thunderobot G50 Pro has four modes on the back, **X / S / T / D**. They select the platform, not wired vs. wireless. **Switch to S (Switch mode)**: the gamepad then presents itself as a Switch "Pro Controller", the board's kernel has a built-in driver (`hid-nintendo`), and the official pairing tool explicitly supports it.
- Unplug the 2.4G receiver from the PC (otherwise it reconnects to the receiver at power-on). With the gamepad off, hold HOME to enter pairing; the light flashes quickly.
- Pairing needs configd (we had turned it off to reduce heat; run `systemctl start configd` before pairing). `robotctl pad pair` automatically searches for devices of the "game controller" class; if it finds nothing, scan with `bluetoothctl`, look for `Pro Controller` (class 0x2508, icon `input-gaming`), then run `robotctl pad pair <address>`. Once paired it's trusted, and it reconnects automatically after the board reboots and the gamepad is powered on.
- Buttons: the "≡" in the middle right = Start (**first press goes HOME, second press hands over to the model**), the "⧉" in the middle left = Select (torque off; press it in an emergency), left stick to walk. **X is bound to "forward roll" in the board config, so don't press letter buttons at random**: in Switch mode the letter buttons' positions may differ from what's printed on the gamepad.

## 3. Power: don't use a power bank, and keep bench supply leads short and thick

- **Power bank + PD trigger cable**: every time it goes from the slumped pose back to HOME, all 15 servos exert force at once and the voltage drops to 5 V. A PD power bank falls back to 5 V on overcurrent; that's the protocol's protection. At 5 V the servos lose 30–40% of their torque and speed and can't reach the pose; robotd only lets the model take over once the standing pose is reached (joint error ≤5°, body tilt ≤10°), so it refuses, goes HOME again, draws another large current, and the cycle repeats. 5 V is also at the lower limit of the HAT's buck converter for the board, so the board may reboot (kissqy has noted "the ZERO reboots after walking a few steps").
- **Bench supply**: set to 8.0 V with the current limit at max. Measured at the servos: 7.7 V at rest, 6.98–7.0 V under load; about 1 V is lost in the leads, which is too much. Leads should be short and thick (0.75 mm² or more), with connectors screwed tight.
- Long term, use an NP-F550 battery.

## 4. "Lunges as soon as it takes over": how we tracked down the IMU offset step by step

### 4.1 What the loss of control looks like

Three runs seen in the recordings (`duck_rec.py`, 50 Hz):

- The first ran for 20 seconds; model outputs hit the joint limits 813 times, saturating on almost every tick.
- In one run **the first 21 seconds were stable**: tilt 2°–4°, small forward/backward sway, leg targets only 5°–8° off; but the left knee was commanded to −5° and only reached −1°, so the servo kept lagging. At 20.9 s the model tried to take a step and commanded left hip +19°, actual +5°; 0.2 s later it commanded +67°, actual −6°; targets saturated at ±100°, and in under 1 second it pitched **backward** to 61°.
- In one run the body was pitched 9.1° forward at handover (just short of the 10° limit). On the very first tick the model commanded right knee +10°, then +17° on the next; 0.08 s later the body started pitching **backward**, reaching 87° at 0.44 s.

**Pattern: every time, it's "the model thinks it's falling forward → saves hard backward → falls backward"**, and the more forward-pitched the body reading before handover, the faster it lost control.

### 4.2 What we ruled out first

| What we checked | How | Result |
|---|---|---|
| Filtering not active? | Read robotd's live state | Active: action scale 0.87–0.90, leg filter 0.7, head 0.5 (kissqy's runtime values). We run his robotd, with only the I²C IMU added |
| IMU axes or signs wrong? | 471 rotation samples, checking that gyro and gravity change satisfy dg/dt = −ω×g (`imu_consistency.py`) | Agreement 0.961; the as-is configuration was the best-matching combination, not misconfigured |
| Joint velocity signs wrong? | Angle differences vs. velocity reported by robotd (`vel_consistency.py`) | Correlation coefficients across 14 joints +0.58 to +0.76, all positive |
| IMU's four directions correct? | Hold the duck and tilt it 20° forward, backward, left and right (`imu_tilt_check.py`) | Forward +33°, backward −20°, left −28°, right +36°; gyro directions all correct too |
| Joint directions misconfigured? | — | If they were, it couldn't have stood for the first 21 seconds at all |

Everything was correct. But "direction is correct" doesn't mean "zero is correct".

### 4.3 The key clue: what zero should be

There's a comment in the official training code (`microduck_velocity_env_cfg.py` in `microduck_rl`):

> `IMU_ORIENTATION_RANDOMIZATION_ANGLE = 6.0` …… zero-centered (random axis) — trains tolerance to misalignment *magnitude*, NOT a pitch bias. **The real board's systematic ~5° pitch offset is corrected at the source in the runtime (imu-pitch-offset), not here.**

Meaning: training only teaches "tolerance to a few degrees of random offset"; **a fixed pitch offset must be calibrated out on the real robot**, and the official duck itself has a systematic offset of about 5°.

Now look at the simulation: the MJCF `STAND` keyframe is the HOME pose (hips ∓26.2°, knees ∓0.3°, ankles ±26°…). In it the body quaternion is the identity, and **the IMU reads exactly 0°: during training, "standing at HOME" = "body level"**.

When we installed the IMU in the early morning, it read 4.95° from vertical at HOME. We assumed that was the duck's natural posture, only verified directions, and marked the parameters as "verified". **We missed verifying the zero.**

### 4.4 Using simulation to compute the "expected tilt" and subtract it to get the IMU offset

On the real robot the knees are often bent a few degrees at HOME, so the body **really** leans forward a bit; you can't treat the entire reading as offset. Method:

1. Take the **actual angles** of all 15 joints while the real robot stands still at HOME (`capture_home.py`);
2. Put them into the official MJCF: using the foot pose of the `STAND` keyframe as the "flat on the ground" reference, substitute the real joint angles, require both feet to stay flat on the ground, solve back for the body orientation, and read gravity at the IMU site (`sim_home_tilt.py`, kinematics only, computes in a few milliseconds);
3. Real IMU reading minus the "expected" value is the IMU mounting offset.

| Stance | From joint angles, the body should be | IMU reads | Offset |
|---|---|---|---|
| Knees in position (< 1° off HOME) | Pitched forward +0.4°, rolled right +0.2° | Pitched forward +8.6°, rolled right +1.9° | **Forward pitch +8.2°, right roll +1.7°** |
| Knees sagging 6°–9° | Pitched forward +8.1°, rolled right −0.2° | Pitched forward +16.9°, rolled right +1.6° | **Forward pitch +8.9°, right roll +1.8°** |

The offsets computed from the two stances differ by only 0.7°, showing the offset comes from the module itself being mounted crooked, not from the stance.

### 4.5 Changing the IMU mount parameters

robotd's convention (`duck-control/src/imu.rs`): the mount quaternion M is `[w,x,y,z]` and describes the rotation "sensor → body"; gravity in the body frame = M applied to the gravity measured by the sensor. The compensation is to pre-multiply a small rotation: **M′ = C ⊗ M**, where C rotates about body +Y by the pitch offset and about +X by the roll offset (`imu_mount_fix.py`).

- Least squares over both data sets: pitch 8.54°, roll 1.78°, residual 0.35°;
- Original `[0.5, 0.5, 0.5, 0.5]` (just an axis swap) → new `[0.454164155, 0.544101455, 0.527409117, 0.468538313]`;
- Written into `["imu_mounts"."bno08x"]` in `/etc/robot/feetech-ft5/hd1910-calibration.toml` (backup `.bak-20261012-imu8deg`); robotd restarted **with torque off**;
- Retest (standing at HOME, left knee sagging 3.3°): expected forward pitch +2.0°, measured +1.4°; **remaining offset −0.55° / −0.47°**.

### 4.6 Why the reading changes

Standing at HOME with nearly identical joint angles, the IMU forward-pitch reading was first 5.2° and later 8.6°, a change of 3.4°. The joints didn't change but the reading did, so most likely **the IMU module itself got knocked**: it fell several times in between, and the IMU wiring was pressed once. Printed parts flexing under load, slack in the servo horns and uneven floors can also account for a degree or two.

So **the IMU module must be fixed rigidly**. After a hard fall, bumping the IMU, or rewiring, spend a minute rechecking per §4.4; if the offset exceeds 1°–2°, recalibrate.

## 5. Poor contact on the IMU module: robotd marks the IMU stale and the duck goes limp

**Symptom**: the duck suddenly goes soft, pressing Start returns "nothing to start" (state Limp), and `robotctl health` shows `orientation frozen — N stale reads`. robotd log: `trunk IMU reader fault … SHTP header: No such device or address (os error 6)`.

**Cause**: `No such device or address` (ENXIO) means the I²C address isn't responding; the BNO085 has "disappeared" from the bus. robotd treats a non-updating IMU as a read failure and enters protection (torque off) after consecutive failures, which is correct in itself. Our driver re-identifies the IMU on its own after it recovers (`BNO08x identified`), with no need to restart robotd.

**How we determined it was poor contact** (`imu_fault_ctx.py` matches each dropout with the state at that moment): during all 77 dropouts the servo voltage was 7.3–7.5 V, so it wasn't a supply sag; most happened while walking with the body swaying, but some happened while completely still, meaning some point had already come loose; dropouts came in bursts, disconnecting, recovering and disconnecting again within a dozen seconds or so. The user checked and it was indeed poor contact; after resoldering and strapping it down, there were 0 stale IMU ticks in 1010 ticks.

**What to do**: solder the IMU module's wires or use latching connectors, with hot glue for strain relief at both ends. If the wire runs through the neck, leave enough slack. Solder close to the module, and after soldering recheck the zero per §4.4.

## 6. Knees sag when standing at HOME

**Symptom**: pressing HOME the same way, sometimes both knees reach position, sometimes they're bent 5°–9° (left knee +8.3°, right knee −6.2°; the opposite signs are due to mirrored mounting, both are actually sagging in the bending direction), and the body really pitches forward with them, reading up to 17°. robotd requires joint error ≤5° and body tilt ≤10° before handover; if exceeded it won't let the model take over and only returns to HOME.

**Cause**: HOME uses the P5 gain from training (the BAM parameters in kissqy's deployment contract), which is fairly soft, and the knees carry the most weight. Depending on how it stood up (hand-held or not, feet flat or not), it ends up in a different position.

**What to do**: put it on a flat floor, take your hands off, wait for it to settle on its own, then press Start the second time. Changing the gain would depart from training conditions; not recommended just for this.

## 7. First alternating steps

After IMU calibration and resoldering, we pushed the stick three times (`walk_report.py`):

| Command | Duration | Alternating knee swing | Leg switches | Body tilt | Fell |
|---|---|---|---|---|---|
| 0.14 m/s | 5.0 s | 24° | about 11 | −0.7° to +1.6° | No |
| 0.14 m/s | 2.5 s | 21° | about 8 | −1.1° to +1.6° | No |
| 0.21 m/s | 6.3 s | 39° | about 26 | −1.0° to +3.4° | No |

The two legs alternate rhythmically, and the larger the command, the bigger the swing. The user's impression was "so-so": you can't tell from the video how far it moved forward. kissqy's reminder: **the soles need to be TPU**; hard plastic soles slip on the floor and it just steps in place. In the parts list for episode 1 of 机械行者Robo's assembly video, the foot assembly includes a "foot plate / anti-slip pad".

## 8. Still unresolved

- **Cooling**: with services off and the SSH storm gone, the CPU still reaches 85°C after about 10 minutes of running the model and throttles to 408–600 MHz. robotd uses 30%–46% of one core while running the model, and the board can't shed heat inside the head shell. Need vent holes and an airflow path.
- **The mouth servo sits at 60–70°C while standing**, far above the other servos' average (41°C); the closed position may be pushing against a mechanical stop. Need to check the mouth's zero position.
- **Filter A/B**: the model was trained without filtering (deployment contract `action_filter.enabled = false`, 1/1/1), while kissqy uses 0.9 / 0.5 / 0.7 at runtime. Tonight after IMU calibration we still used the latter, with no comparison.
- **Forward speed**: robotd's odometry isn't computed; need to mark the floor and measure from video.

## 9. What we changed on the board tonight, and how to revert

| What changed | Why | How to revert |
|---|---|---|
| Commented out `pam_motd.so motd=/run/motd.dynamic` in `/etc/pam.d/sshd` | SSH login no longer runs the 3.8 s welcome script | `cp /etc/pam.d/sshd.bak-20261012 /etc/pam.d/sshd` |
| `duck-quiet.sh quiet`: turns off btd, configd, gamesir-xboxd, updaterd, robot-boot-check.timer | Not needed for walking; reduces heat | `sudo bash duck-quiet.sh restore` (temporarily `systemctl start configd` when pairing a gamepad) |
| `["imu_mounts"."bno08x"].quat` in `hd1910-calibration.toml` | IMU zero calibration (§4.5) | Backup `hd1910-calibration.toml.bak-20261012-imu8deg` |
| `/etc/systemd/system/duck-rec.service` | Records 50 Hz state plus voltage and temperature to `/home/duck/r17/rec/` at boot | `systemctl disable --now duck-rec` |
| Bluetooth pairing `Pro Controller 98:B6:E9:04:1F:9E` | Physical gamepad | `robotctl pad forget <address>` |
| `webpad.py` was modified experimentally, then restored to the original | — | Original backup `webpad.py.orig-20261012` still present |
| Temporary config to run padd as root | Tried, didn't help | Deleted |

The web console patch on the PC is in the working tree (local) of kissqy's branch `hd1910-trunk-imu-i2c`.

## 10. Scripts used

All in [`tools/radxa/onboard-analysis/`](../tools/radxa/onboard-analysis/), read-only; see the README there. The full IMU zero calibration procedure is also written there.

## 11. Next steps

1. **TPU soles**, and mark the floor to measure forward distance and speed (addendum 10-14: our soles are actually already TPU 95A, on the hard side; see [10-14 daytime log §6](HD1910-20261014-白天-仿真找原因与新版放开参数.md#6-脚底摩擦和鞋底));
2. **Manual calibration tool**: turn §4.4 into a button-driven flow (direction check + standing zero, compute and present new parameters, write only after confirmation, log every run). While standing at HOME, compute the offset in the background and warn if it exceeds 2°, but **don't change it automatically**: the duck may be held by hand or standing on a slope;
3. **Filter A/B**: run once each with 1/1/1 and 0.9/0.5/0.7, comparing standing sway and stepping;
4. Cooling, mouth servo;
5. kissqy's one-click image R1: our V1.12 board needs the version with Radxa's bootloader swapped in ([`kissqy-r1-v112.sh`](../tools/radxa/kissqy-r1-v112.sh)). His image only recognizes the bus IMU daughterboard and can't use the BNO085 module, so either flash his IMU firmware onto our imu_to_dxl board, or port the I²C IMU patch onto his already-published V164 source;
6. Preparing to switch to an LSM6DSV16X on HAT J5: J5 is I2C3 (40-pin header pins 3/5) and needs the `i2c3-m0` overlay, at the cost of USB-C no longer negotiating PD. On the C1 HAT this bus already has the aic3104 (0x18) and BMI088 (0x19 / 0x68); the LSM6DSV16X uses 0x6A / 0x6B, so there's no conflict. robotd's `lsm6dsv16x` reader has only been tested on a simulated bus.
