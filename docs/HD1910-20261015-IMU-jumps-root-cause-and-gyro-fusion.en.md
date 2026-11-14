# 2026-10-15 · Root cause of "falls after two or three steps": BNO085 orientation jumps; with gyro fusion on the robot it walks steadily

**English** · [简体中文](HD1910-20261015-IMU乱跳根因与陀螺融合上机.md)

**Robot**: unit #1, new card (kissqy V167 / control.43 + our fork's I²C IMU), BNO085 module glued inside the body, connected to the board's I2C4 (0x4B); servos all at defaults (P = 5, D = 0, torque limit 1000, no parameter file); joint Walk model action scale 0.9, head filter 0.5, leg filter 0.7; full silicone soles; whole duck with battery **806 g** (kissqy trained with 820 g).
**Background**: after fixing the crooked IMU mount on the night of 10-12, the duck could stand and step, but from 10-12 to 10-14 it kept "falling after two or three steps when the stick is pushed". In between we tried changing soles, tuning servo D, tuning filters and scale, and comparing with simulation, none of which solved it (see [10-13 night](HD1910-20261013-夜-掉电-舵机D与蹭地.md), [10-14 daytime](HD1910-20261014-白天-仿真找原因与新版放开参数.md)).

**One-line conclusions**:
1. **Root cause**: the orientation **computed by the BNO085 chip itself** (game rotation vector) jumps 20–60° within 20 ms while walking (about half of the episodes start around foot touchdown), while at the same moment the chip's gyro says the body has barely rotated. The gravity direction the model sees jumps along with it, which amounts to suddenly being told "you're falling"; it corrects, and then it really falls. The chip's gyro itself is fine.
2. **Fix** (software only, no sensor change): robotd integrates its own orientation from the chip's gyro, compares it with each orientation the chip reports, follows slowly when the difference is small, and distrusts the chip when it's large. Config option `[trunk_imu] bno08x_fusion = "gyro"`.
3. **On-robot results** (10-15 evening, measured):
   - Original mode (`chip`): upright for 62 s in walk mode (9 s of that with the stick pushed), 3 falls;
   - New mode (`gyro`): upright for 634 s in walk mode (60 s with the stick pushed, the rest standing and stepping in place), not a single fall while the stick was pushed, only 1 fall in total (between two stick pushes);
   - During the same period the chip jumped 745 times as usual, but the model's input didn't jump with it. In the orientation the model saw there was only 1 jump over 5° (7.2°), when IMU data stalled for about 0.1 s and caught up in one frame on recovery, not a fusion jump (§5.4).

   The user's on-site judgment was "chip falls like crazy, gyro basically never falls, very stable", and **decided not to do alternating comparisons and to just use gyro**. So there is **no** complete A/B statistic here, only the two recordings above and on-site observation.
4. **Still unresolved**: turning is very weak (turning in place reaches only about a quarter of the command); at 19:31 the whole board rebooted once (same symptoms as on 10-13, no shutdown sequence; brownout or crash not determined); the fusion thresholds haven't yet been re-derived from tonight's 100 Hz data.

