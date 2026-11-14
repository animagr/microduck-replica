# servo-web Browser-Based Host Tool: User Guide

**English** · [简体中文](servo-web使用.md)

Use the servo-web browser-based host tool on the RK3566 to view the IMU attitude and servo status in real time in a browser on your computer.

---

## 1. Prerequisites

| Item | Requirement |
|---|---|
| IMU board firmware | Feetech FT-SCS protocol firmware v1.0.0 flashed (ID=200, 1Mbps) |
| RK3566 | servo-web cloned to `/gitclone/microduck-replica/tools/servo-web/` |
| Bus serial port | `/dev/ttyS2` (RK3566 on-board serial port, connected directly to the IMU bus) |
| Network | RK3566 and computer on the same LAN (wlan0 IP, e.g. `<duck IP>`) |
| Browser | Chrome / Edge / Firefox (must support WebSocket and ES Modules) |

## 2. Starting the service

### 2.1 Log in to the RK3566 over SSH or serial

```bash
# Via SSH (SSH must already be configured)
ssh root@<duck IP>

# Or via the USB serial console (COM8 @ 1500000 baud)
# Connect with a serial terminal or Python pyserial and log in as root
```

### 2.2 Stop conflicting services

servo-web and robotd compete for the `/dev/ttyS2` bus, so robotd must be stopped before starting:

```bash
systemctl stop robotd
```

### 2.3 Start server.py

```bash
cd /gitclone/microduck-replica/tools/servo-web
nohup python3 server.py \
  --port /dev/ttyS2 \
  --imu-bus \
  --host 0.0.0.0 \
  --http-port 8080 \
  > /tmp/servo-web.log 2>&1 &
```

Parameters:

| Parameter | Meaning |
|---|---|
| `--port /dev/ttyS2` | Bus serial device |
| `--imu-bus` | Enables IMU bus mode (ID 200 is read in the same sync_read as the servos) |
| `--host 0.0.0.0` | Listens on all network interfaces (allows external access) |
| `--http-port 8080` | HTTP/WebSocket port |
| `> /tmp/servo-web.log 2>&1 &` | Runs in the background, log written to /tmp/servo-web.log |

### 2.4 Confirm the service has started

```bash
# Check the process
ps aux | grep server.py

# Check the log (it should show the bus opened and the IMU enabled)
tail -20 /tmp/servo-web.log
```

Example of a normal log:

```
[总线] 打开 /dev/ttyS2 @ 1000000 8N1
[IMU] 总线 IMU 已启用：ID 200 跟舵机在同一条 sync_read 里读（有网页连着才轮询）
```

(Meaning: "[Bus] opened /dev/ttyS2 @ 1000000 8N1" and "[IMU] bus IMU enabled: ID 200 is read in the same sync_read as the servos (polling only while a web page is connected)".)

## 3. Accessing the web page

### 3.1 Open the page

In a browser on your computer, go to:

```
http://<duck IP>:8080/
```

> Use the RK3566's actual wlan0 IP address; you can check it with `ip addr show wlan0`.

### 3.2 Page layout

The page title is "鸭子舵机调试台" (Duck servo debug console). From top to bottom:

1. **Connection status**: green dot in the top-left corner = WebSocket connected
2. **Servo scan area**: click the "扫描" (Scan) button to scan for bus devices
3. **Servo control area**: torque switch, target position/speed sliders
4. **IMU attitude panel** (`躯干姿态 · IMU`, torso attitude · IMU):
   - Mode label: `总线 · ID 200` (bus · ID 200)
   - Status label: `等待数据` (waiting for data) → `实时跟随` (live tracking) (turns green once valid data is received)
   - Roll / pitch / yaw angles (degrees)
   - Sample count, read rate (Hz), reference voltage (V)
   - Acceleration in g (three axes), angular rate in °/s (three axes)
   - Error counters: IMU / SPI / FIFO
   - Action buttons: 「当前姿态显示归零」 (Zero the displayed current attitude), 「原始姿态」 (Raw attitude)
   - Mounting orientation drop-down (different mounting orientations can be selected)
5. **Pose management area**: save/load/send preset poses
6. **3D visualization area**: torso attitude (rotated by the IMU quaternion) + joint poses (rotated by the servo positions)
7. **Log area**: real-time log at the bottom

