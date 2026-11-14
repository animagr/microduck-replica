//! registers.rs: complete "data-driven" definition of the HD1910M servo memory table
//!
//! The memory table is the servo's internal "parameter register": each address stores one functional parameter.
//! The table comes from Feetech's official docs (the HLS_2 memory table on doc.feetech.cn) and has 5 areas:
//!
//!   Addresses 0 ~ 4    Version info     (read-only: firmware version etc.)
//!   Addresses 5 ~ 39   EPROM config     (read/write; with the "lock flag" it can persist across power loss)
//!   Addresses 40 ~ 55  SRAM control     (read/write, real-time control area, lost on power loss)
//!   Addresses 56 ~ 75  SRAM feedback    (read-only: current position/speed/voltage/temperature/current...)
//!   Addresses 77 ~ 86  Factory params   (read-only: factory calibration values)
//!
//! [Rust concept: turning a "doc table" into "compile-time constants"]
//! We write the whole table as a `&'static [Register]` constant array.
//! The 'static lifetime means the data exists from program start to end,
//! uses no heap memory, and has zero access overhead. The CLI tool looks up this table to validate arguments and print descriptions;
//! adding a register only needs one more line in the table.

/// Register read/write access
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Access {
    /// Read-only (feedback values, version numbers, factory calibration values)
    ReadOnly,
    /// Read/write (configuration and control items)
    ReadWrite,
}

impl Access {
    pub fn as_str(&self) -> &'static str {
        match self {
            Access::ReadOnly => "只读",
            Access::ReadWrite => "读写",
        }
    }
}

/// Memory table areas
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Area {
    Version,      // version info
    Eprom,        // EPROM config (can persist across power loss)
    SramControl,  // SRAM real-time control
    SramFeedback, // SRAM real-time feedback
    Factory,      // factory calibration parameters
}

impl Area {
    pub fn as_str(&self) -> &'static str {
        match self {
            Area::Version => "版本信息",
            Area::Eprom => "EPROM配置",
            Area::SramControl => "SRAM控制",
            Area::SramFeedback => "SRAM反馈",
            Area::Factory => "出厂参数",
        }
    }
}

/// One register definition (corresponds to one row in the official memory table).
///
/// [Rust concept: &'static str]
/// String literals (like "目标位置") are compiled directly into the executable,
/// with a 'static lifetime (lives as long as the program), so storing them in a struct needs no heap allocation.
pub struct Register {
    /// Start address (decimal, same as the official docs)
    pub addr: u8,
    /// English key name used on the command line (e.g. "pos-p"), all lowercase
    pub key: &'static str,
    /// Chinese name (same as the official docs)
    pub cn: &'static str,
    /// Number of bytes: 1 or 2 (2-byte data stores the low byte first = little-endian)
    pub size: u8,
    pub access: Access,
    pub area: Area,
    /// Physical unit (what each LSB represents), e.g. "0.1V", "6.5mA"
    pub unit: &'static str,
    /// Valid value range (checked before writing to avoid corrupting the servo configuration)
    pub min: i64,
    pub max: i64,
    /// Position of the sign bit in sign-magnitude encoding:
    ///   None     : unsigned
    ///   Some(15) : BIT15 is the direction bit (position/speed/current etc.)
    ///   Some(10) : BIT10 is the direction bit (current load)
    /// The Feetech protocol represents negative numbers as "sign bit + absolute value", not the usual two's complement!
    pub sign_bit: Option<u8>,
    /// Remarks
    pub desc: &'static str,
}

impl Register {
    /// Range check before writing: returns Err when out of range, catching errors before sending.
    /// All write paths (write_reg / sync_write / set --defer etc.) share this single check.
    pub fn check_value(&self, value: i64) -> crate::error::Result<()> {
        if value < self.min || value > self.max {
            return Err(crate::error::ServoError::InvalidParam(format!(
                "值 {value} 超出 {}（{}）的合法范围 {} ~ {}",
                self.key, self.cn, self.min, self.max
            )));
        }
        Ok(())
    }
}

