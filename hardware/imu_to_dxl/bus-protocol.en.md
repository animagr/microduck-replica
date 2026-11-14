# `imu_to_dxl` bus protocol · firmware implementation spec

**English** · [简体中文](总线协议.md)

This is the interface contract for **whoever writes the firmware**. The board's job in one sentence:

> **Pose as a servo with ID 200 on the servo bus, and return IMU data when the main controller reads it.**

Every tick (50 Hz), the main controller sends one `sync_read` that reads back ID 200 and all 15 servos at once. If the board fails to answer,
**the data of the 15 servos for that tick is lost along with it** (one sync_read is a single transaction).

- Executable version: [`tools/imu200/imu200.py`](../../tools/imu200/imu200.py), three in one: fake board, test vectors and acceptance check
- Acceptance check: once the firmware is written, run `python imu200.py check --port COMx`; it sends exactly the packets the main controller sends and judges exactly what the main controller judges
- The actual main controller code is in the fork's [`duck-control/src/imu.rs`](https://github.com/fanhao375/microduck/blob/feetech/duck-control/src/imu.rs)
  and `bus.rs`; every criterion in this document notes its source
- For the overall design background, see [Feetech adaptation architecture §4](../../software/飞特适配架构.md)
- **Firmware implementation**: [`firmware/`](firmware/) 0.2.0 (2026-09-22). The host tests and the `check` acceptance on a simulated bus running the real protocol code all pass; **the real bus is yet to be tested on hardware**. Items marked "0.2.0 implementation" below are refinements or corrections to the original spec made while writing the firmware, with the reasons noted alongside

> **Label conventions**: [Manual] = original text of official Feetech documentation; [Source] = a fact readable in the main controller code;
> [Inferred] = derived in this document from bandwidth and time budgets, **must be covered by bench measurements**.

---

## 1. Link

| Item | Value | Source |
|---|---|---|
| Physical layer | Single-wire half-duplex TTL, 3.3 V | [Manual] |
| Baud rate | **1 Mbps**, 8N1 | [Manual] factory default; register 6 = 0 |
| Byte time | 10 µs (10 bits/byte) | Calculated |
| Device ID | **200** (`0xC8`) | [Source] `bus.rs: IMU_DXL_ID` |
| Byte order | Little-endian | [Manual] magnetic encoder series |
| Frame format | `FF FF ID LEN INSTR/ERR ...params... CHK`, `LEN = number of params + 2`, `CHK = ~(ID+LEN+INSTR+Σparams)` | [Manual] `SCS通信协议` (SCS communication protocol) §3 |

**The STS series has no configurable response delay register**: address 7 in the STS memory table is a "reserved address", not Dynamixel's
return delay time (that is only the case in the SMS series). So timing can only be controlled by the firmware itself; see §5.

---

## 2. What the main controller sends

At runtime it sends **only one packet**:

```
sync_read (0x82)  address 56, length 15, ID list [200, 20..24, 30..34, 10..14]
ff ff fe 14 82 38 0f c8 14 15 16 17 18 1e 1f 20 21 22 0a 0b 0c 0d 0e 12
```

The debug console and the FD software also send `PING` and `READ`, and occasionally a stray `WRITE`. **The main controller never writes to this board or configures it at runtime**
[Source], so the firmware can simply hard-code its behavior.

---

## 3. The 15-byte block

15 bytes starting at address 56. **The main controller only looks at the first 12 bytes** [Source] `imu.rs: IMU_BLOCK_LEN = 12`; the last 3 bytes are there to make the block the same length as the servos'.

| Offset | Bytes | Content | Format |
|---|---|---|---|
| 0–1 | 2 | Gyro X | i16 little-endian, **17.5 mdps/LSB** (±500 dps range) |
| 2–3 | 2 | Gyro Y | Same as above |
| 4–5 | 2 | Gyro Z | Same as above |
| 6–7 | 2 | Quaternion x | IEEE 754 **binary16** (half precision), little-endian |
| 8–9 | 2 | Quaternion y | Same as above |
| 10–11 | 2 | Quaternion z | Same as above |
| 12 | 1 | **Sample count**, +1 for each new block of data, wraps 255→0 | u8 |
| 13 | 1 | **Status bits**, see §4 | u8 |
| 14 | 1 | Reserved, **the firmware must fill it with 0** | u8 |

**The quaternion's w is computed by the main controller** (`w = √(1 − x² − y² − z²)`) [Source]; the board must not send w.

