# 2026-10-12: Teardown of kissqy's "one-click system image R1", and modifying it into a card that boots on V1.12

**English** · [简体中文](HD1910-20261012-kissqy镜像R1分析.md)

**In one sentence**: the full-card image kissqy released on 10-12 is carefully made, and private data such as accounts, keys and WiFi have all been cleaned out. But it is built for his hardware: stock Armbian bootloader, HAT + audio + camera + NPU, and the IMU is a board on the bus. Our V1.12 boards very likely will not boot it, and his program does not recognize IMU modules either. The boot layer can be modified directly on top of his image; the script is written and verified offline. IMU module support has to wait until he publishes the V164 source, so we can port our patch onto it.

This document is written for both humans and AI: every conclusion states its basis and how it was checked, so others can re-check it.

---

## 1. How it was checked

- Downloaded `microduck-zero3w-0.15.1-R1.img.xz` (767 MB) from his release page. sha256 `75da978b…a7bce5`, matching what he published.
- Decompressed it in WSL (3.16 GB), mounted the root partition **read-only**, and went through it from start to finish: boot area, boot configuration, preinstalled services and programs, calibration, accounts, then scanned by signature for tokens and private keys. None of the programs in the image were run; only text was read and file attributes inspected, and binaries were only looked at with `strings`.
- Copied out the V164 install scripts and release notes and compared them file by file with the v146 release package.

## 2. What is in the image

