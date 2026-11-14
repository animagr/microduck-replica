# How It Works

**English** · [简体中文](实现原理.md)

This document describes the internal design of the IMU board's Feetech FT-SCS firmware (v1.0.0): the protocol frame state machine, SYNC READ ordering and collision avoidance,
the half-duplex physical layer, the IMU data path and the register map. Read it when porting, extending or troubleshooting the firmware.

---

## 1. System role and overall architecture

### 1.1 Role

- Hardware: STM32G031F8P6 (64MHz Cortex-M0+, 64KB Flash / 8KB RAM) + LSM6DSV16X 6-axis IMU.
- Role: a **slave (ID=200)** on the Feetech FT-SCS single-wire bus, sharing the line with Feetech servos (ID 2, 3, ...),
  at 1Mbps, 8N1, half-duplex.
- The data contract matches duck-control (the RK3566 side) in GitHub `pollen-robotics/microduck`:
  three gyro axes + SFLP floating-point quaternion x/y/z (w is recovered by the host), read with SYNC READ at 50Hz.
  This project does not run the Duck attitude algorithm and does not apply the mounting rotation; the rotation is done by upstream duck-control.
- Bare metal (no RTOS): all protocol logic runs in the main loop; the ISR only stores bytes with timestamps in a ring buffer.

### 1.2 Source file layers

| File | Responsibility |
|---|---|
| `Core/Src/board.c` / `board_config.h` | Clock (HSI16→PLL 64MHz), USART2 bus, USART1 log, SPI1, microsecond timer time base, IWDG, half-duplex send/receive, timestamped receive ring buffer |
| `Core/Src/protocol.c` / `.h` | FT-SCS frame parsing, checksum, instruction dispatch, SYNC READ ordered-reply state machine (~410 lines, no third-party code) |
| `Core/Src/control_table.c` | 256-byte register view: IMU snapshot packing, diagnostic block, writable marker / IMU re-initialization command |
| `Core/Src/imu.c` | LSM6DSV16X configuration, FIFO draining, SFLP attitude parsing, 120Hz sampling, failure detection and automatic recovery |
| `Core/Src/main.c` | Main loop scheduling: receive frames → protocol polling → IMU polling → logging, with protocol traffic first |
| `Drivers/LSM6DSV16X/` | ST's official register driver (register definition layer only) |

Data flow:

```
LSM6DSV16X ─SPI 2MHz─► imu.c FIFO/SFLP ─► imu_snapshot_t
                                              │ (read in the main loop, no tearing)
USART2 ISR ─► 256B ring buffer (with µs timestamps) ─► protocol.c ─► control_table_read ─► reply frame
                                              ▲
                                         proto_poll transmits when there is no bus activity
```

---

## 2. FT-SCS protocol implementation

### 2.1 Frame format

```
Request:  FF  FF  ID  LEN  INST  P_1 ... P_n        CK
Reply:    FF  FF  ID  LEN  ERR   D_1 ... D_d        CK
          └head─┘  └── LEN = 1(INST/ERR) + number of parameter/data bytes + 1(CK) = total length - 4 ──┘
```

- Total frame length = 4 + LEN bytes.
- Checksum (single-byte inverted sum):

  `CK = ~( ID + LEN + INST/ERR + Σ(parameters/data) ) & 0xFF`

  It covers only the bytes starting at ID, not the two `0xFF` header bytes.
- Broadcast ID = 254 (0xFE); valid slave IDs = 1..252.

Test vectors (useful for self-tests when porting):

| Frame | Bytes |
|---|---|
| PING ID200 request | `FF FF C8 02 01 34` |
| PING reply (ERR=0) | `FF FF C8 02 00 35` (note that the reply CK differs from the request) |
| READ 56/12 request | `FF FF C8 04 02 38 0C ED` |
| READ 12-byte reply | LEN = 12 + 2 = 14 |

### 2.2 Instruction set

