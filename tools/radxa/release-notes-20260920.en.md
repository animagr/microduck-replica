**English** · [简体中文](release-notes-20260920.md)

> **This Release was withdrawn on 2026-10-21** (too old). For a ready-made card, use the [replica image](https://github.com/fanhao375/microduck-replica/releases/latest). The release notes from that time are kept below for the record.

> **2026-09-29 first-login erratum: log in with `root` / `1234` first.** The public image does not contain `duck` yet; only after you complete the Armbian first-login wizard are `duck` / `duck1234` created and the root password changed to `duck1234`. This was confirmed by a read-only inspection of the original public image's account database and first-login script. The earlier statement that "you log in directly as duck the first time, and root's initial password is the same" was wrong. Change both default passwords immediately after completing the wizard.
>
> **2026-09-28 networking erratum:** the old card-building script left out the DHCP configuration for `wlan0`. Even with the correct WiFi name and password, the board may fail to get an IPv4 address, so SSH cannot find the board. The repo script has been fixed; cards that are already flashed can have the configuration added as described below, with no need to reflash just for this.
>
> **The `.img.xz` image and `sha256.txt` in this Release are still the original files from Sep 20 and do not include this fix.** This update changes the Release notes, the accompanying user guide and the card-building script in the repo. The `/root/先连WiFi.txt` (connect to WiFi first) file on the card contains the old instructions; follow the updated guide instead. A personal image with the fix applied, on my own board, was tested on real hardware: it obtained a DHCP address and allowed SSH login, and `networkctl` confirmed that the new configuration was in use. This is a verification on a single device; it does not mean the public image has been replaced or that every connectivity loss has been solved.

This is a community image made for the boot-compatibility problems previously seen on my Radxa Zero 3W V1.12 (AIC8800 WiFi): it uses the kernel and system packages of Armbian 26.2.1 Trixie vendor 6.1.115 minimal, replaces the bootloader with Radxa's, and adjusts the boot, login and network configuration. Different board batches need to be verified separately.

There is also a separate 20260929 DHCP-fix candidate release; the old files on this page are kept. The candidate has only been checked offline; the new build has not been flashed to a card and tested on real hardware. The offline check also found that the old release ships pre-generated SSH host keys; for old cards, regenerate them from a local terminal as described in the [updated user guide](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/%E9%95%9C%E5%83%8F%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md#%E6%97%A7%E7%89%88%E5%8D%A1%E9%87%8D%E6%96%B0%E7%94%9F%E6%88%90-ssh-%E4%B8%BB%E6%9C%BA%E5%AF%86%E9%92%A5); no reflash needed.

**A green LED double-blinking can be the normal `heartbeat`; you cannot conclude from the blinking alone that boot failed or that the image is corrupted.** The base image also does not mean the full robot software is installed; networking, the camera and servo control each need their own acceptance check.

### Which file to download

| File | Description |
|---|---|
| `armbian-26.2.1-zero3w-v1.12-bootfix-20260920.img.xz` | The original public image, without a WiFi name/password; after flashing you must configure WiFi and add DHCP. Can be written to a card with Rufus / balenaEtcher / Armbian Imager |
| `sha256.txt` | SHA256 of the original image above, unchanged |
| `radxa-zero3w-image-guide-zh.md` | Updated 2026-09-29: first root login, accounts after the wizard, DHCP fix for old cards, changing WiFi, USB ports and power; content kept in sync with the [repo user guide](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/%E9%95%9C%E5%83%8F%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md) |

SHA256 of the original `.img.xz` file:

```text
4de8a355d3d9180e465af486c409e9b3e4ac82c0e241dc73d4fc0f0db7a67579
```

### First flash and login

1. Verify the image, then flash it to a card of at least 8 GB.
2. Use a **USB cable that carries data** to connect the board's **`5V IN / USB_OTG` (USB 2.0) port** to the computer, with the board powered by USB alone. The other **USB 3.0 Host** port is for peripherals; it is not the port for connecting the computer to the onboard USB serial console.
3. On first boot, wait about 2–3 minutes; once the board has booted normally and loaded the USB gadget, a COM port should appear on the computer. Set the serial tool to **115200 8N1**, press Enter, and log in the first time as **`root` / `1234`**. Only after you complete the Armbian wizard (you can choose `bash` as the shell) does `duck` / `duck1234` exist and the root password become `duck1234`. While still in the root terminal, run `passwd` and `passwd duck` to change both passwords, then use duck for everyday logins. If the wizard is interrupted, the accounts may be in an intermediate state; log in again with the root password you already set and finish the wizard, no reflash needed. If no COM port appears, check the port, the data cable and the power first; do not rely on the green LED alone.
4. The public image has no preset WiFi. Configure wireless authentication and DHCP following "First time online, or changing WiFi" in [Section 4 of the user guide](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/%E9%95%9C%E5%83%8F%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md#4-%E8%BF%9E-wifi); the base image does not have NetworkManager installed, so you cannot use `nmtui` directly.

**HAT power reminder:** the 5V on the HAT / 40-pin header and the VBUS of USB_OTG are on the same power net, so do not power the board from the HAT and from an ordinary computer USB data cable at the same time. If you need to switch to the USB serial console, shut down properly first, disconnect the HAT input, then switch to USB-only power; when debugging under HAT power, prefer WiFi + SSH.

### Old card with WiFi already filled in: only add DHCP

The following applies to this project's base image that still uses `wpa_supplicant` + `systemd-networkd`. If you have since migrated to NetworkManager, use it to check the connection and automatic IPv4 configuration instead, and do not enable two wireless management services at the same time.

Log in via the USB serial console or a local terminal, keep the existing WiFi name and password, and run:

```bash
sudo mkdir -p /etc/systemd/network
sudo tee /etc/systemd/network/25-wlan0.network >/dev/null <<'NETWORK'
[Match]
Name=wlan0

[Network]
DHCP=ipv4
NETWORK
sudo chmod 644 /etc/systemd/network/25-wlan0.network
sudo systemctl enable --now systemd-networkd wpa_supplicant@wlan0
sudo networkctl reload
sudo networkctl reconfigure wlan0
```

Wait about 30 seconds, then check:

```bash
sudo wpa_cli -i wlan0 status   # should show wpa_state=COMPLETED
ip -4 a show wlan0            # should show an IPv4 address assigned by the router
ip -4 route                   # should show a default route
networkctl status wlan0       # shows the matched configuration and DHCP status
```

The default netplan only matches the wired interface; `wpa_supplicant` handles wireless authentication, and the `25-wlan0.network` added here makes `systemd-networkd` request an IPv4 address for the wireless interface. **Filling in the WiFi password alone does not mean DHCP is configured.**

If it still does not work, check in this order: does `wlan0` exist → has wireless authentication completed → has an IPv4 address and a default route been obtained → are the computer and the board on the same LAN where they can reach each other. If authentication has not completed, check the network name, password, signal and router mode first; this patch cannot replace those checks. Detailed diagnostic commands are in the accompanying guide.

### Changing computer / changing WiFi: do I need to reflash?

- **Changing computer does not require a reflash.** As long as the computer and the board are on the same LAN and can reach each other, log in with `ssh duck@<board IP>`; guest networks or AP isolation may block traffic between devices.
- **Changing WiFi requires filling in the new network's name and password, but no reflash.** Reconfigure from the USB serial console or a local terminal following Section 4 of the guide; restarting the wireless service drops any existing SSH session over WiFi.
- The DHCP address may change; find the IP again with `ip -4 a show wlan0` on the board or in the router's device list, rather than reusing an old address.
- If you want to preset your own WiFi before flashing, use the corrected [card-building script and configuration notes](https://github.com/fanhao375/microduck-replica/tree/master/tools/radxa). An image you generate yourself with a password inside is for personal use only; do not upload it publicly.

The wireless credentials on this image are not in netplan, so **do not blindly follow the upstream `migrate-network.sh` → reboot procedure**. Keep the currently working connection first; before migrating, adapt it to import the credentials, retire the old services and recover from a lost connection. Otherwise you may lose connectivity because network management services compete with each other or the password was not imported.

### Boot, peripherals and board batches

The original image swaps in the `u-boot-rk2410` bootloader and boots via `extlinux.conf`; it configures the `uart2-m0` and `dwc3-peripheral` overlays and moves the login console from the servo serial port to the USB gadget. These serve the `/dev/ttyS2` servo serial port and USB serial login respectively; they do not mean the robot control software is installed or the hardware has passed its acceptance check.

On 2026-09-28 my board completed a read-only HAT communication test; after that I fixed sync read to file replies by ID and deployed web debug console 0.15.4. Holding an existing pose for about 64 seconds, all 14 servos had 3000/3000 valid status reads with zero errors in the window, at a target of 50 Hz and an actual rate of about 46.87 Hz. At other times there are still occasional missing replies; protection, motion and the full control loop have not passed their acceptance checks, and this separately deployed debug console is not in this image. See the [3000-round summary](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/50Hz%E4%BF%9D%E6%8C%81%E5%A7%BF%E5%8A%BF%E8%AF%BB%E7%8A%B6%E6%80%81-20260928.md).

A community member reported getting their V1.12J / AIC8800DS2 board working with **B1 bootloader + B1 DTB + Armbian 6.1.115 kernel + Trixie system**; this project has not independently verified that combination. You cannot assume the DTB is interchangeable just because both kernels are 6.1; after swapping the DTB you also need to check the serial and USB overlays. Related experience and operating notes are in Section 6 of the guide.

The 2026-09-28 camera test was done on **Radxa's official B1**: after adjusting the ribbon cable orientation/contact, the IMX219 was detected and a 40-frame short test completed; a retest on this project's Armbian image has not been done yet. See the [wiring diagram and debug log](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/%E6%91%84%E5%83%8F%E5%A4%B4%E8%B0%83%E8%AF%95%E8%AE%B0%E5%BD%95-20260928.md).

### Sources and licenses

- Base: [Armbian official Radxa Zero 3 image](https://www.armbian.com/radxa-zero-3/), 26.2.1 Trixie vendor 6.1.115 minimal, GPL and each package's own license.
- Bootloader: Radxa [`u-boot-rk2410`](https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/) `2017.09-64-39cd993`, GPL-2.0.
- See [`build-armbian-card.sh`](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/build-armbian-card.sh) for the card-building steps; the current script includes the fixes for DHCP, the first-login notes and SSH host key handling, so its output will not be byte-for-byte identical to the old image kept on this page.

This is a community-made image, not an official Armbian or Radxa release. For problems, open an [issue](https://github.com/fanhao375/microduck-replica/issues) in this repo with your board version and logs with personal information redacted.
