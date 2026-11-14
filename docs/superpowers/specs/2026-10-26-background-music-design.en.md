# Music motion keeps running in the web background

**English** · [简体中文](2026-10-26-background-music-design.md)

The user explicitly asked for it to "keep working in the background too." The existing implementation puts music motion inside the foreground remote session, which ends on blur, scrolling out of the area, or a missing 500ms motion heartbeat; so after the user switches to the chat, music capture continues but motion stops. This round hands standalone music motion over to the Studio server for continuous scheduling.

## Approach selection

Use server-side management of the existing standalone music session: a background web page does not need to send high-frequency motion heartbeats. Continuing to rely on browser timers would be subject to background throttling; adding a new standalone resident motion process would cause competition for control ownership; neither is adopted. Use the existing ordered send lock, model identity, stop and neutral cleanup mechanisms.

## Behavior and boundaries

- Only standalone `idle_motion + idle_kind=music` may continue after the web page loses focus, is hidden or scrolls out of the remote area; the rules for ordinary Lively, recording (including recording music), playback, joystick and buttons are unchanged. Starting still requires login, being in the remote area, standing steadily with the policy ready, the physical gamepad disconnected and fresh state.
- When the original web WebSocket truly disconnects, music motion is explicitly stopped / R3 turns off listening or music mode, a physical gamepad connects, another web page takes over / manual action starts, e-stop / torque off, policy / model changes, or key state becomes invalid, the session ends and is cleaned up once. Restoring the source or connection does not automatically revive an old session. Continuing after the page is closed is not supported for now.
- The server must independently maintain fresh robot feedback and physical gamepad state, and must not skip the existing freshness / torque / posture checks. When the music source's beat is unknown it waits; it does not synthesize fake beats or switch the motion model.
- The same page in the background can still be taken over by other pages; background music cannot take back control ownership that has been transferred. Cleanup and output use the existing ordered lock, and after stopping no queued old music frames may be sent.
- During a background music session, the frontend does not actively send stop because of blur/activity going inactive, nor does it keep pretending to send high-frequency heartbeats; disconnection still interrupts. Returning to the page shows the current session/beat state and provides a stop entry. The explanatory text states clearly that it continues in the background and stops on disconnection.
- Switching routes such as `/pad` and `/logs` within the same WebSocket also keeps an already confirmed standalone music session. Destruction of a page whose start was not confirmed, real disconnection and stale replies are isolated using the session token.
- The generic web 30-second application heartbeat timeout stays. While JavaScript heartbeats are paused for the standalone music owner, connection liveness is confirmed through native WebSocket Ping/Pong provided by the local `studio.ws_protocol`: a random matching payload, waiting at most 5 seconds, and on failure the connection is closed and the session ended. Vendored dependencies are not edited, and application heartbeats or observer activity are not faked.

## Verification

First use failing tests to cover continuing in the background beyond 500ms and after 10 seconds with nobody watching, foreground ordinary sessions still stopping, and disconnect / takeover / gamepad / invalidation / audio source off stopping without revival. Protocol tests cover correct/wrong/missing Pong and parent protocol event handling; real local Edge filters JavaScript application heartbeats while keeping native Pong, still has output after switching to the logs page for more than 30 seconds, can be stopped after returning, and does not revive after a real disconnection. On the real robot, only small head music motions are observed under the condition of standing steadily with the policy running. Interface accepted or fake robot output is not treated as a physical motion acceptance check. The current model was not trained for body posture following, so the body limitation is still marked truthfully.

## Scope

This round only changes the music session lifecycle; it does not change the DSP algorithm, control amplitude, model, network, servo parameters or audio recording/playback. Stop conditions and data state verification take priority over continuing in the background.
