# Radxa Zero 3W · An Armbian card that boots (image user guide)

**English** · [简体中文](镜像使用说明.md)

> **2026-10-21: the two September base images (20260920, 20260929) have been withdrawn from Releases**; they are too old. For a ready-made card, use the [replica image](https://github.com/fanhao375/microduck-replica/releases/latest): flash it and it works, with the main program, the walking model and Studio included. The card-building script in this folder is kept, and you can still build your own card with it; the mentions of those two Releases below are only historical records.

This image solves one problem I ran into earlier: **the official Armbian image I tested failed to boot on the Radxa Zero 3W V1.12** (no login, not findable on the LAN),
and it boots after swapping in Radxa's own bootloader. It keeps the official Armbian kernel and system packages and adjusts the bootloader plus the necessary boot, login and network configuration.

The public image **has no WiFi name or password**; on first boot, wait about 2–3 minutes, then log in via the USB serial console and configure the network. The waiting time and the green LED state are no substitute for actually verifying that you can log in.

- For: **Radxa Zero 3W V1.12** (the batch shipped from 2024-11 onward, with AIC8800D80 WiFi); for other batches see Section 6 below
- Base: Armbian 26.2.1 Trixie vendor kernel 6.1.115 minimal (official, unmodified)
- Why this happens and how it was tracked down: [pitfalls log](../../踩坑记录.md#软件)

> 2026-09-28 camera progress: after adjusting the ribbon cable orientation/contact, Radxa's official B1 detected the IMX219 and completed a 40-frame 1920×1080 short test; a retest on this project's image is planned, and the result on the official system cannot yet be taken as this image's camera acceptance check. See the [wiring diagram and full log](摄像头调试记录-20260928.md). A green LED double-blinking can be the normal `heartbeat` and cannot by itself be used to judge a boot failure.

> **2026-09-28 networking erratum:** the Sep 20 card-building script left out the DHCP configuration for `wlan0`. Saving the WiFi name and password only completes the authentication configuration, and the default netplan only covers the wired interface. The script has been fixed; for old cards, just add the configuration as described in Section 4, with no need to reflash just for this. The Release attachment `armbian-26.2.1-zero3w-v1.12-bootfix-20260920.img.xz` is still the original file with an unchanged SHA256 and **does not include this DHCP fix**; the `/root/先连WiFi.txt` (connect to WiFi first) file on the card also has the old instructions, so follow this document instead. A personal image with the fix applied, on my own board, was tested on real hardware: it obtained a DHCP address and allowed SSH login, and `networkctl` confirmed that the new configuration was in use; this does not mean the public image has been replaced, nor that every connectivity loss has been solved. See the [networking and HAT hardware test log](联网与HAT调试记录-20260928.md).

> **2026-09-29 update:** the first login must be `root / 1234`; see Section 3. A separate DHCP-fix candidate image is also provided, and the old release is kept; the candidate has been checked offline for DHCP, the first-login mechanism, file differences and privacy items, but **this new build has not yet been flashed to a card and tested on real hardware**. It is still a base system, without the robot runtime, the web debug console or the policy installed.

## 1. Differences from the official Armbian image

The main changes are as follows (DHCP is the 2026-09-28 script fix; old Release images need it added manually):

| What changed | Why |
|---|---|
| Bootloader replaced with Radxa `u-boot-rk2410` (`idbloader.img` @ sector 64, `u-boot.itb` @ sector 16384) | My earlier boot-compatibility problem was solved by this replacement; the exact package version and checksums are pinned in the card-building script |
| Writes `/boot/extlinux/extlinux.conf` | Radxa's U-Boot uses extlinux and does not read Armbian's `boot.scr` |
| Adds the `uart2-m0` and `dwc3-peripheral` overlays and puts the kernel console on `tty1` | The former exposes `/dev/ttyS2` (the serial port on the 40-pin header, used for the servos), the latter turns the OTG port into a serial port when plugged into a computer; kernel logs no longer go out onto the servo bus |
| Enables `g_serial` + a `ttyGS0` login console and disables the login consoles on `ttyS2` / `ttyFIQ0` | Plug into a computer and you can log in, so you can rescue the board even without a network; with `agetty` holding `ttyS2`, the servos never respond |
| Configures wireless authentication and `wlan0` DHCP | The Wi-Fi version presets the authentication info; both card-building modes write `25-wlan0.network`, filling the gap that the default netplan does not cover the wireless interface. Old images need it added manually |

## 2. Flashing the card

| Version | Difference |
|---|---|
| 20260920 original public release | Original file and SHA256 kept; DHCP has to be added manually, the notes on the card are inaccurate, and the SSH host keys need to be regenerated |
| 20260929 candidate | DHCP preset, first-login notes on the card corrected, pre-generated SSH host keys removed; verified offline only, not flashed and tested on real hardware |

Use any of Rufus, balenaEtcher or Armbian Imager, with a card of 8 GB or more. First verify that the download is correct:

```powershell
# Windows PowerShell
Get-FileHash .\armbian-26.2.1-zero3w-v1.12-dhcpfix-20260929.img.xz -Algorithm SHA256
```

```bash
# Linux / macOS
sha256sum armbian-26.2.1-zero3w-*.img.xz
```

Only flash once it matches the `SHA256` on the release page. Rufus can flash `.img.xz` directly; no need to decompress it yourself.

If you use the old release, replace the file name in the command with `armbian-26.2.1-zero3w-v1.12-bootfix-20260920.img.xz` and check against the **old** Release's checksum; do not mix up the two releases' checksum files.

## 3. First boot

1. Insert the card into the board and connect the **`5V IN / USB_OTG` (USB 2.0) port** to the computer with a data cable, so the board is powered by the computer's USB. The other **USB 3.0 Host** port is for peripherals such as the URT-2 or a USB stick; it cannot be used to make the computer detect the board's USB serial port.
2. Wait about 2–3 minutes; once the board has booted normally and loaded the USB gadget, a **COM port** (USB serial device) should appear in the computer's Device Manager. Open it with PuTTY / MobaXterm / a serial terminal at **115200 8N1** and press Enter. If no COM port appears, check the port, the data cable and the power first; do not conclude from the green LED alone that the system or the image is corrupted.
3. **Log in the first time as `root` / `1234`.** Then complete initialization with the Armbian wizard; if a shell option appears, you can choose `bash`. Only when the wizard reads the presets inside the image does it change the root password to `duck1234` and create `duck` / `duck1234`. Switch to the regular user only after you see the message that `duck` has been created; do not use `duck` for the first authentication.
4. **Change the passwords immediately after completing the wizard.** While still in the root terminal, run:

```bash
passwd            # change root's
passwd duck       # change duck's
```

From then on, log in as `duck`. If you are already in a `duck` terminal, use `passwd` to change your own password and `sudo passwd root` to change the root password. If you built your own card and modified `card.conf`, your own presets apply.

**Why couldn't you log in with the old instructions?** On 2026-09-29 the Sep 20 public image was inspected read-only: the original `/etc/passwd` has no `duck`, and root's password matches `1234`; `PRESET_ROOT_PASSWORD` and `PRESET_USER_NAME` are only applied when `/etc/profile.d/armbian-check-first-login.sh` calls the first-login wizard after login, and they are not first-login credentials. The earlier statement "first login `duck / duck1234`, root password the same" was wrong. If the wizard exits partway, the root password may already have changed while `duck` has not been created yet; log in again with the root password you already set and finish the wizard, or first run `id duck` in the existing root terminal to check. Do not blindly reflash because of this.

It is normal not to see boot logs on the serial console: the kernel logs go to `tty1`, and the serial console is for login only.

### Old cards: regenerate the SSH host keys

The Sep 20 public image ships pre-generated SSH host keys, and cloned cards share them. The Sep 29 candidate image removes these files, keeps an empty `machine-id`, and it was confirmed that the original system's `sshd-keygen.service` is enabled, so `ssh-keygen -A` runs on first boot. This is a static check of the mechanism; the new candidate build has not been flashed and verified.

For cards already flashed with the old release, after completing the first login on the **USB serial console or a local terminal**, run the commands below to regenerate the keys for this board, no reflash needed:

```bash
sudo rm -f /etc/ssh/ssh_host_{rsa,ecdsa,ed25519}_key{,.pub}
sudo ssh-keygen -A
sudo systemctl restart ssh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

The host fingerprint will change. The next time SSH from your computer reports that the old fingerprint does not match, first compare it with the fingerprint shown locally on the board above, then on the computer use `ssh-keygen -R <board IP>` to delete the old entry for that address and reconnect.

**When already powered through the HAT / 40-pin header:** do not use the ordinary USB data cable connection from this section on top of that.
In the official Radxa Zero 3W V1.12 schematic, pages 20 and 22, pins 2/4 of the 40-pin header and the OTG port's
VBUS are both on the same `+5V_INPUT` net, so an ordinary USB data cable ties the computer's 5V and the HAT's
5V output together. When debugging under HAT power, prefer logging in over WiFi + SSH; if you need the USB serial console,
shut down properly and disconnect the HAT input first, then switch to USB-only power.

Erratum (2026-09-28): this section previously described the "USB 3.0 port" as the port for connecting a computer; it has been corrected according to
[Radxa's official interface description](https://docs.radxa.com/en/zero/zero3) and the V1.12 schematic.

## 4. Connecting to WiFi

The following applies to this project's Armbian base image, which uses `wpa_supplicant` + `systemd-networkd`. If you have since migrated to NetworkManager, change the connection through it instead, and do not enable a second wireless management service at the same time. The base image does not have NetworkManager / `nmtui` installed.

The wireless credentials on this image are not in netplan, so you cannot blindly follow the upstream `migrate-network.sh` network migration steps; before migrating, you need to handle credential import, retiring the old services and recovery from a lost connection. See the [folder README](README.md).

### WiFi already filled in: only add DHCP

After confirming that the WiFi name and password are correct, log in via the USB serial console or a local terminal and run:

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

This step keeps the existing WiFi authentication configuration. Then verify the result with "Checking the connection" below; adding DHCP alone will not fix a wrong password, wireless driver problems or power problems.

### First time online, or changing WiFi

Do this via the USB serial console or a local terminal. The following replaces the existing WiFi configuration; restarting the wireless service drops the current SSH session over WiFi. Replace the WiFi name and password in the example with your own, and set `country` to the two-letter country code of where you actually are (`CN` for China):

```bash
sudo mkdir -p /etc/wpa_supplicant /etc/systemd/network
sudo tee /etc/wpa_supplicant/wpa_supplicant-wlan0.conf >/dev/null <<'CONF'
ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev
update_config=1
country=CN

network={
    ssid="YourWiFiName"
    psk="YourWiFiPassword"
    key_mgmt=WPA-PSK
    pairwise=CCMP
    ieee80211w=0
    scan_ssid=1
    priority=10
}
CONF
sudo chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
sudo tee /etc/systemd/network/25-wlan0.network >/dev/null <<'NETWORK'
[Match]
Name=wlan0

[Network]
DHCP=ipv4
NETWORK
sudo chmod 644 /etc/systemd/network/25-wlan0.network
sudo systemctl enable --now systemd-networkd
sudo systemctl enable wpa_supplicant@wlan0
sudo systemctl restart wpa_supplicant@wlan0
sudo networkctl reload
sudo networkctl reconfigure wlan0
```

The wireless service is restarted explicitly here so that the changed WiFi name and password take effect; running `enable --now` alone does not make an already running service reread its configuration.

### Checking the connection

Wait about 30 seconds, then run:

```bash
sudo wpa_cli -i wlan0 status   # successful authentication shows wpa_state=COMPLETED
ip -4 a show wlan0            # check whether an IPv4 address was obtained
ip -4 route                   # check whether there is a default route
networkctl status wlan0       # shows the matched network configuration and DHCP status
```

`wpa_supplicant` connects to the wireless network, and `systemd-networkd` requests an IPv4 address based on `25-wlan0.network`.
The `/etc/netplan/10-dhcp-all-interfaces.yaml` shipped with this image only matches `e*`, `lan[0-9]*` and `wan[0-9]*`, so it **will not obtain an address for wlan0**.

The `WPA-PSK` / `CCMP` / `ieee80211w=0` above carry over the WPA2-compatible configuration used during the earlier AIC8800 debugging; it requires the router to allow WPA2-PSK / AES and cannot be used on networks that only allow WPA3 or enforce PMF. If the handshake fails in mixed mode, you can first test against a WPA2 network for comparison; do not attribute every authentication failure to the same cipher.

Troubleshooting order: if `wlan0` cannot be found, check the device/driver first; if authentication is not `COMPLETED`, check the WiFi name, password, signal and router mode first; if authentication completes but there is no IPv4, then check the DHCP configuration, the network management services and the router's address assignment. For further troubleshooting, look at:

```bash
sudo journalctl -b -u wpa_supplicant@wlan0 -u systemd-networkd --no-pager -n 80
```

Before sharing logs, redact personal information such as your WiFi name, and do not upload authentication configuration files that contain passwords.

Once connected, find `radxa-zero3` in the router, and from then on just `ssh duck@<board IP>`; no need to plug in the serial cable again.

**Changing computer does not require reflashing the system:** the computer and the board just need to be on the same LAN where they can reach each other; guest networks/AP isolation may block traffic between devices. **Changing WiFi requires changing the connection configuration:** the board will not automatically know the new password; just reconfigure following this section, again with no reflash needed. The IP assigned by DHCP may change, so look up the address again instead of reusing the old IP forever.

If you find it a hassle and don't want to connect manually every time: use the card-building script in the repo to write the WiFi in before flashing:
[`build-armbian-card.sh`](build-armbian-card.sh); fill in the WiFi name and password in `card.conf` and generate your own card with networking (this public image was made with the same script, with WiFi left empty).

## 5. Servo serial port

`/dev/ttyS2` is ready (pin 8 TX and pin 10 RX on the 40-pin header), and the login console and kernel logs have both been removed from it.

Note: **the RK3566 UART is full-duplex 3.3 V on two wires, while the Feetech / Dynamixel bus is single-wire half-duplex**; you need a tri-state buffer or an adapter board in between, and direct jumper wiring will not receive any replies. See the [pitfalls log](../../踩坑记录.md#飞线不打-hat-时).

## 6. If your board is not from this batch

The Zero 3W has shipped in several batches, and both the WiFi module and the device tree on the board have changed. How to tell: this card does not boot into the system after flashing, but **Radxa's official image does boot**.

### V1.12J (the 2026-09 batch, AIC8800DS2): someone has already got it working

A community member reported getting their board working with **the B1 bootloader + the B1 DTB + Armbian 6.1.115 kernel + Trixie system**; swapping the bootloader alone was not enough. This is experience with a specific board and image combination; you cannot assume the DTB is interchangeable just because both sides use a 6.1 vendor kernel, and this project has not independently verified that combination. Rule out networking configuration and wiring problems first, then consider the bootloader/device tree comparison below.

Three steps (`/dev/sdX` = the card flashed with Radxa's official B1 image, `/dev/sdY` = the card flashed with this Armbian image; **don't mix up the disks**):

```bash
# 1) Pull the bootloader from B1 and write it to the Armbian card
sudo dd if=/dev/sdX of=idbloader.img bs=512 skip=64    count=16320
sudo dd if=/dev/sdX of=u-boot.itb    bs=512 skip=16384 count=16384
sudo dd if=idbloader.img of=/dev/sdY bs=512 seek=64    conv=notrunc
sudo dd if=u-boot.itb    of=/dev/sdY bs=512 seek=16384 conv=notrunc

# 2) Copy the B1 DTB to the Armbian card (use the file name from the B1 image; find the Zero 3W one)
sudo mount /dev/sdX1 /mnt/b1 ; sudo mount /dev/sdY1 /mnt/armbian
ls /mnt/b1/boot/dtbs/*/rockchip/ | grep -i zero3
sudo cp /mnt/b1/boot/dtbs/*/rockchip/rk3566-radxa-zero3.dtb /mnt/armbian/boot/dtb/rockchip/rk3566-radxa-zero3-b1.dtb

# 3) Point extlinux's fdt at it
sudo sed -i 's|^  fdt .*|  fdt /boot/dtb/rockchip/rk3566-radxa-zero3-b1.dtb|' /mnt/armbian/boot/extlinux/extlinux.conf
sync; sudo umount /mnt/b1 /mnt/armbian
```

After switching to Radxa's DTB, **verify two things**, because the overlays come from the Armbian side and you need to check whether their nodes match:

- whether `ls /dev/ttyS2` exists (the servo serial port on the 40-pin header; whether the `uart2-m0` overlay took effect)
- whether a COM port still appears when the board is plugged into a computer (the `dwc3-peripheral` overlay)

If they don't match, remove the `fdtoverlays` line and use Radxa's own overlays instead (in `/boot/dtbo/` of the B1 image), or modify Radxa's DTB directly.

### Other batches

You can use an official image that boots on your board for comparison, but before porting the bootloader, DTB and overlays you must check board and kernel compatibility; cross-batch compatibility is not guaranteed.
If it still doesn't work, connect the debug serial port on the 40-pin header (3.3 V USB-TTL, 1500000) to look at the U-Boot output, or open an
[issue](https://github.com/fanhao375/microduck-replica/issues) stating clearly your board version, WiFi module and the step where it gets stuck.

### Known issues

- **V1.12J fails to cold boot with HDMI plugged in** (community feedback, in the state before applying the three steps above). If you hit this: cold boot without HDMI first,
  then plug it in after boot; or add `video=HDMI-A-1:d` to the end of extlinux's `append` to disable HDMI output.
  Our image's kernel console is `console=tty1` (goes to the display), which is related to this.

## 7. Sources and licenses

- Base: [Armbian official Radxa Zero 3 image](https://www.armbian.com/radxa-zero-3/), 26.2.1 Trixie vendor 6.1.115 minimal, used as is, GPL and respective licenses
- Bootloader: Radxa [`u-boot-rk2410`](https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/) `2017.09-64-39cd993`, taking `idbloader.img` and `u-boot.itb`, GPL-2.0
- The card-building changes are in [`build-armbian-card.sh`](build-armbian-card.sh), so you can reproduce the card-building process yourself; the current script includes the fixes for DHCP, the first-login notes and SSH host key handling, so its output will not be byte-for-byte identical to the old Release attachments. The 20260929 candidate was made by patching the original public image offline; see the [verification log](镜像离线核验-20260929.md) for details

This image is community-made and **has nothing to do with Armbian or Radxa officially**; if something goes wrong, don't go to them, open an issue in this repo.
