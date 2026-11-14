# Action Lab: single-leg balance

**English** · [简体中文](action-lab-design.md)

Date: 2026-10-23. The user has authorized implementing the first no-code action feature inside the existing training studio.

## User flow

Following the layout the user last specified explicitly, the Action Lab is a standalone page `#/actions` within the same training studio, sitting alongside the training workbench in the left navigation and the mobile bottom bar. The home page keeps a browse entry. The recipe library initially contains the existing flat-ground walking, rough terrain and single-leg balance recipes, and supports search, filtering by category, as well as previews and text descriptions. After choosing a recipe, the user enters the existing new-training drawer; no separate product or server is built.

For single-leg balance, the user chooses the support foot (the robot's own left/right), how high to lift the other foot and how long to hold; advanced training parameters remain collapsed. Recipe cards read category, tags, preview type, source and verification status from the backend `catalog` metadata; only the 3D preview currently being viewed is loaded at a time, to avoid creating many WebGL scenes at once as the number of recipes grows. Text descriptions are likewise a full card type; not every recipe is required to have a video.

The 3D target illustration shows the left and right feet and the foot-lift direction, and is labeled “目标示意 · 非训练结果” (Target illustration · not a training result). The drawing does not claim exact kinematics or balance verification. Created experiments store the action parameters, which are read-only; copying an experiment or promoting a smoke run to full training keeps the parameters. Changing the action target requires a new matching smoke run. Actual policy performance only comes from the physics evaluation video of the selected checkpoint.

## Fixed interface

- Recipe `hd1910-single-leg`, task `Mjlab-Balance-Flat-MicroDuck-HD1910`, experiment directory `microduck_hd1910_balance`.
- Requests and records gain a `skill` object: `support_side` is `left/right`; `lift_height_m` is 0.005–0.02, default 0.01; `hold_seconds` is 1–5, default 3. Reject boolean numbers, non-finite values, unknown fields, and walking recipes that carry skill parameters.
- Recipe metadata gains `experiment_name`; the single-leg recipe provides `skill_defaults` and `skill_limits`, and the front end shows centimeters and seconds according to the backend ranges. New recipes default to 256 environments, 1000 iterations, saving every 25 iterations; smoke runs are still forced to 64 environments, 5 iterations, saving every iteration.
- Action parameters are included in smoke-run matching, resume, export provenance and evaluation. Old walking records without `skill` remain compatible; arbitrary task names, paths or command fragments are not accepted.
- Each recipe's log directory is taken from the server-side whitelist; training log detection, PT scanning, resume paths and evaluation/export checkpoint validation must all be consistent.

## Training engine

Deep-copy from the HD1910 velocity configuration, keeping Feetech BAM, the 61-dim observation, 14-dim action, 50 Hz, NaN guards and matching physics randomization. Add dedicated commands, rewards and phase progress; remove gait rewards/curricula that would counteract the foot lift or rewrite the commands. For left/right, only the selected support foot is trained; no unconditional mirror loss is enabled.

The action consists of: stabilize, lift the foot, hold, put the foot down, and end stable on both feet; the full cycle and parameters are fixed per experiment. Rewards and success judgment must check the correct support foot, foot-lift height, torso attitude, slipping, forbidden body ground contact and recovery after foot-down, to prevent a fall with a foot off the ground from gaming the reward. The new command semantics are recorded separately; it cannot be claimed that the old robot runtime can use it directly just because the input and output dimensions are the same.

The training CLI passes parameters via typed command configuration fields; evaluation and export apply the saved parameters with the same validation function before creating the environment. Keep the existing normalized export path, do not change the dependency lock file, and do not change the behavior of the existing walking recipes.

## Acceptance check

1. CPU configuration/reward tests: ranges, left/right mapping, phase boundaries, termination/success gating, finite values, the 61/14/50 contract, isolation of the old factory; check that the candidate poses and geometry can support the target.
2. Service regression: matching smoke runs, old records, recipe-isolated paths, invalid parameters, pause/continued training, export parameters and provenance.
3. Front end: drafts, unit conversion, left/right switching, smoke-run gating, copying, result display and mobile layout. The target illustration must not become evaluation evidence.
4. Real GPU: 64 environments, 5 iterations, save PT, multiple evaluations over full cycles, real videos, export ONNX and check inference. Record the actual number of successes; a successful training exit is not the same as a successful action.
5. Integrate back into the stable workspace, keeping existing experiments and service state. Restart the service only when there are no active tasks.

## Boundaries

The first version completes a configurable training loop for single-leg balance. Jumping and precise turning in place are not shown as runnable templates. Long-training convergence and real-robot performance are reported based on actual evidence, and are not substituted by the illustrative animation or a passing smoke run.

<a id="后续定位社区动作配方库"></a>

## Future positioning: community action recipe library

The user further clarified: the Action Lab should host action tasks written by community authors, letting ordinary users choose and train them without requiring everyone to write reward code from scratch. The first-version single-leg balance is a complete example of this flow. Community publishing, review, download and automatic installation are not implemented yet.

A planned recipe should include: author and source, license, recipe version, compatible hardware and engine version, action description, adjustable parameters and ranges, training rules, success and failure criteria, evaluation conditions and example videos. Parameters should flow into training, continued training, evaluation and export alike, and users keep their own experiment records after changing the target.

The contribution flow goes through repo PRs first: the author implements the task and tests → the maintainer reviews compatibility and verification evidence → it is included as a selectable recipe → users do a smoke run and then full training. Tasks are still registered via the server-side whitelist; future pages must not treat arbitrary uploaded scripts directly as already-reviewed built-in capabilities.

A recipe card's verification status needs to express separately "training pipeline passes", "completes the action under specified conditions" and "verified on the real robot". One successful exit or a few smoke-run iterations cannot be upgraded to "the action has been learned". Existing policy weights are an optional, separate artifact, labeled with their source and corresponding target, and are not to be conflated with training recipes.

Later, the page will render cards and parameter forms from recipe metadata, gradually reducing hardcoded action names. First stabilize the recipe conventions and the contribution example, then build a sharing entry; this round did not create accounts, an upload service or a community backend.
