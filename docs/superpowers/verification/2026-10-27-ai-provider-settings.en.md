# AI connection settings entry: verification and delivery status

**English** · [简体中文](2026-10-27-ai-provider-settings.md)

Date: 2026-10-27 (JST; the work crossed over from Oct 26). The user confirmed: "Not activated yet; build the configuration entry first."

**Status: installed on duck-0de6 via SSH, and the post-deployment HTTP, runtime file and user data checks passed.** The code, simulated API, browser flow and isolated unit tests on the device passed. After the user confirmed "It's parked", the readback still showed the policy on, standing and all joint velocities at 0; `robot.stop → robot.enable {on:false,toggle:false}`, matching the web console, was issued, accepted was received and policy_enabled=false confirmed, and then the web service was updated. Torque was not automatically re-enabled and the model was not replaced.

## Frozen code and capabilities

- Implementation `907a4a2f2abc0e013044954b829a7e2eb257e9a4`; long-reply context fix `7536e0e48d1a0e92ced15f97417b0247a02a827d`; request cancellation/slow-response deadline fix `991bb50278c185f13248c03519b8e21c4eb0b800`. The final runtime files are frozen at 991bb50.
- "AI 对话" (AI conversation) at the top of the settings page, with an entry in the voice panel. Up to 10 connections, Doubao Ark text model and custom compatible APIs, name/Base URL/Model ID/Key or explicit local Key-free, saving drafts, current selection, edit and delete, a real short connection test, multi-turn text trial chat and clear.
- Saving and selecting do not contact the provider. Incomplete configurations cannot be selected/tested/chatted with. Only the address, model and authentication saved by the user are used; ordinary Chat Completions and the Doubao-specific realtime voice protocol are explained separately, without pretending hardware voice is connected.
- A private single file with atomic writes, POSIX 0600; the Key is not returned as a secret field, does not go into persistent browser storage, logs or diagnostic bundles, and the input is cleared after saving. Changing the address/provider does not carry over the old Key. Protected by the set web login password, session, Origin and CSRF; all AI responses are no-store.
- The AI module has no dependency on the robot port, and does not execute actions, RPCs or code in replies; it does not change the existing audio service, R3, music, motion model or network.

## Checks run

| Scope | Result |
| --- | --- |
| New feature storage/client/real HTTP | 23 items passed in the first round; including atomic save/load, keeping corrupted files, Key/URL changes, drafts, login/CSRF, diagnostic redaction, local simulated requests, rate limiting/timeouts, etc. |
| Related broad-coverage regression | 161 items passed in 120.400 seconds, before the final long-reply and deadline fixes; the pre-existing Windows default audio AF_UNIX thread and resource warnings remain, and this is not claimed as a clean Linux acceptance. |
| Node | 29 related checks passed; 5 targeted long-reply and component lifecycle items passed. |
| Independent spec review | 24 Python items and 5 Node items passed, with no omissions or out-of-scope implementation. |
| Independent quality re-check | 16 client/HTTP items passed in 2.899 seconds; after fixing the only significant network issue, 991bb50 was approved. |
| Final real local Edge | Passed in 5.595 seconds with no console errors; 320/390/1440 layouts, a draft and two connections, save/select sending no external requests, reload keeping the current connection, Key not echoed, short test, continuing after multi-turn/long replies, 401/echoed-Key redaction, clear and delete all passed, and the fake robot had no AI action output. |
| Isolated unit tests on the duck | Using the frozen staging modules and a temporary test directory, 21 items passed in 1.283 seconds; including Linux 0600 and slow-response/cancel recovery. The running web console was not replaced, the actual user configuration was not written, and no public AI service was contacted. |

The browser uses a local simulated provider that actually receives HTTP requests, so it can distinguish save/select from actual test/chat. The simulated Key exists only in temporary test state, is not a user credential, and is not included in the image or the deployed runtime files.

## Review findings and fixes

1. Early on, globally replacing a short Key after JSON serialization would corrupt field names/identifiers. Changed to structured handling of display strings, protecting schema/identity fields, and redacting model output separately; with a `key='model'` regression.
2. The model output limit was 4000 characters while the old validation of history messages allowed only 2000, so a long reply would make the next turn fail. Changed to user 2000, assistant 4000, total 12000, trimming by complete old turns without truncating the previous turn's content; the real browser verified it can still continue after a 2501-character reply.
3. The old client only checked the total time after `getresponse()` returned, so slowly sending the status line/response headers could occupy both worker slots for a long time; an async wait timeout cannot terminate a thread. An independent reproduction of a 0.05-second timeout actually took 0.812 seconds, and after two cancels later requests were busy. Changed to per-request cancellation control, keeping the real connection socket, a watchdog interrupting connected I/O and reclaiming in finally; on re-check a 0.05-second limit exited at 0.062 seconds, and after two cancels the third recovered in 0.015 seconds.

Limitation: the Python standard library's system DNS resolution cannot be interrupted directly; if resolution/connection only returns after expiry, it is closed and no credentials/request are sent. It is not claimed that DNS on every operating system meets an absolute deadline. Configuration requests do not block the web event loop, and the concurrency of abnormal requests is limited.

## Installed package

- Source 991bb50, 8 runtime files, staging: `/home/radxa/.web-ai-settings-20261026-86ab26ebd5`.
- Only the 8 Studio runtime files were replaced and microduck-studio restarted, PID 11672→27725; the PIDs and start times of robotd 1097, padd 1135 and duck-echo 6325 were unchanged, all services active, voice service enabled.
- The install script again confirmed the actual policy_enabled=false before stopping the web service, backing up and updating atomically. Backup directory `/home/radxa/.microduck-backups/web-ai-settings-20261026-86ab26ebd5`, permissions 0700, containing the original runtime files, manifest and user data; the script has failure rollback.
- The independent post-deployment check had exit_code=0: the home page, healthz and all related resources HTTP 200, web resources matching the on-disk hashes, all 8 manifest hashes matching; unauthenticated AI configuration requests 401; the hashes of the original 12 user data files unchanged. The logged-in configuration flow was verified with real local Edge + a simulated provider; the on-site login was not bypassed, and no test Key or test connection was written to the device.
- Evidence: `deployment/apply_frozen_remote.result.json`, `deployment/device-verification.json`, `deployment/stop_before_update_remote.result.json`. This round did not re-flash the image, enable OTA or change Wi-Fi.
- Without the user's real API Key, Doubao or any other real cloud account was not verified; the microphone/speaker, end-to-end voice and AI action calls are not yet connected.

Notes: [configuration usage guide](../../AI对话接入配置-20261027.md). Evidence is in the root workspace `artifacts/ai-provider-settings-20261026/`; in the software ledger this is F26, and the physical problem with music beat-following still has not passed acceptance per the original record.
