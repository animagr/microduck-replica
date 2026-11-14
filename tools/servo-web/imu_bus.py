# -*- coding: utf-8 -*-
"""Read the IMU board (ID 200) from the servo TTL bus. By default uses the repo's Feetech protocol 56/15; optionally the DXL2-compatible 124/12.

Servos and the IMU can run different bus protocols: servo state is still decoded with Feetech SCS, and the IMU block is handed to this module.
The Feetech protocol's 15-byte block criteria follow the controller (the fork's duck-control
imu.rs / bus.rs), the same set as tools/imu200/imu200.py:

- All three quaternion components are 0 → fusion hasn't produced output yet (the controller reuses the previous frame and doesn't count it toward ready)
- Not finite / norm² > 1.02 → the controller rejects this frame
- First 12 bytes identical for 25 consecutive frames → the controller reports orientation is frozen
- The reserved byte (byte 14) must be 0; status bits BIT1/BIT2 are faults reported by the board itself

After the board fails to reply 5 times in a row, reading is suspended, and 200 is PINGed separately every 2 s. Feetech mode still uses a sync read covering the IMU and the servos;
DXL2 mode reads the IMU and the servos separately, and the servos always use Feetech requests.
"""
import math
import struct
import threading
import time

from imu_bridge import BridgeError, HOST_STALE_MS, decode_quaternion, empty_frame

IMU_ID = 200
FEETECH_BLOCK_ADDR = 56
FEETECH_BLOCK_LEN = 15
DXL2_BLOCK_ADDR = 124
DXL2_BLOCK_LEN = 12
BLOCK_ADDR = FEETECH_BLOCK_ADDR
BLOCK_LEN = FEETECH_BLOCK_LEN
WINDOW = 12               # the controller only looks at the first 12 bytes, and StaleImuTracker only compares these 12 bytes
FROZEN_FRAMES = 25        # bus.rs: 25 identical consecutive frames reports frozen
GYRO_DPS_PER_LSB = 0.0175
MISS_DEGRADE = 5          # this many consecutive frames with no reply from 200: first remove it from sync_read
RETRY_S = 2.0             # after removal, PING it separately at this interval

BIT_FUSION_NOT_READY = 0x01
BIT_IMU_COMM_FAIL = 0x02
BIT_SELF_TEST_FAIL = 0x04
BIT_READER_TOO_SLOW = 0x08
SLOW_READER_HZ = 30      # firmware BIT3 = more than 4 refreshes between two reads (120 Hz sampling) ≈ reading slower than 30 Hz


def decode_block(block):
    """Decode a Feetech 15-byte block or a DXL2 12-byte block, without coordinate transformation."""
    if len(block) not in (FEETECH_BLOCK_LEN, DXL2_BLOCK_LEN):
        raise BridgeError(f"块长度 {len(block)}，应为 12（DXL2）或 15（飞特）")
    gyro = struct.unpack_from("<3h", block, 0)
    packed = struct.unpack_from("<3H", block, 6)
    is_dxl2 = len(block) == DXL2_BLOCK_LEN
    return {"gyro_raw": list(gyro), "gyro_dps": [v * GYRO_DPS_PER_LSB for v in gyro],
            "quat_fp16": list(packed), "counter": None if is_dxl2 else block[12],
            "bits": 0 if is_dxl2 else block[13], "reserved": 0 if is_dxl2 else block[14],
            "window": bytes(block[:WINDOW])}


