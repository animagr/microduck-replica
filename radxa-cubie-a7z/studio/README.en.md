# Cubie A7Z Studio installation record

**English** · [简体中文](README.md)

## After Nov 6, 2026 14:34: web virtual gamepad connected

The user has completed servo and IMU calibration, explicitly asked to use the web virtual gamepad, and confirmed that the duck is held steady and that a brief torque-off restart is allowed.

- Fixed the problem where `--configd none` was still turned into an RPC address by `default_pad`: it made `pad-watch` throw `ValueError` and display “认不出有没有实体手柄” (cannot tell whether a physical gamepad is present). The patch is in `a7z-disabled-configd-pad.patch` and only maps the disabled service to `None`; normal configd and the physical-gamepad priority rules are kept.
- The new `pad.py` has been deployed and verified; only Studio was restarted first, and neither main controller PID5314 nor the calibration changed. The old file is saved on the board at `/var/lib/robot/before-vpad-configd-20261106T063223349819Z/pad.py`.
- The main controller on site was already in motion mode, but `[policy] enabled=false` prevented all models from loading. The walking and sit/stand models each passed inference validation through the formal `robotd validate-policy`; then, after first confirming torque was off, only that setting was changed to true, and the main controller was restarted to PID9174. The models loaded successfully; at the end of the restart the policy had not started, torque was confirmed off, and the calibration file was not modified. The configuration backup is on the board at `/var/lib/robot/before-load-walking-20261106T063418908538Z`.
- Running “站起来” (stand up) in a real browser got an accepted reply from the main controller; afterward, phone operation, walking model execution and the page showing “站着，准备好走了” (standing, ready to walk) were observed. No forward velocity was sent by the agent; the user then confirmed on site that "it can already step", so the chain from virtual gamepad to real-world stepping is verified. Long-term stable walking has not passed an acceptance check yet. The physical gamepad state and the physical Select e-stop have still not been checked; the web page does not need a physical gamepad to be connected.
- 13 adaptation regression tests and 159 original gamepad tests passed. On the first run in the sandbox, 5 of the 159 failed because of localhost binding permissions; after allowing local test ports, all passed.
- The intermittent bus fault is not solved yet: after the restart there was once an ID33 status error `0x02`; the board throttled at about 60–63°C after model execution. Two 10-second observation windows each had no new read failures, which cannot replace a five-minute stability or motion acceptance check.

The historical record from the first read-only installation is kept below; it does not describe the current running mode.

Nov 6, 2026: installed on `cubie-XXXX` / `BOARD_IP` at the user's request.

Entry point: <http://BOARD_IP:8000/#/servos>. Open it on the same LAN, and the user calibrates manually following the servo page flow. Studio is set to start at boot.

Install directory `/opt/microduck-studio/app`, standalone Python in `/opt/microduck-studio/python`; the system Python 3.9 was not replaced. State and logs are in `/var/lib/microduck-studio` and `/var/log/microduck-studio` respectively.

The source comes from `f682b7bd30d1ef4e6f931db16406b340d4d54fec` of `fanhao375/microduck-replica`; only `software/studio` was exported and then this directory's patches were applied, without modifying neighboring projects. The standalone runtime is `cpython-3.13.14-linux-aarch64-gnu` provided by uv. The full package and checksums are in the local `artifacts/` and `runtime-build.json`; the full package is not put into Git.

## A7Z compatibility scope

- The root helper uses this Debian 11 machine's fixed tool paths and the standalone Python, and recognizes a `read_only` main controller with write protection.
- When the servo page takes over, it stops the main controller exclusively; after handing back, it restores the original read-only startup command, without launching the gamepad or enabling motion.
- In the current read-only phase, the helper rejects motion calibration submission, IMU mode reset, main controller updates and hold handover; manual calibration on the servo page is run only when the user explicitly clicks.
- Studio's sync read is split into groups of three, so that 15 replies at once do not fill the 64-byte UART FIFO. This is an adaptation of the web page's read path and does not replace robotd's 50 Hz acceptance check.
- The page shows the real read-only snapshot and receive freshness, and does not treat the startup torque reading as live torque. IMU ready is no longer shown as the mounting orientation being confirmed.
- No polling task is created for configd when it is not installed; when connected to a read-only main controller, the body mode reset notification is not sent automatically.

