# Comparison with the kissqy training console · 2026-10-23

**English** · [简体中文](reference-comparison-2026-10-23.md)

Reference repository: [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy), reviewed at commit `525a215a19397767a073b782f57e97cf53683761`. We checked the public training console pages, docs and the actual backend source; we did not run their training program, and did not merge their code into this project.

## How far things work today

Our local demo flow has actually passed: create an experiment, smoke run, full demo, pause/resume/stop, persistent records, evaluating a selected checkpoint, download and continued training, and experiment comparison. Linux process control was tested with real CPU subprocesses and signals.

Real training mode has completed, locally on WSL2 / RTX 5060 Ti, 64-environment, 5-iteration training, video evaluation, ONNX export and a PT/ONNX inference consistency check; see the [acceptance record](verification.md). Users can repeat the smoke run locally first; the target cloud GPU, long training and the real robot have not passed acceptance checks yet. Demo models, metrics and replays cannot prove that a policy has learned an action.

## Main gaps

| Priority | kissqy's implementation | Our current state | Work to add |
|---|---|---|---|
| P0 Real training verification | Publicly records CPU physics stepping with a frozen engine, PPO updates and PT/ONNX consistency verification, and explicitly keeps the limitations on GPU long training and real-robot acceptance | 64-environment, 5-iteration training on the local GPU and the artifact checks have passed; verification on the target cloud GPU is missing | On GPULab, repeat training → save PT → policy replay → export ONNX → compare inference on identical inputs, and save the evidence |
| P1 Cloud connection | The page configures SSH, deploys the environment and sets up port forwarding; a standalone remote background service keeps the queue and results | Users must prepare dependencies, run the service and set up SSH forwarding by hand; closing the web page lets work continue, but shutting down the service stops the tasks it owns | Add connection guidance and a reconnectable execution service, then do environment preparation through the page |
| P1 Watching real actions | Can read rigid-body poses from a specified environment that is training, and can also start interactive physics evaluation of PT/ONNX | The 3D area is CAD; policy performance is viewed through the 250-step checkpoint evaluation video after training stops | Distinguish model appearance, live training view and checkpoint evaluation; first add interactive policy evaluation, then add live training sampling with overhead control |
| P1 Export verification | ONNX checker, Runtime inference, and the joint/observation/action/frequency and calibration conventions between model and firmware | Already calls the existing normalized exporter and packages the provenance and evaluation records; this sample passed an independent inference check, but there is not yet a built-in inference check after every export or a full deployment compatibility check | Add export verification results and specific failure reasons; downloadable does not mean deployable |
| P2 Batch experiments | The queue saves a snapshot of parameters at enqueue time, runs sequentially and handles failures; the UI lists 14 action categories and 35 recipes | A single active task, two HD1910 recipes, five common advanced values | First do experiment copying and a sequential queue, then extend verified action recipes one by one |
| P2 Training diagnostics | GPU/VRAM/temperature, estimated time remaining, per-term rewards and curriculum information | Currently mostly iterations, reward, episode length, sampling speed and logs | Show real resource data and per-term rewards, and explain the reasons for stalls or failures; time estimates must be marked as estimates |

## Design to keep

- Simple by default, with advanced settings collapsed. They concentrate the server, queue, physics parameters, curriculum and so on in a long page, which is feature-rich; our entry point for new users can be more focused. This judgment comes from comparing the pages, not from a usability test with users.
- The same light-gray shell, duck logo, buttons and mobile navigation as the robot web console, reducing the learning cost between the two tools.
- The fixed smoke run, and the configuration-matching checks for learning rate, seed and profile.
- Pause/resume of the real training process. Their pause queue lets the current training continue; another pause/resume pair is for the simulation viewer; these operations must not be treated as the same capability.
- Experiment comparison, evaluation and continued training from a selected checkpoint, clear demo labeling and artifact provenance.

## Implementation order

1. First complete a real small-task loop on the target GPU, to locate environment and engine interface issues.
2. Then add the cloud connection and interactive policy evaluation, so users can see the actions they trained themselves.
3. Improve post-export verification and the model/firmware compatibility check.
4. Add the queue, diagnostics and more verified recipes; keep the interface simple by default.

This comparison did not start paid cloud resources, modify the system image, copy their code or promise training convergence. The original parts of the reference repository declare a personal non-commercial license; reusing their code later requires a separate license check. This round only analyzes interaction and implementation ideas.

### Later implementation update

Later the same day, a standalone Action Lab, a third experimental recipe for HD1910 single-leg balance, and a source catalog of 10 pretrained models each from the official V8 and kissqy V167 were added. The catalog provides version, hardware and download links, and does not mean local evaluation or continued training has been integrated. New training still starts from scratch; community-owned weights keep the original publisher's license and are not packaged into this project.

The training details now include real readings of GPU model, utilization, temperature and VRAM, CPU model, utilization and available temperature, and memory, refreshed about every 3 seconds. A CPU temperature not exposed by WSL is shown as unreadable. These are the overall current state of the execution host; per-term rewards, curriculum, estimated completion time and historical resource curves are still not implemented. Remote connection management and automatic installation also still need to be implemented separately.

## Code and documentation references

- [Project training docs](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/README.md)
- [Real training, evaluation and export](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/runtime_adapter.py)
- [Live training sampling](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/live_view.py)
- [SSH deployment and connection](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_ssh.py)
- [Standalone remote service](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_server_boot.py)
- [Keeping the training backend alive](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/durable_manager.py)
- [Queue snapshots and pause semantics](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/training_queue.py)
- [Public verification records and unverified scope](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/docs/Verification.md)
