# Studio's root helper: servo bus handover, writing calibration, gamepad pairing (install, uninstall, on-robot check)

**English** · [简体中文](INSTALL.md)

Written for humans, and also for any AI that takes over later: every step explains why.

## Redoing the initial IMU calibration (imu-recalibrate)

0.7.2 adds an optional `profile="legacy"|"qinmo"` to `enter` of the same fixed verb, so the IMU page can make a choice once and save it. The parameter does not accept commands, paths or services. It requires explicit capability evidence from the new robotd's `configured_imu_profile`; it does not gate everything by the API version number. Qinmo is marked as configured, supports Feetech, angular rate raw/16.4 °/s; existing boards are auto-detected by default, raw×0.0175 °/s. For the user flow see the [web usage guide](../../../docs/Qinmo-IMU-web-usage.en.md).

The profile transaction holds both the helper lock and `/run/microduck-service-management.lock`, refuses to compete with updates / the bus / an old redo, pauses the gamepad and the fixed duck-echo voice service, and restores the original service state after safely landing; the web console also refuses control actions during the session, while torque release and the necessary calibration operations remain available. It only operates on the fixed `--params /etc/robot/feetech-ft5/robotd.toml` and `--socket /run/robotd.sock` of an actual direct robotd ExecStart, the known service overrides, and that configuration's saved file and the known calibration files. At every level it refuses symlinks, non-root owners or directories / files writable by other users; it refuses read-only, foreign overrides, an I²C source, unsupported protocols and calibration paths. The main / saved configuration only changes `bus.imu_profile` and the compatible `bus.imu_protocol`; comparisons before and after parsing ensure the remaining values are kept, including the image's quoted keys and inline policy arrays. The raw bytes, owner / permissions, digest and mode are durably backed up first; the calibration only clears the bus mounting-orientation verified flag, to avoid reusing a historical orientation of the same profile.

Normal control uses the original gate of two fresh readings of torque disabled / no policy / gains restored. The supported pre-control startup recovery from `configuring_bus` / `waiting_for_bus` is based on the current daemon lifecycle and configuration capability; it does not falsely claim that physical torque is known to be off, and it always enters commissioning. The original factory commissioning can choose the profile, and the factory flow is kept after verification finishes. Cancelling a startup recovery first installs the known factory calibration mode, then removes its own redo mode file, restores the original configuration / calibration and ends the session; it stays in calibration mode and the profile can be chosen again, so no permanently blocking terminated session is left behind. Cancelling from normal control precisely restores the original configuration / calibration and mode.

Completion requires that the on-disk main / saved profile configuration still matches the written digest, that the running configuration and the actually discovered profile agree, and that the new orientation's protocol + profile binding and verified flag all read back consistently. On failure the original files are restored; if they cannot be restored, `recovery_required` and the original backup are kept, preserving a recoverable state. Ordinary commit, redo and cancel keep the optional `imu_bus_profile`, defaulting to legacy; a profile change invalidates pending sampling / computed / to-be-written results. Qinmo cannot be promoted to verified by "skip" or an ordinary write without verification by the main program. There is no physical acceptance check yet; this change does not update the public system image and does not deploy robotd automatically.

The new helper adds the fixed verb `imu-recalibrate`; stdin only accepts four actions, `enter/status/finish/cancel`, and cannot specify commands, paths or services. In motion mode, an existing `verified=true` and saved quaternion can also be re-verified: first hold the robot steady and release torque; `enter` reads the fresh state twice and requires `motion/control`, `policy_enabled=false`, no stand-up in progress, native torque explicitly false, no pending torque-release confirmation, and the HD1910 temporary gains restored. The gamepad service is stopped first, and then the gate is checked again; any ambiguous state is refused.

- Enter: `{"by":"Studio","action":"enter","confirmed":true}`. Keeps the actually effective direct robotd startup arguments and only adds `--commissioning`; wrapper commands or an ambiguous ExecStart are refused. It does not use or delete the factory `zzzz-zz-microduck-commissioning.conf`.
- Status: `{"by":"Studio","action":"status"}`. The session has `active/phase/session_id/source`; the web console reads the public read-only manifest and does not call sudo on every status push.
- Finish: `{"by":"Studio","action":"finish","session_id":"…","source":"bus","quat":[1,0,0,0]}`. Called only after the original `verify-imu` passes and the current source, verified flag, normalized quaternion and calibration file all read back consistently item by item. The original verifier sets `motion_enabled` to false; the helper only restores this value as it was before entering, and all other fields except the current chip's mounting orientation / verified must stay identical. It does not rebuild the whole calibration, and does not overwrite non-2048 zero positions, directions, limits, the other IMU or unknown settings with defaults. If the main program did not keep these fields, completion is refused and the session is kept so it can be cancelled and restored.
- Cancel: `{"by":"Studio","action":"cancel","confirmed":true,"session_id":"…"}`. The main calibration and the saved one are each restored from their original backups, and the original mode and gamepad service state are restored; this does not count as a successful new calibration.

