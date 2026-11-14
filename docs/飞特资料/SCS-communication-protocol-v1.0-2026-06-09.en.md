# Servo SCS Communication Protocol

**English** · [简体中文](SCS通信协议-v1.0-2026-06-09.md)

# 1 Communication protocol overview
&emsp;&emsp;The signal levels are TTL, which is compatible with high-speed communication, and RS485, which has strong noise immunity. Communication is still asynchronous duplex: transmit and receive signals are handled asynchronously.
&emsp;&emsp;The controller and the servos communicate in a request/response manner: the controller sends an instruction frame and the servo returns a response frame.
&emsp;&emsp;Multiple servos are allowed on one bus control network, so each servo is assigned an ID that is unique within the network. The control instructions sent by the controller contain ID information; only the servo whose ID matches receives the instruction in full and returns a response.
Communication is serial asynchronous. One data frame consists of 1 start bit, 8 data bits and 1 stop bit, with no parity bit, for 10 bits in total.
&emsp;&emsp;When some memory-table parameters use a two-byte value range, the byte order depends on the servo type: potentiometer-type servos are big-endian (high byte first, low byte second), and magnetic-encoder-type servos are little-endian (low byte first, high byte second). Each servo model differs slightly in function, so for actual control always refer to the memory table of the specific model.

# 2 Instruction frame
|Header|ID|Data length|Instruction|Parameters|Checksum|
|-|-|-|-|-|-|
|0xFF 0xFF|ID|Length|Instruction|Parameter1 ...Parameter N|Check Sum|

- Header: two consecutive 0xFF bytes indicate that a data packet has arrived.
ID: every servo has an ID. The ID range is 0~253, which is 0x00~0xFD in hexadecimal.
- Broadcast ID: ID 254 is the broadcast ID. If the controller sends ID 254 (0xFE), all servos receive the instruction, and none return a response except for the PING instruction (a broadcast PING must not be used when multiple servos are connected on the bus).
- Data length: equals the number of parameters to send, N, plus 2, i.e. "N+2".
- Instruction: the operation function code of the packet; see 4 Instruction types for details.
- Parameters: control information that must be supplied in addition to the instruction. Parameters support at most two bytes to represent one memory value; for byte order, refer to the memory control table in the servo user manual (different servo models use different byte orders).
- Checksum: the Check Sum is calculated as follows
Check Sum = ~ (ID + Length + Instruction + Parameter1 + ... Parameter N). If the sum in parentheses exceeds 255, take the lowest byte; "~" means bitwise inversion.

# 3 Response frame
|Header|ID|Data length|Status code|Parameters|Checksum|
|-|-|-|-|-|-|
|0xFF 0xFF|ID|Length|ERROR|Parameter1 ...Parameter N|Check Sum|

The returned response frame contains the servo's current status, ERROR. If the servo's current operating state is abnormal, this byte reflects it (see the memory control table in the manual for the meaning of each status). If ERROR is 0, the servo has no error.

# 4 Instruction types
|Instruction|Function|Value|Parameter length|
|-|-|-|-|
|PING (query)|Query the operating status|0x01|0|
|READ DATA (read)|Query data in the control table|0x02|2|
|WRITE DATA (write)|Write data into the control table|0x03|At least 2|
|REGWRITE DATA (asynchronous write)|Similar to WRITE DATA, but the control characters do not take effect immediately after being written; they wait until an ACTION instruction arrives|0x04|At least 4|
|ACTION (execute asynchronous write)|Triggers the action written by REG WRITE|0x05|0|
|SYCNREAD DATA (synchronous read)|Used to query multiple servos at the same time|0x82|At least 3|
|SYCNWRITE DATA (synchronous write)|Used to control multiple servos at the same time|0x83|At least 2|
|RESET (status reset)|Reset the servo status (reset the servo turn count)|0x0A|0|
|Position calibration|Recalibrate the current position to the instruction value|0x0B|0|
|Parameter restore instruction|Restore all servo parameters except the ID|0x06|0|
|Parameter backup instruction|Back up the current parameters, for use by the restore instruction|0x09|0|
|Reboot instruction|Used to reboot the servo|0x08|0|

