//! servo.rs: servo driver layer: actually sends protocol packets to the serial port and parses the replies
//!
//! [Layering recap]
//!   protocol.rs  pure data: build / parse packets (no hardware, unit-testable)
//!   registers.rs pure data: memory table definition (no hardware, unit-testable)
//!   servo.rs     this layer: open the serial port, send/receive bytes, handle timeouts and errors
//!   main.rs      outermost layer: parse the command line and call this layer to run the tests the user wants
//!
//! [Rust concept: trait object Box<dyn SerialPort>]
//! The serialport library's serial port implementation is a different type on each operating system.
//! `Box<dyn SerialPort>` means "some type on the heap that implements the SerialPort trait";
//! we don't care what it actually is, as long as it can read/write. This is
//! Rust's "dynamic dispatch", similar to a Java interface reference, but chosen on demand with zero extra abstraction cost.

use std::io::{Read, Write};
use std::time::Duration;

use serialport::SerialPort;

use crate::error::{Result, ServoError};
use crate::protocol::{self, Instruction, StatusPacket, BROADCAST_ID};
use crate::registers::{self, Register};

/// Servo driver object. Owns an exclusive serial port handle.
///
/// [Rust concept: ownership guarantees "exclusive access"]
/// The serial port is an exclusive resource; only one place can send/receive at a time.
/// Rust's ownership guarantees this at compile time: the serial handle is owned by Servo,
/// operating a servo must go through `&mut self` (a mutable borrow), and only one mutable borrow can exist at a time,
/// so the language itself rules out "two threads reading/writing the serial port at once and garbling packets".
pub struct Servo {
    port: Box<dyn SerialPort>,
    /// If your hardware uses the simple wiring with TX/RX shorted together, the data you send is received back;
    /// set this to true to discard the "echo" after each send before reading the reply.
    discard_echo: bool,
    /// Whether to print raw sent/received packets (very useful when learning the protocol)
    verbose: bool,
}

/// Servo real-time feedback data (memory table addresses 56~69 read back in one go).
///
/// [Rust concept: deriving Debug for a struct]
/// #[derive(Debug)] lets us print the whole struct directly with `println!("{fb:?}")`,
/// very handy when debugging.
#[derive(Debug)]
pub struct Feedback {
    /// Current position (0.087 deg/unit, with direction bit; includes turn count in multi-turn mode)
    pub pos: i64,
    /// Current speed (0.732 RPM/unit, with direction bit)
    pub vel: i64,
    /// Current load/duty cycle (0.1%/unit, BIT10 direction bit)
    pub load: i64,
    /// Current voltage (in V, converted to floating point)
    pub voltage: f64,
    /// Current temperature (°C)
    pub temp: i64,
    /// Servo status byte (0 = normal, faults indicated by bits)
    pub status: u8,
    /// Moving flag
    pub moving: u8,
    /// Current (mA, converted to floating point, with direction)
    pub current: f64,
}

impl Servo {
    /// Open the serial port and create the driver object.
    ///
    /// [Rust concept: the ? operator]
    /// `serialport::new(...).open()?` means: on failure, convert the error into
    /// ServoError and return immediately (via the automatic #[from] conversion in error.rs);
    /// on success, unwrap and continue. This makes error handling both strict and concise.
    pub fn connect(path: &str, baud: u32, timeout_ms: u64, discard_echo: bool, verbose: bool) -> Result<Self> {
        let port = serialport::new(path, baud)
            .timeout(Duration::from_millis(timeout_ms)) // max wait for each read
            .data_bits(serialport::DataBits::Eight)     // 8 data bits
            .parity(serialport::Parity::None)           // no parity
            .stop_bits(serialport::StopBits::One)       // 1 stop bit; datasheet 7-2: 8bit, 1stop, No Parity
            .open()?;
        Ok(Servo { port, discard_echo, verbose })
    }

    // =========================================================================
    // Low-level send/receive
    // =========================================================================