### Coordinate frame: do not apply any transform

The block holds **raw data in the chip's native axis order**. The mounting rotation is done by the main controller (`DEFAULT_MOUNT` = +90° about Y,
torso = `[+raw_z, +raw_y, −raw_x]`) [Source].

> **The firmware must not reorder axes, flip signs or apply any coordinate transform.** If it guesses wrong, the duck will fall in the wrong direction,
> while every electrical-level check still passes. The board's mounting orientation must match the original; if it is mounted differently, change the main controller's mount quaternion, not the firmware.

---

## 4. Status byte (byte 13)

| Bit | Meaning |
|---|---|
| BIT0 | IMU fusion (SFLP) is not ready yet |
| BIT1 | Communication with the IMU chip failed (SPI/I²C error) |
| BIT2 | Self-test failed |
| BIT3 | Since the last read, the block was refreshed **more than 4 times** (≥ 5 times, meaning the main controller reads too slowly, < about 30 Hz). 0.2.0 implementation: originally written as "2 or more times"; with 120 Hz sampling and 50 Hz reading, each read already sees 2~3 refreshes, so half of all frames would report it, which is meaningless |
| BIT4–7 | Reserved, fill with 0 |

The main controller does not currently parse this byte; it is for humans and debugging tools. [Inferred] The bit definitions are set by this document, and the firmware and tools follow them.

Mapping in the 0.2.0 implementation: BIT0 = snapshot not ready or quaternion all 0; BIT1 = IMU error code is SPI / reset timeout / configuration / stale data / FIFO; BIT2 = error code is identity mismatch (WHO_AM_I ≠ 0x70).

---

## 5. Timing

**No Feetech document gives a value for the response delay**; the manual only says "servos return reply packets in the order of the IDs in the instruction packet".
So apart from the baud rate and frame lengths, **everything in the table below is derived from 1 Mbps and the tick budget and must be covered by bench measurements**.

| Item | Value | Source |
|---|---|---|
| Instruction frame (sync_read with 16 IDs) = 24 bytes | **240 µs** | Calculated |
| Single reply frame = 21 bytes | **210 µs** | Calculated |
| Pure wire time for 16 devices | 240 + 16×210 = **3.6 ms** | Calculated |
| Total budget for one tick | **< 6 ms** | [Source] acceptance criterion in item 4 of §5 of the architecture document |
| ⇒ Margin left for 16 bus turnarounds | 2.4 ms ÷ 16 = **≤ 150 µs on average** | Calculated |
| **T_resp**: last stop bit of the instruction frame → the board's first start bit | **Nominal 50 µs, jitter < 10 µs, hard limit 100 µs** | [Inferred] |
| Half-duplex DE assertion | Use hardware DE (`CR3.DEM=1`), with `DEAT`/`DEDT` suggested at 16 units each (≈ 1 µs at 1 Mbps OVER16) | [Inferred], check the bit fields against RM0444 |
| When DE is software-controlled | **Must be released on TC (transmission complete), not TXE** | Half-duplex pitfall number one: switching direction as soon as TXE is set cuts off the stop bit of the last byte, which shows up on the main controller as "occasional checksum errors" |
| Bus idle criterion | USART **IDLE** flag (1 idle frame = 10 bits = 10 µs), IDLE + DMA packet splitting | [Manual] STM32 USART |
| Partial frame discard | For a half-received frame, if the gap between bytes is **> 500 µs**, discard the whole frame and search for `FF FF` again | [Inferred] Without this, a truncated frame sticks to the next frame, an extra packet appears on the bus out of nowhere, and the main controller's whole sync_read gets misaligned. 0.2.0 implementation: originally 100 µs, relaxed to 500 µs. Frames are separated by at least the main controller's 20 ms tick, so partial frames are still discarded, while a USB-serial adapter occasionally inserting a gap of a few hundred microseconds mid-packet no longer causes good frames to be dropped; in addition, a checksum error drops 1 byte and searches for the header again, so it can recover from stuck-together frames without relying on the timeout |

**Timeouts are not the constraint.** On the main controller side, rustypot allows 30 ms per transaction and the debug console 60 ms to find a header; even a reply as slow as 1 ms would not time out,
but it would blow through the tick budget. Write the spec against the 6 ms budget, not against the timeouts.

> **First thing on the board**: measure the Feetech servos' own T_resp (put an ID at the front of the ID list and observe), and **use the same value for the board**.
> If the two sides have different rhythms, the reply order will drift.

