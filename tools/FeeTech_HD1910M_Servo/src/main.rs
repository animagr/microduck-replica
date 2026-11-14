//! main.rs: command-line entry point: parses arguments and calls the servo driver to run tests
//!
//! [Rust concept: the binary target uses this package's library target]
//! This crate has both src/lib.rs (the library, named feetech_servo) and this file (the binary).
//! The binary references library modules via `use feetech_servo::...` just like an "external user";
//! the protocol layer, memory table and driver implementations all live in the library, and the CLI keeps only the command-line interaction logic.

use std::thread;
use std::time::Duration;

use clap::{Parser, Subcommand, ValueEnum};
use indicatif::{ProgressBar, ProgressStyle};

use feetech_servo::error::{Result, ServoError};
use feetech_servo::protocol;
use feetech_servo::registers::{self, find_register, Access, Area, REGISTERS, BAUD_RATES};
use feetech_servo::servo::Servo;

// =============================================================================
// Command-line definition
// =============================================================================

/// Top-level command line: global arguments + one subcommand.
///
/// global = true means these arguments can go before or after the subcommand,
/// e.g. both `feetech-HD1910M-tester dump -i 2` and `feetech-HD1910M-tester -i 2 dump` work.
#[derive(Parser)]
#[command(
    name = "feetech-HD1910M-tester",
    version,
    about = "飞特 HD1910M 串口舵机测试工具（FT-SCS 协议）",
    long_about = "覆盖官方内存表全部可读写寄存器的测试工具。\n\
                  出厂默认：ID=1，波特率=1000000，串口=/dev/ttyUSB0。\n\
                  寄存器可用英文名（如 pos-p）、十进制地址（21）或十六进制（0x15）指定。"
)]
struct Cli {
    /// Serial device path
    #[arg(short, long, default_value = "/dev/ttyUSB0", global = true)]
    port: String,

    /// Baud rate (factory default 1000000)
    #[arg(short, long, default_value_t = 1_000_000, global = true)]
    baud: u32,

    /// Servo ID (factory default 1)
    #[arg(short, long, default_value_t = 1, global = true)]
    id: u8,

    /// Serial send/receive timeout (ms). Lower it when scanning to go faster
    #[arg(short = 't', long, default_value_t = 50, global = true)]
    timeout: u64,

    /// Print raw packets sent and received (turn this on when learning the FT-SCS protocol)
    #[arg(short, long, global = true)]
    verbose: bool,

    /// Needed for the simple wiring with TX/RX shorted together: discard the echo of our own transmissions
    #[arg(long, global = true)]
    echo: bool,

    #[command(subcommand)]
    cmd: Cmd,
}

/// All subcommands.
///
/// [Rust concept: enums with data + Subcommand]
/// Each variant carries its own argument struct, and clap maps them to subcommands;
/// in run() below, a single match dispatches every command. Rust's match
/// checks "are all enum variants covered"; missing one fails compilation, which makes refactoring very safe.
#[derive(Subcommand)]
enum Cmd {
    /// Scan the bus: PING IDs 0~253 one by one and list the servos online
    Scan {
        /// Start ID
        #[arg(long, default_value_t = 0)]
        from: u8,
        /// End ID
        #[arg(long, default_value_t = 253)]
        to: u8,
    },

    /// Read and print the entire memory table (shown by section, with Chinese descriptions and units)
    Dump,

    /// Read one register: get pos-p / get 21 / get 0x15
    Get {
        /// Register: English name / decimal address / 0x hex address
        reg: String,
    },

    /// Write one register (by default only changes RAM; EPROM fields need --save to persist across power loss)
    Set {
        /// Register: English name / address
        reg: String,
        /// Value to write (negative is allowed too, e.g. pos-offset allows -4095)
        value: i64,
        /// Persist across power loss (unlock EPROM → write → lock again)
        #[arg(long)]
        save: bool,
        /// Asynchronous write: buffer first, then trigger together with the action command (for multi-servo sync)
        #[arg(long)]
        defer: bool,
    },

    /// Trigger execution of all buffered asynchronous writes (REG WRITE) (broadcast)
    Action,

    /// Synchronous write: one packet writes the same register on several servos (e.g. "1,2,3" goal-pos 2048)
    Swrite {
        /// Target ID list, comma separated
        ids: String,
        /// Register: English name / address
        reg: String,
        /// Value to write
        value: i64,
    },

    /// Set servo ID (automatically runs unlock → write → lock, persists across power loss)
    SetId {
        /// New ID (0~253)
        new_id: u8,
    },

    /// Set the baud rate (persists across power loss; after changing, reconnect at the new baud rate)
    SetBaud {
        /// Baud rate index 0~7: 0=1M 1=500k 2=250k 3=128k 4=115200 5=76800 6=57600 7=38400
        index: u8,
    },

    /// EPROM write lock: on=locked (not persisted across power loss, default) / off=unlocked (writes persist across power loss)
    Lock {
        #[arg(value_enum)]
        state: LockState,
    },

    /// Factory reset (restores all EPROM fields to defaults, use with care!)
    FactoryReset,

    /// Reboot the servo (0x08, equivalent to a power cycle: SRAM reloads from EPROM, can verify EPROM writes)
    Reboot,

    /// Set operating mode: 0 position servo, 1 motor constant speed, 2 motor constant current, 3 PWM open-loop speed control, 4 pure position PD
    Mode { mode: u8 },

