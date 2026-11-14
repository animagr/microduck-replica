# Microduck Studio

**English** · [简体中文](README.md)

A web console installed on the duck. Open `http://<duck IP>:8000/` in a computer or phone browser to see the duck's current status and turn torque off with one click; you can also stand up/walk, pair a Bluetooth gamepad (through the official `robotctl pad pair`), calibrate servos, calibrate the IMU orientation, write these two together with the orientation into the main program in one go, and run the assembly checks following the “上手清单” (Getting started checklist). While the duck has its hotspot open waiting for network setup, you can also use your phone to pick your home WiFi and enter the password.

## What it does and does not do

- Normally it talks to the duck's main program robotd (`/run/robotd.sock`, interface v40); when the servo page needs to drive the servos directly, it first has robotd hand over the bus, and hands it back when done.
- Every status on the page comes from robotd's read-back: for example, “已卸力 ✓” (Torque off ✓) is only shown once busStatus confirms torque is off, not just because the button was pressed.
- Stopping Studio does not affect the duck; stopping robotd does **not** turn servo torque off (the servos hold their last command), and the page warns about this.
- **Studio exiting does not turn torque off**: if Studio exits (restart, upgrade) while the servo page's bus session is open, it only closes the serial port, and servos that are holding keep holding.
  When the bus is opened, `servo-session.json` (serial port, start time, who opened it) is written to the state folder, and it is only deleted when “交还主程序” (Hand back to main program) succeeds; if Studio sees it on startup
  and robotd is not running, it automatically takes over the bus again (opened read-only, torque unchanged), and the banner at the top of every page stays as before; if the takeover fails, the banner says
  “上次退出时可能还有舵机保持着，去舵机页接管后才能卸力” (Some servos may still have been holding at the last exit; take over on the servo page before you can turn torque off), and the torque-off button at the top takes you to the servo page. If robotd is running: it already released everything when it started, so the marker is deleted.
- During a servo session it checks robotd's socket every 5 seconds: if robotd has been started manually (it would release all servos and fight Studio for the serial port), it logs an error and Studio closes the bus (without writing to the servos),
  and the banner turns red. To go back to the main program, click “交还主程序” (Hand back to main program); do not run `systemctl start robotd` manually.

## Folder layout

```
run.py              Entry point (python3 -I run.py …): puts deps/ on the search path, then enters studio
run_tests.py        Runs all tests
studio/
  log.py            Logging: categories, levels, millisecond timestamps, dedup, redaction, daily rotation; commands are logged as "sent → ack · duration"
  auth.py           Admin password (scrypt), login sessions, failure backoff, Host/Origin checks
  rpc.py            JSON-RPC connection to robotd/configd (one request at a time per connection)
  robotd.py         Connections: one persistent each for polling / live status stream / commands / configd; each torque-off opens a fresh one (so it never hits a dead connection after robotd restarts)
  estop.py          Torque-off state machine: ready → pending → confirmed / unavailable; only accepts read-backs "sent after the torque-off ack"
  state.py          Aggregates raw data into the state pushed to the page (posture, battery, servos, IMU, gamepad, to-dos, network setup)
  models.py         Model library, default restore, read-back of the actual switch, gamepad remapping
  model_package.py  Model deployment package parsing and robotd hardware-free pre-check
  sensors.py        Camera source configuration and on-demand ToF snapshots (independent of motion control)
  net.py            Network setup: reads netcheck's net.json, configd's net.status / scan / connect / forget, toggles the hotspot
  app.py            Web service: static files, login, logs, diagnostic bundle, WebSocket
web/                Pages (Preact + htm, three.js draws the 3D duck; all local files, no CDN; wifi.js is the Connect WiFi card and settings;
                    probe.svg is the small image used to find the duck's new address after connecting to WiFi)
deps/               Pinned-version Python dependencies (starlette, uvicorn, etc., see deps/VERSIONS.txt)
dev/
  record_robotd.py  Records a read-only copy of robotd's real responses on the duck (for the fake robotd and tests)
  fake_robotd.py    Fake robotd + fake configd: replays recorded data, so it runs on a computer without a duck
tests/              Unit tests + data recorded on the real robot, fixtures/now-20261018.jsonl
```

