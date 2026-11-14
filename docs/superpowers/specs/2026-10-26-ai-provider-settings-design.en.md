# Web AI conversation connection settings

**English** · [简体中文](2026-10-26-ai-provider-settings-design.md)

The user asked, with reference to the Xiaozhi voice project, for the existing duck web console to save the provider, API URL, API Key and model, for later use in voice conversations. It was confirmed: "Not activated yet; build the configuration entry first." This version delivers the connection foundation, which can be persistently saved, selected and tested, plus a web text trial chat to verify the API; it does not claim that the microphone, speaker or cloud account are connected.

## Basis and approach

- The [Xiaozhi server configuration](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/config.yaml) treats ASR, LLM and TTS as optional modules; the LLM can be configured with model_name, base_url, api_key.
- The [official Doubao Ark example](https://docs.volcengine.com/docs/ark/context-management?lang=en) uses `https://ark.cn-beijing.volces.com/api/v3`, calling Chat Completions with an API Key and an activated Model ID.
- The [official Doubao Realtime Voice 3.0 documentation](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=en) uses a dedicated Realtime event protocol and `wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`. The ordinary Ark Chat API and realtime voice are not mixed; this version first does a generic conversation connection, and realtime voice will be adapted later.

Use a lightweight proxy in the existing Studio backend, with no need to install the full Xiaozhi server on the RK3566. Requesting the model directly from the web page would expose the Key and is subject to cross-origin restrictions; a full Xiaozhi deployment would introduce another device protocol and set of services, beyond what this configuration entry needs.

## User flow

The settings page gets an "AI 对话" (AI conversation) card placed near the top and clearly visible, and the existing voice panel provides an entry to settings. Up to 10 connections can be added, edited and deleted, and the current connection selected. A configuration contains a name, provider (Doubao Ark text model / other compatible chat API), base URL, Model ID, and an optional API Key. Doubao pre-fills the base URL; the Model ID is filled in by the user from their console, and the latest model ID is not guessed.

Saving a draft allows the Key/model to be missing for now, showing the specific missing items; "测试连接" (Test connection) and "试聊" (Trial chat) only use a saved and complete configuration. An API that requires a Key cannot be enabled without one; a local Key-free service can explicitly select Key-free. Saving and selecting do not automatically call the cloud. After switching/deleting/editing a connection, old test results or trial chat context are cleared, and success of an old configuration cannot be shown as success of the new one.

The connection test verifies authentication/model with one very short real model request, rather than relying only on HTTP 200 or the `/models` listing. The text trial chat has a short multi-turn context and a clear button, and is not written to disk or logs. The UI states clearly "文字试聊尚未连接鸭子麦克风/扬声器，不执行机器人动作" (The text trial chat is not yet connected to the duck's microphone/speaker and does not execute robot actions); the dedicated realtime voice API is not yet adapted in this version.

## Backend and credentials

- A separate module manages the private `state_dir/ai-connections.json`, POSIX 0600, atomic writes, an in-process lock; no default personal configuration is created the first time. Saved connections and the current selection survive restarts. Reading a corrupted or invalid file must report an error and keep the original file, without silently overwriting it.
- The HTTP API reuses the existing login, Origin and CSRF checks, with no-store responses; the API requires a web password to be set, except for the existing explicit local dev-autologin test mode. Unauthenticated and cross-site calls cannot save or use the Key to request the model.
- The Key is only written to the duck via form POST; no GET, snapshot, success/failure response or diagnostic bundle returns the full Key. The page clears the Key input after saving and indicates it is saved with `key_configured`; an empty input keeps the same connection's original Key, which can be explicitly cleared. Changing the target service address/provider must not silently carry over the old Key; it must be re-entered or Key-free selected.
- The private file does not go into Git, the base image or frontend localStorage; encrypted storage is not claimed. Ordinary upgrades keep the user configuration; new logs do not write request bodies, Authorization, the Key or conversation text, and the diagnostic bundle does not include this file.
- Model requests run only in a background thread, and the configuration lock is not held across network requests; there is a small concurrency cap, timeouts and response body/input length limits, and a single call is not retried automatically. URLs are restricted to HTTP(S), with userinfo/query/fragment and control characters forbidden, and redirects that would forward the Key are forbidden. HTTP is only for explicitly local services; public services use HTTPS. Errors are shown by category and redacted, and arbitrary HTML/error content from the server is not treated as instructions to execute.
- The AI module has no dependency on the robot port; it does not execute any actions, RPCs, code or tool calls returned by the model. All existing local voice/music/motion behavior stays the same.

## Acceptance check

Save/load/restart/preservation and clearing of the Key/target changes/corrupted-file protection, real HTTP login and CSRF, and authentication, test, trial chat, timeout, errors, size limits and not following redirects against a simulated compatible API, with no Key in test logs/responses; all verification starts with writing failing tests. Real local Edge completes add, save, reload, switch, test, trial chat, clear and delete on a narrow screen, and the actual simulated service really receives the requests. Without the user's real Key, it is not claimed that the Doubao cloud or hardware voice has passed acceptance. Deployment follows the existing procedure: parked and policy off, frozen files/backup/user-state hash/motion-core identity checks.
