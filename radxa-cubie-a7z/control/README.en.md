# Cubie A7Z control adaptation

**English** · [简体中文](README.md)

2026-11-06: the original program was `97d981c2…`, commissioning; the user has manually installed
`1e465420…` / `a7z-sync3.1-readonly`. **It once passed a five-minute stability window, but failures still occurred afterward; this is not reliably solved yet. The user later explicitly asked to drop read-only mode to do IMU calibration, and submitted it through the web console themselves to enter motion mode; a mode switch does not mean the bus or walking acceptance check has passed.** The readonly in the build name is a historical label; the actual mode is determined by the startup arguments and busStatus.
The original runtime source is in the neighboring local project `10fanhao_duck/runtime/`, not the original provisioning program of this repo.

## Current evidence

- 30-second baseline of the original program: 1 failure in 1514 reads, with UART overrun also increasing by 1.
- Tuning the governor, moving the IRQ, lowering the RX FIFO threshold and limiting wake-up latency all failed to meet the continuous stability requirement; the temporary settings have been reverted.
- Grouped read-only probe: at most 3 devices per group, replies of at most 63 bytes, IMU 200 last, all groups sharing 20 ms.
- One minute: 3000/3000 successful, 49.9997 Hz, slowest 8.97 ms, UART error increment 0.
- Five minutes: 2 out of 14998 exceeded 20 ms (slowest 20.48 ms), UART error increment still 0; **this run does not count as a pass**.
- The above are results of a standalone probe at rest, not the final acceptance of the new robotd, let alone verification of standing, walking or forward rolls.
- With the formal read-only program installed by the user, five minutes of monitoring had 788 failures out of 15000 reads; the missing IDs were concentrated on 32 and 33 in the third group `[31,32,33]`, with a UART error increment of 0.
- A later new window then had 398 failures out of 1502 reads. So "zero UART overruns" cannot be taken as the fix being complete, nor can it be concluded from this that 32 and 33 are damaged.
- ID32 and ID33 tested on their own: PING 100/100 and READ 56/15 100/100 each, no checksum errors; torque was 0 for both before and after the test, and the original read-only process was restored at the end.
- A later standalone C probe compared 9 variants of third-group order, inter-group gaps of 0/100/300/1000 microseconds and group position, 300 cycles each; all 2700 cycles succeeded. This does not show that adding a gap is the fix, because the control with no extra gap also passed.
- A standalone probe using the same Rust Bus ran 600 cycles each of blocking and non-blocking reads, all successful. The original read-only service was then started normally; the binary was not replaced and its configuration was not changed.
- Full window after restarting the original read-only service: 300.001 seconds, all 15000 reads successful, 49.9998 Hz, all device timeout/missing and UART error increments 0, `passed = true`. Session `6141-1793936800693682651`, raw record `/var/lib/robot/cubie-native-after-io-probe-20261106.jsonl`, local result `evidence/stable-window-after-restart-20261106.json`. The earlier error counts were not reset or hidden; what passed is this new window, which does not mean the root cause has been fixed or motion has been verified.
- The user asked for another retest: same sync3.1/PID6141/group 3/read-only configuration, no restart. 15000 reads in 300.002 seconds, 14999 successful, 1 failure, 49.9996 Hz, `passed = false`. This time ID13 returned status error `0x02`; it was not a complete lack of reply. Receive checksum and UART error increments were 0, and 32/33 had no new timeouts. Raw record `/var/lib/robot/cubie-sync31-retest-20261106-01.jsonl`, local record `evidence/sync31-retest-20261106-01.jsonl` and the corresponding `.summary.json`. The meaning of the error bit has not yet been confirmed against the corresponding HD-1910 manual, so the servo is not considered damaged on this basis.
- After calibrating in Studio and handing the robot back, the user again asked for a five-minute retest: sync3.1, group 3, read-only, PID4411, same session without restart. 300.004530 seconds / 15000 cycles / 49.999245 Hz, 12950 successful, 2050 failures, `passed = false`. The failures were ID33 timing out 44 times and ID34 timing out 2006 times; ID13 had no new missing/timeout or 0x02 evidence, and UART hardware error increments were all 0. When an earlier group failed, ID13 was not requested, so its actual coverage was 12950 complete successful reads with another 2050 cycles skipped; a complete fix cannot be declared on this basis. TX918516 / RX4821978 bytes match these group results exactly. Evidence: `evidence/postcal-50hz-20261106-01.jsonl` and the corresponding `.summary.json`.
- In the same round, the result of the calibration the user completed at 13:33 was checked: Studio recorded all 15 calibrated to 2048; the main program file still kept the zero positions shipped with the package (ID13 at 1908, ID34 at 1372). At the user's request, only the 15 `zero_raw` values in `/etc/robot/feetech-ft5/hd1910-calibration.toml` were synced to 2048, written atomically and read back item by item; all directions, limits and other configuration kept their original values, and `motion_enabled` / `imu_mount_verified` / `units_verified` are still false. The backup and source record are in the board-side directory referenced by `evidence/postcal-zero-sync.applied.json`; main controller PID4411 did not change, and no write commands were sent to the servos. The current read-only run does not load the motion calibration, and the disk update is not described as the motion mode acceptance check passing.

