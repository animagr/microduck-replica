//! protocol.rs: FT-SCS custom serial protocol (Feetech's proprietary servo protocol)
//!
//! [Frame format: host-to-servo packet]
//! ```text
//!   Byte index:   0     1     2      3         4          5..N+4    N+5
//!   Content:    0xFF  0xFF   ID   Length   Instruction   params...  Checksum
//! ```
//!   - Header: two fixed 0xFF bytes so the receiver can find the start of a frame;
//!   - ID: target servo address 0~253; 0xFE (254) is the broadcast address (all servos receive it but don't reply);
//!   - Length = number of parameters N + 2 (1 instruction byte + 1 checksum byte);
//!   - Checksum = sum of ID + Length + Instruction + all parameters,
//!     inverted (~) with only the low 8 bits kept. The receiver recomputes it and discards the frame on mismatch.
//!
//! [Servo reply packet] almost the same format, except byte 4 changes from "instruction" to "error status byte":
//! ```text
//!   0xFF  0xFF   ID   Length   Error   params...   Checksum
//! ```
//!
//! [Rust concept: why doesn't this layer touch the serial port?]
//! This layer only does pure data conversion between "byte array <-> struct" and doesn't know the serial port exists.
//! The benefit: it can be unit-tested without hardware (see the #[cfg(test)] module at the bottom of the file);
//! this is a typical "layered design" practice.

use crate::error::{Result, ServoError};

/// Frame header: the FT-SCS protocol always uses two 0xFF bytes to mark the start of a frame.
pub const HEADER: [u8; 2] = [0xFF, 0xFF];

/// Broadcast ID: every servo on the bus executes it, but none returns a reply packet.
/// Commonly used for synchronous writes to multiple servos. Never use it to check whether a servo exists when scanning.
pub const BROADCAST_ID: u8 = 0xFE;

/// Protocol instruction set (all instructions mentioned in lines 7 and 19 of the memory table doc are here).
///
/// [Rust concept: #[repr(u8)]]
/// By default the memory layout of a Rust enum is not guaranteed externally; adding #[repr(u8)]
/// forces each variant to be represented by 1 byte whose value is the number we specify,
/// so `Instruction::Ping as u8` safely yields the protocol byte 0x01.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Instruction {
    /// 0x01 Query whether the servo is online (handshake); a working servo should return a reply packet
    Ping = 0x01,
    /// 0x02 Read memory table: params = [start address, number of bytes to read]
    Read = 0x02,
    /// 0x03 Write memory table: params = [start address, data...], takes effect immediately
    Write = 0x03,
    /// 0x04 Asynchronous write (REG WRITE): same params as write, but it is "noted down" and not executed
    /// until an ACTION instruction arrives, then executed together (for synchronized multi-servo motion)
    RegWrite = 0x04,
    /// 0x05 Trigger execution of what was previously buffered by REG WRITE
    Action = 0x05,
    /// 0x06 Factory reset (all EPROM back to defaults)
    Reset = 0x06,
    /// 0x08 Reboot the servo: equivalent to a power cycle; SRAM reloads from EPROM.
    /// Can be used to verify that EPROM writes were really committed without physically cutting power
    Reboot = 0x08,
    /// 0x0A Status reset (resets the turn counter in multi-turn mode)
    ResetTurns = 0x0A,
    /// 0x0B Position calibration: no params = calibrate the current position as center 2048;
    /// with a 2-byte param (little-endian) = calibrate to the given reading.
    /// On receipt the servo automatically computes and updates the position offset register at address 31;
    /// this is the instruction behind the "Set zero" button in Feetech's FD debugging software.
    /// Note: HD-1910 (HLS-series firmware ≥3.43) doesn't support the old "write 128 to the torque switch" calibration;
    /// this instruction must be used, and a "success" reply doesn't mean it took effect, so always read back to confirm after calibrating.
    Calibrate = 0x0B,
    /// 0x83 Sync write: one instruction writes the same address on several servos at once
    SyncWrite = 0x83,
}

/// Compute the FT-SCS checksum: add all bytes, invert bitwise, keep only the low 8 bits.
///
/// [Rust concept: `impl IntoIterator` and generics]
/// The parameter uses a generic + trait bound so this function accepts both `&[u8]` and `Vec<u8>`,
/// giving callers more freedom. `.iter()` produces an iterator, and `.fold(0u8, ...)` is a "fold" accumulation.
/// wrapping_add is addition that "wraps around on overflow": the checksum is modulo 256 anyway;
/// with a plain `+`, overflow panics in debug mode (the program crashes);
/// that's Rust's safeguard for catching arithmetic errors, and here we explicitly declare "I do want wraparound".
pub fn checksum(bytes: &[u8]) -> u8 {
    let sum = bytes
        .iter()
        .fold(0u8, |acc, &b| acc.wrapping_add(b));
    !sum // `!` on integers is bitwise NOT; only on bool is it logical NOT
}

/// Assemble a complete host-to-servo packet.
///
/// [Rust concept: Vec and ownership]
/// The function creates a Vec<u8> internally and "returns" it to the caller: ownership moves along with it,
/// no malloc/free and no garbage collection; the compiler decides at compile time who is responsible for freeing it.
pub fn build_packet(id: u8, inst: Instruction, params: &[u8]) -> Vec<u8> {
    // Length = instruction (1) + number of params + checksum (1)
    let length = (params.len() + 2) as u8;

    // with_capacity preallocates exactly enough memory, avoiding repeated growth on push
    let mut pkt = Vec::with_capacity(params.len() + 6);
    pkt.extend_from_slice(&HEADER);
    pkt.push(id);
    pkt.push(length);
    pkt.push(inst as u8);
    pkt.extend_from_slice(params);
    // The checksum covers ID..=last param (excluding the header)
    pkt.push(checksum(&pkt[2..]));
    pkt
}

