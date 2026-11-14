# Duck local voice and music listening

**English** · [简体中文](README.md)

In the new version, by default a single click of the gamepad's right-stick button **R3** turns listening on, with a short "quack" sound; release the button and speak, then click again to turn it off, with a low "coo" sound. The web toggle uses the same prompts and only sounds once when the state actually changes; automatic cancellation by Select, disconnects and service exit stays silent. The default is `ECHO_REPLY_MODE=duck`: with voice control enabled it executes clear sit/stand commands, and in music mode it answers clear music questions; ordinary or unrecognized speech gets no response, it does not repeat the human voice, and it offers no free chat. Turning it off cancels pending recognition, stops recording/playback, and then plays the off prompt.

Prompt sounds use the WAV duration from the installed sound effect library plus a 100 ms startup margin and a 350 ms tail, during which audio capture is paused; wait a moment after the prompt ends before speaking. Each time the service starts, listening and music listening are still off by default.

Record-and-playback is kept as a separate `record` command and is not bound to a new button for now. If you explicitly want the old echo behavior, set `ECHO_REPLY_MODE=echo` or pass `--reply-mode echo`; in that case the default pitch and speed are raised to 1.25×, and setting them to 1.0 restores the original voice.

This round's voice features and the web music panel were deployed on the robot over SSH, and the sentence-segmentation issue was confirmed fixed by a retest with a real person. The acoustics of music played through a speaker and the body motion effect still await acceptance checks by a real person; software tests do not replace these two. See [this round's verification](../../docs/superpowers/verification/2026-10-25-audio-interaction.md) for details. The initial historical acceptance check below corresponds to the push-to-talk version.

This is a standalone service, installed over SSH, that reuses the main program's sit/stand action interface; it does not require reflashing or restarting robotd/padd. It only passively listens to the physical gamepad and does not grab the input device exclusively. Audio stays only in memory; no conversation recordings are saved to files.

**Initial historical acceptance check: on 2026-10-25 deployed over SSH to duck-0de6 (192.168.0.102) and set to start at boot. Real microphone capture, pitch-shifted playback, and physical gamepad R3 hold/release all worked. 45 software tests passed; the user then explicitly confirmed that with a real human voice "both stand up and sit down succeeded".**

The actual gamepad is a Nintendo Switch Pro Controller, input device /dev/input/event4. Before and after installation, robotd PID 1090, padd PID 1128 and their start times were unchanged, and the control loop stayed at 50 Hz. The service is set to enabled; the robot was not rebooted for this. When a paired gamepad reconnects after boot, the echo service detects it automatically.

Supported hardware: 64-bit Linux, TLV320AIC3104 HAT, an already working speaker playback path, and a physical gamepad that supports BTN_THUMBR. It captures Mic3R (right channel), as used by the project's initialization script. R3 on the web virtual gamepad is not supported.

## Music listening and explicit questions (deployed on the robot; speaker playback and motion effects await acceptance check)

The web console can control listening and music listening separately; turning on music listening also turns on the microphone, and turning off listening also turns off music mode. R3 and the web console read the same actual listening state. When the physical gamepad is off, you can still start capture from the web console; an actual gamepad disconnect, Select, input overflow and service exit cancel the current input.

Music mode reuses the same microphone stream and estimates the tempo and rough feel from short-time energy onsets and envelope repetition evidence. Upbeat, soothing and swinging are only tempo feedback and do not represent accurate genre or mood recognition. Music is not sent to ordinary echo or sit/stand command recognition. When you ask an explicit question such as "感觉怎么样" (how does it feel) or "喜欢这种歌吗" (do you like this kind of song), a separate local streaming recognizer reuses the existing Vosk Model and, based on the recent reliable tempo, plays the native chirp, coo or greet sound effects; with no reliable tempo it uses inquire. The per-word confidence of the complete question must be at least 0.8; a stable complete partial held for 0.5 seconds can be answered while music keeps playing, and responses are at least 4 seconds apart. Self-capture is suppressed during prompt sounds and their tails.

