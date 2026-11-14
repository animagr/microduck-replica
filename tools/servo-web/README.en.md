# servo-web · Feetech servo web debug console

**English** · [简体中文](README.md)

> The 3D model on the page is for debugging display only and is still based on the upstream simulation geometry; it **must not be exported and used as the latest Feetech printed parts**. Get structural parts and assembly models from [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).

Connect the serial port, drag sliders in the browser to move the servos, and the 3D duck turns along with them. It is for assembly, zeroing and bench acceptance checks, and it is also the tool for items 0–8 of the bench checklist in the [Feetech adaptation architecture](../../software/飞特适配架构.md).

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
- Remote troubleshooting: [`远程排查交接.md`](远程排查交接.md) (remote troubleshooting handoff) is a procedure written for Claude Code on another computer (health check → single-servo troubleshooting → enable protection → folded calibration); over there, say 「先读 tools/servo-web/远程排查交接.md，按里面的流程带我做」 (first read tools/servo-web/远程排查交接.md and walk me through the procedure in it)
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

First confirm the board has a WiFi address and SSH login works, configured per the [board image guide](../radxa/镜像使用说明.md#4-连-wifi). Put this folder and its dependencies on the board, confirm that programs such as `robotd` are not holding `/dev/ttyS2`, then run:

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

Node.js is only used for the frontend math tests and is not needed for normal use of the debug console. Firmware host tests and historical real-board records are in [VALIDATION.md](../../hardware/imu_to_dxl/firmware/VALIDATION.md).

## Notes
