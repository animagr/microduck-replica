//! lib.rs: library target: exposes the servo driver as a "library other programs can reuse"
//!
//! [Rust concept: one crate can be both a "program" and a "library"]
//! Cargo conventions:
//!   - src/main.rs  → compiled into an executable (binary target)
//!   - src/lib.rs   → compiled into a library (library target, other projects can depend on it)
//! The two can coexist in the same package! The benefits:
//!   - our CLI tool (main.rs) keeps existing;
//!   - the GUI project can directly use, via the path dependency `path = "../FeeTech_HD1910M_Servo"`,
//!     the protocol / registers / servo / error modules here, with **zero code duplication**.
//!
//! This is the payoff of layered design: the lower-level modules don't depend on any CLI code in main.rs,
//! so they can be reused directly by another kind of "front end" (a graphical interface).
//!
//! The library name is set to feetech_servo in the [lib] section of Cargo.toml
//! (Rust identifiers can't contain `-`, so an underscore is used).

pub mod error;
pub mod protocol;
pub mod registers;
pub mod servo;
