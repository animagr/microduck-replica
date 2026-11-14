# Voice AI and Motion Scheduling: Design Discussion

**English** · [简体中文](语音AI与动作调度方案-20261026.md)

Date: 2026-10-26 (JST). Source: the user wants to interact with the duck by speaking naturally, and asked whether Doubao or Jev would be suitable for choosing actions; the user also asked that a physical gamepad that is merely connected should not block music dancing.

Status: architecture recommendations and a check of candidate services; no cloud service has been chosen or integrated yet. This document is not a deployment or real-hardware acceptance check record.

Oct 27 addendum: the user confirmed "not subscribed yet, build the configuration entry point first". The web console model configuration and the basic text chat test have been installed on duck-0de6; for details see [entry point verification and delivery status](superpowers/verification/2026-10-27-ai-provider-settings.md). Hardware voice, real-time voice and AI action invocation are still not connected; the overall architecture below remains the plan for later work.

## Recommendation

First connect the existing sit down, stand up, head and beak actions, native quacks, saved replays and music dancing to a common action entry point, then integrate one voice understanding service. The AI chooses the action or the performance style; the local executor checks the current state, waits for completion and handles takeover. Balance, gait, joint limits and beat-by-beat dancing remain the responsibility of local programs.

Keep R3 single-press to start listening and press again to stop, along with the distinct on/off prompt sounds. The user wants the duck to respond with quacks, so free-form speech synthesis is not required in the first phase.

## Three comparable approaches

| Approach | Scope | What needs to be filled in, and limitations |
| --- | --- | --- |
| Existing local recognition and explicit commands | Short commands already supported, such as sit down and stand up; basic functions can be kept independent of the cloud | Currently uses a constrained grammar, not full natural-language recognition; information it loses cannot simply be handed to a later model to recover. |
| Full speech recognition + Jev decisions | Choosing intent from the defined actions, recognizing negation, choosing a quack or style | Needs separate speech recognition; Chinese, background music, negation and uncertain input must be tested. Complex sequential actions should be composed by an explicit workflow; one classification cannot be assumed to produce an arbitrary reliable plan. |
| Doubao real-time voice + tool calling | Continuous natural interaction that needs context, while choosing registered actions | The first candidate for a complete voice service; latency on the current network, music interference, interruption, cost and the quack output strategy must be verified. Interface capability does not mean this duck has passed an acceptance check. |

We recommend integrating only one understanding engine for the first round of comparison, rather than stacking Doubao, Jev and a third model at the same time. The interface keeps the ability to swap. If the first-round goal is continuous natural interaction, evaluate Doubao first; if the goal narrows to a small set of action intents and quack selection, speech recognition + Jev can be evaluated.

## Results of checking Jev

The user's description "JEV or something" may correspond to TypeSafe's Jev; the name is still a guess. The official docs describe it as taking state and predefined questions and returning structured decisions. Choice can pick from options and provides probabilities and confidence; its positioning fits action routing. A correct structured format does not mean the intent judgment is always correct.

In this design, Jev sits after speech recognition. We have not concluded from this that it can replace the whole chain of audio capture, segmentation, speech recognition, dialogue and motion execution.

Official sources (consulted 2026-10-26):

- [TypeSafe Introduction](https://docs.typesafe.ai/introduction)
- [Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [Doubao real-time voice and tool calling](https://docs.volcengine.com/docs/real_time_communication/Accessend-to-endreal-timespeechlargemodel?lang=en)

## Local action entry point and control authority

Proposed flow: microphone → speech recognition/understanding → restricted action selection → local scheduling → existing locomotion policy and sounds.

- The action entry point only accepts registered actions and bounded parameters. For example "sit down", "stand up", "start/stop dancing", "play a particular saved replay", "play a particular quack"; it does not expose arbitrary robot RPC, program execution or joint angle generation.
- Multi-step instructions are executed step by step: first wait for the sit/stand readback to confirm, then move to the next step; on timeout, abort or stale state, end the current flow and do not keep sending old actions.
- The e-stop (emergency stop) always takes priority; explicit gamepad operation takes priority over autonomous actions. Merely being connected over Bluetooth should be judged separately from actual input. Writes from the current padd and the web console need unified coordination; the web console connection guard cannot simply be removed.
- Music dancing is a continuous local activity; the web console handles turning it on/off and display. Whether it may continue after leaving the web console must be designed separately from the existing rule that recording/replay stops on losing focus; it cannot be relaxed globally.
- The beat is estimated continuously and locally from the microphone; the AI can more slowly choose a lively, low-key or swaying performance. When responding to a question, the duck avoids its own quacks to prevent speaker feedback from being taken as a new command.
- Unknown or low-confidence instructions do not trigger actions. After a network disconnect, cloud actions not yet executed are canceled, and the local e-stop and manual control remain.

## Scope of the investigation into the current music not causing swaying

This problem has not been fixed or passed a real-hardware acceptance check, and must not be recorded as something that will be solved by connecting AI.

The existing read-only device records show: all physical gamepads were disconnected; the audio service was listening with music mode on, but there was no consistently stable BPM during sampling. ALSA's period_size at 48 kHz is 6000 frames, i.e. about 125 ms; the current program reads 20 ms of data at a time and uses the read time as the observation time. The status timestamps show data arriving in batches of about 125 ms; the same audio must be compared under uniform versus batched delivery to confirm the effect on beat detection. What was actually playing during sampling was not annotated at the same time, so this factor cannot be declared the sole root cause.

Another known limitation is that web console music dancing inherits the foreground and heartbeat requirements of action sessions, so leaving the page may stop it; being blocked merely because a physical gamepad is connected is also a current rule. These rules differ from what the user wants (continuous listening to music, manual takeover at any time) and need to be handled as an explicit control-authority design.

Numerical evidence: in the workspace, `artifacts/audio-interaction-20261025/music-clock.json`, `music-live.json`, `gate-history.json`. These files are not raw recordings and do not serve as an acceptance check of music classification accuracy or action effect.

## Order of subsequent acceptance checks

1. Stabilize the real microphone beat and timeline, and verify separately whether the head and body follow the beat.
2. Verify the takeover rules for an idle connected gamepad versus active operation, to avoid multiple sources competing to write.
3. Connect the common action entry point, then choose one voice understanding engine.
4. Verify with varied Chinese phrasings, negation, background songs, network timeouts and multi-step sit/stand; judge execution results by actual action readback.

This design is filed as F26 in the features ledger; the general action catalog remains under F20, and music effects and questions are under F24 and F25 respectively, to avoid double counting.
