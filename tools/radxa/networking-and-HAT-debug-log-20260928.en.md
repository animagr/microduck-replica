# 2026-09-28: DHCP fix and read-only HAT servo hardware test

**English** · [简体中文](联网与HAT调试记录-20260928.md)

The dates in this log follow the debugging computer; the board's system time has not been confirmed to be synchronized, so its log timestamps are not used to infer the actual date.

## Networking conclusion

The earlier Sep 20 image configured `wpa_supplicant` wireless authentication, but the default netplan only matches the wired interface and no DHCP was configured for `wlan0`. The fix adds `/etc/systemd/network/25-wlan0.network`:

```ini
[Match]
Name=wlan0

[Network]
DHCP=ipv4
```

Hardware test on my personal image:

- Logged in successfully over WiFi SSH; the hostname is `radxa-zero3`.
- The system is Armbian 26.2.1 Trixie, kernel `6.1.115-vendor-rk35xx`.
- `networkctl status wlan0` shows `Network File: /etc/systemd/network/25-wlan0.network`, state `routable (configured)` / `online`, with a DHCPv4 address and a default route.
- `systemd-networkd` and `wpa_supplicant@wlan0` are active; NetworkManager is not enabled; `systemctl --failed` shows no failed services.
- At the first check, the board had been up for about 6 minutes and the CPU temperature was about 56℃. The kernel log still has warnings about display/GPU, Ethernet and SD tuning during boot, so "SSH works" cannot be taken to mean all hardware is fine.

This proves the fix works with the current board and wireless environment. Repeated cold boots and compatibility with other routers have not been tested, so it cannot be claimed that all networking problems are solved. The old `.img.xz` and checksum in the public Release have not been replaced; users still need to add the configuration following the [user guide](image-user-guide.en.md).

## HAT serial test

The board's `/dev/ttyS2` exists and is not used by any process; `serial-getty@ttyS2` and `serial-getty@ttyFIQ0` are both masked. The test was done through the HAT at **1,000,000 baud**, allowing only the protocol's `PING` / `READ`; no register write, torque enable, calibration or motion commands were sent.

First read: 13 servos responded; IDs 23 and 34 did not. A full ID scan and later rechecks showed:

- Joint IDs `10–14`, `20–24` and `30–33` all respond, 14 servos in total.
- The user confirmed the mouth servo had been changed from 34 to 29, so 34 not responding is expected; for 29, testing stopped after only the firmware/model fields were identified.
- ID 23 (left knee) has intermittent missing replies; it cannot be judged broken or unconnected based on the first scan.

20 consecutive rounds reading feedback registers `56–70` from each of the 14 joint servos above:

| Target | Successes / attempts | Observations |
|---|---|---|
| ID 23, left knee | 18 / 20 | 2 times no frame header received; successful responses had status code 0 |
| The other 13 joint servos | 20 / 20 each | All status codes 0, no checksum or ID errors |

During the reads the voltage was about 7.4–7.5V and the temperature about 30–33℃. In the register snapshot, all 14 joint servos had the torque switch at 0, status bits at 0 and operating mode 4. This is a short read-only communication check, not a test of stability under load or in motion.

## To resolve before any motion

1. **ID 23's intermittent communication problem.** First shut down properly and disconnect the HAT input, then check this servo's plug, cable and power connection, and retest; if needed, compare against cables/ports that communicate normally. The current data alone cannot determine whether it is the cable, the contact, the device or bus timing.
2. **Unload protection configuration.** Register 19 read as `4` on all 14 joint servos. According to the Feetech memory table in this repo, this only sets the overheat protection bit; the voltage, overcurrent and overload unload bits are not set. This time it was only read, not modified. The thresholds also need to be checked against the specific model; simply turning the switches on does not mean the protection passes its acceptance check.
3. **Zero pose and mechanical range.** Whether the value 2048 corresponds to a safe assembly zero position for each joint still needs to be confirmed joint by joint; a large calibration offset alone does not prove an assembly error. After protection and communication are confirmed, do low-speed, small-range verification with the body supported.
4. **Other functions.** No `/dev/video*` appeared during this Armbian boot; camera configuration/retest is still pending. No policy model or robot actions were run this time.

## WiFi debug web page on the board

`servo-web` 0.15.2 was then deployed to `/home/duck/servo-web` on the board, the manual service `microduck-servo-web` was started, and the browser accesses it at `http://<board IP>:8080/`. The home page, model assets, `/api/info` and WebSocket live data were verified as working, with `fake=false` and the serial port `/dev/ttyS2`. The startup scan this time found 13 servos; ID 23 did not respond at that moment and was therefore not added to automatic polling, so the normal polling of the other 13 cannot be taken to mean ID 23 has recovered.

The startup parameters manage `20–24`, `30–33` and `10–14`, excluding the mouth servo 29 at the user's request. The service is not enabled to start at boot; this is a separate deployment on the board and is not packaged into the public base image. Commands:

```bash
sudo systemctl status microduck-servo-web --no-pager
sudo systemctl stop microduck-servo-web   # stop it before switching to another bus test tool
sudo systemctl start microduck-servo-web  # start manually when needed after the board reboots
```

Before deployment, the behavior where the debug console automatically released the speed/acceleration limits when connecting to the serial port was fixed; on startup 0.15.2 only scans and reads phase, and writes no motion settings. The protocol simulator's regression tests and self-checks all pass. The web page still has physical motion and calibration buttons; it is not a restricted read-only page. This acceptance check only accessed the page and read status, and did not trigger those buttons.

The raw read-only register snapshots and the consecutive-read statistics are saved in `Radxa-Zero3W/调试记录/` (debug log) on the debugging computer. The hardware test results cover only the devices and operations listed in this document.

## Follow-up: head connection and sync read fix

The user then moved HAT DATA to the ID 33 head servo and continued investigating the occasional timeouts. A knock-on misjudgment caused by sync read matching IDs in order was found and independently reproduced; it was fixed to file replies by the actual responding ID, and the board's debug console was updated to 0.15.3. After the fix, all 14 servos were read successfully within 200 frames on the web page; the raw reply-packet experiment still showed occasional missing replies from 31/33, so it cannot be concluded that the physical problem is gone. Power, common ground, interface circuitry and subsequent single-variable tests are in the [detailed investigation log](HAT-servo-intermittent-timeout-debug-20260928.en.md).