| INST | Name | Parameters | Reply |
|---|---|---|---|
| 0x01 | PING | none | Empty status reply for unicast only; **broadcast PING is silent** (the servos on the bus answer; the IMU stays out of it) |
| 0x02 | READ | addr(u8), count(u8) | ERR + count bytes; count 1..128, addr+count ≤ 256; broadcast not accepted |
| 0x03 | WRITE | addr(u8), data… | ERR returned for unicast; silent for broadcast |
| 0x82 | SYNC READ | addr, count, id… (sent to broadcast) | Each slave replies in list order |
| 0x83 | SYNC WRITE | addr, dlen, [id, dlen bytes]… | Executed silently, no reply |
| Other | — | — | Always silently discarded |

Reg Write/Action/Bulk are not implemented, there are no Flash writes, and ID and baud rate are **fixed and cannot be changed** (writing 5/6 returns an access error).
There is **no return delay** (replies are scheduled immediately). Error codes follow Feetech semantics: 1 RESULT, 2 INSTRUCTION, 3 CRC,
4 RANGE, 5 LENGTH, 6 LIMIT, 7 ACCESS.

Frame size guard: `PROTO_MAX_READ=128`; the largest accepted LEN = 132 (a READ reply with 128 data bytes has LEN=130,
a single-segment 128-byte SYNC WRITE has LEN=132). A larger LEN is immediately treated as noise, so the receiver does not swallow a whole stretch of subsequent bus traffic.

### 2.3 Receive state machine (proto_feed, called per byte)

1. Search for two consecutive `0xFF`; extra leading FF bytes are allowed; ID=0/255 is treated as malformed and the search restarts.
2. As soon as LEN arrives, compute the full frame length (4+LEN), then collect bytes by length; it does not look for headers inside the data.
3. Once complete, a correct checksum → `rx_packets++` → `execute()`; an error → `checksum_errors++`,
   and the receiver scans back from the end of this frame for `0xFF` to try to rescue the next frame header nested in a falsely short frame (resynchronization).
4. If the gap between bytes exceeds 1500µs (`PROTO_BYTE_TIMEOUT_US`), the partial frame is discarded and `receive_timeouts` is incremented.
5. **Timestamps are taken when the ISR enqueues the byte** (not when the main loop dequeues it), which keeps the timing used for ordering decisions accurate.

### 2.4 Transmission and the "bus idle" principle

A reply is first assembled in `tx[]` and marked as scheduled (`schedule_reply`); the actual transmission happens in `proto_poll()`:

- `pending=1` (ready to send): the reply is sent only if `rx_length==0` (no frame is currently being received) and
  no more than 2000µs (`PROTO_REPLY_EXPIRY_US`) have passed since it was scheduled; otherwise this round is abandoned (yielding the bus).
- While `pending=1`, receiving any new byte cancels the reply immediately (`cancelled_replies++`):
  any other device talking means the bus no longer belongs to us.
- The main loop drains the receive ring buffer **before** calling `proto_poll`; this is the precondition for the checks above to hold.

---

## 3. SYNC READ ordered replies and collision avoidance (core mechanism)

### 3.1 The problem: a shared bus with no slot token

An FT-SCS SYNC READ frame carries the full ID list (e.g. `[2,3,200]`). Every slave sees all the IDs,
and the replies must come "in list order, without colliding". But the protocol has no explicit token: the host does not call on each device in turn,
so each slave must decide for itself when it is its turn.

The Feetech servo firmware (3.46 in hardware tests) **predicts its slot**: it does not wait for the previous device to finish replying,
but starts sending its own reply early, about "+180µs after the start of the previous frame". The IMU board has to coexist with this behavior.

### 3.2 Ordering state machine

The firmware walks the ID list to find its own position i (SYNC READ dispatch in `protocol.c`, around L260-263):

- **i is first (i==2, the first entry in the list)**: `schedule_reply(preceding=-1)` → `pending=1`,
  scheduled for immediate transmission.
- **Not first**: remember the "preceding ID" = the ID just before its own in the list, `pending=2`.
  Then, in `execute()`, it **sniffs the bus**: only after seeing a frame with a valid checksum from that preceding ID
  does it move `pending=2 → pending=1` ("the previous device has sent, it is my turn").
  - If no valid frame from the previous device arrives within 25ms (`PROTO_TRANSACTION_TIMEOUT_US`), it gives up this round
    to avoid grabbing the bus at random.
  - If, while waiting, it sees a new host frame addressed to itself or to broadcast, this round is void (a new transaction has started).

