//! Minimal implementation of the Feetech STS3215 bus servo communication protocol (FEETECH STS/SCS serial protocol).
//!
//! Frame format (each byte sent over UART, default 1,000,000 baud 8N1):
//!   [0xFF, 0xFF, ID, LENGTH, INSTRUCTION, PARAM1..PARAMn, CHECKSUM]
//!   - LENGTH    = number of parameter bytes + 2 (instruction byte + checksum byte)
//!   - CHECKSUM  = low 8 bits of ~(ID + LENGTH + INSTRUCTION + all parameters)
//!
//! The servo reply frame has the same format, except INSTRUCTION is replaced by the ERROR status byte.

use serialport::SerialPort;
use std::io::{self, ErrorKind};
use std::time::{Duration, Instant};

// ---- Instruction codes ----
pub const INST_PING: u8 = 0x01;
pub const INST_READ: u8 = 0x02;
pub const INST_WRITE: u8 = 0x03;

/// STS3215 memory table (common register addresses).
/// Checked against Feetech's official SDK `sms_sts.py` (FTServo_Python).
#[allow(dead_code)] // the full register table is kept as a reference
pub mod reg {
    // ---- EPROM read-only ----
    pub const FIRMWARE: u8 = 0; // 3 bytes, firmware version
    pub const MODEL_NUMBER: u8 = 3; // u16, model
    // ---- EPROM read/write (write LOCK=0 to unlock before modifying) ----
    pub const ID: u8 = 5; // u8, servo ID
    pub const BAUD_RATE: u8 = 6; // u8, baud rate index 0=1M 4=115200 ...
    pub const MIN_POSITION: u8 = 9; // u16, min angle limit
    pub const MAX_POSITION: u8 = 11; // u16, max angle limit
    pub const MAX_TEMPERATURE: u8 = 13; // u8, max temperature protection
    pub const MAX_VOLTAGE: u8 = 14; // u8, max voltage, unit 0.1V
    pub const MIN_VOLTAGE: u8 = 15; // u8, min voltage, unit 0.1V
    pub const MODE: u8 = 33; // u8, 0=position mode 1=wheel mode
    // ---- SRAM read/write ----
    pub const TORQUE_ENABLE: u8 = 40; // u8, torque switch 1=hold 0=release
    pub const ACCELERATION: u8 = 41; // u8, acceleration
    pub const GOAL_POSITION: u8 = 42; // u16, target position 0~4095
    pub const GOAL_TIME: u8 = 44; // u16, running time ms
    pub const GOAL_SPEED: u8 = 46; // u16, running speed steps/s
    pub const TORQUE_LIMIT: u8 = 48; // u16, torque limit
    pub const LOCK: u8 = 55; // u8, EEPROM lock: 0=unlocked 1=locked
    // ---- SRAM read-only ----
    pub const PRESENT_POSITION: u8 = 56; // u16, current position 0~4095
    pub const PRESENT_SPEED: u8 = 58; // u16, current speed
    pub const PRESENT_LOAD: u8 = 60; // u16, current load bit0~9=magnitude bit10=direction, unit 0.1%
    pub const PRESENT_VOLTAGE: u8 = 62; // u8, current voltage, unit 0.1V
    pub const PRESENT_TEMPERATURE: u8 = 63; // u8, current temperature °C
    pub const SERVO_STATUS: u8 = 65; // u8, servo status (alarm bits)
    pub const MOVING: u8 = 66; // u8, whether moving
    pub const PRESENT_CURRENT: u8 = 69; // u16, current, unit about 6.5mA
}

/// Servo real-time status read back in one go (parsed from 15 consecutive bytes starting at address 56).
#[derive(Debug, Clone)]
pub struct ServoStatus {
    pub position: u16,    // 0~4095
    pub speed: i16,       // steps/s (with direction)
    pub load: i16,        // 0.1%, with direction
    pub voltage: f32,     // V
    pub temperature: u8,  // °C
    pub servo_status: u8, // non-zero means an alarm (over-voltage/over-current/overheat etc.)
    pub moving: bool,
    pub current_ma: f32, // mA
}

