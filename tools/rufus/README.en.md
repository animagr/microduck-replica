# Rufus · Windows card-flashing tool

**English** · [简体中文](README.md)

[Back to tools index](../README.md) · [Flashing and first use](../../software/image/烧录和第一次使用.md)

Used to write the duck image to a microSD card. Provided here is the official, unmodified **Rufus 4.15 portable edition for Windows x64**; no installation needed.

**[Download rufus-4.15p.exe](rufus-4.15p.exe)** · [Official release page](https://github.com/pbatard/rufus/releases/tag/v4.15) · [Other platforms and newer versions](https://rufus.ie/zh/)

## Flashing steps

1. Download the duck's `.img.xz` image, put the microSD card in a card reader and connect it to the computer.
2. Open Rufus and under **Device** (「设备」 in the Chinese UI) check the SD card's capacity and drive letter. **Writing erases all data on the selected card.**
3. Click **SELECT** (「选择」) and choose the image file. If the file filter does not show `.img.xz`, switch it to all files.
4. Double-check the target card, click **START** (「开始」), wait until the status returns to **READY** (「准备就绪」), then safely eject the card reader.
5. When Windows asks to format the Linux partition, click **Cancel** (「取消」). Put the card back into the duck and continue with [first boot and network setup](../../software/image/烧录和第一次使用.md#3-第一次开机).

## Source and verification

The official release was checked on 2026-10-25. The EXE's SHA256 matches the GitHub release asset, the Windows digital signature is valid, and the signer is Akeo Consulting; the downloaded file has not been modified.

| File | Purpose |
|---|---|
| [rufus-4.15p.exe](rufus-4.15p.exe) | Windows x64 portable edition |
| [rufus-4.15-source.zip](rufus-4.15-source.zip) | Official source code of the same version, with build files and component licenses kept |
| [LICENSE.txt](LICENSE.txt) | Rufus's GPL-3.0-or-later license |
| [SHA256SUMS.txt](SHA256SUMS.txt) · [SOURCE.json](SOURCE.json) | Checksums, download source and version record |

To verify the file, run `Get-FileHash .\rufus-4.15p.exe -Algorithm SHA256` in PowerShell and compare it with `SHA256SUMS.txt`.

Rufus is written by Pete Batard / Akeo Consulting; source code and updates are maintained at [pbatard/rufus](https://github.com/pbatard/rufus).
