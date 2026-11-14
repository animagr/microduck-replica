# Music Interaction Implementation Plan

**English** · [简体中文](2026-10-25-music-interaction.md)

> **For agentic workers:** Use superpowers:subagent-driven-development, with specification and code quality reviews before deployment.

**Goal:** When music is playing from the speaker, the duck makes small rhythmic movements to the beat, and when it hears a clear question it responds with calls that match the feel of the music.

**Architecture:** Reuse continuous_audio's single PCM stream, with MusicFeel extracting the beat; a dedicated local streaming question recognizer and the ordinary sit/stand recognizer process audio mutually exclusively. A private Unix socket provides bounded status and toggles, and Studio reuses the priority and heartbeat of the web action session to send head/body intents.

**Tech Stack:** Standard library, existing Vosk Model, AF_UNIX, Studio Python/JavaScript.

Later correction from the user: when listening is actually turned on, make one short call; in everyday mode, default to the duck's native response rather than echoing verbatim. Recording-and-echo stays as a separate explicit echo/record feature, and a dedicated button is out of scope this round. This correction takes precedence over the earlier interim design of "ordinary speech continues to be echoed".

### 1. Perception and question recognition

- [ ] `music_feel.py`/tests: 20 ms RMS onsets, 8 s/64-point cap, BPM/beat freshness, lively/somber/swing/uncertain, whitelist of clear questions. Fast/slow is not the same as an accurate genre. Simulated 75/125 BPM, swing, constant noise, silence, tempo changes and the wrong channel must each be covered.
- [ ] `music_interaction.py`/tests: reuse the Vosk Model with a separate bounded streaming question queue; allow responding to stable, complete questions while background music isn't muted, with partial word confidence at least 0.8, complete whitelist match stable for 0.5 s, and 4 s de-duplication. Music mode doesn't treat a whole song as ordinary echo or sit/stand commands. Each response suppresses its own audio via ContinuousAudio and uses the recent reliable rhythm from before the question. Clearing the queue or dropping frames resets recognition state; no arbitrary transcripts may be retained.

### 2. Local control service

- [ ] `audio_control.py`/tests: `/run/duck-echo/control.sock`, 0600, bounded single-request JSON, with only the methods status and set; it can only toggle listening and music mode, and must not accept arbitrary robot commands. Status contains only toggles, rhythm and faults, with no PCM or conversation text. Off by default at startup. R3 and web changes use the same real active state, and close/Select/disconnect cancel it. Web music can turn on the microphone while the physical gamepad is off.
- [ ] Integrate so the daemon keeps the main thread able to handle the no-gamepad state and reconnection; clean up on socket exit; the unit uses RuntimeDirectory, and the install manifest includes all modules. Test toggle races, oversized input, invalid fields, and that old questions don't trigger calls after closing.

### 3. Web console and rhythmic movement

- [ ] The Studio local client fetches status in the background, and snapshots don't block the event loop; authenticated pad.op provides listening and music entry points.
- [ ] MotionStudio adds a music session/beat sampling, reusing action preparation, heartbeat, lost connection, physical gamepad takeover and the sit/stand barrier; it only sends small head/body intents and does not automatically turn on torque or start the policy. When a human gamepad is connected, web rhythmic movement pauses and shows the reason; after the user turns off the physical gamepad, listening to music can be turned on from the web console. With no reliable beat, wait first; when sound/status goes stale, stop output and clear latches.
- [ ] The existing gamepad page shows a "语音/听音乐" (Voice/Listen to music) toggle next to the recording panel, along with listening status, BPM and a rough music feel; stop, leaving the page, and e-stop still follow the existing flow.

### 4. Verification and release

- [ ] Python unit tests + Linux fake ALSA/fake robot IPC, front-end and browser checks; verify switching between modes and feedback suppression.
- [ ] Freeze the component package, file hashes and backups of the original device files; restart only the necessary services while stopped; confirm the robotd/padd processes are unchanged, and record load, temperature and the remaining human acceptance checks.
- [ ] Update F16/17 in the master ledger, add new IDs for music rhythmic movement/music Q&A, and clearly state the boundary between software verification and human acceptance with real music and reverberation.
