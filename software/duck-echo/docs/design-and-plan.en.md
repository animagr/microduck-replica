# Duck microphone echo (2026-10-25)

**English** · [简体中文](design-and-plan.md)

The user authorized choosing the interaction independently, deploying over SSH and verifying, without reflashing. It is implemented as a standalone Python 3 service installed at `/opt/duck-echo`; it does not modify or restart robotd or padd and does not send motion commands.

## Interaction and scope

The chosen interaction is: hold the right-stick button R3 (Linux BTN_THUMBR=318) to record, release to echo it back; at most 10 seconds, and presses that are too short do not play anything. By default the captured right channel is played back at 1.25× the sample rate, producing a slight pitch shift. An original-voice mode can be configured with 1.0. Holding for a new round interrupts the previous round's playback. Disconnecting the gamepad or stopping the service discards the clip being recorded.

Also provided are the commands `probe` (bounded recording that reports the level), `record --seconds 4` (timed recording and echo) and `devices` (list available gamepads). Audio stays in memory; no conversation files are saved and the cloud is not accessed.

Candidate options: hold-to-record is easy to control and avoids recording the speaker itself; press once to start and again to stop makes it easy to forget to turn it off; automatic speech detection needs an extra noise gate and echo handling. The first option was chosen this time.

## Audio and input

ALSA captures with `arecord -t raw -f S16_LE -c 2 -r 48000`, and a reader thread collects at most 10 seconds of data; Mic3R is the right channel selected by the existing HAT initialization script. Playback takes the right channel, duplicates it to both channels, and plays it with aplay. Capture process errors, a busy sound card or silent recordings must be logged clearly, without claiming the audio succeeded. Raw PCM and the playback subprocess have explicit length limits and exit deadlines.

The physical gamepad is passively read via evdev in read-only mode, without EVIOCGRAB, so padd is not blocked. If the button is already held at startup, it must be released before the next press is accepted. Key repeats do not start a new recording; an input buffer overflow or unplugging cancels the recording. With no gamepad, hot-plugging is checked periodically.

## Installation and acceptance check plan

- [x] First write tests for PCM channels, levels, the state machine and evdev events; confirm they fail because the implementation is missing.
- [x] Implement PCM processing, bounded record/playback, the R3 state machine, hot-plug monitoring and the command line.
- [x] Provide a systemd unit, microphone path preparation, and install/uninstall scripts; uninstalling restores the capture settings from before installation.
- [x] Run all unit tests and the command-line help locally; check Python syntax and script line endings.
- [x] Once SSH is reachable, first check the hostname, sound card, services and gamepad devices, and record the original state.
- [x] Upload the standalone folder, run the microphone probe and check for a non-zero level; run a bounded record/playback before starting the R3 service.
- [x] Check the new service's logs and re-check the robotd/padd processes and runtime status. Real speech and button listening tests must pass acceptance checks on real hardware; offline tests cannot replace them.

## Initial connection troubleshooting

On 2026-10-25 the initial scan found no TCP 22, and no Microduck hotspot appeared in the Wi-Fi list. After the user confirmed the robot was powered on, duck-0de6 was rediscovered at 192.168.0.102. After checking the historical host key, the connection was made with the current login details provided by the user; the login password was not written to any project file.

## Offline verification and review

- Ubuntu 22.04 / Python 3.10: 25 tests passed, including simulated record/playback driven by real subprocesses, time limits, disconnects, busy sound card, both microphone control names, backup lifecycle, and recovery from a failed upgrade.
- `systemd-analyze verify` was run on a temporary service file with 0644 permissions, exit code 0.
- The project's `microduck/deploy/audio/aic3104-i2c3.dts` explicitly selects the generic aic3x compatible, whose control name is Mic3R; the codec driver's AIC3104-specific branch uses Mic2R. Installation identifies it from the actual control list rather than relying on guesses.
- The issues found in review, "reinstalling wrongly reuses the first backup" and "capture settings are not restored after a failed install", were both reproduced with failing tests first, then fixed and verified.
- The above is offline verification; the subsequent real-hardware acceptance check is below.

## Real-hardware acceptance check

- Device duck-0de6, aarch64, aic3104 sound card, Mic3R control present.
- The microphone probe succeeded, and a subsequent bounded recording captured about 2.876 seconds of valid audio, RMS 1233.255, -28.5 dBFS; the pitch-shifted playback process exited with code 0.
- `/opt/duck-echo` is installed, duck-echo.service is active/running and enabled, runs as user radxa, and no automatic service restarts occurred.
- The previously paired Pro Controller reconnected successfully; the service recognized Nintendo Switch Pro Controller /dev/input/event4, R3 event code 318.
- The logs continuously recorded multiple real R3 record/playback rounds, with clips of about 0.75–2.125 seconds, all of which completed playback. The user explicitly replied "可以" (works), confirming they heard the duck echo.
- Before and after installation, robotd PID 1090, padd PID 1128 and their start times were unchanged; health status healthy, control loop 50 Hz, bus ok, imu ready.
- It is enabled at boot; the robot was not rebooted for verification. The default 1.25× pitch/speed and 10-second recording limit are kept.
- Evidence is in the workspace at artifacts/duck-echo-20261025: hardware-preflight.json, hardware-install.json and hardware-service.json; none contain the login password or conversation audio.