Valid ID list requirements: at least 1 ID, all within 1..252, no duplicates; if the list is malformed, the board does not reply even if its own ID is in it.

### 3.3 Measured collisions and the hard ordering rule

| Host list | IMU success rate (30 rounds) | Notes |
|---|---|---|
| `[200, 2, 3]` (IMU first) | **3/30** | The servo starts talking early at +180µs after the start of the IMU frame and hits exactly the IMU checksum byte |
| `[2, 200, 3]` (middle) | 30/30 | The IMU sends after hearing a valid frame from ID2 |
| `[2, 3, 200]` (last) | 30/30 | Same as above, preceding=3 |
| `[200]` (alone) | 30/30 | No servo follows, no collision |

**Conclusion: the host must place ID 200 after all servos (middle/last) or in a group of its own; first position is forbidden.**
In this project, `bus_monitor.py` always uses `[servos..., 200]` and `imu_monitor.py` lists only `[200]`.
(An artificial 506µs slot delay was tried in the past; it made things worse and was removed.)

### 3.4 50Hz time budget (why time is not the bottleneck)

At 1Mbps with 10 bits per byte (1 start + 8 data + 1 stop):

- SYNC READ request (with 3 devices, 11 bytes) ≈ 110µs;
- each 12-byte data reply (18 bytes) ≈ 180µs;
- one round with three devices takes ≈ 110 + 3×180 ≈ **650µs**, only **3.3%** of the 20ms period at 50Hz.

The margin is huge. The real constraint is not a lack of time but the electrical collisions caused by the servos' "predictive transmission",
so the fix is ordering + sniffing and yielding, not squeezing the slots.

---

## 4. Half-duplex physical layer

The board connects to the single-wire bus through a transceiver buffer (see `board.c board_bus_send`):

- **PA1 = 1OE# (direction enable, active low)**: pulled low before sending to drive the bus, pulled high after sending to release it.
- **PB7 = RX_EN**: pulled low while sending to **suppress the board's own echo** (otherwise it would receive the frames it sends);
  PA3 receive is held by a pull-up.
- Send sequence (with USART2 interrupts disabled to protect the critical section):
  1. Before sending, check again that there is no bus activity (`BUSY/RXNE/ORE/FE/NE/PE` all clear, ring buffer empty);
     if there is activity, abandon this transmission and increment `tx_busy_drops` (never overwrite bytes that are being received);
  2. PB7 suppresses echo → clear the TC flag → pull PA1 low;
  3. Write TDR byte by byte, then **wait for TC (transmission complete, including the last stop bit)** rather than TXE;
  4. Only then release PA1 and re-enable reception; there is a timeout guard (an upper bound computed from the byte count), and a timeout increments `tx_timeouts`.
- Receive: the USART2 interrupt pushes each byte into a 256-byte ring buffer (a power of 2) and records a microsecond timestamp;
  overflow increments `rx_overflows` (old data is not overwritten); hardware errors increment `uart_errors` and report `bus_fault`,
  and the main loop then calls `proto_reset_receiver()` to reset the frame state machine.

This "assemble frame → wait for idle → atomic transmit → wait for TC → release" timing guarantees that replies appear on the line intact
and do not get mixed up with incoming frames or with the board's own echo.

---

## 5. Register map (ID 200)

All multi-byte integers are **little-endian**. 0..9 are owned by the protocol layer (read-only, fixed values); everything else is packed on the fly by control_table.

### 5.1 Identity and configuration area (0..9)

| Address | Length | Content |
|---|---|---|
| 0..1 | 2 | Model 0x4D44 (little-endian: 44 4D) |
| 2 | 1 | Firmware version = 1 |
| 5 | 1 | ID = 200 (fixed) |
| 6 | 1 | Baud rate code = 0 (Feetech code 0 = 1Mbps, fixed) |
| 9 | 1 | Return delay = 0 (immediate reply) |
| 3,4,7,8 | — | Reserved, read as 0; the whole 0..9 area is read-only |

### 5.2 Fast block starting at 56 (same address as the servo status block; the core of SYNC READ 56/12)

