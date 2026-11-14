# -*- coding: utf-8 -*-
"""Minimal implementation of the Feetech STS/SMS bus: packet format, read/write, sync read/write, reboot.

Written against docs/飞特资料/SCS通信协议-v1.0-2026-06-09.md and 磁编码STS内存表手册-v1.1-2026-08-27.md,
with no dependency on the Feetech SDK. Byte order follows the magnetic-encoder series: little-endian.

Moved from tools/servo-web/feetech.py in this same repo (v0.15.4, our own code, used on real hardware). Two changes in Studio:
- Per-servo communication stats (per_id): how many times asked, answered, missed, consecutive misses, status-bit alarms.
  servo-web only had cumulative counts for the whole bus (user on 10-18 asked for "whether each servo's replies drop frames"); the definitions follow robotd's
  communication_stats (missing / timeout / consecutive).
- serial is imported only when used: pyserial is not needed with the simulator (sim_bus).
"""
import struct
import threading
import time

PING, READ, WRITE, REG_WRITE, ACTION = 0x01, 0x02, 0x03, 0x04, 0x05
RECOVERY, REBOOT, BACKUP, RESET_TURNS, CALIBRATE = 0x06, 0x08, 0x09, 0x0A, 0x0B
SYNC_READ, SYNC_WRITE = 0x82, 0x83
INSTR_NAMES = {0x01: "PING", 0x02: "READ", 0x03: "WRITE", 0x04: "REG_WRITE", 0x05: "ACTION",
               0x06: "参数恢复", 0x08: "REBOOT", 0x09: "参数备份", 0x0A: "清圈数", 0x0B: "位置校准",
               0x82: "SYNC_READ", 0x83: "SYNC_WRITE"}
BROADCAST = 0xFE

# Memory table: address -> (name, byte count, area). Used for register export.
REGISTERS = {
    0: ("固件主版本", 1, "只读"), 1: ("固件次版本", 1, "只读"), 2: ("END 字节序(0=小端)", 1, "只读"),
    3: ("舵机主版本", 1, "只读"), 4: ("舵机次版本", 1, "只读"),
    5: ("ID", 1, "EEPROM"), 6: ("波特率(0=1M)", 1, "EEPROM"), 7: ("预留地址（STS 无应答延时寄存器）", 1, "EEPROM"),
    8: ("应答状态级别", 1, "EEPROM"), 9: ("最小角度限制", 2, "EEPROM"), 11: ("最大角度限制", 2, "EEPROM"),
    13: ("最高温度上限", 1, "EEPROM"), 14: ("最高输入电压", 1, "EEPROM"), 15: ("最低输入电压", 1, "EEPROM"),
    16: ("最大扭矩", 2, "EEPROM"), 18: ("相位", 1, "EEPROM"), 19: ("卸载条件", 1, "EEPROM"),
    20: ("LED报警条件", 1, "EEPROM"), 21: ("位置环P", 1, "EEPROM"), 22: ("位置环D", 1, "EEPROM"),
    23: ("位置环I", 1, "EEPROM"), 24: ("最小启动扭矩", 1, "EEPROM"), 25: ("积分限制值", 1, "EEPROM"),
    26: ("正向不灵敏区", 1, "EEPROM"), 27: ("负向不灵敏区", 1, "EEPROM"), 28: ("保护电流", 2, "EEPROM"),
    30: ("角度分辨率", 1, "EEPROM"), 31: ("位置偏移", 2, "EEPROM"), 33: ("运行模式", 1, "EEPROM"),
    34: ("保持扭矩", 1, "EEPROM"), 35: ("保护时间", 1, "EEPROM"), 36: ("过载扭矩", 1, "EEPROM"),
    37: ("速度环P", 1, "EEPROM"), 38: ("过流保护时间", 1, "EEPROM"), 39: ("速度环I", 1, "EEPROM"),
    40: ("扭矩开关", 1, "SRAM"), 41: ("加速度", 1, "SRAM"), 42: ("目标位置", 2, "SRAM"),
    44: ("PWM开环速度", 2, "SRAM"), 46: ("运行速度", 2, "SRAM"), 48: ("转矩限制", 2, "SRAM"),
    # 50–52: the STS manual says "undefined"; on the HD-1910 these are the running P / D / I (RAM, copied from 21–23 at power-up).
    # The main program writes here when enabling torque (fork duck-control/src/hd1910.rs:77-79, 149, 257-267; hd1910_test.rs:44-47)
    50: ("位置环P（运行中）", 1, "SRAM"), 51: ("位置环D（运行中）", 1, "SRAM"), 52: ("位置环I（运行中）", 1, "SRAM"),
    55: ("锁标志", 1, "SRAM"),
    56: ("当前位置", 2, "反馈"), 58: ("当前速度", 2, "反馈"), 60: ("当前负载", 2, "反馈"),
    62: ("当前电压(0.1V)", 1, "反馈"), 63: ("当前温度(°C)", 1, "反馈"), 64: ("异步写标志", 1, "反馈"),
    65: ("舵机状态位", 1, "反馈"), 66: ("移动标志", 1, "反馈"), 67: ("目标位置(回读)", 2, "反馈"),
    69: ("当前电流(6.5mA)", 2, "反馈"),
    80: ("移动速度阀值", 1, "出厂"), 81: ("DTs(ms)", 1, "出厂"), 82: ("速度单位系数", 1, "出厂"),
    83: ("最小速度限制", 1, "出厂"), 84: ("最大速度限制", 1, "出厂"), 85: ("加速度限制", 1, "出厂"),
    86: ("加速度倍数", 1, "出厂"),
}
STATUS_BITS = {0: "电压", 1: "磁编码", 2: "温度", 3: "电流", 5: "负载"}
DUMP_END = max(REGISTERS) + 1   # 87: the last address in the register table is 86


