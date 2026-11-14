# Offline verification of the 20260929 public candidate image

**English** · [简体中文](镜像离线核验-20260929.md)

This verification addresses the public image's first-login failure and missing DHCP. No real hardware was connected, no personal WiFi image was read, and no ARM programs inside the image were run. The candidate is published separately as a Pre-release, and the old files are kept.

## Root cause of the first-login problem

The SHA256 of the 20260920 public compressed image was checked and matches the Release:

```text
4de8a355d3d9180e465af486c409e9b3e4ac82c0e241dc73d4fc0f0db7a67579
```

The root partition's starting sector, 32768, was read from the GPT, and the partition was mounted with `loop,ro,noload,offset=16777216`; only whether each password candidate matched was output, and the contents of `/etc/shadow` were not printed.

| Check | Result |
|---|---|
| duck present in `/etc/passwd` | No |
| root password matches `1234` | Yes |
| root password matches `duck1234` | No |
| `/etc/systemd/network/25-wlan0.network` | Missing |

`PRESET_ROOT_PASSWORD`, `PRESET_USER_NAME` and `PRESET_USER_PASSWORD` in the original image's `/root/.not_logged_in_yet` are only wizard inputs. Lines 10–11 of `/etc/profile.d/armbian-check-first-login.sh` call `/usr/lib/armbian/armbian-firstlogin` after root logs in; in the latter, line 670 reads the presets, line 823 sets the root password, and inside `add_user` line 589 creates the regular user, line 602 sets its password, and line 626 deletes the first-login marker. So the first login must use `root / 1234`, and the duck account and the new root password only take effect after the wizard completes; the presets cannot be treated as first-login credentials.

## The new candidate build

Copied solely from the public image above, with these offline changes:

1. Added `/etc/systemd/network/25-wlan0.network`, matching `wlan0` with `DHCP=ipv4`.
2. Updated `/root/先连WiFi.txt` (connect to WiFi first) to spell out the first root login, the wizard, changing passwords and networking; fixed the indentation of the heredoc end marker in the fix command block; after extracting the commands, `bash -n` reports no errors or warnings.
3. Removed the original package's 3 sets of SSH host keys and public keys, zeroing the related content and free space. `/etc/machine-id` is empty, and the original system already has an enabled `sshd-keygen.service` with `ConditionFirstBoot=yes`, `Before=ssh.service` and `ExecStart=ssh-keygen -A`; actual generation on first boot still needs to be verified by flashing a card.

A full comparison of the two read-only mounted file trees (file SHA256, permissions, owners and symlinks) found only the 8 file paths above to differ. The first 16 MiB boot region is identical byte for byte. `e2fsck -f -n` on the root partition completed all five passes with exit code 0. A scan of the new raw image found none of the complete old host private key contents.

The privacy check covered WiFi authentication files, NetworkManager connections, `/etc/environment`, authorized_keys, root/home shell history and user home directories; the original package contains no personal WiFi/proxy/user credentials, and the new build introduces none. The default public passwords that remain must be changed on first use. See [`image-verification-20260929.json`](image-verification-20260929.json) for the verification report.

The new build is still a base system; it does not add the web debug console, robot runtime, servo settings, IMU or policy. The current card-building script has also been updated with the first-login notes and SSH host key handling; this candidate build is an offline patch of the original public image, not a rebuild by rerunning the whole card-building script.

## Not done yet

This new build has not yet been flashed and booted, and the generation of new SSH host keys and an actual WiFi connection have not been verified. The Sep 28 networking hardware test of the personal DHCP-fixed image cannot replace an on-hardware acceptance check of this candidate file. The camera, servo control, IMU and gait are also outside the scope of this offline check.