## Running on a computer (no duck)

Requires Python 3.13 (same as the board; on Windows it is `py -3.13`).

```bash
py -3.13 -I dev/fake_robotd.py --fixture tests/fixtures/now-20261018.jsonl \
    --net-mode hotspot --net-state-file ./state-dev/net.json   # fake robotd + fake hotspot network setup, listening on 17001/17002
py -3.13 -I run.py --listen 127.0.0.1:18080 --robotd tcp:127.0.0.1:17001 --configd tcp:127.0.0.1:17002 \
    --net-state ./state-dev/net.json --dev-autologin --state-dir ./state-dev --log-dir ./logs-dev
```

Open `http://127.0.0.1:18080/` in a browser. `--dev-autologin` only accepts local requests and can only be used with `127.0.0.1`, which is handy for screenshot testing; do not use it on the duck.
The fake robotd can select the main program mode with `--mode commissioning|motion` (the factory scenario is `--mode commissioning --calib factory`), and change posture with `--posture limp|policy|commissioning|starting`; `--net-mode hotspot|wifi|none` writes a fake net.json.
Commissioning mode follows the fork's real behavior: after startup it first returns the startup report (`phase=configuring_bus`), and only returns live snapshots after the first successful read; `--commissioning-stuck-status` simulates the old fork (the startup report never clears, and Studio keeps seeing “启动中” (Starting)).
Without `--net-state` it reads `/run/microduck/net.json`; if the file is missing (on a computer, old images) WiFi is not shown. Without `--duck-label`, the UI uses the hostname (`duck-xxxx` on the duck).

Python on Windows has no Unix sockets, so addresses are written as `tcp:host:port`; on the duck it is `unix:/run/robotd.sock` (the default).

## Camera and ToF

After “手柄” (Gamepad) on the left are two separate pages, “摄像头” (Camera) and “ToF”, which also have entries in the phone's bottom bar.

The status bar on the overview / gamepad page shows, in order, battery, servos, IMU, camera, ToF, gamepad and board. The camera's "service online" state is determined only from a read-only `hello` on the local mediad socket; a configuration file or test pattern is not treated as a real camera being connected; open the page to see the actual video. ToF shows online based on new frames, and fake/sim is explicitly labeled as simulated data. The status bar checks every 10 seconds, cancels when switching pages or going to the background, and clears stale status; the checks do not request video frames, set up WebRTC or start system services.

The current image does not yet have a unified policy of "automatically detecting camera/ToF hardware at boot and then starting or stopping services based on the result". firstboot's automatic detection targets the IMU; the image defaults to `media.source="test"` to avoid repeated crashes without a camera, but the media service may still be running. If the web page is not connected, it may be a network or service problem, so you cannot conclude from that alone that the hardware is not installed and shut down the service.

Scroll down the overview to the gamepad section: there is a camera preview below the 3D duck on the left, while the gamepad and remote control stay on the right. On desktop the whole left column is sticky, laying out posture and video according to the available height, and scrolls with the page when there is not enough space; on phones the order is gamepad diagram, 3D, camera, remote control. The existing WebRTC video is connected automatically only when the preview card is on screen, the overview is visible, and the read-only check reports that the source is configured as a camera and the video service is online. Test sources, unknown sources and an offline service show a placeholder, are rechecked every 10 seconds, and do not auto-play the test pattern. Switching pages, scrolling the card out of view or going to the background cancels reading and releases the video connection; the standalone camera page can still play the test source on demand. This layout reuses the same video client, does not start system services, and does not mean camera hardware hot-plug auto-configuration has been implemented.