### 3.3 Start viewing IMU data

**Once the page is connected, it starts reading IMU data automatically; no extra setup is needed.**

After the WebSocket connection is established, server.py's polling loop starts automatically, and every sync_read frame includes ID 200.
The IMU panel status changes from 「等待数据」 (waiting for data) to "实时跟随" (live tracking), and the angles and sample data start refreshing in real time.

### 3.4 Check that the IMU data is normal

Check in the IMU panel:

| Field | Normal value | Troubleshooting |
|---|---|---|
| Status label | `实时跟随` (live tracking, green) | If it shows 「等待数据」 (waiting for data) / 「数据无效」 (data invalid): check the IMU board power and whether the firmware has been flashed |
| Mode label | `总线 · ID 200` (bus · ID 200) | If the IMU panel is not shown: confirm that server.py was started with the `--imu-bus` parameter |
| Roll/pitch/yaw | Change as the board is rotated | Numbers do not move: check the bus wiring and whether /dev/ttyS2 is in use |
| Sample count | Keeps increasing | Not increasing: no response on the bus; check whether the IMU board is powered |
| Read Hz | 30~60 Hz | 0 or very low: check whether another process is using the bus |
| Acceleration / angular rate | Values on all three axes | All `—`: validPacket did not pass; check the ready/configured fields |

### 3.5 Servo operation (optional)

1. Click the "扫描" (Scan) button and wait for the scan to finish (about 2 seconds)
2. The list of online servos is shown in the scan area
3. Click 「扭矩开」 (Torque on) to enable servo torque
4. Drag the sliders to set the target position, or click a preset pose button
5. When finished, click "扭矩关" (Torque off)

> **Safety note**: with torque enabled the servos hold their position; first make sure nothing interferes within the servo horn's range of motion.

## 4. Test procedure

### 4.1 Basic connection test

1. Confirm that the IMU board is powered and the bus is connected to `/dev/ttyS2`
2. Stop robotd: `systemctl stop robotd`
3. Start server.py (see section 2.3)
4. Check the log for errors: `tail -20 /tmp/servo-web.log`
5. Open `http://<duck IP>:8080/` in a browser on your computer
6. The green dot in the top-left corner lights up = WebSocket connected successfully
7. The IMU panel appears and its status shows "实时跟随" (live tracking)

### 4.2 IMU data verification

1. Leave the IMU board still and check that the angle values are stable (roll/pitch close to 0°)
2. Slowly tilt the board; the roll/pitch angles should follow
3. Rotate the board horizontally; the yaw angle should change (note: six-axis yaw drifts, which is normal)
4. The sample count keeps increasing and the read rate is in the 30~60 Hz range
5. The error counters (IMU/SPI/FIFO) stay at 0

### 4.3 Zeroing and raw attitude

1. Place the board in the desired "zero" attitude
2. Click 「当前姿态显示归零」 (Zero the displayed current attitude): the current attitude is set to 0° (affects only the page display, nothing is written to the hardware)
3. Rotate the board; the angles are shown relative to the zero
4. Click 「原始姿态」 (Raw attitude): switches back to the raw attitude display, including the mounting orientation

### 4.4 Combined servo test

1. Click "扫描" (Scan) and confirm the servos are online
2. Click 「扭矩开」 (Torque on)
3. Drag the position slider; the servo should follow
4. At the same time, check that the IMU panel data is unaffected (the IMU and servos are read in the same frame)
5. When finished, click "扭矩关" (Torque off)

### 4.5 Multi-device same-frame read verification

1. Connect the IMU board + 1~2 Feetech servos to the bus
2. Start server.py and open the web page
3. The scan finds the IMU (ID 200) + servos
4. The IMU panel shows "实时跟随" (live tracking) + the servo position data refreshes at the same time
5. The read rate is stable (it does not drop noticeably because of multiple devices)
6. No ck_err / timeout errors in the log

## 5. Stopping the service

```bash
# Find the process ID
ps aux | grep server.py

# Stop it
kill <PID>

# Or do it in one command
pkill -f 'python3 server.py'

# Restore robotd (if needed)
systemctl start robotd
```

