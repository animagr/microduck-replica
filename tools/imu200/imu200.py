# -*- coding: utf-8 -*-
"""ID 200 IMU block: encode/decode + fake board (simulator) + conformance check for the real board.

The `imu_to_dxl` board has to impersonate a servo with ID 200 on the servo bus; the controller's sync_read each tick
(address 56, length 15) reads it back together with the 15 servos in one go. For the full protocol see
[`hardware/imu_to_dxl/总线协议.md`](../../hardware/imu_to_dxl/总线协议.md); this file is its **executable version**:

  python imu200.py demo                  # fake board + the real controller code, run once in memory
  python imu200.py vectors               # print test vectors (hex), to copy from when writing firmware
  python imu200.py check --port COM6     # run the conformance check against a real board, PASS/FAIL per item

All criteria are written to match the controller's real code (the fork's `duck-control/src/imu.rs` and `bus.rs`), not the protocol text,
so passing here = the controller will accept it. Logs follow the repo convention: `logs/imu200-<date>.log` (including raw TX/RX hex),
plus one JSONL line per frame, so when something goes wrong just read the file.
"""
import argparse
import json
import math
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "servo-web"))
import feetech  # noqa: E402  the repo's Feetech protocol implementation, not reinvented

IMU_ID = 200
BLOCK_ADDR = 56           # same address range as the servos, so ID 200 can squeeze into the same sync_read
BLOCK_LEN = 15            # the controller actually uses the first 12 bytes (imu.rs: IMU_BLOCK_LEN = 12); the last 3 bytes pad it to the servos' block length
IMU_WINDOW = 12           # the window the controller looks at, also the range StaleImuTracker compares byte by byte
GYRO_LSB_DPS = 0.0175     # ±500 dps range, 17.5 mdps/LSB (imu.rs: GYRO_RAD_PER_LSB)
GYRO_MAX_LSB = 28571      # LSB at ±500 dps full scale; exceeding it means the firmware range is misconfigured
READY_FRAMES = 25         # the controller needs a cumulative (not consecutive) 25 frames with a valid quaternion to be ready (imu.rs: quat_samples)
NORM_SQ_MAX = 1.02        # imu.rs criterion: rounding margin for half precision at full scale
STALE_RUN_MAX = 25        # bus.rs: StaleImuTracker, 25 consecutive frames with identical 12 bytes → report frozen
TICK_BUDGET_MS = 6.0      # architecture doc §5 item 4: budget for one sync_read reading 16 devices
MOUNT = (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0)   # imu.rs: DEFAULT_MOUNT, +90° about Y

JOINT_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]
FULL_IDS = [IMU_ID] + JOINT_IDS        # this is exactly the list the controller sends each tick, 200 first


# ---- Logging: same format as servo-web, debug goes only to the file ----
LOG_DIR = os.path.join(HERE, "logs")
_log_file = None


def log(msg, cat="总线", level="info"):
    global _log_file
    tag = {"info": "", "warn": "[警告]", "error": "[错误]", "debug": "[调试]"}[level]
    line = f"{time.strftime('%H:%M:%S')} [{cat}]{tag} {msg}"
    try:
        if _log_file is None:
            os.makedirs(LOG_DIR, exist_ok=True)
            _log_file = open(os.path.join(LOG_DIR, f"imu200-{time.strftime('%Y-%m-%d')}.log"),
                             "a", encoding="utf-8")
        _log_file.write(line + "\n")
        _log_file.flush()
    except OSError:
        pass
    if level != "debug":
        print(line)


def attach_trace(bus):
    """Hook raw TX/RX into the log. Note that trace_skip must be cleared: by default it filters out SYNC_READ,
    and that is exactly the one we want to debug."""
    bus.trace_skip = set()
    bus.trace = lambda s: log(s, "总线", "debug")


# ---- Half precision: the firmware side probably has nothing ready-made; follow IEEE 754 binary16 so it's easy to copy ----
def f32_to_f16(x):
    return struct.unpack("<H", struct.pack("<e", x))[0]