- **Camera**: connects to the existing mediad LAN WebRTC video (default signaling port 8443), and can start, stop and reconnect. The page only shows playing once the actual picture starts updating; switching away or going to the background releases the connection. It only reads video and frame metadata, does not open the computer's/phone's camera, and sends no motion commands. The picture is displayed according to the mounting angle reported by the runtime.
- **Source label**: the image's `[media] source="test"` means a test pattern; even if it plays, it does not mean a real camera is connected. When configured as camera, it also only shows “配置：摄像头” (Config: camera), since a configuration file cannot prove the current runtime state; when the video service is marked as a simulated device, that is noted separately. The current version ignores the old `media.camera` switch, and Studio does not guess the real source from it.
- **ToF**: gets the 8×8 distance zones through `tof.stream` on `/run/tofd/tof.sock`, and shows the number of valid cells, the nearest/farthest valid millimeter values and the raw status of each cell. Only cells with status 5/9 and a positive distance count toward statistics; no target (255) and measurement failure are shown separately. Service not connected, no sensor attached, waiting for the first frame, format error and stale data each have their own explanation. fake/sim data is labeled “模拟数据” (simulated data).
- Sensor reading is independent of robotd's motion connection and only happens while the relevant page is visible; there is no automatic obstacle avoidance, navigation or background recording, and system services and configuration are not changed.

Advanced installations can specify local services with `--tof unix:/run/tofd/tof.sock`, `--camera-socket unix:/run/mediad/media.sock` and `--camera-signaling-port 8443`; `--tof none` or `--camera-socket none` explicitly turns off the corresponding read-only probe. For development tests, the socket can point to a controlled `tcp:127.0.0.1:port`. The web page does not accept arbitrary socket or video server addresses. Camera signaling uses the hostname Studio was opened with; an SSH tunnel that only forwards port 8000 remotely will not automatically forward the video link.

The local `tests/test_sensors_e2e.py` uses clearly labeled fake ToF and browser RTC test implementations to verify real web playback, navigation, errors and resource release; these software tests do not replace camera, encoder and ToF hardware acceptance checks.

## Web motion recording, playback and Lively

The remote control section adds “动作录制与回放” (Motion recording and playback). First get the duck standing steadily and ready to walk following the usual flow, turn off the physical gamepad, then click “开始录制” (Start recording) and operate the web sticks, head/body/beak, sounds, or click “坐下／站起来” (Sit down / Stand up) (the web D-pad down also works). Recording only "sit down → stand up" can also be saved as a clip; during sit/stand, wait for the status prompt to confirm before doing the next step. You can turn on “灵动” (Lively) at the same time to generate small random head and beak movements; Lively stops first when a sit/stand starts. Paused recording time does not count as waiting time; after finishing, enter a name and save.

Select a clip from the list and play it 1, 3 or 5 times; pause, resume, stop, rename and delete are supported, and saved content persists across refreshes and restarts. Lively can also be turned on by itself. Motion is still executed by robotd; the web page does not take over the servo bus, and turning on Lively does not automatically stand up or enable torque.

It records the control commands that were finally allowed to be sent, along with their timing; it does not guarantee repeating the same spatial path. It does not record camera video, microphone audio, torque on/off, start walking/stop policy or settings changes. Sit down and stand up are saved as explicit target steps; during playback it reads the current posture instead of blindly pressing the toggle again, and only executes the next step after a fresh policy phase and continuous actual/target joint read-backs confirm it, with the playback timeline paused while waiting. Recordings that include sit/stand are saved as v2, and old v1 recordings can still be read; rolling back to a program that only supports v1 skips v2, which can still be read after restoring the new program, so the original recordings should not be deleted.

A recording that ends sitting can be played once; if you choose multiple loops, it must be recorded back to standing at the end, otherwise the page explains why and does not add a stand-up step automatically. An ordinary pause/stop or leaving the web page only cancels subsequent steps and clears continuous control; a sit/stand already handed to the main program will still complete; if you need torque off immediately, use the existing e-stop. If the sit/stand phase/read-back is unclear, the 15-second wait times out, or the ack is lost, subsequent steps stop and the reason is explained, with no automatic retry of the toggle.

