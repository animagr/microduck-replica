**English** · [简体中文](release-notes-20260929.md)

> **This Release was withdrawn on 2026-10-21** (too old). For a ready-made card, use the [replica image](https://github.com/fanhao375/microduck-replica/releases/latest). The release notes from that time are kept below for the record.

> **Candidate image (Pre-release): offline verification is complete; this new build has not yet been flashed to a card, booted or tested for networking on real hardware.** This release is built from the original 20260920 public image; it only adds wireless DHCP, corrects the login/networking notes on the card, and removes the pre-generated SSH host keys. The old files remain in the original Release. Existing old cards can be fixed by following the guide, with no need to reflash just for this update.

Target baseline: Radxa Zero 3W V1.12 / AIC8800, Armbian 26.2.1 Trixie vendor 6.1.115 minimal + Radxa `u-boot-rk2410`. Other board batches, cameras and routers need to be verified separately.

**This is a base system; it does not include the robot runtime, the web debug console, servo settings, IMU configuration or the gait policy. No personal WiFi, proxy or login keys are written into it.** What I verified for networking on my board on 09-28 was a different, personal image; that result cannot be taken to mean this candidate build has passed a flash-and-boot test.

### Attachments

| File | Purpose |
|---|---|
| `armbian-26.2.1-zero3w-v1.12-dhcpfix-20260929.img.xz` | New candidate image; write it to a card of at least 8 GB with Rufus / balenaEtcher / Armbian Imager |
| `sha256.txt` | Checksum for this release's compressed image; do not mix it up with the old release's checksum |
| `radxa-zero3w-image-guide-zh.md` | First login, networking, changing WiFi, fixing old cards, power and board batch notes |
| `image-verification-20260929.json` | Offline checks, provenance, SHA256 of the raw image/compressed file, per-file differences, and the "not tested on real hardware" marker |

Compressed image size: 419,157,756 bytes; SHA256:

```text
d7a4dc60a0c622786ae3eb03ebea2d5316d4cff44373945f4a61f44ac7019f63
```

### First login and networking

1. Verify the downloaded file, then flash the card. For the USB serial console, use the board's **`5V IN / USB_OTG` (USB 2.0) port** with a data cable to the computer, powered by USB alone; do not combine it with HAT input power. The USB 3.0 Host port is for peripherals.
2. Wait for the COM port to appear after boot and open it at **115200 8N1**. **The first account is `root / 1234`**, not duck.
3. Complete the Armbian first-login wizard (you can choose `bash` as the shell); only the wizard creates `duck / duck1234` and sets the root password to `duck1234`. While still in the root terminal, immediately run `passwd` and `passwd duck` to change both default passwords. If the wizard is interrupted, the system may be in an intermediate state; keep using the root password you already set to finish initialization.
4. Configure your own WiFi following Section 4 of the accompanying guide. `wpa_supplicant` handles authentication, and the `/etc/systemd/network/25-wlan0.network` preinstalled in this release makes `systemd-networkd` request an IPv4 address. The base image has no NetworkManager / `nmtui`.
5. After checking `wpa_state=COMPLETED`, the IPv4 address and the default route, use `ssh duck@<board IP>` from the same LAN where the devices can reach each other. On the first SSH connection, compare the host fingerprint with the one shown locally on the board.

### Verification for this release

- The only source used was the original public `.img.xz`, SHA256 `4de8a355d3d9180e465af486c409e9b3e4ac82c0e241dc73d4fc0f0db7a67579`; no image containing personal WiFi was used.
- The GPT root partition starts at sector 32768. The first 16 MiB boot region is unchanged byte for byte, and the kernel, DTB, overlays and account database are all unmodified.
- A read-only `e2fsck -f -n` on the root partition passes; the final check mounted it with `ro,noload`. File contents, permissions, owners and symlinks were compared with the original, and only the three kinds of changes listed above are present.
- The initial root password matches `1234` and does not match `duck1234`; there is no duck account initially, and the original Armbian first-login presets and flow are kept.
- The candidate image contains no SSH host keys; an empty `machine-id` together with the enabled `sshd-keygen.service` makes the original system run `ssh-keygen -A` on first boot. The static service mechanism has been verified; the actual first boot still needs to be verified.
- There are no WiFi authentication files, personal proxy, authorized_keys, user home directory contents or shell history. The full content of the old image's host private keys does not remain in the new raw image either. The networking commands on the card pass a Bash syntax check.

The attached verification report is the authoritative source for the full data. Offline verification does not replace flashing and booting, SSH key generation, an actual wireless connection or a hardware acceptance check.

### Project status and sources

The debug console 0.15.4, deployed separately on the board, once read 3000/3000 valid status reads for each of the 14 servos during a roughly 64-second window holding an existing pose, at a target of 50 Hz and an actual rate of about 46.87 Hz, with no timeout/checksum/ID errors in the window. At other times there are still occasional missing replies; this does not constitute an acceptance check of the full control loop, IMU, actions under load or gait. So far the camera has only been confirmed to produce images on the official B1. See the [test summary](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/50Hz%E4%BF%9D%E6%8C%81%E5%A7%BF%E5%8A%BF%E8%AF%BB%E7%8A%B6%E6%80%81-20260928.md).

The base comes from [Armbian](https://www.armbian.com/radxa-zero-3/) and the bootloader from Radxa's [`u-boot-rk2410`](https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/), under the GPL and each package's own license. This is a community-modified build, not an official Armbian or Radxa release. [Card-building script and guide](https://github.com/fanhao375/microduck-replica/tree/master/tools/radxa).
