# Local music beat-following fix plan

**English** · [简体中文](2026-10-26-music-local-fix.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Execute the tasks below in order; for each item, first run a failing regression test, then implement and review.

**Goal:** Fix the problem where beats from real music picked up by the microphone cannot reliably drive the head/body, make the "waiting for beat" state and the actual motion state explicit, and verify the takeover boundary of a physical gamepad.

**Architecture:** Keep the single microphone channel, the existing robot.head/robot.pose interfaces and the motion policy. Capture requests a 20ms period; beat detection uses a finite volume envelope advanced per sample plus periodicity evidence, and generates no actions for unstable input. The web console keeps the existing recording/playback protections; music control is allowed to coexist with an idle gamepad only when the evidence is sufficient, and the general protections are not removed.

**Tech Stack:** Python standard library, ALSA arecord, Studio Python/Preact, the existing Unix RPC and side-channel gamepad data.

## Evidence already collected

On 2026-10-26 the user ran two 8-second captures that saved only numeric values while music was playing: the default period was 6000 frames/125ms; after requesting `--period-time=20000 --buffer-time=80000` the actual period was 960 frames/20ms, and both ended normally. On real music with the small period, the old detector produced 0 stable snapshots; the volume envelope of the same segment shows repetition at a lag of about 0.6s, so drum hits cannot be located only by a 1.65x increase between adjacent frames. The evidence is in the root workspace at artifacts/music-local-fix-20261026/capture-ab.json; no PCM was written to disk.

## Task 1: Capture timeline and real-music beats

Files: `software/duck-echo/continuous_audio.py`, `music_feel.py`, `test_music_feel.py`, `test_alsa_linux.py`; if extra tests are needed, a new `test_music_timing.py` may be added in the same directory.

- [ ] Add failing regressions first: the same fixed PCM fed as uniform 20ms input and as 125ms batched input should yield similar BPM and a valid last_beat that is not in the future; input chunk boundaries must not change the energy timeline.
- [ ] Add a numeric-envelope regression for real music (take a small-period segment from capture-ab); BPM must come from repeated evidence, not a fixed 100/120. Keep the existing cases: strong drum hits at 75/125, swing, sustained constant volume, silence/stale input, tempo changes, etc.
- [ ] Capture requests a 20ms period/80ms buffer; verify there is no regression in voice sentence segmentation, prompt sounds or cancellation. Finite-window period estimation stays unknown when there is no reliable rhythm, and releases the old beat after the sound stops.
- [ ] Comparison test command: `python -X utf8 -m unittest test_music_feel test_music_timing test_continuous_audio`; full suite: `python -X utf8 -m unittest discover -p 'test_*.py'`. Run all tests on the device's Linux before deploying.
- [ ] Commit the task code; do an independent spec review followed by a quality review, and fix important issues.

## Task 2: Motion path and visible state

Files: `software/studio/studio/audio_interaction.py`, `motion_studio.py`, `pad.py`, `pad_drive.py` (only if necessary), `web/motion-studio.js`, `web/audio-interaction.js`, and matching tests.

- [ ] Trace the real control ownership and send path; confirm the posture, BPM, motion session and robot.pose readback. Locate the problem first, then change it.
- [ ] Show waiting for a stable beat as an explicit state, so the UI does not just show "随乐律动中" (Moving to the music) while nothing moves. For state expiry, silence and the stop switch, verify the head returns to center/pose goes inactive.
- [ ] Separate "gamepad merely connected" from "active input"; first check whether native padd keeps writing head/pose in idle mode. Allow music to run only when it can be confirmed there is no competing write and the side-channel data is fresh; actual gamepad operation cancels the current music. Keep the existing e-stop and recording/playback rules. If evidence about the mode is missing, document the protocol gap explicitly rather than removing the protection wholesale based on connection state.
- [ ] Run the affected Studio backend and Node tests. Updating only Studio first requires checking that the robot is safely parked, and preserving user state and process identities.
- [ ] Commit and do spec and quality reviews.

## Task 3: On the robot, re-check and records

- [ ] Deploy the voice component from a fixed commit and hash, run the device Linux tests, keep a rollback backup, and restart only the necessary services.
- [ ] Read back the actual ALSA period, beat freshness/BPM/confidence; if needed, retest with the music the user is playing, and avoid treating fake-microphone results as a real pass.
- [ ] Verify the web waiting/moving/stopped states against the real head/body output; physical motion is confirmed by the user, and file existence is not a substitute for the acceptance check.
- [ ] Update the software feature ledger F24/F25 and the verification records, recording separately what code was fixed, what was deployed, what passed on real hardware, and what is still missing.