## Verification

- 119 existing bus helper and servo tests, 159 web gamepad tests, 6 A7Z compatibility regression tests and 4 state tests passed. The gamepad tests use a local simulated service and do not operate real hardware.
- On the real robot, Studio's real `ServoSession` was run, reading as radxa with the same supplementary groups as the service. The send path only allowed PING / READ / SYNC_READ; 225 read requests, all 15 servos online, all 15 torque readbacks 0, and 0 motor write commands. The test only closed the serial port, the helper handed back successfully, the main controller returned to `--read-only`, and padd / GameSir were not started.
- The overview and logs were checked in a real browser; screenshots at desktop 1440×900 and phone 390×844 are in the local `evidence/`. The page shows a read-only main controller and 15/15; IMU mounting orientation is not confirmed. No calibration, torque-on or motion was performed in the browser.
- The installation and fixes did not replace the robotd binary, rewrite the calibration file or change the main controller's startup mode. The handover verification stopped and started the read-only robotd normally once; at the end of verification the PID was 25987.

## Operating boundaries at the first installation

At this point the user can complete the hardware zero position calibration on the servo page. The packaged zero positions, directions and limits in the main program's `hd1910-calibration.toml` still need to be checked afterward; step three on the web page, “写进主程序” (write to main program), is not available in the read-only phase, so motion is not automatically enabled as a result.

The ID13 0x02 investigation has been paused at the user's request, and the raw evidence is kept in `control/evidence/id13-status-20261106-01.jsonl`: before pausing, 11310 independent sampling cycles were recorded, catching one valid frame where both the error byte and register 65 were 0x02. This is not a five-minute acceptance check, and the fault has not been declared fixed. Retest after the user calibrates.

## Checking the service

```sh
sudo systemctl status microduck-studio --no-pager
sudo journalctl -u microduck-studio -n 40 --no-pager
```

There is no need to restart the main controller to open the web page. After the servo page takes over, the bus should be released through the page's “交还主程序” (hand back to main program).

## Later IMU calibration and overview display fix

The user then explicitly asked to drop read-only mode and complete IMU calibration in the web console. The original binary was switched to `--commissioning`, and phase=ready, torque_state=off, policy_motion_enabled=false and valid IMU200 data were confirmed; the agent did not run HOME or enable the policy. The user then completed IMU calibration through the web page, submitted the calibration and enabled the standing pose; it is now in motion mode.

The mode switch ran into a leftover read-only override: after the web submission removed the commissioning override, `zz-cubie-readonly.conf` took effect again and made the submission fail. The read-only override has been moved into a backup on the board, and a new `zz-cubie-base.conf` provides the normal base startup command, with the commissioning override responsible only for temporary calibration. The fix did not restart the main controller or change the user's new calibration at the time. After the user submitted again, it entered normal mode and no longer returns to read_only.

The overview originally only handled `native.joints`, and the calibration snapshot was not fully wired in; the read-only adaptation also spread a single failed round into everything being stale, and motion mode would show one failed strict acquisition round as all devices offline. The display layer now uses recent readbacks with a time limit: a recent response is shown only if the native time plus the IPC receive age totals less than 500ms; when expired it shows “等待有效回读” (waiting for valid readback), and real sync read errors are reported separately. The original `feedback_fresh`, the main controller's sync read criteria and the motion safety logic are all unchanged.

11 A7Z adaptation regression tests and 43 related state/servo/startup diagnostic tests passed. The real web console overview on desktop and phone both show 15/15; screenshots are `evidence/feedback-fixed-desktop.jpg` and `evidence/feedback-fixed-mobile.jpg`. This only verifies display and interaction, and does not mean bus stability or walking has passed.

## Refresh interval fix for constantly flickering servo status

Follow-up fix on Nov 6, 2026: previously only the 500 ms validity period of the display readback was adjusted, but it was missed that motion mode's `robot.busStatus` was still polled every 1 second, so each time new data arrived it showed 15/15, and half a second later showed “等待有效回读” (waiting for valid readback) again. The first connection had the same 1-second gap.