| | Current state |
|---|---|
| Gyro fusion (`gyro` mode) | In use on our duck. The build at the time came from the `hd1910-v167-gyro-fusion` branch; the default is still `chip`, so you have to switch it yourself |
| Formal A/B statistics | Not done (user's on-site decision) |
| Raw 100 Hz log | One file, about 37 MB (about 13 MB from the shadow phase), no dropped lines; only used to check the stop-rule cases, thresholds not yet re-derived from it |
| Turning | Weak, cause in §6.1, not yet tuned |
| Whole-board reboot | Happened again tonight, cause not determined, waiting for the 10 A supply comparison |

---

## 0. Issues at a glance

| # | Question | Conclusion | Evidence | Details |
|---|---|---|---|---|
| 1 | Why does it fall after two or three steps | The BNO085's own computed orientation jumps at touchdown and misleads the model | Measured (recordings, about 600,000 frames) | §3 |
| 2 | A group member got it working with the same servos, model and parameters; why can't we | Compared the differences one by one; the IMU chip is the biggest | Group chat + measurements | §2 |
| 3 | How to fix it | Integrate orientation from the chip's gyro ourselves, using the chip's orientation only for slow correction | Code + replay + on the robot | §4, §5 |
| 4 | Did the fix work | Yes: with the stick pushed, from "2 falls in 9 s" to "no falls in 60 s" | Measured (two recordings, no alternating comparison) | §5 |
| 5 | Why the jump-detection yardstick gives false alarms during falls | The gyro in the recordings went through a three-point median and is one frame late, so extrapolating during fast rotation is off by 5° | Measured + review | §5.5 |
| 6 | Why turning is weak | Joints only reach about half of their targets and the feet can't lift; unrelated to the IMU | Measured | §6.1 |
| 7 | Whole-board reboot | Not determined | Black box logs | §6.2 |

---

## 1. Symptom: falls after two or three steps (10-12 to 10-14)

- With the model in control, standing is steady; push the stick and after two or three steps it pitches forward or sideways and falls.
- We tried four kinds of soles: tape, TPU, rubber and silicone. The grippier the sole, the more likely it falls. With tape and TPU it was actually slipping and never really walked; only once silicone stopped the slipping was the problem fully exposed.
- The stiffer the servos (the larger D), the more likely it falls.
- On 10-14 we briefly thought it was "the knees only swing 1/3, the servos can't keep up" and planned to retrain the model.

## 2. Troubleshooting strategy

### 2.1 Compare differences one by one with someone who got it working

Someone in the group got it working with **the same HD-1910 servos and the same kissqy model**. We asked about his servo parameters and the answer was "P5 D0, everything else default", i.e. the state of V167 without a parameter file. So the servos and the model themselves are fine, and the problem lies in the differences between us and him. We listed the differences and went through them one at a time:

| Difference | How we checked | Result |
|---|---|---|
| Servo parameters | Made them the same as his: no parameter file (P5 / D0 / 1000), scale 0.9, head 0.5, leg 0.7 | That's tonight's setup, and chip mode still falls |
| Mass | Weighed the whole duck | 806 g vs. 820 g in training, 1.7% difference, ruled out |
| **IMU chip** | Ours is a BNO085; kissqy's one-click image only recognizes his bus IMU daughterboard (ST's LSM6DSV16X), so we **infer** the person who got it working used the ST chip (not asked directly) | **Prime suspect, see §3** |
| Power supply | 10 A bench supply arriving 10-16 | Not yet checked |
| Soles | Didn't ask what material his are | Not yet checked |
| Mechanics | — | Not yet checked |

### 2.2 First find "physically impossible" data, then tune

From 10-12 to 10-14 we tuned lots of parameters, and each time it was "maybe a bit better, maybe not". On 10-15 we changed approach: no tuning; first check whether the sensor data **is consistent with itself**.

The criterion is simple: the IMU provides both orientation (gravity direction) and gyro (angular velocity). Using this frame's gyro to propagate the previous frame's gravity direction forward 20 ms should give roughly this frame's gravity direction (`dg/dt = −ω × g`). A difference of 5° or more means "the gyro says it barely rotated, but the orientation jumped", which is physically impossible, so one of them must be lying.

### 2.3 Wrong turns we took (correction record)

- **"The IMU lags the joints by 54 / 64 ms" was a miscalculation** (10-14 night): we used the wrong foot axes from the MJCF; retracted.
- **"Silicone soles trip the feet" was wrong** (10-14 night): the user corrected this. With tape and TPU it was actually slipping; once silicone stopped the slipping, what got exposed was exactly the IMU jumps (harder impacts).
- **"The servos aren't good enough, we need to retrain" withdrawn** (10-15): the user pointed out that "lots of people got it working with his", so the servos and model themselves are fine. "The knees only swing half" does exist (see §6.1), but it's not the main cause of "falls after two or three steps".

## 3. Analysis: the BNO085's own computed orientation jumps at touchdown

### 3.1 Results (10-15 morning, recordings from the old and new cards, about 600,000 frames, 50 Hz)