### Queuing rules

The board **replies only when its own ID appears in the ID list, and must reply in its own position**.

At runtime 200 is always first in the list [Source] `bus.rs`, so this degenerates into "after the instruction frame is received, wait T_resp and send".
**But the firmware must not implement only this case**: during debugging 200 gets moved to the middle, and sending immediately would then collide with the servos' replies.

General implementation (recommended):

```
On receiving a sync_read with its own ID at list index k:
  k == 0  → wait T_resp, then send
  k > 0   → keep receiving before sending; on seeing the reply frame of the j-th device ahead (ID earlier in the list, length = read length + 2, 5th byte is not an instruction code)
            record "the first j+1 have replied",
            once all k ahead have replied → wait T_resp, then send;
            1 ms of bus silence → treat it as one device ahead being offline and record a gap (it must not stay silent forever when a device is offline)
  any other frame appearing while waiting (the main controller sent a new instruction) → this transaction is void; still not its turn after 25 ms → give up
```

0.2.0 implementation: originally written as "a k × 250 µs timeout fallback", which is not enough. A 15-byte reply frame is 21 bytes = 210 µs, and adding each device's T_resp already exceeds 250 µs; for positions further back, the fallback would trigger while a device ahead is still replying and collide directly. Changed to detecting absence by "bus silence".

---

## 6. Power-up timing

| Item | Requirement | Source |
|---|---|---|
| Bus handler | Must be able to reply **within 50 ms** after VCC becomes valid | [Inferred] |
| While the IMU is not ready | **Return an all-zero quaternion; never stay silent** | [Source] the board not answering = the data of all 15 servos for that tick is lost |
| Meaning of an all-zero quaternion | The main controller reuses the previous frame and does not count it toward ready | [Source] `imu.rs` |
| Reaching ready | The main controller needs a **cumulative** (not consecutive) 25 frames of valid quaternions to count as ready, ≥ 0.5 s at 50 Hz | [Source] `imu.rs: quat_samples` |

---

## 7. How the main controller decides a frame is valid (the firmware must satisfy this)

[Source] `imu.rs`; every item must pass, otherwise the frame does not count:

1. The three quaternion components are **not all 0**
2. All three components are **finite** (not inf / NaN)
3. **norm² = x²+y²+z² ≤ 1.02**
4. After multiplying by the mount conjugate, **norm > 0.5**

> If any of these four fails, the main controller treats the frame as never having arrived. **The `imu200.py` tool uses the same criteria**,
> so do not expect "it passes the tool but the main controller is pickier", or the other way round.

### Freeze detection: two prohibitions for the firmware

The main controller's `bus.rs: StaleImuTracker` **compares the first 12 bytes byte by byte**, and reports
`orientation is frozen` if 25 consecutive frames are identical. This gives two hard constraints:

1. **Do not smooth or quantize the gyro** to the point where the low bits stop changing at rest. A real chip's low bits jitter at rest anyway, so the block changes byte by byte.
   With smoothing, the main controller reports a freeze 0.5 seconds after the duck goes still.
2. **Do not rely on byte 12/13 to look alive**: the sample count and status bits are at 12 and 13, **outside the main controller's 12-byte window**,
   so changes in them do not make the block "look fresh".

---

## 8. How to reply to other instructions

