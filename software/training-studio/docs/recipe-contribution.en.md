# Contributing an action recipe

**English** · [简体中文](recipe-contribution.md)

The Action Lab is the recipe library inside the training studio. Currently, the repo maintainers include tasks through code and PRs, and users choose a recipe on the page, set parameters and train. Web upload, remote download, automatic installation and a community account system are not implemented yet.

## What the author delivers

An action recipe that can be included needs to provide all of the following:

1. The action goal, start state, end state and failure conditions.
2. The supported robot model, servos and engine version.
3. A really registered training task, reward and termination rules, sensible defaults and a separate experiment directory.
4. The types, ranges and units of the adjustable parameters; parameters must flow through training, continued training, evaluation and export.
5. A full-cycle evaluation method and success criteria; cumulative reward cannot directly substitute for whether the action was completed.
6. Tests, smoke-run records, raw videos and known limitations. If there is no actual replay yet, a text description can be provided first.
7. Author, source origin, license and version information. Trained weights are a separate, optional artifact, labeled with the corresponding recipe and target.

## Where recipes are currently included

Engine tasks are in `software/training/src/mjlab_microduck/tasks/` and are registered in the task registry. The training studio uses the server-side whitelist in `software/training-studio/training_studio/config.py`, and does not let the page directly run arbitrary task names or scripts.

The existing single-leg balance example includes `balance_parameters.py`, `microduck_balance_env_cfg.py`, the related `mdp.py` functions and tests. Adding other kinds of actions requires implementing parameter validation and CLI passing suited to them; the three fields of single-leg balance cannot simply be reused.

Each recipe's `catalog` metadata determines how it is shown in the Action Lab:

| Field | Purpose |
| --- | --- |
| `category` | Page category, e.g. walking, balance |
| `tags` | Tags for search |
| `preview_kind` | Currently supports `robot_model`, `balance_target`, `text` |
| `source_label` | Source description on the current card; does not replace source-code attribution and license |
| `verification_state` / `verification_label` | Verification status and its user-readable label |
| `instructions` | Brief steps or goal description for this action |

Both the 3D model and the target illustration must be labeled as not being training results. When a video/image preview type is added in the future, the actual policy, target, conditions and source need to be recorded with it; a demo animation must not be shown as a video of successful training.

## How to review and show verification status

First review the hardware and task interface, then run the CPU tests, a 64-environment × 5-iteration smoke run, a full action evaluation and an export check. The page shows separately:

- **Not yet verified**: the task exists, but the corresponding verification evidence has not been obtained yet.
- **Smoke run passed**: the training and artifact pipeline runs end to end; this does not mean the action has been learned.
- **Action verification result**: gives the number of successes, number of attempts and failures under a fixed target and conditions.
- **Real-robot verification result**: separately records the hardware, deployment interface and hardware-test evidence.

The page currently has only the three recipes built into the project. Single-leg balance has passed a real smoke run, and the 5-iteration policy's action success rate is still 0/8; rough terrain has not yet passed this project's GPU verification. Future recipes from community authors use the same evidence standard.