## 6. Troubleshooting

| Symptom | What to check |
|---|---|
| The browser cannot open the page | Whether the RK3566 is on, whether the IP is correct, whether the firewall allows port 8080 |
| Gray dot in the top-left corner (cannot connect) | Whether server.py is running; confirm the process with `ps aux \| grep server.py` |
| IMU panel not shown | Whether server.py was started with the `--imu-bus` parameter; whether the log shows "IMU 已启用" (IMU enabled) |
| Status shows 「等待数据」 (waiting for data) | Whether the IMU board is powered, whether the bus wiring is correct, whether `/dev/ttyS2` is held by robotd |
| All angles show `—` | validPacket did not pass: confirm that the imu_bus.py live frame contains `ready=1, configured=1` |
| Sample count not increasing | No response on the bus: check whether the IMU board has been flashed with the Feetech protocol firmware and whether its power is normal |
| Read rate is 0 | No web page connected (polling only starts when there is a WebSocket client); or calibration is in progress |
| No servos found in the scan | Whether the servo power (VDD_BUS) is normal, whether the IDs are within the scan range, bus wiring |
| Servos do not move | Whether 「扭矩开」 (Torque on) was clicked after scanning, whether the mode/speed registers are correct |
| Log reports ck_err / timeout | Bus interference, leads too long, missing termination resistor; whether ID 200 is last in the SYNC READ list |
| `/dev/ttyS2` in use | Use `fuser /dev/ttyS2` to see which process holds it; kill it first or run `systemctl stop robotd` |

## 7. Feetech FT-SCS protocol

### 7.1 Frame format

The IMU board uses the Feetech FT-SCS (Feetech Servo Communication Serial) half-duplex bus protocol
and runs on the same bus as Feetech SCS/STS servos. All frames use the same format:

```
Request frame:   FF FF  ID  LEN  INST  P1..Pn  CK
Response frame:  FF FF  ID  LEN  ERR   D1..Dd  CK
```

| Field | Description |
|---|---|
| `FF FF` | Frame header (2 bytes, always 0xFF 0xFF) |
| `ID` | Device address (1 byte; 0xFE=broadcast, 1~252=unicast) |
| `LEN` | Length (1 byte; = 2 + number of parameter/data bytes) |
| `INST`/`ERR` | Instruction code (requester) / error code (responder) |
| `P1..Pn`/`D1..Dd` | Parameters (requester) / data (responder) |
| `CK` | Checksum (1 byte) |

Total frame length = 4 + LEN bytes.

### 7.2 Checksum algorithm

```
CK = ~(ID + LEN + INST/ERR + sum(P1..Pn/D1..Dd)) & 0xFF
```

- Add up all bytes from ID to the last data byte and take the low 8 bits
- Invert and take the low 8 bits
- The FF FF frame header is not included in the checksum

Firmware implementation (`protocol.c`):

```c
uint8_t proto_checksum(const uint8_t *bytes, uint16_t length) {
    uint16_t sum = 0;
    for (uint16_t i = 0; i < length; ++i)
        sum += bytes[i];
    return ~(uint8_t)(sum & 0xFF);
}
```

### 7.3 Instruction set

| Instruction code | Name | Description |
|---|---|---|
| 0x01 | PING | Unicast replies with an empty status frame; broadcast PING gets no reply |
| 0x02 | READ | Read registers (addr u8, count u8); unicast |
| 0x03 | WRITE | Write registers (addr u8, data...); unicast ACK, broadcast silent |
| 0x82 | SYNC READ | Broadcast read (addr, count, id...); each ID replies in turn in list order |
| 0x83 | SYNC WRITE | Broadcast write (addr, dlen, [id, data]...); silent |

The IMU board's identity registers (addresses 0~9) are read-only; a WRITE to them is rejected with ERR_ACCESS(7).
Address 85 (user_marker) accepts a 1-byte write, and writing 0xA5 to address 240 triggers IMU reinitialization.

### 7.4 Error codes

| Code | Name | Meaning |
|---|---|---|
| 0 | OK | Success |
| 1 | RESULT | Result error |
| 2 | INSTRUCTION | Instruction error |
| 3 | CRC | Checksum error |
| 4 | RANGE | Address range error |
| 5 | LENGTH | Length error |
| 6 | LIMIT | Limit error |
| 7 | ACCESS | Access error (write to a read-only area, write to the identity area, etc.) |