    /// Position mode: rotate to target position (automatically turns on torque)
    Goto {
        /// Target position: 0~4095 maps to 0~360° (center 2048; may be negative or above 4095 in multi-turn mode)
        target: i64,
        /// Optional: also set running speed (0.732 RPM/unit)
        #[arg(long)]
        speed: Option<i64>,
        /// Optional: also set acceleration (8.7 deg/s² per unit, 0 = max)
        #[arg(long)]
        acc: Option<i64>,
    },

    /// Angle control: enter an angle and go straight to the corresponding position, 0° = center (2048), supports multi-servo sync
    Angle {
        /// Target angle (default unit: degrees; with --rad it's parsed as radians), range ±180°
        angle: f64,
        /// Input unit is radians (e.g. 0.1745 ≈ 10°)
        #[arg(long)]
        rad: bool,
        /// Target ID list, comma separated (default right leg 11,12)
        #[arg(long, default_value = "11,12")]
        ids: String,
        /// Optional: also set running speed (0.732 RPM/unit)
        #[arg(long)]
        speed: Option<i64>,
    },

    /// Right-leg oscillation test: several servos swing a small sine wave around center a few times, then return to center
    Swing {
        /// Target ID list, comma separated (default right leg 11,12)
        #[arg(long, default_value = "11,12")]
        ids: String,
        /// Swing amplitude (degrees, capped at 30° to avoid interference)
        #[arg(long, default_value_t = 10.0)]
        amplitude: f64,
        /// Number of full back-and-forth cycles
        #[arg(long, default_value_t = 3)]
        cycles: u32,
        /// Duration of each cycle (ms); larger is gentler
        #[arg(long, default_value_t = 2000)]
        period: u64,
        /// Optional: limit running speed (0.732 RPM/unit)
        #[arg(long)]
        speed: Option<i64>,
    },

    /// Torque switch: on = output enabled, off = output disabled (shaft free), damp = damping mode
    Torque {
        #[arg(value_enum)]
        state: TorqueState,
    },

    /// Set torque limit (address 48, 0~1000, unit 0.1%): limits stall torque output
    TorqueLimit { value: i64 },

    /// Set target current (address 44, -2047~2047, unit 6.5 mA): core of force control
    GoalCurrent { value: i64 },

    /// Set running speed (address 46; in constant-speed mode BIT15 is the direction bit)
    Speed { value: i64 },

    /// Set PID parameters: position loop / velocity loop / current loop
    Pid {
        /// Which loop: position (position loop PDI) velocity (velocity loop PI) current (current loop PI)
        #[arg(value_enum)]
        pid_loop: PidLoop,
        #[arg(long)]
        kp: Option<i64>,
        #[arg(long)]
        kd: Option<i64>,
        #[arg(long)]
        ki: Option<i64>,
        /// Write the runtime area (addresses 50~52, takes effect immediately, lost on power loss); by default writes the EPROM config area
        #[arg(long)]
        ram: bool,
        /// Persist across power loss when writing EPROM
        #[arg(long)]
        save: bool,
    },

    /// Live monitor: continuously print position/speed/load/voltage/temperature/current (Ctrl+C to stop)
    Monitor {
        /// Refresh interval (ms)
        #[arg(long, default_value_t = 100)]
        interval: u64,
        /// Number of prints (prints forever if not given)
        #[arg(long)]
        count: Option<u32>,
    },

    /// Protection parameters: over-temperature / over-voltage / under-voltage / over-current / unload conditions / LED alarm
    Protect {
        /// Max temperature limit °C (address 13)
        #[arg(long)]
        max_temp: Option<i64>,
        /// Max input voltage, unit 0.1 V (address 14, e.g. 100 = 10.0 V)
        #[arg(long)]
        max_voltage: Option<i64>,
        /// Min input voltage, unit 0.1 V (address 15, e.g. 40 = 4.0 V)
        #[arg(long)]
        min_voltage: Option<i64>,
        /// Over-current protection time, unit 10 ms (address 38, e.g. 200 = 2 s)
        #[arg(long)]
        overcur_time: Option<i64>,
        /// Unload condition bitmask (address 19): BIT0 voltage BIT1 magnetic encoder BIT2 overheat BIT3 over-current
        #[arg(long)]
        unload: Option<i64>,
        /// LED alarm bitmask (address 20): same bit definitions as above
        #[arg(long)]
        led: Option<i64>,
        /// Persist across power loss
        #[arg(long)]
        save: bool,
    },

    /// Set angle limits (addresses 9/11; add --save to persist across power loss; in multi-turn mode both should be 0)
    Limits {
        /// Min angle limit (default raw units 0~4094; with --deg input as degrees)
        min: f64,
        /// Max angle limit (default raw units 1~4095; with --deg input as degrees)
        max: f64,
        /// min/max input as angles (degrees): 0~360° maps to raw values 0~4095
        #[arg(long)]
        deg: bool,
        /// Persist across power loss (writes both registers in one unlock sequence)
        #[arg(long)]
        save: bool,
    },

    /// Zero calibration (0x0B instruction): calibrate the current mechanical position as center 2048, same as "Set zero" in Feetech's FD software
    ///
    /// Usage: torque off to free the shaft → move the joint to the zero position by hand → run this command immediately → torque on.
    /// The servo automatically updates the position offset register at address 31 and persists it; after calibration it is read back to confirm.
    Zero {
        /// Calibration target reading (default 2048 = center; range 0~4095). Only meaningful in single-turn position mode
        #[arg(long)]
        to: Option<i64>,
    },

    /// Set position offset (address 31, -4095~4095, manual zero correction; the zero command's automatic calibration is recommended)
    Offset {
        value: i64,
        /// Persist across power loss
        #[arg(long)]
        save: bool,
    },
}

