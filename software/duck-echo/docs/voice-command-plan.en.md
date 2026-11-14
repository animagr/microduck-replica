# R3 Chinese voice actions (2026-10-25)

**English** · [简体中文](voice-command-plan.md)

The user chose hold-the-gamepad-button-to-talk, release-to-execute, with updates continuing over SSH. The existing R3 echo is kept: when sit down or stand up is clearly recognized, it is executed; all other speech continues to be echoed.

## Design

- Uses the Vosk small-cn-0.22 local Chinese model (about 42 MB officially); recordings are not uploaded. The model stays resident in a background recognition thread and only processes one bounded recording after R3 is released.
- Uses a small vocabulary that keeps unknown speech, negation and quotation forms. Full dictation takes 6–7 seconds on the board; the small vocabulary takes about 0.26–0.51 seconds on 14 synthetic utterances on the same board.
- The whitelist contains only sit down and stand up plus a few clear synonyms. The complete sentence is exact-matched after removing whitespace and punctuation; "不要坐下" (don't sit down), "坐下再站起来" (sit down and then stand up) and low-confidence results do not trigger actions, and no fuzzy matching is used.
- Ordinary speech, recordings with an explicit "复读" (echo) prefix, and recordings with no recognized command keep using echo. Starting a new recording, a gamepad disconnect or exiting the service cancels old commands that have not been executed; results that took more than 6 seconds to process must not be executed. When a recording reaches the 10-second limit, that round is cancelled and nothing is executed automatically.
- Each execution first reads robot.policies and robot.busStatus. Saying sit down again while already sitting does not send a toggle; saying stand up again while already standing does not toggle. Standing up from limp goes through robot.init; standing up while sitting with a healthy policy goes through sit_toggle.
- To sit down from the standing hold state, it first checks that HOME is done and torque is confirmed, then zeroes velocity, enables the policy via robot.enable, waits for the read-back, and then requests sit_toggle. If the main program rejects any step, it stops; it does not change firmware, motion configuration, calibration or safety gates.
- When sitting with torque off, it does not force initialization or bypass the existing main program's posture rules. The action acknowledgment and the target sit/stand state are checked separately.
- Only /opt/duck-echo and its service are modified; voice mode can be turned off to return to pure echo. The model and dependencies are installed in isolation, and the motion services are not restarted.

## Files and verification order

1. `voice_commands.py`: command parsing, bounded JSON-RPC, sit/stand-state actions; first write tests for negated sentences, low confidence, idempotent sit/stand and rejection of unknown states.
2. `speech_control.py`: Vosk recognition, bounded queue, cancellation and expiry; verify recognition with the real model and system-synthesized test speech, and verify with unit tests that late results are not executed.
3. `duck_echo.py`: attach the handler only when voice is enabled; keep the original behavior when it is not; cover fallback for ordinary sentences, timeout cancellation and disconnect cancellation.
4. Install script and service: install the two modules, isolate the dependency and model paths, increase the memory budget needed for voice mode; update through the existing rollback mechanism.
5. Deploy on the robot after Linux tests, real-model tests and service configuration verification are done. Check CPU/memory, read-only action state and model loading; observe recognition first, then verify sit down and stand up with real R3 commands, and re-check that the original motion processes did not restart.

## Sources

- https://alphacephei.com/vosk/models
- https://alphacephei.com/vosk/install
- https://github.com/alphacep/vosk-api/blob/master/python/example/test_simple.py
- This project's stand-up/sit-down state logic in studio/pad_drive.py and the NDJSON RPC in studio/rpc.py.

## Completed verification and deployment

- 45 software tests passed (Linux simulated ALSA with real subprocesses, state machine, commands, concurrent cancellation, install rollback and offline dependency unpacking).
- The real model on Windows and the real ARM64 model on the board both verified positive/negated/quoted/ordinary speech; all 14 synthetic utterances on the board produced the expected command or rejection, with peak memory 144 MB.
- Python 3.13 on the board has no pip; the ARM64/cp313 wheels officially distributed on PyPI were unpacked offline into /opt/duck-echo/asr-deps, without changing system Python packages.
- The model is installed in /opt/duck-echo/models, mode ECHO_VOICE_MODE=actions is on, the service is active, the voice worker thread is ready, and resident memory is about 123 MB.
- The motion services robotd PID 1090 and padd PID 1128 and their start times were unchanged, and the control loop is about 50 Hz.
- The initial action state was not HOMEd, torque off, sitting=false. Saying "站起来" (stand up) first uses the native robot.init; sit down is tested after a normal stand-up.
- The issues found in review, the actual robot.policies slots[] structure and the input-overflow cancellation problem, were both reproduced with failing tests first and then fixed.
- The user explicitly replied "站起来和坐下都成功" (both stand up and sit down succeeded), completing the real-person R3 voice and sit/stand action acceptance check; this conclusion comes from user feedback.
- After the acceptance check, an SSH re-check timed out and a scan bound to the wired NIC found no SSH host, so no new logs corresponding to this real-person action were obtained. Earlier deployment and recognition logs are kept, and the intermittent network problem has not been ruled out yet; voice control and motion behavior were not changed to troubleshoot the network.