def f16_to_f32(h):
    return struct.unpack("<e", struct.pack("<H", h))[0]


def encode_block(gyro_dps=(0.0, 0.0, 0.0), quat_xyz=(0.0, 0.0, 0.0), counter=0, status=0):
    """15 bytes: gyro x/y/z (i16 little-endian, 17.5 mdps/LSB) + quat x/y/z (half) + sample counter + status + reserved.

    Both gyro and quaternion are validated with the controller's criteria: generating a block the controller is certain to reject without raising an error is the worst way for this kind of tool to fail.
    """
    raw = [int(round(v / GYRO_LSB_DPS)) for v in gyro_dps]
    if any(abs(v) > GYRO_MAX_LSB for v in raw):
        raise ValueError(f"陀螺超量程：{gyro_dps} dps，±500 dps 对应 ±{GYRO_MAX_LSB} LSB")
    norm_sq = sum(v * v for v in quat_xyz)
    if not all(math.isfinite(v) for v in quat_xyz) or norm_sq > NORM_SQ_MAX:
        raise ValueError(f"四元数主控会拒绝：{quat_xyz}，norm² = {norm_sq:.3f} > {NORM_SQ_MAX}")
    return (struct.pack("<hhh", *raw)
            + struct.pack("<HHH", *(f32_to_f16(v) for v in quat_xyz))
            + bytes([counter & 0xFF, status & 0xFF, 0]))


def _qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def decode_block(b):
    """Decode 15 bytes, criteria copied item by item from imu.rs:

    - All three quaternion components are 0 → fusion hasn't produced output yet; the controller reuses the previous frame and doesn't count it toward ready
    - Any component not finite, or norm² > 1.02 → the controller **rejects** this frame (the tool must be just as strict,
      otherwise bad firmware is all green here and imu_ready() is forever false on the real robot)
    - w = √(1 − norm²), then multiplied by the conjugate of mount; norm ≤ 0.5 is also rejected
    """
    if len(b) != BLOCK_LEN:
        raise ValueError(f"要 {BLOCK_LEN} 字节，给了 {len(b)}")
    gx, gy, gz = struct.unpack_from("<hhh", b, 0)
    packed = struct.unpack_from("<HHH", b, 6)
    qx, qy, qz = (f16_to_f32(h) for h in packed)
    finite = all(math.isfinite(v) for v in (qx, qy, qz))
    norm_sq = (qx * qx + qy * qy + qz * qz) if finite else float("inf")
    accepted, quat, gravity = False, None, None
    if any(packed) and finite and norm_sq <= NORM_SQ_MAX:
        w = math.sqrt(max(0.0, 1.0 - norm_sq))
        q = _qmul((w, qx, qy, qz), (MOUNT[0], -MOUNT[1], -MOUNT[2], -MOUNT[3]))
        n = math.sqrt(sum(v * v for v in q))
        if n > 0.5:
            accepted = True
            quat = tuple(v / n for v in q)
            # gravity = gravity direction in the torso frame, [0, 0, -1] when upright (same as imu.rs)
            w0, x0, y0, z0 = quat
            gravity = (-2 * (x0 * z0 - w0 * y0), -2 * (y0 * z0 + w0 * x0),
                       -(1 - 2 * (x0 * x0 + y0 * y0)))
    return {
        "gyro_raw": (gx, gy, gz),
        "gyro_dps": (gx * GYRO_LSB_DPS, gy * GYRO_LSB_DPS, gz * GYRO_LSB_DPS),
        "quat_packed": packed,
        "quat_xyz": (qx, qy, qz),
        "quat_trunk": quat,
        "gravity": gravity,
        "norm_sq": norm_sq,
        "finite": finite,
        "counter": b[12],
        "status": b[13],
        "reserved": b[14],
        "accepted": accepted,                  # whether the controller would count this frame toward ready
        "window_hex": b[:IMU_WINDOW].hex(),     # these 12 bytes are exactly what StaleImuTracker compares
    }


