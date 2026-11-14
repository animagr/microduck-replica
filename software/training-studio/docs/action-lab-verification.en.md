# Action Lab acceptance check · 2026-10-23

**English** · [简体中文](action-lab-verification.md)

The first version integrates the experimental HD1910 single-leg balance into the existing training studio: choose the support foot, foot-lift height and hold time, and use the existing training, pause/resume, checkpoint, evaluation and export flows. Later, at the user's request, a standalone `#/actions` Action Lab was added, containing the current three built-in recipes. Community publishing and automatic installation are not implemented yet.

## Acceptance check of the standalone action library page

Catalog metadata commit `6ca4d5f` and UI commit `109083a` have been merged into `studio-dev` via `a8e498f`; the entry point is still the original 8094 service. The new content only touches the catalog, navigation and docs, and does not change the verified training engine.

- Node state and parameter tests updated to **21/21**; backend action recipe regression **13/13**.
- Edge / Playwright checked, on both an isolated demo service and the original real service: the workbench entry, left navigation, direct access, refresh, browser forward/back, as well as categories, multi-keyword search and clearing a no-results state.
- The three recipes were verified with the model, text and single-leg target illustration respectively. The catalog itself does not create WebGL views; opening a preview loads only one view, which is released on close; close, Escape, Tab focus cycling and focus restoration all pass.
- Both the card and the details entry open the training settings of the correct recipe, defaulting to a smoke run. The entire browse-and-select acceptance check did not send any POST request that creates a task.
- Checked widths of 1440, 768, 390 and 320 pixels. The five-item mobile navigation has no horizontal overflow, and the bottom actions of the preview and training drawers are visible. Geometry assertions wait for the drawer entrance animation to finish; screenshots were checked manually.
- The original service confirmed the GPU environment is ready and there are no active tasks; the old flat-ground experiment `caa6a1c5de10` and the single-leg experiment `a930fbbab951` are kept, the single-leg result is still 0/8, and the actual video plays. Page errors and failed resources are both zero.
- Independent code review has no remaining P1/P2. This time GPU training was not started again, and no community online publishing feature was added.

The evidence is in the outer `本地记录/training-action-lab-20261023/catalog-browser.mjs` (`本地记录` = local records), `catalog-validation/` and `catalog-validation-stable/`, including reports and desktop and mobile screenshots. For the inclusion process see [Contributing recipes](recipe-contribution.en.md).

## Verification scope

- Windows backend, 73 tests: 70 passed, 3 Linux-only tests skipped; WSL backend 73/73 passed.
- Node state and parameter tests 18/18 passed.
- Engine parameter, configuration, foot-sole geometry, HD1910 and NaN regressions 46/46 passed.
- The real CUDA test with 4 environments and 30 steps passed: right-foot command, 61-dim actor, 14-dim action, 50 Hz, finite critic/rewards, partial resets work.
- Edge / Playwright at 1440 and 390 width checked target editing, centimeter conversion, independent per-recipe drafts, copying, smoke-run gating after parameter changes, demo-evaluation labeling and actual replay. No page errors or horizontal overflow.
- The independent specification and code reviews found an evaluation initialization random-seed issue, which was fixed and retested; no remaining P1/P2.

The CPU tests show tuple/list type warnings from the original configuration, and the GPU tests show a notice that actuator names also match a site; neither prevented execution. ONNX Runtime's CPU inference prints a WSL GPU device probing warning, but CPU inference actually completes; these notices cannot be taken as evidence of GPU training failure.

## Real training and artifacts

Hardware: RTX 5060 Ti 16 GB, WSL2 Ubuntu 22.04, torch 2.9.1+cu128, mjlab 1.3.0, rsl-rl-lib 5.0.1. The dependency lock file was not changed.