/// Parsed servo reply packet.
pub struct StatusPacket {
    /// ID of the replying servo
    pub id: u8,
    /// Error status byte: 0 means normal; when non-zero each bit represents a fault
    /// (BIT0 voltage / BIT1 magnetic encoder / BIT2 temperature / BIT3 current)
    pub error: u8,
    /// Data carried by the reply (the return value of a read instruction goes here)
    pub params: Vec<u8>,
}

/// Parse a string of received raw bytes into a StatusPacket, with full validation.
///
/// [Rust concept: using Result as a "composable validation pipeline"]
/// Each check returns Err(...) early on failure, and the success path is written straight down,
/// avoiding deeply nested if/else (the so-called "guard clause" style).
pub fn parse_status(buf: &[u8]) -> Result<StatusPacket> {
    // A frame is at least 6 bytes: header 2 + ID + Length + Error + Checksum
    if buf.len() < 6 {
        return Err(ServoError::Malformed("应答包太短，不足 6 字节".into()));
    }
    if buf[0] != HEADER[0] || buf[1] != HEADER[1] {
        return Err(ServoError::Malformed("帧头不是 0xFF 0xFF".into()));
    }
    let id = buf[2];
    let length = buf[3] as usize;
    // Total length claimed by the Length field = header 2 + ID + Length + value of Length
    if buf.len() != length + 4 {
        return Err(ServoError::Malformed("包长度与 Length 字段不符".into()));
    }
    // Recompute the checksum (same range: from ID up to before the checksum byte)
    let expect = checksum(&buf[2..buf.len() - 1]);
    if expect != buf[buf.len() - 1] {
        return Err(ServoError::Checksum);
    }
    Ok(StatusPacket {
        id,
        error: buf[4],
        // Parameter area = after the error byte, before the checksum byte; may be empty (e.g. a PING reply)
        params: buf[5..buf.len() - 1].to_vec(),
    })
}

/// Translate the servo status byte (reply packet Error byte / memory table address 65) into a Chinese description.
///
/// [Rust concept: bit operations + Vec<String> + join]
/// The status byte is bit-encoded: BIT0(1)=voltage BIT1(2)=magnetic encoder BIT2(4)=temperature BIT3(8)=current.
/// When several faults are present the value is the sum of the bits, so test each bit with `&`.
pub fn describe_status(status: u8) -> String {
    if status == 0 {
        return "正常".to_string();
    }
    let mut problems: Vec<&str> = Vec::new();
    // [Rust concept: iterator-style bit checks] a plain array loop here, simple and direct
    let bits = [
        (1 << 0, "电压异常"),
        (1 << 1, "磁编码器异常"),
        (1 << 2, "过热"),
        (1 << 3, "过流"),
    ];
    for (bit, name) in bits {
        if status & bit != 0 {
            problems.push(name);
        }
    }
    problems.join(" + ")
}

// =============================================================================
// [Rust concept: unit tests]
// `#[cfg(test)]` means this module is compiled only for `cargo test`, and excluded from release builds.
// The protocol layer is pure functions with no hardware dependency, ideal for ensuring correctness with unit tests.
// =============================================================================
#[cfg(test)]
mod tests {
    use super::*; // bring in everything from the parent module (super = the module one level up)

    #[test]
    fn test_build_ping_packet() {
        // The classic PING ID=1 packet: FF FF 01 02 01 FB
        let pkt = build_packet(1, Instruction::Ping, &[]);
        assert_eq!(pkt, vec![0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB]);
    }

    #[test]
    fn test_checksum_wraps() {
        // 0xFF + 0xFF overflows u8; wrapping_add should wrap around instead of panicking
        assert_eq!(checksum(&[0xFF, 0xFF]), !0xFEu8);
    }

    #[test]
    fn test_parse_status_roundtrip() {
        // Build a valid reply packet ourselves (reading address 56 returns 2 bytes), then parse it back
        let raw = [0xFF, 0xFF, 0x01, 0x04, 0x00, 0x00, 0x08, 0xF2];
        let pkt = parse_status(&raw).expect("合法包应该解析成功");
        assert_eq!(pkt.id, 1);
        assert_eq!(pkt.error, 0);
        assert_eq!(pkt.params, vec![0x00, 0x08]); // little-endian: position = 0x0800 = 2048
    }

    #[test]
    fn test_parse_bad_checksum() {
        let raw = [0xFF, 0xFF, 0x01, 0x04, 0x00, 0x00, 0x08, 0x00]; // checksum byte deliberately wrong
        assert!(matches!(parse_status(&raw), Err(ServoError::Checksum)));
    }

    #[test]
    fn test_build_calibrate_packet() {
        // Position calibration ID=1 calibrated to 2048 (0x0800): FF FF 01 04 0B 00 08 E7
        let pkt = build_packet(1, Instruction::Calibrate, &2048u16.to_le_bytes());
        assert_eq!(pkt, vec![0xFF, 0xFF, 0x01, 0x04, 0x0B, 0x00, 0x08, 0xE7]);
        // No params = calibrate to center 2048: FF FF 01 02 0B F1
        let pkt = build_packet(1, Instruction::Calibrate, &[]);
        assert_eq!(pkt, vec![0xFF, 0xFF, 0x01, 0x02, 0x0B, 0xF1]);
    }
}
