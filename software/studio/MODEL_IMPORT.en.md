# Importing trained models

**English** · [简体中文](MODEL_IMPORT.md)

Open “模型管理” (Model management) in Studio; there is no need to reflash the system image.

1. On the training computer, find the model folder exported from a single deployment.
2. Pack `policy.onnx`, `manifest.json` and `deployment-contract.json` into a ZIP, tar.gz or tgz. If the export also produced `deployment-execution.json`, `deployment-runtime.json` or `model-info.json`, put them in the same folder. Do not mix in training logs, scripts or multiple models.
3. Select the deployment package, optionally enter a display name, and click “导入模型” (Import model). The deployment package is limited to 64 MiB; after extraction the limit is 256 MiB.
4. A successful import only means it is installed. First turn torque off, then choose the purpose on the model card and click “使用此模型” (Use this model). The page only shows success after the main program confirms the actual model path.
5. If you need an action button, click the model's “设置按键” (Set button), then press the action button once on the physical gamepad, or choose it in the “手柄按键” (Gamepad button) drop-down; a button that is already in use needs confirmation before it is replaced. Walking still uses the original stand and walk controls.

A lone ONNX file lacks the action purpose, joint order, standing pose and runtime parameters, so it cannot be treated directly as a compatible deployment package. Studio checks the file identity and contract, then calls the local `robotd validate-policy` to pre-check the ONNX. If no usable pre-check program is available, the import is refused; successful extraction is never treated as compatibility.

The current running program's base standing pose and servo P parameters are fixed at startup. A model whose base standing pose, P parameters or joint order differ from the existing ones cannot be hot-swapped directly, and the page gives the reason; the corresponding deployment adaptation needs to be done first.

## How models, actions and buttons relate

- “已安装” (Installed): the model file is in the library; “当前选用” (Currently selected): this model has been selected for that purpose; “正在执行” (Running): the main program is running it.
- Buttons are bound to actions, and an action uses the currently selected model. The buttons that can be set are A, X, LB, RB and D-pad down. Walking and standalone standing are not bound as ordinary action buttons.
- Recording a physical button requires confirming that torque is off, that the five-button configuration is complete and consists of regular actions, and waiting for the configuration to be stable for two seconds; if there are special action bindings such as a direct stand-up, assign them with the drop-down, to avoid the button press also triggering the original action during recording.
- “取消绑定” (Unbind) only clears that button; “恢复默认按键” (Restore default buttons) restores the default actions for the five buttons; neither deletes any model.
- “恢复内置” (Restore built-in) switches a purpose back to the default model recorded initially; imported models stay in the library.
- Built-in defaults cannot be deleted. An imported model cannot be deleted while it is still referenced by a current purpose; first switch to another model or restore the built-in one.

Imported files and display names are stored in Studio's state folder; on the duck this is usually `/var/lib/microduck-studio`. This folder is kept when Studio is upgraded. Default model files stay in their original install location. Renaming only changes the display name, not the model identity.

## Development verification

`tests/test_models.py` and `tests/test_model_package.py` use temporary models and a fake main program and do not touch the servos. `tests/test_models_e2e.py` uses real HTTP, deployment package parsing, the model library and headless Edge, with the pre-checker and runtime interface in the tests explicitly replaced by local test implementations. These tests confirm the software flow and do not replace the motion acceptance check of an actual model on hardware.
