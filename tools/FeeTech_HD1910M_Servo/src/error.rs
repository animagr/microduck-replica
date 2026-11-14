//! error.rs: defines in one place all the "error types" this project can produce
//!
//! [Rust concept: error handling]
//! Rust has no try/catch exceptions like Java/Python; instead, "may fail" is written
//! explicitly into the function signature: return `Result<T, E>`, either success with a T or failure with an E.
//! The caller must handle the Result (with match, if let, or propagate it with the `?` operator),
//! or the compiler reports an error. This is Rust's famous "the compiler forces you to write robust code".
//!
//! [Rust concept: enums]
//! Rust enums are far more powerful than C enums: each variant can carry data of a different type,
//! more like an "algebraic data type". Each error variant below carries relevant context.

use thiserror::Error;

/// Unified error type for the servo tool.
///
/// `#[derive(Error, Debug)]` is a "derive macro": it has the thiserror library automatically
/// implement the standard library's `std::error::Error` trait (trait/interface) for our enum;
/// `{0}`, `{1}` in the `#[error("...")]` annotation refer to the data carried by the enum variant.
#[derive(Error, Debug)]
pub enum ServoError {
    /// Serial port open/read/write failed. `#[from]` means `?` can automatically convert
    /// serialport's error into our error type, saving handwritten conversion code.
    #[error("串口错误: {0}")]
    Serial(#[from] serialport::Error),

    /// Standard IO error (e.g. low-level errors while reading the serial port)
    #[error("IO 错误: {0}")]
    Io(#[from] std::io::Error),

    /// Timed out waiting for the servo's reply: the most common error: bad wiring / wrong ID / wrong baud rate
    #[error("响应超时：舵机未应答（检查接线、ID、波特率）")]
    Timeout,

    /// Reply packet checksum mismatch, meaning interference on the line or truncated data
    #[error("应答包校验和错误")]
    Checksum,

    /// Reply packet doesn't match the protocol format (wrong header, wrong length, etc.)
    #[error("应答包格式错误: {0}")]
    Malformed(String),

    /// The servo returned an error status byte (voltage/temperature/current/encoder fault);
    /// the first field is the raw status byte, the second is the parsed Chinese description.
    #[error("舵机报告异常 (状态字 0x{0:02X}): {1}")]
    ServoStatus(u8, String),

    /// The user's input parameter is invalid (out of range, read-only register, etc.)
    #[error("参数错误: {0}")]
    InvalidParam(String),
}

/// [Rust concept: type aliases]
/// Give a long, frequently used type a short name. The standard form `Result<T, ServoError>`
/// is abbreviated throughout this project as `Result<T>`.
/// Note that it "shadows" the standard library's Result; this is a common convention in the Rust community.
pub type Result<T> = std::result::Result<T, ServoError>;