class SimImu200:
    """Fake board: plug it into sim_bus.SimSerial and the real controller code can read it.

    Written to match the behavior in the protocol file:
    - The block is driven by the IMU's data-ready (default 120 Hz), **not updated once per read**: the counter is a sample counter,
      so with the controller reading at 50 Hz it steps by 2~3. Making it "increment once per read" would mask faults like "IMU dead but the bus processor still alive"
    - The bus processor comes up before the IMU: it can reply after bus_up_ms, and only outputs quaternions after imu_ready_ms, returning all zeros in between
    - The gyro has noise: a real chip's low bits jump even at rest, so the block changes byte by byte. If the firmware smooths so the 12 bytes don't change,
      the controller reports frozen within 0.5 s
    - answer=False pretends to be a board that doesn't reply (consequence on the real robot: the whole sync_read fails, losing data from all 15 servos)
    """

    def __init__(self, sid=IMU_ID, sample_hz=120, bus_up_ms=0, imu_ready_ms=500,
                 answer=True, noise=True):
        self.r = bytearray(feetech.DUMP_END)
        self.r[0], self.r[1] = 0, 1           # firmware version 0.1, don't impersonate the servos' 3.46
        self.r[2], self.r[5], self.r[6], self.r[8] = 0, sid, 0, 1   # END little-endian, ID, 1 Mbps, reply level 1
        self.sample_hz, self.bus_up_ms, self.imu_ready_ms = sample_hz, bus_up_ms, imu_ready_ms
        self.answer, self.noise = answer, noise
        self.counter, self.samples, self.last_ms = 0, 0, 0.0
        self.muted = set()
        self.block = encode_block(counter=0, status=0x01)

    @property
    def id(self):
        return self.r[5]

    def tick(self, clock_ms=0.0):
        """Advance sampling on the virtual clock: a new block every 1/sample_hz seconds, regardless of how many times it's read."""
        while clock_ms - self.last_ms >= 1000.0 / self.sample_hz:
            self.last_ms += 1000.0 / self.sample_hz
            self.samples += 1
            self.counter = (self.counter + 1) & 0xFF
            t = self.last_ms / 1000.0
            n = (self.samples % 7 - 3) * 0.02 if self.noise else 0.0   # low-bit jitter so the block changes byte by byte
            if self.last_ms < self.imu_ready_ms:
                self.block = encode_block(gyro_dps=(0, 0, 0), quat_xyz=(0, 0, 0),
                                          counter=self.counter, status=0x01)
            else:
                yaw = 0.3 * math.sin(t)
                self.block = encode_block(
                    gyro_dps=(5.0 * math.sin(t) + n, -2.0 + n, 0.5 + n),
                    quat_xyz=(0.0, 0.0, math.sin(yaw / 2)),
                    counter=self.counter, status=0x00)

    def alive(self, clock_ms):
        return self.answer and clock_ms >= self.bus_up_ms

    def read(self, addr, n, clock_ms=0.0):
        self.tick(clock_ms)
        if addr == BLOCK_ADDR and n == BLOCK_LEN:
            return self.block
        return bytes(self.r[addr:min(addr + n, feetech.DUMP_END)])

    def write(self, addr, data):
        pass          # protocol: the controller never writes this board; writes are still ACKed but change nothing