The session is first persisted to `/var/lib/microduck-helper/imu-recalibrate/manifest.json` (root:root 0644); each separate `<session_id>/` backup directory is 0700, and the main calibration, the saved one and the parsed original calibration are each backed up and checked with SHA256. The parent directory is 0755, and operation records are still 0600. The session uses its own persistent mode file `/etc/systemd/system/robotd.service.d/zzzzzz-studio-imu-recalibrate.conf`, with the session ID and a content digest, and only a file exactly as written by this session may be deleted; restarting Studio / refreshing the web page restores the session, and the persistent mode file survives a power loss. A failure in the start phase restores the original state; a failure in the finish phase restores the verified safe calibration mode, after which the original verification can be redone or cancelled. The gamepad service is restored only when in motion mode, with the full calibration reading back consistently and torque disabled.

`imu-recalibrate` shares `helper.lock` with bus / calibration operations. While a session is active, `bus-take` and ordinary `calib-commit` are refused; web torque release is still available. Uninstall (including `--purge`) refuses when it finds an unfinished or unreadable session; finish or cancel it first, to avoid deleting the recovery backups. This flow keeps the original 3-second still / 3-second forward-tilt coarse calibration and the runtime verification of nodding down after standing upright; the factory calibration mode uses the original flow directly.

Plan source: scratchpad `console/handover-plan.md` (v2 final) §2.2, §4.2, §5; rules follow `console/studio-ops-plan.md` §7.

## 1. What it does

Studio's servo page needs to open the servo bus `/dev/ttyS2` itself, so the main program robotd has to stop first and be handed the bus back afterwards.

- Stopping and starting robotd requires root, and Studio is not root.
- So Studio is given only "a key that opens just this one door": sudoers only allows the single file `/usr/local/sbin/microduck-helper`.
- It only recognizes twelve fixed verbs, validates the parameters one by one, and reads robotd's state itself rather than trusting what the web page sends (since 0.5.0: added `calib-read`, and `calib-commit` recognizes calibration / motion mode by how the fork actually starts; 0.5.2: `bus-give-back` also counts a live snapshot in calibration mode as "the main program is up"; 0.6.0: added `ssh-status` / `ssh-password`, the SSH switch on the "More" page; 0.7.0: added `imu-recalibrate`, which durably saves the session for redoing the initial IMU calibration).