/// Values for the lock switch (clap automatically restricts to on/off)
#[derive(Clone, Copy, ValueEnum)]
enum LockState {
    /// Locked: EPROM writes not persisted across power loss (factory default)
    On,
    /// Unlocked: EPROM writes persisted across power loss
    Off,
}

/// Values for the torque switch
#[derive(Clone, Copy, ValueEnum)]
enum TorqueState {
    /// Enable torque output
    On,
    /// Disable torque output (servo can be turned by hand)
    Off,
    /// Damped output (resists when turned by hand, commonly used for teaching by demonstration)
    Damp,
}

/// PID loop selection
#[derive(Clone, Copy, ValueEnum)]
enum PidLoop {
    /// Position loop: P=addr 21 D=addr 22 I=addr 23 (runtime area 50/51/52)
    Position,
    /// Velocity loop: P=addr 37 I=addr 39 (runtime area 50/52)
    Velocity,
    /// Current loop: P=addr 34 I=addr 35 (EPROM area only)
    Current,
}

// =============================================================================
// Program entry point
// =============================================================================

/// [Rust concept: fn main() -> Result]
/// main can also return Result: when it returns Err, the program exits with a non-zero status and prints the error,
/// so `?` can be used happily in main too.
fn main() -> Result<()> {
    let cli = Cli::parse();

    // The scan command doesn't need to connect to a specific servo first, but it still needs the serial port
    let mut servo = Servo::connect(&cli.port, cli.baud, cli.timeout, cli.echo, cli.verbose)?;
    if cli.verbose {
        eprintln!("已打开 {} @ {} bps, 目标 ID = {}", cli.port, cli.baud, cli.id);
    }

    // [Rust concept: match exhaustiveness checking]
    // The compiler forces us to handle every variant of Cmd; forgetting to handle a new subcommand fails compilation.
    match cli.cmd {
        Cmd::Scan { from, to } => cmd_scan(&mut servo, from, to),
        Cmd::Dump => cmd_dump(&mut servo, cli.id),
        Cmd::Get { reg } => cmd_get(&mut servo, cli.id, &reg),
        Cmd::Set { reg, value, save, defer } => cmd_set(&mut servo, cli.id, &reg, value, save, defer),
        Cmd::Action => {
            servo.action()?;
            println!("已广播 ACTION，所有缓存的异步写已触发执行");
            Ok(())
        }
        Cmd::Swrite { ids, reg, value } => {
            let reg = find_register(&reg).ok_or_else(|| {
                ServoError::InvalidParam(format!("未知寄存器 \"{reg}\""))
            })?;
            // Parse the comma-separated ID list: "1,2,3" → vec![1, 2, 3]
            let ids: std::result::Result<Vec<u8>, _> =
                ids.split(',').map(|s| s.trim().parse::<u8>()).collect();
            let ids = ids.map_err(|_| ServoError::InvalidParam("ID 列表格式应为 1,2,3".into()))?;
            servo.sync_write(&ids, reg, value)?;
            println!("已同步写 {:?} 的 {}（{}）= {value}", ids, reg.key, reg.cn);
            Ok(())
        }
        Cmd::SetId { new_id } => cmd_set_id(&mut servo, cli.id, new_id),
        Cmd::SetBaud { index } => cmd_set_baud(&mut servo, cli.id, index),
        Cmd::Lock { state } => {
            let v = match state {
                LockState::On => 1,
                LockState::Off => 0,
            };
            servo.write_reg(cli.id, find_register("lock").unwrap(), v)?;
            println!("锁标志已写为 {v}（{}）", if v == 0 { "已解锁：EPROM 写入将掉电保存" } else { "已上锁：EPROM 写入掉电不保存" });
            Ok(())
        }
        Cmd::FactoryReset => {
            servo.factory_reset(cli.id)?;
            println!("已发送恢复出厂设置指令，请重新上电舵机（ID 恢复为 1，波特率恢复为 1Mbps）");
            Ok(())
        }
        Cmd::Reboot => {
            // Some firmware doesn't reply before rebooting; a timeout doesn't count as failure
            match servo.reboot(cli.id) {
                Ok(()) => println!("已发送重启指令并收到应答"),
                Err(ServoError::Timeout) => println!("已发送重启指令（舵机未应答，可能已直接重启）"),
                Err(e) => return Err(e),
            }
            println!("请等待约 1 秒让舵机完成重启再进行通信");
            Ok(())
        }
        Cmd::Mode { mode } => {
            let reg = find_register("mode").unwrap();
            servo.write_reg(cli.id, reg, mode as i64)?;
            const MODES: [&str; 5] = [
                "0:位置伺服模式（位置+限流）",
                "1:电机恒速模式（恒速+限流）",
                "2:电机恒流模式（限流）",
                "3:PWM开环调速模式",
                "4:纯位置PD模式（Sim2Real，出厂默认）",
            ];
            println!("运行模式已设为 {mode} = {}", MODES[mode as usize]);
            println!("提示：模式存在 EPROM，加 --verbose 可观察报文；如需掉电保存请用 set mode {mode} --save");
            Ok(())
        }
        Cmd::Goto { target, speed, acc } => cmd_goto(&mut servo, cli.id, target, speed, acc),
        Cmd::Angle { angle, rad, ids, speed } => {
            cmd_angle(&mut servo, &ids, angle, rad, speed)
        }
        Cmd::Swing { ids, amplitude, cycles, period, speed } => {
            cmd_swing(&mut servo, &ids, amplitude, cycles, period, speed)
        }
        Cmd::Torque { state } => {
            let v = match state {
                TorqueState::On => 1,
                TorqueState::Off => 0,
                TorqueState::Damp => 2,
            };
            servo.write_reg(cli.id, find_register("torque-switch").unwrap(), v)?;
            let desc = match state {
                TorqueState::On => "已打开扭力输出",
                TorqueState::Off => "已关闭扭力输出（舵机松轴，可手动转动）",
                TorqueState::Damp => "已切到阻尼输出（手动转动有阻力，可用于示教）",
            };
            println!("{desc}");
            Ok(())
        }
        Cmd::TorqueLimit { value } => {
            servo.write_reg(cli.id, find_register("torque-limit").unwrap(), value)?;
            println!("转矩限制已设为 {value}（= {:.1}%）", value as f64 / 10.0);
            Ok(())
        }
        Cmd::GoalCurrent { value } => {
            servo.write_reg(cli.id, find_register("goal-current").unwrap(), value)?;
            println!("目标电流已设为 {value}（≈ {:.0} mA）", value as f64 * 6.5);
            Ok(())
        }
        Cmd::Speed { value } => {
            servo.write_reg(cli.id, find_register("speed").unwrap(), value)?;
            println!("运行速度已设为 {value}（≈ {:.1} RPM）", value as f64 * 0.732);
            Ok(())
        }
        Cmd::Pid { pid_loop, kp, kd, ki, ram, save } => {
            cmd_pid(&mut servo, cli.id, pid_loop, kp, kd, ki, ram, save)
        }
        Cmd::Monitor { interval, count } => cmd_monitor(&mut servo, cli.id, interval, count),
        Cmd::Protect { max_temp, max_voltage, min_voltage, overcur_time, unload, led, save } => cmd_protect(
            &mut servo, cli.id, max_temp, max_voltage, min_voltage, overcur_time, unload, led, save,
        ),
        Cmd::Limits { min, max, deg, save } => cmd_limits(&mut servo, cli.id, min, max, deg, save),
        Cmd::Zero { to } => cmd_zero(&mut servo, cli.id, to),
        Cmd::Offset { value, save } => {
            cmd_write_eprom(&mut servo, cli.id, "pos-offset", value, save)?;
            println!("位置偏移已设为 {value}{}", if save { "（已掉电保存）" } else { "" });
            Ok(())
        }
    }
}