    /// Send one instruction and wait for the reply; returns the parsed reply packet.
    /// This is the common channel for all instructions.
    fn transact(&mut self, id: u8, inst: Instruction, params: &[u8], expect_reply: bool) -> Result<StatusPacket> {
        let pkt = protocol::build_packet(id, inst, params);

        // Clear leftover bytes in the receive buffer (the tail of the previous exchange, noise, etc.),
        // otherwise old data might be mistaken for this reply.
        let _ = self.port.clear(serialport::ClearBuffer::Input);

        if self.verbose {
            eprintln!("  >> 发送: {:02X?}", pkt);
        }

        // [Rust concept: passing &mut self]
        // write_all needs a mutable borrow of the serial port. Since transact itself borrows &mut self,
        // the compiler guarantees nobody else can touch the serial port in the meantime.
        self.port.write_all(&pkt)?;
        self.port.flush()?;

        // The simple wiring (TX/RX shorted) first receives what we just sent; discard the same number of bytes
        if self.discard_echo {
            let mut echo = vec![0u8; pkt.len()];
            let _ = self.port.read_exact(&mut echo);
        }

        // The broadcast address doesn't reply; with reply level 0, write instructions don't reply either
        if !expect_reply || id == BROADCAST_ID {
            return Ok(StatusPacket { id, error: 0, params: Vec::new() });
        }

        let raw = self.recv_packet()?;
        if self.verbose {
            eprintln!("  << 接收: {:02X?}", raw);
        }
        let status = protocol::parse_status(&raw)?;
        // Verify that the replying servo ID is the one we addressed
        // (there may be several servos on the bus; receiving someone else's reply means the timing went wrong)
        if status.id != id {
            return Err(ServoError::Malformed("应答包 ID 与请求不符".into()));
        }
        if status.error != 0 {
            return Err(ServoError::ServoStatus(
                status.error,
                protocol::describe_status(status.error),
            ));
        }
        Ok(status)
    }

    /// Read one complete reply packet from the serial port (scan byte by byte for the header → read ID/Length → read the rest).
    ///
    /// [Rust concept: translating "timeout IO errors" into "domain errors"]
    /// A serial read timeout shows up as io::ErrorKind::TimedOut; we map it to
    /// ServoError::Timeout so the upper layers see a more meaningful error.
    fn recv_packet(&mut self) -> Result<Vec<u8>> {
        // Step 1: scan byte by byte until the header 0xFF 0xFF is found
        // (there may be noise bytes on the bus; we can't assume the first byte is the header)
        let mut window = [0u8; 2]; // sliding window: holds the two most recently received bytes
        let mut found = false;
        for _ in 0..64 {
            // Scan at most 64 bytes, give up if not found
            let mut b = [0u8; 1];
            self.port.read_exact(&mut b).map_err(|e| match e.kind() {
                std::io::ErrorKind::TimedOut => ServoError::Timeout,
                _ => ServoError::Io(e),
            })?;
            window[0] = window[1];
            window[1] = b[0];
            if window == protocol::HEADER {
                found = true;
                break;
            }
        }
        if !found {
            return Err(ServoError::Malformed("找不到帧头 0xFF 0xFF".into()));
        }

        // Step 2: read ID and Length
        let mut head = [0u8; 2];
        self.port.read_exact(&mut head).map_err(|e| match e.kind() {
            std::io::ErrorKind::TimedOut => ServoError::Timeout,
            _ => ServoError::Io(e),
        })?;
        let length = head[1] as usize;

        // Step 3: read the remaining bytes according to Length (Error + params + checksum)
        let mut rest = vec![0u8; length];
        self.port.read_exact(&mut rest).map_err(|e| match e.kind() {
            std::io::ErrorKind::TimedOut => ServoError::Timeout,
            _ => ServoError::Io(e),
        })?;

        // Assemble a complete frame and hand it to the protocol layer for parsing
        let mut full = Vec::with_capacity(4 + length);
        full.extend_from_slice(&protocol::HEADER);
        full.extend_from_slice(&head);
        full.extend_from_slice(&rest);
        Ok(full)
    }

    // =========================================================================
    // Instruction-level API (one-to-one with protocol instructions)
    // =========================================================================

