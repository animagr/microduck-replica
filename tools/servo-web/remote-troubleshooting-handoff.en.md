# Remote troubleshooting handoff: servo health check, ID 21, folded calibration

**English** · [简体中文](远程排查交接.md)

This is for Claude Code on another computer to read, and a person can follow it too. Start Claude Code in the project folder and say this as the first message:

> 先读 tools/servo-web/远程排查交接.md，按里面的流程带我做。 (First read tools/servo-web/远程排查交接.md and walk me through the procedure in it.)

## Your (the AI's) role and rules

**Scenario**: this computer is at a colleague's place, and the duck (15 Feetech HD-1910 servos) is connected to it. The person sitting at the computer is the project owner, connected in via remote desktop; the person working hands-on next to the duck is the colleague, who may not be able to see the screen.

**You lead the procedure, one step at a time.** For each step, state three things clearly:

1. What to ask the colleague to do, in words the owner can relay directly
2. What commands you run yourself
3. What counts as normal and what doesn't

Wait for the owner's reply before moving on.

**Rules**:

1. Use Chinese throughout, including the summary.
2. Sections 1, 2.1 and 2.2 are read-only. **Before writing EEPROM, enabling torque or making a servo move**, explain clearly what will happen and how to undo it, and wait until the owner explicitly says 「可以」 (OK).
3. Do not use FD's 「中位校准」 (center calibration): it simply takes the current position as 2048, so clicking it in any pose other than straightened sets the zero point wrong.
4. Do not change code, commit or push. If you find a code problem, record it in the log, and the owner will take it back and deal with it.
5. Append what was done and what was read at each step to `tools/servo-web/logs/远程排查-日期.md` (remote troubleshooting, date). On an error, state which step it got stuck at and paste the raw error message.
6. Only one program can use the serial port at a time. Before running `servo_report.py`, close the debug console (`server.py`) and FD.

## 0. Preparation

**The AI does this itself:**

- `git pull`, and confirm two things:
  - `VERSION` in `tools/servo-web/server.py` is 0.15 or later. From 0.15.0 on, before enabling torque the target is first aligned to the current position; in older versions, if you posed the servos with torque off and then enabled torque, the servos would lunge.
  - `tools/servo-web/servo_report.py` exists.
- `pip install -r tools/servo-web/requirements.txt`
- List serial ports: `python -c "import serial.tools.list_ports as l; [print(p.device, p.description) for p in l.comports()]"`

**Ask the colleague to:**

- **Plug the URT-2 into USB first, then power the servos.** In the reverse order the bus level gets stuck at 2.1 V and not a single servo is found.
- Say how it is powered: battery or power supply, and what voltage. If the power supply has current limiting, limit it to 2 A.
- Close FD.

## 1. Full-robot health check (read-only, all 15 connected)

```bash
cd tools/servo-web
python servo_report.py --port COMx
```

Explain the terminal output and the red items in `logs/体检-*.md` (health check) to the owner. Focus on:

- How many are online, and whether ID 21 is there
- Unload conditions register 19: whether overheat (4), overcurrent (8) and overvoltage (1) are enabled. From the factory usually only 4 is set
- Whether any bit of status register 65 is set
- Any with an especially large offset (more than 200 steps)

For ones that aren't found: check the wiring and power first; if you suspect a wrong ID, add `--scan-all`.

## 2. ID 21 (left hip roll)

**Background**: something went wrong with ID 21 while the colleague was debugging with FD; after power-off the servo horn cannot be turned, and it is suspected to be burned out. Overcurrent protection is off by default from the factory, and only overheat (80 °C) is enabled. When stalled it keeps drawing a large current, and it may fail before the overheat protection gets a chance to act.

### 2.1 Compare the feel first (unpowered)

Ask the colleague to power off and turn the horns of ID 21 and ID 20 with the same force. The HD-1910 has a 1:320 gear ratio, so even a good servo is basically impossible to turn when unpowered.

- ID 20 won't turn either: the feel tells you nothing; continue testing
- ID 20 turns but ID 21 doesn't budge at all: most likely the gears are stripped and jammed, or the joint is binding

### 2.2 Connect it alone and read

