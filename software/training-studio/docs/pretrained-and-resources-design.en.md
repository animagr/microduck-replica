# Pretrained model catalog and execution-host resources · 2026-10-23

**English** · [简体中文](pretrained-and-resources-design.md)

The user asked to add kissqy's trained models to the Action Lab and to review the official V8; the training details need to show the GPU model, temperature, VRAM, CPU and memory, as well as training progress. Following the already-decided standalone Action Lab and web console style, this is split into two changes that can each pass an acceptance check independently.

## Pretrained models

The Action Lab distinguishes training recipes from pretrained models. A recipe creates a new experiment; a model entry shows the source, version, hardware, purpose, format, download location and verification scope of existing weights. They can be filtered by source and keyword, and the details explain the current capabilities. The UI does not disguise external weights as experiments completed locally.

The official source is pinned to `pollen-robotics/microduck-policies` V8 (`665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448`), whose manifest specifies XL330, 61 inputs, 14 outputs, 50 Hz. kissqy is pinned to the V167 release manifest at `525a215a19397767a073b782f57e97cf53683761`, HD1910, including the ONNX files visible in the source and the weights inside the release package. Model download links point to the original publisher, keeping attribution, version and license information; models bound by personal non-commercial licenses are not redistributed.

What is integrated now is a catalog of ready-made models that can be browsed and downloaded. An ONNX file has no full PPO optimizer or training checkpoint, so the existing "continue training" cannot be used; a plain 61→14 shape also does not prove compatibility of commands, HOME or servo dynamics. The page states clearly that local evaluation/continued training is not integrated, and it does not overwrite the current robot policy. Adding more entries only requires extending the server-side manifest.

## Current execution-host resources

The training details gain a resource panel, fetched through a separate read-only `/api/resources`. A background task starts lazily and caches system readings about every 3 seconds; GPU probing has a timeout, does not take the training lock and does not affect the polling of the existing `/api/state`. GPUs support multiple cards, showing model, load, temperature and VRAM; the CPU shows model, cores, utilization and readable temperature; memory shows used/total. Iterations and throughput continue to come from the actual training logs.

These are overall current readings of the execution host. WSL CPU/memory reflect what the subsystem can see, and the GPU includes other processes; viewing a finished experiment also cannot be taken as historical usage. Missing temperatures or unsupported driver fields return null with a reason; the initial sample and a lost connection show "sampling" and "data stale" respectively, without faking zero usage. The demo environment does not generate fictitious hardware readings.

## Implementation and acceptance check

1. Add `training_studio/pretrained.py` and a version-controlled model manifest; test unique IDs, pinned sources, HTTPS, format/hardware, non-resumability and returning copies. Wire it into `state.pretrained_models`.
2. Add `training_studio/resources.py` and the API; first test CSV empty values/multiple GPUs, CPU deltas, memory, unavailable temperature, timeouts and caching/shutdown, then implement the probes. Do a real read of the local WSL NVIDIA status.
3. Add `web/pretrained.js` and `web/resources.js`, and update the action library and RunView; test the query and formatting logic, and do the acceptance check on desktop and at 390/320 widths for source filtering, details, external links, empty values, disconnects and resource display.
4. After independent review, Python/Node regressions and browser tests pass, merge into the branch in use. Restart only when the original service has no active tasks, keeping all experiments. Do not trigger training, model deployment or paid cloud operations.