// =============================================================================
// Implementations of each subcommand
// =============================================================================

/// Scan the bus (with a progress bar)
///
/// [Rust concept: using the third-party crate indicatif]
/// After adding one dependency line to Cargo.toml, just `use indicatif::...`.
/// ProgressBar refreshes a progress bar line in the terminal in real time:
///   - ProgressStyle::with_template defines the display template (placeholders like {bar} {pos} {msg})
///   - progress_chars customizes the bar's fill characters (Unicode block characters look finer)
///   - enable_steady_tick keeps the spinner animating while waiting
///   - pb.println prints a line above the progress bar without garbling it
fn cmd_scan(servo: &mut Servo, from: u8, to: u8) -> Result<()> {
    let total = (to - from + 1) as u64;
    let pb = ProgressBar::new(total);
    pb.set_style(
        ProgressStyle::with_template(
            "{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({percent}%) {msg}",
        )
        .unwrap() // the template is a correct string hard-coded at compile time, so unwrap is safe here
        .progress_chars("█▉▊▋▌▍▎▏  "),
    );
    // Advance the spinner every 100 ms, otherwise the screen is frozen while waiting for timeouts
    pb.enable_steady_tick(Duration::from_millis(100));

    let mut found = Vec::new();
    for id in from..=to {
        pb.set_message(format!("PING ID {id}"));
        if servo.ping(id)? {
            found.push(id);
            pb.println(format!("  ✔ 发现舵机，ID = {id}"));
        }
        pb.inc(1); // progress +1
    }

    // Finish the progress bar: clear it, then print the final result
    pb.finish_and_clear();
    if found.is_empty() {
        println!("扫描完成（ID {from} ~ {to}）：没有发现任何舵机。请检查：接线 / 供电 / 波特率（-b）/ 串口（-p）");
    } else {
        // [Rust concept: iterator map + collect to build a string]
        let list: Vec<String> = found.iter().map(|id| id.to_string()).collect();
        println!("扫描完成：发现 {} 个舵机，ID: {}", found.len(), list.join(", "));
    }
    Ok(())
}

/// Read and print the entire memory table.
///
/// [Performance tip: block reads] the memory table has gaps at some addresses (e.g. 10, 12, 29);
/// reading register by register sends dozens of instructions; instead read 5 large contiguous blocks by region,
/// then take values from the buffer by address, which is much faster.
fn cmd_dump(servo: &mut Servo, id: u8) -> Result<()> {
    // (start address, read length): covers 0~4, 5~39, 40~55, 56~75, 77~86
    let blocks = [(0u8, 5u8), (5, 35), (40, 16), (56, 20), (77, 10)];
    let mut image = [0u8; 128]; // memory table image, index = address
    for (start, len) in blocks {
        let data = servo.read(id, start, len)?;
        if data.len() < len as usize {
            return Err(ServoError::Malformed("块读取长度不足".into()));
        }
        // Copy into the image buffer
        image[start as usize..(start + len) as usize].copy_from_slice(&data[..len as usize]);
    }

    println!("====== HD1910M 内存表（ID={id}）======");
    let mut last_area: Option<Area> = None;
    for reg in REGISTERS {
        // Print the section title when the section changes
        if last_area != Some(reg.area) {
            println!("\n----- {} -----", reg.area.as_str());
            last_area = Some(reg.area);
        }
        let raw = if reg.size == 1 {
            image[reg.addr as usize] as u16
        } else {
            u16::from_le_bytes([image[reg.addr as usize], image[reg.addr as usize + 1]])
        };
        let val = registers::decode_value(raw, reg.sign_bit);
        println!(
            "  [{:>2}/0x{:02X}] {:<12} {:<10} = {:>6} {:<8} [{}] {}",
            reg.addr, reg.addr, reg.key, reg.cn, val, reg.unit,
            reg.access.as_str(), reg.desc
        );
    }
    Ok(())
}

