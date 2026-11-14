# No-HAT build · replacing the HAT with ¥70 of modules and jumper wires

**English** · [简体中文](不打HAT.md)

> The official HAT is a 4-layer board with components on both sides and 110 parts — one round of prototyping and assembly costs over ¥1,000, and **many people feel it is not worth it**.
> This is the alternative: one buck converter + one half-duplex adapter board, with jumper wires for the rest. **Functionally you only lose the onboard audio and the shutdown detect signal.**

Read [Hardware basics](硬件入门.md) first to understand what the HAT is supposed to do, then read this to see how to do without it.

[![No-HAT wiring diagram](../assets/hw/不打HAT-接线图.png)](不打HAT-接线图.html)

> **The source file of the diagram is [`不打HAT-接线图.html`](不打HAT-接线图.html)** — inline SVG; download it and open it in a browser to zoom, select text and print on A3.
> To swap a module or change a pin, edit it directly. The PNG above is only a preview for GitHub.

**Goal**: the controller is powered from the battery, communicates with the servo bus through the adapter board, and the ToF hangs on I²C — **without the HAT board**, ¥70 of modules standing in for over ¥1,000 of prototyping.

> ⚠️ **This chapter is a plan; it has not been built yet.** The wiring part comes from datasheets and the official schematics, and the software part from the source of the official `setup-board.sh`.
> When you build it, fix whatever step turns out wrong here. When done, clear out the "Not yet built, to be verified" section.

## What to buy

Taobao links go dead; **search terms and the numbers to check do not**. For each row, search with the "Search term" and choose by "Check before buying". When you find a suitable one, paste the link into the [Electronics purchase list](电控采购清单.md).

| Item | Search term | Check before buying | Approx. price |
|---|---|---|---|
| **Buck converter** | 「UBEC 5V 3A 2S」 | **Minimum input ≤ 6 V** (many labeled 2–6S actually start at 7 V, and drop out of regulation before a 2S pack is nearly empty) · output ≥ 2 A continuous · synchronous buck, **do not buy LM2596** | ¥10–15 |
| **Half-duplex adapter board** | 「串口总线舵机驱动板 ST SC」 (serial bus servo driver board ST SC) | Either the TTL or USB version works. **Logic supply range must include 3.3 V** (some only take 5 V, and then cannot be connected to the controller) · servo-side power must handle 8.4 V. **If you already have an FE-URT-2, that is the USB version, so you can skip buying one for now** (see step 4) | ¥22 |
| 2×20 pin header | 「树莓派 彩色排针 2x20」 (Raspberry Pi colored pin header 2x20) | 2.54 mm · straight · colored ones make pins easier to count | ¥1 |
| High-endurance microSD ×2 | 「SanDisk 高耐久 64G」 (SanDisk high endurance 64G) or 「海康 PLUS 64G」 (Hikvision PLUS 64G) | **Sold by JD itself (京东自营)** · labeled High Endurance / for surveillance · **not** a normal card like Ultra / EVO | ¥90×2 |
| Card reader | 「USB3.0 读卡器 TF」 (USB3.0 TF card reader) | USB 3.0 | ¥15 |
| Silicone wire | 「18AWG 硅胶线 红黑」 (18AWG silicone wire red black) | 18 or 20 AWG · silicone insulation (soft, heat resistant) · 1 m each of red and black | ¥10 |
| Fuse holder + fuse | 「5x20 保险丝座 带线」 (5x20 fuse holder with leads) + 「5A 保险丝 5x20」 (5A fuse 5x20) | A holder with leads saves soldering · fast-blow 5 A | ¥5 |
| Power switch | 「船型开关 KCD1」 (rocker switch KCD1) | Rated ≥ 6 A · single-pole single-throw is enough | ¥3 |
| PH2.0 3P lead ×5 | 「PH2.0 3P 端子线 单头」 (PH2.0 3P terminal lead single-ended) | 2.0 mm pitch · 3 pins · single-ended with wire (bare wire on the other end) | ¥5 |
| Dupont wires | 「杜邦线 母对母 20cm」 (Dupont wire female-to-female 20cm) | Female-to-female · 20 cm · strip of 40 | ¥5 |
| 470 µF electrolytic | 「470uF 16V 电解电容」 (470uF 16V electrolytic capacitor) | 16 V or higher · 105 ℃ | ¥1 |
| *(Optional) USB sound card* | 「USB 声卡 免驱 3.5mm」 (USB sound card driverless 3.5mm) | **Driverless** (Linux recognizes the UAC standard) · with a microphone jack | ¥15 |
| *(Optional) small speaker* | 「3W 4欧 小喇叭」 (3W 4 ohm small speaker) | 4 Ω 3 W · connecting to the sound card's 3.5 mm jack needs an amplifier, or just buy a small USB speaker with a built-in amplifier | ¥5 |