Model skills such as kicking, rolling and picking up are still not recorded; skills from ordinary remote control are unaffected. Right after doing one of these model skills, you need to manually stop the policy, start walking again and wait for a fresh read-back to confirm readiness before starting recording/Lively; skill completion cannot be judged from a guessed duration.

Only one page session at a time. Manual takeover with buttons/sticks stops automatic playback first; a physical gamepad connecting, the web page leaving the remote control section, going to the background, losing focus, disconnecting, e-stop or an abnormal status all stop automatic output, and reconnecting does not resume playback. Pausing clears velocity and head/body/beak targets; resuming restores the latched pose at the pause point, while velocity waits for the next fresh motion frame; after a model/control configuration change, old clips are no longer played back. At the end of each round it recenters, exits the body latch and closes the beak, and late continuous targets are merged to avoid sending a string of outdated motions.

Each clip is at most 60 seconds, 6,000 events and 1 MiB; at most 20 clips, with names up to 32 characters. Versioned JSON files are saved in `motion-recordings/` in Studio's state folder with atomic writes; corrupted recordings are skipped with a notice on the page, without affecting other controls or usable recordings. This user data folder must be kept when uninstalling/upgrading.

The implementation is split into `studio/motion_store.py` (file validation/saving), `studio/motion_studio.py` (session/timeline/Lively), `studio/motion_posture.py` (sit/stand targets and read-back checks), `web/motion-studio.js` (UI) and `web/motion-heartbeat.js` (page liveness). It is connected through `op=motion` on the existing `pad.op`, and the original `pad.motion` state is not renamed. Current development and acceptance check records are in the [web motion implementation plan](../../docs/superpowers/plans/2026-10-25-web-motion-studio.md) and the [sit/stand extension plan](../../docs/superpowers/plans/2026-10-25-web-posture-recording.md); local simulation passes and real-duck acceptance checks are recorded separately.

2026-10-25: c18783c has been deployed to the current duck's original control URL, restarting only Studio; 351 software checks and read-backs of static assets/user data/control service identity passed. This device has web login protection, and the login was not bypassed to check the snapshot, so the actual motion effect still awaits user confirmation. The frozen source package, backups and rollback scope are in the [deployment acceptance check](../../docs/superpowers/verification/2026-10-25-web-motion-studio.md). The image and generic online upgrade were not updated.

The same day, after the user confirmed the entry point via screenshot, it was found that the skill recovery barrier for stopping the policy wrongly waited for a static configuration switch to turn off. db970dd fixed it to use the live runtime state `bus.policy_enabled`, and prompts the user to confirm it has stopped and then click “开始走” (Start walking); 205 backend tests and the full browser recovery/record-playback flow passed, and it has been updated on the original duck, restarting only Studio. The real head and beak motion effect still awaits user confirmation; see the follow-up fixes in the same acceptance check record.

Later the same day, aa825fc added sit down/stand up to recording; 389 software checks and an independent review passed, and it was deployed. The user confirmed "能保存，回放坐站也正常" (saving works, and sit/stand playback is normal too); the real-hardware scope, state waits and v2 rollback boundaries are in the [sit/stand acceptance check](../../docs/superpowers/verification/2026-10-25-web-posture-recording.md).

## Bench mode: main controller not flashed, tune servos on a computer with the Feetech debug board

Plug the Feetech debug board (or a USB-to-TTL adapter) into the computer, connect the servos and power, then:

```bash
py -3.13 -I run.py --bench
```

It does not connect to the main program and automatically opens the browser on the “舵机” (Servos) page; pick the COM port in the “串口” (Serial port) drop-down in the page header and click “连接” (Connect) to start tuning (same as servo-web).
To take a look without hardware attached: choose “演示（没接舵机）” (Demo (no servos attached)) as the serial port, and Studio pretends in software that there are 15 servos.

## Installing on the duck

