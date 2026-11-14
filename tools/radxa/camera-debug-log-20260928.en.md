# Radxa Zero 3W / Camera 8M219: images captured after adjusting the ribbon cable

**English** · [简体中文](摄像头调试记录-20260928.md)

On 2026-09-28, under the official Bookworm KDE B1, the IMX219 chip ID was read and a **40-frame, 1920×1080 short capture** was completed. After the user checked and adjusted which side of the ribbon cable faced which way, the earlier detection failure went away.

## Read this first for wiring

<p align="center"><img src="../../assets/hw/radxa-camera-cable-reference-20260928.png" alt="Camera wiring reference: lens side facing the viewer, Radxa and UKCA markings visible on the back of the board, ribbon cable in a U shape" width="420"></p>

*Image provided by the project maintainer as a reminder of the orientation at both ends of the cable; it is not a photo of this test setup, nor a captured frame. The connector position may differ between camera modules.*

In the image, the lens side is on the left and the back of the board is on the right. **At both ends, check that the exposed metal contacts face the metal spring contacts inside the socket**; do not go only by the printed side of the cable, its color, or the copper traces under the coating. The overall pose in the photo is only for comparison and cannot replace checking the contacts.

- ZERO 3W / 3E with the Radxa Camera 8M219: the official spec is a **22-pin, 0.5 mm → 15-pin, 1.0 mm, same-side-contact ribbon cable**. "Same side" means that when the cable lies flat naturally, the exposed contact areas at both ends are on the same side.
- **Shut down properly first, then cut all power, including HAT and USB, before operating the latch and the cable.** A system shutdown does not mean the connector is unpowered.
- Insert it straight and all the way in, confirm there is no sideways misalignment, and lock it according to the connector's actual design. Do not flip the cable to test the orientation while powered.
- The official generic ZERO 3 tutorial uses a Pi Camera V1.3 / OV5647 as the example; do not apply that example's lens orientation directly to the 8M219.

## System and configuration used this time

| Item | This hardware test |
|---|---|
| Board | Radxa Zero 3W; the device tree compatible list includes `radxa,zero3w-aic8800ds2` |
| Camera | **Radxa Camera 8M219 (IMX219)**; having the same chip does not mean the actual module is a Raspberry Pi Camera V2 |
| System | Official Bookworm KDE B1 / Debian 12 |
| Kernel | `6.1.84-10-rk2410-nocsf` |
| Camera overlay | `/boot/dtbo/radxa-zero3-radxa-camera-8m.dtbo` |
| Image processing service | `rkaiq_3A.service`, active during capture |
| Successful output | `/dev/video0` (rkisp_mainpath), 1920×1080 JPEG |

The base flashed to the card comes from [Radxa's official rsdk-b1](https://github.com/radxa-build/radxa-zero3/releases/tag/rsdk-b1). On my test card, the only changes were presetting Wi-Fi and enabling SSH in the official first-boot configuration; the bytes outside the configuration partition are identical to the original. **The camera overlay was enabled separately after boot with the official tool**; it is not enabled by default on the original card.

This official test card is not the same as the finished Armbian card in this folder; the accounts, kernel and boot configuration differ, and the robot runtime was not installed on the official card in this round. The Armbian card's promise that "a COM port appears automatically when plugged into a computer" does not apply to the official card either.

## Evidence from detection failure to success

Before the cable was adjusted, both the original Armbian and the official B1 showed:

```text
imx219 2-0010: Reading register 100 from 10 failed
imx219 2-0010: Error -5 setting default controls
imx219: probe of 2-0010 failed with error -5
```

At that point, although `/dev/media0` and `/dev/video0..9` existed, there was no IMX219 sensor entity, `2-0010` had no driver bound, and a targeted read of the chip ID also returned ENXIO.

After adjusting the cable and powering up again, the official system read:

```text
imx219 2-0010: Model ID 0x0219, Lot ID 0x512035, Chip ID 0x0732
rkisp-vir0: Async subdev notifier completed
```

`2-0010` was bound to `imx219`, the media topology showed `m00_b_imx219 2-0010` (`/dev/v4l-subdev3`), the sensor → DPHY → ISP link was enabled, and an actual capture then succeeded.

## Retest commands under the official B1

These commands are for this version and the **8M219**; do not apply them directly to other cameras or to Armbian configuration files. First save the existing boot configuration, then enable the corresponding overlay with the official tool:

```bash
sudo rsetup enable_overlays radxa-zero3-radxa-camera-8m.dtbo
sudo reboot
```

After reconnecting over SSH, confirm layer by layer:

```bash
uname -r
sudo dmesg | grep -Ei 'imx219|rkisp|csi2-dphy'
readlink -f /sys/bus/i2c/devices/2-0010/driver
media-ctl -d /dev/media0 -p
systemctl is-active rkaiq_3A
```

After confirming that no other program is using the camera, capture a limited number of frames; this requires `gst-launch-1.0`, V4L2, video conversion and JPEG encoding plugins to be available on the system:

```bash
timeout 25s gst-launch-1.0 -e \
  v4l2src device=/dev/video0 io-mode=4 num-buffers=40 ! \
  video/x-raw,format=NV12,width=1920,height=1080 ! \
  videoconvert ! jpegenc ! \
  multifilesink location=/tmp/microduck-camera-check.jpg
```

This command writes to the same file repeatedly and keeps the **last frame** when it finishes; it does not save 40 photos. This time the output ended with a normal EOS and exit code 0 after about 4.05 seconds; the JPEG was downloaded, decoded and actually viewed, and an indoor scene was visible. The plugin scanner did print a `GstRtpSrc/GstRtpSink` duplicate registration warning, but the capture succeeded; this cannot be summarized as "zero errors in all logs".

## How far this has been verified

- **Verified**: with the current official configuration, the camera is detected, the media link is set up, a 40-frame short test completes and a real image is obtained.
- **Not verified**: a stable 30 fps, long captures, image quality tuning, the robot video service, and the result on the original Armbian with correct wiring. The sensor defaulted to 3280×2464 at about 21 fps at the time; a 1920×1080 JPEG output does not mean the sensor was switched to 1080p30.
- **Wiring conclusion**: the fault went away after adjusting orientation/contact; reseating the cable and whether the power setup changed were not fully isolated, so this does not prove that a reversed cable was the only factor.
- **Power caveat**: the user initially powered it as 7.4V → HAT → board; whether the board was later switched to independent USB power was not confirmed. This camera success does not count as an acceptance check of HAT load or of all functions.

Under HAT power, prefer Wi-Fi / SSH. On the V1.12 board, the 40-pin 5V and the VBUS of `5V IN / USB_OTG` are on the same net, so an ordinary USB data cable may introduce a second 5V source; do not combine power sources. The USB 3.0 port is a Host port, so switching to that port will not solve debugging over a computer connection. See the [USB port and power notes](镜像使用说明.md#3-第一次开机) for details.

## References

- [Radxa Camera 8M219 official docs and cable spec](https://docs.radxa.com/accessories/camera/camera-8m-219)
- [Official ZERO 3 camera connection and usage guide](https://docs.radxa.com/zero/zero3/accessories/camera)
- [Official board overview and interface description](https://docs.radxa.com/en/zero/zero3)
- [This project's debug log](../../调试记录.md) · [Pitfalls log](../../踩坑记录.md#主板--hat--摄像头)
