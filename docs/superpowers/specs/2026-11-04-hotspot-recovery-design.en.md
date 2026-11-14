# Hotspot fallback recovery after network change

**English** · [简体中文](2026-11-04-hotspot-recovery-design.md)

The user's expectation is clear: when the old Wi-Fi is unavailable, the hotspot starts automatically, the phone configures a new network from a fixed local address, and on failure it can return to the hotspot. On 2026-11-04, the 20261027 real robot duck-658d showed no visible hotspot; both the computer and the phone confirmed it was not visible, and BLE advertising was visible but GATT/pairing did not connect. Logs from this card have not been obtained yet, so no particular source code gap can be identified as the root cause on this unit.

## Scope of this change

Keep the existing NetworkManager network setup method, fix the independently reproducible recovery gaps, and keep the existing network, servo, IMU and model configuration.

- When the old network keeps retrying between connecting/disconnected, the recovery timer must not be postponed indefinitely. Once the continuous window in which the network card is available but not connected to a network accumulates 123 seconds, the fallback decision is triggered; the actual calls and hotspot startup take additional time, so this is not a hard deadline for the broadcast being visible. A normal connection, the network card being unavailable, and a valid web network-change window reset the timer boundary.
- When there is no hotspot connection in memory, prefer loading the existing hotspot configuration from disk, keeping the hotspot password the user set. Only if the file is really missing is the hotspot-only branch of the existing first-time initialization script called.
- After rebuilding, explicitly notify NetworkManager to load the specified configuration; a failure to create, load or read back must not go on to report hotspot success, and is retried with the existing 60-second backoff.
- After `connection up` returns success, the local connection state must still be read back; this only confirms the local state and is not equivalent to the phone being able to discover the broadcast.
- The existing 45-second disconnected rule, the web-initiated network-change window, the existing hotspot client protection and the boundaries unrelated to IMU/servos remain in effect.

This change does not speculate about Wi-Fi driver, power supply or RF faults; it does not automatically reboot the board, reload the wireless module or change motion parameters. Offline checks of the local card use a read-only mount, and no fix is written to the card without on-site verification.

## Verification and delivery

First run the existing 28 netcheck tests, then add failing cases for the real state sequence and the configuration loading order, confirm the original code fails, and after the minimal fix retest the full image tests. The fix is kept in a separate workspace first, and a local pass is not recorded as a real-hardware fix or a released image.

The real-hardware acceptance check requires saving the raw network logs after network connectivity is restored, verifying network setup behavior when leaving the old network, with a wrong password, after reboot, and with no servos/no IMU, and having the phone confirm the hotspot is visible and the web page can be opened.
