# 2026-10-14 daytime · Using simulation comparisons to find the cause of foot scuffing, soles, and unlocking P / D / torque in the new version (not yet on the robot)

**English** · [简体中文](HD1910-20261014-白天-仿真找原因与新版放开参数.md)

**Robot**: same as [10-13 night](HD1910-20261013-夜-掉电-舵机D与蹭地.md). The duck was offline during the day, so **this page is entirely PC-side analysis and code preparation, with no new on-robot data**. All real-robot data used comes from the recordings made on the old card between the afternoon of 10-13 and the early morning of 10-14.
**Background**: on the night of 10-13 we found that both feet clear the ground by only half as much as in simulation (3–6 mm vs. 11–12 mm) and the stance knee can't straighten; after D was set to 0, the left toe pointed down when stepping.

**One-line conclusions** (items 1–5 are findings in simulation, none yet verified on the real robot):
1. **Simulation conditions must be aligned before comparing with the real robot**. This morning's simulation sets used action scale 1.0, no filtering and a 737 g duck, which differ from the real robot. On the real old card, the joint model's actual action scale is about 0.83 (0.9 × voltage compensation), leg filter 0.7, head filter 0.5; the HD-1910 model kissqy trained with is 820 g (we haven't weighed ours, so we estimate with that for now). After alignment (Luwu parameters, P4, 820 g), the simulated stance knee is −3.4° / −3.5°, close to the real robot's −4.5° / −2.6°; clearance is 7.4 / 7.3 mm vs. the real robot's 4.8 / 5.8 mm. **In simulation, "the stance knee can't straighten" is mostly explained by scale, filtering and mass**; but that simulation set jitters (see the next item), and voltage wasn't aligned either.
2. **After alignment, simulation shows high-frequency jitter that the real robot doesn't have**: jitter makes up 96%, step frequency 4.1 Hz, whereas the real robot at D0 has only 6% and 3.0 Hz. A few other cases in simulation do the same: soles too slippery (friction 0.3), Feetech parameters with P3, and Feetech parameters with 200 g or more added to 737 g (Luwu parameters at scale 1.0 don't jitter even with 300 g added). Simulation and the real robot don't agree on this point, and we haven't found why, so simulation can only be used to find directions, not to draw conclusions directly.
3. **Action scale is a knob that's already adjustable**: with filtering in both cases, raising the scale from 0.83 to 1.0 raises simulated clearance from 11.1 / 10.4 mm to 14.0 / 13.0 mm and the stance knee from −1.3° / +0.1° to +3.2° / +6.1°. But the real robot can't get that much: changing the joint scale from R17's 0.9 to 1.0 (V164's default is already 1.0) still gets multiplied by voltage compensation (about 0.925 at 8.0 V), so the actual scale only rises from 0.83 to about 0.925, an 11% increase, versus 20% in simulation. Estimating linearly, the real-robot gain is only about half of simulation's (simulation didn't run the 0.925 set). Worth trying on the real robot, while keeping an eye on power.
4. **Two factors have little effect**: with or without a 70% output cap, simulation results are nearly identical (with Luwu's parameters only peaks are clipped, and Feetech's parameters never hit it), not verified on the real robot; speed isn't the cause of the gap either: the real robot's median when the stick is pushed is 0.21–0.25 m/s, and the simulation comparison used 0.2.
5. **Soles**: our soles are TPU 95A, on the hard side; kissqy says his 90A ones went hard and slippery after two days. In simulation an overly slippery floor turns into shuffling steps plus jitter, but the real robot at D0 doesn't jitter, so we can't say the problem is the soles. Softer soles are cheap and worth trying.
6. **Standing at HOME, the two feet aren't coplanar laterally**: the difference comes entirely from the two hip roll joints not reaching the HOME target; it's different every time it settles, always in the "legs splaying outward" direction, apparently pressed by body weight (a guess, based on measured joint angles plus simulation geometry). A zero offset can't be seen with this method and hasn't been ruled out.
7. **We unlocked P / D / torque limit and head/leg filters in kissqy's new version (V164) locally**: code, tests and review are done, **not yet on the robot**, not public.