- **While walking the chip's orientation jumps in bursts**: tilt jumps 20–60° within 20 ms while the gyro rotates only 1–2° at the same moment. Of the 53 episode starts, about half are within 60 ms of a foot switch.
- **The jump rate depends on soles and servo stiffness** (in frames where the stick is pushed for walking):

  | Condition | Share of jump frames |
  |---|---|
  | Tape feet | 1.9% |
  | Silicone, P3 / D0 | 4.9% |
  | Rubber | 8.8% |
  | Silicone, P5 / D4 | 23.2% |
  | Silicone, P5 / D0 (10-15 evening, new card, chip mode) | 31.7% (only 546 frames, small sample) |
  | Standing still at HOME | 0.05% |

- **The median time to the first episode after starting to walk is 1.8 s**, which is exactly "two or three steps".
- **It lines up with falls**: about 80% of falls while walking had jumps within 1.5 s before the fall. All 3 falls in chip mode on the evening of 10-15 had jumps within 1.5 s before. This has no baseline (jumps already make up 30% of stick-pushed frames, so a random 1.5 s window often contains some), so it's only for reference; the next item and §5.4 carry more weight.
- **How badly the policy is misled**: within 0.6 s of an episode, the gravity direction the model sees deviates from the gyro integration by a per-segment maximum with a median of 31° (90th percentile 62°); walking without episodes, as a control, is only 0.8°.

### 3.2 What was ruled out

| Suspicion | How it was ruled out | Conclusion |
|---|---|---|
| Corrupt I²C reads | In the jump frames, the length of the raw quaternion (Q14) is normal (median 16384) | Not corrupt reads; it's the chip's own fusion output |
| The gyro can't be trusted either | Gyro vs. angular velocity derived from the quaternion: per-axis correlation 0.97–0.99, ratio 1.00–1.06; the legs' forward kinematics side with the gyro | The gyro is trustworthy |
| Crooked mount, coordinate frame, units | Tilt test: forward/back tilt changes only pitch, left/right tilt changes only roll; yaw mounting error about −1.7° ± 2° | No problem |
| Loose module | The user confirmed it's glued firmly and doesn't move at all | Not loose |
| Caused by linear acceleration | Correlation between the deviation and linear acceleration is about 0 | Doesn't explain it |

### 3.3 Mechanism (a guess)

Internally the chip uses the accelerometer to correct tilt. Foot impacts are very hard, the accelerometer reading goes haywire for a few milliseconds, and the chip's fusion algorithm drags the orientation off with it. The grippier the feet and the stiffer the servos, the bigger the impact and the more jumps, which is consistent with the table in §3.1. We can't see how the chip computes internally, so **this is a guess**, but the fix doesn't depend on it: as long as the gyro is trustworthy, we can stop trusting the chip's orientation.

## 4. Fix: integrate orientation from the chip's gyro inside robotd

### 4.1 Why software only

The user required no sensor change, only software. Recording the alternative too: to compare against an ST chip, a separate LSM6DSV16X module can be connected on the torso (the fork supports `source = "lsm6dsv16x"`, not yet tried on the real robot). The LSM6DSV16X onboard the official HAT revision D1 is on J5 (I2C3), and since the HAT is mounted in the head it can only serve as a head IMU, not replace the torso IMU; our BNO085 is on I2C4.

### 4.2 Algorithm (the minimal version after review)

The implementation at the time is documented in §2.6 of `robotd-design.md` on `hd1910-v167-gyro-fusion`. The flow is as follows.

- The chip reports the gyro every 10 ms, and robotd integrates it into its own orientation;
- Each time the chip reports an orientation, compare the tilt difference θ between the two orientations:
  - **θ < 6°**: trust the chip and follow it slowly with a 0.66 s time constant;
  - **θ ≥ 6°**: distrust the chip and ride on the gyro for this one;
  - **Distrust continuously for 0.5 s**: if the chip itself is steady and the body is still (e.g. lying down after a fall) → snap to the chip in one step; if still moving → pull toward the chip at no more than 5° per second, with no sudden jumps;
