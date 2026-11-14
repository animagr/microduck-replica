# Action Lab: start with your first action

**English** · [简体中文](custom-actions.md)

Applies to: HD1910 Microduck · 2026-10-23

## 1. If you are a complete beginner, start like this

Enter “动作实验室” (Action Lab) from the left navigation or the training studio home page. It is a standalone library of action recipes: you can search, filter by category, and view previews or text descriptions. Choose “单脚平衡” (Single-leg balance) and use that recipe, starting with the recommended target: **left-foot support, lift the other foot 1 cm, hold for 3 seconds**. Left and right are from the robot's own point of view.

1. **Pick an action target.** Adjust the support foot, foot-lift height and hold time. The 3D view helps you understand the target; it is not a physics simulation or a training result.
2. **Click “开始短试跑” (Start smoke run).** It uses 64 environments and 5 iterations to confirm that the environment, training and saving work properly. A few iterations of smoke running usually will not learn this action.
3. **After the smoke run passes, start full training.** You can keep the recommended parameters at first. The iteration progress shows how much computation has been done, not how much has been learned.
4. **Select a checkpoint, then click “评估” (Evaluate).** The balance evaluation runs 8 attempts, each including preparation, lifting the foot, holding and putting the foot down. Look at the number of successes and the actual replay.
5. **Adjust based on the replay.** Start with a low foot lift and a short hold; after changing the target, do a new smoke run. Save different experiments and compare their respective targets and results.

Without a checkpoint evaluation video, rotating the 3D duck cannot tell you whether it has learned. Demo mode uses synthetic data and is only for getting familiar with the page; practicing actions requires real GPU mode.

### Trained models and the official V8

The Action Lab's “预训练模型” (Pretrained models) tab contains the official V8 policy collection and the HD1910 models released in kissqy V167. You can search by source, action type or keyword, and view the version, hardware, checkpoint number, download location and license. Some kissqy weights are inside their full release package, and the details list their location in the package.

**The official policy collection has reached V8, but new experiments in this training studio still train from scratch and do not automatically load V8.** The official V8 manifest targets the XL330; kissqy's self-trained versions target the HD1910, and the two kinds of weights cannot be swapped based only on their names or identical input dimensions. The V8 default VelStand includes walking, zero-velocity standing and fall recovery, and the collection also keeps the early separate walking/standing models. [Official V8 manifest](https://huggingface.co/pollen-robotics/microduck-policies/blob/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json)

“获取 ONNX” (Get ONNX) opens the publisher's weight file; “查看发布包” (View release package) opens the original package page; neither automatically installs anything or modifies the robot. The catalog does not yet provide local simulation evaluation or continued training of external models. ONNX is for inference and has no full PPO training state; continued training requires a compatible PT checkpoint, configuration, normalization and other data, so an ONNX file cannot be uploaded as if it were the same file.

### What data to watch during training

The execution-host resource panel on the details page shows the current GPU model, utilization, temperature and VRAM, the CPU model, utilization and temperature, as well as memory usage. It refreshes about every 3 seconds; items that cannot be read show the reason. In WSL the CPU temperature is usually unreadable, CPU/memory reflect what the virtual machine can see, and the GPU reading covers the whole card, including other processes. When viewing a finished experiment, the resource data is still the machine's current state, not that training run's historical usage.

The training iterations and sampling speed come from that experiment's log. Right after starting, before the first iteration has been output, there is temporarily no throughput; a finished experiment keeps the last recorded metrics. Iterations are not physics simulation steps, nor are they the action success rate.

## 2. What the three options mean

| Option | Current range | Meaning |
| --- | --- | --- |
| Support foot | Left foot / right foot | This foot stays on the ground and the other foot is lifted |
| Foot-lift height | 0.5–2 cm | Target distance between the sole of the lifted foot and the ground |
| Hold time | 1–5 seconds | How long to keep holding while the stable-standing conditions are met; not the total duration of the whole action |

The action sequence is: prepare on both feet → lift the foot → hold → put the foot down and return to two-foot support. A full cycle is about "hold time + 3.5 seconds". This defines the task target; the policy finds its own way to control the joints and does not copy the preview pose.

This is an **experimental simulation recipe**. The model can reach these foot-lift heights, but that does not prove the policy can complete the action stably, nor that the physical robot behaves the same way. Mass, inertia, power supply and servo errors still affect the results. Importing a duck profile is for recording and cross-checking; it currently does not automatically rewrite the physics model.

## 3. How to tell whether it has really learned

A rising reward curve means the policy matches the training score better. The action acceptance check additionally verifies: the specified foot keeps supporting, the other foot is off the ground, body attitude and velocity are under control, the hold lasts long enough, and finally two-foot support is restored. A foot in the air after falling, a momentary foot lift, or falling after the hold do not count as a complete success.

The report keeps each attempt's result, hold time and failure reason, and the video includes all attempts. **0/8 is also shown truthfully**. 8 attempts is a small sample that is convenient for repeated checking; before deployment, more initial poses, perturbations and real-hardware verification are still needed.

| What you see in the replay | Next step |
| --- | --- |
| Falls right at the start | Check the model, task and values; do not just add more iterations |
| Stands, but does not lift the foot | Check the target and training progress, and try a lower target |
| Lifts the foot, then puts it down quickly | First shorten the hold time, and check the support and tilt conditions |
| Completes the hold, falls when putting the foot down | The return phase has not been learned yet; the complete action still counts as a failure |
| High score, but the motion is wrong | Keep the video and configuration, adjust the task rules; the score cannot replace the acceptance check |