class BusImuService:
    """Same interface as BridgeService (start/stop/get_status); data is fed in by the server's status polling."""

    demo = False
    backend = "bus"

    def __init__(self, poll_hz=None, protocol="feetech"):
        # The debug console reads at its own poll_hz (default 10 Hz). Below 30 Hz BIT3 lights up every frame; that's us reading slowly, not the controller, so no warning
        self.poll_hz = poll_hz
        self.protocol = protocol
        self.lock = threading.Lock()
        self.frame = self._frame("disconnected", "等待第一条带 ID 200 的 sync_read。")
        self.last_publish = time.monotonic()
        self.misses = 0
        self.total_misses = 0
        self.excluded_since = None       # when it was removed from sync_read; None = 200 included normally
        self.last_probe = None
        self.last_window = None
        self.same_run = 0
        self.previous_ok = None
        self.smooth_hz = 0.0
        self.frames = 0

    # ---- Lifecycle: no thread of its own, interface aligned with BridgeService ----
    def start(self):
        pass

    def stop(self):
        pass

    def set_protocol(self, protocol):
        if protocol not in ("dxl2", "feetech"):
            raise ValueError(f"不支持的 IMU 总线协议：{protocol}")
        with self.lock:
            if protocol == self.protocol:
                return False
            self.protocol = protocol
            self.misses = 0
            self.excluded_since = None
            self.last_probe = None
            self.last_window = None
            self.same_run = 0
            self.previous_ok = None
            self.smooth_hz = 0.0
            self.frame = self._frame("disconnected", f"已切换到 {protocol}，等待 ID 200 应答。")
            self.last_publish = time.monotonic()
        return True

    def _frame(self, status, message, **extra):
        frame = empty_frame("live", status, message)
        frame.update(backend="bus", probe_name="舵机总线 ID 200", **extra)
        return frame

    def _publish(self, frame):
        frame["timestamp_ms"] = int(time.time() * 1000)
        with self.lock:
            self.frame = frame
            self.last_publish = time.monotonic()

    def get_status(self):
        with self.lock:
            result = dict(self.frame)
            elapsed_ms = (time.monotonic() - self.last_publish) * 1000
        if result["live"] and elapsed_ms >= HOST_STALE_MS:
            result.update(status="stale", live=False, quaternion_xyzw=None, gyro_dps=None, hz=0.0,
                          message="总线轮询停了（没有网页连着，或者正在校准），姿态暂停。")
        return result

    # ---- Polling side ----
    def include_in_sync(self):
        """Whether this frame's sync_read should include 200."""
        return self.excluded_since is None

    def due_probe(self, now=None):
        """While removed, once it's time, 200 should be PINGed separately once."""
        if self.excluded_since is None:
            return False
        now = time.monotonic() if now is None else now
        if self.last_probe is None or now - self.last_probe >= RETRY_S:
            self.last_probe = now
            return True
        return False

    def probe_result(self, answered):
        """Result of the separate PING: if it replied, put it back into sync_read. Returns whether it was put back."""
        if answered and self.excluded_since is not None:
            self.excluded_since = None
            self.misses = 0
            self._publish(self._frame("disconnected", "ID 200 的 PING 有应答了，下一帧重新带上它。"))
            return True
        return False

    def feed(self, block, now=None):
        """block = 200's 15 bytes; None = it didn't reply this frame (or wasn't included). Returns the generated frame."""
        now = time.monotonic() if now is None else now
        if block is None:
            self.misses += 1
            self.total_misses += 1
            if self.misses >= MISS_DEGRADE and self.excluded_since is None:
                self.excluded_since = now
            frame = self._frame("disconnected",
                                f"ID 200 连续 {self.misses} 帧没应答：检查小板供电、总线接线（J1/J2 的 DATA）"
                                f"和 IMU 协议（当前 {self.protocol}）；舵机已改为单独读，每 {RETRY_S:.0f} 秒单独 PING 一次 200。",
                                misses=self.total_misses)
            self._publish(frame)
            return frame
        self.misses = 0
        self.excluded_since = None
        d = decode_block(block)
        extra = {"connected": True, "sample_count": d["counter"], "raw_gyro": d["gyro_raw"],
                 "quat_fp16": d["quat_fp16"], "status_bits": d["bits"] if self.protocol != "dxl2" else None,
                 "misses": self.total_misses,
                 "errors": {"imu": d["bits"] & (BIT_IMU_COMM_FAIL | BIT_SELF_TEST_FAIL), "spi": None,
                            "fifo": None, "quaternion": None, "recovery": None}}
        self.same_run = self.same_run + 1 if d["window"] == self.last_window else 0
        self.last_window = d["window"]
        if d["reserved"] != 0:
            frame = self._frame("error", f"块的保留字节（byte 14）是 {d['reserved']}，规格要求 0：固件不符合总线协议 §3。", **extra)
        elif d["bits"] & BIT_SELF_TEST_FAIL:
            frame = self._frame("error", "小板报告 IMU 自检失败（BIT2，WHO_AM_I 不对）：检查 IMU 芯片焊接。", **extra)
        elif d["bits"] & BIT_IMU_COMM_FAIL:
            frame = self._frame("error", "小板报告跟 IMU 芯片通信失败（BIT1：SPI/复位/配置/FIFO/数据过期）。", **extra)
        elif not any(d["quat_fp16"]) or d["bits"] & BIT_FUSION_NOT_READY:
            frame = self._frame("stale", "IMU 融合还没出数（四元数全 0 / BIT0），刚上电约 0.5 秒内正常。", **extra)
        elif self.same_run + 1 >= FROZEN_FRAMES:
            frame = self._frame("stale", f"前 12 字节连续 {self.same_run + 1} 帧完全相同：主控会报 orientation is frozen。"
                                "真芯片静置时低位也在跳，固件不能平滑或量化陀螺。", **extra)
        else:
            try:
                quaternion = decode_quaternion(tuple(d["quat_fp16"]))
            except BridgeError as exc:
                frame = self._frame("error", f"四元数主控会拒绝：{exc}", **extra)
            else:
                if self.previous_ok is not None:
                    instant = 1.0 / max(1e-4, now - self.previous_ok)
                    self.smooth_hz = instant if self.smooth_hz == 0 else self.smooth_hz * 0.8 + instant * 0.2
                self.previous_ok = now
                slow = ("；BIT3：两次读之间块刷新了 4 次以上，读得太慢"
                        if d["bits"] & BIT_READER_TOO_SLOW
                        and (self.poll_hz is None or self.poll_hz >= SLOW_READER_HZ) else "")
                frame = self._frame("live", "正在从舵机总线读 ID 200（跟主控同一条 sync_read）" + slow + "。",
                                    live=True, quaternion_xyzw=quaternion, gyro_dps=d["gyro_dps"],
                                    hz=round(self.smooth_hz, 1), age_ms=None, **extra)
        self.frames += 1
        self._publish(frame)
        return frame


class FakeImu200:
    """Fake board for the fake bus (--fake): new block at 120 Hz, gyro low bits with jitter, quaternion slowly rotating about Z."""

    def __init__(self, sample_hz=120.0, ready_after_s=0.5):
        self.t0 = time.monotonic()
        self.sample_hz, self.ready_after_s = sample_hz, ready_after_s

    def block(self, now=None):
        t = (time.monotonic() if now is None else now) - self.t0
        n = int(t * self.sample_hz)
        if t < self.ready_after_s:
            return bytes(12) + bytes([n & 0xFF, BIT_FUSION_NOT_READY, 0])
        jitter = (n % 7) - 3
        yaw = 0.6 * math.sin(t * 0.5)
        gyro = (int(17 * math.cos(t * 0.5)) + jitter, jitter, -jitter)
        quat = (0.05, 0.0, math.sin(yaw / 2))   # a slight tilt, so it's never the all-zero "not ready" marker even when z crosses zero
        return (struct.pack("<3h", *gyro) + struct.pack("<3e", *quat)
                + bytes([n & 0xFF, 0, 0]))