impl ServoStatus {
    /// Convert position 0~4095 into an angle (degrees).
    pub fn angle_deg(&self) -> f32 {
        self.position as f32 * 360.0 / 4096.0
    }
}

/// The opened bus. All communication with servos goes through it.
pub struct StsBus {
    port: Box<dyn SerialPort>,
    /// Max wait time for reading a single packet
    timeout: Duration,
}

impl StsBus {
    /// Open the serial port, e.g. StsBus::open("/dev/ttyUSB0", 1_000_000)
    pub fn open(path: &str, baud: u32) -> io::Result<Self> {
        let port = serialport::new(path, baud)
            .data_bits(serialport::DataBits::Eight)
            .stop_bits(serialport::StopBits::One)
            .parity(serialport::Parity::None)
            .flow_control(serialport::FlowControl::None)
            .timeout(Duration::from_millis(20))
            .open()?;
        Ok(Self {
            port,
            timeout: Duration::from_millis(150),
        })
    }

    fn checksum(bytes: &[u8]) -> u8 {
        !bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b))
    }

    /// Send one instruction packet.
    fn send_packet(&mut self, id: u8, inst: u8, params: &[u8]) -> io::Result<()> {
        let len = params.len() as u8 + 2;
        let mut pkt = Vec::with_capacity(6 + params.len());
        pkt.extend_from_slice(&[0xFF, 0xFF, id, len, inst]);
        pkt.extend_from_slice(params);
        pkt.push(Self::checksum(&pkt[2..]));
        self.port.write_all(&pkt)?;
        self.port.flush()
    }

    /// Read exactly n bytes before the deadline.
    fn read_n(&mut self, n: usize, deadline: Instant) -> io::Result<Vec<u8>> {
        let mut buf = vec![0u8; n];
        let mut got = 0;
        while got < n {
            match self.port.read(&mut buf[got..]) {
                Ok(0) => {}
                Ok(k) => got += k,
                Err(e) if e.kind() == ErrorKind::TimedOut => {
                    if Instant::now() >= deadline {
                        return Err(io::Error::new(
                            ErrorKind::TimedOut,
                            "等待舵机应答超时",
                        ));
                    }
                }
                Err(e) => return Err(e),
            }
        }
        Ok(buf)
    }

    /// Receive one reply packet, returning (id, error, parameter area).
    fn recv_packet(&mut self) -> io::Result<(u8, u8, Vec<u8>)> {
        let deadline = Instant::now() + self.timeout;
        // 1. Slide byte by byte to find the header 0xFF 0xFF
        let mut prev = self.read_n(1, deadline)?[0];
        loop {
            let cur = self.read_n(1, deadline)?[0];
            if prev == 0xFF && cur == 0xFF {
                break;
            }
            prev = cur;
        }
        // 2. id + length
        let head = self.read_n(2, deadline)?;
        let (id, len) = (head[0], head[1] as usize);
        // 3. error + params + checksum (length already includes the 2 bytes error and checksum)
        let body = self.read_n(len, deadline)?;
        let mut all = vec![id, len as u8];
        all.extend_from_slice(&body);
        if Self::checksum(&all) != 0x00 {
            let hex: Vec<String> = all.iter().map(|b| format!("{b:02X}")).collect();
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                format!("校验和错误, 收到字节: {}", hex.join(" ")),
            ));
        }
        let error = body[0];
        let params = body[1..body.len() - 1].to_vec();
        Ok((id, error, params))
    }

    /// Receive one reply packet. Some adapter boards echo what was sent back to RX: the echo packet is
    /// byte-for-byte identical to the sent packet (the "error position" happens to equal the instruction code). But note: a ping reply
    /// from a servo with an alarm (error=0x01) is indistinguishable from the ping echo at the byte level, so the strategy is:
    /// if the first packet looks like an echo, wait for a second packet; if none arrives, treat the first packet as the real reply.
    fn recv_non_echo(&mut self, sent_id: u8, sent_inst: u8, sent_params: &[u8]) -> io::Result<(u8, u8, Vec<u8>)> {
        let first = self.recv_packet()?;
        let looks_like_echo = first.0 == sent_id && first.1 == sent_inst && first.2 == sent_params;
        if !looks_like_echo {
            return Ok(first);
        }
        match self.recv_packet() {
            Ok(second) => Ok(second), // there's a second packet: the first was the echo
            Err(e) if e.kind() == ErrorKind::TimedOut => Ok(first), // no second packet: the first one is the reply
            Err(e) => Err(e),
        }
    }

    /// Set the RTS / DTR control lines (some adapter boards use them for transmit direction or enable).
    pub fn set_rts(&mut self, on: bool) -> io::Result<()> {
        self.port
            .write_request_to_send(on)
            .map_err(|e| io::Error::new(ErrorKind::Other, e.to_string()))
    }
    pub fn set_dtr(&mut self, on: bool) -> io::Result<()> {
        self.port
            .write_data_terminal_ready(on)
            .map_err(|e| io::Error::new(ErrorKind::Other, e.to_string()))
    }

    /// Broadcast scan: returns the list of servo IDs that replied.
    #[allow(dead_code)] // kept as library API; the CLI uses the version with a progress bar
    pub fn scan(&mut self, from: u8, to: u8) -> Vec<u8> {
        let mut found = Vec::new();
        for id in from..=to {
            if self.ping(id).unwrap_or(false) {
                found.push(id);
            }
        }
        found
    }

    /// For diagnostics: send an arbitrary instruction packet and return verbatim all raw bytes received in the following 500 ms.
    /// Returns (bytes sent, bytes received).
    pub fn raw_exchange(&mut self, id: u8, inst: u8, params: &[u8]) -> io::Result<(Vec<u8>, Vec<u8>)> {
        self.port.clear(serialport::ClearBuffer::Input)?;
        // Rebuild the sent content for display
        let len = params.len() as u8 + 2;
        let mut sent = vec![0xFF, 0xFF, id, len, inst];
        sent.extend_from_slice(params);
        sent.push(Self::checksum(&sent[2..]));

        self.port.write_all(&sent)?;
        self.port.flush()?;

        let deadline = Instant::now() + Duration::from_millis(500);
        let mut out = Vec::new();
        let mut buf = [0u8; 64];
        while Instant::now() < deadline {
            match self.port.read(&mut buf) {
                Ok(n) if n > 0 => out.extend_from_slice(&buf[..n]),
                Ok(_) => {}
                Err(e) if e.kind() == ErrorKind::TimedOut => {}
                Err(e) => return Err(e),
            }
        }
        Ok((sent, out))
    }

    /// Probe whether the servo with a given ID is online.
    /// Note: the reply packet's error byte is the servo's alarm status (e.g. bit0 = voltage fault);
    /// a servo with an alarm still counts as "online".
    pub fn ping(&mut self, id: u8) -> io::Result<bool> {
        self.port.clear(serialport::ClearBuffer::Input)?;
        self.send_packet(id, INST_PING, &[])?;
        match self.recv_non_echo(id, INST_PING, &[]) {
            Ok((rid, _err, _)) => Ok(rid == id),
            Err(e) if e.kind() == ErrorKind::TimedOut => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Read len bytes from the servo (len <= 250).
    /// The error byte (alarm status) isn't treated as a failure; data is returned as usual.
    pub fn read(&mut self, id: u8, addr: u8, len: u8) -> io::Result<Vec<u8>> {
        self.port.clear(serialport::ClearBuffer::Input)?;
        self.send_packet(id, INST_READ, &[addr, len])?;
        let (rid, _err, params) = self.recv_non_echo(id, INST_READ, &[addr, len])?;
        if rid != id {
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                format!("应答 ID 不匹配: 期望 {id}, 收到 {rid}"),
            ));
        }
        Ok(params)
    }

    pub fn read_u8(&mut self, id: u8, addr: u8) -> io::Result<u8> {
        Ok(self.read(id, addr, 1)?[0])
    }

    /// u16 is little-endian (low byte first).
    pub fn read_u16(&mut self, id: u8, addr: u8) -> io::Result<u16> {
        let b = self.read(id, addr, 2)?;
        Ok(u16::from_le_bytes([b[0], b[1]]))
    }

    /// Write some bytes (writing SRAM registers; no reply from the servo is normal).
    pub fn write(&mut self, id: u8, addr: u8, data: &[u8]) -> io::Result<()> {
        let mut params = vec![addr];
        params.extend_from_slice(data);
        self.send_packet(id, INST_WRITE, &params)?;
        // The reply to a write instruction (if enabled) is discarded directly, without blocking
        let _ = self.recv_packet();
        Ok(())
    }

    pub fn write_u8(&mut self, id: u8, addr: u8, v: u8) -> io::Result<()> {
        self.write(id, addr, &[v])
    }

    #[allow(dead_code)] // kept as library API
    pub fn write_u16(&mut self, id: u8, addr: u8, v: u16) -> io::Result<()> {
        self.write(id, addr, &v.to_le_bytes())
    }

    /// Torque switch: true = hold (controllable), false = release (can be moved by hand).
    pub fn set_torque(&mut self, id: u8, enable: bool) -> io::Result<()> {
        self.write_u8(id, reg::TORQUE_ENABLE, enable as u8)
    }

    /// Move the servo to the target position (0~4095); speed is in steps/s, time_ms is the desired duration.
    /// Same as the official SDK's WritePosEx: write 7 bytes in one go starting at ACCELERATION(41).
    pub fn move_to(&mut self, id: u8, pos: u16, speed: u16, time_ms: u16) -> io::Result<()> {
        self.set_torque(id, true)?;
        let pos = pos.min(4095);
        let mut data = Vec::with_capacity(7);
        data.push(50); // acceleration
        data.extend_from_slice(&pos.to_le_bytes());
        data.extend_from_slice(&time_ms.to_le_bytes());
        data.extend_from_slice(&speed.to_le_bytes());
        self.write(id, reg::ACCELERATION, &data)
    }

    /// Read back the 15 bytes starting at address 56 in one go and parse them into ServoStatus.
    pub fn read_status(&mut self, id: u8) -> io::Result<ServoStatus> {
        let b = self.read(id, reg::PRESENT_POSITION, 15)?;
        // b[0..2]  position   b[2..4] speed  b[4..6] load
        // b[6] voltage b[7] temperature  b[8] write flag  b[9] status
        // b[10] moving  b[11..13] reserved  b[13..15] current
        let position = u16::from_le_bytes([b[0], b[1]]);
        let speed = sts_signed(i16::from_le_bytes([b[2], b[3]]));
        let load_raw = u16::from_le_bytes([b[4], b[5]]);
        // Load: bit0~9 is magnitude (0.1%), bit10 is direction
        let load = if load_raw & 0x0400 != 0 {
            -((load_raw & 0x03FF) as i16)
        } else {
            (load_raw & 0x03FF) as i16
        };
        let current_raw = i16::from_le_bytes([b[13], b[14]]);
        let current_ma = sts_signed(current_raw) as f32 * 6.5;
        Ok(ServoStatus {
            position,
            speed,
            load,
            voltage: b[6] as f32 * 0.1,
            temperature: b[7],
            servo_status: b[9],
            moving: b[10] != 0,
            current_ma,
        })
    }
}

/// 2-byte signed numbers in the Feetech protocol: bit15 is the sign bit, the low 15 bits are the value.
fn sts_signed(v: i16) -> i16 {
    if v & (1 << 15) != 0 {
        -(v & !(1 << 15))
    } else {
        v
    }
}