# ---- Controller side: conformance check ----
def check(bus, sid=IMU_ID, frames=200, hz=50, full_bus=True, frame_log=None):
    """Query the board with the packets the controller would send, judging item by item. Returns [(passed?, description), ...]."""
    out = []

    def ok(cond, what, level=None):
        out.append((bool(cond), what))
        log(("✓ " if cond else "✗ ") + what, "总线", level or ("info" if cond else "warn"))
        return cond

    # 1. Power-up: ping waits up to 5 s, record the time of the first reply
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5.0:
        if bus.ping(sid) is not None:
            break
        time.sleep(0.05)
    boot_ms = (time.monotonic() - t0) * 1000
    if not ok(bus.ping(sid) is not None, f"PING ID {sid} 有应答（上电后 {boot_ms:.0f} ms）"):
        return out

    # 2. Unicast READ can read the block (needed by the debug console)
    try:
        _, blk = bus.read(sid, BLOCK_ADDR, BLOCK_LEN)
        ok(len(blk) == BLOCK_LEN, f"READ 地址 {BLOCK_ADDR} 长 {BLOCK_LEN} 回了 {len(blk)} 字节")
        d = decode_block(blk)
        ok(d["reserved"] == 0, f"保留字节（byte 14）是 0（实际 {d['reserved']}）")
    except Exception as e:
        ok(False, f"READ 地址 {BLOCK_ADDR}：{type(e).__name__}: {e}")
        return out

    # 3. Version/model registers (0–4) are readable, END is little-endian
    try:
        _, head = bus.read(sid, 0, 5)
        ok(head[2] == 0, f"END 字节序 = 0 小端（实际 {head[2]}）")
        log(f"版本区 0–4 = {list(head)}", "总线")
    except Exception as e:
        ok(False, f"READ 地址 0 长 5：{type(e).__name__}: {e}")

    # 4. The one the controller really sends: read 16 IDs together
    ids = FULL_IDS if full_bus else [sid]
    stats0 = dict(bus.stats)
    counters, accepted, windows, times, misses, partial = [], 0, [], [], 0, 0
    first_quat_ms = ready_ms = None
    t_start = time.monotonic()
    for k in range(frames):
        t = time.perf_counter()
        got = bus.sync_read(ids, BLOCK_ADDR, BLOCK_LEN)
        times.append((time.perf_counter() - t) * 1000)      # wraps only this statement, excluding our own sleep
        v = got.get(sid)
        if not v:
            misses += 1
        else:
            d = decode_block(v[1])
            counters.append(d["counter"])
            windows.append(d["window_hex"])
            if d["accepted"]:
                accepted += 1
                if first_quat_ms is None:
                    first_quat_ms = (time.monotonic() - t_start) * 1000
                if accepted == READY_FRAMES and ready_ms is None:
                    ready_ms = (time.monotonic() - t_start) * 1000
            if frame_log:
                frame_log.write(json.dumps({
                    "frame": k, "ms": round(times[-1], 3), "counter": d["counter"],
                    "gyro_raw": d["gyro_raw"], "quat_packed": d["quat_packed"],
                    "status": d["status"], "accepted": d["accepted"], "window": d["window_hex"],
                }, ensure_ascii=False) + "\n")
        if full_bus and got:
            partial += sum(1 for i in ids if got.get(i) is None and i != sid)
        time.sleep(max(0.0, 1.0 / hz - (time.perf_counter() - t)))
    dstats = {k: bus.stats[k] - stats0.get(k, 0) for k in bus.stats}

    ok(misses == 0, f"{frames} 帧里 IMU 一帧不漏（漏了 {misses}）")
    if full_bus:
        ok(partial == 0, f"同一条 sync_read 里 15 颗舵机也都答了（缺 {partial} 个）")
    ok(dstats.get("bad_id", 0) == 0,
       f"应答没错位（bad_id {dstats.get('bad_id', 0)}）—— 错位一次后面 15 个全废")
    ok(dstats.get("bad_checksum", 0) == 0, f"没有校验错（{dstats.get('bad_checksum', 0)}）")

    # 5. Counter: sample counter, reading at 50 Hz with 120 Hz sampling → +1~4 per frame; constantly 0 means the board isn't sampling
    steps = [(b - a) % 256 for a, b in zip(counters, counters[1:])]
    ok(steps and all(1 <= s <= 4 for s in steps),
       f"采样计数每帧 +1~4（实际 {sorted(set(steps))[:5]}）—— 恒 0 说明 IMU 没在出数，总线处理器却还活着")

    # 6. Frozen: the controller compares the first 12 bytes; 25 identical frames in a row reports frozen
    run = best = 0
    for a, b in zip(windows, windows[1:]):
        run = run + 1 if a == b else 0
        best = max(best, run)
    ok(best < STALE_RUN_MAX,
       f"12 字节窗口最长连续相同 {best} 帧（主控 ≥{STALE_RUN_MAX} 帧就报 frozen）")

    # 7. Whether there are enough frames the controller will accept, and how long until ready
    ok(accepted >= READY_FRAMES,
       f"{frames} 帧里主控会接受 {accepted} 帧（累计 {READY_FRAMES} 帧才 ready）"
       + (f"，{ready_ms:.0f} ms 到 ready" if ready_ms else "，没到 ready"))
    if first_quat_ms is not None:
        log(f"第一个有效四元数在开跑后 {first_quat_ms:.0f} ms", "总线")

    # 8. Timing: count only the bus transaction itself; the criterion is the tick budget, not the timeout
    times.sort()
    p99 = times[max(0, int(len(times) * 0.99) - 1)]
    ok(p99 < TICK_BUDGET_MS,
       f"事务耗时 min {times[0]:.2f} / 平均 {sum(times)/len(times):.2f} / p99 {p99:.2f} / max {times[-1]:.2f} ms"
       f"（预算 {TICK_BUDGET_MS} ms，不是超时 60 ms）")

    # 9. Broadcast PING shouldn't be answered (manual §4.1: broadcast PING can't be used with multiple devices on the bus)
    try:
        bus._send(feetech.BROADCAST, feetech.PING)
        time.sleep(0.01)
        noise = bus.ser.read(64)
        ok(not noise, f"广播 PING 不应答（收到 {len(noise)} 字节）")
    except Exception as e:
        log(f"广播 PING 测试跳过：{type(e).__name__}: {e}", "总线", "warn")

    # 10. Write a register: should be ACKed without affecting the data (the controller never writes it, but the debug console might slip)
    try:
        before = bus.read(sid, BLOCK_ADDR, BLOCK_LEN)[1][:IMU_WINDOW]
        bus.write_u8(sid, 40, 0)
        after = bus.read(sid, BLOCK_ADDR, BLOCK_LEN)[1][:IMU_WINDOW]
        ok(True, "写寄存器不会把板子写坏（写完还能正常读块）")
        log(f"写前后 12 字节：{before.hex()} → {after.hex()}", "总线", "debug")
    except Exception as e:
        ok(False, f"写寄存器以后读不到块了：{type(e).__name__}: {e}")

    log(f"总线统计增量：{dstats}", "总线")
    return out


