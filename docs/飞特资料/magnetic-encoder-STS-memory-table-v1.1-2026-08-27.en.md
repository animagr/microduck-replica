# Magnetic Encoder STS Servo: Memory Table Explained

**English** · [简体中文](磁编码STS内存表手册-v1.1-2026-08-27.md)

# 1 Servo communication protocol
The servo uses the FT-SCS custom protocol. The factory default serial configuration for STS servos is a default baud rate of 1M over TTL single-wire bus communication, 8 data bits, no parity, 1 stop bit; the baud rate can be configured in the range 38400~1Mbps, and the default communication address (station number) is 1.
[FT-SCS custom protocol](http://doc.feetech.cn/#/tiaozhunlujingft?srcType=FT-SCS-Protocol-41ad23fe8a244712ba160b93)

# 2 Servo memory table definition
If a function address uses two-byte data, the low byte is at the lower address and the high byte at the higher address.
## 2.1 Version information
|Address DEC|Address HEX|Function name|Bytes|Initial value|Access|Value range|Unit|Description|
|-|-|-|-|-|-|-|-|-|
|0|0x00|Firmware major version|1|--|Read-only||||
|1|0x01|Firmware minor version|1|--|Read-only|||
|2|0x02|END|1|0|Read-only|||0 means little-endian storage|
|3|0x03|Servo major version|1|--|Read-only||||
|4|0x04|Servo minor version|1|--|Read-only||||

## 2.2 EPROM configuration
Address DEC|Address HEX|Function name|Bytes|Initial value|Access|Value range|Unit|Description|
|-|-|-|-|-|-|-|-|-|
|5|0x05|Servo ID|1|1|Read/write|0 ~ 253|No.|Unique primary ID on the bus|
|6|0x06|Baud rate|1|0|Read/write|0 ~ 7|None|0-7 represent the baud rates: 1000000(0), 500000(1), 250000(2), 128000(3), 115200(4), 76800(5), 57600(6), 38400(7)|
|7|0x07|Reserved address|1|--|Read/write|--|--||
|8|0x08|Response status level|1|1|Read/write|0 ~ 1|None|0: no response packet for any instruction except read and PING; 1: response packet for all instructions|
|9|0x09|Minimum angle limit|2|0|Read/write|0 ~ 4094|0.087 deg|0 for multi-turn absolute position control|
|11|0x0B|Maximum angle limit|2|4095|Read/write|1 ~ 4095|0.087 deg|0 for multi-turn absolute position control|
|13|0x0D|Maximum temperature limit|1|70|Read/write|0 ~ 100|°C||
|14|0x0E|Maximum input voltage|1|--|Read/write|0 ~ 254|0.1V||
|15|0x0F|Minimum input voltage|1|40|Read/write|0 ~ 254|0.1V||
|16|0x10|Maximum torque|2|1000|Read/write|0 ~ 1000|0.1%|Copied to the torque limit at address 48 on power-up|
|18|0x12|Phase|1|--|Read/write|0 ~ 254|None|Special function byte; do not modify without a specific need|
|19|0x13|Unload conditions|1|--|Read/write|0 ~ 254|None|Setting a bit to 1 enables the corresponding protection; setting it to 0 disables it|
|20|0x14|LED alarm conditions|1|--|Read/write|0 ~ 254|None|Setting a bit to 1 enables the flashing-LED alarm; setting it to 0 disables it|
|21|0x15|Position loop P (proportional gain)|1|--|Read/write|0 ~ 254|None|Proportional gain of motor control (1/4)|
|22|0x16|Position loop D (derivative gain)|1|--|Read/write|0 ~ 254|None|Derivative gain of motor control (1/8)|
|23|0x17|Position loop I (integral gain)|1|0|Read/write|0 ~ 254|None|Integral gain of motor control|
|24|0x18|Minimum startup torque|1|--|Read/write|0 ~ 254|0.1%|Sets the servo's minimum output startup torque|
|25|0x19|Integral limit|1|0|Read/write|0 ~ 254|None|Maximum integral value = integral limit * 4; 0 disables the integral limit; effective in position mode 0 and mode 4|
|26|0x1A|Positive dead band|1|1|Read/write|0 ~ 16|0.087 deg|Smallest unit is one minimum resolution angle|
|27|0x1B|Negative dead band|1|1|Read/write|0 ~ 16|0.087 deg|Smallest unit is one minimum resolution angle|
|28|0x1C|Protection current|2|511|Read/write|0 ~ 2047|6.5mA|The maximum settable current is 500 * 6.5mA = 3250mA|
|30|0x1E|Angle resolution|1|1|Read/write|1 ~ 128|None|Multiplication factor applied to the sensor's minimum resolution angle|
|31|0x1F|Position offset|2|0|Read/write|0 ~ 8191|0.087 deg|0 ~ 2047 means 0 ~ 2047; 2048 ~ 4095 means 0 ~ -2047; 4096 ~ 6143 means 2048 ~ 4095; 6144~8191 means -2048 ~ -4095 (representing an offset of -4095~4095)|
|33|0x21|Operating mode|1|0|Read/write|0 ~ 3|None|0: position servo mode; 1: motor constant-speed mode; 2: PWM open-loop speed mode; 3: stepper mode|
|34|0x22|Holding torque|1|20|Read/write|0 ~ 254|1%|Output torque after overload protection is triggered; e.g. 20 means 20% of maximum torque|
|35|0x23|Protection time|1|200|Read/write|0 ~ 254|10ms|How long the current load output must exceed the overload torque; e.g. 200 means 2 seconds; the maximum settable is 2.5 seconds|
|36|0x24|Overload torque|1|80|Read/write|0 ~ 254|1%|Maximum torque threshold that starts the overload protection timer; e.g. 80 means 80% of maximum torque|
|37|0x25|Speed loop P (proportional gain)|1|--|Read/write|0 ~ 254|None|Speed loop proportional gain in motor constant-speed mode (mode 1)|
|38|0x26|Overcurrent protection time|1|200|Read/write|0 ~ 254|10ms|Maximum settable is 254 * 10ms = 2540ms|
|39|0x27|Speed loop I (integral gain)|1|--|Read/write|0 ~ 254|None|Speed loop integral gain in motor constant-speed mode (mode 1)|

## 2.3 SRAM control
Address DEC|Address HEX|Function name|Bytes|Initial value|Access|Value range|Unit|Description|
|-|-|-|-|-|-|-|-|-|
|40|0x28|Torque switch|1|0|Read/write|0 ~ 2|None|Write 0: torque output off; write 1: torque output on; write 2: damping output (the torque limit (48) controls the damping force), write 128: correct any current position to 2048|
|41|0x29|Acceleration|1|0|Read/write|0 ~ 254|8.7 deg/s^2^|Servo acceleration/deceleration; 0 means maximum acceleration|
|42|0x2A|Target position|2|0|Read/write|-32767 ~ 32767|0.087 deg|Absolute position control; the maximum corresponds to the maximum effective angle; BIT15 is the direction bit|
|44|0x2C|PWM open-loop speed|2|1000|Read/write|0~1000|0.1%|Effective in PWM open-loop speed mode; BIT10 is the direction bit|
|46|0x2E|Running speed|2|Servo's factory default maximum speed|Read/write|-32767 ~ 32767|0.732RPM/0.0146RPM|Controls the motor's maximum running speed; BIT15 is the direction bit. Speed 0 means maximum speed by default, and can be set via the phase to mean stop. The speed unit can be set via the phase to one of two units, 0.732RPM/0.0146RPM; when the speed unit is set to 0.0146RPM, the precision is still 0.732RPM|
|48|0x30|Torque limit|2|Maximum torque (16), default 1000|Read/write|0 ~ 1000|0.1%|Users can modify this value in software to control the stall torque output|
|50~54|0x32~0x36|Undefined|1|--|Read/write|--|--||
|55|0x37|Lock flag|1|1|Read/write|0 ~ 1|None|Write 0 to release the write lock: values written to EPROM addresses are kept after power loss; write 1 to enable the write lock: values written to EPROM addresses are not kept after power loss|

## 2.4 SRAM feedback
|Address DEC|Address HEX|Function name|Bytes|Initial value|Access|Value range|Unit|Description|
|-|-|-|-|-|-|-|-|-|
|56|0x38|Current position|2|--|Read-only|--|0.087 deg|Reports the servo's current absolute position; BIT15 is the direction bit. In stepper mode 3 it returns the step difference between the current and target positions; BIT15 is the direction bit|
|58|0x3A|Current speed|2|--|Read-only|--|0.732RPM/0.0146RPM|Reports the current motor rotation speed; the speed unit depends on the phase setting; BIT15 is the direction bit|
|60|0x3C|Current load|2|--|Read-only|--|0.1%|Current voltage duty cycle of the control output driving the motor; BIT10 is the direction bit|
|62|0x3E|Current voltage|1|--|Read-only|--|0.1V|Current servo operating voltage|
|63|0x3F|Current temperature|1|--|Read-only|--|°C|Current internal servo operating temperature|
|64|0x40|Asynchronous write flag|1|0|Read-only|--|None|Flag bit used with the asynchronous write instruction|
|65|0x41|Servo status|1|0|Read-only|--|None|A bit set to 1 means the corresponding error has occurred|
|66|0x42|Moving flag|1|0|Read-only|--|None|1 while the servo is moving, 0 when it has reached the target and stopped; stays 0 if the target position is not updated|
|67|0x43|Target position|2|0|Read-only|--|0.087 deg|Current target position|
|69|0x45|Current current|2|--|Read-only|--|6.5mA|Reports the current motor phase current|
|71|0x47|Undefined|2|--|Read-only|--|--||

## 3.5 Factory parameters
|Address DEC|Address HEX|Function name|Bytes|Initial value|Access|Value range|Unit|Description|
|-|-|-|-|-|-|-|-|-|
|80|0x50|Moving speed threshold|1|--|Read-only|--|--|--|
|81|0x51|DTs(ms)|1|--|Read-only|--|--|--|
|82|0x52|Speed unit coefficient|1|--|Read-only|--|--|--|
|83|0x53|Minimum speed limit|1|--|Read-only|--|--|Unit 0.732rpm|
|84|0x54|Maximum speed limit|1|--|Read-only|--|--|Unit 0.732rpm|
|85|0x55|Acceleration limit|1|--|Read-only|--|--|--|
|86|0x56|Acceleration multiplier|1|--|Read-only|--|--|The acceleration multiplier takes effect when acceleration is 0; when both the acceleration multiplier and acceleration are 0, the servo responds fastest|

# 3 Special byte explanations
## 3.1 Servo phase
- **Bit / bit weight: description**
- BIT0 (1): drive direction phase; (0) forward, (1) reverse
- BIT1 (2): drive bridge mode; (0) brushless, (1) brushed; takes effect after reboot
- BIT2 (4): speed unit; (0) 0.732RPM, (1) 0.0146RPM
- BIT3 (8): speed mode; (0) speed 0 means stop, (1) speed 0 means maximum speed
- BIT4 (16): angle feedback mode; (0) report single-turn angle, (1) report full angle
- BIT5 (32): drive bridge configuration, (0) discrete H-bridge, (1) integrated H-bridge / no current feedback
- BIT6 (64): PWM frequency, (0) 24kHz, (1) 16kHz
- BIT7 (128): position feedback direction phase, (0) forward, (1) reverse
- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">If several bits are set at the same time, the servo's phase value is the sum of the bit values. For example: if the original phase value is 0 and the servo should run in reverse, the phase value is 128+1=129;
</div> 

## 3.2 Servo status
**Servo status: 0 means normal, 1 means abnormal**
- **Bit / bit weight: description**
- BIT0 (1): voltage status
- BIT1 (2): magnetic encoder status
- BIT2 (4): temperature status
- BIT3 (8): current status
- BIT4 (16): ----
- BIT5 (32): load status
- BIT6 (64): ----
- BIT7 (128): ----
- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">If several states occur at the same time, the servo status value is the sum of the bit values. For example: voltage overvoltage/undervoltage plus servo overheating gives a servo status value of 4+1=5;
</div> 

## 3.3 Unload conditions
**Unload conditions: 0 means disabled, 1 means enabled**
- **Bit / bit weight: description**
- BIT0 (1): voltage protection
- BIT1 (2): magnetic encoder protection
- BIT2 (4): overheat protection
- BIT3 (8): overcurrent protection
- BIT4 (16): ----
- BIT5 (32): load overload
- BIT6 (64): ----
- BIT7 (128): ----
- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">If several bits are set at the same time, the servo's unload condition value is the sum of the bit values. For example: with voltage protection and overheat protection both enabled, the unload condition value is 4+1=5;
</div>

## 3.4 LED alarm conditions
**LED alarm conditions: 0 means disabled, 1 means enabled**
- **Bit / bit weight: description**
- BIT0 (1): voltage alarm
- BIT1 (2): magnetic encoder alarm
- BIT2 (4): overheat alarm
- BIT3 (8): overcurrent alarm
- BIT4 (16): ----
- BIT5 (32): load overload alarm
- BIT6 (64): ----
- BIT7 (128): ----

- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">If several bits are set at the same time, the servo's LED alarm condition value is the sum of the bit values. For example: with the voltage alarm and overheat alarm both enabled, the alarm condition value is 4+1=5;
</div>