| | Current state |
|---|---|
| Soles | TPU 95A; buying 85A TPU and silicone / rubber anti-slip pads, not yet swapped |
| Whole-duck mass | Not weighed |
| Adjustable P / D / torque in the new version | Code done, tested, reviewed; not yet installed on the new card |
| Simulation script | Local only (can swap servo parameters, action scale, output cap, added mass, friction, head/leg filters), not in the repo; command in §1 |
| To do tonight | §10 |

---

## 0. Issues at a glance

| # | Question | Conclusion | Evidence | Details |
|---|---|---|---|---|
| 1 | Why simulation lifts higher and straightens the knee more than the real robot | This morning's simulation conditions differed from the real robot; after aligning scale, filtering and mass, the knee is close to the real robot | Simulation | §1, §2 |
| 2 | Why simulation jitters after alignment | Not investigated; the real robot at D0 doesn't jitter | Simulation | §2 |
| 3 | Do Luwu's or Feetech's official parameters better match our servos | At scale 1.0 Feetech's look more alike; after aligning conditions both are close, and Feetech's gait breaks down with added mass | Simulation | §3 |
| 4 | Does the 700 torque cap clip motions | With or without a 70% cap in simulation, results are nearly identical; not verified on the real robot | Simulation | §3 |
| 5 | Is the whole duck too heavy | Simulation is 83 g lighter than kissqy's training model; we haven't weighed ours | Simulation; not weighed | §4 |
| 6 | Is the commanded speed too low | Not the cause of the gap; pushing to the full 0.3 m/s lifts about 2 mm more | Measured speed + simulation | §5 |
| 7 | Are the soles too slippery | In simulation too slippery means shuffling plus jitter, which doesn't match the real robot at D0; softer soles are worth trying | Simulation | §6 |
| 8 | The feet aren't coplanar laterally; is it the zero position | The part that varies each time isn't the zero position and looks like it's pressed by body weight (a guess); the zero itself can't be seen with this method | Measured joint angles + simulation geometry | §7 |
| 9 | P / D / torque can't be adjusted on the new card | Locally adjustable version written, not yet on the robot | Code + tests | §8 |
| 10 | The new web console's "修复手柄连接" (Fix gamepad connection) does nothing for the G50 Pro | It only recognizes the GameSir Nova 2 Lite | Read the code | §9 |

---

## 1. How the simulation was done, and how it differs from the real robot

- **Model**: kissqy's walking model, the very `walk/policy.onnx` running on the real robot, completely unchanged;
- **Simulation**: the scene `scene_backlash.xml` (with backlash) from the official training project 0.15.1, with servos modeled by BAM (the servo physics model). We locally modified the inference script in the training project and added several switches: swap the servo parameter file, cap servo output (corresponding to the torque limit in simulation), add mass to the torso, change sole and floor friction, and head/leg filters (same as robotd: each tick "new target = α × model target + (1 − α) × previous target"); action scale was already a parameter of the script. **This script is local only and not in the repo**; the command looks like this (bracketed parts are added as needed):

  ```
  HEADLESS=1 SIM_SECONDS=24 BAM_JSON=<servo parameter json> MAX_PWM=0.7 \
    [EXTRA_MASS_G=83] [FRICTION=0.3] [HEAD_LOWPASS=0.5 LEGS_LOWPASS=0.7] \
    python infer_policy_kq_cmp.py --walking walk/policy.onnx --new-cmd-obs \
      --lin-vel-x 0.2 --kp-fw 4 --action-scale 0.83 \
      --scene src/mjlab_microduck/robot/microduck/scene_backlash.xml --save-csv 输出.csv
  ```
