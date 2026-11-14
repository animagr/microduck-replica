# Radxa ZERO 3W: flashing and first use

**English** · [简体中文](烧录和第一次使用.md)

This page applies to the **Radxa ZERO 3W**. If the board's silkscreen says **Cubie A7Z**, use the [A7Z flashing and network setup guide](../../radxa-cubie-a7z/image/README.en.md). The download links for both boards are in [Download the image for your board](../../README.en.md).

> The [20261027 image](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) is public and marked as Latest; the build, read-only decompression and release attachment checks are complete, but the physical acceptance check of a fresh card for this version is still pending. It comes preinstalled with web software upgrades and local R3 “坐下／站起来” (sit down / stand up) voice; use them after completing the original calibration/stable-standing flow, see [Software update and voice](../../docs/software-update-and-voice-guide-20261027.en.md). Existing cards can later keep their own data through component upgrades, with no need to reflash for every web feature.

Follow this to the end and the duck can stand and walk. Everything is done in a browser: no SSH, no typing commands.

> **The image is free, for personal learning and non-commercial replicas only.** The walking and action models in it are under the author's personal non-commercial license:
> they must not be preinstalled or distributed with products such as HATs, complete robots or kits; do not sell flashed cards, and do not use them for paid services.
> The licenses for each part are in `/usr/share/doc/microduck/` in the image, and the same three txt files are on the release page.

## 1. Preparation

- An assembled **Feetech HD-1910 version** duck: all 15 servo IDs set and the HAT plugged in. Do not use this image on an original XL330 duck.
  - In our hardware tests we used a Radxa Zero 3W (no eMMC) + a 32 GB microSD card, with a C1 HAT.
- Torso IMU, pick one:
  - An **IMU module** (BNO085 or LSM6DSV16X) wired with four wires directly to the board: to the HAT's J5, or to pins 27 / 28 of the 40-pin header.
    The D1 HAT has its own LSM6DSV16X in the head (address 0x6A), so the torso module must be set to **0x6B**.
    The recommended mounting for the LSM6DSV16X module: module x axis pointing down, z axis pointing toward the duck's front (this is how Duck No. 2 is mounted). Mounted this way, you can skip the IMU step entirely.
  - Or the IMU small board on the servo bus (ID 200): when no module is detected, the main program looks for it on the bus.
    Since 20261023c, it automatically detects FT6, this repo's imu_to_dxl Feetech firmware (0.2.0 and later), and DXL 2.0 firmware using the 124/12 SFLP layout.
    Not every vendor's firmware is compatible: other register formats, IDs or baud rates need adaptation; the IMU page shows the actual detection result.
    After replacing the IMU or changing its mounting orientation, redo the orientation calibration; an orientation confirmation from the old Feetech firmware cannot be used directly to enable torque with DXL2.
  - **Connect the IMU before the first boot**: the duck detects it by itself during the first boot.
- A microSD card, 8 GB or larger, 32 GB recommended; a card reader.
- A computer (for flashing) and a phone (for network setup).

## 2. Download, verify, flash the card

1. Download `microduck-replica-<date>.img.xz` and the `.sha256` with the same name (from GitHub Releases or the cloud drive).
2. Verify the file downloaded correctly (you can skip this, but if something strange happens, check this first):
   - Windows: open PowerShell in the download folder, run `Get-FileHash microduck-replica-日期.img.xz`, and compare it with the string in the `.sha256` file (case does not matter);
   - Mac / Linux: `shasum -a 256 -c microduck-replica-日期.img.xz.sha256`.
