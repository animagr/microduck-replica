# HD1910M Servo Test Tool - A Hands-On Rust Tutorial

**English** · [简体中文](TUTORIAL.md)

> This manual is meant to be read alongside the source code. Goal: through a project that "really controls hardware",
> learn the core concepts of Rust while mastering the Feetech FT-SCS serial servo protocol.
>
> Hardware: HD1910M servo (6V 12kg·cm, 360° magnetic encoder, TTL half-duplex serial, with force control)
> Software: Rust 1.98+ / Raspberry Pi / CH340 USB-to-serial adapter

---

## Contents

1. [Hardware connection](#1-硬件连接)
2. [Five-minute quick start](#2-五分钟上手)
3. [FT-SCS communication protocol in detail](#3-ft-scs-通信协议详解)
4. [Memory table in detail](#4-内存表详解)
5. [Project structure and layered design](#5-项目结构与分层设计)
6. [Rust concepts explained](#6-rust-知识点精讲)
7. [Complete command reference](#7-命令完整参考)
8. [Experiment tutorials (hands-on)](#8-实验教程动手做)
9. [Safety precautions](#9-安全注意事项)
10. [Troubleshooting common problems](#10-常见问题排查)

---

## 1. Hardware connection

Servo lead (AMP2.0-3P connector):

| Pin | Wire color | Function | Connects to |
|------|------|------|----------|
| 1 | Black | Signal (TTL serial signal) | TX and RX of the CH340 (half-duplex, see below) |
| 2 | Black | Vcc (4~8.4V, typically 6V/7.4V) | **External power supply positive** (cannot be powered from USB!) |
| 3 | Black | GND | External power supply negative, **must share ground with the CH340's GND** |

Key points:

- **Half-duplex**: the servo has only one signal wire, used for both sending and receiving. The CH340 is full-duplex (separate TX/RX);
  the simple wiring is to short the CH340's TX and RX together and connect them to the servo signal wire. The cost is that the data you send
  is received back by yourself ("echo"); in that case, run the program with the `--echo` flag to discard the echo.
  The more proper approach is to use Feetech's official half-duplex adapter board (URT-1, etc.), in which case `--echo` is not needed.
- **Common ground**: servo GND, power supply GND, and CH340 GND must all be connected together, otherwise communication is unreliable.
- **Power supply**: stall current can reach 1.6A (at 6V), which a USB port cannot supply; always use a separate power supply.
- On a Raspberry Pi, the CH340 is usually detected as `/dev/ttyUSB0` (this tool's default).

---

## 2. Five-minute quick start

```bash
# Build (the first time downloads dependencies and compiles; output goes in target/debug/)
cargo build

# From then on, run like this (cargo run compiles first and then executes; everything after -- is passed to our program)
cargo run -- scan

# You can also run the compiled binary directly
./target/debug/feetech-HD1910M-tester scan

# 1. Scan the bus for servos (with progress bar)
./target/debug/feetech-HD1910M-tester scan

# 2. Read the whole memory table
./target/debug/feetech-HD1910M-tester dump

# 3. Real-time monitoring (position/speed/voltage/temperature/current, Ctrl+C to stop)
./target/debug/feetech-HD1910M-tester monitor

# 4. Move to the 90° position (1024 ≈ 90°, center is 2048)
./target/debug/feetech-HD1910M-tester goto 1024

# 5. List all commands
./target/debug/feetech-HD1910M-tester --help
./target/debug/feetech-HD1910M-tester pid --help   # Show help for a specific subcommand
```

Global options (can go before or after the subcommand):

```
-p / --port     Serial port path, default /dev/ttyUSB0
-b / --baud     Baud rate, default 1000000
-i / --id       Servo ID, default 1
-t / --timeout  Timeout in milliseconds, default 50 (can be lowered to 20 to speed up scanning)
-v / --verbose  Print raw sent/received packets (a great tool for learning the protocol!)
    --echo      Enable with the TX/RX shorted wiring to discard echo
```

---

## 3. FT-SCS communication protocol in detail

Corresponding source: `src/protocol.rs`

The servo's factory serial configuration: **1Mbps, 8 data bits, no parity, 1 stop bit** (datasheet section 7-2).
The protocol is the classic "master-slave request/response" style: the host (Raspberry Pi) sends an instruction packet, and the servo returns a response packet.

### 3.1 Host instruction packet

```
 Byte:    0     1     2      3         4         5..N+4     N+5
 Field: 0xFF  0xFF   ID   Length  Instruction  Params...   Checksum
```

- **Header** `0xFF 0xFF`: two fixed bytes; the receiver uses them to align to the start of a frame;
- **ID**: target servo station number 0~253; `0xFE` is the broadcast address (all servos execute, but none respond);
- **Length** = number of parameters N + 2 (1 byte instruction + 1 byte checksum);
- **Checksum** = `~(ID + Length + Instruction + all parameters)`, low 8 bits.
  The receiver recalculates it; a mismatch means a transmission error, and the whole packet is discarded.

### 3.2 Servo response packet

The format is almost the same as the instruction packet, except byte 4 changes from "instruction" to "**error status byte**":

```
 0xFF  0xFF   ID   Length   Error   Params...   Checksum
```

An Error of 0 means normal; when nonzero it is interpreted bit by bit (BIT0 voltage / BIT1 magnetic encoder / BIT2 temperature / BIT3 current).

### 3.3 Instruction set

| Instruction | Value | Purpose |
|------|-----|------|
| PING | 0x01 | Handshake, checks whether the servo is online |
| READ | 0x02 | Read the memory table, params = [start address, byte count] |
| WRITE | 0x03 | Write the memory table, params = [start address, data...], takes effect immediately |
| REG WRITE | 0x04 | Asynchronous write: buffered first, not executed |
| ACTION | 0x05 | Triggers all buffered asynchronous writes (the key to synchronized multi-servo motion) |
| RESET | 0x06 | Restore factory settings |
| SYNC WRITE | 0x83 | One packet writes the same address on multiple servos |

### 3.4 A real example

With the `-v` flag you can see the packets actually sent and received, e.g. `goto 911 --speed 500`:

```
>> 发送: [FF, FF, 01, 05, 03, 2E, F4, 01, D3]   # WRITE address 46 (speed) = 0x01F4 = 500
<< 接收: [FF, FF, 01, 02, 00, FC]               # Response: Error=0, normal
>> 发送: [FF, FF, 01, 04, 03, 28, 01, CE]       # WRITE address 40 (torque switch) = 1
>> 发送: [FF, FF, 01, 05, 03, 2A, 8F, 03, 3A]   # WRITE address 42 (goal position) = 0x038F = 911
```

(`发送` = sent, `接收` = received, as printed by the tool.)

Verify the checksum by hand: `0x01+0x05 = 0x06, +0x03 = 0x09, +0x2E = 0x37, +0xF4 = 0x12B, +0x01 = 0x12C`;
keeping only the low 8 bits gives `0x2C`, and bitwise NOT gives `!0x2C = 0xD3`, which matches the last byte of the packet exactly ✔

> **Exercise**: open the unit tests at the bottom of `src/protocol.rs` (`cargo test`);
> they contain full assertions for a PING packet. Try verifying them by hand.

---

## 4. Memory table in detail

Corresponding source: `src/registers.rs`

The memory table is the servo's internal "parameter register"; each address stores one parameter. **Two-byte data is stored low byte first (little-endian)**.

### 4.1 Five sections

| Address | Section | Access | Description |
|------|------|------|------|
| 0~4 | Version info | Read-only | Firmware/servo version numbers, endianness flag |
| 5~39 | EPROM configuration | Read/write | ID, baud rate, PID, protection parameters... **persist across power loss** |
| 40~55 | SRAM control | Read/write | Torque switch, goal position/current/speed... take effect in real time, lost on power loss |
| 56~75 | SRAM feedback | Read-only | Present position/speed/load/voltage/temperature/current |
| 77~86 | Factory parameters | Read-only | Factory calibration values, do not touch |

### 4.2 Lock flag (address 55): the EPROM persistence mechanism

This is the mechanism people trip over most often:

- Lock = **1 (factory default)**: writing to the EPROM area (addresses 5~39) only changes the value in RAM, and **the original value is restored after power loss**;
- Lock = **0**: values written to the EPROM area are actually burned into EPROM and **persist across power loss**.

So the standard flow for "persisting a configuration" is: **unlock → write → lock again**.
This tool's `set <register> <value> --save`, `set-id`, and `set-baud` all follow this flow automatically
(see the `save_reg` function in `src/servo.rs`).

> Why not just keep it unlocked all the time? EPROM has a limited erase/write endurance (about 100,000 cycles),
> and locking prevents a program bug from wearing out the servo with runaway writes.

### 4.3 Sign-magnitude encoding: negative numbers are not two's complement!

In the Feetech protocol, directional quantities (position, speed, current, load, position offset) are **not** represented
in the two's complement common in computing, but as "**sign bit + absolute value**":

- Most quantities: **BIT15 is the direction bit**, and the low 15 bits are the absolute value. For example, `-100` is encoded as `0x8000 | 100 = 0x8064`;
- Present load (address 60) is special: **BIT10 is the direction bit**, and the low 10 bits are the absolute value.

If you decode `0x8064` as two's complement, you get -32668 instead of -100, which is completely wrong.
This tool handles it uniformly in `decode_value`/`encode_value` in `src/registers.rs`;
each register's `sign_bit` field declares which bit it uses as the sign bit.

### 4.4 Operating mode (address 33)

| Value | Mode | Description |
|----|------|------|
| 0 | Position servo mode | Position closed loop + goal current force limit (force control capable) |
| 1 | Motor constant-speed mode | Speed closed loop; speed does not drop as load increases (for wheel drive) |
| 2 | Motor constant-current mode | Current closed loop, outputs constant torque |
| 3 | PWM open-loop speed control | Duty-cycle voltage control, no closed loop, speed varies with load |
| 4 | Pure position PD mode | Proportional-derivative position closed loop (Sim2Real, **factory default on this model**) |

### 4.5 Two sets of addresses for PID parameters

This is the most elegant part of the memory table design:

- **EPROM configuration area** (21/22/23 position loop P/D/I, 37/39 speed loop P/I, 34/35 current loop P/I):
  stores the "factory defaults", which are copied into the runtime area **at power-on**;
- **SRAM runtime area** (50 Kp / 51 Kd / 52 Ki): the values **actually in effect at runtime**; changes take effect immediately and are lost on power loss.

The right way to tune: first iterate in the runtime area with `pid position --kp 40 --ram`,
and once satisfied, write it to EPROM permanently with `pid position --kp 40 --save`.

Note that the "meaning of runtime addresses 50/51/52 changes with the mode": in position servo mode they are the position loop PID;
in constant-speed mode (mode 1) they become the speed loop PI (Kd has no effect).

### 4.6 Protection registers

- Address 13: maximum temperature limit (default 80°C; torque is turned off on overheat);
- Addresses 14/15: maximum/minimum input voltage (in 0.1V units);
- Address 28: protection current (in 6.5mA units) + address 38: overcurrent protection time (in 10ms units):
  if the current stays over the limit for this long, overcurrent protection kicks in (sending a new position command clears it);
- Address 19: unload condition / address 20: LED alarm condition: **bitmasks**,
  BIT0(1)=voltage BIT1(2)=magnetic encoder BIT2(4)=overheat BIT3(8)=overcurrent; set to 1 to enable.
  For example, enabling both voltage and overheat protection is `1+4=5`.

---

## 5. Project structure and layered design

```
FT-HD1901M_Servo/
├── Cargo.toml          # Project manifest: package name, version, third-party dependencies
├── src/
│   ├── main.rs         # Layer 4: command-line definition and dispatch (clap)
│   ├── servo.rs        # Layer 3: serial driver (opening the port, send/receive, timeout handling)
│   ├── protocol.rs     # Layer 2: protocol packet building/parsing (pure data, no hardware)
│   ├── registers.rs    # Layer 2: memory table definition (pure data, no hardware)
│   └── error.rs        # Used across all layers: unified error type
└── TUTORIAL.md         # This manual
```

**Why layering matters**: the bottom two layers (protocol, registers) are pure data transformations with no serial operations at all,
so they can be unit tested without hardware (`cargo test`). If all the code were mashed together,
testing the protocol logic would require actually connecting a servo. This is "separation of concerns".

Dependencies flow in one direction: `main.rs → servo.rs → protocol.rs / registers.rs`,
and `error.rs` is used by all layers. A lower layer never references a higher one.

---

## 6. Rust concepts explained

Concepts are explained in the order you encounter them in the source. Each one is annotated with its location in the source.

### 6.1 Cargo and the module system - `Cargo.toml`, the top of `src/main.rs`

- `Cargo.toml` declares dependencies, which are downloaded automatically from crates.io at build time and pinned in `Cargo.lock`;
- `mod error;` declares a module, and `use crate::error::Result;` brings a name from the module into scope;
- `crate::` means "start from the project root", similar to an absolute path.

### 6.2 Error handling: Result and `?` - `src/error.rs`

Rust has no exceptions. Functions that can fail return `Result<T, E>`:

```rust
// Traditional style (verbose)
let port = match serialport::new(path, baud).open() {
    Ok(p) => p,
    Err(e) => return Err(ServoError::Serial(e)),
};

// With the ? operator (equivalent, one line)
let port = serialport::new(path, baud).open()?;
```

The semantics of `?`: **on failure, convert the error type and return early; on success, unwrap the value and continue**.
The `#[from]` annotation (provided by thiserror) automatically converts `serialport::Error` into our own
`ServoError`, so a single `?` is enough.

**Why define a custom error enum?** The upper layers deal with only one error type, and a `match` can distinguish
"timeout" (maybe there is simply no servo with this ID, which is normal during a scan) from "checksum error" (something is wrong with the wiring).
See `ping()` in `servo.rs`.

### 6.3 Enums: Rust's "killer feature" - `src/error.rs`, `src/protocol.rs`

```rust
pub enum ServoError {
    Timeout,                        // No data
    Checksum,
    Malformed(&'static str),        // Carries one string
    ServoStatus(u8, String),        // Carries two pieces of data
}
```

Each variant can carry data of different types and in different amounts. Combined with `match`'s **exhaustiveness checking**
(missing a variant is a compile error), refactoring is very safe:

```rust
match self.transact(id, Instruction::Ping, &[], true) {
    Ok(_) => Ok(true),
    Err(ServoError::Timeout) => Ok(false),  // Timeout = no servo with this ID, not a failure
    Err(e) => Err(e),                        // Other errors keep propagating up
}
```

### 6.4 Option: eliminating null pointers - `find_register` in `src/registers.rs`

In Rust, "a lookup that may fail" returns `Option<&Register>` (`Some(x)` or `None`)
rather than null. The caller must explicitly handle the None case, and the compiler enforces it:

```rust
let reg = find_register(name).ok_or_else(|| {
    ServoError::InvalidParam(format!("未知寄存器 \"{name}\""))
})?;  // If not found, convert None into Err and return
```

"Optional arguments" on the command line (such as `goto --speed`) are also `Option<i64>`:
`Some(value)` if given, `None` if not, handled with `if let Some(s) = speed { ... }`.

### 6.5 Ownership and borrowing: a language-level guarantee of exclusive serial port access - `src/servo.rs`

Rust's core rules:

1. Every value has exactly one **owner**; when the owner goes out of scope, the value is freed automatically;
2. You can have any number of **immutable borrows** (`&T`) or **one** mutable borrow (`&mut T`), but not both;
3. A borrow cannot outlive its owner.

The serial port handle is **owned** by the `Servo` struct, and all operation methods require `&mut self`.
The compiler therefore guarantees that only one piece of code can operate the serial port at any moment.
**Bugs common in C, like "multiple threads writing to the serial port at once and interleaving packets", simply do not compile in Rust.**

### 6.6 Structs and impl - `src/servo.rs`

```rust
pub struct Servo {          // Data
    port: Box<dyn SerialPort>,
    discard_echo: bool,     // Private field (no pub); outside code cannot tamper with it
    verbose: bool,
}

impl Servo {                // Behavior (methods)
    pub fn connect(...) -> Result<Self> { ... }  // Associated function (like a static method/constructor)
    pub fn ping(&mut self, id: u8) -> Result<bool> { ... }  // &mut self = mutable borrow of itself
}
```

The three receiver kinds, `&self` (read-only borrow) / `&mut self` (mutable borrow) / `self` (takes ownership),
write "whether this method modifies the object" into the function signature, visible to the caller at a glance.

### 6.7 Traits and trait objects - `Box<dyn SerialPort>`

Traits are similar to interfaces in Java/Go. In the `serialport` library, the serial port is a different type on Linux/Windows/macOS,
but each implements the `SerialPort` trait. `Box<dyn SerialPort>` means
"a value on the heap that implements this trait", and we use it only through the methods the trait defines.
This makes the code cross-platform and independent of the concrete type.

### 6.8 Iterators and closures - scattered throughout

```rust
// protocol.rs: fold to sum (the closure |acc, &b| ... captures its environment)
let sum = bytes.iter().fold(0u8, |acc, &b| acc.wrapping_add(b));

// main.rs: map + collect turns a Vec<u8> into a Vec<String>, then join
let list: Vec<String> = found.iter().map(|id| id.to_string()).collect();

// main.rs: parse a comma-separated string into a Vec<u8>
let ids: Result<Vec<u8>, _> = ids.split(',').map(|s| s.trim().parse::<u8>()).collect();
```

Iterators are a **zero-cost abstraction**: after compilation they are equivalent to a hand-written for loop, with no runtime overhead.

### 6.9 derive macros and clap - `src/main.rs`

```rust
#[derive(Parser)]                    // Let clap implement argument parsing automatically
struct Cli {
    /// This doc comment line automatically becomes help text in --help!
    #[arg(short, long, default_value_t = 1)]
    id: u8,
}
```

`#[derive(...)]` is a "derive macro": the macro generates code automatically at compile time.
In this project, `Debug` (automatic debug printing), `Clone/Copy` (automatic copying),
`Error` (thiserror automatically implements the error trait), and `Parser/Subcommand/ValueEnum` (clap) are all derive macros.

### 6.10 Unit tests - `#[cfg(test)] mod tests` at the bottom of each file

```rust
#[cfg(test)]           // Compiled only for cargo test; not included in release builds
mod tests {
    use super::*;      // super = parent module
    #[test]
    fn test_build_ping_packet() {
        assert_eq!(build_packet(1, Instruction::Ping, &[]),
                   vec![0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB]);
    }
}
```

Just run `cargo test`. Tests for the pure logic layers (protocol, memory table) need no hardware.

### 6.11 Quick reference of handy idioms

| Idiom | Meaning | Where |
|------|------|------|
| `wrapping_add` | Addition that wraps on overflow (the checksum needs modulo 256) | protocol.rs |
| `u16::from_le_bytes([a, b])` | Combine two bytes into a u16, little-endian | servo.rs |
| `to_le_bytes()` | Split a u16 into a little-endian byte array | servo.rs |
| `Vec::with_capacity(n)` | Preallocate capacity to avoid repeated reallocation | protocol.rs |
| `format!` / `println!` with inline variable `{value}` | Rust 2021 string interpolation | Throughout |
| `.expect("...")` | Unwrap when you are sure it cannot fail; panics with a message on failure | servo.rs |
| `matches!(x, Err(...))` | Check whether a value matches a pattern | protocol.rs tests |
| `&[u8]` vs `Vec<u8>` | Borrowed slice vs owned array | Function parameter design |

---

## 7. Complete command reference

> By default, all write operations **only change RAM (restored after power loss)**; registers in the EPROM area persist across power loss only with `--save`
> (which automatically performs unlock → write → lock). This design protects EPROM lifetime.

### Queries

```bash
feetech-HD1910M-tester scan                          # Scan IDs 0~253 (with progress bar)
feetech-HD1910M-tester scan --from 1 --to 10         # Scan only part of the range
feetech-HD1910M-tester dump                          # Print the whole memory table (in 5 sections, with units and descriptions)
feetech-HD1910M-tester get pos-p                     # Read a single register (supports English names)
feetech-HD1910M-tester get 21                        # Also supports decimal addresses
feetech-HD1910M-tester get 0x15                      # And hexadecimal addresses
feetech-HD1910M-tester get status                    # Status byte automatically translated into Chinese
feetech-HD1910M-tester monitor                       # Real-time monitoring (Ctrl+C to stop)
feetech-HD1910M-tester monitor --interval 50 --count 100
```

### Generic write (covers all writable registers in the memory table)

```bash
feetech-HD1910M-tester set <register> <value>             # Write RAM (takes effect immediately, restored after power loss)
feetech-HD1910M-tester set <register> <value> --save      # Write EPROM, persisted across power loss
feetech-HD1910M-tester set <register> <value> --defer     # Asynchronous write (buffered)
feetech-HD1910M-tester action                        # Broadcast to trigger all buffered asynchronous writes
feetech-HD1910M-tester swrite 1,2,3 goal-pos 2048    # Sync write: same register on multiple servos
```

Examples: `set deadband-cw 3`, `set integral-limit 10 --save`, `set min-start-force 20`.

### ID / baud rate / lock / factory reset

```bash
feetech-HD1910M-tester set-id 2              # Change the ID from its current value to 2 (saved automatically; connect with -i 2 afterward)
feetech-HD1910M-tester set-baud 4            # Baud rate index 0~7 → here changed to 115200 (saved, takes effect after restart)
feetech-HD1910M-tester lock on               # Lock: EPROM writes do not persist across power loss (default state)
feetech-HD1910M-tester lock off              # Unlock: EPROM writes persist across power loss
feetech-HD1910M-tester factory-reset         # Restore factory settings (use with care! ID goes back to 1, baud rate back to 1M)
```

### Motion control

```bash
feetech-HD1910M-tester mode 0                        # Position servo mode (0~4, see section 4.4 for meanings)
feetech-HD1910M-tester goto 2048                     # Move to center (torque enabled automatically)
feetech-HD1910M-tester goto 1024 --speed 500 --acc 50
feetech-HD1910M-tester torque on / off / damp        # Torque on / release shaft / damping (for teaching by hand)
feetech-HD1910M-tester speed 1000                    # Running speed (in constant-speed mode, BIT15 sets the direction)
```

### Torque / force control

```bash
feetech-HD1910M-tester torque-limit 500      # Torque limit 50% (0~1000 = 0~100%)
feetech-HD1910M-tester goal-current 100      # Goal current ≈ 650mA (unit 6.5mA)
feetech-HD1910M-tester set max-torque 800 --save     # Max torque 80% (EPROM, copied to address 48 at power-on)
feetech-HD1910M-tester set protect-current 300 --save # Protection current ≈ 1.95A (EPROM)
feetech-HD1910M-tester set min-start-force 20 --save  # Minimum starting force 2%
```

### PID tuning (three loops)

```bash
feetech-HD1910M-tester pid position --kp 40 --kd 8            # Position loop, writes the EPROM configuration (effective this session)
feetech-HD1910M-tester pid position --kp 40 --kd 8 --ram      # Writes the runtime area, takes effect immediately (recommended for tuning)
feetech-HD1910M-tester pid position --kp 40 --kd 8 --save     # Writes EPROM, persisted across power loss (once tuned)
feetech-HD1910M-tester pid velocity --kp 60 --ki 20           # Speed loop (for constant-speed mode)
feetech-HD1910M-tester pid current --kp 200 --ki 50           # Current loop (the core of force control)
```

### Protection and limits

```bash
feetech-HD1910M-tester protect --max-temp 80                          # Overtemperature threshold 80°C
feetech-HD1910M-tester protect --min-voltage 40 --max-voltage 100     # Voltage window 4.0~10.0V
feetech-HD1910M-tester protect --overcur-time 200                     # Overcurrent lasting 2 seconds triggers protection
feetech-HD1910M-tester protect --unload 12 --led 12                   # Unload and flash the LED on overheat + overcurrent
feetech-HD1910M-tester limits 0 4095 --save                           # Angle limits (set 0 0 for multi-turn mode)
feetech-HD1910M-tester limits 90 270 --deg --save                     # Can also be entered as angles (0~360°)
feetech-HD1910M-tester offset -100 --save                             # Position offset (manual zero correction)
feetech-HD1910M-tester zero                                           # Zero calibration: calibrate the current position as center 2048
feetech-HD1910M-tester zero --to 1024                                 # Or calibrate to a specified reading (read back automatically to confirm)
```

---

## 8. Experiment tutorials (hands-on)

> Do them in order; each experiment has "things to observe". Adding `-v` throughout to see the packets is recommended.

### Experiment 1: Communication handshake and protocol observation

```bash
feetech-HD1910M-tester -v get pos
```

Things to observe: in the sent packet `FF FF 01 04 02 38 02 ...`, `02` is the READ instruction, `38` is start address 56,
and `02` means read 2 bytes; in the response packet you can find the little-endian bytes of the present position. Verify the checksum by hand.

### Experiment 2: Understanding the memory table

```bash
feetech-HD1910M-tester dump
feetech-HD1910M-tester get mode        # See the current operating mode (factory = 4, pure position PD)
feetech-HD1910M-tester get status      # Chinese interpretation of the status byte
```

### Experiment 3: Torque switch and teaching by hand

```bash
feetech-HD1910M-tester torque off      # Release the shaft and turn the servo by hand
feetech-HD1910M-tester monitor         # Watch in another terminal: position changes as you turn it, load ≈ 0
feetech-HD1910M-tester torque damp     # Damping mode: turn it by hand again, there is noticeable resistance
feetech-HD1910M-tester torque on       # Restore torque
```

### Experiment 3.5: Zero calibration (setting the current mechanical position as center)

After mechanical assembly, the zero position often does not line up with the servo's center 2048. In that case use zero calibration (equivalent to "set zero" in Feetech's FD software):

```bash
feetech-HD1910M-tester torque off      # 1. Release the shaft
# 2. Move the joint by hand to the zero position you want (do not wait in between; gravity will pull the joint off)
feetech-HD1910M-tester zero            # 3. Calibrate immediately: the current position is calibrated as 2048, persisted across power loss
feetech-HD1910M-tester torque on       # 4. Restore torque (after calibration the current reading is already 2048, so it will not jump)
```

Things to observe: the command automatically reads back "present position + position offset at address 31" to confirm the calibration took effect.
Note that HD-1910 (HLS-series firmware) **does not support** the old-style calibration method of "writing 128 to the torque switch" (the write returns success but has no effect);
you must use the 0x0B position calibration instruction that the `zero` command uses. Do not calibrate in multi-turn mode.

### Experiment 4: Position motion and feedback

```bash
feetech-HD1910M-tester monitor --count 100 &          # Monitor in the background (or open another terminal)
feetech-HD1910M-tester goto 1024 --speed 300
feetech-HD1910M-tester goto 3072 --speed 1000
```

Things to observe: the `moving` flag becomes 1 during motion; speed ramps up and then down (trapezoidal profile);
once in position, the position settles within ±1 of the target (the effect of the deadband).

### Experiment 5: PID tuning (runtime area, safe and reversible)

```bash
# Lower Kp → motion becomes softer and reaches position more slowly
feetech-HD1910M-tester pid position --kp 8 --ram
feetech-HD1910M-tester goto 1024

# Higher Kp → faster response but may jitter/hum
feetech-HD1910M-tester pid position --kp 80 --ram
feetech-HD1910M-tester goto 3072

# Restore the factory values (pos-p=32 as seen in dump), or power cycle to restore automatically
feetech-HD1910M-tester pid position --kp 32 --kd 40 --ram
```

### Experiment 6: Force control (goal current limit)

```bash
feetech-HD1910M-tester mode 0                 # Position servo mode (position + current limit)
feetech-HD1910M-tester goal-current 30        # Goal current ≈ 195mA, the servo becomes very weak
feetech-HD1910M-tester goto 2048
# Gently block the servo by hand: it cannot push past you, and the current is clamped at the set value (watch the current in monitor)
feetech-HD1910M-tester goal-current 500       # Restore (≈3.25A limit)
```

### Experiment 7: Protection features

```bash
feetech-HD1910M-tester protect --max-temp 40  # Lower the temperature threshold to 40°C
# Cover the servo with your hand or wait for it to heat up... above 40°C torque is turned off, and get status shows overheat
feetech-HD1910M-tester protect --max-temp 80  # Remember to set it back when you are done
```

### Experiment 8: Verifying the EPROM lock mechanism

```bash
feetech-HD1910M-tester set resp-level 1       # Without --save: changes RAM only
feetech-HD1910M-tester get lock               # Check the current lock state (default 1)
feetech-HD1910M-tester set min-angle 10       # Change a value
# Power cycle the servo, then dump again: min-angle is back to 0, because lock=1 means it was not saved
feetech-HD1910M-tester set min-angle 10 --save
# Power cycle again: this time the value stays
feetech-HD1910M-tester set min-angle 0 --save # Restore after the experiment
```

### Experiment 9: Changing the ID (the first step in networking multiple servos)

```bash
feetech-HD1910M-tester set-id 2               # The current servo becomes ID 2
feetech-HD1910M-tester -i 2 dump              # Connect using the new ID
feetech-HD1910M-tester -i 2 set-id 1          # Change it back (when practicing with a single servo)
```

### Experiment 10: Asynchronous and sync writes (multi-servo synchronization, needs 2 or more servos)

```bash
feetech-HD1910M-tester -i 1 set goal-pos 1024 --defer   # Buffered, does not move
feetech-HD1910M-tester -i 2 set goal-pos 3072 --defer   # Buffered, does not move
feetech-HD1910M-tester action                            # Broadcast: both start at the same time!
```

---

## 9. Safety precautions

1. **Stalling generates heat**: prolonged stall current can reach 1.6A, and the temperature rises quickly. During force-control experiments,
   limit the output with `torque-limit` or `goal-current`, and watch the temperature in monitor.
2. **EPROM lifetime**: about 100,000 erase/write cycles. During tuning always use `--ram` or omit `--save`,
   and save only once settled. Never use `--save` in a loop!
3. **Phase register (address 18)**: controls low-level configuration such as motor direction/encoder direction;
   changing it carelessly can make the servo spin out of control. Do not touch it unless you fully understand section 3.1 of the documentation.
4. **Before changing ID / baud rate**: make sure you can reconnect with the new parameters (write them down!).
   If you forget, recover with `factory-reset` or by scanning at each baud rate.
5. **Mechanical mounting**: during experiments, do not let the servo swing a load around in the air, to avoid hitting your hand or flinging parts off.

---

## 10. Troubleshooting common problems

| Symptom | What to check |
|------|------|
| `响应超时` (response timeout) | ① Is the servo powered? ② Is GND shared? ③ Is the baud rate right (default 1M; use `-b` if changed)? ④ Is the ID right (find it with `scan`)? ⑤ With TX/RX shorted wiring, add `--echo` |
| `串口错误: Permission denied` (serial port error) | Add your user to the dialout group: `sudo usermod -aG dialout $USER`, then log in again |
| `校验和错误` (checksum error) | Line interference/poor contact, check the jumper wires; or baud rate mismatch |
| scan finds nothing but the servo is definitely online | Lengthen the timeout with `-t 30`; try each baud rate: `-b 115200 scan`, etc. |
| Servo reports "过流" (overcurrent) | Sending a position command again clears it; long-term fix: lower protect-current or torque-limit |
| Configuration is gone after a restart | EPROM writes need `--save` (lock mechanism, see section 4.2) |
| Position reading is a strange large negative number | This no longer happens, but you should know why: sign-magnitude encoding mistaken for two's complement (see section 4.3) |

---

## Appendix: recommended learning path

1. First get experiments 1~4 working to build intuition for the protocol and the memory table;
2. Read through `src/protocol.rs` (the shortest, 200 lines) to understand packet building/parsing;
3. Read `src/registers.rs` to understand the approach of "turning a documentation table into code";
4. Read `src/servo.rs`, focusing on how `&mut self`, Result, and `?` chain together;
5. Read `src/main.rs` to see clap's declarative CLI and match-based dispatch;
6. Practice by modifying the code: add an "only show registers that differ from factory values" feature to `dump`;
   or add a `wave` subcommand that swings the servo sinusoidally and observe it with monitor.

Happy learning!