**busStatus in calibration mode** (`robot.busStatus` in the fork's `robotd/src/main.rs`, `Status` in `feetech_commissioning.rs`): as soon as robotd starts, it first writes a startup report `{"build","mode":"commissioning","phase":"configuring_bus","port"}`, and keeps returning it while the phase is still the startup phase; only after the first successful read does it return a live snapshot (phase `ready` / `moving` / `read_error` / `stop_unconfirmed` / `power_pending`, with `last_sample`). Old forks never clear the startup report: when handing back from the servo page, the helper waits the full 30 seconds and judges `soft_failed` (`detail.still_starting = true`; the message says “一直报启动中” (keeps reporting starting up), not “起不来” (fails to start)). A new fork (images after 20261020) is required.

**The factory image runs calibration mode**: the image places `/etc/systemd/system/robotd.service.d/zzzz-zz-microduck-commissioning.conf`, whose `ExecStart` has `--commissioning` (fork `main.rs:1300-1315`: the mode in busStatus depends only on the startup arguments, not on what is written in the calibration file). In calibration mode `calibration-status` can be read immediately, busStatus has `last_sample` (15 servos + `imu`), and `verify-imu` writes the orientation into the calibration file; in motion mode, if the calibration is invalid / the servo bus cannot be opened, it stops at `waiting_for_bus`, and `calibration-status` returns `calibration not available yet`. When step 3 writes successfully, the helper deletes this file, runs `daemon-reload` and restarts robotd, and the main program returns to motion mode. If `ExecStart` has `--commissioning` but the file is not there, the helper refuses to switch automatically (`foreign_commissioning`) and has a person go to the log page to export a diagnostics bundle.

## In the image vs. manual install

The “连 WiFi” (Connect WiFi) card is not something Studio can provide on its own; it depends on four things in the replica image:

- `/run/microduck/net.json` written by netcheck;
- the `Microduck-Hotspot` hotspot configuration in NetworkManager;
- configd running with `--allow-user btd,radxa`;
- the mDNS configuration (`duck-xxxx.local`).

A duck on which Studio and the root helper were installed manually according to this document, but without the replica image overlay, has none of these, so Studio does not show the “连 WiFi” (Connect WiFi) card; the overview, gamepad, servos, IMU, logs and setting a web password all work as usual.
The web password is set under “更多 → 登录密码” (More → Login password); the command line `python3 -I run.py set-password` must be run as the radxa user, not with `sudo`, otherwise Studio cannot read the password file.

| Verb | stdin (one JSON object) | What it does |
|---|---|---|
| `bus-take` | `{"by": "who·which computer", "allow_seated": false}` | Takes over, **without releasing torque**: first stops the gamepad service → reads the main program's state twice, 200 ms apart (refuses if a policy is running; a sitting pose is only allowed with `allow_seated` and when not moving; if it is returning to the standing pose, waits up to 3 seconds) → raises the flag → `systemctl stop --no-block robotd`, KILL if it has not stopped within 10 seconds → confirms nobody holds the serial port |
| `bus-give-back` | `{"by": …, "soft": true}` | Soft hand-back: Studio has already released all torque on the bus. Lowers the flag → starts robotd → waits until all 4 startup steps succeed and the main program is up (motion mode `phase=control`, or a live snapshot in calibration mode `ready` / `moving` / `read_error` / `stop_unconfirmed` / `power_pending`; `read_error` still counts as success, with the original message written into reason) → brings the gamepad service back → releases the lock. If it still reports the startup phase after 30 seconds: `soft_failed`, `detail.still_starting = true` |
| | `{"by": …, "marker": {…}}` | Hand-back without releasing torque: writes the handover marker → lowers the flag (**keeps the lock**) → starts robotd → waits for robotd to take over (takes over holding, without starting the model). If it does not take over, the bus is taken back and given to Studio to continue holding. Calibration mode does not recognize the marker (opening the bus releases all torque first): as soon as a live snapshot arrives it returns `limp`, instead of waiting 15 seconds and then taking the bus back |
| `bus-abort` | `{"by": …}` | Aborts the handover (web torque release was pressed during the handover countdown): raises the flag → KILLs robotd → deletes the marker → confirms the serial port is free. Target within 1 second, after which Studio opens the serial port itself and releases torque. **Refuses when there is no session (exit 3)**: if neither the flag, the management lock nor the handover marker is present, it touches nothing |
| `pad-pair` | `{"by": …, "mac": optional, "timeout": 10–120 (default 60)}` | Runs the official `/usr/local/bin/robotctl pad pair --json --timeout N [MAC]` as root. The MAC is uppercased first and then validated. Total subprocess timeout = `timeout + 30` seconds (killed on timeout). On boards with `/var/lib/robot/weird-ble`, robotctl first stops btd, power-cycles the adapter, and finally brings btd back up. **Does not touch** the bus flag, the hold unit or robotd, and does not take the service management lock; only takes `helper.lock`, so only one pairing runs at a time |
| `pad-forget` | `{"by": …, "mac": …}` | Runs the official `/usr/local/bin/robotctl pad forget MAC` as root (MAC required, validated as above). Likewise does not touch the bus, the hold unit or robotd |
| `wifi-hotspot-down` | `{"by": …, "ssid": optional}` | **Before** turning off the hotspot, writes `/run/microduck/studio-connecting.json` (root 0644, `until` = now + 90 seconds, with the target SSID; written to a temp file first and then renamed, directory 0755), so netcheck does not intervene during this period. Then `nmcli connection down Microduck-Hotspot` (command timeout 15 seconds). If the hotspot was not on to begin with, it counts as success (nmcli saying "not an active connection" also counts as success); waits up to 10 seconds until wlan0 is no longer on this connection. **Does not touch** the bus flag, the hold unit or robotd, and does not take `helper.lock`; uses `wifi.lock` |
| `wifi-hotspot-up` | `{"by": …}` | `nmcli connection up Microduck-Hotspot`. If it is already on, it counts as success; waits up to 30 seconds from up until wlan0 is really on this connection. After it is up, deletes `/run/microduck/studio-connecting.json` (the file not existing is not an error). Likewise does not touch the servo bus; uses `wifi.lock` |
| `calib-read` | `{"by": …}` (optional) | Only reads the current calibration file: returns the parsed `calibration`, which mode it is in now (`commissioning` / `motion` / `foreign`), whether the commissioning drop-in exists, and whether `ExecStart` has `--commissioning`. **Does not take `helper.lock` and writes no files**; it is the fallback for Studio when motion mode is stuck at `waiting_for_bus` and `calibration-status` cannot be read. |
| `calib-commit` | `{"by": …, "joints": [{"id", "direction"} × 15], "imu": {"source": "bus\|bno08x\|lsm6dsv16x", "quat": [w,x,y,z]}, "dry_run": false}` | Writes the servo zero positions (2048), directions and IMU mounting orientation into robotd's `hd1910-calibration.toml`. Order: **first take `helper.lock`, then check the bus-held flag**; calibration mode skips the posture gate, motion mode reads busStatus twice 200 ms apart (refuses with exit 3 if a policy is running / it is standing); mode detection: the image's `zzzz-zz-microduck-commissioning.conf` present = calibration mode (deleted after writing, `daemon-reload` switches to motion mode), absent and `ExecStart` without `--commissioning` = motion mode (only the calibration is replaced), `ExecStart` has it but the file is absent = `foreign_commissioning` (does not dare to switch automatically, exit 3). Reads the current file, builds the new content with the standard limits, and validates each entry (same as the fork's `Calibration::validate`). Each write produces a set `calib-backups/<4-digit sequence>-<UTC>/` (main file, `.saved.toml`, commissioning file, `manifest.json`; the sequence number is the existing maximum +1, 10 sets kept); `.previous`, `.toml` and `.saved.toml` are all written to a temp file first, fsynced and renamed, keeping the original owner and permissions; after writing, they are read back and validated item by item. From the first write onward, any exception rolls back first and then reports the error. After restarting robotd, waits up to 40 seconds for hello; then reads `robot.busStatus` every 0.5 seconds for up to 30 seconds: **success = `mode=="motion"` and `phase=="control"`, and the 15 servos read back by `calibration-status` (name / id / zero_raw / direction / calibrated / min_rad / max_rad), `motion_enabled`, the bus board's `imu_mount_quat` / `imu_mount_verified`, and the quat / verified of every slot of `imu_mounts` match what was written (floating point 1e-9)**. On failure, returns by cause `calib_rejected` (the calibration did not pass the main program's checks) or `bus_unavailable` (the main program cannot open the servo bus; check the servo power first), and rolls back. The whole non-dry_run sequence runs in a separate unit via `systemd-run`, with the result written to `last-result.json`; `dry_run: true` stops after validation and only returns the full text in `detail.toml`, without writing files or restarting. |
| `ssh-status` | `{"by": …}` (optional) | Read-only: whether SSH password login is on (checks whether `05-microduck-ssh-password.conf` exists), whether the `ssh` service is running, and how many keys are registered in radxa's `authorized_keys`. Takes no lock and writes no files (it does not overwrite `last-result.json` either). |
| `ssh-password` | `{"by": …, "on": true, "password": "…"}` / `{"by": …, "on": false}` | On: the password must be 8–64 visible characters and must not be something anyone can guess, such as `microduck` (otherwise returns `bad_password`, exit 2); takes `ssh.lock`, `chpasswd` sets radxa's password from stdin, writes `/etc/ssh/sshd_config.d/05-microduck-ssh-password.conf` (`PasswordAuthentication yes`), and only runs `systemctl reload-or-restart ssh` after `sshd -t` passes and `sshd -T` reads back `passwordauthentication yes`; if any step fails, it deletes this file and reverts (`sshd_config_bad` / `not_effective` / `reload_failed`). Off: deletes the file and reloads; radxa's password is not changed (sudo still uses it). **The password is only in stdin; it never goes into the command line, the journal, `last-result.json` or the oplog.** |

**Output**: one JSON per line: `{"step", "level", "ms", "msg", "detail"}`; the last line has `step="done"`, and `detail` contains `exit` and `result`. The same result is written to `/run/microduck-helper/last-result.json` (0644), which Studio reads after a restart.

The `detail` of `pad-pair` also has: `pair` (robotctl's stdout, parsed as `PadPairResult`: `{"outcome":"paired","pad":{…}}` or `{"outcome":"failed","reason":"not_found|ambiguous|timeout|no_adapter|rejected|other","detail":…}`), `stderr` (a few lines of notices from robotctl, such as `paused btd …`, `warning: …`) and `stdout`. Exits 0 when paired; exits 5 when robotctl reports failure, with `detail.reason` keeping the official reason. The `detail` of `pad-forget` has `removed` (true / false / null), `stdout` and `stderr`.

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Bad arguments (unknown verb, stdin is not a JSON object, unknown keys, marker validation failed) |
| 3 | State does not allow it (guard not installed, a policy is running, the duck is standing / walking, no session, not root; for `calib-commit` it can also be bus-held or `foreign_commissioning`) |
| 4 | Busy or aborted (the management lock is held by a board-side script, the helper is running another bus operation / another pairing or forget, another WiFi hotspot operation, the hand-back was aborted) |
| 5 | Execution failed (could not stop, serial port occupied, robotd did not recognize the marker and already released all torque, soft hand-back could not start; or `pad-pair` / `pad-forget` cannot find robotctl, robotctl reports pairing failed, killed on timeout; turning the hotspot off / on failed, nmcli error, wait timed out; `calib-commit` write failed / restart failed / the main program did not enter motion mode / readback mismatch, already rolled back) |
| 6 | Handover failed, bus already taken back (flag raised again, robotd stopped, lock still held); Studio reopens the serial port and continues holding |

Values of `result`:

- bus-take: `taken`, `refused`, `no_guard`, `busy`, `stop_failed`, `port_busy`
- bus-give-back: `adopted`, `retake`, `retake_failed`, `limp` (motion mode did not recognize the marker, or calibration mode), `aborted`, `soft`, `soft_failed` (when the main program keeps reporting the startup phase, `detail.still_starting = true` and `detail.msg` is the full sentence), `refused`, `no_session`, `detach_failed`
- bus-abort: `aborted`, `abort_incomplete`, `no_session` (refused when there is no session, exit 3)
- pad-pair: `paired`, `pair_failed` (exit 5, `detail.reason` is the official reason), `timeout`, `no_robotctl`, `bad_output`
- pad-forget: `forgotten`, `forget_failed`, `timeout`, `no_robotctl`
- wifi-hotspot-down: `hotspot_down`, `already_down`, `down_failed`, `timeout`, `nmcli_failed`
- wifi-hotspot-up: `hotspot_up`, `already_up`, `up_failed`, `timeout`, `nmcli_failed`
- calib-read: `read`. `detail` has `calibration`, `mode` (`commissioning` / `motion` / `foreign`), `commissioning_present`, `exec_has_commissioning`, `mode_text`; takes no lock and writes no files
- calib-commit: `preview` (dry_run), `committed` (`mode=motion` and `phase=control`, and the `calibration-status` readback matches item by item), `not_motion` (still not in motion mode after 30 seconds), `calib_rejected` (the main program says the calibration did not pass its checks), `bus_unavailable` (the main program cannot open the servo bus), `readback_mismatch` (entered motion mode but the readback does not match), `bus_held`, `no_calibration`, `bad_calibration`, `joint_mismatch`, `invalid`, `bad_toml`, `restart_failed`, `write_failed`, `backup_failed`, `read_failed`, `foreign_commissioning`, `refused` (a policy is running / it is standing). In failure results, `detail.rolled_back` / `files_restored` / `mode_restored` / `robotd_up_after_rollback` are reported separately; `readback_ok`, `mismatches`, `bus_status` (the last mode / phase / error) and `backup` are also present. If the rollback itself did not fully succeed, `msg` will say “去日志页导出诊断包” (go to the log page and export a diagnostics bundle)
- Possible for all: `bad_args`, `bad_marker`, `bad_verb`, `not_root`, `busy`, `error`

## 2. Files and paths

| Thing | Location | Why |
|---|---|---|
| Helper | `/usr/local/sbin/microduck-helper` (root:root 0755, `#!/usr/bin/python3 -IS`) | `-I` does not read the user's environment and directories, `-S` does not load site. Linux treats everything after the shebang as a single argument, so it is written as `-IS`, not `-I -S` |
| robotd drop-in | `/etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf` | `ConditionPathExists=!/run/microduck-helper/bus-held`: while the flag exists, robotd cannot start. **Do not use `systemctl mask --runtime`**: robotd's unit file lives in /etc, and a mask in /run cannot override it |
| sudoers | `/etc/sudoers.d/microduck-studio` (0440) | Allows only one full path. `visudo -cf` before installing |
| Flag | `/run/microduck-helper/bus-held` (directory 0755, file 0644) | On a RAM disk: gone after power loss or reboot, and robotd starts at boot as usual. It is not placed in Studio's directory because if Studio's unit later uses `RuntimeDirectory`, systemd will delete that directory when Studio restarts. **Studio's unit must not use `RuntimeDirectory=microduck-helper`** |
| Abort request | `/run/microduck-helper/abort` | Written by bus-abort; a running bus-give-back stops when it sees it |
| Helper's own lock | `/run/microduck-helper/helper.lock` (flock) | bus-take, bus-give-back, calib-commit, imu-recalibrate, pad-pair and pad-forget run one at a time (the servo page cannot take over the bus while calibration is being written / the main program is restarting, and only one pairing is allowed at a time). **bus-abort does not take it**: torque release must not be blocked by a running hand-back, and each of its steps can be repeated |
| Hotspot lock | `/run/microduck-helper/wifi.lock` (flock) | `wifi-hotspot-down` / `wifi-hotspot-up` run one at a time; separate from the servo bus's `helper.lock`, so they do not block each other |
| Official robotctl | `/usr/local/bin/robotctl` (hardcoded in `deploy/microduck-helper`) | Only `pad-pair` / `pad-forget` call it. If it does not exist, returns `no_robotctl` (exit 5); it does not search other paths |
| Management lock | `/run/microduck-service-management.lock`, held continuously by the transient unit `microduck-bus-hold` (`flock -n … sleep infinity`) | The board's `service.sh` does not touch robotd if it cannot get this lock |
| Handover marker | `/run/microduck-handover/handover.json` (directory 0700, file 0600; temp file in the same directory + fsync + rename) | Only root reads and writes it; robotd deletes it after reading |
| Operation log | `/var/lib/microduck-helper/oplog.jsonl` (parent directory 0755, log file 0600; private backup subdirectories 0700) | One line per operation: who, when, result. The parent directory lets Studio read the public IMU session state; logs and backups are still readable only by root |
| Calibration backups | `/var/lib/microduck-helper/calib-backups/<4-digit sequence>-<UTC>/` (directory 0700, files 0600, only the latest 10 sets kept) | Each set has the pre-write `.toml`, `.saved.toml` (each backed up separately), the commissioning drop-in (if present) and `manifest.json` (original owner, permissions, sha256). The sequence number is the existing maximum directory +1, not ordered by wall clock; rollback restores each file according to the manifest |

**Marker format** (the fork's robotd reads it this way):

```
{"schema": "microduck-handover/1", "requested_by": str, "boot_id": str, "mono_ms": int,
 "ttl_ms": int, "port": "/dev/ttyS2", "arm_registers": {"limit", "p", "d"} (optional),
 "joints": [{"id", "torque", "goal", "present", "offset", "load"?, "temp"?, "status"?} × 15]}
```

- `boot_id` and `mono_ms` (CLOCK_MONOTONIC milliseconds) are **filled in by the helper itself**; if Studio provides them, they are overwritten.
- **A ttl_ms over 30000 is rejected outright (exit code 2), not silently truncated**; below 1000 is also rejected; default 20000. The robotd side also accepts at most 30 seconds, so both sides agree.
- The ids must be exactly 10–14, 20–24, 30–34, each once; torque must be 1 (the main program only takes over when all 15 are enabled); goal, present and offset are integers in −32767..32767.

**Timings**:

| Timing | Value |
|---|---|
| Interval between the two gate reads | 0.2 s |
| Waiting for return to standing pose | 3 s |
| stop to KILL | 10 s |
| Further wait after KILL | 3 s |
| robotd reading the marker | 15 s |
| Completing startup step 4 after takeover | 20 s |
| Soft hand-back | 30 s |
| Aborting the handover | wait 0.5 s after KILL |
| Waiting for robotd after writing calibration | 40 s (unit active + hello on `/run/robotd.sock`) |
| Waiting for motion mode | 30 s (reads busStatus every 0.5 s; success also requires the calibration-status readback to match item by item) |
| Studio waiting for the helper | 180 s (on timeout it still reads `last-result.json` instead of directly reporting TimeoutExpired) |

**Environment variables**: `MICRODUCK_HELPER_DETACHED`, `MICRODUCK_HELPER_REQUEST`, `MICRODUCK_HELPER_REQUESTED_MS` (used by both `bus-give-back` and `calib-commit`).

- Purpose: when bus-give-back / non-dry_run calib-commit is first called, it uses `systemd-run --wait --pipe --collect --quiet --unit=microduck-handover-<time>-<pid>` to put itself into a separate transient unit and run again, passing stdin through unchanged and passing the output back unchanged. That way, even if Studio dies, the hand-back is not cut off halfway.
- These variables **only** decide "do not re-launch again" and how abort requests and results are matched up; **they grant no permissions**. sudo uses env_reset by default, so the caller cannot pass them in either.
- **No environment variable can change the root directory**: tests import the module and swap in a fake Ctx, without relying on environment variables.

**Everywhere that decides whether robotd is up** looks at `systemctl show robotd -p ActiveState,SubState,Result,ConditionResult`. While the flag exists, `systemctl start robotd` returns 0, but the unit stays inactive with `ConditionResult=no`, which must not be treated as up. Before every robotd start, `reset-failed` is run first, to avoid hitting start-limit-hit.

**Trust boundary**: a user who can sudo the helper (currently radxa) can already open ttyS2 directly; and robotd reads back from the bus to check the marker. So a forged marker grants no extra permissions; at worst it "holds servos that were already holding".

## 3. Installation (once, over SSH)

```sh
# On the computer: copy the deploy directory to the duck
scp -r deploy radxa@duck:/tmp/studio-deploy
# On the duck
cd /tmp/studio-deploy && sudo sh install.sh radxa
```

`install.sh` does four things:

1. Installs the helper into `/usr/local/sbin` (0755); warns if `/usr`, `/usr/local` or `/usr/local/sbin` are not owned by root, or are writable by group / others;
2. Installs the drop-in, then runs `systemctl daemon-reload`. **Does not restart robotd**;
3. Generates the sudoers line and installs it (0440) only after `visudo -cf` passes;
4. Prints check information.

**Step 1 only installs the `[Unit]` section of the drop-in.** `[Service] Environment=MICRODUCK_HANDOVER_MARKER=…` is commented out: after the fork's robotd is installed and step 3 (Studio hand-back without releasing torque) passes its acceptance check, manually uncomment those two lines and run `daemon-reload`. Once enabled, robotd will look at the handover marker the next time it starts; without a marker it behaves exactly like V167. Older robotd does not recognize this variable, so enabling it has no effect there.

Check right after installing:

```sh
systemctl show robotd -p DropInPaths            # Must include zzzz-studio-bus.conf
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-nope; echo $?   # As radxa: should be 2
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-take;  echo $?  # Should be 2: missing by (nothing touched)
echo '{}' | sudo -n /usr/local/sbin/microduck-helper pad-pair;  echo $?  # Should be 2: missing by (robotctl not run)
echo '{}' | sudo -n /usr/local/sbin/microduck-helper wifi-hotspot-down; echo $?  # Should be 2: missing by (nmcli not touched)
echo '{}' | sudo -n /usr/local/sbin/microduck-helper wifi-hotspot-up;   echo $?  # Should be 2: missing by (nmcli not touched)
echo '{}' | sudo -n /usr/local/sbin/microduck-helper calib-read;       echo $?  # Should be 0: reads file + mode (no lock, no writes)
echo '{}' | sudo -n /usr/local/sbin/microduck-helper calib-commit;   echo $?  # Should be 2: missing by (calibration not read or written)
ls -l /usr/local/bin/robotctl                                        # Official 0.15.1 or newer
stat -c '%U:%G %a %n' /usr /usr/local /usr/local/sbin /usr/local/sbin/microduck-helper
sudo -l -U radxa | grep microduck-helper
```

## 4. Uninstall

```sh
sudo sh uninstall.sh            # Refused while the flag exists (Studio is holding the bus)
sudo sh uninstall.sh --purge    # Also deletes /var/lib/microduck-helper
```

Uninstall deletes the sudoers line, the drop-in (then runs daemon-reload) and the helper, stops `microduck-bus-hold`, and clears `/run/microduck-helper` and `/run/microduck-handover`. robotd is not restarted.

## 5. What to look at when something goes wrong

- `sudo ls -l /run/microduck-helper/`: `bus-held` present = the main program is being blocked by Studio, and its failure to start is intentional. To release it: hand the bus back in Studio, or reboot.
- `cat /run/microduck-helper/last-result.json`: what was done last time and which step it got stuck on (`steps` is the last 30 lines of progress).
- `journalctl -t microduck-helper -b`: every progress line is written here.
- `systemctl status microduck-bus-hold`: whether the management lock is held by Studio.
- `sudo tail /var/lib/microduck-helper/oplog.jsonl`: the operation log.

## 6. On-robot check list (duck no. 2, with the user holding it; once he says start, run straight through without asking each time)

**Read-only checks first** (touch nothing):

- `systemctl --version` (257), `sudo -V | grep -i -E 'env_reset|secure_path'`, `ls -l /etc/sudoers.d`.
- **The systemd-run behaviors**:
  - `systemd-run --wait --pipe --collect --quiet -p … /bin/sh -c 'exit 6'; echo $?`: whether `--wait` passes the service's exit code back. The helper does not rely on this; it first matches the request_id in last-result, and only uses systemd-run's exit code if they do not match;
  - with `--pipe`, if the caller is killed, a process inside the service writing to stdout gets EPIPE (the helper ignores SIGPIPE) rather than being killed along with it;
  - transient units default to `KillMode=control-group`, so `systemctl stop microduck-bus-hold` stops flock and sleep together and the lock is released with them. Check with `flock -n /run/microduck-service-management.lock true; echo $?`.

**Step 1 on-robot tests (those related to the helper)**:

| No. | What to do | What to look for |
|---|---|---|
| U1 | `bus-take` with torque released | Exit code 0; flag present; robotd inactive; Studio opens the serial port and reads register 40 as all 0, positions unchanged |
| U2 | `bus-take` while holding the standing pose (after init) | 0; Studio reads register 40 as all 1, position difference <1°, the duck does not sink |
| U3 | `bus-take` with the policy on (gamepad Start enters holding) | 3, with the reason “先按手柄 Start…” (Press gamepad Start first…); padd is back; robotd was not stopped. After pressing Start for 2 seconds to return to the standing pose, take again → 0, no going limp |
| U4 | `sudo systemctl start robotd` while the flag exists | Exit code 0, but `systemctl show robotd -p ActiveState,ConditionResult` is inactive / no; the board's `service.sh status` (path as actually on the board) is refused by the lock: “已有服务管理操作正在执行” (A service management operation is already in progress) |
| U4b | Automatic restart after KILL while the flag exists | **Do not do this with robotd while the user is holding the bus.** First verify with a fake unit: create a transient service with the same Condition, start it, raise the flag, `systemctl kill -s KILL`, and see whether it is restarted after 2 seconds. Once the user is free, do it once more on robotd |
| U4c | `systemctl start robotd` 6 times in a row while the flag exists | See whether `Result` becomes start-limit-hit. Then lower the flag (`bus-give-back {"soft":true}` runs reset-failed first) and confirm it can start |
| U5 | `systemctl restart studio-trial` during a session | The duck does not go limp; the flag and `microduck-bus-hold` are still there; after Studio comes up, `bus-take` returns 0, with `session_was_open=true` in detail |
| U6 | Soft hand-back | Hold the duck; `bus-give-back {"soft":true}` returns 0; robotd's four steps succeed; padd is back; `microduck-bus-hold` has stopped |
| U7 | Leaving the servo page | No hand-back while holding (part of another subagent's work, verified together) |
| V0 (helper part) | Measure how long `bus-take` and `bus-abort` each take | Look at `ms` in last-result; abort target ≤1 second |
| U8 | Pair a gamepad once in Studio (Thunderobot G50 Pro, Switch Pro mode, name `Pro Controller`) | In the wizard, “配对走的是” (Pairing goes through) shows the helper; in `cat /run/microduck-helper/last-result.json`, `verb=pad-pair`, `result=paired`, and `detail.stderr` has `paused btd …`; within 30 seconds padd recognizes it and enters the button test. Without the new helper, the wizard prompts to reinstall first |
| U9 | `wifi-hotspot-down {"by":"核对","ssid":"Home"}` while the hotspot is on | Exit 0, `result=hotspot_down`; before turning it off, `/run/microduck/studio-connecting.json` already exists (root 0644, `until` about 90 seconds later, `ssid=Home`); `Microduck-Hotspot` is not in `nmcli connection show --active`; the phone's hotspot connection drops. Call again with the hotspot already off → 0, `already_down`, and no connection window is written |
| U10 | `wifi-hotspot-up {"by":"核对"}` while the hotspot is off | Exit 0, `result=hotspot_up`; `Microduck-Hotspot` (wlan0) is in `nmcli connection show --active`; the phone can find the hotspot; `studio-connecting.json` has been deleted. Call again → 0, `already_up`, and the file not existing is not an error |
| U11 | Preview only first: `calib-commit {…, "dry_run": true}` (joints / imu the same as in Studio's preview) | Exit 0, `result=preview`; in `detail.toml` the 15 servos have `calibrated = true`, `motion_enabled = true`, and limits and quaternion are present; `detail.mode` is `commissioning` (factory) or `motion`; the sha256 and mtime of `hd1910-calibration.toml` are unchanged, and robotd was not restarted |
| U12 | Real write (hold the duck steady): same as above with `dry_run: false` | Exit 0, `result=committed`; `detail.mode_before=commissioning`, `detail.bus_status.mode=motion`, `phase=control`, `readback_ok=true`, `mismatches=[]`; `zzzz-zz-microduck-commissioning.conf` is gone and `daemon-reload` has run; `.saved.toml` is identical to the main file and `.previous.toml` is the pre-write version; `calib-backups/` has one more set (all three files in the manifest); `systemctl show robotd -p ActiveState` is active; step 3 of Studio's checklist becomes complete and the top bar shows motion mode |
| U12b | Rollback (calibration rejected): change the IMU in use to not verified (or a mismatched source), and run U12 again | Exit 5, `result=calib_rejected`; `reason` is “标定没通过主程序的检查：motion requires all 15 calibrated joints…” (Calibration did not pass the main program's checks: …); `detail.bus_status` is `mode=motion`, `phase=waiting_for_bus`; `detail.files_restored` / `mode_restored` / `robotd_up_after_rollback` are all true, and `detail.rolled_back` is also true; the main file and `.saved.toml` are the same as before U12, the commissioning file has been put back, and robotd started once more (back in calibration mode) |
| U12c | Rollback (servos not powered): turn off servo power and run U12 again | Exit 5, `result=bus_unavailable`; `reason` is “主程序打不开舵机总线：torque readback…。舵机电源开了吗？” (The main program cannot open the servo bus: torque readback…. Is the servo power on?); `detail.bus_status.phase=waiting_for_bus`; files and mode are both restored |
| U12d | Rollback (readback mismatch): temporarily change one servo's `zero_raw` in the fake main program / test stub's calibration-status, and run U12 again | Exit 5, `result=readback_mismatch`, `detail.readback_ok=false`, `detail.mismatches` states which item; files and mode are both restored |
| U13 | Rollback: temporarily make robotd unable to start (create `robotd.service.d/zzzz-e2e-fail.conf` containing `[Unit]` + `ConditionPathExists=/nonexistent-e2e`, `daemon-reload`), and run U12 again | Exit 5, `result=restart_failed`, `detail.files_restored=true`, `detail.robotd_up_after_rollback=false` (it is only true after really waiting for hello); the main file and `.saved.toml` are the same as before U12; `detail.journal` has robotd's last 30 lines; `reason` includes “去日志页导出诊断包” (go to the log page and export a diagnostics bundle). After checking, delete that drop-in, run `daemon-reload` and `systemctl start robotd` |

**Not yet covered**: marker hand-back (`{"marker": …}`) can only be tested on the board after the fork's robotd is installed and the drop-in's Environment is enabled; that is V1–V12 of step 4.

## 7. Known limitations

- bus-take has a window of about 0.1 seconds between "finishing the state check" and "raising the flag and stopping robotd", during which the Bluetooth app can still turn the policy on. padd and gamesir have already been stopped first, but btd has not.
- configd's `system.reboot` and a direct `poweroff` over SSH cannot be intercepted (plan §2.5). On a reboot, robotd releases all torque when it comes up, per the old rule.
- During the handover countdown the gamepad's Select has no effect (padd only starts after all four robotd steps succeed); during those few seconds use web torque release (which goes through bus-abort) or cut the power.
- An old helper (that does not recognize `pad-pair`) returns `bad_verb`; Studio treats that as having no new helper and falls back to configd → bluetoothctl. On this board (`/var/lib/robot/weird-ble`) the fallback path may fail to pair, and the wizard will prompt to reinstall the helper or run `sudo robotctl pad pair` on the duck.
- An old helper (0.2.0, which does not recognize `wifi-hotspot-down` / `wifi-hotspot-up`) also returns `bad_verb`; when configuring the network, Studio will prompt “小助手太旧，重装 deploy/install.sh” (Helper too old, reinstall deploy/install.sh).