/// Read one register and print it nicely
fn cmd_get(servo: &mut Servo, id: u8, name: &str) -> Result<()> {
    let reg = find_register(name).ok_or_else(|| {
        ServoError::InvalidParam(format!("未知寄存器 \"{name}\"，用 dump 命令查看全部寄存器名"))
    })?;
    let val = servo.read_reg(id, reg)?;
    println!(
        "[{}/0x{:02X}] {}（{}）= {} {}",
        reg.addr, reg.addr, reg.key, reg.cn, val, reg.unit
    );
    // For bitmask registers, add a bit-by-bit explanation to help understanding
    match reg.key {
        "status" => println!("  状态解析: {}", protocol::describe_status(val as u8)),
        "unload-cond" | "led-alarm" => println!("  位含义: {}", describe_protect_bits(val as u8)),
        _ => {}
    }
    Ok(())
}

/// Write one register
fn cmd_set(servo: &mut Servo, id: u8, name: &str, value: i64, save: bool, defer: bool) -> Result<()> {
    let reg = find_register(name).ok_or_else(|| {
        ServoError::InvalidParam(format!("未知寄存器 \"{name}\"，用 dump 命令查看全部寄存器名"))
    })?;
    if reg.access == Access::ReadOnly {
        return Err(ServoError::InvalidParam(format!(
            "{}（{}）是只读寄存器，不能写入", reg.key, reg.cn
        )));
    }
    if defer {
        // Asynchronous write: do the same range check before writing (previously missing; out-of-range values were encoded and sent as is)
        reg.check_value(value)?;
        let val = registers::encode_value(value, reg.sign_bit);
        let bytes = if reg.size == 1 { vec![val as u8] } else { val.to_le_bytes().to_vec() };
        servo.reg_write(id, reg.addr, &bytes)?;
        println!("已缓存异步写 {}（{}）= {value}，执行 action 命令后生效", reg.key, reg.cn);
        return Ok(());
    }
    if save {
        servo.save_reg(id, reg, value)?;
        println!("{}（{}）= {value}（已写入 EPROM，掉电保存）", reg.key, reg.cn);
    } else {
        servo.write_reg(id, reg, value)?;
        let tip = if reg.area == Area::Eprom { "（仅本次有效，掉电恢复；加 --save 可保存）" } else { "" };
        println!("{}（{}）= {value}{tip}", reg.key, reg.cn);
    }
    Ok(())
}

/// Helper for writing EPROM registers (used by the offset command)
fn cmd_write_eprom(servo: &mut Servo, id: u8, key: &str, value: i64, save: bool) -> Result<()> {
    let reg = find_register(key).unwrap();
    if save {
        servo.save_reg(id, reg, value)
    } else {
        servo.write_reg(id, reg, value)
    }
}

/// Set the active range (angle limits): address 9 min angle + address 11 max angle.
///
/// Corresponds to the angle limits in Feetech's FD software; supports input as raw values or angles (--deg).
/// With --save, shares one unlock/lock sequence (half the EPROM round trips of calling save_reg for each),
/// and reads back to confirm after writing: Feetech may reply "success" even for unsupported/ineffective writes, so the read-back is authoritative.
fn cmd_limits(servo: &mut Servo, id: u8, min: f64, max: f64, deg: bool, save: bool) -> Result<()> {
    // Angle (degrees) → raw position value; raw input is rounded directly
    let (min, max) = if deg {
        ((min / DEG_PER_COUNT).round() as i64, (max / DEG_PER_COUNT).round() as i64)
    } else {
        (min as i64, max as i64)
    };

    // Range check. Note: multi-turn mode requires both to be 0, while max-angle's nominal lower bound is 1,
    // so the 0/0 combination is special-cased and allowed (the official doc says: "this value is 0 for multi-turn absolute position control")
    let multico = min == 0 && max == 0;
    if !(0..=4094).contains(&min) {
        return Err(ServoError::InvalidParam(format!("最小角度限制 {min} 超出 0~4094")));
    }
    if !multico && !(1..=4095).contains(&max) {
        return Err(ServoError::InvalidParam(format!("最大角度限制 {max} 超出 1~4095")));
    }
    if !multico && min >= max {
        return Err(ServoError::InvalidParam(format!(
            "最小角度限制 {min} 必须小于最大角度限制 {max}（多圈模式请设 0 0）"
        )));
    }

    let min_reg = find_register("min-angle").unwrap();
    let max_reg = find_register("max-angle").unwrap();
    if save {
        // Write two registers in one unlock sequence; whichever step fails, make sure to lock again
        let lock = find_register("lock").unwrap();
        servo.write_reg(id, lock, 0)?;
        let r1 = servo.write_reg(id, min_reg, min);
        let r2 = servo.write_reg(id, max_reg, max);
        let relock = servo.write_reg(id, lock, 1);
        r1.and(r2).and(relock)?;
    } else {
        servo.write_reg(id, min_reg, min)?;
        servo.write_reg(id, max_reg, max)?;
    }

    // Read back to confirm
    let rb_min = servo.read_reg(id, min_reg)?;
    let rb_max = servo.read_reg(id, max_reg)?;
    println!(
        "角度限制回读 = {rb_min} ~ {rb_max}（约 {:.1}° ~ {:.1}°）{}",
        rb_min as f64 * DEG_PER_COUNT,
        rb_max as f64 * DEG_PER_COUNT,
        if save { "，已掉电保存" } else { "（仅本次有效，加 --save 可掉电保存）" }
    );
    Ok(())
}