| Address | Length | Content | Range/encoding |
|---|---|---|---|
| 56,58,60 | 3×i16 | Gyro gx,gy,gz (raw counts in the sensor axis frame) | ±500 dps, **17.5 mdps/LSB** |
| 62,64,66 | 3×u16 | Quaternion qx,qy,qz (**IEEE-754 fp16**, raw SFLP output) | w recovered by the host |
| 68,70,72 | 3×i16 | Acceleration ax,ay,az | ±4g, 0.122 mg/LSB |
| 74 | 1 | sample_count low byte | — |
| 75 | 1 | Status flags: bit0 ready, bit1 configured, bit2 error | — |
| 76 | 1 | WHO_AM_I = 0x70 (112) | — |
| 77 | 1 | IMU error code (see the enum in imu.h) | — |
| 78 | 1 | Clock status | — |
| 79 | 1 | Watchdog enabled = 1 | — |
| 80..83 | u32 | sample_count (number of accepted SFLP records, not the number of host reads) | — |
| 84 | 1 | **user_marker, the only freely readable/writable RAM byte** (there is no LED on the board) | — |
| 240 | 1 | Write 0xA5 → request IMU re-initialization; any other access is rejected | — |

**Why the fast block is at 56**: at the same address 56, Feetech servos provide position/speed/load/voltage/temperature/moving status
(pos i16, spd i16 with a direction bit, load i16, voltage at 62 in 0.1V, temperature at 63, moving at 66).
So **a single `SYNC READ 56/12`** lets the host fetch the IMU's gyro + quaternion and every servo's status at once,
with the device type distinguished by ID (200 is the IMU; the rest are decoded as servos). The content of the IMU block carries over microduck's
old DXL2@124 data block (gyro + SFLP xyz), so the host data contract is unchanged.

### 5.3 Diagnostic block 90..185 (24×u32, 96 bytes, revision 1)

imu_probe reads 90/96 during the acceptance check. In a healthy system, the key counters should stay at 0 over time, or only increase monotonically to reflect real events:

| Offset | Counter | Offset | Counter |
|---|---|---|---|
| 90 | gyro_count | 138 | malformed_packets |
| 94 | accel_count | 142 | rx_timeouts |
| 98 | uptime_ms | 146 | rx_packets (valid frames) |
| 102 | gyro data age ms | 150 | tx_packets |
| 106 | quaternion age ms | 154 | cancelled_replies (times yielded) |
| 110 | spi_errors | 158 | reset_flags |
| 114 | fifo_overflows | 162 | clock_hz (64000000) |
| 118 | invalid_quaternions | 166 | tx_timeouts |
| 122 | recovery_count (IMU restarts) | 170 | log_dropped (dropped log lines) |
| 126 | rx_overflows (ring buffer overflows) | 174 | diagnostic table version = 1 |
| 130 | uart_errors | 178 | tx_busy_drops (transmissions abandoned while busy) |
| 134 | checksum_errors | 182 | reserved (0) |

Each call to `control_table_read` builds an all-zero 256-byte table on the stack, takes one IMU snapshot and packs it all at once,
so the data returned by a single READ is inherently untorn (acquisition and the callback both run in the main loop, with no concurrency).

---

## 6. IMU data path (imu.c)

1. **SPI1, mode 3, 2MHz** (PCLK/32); the LSM6DSV16X is configured with gyro/accelerometer ODR 120Hz,
   gyro ±500dps, accelerometer ±4g, with the FIFO and SFLP (Sensor Fusion Low Power) attitude output enabled.
2. **Sampled at 120Hz, consumed at 50Hz**: each host period (20ms) contains 2 or more sensor updates;
   `imu_poll` drains the FIFO in one go (budget of 16 frames) and takes the latest valid record, which naturally absorbs jitter.
3. **Quaternion encoding**: the IEEE-754 half-precision (fp16) qx/qy/qz output by SFLP is used directly;
   the host recovers a non-negative `qw = sqrt(max(0, 1 - qx² - qy² - qz²))`. The firmware sends only 3 components to save bandwidth;
   the sign convention is owned by upstream duck-control.
4. **Ready/failure semantics**:
   - When not ready, the gyro and quaternion bytes are **all zero** (the not-ready marker kept from upstream);
     acceleration and counters are still readable for diagnostics;
   - gyro/quat data older than 100ms is treated as stale; FIFO, SPI, WHO_AM_I, configuration and quaternion validity
     each have their own error code (imu_error_t).
