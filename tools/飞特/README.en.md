# Feetech servo debug software

**English** · [简体中文](README.md)

Set IDs, change parameters, drag a slider and watch the servo turn. This folder keeps the Windows debug software and a copy of an old driver, and also links to the official drivers, a serial terminal and the latest materials.

| File | What it does | Version | Size |
|---|---|---|---|
| [FD1.9.8.5(250729).7z](FD1.9.8.5%28250729%29.7z) | **FD debug software**. Set IDs, enable overcurrent/overvoltage protection, drag sliders to test servos | 1.9.8.5 (2025-07-29), switchable between Chinese and English | 167 KB |
| [CH340_URT.rar](CH340_URT.rar) | **Copy of the old CH340 driver**. For the corresponding adapter chip; for the URT-2's CH343 driver, see the official links below | — | 224 KB |

## Installation

```
1  Plug in the URT-2 → USB-Enhanced-SERIAL CH343 (COMx) appears under "Ports" in Device Manager; note the number
   If it does not appear, first check the adapter chip model, then pick the matching driver from the official links below
2  Extract FD1.9.8.5(250729).7z → run it directly, no installation needed
3  In FD, select that COM port → baud rate 1000000 → click "Open" → click "Search"
```

If it finds the servo, you're connected. **How to wire jumpers, how to power it, setting IDs, which parameters to change, the ID mapping table**: all in [Debug log · Servo configuration](../../调试记录.md#舵机配置--拿到货一步一步做), step by step.

## Drivers and serial terminal

| Official link | Purpose |
|---|---|
| [CH343SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH343SER.ZIP) | For CH343 adapter boards such as the URT-2; no separate install needed if the system already recognizes it |
| [CH341SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH341SER.ZIP) | For adapter boards with CH340 / CH341 chips |
| [UartAssist.zip](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | General-purpose serial send/receive tool; sends and receives text or hex data according to the device protocol |

The official repository was checked on 2026-10-25, and FD 1.9.8.5 is still listed as the stable version. For later versions, the [official Feetech repository](https://gitee.com/ftservo/fddebug) is authoritative; for the protocol, memory table and SDK, see the [Feetech materials index](../../docs/飞特资料/README.md).

## Source and verification

Copied as is from the master branch of Feetech's official Gitee repository [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug) (2026-09-11), **MIT license** (`LICENSE` in the same folder).

```
sha256
FD1.9.8.5(250729).7z   33b92ac03ff048238bb6455a96aec98e97f6c87a97903ac197406f6d937c7734
CH340_URT.rar          546aaf96a54647f7a3ddd7e21389d64be2d198926c6058d8b19ee90e9eea4e17
```

If you suspect a file is corrupted, run `sha256sum` and compare against these two lines.

**Why it's in the repo**: Gitee sometimes requires a login to download and sometimes changes its folder structure; people who clone this repo shouldn't have to go hunting for it. MIT allows redistribution as is.
**To update**: get the new version from the repository above, replace the files, update the version numbers and hashes here, and update the version in [NOTICE](../../NOTICE.md).

## Web debug console

FD only runs on Windows. To install on the board, or if you want to watch a 3D model move along, use [`../servo-web/`](../servo-web/): `python server.py --port COM5`, open it in a browser and you can drag the sliders, and even export all registers 0–90 with one click.