| Item | Content |
|---|---|
| System | Armbian 26.2.1 trixie, vendor kernel 6.1.115, a single ext4 partition (starting at sector 32768, about 3 GB, automatically expanded to fill the card on first boot) |
| Bootloader | **Armbian mainline U-Boot 2025.10 + memory init firmware v1.21**, using `boot.scr` + `armbianEnv.txt` |
| Device tree | `rk3566-radxa-zero3.dtb` (AIC8800 Wi-Fi version) |
| Overlays | `uart2-m0` (servo serial port), `i2c3-pihat` (HAT's J5, 40-pin header pins 3/5), `aic3104-i2c3` (HAT audio chip), `radxa-zero3-rpi-camera-v2` (camera), `npu-enable` |
| Official programs | 0.15.1, built from source by him (`0.15.1-dev.local…g1fa8438`) |
| His firmware | build `1fa8438-feetech-ft6-control.40`, web console version 1.0.163 (his README says V164), built on 10-11 |
| Models | Walking, sit/stand, picking things up, forward roll, left/right ball kicks; plus roller-skate actions |
| Started at boot | robotd, padd, mediad (camera), tofd (ranging), btd, configd, gamesir-xboxd (physical gamepad bridge), aic3104-init, hotspot network setup portal |
| First boot | Hotspot `Microduck-kissqy` / `12345678`, web page `http://10.42.0.1:8088` to configure home WiFi and set the login password; only after that are SSH keys generated and SSH enabled |
| Official automatic upgrades | `auto_apply = "off"`, official boot self-check disabled |

## 3. What was done well (worth copying)

- **No private data left behind**: no GitHub tokens, private keys, his home WiFi password or command history; logs cleared.
- **Accounts locked by default**: neither root nor radxa has a password; you must set one yourself during first-time network setup.
- **SSH host keys differ per card**: none in the image, generated on first boot; machine-id also cleared.
- **Automatic upgrades turned off**: so official updates do not replace his foundation. We did the same when setting up the first robot in the early morning of 10-12.

## 4. Where it does not match our hardware

| Problem | Who is affected | Basis |
|---|---|---|
| **V1.12 boards may not boot** | Our first robot's V1.12 (AIC8800) batch; group members say the 2026-09 V1.12J batch also needs a different device tree | The bootloader is Armbian mainline U-Boot 2025.10 + DDR v1.21. The first robot got stuck on exactly this combination in September and only came up after switching to the Radxa bootloader (see [pitfall log · software](../踩坑记录.md#软件)). His board boots, which shows his batch has no such problem |
| **Only accepts the bus IMU board** | People using BNO085 / LSM6DSV16X modules | The firmware only has code to read ID 200, with required identity `06 00 00 00 F2` (his FT6 firmware) and no I²C IMU; the boot configuration also does not enable I2C4 (pins 27/28) |
| **His prototype's calibration preinstalled, IMU marked "confirmed"** | Everyone | The zero positions in `hd1910-calibration.toml` are from his duck (2281, 2176, ...), directions all −1, `imu_mount_verified = true`. Fortunately `motion_enabled = false`, so it will not move as soon as it is powered |
| **Camera and ranging services on by default** | People without a camera or ToF installed | Without the devices, mediad and tofd keep crashing and restarting and the board heats up until it throttles; see [on-robot record §4](HD1910-20261012-kissqy整套上机.md) |
| **Full HAT configuration by default** | People with a no-HAT build | Audio chip and I2C3 overlays are on; in a no-HAT build this does not prevent booting, but those features do not work |
| **robotd has no I²C device permission** | Adding IMU module support on his image later | robotd's systemd configuration only allows the servo serial port and the sound card, not `char-i2c` |

## 5. What V164 changed compared with v146 (relevant to us)

From the release notes copied out of the image (R150 to R157-Fix6):

- **The web gamepad works differently** (R157): web input is now sent directly to robotd over a persistent SSH connection; **there is no longer a virtual Xbox gamepad, and no webpad service**. In the early morning of 10-12, our "pressing Start did nothing" got stuck exactly on the webpad path (it could not start in time while throttled), so the new version should not have that problem.
- **Startup flow** (R150, R153, R157): first confirm that all 15 servos are torque-off, then wait for the IMU to be ready; initialization retries up to 5 times instead of exiting after one failure; HOME and policies are refused while not ready.
- **Model import removed** (R154): the web console can no longer import models. For a future action community, we need to ask him why, or use the official `robotctl policy load`.
- In the install scripts, the files relevant to our IMU patch: `calibration-config.py` unchanged, `rebuild-config.py` 13 lines changed, `runtime.py` 189 lines changed, `voice-setup.py` 23 lines changed; `uart-service.py` and `webpad.py` deleted. The packaging part of the patch can be ported; the robotd part has to wait for the source.

**The source in his repo is still v146**; his README explicitly says "the old repo source has not yet been updated to match".

## 6. Modifying his image: three layers

### 6.1 The boot layer: done

Script [`tools/radxa/kissqy-r1-v112.sh`](../tools/radxa/kissqy-r1-v112.sh), run in WSL:

```bash
sudo bash kissqy-r1-v112.sh microduck-zero3w-0.15.1-R1.img.xz [--no-camera] [--no-tof] [--overlay i2c4-m0]
```

It only changes the following and keeps everything else as is (his firmware, models, first-time network setup, account locking and first-boot SSH key generation are untouched):

1. Writes the Radxa `u-boot-rk2410 2017.09-64` bootloader at sectors 64 and 16384 (the same package used by our [card-flashing script](../tools/radxa/README.md), sha256 pinned);
2. Adds `/boot/extlinux/extlinux.conf`. The Radxa bootloader only reads this file, not `boot.scr`. Overlays, device tree and kernel parameters are all carried over from the image's own `armbianEnv.txt`, so his HAT audio, camera and NPU still take effect;
3. `--overlay NAME`: adds an extra overlay, e.g. `i2c4-m0` (for an IMU module wired to 40-pin header pins 27/28);
4. `--no-camera`, `--no-tof`: when no camera or ToF is installed, mediad and tofd are not started at boot;
5. Writes how this card was modified to `/etc/microduck-v112-image.txt`.

**Offline verification results** (one image made with `--no-tof --overlay i2c4-m0`, `microduck-zero3w-0.15.1-R1-V112.img`, sha256 `652dd54e…4c5bcc`):

- The boot area is byte-for-byte identical to Radxa's official package, memory init firmware v1.25;
- Sectors 0 to 63 (partition table) untouched, image size unchanged;
- Comparing the root partition file by file with the original, only `extlinux.conf` and the notes file were added, `armbianEnv.txt` was changed, and tofd's autostart link was removed; not a single other byte changed;
- The kernel, initrd, device tree and 6 overlay files referenced in extlinux are all present.

**Not yet tested on the robot**: it needs to be flashed onto a blank card and tried on the first robot for booting and hotspot network setup. Do not touch the card currently in the first robot.

### 6.2 The hardware differences layer: choose with switches

| Your situation | What to add |
|---|---|
| No camera installed | `--no-camera` |
| No ToF installed | `--no-tof` |
| IMU module jumper-wired to 40-pin header pins 27/28 | `--overlay i2c4-m0` |
| IMU module plugged into the HAT's J5 | Nothing needed, his image already enables I2C3; avoid address clashes with on-board chips, see §9.2 |
| IMU module plugged into a modified J6 | `--overlay i2c4-m0`, the same as jumper wires to pins 27/28, see §9.3 |

### 6.3 The firmware layer: waiting for the V164 source

To make his program recognize IMU modules, the I²C IMU support in our branch (`hd1910-trunk-imu-i2c`) must be ported to V164, and `DeviceAllow=char-i2c rw` added to robotd. This cannot be done until he publishes the source. We can first ask him when he will sync the source and whether he would be willing to merge it directly into his image.

## 7. Read this before flashing his image

1. **Which board revision?** If the silkscreen on the back says V1.12 and it has AIC8800 Wi-Fi, first use the script in 6.1 to swap the bootloader; the 2026-09 V1.12J batch may also need a different device tree (see the pitfall log).
2. **Which IMU?** His bus board (flashed with his FT6 firmware) works directly; BNO085 and LSM6DSV16X modules cannot be used for now and have to wait for the patch.
3. **Camera and ToF installed?** If not, turn off the corresponding services, otherwise the board will heat up until it throttles.
4. **After flashing, change the calibration first**, before touching HOME: replace the zero positions and directions with your own, and reconfirm the IMU mounting orientation. The IMU of his prototype is also marked "confirmed" in the image, so never enable motion directly.
5. On first boot, connect to the hotspot `Microduck-kissqy`, password `12345678`.

## 8. Next steps

1. Flash the modified image onto a blank card and try booting, hotspot network setup and SSH on the first robot.
2. Ask kissqy: when the V164 source will be synced; why model import was removed; whether he is willing to merge IMU module support, the V1.12 bootloader and "turn off services when there is no camera".
3. Once the source is out, port the IMU patch to V164, then make a "his image + IMU module" card.

## 9. Connecting an IMU module on the HAT: C1 (old revision, the one we have) vs D1 (latest official revision)

When using an IMU module (BNO085, LSM6DSV16X) and not wanting to run jumper wires from the board's 40-pin header, you can plug into the ready-made ports on the HAT. Data sources for the two revisions:

- **C1**: the production files we used for our boards, `官方HAT-production/`. The Gerbers carry each pad's net name (X2 attributes `TO.P` / `TO.N`), cross-checked against the BOM.
- **D1**: the `kicad_pcb` of the official KiCad project `hardware-official/elec_RPI_Robot_HAT` (commit `4478fdf`).

Both are derived from production files and schematics and **have not yet been connected on the robot**.

### 9.1 Four 4-pin ports, same definition on both revisions

J5 to J8 are all JST-SH 1.0 mm 4-pin (BM04B-SRSS-TB), pin order: **1 GND, 2 3V3, 3 SDA, 4 SCL**. This is the same as Qwiic / STEMMA QT, so modules with a Qwiic port plug in directly with a standard cable.

| Port | Connects to 40-pin header | Hardware I²C? | Notes |
|---|---|---|---|
| J5 | 3 / 5 (IO_02 / IO_03) | Yes, the Zero 3W's I2C3 | Requires enabling the official `i2c3-pihat` overlay, at the cost of USB-C no longer negotiating PD; kissqy's image R1 already has it on. On-board 10k pull-ups R12/R13 |
| J6 | 7 / 29 by default; can be rerouted to 27 / 28 | I2C4 after rerouting | See 9.3 |
| J7 | 24 / 21 | No (SPI pins) | Has 10k pull-ups; can only emulate I²C with `i2c-gpio`, not recommended |
| J8 | 19 / 23 | No (SPI pins) | Same as J7 |

### 9.2 What is already on the J5 bus: differs between revisions

I²C is a bus, so several devices can share it as long as addresses do not conflict. Before connecting, check which chips on the board already occupy which addresses:

| Chip | C1 (the one we have) | D1 (latest official) |
|---|---|---|
| Audio aic3104 (U2) | 0x18 | 0x18 |
| On-board IMU | BMI088 (U11): accelerometer SDO1 to 3V3 via R14 (0Ω) → **0x19**; gyro SDO2 to ground via R15 (0Ω) → **0x68** | LSM6DSV16X (U12): SDO/SA0 to ground via R30 (0Ω, populated) → **0x6A** |
| ToF (officially intended, we have not connected it) | 0x29 | 0x29 |

External module addresses:

- **BNO085** (0x4A / 0x4B): no conflict on either revision.
- **LSM6DSV16X** (0x6A / 0x6B): both usable on C1; **on D1 you must use 0x6B**, since 0x6A is taken by the on-board chip. Tie the module's SA0 high, and also set `i2c_address = 0x6B` explicitly in robotd.

### 9.3 Rerouting J6 to I2C4: not a single line of software changes

J6 is wired the same way on both revisions:

- pin 3: to 40-pin header pin 7 via **R18 (0Ω, populated by default)**, and to pin 27 via **R17 (0Ω, not populated by default)**;
- pin 4: to pin 29 via **R19 (0Ω, populated by default)**, and to pin 28 via **R16 (0Ω, not populated by default)**;
- 10k pull-ups R20/R21 are both present.

C1's BOM lists exactly R16/R17 as `DNP-0R` (not populated) and R18/R19 as `0R`. **Remove R18 and R19 and fit 0Ω on R16 and R17 (or bridge them)**, and J6 connects to 27/28, i.e. I2C4, i.e. `/dev/i2c-4`, the same bus the first robot's jumper-wired BNO085 uses now. That is our robotd's default configuration, so it works as soon as it is plugged in. The "short a few components and it works as I²C" mentioned online most likely refers to this port.

### 9.4 Why the on-board IMU cannot be used directly

C1's BMI088 and D1's LSM6DSV16X are both soldered onto the HAT, and the official team treats it as the "head IMU" (the `[head_imu]` comment in `robotd.toml` describes a BMI088 on the head module; the 0.16.1 commit that reads the beta board's LSM6DSV16X also calls it the head IMU). Based on this comment, plus the user saying holes would be drilled in the head shell for cooling, **we infer that the HAT and the board are mounted in the head**. The head rotates relative to the body, while the policy needs the attitude of the **trunk**, so the on-board chip cannot serve as the trunk IMU.

The external module must be fixed to the trunk, with the wires running from the HAT in the head down through the neck. Use flexible wire with enough length to allow for joint rotation, and provide strain relief at both ends. The first robot's BNO085, currently jumper-wired from the 40-pin header, is routed the same way.

### 9.5 Software configuration

When plugged into J5, `/etc/robot/feetech-ft5/robotd.toml`:

```toml
[trunk_imu]
source = "bno08x"            # for LSM6DSV16X write "lsm6dsv16x", and i2c_address is required
i2c_device = "/dev/i2c-3"    # use the actual bus number
i2c_address = 0x4B
```

- First use `i2cdetect -y 3` to confirm that the module's address (0x4A/0x4B or 0x6A/0x6B) and the on-board chips' addresses are visible, then start robotd.
- The card currently in the first robot **does not have the i2c3 overlay enabled**; add `rk3568-i2c3-pihat.dtbo` to the `fdtoverlays` line in `/boot/extlinux/extlinux.conf`. This board uses the Radxa bootloader, so **changing `armbianEnv.txt` has no effect**. Also, this dtbo is built by the official `setup-board.sh`, which the first robot has never run, so first confirm that the file exists under `/boot/dtb/rockchip/overlay/`.
- If you modify J6, none of this is needed: it is still `/dev/i2c-4`.

### 9.6 Which port to choose

- **For our setup, prefer modifying J6**: no software changes, and J5 stays free for a future ToF.
- **If you do not want to pick up a soldering iron, use J5**: change the overlay, accept that USB-C will not negotiate PD, and avoid addresses per 9.2.
- Whichever you choose, the first time you connect it, run `i2cdetect` and see the address before going further.