/// Zero calibration (0x0B instruction): calibrate the current mechanical position as target (default center 2048).
///
/// [Key points] unlock EPROM before calibrating so the offset write persists across power loss;
/// after calibration, double-check by reading back "current position + position offset" (Feetech's "success" reply can't be trusted;
/// in hardware tests the HD-1910 also replied success to an unsupported write-128 calibration).
fn cmd_zero(servo: &mut Servo, id: u8, to: Option<i64>) -> Result<()> {
    let target = to.unwrap_or(CENTER_POS);
    if !(0..=4095).contains(&target) {
        return Err(ServoError::InvalidParam(format!(
            "校准目标 {target} 超出 0~4095（仅单圈位置模式有意义）"
        )));
    }

    // Read once before calibrating so the user sees "what this position used to read"
    let before = servo.read_reg(id, find_register("pos").unwrap())?;
    println!(
        "校准前：当前位置 = {before}（相对中位 {:+.1}°），将标定为 {target}",
        (before - CENTER_POS) as f64 * DEG_PER_COUNT
    );

    // Unlock → calibrate → lock: ensures the position offset at address 31 is written to EPROM and persists across power loss
    let lock = find_register("lock").unwrap();
    servo.write_reg(id, lock, 0)?;
    let result = servo.calibrate(id, Some(target as u16));
    let relock = servo.write_reg(id, lock, 1);
    result.and(relock)?;

    // The servo needs a moment to compute and write the offset internally
    thread::sleep(Duration::from_millis(100));

    // Read back to confirm: position should become target, and the offset register should have been updated by the servo
    let after = servo.read_reg(id, find_register("pos").unwrap())?;
    let offset = servo.read_reg(id, find_register("pos-offset").unwrap())?;
    println!("校准后：当前位置 = {after}，位置偏移(31号) = {offset}（已掉电保存）");
    if (after - target).abs() > 4 {
        return Err(ServoError::Malformed(format!(
            "校准疑似未生效：回读位置 {after} 与目标 {target} 偏差超过 4 个单位，\
             请用 -v 重试并检查固件是否支持 0x0B 指令"
        )));
    }
    println!("零位校准完成：现在的机械位置就是读数 {target}（相对中位 {:+.1}°）",
        (target - CENTER_POS) as f64 * DEG_PER_COUNT);
    println!("提示：若刚才 torque off 用手摆的位，请先 goto {target} 再 torque on，避免关节被拉回旧零位");
    Ok(())
}

/// Set servo ID: the most important configuration operation, must persist across power loss
///
/// [Common pitfall] once the ID register write succeeds, the servo **immediately** replies on the new ID,
/// so the final "lock again" step must be sent to the new ID: if it's still sent to the old ID,
/// you get a timeout error (the ID actually changed successfully; it's a false alarm).
fn cmd_set_id(servo: &mut Servo, old_id: u8, new_id: u8) -> Result<()> {
    if new_id > 253 {
        return Err(ServoError::InvalidParam("ID 必须在 0~253 之间".into()));
    }
    if new_id == old_id {
        println!("新 ID 与当前 ID 相同（{old_id}），无需修改");
        return Ok(());
    }
    println!("正在把舵机 ID 从 {old_id} 改为 {new_id}（解锁 → 写入 → 上锁）...");
    let lock = find_register("lock").unwrap();
    let id_reg = find_register("id").unwrap();

    // 1) Unlock: make EPROM writes persist across power loss (sent to the old ID)
    servo.write_reg(old_id, lock, 0)?;
    // 2) Write the new ID (sent to the old ID; as soon as the reply arrives, the servo only answers to the new ID)
    servo.write_reg(old_id, id_reg, new_id as i64)?;
    // 3) Lock again: must be sent to the **new ID**
    servo.write_reg(new_id, lock, 1)?;

    println!("完成！以后请用 -i {new_id} 连接该舵机。例如：feetech-HD1910M-tester -i {new_id} dump");
    println!("注意：如果总线上还有其他 ID={new_id} 的舵机会冲突，请先单独连接再改。");
    Ok(())
}

/// Set the baud rate
fn cmd_set_baud(servo: &mut Servo, id: u8, index: u8) -> Result<()> {
    if index > 7 {
        return Err(ServoError::InvalidParam("波特率索引必须在 0~7 之间".into()));
    }
    let baud = BAUD_RATES[index as usize];
    let reg = find_register("baud").unwrap();
    servo.save_reg(id, reg, index as i64)?;
    println!("波特率已设为索引 {index}（{baud} bps）并掉电保存。");
    println!("舵机重新上电后生效，之后请用 -b {baud} 连接。");
    Ok(())
}

/// Position mode motion
fn cmd_goto(servo: &mut Servo, id: u8, target: i64, speed: Option<i64>, acc: Option<i64>) -> Result<()> {
    // Optional arguments: Option<i64>; written only if given, otherwise the servo's existing configuration is left alone
    if let Some(a) = acc {
        servo.write_reg(id, find_register("acc").unwrap(), a)?;
    }
    if let Some(s) = speed {
        servo.write_reg(id, find_register("speed").unwrap(), s)?;
    }
    // Turn on torque, otherwise the servo won't hold position
    servo.write_reg(id, find_register("torque-switch").unwrap(), 1)?;
    servo.write_reg(id, find_register("goal-pos").unwrap(), target)?;
    let deg = target as f64 * 0.0879; // 0.087 deg/unit (documented nominal value, 360°/4096≈0.0879)
    println!("目标位置 = {target}（约 {deg:.1}°），舵机运动中... 可用 monitor 命令观察");
    Ok(())
}