- Only tilt is handled; heading has no threshold;
- Time is always report sequence number × 10 ms, never host time (the host may read a batch of backlogged reports at once, but they are still 10 ms apart);
- After a gyro gap (sequence number jumps too far, or more than 100 ms of host time elapsed), wait for the chip to be steady for 0.5 s and then snap fully.

### 4.3 How we make sure nothing goes wrong

- **Default `chip`**: installing it changes nothing, and the orientation sent to the model doesn't differ in a single field from before (pinned by a randomized-packet differential test); fusion only runs alongside in the background and outputs diagnostics. This is called **shadow mode**.
- **`gyro` must be switched on yourself**, using the command in section 4.4 of IMU-MODULE.md (written with kissqy's own `configure.py` on the board; **don't add it by hand with nano or sed**: two keys with the same name in one section make every version of robotd fail to start).
- **Internal fusion error**: the panic is caught, fusion is turned off (`disabled`), and it automatically falls back to sending the chip's orientation.
- **Raw log**: `bno08x_raw_log` writes every chip report to a CSV, capped at 64 MB; if disk writes can't keep up it counts dropped lines rather than slowing the IMU.
- **Stop rules**: every on-robot step has a rule of "if you see this, fall back to chip" (§5.5).
- **Rollback**: the install script makes backups automatically, and `rollback <backup directory>` returns to the pre-install state in one command.

### 4.4 Process (each step: design and review first, then implement)

1. **Design**: first only a design, replaying a Python reference implementation offline on the 50 Hz recordings and comparing several thresholds and following methods. Replay of the early prototype (4° threshold): jumps in the divergent segments dropped from 72 to 0, and the median difference from the chip while standing still was 0.08°.
2. **Design review**: the independent review cut it down to the minimal version, see §4.2. Replaying the minimal version on the same recordings: 0 steps during upright walking (all 4 were after falling), median difference from the chip while standing at HOME 0.011°.
3. **Implementation**: pure Rust core + hooked into BNO08x reading + config option + diagnostics + raw log + install script preserving the new key + documentation, 10 commits.
4. **Two rounds of code review**; the two must-fix items:
   - Writing the key with sed twice produces a duplicate key, and every version of robotd exits at startup step 1 → changed to write it with `configure.py`, which gives the same result no matter how many times it's run;
   - The 4 "steps" in the replay were all after falling → stop rules only count upright walking frames.
5. **Tests**: Rust 673 passed / 17 failed, with the failure list identical to the unmodified baseline; fake-board install tests 73/73; replay tests on 4 recordings, Rust and Python equal one by one.

## 5. On the robot (10-15 evening)

### 5.1 Preparation

Read-only survey → backup (packed on the board, pulled back to the PC and sha-checked) → uploaded 9 files, sha-checking each → install script runs `check` first, then `install`. This was the first run of this version of the install script on a real board, and it passed first time. Checks: `bno08x_fusion="chip"` in the robotd startup log, counters `mode=chip`, `disabled=false`.

### 5.2 chip shadow: standing still, tilting, walking

| | Result |
|---|---|
| Upright walking | 3382 frames (68 s; excluding 5.7 s with tilt >30°, 62 s counted), stick pushed 9 s, 3 falls |
| Chip path (what the model sees) jumps >5° | 330, max 65°; 31.7% of stick-pushed frames |
| Shadow fusion path | 0 (counted on the aligned basis, see §5.5) |
| Fusion decisions (upright walking frames) | Accepted 2860, rejected 533, followed 1 |
| Standing still, tilt difference between fusion and chip | All standing frames: median 0.009°, P90 0.031°; worst 10 s window: median 0.043°, P90 0.271° |
| Gyro gaps, realignment after gaps | 0, so the somewhat conservative rule "host time > 100 ms counts as a gap" doesn't need changing |

### 5.3 gyro standing still and tilting

After switching to `gyro`, standing still for 455 s (46 windows of 10 s): in the worst window the tilt difference between fusion and chip had a median of 0.026° and P90 of 0.096° (stop rule is 0.5° / 1°); not a single rejection, realignment or error. Tilt test: leaning back, orientation change 16.7° vs. gyro integration 16.7°; returning upright −18.0° vs. −17.7°.