### 7.5 SYNC READ ordered response rules

SYNC READ is a broadcast instruction; multiple devices reply in turn in the order of the ID list. The response rules of the IMU board (ID=200)
(`protocol.c`):

1. **ID 200 first in the list** (`i == 2`): replies directly, but the Feetech servos start transmitting early, causing collisions
   (only 3/30 succeeded in testing); **do not order it this way**
2. **ID 200 in the middle/last position of the list**: waits for the preceding ID's response frame to pass on the bus, then sends its own response
   (30/30 succeeded in testing)
3. **Predecessor did not respond / checksum error**: the IMU board skips this round to avoid a bus collision
4. **Timeout protection**: waiting for the predecessor for more than 25ms (`PROTO_TRANSACTION_TIMEOUT_US`) cancels automatically

> **The host must place ID 200 after the servos** (`[servo IDs..., 200]`) or in a group of its own (`[200]`).

---

## 8. Register definitions

### 8.1 Identity area (addresses 0~9, read-only)

| Address | Field | Value | Description |
|---|---|---|---|
| 0 | Firmware version Major | 1 | |
| 1 | Firmware version Minor | 0 | |
| 2 | Byte order | 0 | 0=little-endian |
| 3-4 | Model | 0x4D44 | Low byte first (3=0x44, 4=0x4D) |
| 5 | Device ID | 200 | Fixed, not writable |
| 6 | Baud rate code | 0 | 0 = 1,000,000 bit/s |
| 7 | Reserved | 0 | |
| 8 | Status level | 1 | Returns the error code (when non-zero) |
| 9 | Reserved | 0 | |

### 8.2 Fast block (addresses 56~70, 15 bytes)

Same address (56) as the Feetech servo status block, so one SYNC READ 56/15 reads the IMU board and all servos at the same time.

| Offset | Address | Field | Type | Description |
|---|---|---|---|---|
| 0-1 | 56-57 | Gyroscope X | i16 LE | Range ±500 dps, 17.5 mdps/LSB |
| 2-3 | 58-59 | Gyroscope Y | i16 LE | Same as above |
| 4-5 | 60-61 | Gyroscope Z | i16 LE | Same as above |
| 6-7 | 62-63 | Quaternion X | fp16 (binary16) | SFLP format, x component |
| 8-9 | 64-65 | Quaternion Y | fp16 | SFLP format, y component |
| 10-11 | 66-67 | Quaternion Z | fp16 | SFLP format, z component |
| 12 | 68 | Sample count | u8 | Low 8 bits of the SFLP record count, +1~4 per frame |
| 13 | 69 | Status bits | u8 bitfield | See 8.3 |
| 14 | 70 | Reserved | u8 | Always 0, checked by server.py |

The quaternion w component is not transmitted on the bus; the host reconstructs it:

```python
norm2 = x*x + y*y + z*z
w = sqrt(max(0, 1 - norm2))    # if norm2 > 1, normalize xyz
```

Gyroscope conversion:

```python
gyro_dps = raw_i16 * 0.0175    # 17.5 mdps/LSB → dps
```

### 8.3 Status bit definitions (address 69)

| Bit | Name | Value | Meaning |
|---|---|---|---|
| BIT0 | FUSION_NOT_READY | 0x01 | Fusion not ready (quaternion all 0 or just powered up) |
| BIT1 | IMU_COMM_FAIL | 0x02 | IMU communication failure (SPI/reset/configuration/FIFO/data stale/quaternion) |
| BIT2 | SELF_TEST_FAIL | 0x04 | Self-test failure (WHO_AM_I does not match = 0x70) |
| BIT3 | READER_TOO_SLOW | 0x08 | Host reads too slowly (SFLP refreshed ≥5 times between two reads) |

Firmware logic for setting the bits (`control_table.c`):

```c
if (!s->ready || quat_fp16 all 0)      bits |= BIT0;  // fusion has no output yet
if (error is SPI/RESET/CONFIG/STALE/FIFO/QUAT) bits |= BIT1;  // communication failure
if (error is ID)                      bits |= BIT2;  // self-test failure
if (sample_count increment >= 5)      bits |= BIT3;  // reading too slowly
```