def run_demo():
    from sim_bus import SimSerial
    port = SimSerial(JOINT_IDS)
    port.latency_ms = 0.25                       # 0.25 ms per packet, close to the on-wire time at 1 Mbps
    port.servos[IMU_ID] = SimImu200(imu_ready_ms=200)
    bus = feetech.FeetechBus(None, ser=port)
    attach_trace(bus)

    print("== 一条 sync_read 同时读 IMU 和 15 颗舵机（主控每 tick 就是这么干的）==")
    for n in range(6):
        got = bus.sync_read(FULL_IDS, BLOCK_ADDR, BLOCK_LEN)
        d = decode_block(got[IMU_ID][1])
        miss = [i for i in JOINT_IDS if got.get(i) is None]
        print(f"  第{n}帧 计数={d['counter']:>3} 陀螺 {d['gyro_dps'][0]:+6.2f},{d['gyro_dps'][1]:+6.2f},"
              f"{d['gyro_dps'][2]:+6.2f} dps  {'主控接受' if d['accepted'] else '融合还没出数'}"
              f"  舵机缺 {len(miss)} 个")
        time.sleep(0.02)

    print("\n== 一致性检查（同一套判据，对真板子就是 check --port）==")
    bad = sum(not g for g, _ in check(bus, frames=60, frame_log=None))

    print("\n== 板子不应答：整条 sync_read 跟着废，15 颗舵机数据一起丢 ==")
    port.servos[IMU_ID].answer = False
    got = bus.sync_read(FULL_IDS, BLOCK_ADDR, BLOCK_LEN)
    lost = [i for i in FULL_IDS if got.get(i) is None]
    print(f"  IMU 不答这一帧，{len(lost)}/{len(FULL_IDS)} 个设备的数据没了：{lost[:6]}…")
    port.servos[IMU_ID].answer = True

    print("\n== 坏固件示例：四元数 norm² = 2（主控会拒绝，工具必须也拒绝）==")
    bad_blk = struct.pack("<hhh", 0, 0, 0) + struct.pack("<HHH", f32_to_f16(1.0), f32_to_f16(1.0),
                                                         f32_to_f16(0.0)) + bytes([9, 0, 0])
    d = decode_block(bad_blk)
    print(f"  norm²={d['norm_sq']:.2f} → 主控接受？{d['accepted']}（应该是 False）")
    print(f"\n日志在 {LOG_DIR}")
    return bad