## 4.1 Status query instruction PING
- Function: read the servo's operating status
- Length: 0x02
- Instruction: 0x01
- Parameters: none
- When the PING instruction uses the broadcast address, the servo still returns a response.

**Example 1: read the operating status of the servo with ID 1.**
Instruction frame: FF FF 01 02 01 FB (sent as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 02
Instruction: 01
Checksum: FB
```

Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 02
Status: 00
Checksum: FC
```

## 4.2 Read instruction READ DATA
- Function: read data from the servo's memory control table
- Length: 0x04
- Instruction: 0x02
- Parameter 1: start address of the data to read
- Parameter 2: length of the data to read

**Example 2: read the current position of the servo with ID 1 (low byte first, high byte second). The position parameter is at memory-table address 0X38 and spans two consecutive bytes.**

Instruction frame: FF FF 01 04 02 38 02 BE (sent as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 04
Instruction: 02
Parameters: 38 02 (current position address, read data length)
Checksum: BE
```

Response frame: FF FF 01 04 00 18 05 DD (displayed as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 04
Status: 00
Parameters: 18 05
Checksum: DD
```
The two bytes read are (little-endian): low byte L 0x18, high byte H 0x05. Combined, the two bytes form the 16-bit value 0X0518, so the current position in decimal is 1304.

## 4.3 Write instruction WRITE DATA
- Function: write data into the servo's memory control table
- Length: N+2 (N is the parameter length)
- Instruction: 0x03
- Parameter 1: start address of the data to write
- Parameter 2: 1st data byte to write
- Parameter 3: 2nd data byte to write
...
- Parameter N: nth data byte to write, N=n+1

**Example 3: use the broadcast ID (0xFE) to set the ID of a servo with any ID to 1. The ID is stored at address 5 in the memory table.**
Instruction frame: FF FF FE 04 03 05 01 F4 (sent as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 04
Instruction: 03
Parameters: 05 01 (ID address, new ID value)
Checksum: F4
```

Because the instruction is sent with the broadcast ID, no data is returned. In addition, the EPROM in the memory table has a protection lock switch, which must be turned off (set to 0) before changing the ID; otherwise the example ID will not be saved after power loss. For detailed steps, see the memory table or user manual of the specific servo model.

**Example 4: make servo ID1 rotate to position 2048 at a speed of 1000 steps per second. The start address of the target position in the memory table is 0x2A, so six consecutive bytes are written starting at address 0x2A.**

- Position data 0x0800 (2048)
- Reserved data 0x0000 (0)
- Speed data 0x03E8 (1000)

Instruction frame: FF FF 01 09 03 2A 00 08 00 00 E8 03 D5 (sent as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 09
Instruction: 03
Parameters:
2A (start address)
00 08 (position)
00 00 (reserved)
E8 03 (speed)
Checksum: D5
```

Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 02
Status: 00
Checksum: FC
```
The returned operating status is 0, which means the servo received the instruction correctly without errors and has started executing it. The instruction packet was sent with a non-broadcast ID (not 0xFE), so the servo returns a status packet after receiving the instruction.

## 4.4 Asynchronous write instruction REG WRITE
The REG WRITE instruction is similar to WRITE DATA; only the execution time differs. When a REG WRITE instruction frame is received, the received data is stored in a buffer for later use and the asynchronous write flag register is set to 1. When an ACTION instruction is received, the stored instruction is finally executed.
- Length: N+2 (N is the parameter length)
- Instruction: 0x04
- Parameter 1: start address of the area to write
- Parameter 2: 1st data byte to write
- Parameter 3: 2nd data byte to write
- Parameter N: nth data byte to write, N=n+1

**Example 5: make servos ID1 to ID10 rotate to position 2048 at a speed of 1000 per second.**

```language
ID 1: asynchronous write instruction frame: FF FF 01 09 04 2A 00 08 00 00 E8 03 D4 
ID 1: response frame: FF FF 01 02 00 FC
ID 2: asynchronous write instruction frame: FF FF 02 09 04 2A 00 08 00 00 E8 03 D3 
ID 2: response frame: FF FF 02 02 00 FB
ID 3: asynchronous write instruction frame: FF FF 03 09 04 2A 00 08 00 00 E8 03 D2 
ID 3: response frame: FF FF 03 02 00 FA
ID 4: asynchronous write instruction frame: FF FF 04 09 04 2A 00 08 00 00 E8 03 D1 
ID 4: response frame: FF FF 04 02 00 F9
ID 5: asynchronous write instruction frame: FF FF 05 09 04 2A 00 08 00 00 E8 03 D0 
ID 5: response frame: FF FF 05 02 00 F8
ID 6: asynchronous write instruction frame: FF FF 06 09 04 2A 00 08 00 00 E8 03 CF 
ID 6: response frame: FF FF 06 02 00 F7
ID 7: asynchronous write instruction frame: FF FF 07 09 04 2A 00 08 00 00 E8 03 CE 
ID 7: response frame: FF FF 07 02 00 F6
ID 8: asynchronous write instruction frame: FF FF 08 09 04 2A 00 08 00 00 E8 03 CD 
ID 8: response frame: FF FF 08 02 00 F5
ID 9: asynchronous write instruction frame: FF FF 09 09 04 2A 00 08 00 00 E8 03 CC 
ID 9: response frame: FF FF 09 02 00 F4
ID10: asynchronous write instruction frame: FF FF 0A 09 04 2A 00 08 00 00 E8 03 CB
ID10: response frame: FF FF 0A 02 00 F3
```

## 4.5 Execute asynchronous write instruction ACTION
- Function: trigger the REG WRITE instruction
- Length: 0x02
- Instruction: 0x05
- Parameters: none

1. The ACTION instruction is very useful when controlling multiple servos at the same time.
2. When controlling multiple servos, the ACTION instruction lets the first and the last servo execute their respective actions at the same time, with no delay in between.
3. When sending the ACTION instruction to multiple servos, the broadcast ID (0xFE) must be used, so no data frame is returned for this instruction.

**Example 6: after the asynchronous write instructions that make servos ID1 to ID10 rotate to position 2048 at a speed of 1000 per second have been sent, the asynchronous write must be executed.**
```
Instruction frame: FF FF FE 02 05 FA
Response frame: none
```

## 4.6 Synchronous write instruction SYNC WRITE
- Function: used to control multiple servos at the same time.
- ID: 0xFE
- Length: (L+1)*n+4 (L: data length sent to each servo, n: number of servos)
- Instruction: 0x83
- Parameter 1: start address of the data to write
- Parameter 2: length of the data to write (L)
- Parameter 3: ID of the 1st servo
- Parameter 4: 1st data byte written to the 1st servo
- Parameter 5: 2nd data byte written to the 1st servo
...
- Parameter L+3: Lth data byte written to the 1st servo
- Parameter L+4: ID of the 2nd servo
- Parameter L+5: 1st data byte written to the 2nd servo
- Parameter L+6: 2nd data byte written to the 2nd servo
…
- Parameter 2L+4: Lth data byte written to the 2nd servo
…

Unlike REG WRITE+ACTION, it offers better real-time performance: a single SYNC WRITE instruction can modify the control tables of multiple servos at once, whereas REG WRITE+ACTION does it in steps. Even so, when using SYNC WRITE, the length of the data written and the start address where it is stored must be the same for all servos.

**Example 7: for the 4 servos ID1-ID4, write position 0x0800, time 0X0000 and speed 0x03E8 at start address 0x2A (low byte first, high byte second).**
Instruction frame: FF FF FE 20 83 2A 06 01 00 08 00 00 E8 03 02 00 08 00 00 E8 03 03 00 08 00 00 E8 03 04 00 08 00 00 E8 03 58 (sent as hexadecimal)
```language
Header: FF FF
ID: FE
Payload length: 20
Instruction: 83
Parameters:
2A 06 (start address, data length)
01 00 08 00 00 E8 03 (instruction for servo ID1)
02 00 08 00 00 E8 03 (instruction for servo ID2)
03 00 08 00 00 E8 03 (instruction for servo ID3)
04 00 08 00 00 E8 03 (instruction for servo ID4)
Checksum: 58
```

## 4.7 Synchronous read instruction SYNC READ
- Function: used to query multiple servos at the same time.
- ID: 0xFE
- Length: n+4 (n is the number of servos)
- Instruction: 0x82
- Parameter 1: start address of the data to read
- Parameter 2: length of the data to read
- Parameter 3: ID of the 1st servo
- Parameter 4: ID of the 2nd servo
…
- Parameter N: ID of the nth servo, N=n+2

A single SYNC READ instruction can query the control tables of multiple servos at once. The synchronous read instruction specifies the IDs of the servos to query, and the servos return their response packets in the order of the IDs in the instruction packet. When using SYNC READ, the data length and start address of all queried data must be the same (this instruction is available on some serial bus servos only).

**Example 8: query the current position, current speed, current load, current voltage and current temperature of the 2 servos ID1-ID2 (start address 0x38, 8 bytes of data in total, low byte first, high byte second).**

Instruction frame: FF FF FE 06 82 38 08 01 02 36
```language
Header: FF FF
ID: FE
Length: 06
Instruction: 82
Parameters:
38 08 (data start address, data length)
01 02 (ID01 ID02)
Checksum: 36
```

Response frames:
```language
Servo ID01: FF FF 01 0A 00 00 08 00 00 00 00 79 1E 55 
Servo ID02: FF FF 02 0A 00 FF 07 00 00 00 00 77 23 53
```
The response frames can be decoded in the same way as for the read instruction.

## 4.8 Status reset instruction RESET
- Function: reset the servo status (reset the servo turn count)
- Length: 0x02
- Instruction: 0x0A
- Parameters: none

**Example 9: reset the servo with ID 01.**
```language
Instruction frame: FF FF 01 02 0A F2 (sent as hexadecimal)
Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```

## 4.9 Position calibration instruction
- Function: recalibrate the current position to the set value
- Length: 0x02 or 0x04
- Instruction: 0x0B
- Parameters: none, or the set value

**Note: a position calibration instruction without parameters calibrates the current position to the midpoint. The calibration instruction is supported only by some servo models; see the table below for model support.**

**Example 10: recalibrate the current position to the midpoint.**
```language
Instruction frame: FF FF 01 02 0B F1 (sent as hexadecimal)
Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```

**Example 11: recalibrate the current position to 1024.**
Instruction frame: FF FF 01 04 0B 00 04 EB (sent as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 04
Instruction: 0B
Set value: 00 04 (1024)
Checksum: EB
```

Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```language
Header: FF FF
ID: 01
Length: 02
Status: 00
Checksum: FC
```

|Servo model|Firmware version|Condition|Notes|
|-|-|-|-|
|SMS servos|<=2.54|None|Supports midpoint calibration by writing 128 to the torque switch|
|STS servos|>=3.10|None|Supports the instruction with and without parameters; supports midpoint calibration by writing 128 to the torque switch|
|HLS servos|>=3.43|None|Supports the instruction with and without parameters; does not support midpoint calibration by writing 128 to the torque switch|

## 4.10 Parameter restore instruction
- Function: restore all servo parameters except the ID
- Length: 0x02
- Instruction: 0x06
- Parameters: none

**Example 11: restore servo parameters.**
```language
Instruction frame: FF FF 01 02 06 F6 (sent as hexadecimal)
Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```
**Note: unlock the EPROM parameters before restoring servo parameters**

## 4.11 Parameter backup instruction
- Function: parameter backup (used by the parameter restore instruction)
- Length: 0x02
- Instruction: 0x09
- Parameters: none

**Example 12: back up servo parameters.**
```language
Instruction frame: FF FF 01 02 09 F3 (sent as hexadecimal)
Response frame: FF FF 01 02 00 FC (displayed as hexadecimal)
```
**Note: unlock the EPROM parameters before backing up servo parameters**

## 4.12 Reboot instruction
- Function: reboot instruction (reboots the servo)
- Length: 0x02
- Instruction: 0x08
- Parameters: none

**Example 13: reboot the servo.**
```language
Instruction frame: FF FF 01 02 08 F4 (sent as hexadecimal)
Response frame: none (reboot takes about 800ms)
```
**Note: turn off the torque switch before rebooting the servo**
