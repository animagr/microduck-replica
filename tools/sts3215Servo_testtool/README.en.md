# sts3215Servo_testtool — Rust test tool for STS3215 servos

**English** · [简体中文](README.md)

A learning/test project that uses Rust to control Feetech (FEETECH) STS3215 bus servos through a USB-to-TTL adapter board.
The protocol is a minimal self-written implementation of the STS/SCS serial protocol, and the code lives in two files:

- `src/sts.rs` — protocol library: frame packing/checksum, ping, register read/write, status parsing (`ServoStatus`)
- `src/main.rs` — command-line tool: scan, read info, motion, single test, batch test

The tool's terminal output is in Chinese; the examples below show it verbatim, with an English gloss after each one.

## Hardware wiring

```
USB adapter board (e.g. Feetech URT-1 / Waveshare Bus Servo Adapter) --TTL--> STS3215 servo
The servo needs its own power supply (7.4V for the 7.4V version, 12V for the 12V version); do not draw power from USB!
```

Default serial port `/dev/ttyUSB0`, default baud rate 1,000,000 (the STS3215 factory setting).

## Common commands

```bash
source ~/.cargo/env          # load the cargo environment on first use
cargo build --release        # build
cargo run -- scan                       # scan for servos on the bus (with a progress bar)
cargo run -- info 1                     # read position/voltage/temperature/current/load of servo ID=1
cargo run -- read 1 42 2                # read any register: ID=1, 2 bytes starting at address 42 (hex)
cargo run -- move 1 2048                # move ID=1 to the center position 2048
cargo run -- move 1 3072 --speed 800    # move at a given speed
cargo run -- test 1                     # full test of ID=1: position sweep + current/load sampling
cargo run -- test-all                   # scan and batch-test all servos, print a summary table
cargo run -- raw 1                      # low-level diagnostics: print the raw bytes sent/received
cargo run -- set-id 1 2                 # change ID=1 to ID=2 (only this one servo may be on the bus!)
cargo run -- --port /dev/ttyUSB1 scan   # specify the serial port
cargo run -- --baud 115200 scan         # specify the baud rate
```

## Command examples and actual results

All output below was measured on a Raspberry Pi 5 + Feetech official adapter board (CH340) + STS3215 (7.4V version, ID=1).

### scan — scan the bus

```bash
$ cargo run -- scan
扫描中 [##############################] 254/254  已发现 1 个
  ID   1  在线  型号=777  电压=7.4V (范围 4.0~8.0V)  温度保护=70°C
共发现 1 个舵机。
```

Gloss: 扫描中 = scanning, 已发现 1 个 = 1 found, 在线 = online, 型号 = model, 电压 = voltage, 范围 = range, 温度保护 = temperature protection, 共发现 1 个舵机 = 1 servo found in total.

When the voltage is outside the "范围" (range), for example when 9V is connected by mistake, an overvoltage/undervoltage alarm has been triggered and the servo LED will blink.

### info — read live status

```bash
$ cargo run -- info 1
舵机 ID 1:
  位置     : 2049 / 4095   (180.1°)
  速度     :    0 步/秒
  负载     :  0.0 %
  电压     :  7.4 V
  温度     :   30 °C
  电流     :    0 mA
  运动中   : 否
```

Gloss: 舵机 = servo, 位置 = position, 速度 = speed (步/秒 = steps/s), 负载 = load, 电压 = voltage, 温度 = temperature, 电流 = current, 运动中 = moving, 否 = no.

When there is an alarm, an extra line `⚠ 报警 : 状态码 0x01` (alarm: status code 0x01) appears (bit0 = voltage fault). Position conversion: 4096 steps = 360°.

### move — move to a given position

```bash
$ cargo run -- move 1 2048 --speed 1000
舵机 1 -> 目标 2048，等待到位...
到位: 当前位置 2049 (180.1°)
```

Gloss: servo 1 -> target 2048, waiting to reach position... / In position: current position 2049 (180.1°).

- `pos`: target position 0–4095 (2048 is the center)
- `--speed`: steps/s, higher is faster; `--time ms`: desired duration, 0 means unlimited
- Measured positioning accuracy: error ≤1 step (about 0.09°)

### test — full test of a single servo

```bash
$ cargo run -- test 1
== 测试舵机 ID 1 ==
  型号=777  电压=7.4V  温度=30°C  位置=2049
  目标 2048 -> 实际 2049  偏差   1  OK
  目标 1024 -> 实际 1025  偏差   1  OK
  目标 3072 -> 实际 3072  偏差   0  OK
  目标 2048 -> 实际 2049  偏差   1  OK
-- 报告: 舵机 1 --
  型号=777  电压=7.4V  温度=30°C
  峰值电流=84mA  峰值负载=38.8%  最大位置偏差=1
  结果: ✅ PASS
```

Gloss: 测试舵机 = testing servo, 目标 = target, 实际 = actual, 偏差 = error, 报告 = report, 峰值电流 = peak current, 峰值负载 = peak load, 最大位置偏差 = max position error, 结果 = result.