The raw results are on the board in `/var/lib/robot/cubie-sync50-*.jsonl`; the local summary is in the Git-ignored `evidence/`.
Grouping changes the relative sampling times of the joints and the IMU; the model, position commands and control frequency are unchanged, and the effect on motion still has to be verified on site.

## Files

- `runtime-a7z-sync3.patch`: the original runtime library's default behavior is kept; with `CUBIE_A7Z_SYNC_GROUP_SIZE=3` set, grouping is enabled for 56/15 telemetry. The groups share one 20 ms deadline, there are no retries, incomplete samples are not accepted, and devices not yet requested are not counted as timeouts. Other register reads and writes are not grouped.
- `prepare_runtime.py`: exports a clean copy from `d1a2c62efdfb8c7a446ac99f562849e5a3a9587f` and then applies the patch, without modifying uncommitted source in other projects.
- `cubie-servo-uart.py`: before startup, sets the PB9/PB10 function value to 2, the 32 MHz clock and the ttyS2 alias, and checks the model, console conflicts and register readback; `--check` does not write registers. It never reads the UART RBR, which would consume RX bytes, or the driver `status` node.
- `bus_monitor.py`: only calls `robot.busStatus` and reads UART statistics. Acceptance requires at least 300 seconds, 50 Hz, 16 devices, the same process session, and no growth in failure or UART error counts; any failure along the way fails the whole window.
- `sync_probe.py`: an experimental tool that only encodes the fixed 0x82/56/15 request. An outer supervisor must pause the original process and guarantee it is restored; do not use the UART concurrently with a running robotd.
- `sync_matrix.c`: a standalone read-only timing comparison tool that only encodes 0x82/56/15; it compares three orders of the head group, different gaps across all groups, and group position. It does not replace the formal program, and still requires supervised pausing/restoring of the original process.
- `diagnostics/a7z-read-probe.rs`: a standalone read-only probe using the formal Bus library, comparing blocking/non-blocking file modes. It relies on the serial port's exclusive lock; a supervisor script must stop the confirmed read-only service normally, and guarantee that the original read-only service is restarted after it ends or fails.
- `install_readonly.py`: verifies the candidate package and backs up the program, configuration and unit; it replaces them only when the old service is confirmed to have torque off and no motion. The new service is pinned to `--read-only` and rejects all servo writes at the packet boundary. It clears the packaged `motion_enabled` and `imu_mount_verified`, disables the policy, and does not fake `units_verified`.

A normal exit of the old commissioning program sends torque-off packets. After the installer confirms the original service has torque off, it temporarily blocks startup and sends SIGKILL through the systemd stop job, to avoid writes during shutdown and automatic restarts. After the replacement, it checks the effective startup command and waits for the running main controller to confirm read-only protection.
If the replacement fails, check the stopped state and the backup first before deciding how to recover. The backup location is printed as
`/var/lib/robot/cubie-before-sync3-时间/` (时间 = timestamp). **Do not restore and start motion mode without checking.**

Automatic approval once refused to let the agent run this deployment directly; the user then completed the replacement themselves with the commands below.

## Manual replacement by the user

Before switching from commissioning, exit Studio and stop any other clients that can write to the main controller. The installer rechecks torque-off and idle state before stopping, but the preview runtime still allows other clients to send commands after the recheck.

Run this in a terminal on your computer from the repo root; replace `BOARD_IP` with the board's actual LAN address:

```sh
cd radxa-cubie-a7z/control/artifacts
scp cubie-a7z-sync3-readonly.tar.gz cubie-a7z-sync3-readonly.tar.gz.sha256 ../install_readonly.py radxa@BOARD_IP:/tmp/
ssh -t radxa@BOARD_IP
```

Run this in the A7Z terminal after logging in. After verifying and unpacking the runtime, use the installer uploaded with the current source. The installer digest in `runtime-build.json` corresponds to the old script inside the historical archive. sudo prompts for the password interactively.

```sh
cd /tmp &&
sha256sum -c cubie-a7z-sync3-readonly.tar.gz.sha256 &&
mkdir -p cubie-a7z-sync3-readonly &&
tar -xzf cubie-a7z-sync3-readonly.tar.gz -C cubie-a7z-sync3-readonly &&
cp /tmp/install_readonly.py /tmp/cubie-a7z-sync3-readonly/install_readonly.py &&
sudo python3 /tmp/cubie-a7z-sync3-readonly/install_readonly.py /tmp/cubie-a7z-sync3-readonly
```

After a successful install, do only the read-only acceptance check:

