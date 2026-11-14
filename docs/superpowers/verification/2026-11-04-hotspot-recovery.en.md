# Hotspot fallback after a network change: source candidate and on-robot recovery record

**English** · [简体中文](2026-11-04-hotspot-recovery.md)

Date: 2026-11-04 (JST). Source baseline cc253f3, separate worktree branch fix/hotspot-recovery-20261104. The user confirmed this unit was flashed with the 20261027 image, reported that after moving to a new location the hotspot did not appear automatically, and asked for a follow-up fix.

## Facts that can be confirmed on the robot

- The duck is duck-658d. At first there was no SSH/web endpoint on the LAN; the BLE advertisement was visible, but reading the GATT services and pairing did not work. Neither the computer nor the user's phone could see Microduck-658d.
- After shutting the robot down, the user provided the original system card. It was confirmed to be a Linux card of about 29.12 GiB in a DD-TEK USB card reader; it was first mounted with the device read-only and ext4 ro,noload, to avoid replaying the filesystem journal.
- The firstboot/netcheck programs and their enable links on the card were complete, there was an existing Microduck-Hotspot configuration, and the saved old network was not available at the site. The historical kernel log contains AP started and client association records. The current software version tree is 2026.10.3101.
- The netcheck/NetworkManager service logs from the time of the failure were not persisted, so the card cannot directly prove why the hotspot was not broadcast this time. The source failure sequence constructed later cannot be treated as the confirmed root cause on this unit.
- The user explicitly authorized adding a Wi-Fi configuration for the site and the maintenance SSH public key already on this computer. Only those two files were actually added; the original network configuration, the robotd configuration and the servo/IMU calibration were checked hash by hash before and after writing and remained identical. No reflash, no model change, and no motion commands were sent. The credentials were read from a network already saved on this computer and were not printed in the conversation or in public documents.
- After the system card was unmounted cleanly and the card reader released, the user reinstalled it and powered on; SSH verified the identity using the host public key read from the system card, and connected to 192.168.0.104. The web /healthz returned 200, and suite_version was 2026.10.3101.
- Read-only response: imu_source=bus, board=imu_to_dxl, protocol=feetech, IMU ready, orientation record verified; feedback from all 15 servos was fresh, voltage about 7.74 V, policy off, torque read back as off. This proves it could be read at that moment; it does not prove that the mounting angle, zero positions or motion are accurate.

## Source candidate

1. In addition to the original 45-second disconnected rule, add a 123-second fallback decision that tracks consecutive offline events across connecting/disconnected retries; a network change window initiated from the web console and a successful connection reset the old timeout.
2. When the hotspot connection is missing from NetworkManager's memory, first explicitly load the existing keyfile, keeping the user's SSID/password; only if the file is missing run the hotspot-only creation, and then load it explicitly.
3. If creation, loading, read-back of the connection identity or read-back of the activation state fails, stop that start attempt and back off for the original 60 seconds; a successful command is not treated as the phone already being able to see the hotspot.

## Verification scope

- The original 28 netcheck baseline tests pass.
- A first batch of 8 new regression tests was added; the original program did produce 8 assertion failures; after the change all 36 pass. Then a case "clear the old connection timeout after the network interface becomes unavailable during hotspot mode" was added; it first reproduced a failure, then a one-line reset was added, and finally all 37 pass. The original cases for keeping a valid web connection window, interface not ready, existing hotspot clients, scan failure and retry interval were kept.
- The independent code review and the re-review of the last one-line fix found no significant correctness or regression issues; the 37 dedicated tests pass, and git diff --check is clean.
- The full image test suite initially failed on Windows because sh was missing; after adding the existing Git Bash path to that test process, a rerun of 136 tests took 674.207 s, with 1 failure, 3 errors, 1 skipped. Of these, the file attribute record and leftover reference checks reproduced the same errors/failures in two targeted comparisons against the unmodified baseline; the other two errors were the Windows process not finding openssl. These image assembly code paths were not changed, nor were they changed to skip. After the last dedicated test was added, the whole suite was not rerun. We cannot claim the full image test suite passes.

## Not yet done

The source candidate has not been installed on the duck, pushed or released, and no new image has been made. The actual disconnection fallback, phone visibility, recovery from a wrong new Wi-Fi password, and the acceptance check for migrating between old and new images still need to be done. The problem in the original image cannot be marked as solved based on this set of unit tests alone.

Raw data and logs are stored in the workspace root at artifacts/bus-duck-check-20261104; that directory contains private maintenance material and should not be added to Git or release attachments as a whole.