def sign15(v):
    """16-bit quantity with BIT15 as the direction bit (position, speed, current)."""
    return -(v & 0x7FFF) if v & 0x8000 else v


def sign10(v):
    """BIT10 is the direction bit (load)."""
    return -(v & 0x3FF) if v & 0x400 else v


class BusError(Exception):
    pass


class BusTimeout(BusError):
    """No reply or incomplete reply. At reply level 0, write instructions don't reply anyway; the caller decides whether that counts as an error."""


def hexs(b):
    return " ".join(f"{x:02x}" for x in b)


class FeetechBus:
    def __init__(self, port, baud=1_000_000, timeout=0.02, ser=None):
        # ser is for the simulator (sim_bus.SimSerial); real hardware goes through the serial port
        if ser is None:
            import serial   # noqa: PLC0415 —— only a real serial port needs pyserial
            ser = serial.Serial(port, baud, timeout=timeout, write_timeout=0.1)
        self.ser = ser
        # Serial port mutex. Don't call it self.lock: that would shadow the lock(sid) "set EEPROM lock" method below (hit on real hardware 2026-09-20)
        self._io = threading.Lock()
        # Raw TX/RX log: set a trace(text) callback to start recording. Operations Feetech doesn't support still reply "success",
        # and only the hex tells "really done" apart from "pretended to do it". The 10 Hz status polling isn't logged, otherwise the log would be all polling
        self.trace = None
        self.trace_skip = {SYNC_READ, SYNC_WRITE}
        self._last = (None, None)
        self.stats = {"tx": 0, "rx_ok": 0, "timeout": 0, "bad_checksum": 0, "bad_id": 0}
        # Per servo: {id: {"asked", "ok", "missed", "alarm", "streak", "max_streak"}}.
        # The ID in a frame with a checksum error can't be trusted; those are only counted in the bus-level stats
        self.per_id = {}

    def _note(self, sid, ok, err=0):
        c = self.per_id.get(sid)
        if c is None:
            c = self.per_id[sid] = {"asked": 0, "ok": 0, "missed": 0, "alarm": 0, "streak": 0, "max_streak": 0}
        c["asked"] += 1
        if ok:
            c["ok"] += 1
            c["streak"] = 0
            if err:
                c["alarm"] += 1
        else:
            c["missed"] += 1
            c["streak"] += 1
            c["max_streak"] = max(c["max_streak"], c["streak"])

    def close(self):
        self.ser.close()

    # ---- Packets ----
    @staticmethod
    def _packet(sid, instr, params=b""):
        length = len(params) + 2
        chk = (~(sid + length + instr + sum(params))) & 0xFF
        return bytes([0xFF, 0xFF, sid, length, instr]) + bytes(params) + bytes([chk])

    def _send(self, sid, instr, params=b""):
        self.ser.reset_input_buffer()
        pkt = self._packet(sid, instr, params)
        self.ser.write(pkt)
        self.stats["tx"] += 1
        self._last = (sid, instr)
        if self.trace and instr not in self.trace_skip:
            note = ""
            if instr in (READ, WRITE) and params:
                reg = REGISTERS.get(params[0])
                note = f"  地址{params[0]}" + (f"「{reg[0]}」" if reg else "") + (
                    f" 写 {list(params[1:])}" if instr == WRITE else f" 读 {params[1]} 字节")
            self.trace(f"→ #{sid} {INSTR_NAMES.get(instr, hex(instr))} {hexs(pkt)}{note}")

    def _read_status(self, expect_id=None):
        """Read one reply frame, return (id, error, params)."""
        # Look for FF FF
        hdr = b""
        deadline = time.monotonic() + self.ser.timeout * 3
        while time.monotonic() < deadline:
            b = self.ser.read(1)
            if not b:
                break
            hdr = (hdr + b)[-2:]
            if hdr == b"\xff\xff":
                break
        who = f"id {expect_id}" if expect_id is not None else "舵机"
        if hdr != b"\xff\xff":
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} 没应答（{self.ser.timeout * 3 * 1000:.0f} ms 内没收到帧头）")
        rest = self.ser.read(2)
        if len(rest) < 2:
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} 应答断在 ID/长度（收到 ff ff {hexs(rest)}）")
        sid, length = rest[0], rest[1]
        body = self.ser.read(length)
        if len(body) < length:
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} 应答不完整：长度 {length} 只收到 {len(body)}（ff ff {hexs(rest + body)}）")
        err, params, chk = body[0], body[1:-1], body[-1]
        if ((~(sid + length + err + sum(params))) & 0xFF) != chk:
            self.stats["bad_checksum"] += 1
            raise BusError(f"{who} 校验和不对（ff ff {hexs(rest + body)}）")
        if expect_id is not None and sid != expect_id:
            self.stats["bad_id"] += 1
            raise BusError(f"等 id {expect_id} 的应答，来的是 id {sid}（ff ff {hexs(rest + body)}）")
        self.stats["rx_ok"] += 1
        if self.trace and self._last[1] not in self.trace_skip:
            self.trace(f"← #{sid} 状态0x{err:02X} {hexs(b'\xff\xff' + rest + body)}"
                       + (f"  数据 {list(params)}" if params else ""))
        return sid, err, bytes(params)

    # ---- Instructions ----
    def ping(self, sid):
        with self._io:
            self._send(sid, PING)
            try:
                _, err, _ = self._read_status(sid)
                return err
            except BusError:
                return None

    def read(self, sid, addr, n):
        with self._io:
            self._send(sid, READ, bytes([addr, n]))
            try:
                _, err, params = self._read_status(sid)
            except BusError:
                self._note(sid, False)
                raise
            self._note(sid, True, err)
            if len(params) != n:
                raise BusError(f"id {sid} 读地址 {addr} 起 {n} 字节，只回了 {len(params)} 字节")
            return err, params

    def write(self, sid, addr, data, wait=True):
        with self._io:
            self._send(sid, WRITE, bytes([addr]) + bytes(data))
            if not wait or sid == BROADCAST:
                return None
            try:
                _, err, _ = self._read_status(sid)
                return err
            except BusTimeout:
                # At reply level 0, write instructions don't reply; not an error. The caller gets None and decides
                return None

    def write_u8(self, sid, addr, v):
        return self.write(sid, addr, [v & 0xFF])

    def write_u16(self, sid, addr, v):
        return self.write(sid, addr, struct.pack("<H", v & 0xFFFF))

    def read_u8(self, sid, addr):
        return self.read(sid, addr, 1)[1][0]

    def read_u16(self, sid, addr):
        return struct.unpack("<H", self.read(sid, addr, 2)[1])[0]

    def sync_write(self, addr, length, id_values):
        """id_values: [(id, bytes), ...], each bytes of length = length."""
        params = bytes([addr, length])
        for sid, data in id_values:
            assert len(data) == length
            params += bytes([sid]) + bytes(data)
        with self._io:
            self._send(BROADCAST, SYNC_WRITE, params)

    def sync_read(self, ids, addr, n):
        """Returns {id: (err, params) or None}; filed by the ID in the reply, so a missing packet doesn't take the following packets with it."""
        out = dict.fromkeys(ids)
        with self._io:
            self._send(BROADCAST, SYNC_READ, bytes([addr, n]) + bytes(ids))
            for _ in ids:
                try:
                    sid, err, params = self._read_status()
                except BusTimeout:
                    break
                except BusError:
                    continue
                if sid not in out:
                    self.stats["bad_id"] += 1
                elif len(params) == n and out[sid] is None:
                    out[sid] = (err, params)
            for sid, v in out.items():
                self._note(sid, v is not None, v[0] if v else 0)
        return out

    def reboot(self, sid):
        """0x08, no reply, comes back after about 800 ms."""
        with self._io:
            self._send(sid, REBOOT)

    def calibrate_to(self, sid, value=None):
        """0x0B position calibration: change the servo's reading of "the current position" to value (default is the center 2048); the servo computes and stores the offset itself.
        Protocol manual 4.9: STS ≥3.10 and HLS ≥3.43 support the parameter. The HD-1910 (firmware 3.46) ignores writing 128 to the torque switch, so this is the only way.
        Returns the status byte from the reply; returns None if there is no reply."""
        params = b"" if value is None else struct.pack("<H", value & 0xFFFF)
        with self._io:
            self._send(sid, CALIBRATE, params)
            try:
                return self._read_status(sid)[1]
            except BusTimeout:
                return None

    def unlock(self, sid):
        return self.write_u8(sid, 55, 0)

    def lock(self, sid):
        return self.write_u8(sid, 55, 1)

    # ---- Combined actions ----
    def state(self, sid):
        """56..70: position speed load voltage temperature async-write status moving target current = 15 bytes."""
        err, p = self.read(sid, 56, 15)
        return self._decode_state(err, p)

    @staticmethod
    def _decode_state(err, p):
        pos, spd, load = struct.unpack_from("<HHH", p, 0)
        goal, cur = struct.unpack_from("<HH", p, 11)
        return {
            "err": err, "pos": sign15(pos), "speed": sign15(spd), "load": sign10(load),
            "volt": p[6] / 10.0, "temp": p[7], "status": p[9], "moving": p[10],
            "goal": sign15(goal), "current_ma": sign15(cur) * 6.5,
            "status_text": "".join(n for b, n in STATUS_BITS.items() if p[9] >> b & 1) or "",
        }

    def states(self, ids):
        """Get everything in one sync_read; IDs that fail have the value None."""
        raw = self.sync_read(ids, 56, 15)
        return {sid: (self._decode_state(*v) if v else None) for sid, v in raw.items()}

    def dump(self, sid):
        """Read all of 0–86, decoded by REGISTERS."""
        raw = b""
        for start in range(0, DUMP_END, 10):          # the HD-1910 table ends at 86; reading past it, the servo only returns the remaining bytes
            n = min(10, DUMP_END - start)
            for attempt in range(4):
                try:
                    raw += self.read(sid, start, n)[1]
                    break
                except BusError as e:
                    if attempt == 3:
                        raise BusError(f"导出到地址 {start}：{e}")
                    time.sleep(0.01)
        rows = []
        for addr in sorted(REGISTERS):
            name, size, area = REGISTERS[addr]
            v = raw[addr] if size == 1 else struct.unpack_from("<H", raw, addr)[0]
            rows.append({"addr": addr, "name": name, "area": area, "size": size, "value": v})
        return {"rows": rows, "raw": list(raw)}

    def set_id(self, old, new):
        self.unlock(old)
        # The reply to the change-ID packet may come back with the new ID or the old ID; don't wait for it. The receive buffer is cleared before the next packet is sent
        self.write(old, 5, [new & 0xFF], wait=False)
        time.sleep(0.02)
        self.lock(new)
        return self.ping(new) is not None
