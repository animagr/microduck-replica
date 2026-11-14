# Can servo IDs being offline stop the hotspot from appearing?

**English** · [简体中文](热点与主板型号排查.md)

> Real-hardware feedback, 2026-11-04: a Zero 3W running the 20261027 image, with the web software updated to 2026.10.3101, was moved to a place where the old Wi-Fi was unavailable, and neither the phone nor the computer could see the fallback hotspot. The system card did contain the network setup service and hotspot configuration, and the historical kernel log had recorded the AP starting; "preinstalled" alone cannot guarantee that recovery succeeds this time. After the site's Wi-Fi was added offline, the connection was restored, and the IMU and 15 servos read back normally. The network setup service logs from the time of the failure were not persisted, so the root cause cannot yet be attributed to a definite code path.

The source fix candidate targets three reproducible gaps: looping retries of the old network must not postpone the fallback indefinitely; a hotspot configuration already on disk is first loaded explicitly, keeping the user's password; and success is not reported when rebuilding, loading or reading back the activation state fails. The fallback decision is triggered after a cumulative 123 seconds offline, with additional time for device enumeration and command execution. The candidate's 37 dedicated tests have passed; it has not yet been deployed, the disconnection fallback has not been verified on real hardware, and the public image has not been updated.

If the old network is forgotten and the hotspot cannot be seen, first try to recover through an existing Bluetooth, SSH or serial port entry point; if none is available, a maintainer can add a known Wi-Fi configuration offline after confirming the disk's identity and backing up the calibration. Do not format the system card, and do not treat reflashing and recalibration as a required first step.

No. In the current image, `microduck-netcheck` manages Wi-Fi and the fallback hotspot; the service depends only on network management and the first-boot initialization order, not on `robotd`, servo IDs or the bus IMU being online. First-boot initialization creates the hotspot configuration first, then tries to detect an I²C IMU; it completes the hotspot configuration even if no IMU is found. Servos not connected, IDs not set and the wireless hotspot should be checked separately.

## First confirm whether it is a Zero 3W or a Zero 3E

[Radxa's official documentation](https://docs.radxa.com/en/zero/zero3/getting-started/preparation): **the Zero 3W has onboard Wi-Fi; the Zero 3E has no onboard Wi-Fi and connects via its Ethernet port.** If it really is a 3E, it cannot broadcast a Wi-Fi hotspot without added wireless hardware.

The current public replica image of this project mainly targets the Zero 3W; full boot, Ethernet port and external wireless adapter support on the Zero 3E have not been verified. Having the same RK3566 processor does not mean the kernel, device tree and network hardware are directly interchangeable. With a 3E, first check whether the system boots and recognizes the Ethernet port; when using an external wireless adapter, also confirm driver and AP mode support. The current network setup scripts use `wlan0`; if an external adapter shows up under a different interface name, that also needs separate adaptation.

## When you can log in to the system, read this information first

Run the following read-only commands over an already working Ethernet cable, SSH or serial terminal:

```sh
cat /proc/device-tree/model
nmcli -f DEVICE,TYPE,STATE,CONNECTION device
ip -br address
systemctl status microduck-firstboot microduck-netcheck NetworkManager --no-pager
journalctl -b -u microduck-firstboot -u microduck-netcheck -u NetworkManager --no-pager -n 80
```

- **A 3W has no `wlan0`**: first check the board batch, wireless driver and device tree; changing servo IDs will not make the wireless adapter appear.
- **`wlan0` is connected to your home Wi-Fi**: from a device on the same network, open port `8000` at the duck's current IP; the fallback hotspot not showing at the same time does not mean the system is offline.
- **`wlan0` exists but is not connected**: check the NetworkManager and `microduck-netcheck` logs to see whether it is trying a saved network, starting the hotspot or reporting a failure. First boot and connection attempts take time; you cannot judge from the LED alone.
- **The `Microduck-xxxx` hotspot has started**: connect your phone to that hotspot and open `http://10.42.0.1:8000/`. If you see a "no internet" notice you can still keep the connection; the hotspot is for local control.
- **A 3E has only the Ethernet port**: check whether the port got an IP, then access it from the same network; this project has not completed an acceptance check for this board model, so we cannot promise that swapping the card or a software update will solve all compatibility issues.

When sharing logs, the device/service status above is enough; do not publish Wi-Fi passwords, SSH private keys or AI keys.

## One-line answer for the group chat

"The hotspot does not depend on servo IDs. First confirm whether you are using a 3W or a 3E: the 3E has no onboard Wi-Fi, so without a wireless adapter there will be no hotspot; our current image mainly targets the 3W. Once the board model is confirmed, check the network interfaces and boot logs."
