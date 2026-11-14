# AI Chat Setup

**English** · [简体中文](AI对话接入配置-20261027.md)

The first version is for saving model connections first, then testing and text trial chat once the service is activated. **The duck's microphone, speaker, real-time voice and AI-triggered actions are not connected yet.** Selecting the current connection does not change the existing R3, the local sit/stand voice commands or the music features.

Installed on duck-0de6 on 2026-10-27; see the [deployment and verification record](superpowers/verification/2026-10-27-ai-provider-settings.md). Without a real account or key, you can save a draft first.

## Starting from the web console

Open `http://duck-0de6:8000/#/settings`, log in, and work in the "AI 对话" (AI chat) card near the top. The original "语音与音乐互动" (voice and music interaction) panel also has an entry point to these settings.

1. Click "新建连接" (new connection) and enter a name.
2. Choose a provider and fill in the base URL and Model ID. Without an account, you can fill in just the name and save a draft.
3. After activating the service, enter the API Key in the web console and save. Do not send the key in a chat.
4. A complete configuration can be "设为当前" (set as current); clicking "测试连接" (test connection) sends one very short real model request.
5. Send a message in "文字试聊" (text trial chat) to see whether the model answers normally. Text replies do not drive the robot.

Up to 10 connections can be saved. Saving, editing and selecting do not access the cloud automatically; when required fields are missing, the connection is clearly shown as "待补齐" (incomplete) and cannot be tested or used for trial chat. The current selection persists across web service restarts.

## Two kinds of providers

| Choice | Base URL and model |
| --- | --- |
| 豆包·方舟文字模型 (Doubao Ark text model) | Prefilled with `https://ark.cn-beijing.volces.com/api/v3`; fill in the Model ID or inference endpoint ID and the API Key from your own Ark console. This is not your Doubao mobile app login. |
| 其他OpenAI兼容接口 (other OpenAI-compatible API) | Fill in the HTTP(S) base URL, model name and key provided by the service; the program appends `/chat/completions`. Only explicitly local services may use HTTP and "无需API Key" (no API Key needed). |

Doubao Realtime Voice 3.0 uses a separate WebSocket interface and event protocol, so you cannot use a real-time voice URL or an audio service key as an ordinary text API. This version does not pretend to support it; voice adaptation will be done separately later.

Requests are sent by the web backend on the duck. When using a cloud model, the duck itself needs internet access; a phone or computer accessing the control page also needs to be able to reach the duck. Whether a model can be called depends on your own account permissions, Model ID and the API's actual response.

## How keys and conversations are stored

- The key is stored in the private `ai-connections.json` on the duck itself, with Linux permissions 0600 and no additional encryption. Reading the configuration only returns whether a key is saved, not the full key; it does not go into browser localStorage, logs or diagnostic bundles.
- When editing with the same provider and URL, leaving the key field empty keeps the stored key; changing the provider or URL does not silently reuse the old key. You can tick the clear option, or explicitly choose a local key-free service.
- The input field is cleared after saving. New base images contain nobody's key; software upgrades keep local user configuration, and backups that contain private configuration should keep private permissions.
- Text context is kept only in the memory of the current page; switching or modifying the connection, or leaving the settings page, clears it, and it is not written to a chat history file. Input is limited to 2000 characters and model replies to 4000 characters; recent context is kept in complete rounds, up to 12000 characters in total.

## Common messages

| Message | Next step |
| --- | --- |
| 待补齐 (incomplete) | Fill in the Model ID, URL or key, then save. |
| API Key无效或尚未开通 (API Key invalid or not yet activated) | Check that the key belongs to the current provider and that the corresponding service is activated. |
| 提供商拒绝访问 (provider denied access) | Check your account permissions for the selected model. |
| 模型或接口路径不存在 (model or API path does not exist) | Check the Model ID and base URL, and avoid entering `/chat/completions` twice. |
| 限流或余额不足 (rate limited or insufficient balance) | Check your quota and call limits in your own provider console. |
| 请求超时或连接中断 (request timed out or connection interrupted) | Check the duck's network, the service URL and the provider's status, then retry. |
| 连接已更改 (connection changed) | The configuration was modified during the request; the old result is not counted as a success for the new configuration. Reload and test again. |

"测试成功" (test succeeded) only means that one request was answered normally; it does not mean a persistent connection, hardware voice or all models have passed acceptance checks. There is currently no real user key; development checks used a local mock provider, and real cloud behavior needs to be verified after activation.

## References and next steps

This version borrows Xiaozhi's structure of configuring recognition, conversation and synthesis as separate modules, and implements lightweight connection management in the existing Studio, without installing the full Xiaozhi server separately on the RK3566. Future work will add microphone capture, full recognition/real-time voice, speaker output and a restricted action entry point as independent adaptations.

- [Xiaozhi server configuration source](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/config.yaml)
- [Doubao Ark official calling example](https://docs.volcengine.com/docs/ark/context-management?lang=en)
- [Doubao Realtime Voice 3.0 official API](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=en)

The feature belongs to software ledger item F26; the music beat-following and body model issues keep their original records, and the AI configuration entry point is not to be taken as meaning they have been fixed.