// =============================================================================
// Right-leg test (angle / oscillation): center 2048 is 0°, controlled by angle rather than raw position value
// =============================================================================

/// Raw value for the center position (0~4095 maps to 0~360°)
const CENTER_POS: i64 = 2048;
/// Angle (degrees) per position unit: 360° / 4096
const DEG_PER_COUNT: f64 = 360.0 / 4096.0;
/// Max amplitude (degrees) allowed for the oscillation test. The right leg's structural parts are tightly packed; too large an amplitude causes interference
const MAX_SWING_AMPLITUDE_DEG: f64 = 30.0;

/// Angle (degrees, relative to center) → raw servo position value
fn deg_to_pos(deg: f64) -> i64 {
    CENTER_POS + (deg / DEG_PER_COUNT).round() as i64
}

/// Parse a comma-separated ID list: "11,12" → vec![11, 12]
fn parse_ids(ids: &str) -> Result<Vec<u8>> {
    let ids: std::result::Result<Vec<u8>, _> =
        ids.split(',').map(|s| s.trim().parse::<u8>()).collect();
    ids.map_err(|_| ServoError::InvalidParam("ID 列表格式应为 11,12".into()))
}

/// Angle control: the servo turns to however many degrees (or radians) you enter, relative to center.
/// Multiple IDs are sent together in one SYNC WRITE packet, so both servos move in unison.
fn cmd_angle(servo: &mut Servo, ids: &str, angle: f64, rad: bool, speed: Option<i64>) -> Result<()> {
    let ids = parse_ids(ids)?;
    // Convert everything to degrees: radians × 180/π
    let deg = if rad { angle.to_degrees() } else { angle };
    // In single-turn position mode only ±180° targets are well defined; anything beyond is rejected
    if !(-180.0..=180.0).contains(&deg) {
        return Err(ServoError::InvalidParam(format!(
            "角度 {deg}° 超出 ±180° 范围（相对中位）"
        )));
    }
    let target = deg_to_pos(deg);
    // Turn on torque + optional speed limit + send target positions synchronously
    servo.sync_write(&ids, find_register("torque-switch").unwrap(), 1)?;
    if let Some(s) = speed {
        servo.sync_write(&ids, find_register("speed").unwrap(), s)?;
    }
    servo.sync_write(&ids, find_register("goal-pos").unwrap(), target)?;
    println!(
        "目标角度 = {:.2}°（原始位置 {target}，中位 {CENTER_POS}），已同步下发到 {:?}",
        deg, ids
    );
    Ok(())
}

/// Oscillation test: smooth sine swing around center, small amplitude and slow, to avoid leg structure interference.
///
/// [Approach] split each cycle into small steps (50 ms each);
/// at each step compute the target as pos = center + amplitude × sin(phase) and send it with a sync write,
/// so both servos follow the same smooth curve, moving in unison and gently.
fn cmd_swing(
    servo: &mut Servo,
    ids: &str,
    amplitude: f64,
    cycles: u32,
    period: u64,
    speed: Option<i64>,
) -> Result<()> {
    let ids = parse_ids(ids)?;
    if amplitude <= 0.0 || amplitude > MAX_SWING_AMPLITUDE_DEG {
        return Err(ServoError::InvalidParam(format!(
            "幅度必须在 0 ~ {MAX_SWING_AMPLITUDE_DEG}° 之间（保护腿部结构，避免干涉）"
        )));
    }
    if period < 400 {
        return Err(ServoError::InvalidParam("周期太短（<400ms）动作会太急，请加大 --period".into()));
    }

    let goal_pos = find_register("goal-pos").unwrap();
    // Turn on torque, optional speed limit (lower speed = gentler)
    servo.sync_write(&ids, find_register("torque-switch").unwrap(), 1)?;
    if let Some(s) = speed {
        servo.sync_write(&ids, find_register("speed").unwrap(), s)?;
    }

    // Return to center first, wait until settled, then start
    println!("回到中位 {CENTER_POS}（0°）...");
    servo.sync_write(&ids, goal_pos, CENTER_POS)?;
    thread::sleep(Duration::from_millis(800));

    println!(
        "开始振荡：幅度 ±{amplitude}°，{cycles} 次，每周期 {period}ms（Ctrl+C 可随时中止）"
    );
    const STEP_MS: u64 = 50; // 50 ms per step, enough to draw a smooth sine
    let steps_per_cycle = (period / STEP_MS).max(1);
    for cycle in 1..=cycles {
        for step in 0..steps_per_cycle {
            // Phase goes from 0 to 2π, exactly one full cycle
            let phase = 2.0 * std::f64::consts::PI * step as f64 / steps_per_cycle as f64;
            let target = deg_to_pos(amplitude * phase.sin());
            servo.sync_write(&ids, goal_pos, target)?;
            thread::sleep(Duration::from_millis(STEP_MS));
        }
        println!("  第 {cycle}/{cycles} 次完成");
    }

    // Finish: return to center and read back the actual position for easy checking
    servo.sync_write(&ids, goal_pos, CENTER_POS)?;
    thread::sleep(Duration::from_millis(500));
    println!("振荡结束，已回中位。实际反馈：");
    for &id in &ids {
        let fb = servo.read_feedback(id)?;
        let deg = (fb.pos - CENTER_POS) as f64 * DEG_PER_COUNT;
        println!("  ID {id}: 位置 {}（相对中位 {deg:+.2}°），电压 {:.1}V，温度 {}°C", fb.pos, fb.voltage, fb.temp);
    }
    Ok(())
}

