# Local music interaction fix and real-world limits

**English** · [简体中文](2026-10-26-local-music-fix.md)

Date: 2026-10-26 (JST). This round deployed software fixes, but the user still reports it waiting for the beat with the head and body not moving to the music; **it has not yet passed the real-music motion acceptance check**.

## Deployed

- Voice `2f24a6ae7b5a2b16d2b222eee507aa91b988c9fc`: 20ms ALSA period/80ms buffer, an audio timeline advanced per sample, continuous envelope periodicity detection, handling of short stream dropouts and clock drift, and releasing the old beat at the noise floor after the song stops.
- Studio `6ca5459c781663d3872cf3a2b4697ee21a05c892`: waiting for the beat and producing music movement are shown separately; R3/service off ends the standalone music session, and resuming listening does not revive the old session. The foreground/heartbeat and physical gamepad protections are still kept.
- Voice backup `/var/lib/duck-echo/upgrades/20261026-012132-2f24a6ae7b`, PID 42568 at deployment; a later capture comparison restarted only this voice service, so 42568 can no longer be treated as the current PID. Web backup `/home/radxa/.microduck-backups/web-audio-20261025-cefb03d009`, running PID 43893.
- Before the web update, the user confirmed the robot was parked, with readback standing/homed, policy_enabled=false; no stop command was re-sent. 5 Studio files were updated; the hashes of the 12 original user data files were unchanged. robotd 1099/padd 1132 and their start times were preserved.
- 8 HTTP resource/health checks passed, static asset hashes match the frozen files and are no-cache; the real WebSocket snapshot requires login, and the login was not bypassed.

## Software and performance checks

- Voice on Windows, 150 items: 133 passed, 17 skipped as Linux-only; all 150 passed in WSL and on the duck. The final version on the duck took 98.600 seconds.
- Studio Python 3.13 backend 257 items and Node 11 items passed; the related 88 backend items in the independent review passed.
- The full local Edge flow passed in 88.561 seconds: it first shows waiting with no fabricated motion, then shows music movement; the fake robot recorded 22 head frames and 21 body frames; the sit/stand recording/multiple playback and narrow-screen checks are kept. This is not the real-hardware effect.
- The two-stage independent review fixed weak onsets masking repetition evidence, timeouts after the song stops at slow tempos, and accumulated time offset from short mode switches. No known significant software review items remain.
- ARM offline numeric benchmark (7fb0b86 detection core): processing an 8-second envelope took about 521.66ms CPU, the slowest frame 30.05ms, and cached snapshots averaged about 0.019ms; this is not a long-duration temperature test of the full ASR/music stack.

## Real capture and user results

- While the user played music nearby, two 8-second A/B captures showed that the default period is 6000 frames = 125ms; after requesting a small period, the actual period was 960 frames = 20ms. The old onset algorithm produced no stable result on the small-period song segment, while the new algorithm obtained about 100BPM from that segment's numeric envelope. Only numeric values were written to disk; no PCM or conversation recordings were saved.
- After deployment on the robot the user reported "it keeps waiting for the beat, and the head and body don't move", which is still treated as unfixed. The first 45-second motor observation happened before the user started operating: listening/music were both false and the policy was off, so it did not cover their actual playback and cannot be used for the motion acceptance check.
- A later continuous 6-second real service readback had 60/60 valid items, about 65.2BPM, confidence 0.667–0.815; but on reading again it returned to unknown. Locking onto real music is still unstable, and passing on a single segment does not mean real songs generally work.
- Running the installed AudioClient with Studio's actual Python 3.13 as radxa UID 1000 read successfully; the same MusicRhythm correctly waits when unknown. The problem cannot be attributed to control socket permissions or a proven clock difference.

## Later capture and independent algorithm comparison (still not accepted)

