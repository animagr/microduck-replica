# servo-web · Feetech servo web debug console

**English** · [简体中文](README.md)

> The 3D model on the page is for debugging display only and is still based on the upstream simulation geometry; it **must not be exported and used as the latest Feetech printed parts**. Get structural parts and assembly models from [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).

Connect the serial port, drag sliders in the browser to move the servos, and the 3D duck turns along with them. It is for assembly, zeroing and bench acceptance checks, and it is also the tool for items 0–8 of the bench checklist in the [Feetech adaptation architecture](../../software/feetech-adaptation-architecture.en.md).

The page UI is in Chinese; button and panel names are quoted below as they appear on screen, with an English gloss.

![UI](../../assets/servo-web.png)

- 15 sliders grouped as left leg / head-neck / right leg; the yellow line is the servo's actual position, and each servo has a torque switch. **Before enabling torque, the target is first aligned to the current position**: if you moved a joint by hand with torque off, sent a pose, or calibrated, the goal register still holds the old value, and without alignment the servo would lunge as soon as torque is enabled; a servo whose position cannot be read is not enabled
- Live readback: position, voltage, temperature, load, current, status bits (overcurrent / overheat / overload are marked red)
- The 3D model follows the actual positions (it uses the MuJoCo model from [microduck_rl](https://github.com/apirrone/microduck_rl), Apache-2.0); the ± next to each joint is the joint direction, stored in `directions.json` and shared by all pages; 3D, stance, sequences and the expressive moves all convert through it without moving the servos; 「复制 robotd 方向表」 (copy robotd direction table) generates the line that `robotd.toml` needs. Checked one by one on the real robot: all 15 are reversed (the direction in which the HD-1910 reading increases is opposite to the XL330, and the mounting was copied from the XL330, so the whole thing is reversed once)
- Poses: save the current actual positions as a pose and send it back with one click; JSON with `steps` is a sequence (the built-in 「站起来」 (stand up) has three steps). All poses / stances / zero position interpolate linearly from the current position over the 「过渡时间」 (transition time), and you can click 「停」 (stop) at any time
- One-click calibration (Feetech only; the XL330 does not have this feature): put the duck in the shape of the "reference", and with one click change the selected servos' reading of "the current position" to the reference value. There are three references:
  - **零位 2048 (zero position 2048)**: with torque on, use the sliders to get the legs straight, foot plates vertical, head level and mouth closed, then support it and click. Saved poses are automatically converted to the new zero
  - **官方折叠（头颈摆正） (official fold, head and neck straight)** (recommended): the duck is folded and lying stable, no need to hold it in the air. Fold the knee until the ankle just touches the thigh servo (parts butt against each other, so it's the same every time), set hip pitch perpendicular to the torso with a square, set hip yaw/roll and ankle straight, neck vertical, head level, mouth closed. Target readings: legs computed from the official FOLD angles and ± (with all ± at −1, 22/23 = 1025, 12/13 = 3071), and 2048 for the rest; after calibration the zero is the official 2048, saved poses are converted automatically, and all 15 are calibrated together. The head and neck do not use the official FOLD 57°: that is not a contact point and cannot be set accurately by eye (see [`tools/fold_contact`](../fold_contact/)). The knee target is computed from the official 1.57 rad (90.0°); in the official geometry the ankle touches the thigh servo at 89.6°, so the zero is off by about 0.36° (4 steps). Posing it by hand with torque off is fine, and torque stays off after calibration. When this reference is selected, the 3D view automatically overlays 「校准用折叠」 (folded for calibration) for you to match
  - **A saved pose** (e.g. 「缩」 (tucked)): the duck tucks itself up and rests stably, positioned by mechanical contact, no need to hold it. The zero is still the official 2048, so the official code and policy need no offset; other poses use the same set of readings as the reference and are not shifted

  Clicking the button first pops up a confirmation dialog listing, servo by servo, "current → will be written as, difference in degrees" (computed by the server, the same data as the real calibration). **Differences of 30° or more ask for a second confirmation but are not blocked**: a horn mounted half a turn off gives a 180° difference, and calibration corrects exactly that; a ± direction set wrong also gives roughly 180° (for joints at ±90° when folded), and calibrating that in would be wrong, so it reminds you to check ± first (with torque off, move it a little by hand and see whether the 3D model turns the same way). After calibration, the log lists the large differences separately.

  It uses the 0x0B position calibration instruction (the HD-1910 does not accept writing 128 to the torque switch; see below). For each servo: unlock → read position → torque off → 0x0B → read back → change the target only if it matches → restore torque → lock; torque is off for only a few milliseconds, so the joint is not pushed down by gravity and does not jump; if it doesn't match, nothing moves and a failure is reported; on an error midway, it still locks. The original offsets are backed up in `calib/` and can be undone (only the poses shifted that time are shifted back). At the end it only releases speed and acceleration (41, 46), and no longer writes goal 42 along with them
- Single servo: pick a servo from the dropdown (with joint names, offline ones marked), export all registers 0–86 (JSON / Markdown table, used as a **register baseline record**), reboot 0x08, center calibration, change ID (old IDs list only online servos, new IDs list the 15 standard slots with occupied ones marked), write register (dropdown with register names, unlock automatically ticked for the EEPROM area, read back and verified after writing)
- All raw serial traffic goes into the log file (hex + register name + servo reply); this is what you rely on to track down those Feetech operations that "reply success but don't execute"
- Logs are split into 系统 / 总线 / 运动 / 校准 / 寄存器 / 姿态 / 方向 / IMU / 页面 (system / bus / motion / calibration / register / pose / direction / IMU / page); warnings and errors are colored and counted, and you can filter by category, show only warnings and errors, or copy with one click. Each entry is also written to `logs/servo-web-日期.log` (date), with a traceback for errors; calibration writes one line per servo: readings before and after, offsets before and after, and the reply at every step. If something goes wrong, send this file and it can be investigated
- `sync_read` timing test: reads all 15 at once 200 times and reports min / avg / p99 / max and the failure count
- Servo health check (command line, **read-only**): `python servo_report.py --port COM5` reads each servo's protection switches (unload conditions 19), status bits, temperature, voltage, current, offset and angle limits, flags red/yellow per step 5 of the 《调试记录》 (debug log), and saves them as `logs/体检-时间.md` (health check, time) and a `.json` with the same name (raw values 0–86). For a single servo use `--ids 21`; if you don't know the ID use `--scan-all`. The serial port must not be held by the debug console or FD at the same time
- Remote troubleshooting: [`远程排查交接.md`](remote-troubleshooting-handoff.en.md) (remote troubleshooting handoff) is a procedure written for Claude Code on another computer (health check → single-servo troubleshooting → enable protection → folded calibration); over there, say 「先读 tools/servo-web/远程排查交接.md，按里面的流程带我做」 (first read tools/servo-web/远程排查交接.md and walk me through the procedure in it)
- Self-test: `python selftest.py`, without servos connected. [`sim_bus.py`](sim_bus.py) is a protocol-level HD-1910 simulator (sends and receives Feetech packets byte by byte, simulating lock, torque, 0x0B, the HD-1910 not accepting 128, offsets and dropouts), letting the real `feetech.py` + `server.py` run through calibration, undo, ID change, register writes and export. If you change code that talks to the servos, run it first before going to the real robot
- The backend does not depend on the Feetech SDK; [`feetech.py`](feetech.py) sends packets directly according to the 2026 protocol manual ([`docs/飞特资料/`](../../docs/飞特资料/)), a little over a hundred lines

## Running it

```bash
pip install -r requirements.txt
python server.py --port COM5                 # Windows + URT-2; check the port number in Device Manager
python server.py --port /dev/ttyUSB0         # on the board, URT-2 plugged into the board's USB port
python server.py --port /dev/ttyS2           # on the board via UART2 on the 40-pin header (needs a half-duplex adapter first, see below)
python server.py --fake                      # no servos: simulation mode with virtual servos
```

**Simulation mode** (when no serial port is connected): the virtual servos follow trapezoidal profiles according to the real servos' speed and acceleration registers; poses, sliders, sequences, expressive moves and official poses all move in 3D at the same speed as the real robot; torque is on by default and there is no gravity. The 「模拟」 (simulation) panel at the top right lets you choose the IMU: 不接 (none) / 接虚拟小板 (connect a virtual board; ID 200 on the fake bus, the same path as `--imu-bus`) / 虚拟小板掉线 (virtual board drops out; see how the debug console takes 200 out of the queue, PINGs it on its own, and brings it back). Plug in USB, pick the serial port in the top bar and click 「连接」 (connect) to switch to the real servos; this panel then hides automatically and the virtual board is unplugged with it.

You can also rehearse one-click calibration and undo in simulation: it only changes the virtual servos, and backups go to the system temp directory, **without touching `calib/` and `poses/`** (if the virtual servos' offsets got mixed into `calib/`, clicking 「撤销」 (undo) after connecting the real servos would write them into the real servos). Saving poses and changing ± are explicit operations and write files as usual.

If the serial port cannot be opened, it does not crash: the page still opens (fake bus), a serial port dropdown appears in the top bar, and once USB is plugged in you pick one and click 「连接」 (connect) to take over, no restart needed.

Open `http://127.0.0.1:8080` in the browser; when running on the board use the board's IP, and phones can open it too. The IDs managed by default are `20-24,30-34,10-14`; use `--ids` for others. The 3D model files are in `model/` and are already generated; to regenerate them:

```bash
python build_model.py --src <microduck_rl>/src/mjlab_microduck/robot/microduck
```

### Board + HAT, debugging over WiFi

First confirm the board has a WiFi address and SSH login works, configured per the [board image guide](../radxa/image-user-guide.en.md). Put this folder and its dependencies on the board, confirm that programs such as `robotd` are not holding `/dev/ttyS2`, then run:

```bash
python server.py --port /dev/ttyS2 --ids 20-24,30-33,10-14 --host 0.0.0.0 --http-port 8080
```

Connect the computer/phone to the same LAN where the devices can reach each other and open `http://<board IP>:8080` in the browser. This example excludes the mouth; to include it, adjust to the actual ID. The web page can operate physical servos, so only use it on a trusted LAN. From 0.15.2 on, starting up / connecting the serial port only scans and reads phase, and no longer automatically releases the speed and acceleration limits; the motion, calibration and other buttons on the page still actually send control commands.

From 0.15.4 on, the target rate for real servo status readback and web push is **50 Hz** (previously 10 Hz); simulation mode is still 30 Hz. The 「刷新」 (refresh) figure in the top bar is the rate at which the web page actually receives status, affected by serial port time, timeouts, system scheduling and the network. Raising the readback rate does not change the timing of poses, enable state or motion commands, nor does it mean that a full 50 Hz control loop including IMU, policy inference and command writes has been verified.

The sliders only write the goal position and keep the servo's existing speed/acceleration settings; if that phase defines "speed 0 = stop" and the current speed is 0, dragging the slider may not move it. When you need motion, confirm protection, support and mechanical range first, then use the smooth transition features that set the speed explicitly.

When you need to compare against "computer USB-to-serial direct connection", first stop the debug program on the board, then shut down properly, cut power and swap the cables. After powering up again, run `python server.py --port COM<actual number> --ids 23` on the computer and compare using the same servo; do not let the HAT controller and the USB-to-serial adapter send commands to the same bus at the same time. For a read-only report you can also use `python servo_report.py --port COM<actual number> --ids 23`.

## Official poses: go to the pose / 3D overlay comparison

The 「官方姿势」 (official poses) panel holds the four keyframes from microduck_rl's `scene.xml`: **零位** (zero position; all 2048), **站** (stand; STAND), **坐** (sit; SIT), **折叠** (fold; FOLD).

- 「去」 (go): converts the official angles to readings using each servo's ± and the current zero, and moves there over the 「过渡时间」 (transition time). **When sending fold, the knee is only folded to 88°**: computed on the exact mesh, in the official geometry with hip at 90° and ankle at 0°, the ankle touches the servo on the thigh when the knee is folded to 89.6°, so the official 90° would make the servo push hard against the parts (see [`tools/fold_contact`](../fold_contact/))
- 「3D 叠加」 (3D overlay): draws an extra semi-transparent blue duck in the official pose in 3D, and below it lists per joint how many degrees "actual − official" differ (>2° yellow, >5° red). When the duck is placed in that pose, the difference is how far the zero is off

## Optional: IMU torso attitude (servo bus / ST-Link / DAPLink / J-Link)

The debug console can combine two kinds of readings on **the same model**: servo joint angles keep driving the existing joints, and the IMU quaternion drives the torso attitude. It reuses this service, `/ws`, the model files and the CDN, without starting a second web service. When no IMU parameters are given, this section is hidden and the existing serial features work as usual.

It applies to the verified **STM32G031F8P6 + LSM6DSV16X board of the same design**; J-Link mode requires Windows x64, Python 3.11+, the SEGGER J-Link USB driver installed yourself, and `JLink_x64.dll`. Bare-board firmware and flashing steps are in [`hardware/imu_to_dxl/firmware/`](../../hardware/imu_to_dxl/firmware/), and the schematic and wiring are in the [hardware folder](../../hardware/imu_to_dxl/). J3.1 to GND, J3.2 to SWCLK, J3.3 to SWDIO, **J3.6 to VTref**; J3.4/5 are the serial port and must not be connected as the power reference.

1. Copy `imu-jlink.example.json` to `imu-jlink.json` and fill in your own `dll` and `probe_serial`. The file is ignored by Git.
2. Make Keil, J-Link Commander and the like exit debugging to release the probe; the matching HEX should already be running on the board.
3. Run the following commands in `tools/servo-web/`; the browser still opens `http://127.0.0.1:8080`:

```bash
python server.py --port COM5 --imu-jlink imu-jlink.json  # servo serial port + real IMU
python server.py --fake --imu-jlink imu-jlink.json       # IMU bare board only, joints use demo values
python server.py --fake --imu-demo                       # both are demo, no hardware connected
```

Paths in the JSON are relative to that configuration file; the DLL can be a full path like `E:/SEGGER/JLink/JLink_x64.dll`, but you must change it to your actual install location. `firmware` can be omitted and defaults to the repo's `hardware/imu_to_dxl/firmware/Build/imu_to_dxl.hex`; `hz` is 1–20; `resume` defaults to `false`. Only set `resume: true` when you explicitly need to resume a halted CPU, and it must also pass the firmware check first. The serial number has no default, and no probe is selected automatically.

The display zero is set automatically when the first valid attitude is received, or you can lay the board flat and click "归零" (zero). The mounting orientation defaults to Y +90° (`DEFAULT_MOUNT`); adjust it to the actual mounting orientation and zero again. These operations only affect the web page and write nothing to the IMU, servos or Flash. After zeroing, the view shows relative attitude; "原始姿态" (raw attitude) is also only relative to the IMU's startup reference.

### Easiest: `--imu-bus`, read directly from the servo bus

The small board sits on the servo bus (Feetech protocol from firmware 0.2.0 on), so **no debugger is needed at all**: a single URT-2 cable reads the servos and the IMU together:

```bash
python server.py --port COM5 --imu-bus      # real bus: 15 servos + ID 200
python server.py --fake --imu-bus           # no hardware: a fake small board on the fake bus, to see how it looks
```

- It sends **the same** sync_read the controller sends every tick: address 56, length 15, **ID 200 first**, followed by the servos. Servo status is decoded as before, and the 200 block is decoded by the controller's criteria (an all-zero quaternion = fusion has no output yet; norm² > 1.02 rejected; 12 bytes unchanged for 25 consecutive frames = frozen; reserved bytes must be 0; status bits BIT1/BIT2 are faults reported by the board itself), the same rules as `tools/imu200`.
- The spec states: when the board doesn't reply, the servo data after it in the same sync_read is lost along with it. So if 200 **fails to reply for 5 consecutive frames it is taken out of the queue**, the servos are read on their own, and 200 is PINGed separately every 2 seconds and put back once it replies. Without the small board connected, the debug console still works, and the IMU category in the log states where it is stuck.
- `imu_to_dxl` boards compatible with the original DXL 2.0 protocol: the web page can switch protocols, or use `--imu-bus-protocol dxl2`; the default is still the Feetech protocol. DXL2 reads ID 200, address 124, length 12.
- It only polls while a web page is connected (in the same loop as servo status); it pauses during calibration. On the bench with only the small board connected and no servos found by the scan, it still reads 200.
- When the real bus is read at the 50 Hz target, the 120 Hz firmware usually refreshes about 2–3 times between reads; when the actual period stretches, BIT3 (「读得太慢」, "read too slowly") may still appear. Up to 0.15.3 it read at 10 Hz, with about 12 refreshes between reads. The debug console still does not treat BIT3 as an alarm on its own; the raw status bits are kept in the frame (`status_bits`).
- Boards with firmware 0.1.0 (Dynamixel 2.0) do not reply in the default Feetech mode: if you keep the original firmware, just switch to DXL2 compatibility mode; or flash 0.2.0 per [`firmware/`](../../hardware/imu_to_dxl/firmware/) and use the default Feetech mode. DXL2 mode splits the IMU and the Feetech servos into two serial transactions, while Feetech mode still uses the sync read above.

### No J-Link: `--imu-swd` (ST-Link / DAPLink, via pyOCD)

It reads the same way as above: first check the target voltage, then compare the on-board Flash byte by byte, then read the same RAM snapshot, without flashing or writing memory. The difference is that it goes through [pyOCD](https://pyocd.io/), so **both ST-Link and CMSIS-DAP (DAPLink) work**, with no configuration file. **For J-Link, use `--imu-jlink` above**: connecting a J-Link through pyOCD by default supplies 5 V from pin 19 and may silently upgrade the probe firmware, bypassing that path's safeguards, so `--imu-swd` refuses J-Link outright.

```bash
pip install pyocd
python server.py --fake --imu-swd                           # only one debugger plugged in: selected automatically
python server.py --fake --imu-swd 301612179216303030303032  # several plugged in: specify by UID (look it up with pyocd list)
python server.py --port COM5 --imu-swd                      # servo serial port + real IMU
```

- Wiring as above: J3.1 GND, J3.2 SWCLK, J3.3 SWDIO, J3.6 to the debugger's **VTref / TVCC** (voltage sensing only, no power supplied). The board powers itself from the bus connector; if the debugger has a 3.3 V output pin (pin 19 on some ST-LINK/V2), **don't connect it at the same time as bus power**.
- The ST-LINK/V2 20-pin header comes in different versions: on some, pins 4/6/8/10 are GND; on others they are UART, BOOT0, SWIM. **Use only pins 12/18/20 for GND**.
- It connects in `attach` mode: no reset, no halt, and no Go sent on disconnect; it does not load `pyocd.yaml` / user scripts from the current directory. It still writes debug registers (DHCSR.C_DEBUGEN etc.), and C_DEBUGEN stays set after disconnect, so it cannot be considered zero impact on the target. Hardware test (2026-09-22, ST-LINK/V2 V2J43S7, 100 kHz): over 3 consecutive connections, the chip's timer matched the wall clock, so it **does not make the board reboot**; refresh about 20 Hz, data age 6–11 ms.
- Before connecting to the chip it checks the target voltage: only ST-Link can measure it, and anything outside 3.0–3.5 V is refused (near 0 V it hints that VTref/TVCC is not connected or the board is unpowered); DAPLink cannot read the voltage, so the page shows 「—」 and does not block. Errors distinguish between "the debugger cannot be opened" (held by Keil/CubeProgrammer, ST-Link firmware too old) and "cannot connect to the chip" (wiring, power).
- To go back to Keil or CubeProgrammer, stop this service first to release the debugger.

Connections, faults, state changes and display calibration are recorded in the same `logs/servo-web-日期.log` (date), under the **IMU** category; data is not logged frame by frame. Stopping the service releases the debugger (J-Link / ST-Link / DAPLink); to go back to debugging in Keil, stop this service first; closing the browser tab alone does not release the probe. There is currently no web-side probe reconnect or reset operation; after dealing with a connection fault, restart the service.

### Firmware verification and scope of validation

- Only one `.hex` is committed; there is no need to download `.bin` or `.map`. The SWD / J-Link backends verify the Intel HEX records and the contiguous Flash image, which decodes to **10724 bytes** (firmware 0.2.0), SHA-256 `66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e`, RAM layout `sample=0x2000006C`, `tick=0x20000A34`. Only this image uses the reviewed RAM layout, and after connecting the actual Flash is also compared byte by byte; different firmware is refused for reading attitude or resuming the CPU.
- After modifying the firmware, first check the structures, addresses and sizes in the new MAP, then update the corresponding verified hash and layout. Do not simply disable the hash check. This tool does not flash.
- Previously, J-Link 9.78 with SWD at 100 kHz read about 20 Hz on the real board; establishing a connection through the SDK once caused the program on the board to restart, so it cannot be considered non-intrusive observation. The current integrated version has separately passed hardware-free self-tests, but **real servos and a real IMU running at the same time have not been verified yet**; the axes and long-term stability need to be checked on the robot.
- **The bundled firmware 0.2.0 already uses the Feetech protocol** (ID 200, 15-byte block at address 56), and the real protocol code passed `imu200.py check` on the simulated bus; but **the real bus has not been tested yet**, and a normal SWD view does not mean the real bus or the `FeetechIo` acceptance check passes. Run `imu200.py check --port` before putting it on the full robot.
- A six-axis IMU's heading drifts, and the web page does not measure translation or detect real foot contact. The center of mass and support area are still estimates from the model geometry and cannot be used to conclude that the robot can stand or walk stably; when the stream drops, the last attitude is kept and marked invalid.

### Hardware-free regression checks

```bash
pip install -r requirements-test.txt
python selftest.py
python -m pytest test_feetech_sync.py test_imu_bridge.py test_imu_server.py test_imu_swd.py test_imu_bus.py test_dxl2.py test_sim.py test_servo_report.py
node --test test_imu_attitude.cjs
```

Node.js is only used for the frontend math tests and is not needed for normal use of the debug console. Firmware host tests and historical real-board records are in [VALIDATION.md](../../hardware/imu_to_dxl/firmware/VALIDATION.en.md).

## Notes

- **Plug the URT-2 into USB first, then power the servos.** In the reverse order the bus level gets stuck at 2.1 V, the scan finds not a single servo, and only broadcasts get back a few 0s; see the [pitfalls log](../../PITFALLS.en.md).
- **Before using ttyS2 on the board, run `sudo systemctl stop robotd` first.** The official daemon opens this port every second to look for servos, and if both sides transmit at once the packets collide. Using the URT-2 via ttyUSB0 doesn't have this problem.
- **Wiring ttyS2 directly to the servos with jumper wires will not receive any replies.** Radxa's UART is full-duplex 3.3 V on two wires, while the Feetech bus is single-wire half-duplex; in between you need either a tri-state buffer (what the official HAT does) or the chip design taken from a URT-2. Once the adapter board is built, first use the timing test on the page to check for echo: echo shows up as everything being "无应答" (no reply).
- Center calibration and ID change write EEPROM, and the page pops up a confirmation. When changing an ID, have only that one servo on the bus.
- **The HD-1910 (firmware 3.46) does not accept writing 128 to the torque switch.** The memory table says it supports center calibration, but in a hardware test over 4 rounds with 15 servos: unlocked, torque off, wrote 128, the servo replied 「成功」 (success), and not a single offset changed. The table in section 4.9 of the protocol manual also says HLS ≥3.43 does not support it. Calibration always goes through 0x0B.
- "全部回 2048" (all back to 2048) executes immediately on servos with torque on; for servos mounted on the legs, turn torque off first or do them one at a time.
- The page loads three.js from jsdelivr, so the computer opening the page needs internet access; the backend itself does not.
- The mouth (ID 34) has no joint in the model; the slider moves the servo, but 3D doesn't show it.

## Versions

The version number is shown next to the page title. When the page and server versions differ, it is marked red with a hint to restart `server.py` first and then press Ctrl+F5; this usually means the browser is still using the old page. When changing code, bump `VERSION` in `server.py` and `PAGE_VERSION` in `index.html` together.

| Version | Date | What changed |
|---|---|---|
| 0.15.6 | 2026-10-23 | Fixed DXL 2.0 IMU normal polling continuously writing to the raw log; uses the bus's `trace_skip` setting, keeping logs of failed requests and manual diagnostics |
| 0.15.5 | 2026-10-17 | Added a compatibility mode for the original DXL 2.0 `imu_to_dxl` and a web protocol switch; the default Feetech protocol is unchanged |
| 0.15.4 | 2026-09-28 | Target rate for real servo status readback and web push raised from 10 Hz to 50 Hz; simulation mode stays at 30 Hz, motion and enable logic unchanged |
| 0.15.3 | 2026-09-28 | Sync read files replies by the actual ID in the reply packet, fixing the problem where one missing packet caused the following normal replies to be counted as failures too; real missed reads are still kept rather than hidden by adding retries; added protocol byte-stream regression tests |
| 0.15.2 | 2026-09-28 | Starting up / connecting the serial port only reads phase and no longer automatically writes the speed and acceleration registers; added board + HAT WiFi debugging and the USB-to-serial comparison method |
| 0.15.1 | 2026-09-22 | Servo health check `servo_report.py` (read-only, verified on the protocol simulator to send not a single write instruction); `远程排查交接.md` (remote troubleshooting handoff); in the calibration confirmation dialog, the ankle wording changed to 「脚板跟小腿成直角」 (foot plate at a right angle to the shank) (the old 「对齐」 (aligned) was easy to misread) |
| 0.15.0 | 2026-09-22 | Fixes from a review (done by a subagent): before enabling torque, the target is first aligned to the current position (after calibrating with torque off and unfolding by hand, enabling torque would snap back to the fold); calibration wrap-up no longer rewrites goal 42 with the read-back 67; calibration / undo in simulation doesn't touch `calib/`, `poses/`; the fake bus encodes offsets as sign-magnitude; connecting a real serial port unplugs the simulated virtual IMU, and connect / unplug is broadcast to all pages. The calibration confirmation dialog lists "current → will be written as, difference in degrees" per servo, asking for a second confirmation at 30° or more without blocking; 3D can overlay 「校准用折叠」 (folded for calibration); a reminder not to press 「折叠」 (fold) before the zero has been calibrated |
| 0.14.0 | 2026-09-22 | Simulation mode: virtual servos follow trapezoidal profiles according to the speed / acceleration registers (previously only a first-order follow when torque was on), torque on by default, status pushed at 30 Hz; the 「模拟」 (simulation) panel can connect / unplug the virtual IMU board at any time. 3D now redraws only on change (400k+ triangles were drawn at 60 fps constantly, so clicking a button took ages to bring up the confirmation dialog). One-click calibration gained the 「官方折叠」 (official fold) reference: targets computed as official FOLD angle × ±, after calibration the zero is the official 2048, saved poses are converted accordingly; legs in the official fold, head and neck straight, all 15 calibrated together |
| 0.13.0 | 2026-09-22 | 「官方姿势」 (official poses) panel: four buttons for zero position / stand / sit / fold (official keyframes converted by ±; the fold bends the knee 2° less so it doesn't push against parts); 3D overlays the official pose semi-transparently and lists the "actual − official" angle difference per joint, used to see how far the zero is off |
| 0.12.0 | 2026-09-22 | Optional `--imu-bus`: reads the IMU board directly from the servo bus with the same sync_read as the controller (address 56, length 15, 200 first), decoding the block by the controller's criteria (not ready, rejected, frozen, reserved bytes, board fault bits); 200 is taken out of the queue after 5 consecutive frames with no reply and PINGed separately every 2 seconds, and the servos are still read without the board connected; `--fake --imu-bus` has a fake board to see how it looks. Matching firmware 0.2.0 (Feetech protocol); the HEX hash and RAM addresses of the SWD/J-Link observer updated accordingly |
| 0.11.0 | 2026-09-22 | Optional `--imu-swd`: reads IMU attitude through pyOCD with ST-Link / DAPLink, no J-Link DLL or configuration file needed (J-Link still goes through `--imu-jlink`, and `--imu-swd` refuses it). The same safeguards as the J-Link path: check voltage before connecting to the chip, compare on-board Flash, read-only RAM, a halted CPU is not resumed automatically; connects in attach mode, and the hardware test showed it does not make the board reboot. Selected automatically when only one debugger is plugged in; with several, a UID must be given. ST-Link also shows the target voltage; pyOCD warnings are recorded in the IMU log as well. The web label shows the actual debugger name |
| 0.10.0 | 2026-09-21 | Optional `--imu-jlink`: combines servo joint angles and IMU torso attitude in the same WebSocket, log and 3D model; keeps mounting orientation/display zeroing, supports hardware-free `--imu-demo`, and the original UI is unchanged when IMU is not enabled. The matching firmware and hardware materials are kept together, and the repo keeps only the HEX |
| 0.9.1 | 2026-09-20 | Raw serial traffic goes into the log file: what each packet sent and what the servo replied, in hex + register name (`→ #32 位置校准 ff ff 20 02 0b f2` / `← #32 状态0x00 …`, i.e. position calibration / status). Feetech replies 「成功」 (success) even for unsupported operations, so only by looking at the raw bytes can you tell "really did it" from "pretended to do it". The 10 Hz status polling is not logged, otherwise the log would be nothing but that |
| 0.9.0 | 2026-09-20 | Calibration rewritten after a code review (found by a subagent, all in the "will yank the joint away" category): the criterion changed from "reading equals target" to "did the offset register change", because Feetech replies success even for unsupported operations; **gravity sag compensation**: during the few milliseconds with torque off the joint drops (measured 0.62 steps/ms on the neck, while a USB serial round trip takes 1–16 ms), so the sag is computed from "reading before calibration, target, offset change" and added back, reducing the zero error on a slow 16 ms bus from 99 steps to 0; read back to confirm after torque off (losing that packet would make 0x0B run with torque on, and as soon as the offset changes it pulls at full speed); the goal position is always written as the current reading, never the target value; on errors, finally still writes the goal, restores torque and locks; exclusive bus access during calibration with lowered acceleration and speed; the offset sign direction is probed once at startup (±1 step) instead of trial and error per servo; registers 31/42/46 now use sign-magnitude encoding (negative numbers previously written as two's complement were interpreted as -32763 and hit the limit); offset range narrowed to ±2047; on undo, poses saved after calibration are shifted back too; backups are written atomically, persisted to disk before shifting poses. The simulator gained gravity sag and bus latency, so this class of bug can now be tested |
| 0.8.1 | 2026-09-20 | The page starts even if the serial port can't be opened (USB not plugged in, port number changed, port in use no longer crash it), falling back to the fake bus and listing the existing serial ports in the log; the top bar gained a serial port dropdown and a 「连接」 (connect) button, so after plugging in USB one click takes over, with no service restart |
| 0.8.0 | 2026-09-20 | Calibration switched from writing 128 to the 0x0B instruction (the hardware test showed the HD-1910 doesn't accept 128; the "success" in 0.7.x was really just readings that were already close to 2048); success requires the reading to actually become the target; a saved pose can be chosen as the reference (calibrating while 「缩」 (tucked)); torque is off for only a few milliseconds (0.7.x waited 30–130 ms with it off, and the neck was pushed down 80 steps); undo only shifts the poses shifted that time (in 0.7.x undo shifted the later-saved 「站」 (stand) and 「缩」 (tuck) in the opposite direction; restored from the logs); backup file names include milliseconds; single-servo calibration follows the reference |
| 0.7.3 | 2026-09-20 | Fixed 0.7.1 calibration failing on all 15 (`'_thread.lock' object is not callable`: the serial mutex was named `self.lock`, shadowing the `lock()` method that applies the EEPROM lock); export reads up to 86 (previously read to 90, and the real servo replied "short read"); calibration also locks on errors midway, and does not restore torque on error; log categories + writing to file + filter and copy; single-servo operations switched to a dropdown; protocol-level simulator and self-test |
| 0.7.2 | 2026-09-20 | Poses can be deleted (× button; moved into `poses/.trash/` so they can be recovered); pose buttons with the same name show the date |
| 0.7.1 | 2026-09-20 | Fixed center calibration: 0.7.0 wrote 128 with torque on and locked; the servo replied "成功" (success) but wasn't calibrated at all, and then writing the goal as 2048 actually pulled the joint back to the old zero. Changed to per servo: unlock → torque off → write 128 → read back to confirm → goal → restore torque → lock; if calibration doesn't succeed, nothing moves |
| 0.7.0 | 2026-09-20 | One-click center calibration (all or specified IDs) + undo; top bar shows online count, refresh rate, average voltage; joint angle shown per servo (borrowed from a community member's debug console); all 15 directions reversed |
| 0.6.0 | 2026-09-20 | Joint directions stored in `directions.json`, shared by all pages; on the real robot, 23, 13 and 30–34 checked as reversed; 「复制 robotd 方向表」 (copy robotd direction table); page disables browser caching; version number |
| 0.5.0 | 2026-09-19 | 「灵动」 (expressive) head moves; smooth motion made non-blocking on the backend; fixed writing 0 to the speed register meaning stop when phase BIT3=0 |
| 0.4.0 | 2026-09-18 | Center-of-mass projection and support area in 3D; smooth motion (the servo runs its own trapezoidal profile); goal position read back and verified, resent if not reached |
| 0.3.0 | 2026-09-18 | Save/load poses, 「缩起来」 (tuck up) and 「站姿」 (stance) buttons, stand-up / tuck-back sequences, transition time |
| 0.2.0 | 2026-09-17 | Mouth hinge, a hint when torque isn't on, official stance button, default port changed to 8080 |
| 0.1.0 | 2026-09-17 | First version: sliders, live readback, 3D follow, register export, timing test, ID change, center calibration |

## Files

| File | What it does |
|---|---|
| `server.py` | HTTP + WebSocket service, starlette + uvicorn |
| `feetech.py` | Feetech protocol: PING / READ / WRITE / SYNC_READ / SYNC_WRITE / REBOOT, register name table |
| `sim_bus.py` / `selftest.py` | Protocol-level servo simulator / backend self-test |
| `servo_report.py` / `test_servo_report.py` | Servo health check (read-only) / tests against `sim_bus` |
| `远程排查交接.md` | Troubleshooting and calibration procedure for the AI on another computer (remote troubleshooting handoff) |
| `logs/` `calib/` | Runtime logs and pre-calibration offset backups; local to this machine, not in the repo |
| `index.html` | Single-file frontend; three.js comes from a CDN |
| `imu_bridge.py` / `test_imu_bridge.py` | J-Link / pyOCD reading, firmware verification, sample decoding and hardware-free tests |
| `test_imu_swd.py` | Tests for the `--imu-swd` (pyOCD) reader: uses a fake pyocd module, no probe connected |
| `imu_bus.py` / `dxl2.py` | `--imu-bus`: IMU bus reading and DXL2 compatibility adapter |
| `imu_attitude.js` / `test_imu_attitude.cjs` | IMU quaternion, mounting orientation and display reference conversion, and regression tests |
| `imu-jlink.example.json` / `test_imu_server.py` | Personal configuration template / IMU integration tests for the existing service |
| `build_model.py` | MuJoCo XML + STL → `model/model.json` + `model/meshes.bin` (vertices int16-quantized, 21 MB down to 2.9 MB) |
| `model/` | The generated model, 14 joints |