Pausing keeps the process and VRAM. Closing the browser does not end training; pausing also does not automatically shut down the cloud machine or stop platform billing. After stopping, you can continue from a saved checkpoint.

## 4. What if I want to play with more unusual actions?

**You don't need to learn to code first, and you don't need to use AI first either.** For actions that are already integrated, you can directly pick a template, change parameters, run and watch the replay. A completely new action first needs its task rules integrated into the engine; at this stage you cannot type one sentence and automatically train an arbitrary action.

The future direction of the Action Lab is a community-built **action recipe library**: authors write the action target, training rules and verification method, and after review the recipe is included; other users choose a recipe and adjust the parameters to train it themselves. Currently there are three built-in training recipes and twenty upstream pretrained model entries. Models are obtained from the original publishers; community web submissions and automatic installation are not implemented yet.

| Idea | Current entry or next step |
| --- | --- |
| Stand on the left foot or right foot, change the height and time | Single-leg balance in the Action Lab |
| Walk on flat ground, adapt to rough terrain | The existing walking recipes |
| Head shaking, waving, fixed-sequence performances | Consider joint keyframe choreography; this training studio does not provide that editor yet |
| Jump once and then stand stable | Not integrated yet; first check the servo output and landing conditions |
| Turn exactly one full circle and then stop | Not integrated yet; needs accumulated turn angle and a stop condition |
| Upload a dance video for the duck to imitate | Not supported yet; needs motion mapping and imitation training |

When describing a new action, state clearly: **what pose it starts from → which body part moves and how → how long to hold → what pose it ends in → what counts as a failure**. For example: "Stand on both feet, support on the right foot, lift the left foot 1 cm, hold for 2 seconds, then stand on both feet again; it must not prop itself on the ground with its head at any point."

## 5. How the official project trains

The official project uses PPO reinforcement learning, trying actions in a large number of simulated environments, adjusting the policy through rewards, and then exporting ONNX. When developing a new action, first pick a similar task, confirm the physical conditions, define the target and acceptance check, then do a smoke run. [Official project](https://github.com/pollen-robotics/microduck_rl) · [Official development guide](https://github.com/pollen-robotics/microduck_rl/blob/develop/AGENTS.md#building-a-new-env--the-workflow)

The training studio wraps already-implemented tasks as selectable recipes. Single-leg balance is an experimental HD1910 task added by this repo. The official project also has tasks such as SitStand, StandUp, BallKick and Roulade, but they need to be adapted to the HD1910; Spin uses a roller-skating model and cannot be applied directly to the current feet. [Official task registry](https://github.com/pollen-robotics/microduck_rl/blob/develop/src/mjlab_microduck/tasks/__init__.py)

## 6. Advanced: adding your own action

If you only want to try existing actions, you can skip this section.

1. Measure the model, joint ranges, actuators and contacts, confirm the target is reachable, and then verify it can stand stably after perturbations.
2. Reuse the actuator and observation interfaces from the HD1910 configuration, and add a new task and a separate experiment name.
3. Define the target command, rewards and failure conditions; the success criteria are independent of the reward and cover the final recovery phase.
4. Test the configuration, left/right feet, boundary values and "a wrong action cannot succeed".
5. Run 64 environments, 5 iterations, and check the logs, checkpoints, full-cycle evaluation and export.
6. Practice easy targets first, then decide based on the replay whether to raise the difficulty.
7. Integrate bounded action parameters, making sure training, continued training, evaluation and export use the same target.

The following paths are relative to `software/training/`:

| File | Purpose |
| --- | --- |
| `src/mjlab_microduck/balance_parameters.py` | Parameters, cycle, success criteria and command convention |
| `src/mjlab_microduck/tasks/microduck_balance_env_cfg.py` | HD1910 balance environment and experiment configuration |
| `src/mjlab_microduck/tasks/mdp.py` | Commands, rewards and physical measurements |
| `src/mjlab_microduck/tasks/__init__.py` | Task registration |
| `scripts/export.py` | Keeps observation normalization and exports the target |

The training studio recipes are in `software/training-studio/training_studio/config.py`. Logs and checkpoints are resolved to directories per recipe; adding only a web card does not create a trainable action.

## 7. Command-line smoke run

For Linux / WSL2 with dependencies already prepared, run in the `software/training/` directory. The following commands really use the GPU.

```bash
uv run --frozen list-envs

uv run --frozen train Mjlab-Balance-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.save-interval 1 --agent.logger tensorboard \
  --env.commands.twist.support-side left \
  --env.commands.twist.lift-height-m 0.01 \
  --env.commands.twist.hold-seconds 3
```

Local dependencies are frozen at mjlab 1.3.0; for the upstream version see `UPSTREAM.md`. Task names in the latest online docs do not mean they are supported locally; the current `list-envs` is authoritative.

## 8. What is still missing after export

The export package keeps the checkpoint, action target, training configuration, evaluation evidence and the ONNX with observation normalization. The balance policy still uses a **61-dim observation, 14-dim action, 50 Hz**, but the meaning of the target command has changed.

**Identical dimensions do not mean it can be dropped directly into the existing walking controller.** The deployment side needs to provide the support side, foot-lift target and action phase according to the command convention in the package, and check the joint order, zero positions and outputs. Real-robot deployment of single-leg balance has not been verified yet; confirm the simulation results first, then do controlled hardware tests.