- Actual ALSA `cget` check: right channel Mic3R on, the other PGA inputs off, PGA Capture Switch on,on, gain 60,60 (30dB), AGC off. This is consistent with the current service capturing the right channel; a normal configuration alone does not prove that music from the speaker clearly reaches the microphone.
- Two service state observations of about 62 seconds each had no reliable beat, with right-channel RMS after DC removal roughly 207–414. Confirmation that the user's "test the microphone" comparison was completed has not been received, so these data cannot be treated as confirmed test clips of speech or a specific song.
- The aubio 0.4.9 DSP core was built in private staging, original source SHA256 `d48282ae4dab83b3dc94c16cf011bcb63835c1c02b515490e1883049c3d1f3da`; no system packages were installed and the production algorithm was not changed. In a 12-second real-capture comparison, tempo output predicted beats but its native confidence was always 0, and specflux reported an onset only once at startup. The predicted beat count must not be used as proof of a reliable beat.
- Short cue-tone acoustic loopback: right-channel RMS before/after the cue was about 302/294, and during the 700Hz and 1100Hz cues about 28659/32049, with matching frequency components; the left channel was always 0. This confirms the right channel can pick up the robot's own output; the latter clipped, so that volume is not reused for testing. This result cannot replace comparisons with music from a speaker and close-range speech.
- The cue-tone test only temporarily stopped the voice service to get exclusive access to the sound card, and a finally block restored the original listening/music switches; no motion interface was called. After restoring: voice PID 53645, Studio 43893, robotd 1099, padd 1132. The actually running software is still voice 2f24a6a/Studio 6ca5459.
- A numeric input observer with a 300-second automatic limit was started, saving only time, RMS, BPM, confidence and switches, without saving speech or PCM. A synchronized confirmation of the user playing music from a speaker/speaking is still needed to continue locating the difference between input and detection.

## Key findings on the body model's capability

A short, small-amplitude, no-walking interface comparison was done while the robot was standing steadily, with the policy running, torque confirmed, joint feedback fresh and the physical gamepad disconnected; no automatic HOME, enable or model change was done. Every probe ended by sending head zero/pose inactive and getting accepted.

- 6-second 1Hz head/body comparison: 300 requests accepted; the actual head yaw range was 0.08897rad, and the body joints were essentially unchanged.
- 6-second slow static roll of 0.04rad: no visible actual body position change; adding a move-zero heartbeat did not help either, ruling out that hypothesis.
- Simultaneously subscribing to the real targets: body joint targets changed only about 0.002–0.010rad, and measured positions basically did not move. It cannot be said that the duck can perform the motion just because the RPC was accepted.
- The current actual model is `Mjlab-VelStand-Rough-Backlash-MicroDuck`, SHA256 `1cbf8730eadd75a5704332c9f3c10f60bfa9412135b907831c9dbd731ce1795f`. Verified from the training snapshot in the full contract exported from the device: `body_pose_tracking.weight=0.0`, `head_pose_tracking.weight=2.0`; there is no later curriculum term that enables the body tracking reward.
- Offline counterfactual inference with the local ONNX exactly matching that SHA: changing roll from 0 to +.04 changed the left/right hip_roll outputs by only +.000238/+.000453rad; the largest leg output change was about .00765rad. This is single-step sensitivity, not a physical rollout.
- The native pinned source 4734cbb keeps body z/roll/pitch at observations 57–59 and still sends them to the walk model when the stand slot is empty, so body commands are not dropped because of this. The main limitation is the current model's training objective; friction/deadband may be additional factors and have not been quantified separately.

Therefore, the earlier assumption in this round that "interface support is enough to reuse the existing model for body movement to the music" does not hold. Reliable body beat-following requires independently verifying a model with body tracking capability, and cannot be claimed as solved by connecting a large voice model, amplifying commands or removing protections.

## Candidate model and control ownership boundaries

The local HD1910 recovery teacher `firmware/policies/stand/policy.onnx` (SHA256 `a481d9f211f31d9476ab1a319fe362a21ef0879d9fa59442a122845af598268c`) has a body tracking training curriculum, its hardware/home/order/dim match the current model, and its offline body input response is clear. But its role is teacher_only, deployment_verified=false, and the README explicitly says it should not be put automatically into the zero-velocity stand slot; the stand slot affects all low-speed/stopped postures. It is listed only as a simulation candidate, **not enabled or substituted**.

Coexistence with an idle physical gamepad still requires a native channel ownership/takeover protocol: the existing raw tap does not provide the native head/body/IMU mode, and stop cleanup may race with gamepad writes. The protection is kept in this round. In the previous version 6ca5459, the web music session ended when leaving the foreground; the user then explicitly asked for it to keep running in the background, and the standalone lifecycle was completed in 29b9400 and deployed, see [background running verification](2026-10-26-background-music.en.md). Sound detection and body model capability are still accepted separately based on the evidence on this page.

Next, first check reliable beats/head and mouth behavior with real music; the body model gets separate simulation and acceptance as the user chooses. Doubao/Jev was not connected, the image was not re-flashed, and no OTA was released.

Numeric and deployment evidence: root workspace `artifacts/music-local-fix-20261026/`; the final voice Linux check is in `artifacts/audio-interaction-20261025/linux-tests-2f24a6ae7b.json`.
