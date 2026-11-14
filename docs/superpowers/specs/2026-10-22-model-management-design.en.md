# Studio model management

**English** · [简体中文](2026-10-22-model-management-design.md)

The user has approved UI-08 and on 2026-10-22 explicitly asked for implementation to start. The goal is to install models that were already trained and exported on a computer onto the duck, and to select, name, rebind gamepad buttons, delete and restore defaults, without requiring the user to re-flash the system image.

## Usage flow

"管理" (Manage) in the overview goes directly to `#/models`. At the top are an import button and a brief explanation; the list distinguishes built-in defaults from user imports and shows name, purpose, whether it is currently selected, whether it is currently running, and buttons. Installing does not automatically enable it or apply torque. Paths, hashes and training details are shown collapsed. Weight and exporting the duck profile stay on the original settings page and are not mixed into model management.

Import supports a ZIP or tar.gz made from an existing deployment export directory: one policy.onnx, manifest.json, deployment-contract.json, plus the model's optional execution configuration. Before installing, check archive boundaries, file identity, purpose, and the main program's real ONNX preflight; failures do not appear in the list of available models. The name is editable; overwriting system files or existing models is forbidden.

Selection reuses robot.loadPolicy; success is determined by the robot.policies readback, and accepted cannot be treated as success. On failure, try to restore the old path and report the rollback result truthfully. The base built-in path is saved as the default restore source, so that the generic custom_only reset does not mistakenly point to another official model.

Gamepad buttons use A, X, LB, RB and D-pad down, which the current main program actually supports; reuse pad.bind, unbind with an empty string, and restore defaults using the native semantics of omitting skill. Conflicts explicitly show the existing action, and the write happens only after the user chooses to replace it. Actions are separate from model purposes; walking is not an ordinary press-once skill.

Self-imported models may be deleted; if one is still referenced by a slot or button purpose, first explicitly require switching / restoring the default, leaving no dangling references. Built-in files have no delete entry. While moving / without confirmed torque off, runtime configuration changes such as switching are rejected; the existing e-stop and basic buttons are kept.

## Architecture

- All imported files live under the Studio user-writable state/models, default /var/lib/microduck-studio/models. No additional root helper privileges are needed.
- model_package.py: safe archive extraction, static contract checks, calls robotd validate-policy; does not connect to hardware.
- models.py: library metadata, default sources, install, rename, delete, runtime RPC and readback confirmation.
- app.py: HTTP API behind same-origin / session / CSRF checks, streaming upload size limit, serialized changes.
- models.js: standalone management page. The existing overview card in tune.js becomes a link to this page.

## HTTP contract

GET /api/models returns {ok:true,data:View}; POST /api/models/import accepts raw ZIP/tar.gz bytes, URL parameters filename, name (optional), and requires X-CSRF. POST /api/models/op accepts JSON of at most 32KiB and requires X-CSRF.

Operations: rename{id,name}, select{id,slot}, restore{slot}, delete{id}, bind{button,slot,replace?}, unbind{button}, reset_bindings{}.

Success returns {ok:true,data:View}. Failure returns {ok:false,error:reason in Chinese,code:optional identifier}, with HTTP 400/409/413/503 chosen according to the actual error. ModelError is the service layer's expected exception.

View contains:

```
{
 items:[{id,name,source:'builtin'|'imported',task,suggested_slot,slots:[],running:false,
         buttons:[],can_delete:false,reason:null,sha12,installed:true}],
 slots:[{slot,label,model_id,path,error,default_id}],
 bindings:[{button,label,slot,skill,model_id,default_skill}],
 capabilities:{import:false,select:false,reason:null},
 buttons:[{button,label}],
 error:null
}
```

Models(rd,log,state_dir,tune=None,root='/',validator=None,rpc=None) provides async view(), import_package(path,name='') and handle(args,by=None). Tests can inject validator and rpc; production uses the fixed trusted robotd path and the real socket, and tests / demos must not treat fake success as production confirmation.

## Verification and delivery

Write failing cases first, then implement the key read/write paths. Archive traversal / links / duplicate paths / size / hash / incompatibility must be rejected; temporary failures leave no half-installation; defaults cannot be deleted, referenced models cannot be deleted; selection and button changes require readback and roll back on failure. HTTP verifies session / Origin / CSRF and size; a headless browser verifies the management entry, import, naming, selection, rebinding, deletion and restore. On the real robot, send no motion and do not switch the actual control model; actual deployment and loading are checked separately against the current state.