| Instruction | Behavior |
|---|---|
| `SYNC_READ 0x82` address 56 length 15 | Reply with the 15-byte block following the rules in §5 |
| `PING 0x01` (unicast) | Return a status frame, ERROR = 0 |
| `PING` (broadcast `0xFE`) | **No reply** [Manual] §4.1: broadcast PING must not be used with multiple devices on the bus |
| `READ 0x02` | Return the bytes at the requested address (support at least 0–8 and 56–70) |
| `WRITE 0x03` (unicast) | **Return a status frame with ERROR=0 and ignore the content entirely**. Without a reply, the debug console stalls 60 ms on every write |
| Any broadcast instruction (except sync_read) | No reply [Manual] |
| `REBOOT 0x08` | Actually reboots, **no reply**, back within 800 ms (matching the servos' rhythm) [Manual] §4.12. Note: if a blank chip has not been power-cycled after its first flash, a soft reset enters ST's built-in bootloader, and the USART2 it listens on is exactly the servo bus; power-cycle once after flashing (see `踩坑记录` (pitfall log)) |
| `0x06` / `0x09` / `0x0A` / `0x0B`, `REG_WRITE 0x04`, `ACTION 0x05` (unicast) | ACK, no action |
| Unrecognized instruction (unicast) | No reply, counted in the diagnostic bad-packet counter (0.2.0 implementation) |

**The ERROR byte of reply frames is always `0x00`.** The debug console and FD decode it as servo status bits; a non-zero value produces baffling overvoltage/overtemperature warnings.

---

## 9. Register area (for debugging tools to read)

| Address | Content |
|---|---|
| 0–1 | Firmware version (major.minor); **use your own version number, do not pose as the servos' 3.46**; 0.2.0 is `0, 2` |
| 2 | END byte order = **0** (little-endian); the debug console asserts this |
| 3–4 | Model (custom); 0.2.0 is `0x4D44` |
| 5 | ID = 200 |
| 6 | Baud rate = 0 (1 Mbps) |
| 8 | Response status level = 1 |
| 56–70 | The block from §3 (15 bytes) |

---

## 10. Test vectors

All generated by [`imu200.py vectors`](../../tools/imu200/imu200.py), with checksums already computed; they can be sent directly from a serial terminal:

```
The full sync_read sent by the main controller every tick (16 IDs, 200 first)
  ff ff fe 14 82 38 0f c8 14 15 16 17 18 1e 1f 20 21 22 0a 0b 0c 0d 0e 12

Ask only 200 (for debugging)
  ff ff fe 05 82 38 0f c8 6b

PING 200
  ff ff c8 02 01 34

Reply · fusion has no output yet (quaternion all 0, status BIT0=1, count 0)
  ff ff c8 11 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 25

Reply · with data (gyro +1.75 / −0.875 / +0.0525 dps, quaternion z = 0.3827, count 7)
  ff ff c8 11 00 64 00 ce ff 03 00 00 00 00 00 20 36 07 00 00 95
  data part  64 00 ce ff 03 00 00 00 00 00 20 36 07 00 00
```

Gyro +1.75 dps → `1.75 / 0.0175 = 100` → `64 00`; quaternion z = 0.3827 → half precision `0x3620` → `20 36`.

---

## 11. Acceptance check

```bash
cd tools/imu200
python imu200.py demo                 # first see how the fake board answers (no hardware needed)
python imu200.py check --port COM6    # connect the real board; 13 items, each PASS/FAIL
```

`check` verifies the following (all using the main controller's real criteria):

- PING gets a reply, and how long after power-up it can reply
- Unicast READ can read the block, the reserved byte is 0, END = 0
- **Full sync_read with 16 IDs**: the IMU and all 15 servos reply, `bad_id = 0` (one misalignment ruins everything after it), no checksum errors
- Sample count +1~4 per frame (constantly 0 = the IMU has no output but the bus handler is still alive)
- Longest run of identical 12-byte windows < 25 frames (freeze criterion)
- Number of frames the main controller would accept, and how long until ready
- **Transaction time p99 < 6 ms** (the tick budget, not the 60 ms timeout)
- Broadcast PING gets no reply, and writing registers does not break the board

Logs go to `tools/imu200/logs/`: raw send/receive hex + one JSONL line per frame (frame number, duration, count, raw gyro values,
quaternion bit patterns, 12-byte window). Problems like "occasional dropped frames" or "data not moving" are tracked down by going through this file.

One more item must be confirmed by hand because the tool cannot test it: **with the board lying level at rest, the decoded gravity should be ≈ `[0, 0, −1]`**
(`decode_block` in `imu200.py` gives `gravity`). A board mounted 90° off passes every check above, and then the duck falls in the wrong direction.

---

## 12. Still open / to be measured

| Item | Status |
|---|---|
| Real value of T_resp | Waiting to measure the Feetech servos' own response delay; the board takes the same value (firmware `PROTO_RESPONSE_DELAY_US`, currently 50 µs) |
| Time from SFLP power-up to the first non-zero quaternion | To be measured; an upper bound should be written into this document |
| Whether the status bits are enough | BIT4–7 are kept free, to be added if testing shows a need |
| Exact `DEAT`/`DEDT` bit fields | To be hard-coded after checking against RM0444 |

---

> This board is a third-party replica part; the official project has never published its schematic, firmware or protocol. This document is the result of reverse-engineering from the official runtime source code +
> our own definitions, and **has not been verified on physical hardware**. If you find a problem, please open an [issue](https://github.com/fanhao375/microduck-replica/issues).