def run_vectors():
    def frame(sid, instr, params):
        ln = len(params) + 2
        body = [sid, ln, instr] + list(params)
        return "ff ff " + " ".join(f"{b:02x}" for b in body + [(~sum(body)) & 0xFF])

    print("主控每 tick 发的完整 sync_read（16 个 ID，200 在最前）：")
    print("  " + frame(0xFE, feetech.SYNC_READ, [BLOCK_ADDR, BLOCK_LEN] + FULL_IDS))
    print("\n只问 200 的简化版（调试用）：")
    print("  " + frame(0xFE, feetech.SYNC_READ, [BLOCK_ADDR, BLOCK_LEN, IMU_ID]))
    print("\nPING 200：")
    print("  " + frame(IMU_ID, feetech.PING, []))
    print("\n应答 · 融合还没出数（四元数全 0，状态 BIT0=1，计数 0）：")
    blk = encode_block(counter=0, status=0x01)
    print("  " + frame(IMU_ID, 0x00, list(blk)) + "\n  数据段 " + " ".join(f"{b:02x}" for b in blk))
    print("\n应答 · 有数（陀螺 +1.75/−0.875/+0.0525 dps，四元数 z=0.3827，计数 7）：")
    blk = encode_block(gyro_dps=(1.75, -0.875, 0.0525), quat_xyz=(0.0, 0.0, 0.3827), counter=7)
    print("  " + frame(IMU_ID, 0x00, list(blk)) + "\n  数据段 " + " ".join(f"{b:02x}" for b in blk))
    d = decode_block(blk)
    print(f"\n解回来：陀螺 {d['gyro_raw']} LSB，四元数 {d['quat_packed']}（half），"
          f"主控接受={d['accepted']}，躯干系重力 {tuple(round(v, 3) for v in d['gravity'])}")


def main():
    ap = argparse.ArgumentParser(description="ID 200 IMU 块：模拟、测试向量、真板子检查")
    ap.add_argument("cmd", choices=["demo", "vectors", "check"])
    ap.add_argument("--port", help="真板子在哪个串口（check 用）")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--only-imu", action="store_true", help="只问 200，不带 15 颗舵机")
    a = ap.parse_args()
    if a.cmd == "demo":
        sys.exit(run_demo() and 1)
    if a.cmd == "vectors":
        return run_vectors()
    if not a.port:
        sys.exit("check 要 --port，例如 --port COM6")
    bus = feetech.FeetechBus(a.port, a.baud)
    attach_trace(bus)
    os.makedirs(LOG_DIR, exist_ok=True)
    fl = open(os.path.join(LOG_DIR, f"imu200-frames-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"),
              "w", encoding="utf-8")
    try:
        log(f"对着 {a.port} @ {a.baud} 检查 ID {IMU_ID}，{a.frames} 帧", "总线")
        bad = sum(not g for g, _ in check(bus, frames=a.frames,
                                          full_bus=not a.only_imu, frame_log=fl))
        print("\n全部通过" if not bad else f"\n{bad} 项没过")
        print(f"日志：{LOG_DIR}")
        sys.exit(1 if bad else 0)
    finally:
        fl.close()
        bus.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