    /// PING handshake: returns Ok(true) if the servo is online, Ok(false) on timeout, other errors are propagated as is.
    ///
    /// [Rust concept: handling error types separately with match]
    /// A timeout only means "no servo at this ID" and isn't a failure; other errors are real failures.
    pub fn ping(&mut self, id: u8) -> Result<bool> {
        match self.transact(id, Instruction::Ping, &[], true) {
            Ok(_) => Ok(true),
            Err(ServoError::Timeout) => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Read memory: read len bytes starting at addr.
    pub fn read(&mut self, id: u8, addr: u8, len: u8) -> Result<Vec<u8>> {
        let resp = self.transact(id, Instruction::Read, &[addr, len], true)?;
        Ok(resp.params)
    }

    /// Write memory (takes effect immediately): write data starting at addr.
    pub fn write(&mut self, id: u8, addr: u8, data: &[u8]) -> Result<()> {
        // Params = [start address, data...], assembled with an iterator
        let mut params = Vec::with_capacity(data.len() + 1);
        params.push(addr);
        params.extend_from_slice(data);
        self.transact(id, Instruction::Write, &params, true)?;
        Ok(())
    }

    /// Asynchronous write (REG WRITE): buffered first, actually executed only after the action() broadcast.
    /// Typical use: REG_WRITE target positions to several servos individually, then one broadcast ACTION
    /// starts all servos at once: the basis of multi-axis synchronization.
    pub fn reg_write(&mut self, id: u8, addr: u8, data: &[u8]) -> Result<()> {
        let mut params = Vec::with_capacity(data.len() + 1);
        params.push(addr);
        params.extend_from_slice(data);
        self.transact(id, Instruction::RegWrite, &params, true)?;
        Ok(())
    }

    /// Broadcast ACTION: trigger all servos to execute their previously buffered REG_WRITE content.
    pub fn action(&mut self) -> Result<()> {
        self.transact(BROADCAST_ID, Instruction::Action, &[], false)?;
        Ok(())
    }

    /// Sync write (SYNC WRITE 0x83): one packet writes the same register on several servos.
    ///
    /// Packet structure (broadcast ID, no reply):
    ///   FF FF FE Length 0x83 start-address data-length [ID1 data...] [ID2 data...]... Checksum
    ///
    /// Typical scenario: the 6 joints of a robot arm must receive target positions "simultaneously";
    /// addressing them one by one staggers them by tens of milliseconds, while a single sync write packet reaches all at once.
    pub fn sync_write(&mut self, ids: &[u8], reg: &Register, value: i64) -> Result<()> {
        if ids.is_empty() {
            return Err(ServoError::InvalidParam("同步写至少需要一个目标 ID".into()));
        }
        reg.check_value(value)?;
        let val = registers::encode_value(value, reg.sign_bit);
        let data: Vec<u8> = if reg.size == 1 {
            vec![val as u8]
        } else {
            val.to_le_bytes().to_vec()
        };

        // Assemble params: start address + per-servo data length + [ID, data...] for each servo
        let mut params = Vec::with_capacity(2 + ids.len() * (1 + data.len()));
        params.push(reg.addr);
        params.push(data.len() as u8);
        for &id in ids {
            params.push(id);
            params.extend_from_slice(&data);
        }
        // Sync write is a broadcast instruction; servos don't reply
        self.transact(BROADCAST_ID, Instruction::SyncWrite, &params, false)?;
        Ok(())
    }

    /// Factory reset (all EPROM at addresses 5~39 back to defaults).
    pub fn factory_reset(&mut self, id: u8) -> Result<()> {
        self.transact(id, Instruction::Reset, &[], true)?;
        Ok(())
    }

    /// Reboot the servo (0x08): equivalent to a power cycle; SRAM reloads from EPROM.
    /// Used to verify that EPROM writes were really committed (robotd's servo-replacement flow uses it too).
    pub fn reboot(&mut self, id: u8) -> Result<()> {
        self.transact(id, Instruction::Reboot, &[], true)?;
        Ok(())
    }

    /// Position calibration (0x0B): recalibrate the servo's "current position" to the target reading
    /// (None = center 2048, same as the "Set zero" button in Feetech's FD debugging software).
    ///
    /// On receipt the servo automatically computes and updates the position offset register at address 31.
    /// [Note] HD-1910 (HLS-series firmware ≥3.43) doesn't support the old "write 128 to the torque switch" calibration;
    /// this instruction must be used. Also, Feetech may reply "success" even for unsupported operations,
    /// so callers should read back the position and offset registers to confirm after calibrating (see the zero command).
    pub fn calibrate(&mut self, id: u8, target: Option<u16>) -> Result<()> {
        let params = match target {
            Some(t) => t.to_le_bytes().to_vec(), // little-endian: low byte first
            None => Vec::new(),
        };
        self.transact(id, Instruction::Calibrate, &params, true)?;
        Ok(())
    }

    // =========================================================================
    // Register-level API (uses the memory table; handles multi-byte values, sign bits and range checks automatically)
    // =========================================================================

    /// Read one register and decode it into a signed integer (handles little-endian and sign-magnitude encoding automatically).
    pub fn read_reg(&mut self, id: u8, reg: &Register) -> Result<i64> {
        let raw = self.read(id, reg.addr, reg.size)?;
        if raw.len() < reg.size as usize {
            return Err(ServoError::Malformed("读到的数据长度不足".into()));
        }
        // Little-endian assembly: the lower address is the low byte (doc section 2: "the low byte is at the lower address")
        let val = if reg.size == 1 {
            raw[0] as u16
        } else {
            u16::from_le_bytes([raw[0], raw[1]])
        };
        Ok(registers::decode_value(val, reg.sign_bit))
    }

    /// Write one register (automatic range check, sign-magnitude encoding, little-endian split).
    ///
    /// Note: this function writes directly. If writing the EPROM area and it must persist across power loss,
    /// use save_reg().
    pub fn write_reg(&mut self, id: u8, reg: &Register, value: i64) -> Result<()> {
        // [Defensive programming] validate before writing: refuse writes to read-only registers and out-of-range values.
        // The memory table is our "schema"; catching errors before sending is much better than letting the servo misbehave.
        if reg.access == registers::Access::ReadOnly {
            return Err(ServoError::InvalidParam(format!(
                "寄存器 {}（{}）是只读的，不能写入",
                reg.key, reg.cn
            )));
        }
        reg.check_value(value)?;
        let val = registers::encode_value(value, reg.sign_bit);
        let bytes = if reg.size == 1 {
            vec![val as u8]
        } else {
            val.to_le_bytes().to_vec() // little-endian: low byte sent first
        };
        self.write(id, reg.addr, &bytes)
    }

    /// Write an EPROM register and persist it across power loss.
    ///
    /// [Important mechanism: the lock flag (address 55)]
    ///   lock=1 (default): writing EPROM-area values only changes RAM, not persisted across power loss;
    ///   lock=0: writing EPROM-area values really writes to EPROM, persisted across power loss.
    /// So the persistence flow is: unlock (write 0) → write the target register → lock again (write 1).
    ///
    /// [Why not just stay unlocked?] EPROM has limited erase/write endurance (about 100,000 cycles);
    /// staying locked prevents a program bug from wearing out the servo with runaway writes.
    pub fn save_reg(&mut self, id: u8, reg: &Register, value: i64) -> Result<()> {
        if reg.area != registers::Area::Eprom {
            // The SRAM area takes effect in real time and is lost on power loss anyway; no unlock flow needed
            return self.write_reg(id, reg, value);
        }
        let lock = registers::find_register("lock").expect("lock 寄存器必定存在");
        self.write_reg(id, lock, 0)?; // unlock
        let result = self.write_reg(id, reg, value);
        // Lock again whether or not the write succeeded; get the result before `?` so an error doesn't skip locking
        let relock = self.write_reg(id, lock, 1);
        result.and(relock)
    }

    // =========================================================================
    // High-level semantic API (convenience methods for test scenarios)
    // =========================================================================

    /// Read back all real-time feedback at once (addresses 56~70, 15 bytes total; one read is much faster than several).
    pub fn read_feedback(&mut self, id: u8) -> Result<Feedback> {
        let raw = self.read(id, 56, 15)?;
        if raw.len() < 15 {
            return Err(ServoError::Malformed("反馈数据长度不足".into()));
        }
        // Helper closure: take a 2-byte little-endian value
        let u16le = |i: usize| u16::from_le_bytes([raw[i], raw[i + 1]]);
        Ok(Feedback {
            pos: registers::decode_value(u16le(0), Some(15)),        // 56 current position
            vel: registers::decode_value(u16le(2), Some(15)),        // 58 current speed
            load: registers::decode_value(u16le(4), Some(10)),       // 60 current load, BIT10 direction bit
            voltage: raw[6] as f64 / 10.0,                           // 62 voltage 0.1V
            temp: raw[7] as i64,                                     // 63 temperature °C
            status: raw[9],                                          // 65 servo status
            moving: raw[10],                                         // 66 moving flag
            current: registers::decode_value(u16le(13), Some(15)) as f64 * 6.5, // 69 current 6.5mA
        })
    }
}
