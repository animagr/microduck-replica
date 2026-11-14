# Feetech Servo Documentation and SDKs

**English** · [简体中文](README.md)

[Back to tools index](../../tools/README.en.md) · [Feetech official e-manual](http://doc.feetech.cn/#/prodinfodownload?srcType=FTServo-emanual-ab4947a479784a71a8cb7928)

## Current documents on the official site

Checked against the official index and content API of the Feetech documentation site on 2026-10-25. The update times in the table below come from the site's `lastModifiedDate` field and are not the same as the release date on each document's cover.

| Document | Version listed on the site | Last updated on the site (UTC+8) |
|---|---|---|
| [SCS communication protocol](http://doc.feetech.cn/#/f?q=2506ba160b93) | 1.0 | 2026-10-08 |
| [STS memory table](http://doc.feetech.cn/#/f?q=2506abfb1cb0) | 1.1 | 2026-10-08 |
| [SMS memory table](http://doc.feetech.cn/#/f?q=2602a06ca658) | 1.1 | 2026-10-08 |
| [FD debugging software and serial tool](https://gitee.com/ftservo/fddebug) | As released in the official repo | [Download and notes in this repo](../../tools/飞特/README.en.md) |
| [HD-1910-C001 datasheet](../../tools/FeeTech_HD1910M_Servo/HD-1910-C001串型规格书20260907.pdf) | File dated 2026-09-07 | Model datasheet already in this repo |

## Offline copies (2026-09-17 snapshot)

Below are copies of the e-manuals saved on 2026-09-17, kept for searching and for cross-checking against the [Feetech adaptation architecture](../../software/feetech-adaptation-architecture.en.md). **The official site has been modified since; the offline copies keep their original dates. The official site is authoritative for current content.**

| File | Version | Site update date | Purpose |
|---|---|---|---|
| [`SCS通信协议-v1.0-2026-06-09.md`](SCS-communication-protocol-v1.0-2026-06-09.en.md) | v1.0 | 2026-06-09 | Packet format, instruction table. **This version has the reboot instruction 0x08, parameter backup 0x09 and status reset 0x0A**, which the 2019 version lacks |
| [`磁编码STS内存表手册-v1.1-2026-08-27.md`](magnetic-encoder-STS-memory-table-v1.1-2026-08-27.en.md) | v1.1 | 2026-08-27 | Memory table for the STS series that the HD-1910 belongs to: EEPROM / SRAM regions, factory defaults, lock flag semantics, status bit definitions |
| [`磁编码SMS内存表手册-v1.1-2026-08-27.md`](magnetic-encoder-SMS-memory-table-v1.1-2026-08-27.en.md) | v1.1 | 2026-08-27 | Same as above, SMS (RS485) version. Differences from STS: 7 is the response delay (reserved on STS), 33 operating mode range is 0~2, 40 torque switch has no damping value 2, 83 is Hts, and phase BIT5 has a different meaning |
| `磁编码SMS&STS&HTS-十六进制指令生成表-250508.xlsx` (magnetic encoder SMS/STS/HTS hex instruction generator) | 250508 | 2025-05-08 | Official Excel sheet: fill in parameters and it generates hexadecimal instruction frames automatically, ready to send from a serial terminal; includes ready-made examples for unlock / change ID / clear turn count / midpoint calibration |

For the HD-1910-C001's custom differences (factory mode 4, torque, gear ratio), see the [HD-1910 pre-training data checklist](../HD-1910-pre-training-data-checklist.en.md); the model datasheet is in the table above.

## Official SDKs

| Development environment | Official source code |
|---|---|
| Python | [FTServo_Python](https://gitee.com/ftservo/FTServo_Python) |
| Linux / C++ | [FTServo_Linux](https://gitee.com/ftservo/FTServo_Linux) |
| Arduino | [FTServo_Arduino](https://gitee.com/ftservo/FTServo_Arduino) |
| STM32 HAL | [FTServo_stm32HAL](https://gitee.com/ftservo/FTServo_stm32HAL) |

## How to check versions

How the documents were fetched (the documentation site's API, for the next update):

```text
Index    http://longbos.com:9009/workflow/yf-specification/getBysrcType/FTServo-emanual-ab4947a479784a71a8cb7928
Content  http://longbos.com:9009/workflow/yf-specification/getQr/<q>     q is the value of #/f?q=… in the index content
       STS memory table 2506abfb1cb0 · SMS memory table 2602a06ca658 · SCS protocol 2506ba160b93
Returns JSON; data.mdcontent is the Markdown content, data.lastModifiedDate is the update time
```