What you lose without the HAT: the **shutdown detect signal** (LM5050-1 IO_06), the onboard BMI088 (the official software does not use it anyway), and the **onboard audio** — audio can be added back with a USB sound card, see step 8.
No shutdown signal + microSD = hard power cuts damage the card; **shut down in software first, then cut power**.

## Step 1 · Bring up the controller, with nothing connected

> ⚠️ **Zero 3W boards bought after 2024-11 are version V1.12 (WiFi module AIC8800), and the official Armbian image will not boot when flashed directly**:
> the LED double-blinks, it never boots into the system, and it cannot be found on the LAN. The reason is that the mainline U-Boot Armbian ships for this board (whose memory init firmware is v1.21 from 2024-01)
> cannot bring up the new board; replacing it with Radxa's own bootloader fixes it. This is why Radxa's official OS boots and Armbian does not.
> It took us two days and nine card flashes to pin this down, see the [pitfall log](../踩坑记录.md). The card-making script below already handles this step together with the other pitfalls.

**Image**: Armbian **26.2.1 · Debian 13 (trixie) · minimal · vendor kernel 6.1.115**, the version specified by Pollen's official documentation.
Mirrors in China now only have 26.8.1; 26.2.1 is here (376 MB):

```
https://fi.mirror.armbian.de/archive/radxa-zero3/archive/Armbian_26.2.1_Radxa-zero3_trixie_vendor_6.1.115_minimal.img.xz
```

Do not choose `current_6.18` (mainline kernel, not recognized by the official runtime), and do not choose the desktop version.

**1a · Make the card** (bake WiFi, password, bootloader and serial port into the image, so you can ssh in right after flashing and inserting it)

Copy the three files in the repo's [`tools/radxa/`](../tools/radxa/) to any local directory. Your computer needs WSL2 (if you do not have it, run `wsl --install` in an administrator PowerShell and reboot once):

1. Open `card.conf` in Notepad and change the WiFi name and password. The default username and password are `duck` / `duck1234`. If you are in China and want to install the official software, set `HTTP_PROXY=` to the address of the proxy on your computer (for example, with Clash enable "允许局域网" (Allow LAN) and enter `http://<PC IP>:7890`).
2. Right-click `1-做卡.ps1` → "Run with PowerShell", and pick the downloaded `.img.xz`. It decompresses in WSL, swaps the bootloader and writes the configuration, and in about a minute produces an `xxx-鸭子卡.img` (2.2 GB).
3. Solder the pin header first: solder two diagonal pins, flip it over to check that it is straight, then solder the remaining 38.

**1b · Flash the card** (Rufus portable, 2 MB, no install)