Now all modes and the first connection query the main controller's cached status uniformly at 10 Hz, keeping the 500 ms expiry and RPC failure handling, without extra serial port operations and without changing the main controller's acquisition or motion criteria. The board's `studio/robotd.py` was updated precisely and only Studio was restarted; during deployment main controller PID9094 did not change, the policy was off, torque was confirmed off, and the calibration was not modified. The backup is `/opt/microduck-studio/before-feedback-poll-20261106T072136097847Z/robotd.py`.

14 adaptation tests and 78 backend/servo/startup state tests passed. The new regression test actually runs the polling scheduler, covering three modes, the first connection and expiry after readbacks stop. The original backend anti-busy-loop test was adjusted to the 10 Hz expectation and still asserts backoff for failed queries.

In the real browser on the real robot, before the fix, 35 of 60 samples were waiting for readback and 25 were 15/15; after the fix, all 200 samples each at 1440×900 and 390×844 were 15/15, with 0 waiting for readback. Screenshots and raw samples are saved in `evidence/feedback-poll-*-20261106.*`. This is a display-layer acceptance check and does not represent long-term bus stability or motion acceptance.

## Joint tracking debug entry (pending installation on the board)

The servo page adds “关节跟踪调试” (joint tracking debug). Once Studio has taken over the serial port, all joints are confirmed torque-off, and the operator has steadied the duck's torso on a stand with both feet off the ground and the range of motion cleared, select joints on the page, confirm support, and click “开始测试” (start test). The default is ±3°, with a slow ramp and 0.25/0.5 Hz sine waves; optionally, matching left/right joints can move in anti-phase. Basic tests can select several joints at once, and the program tests them one by one in order; when “临时调整 P/D” (temporarily adjust P/D) is checked, only one joint can be selected per round, and blank parameters keep their current values. First capture a baseline with the original parameters, then change only one parameter and retest the same motion. At the end, torque is turned off automatically and the original RAM P/D is restored. The page records target angle and position, speed, load, temperature, voltage, errors, and bus TX/RX data with timestamps, shows curves, per-phase errors and historical comparisons, and lets you download the raw `.jsonl` and the analysis `.json`. These are records of serial registers and control commands, not voltage waveforms on the servo wire.

The debugging measures **no-load tracking**; it can locate obvious lag, oscillation and bus anomalies, but cannot prove that a gait under load is stable. Problems like the feet stepping on each other still require rechecking the mechanical zero positions, assembly, power supply and actual walking logs. The program does not choose Kp/Kd automatically, does not write EEPROM or the calibration file, and does not change the robotd model. Pressing stop, e-stop, hand back, leaving the page or losing the page connection stops target writes and attempts to turn torque off and restore P/D; if the readback cannot confirm this, the page shows a failure, and torque and parameters must be checked on site.

The local source consists of `a7z-leg-tracking.patch`, `tracking/studio/leg_tracking.py`, `tracking/web/leg-tracking.js` and two analysis/probe modules in `control/diagnostics/`. The build script only accepts A7Z Studio source files whose hashes were reviewed in `tracking-baseline.json`, and outputs an update package of 8 files. The board-side install script previews by default; only with `--apply`, and only when the main controller policy is off, torque is confirmed off and Studio has not taken over the bus, does it back up and restart only Studio. It verifies that the main controller PID, binary and calibration file are unchanged, and automatically rolls back the Studio files on failure. The full package is still not put into Git.

```sh
python3 radxa-cubie-a7z/studio/prepare_tracking.py /path/to/clean-A7Z-studio-source radxa-cubie-a7z/studio/artifacts/leg-tracking-bundle
```

In an existing A7Z terminal login session, transfer the generated `.tar.gz` and `.sha256` to the board and verify them; after unpacking, run the preview first, then use `--apply` according to the on-site state. Do not skip the script's hash or torque checks.

```sh
sha256sum -c leg-tracking-bundle.tar.gz.sha256
mkdir -p /tmp/leg-tracking-bundle
tar -xzf leg-tracking-bundle.tar.gz -C /tmp/leg-tracking-bundle
python3 /tmp/leg-tracking-bundle/install_tracking.py /tmp/leg-tracking-bundle
sudo python3 /tmp/leg-tracking-bundle/install_tracking.py /tmp/leg-tracking-bundle --apply
```

The probe, analyzer, Studio protocol-level simulated servos and A7Z adaptation tests have passed locally; the desktop and narrow-screen pages can only be accepted against the local backend. **This debugging routine has not yet been installed on the board or run on the real robot.**