### 5.4 gyro walking

| | chip (shadow segment) | gyro |
|---|---|---|
| Time upright in walk mode | 62 s | 634 s (outside of stick pushes, standing and stepping in place) |
| Stick-pushed time | 9 s | 60 s (13 forward pushes, sometimes diagonal, 1–8 s each) |
| Falls | 3 (2 while the stick was pushed) | 1 (not during a push) |
| Chip path jumps >5° | 330 (this is what the model saw) | 745, all blocked by fusion |
| Jumps >5° seen by the model | 330 | 1 (7.2°): IMU data stalled for about 0.1 s (gyro and orientation not updated for 3–4 consecutive frames) and caught up in one frame on recovery; the fusion decisions before and after were all accepted, so not a fusion jump; related to the known "stale IMU frames" |
| Fusion decisions (upright walking frames) | — | Accepted 29484, rejected 2228, followed 13, realignments and errors 0 |

By stick-pushed time, chip falls about 14 times per minute and gyro 0. The two segments weren't alternated and the chip segment is very short, so **this is not an A/B conclusion** (`ab_blocks.py` would compute p = 0.016, but that presumes the two segments are comparable, which doesn't hold here, so it isn't taken as a conclusion). The user watched on site and decided to stop comparing and just use gyro.

### 5.5 Stop rules: the jump-detection yardstick gives false alarms during falls

**Symptom**: in the chip shadow segment, counted the original way, the fusion path had 5 jumps over 5°: 4 within 0.5 s before a fall, and 1 right after a stick push ended while the body was swaying hard. Simulating gyro mode's publishing path (the published value also passes through the median and is paired with the current frame's gyro, with delay alignment) gives 0, but the maximum is 3.75°, only 1.25° short of 5°, and all at the moment of falling. The original rule of "fall back to chip after 1 occurrence" could be triggered by a fall itself at any time.

**Cause** (re-checked by independent review): `imu.gyro` in the recordings passes through a three-point median and is one frame behind reality; `imu.fusion.fused` doesn't pass through the median. Using one-frame-late angular velocity to extrapolate an undelayed orientation is off by 5° when the body rotates fast (130–640° per second during a fall). All 5 happened in frames where fusion "rejected", and in such frames fusion only integrates, so it can't jump in one step; the rotation angle of the fusion quaternion between two frames matches the integration of the 100 Hz raw gyro (within one report of alignment). Extrapolating with the next frame's gyro instead gives 0.

**Revised rules** (reviewed):
- For each jump, look at the fusion decisions within ±2 frames:
  - If there's `realign_long`, `realign_gap`, `fallback` or `follow` (the only four through which fusion can jump in one step) → **fall back after 1 occurrence**, with no exemptions;
  - If there's only `accepted`, `rejected`, `slew` → don't count those within 1 s before a fall or where the previous frame's tilt was already ≥30°; for the rest, fall back at ≥3 per segment, and record 1–2 and examine each one.
- An IMU read stall (a few frames not updating, catching up in one frame on recovery) also counts as a soft step; the 1 case in gyro walking was exactly this. A longer block might accumulate 3, in which case examine each to see whether it's a stall.
- Judging script: [`tools/radxa/onboard-analysis/judge_block.py`](../tools/radxa/onboard-analysis/judge_block.py); counting falls per segment and falls per minute: [`ab_blocks.py`](../tools/radxa/onboard-analysis/ab_blocks.py).

## 6. Still unresolved

### 6.1 Weak turning: joints only reach half (inferred to be unrelated to the IMU)

| Action | Commanded turn rate | Actual turn rate |
|---|---|---|
| Turn right in place | 58°/s | 15°/s |
| Turn left in place | 84°/s | 19°/s |
| Turn while walking (3 segments) | 61–79°/s | −4 to 11°/s, once turning the wrong way |
| Backing up while turning (1.2 s) | −79°/s | −43°/s (small sample) |

