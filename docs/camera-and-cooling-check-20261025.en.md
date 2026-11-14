# Camera and cooling check

**English** · [简体中文](摄像头与散热核对-20261025.md)

Date: 2026-10-25 (JST). The user wants to continue working on the camera, but is worried about the board heating up. This was a read-only check only; no real camera capture, video viewing or stress test was started, and no running service was modified.

## Current measurements

Evidence: artifacts/duck-camera-thermal-20261025/baseline.json in the workspace, recorded at 15:39 on the computer, observed for about 8.24 seconds.

| Item | Result read this time |
| --- | --- |
| Current physical cooling | The user then explicitly confirmed: no heatsink or fan installed yet; case ventilation, internal clearance and ambient temperature still to be checked |
| SoC temperature | Start 76.25°C, end 73.333°C |
| GPU temperature | 72.777 → 72.222°C |
| Combined busy ratio of all CPU cores | 6.97% |
| CPU frequency / maximum allowed frequency | Both 1.8 GHz when read, ondemand |
| Video configuration | media.source=test in /etc/robot/robotd.toml |
| mediad | active, automatic restart count 0, about 0.97% of one CPU core during the window |
| ToF service | inactive |
| System passive thermal trip points | 75°C and 85°C in the configuration; the critical point is listed separately and must not be used as a target for normal operation |

This is a short window, so long-term temperature stability cannot be concluded from it. A configuration set to the test source also cannot prove that a real camera is already working. The current readings do not show the CPU being limited to the 408 MHz seen in past failures, but the temperature is fairly close to the thermal control range.

## Past issues and what is different this time

The [pitfall log](../踩坑记录.md) recorded two independent phenomena on 10-11/12: when the camera/ToF were missing, services restarted repeatedly and GStreamer scanning maxed out the CPU; after stopping the related services, the sealed body still got hot enough to throttle. The current window did not reproduce the former high load. The user then confirmed that no heatsink or fan is installed yet, so adding cooling is a prerequisite for this round of continuous camera testing; case ventilation and ambient temperature still need to be checked.

## Suggested order

1. **First verify the benefit of airflow.** Keeping power, board position and running tasks as similar as possible, compare three cases: the original case, the case opened around the board, and an external USB fan blowing air in; do disassembly and reassembly with power off. For each group, record the ambient temperature and about 10 minutes of board temperature/frequency; do not draw conclusions from a single lowest temperature.
2. **Choose the permanent cooling based on the structure.** Prefer a low-profile lightweight heatsink that fits the SoC, or a small-fan solution with a clear inlet/outlet airflow path. First check the HAT, CPU orientation, height inside the case, wiring harness and range of motion, then decide the size and mounting method. Contact and airflow need to be checked; "a heatsink is installed" does not by itself mean it is effective. The fan's power supply and control method must be checked against the board/HAT interfaces; a motor cannot be driven directly from GPIO. Record the added mass and its position in the duck's profile.
3. **Then do a low-load verification with the real camera.** First confirm the sensor and actual frames, then confirm the encoding path; start from the lower frame-rate settings supported by the existing service, and progressively compare CPU, temperature, frequency and control cycle with preview off/on. The settings actually supported need to be checked against the currently installed version; do not promise up front that any resolution can be switched to directly.
4. **Finally decide the usual mode.** Only set up the video connection when the page is open/being viewed, and release it on exit; whether the underlying capture starts and stops on demand needs separate verification, since closing the browser connection does not mean the media pipeline has stopped. Avoiding useless capture, encoding or endless retries when nobody is watching or hardware is missing is a service policy still to be implemented/verified.

On the software side, prefer hardware H.264 encoding, and check whether pixel format conversion, on-board rotation and the like fall back to the CPU. Upstream has recorded cases where rotation/conversion broke zero-copy and significantly increased load; this is only a direction for later checks on this device, and cannot be used to assert that the currently installed version has that problem. References: [Microduck video bring-up notes](https://github.com/pollen-robotics/microduck/blob/main/docs/project/media-bringup.md), [Radxa ZERO 3W encoding capabilities](https://radxa.com/products/zeros/zero3w/).

## Completion criteria and delivery record

The goal is continuous preview for about 10 minutes alongside the existing control tasks, recording the real frame rate, temperature curve, thermal control state, and changes to gamepad/control cycles. An SoC temperature below about 70°C can be used as an engineering target with margin; this is not a manufacturer rating, nor a temperature that can be guaranteed before testing. After a fan is installed, do a separate R3 recording/voice command comparison to check the actual effect of fan noise and mounting vibration on the microphone, then decide the fan speed and mounting position.

This time, no physical cooling modification, real camera on the robot, or on-demand media service change was completed. Later software changes and image/update packaging are recorded under F09/F21 in the [software ledger](软件功能与升级总账.md); the hardware solution and test environment should also be recorded along with the results.