/// The full memory table (matches the official HLS_2 doc row by row).
///
/// [Rust concept: constant arrays]
/// Declared with const, so the entire content is fixed at compile time. Traversal is just ordinary array iteration.
pub const REGISTERS: &[Register] = &[
    // ---------------- 2.1 Version info (read-only) ----------------
    Register { addr: 0,  key: "fw-major",    cn: "固件主版本号", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "固件主版本号" },
    Register { addr: 1,  key: "fw-minor",    cn: "固件次版本号", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "固件次版本号" },
    Register { addr: 2,  key: "endian",      cn: "END",         size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "0 表示小端存储结构" },
    Register { addr: 3,  key: "servo-major", cn: "舵机主版本号", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "舵机主版本号" },
    Register { addr: 4,  key: "servo-minor", cn: "舵机次版本号", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "舵机次版本号" },

    // ---------------- 2.2 EPROM config (read/write, can persist across power loss) ----------------
    Register { addr: 5,  key: "id",              cn: "主ID",           size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "号",     min: 0, max: 253,   sign_bit: None, desc: "总线上唯一的主ID（出厂默认1），对主ID写入会同步修改副ID" },
    Register { addr: 6,  key: "baud",            cn: "波特率",         size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 7,     sign_bit: None, desc: "0~7 = 1000000/500000/250000/128000/115200/76800/57600/38400" },
    Register { addr: 7,  key: "id2",             cn: "副ID",           size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "号",     min: 0, max: 253,   sign_bit: None, desc: "第二标识，适用于写/异步写/异步执行/同步写指令" },
    Register { addr: 8,  key: "resp-level",      cn: "应答状态级别",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 1,     sign_bit: None, desc: "0: 除读与PING外不应答；1: 所有指令都应答" },
    Register { addr: 9,  key: "min-angle",       cn: "最小角度限制",   size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0.087度", min: 0, max: 4094,  sign_bit: None, desc: "多圈绝对位置控制时此值为0" },
    Register { addr: 11, key: "max-angle",       cn: "最大角度限制",   size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0.087度", min: 1, max: 4095,  sign_bit: None, desc: "多圈绝对位置控制时此值为0" },
    Register { addr: 13, key: "max-temp",        cn: "最高温度上限",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "°C",    min: 0, max: 100,   sign_bit: None, desc: "超过此温度关闭扭矩输出（出厂默认70°C开启保护）" },
    Register { addr: 14, key: "max-voltage",     cn: "最高输入电压",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0.1V",  min: 0, max: 254,   sign_bit: None, desc: "超过此电压进入过压保护" },
    Register { addr: 15, key: "min-voltage",     cn: "最低输入电压",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0.1V",  min: 0, max: 254,   sign_bit: None, desc: "低于此电压进入欠压保护（出厂默认4.0V）" },
    Register { addr: 16, key: "max-torque",      cn: "最大扭矩",       size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0.1%",  min: 0, max: 1000,  sign_bit: None, desc: "上电时赋值给48号地址转矩限制" },
    Register { addr: 18, key: "phase",           cn: "相位",           size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "特殊功能字节（方向/编码器/PWM频率等），无特别需求不可修改！" },
    Register { addr: 19, key: "unload-cond",     cn: "卸载条件",       size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "位设置: BIT0电压 BIT1磁编码 BIT2过热 BIT3过流，1=开启保护" },
    Register { addr: 20, key: "led-alarm",       cn: "LED报警条件",    size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "位设置: BIT0电压 BIT1磁编码 BIT2过热 BIT3过流，1=开启闪灯报警" },
    Register { addr: 21, key: "pos-p",           cn: "位置环P比例系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "上电赋值给50号地址Kp（位置环比例，1/8）" },
    Register { addr: 22, key: "pos-d",           cn: "位置环D微分系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "上电赋值给51号地址Kd（位置环微分，1/4）" },
    Register { addr: 23, key: "pos-i",           cn: "位置环I积分系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "上电赋值给52号地址Ki" },
    Register { addr: 24, key: "min-start-force", cn: "最小启动力",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0.1%",  min: 0, max: 254,   sign_bit: None, desc: "舵机的最小输出启动扭矩" },
    Register { addr: 25, key: "integral-limit",  cn: "积分限制值",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "最大积分值=该值*4，0=关闭积分限制，模式0与模式4生效" },
    Register { addr: 26, key: "deadband-cw",     cn: "正向不灵敏区",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0.087度", min: 0, max: 16,    sign_bit: None, desc: "最小单位为一个最小分辨角度" },
    Register { addr: 27, key: "deadband-ccw",    cn: "负向不灵敏区",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0.087度", min: 0, max: 16,    sign_bit: None, desc: "最小单位为一个最小分辨角度" },
    Register { addr: 28, key: "protect-current", cn: "保护电流",       size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "6.5mA", min: 0, max: 2047,  sign_bit: None, desc: "上电赋值给44号地址目标电流" },
    Register { addr: 30, key: "angle-resolution",cn: "角度分辨率",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 1, max: 128,   sign_bit: None, desc: "对传感器最小分辨角度的放大系数" },
    Register { addr: 31, key: "pos-offset",      cn: "位置偏移",       size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0.087度", min: -4095, max: 4095, sign_bit: Some(15), desc: "BIT15为方向位，用于校正机械零位" },
    Register { addr: 33, key: "mode",            cn: "运行模式",       size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 4,     sign_bit: None, desc: "0位置伺服(位置+限流) 1电机恒速 2电机恒流 3PWM开环调速 4纯位置PD(Sim2Real)" },
    Register { addr: 34, key: "cur-p",           cn: "电流环P比例系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "电流环比例系数（力控核心参数）" },
    Register { addr: 35, key: "cur-i",           cn: "电流环I积分系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "电流环积分系数（力控核心参数）" },
    Register { addr: 36, key: "reserved-36",     cn: "无定义(36)",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "官方文档未定义，谨慎修改" },
    Register { addr: 37, key: "vel-p",           cn: "速度闭环P比例系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",   min: 0, max: 254,   sign_bit: None, desc: "电机恒速模式(模式1)下速度环比例系数，上电赋值给50号Kp" },
    Register { addr: 38, key: "overcur-time",    cn: "过流保护时间",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "10ms",  min: 0, max: 254,   sign_bit: None, desc: "电流超限持续该时间后进入过流保护" },
    Register { addr: 39, key: "vel-i",           cn: "速度闭环I积分系数", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",   min: 0, max: 254,   sign_bit: None, desc: "电机恒速模式(模式1)下速度环积分系数，上电赋值给52号Ki" },

    // ---------------- 2.3 SRAM control (read/write, lost on power loss) ----------------
    Register { addr: 40, key: "torque-switch", cn: "扭矩开关",   size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 2,     sign_bit: None, desc: "0:关闭扭力输出 1:打开扭力输出 2:阻尼输出" },
    Register { addr: 41, key: "acc",           cn: "加速度",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "8.7度/秒²", min: 0, max: 254, sign_bit: None, desc: "运行加/减速度，0表示最大加速度" },
    Register { addr: 42, key: "goal-pos",      cn: "目标位置",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "0.087度", min: -32767, max: 32767, sign_bit: Some(15), desc: "绝对位置控制，BIT15为方向位；多圈模式可超4095" },
    Register { addr: 44, key: "goal-current",  cn: "目标电流",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "6.5mA", min: -2047, max: 2047, sign_bit: Some(15), desc: "除模式3外控制电机最大运行电流；恒流模式BIT15为电流方向位；PWM模式范围-1000~1000且BIT10为方向位" },
    Register { addr: 46, key: "speed",         cn: "运行速度",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "0.732RPM", min: -32767, max: 32767, sign_bit: Some(15), desc: "电机最高运行速度，0=停止；恒速模式BIT15为速度方向位" },
    Register { addr: 48, key: "torque-limit",  cn: "转矩限制",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "0.1%",  min: 0, max: 1000,  sign_bit: None, desc: "控制堵转扭矩输出（上电时=16号最大扭矩）" },
    Register { addr: 50, key: "kp",            cn: "运行Kp",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 254,   sign_bit: None, desc: "位置伺服:位置环P(1/8)；恒速模式:速度环P（运行时实时生效）" },
    Register { addr: 51, key: "kd",            cn: "运行Kd",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 254,   sign_bit: None, desc: "位置伺服:位置环D(1/4)；恒速模式:无效" },
    Register { addr: 52, key: "ki",            cn: "运行Ki",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 254,   sign_bit: None, desc: "位置伺服:无效；恒速模式:速度环I" },
    Register { addr: 53, key: "reserved-53",   cn: "无定义(53)", size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 255,   sign_bit: None, desc: "官方文档未定义，谨慎修改" },
    Register { addr: 54, key: "reserved-54",   cn: "无定义(54)", size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 255,   sign_bit: None, desc: "官方文档未定义，谨慎修改" },
    Register { addr: 55, key: "lock",          cn: "锁标志",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 1,     sign_bit: None, desc: "0:关闭写入锁(EPROM写值掉电保存) 1:打开写入锁(掉电不保存，默认)" },

    // ---------------- 2.4 SRAM feedback (read-only) ----------------
    Register { addr: 56, key: "pos",            cn: "当前位置",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0.087度",  min: -32767, max: 32767, sign_bit: Some(15), desc: "当前绝对位置，BIT15为方向位（多圈模式含圈数）" },
    Register { addr: 58, key: "vel",            cn: "当前速度",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0.732RPM", min: -32767, max: 32767, sign_bit: Some(15), desc: "当前电机转动速度，BIT15为方向位" },
    Register { addr: 60, key: "load",           cn: "当前负载",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0.1%",     min: -1000, max: 1000,   sign_bit: Some(10), desc: "驱动电机的电压占空比，BIT10为方向位" },
    Register { addr: 62, key: "voltage",        cn: "当前电压",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0.1V",    min: 0, max: 255,   sign_bit: None, desc: "当前舵机工作电压" },
    Register { addr: 63, key: "temp",           cn: "当前温度",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "°C",     min: 0, max: 255,   sign_bit: None, desc: "当前舵机内部工作温度" },
    Register { addr: 64, key: "async-flag",     cn: "异步写标志", size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 255,   sign_bit: None, desc: "采用异步写指令时的标志位" },
    Register { addr: 65, key: "status",         cn: "舵机状态",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 255,   sign_bit: None, desc: "BIT0电压 BIT1磁编码 BIT2温度 BIT3电流，置1=异常" },
    Register { addr: 66, key: "moving",         cn: "移动标志",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 255,   sign_bit: None, desc: "BIT0:运动中为1；BIT1:运动中为1/到位停止为0" },
    Register { addr: 67, key: "goal-pos-fb",    cn: "目标位置反馈", size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0.087度", min: 0, max: 65535, sign_bit: None, desc: "当前目标位置" },
    Register { addr: 69, key: "current",        cn: "当前电流",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "6.5mA",   min: -32767, max: 32767, sign_bit: Some(15), desc: "当前电机相电流，BIT15为方向位" },
    Register { addr: 71, key: "reserved-71",    cn: "无定义(71)", size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 65535, sign_bit: None, desc: "官方文档未定义" },
    Register { addr: 73, key: "current-offset", cn: "电流偏置",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 65535, sign_bit: None, desc: "电流0点偏移值" },

    // ---------------- 2.5 Factory parameters (read-only, factory calibration) ----------------
    Register { addr: 77, key: "v-fk",            cn: "vFk(*10)",     size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 78, key: "v-kgi",           cn: "vKgI",         size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 79, key: "p-fk",            cn: "pFk(*10)",     size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 80, key: "move-speed-th",   cn: "移动速度阀值", size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "判定“是否在运动”的速度阀值" },
    Register { addr: 81, key: "dts",             cn: "DTs(ms)",      size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 82, key: "e-fk",            cn: "eFk(*10)",     size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 83, key: "vk",              cn: "Vk(ms)",       size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 84, key: "max-speed-limit", cn: "最大速度限制", size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 85, key: "acc-limit",       cn: "加速度限制",   size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
    Register { addr: 86, key: "acc-multi",       cn: "加速度倍数",   size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "工厂标定参数" },
];

/// Baud rate index table: the actual baud rates for values 0~7 at memory table address 6.
pub const BAUD_RATES: [u32; 8] = [
    1_000_000, 500_000, 250_000, 128_000, 115_200, 76_800, 57_600, 38_400,
];

/// Look up a register by "English key name" or "address".
///
/// Supported forms (command-line friendly):
///   - Key name: "pos-p", "id", "torque-limit" (case-insensitive)
///   - Decimal address: "21"
///   - Hex address: "0x15"
///
/// [Rust concept: Option<T>]
/// "Might not be found" is expressed with `Option`: Some(register) or None.
/// This is Rust's replacement for null: the compiler forces you to handle the "not found" case,
/// eliminating null pointer exceptions at the root.
///
/// [Rust concept: chained iterator calls]
/// `.iter().find(...)` is functional style: iterate the array and return the first element matching the condition.
pub fn find_register(name_or_addr: &str) -> Option<&'static Register> {
    let key = name_or_addr.to_lowercase();

    // First try parsing as an address: "0x15" (hex) or "21" (decimal)
    let addr: Option<u8> = if let Some(hex) = key.strip_prefix("0x") {
        u8::from_str_radix(hex, 16).ok() // .ok() converts Result into Option
    } else {
        key.parse::<u8>().ok()
    };
    if let Some(a) = addr {
        return REGISTERS.iter().find(|r| r.addr == a);
    }

    // Then match by key name
    REGISTERS.iter().find(|r| r.key == key)
}

/// Sign-magnitude decoding: restore the protocol's raw u16 into a signed integer.
///
/// Negative numbers in the Feetech protocol are not two's complement! They are "sign bit + absolute value":
///   a 1 at sign_bit means negative, and the remaining bits are the absolute value.
///   For example, position -100 is encoded as 0x8000 | 100 = 0x8064.
pub fn decode_value(raw: u16, sign_bit: Option<u8>) -> i64 {
    match sign_bit {
        Some(bit) => {
            let sign_mask = 1u16 << bit;        // sign bit mask, e.g. 0x8000
            let mag_mask = sign_mask - 1;       // magnitude mask, e.g. 0x7FFF
            let mag = (raw & mag_mask) as i64;
            if raw & sign_mask != 0 { -mag } else { mag }
        }
        None => raw as i64,
    }
}

/// Sign-magnitude encoding: pack a signed integer into the u16 the protocol expects.
pub fn encode_value(value: i64, sign_bit: Option<u8>) -> u16 {
    match sign_bit {
        Some(bit) => {
            let sign_mask = 1u16 << bit;
            let mag = value.unsigned_abs() as u16; // unsigned_abs: |v| directly as an unsigned number
            if value < 0 { mag | sign_mask } else { mag }
        }
        None => value as u16,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_by_key_and_addr() {
        assert_eq!(find_register("pos-p").unwrap().addr, 21);
        assert_eq!(find_register("POS-P").unwrap().addr, 21); // case-insensitive
        assert_eq!(find_register("21").unwrap().key, "pos-p");
        assert_eq!(find_register("0x15").unwrap().key, "pos-p");
        assert!(find_register("not-exist").is_none());
    }

    #[test]
    fn test_sign_magnitude_roundtrip() {
        // Position -100 should encode to 0x8064 and decode back
        let raw = encode_value(-100, Some(15));
        assert_eq!(raw, 0x8064);
        assert_eq!(decode_value(raw, Some(15)), -100);
        // Unsigned registers are unaffected
        assert_eq!(decode_value(1000, None), 1000);
        // Load uses BIT10 as the sign bit: -500 → 0x0400 | 500
        let raw = encode_value(-500, Some(10));
        assert_eq!(decode_value(raw, Some(10)), -500);
    }

    #[test]
    fn test_check_value() {
        let reg = find_register("pos-p").unwrap(); // range 0~254
        assert!(reg.check_value(254).is_ok());
        assert!(reg.check_value(255).is_err());
        assert!(reg.check_value(-1).is_err());
        let offset = find_register("pos-offset").unwrap(); // range -4095~4095
        assert!(offset.check_value(-4095).is_ok());
        assert!(offset.check_value(-4096).is_err());
    }
}
