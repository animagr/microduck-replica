# Changelog (CHANGELOG)

**English** · [简体中文](CHANGELOG.md)

This file records all notable changes to the HD1910M servo test tool.

## [0.2.0] - 2026-10-03

Author: 漂移菌

The main theme of this release: **filling in the "zero calibration" and "range-of-motion limit" capabilities to match Feetech's FD debugging software**,
with full validation on the microduck robot (15 HD-1910 servos, firmware 3.46).

### New features

#### 1. Zero calibration `zero` (0x0B position calibration instruction) - the core addition

Equivalent to the "set zero / center calibration" button in Feetech's FD debugging software: it calibrates the servo's **current mechanical position** to a given reading
(default center 2048), and the servo automatically computes and updates the position offset register at address 31.

> Why the old method does not work: HD-1910 (HLS-series firmware ≥3.43) **does not support** center calibration by "writing 128 to the torque switch"
> (the write returns "success" but the offset register does not change). 0x0B is the only correct calibration instruction for this model.

Usage (one servo at a time during assembly):

```bash
feetech-HD1910M-tester torque off      # 1. Release the shaft
# 2. Move the joint to its mechanical zero by hand and hold it (do not wait in between; gravity will pull it off)
feetech-HD1910M-tester zero            # 3. Calibrate: current position → 2048, saved automatically to non-volatile memory
feetech-HD1910M-tester torque on       # 4. Restore torque
feetech-HD1910M-tester zero --to 1024  # You can also calibrate to any reading (0~4095)
```

Internal flow of the command: read the pre-calibration position → unlock EPROM → send 0x0B → lock again → delay →
**read back both "present position + position offset" for double confirmation** (an error is reported if the deviation is >4 units).
Because Feetech may return "success" even for unsupported operations, the readback is the only source of truth.

#### 2. Reboot command `reboot` (0x08)

Equivalent to a power cycle: SRAM is reloaded from EPROM. Used to verify **without physically cutting power** that an EPROM write was actually persisted
(robotd's servo replacement flow uses this same instruction).

```bash
feetech-HD1910M-tester reboot          # Wait about 1 second after reboot before communicating
```

A trick for verifying EPROM persistence: first write an SRAM marker value (e.g. `torque-limit 300`) → `reboot` →
read it back and find it restored to the EPROM/power-on default (1000), which proves the reboot really happened; at that point, whatever the EPROM items read back is what is stored.

#### 3. New instructions in the protocol layer

`Instruction::Reboot = 0x08`, `Instruction::ResetTurns = 0x0A` (multi-turn count reset),
`Instruction::Calibrate = 0x0B`, with packet-building unit tests.

### Enhancements

#### `limits` range-of-motion limits (min/max angle at addresses 9/11)

- Added `--deg`: enter angles directly, e.g. `limits 90 270 --deg --save` (0~360° maps to 0~4095)
- Added cross-validation: `min >= max` is rejected outright; `0 0` for multi-turn mode is special-cased and allowed
  (previously it was wrongly rejected by max-angle's nominal lower bound of 1)
- `--save` now **writes both registers within a single unlock/lock** (halving EPROM round trips),
  and guarantees re-locking if any step fails
- **Reads back to confirm** after writing and displays the values as angles

```bash
feetech-HD1910M-tester limits 1024 3072 --save   # Raw values: center ±90°
feetech-HD1910M-tester limits 90 270 --deg       # Angle values: RAM only, for debugging
```

### Fixes

- **`set --defer` skipped range validation before the asynchronous write**: out-of-range values were encoded and sent as is. Now all write paths
  (`write_reg` / `sync_write` / `set --defer`) go through `Register::check_value()`.

### Internal improvements

- `Register::check_value()`: range validation consolidated from three duplicated code paths into one
- `ServoError::Malformed` now carries a `String`, so it can report dynamic error messages
- Simplified a redundant branch in the `pid` command
- New unit tests: 0x0B packet building, check_value boundaries (all 8 tests pass)

### Hardware validation record (microduck, 15 HD-1910 servos, firmware 3.46)

- **0x0B calibration hardware test**: position 2958 (+80°) → exactly 2048 after calibration, offset register automatically written to 910
  (= 2958−2048; the hardware test confirms the offset semantics are "feedback value = raw value − offset"), persisted across power loss
- **0x08 reboot works on real hardware** (the "pending bench verification" item in the project docs can be crossed off)
- **Full acceptance check of all 15 servos**: ID table (10-14/20-24/30-34), firmware 3.46, endianness 0, baud rate 1M,
  response level 1, mode 4, voltage window 4.0~10.0V, unload condition 13 (voltage + overheat + overcurrent) all meet spec;
  each joint's reading deviates ≤4 units from the standing pose target

---

## [0.1.0] - Initial release

- Complete FT-SCS protocol implementation: PING / READ / WRITE / REG WRITE / ACTION / SYNC WRITE / factory reset
- `dump` / `get` / `set` covering all registers in the official HLS_2 memory table (supports key names / decimal / hexadecimal addresses)
- `scan` bus scan, `monitor` real-time monitoring (position / speed / load / voltage / temperature / current)
- `goto` / `angle` / `swing` motion control, `torque` / `torque-limit` / `goal-current` force control
- Three-loop PID tuning (`pid`), protection parameters (`protect`), ID / baud rate settings (`set-id` / `set-baud`)
- EPROM lock mechanism (`lock` / `--save`): unlock → write → lock, protecting EPROM lifetime