/// Set PID: choose which registers to write based on the "loop"
fn cmd_pid(
    servo: &mut Servo,
    id: u8,
    pid_loop: PidLoop,
    kp: Option<i64>,
    kd: Option<i64>,
    ki: Option<i64>,
    ram: bool,
    save: bool,
) -> Result<()> {
    // Determine register key names from the loop and the target area
    // (doc: addresses 50/51/52 in the runtime area are the position-loop PID in position mode, and the velocity-loop PI in constant-speed mode)
    let (k_p, k_d, k_i): (&str, Option<&str>, Option<&str>) = match (pid_loop, ram) {
        (PidLoop::Position, false) => ("pos-p", Some("pos-d"), Some("pos-i")),
        (PidLoop::Position, true) => ("kp", Some("kd"), Some("ki")),
        (PidLoop::Velocity, false) => ("vel-p", None, Some("vel-i")),
        (PidLoop::Velocity, true) => ("kp", None, Some("ki")),
        (PidLoop::Current, false) => ("cur-p", None, Some("cur-i")),
        (PidLoop::Current, true) => {
            return Err(ServoError::InvalidParam("电流环没有运行区映射，请去掉 --ram".into()))
        }
    };

    // Pair up (parameter value, register key name) and write them one by one
    let pairs: [(Option<i64>, &str); 3] = [
        (kp, k_p),
        (kd, k_d.unwrap_or("")),
        (ki, k_i.unwrap_or("")),
    ];
    let mut wrote_any = false;
    for (value, key) in pairs {
        if let (Some(v), false) = (value, key.is_empty()) {
            let reg = find_register(key).unwrap();
            if save { servo.save_reg(id, reg, v)?; } else { servo.write_reg(id, reg, v)?; }
            println!("  {}（{}）= {v}", reg.key, reg.cn);
            wrote_any = true;
        }
    }
    if !wrote_any {
        return Err(ServoError::InvalidParam(
            "至少给一个参数，如：pid position --kp 40 --kd 8".into(),
        ));
    }
    match (ram, save) {
        (true, _) => println!("已写入运行区（立即生效，掉电丢失）—— 适合调参时反复试"),
        (false, true) => println!("已写入 EPROM 并掉电保存"),
        (false, false) => println!("已写入 EPROM 配置（本次有效；调好后加 --save 保存）"),
    }
    Ok(())
}

/// Live feedback monitor
fn cmd_monitor(servo: &mut Servo, id: u8, interval: u64, count: Option<u32>) -> Result<()> {
    println!("位置      速度      负载%    电压V   温度°C  电流mA   移动  状态");
    let mut n = 0u32;
    loop {
        let fb = servo.read_feedback(id)?;
        println!(
            "{:<9} {:<9} {:<8.1} {:<7.1} {:<7} {:<8.0} {:<5} {}",
            fb.pos, fb.vel, fb.load as f64 / 10.0, fb.voltage, fb.temp,
            fb.current, fb.moving, protocol::describe_status(fb.status),
        );
        n += 1;
        // [Rust concept: pattern matching on Option]
        // count is Option<u32>: Some(n) means the user specified a count
        if let Some(max) = count {
            if n >= max {
                break;
            }
        }
        thread::sleep(Duration::from_millis(interval));
    }
    Ok(())
}

/// Protection parameter settings
#[allow(clippy::too_many_arguments)]
fn cmd_protect(
    servo: &mut Servo,
    id: u8,
    max_temp: Option<i64>,
    max_voltage: Option<i64>,
    min_voltage: Option<i64>,
    overcur_time: Option<i64>,
    unload: Option<i64>,
    led: Option<i64>,
    save: bool,
) -> Result<()> {
    let pairs: [(Option<i64>, &str); 6] = [
        (max_temp, "max-temp"),
        (max_voltage, "max-voltage"),
        (min_voltage, "min-voltage"),
        (overcur_time, "overcur-time"),
        (unload, "unload-cond"),
        (led, "led-alarm"),
    ];
    let mut wrote_any = false;
    for (value, key) in pairs {
        if let Some(v) = value {
            let reg = find_register(key).unwrap();
            if save { servo.save_reg(id, reg, v)?; } else { servo.write_reg(id, reg, v)?; }
            println!("  {}（{}）= {v}", reg.key, reg.cn);
            wrote_any = true;
        }
    }
    if !wrote_any {
        return Err(ServoError::InvalidParam(
            "至少给一个参数，如：protect --max-temp 80 --unload 12 --led 12".into(),
        ));
    }
    if save {
        println!("已全部掉电保存");
    } else {
        println!("（仅本次有效，加 --save 可掉电保存）");
    }
    Ok(())
}

/// Translate the unload-condition/LED-alarm bitmasks into Chinese (see doc sections 3.3/3.4 for bit definitions)
fn describe_protect_bits(v: u8) -> String {
    if v == 0 {
        return "全部关闭".to_string();
    }
    let bits = [
        (1u8, "电压"),
        (2, "磁编码"),
        (4, "过热"),
        (8, "过流"),
    ];
    let mut names = Vec::new();
    for (bit, name) in bits {
        if v & bit != 0 {
            names.push(name);
        }
    }
    names.join("+")
}