- **How we compare**: the simulation recordings are converted into the same format as the real-robot recordings and analyzed with the same [`tools/gait-analysis/`](../tools/gait-analysis/) scripts;
- **Real-robot reference**: the P4 / D0 / 681 set with the IMU corrected, from the early morning of 10-14 ([10-13 night §5.2](HD1910-20261013-夜-掉电-舵机D与蹭地.md#52-几组参数对比每组走-842-秒)). Note it only walked for 12 seconds (the report script recommends 15 seconds or more for reliability), and the torque limit was 681, not 700.

**Condition comparison** (not aligned this morning; discovered during the afternoon review):

| Condition | Real robot (old card, P4 set) | kissqy training | This morning's simulation | Afternoon rerun (aligned) |
|---|---|---|---|---|
| Action scale | 0.9 × voltage compensation (7.4 / voltage, about 0.925 at 8.0 V) ≈ 0.83 | 1.0 | 1.0 | 0.83 |
| Head / leg filter | 0.5 / 0.7 | No filtering | No filtering | 0.5 / 0.7 |
| Whole-duck mass | Not weighed | 820 g (sum of part masses in the model package) | 737 g (official 0.15.1 model) | 820 g (all 83 g added to the torso, distributed differently from kissqy's, see §4) |
| Servo P / D | P4 / D0 | P5 / no D in the model | P4 / no D | P4 / no D |
| Torque cap | 681 | None | 70% | 70% |
| Servo voltage | About 8.0 V | Not checked | 7.4 V | 7.4 V |
| Forward speed | Median 0.25 m/s with the stick pushed | Random ±0.4 | 0.2 | 0.2 |

Also, the "Simulation" row in the table in [10-13 night §5.2](HD1910-20261013-夜-掉电-舵机D与蹭地.md#52-几组参数对比每组走-842-秒) was a different run: P5, 0.15 m/s, no torque cap, hence 11.4 / 11.8 mm. The P5 set on this page is at 0.2 m/s, 13.4 / 12.1 mm. The conditions differ, so don't compare them against each other.

---

## 2. After aligning conditions: the stance knee is close, but simulation gains jitter

Luwu parameters (the set kissqy trained with), P4, output cap 70%, 0.2 m/s. Servo voltage was not aligned (simulation 7.4 V, real robot about 8.0 V):

| Simulation conditions | Stance knee left / right (+ is straightening) | Foot clearance left / right | Body roll sway | Of which >4 Hz (jitter) | Step frequency |
|---|---|---|---|---|---|
| Morning: scale 1.0, no filtering, 737 g | +3.5° / +6.5° | 12.7 / 11.9 mm | 36.5°/s | 8% | 3.14 Hz |
| Only scale changed to 0.83 | −0.6° / +1.5° | 9.6 / 8.9 mm | 33.5°/s | 6% | 3.68 Hz |
| Only filtering added (scale 1.0) | +3.2° / +6.1° | 14.0 / 13.0 mm | 39.0°/s | 7% | 2.80 Hz |
| Scale 0.83 + filtering (= real robot settings) | −1.3° / +0.1° | 11.1 / 10.4 mm | 37.4°/s | 9% | 3.31 Hz |
| Plus mass up to 820 g | **−3.4° / −3.5°** | **7.4 / 7.3 mm** | 37.2°/s | **96%** | **4.10 Hz** |
| **Real robot** P4 / D0 / 681 | **−4.5° / −2.6°** | **4.8 / 5.8 mm** | 43.7°/s | 6% | 3.01 Hz |

How to read it:
- **Scale 0.83 is the main reason the stance knee can't straighten**: actions are 17% smaller overall, so the model's "straighten" push is smaller too. Changing only this, the knee drops from +3.5° / +6.5° to −0.6° / +1.5°;
- **Filtering actually makes the feet lift higher**: step frequency drops from 3.1 to 2.8 Hz and steps become slower and bigger. So with both added, clearance is only 1.5–1.6 mm lower than this morning;
- **Adding mass up to kissqy's training model's 820 g**, the stance knee is −3.4° / −3.5°, about the same as the real robot's −4.5° / −2.6°; clearance is 7.4 / 7.3 mm, still about 2 mm higher than the real robot. Note that we added all 83 g to the torso, while kissqy's model distributes it to the legs and head (§4);
- **But now simulation turns into 4.1 Hz shuffling, with jitter at 96%**, which isn't what the real robot does at D0. A few other cases in simulation also produce this shuffling plus jitter: soles too slippery (§6), Feetech parameters with P3 (§3), Feetech parameters with 200 g or more added (§4). Why the real robot doesn't do this hasn't been investigated; it may relate to the servo model or joint friction in simulation. Until this is understood, simulation numbers can only be taken as directional.

**What can be used**: changing scale 0.83 → 1.0 has a big effect in simulation (with filtering: clearance 11.1 / 10.4 → 14.0 / 13.0 mm, stance knee −1.3° / +0.1° → +3.2° / +6.1°). What can be done on the real robot is change the joint scale from 0.9 to 1.0 (in V164 this joint model already defaults to 1.0; R17 is 0.9), but it still gets multiplied by voltage compensation: at 8.0 V the actual scale only rises from 0.83 to about 0.925, an 11% increase, versus 20% in simulation. Estimating linearly, the real-robot gain is only about half of simulation's (simulation didn't run the 0.925 set). Item 3 in 10-13 night [§7.5](HD1910-20261013-夜-掉电-舵机D与蹭地.md#75-下一步一次只改一样) already planned to try this. A bigger scale also means more current, so sort out power first (10-13 night §2).

---

## 3. Two sets of servo parameters: Luwu's and Feetech's official

Two parameter sets: Luwu's published 1910 M6 (the one kissqy trained with) and Feetech's official HD-1910 ([parameter sources](HD-1910-M6参数来源.md)). We integrated Feetech's set **approximately**: the official release provides a dedicated HD1910 control model, but our simulation still uses the STS3215 control model that Luwu's set uses, with the official m6 parameters converted over (gain ratio 0.982, speed limit 100).

Morning (scale 1.0, no filtering, 737 g), P4, output cap 70%:

| | Stance knee left / right | Foot clearance left / right | Body roll sway | Jitter | Step frequency |
|---|---|---|---|---|---|
| Luwu parameters | +3.5° / +6.5° | 12.7 / 11.9 mm | 36.5°/s | 8% | 3.14 Hz |
| Feetech parameters | +0.6° / +3.3° | 10.9 / 9.9 mm | 36.8°/s | 7% | 3.35 Hz |

After aligning conditions in the afternoon (scale 0.83, filtering):

| | Stance knee left / right | Foot clearance left / right | Jitter | Step frequency |
|---|---|---|---|---|
| Luwu parameters | −1.3° / +0.1° | 11.1 / 10.4 mm | 9% | 3.31 Hz |
| Feetech parameters | −1.0° / −1.6° | 12.3 / 10.6 mm | 10% | 3.01 Hz |
| Luwu parameters, 820 g | −3.4° / −3.5° | 7.4 / 7.3 mm | 96% | 4.10 Hz |
| Feetech parameters, 820 g | −4.9° / −6.0° | 7.4 / 6.4 mm | 36% | 1.00 Hz (gait broke down) |

- This morning Feetech's parameters looked more like the real robot; after aligning conditions the two are about the same, and Feetech's set's gait broke down at 820 g. **Which parameter set better matches our servos can't be told in simulation**. To decide, run single-joint step responses on the real robot and compare against each set;
- **Torque cap**: at P5 and 737 g, results with or without a 70% output cap are nearly identical (Luwu parameters: uncapped 13.4 / 12.1 mm, capped at 70% 13.5 / 12.4 mm; with Feetech parameters the two data sets are exactly identical, meaning the cap was never triggered). With Luwu's parameters the knee occasionally needs more than 70% (last paragraph of 10-13 night §5.2), and only that peak gets clipped. This only shows that the effect is small in simulation under these conditions; **whether it can be ruled out on the real robot has not been verified**;
- **At P3, simulation is actually less stable than the real robot**: simulated P3 (scale 1.0) with Luwu's parameters sways 54.7°/s with clearance 9.7 / 11.0 mm; with Feetech's parameters it's 97% jitter, 4.27 Hz shuffling. The real robot at P3 / D0 sways only 30–36°/s with 4–8% jitter. This is the same kind of mismatch as the last item of §2.

---

## 4. Mass: the simulation model is 83 g lighter than kissqy's training model

- The official 0.15.1 simulation model's whole duck is **737.2 g**, of which the torso is 199.2 g;
- In kissqy's model package `deployment-contract.json`, the part masses add up to **820.0 g** (`model.total_mass_kg = 0.82`). In other words, he trained on an 820 g HD-1910 version of the model. Compared part by part with the official model, the extra 83 g is distributed as follows: torso +14.8 g; both legs together +40 g (per side `upper_leg` +10, `yaw2roll` (the right one is called `bearing_roll`) +5, `leg` +5); head and neck together +28 g (`jaw_soft` +13, `neck` +10, `yaw_roll_motion` +5);
- We **haven't weighed** ours.

This morning we added mass to the torso on top of 737 g (scale 1.0, no filtering, P4, output cap 70%). +100 g is roughly kissqy's training mass:

| Torso added mass | Luwu: clearance left / right, stance knee, jitter | Feetech: clearance left / right, stance knee, jitter |
|---|---|---|
| None (737 g) | 12.7 / 11.9 mm, +3.5° / +6.5°, 8% | 10.9 / 9.9 mm, +0.6° / +3.3°, 7% |
| +100 g | 11.4 / 11.1 mm, +3.2° / +4.5°, 6% | 8.9 / 8.6 mm, −0.1° / +0.9°, 9% |
| +200 g | 9.3 / 9.5 mm, +1.8° / +1.7°, 5% | 7.0 / 6.8 mm, −2.0° / −0.8°, **88%** |
| +300 g | 8.5 / 7.9 mm, +0.2° / −0.5°, 5% | 6.3 / 6.4 mm, −3.0° / −2.1°, **98%** |

- The heavier it is, the less the stance knee straightens and the lower the feet lift, in the same direction as the real robot; Feetech's parameters turn into shuffling plus jitter at +200 g or more;
- In simulation all the mass is added to the torso, while most of the extra mass in kissqy's model is in the legs and head (see above), which has a different effect; and our duck's mass distribution is even less known;
- **Weigh it**: a kitchen scale, lifting the power cable so it doesn't press on the scale. Compare the measured mass with 820 g: the heavier it is, the more suspicious this factor becomes. Everyone uses the HD-1910, so weighing one is already a useful reference.

---

## 5. Speed: not the cause of the gap

| | Forward speed |
|---|---|
| Real robot with stick pushed (median / max) | P3 / D0: 0.23 / 0.30; P4: 0.25 / 0.30; P5 / D0: 0.21 / 0.28; 10-13 afternoon P5 / D20: 0.13 / 0.30 m/s |
| Gamepad pushed fully | 0.3 m/s (padd's `--max-linear` default) |
| Model training range | Forward/backward ±0.4 m/s, lateral ±0.3 m/s, turning ±1.0 rad/s |

Simulation (Luwu parameters, P4, output cap 70%, scale 1.0, no filtering):

| Commanded speed | Foot clearance left / right | Stance knee left / right | Step frequency |
|---|---|---|---|
| 0.2 m/s | 12.7 / 11.9 mm | +3.5° / +6.5° | 3.14 Hz |
| 0.3 m/s | 15.0 / 13.9 mm | +5.5° / +8.6° | 2.93 Hz |
| 0.4 m/s | 16.7 / 16.3 mm | +6.0° / +10.0° | 2.72 Hz |

- The real robot's median with the stick pushed is 0.21–0.25 m/s, already no lower than the 0.2 used in the simulation comparison, so **the gap with simulation isn't caused by speed**. The slowest set, 10-13 afternoon (0.13), doesn't have lower clearance than the others either (6.9 / 6.5 mm; that set was D20, and like the P3 / D0 and P5 / D0 sets it was recorded before the IMU correction, with about 2 mm of bias);
- In simulation, the higher the speed, the bigger the steps and the higher the feet lift: pushing fully to 0.3 lifts about 2 mm more;
- When comparing parameter sets, push the stick fully every time so the speed is the same. Reaching 0.4 requires changing padd's `--max-linear`; leaving it for now.

---

## 6. Sole friction and soles

### 6.1 Simulation

When kissqy's model was trained, each simulation environment's sole friction coefficient was randomly drawn between 0.7 and 1.3 (training config `foot_friction`; the foot's contact priority is set higher than the floor's, so the foot-side friction is what takes effect), so it has never seen a more slippery floor. In simulation, same model, other conditions unchanged (scale 1.0, no filtering), changing only friction (both feet and the floor together):

| Friction coefficient | Foot clearance left / right | Body roll sway | Of which >4 Hz (jitter) | Step frequency | Stance knee left / right |
|---|---|---|---|---|---|
| Unchanged (model's original value) | 12.7 / 11.9 mm | 36.5°/s | 8% | 3.14 Hz | +3.5° / +6.5° |
| 0.5 | 12.6 / 12.2 mm | 37.6°/s | 10% | 3.05 Hz | +3.0° / +6.4° |
| 0.3 | 7.6 / 7.1 mm | 43.7°/s | **99%** | **4.48 Hz** | −0.1° / +0.6° |
| 0.2 | Can't walk (computed step frequency only 0.5 Hz, body pitched forward to 39°) | | | | |
| 0.3, speed raised to 0.4 | 9.0 / 9.1 mm | 41.4°/s | 52% | 3.97 Hz | +3.6° / +4.8° |

- 0.5 has almost no effect; dropping to 0.3 turns it into 4.5 Hz shuffling, almost entirely high-frequency jitter, with the feet lifting only 7 mm;
- On the real robot only the 10-13 afternoon P5 / D20 set jittered a lot (51%), so it resembles this in terms of "jitter"; but that set's step frequency was 2.89 Hz, not 4.5 Hz shuffling like simulation. And **after D was set to 0, the real robot stopped jittering on the same tabletop** (the user confirmed the D20 and D0 sets were walked on the same tabletop, so "setting D to 0 drops jitter from 51% to 4–8%" holds). If the tabletop really were as slippery as 0.3, then per simulation it should jitter at D0 too. So simulation **can't explain** the real robot's behavior at D0, and "soles too slippery" is just a suspect that hasn't been ruled out;
- The user feels the duck walks better on a mouse pad than on the tabletop; that's an impression, with no data.

### 6.2 Our soles and materials to switch to

- Confirmed with our partner on 10-14: our soles are **TPU 95A**. The 10-12 night item "need TPU soles" should be amended: TPU comes in soft and hard grades, and 95A is on the hard side;
- kissqy (in the group chat): the 90A he bought went hard and started slipping after two days, so he switched to 85A. Someone in the group also said "you might as well just buy silicone";
- When the user said in the group that our shuffling feels like a friction issue, kissqy replied: "I haven't solved that one yet, but you can work around it with the HOME gain, because adding filtering makes it soft";
- The options we discussed with our partner: **85A TPU**, or a **PLA foot plate + silicone / rubber anti-slip pads**. In our partner's video they tried a corrugated rubber anti-slip sticker, soft and flexible, looking about 1–2 mm thick;
- Our suggestions (from experience, not measured):
  - Thin and flat: 1–2 mm, both feet the same thickness, stuck down flat and fully covering, with no lifted edges, and the foot size about the same as in the simulation model;
  - Bevel or round the front end (toe) of the anti-slip pad and don't let it extend past the foot plate edge: currently the foot only lifts 3–6 mm when stepping, and a hard edge at the toe is the most likely thing to catch the ground;
  - Don't use thick sponge or EVA (too soft, it sinks in, changing body height and sway); don't use gritty anti-slip tape (too grippy, it will scratch the floor).

### 6.3 How to measure friction (not yet measured)

- **Inclined plane method**: friction coefficient = tan(angle at which sliding starts). 35° ≈ 0.70 (the training minimum), 30° ≈ 0.58, 25° ≈ 0.47, 20° ≈ 0.36, 15° ≈ 0.27;
- **Don't test with the whole duck standing on the incline**: high center of mass and short feet mean it tips over before sliding (a rough calculation during review: facing downhill it tips at about 11–12°, sideways at about 25°; not measured). Make a low sample block: a 3×3 cm square of the same material, glued under a small box, with 100–300 g on top;
- Use a board with the same surface the duck normally walks on, raise it slowly, stop as soon as the sample starts to slide, read the angle with a phone level app, measure 3 times and take the median;
- The user felt this was hard to measure, so it hasn't been done yet. Walking one set with the same parameters on the same tabletop before and after changing soles, and comparing jitter and clearance, will also show it.

---

## 7. Standing at HOME the two feet aren't coplanar laterally: both hip roll joints splay outward, differently each time

10-13 night [§6](HD1910-20261013-夜-掉电-舵机D与蹭地.md#6-imu-横滚零点往回补-114) left an open question: according to the servo readings, the two soles aren't in the same plane laterally. Today we broke it down joint by joint with the new script [`home_roll.py`](../tools/gait-analysis/home_roll.py):

