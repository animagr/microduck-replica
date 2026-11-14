# Action Lab Implementation Plan

**English** · [简体中文](action-lab-plan.md)

> **For agentic workers:** Use subagent-driven-development to implement this plan task by task, with independent specification and quality reviews.

**Goal:** Users can set a single-leg balance target on the existing training page, and train, evaluate, save and export with the real engine.

**Architecture:** A dedicated HD1910 task handles the physical action; the service passes the bounded skill parameters into training, evaluation and export and archives them; the existing Preact drawer gains visual configuration. The recipe whitelist uniformly determines experiment paths, and all process-ownership rules follow the existing service.

**Tech Stack:** Python 3.12 stdlib service, mjlab 1.3.0 / rsl-rl 5.0.1, WSL2 CUDA, Preact/Three.js, unittest/pytest/Node/Playwright.

## 1. Environment and baseline

- [x] Create a separate workspace from `9d0fe05`, keeping the stable service on 8094.
- [x] Windows backend: 56 tests (53 passed, 3 skipped); Node: 11 tests passed.
- [x] Offline locked virtual environment `/root/.cache/microduck-action-lab-20261023`, editable install pointing to the new workspace; the stable environment is not changed.

## 2. New balance engine

Files: `software/training/src/mjlab_microduck/tasks/microduck_balance_env_cfg.py`, `tasks/mdp.py`, `tasks/__init__.py`, `scripts/export.py`; new `tests/test_balance_cfg.py`, `tests/test_balance_mdp.py`.

- [x] First write failing test cases for configuration, phases, left/right foot, invalid parameters and success judgment, and run them to confirm they fail because the new task is missing.
- [x] Implement the dedicated command, the parameter-application function, rewards and success counting, the correct HD1910 physics configuration and registration. The fields are fixed as `support_side`, `lift_height_m`, `hold_seconds`.
- [x] Verify that the parameters change the environment configuration through real CLI parsing, and that evaluation/export use the same parameter-application function.
- [x] Run the CPU tests and geometry/pose measurements, and record the feasibility boundaries of the target. The new tests should verify that lifting a foot after falling cannot succeed, that left/right switching is correct, and that the foot still has to be put down after the hold is completed.

## 3. Recipes and parameter plumbing in the service

Files: `training_studio/config.py`, `commands.py`, `service.py`, `environment.py`, `evaluate.py`; new `tests/test_skills.py`.

- [x] Use a real CPU demo subprocess to test that changing skill parameters loses eligibility for full training; old walking records still match; no process is created when parameters are invalid.
- [x] `validate_skill(recipe_id, value)` returns normalized parameters or None; `experiment_for(run)` only looks up the server-side whitelist and validates the task id; all log/checkpoint paths switch to using it.
- [x] New records, resume, provenance ZIP and evaluation parameters all store a consistent skill; real commands use only fixed flags and validated numeric values.
- [x] Evaluation covers the full cycle and multiple attempts, saving each result and per-item statistics; the read summary is shown under the selected checkpoint, and failure results must also be visible.
- [x] Run the full Windows/WSL backend tests and the engine parameter-passing integration tests.

## 4. No-code operation on the same page

Files: `web/skillform.js`, `state.js`, `newrun.js`, `views.js`, `ui.js`, `styles.css`, `tests/state.test.mjs`.

- [x] First write Node tests for parameter normalization / smoke-run matching / unit conversion / summary.
- [x] Home-page Action Lab entry, the new recipe and basic skill controls, with ranges from the backend; keep a draft per recipe.
- [x] Reuse Duck3D to build a clearly labeled target illustration; kinematic centimeter values are not invented from the drawing. Show the full phase description and left/right foot text.
- [x] Fix the old hardcoding that displayed everything non-rough as flat ground; experiment details, copying, comparison and checkpoint evaluation all show the corresponding action target and results.
- [x] Browser tests at 1440/390 width: action settings, switching between old recipes, drafts, gating on parameter changes, parameter submission, details, and distinguishing real/demo results, with no overflow/page errors.

## 5. Real verification and delivery

- [x] Independent specification review, then independent code-quality review; fix concrete issues.
- [x] Isolated state for the new service; start a real balance smoke run 64×5 from the browser and check the logs, PT and action configuration YAML.
- [x] Evaluate multiple times over the full action cycle and actually play the videos; export ONNX and check inputs/outputs, finite values and PT/ONNX consistency.
- [x] If the smoke run only proves the pipeline, report the success rate clearly and keep the experiment template, without claiming the action has been learned; if the reward needs debugging, first look at the measured failures before changing it.
- [x] Update the usage guide and acceptance record, commit, then merge into the stable workspace; keep the user's other changes, and switch the service only after confirming there are no active tasks.
