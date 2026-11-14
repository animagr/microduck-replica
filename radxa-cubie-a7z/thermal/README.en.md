# A7Z low-temperature throttling fix

**English** · [简体中文](README.md)

Applies to: Cubie A7Z, kernel `5.15.147-21-a733`.

The board device tree in use changes the first CPU trip to `active`, leaving only one
`passive` trip, which makes `power_allocator` keep allocating power even at low temperature. When the big cores are idle
and request zero power, it allocates zero power even with ample budget, which then caps the maximum frequency at
416 MHz. The original perf evidence is in `../control/evidence/thermal-perf-20261106.txt` on the local machine.

This fix only changes the governor of `cpul_thermal_zone` and `cpub_thermal_zone` to
the kernel's built-in `step_wise`. The fan binding, the 60°C active/passive trip, the 2°C hysteresis,
the 110°C critical trip and thermal enabled are kept; it does not write frequencies, cooling states or simulated temperatures.
Other thermal zones keep their original policy.

The script locates zones by type and verifies the model, kernel, trips and CPU cooling bindings.
The first application saves the original policy; if the write or the low-temperature release verification fails, the previous policy is restored.
A systemd oneshot applies it at boot, and the kernel continues to handle thermal management at runtime.

Local tests:

```sh
cd radxa-cubie-a7z/thermal
python3 -m unittest -v test_thermal_policy
sh -n install.sh
```

On the board, put these three runtime files in the same directory and install:

```sh
sudo sh install.sh
python3 /usr/local/lib/cubie-thermal-policy/thermal_policy.py --check
```

Roll back to the policy from before the first application:

```sh
sudo systemctl disable --now cubie-thermal-policy.service
sudo python3 /usr/local/lib/cubie-thermal-policy/thermal_policy.py --restore
```

Rolling back restores the original `power_allocator`, which has the low-temperature throttling problem. This fix does not restart or change
robotd, Studio, the serial port, the servos or the calibration configuration; persistence across boots must be verified at a later actual reboot.

## 2026-11-06 on-board verification

- The same set of 9 tests was run on the local machine and on the board, and all passed; the SHA-256 of the deployed script matches the local one.
- The `cubie-thermal-policy.service` service is enabled, its result is success, and both CPU zones are `step_wise`.
- 150 samples over 30 seconds of passive sampling: CPU cooling was always 0, and the maximum allowed frequency of both clusters always equaled their respective hardware limits; instantaneous frequency still varied normally with load.
- With `robotd --read-only` confirmed, a time-limited 15-second load test was run on CPU6/7; the big cores reached 2002 MHz, with a maximum temperature of 63.86°C.
- Above 60°C, 24 throttled samples actually occurred, with the cap dropping to 1716–1950 MHz; after the load ended, the temperature fell to 40.796°C, the cap returned to 2002 MHz, cooling returned to 0, and all load processes exited.
- The readback of thermal enabled, the 60°C trip and the 110°C critical configuration for both CPU zones kept their original values. The device was not actually heated to 110°C, nor rebooted for the verification.

Local evidence: `../control/evidence/thermal-fix-idle-20261106.json`,
`thermal-fix-load-20261106.json` and `thermal-fix-20261106.summary.json`.