1. Download `rufus-x.xxp.exe` from [rufus.ie](https://rufus.ie/zh/). Plug the card reader into the computer, **with this as the only USB-drive-type device plugged in**, and double-click Rufus. When it asks whether to check online for updates, click **No**:

   <img src="../assets/flash/烧卡-1-Rufus问更新-点否.png" width="420">

2. "设备" (Device) will select the card reader automatically. Click "**选择**" (Select) and pick the `xxx-鸭子卡.img` generated above:

   <img src="../assets/flash/烧卡-2-设备自动选中-点选择.png" width="380">

3. Click "**开始**" (Start); when the dialog says the data on the card will be erased, click OK. Writing takes about 2 minutes:

   <img src="../assets/flash/烧卡-3-正在写入.png" width="380">

4. When the status bar returns to "准备就绪" (Ready), it is done; close Rufus and remove the card. **Along the way Windows will pop up "do you want to format the disk" several times; click Cancel every time.** It does not recognize Linux partitions; this is normal.

   <img src="../assets/flash/烧卡-4-完成-准备就绪.png" width="380">

**1c · Power on, find the IP, ssh**

Insert the card into the Radxa, and plug a 5V charger (an Apple 20W one is fine; do not use a Huawei fast charger) into the **`5V IN / USB_OTG` port** (silkscreen on the back of the board, at the end near the TF card slot).
Wait 2 to 3 minutes; it connects to WiFi by itself. Watch the LED: **double-blink for a few seconds → double-blink for two minutes → solid on** means it is up; if it keeps double-blinking without change, it has not come up.
Find a device called `radxa-zero3` in your router's admin page to get its IP; Windows has ssh built in:

```
ssh duck@<that IP>        # the password is the one in card.conf
```

**A lifeline: this USB cable is also a serial port.** Plug the board's `5V IN` port into a USB port on your computer (the computer powers it), and a new "USB 串行设备 (COMx)" (USB Serial Device (COMx)) appears in Device Manager.
Open it in a serial terminal at 115200 and you get a login prompt; the root password is in `card.conf`. If WiFi will not connect or ssh will not get in, go in from here and look.

Only continue once it is up and you can ssh in. **Do not mix up bring-up problems with wiring problems.**

## Step 2 · Make `/dev/ttyS2` appear

The card-making script has already enabled it: the `uart2-m0` overlay is attached in extlinux, the kernel console is on tty1, and `serial-getty@ttyS2` and `ttyFIQ0` are both masked. ssh in and confirm:

```bash
ls -l /dev/ttyS2            # exists
sudo fuser -v /dev/ttyS2    # nobody is using it
cat /proc/cmdline           # contains no console=ttyS2 / ttyFIQ0
```

The official `setup-board.sh` modifies `overlay_prefix` / `overlays` / `console` in `/boot/armbianEnv.txt`, which has no effect on this card (Radxa's U-Boot uses extlinux and does not read boot.scr),
but its own checks all pass, so run it as usual. **If `apt upgrade` upgrades the kernel package, the file names in extlinux.conf must be updated to match**; check `/boot/extlinux/extlinux.conf` before upgrading.

Likewise, if you add an overlay later (for example the camera `rk3568-radxa-zero3-rpi-camera-v2.dtbo`, which `setup-board.sh` mirrors to this name), append its path to the end of the `fdtoverlays` line in extlinux.conf and reboot. Without a camera connected, `mediad` keeps restarting; the other items in `robotctl health` are unaffected, which is normal.

## Step 3 · Power, measure after each section you connect

```
NP-F550 ──► switch ──► 5A fuse ──┬──► buck converter ──► 5 V ──► Radxa pin 2 (or 4)
                                 │        │
                                 │        └── 470 µF across the input
                                 │
                                 └──► servo bus VDD (raw voltage, 18 AWG)
Common ground: battery negative · buck output ground · Radxa pin 6 · servo bus GND
```

```
1  Connect the switch and fuse, measure: with the switch closed, the fuse should conduct end to end
2  Connect the buck converter, do not connect the Radxa yet, measure the output: 5.0 V ±0.2, correct polarity
3  ⚠️ Confirm polarity before plugging into the Radxa — pin 2/4 are unprotected, reversed polarity kills the board
4  Unplug the Radxa's USB-C, bring it up on 5 V via pin 2, ssh works
5  Then connect the servo bus VDD
```

## Step 4 · Connect the servo bus to the controller

```
Radxa 40-pin                    Adapter board MCU side
pin 1   3.3 V    ──────────►   VCC       ⚠️ 3.3 V only; on 5 V its TX will damage the controller's RX
pin 8   UART2_TX ──────────►   RX        ← crossed
pin 10  UART2_RX ◄──────────   TX        ← crossed
pin 6   GND      ──────────►   GND

Adapter board servo side
DATA  ──► servo bus S
V     ◄── servo bus VDD (raw battery voltage, connected in step 3)
G     ──► common ground
```

**USB version of the adapter board**: no need to connect pins 1/8/10; plug it into the Radxa's USB port, and the serial port becomes `/dev/ttyUSB0` or `/dev/ttyACM0`.
Then change `port` in `robotd.toml` to that. Easier, but the uart2-m0 overlay from step 2 is no longer used (agetty stays masked, which is harmless).

> 💡 **The Feetech FE-URT-2 debug board is a USB-version adapter board** — once the IDs are set, move it straight onto the robot: USB-C into the Radxa's host port, S on the TTL port to the bus, G to bus ground.
> **Feed raw battery voltage directly to the servo bus, not through the URT-2's V1 terminal** — V1 may be tied straight to USB 5 V, and 7.4 V there would backfeed into the Radxa.
> The DIP switch on the board sets the signal level (3.3 / 5 V); set it to 5 V. You can hold off on buying the adapter board.
> First check whether the Radxa recognizes the CH343: look for `ttyACM0` in `dmesg | tail`; if it is not there, WCH's website has Linux driver source.
> It is your only debug board; once it is installed you can no longer configure servos on the computer — **finish setting all 15 IDs before moving it**.

**How to branch the bus** — head, left leg and right leg split into three branches at the torso. A half-duplex single-wire bus is **parallel**, not a chain, so star and tree layouts both work; daisy-chaining is just convenient for routing:

```
Adapter TTL ──┬──► head/neck  30 → 31 → 32 → 33 → 34
              ├──► left leg   20 → 21 → 22 → 23 → 24
              └──► right leg  10 → 11 → 12 → 13 → 14
              (imu_to_dxl 200 hangs on any branch in the torso)
```

Ways to split: the URT-2 has two TTL ports, one branch each, and the third branch splits off from a servo; or buy a 「舵机总线分线板 3P」 (servo bus splitter board 3P) with one in and four out (¥5); or solder three wires together.
**Run V and G separately to the three branches in 18 AWG**; S can go any way. ⚠️ **Do not route the current of all three branches through the `imu_to_dxl` board** — although its four connectors are in parallel, the 2-layer board's straight copper pours were not designed for several amps and will burn. Hang it at the end or middle of one branch.

## Step 5 · Verify communication with one servo

Attach **only one** servo with its ID already set (for example left knee 23), and on the controller:

```bash
# The bus benchmark tool shipped with the official runtime (only available after step 7), or a quick ping with Python first:
pip install feetech-servo-sdk    # or scservo_sdk
# 1 Mbps, ping ID 23 — if it answers, it works
```

If it does not, check in order: does `ls /dev/ttyS2` exist → is `fuser` showing someone using it → are TX/RX crossed → is the adapter board VCC 3.3 V → contact of the S wire.

## Step 6 · ToF

```
VL53L8CX          Radxa 40-pin
SDA      ◄──►    pin 3
SCL      ◄──►    pin 5
3V3      ◄───    pin 17     (pin 1 is used by the adapter board, keep them separate)
GND      ────►   pin 6
```

pin 3/5 have onboard pull-ups; no external ones needed.

⚠️ **I²C also needs an overlay.** The official one re-muxes `i2c3` to M0 (that is, pin 3/5), at the cost of losing USB-C PD negotiation.
The official overlay is in `deploy/audio/i2c3-pihat.dts` and is written for the HAT; **whether it can be used directly without the HAT is yet to be verified**.

## Step 7 · Run the official runtime

```bash
curl -fsSL https://raw.githubusercontent.com/pollen-robotics/microduck/main/scripts/provision.sh -o /tmp/provision.sh
sudo sh /tmp/provision.sh
# = setup-board.sh → migrate-network.sh → reboot → install.sh, fully automatic
robotctl health
```

`robotd.toml` is in `/etc/robot/`; the serial port defaults to `/dev/ttyS2`; for the USB version of the adapter board, change it to `/dev/ttyUSB0`.

## Step 8 · If you want sound (optional)

Without the HAT there is no codec, so the official quacks, head-pat detection, ToF keyboard and multi-duck chorus cannot be used — **but the robot walks just the same**; in the official comment's own words, "boards without a codec walk exactly the same, they just make no sound".

To get it back, plug in a **USB sound card** (a driverless one that Linux recognizes directly):

```bash
aplay -l                          # find the name of the USB Audio card, e.g. card 1: Device
sudo nano /etc/robot/robotd.toml
```

```toml
[audio]
enabled = true
device = "plughw:CARD=Device"     # replace with the name shown by aplay -l; the official default is plughw:aic3104
```

```bash
sudo systemctl restart robotd
```

Connect the speaker to the sound card's 3.5 mm jack (a small speaker needs an amplifier; a small USB speaker with a built-in amplifier is the easiest), and the microphone to the sound card's mic jack.

⚠️ **Not verified**: the official `sounds` and `pet_detect` are written for the aic3104's sample rate and channel count, which a USB sound card may not match. If you get it working, update this item.

## Not yet built, to be verified

| Item | Question | How to verify |
|---|---|---|
| Third-party adapter board @ 1 Mbps | The official HAT's direction circuit is `1G08+1G125+1G126`; does the ¥22 board switch direction fast enough | Step 5 works, `bench_dynamixel_bus` error count is 0 |
| Can `i2c3-pihat.dts` be used without the HAT | That overlay is written for the HAT | In step 6, `i2cdetect -y 3` shows 0x29 |
| Can the buck converter handle the voltage drop when the servos start | The battery voltage drops when all 15 move at once | The controller does not reboot while walking; if it does, increase the input capacitance |
| Which Armbian image exactly | The official docs say 26.2.x, without saying minimal or desktop | It is fine as long as you can ssh in after step 1 |
| Can a USB sound card replace the aic3104 | The official audio code is written for the codec's sample rate | In step 8, the audio line of `robotctl health` shows no error and it quacks at boot |

The wiring diagram is at the top of this document; its source file is `不打HAT-接线图.html` in the same directory.