3. Flash the card with [balenaEtcher](https://etcher.balena.io/): select the image file (no need to decompress the `.img.xz`) → select the SD card → Flash.
   The official Raspberry Pi Imager also works: under "Operating System", choose "Use custom" at the very bottom.
4. After flashing, Windows may pop up "You need to format the disk"; click **Cancel**, do not format it.

## 3. First boot

1. Insert the SD card into the board and power on the duck (connect the servo power as well).
2. Wait **about 3 minutes**. The first boot does three things: expands into the remaining space on the SD card; gives the duck a name (`duck-` plus 4 characters, e.g. `duck-c51b`); detects the IMU module. Later boots are faster.
3. When the duck cannot connect to any WiFi (which is always the case on the first boot), it opens its own hotspot:
   - Name: `Microduck-` plus the same 4 characters, e.g. `Microduck-c51b`;
   - Password: `microduck`.

## 4. Connect your phone to the duck and set up your home WiFi

1. Find `Microduck-xxxx` in your phone's WiFi list and connect with the password `microduck`.
   If the phone says "This network has no internet access", choose **Stay connected**.
2. Open **http://10.42.0.1:8000/** in the phone's browser and you will see Microduck Studio.
   If it does not open, first **turn off mobile data** on the phone and try again (some Android phones route around a WiFi with no internet).
3. At the top is the “连 WiFi” (Connect WiFi) card: tap your home WiFi, enter the password, tap “连接” (Connect), read the confirmation dialog carefully, then tap “断开去连「你家 WiFi」” (Disconnect and connect to "your home WiFi").
   You need to enter the password every time you connect, including for networks marked “已保存” (Saved).
4. The duck shuts down the hotspot and connects to your home WiFi; **the phone will disconnect, which is normal**.
5. Reconnect the phone (or computer) to your home WiFi and open, depending on the device (xxxx is the 4 characters in the hotspot name):
   - **Windows computer**: **http://duck-xxxx:8000/** (without `.local`; it opens even with a proxy like Clash running);
   - **iPhone, Mac**: **http://duck-xxxx.local:8000/**;
   - **Android phone, or if none of the above opens**: go to your router's admin page, find `duck-xxxx` in the device list, and open its IP, e.g. `http://192.168.1.23:8000/`.
   - Once it opens, the “更多” (More) page lists all of this duck's current addresses; you can bookmark one.
6. If you entered the wrong password, or the duck did not connect: the hotspot comes back by itself (usually right away, at most about 2 minutes). Connect to `Microduck-xxxx` again, and the card shows in red why the last attempt failed; fix it and try again.

You do not have to connect to your home WiFi: you can stay connected to the duck's hotspot and use Studio, and all features work.

**Security reminder**: everyone knows the hotspot password, and Studio has no login password by default, so **anyone nearby who connects to the hotspot can control the duck**.
Before demonstrating in public, set a login password on Studio's “更多” (More) page.

**Outdoor use without WiFi** (talking through the phone + gamepad): see [Studio's offline notes](../studio/deploy/OFFLINE.en.md):
after connecting the phone to `Microduck-xxxx`, open `https://10.42.0.1:8000/m`, follow the prompts to install the duck's certificate, and you can use the onboard Vosk to recognize “手机说话” (phone voice); the physical gamepad connects directly over Bluetooth and does not need WiFi.

## 5. Follow the “上手清单” (Getting started checklist)

The overview page has a “上手清单” (Getting started checklist); work through it from top to bottom. Each step has three buttons: “去做” (Go) takes you to the corresponding page; for something you did before (for example, the servo zero position was calibrated long ago) tap “已完成” (Done); to put a step off, tap “跳过” (Skip). If the main program says a step is not finished yet, tapping “已完成” (Done) or “跳过” (Skip) shows a one-line warning about the consequences, and it counts once you confirm.

1. **Servo zero position**: go to the servo page, put the duck in the zero position (legs straight, head straight, beak closed), and tap “一键校准” (One-click calibration).
2. **IMU orientation**: go to the IMU page and do the coarse calibration: hold the duck up with both hands, level, keep still, then tilt it forward as the page prompts.
   After the page computes the orientation, it hands it to the main program for another check: hold it level, then **tilt it forward 15–30° within 20 seconds**.
   Once the main program verifies it, the orientation is recorded.
   - **The more accurate way: standing calibration**. On the IMU page tap “站姿使能” (Enable standing pose); the 15 servos turn together into the standing pose within 3 seconds and lock (it can stand even in commissioning mode,
     but without balance control, so keep a hand on it). Once it is standing, do “站着校准” (Standing calibration) (still, forward, back, left, right), then tap “失能” (Disable) or “卸力” (Torque off) at the top, and hold the duck.
     The computed orientation is written into the main program together in step 3. You can do standing calibration even without the coarse calibration.
   - **Calibrated before, or want to skip for now**: tap “已完成” (Done) or “跳过” (Skip), and step 3 writes the IMU orientation for the default mounting:
     the bus IMU small board uses the official mounting; BNO085 uses the fork's default mounting; LSM6DSV16X uses the replica's recommended mounting (module x axis down, z axis forward).
     If yours is mounted differently, the duck will fall to one side when it stands up: do a standing calibration as described above and write into the main program again.
3. **Write into main program** (“写进主程序”): writes the results of the two steps above into the main program in one go. Before writing, have the duck **sitting or limp** (if it is standing via “站姿使能” (Enable standing pose), tap “失能” (Disable) first), and the servo power must be on.
   After writing, the main program restarts (about 20 seconds, up to a minute if slow) and switches from commissioning mode to motion mode; **hold the duck firmly**.
   If the main program does not accept this calibration, it automatically switches back to the previous one, and the page shows the reason.
   From then on, after boot it can stand and walk right away, even without opening the web page.
4. **Pair the gamepad**: go to the gamepad page and follow the wizard to pair a Bluetooth gamepad. You can also start with the web gamepad.
   For gamepads that can switch platforms, such as the Thunderobot G50 Pro, set the switch on the back to **X mode (Xbox)**: on 20261021b, X mode connects right away; S mode (Switch Pro) pairs successfully, but the main program receives no button presses and the gamepad turns itself off after a while (the cause is still being investigated).
5. **Test the e-stop**: **short-press** Select on the gamepad once and confirm that the duck goes limp (torque off) immediately. (Holding Select for 2 seconds means sit down, torque off, **shut down**; do not hold it when testing the e-stop.)
6. **Stand up and walk a few steps**: tap “站起来” (Stand up), then “开始走” (Start walking), and push the stick.

Whenever you want the duck to go limp immediately: tap the red “卸力” (Torque off) at the top right of the page, or press the space bar.

## 6. Gamepad controls

Button positions are described as on an Xbox controller:

| Button | What it does |
|---|---|
| Start | First press stands up; pressing again starts walking / stops |
| Left stick / right stick | Walk / turn |
| Select short press | Torque off immediately (e-stop) |
| Select hold 2 seconds | Sit down, torque off, shut down |
| D-pad down | Sit down / stand up |
| D-pad right | Reboot all servos |
| A (bottom one) | Bend down to pick something up |
| X (left one) | Forward roll |
| LB / RB | Left kick / right kick |
| Y / B | Head mode / body posture |
| Triggers | Open beak |
| D-pad up hold 3 seconds | Switch between walking and roller skating (requires the passive roller-skate parts; do not press on an ordinary duck) |

The first time you try the forward roll and kicks, leave space around the duck. Which model each action uses is listed in `/usr/share/doc/microduck/模型说明.txt` in the image.

## 7. Troubleshooting

- **The `Microduck-xxxx` hotspot does not appear**:
  - When the duck is already connected to your home WiFi, it does not open the hotspot; open `http://duck-xxxx.local:8000/` or the IP from your router directly;
  - Wait 2 more minutes on the first boot; if it still does not appear, power off and boot again.
- **The page does not open**: make sure the phone is connected to the duck's hotspot (or to the same WiFi as the duck) and that the address ends with `:8000`; on Android phones, turn off mobile data and try again.
- **The computer runs a proxy such as Clash**: `.local` addresses get captured by the proxy and do not open (error 502). On Windows use `http://duck-xxxx:8000/` or the IP instead;
  if it still does not open with TUN mode on, set the LAN (192.168.0.0/16, 10.0.0.0/8) to direct connection in the proxy software, or add `*.local` to the bypass list.
- **The IMU step says “主程序还没报用的是哪颗 IMU” (the main program has not reported which IMU it is using)**: most likely the module was not detected during the first boot. Check the wiring and address (on a D1 HAT the torso module must be 0x6B),
  then run `sudo microduck-firstboot --detect-imu-only --force` over SSH and reboot the duck.
- **Getting help**: on Studio's “更多” (More) page (on a computer you can also go to the “日志” (Logs) page), tap “导出诊断包” (Export diagnostic bundle), send the file to the group, and say which step you are stuck on.
  The diagnostic bundle contains the duck's serial number and LAN IP; send it privately if you mind.

## 8. Advanced (not needed for normal use)

- **SSH remote login** (log in and fix problems yourself without reflashing the card): “SSH 远程登录” (SSH remote login) on Studio's “更多” (More) page.
  First set the web login password as above, then **choose your own SSH password** (at least 8 characters, not `microduck`), and tap “打开 SSH 密码登录” (Enable SSH password login).
  The card shows the login command, e.g. `ssh radxa@duck-xxxx`: run it in PowerShell on Windows or Terminal on Mac, and enter the password you just set.
  This password is also the `sudo` password on the duck. When you no longer need it, tap “关掉 SSH 密码登录” (Disable SSH password login) to go back to keys only.
  From the factory, SSH only accepts keys, not passwords; the image **contains no one's keys**, and there is no default password that allows remote login.
- **Local login** (with a monitor and keyboard attached): username `radxa`, default password `microduck`; root cannot log in. After logging in, change it with `passwd`.
- **Register an SSH key** (no password, more secure): “办法二” (Method 2) on the same “SSH 远程登录” (SSH remote login) card.
  If you do not have a key yet, on Windows run `ssh-keygen -t ed25519` in PowerShell and press Enter through all prompts;
  then run `type $env:USERPROFILE\.ssh\id_ed25519.pub` (Mac: `cat ~/.ssh/id_ed25519.pub`), paste the whole line it prints, and tap “登记这把钥匙” (Register this key).
  **Paste only the `.pub` one**; the other one is the private key, never give it to anyone. Registered keys are listed on the card and can be deleted.
- **Studio login password**: set it on the “更多” (More) page. You can also run `python3 -I /home/radxa/studio-dev/run.py set-password` as radxa on the duck, **without sudo** (with sudo, Studio cannot read the password file).
  While no password has been set, anyone who opens Studio can set the first one, so set it yourself before going out to demonstrate.
- **Forgot the login password**: log in to the duck over SSH, delete the password file `/var/lib/microduck-studio/password.json` or `/home/radxa/studio-dev/state/password.json` (whichever exists), then run `sudo systemctl restart microduck-studio` to return to the no-password state.
- **Camera attached**: the image uses a test pattern by default, so a duck without a camera does not report errors. If you have a camera attached, change `source = "test"` in the `[media]` section of `/etc/robot/robotd.toml` to `source = "camera"`, then run `sudo systemctl restart mediad`.
- **Two default behaviors to know**: when the battery voltage is low it **does not shut down automatically**, it only shows a warning on the page; when you see the warning, stop and charge, and do not drain the battery completely;
  after the duck falls it **does not go limp automatically**; before picking it up, press Select or tap “卸力” (Torque off).
- **HTTPS certificate / phone microphone**: the first boot generates a local CA (`/etc/microduck/tls/`), and Studio starts with HTTPS automatically.
  Older ducks can migrate with `sudo microduck-firstboot --tls-only`; how to install the certificate on the phone and how to use it without WiFi is in [Studio's offline notes](../studio/deploy/OFFLINE.en.md).
- **What the image contains, and licenses**: the `/usr/share/doc/microduck/` folder on the duck, or the [image build notes](README.en.md).