```sh
sleep 5
sudo python3 /usr/local/lib/cubie-control/bus_monitor.py --seconds 300 \
  --output "/var/lib/robot/cubie-native-$(date +%Y%m%d-%H%M%S).jsonl"
```

The window passes only with exit code 0 and a final result of `passed: true`; exit code 2 means it did not pass.
Even a pass does not allow moving directly with the packaged calibration: you still need to confirm this robot's zero positions and IMU mounting, deal with the abnormal mouth range, then connect padd/GameSir and verify standing, walking, sit-to-stand and forward rolls in turn.
The startup settings are prepared as persistent configuration, but a reboot after the replacement has not been verified yet.

## Known differences from the Zero 3W

The upstream runtime source `packaging/uart-service.py` does more than set the baud rate: it identifies
`fe660000.serial/ttyS2`, sets `rx_trig_bytes` to 1 after the serial port is opened, sets/reads back
the IRQ's CPU3 affinity, and only after successful verification releases acquisition through `robot.uartConfigured`.
The A7Z currently uses `uart-ng`, a UART0/ttyAS0 alias and a 32 MHz host clock adaptation, so that script cannot be copied over directly.
Without A/B logs of the same duck with the main controller swapped, it cannot be claimed that every Zero 3W window has zero errors, nor that its DMA is enabled or its FIFO larger.

## Build and test

```sh
python3 prepare_runtime.py /path/to/Microduck-kissqy /tmp/cubie-runtime
cd /tmp/cubie-runtime/microduck-hd1910/firmware
cargo test --locked -p duck-control a7z_ -- --test-threads=1
cargo board --locked -p robotd
```

Requires Rust 1.99+, cargo-zigbuild, zig and the aarch64 Linux target; the target is pinned to glibc 2.31.
The candidate output checksums and patch checksums are in `runtime-build.json`; the local binary and install package are in the ignored `artifacts/`.
Model files reuse the existing files on the board and are not included in the install package.

Completed: 20 local tool tests and the existing 12 provisioning tests; on the A7Z virtual serial port, 4 grouping tests, 3 read-only mode tests and 1 20 ms boundary test all passed.
When the full Feetech test suite runs on macOS, one 16 ms artificial-delay test exceeds its deadline; that test passed when rerun on A7Z Linux. The deadline was not relaxed.

## Left foot stepping inward investigation (2026-11-06)

The user reported that after walking for a while, the left foot steps on the right foot and the robot falls; ID11 has not been replaced yet. By the model's own left and right, the left leg is ID20–24
and the right leg ID10–14; the current IDs, directions and limits match the packaged configuration, which does not mean the physical assembly, zero positions or load capacity are correct.
Currently an external fan blows on the bare board, with no installed heatsink. A static torque-off window of 305.615 seconds / 15281 reads had one
ID11 status error 0x02, a maximum of 43.71°C, and no throttling or UART hardware error growth, so the error cannot be attributed to high temperature.

- `diagnostics/record_motion.py`: only sends robot.subscribe / busStatus / health, recording target angles,
  actual angles, attitude, commands and health. A 5-second check on the real robot with torque off received 98 frames (about 19.4Hz), with no motion commands;
  this check does not count as gait verification. Later dynamic tests must separately confirm the actual support and that the operator is ready.
- `diagnostics/hip_roll_probe.py`: after the user confirmed the robot was securely on a stand with both feet off the ground, ID21 and ID11 were each moved slowly by ±57 steps
  (about 5.01°), returned to their own starting points and set to torque off. Only use it when both the main controller and Studio are stopped; the original running P32/D40/I0,
  speed and torque limit are all kept. The packet gate rejects writes to other servos, out-of-range targets, EEPROM, broadcast, reset and similar instructions.
  It only writes the RAM torque switch 40 and goal position 42 of the two servos, and does not change zero positions/directions/limits or the main program configuration.
- Left ID21 settled with an error of 0.09–0.44°, right ID11 0.26–0.53°; both had status 0 and a maximum of 31°C.
  This is not a load test with the P5/D0 used for walking, so it cannot rule out mechanical looseness, insufficient tracking under load or model/attitude issues,
  and there is no evidence that the left servo is damaged.
- The test used a time-limited systemd supervisor that independently confirmed torque-off on exit, then restored the original main controller and Studio. At the end, main controller PID9094,
  policy off, all torque off, and the program/configuration/calibration hashes unchanged. Raw record and summary:
  `evidence/crossfeet-hip-roll-20261106-01.jsonl` and the corresponding `.summary.json`.

The earlier group3 standalone read-only control run was interrupted because the user was preparing to replace a servo; it last saved at 3450 cycles with no complete result,
so it does not count as a five-minute pass, and the group1 control run was not performed. The supervisor initially compared systemd ExecStart metadata that included the PID/time by mistake;
it was changed to check the stable argv while keeping the program/configuration/calibration hash checks, and torque-off restoration has been re-verified.