| Experiment | Target | Result |
| --- | --- | --- |
| `1eddca56e439`, isolated service | Left-foot support, 1 cm foot lift, 3-second hold | 64 environments × 5 iterations, 7,680 samples, 5 PTs; actual evaluation and ONNX export completed |
| `a930fbbab951`, original 8094 service | Right-foot support, 0.5 cm foot lift, 1-second hold | 64 environments × 5 iterations, 7,680 samples, 28.9 seconds including startup, 5 PTs; actual evaluation, close-up video and export completed |

Final acceptance check of the official-entry experiment `a930fbbab951`:

- All 8 attempts triggered a physical failure early, **0/8 successes**, 250 steps in total. Each attempt's budget covers the full 4.5-second cycle; failures end early, rather than each attempt being cut to a fixed short video.
- Video 960×540, 50 FPS, 250 frames, 5 seconds, keeping all 8 attempts; it played successfully in the browser. The camera was moved from the default 3 m to 0.7 m so the feet can be seen clearly.
- Initialization seed 42; per-attempt reset seeds 42–49. In two evaluations after the fix, the termination step of each attempt was identical, and the mean reward differed only by a floating-point difference of about 3.43e-8. The 8 attempts share one initialization voltage/resistance sample, which does not cover the full hardware randomization distribution.
- All 76 tensors in the checkpoint are finite, and the actor weights and observation normalization load successfully in strict mode.
- ONNX checker and CPU inference with 32 sets of zero/random inputs passed, with a 61-dim input and 14-dim output; the maximum absolute PT/ONNX difference is `4.0531158447265625e-6`, passing `atol=1e-5, rtol=1e-4`.
- The saved environment YAML, run.skill, skill.json, evaluation summary, ONNX command metadata and export ZIP all have exactly the same target.
- The export contract explicitly marks `runtime_adapter_required=true` and `hardware_validated=false`. Identical input and output dimensions do not mean it can be used directly with the original walking deployment side.

SHA-256 of the final representative artifacts:

- `model_4.pt`: `b785059649269a9f18065e18050122a3acd571d06f5a96b387d8883cffab3b1e`
- `policy.onnx`: `2076ce787aaf20fc1b9c3dd83eba229d3d6dae09e6471739e7701c5b72e3c878`
- `rl-video-step-0.mp4`: `f547716356ba95f66bb76bef357277fda04151fdc054ab8a3691d3d0a90d8da6`

## Integration and evidence

Developed in a separate workspace starting from `9d0fe05`; the engine `2e5a3f1`, the startup random-seed fix `9261167` and the close-up camera fix `a168cc2` have been merged into `studio-dev`. Other commits for the web console status bar and the untracked files in `software/studio/docs/` were kept at the same time. The original service was restarted only when it had no active tasks, continues to use the original state directory, and the old walking experiment `caa6a1c5de10` is readable. The temporary 8095/8096 services have been shut down, and the user continues to use 8094.

The outer `本地记录/training-action-lab-20261023/` holds the browser scripts, run logs, screenshots and isolated verification; `stable-validation/` holds the check scripts, artifact reports and final screenshots for the official entry. The real run.json/artifacts are still stored in the original `本地记录/training-local-20261023/state/runs/a930fbbab951/`. Models and videos were not added to Git.

The Git paths of the Windows worktree cannot be resolved directly by WSL Git, so the run record's git_commit may still be null; the SHA-256 of the source files is kept. New records already store the actually installed version separately from the platform candidate version in the lock file, to avoid writing a cu129 lock-file candidate as the actually installed version.

## Conclusion boundaries

This round proves that a configurable target flows through real training, saving, full-cycle attempts, actual replay and export. **It does not prove that the policy has learned single-leg balance**. The model geometry can reach a 5–20 mm foot lift, but reliable static balance has not been proven; the short-training failure is shown truthfully.

Long-training convergence, real long-training pause/resume for the new task, cloud platforms and real-robot deployment still need to be verified separately. The existing pause/resume regressions pass in the service tests and should not be described as having completed these additional hardware tests. Jumping, precise turning in place, video imitation and community recipe publishing are still outside the currently runnable scope.