5. **Automatic recovery**: after a failure, the reset → WHO_AM_I → configuration sequence is rerun with a 1000ms backoff,
   with a 1500ms startup timeout; recovery does not clear lifetime counters, and `recovery_count` records the number of recoveries.
   The host can also request re-initialization by writing 240=0xA5, or by pressing `r` on the log port.
6. The main loop runs `imu_poll` only when "no command is being received and no reply is pending"; protocol traffic always has priority.

---

## 7. Main loop and engineering details

```c
board_init(); proto_init(..., control_table_read/write, send_packet); imu_init();
for (;;) {
    if (board_bus_take_fault()) proto_reset_receiver();      // reset the frame state machine after a UART fault
    while (board_bus_pop(&byte, &ts)) proto_feed(..., ts);   // drain RX first (using enqueue timestamps)
    proto_poll(now_us);                                      // transmit only when due and the bus is idle
    if (rx_length==0 && pending==0) {                        // do sensor work/logging only when the protocol is idle
        imu_poll();
        handle log port commands (s/l/r/?); print a status line every second;
    }
    board_watchdog_feed();                                   // IWDG
}
```

- Logging uses a separate USART1 (115200) with a 512B transmit ring buffer; log congestion only increments `log_dropped`
  and never blocks the protocol. DAP-Link CDC needs DTR/RTS asserted to produce output.
- IWDG is always on (`BOARD_ENABLE_WATCHDOG=1`); the clock is HSI16→PLL 64MHz and does not depend on an external crystal being fitted.
- All build-time board options are collected in `board_config.h` (baud rate, RX_EN pin, SPI speed, log swap, etc.).
- Build: `Tools/build.ps1` calls ArmClang on the command line; the output and build.json go to `Build/`;
  the linker script is `MDK-ARM/imu_to_dxl.sct`. Only one Keil project, for DAP, is kept (`imu_to_dxl_dap.uvprojx`).

---

## 8. How the host tools reuse the same contract

The Python tools under `Tools/` are reference implementations of the protocol and can be used directly as a reference for your own host:

- `imu_monitor.py` exports the frame primitives `ft_frame() / checksum() / build_sync_read() / parse_reply()`;
  the parse slice `body = buf[2 : 4+len]` and stepping by 4+len match the firmware frame state machine exactly.
- `bus_monitor.py` sends one broadcast SYNC READ 56/12 with the list `[servos..., 200]` on a 20ms period;
  goal positions are sent all at once with one broadcast SYNC WRITE 0x83 (addr 42, 2B),
  with automatic fallback to individual writes for servos that do not respond to SYNC WRITE; before receiving each round it clears the parse buffer and the serial input buffer,
  so late frames do not pollute the next round.
- Host-side data decoding: gyro×0.0175 gives dps; convert fp16→float32 and then recover qw;
  ready/whoami/age and the diagnostic counters are used to judge health.

When porting to the RK3566 or another controller, both hard rules must be carried over:
**(1) put ID 200 after the servos in the SYNC READ list; (2) gyro 17.5mdps/LSB, quaternion fp16, qw recovered by the host.**

---

## 9. Testing and validation strategy

Hardware-free host tests (`Tools/test.ps1`, compiling C test cases with gcc):

- `Tests/protocol_test.c`: 93 assertions, covering framing/checksum vectors, PING/READ/WRITE,
  SYNC READ immediate reply when first / sniffed reply when not first / timeout skip when the preceding device is missing / voiding on a new frame, recovery from malformed frames and timeouts,
  silent broadcast PING, and more; `proto_context` is only 1104 bytes.
- `Tests/control_table_test.c`: 18 register map and boundary checks.
- `Tests/imu_test.c`: 16 IMU scenarios (with the `Tests/imu_board/board.h` stub),
  covering FIFO/SFLP/failure recovery.
- `Tests/probe_test.py`: 9 offline probe decoding checks.

Hardware acceptance data (2026-09, Feetech firmware 3.46, 8.0V, 1Mbps): probe 249/250 (a single transient timeout),
imu_monitor 251/251 with zero errors, bus_monitor without demo 598/598, with demo 741/741 and no fallback.