Ratio of the model's targets to what the servos actually reach (ratio of joint angle standard deviations, using only upright frames with nonzero stick): hip yaw 57–95%, hip roll 31–56%, knee 48–55%, hip pitch 45–67%. The legs only swing half as much, the feet can't lift, and there's no way to rotate the foot in the air; the full silicone feet grip firmly, so they can't twist on the ground either (**a guess**). We infer this is the "knees only swing half" mentioned before, previously masked by the IMU jumps. Turning has only been tested in gyro mode after the reboot, not in chip mode; per the code, the angular velocity used for turning is the chip's raw gyro in both modes, so we **infer** it's unrelated to this change.

Next steps, one change at a time: first ask the group member who got it working whether turning works well and what his soles are made of; then try action scale 0.9 → 1.0; then servo P 5 → 6, 7; compare again once the 10 A supply arrives.

### 6.2 Whole-board reboot (19:31:42)

The duck was standing in place in walk mode when the logs suddenly cut off with no shutdown sequence, and the recording file ended with a run of null bytes, indicating a brownout or crash. Just before, the battery was at 7.59 V, CPU at 78°C, WiFi normal. It's the same kind as the "whole-board reboot" on [10-13 night](HD1910-20261013-夜-掉电-舵机D与蹭地.md). robotd is an ordinary process, and if it crashed it would just restart itself, not reboot the whole board, so we **infer** it's unrelated to this change. But at the time the raw log was continuously writing to the card and the CPU was at 78°C, two things different from 10-13, which haven't been ruled out. Cause not determined; compare once the 10 A supply arrives.

### 6.3 Other

- The thresholds 6°, 5°/s and 0.5 s are initial values set from 50 Hz recordings; tonight we recorded a 100 Hz raw log but haven't used it to re-derive them yet; the true ordering of gyro and orientation within the same packet (and whether to compensate ahead) hasn't been examined either.
- The LSM6DSV16X hasn't been tried on the real robot.
- `gyro` isn't the default yet; you have to switch it yourself.

## 7. How to follow along (for BNO085 module users)

1. Wire it up and confirm the IMU orientation per the [replica image getting-started guide](../software/image/烧录和第一次使用.md). Reproducing this page's experiment requires the `hd1910-v167-gyro-fusion` build from that time.
2. First stand and walk in the default `chip` mode while recording ([`duck_rec.py`](../tools/radxa/onboard-analysis/duck_rec.py)), and use `judge_block.py` to see how much the chip path jumps.
3. Switch to `gyro` with the command in section 4.4, `reconnect` (this turns torque off, so hold it), stand still for 5 minutes and watch θ, then walk.
4. Check the counters before and after each segment (the command in section 4.4), and decide per the rules in §5.5 whether to fall back to `chip`.

## 8. Key points for those who come after, and for AI

- **First check whether the data is consistent with itself, then tune.** The most crucial step this time was using "orientation propagated from the gyro vs. orientation given by the chip" to find physically impossible jumps. The previous three days of tuning were all fighting a model that was being deceived.
- **Compare differences one by one with someone who got it working.** With the same servos, model and parameters, if someone else can walk, the problem is in the differences.
- **Shadow mode first**: a new algorithm first only runs alongside without publishing, and is switched on only after real-robot data confirms it's fine.
- **The criterion can lie too**: the jump-detection yardstick must be aligned with the data's latency (the gyro in the recordings went through a three-point median and is one frame late).
- **Keep corrections on record**: wrong conclusions ("IMU lags 54 ms", "silicone trips the feet", "the servos aren't good enough, retrain") all keep their correction records; don't delete them.

## 9. Data and scripts

- Recordings, raw logs, counters: private directory on the debugging PC `Radxa-Zero3W/调试记录/陀螺融合上机-20261015/` (not uploaded as a public attachment).
- Scripts: `judge_block.py` and `ab_blocks.py` in [`tools/radxa/onboard-analysis/`](../tools/radxa/onboard-analysis/).
- The historical implementation branch is `hd1910-v167-gyro-fusion`, documented in that branch's `trunk-imu-i2c.zh-CN.md`. For public use, start from the [replica image getting-started guide](../software/image/烧录和第一次使用.md).