Continuous capture requests a 20 ms period and an 80 ms buffer; beat times advance by sample count, which avoids tempo distortion caused by the driver delivering data in batches. The repetition estimate only keeps a bounded numeric envelope, computes at most five times per second, and status reads reuse a cache. Smooth music usually needs several seconds of repetition evidence; when there is no clear repetition, the sound stops, or capture goes stale, no beat is generated. A stable reading is only a periodicity estimate of the volume envelope; ambiguity may remain about strong vs. weak beats, double tempo and mixed rhythms. When evidence conflicts, stronger support wins, and a unique musical beat position cannot be guaranteed.

Only toggle mode provides the private `/run/duck-echo/control.sock` (directory 0700, socket 0600). Each connection carries one UTF-8 JSON line, at most 8192 bytes, and only `{"method":"status"}` or `{"method":"set","listening":true,"music":true}` are supported; booleans must be JSON true/false. It returns listening, music, tempo and a short fault message, and does not provide recordings, transcripts or arbitrary robot commands. Restarting the service resets it to off. hold mode keeps the old push-to-talk behavior and has no web music control socket.

Music Q&A requires the local recognition model to be installed. If the model is not ready, the status shows a music recognition fault; standalone record-and-playback and explicit echo mode still work. Software tests with fake ALSA/UNIX sockets do not mean that real music through a speaker, reverberation and question recognition have passed acceptance checks.

## Chinese command mode