### test-all — batch test (multiple servos)

Illustration of the output with several servos connected (each servo first prints its own full report, followed by a summary at the end):

```bash
$ cargo run -- test-all
扫描中 [##############################] 254/254  已发现 2 个
发现 2 个舵机: [1, 2]
... (each servo prints its own test report) ...
==== 批量测试汇总 ====
ID   型号     电压V    温度°C  峰值电流mA   峰值负载%    位置偏差   结果
1    777      7.4      30      84          38.8        1        PASS
2    777      7.4      29      79          35.2        1        PASS
```

Gloss: 发现 2 个舵机 = 2 servos found, 批量测试汇总 = batch test summary; columns: ID, model, voltage V, temperature °C, peak current mA, peak load %, position error, result.

> Note: the ID=2 row above is illustrative data; when you test, go by your servos' actual readings.

### read — read any register (for learning the memory table)

```bash
$ cargo run -- read 1 14 2
舵机 1 地址 14 起的 2 字节: 50 28      # max voltage 0x50=80→8.0V, min 0x28=40→4.0V
$ cargo run -- read 1 3 2
舵机 1 地址 3 起的 2 字节: 09 03       # model = 0x0309 = 777 (little-endian)
```

Gloss: servo 1, 2 bytes starting at address 14 / address 3.

### raw — low-level diagnostics (for troubleshooting communication)

```bash
$ cargo run -- raw 1
PING:
  发送: FF FF 01 02 01 FB
  收到: FF FF 01 02 01 FB               # normal reply (error=01 means a voltage alarm)
READ 状态区(地址56,15字节):
  发送: FF FF 01 04 02 38 0F B1
  收到: FF FF 01 11 01 EB 0F 00 00 ...  # 15 bytes of raw status data
```

Gloss: 发送 = sent, 收到 = received, 状态区(地址56,15字节) = status area (address 56, 15 bytes).

An empty "收到" (received) = the servo did not reply (check power/wiring/baud rate); identical to what was sent with no second packet = the adapter board is echoing.

### set-id — change a servo's ID

```bash
$ cargo run -- set-id 1 2    # ⚠ only this one servo may be on the bus
ID 1 在线，准备修改为 2 ...
✅ 修改成功：ID 1 -> 2（断电重启后依然有效）
```

Gloss: ID 1 online, about to change it to 2... / Changed successfully: ID 1 -> 2 (still in effect after a power cycle).

## Multiple servos: change IDs before putting them on the bus

New servos all ship with ID 1; several servos with the same ID on the same bus will **reply at the same time and collide**
(the scan may show only 1, or none at all). The correct procedure:

1. Connect **only one** servo to the bus
2. `cargo run -- set-id 1 2` to change it to a new ID (EEPROM operation: automatically unlock → write → lock; survives power loss)
3. Power off, connect the next one, and repeat, changing it to 3, 4, ...
4. Once all are connected, `cargo run -- scan` should show every servo, each with a different ID

> ⚠ Note: if several servos with the same ID are on the bus when `set-id` runs, they will **all** be changed to the same new ID.

## Hardware test notes

- Factory defaults: ID=1, baud rate 1M, model reading 777
- The power supply must match the version: the 7.4V version (C001) has a voltage upper limit of about 8.0V, and connecting 9V triggers an **overvoltage alarm** (LED blinks, status code 0x01); the 12V version (C018) uses 12V
- Measured position accuracy: target/actual error of only 1 step (about 0.09°)

## What is tested (test / test-all)

1. Ping reply + read the model
2. Baseline readings: voltage, temperature, position
3. Position sweep: center 2048 → 1024 → 3072 → 2048, sampling every 20 ms during motion
4. Record peak current (mA), peak load (%) and max position error
5. Judge PASS/FAIL (voltage faults, alarm bits, excessive error and excessive temperature rise are all flagged)

## Writing your own test script

Just follow `test_one()` in `main.rs`. Core API:

```rust
let mut bus = StsBus::open("/dev/ttyUSB0", 1_000_000)?;
bus.ping(1)?;                      // is it online
bus.move_to(1, 2048, 1000, 0)?;    // move: id, position, speed, time
let s = bus.read_status(1)?;       // read back all status at once
println!("{}V {}mA {}°C", s.voltage, s.current_ma, s.temperature);
bus.set_torque(1, false)?;         // release torque (can be turned by hand)
```

Register addresses are in the `reg` module in `sts.rs`; for the full definitions, see Feetech's *STS3215 Serial Protocol Manual*.

## FAQ

- **Permission denied**: run `sudo usermod -aG dialout $USER`, then log in again
- **No servos found in the scan**: check power (is the servo LED on?), the baud rate (try `--baud 115200`), and whether TX/RX are swapped
- **Checksum errors**: there is interference on the bus or the wires are too long; shorten the cables and check grounding