How server.py handles the status bits:

| State | server.py behavior |
|---|---|
| BIT0 set | Frame status="stale" (fusion has no output yet; normal within about 0.5 seconds after power-up) |
| BIT1 set | Frame status="error" (communication failure; check soldering/wiring) |
| BIT2 set | Frame status="error" (self-test failure; check the IMU chip soldering) |
| BIT3 set | A slow-read hint is attached to the live frame; data validity is not affected |
| byte 14 ≠ 0 | Frame status="error" (reserved byte non-zero; firmware does not conform to the protocol) |

### 8.4 Extended area (addresses 71~85)

| Address | Field | Type | Description |
|---|---|---|---|
| 71-76 | Acceleration X/Y/Z | i16 × 3 LE | Range ±4 g, 0.122 mg/LSB |
| 77 | WHO_AM_I | u8 | LSM6DSV16X = 0x70 (112) |
| 78 | Error code | u8 | imu_error_t enum value |
| 79 | Clock status | u8 | |
| 80 | Watchdog enable | u8 | |
| 81-84 | Sample count | u32 LE | Total number of SFLP records (full 32 bits) |
| 85 | User marker | u8 | Writable, RAM (lost on power loss) |

### 8.5 Diagnostic area (addresses 90~185, 96 bytes)

24 little-endian u32 words, in order:

| Offset | Address | Name | Description |
|---|---|---|---|
| 0 | 90 | gyro_count | Total gyroscope samples |
| 1 | 94 | accel_count | Total acceleration samples |
| 2 | 98 | uptime_ms | Uptime (milliseconds) |
| 3 | 102 | gyro_age_ms | Milliseconds since the last gyroscope data |
| 4 | 106 | quat_age_ms | Milliseconds since the last quaternion |
| 5 | 110 | spi_errors | Number of SPI communication errors |
| 6 | 114 | fifo_overflows | Number of FIFO overflows |
| 7 | 118 | invalid_quaternions | Number of invalid quaternions |
| 8 | 122 | recovery_count | Number of IMU recoveries |
| 9 | 126 | rx_overflows | UART RX overflows |
| 10 | 130 | uart_errors | UART errors |
| 11 | 134 | checksum_errors | Protocol checksum errors |
| 12 | 138 | malformed_packets | Number of malformed packets |
| 13 | 142 | receive_timeouts | Receive timeouts |
| 14 | 146 | rx_packets | Packets received |
| 15 | 150 | tx_packets | Packets sent |
| 16 | 154 | cancelled_replies | Cancelled responses |
| 17 | 158 | reset_flags | Reset flags |
| 18 | 162 | clock_hz | Clock frequency |
| 19 | 166 | tx_timeouts | Transmit timeouts |
| 20 | 170 | log_dropped | Dropped log entries |
| 21 | 174 | diag_revision | Diagnostic table version (=1) |
| 22 | 178 | tx_busy_drops | Drops due to busy bus |
| 23 | 182 | reserved | Reserved |

---

## 9. Validation logic

### 9.1 Firmware-side validation (receiving request frames)

`proto_feed()` in `protocol.c` receives byte by byte; the validation flow is:

1. **Header search**: wait for 2 × 0xFF; extra 0xFF bytes are tolerated; a non-0xFF byte resets
2. **ID check**: 0x00 and 0xFF are invalid and reset
3. **LEN check**: LEN < 2 or > 132 (`PROTO_MAX_FRAME_LEN`) is discarded
4. **Checksum check**: `complete_packet()` computes the checksum over ID through the second-to-last byte
   and compares it with the last byte; mismatch → `checksum_errors++`, the instruction is not executed
5. **Instruction check**: parameter count, address range, uniqueness of the SYNC READ ID list, etc.

### 9.2 server.py-side validation (parsing the 15-byte block)

`feed()` in `imu_bus.py` validates the 15-byte block returned by ID 200 item by item:

| Check | Behavior on failure | Corresponding state |
|---|---|---|
| block length = 15 | Cannot happen (sync_read has fixed length) | — |
| Reserved byte (offset 14) == 0 | status="error" | Firmware does not conform to the protocol |
| BIT2 (self-test failure) set | status="error" | WHO_AM_I mismatch |
| BIT1 (communication failure) set | status="error" | SPI/reset/configuration/FIFO |
| BIT0 (not ready) set or quaternion all 0 | status="stale" | Fusion has no output yet |
| First 12 bytes identical for ≥8 consecutive frames | status="stale" | Data frozen |
| Quaternion fp16 decoding error | status="error" | Quaternion invalid |
| All of the above pass | status="live" | Normal data |

### 9.3 Front-end validation (displaying data)

`validPacket()` in `imu_attitude.js` requires all of the following conditions to hold:

| Condition | Description |
|---|---|
| `live === true` | Frame is marked live |
| `status === "live"` | Status string matches |
| `ready === 1` | IMU ready (firmware ready flag) |
| `configured === 1` | IMU configured (firmware configured flag) |
| `connected === true` | Bus connection is normal |
| `quaternion_xyzw` Array(4) | The quaternion is a 4-element array |
| All 4 elements are finite numbers | Not NaN/Infinity |
| Norm > 0.5 and < 1.5 | Quaternion sanity check |
| `sample_count` is a non-negative safe integer | Sample count is valid |

If any condition is not met, the angles/samples/Hz on the page all show `—` and the status label turns yellow.

> Note: `ready` and `configured` are set to 1 in the live frame by server.py's `imu_bus.py`.
> If they are missing (e.g. an old imu_bus.py), the data is still being broadcast but the page shows `—`.

---

## 10. Data flow and polling mechanism

### 10.1 Polling trigger condition

The logic of server.py's `stream_should_poll()`:

```
WebSocket client present && (servo online || imu_backend=="bus") && not locked by calibration
```

That is: **polling happens only while a web page is connected**. IMU data is broadcast by a separate `imu_stream` coroutine and does not block the servo stream.

### 10.2 sync_read list order

The order of the sync_read ID list in `read_states_with_imu()`:

```python
ids_sent = servo_ids + ([imu_bus.IMU_ID] if with_imu else [])
#          ^^^^^^^^^^                          ^^^^^^^^^^^^^^^^
#          servos first                        IMU last
```

**The IMU must be last**, never first:
- First: the IMU replies directly and talks at the same time as the Feetech servos → bus collision → frame misalignment (0xFF appears in the data area) → checksum error
- Last: the IMU waits until the last servo has finished replying before talking → no collision (30/30 succeeded)
- Alone in its own group `[200]`: no other devices → no collision

> **Note**: when `PRESENT` is empty (no servos found in the scan), `ids_sent = [200]`, and reading the IMU alone does not collide.
> Once servos come online, `[200] + servo_ids` causes collisions; this is exactly why the IMU data used to come and go.

### 10.3 Data flow

```
Feetech servos (ID=2..) ──┐
                         ├──> /dev/ttyS2 ──> server.py sync_read ──> WebSocket ──> browser
IMU board (ID=200) ─────┘    (replies last)                    ↓                ↓
                                                          imu_bus.py      imu_attitude.js
                                                              ↓                ↓
                                                           feed()          IMU panel refresh
                                                     (validate+decode)
```

### 10.4 Timing parameters

| Parameter | Value | Description |
|---|---|---|
| Bus baud rate | 1,000,000 bit/s | 8N1 |
| IMU sample rate | 120 Hz | On-chip SFLP fusion rate |
| Host polling rate | ~30~60 Hz | Depends on the number of bus devices and the page refresh |
| Byte timeout | 1500 µs | A frame is discarded if the gap between bytes exceeds this |
| Transaction timeout | 25,000 µs | SYNC READ cancels if waiting for the predecessor exceeds this |
| Response validity | 2,000 µs | A prepared response is cancelled if not sent within this |
| Host data expiry | 1,000 ms | A frame is marked stale if its publication exceeds this |
| Data freeze threshold | 8 frames | Marked frozen if the first 12 bytes are identical for 8 consecutive frames |
| Slow-read threshold | 5 times | BIT3 is set if SFLP refreshes ≥5 times between two reads |