Local voice control mode: when you say a clear short command such as "坐下" (sit down), "坐下来" (sit down), "站起来" (stand up) or "起立" (rise), the corresponding action is executed; ordinary speech is not played back by default. "不要坐下" (don't sit down), multiple actions mixed in one sentence, and low-confidence recognitions do not trigger actions. Pressing Select, a gamepad disconnect, or an input overflow cancels old commands that have not been executed and turns off continuous listening.

On the duck's CPU it has passed 14 synthetic test utterances covering positive commands, negations, quotations, mixed actions and ordinary speech, with recognition taking about 0.26–0.51 seconds and peak memory about 144 MB. It uses a small vocabulary that includes unknown speech and negated forms, avoiding the 6–7 second delay of full dictation. The user then tested with the real microphone and R3, and confirmed that both standing up and sitting down succeeded.

After the acceptance check, both SSH and the web console once became unreachable. The connection was later restored via Bluetooth network setup; this duck was pinned to TP-LINK_5G_6494 (5240 MHz), and auto-connect for other saved networks and Wi-Fi power saving were turned off. 20 consecutive web visits all succeeded. Bluetooth logs for about 160 seconds with voice off and about 180 seconds with voice on showed no disconnects, and the maximum gamepad data gap was under 49 ms in both; while voice was on, real-person echo, sit down and stand up were completed, with logs showing accepted=true for two actions. The user confirmed that echo and the sticks both worked normally; another time the light was seen blinking, the actions were still normal and the logs had no corresponding disconnect. Earlier logs did show real drops whose cause has not been determined yet; a short retest cannot prove that a long-term intermittent problem has fully disappeared. See docs/network-20261025.md and the local artifacts/duck-network-20261025/final-verification.json for details.

It uses Vosk small-cn-0.22, with the model and dependencies in /opt/duck-echo; no speech is uploaded. Full recordings are not written to files, and logs only record the command category, confidence and action acknowledgment, not ordinary conversation text. It always reads the current sit/stand state first, so repeating "坐下" (sit down) will not make it stand up instead; when the main program rejects a posture request, it does not bypass that. Recovery after torque off while sitting still follows the existing firmware requirements.

Single-click mode processes one utterance after a pause in speech, up to 10 seconds long; recognition results older than 6 seconds are no longer executed. Capture is suppressed during its own echo playback and action prompt sounds, and listening resumes after the tail ends. Ordinary automatic segmentation suits quiet environments; when music is playing continuously through a speaker, turn on music mode.

To restore the old push-to-talk behavior, set `ECHO_TRIGGER_MODE=hold` in `/etc/default/duck-echo`, then restart only the `duck-echo` service. hold mode still processes after R3 is released; when voice control records the full 10 seconds, that utterance is cancelled.

```bash
# Update the runtime files first, then prepare the local recognition dependencies and model. For offline installation you can provide ARM64/cp313 wheels.
sudo python3 /home/radxa/duck-echo/install.py
sudo python3 /opt/duck-echo/install_speech.py --mode actions \
  --archive /home/radxa/duck-echo/vosk-model-small-cn-0.22.zip \
  --wheels /home/radxa/duck-echo/arm64-wheels

# Observe recognition without executing actions for now:
sudo python3 /opt/duck-echo/install_speech.py --mode shadow

# Turn off command recognition (if you need echo, set ECHO_REPLY_MODE=echo separately):
sudo python3 /opt/duck-echo/install_speech.py --mode off
```

Sources: [official Vosk models](https://alphacephei.com/vosk/models), [ARM64 installation support](https://alphacephei.com/vosk/install).

## Deploying on the robot over SSH

Upload this folder to `/home/radxa/duck-echo` on the duck. On the duck, run:

```bash
cd /home/radxa/duck-echo
arecord -l
python3 duck_echo.py devices
sudo python3 install.py prepare-mic
python3 duck_echo.py probe --seconds 3
python3 duck_echo.py record --seconds 4
sudo python3 install.py
journalctl -u duck-echo -n 30 --no-pager
```

Speak next to the microphone during the 3 seconds of `probe`; the output includes peak, rms and dbfs. On silence, too short a capture, or a capture failure, the exit code is 2. The `record` command records for 4 seconds and then plays it back; `playback_ok: true` is printed only if the playback process exits successfully. A successful process still needs your ears to confirm the actual sound quality and speaker loudness.

Installation requires sudo; the service runs as the radxa user and is added to the audio/input/robot supplementary groups. It depends on the system Python 3, alsa-utils and systemd; no Python packages need to be downloaded.

## Original voice and device settings

```bash
sudo nano /etc/default/duck-echo
# ECHO_PITCH=1.0 is the original voice, 1.25 is a higher, faster voice.
# ECHO_CHANNEL=1 is the Mic3R right channel; change to 0 only if the hardware really uses the left channel.
sudo systemctl restart duck-echo
```

This restarts only the echo service. If the sound card name is different, change ECHO_CAPTURE/ECHO_PLAYBACK; this install script's microphone settings are specific to the aic3104, and for other sound cards you need to confirm the capture path for that hardware separately.

## Diagnostics and rollback

- When the matching new padd is present, the service reads `/run/padd/mapping-state.json` and selects padd's actual evdev node, so it works even if that gamepad does not have the Linux default BTN_THUMBR (318). Custom R3/Select are handled by their raw button or hat-axis bindings; if a custom configuration omits R3, it does not fall back to 318. Only when an old installation has never provided this state file does it keep using the first gamepad that supports the default R3.
- A calibration pause cancels existing listening, recognition, pending actions and playback, and button presses during the pause only update the baseline; any change in configuration, device, process or pause state re-establishes the button baseline. If R3 is already held at startup or resume, release it first and then press it. Once the new-version state has been read, if the state disappears or is corrupted or the process exits, it conservatively deactivates until a valid state returns.
- No audio recorded: check `arecord -l`, the probe level and the Mic3R soldering/wiring; this unit's hardware has not been verified yet, so silence is not attributed to either the software or the soldering.
- Playback reports Device busy: release the existing sound trigger and try again. Native sound effects and echo may compete for the hardware playback path; this version reports an error and will not stop robotd or tamper with the global ALSA playback configuration.
- Pitch shifting also changes speed; this version supports recognizing short sit/stand commands after a button press, and does not include continuous wake words, free conversation, or voice changing that preserves speed.

```bash
sudo systemctl stop duck-echo
sudo python3 /opt/duck-echo/install.py uninstall
```

Uninstalling stops the echo service and restores the microphone capture settings from before installation. The program and backups remain in /opt/duck-echo and /var/lib/duck-echo; speaker volume is not changed by this install script. If installation or upgrade fails, it tries to restore the files it modified this time, the capture settings and the previous echo service state; if restoration fails, it prints an explicit error.

## Offline verification

```bash
python3 -m unittest discover -v
python3 duck_echo.py --help
```

The Linux integration tests run real subprocesses with temporary fake arecord/aplay/amixer programs, covering record and playback, time limits, disconnects, sound card busy, and microphone settings restore; they do not mean the sound on the real robot has passed acceptance checks.