Ask the colleague to remove ID 21 from the leg (or at least unplug the other servos' cables), so it is the only one on the bus, then power on.

```bash
python servo_report.py --port COMx --ids 21
```

- **PING fails**: run `--scan-all` again; the ID may have changed. If it still fails, the driver is most likely burned out; stop here for this servo and record it.
- **It responds**: look at which bit of status register 65 is set, and at 19, temperature, current and voltage.

### 2.3 Move it a little (requires the owner's consent)

Only do this if 2.2 could read it successfully.

```bash
python server.py --port COMx --ids 21
```

The owner opens http://127.0.0.1:8080 in the browser:

1. In 「单颗操作 → 写寄存器」 (single servo → write register), select 48 (torque limit), value 300 (= 30%), and **do not tick 「解锁写」 (unlocked write)**. 48 is in SRAM and reverts on power-off.
2. Tick torque. 0.15.0 first aligns the target to the current position, so it will not move.
3. Drag the slider about 50 to one side (about 4°) and watch the yellow line and the current.

How to judge:

| Symptom | Conclusion |
|---|---|
| It follows and turns | The servo itself is fine; the problem is in the joint mechanics (binding from assembly, hitting a limit) |
| Current flows but it doesn't turn | Gears jammed |
| No current and it doesn't turn | Driver or motor is broken |

When done, turn torque off and close the debug console. If ID 21 needs a replacement, see the end of Section 4.

## 3. Protection settings (the owner decides)

For servos where the health check shows register 19 missing overcurrent or overvoltage, they should be enabled per step 5 of the 《调试记录》 (debug log):

- Value = original value + 8 + 1 (add whichever is missing). For a factory value of 4, write 13.
- Whether to also enable overload (32) (factory 4 → 45): ask the owner.

How: in the debug console, 「单颗操作」 (single servo) → select the servo → 「写寄存器」 (write register), select 19, enter the value, **tick 「解锁写」 (unlocked write)** (EEPROM), and click write. The page reads it back to verify. Write each servo one by one. Alternatively, tick overcurrent and overvoltage protection on FD's programming page and save.

After writing, close the debug console and rerun the full-robot health check to confirm there are no red items left.

## 4. Folded calibration (whether to do it, and whether today, is the owner's call)

**Prerequisites**: all 15 online, no red items in the health check, debug console 0.15 or later. For details, see one-click calibration in the [README](README.md) and the section 「缩着能不能当标定基准」 (can the tucked pose serve as the calibration reference) in the 《调试记录》 (debug log).

1. Turn torque off on all servos and lay the duck face down on a flat table. In the 3D overlay, select 「校准用折叠」 (folded for calibration) and pose it to match.
2. Pose it in this order. Where the knee makes contact depends on the hip angle, so set the hips first:
   1. Hip yaw and roll straight: legs not splayed or turned outward
   2. Hip pitch: use a square to set the thigh perpendicular to the torso
   3. Ankle 0°: foot plate at a right angle to the shank
   4. Fold the knee inward, stopping just as the ankle touches the servo on the thigh; don't push hard against it
   5. Recheck the hips with the square
   6. Neck vertical, head level and facing straight ahead, not tilted, mouth closed
3. Select the reference 「官方折叠（头颈摆正）」 (official fold, head and neck straight), select all 15, and click 「一键校准」 (one-click calibration).
   - In the confirmation dialog, a few degrees of difference per servo is normal.
   - If any differ by 30° or more, stop first and determine the cause: the horn was mounted half a turn off (calibrate as usual), or the ± sign is set wrong (check first: with torque off, move it by hand and see whether the 3D model turns the same way).
4. After calibration, the readings should be 22/23 = 1025, 12/13 = 3071, and 2048 for the rest.
5. Unfold the legs by hand, support the duck, and enable torque (it won't jump). For the official pose, click 「零位」 (zero position) with a 3-second transition, and watch while holding it:
   - Legs in a straight line, foot plates perpendicular to the shanks, left-right symmetric, head level.
   - For ones off by a degree or two: with torque on, straighten them with the slider, click 「校准这一颗」 (calibrate this one), and select the reference 「零位 2048」 (zero position 2048). The most likely ones to need adjustment are the ankles and hip roll, which were posed by eye when folded.
6. Click 「站」 (stand) and see whether it stands steadily and is left-right symmetric.
7. Power off and on again; if the readings stay the same in the same pose, the offsets were written to EEPROM.

**If ID 21 is replaced with a new servo**, complete these in order before calibration:

1. Connect only the new servo to the bus, and in the debug console use 「改 ID」 (change ID) to change it to 21
2. Move it to 2048
3. Mount the horn in the direction of the joint straightened; if the teeth don't line up, take the nearest position
4. Enable overcurrent and overvoltage protection (Section 3)
5. After mounting it back on the leg, check ±: with torque off, move it by hand and watch the direction in 3D

## 5. Wrap-up: what to bring back

Tell the owner to copy these back:

- `tools/servo-web/logs/体检-*.md` (health check) and the `.json` with the same name
- `tools/servo-web/logs/远程排查-*.md` (remote troubleshooting): the process you recorded
- `tools/servo-web/logs/servo-web-*.log`: the debug console log; every calibration and register-write step is in it
- New files in `tools/servo-web/calib/`: calibration backups, needed for undoing

Finally, summarize in Chinese: the conclusion on ID 21, which servos had their protection changed, whether calibration was done, and what is still left undone.

## Appendix: background quick reference

- **IDs**: 20–24 left leg (hip yaw / roll / pitch, knee, ankle), 30–34 neck pitch, head pitch / yaw / roll, mouth, 10–14 right leg. 1 Mbps, single-wire half-duplex, URT-2.
- **Directions**: all 15 are −1, verified on the real robot on 2026-09-20, stored in `directions.json`.
- **Zero point**: official 2048 = legs straight, standing (all MJCF joints at 0). The official code and policy add no compensation.
- **Registers**:

  | Address | Content |
  |---|---|
  | 19 | Unload conditions: 1 voltage, 2 magnetic encoder, 4 overheat, 8 overcurrent, 32 overload |
  | 65 | Status bits, same bit layout as 19 |
  | 28–29 | Protection current, ×6.5 mA |
  | 38 / 35 / 36 | Overcurrent protection time / protection time / overload torque (%) |
  | 13 | Temperature limit |
  | 9–12 | Min / max angle limits |
  | 31 | Position offset, BIT15 = negative |
  | 48 | Torque limit, 1000 = 100%, SRAM |
  | 63 / 69 | Current temperature / current current (×6.5 mA) |

- The HD-1910 (firmware 3.46) does not accept the "write 128 to the torque switch" style of center calibration; the debug console uses 0x0B.
