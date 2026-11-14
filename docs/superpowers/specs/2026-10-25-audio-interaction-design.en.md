# Continuous voice and music interaction

**English** · [简体中文](2026-10-25-audio-interaction-design.md)

The user has decided: a single click of R3 turns voice on, another click turns it off; sound comes from a nearby phone or speaker; while listening to music the duck responds with small head and body movements, and when asked "感觉怎么样" (How does it feel?) or "喜欢这种歌吗" (Do you like this kind of song?) it makes different sounds depending on how the music feels. Keep using the onboard microphone, local recognition, the existing web console and SSH software updates.

## First delivery: R3 continuous voice

When on, a single bounded microphone stream is shared, pauses automatically segment sentences, and each sentence is at most 10 seconds; turning off, Select, gamepad disconnection, input frame drops and service exit all cancel pending recognition and playback. Key repeats are ignored, and if R3 is already held at startup it must be released first. The sit down/stand up voice commands are kept. Per the user's later explicit request, a short sound is made once when R3 or the web page actually turns voice on, and the default everyday mode no longer plays back the user's original words; recognized actions and music questions are answered with the duck's native sounds. Recording playback (repeat-after-me) is a separate feature; the explicit echo configuration and CLI record are kept, and a dedicated button is left for a later decision. While playing its own sounds, it pauses processing of captured audio and leaves a tail gap, to prevent repeating itself. Single-click mode is the default, and an explicit hold configuration is kept for fallback. No audio is stored on disk, and no cloud service is used.

The first delivery has confirmed actual sentence segmentation using repeat-after-me; the later everyday mode is accepted using the sit/stand voice commands, native sounds and music Q&A, and nothing is executed after the next click. Single-click toggling must not be made to still require holding, or to auto-close every 10 seconds. A microphone failure must exit the current listening round and must not busy-loop repeatedly.

The user then explicitly asked for a different cue when turning off too: when explicit R3 or the web page switches from on to off, a low coo is played once, and chirp is used for turning on; the end of a sentence keeps listening and does not play the off cue. Automatic cancellations such as Select, disconnection, input frame drops, failures and service exit make no sound. The off cue uses the existing bounded dispatch thread; reopening/exiting cancels an old cue not yet played, and no new thread is created per click.

## Second delivery: music perception and response

The same microphone stream produces the beat and a rough upbeat, mellow, relaxed swing or uncertain state; fast versus slow is not treated as accurate jazz genre recognition. Question phrases are handled separately from action commands, only confirmed questions trigger sounds, and its own audio is suppressed while sounding. When unsure, a questioning sound is used. Questions must be tested in practice while music keeps playing; silent unit tests alone cannot substitute for this.

## Third delivery: motion and web

Small head and body intents are sent through Studio's existing control arbitration, and run only when the policy has taken over, the state is fresh and the posture is stable. Manual gamepad operation, web control, recording playback, Lively, sit/stand and disconnection take priority; it does not actively enable torque, start the policy or switch models. Movement to the music stops on silence, stale data or turning off. The web page shows listening, beat, music feel and pause reasons. The current board has no heatsink, so load and temperature need to be recorded before enabling always-on analysis.

## Release

Deliver testable versions step by step, keep the pre-install files and configuration, and write tests and versions into the software feature ledger. Restart only the services this task needs; do not restart the motion core. Real motion acceptance is left to the user.