1. Copy: copy the whole `software/studio` folder to `/home/radxa/studio-dev` on the duck (`scp -r` or unpacking an archive from a USB stick both work).
2. Self-check: run `python3 -I run.py --selfcheck` on the duck (read-only: prints the version and queries robotd / configd / padd once each).
3. Install the root helper: `cd deploy && sudo sh install.sh radxa`. The 0.7.2 helper handles servo bus handover, gamepad pairing, the hotspot toggle, `calib-read` / `calib-commit` (write calibration into the main program and switch to motion mode), `ssh-status` / `ssh-password` (the SSH toggle on the “更多” (More) page), and `imu-recalibrate` (re-verifies the saved IMU mounting orientation); before turning off the hotspot it writes `/run/microduck/studio-connecting.json` so that netcheck stays out of the way during the connection. When handing back from the servo page, a live snapshot in commissioning mode also counts as the main program being up (0.5.1 only accepted motion mode's `control`, so in commissioning mode it always waited the full 30 seconds and concluded "failed to start"). Steps, uninstallation and on-robot checks are in `deploy/INSTALL.md`.
4. Boot service: install it with the commands in the header of `deploy/microduck-studio.service`:

   ```bash
   sudo install -m 644 microduck-studio.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now microduck-studio
   ```

   To remove:

   ```bash
   sudo systemctl disable --now microduck-studio && sudo rm /etc/systemd/system/microduck-studio.service && sudo systemctl daemon-reload
   ```

5. Open `http://<duck IP>:8000/` and follow the “上手清单” (Getting started checklist) on the page.

The main path for gamepad pairing is the root helper calling the official `/usr/local/bin/robotctl pad pair --json`: on `/var/lib/robot/weird-ble` boards it first stops `btd`, power-cycles the Bluetooth adapter, and brings `btd` back up after pairing. If the helper is not installed or is an old version, it falls back to configd → bluetoothctl; on this board that may fail to pair, and the wizard suggests reinstalling the helper or running `sudo robotctl pad pair` on the duck.

A pairing result does not mean the buttons are ready. After helper/configd returns bound, while waiting for the connection and padd input the wizard makes up to two additional connection requests to the target gamepad, each at most 5 seconds and never beyond the current wait window; it does not clear the pairing or restart Bluetooth. Readiness is confirmed only by a padd input report from the same MAC; other connected gamepads do not count. When the status service updates slowly, or input arrives right at the timeout boundary, actual input takes precedence; if the same gamepad recovers a bit later, the wizard's old “未连接／读不到按键” (Not connected / cannot read buttons) message is also cleared. If the user has cancelled, padd is not running, or walking has started, no further reconnection attempts are made. The fallback notice for old versions without an input side channel is still clearly labeled “没法再核对” (cannot verify further).

This reconnect assist targets the web pairing flow; if the gamepad is already paired and just asleep, first short-press the Home / Xbox button to wake it, with no need to forget and re-pair every time. This fix does not provide unlimited background reconnection, and does not mean the reconnect behavior of every model after power loss has been checked one by one.

The factory image runs robotd in commissioning mode: `ExecStart` in `/etc/systemd/system/robotd.service.d/zzzz-zz-microduck-commissioning.conf` includes `--commissioning`. This way `calibration-status` and `busStatus.last_sample` can be read immediately, and the IMU page's coarse calibration and the servo page's center calibration can both be done. After step 3 of the getting-started checklist is written successfully, the helper deletes this file, runs `daemon-reload` and restarts robotd, and the main program returns to motion mode. If `systemctl show robotd -p ExecStart` contains `--commissioning` but that file is not present, the helper refuses to switch automatically (`foreign_commissioning`); go to the logs page and export a diagnostic bundle.

The “IMU 安装方向” (IMU mounting orientation) entry on the IMU page is always available: even a mounting quaternion that has already been saved and verified can be redone with “重新标定方向” (Recalibrate orientation). First hold the duck and turn torque off; after a second confirmation, motion mode temporarily returns to commissioning mode through the new root helper; if already in commissioning mode, it simply re-collects. It keeps the original flow: 3 seconds still, tilt the whole torso forward 15–30° and collect for 3 seconds, compute the orientation, and verification by the main program. **Before clicking “交给主程序验证” (Hand to main program for verification), first return the robot upright and hold it still**, then tilt forward as prompted. The helper's recalibration recovery session keeps torque off; factory commissioning mode also supports the standing-pose data collection described below, and the standing fine-calibration flow is unchanged.

The IMU on bus ID 200 is detected automatically by the main program at startup; FT6, IMU-to-DXL (Feetech) and SFLP 124/12 (Dynamixel 2.0) are supported. The IMU page in both commissioning and motion mode shows the actual protocol and board. The board name indicates the detected register layout and does not prove the vendor. To specify it manually, change the main program configuration `bus.imu_protocol = "auto" / "feetech" / "dxl2"`; the web page has no button to switch protocols at runtime. The I²C BNO085 and LSM6DSV16X flows are unchanged.

Qinmo's one-time web selection, controlled reconnection and the mandatory mounting orientation verification are covered in the [usage guide](../../docs/Qinmo-IMU-网页使用.md). The configured type and the actual connection are shown separately; Qinmo is explicitly labeled as configured, and the vendor cannot be certified automatically from ID200 or the layout. The new helper 0.7.2 also keeps `imu_bus_profile` (default legacy), and a type change, even between Feetech types, invalidates the old orientation and pending write results. Local software verification does not mean a physical acceptance check, and the published image has not been deployed or updated.

The bus mounting orientation's `imu_bus_protocol` is written after the main program verifies it successfully; old calibrations without this field are only compatible with Feetech. When the detected protocol does not match, the page prompts for recalibration, and skipping step 2 cannot make the old orientation count as verified. The main program keeps the redo entry available through the disabled state in motion mode. Step 3 and helper 0.7.1 keep and read back this field; after a redo completes, the new binding can be adopted, and cancelling restores the original file. A change in protocol, board layout or raw identity bytes invalidates the current collection, in-flight computation and old standing calibration results. DXL2 boards do not provide sample sequence numbers, status bits or sensor reading age; the main program uses host-side receive freshness and raw-byte freeze checks, and the page does not fabricate these diagnostic values.

For the first mounting orientation calibration in factory commissioning mode, you can also first click “站姿使能” (Enable standing pose) manually: wait for the HOME hold to stand steadily (error ≤5°), hold the whole torso with both hands while collecting still and forward-tilt data, then return it upright and hand it to the main program for verification. Both torque off and clearly standing steadily are allowed; standing up in progress, unknown torque, moving, and torque-off pending confirmation are still refused. A recalibration recovery session entered from motion mode through the helper still requires torque off throughout, to avoid the main program restarting during recovery mode affecting the standing pose. Data collection never enables torque or starts motion automatically.

The recalibration session keeps the original calibration and startup configuration; it can be continued after refreshing the web page or restarting Studio, or you can “取消并恢复原参数” (Cancel and restore original parameters). After verification passes, it reads back the current chip and new orientation item by item, and restores only the original motion permission and run mode; the servo zero positions (including zero positions other than 2048), directions, limits, other IMUs and unknown configuration are all kept; even after a successful restore, torque stays off. On failure the restore entry is kept, and an orientation that was not read back is never reported as complete. This flow requires updating Studio, the root helper and sudoers together; it does not call step 3 of the getting-started checklist to rewrite the servo calibration.

**Commissioning-mode status requires the new fork**: as soon as the fork's robotd starts, it writes a startup report (`{"mode":"commissioning","phase":"configuring_bus",...}`), and `robot.busStatus` keeps returning it as long as its phase is a startup phase; only after the first successful read does it return commissioning mode's live snapshot (phase is `ready` / `moving` / `read_error` / `stop_unconfirmed` / `power_pending`, with `last_sample`). The old fork's commissioning mode never cleared the startup report, so Studio would see “启动中” (Starting) forever and never get `last_sample` (this is what happened in the 10-20 real-hardware acceptance check); the fork has been changed to clear it after the first successful read, so use an image from after 20261020 (or reinstall that robotd). On Studio's side: all of these live snapshot phases count as "main program is up" (`read_error` means it is up but reading the servos failed, and the main program's message is shown verbatim); if it keeps reporting a startup phase for more than 30 seconds (counted from this connection), the overview header changes to “主程序一直报『启动中』” (The main program keeps reporting "Starting") and offers “去日志页” (Go to logs page), and the top bar, to-dos and getting-started checklist header no longer say “通常 10 秒” (usually 10 seconds).

When the battery is powered by a bench power supply, choose “台架电源” (Bench power supply) as the model in “设置 → 电池” (Settings → Battery): only the voltage is shown, with no charge level calculated or reported.
Studio has no password by default, so anyone on the same network can open it. You can set one directly in “设置 → 网页登录密码” (Settings → Web login password); once set, you must log in before changing it, and you can also clear it. The command line `python3 -I run.py set-password` still works, but run it as the radxa user, without `sudo` (Studio cannot read a password file written by root).

### Letting an AI assistant on your computer connect over SSH

Below the overview dashboard strip and at the top of the settings page there is a “让 AI 连接鸭子（SSH）” (Let AI connect to the duck (SSH)) entry; clicking it goes to `#/settings/ssh` and jumps to the three-step guide. No monitor is needed; the computer must first be able to reach the duck's web page / board address.

1. **Web login password**: used for the browser control pages, at least 6 characters. If already set, it shows “已设置” (Set), and expands only when you need to change it.
2. **SSH system login password**: used by a computer terminal or AI coding assistant to log in to the board's system account (usually `radxa`), 8–64 characters. Set the web login password first, then enable this as needed; you can skip it for everyday web control. If it is already enabled or a public key already exists, there is no need to set the password again; public key registration/deletion remains available in the expandable section.
3. **Copy the connection instructions for the AI**: shows the board address, username, the standard SSH port 22 and the login command. Shown only when the SSH service is read as running and a password/public key login method exists. The copied content includes how to connect but not the password; the system password is entered by you when the connected terminal prompts for it. If the browser does not allow automatic copying, the full text is shown in a selectable form for manual copying.

The two passwords are stored and changed independently; “确认密码” (Confirm password) means entering the same password you are setting a second time to prevent typos; normal login only asks for it once. After the web password is saved for the first time, the front end refreshes the current browser session and CSRF before entering SSH settings. An SSH status of configured does not mean the computer has successfully connected; check the connection read-only first. When the status is unknown or the service is not running, the page offers a refresh and an explanation.

This section is the remote debugging entry for an AI coding assistant on your computer. The development browser tests use an isolated SSH helper fixture and do not actually change the computer's system password, SSH service or user keys; they do not replace an end-to-end acceptance check on the real robot.

## Getting started checklist: Go, Done, Skip

Every row always has three buttons (user, 10-20: "可能有人之前做过重新走一遍" (someone may have done it before and is going through it again), "允许人家直接跳过" (let people skip it directly)):

- **“去做” (Go)**: goes to that step's page; rows where a problem was detected say “重新做” (Redo).
- **“已完成” (Done)**: I did this before (e.g. Duck No. 2's zero positions were calibrated long ago on Studio's servo page); the row gets ✓ and says “你标了已完成（时间）” (You marked this done (time)). The former “已经校过，核对一下” (Already calibrated, check it) is this button.
- **“跳过” (Skip)**: don't do it for now; the row gets ↷.

Marked rows offer “重新做” (Redo) and “取消” (Cancel) (for skipped rows, “取消跳过” (Unskip)). A mark is bound to that step's fingerprint (servo zero positions, IMU orientation, calibration, gamepad…); if the fingerprint changes, the mark no longer counts and the row goes back to "to do"; if the fingerprint cannot be read when marking, it is bound once it can be read.
The cases that used to be locked (the main program says it is not finished, unreadable (?), a problem detected, testing the e-stop, tuning servos) can all be clicked now, but “已完成” (Done) and “跳过” (Skip) need two clicks, and the second click's button states the consequence (something like “确定跳过？主程序说标定没做完：跳过了鸭子也站不起来” (Really skip? The main program says calibration is not done: if you skip, the duck still cannot stand up)); the back end also refuses without receiving the confirmation.
If step 1 is marked done or skipped, “舵机零位” (Servo zero position) in the readiness check of step 3, “写进主程序” (Write into main program), counts as satisfied (all 15 are written with 2048 as the zero position, which is only correct if the zero positions were calibrated on Studio's servo page).
If step 2 is marked done or skipped, the orientation of the IMU currently used by the main program has not been confirmed, and no standing calibration was done on the IMU page (no `imu-pending.json`), step 3 **writes this IMU with the default mounting and marks it as confirmed** (10-21 real-hardware acceptance check: after skipping everything, the fork required the IMU orientation to be confirmed before entering motion mode, and the duck stayed stuck in commissioning mode):

- Bus small board (`bus`): the existing `imu_mount_quat` in the file (from the factory this is the official mounting `[0.7071067811865476, 0, 0.7071067811865476, 0]`);
- BNO085 (`bno08x`): `[0.5, 0.5, 0.5, 0.5]`, `BNO08X_DEFAULT_MOUNT` in the fork's `duck-control/src/trunk_imu.rs`;
- LSM6DSV16X (`lsm6dsv16x`): `[0.7071067811865476, 0, 0.7071067811865476, 0]`, the replica's recommended mounting (module x down, z forward, measured on Duck No. 2 on 10-17). The fork's own default is the identity quaternion ("the small board has no commonly agreed up direction"), which is not used.

The readiness check says “你标了第 2 步已完成：IMU 按默认装法写（芯片：哪种装法）。装得不一样的，站起来会往一边倒——写完以后在 IMU 页站着校一次，再写一次主程序” (You marked step 2 done: the IMU will be written with the default mounting (chip: which mounting). If yours is mounted differently, it will fall to one side when standing up; after writing, do a standing calibration on the IMU page and write into the main program again); the second click on “写进主程序” (Write into main program) says “确定？IMU 按默认装法写” (Sure? The IMU will be written with the default mounting). If a standing calibration was done on the IMU page (`imu-pending.json` exists), it is used as before; if the orientation is already confirmed in the main program, the main program's is used as before; if what the IMU page recorded is for a different chip, or the main program has not yet reported which IMU it uses, it does not guess and keeps blocking as before. The helper's `calib-commit` still only accepts `imu: {source, quat}`. This way **skip steps 1 and 2 → step 3 write into main program → motion mode** works end to end.

## Choosing the address to open Studio

A Windows computer with Clash's system proxy running cannot open `duck-xxxx.local` (it goes through the proxy, 502); the dotless `duck-xxxx` opens (Windows finds the duck via LLMNR, and the proxy bypasses it by `<local>`). So the page lists addresses by device:

- Windows computer: `http://duck-xxxx:8000/` (opens even with the proxy running);
- iPhone, Mac: `http://duck-xxxx.local:8000/`;
- Android phone, or if none opens: find `duck-xxxx` in the router's device list and use its IP;
- If the computer has Clash's TUN mode on and still cannot open it: set the LAN (192.168.0.0/16) to direct connection in Clash.

The “更多” (More) page has a “这只鸭子的地址” (This duck's addresses) block listing the currently usable IP (`ip4` from configd's `net.status`; 10.42.0.1 in hotspot mode), `duck-xxxx` and `duck-xxxx.local`, each copyable; hovering over the duck's name in the overview top bar also shows the IP. The duck's own hotspot is filtered out of the Connect WiFi list (by `hotspot_ssid` in net.json; if missing, by "starts with `Microduck-` and saved").
