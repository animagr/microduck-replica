# -*- coding: utf-8 -*-
"""Protocol-level HD-1910 simulator: pretends to be a serial port, receives Feetech instruction packets, and replies with status packets according to the register table.

Unlike FakeBus in server.py: FakeBus simulates the high-level interface and can't test feetech.py;
this one lets the real FeetechBus send and receive bytes against it, with packet format, checksum, sync read/write, lock, torque and the preconditions for center calibration all behaving like the real servo.

  bus = feetech.FeetechBus(None, ser=SimSerial([20, 21, ...]))

Simulated real-servo behaviors (with sources):
- Writing 128 to the torque switch: HD-1910 (firmware 3.46) replies "success" but does nothing (4 rounds of hardware tests on 2026-09-20, same with unlocked and torque off;
  the protocol manual also says HLS ≥3.43 doesn't support it). With accept_128=True it follows STS rules: calibrates only when lock flag = 0 and torque switch = 0
- 0x0B position calibration: the reading at the current position becomes the parameter value (no parameter = 2048). support_0b=False simulates a servo that doesn't accept this instruction
- Offset register 31: offset_adds controls whether "position = raw + offset" or "raw − offset"; the manual doesn't pin it down, so both can be simulated
- Gravity sag: once torque is off, a joint mounted on the duck drops (hardware test on the neck: 80 steps in 130 ms ≈ 0.62 steps/ms).
  droop is set to steps dropped per millisecond; without simulating this, bugs like "waiting too long after torque-off calibrates the sagged position as zero" can't be caught
- Bus latency: on the real robot each round trip (send packet + wait for reply + USB latency timer) is about 1~2 ms. latency_ms simulates it
  and also drives a virtual clock: sag is computed on this clock, so tests are deterministic regardless of machine speed; time.sleep is counted too
- The register table ends at 86; reading past the end returns only the remaining bytes (hardware test: reading 10 from 80 returns 7)
- Bit 15 of position, speed and current is the sign bit; offset register 31 also records the sign in bit 15 (34279 = -1511 has been read on real hardware)
- REBOOT (0x08) returns no packet
"""
import struct
import time

import feetech

TABLE_END = 87


def enc15(v):
    return (0x8000 | (-v & 0x7FFF)) if v < 0 else (v & 0x7FFF)


class SimServo:
    def __init__(self, sid, phys=2048):
        self.r = bytearray(TABLE_END)
        r = self.r
        r[0], r[1], r[2], r[3], r[4] = 3, 46, 0, 3, 10      # firmware 3.46, END=0 little-endian
        r[5], r[6], r[8] = sid, 0, 1                        # ID, baud rate 1M, reply level 1
        struct.pack_into("<HH", r, 9, 0, 4095)
        r[13], r[15] = 70, 40
        struct.pack_into("<H", r, 16, 1000)
        r[18], r[21], r[22], r[33] = 52, 32, 32, 4          # phase 52, P/D 32, mode 4
        struct.pack_into("<H", r, 48, 1000)
        r[55] = 1                                           # locked from the factory
        r[62], r[63] = 74, 30
        self.phys = phys          # physical encoder reading (without offset)
        self.off = 0              # offset: reported position = phys + off
        self.goal = None
        self.calibrations = 0     # how many center calibrations were actually done, for tests
        self.muted = set()        # reading these addresses returns no packet, simulating a dropout midway
        self.accept_128 = False   # HD-1910 doesn't accept 128
        self.support_0b = True
        self.ignore_offset_writes = False   # simulates a servo that doesn't even accept offset writes
        self.offset_adds = True   # reported position = phys + off; when False = phys − off (the manual doesn't pin it down, both must work)
        self.droop = 0.0          # steps dropped per millisecond while torque is off; measured 0.62 on the real neck
        self._t = 0.0             # bus virtual clock at the last tick (ms)
        self.mute_after_calib = set()   # as soon as a calibration finishes, add these addresses to muted

    @property
    def id(self):
        return self.r[5]

    def pos(self):
        return self.phys + (self.off if self.offset_adds else -self.off)

    def tick(self, clock_ms=0.0):
        """With torque on, go straight to the target (the simulator ignores dynamics); with torque off, drop by droop.

        clock_ms is the bus's virtual clock, advanced by SimSerial using per-packet latency and real sleeps."""
        dt_ms, self._t = clock_ms - self._t, clock_ms
        if self.r[40] == 1 and self.goal is not None:
            self.phys = self.goal - (self.off if self.offset_adds else -self.off)
        elif self.droop:
            self.phys -= self.droop * dt_ms
        p = round(self.pos())
        struct.pack_into("<H", self.r, 56, enc15(p))
        struct.pack_into("<H", self.r, 67, enc15(self.goal if self.goal is not None else p))
        struct.pack_into("<H", self.r, 31, enc15(self.off))

    def write(self, addr, data):
        for k, b in enumerate(data):
            a = addr + k
            if a >= TABLE_END:
                break
            if a == 40 and b == 128:
                if self.accept_128 and self.r[40] == 0 and self.r[55] == 0:
                    self.recalibrate(2048)
                continue                                     # reply success, do nothing
            self.r[a] = b
        # Commit multi-byte registers
        if addr <= 42 < addr + len(data):
            self.goal = feetech.sign15(struct.unpack_from("<H", self.r, 42)[0])
        if addr <= 31 < addr + len(data) and not self.ignore_offset_writes:
            self.off = feetech.sign15(struct.unpack_from("<H", self.r, 31)[0])
        if addr <= 40 < addr + len(data) and self.r[40] == 1 and self.goal is None:
            self.goal = self.pos()

    def recalibrate(self, value):
        # phys is fractional because of sag, so the offset must be rounded: real servo registers can only hold integers
        self.off = round((value - self.phys) if self.offset_adds else (self.phys - value))
        self.calibrations += 1
        self.muted |= self.mute_after_calib

    def read(self, addr, n, clock_ms=0.0):
        self.tick(clock_ms)
        return bytes(self.r[addr:min(addr + n, TABLE_END)])


class SimSerial:
    """Fake serial port: write() receives instructions and generates replies from the servos on the bus; read() spits the replies out."""

    def __init__(self, ids, phys=None):
        self.timeout = 0.02
        self.servos = {i: SimServo(i, (phys or {}).get(i, 2048)) for i in ids}
        self.rx = bytearray()
        self.latency_ms = 0.0     # ms per round trip; about 1~2 on the real URT-2
        self.clock = 0.0          # bus virtual clock (ms): +latency per packet, plus real time the caller spent sleeping
        self._wall = time.monotonic()

    # ---- Serial port interface ----
    def reset_input_buffer(self):
        self.rx.clear()

    def read(self, n=1):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def close(self):
        pass

    def write(self, data):
        data = bytes(data)
        while len(data) >= 6:
            if data[0] != 0xFF or data[1] != 0xFF:
                data = data[1:]
                continue
            sid, length = data[2], data[3]
            pkt = data[:4 + length]
            data = data[4 + length:]
            instr, params = pkt[4], pkt[5:-1]
            if ((~sum(pkt[2:-1])) & 0xFF) != pkt[-1]:
                continue                                         # checksum error: a real servo ignores it
            self._handle(sid, instr, params)
        return len(data)

    # ---- Servos ----
    def _by_id(self, sid):
        for s in self.servos.values():
            if s.id == sid:
                return s
        return None

    def _advance(self):
        """Advance the virtual clock: latency of one bus round trip, plus real time slept since last time (time.sleep in the code must count toward sag)."""
        now = time.monotonic()
        self.clock += self.latency_ms + (now - self._wall) * 1000
        self._wall = now
        return self.clock

    def _reply(self, s, params=b""):
        s.tick(self.clock)
        err = s.r[65]
        length = len(params) + 2
        body = bytes([s.id, length, err]) + bytes(params)
        self.rx += bytes([0xFF, 0xFF]) + body + bytes([(~sum(body)) & 0xFF])

    def _handle(self, sid, instr, p):
        self._advance()
        if instr == feetech.SYNC_WRITE:
            addr, ln = p[0], p[1]
            rest = p[2:]
            for k in range(0, len(rest), ln + 1):
                s = self._by_id(rest[k])
                if s:
                    s.write(addr, rest[k + 1:k + 1 + ln])
            return
        if instr == feetech.SYNC_READ:
            addr, ln = p[0], p[1]
            for i in p[2:]:
                s = self._by_id(i)
                # alive() is for the fake IMU board: simulates "bus processor not up yet" and "board not answering at all"
                if s and addr not in getattr(s, "muted", ()) and getattr(s, "alive", lambda _: True)(self.clock):
                    self._reply(s, s.read(addr, ln, self.clock))
            return
        s = self._by_id(sid)
        if s is None:
            return
        if instr == feetech.PING:
            if sid == feetech.BROADCAST or not getattr(s, "alive", lambda _: True)(self.clock):
                return                                       # manual: broadcast PING can't be used with multiple devices on the bus
            self._reply(s)
        elif instr == feetech.READ:
            if p[0] in s.muted or not getattr(s, "alive", lambda _: True)(self.clock):
                return
            self._reply(s, s.read(p[0], p[1], self.clock))
        elif instr == feetech.WRITE:
            s.write(p[0], p[1:])
            self._reply(s)                                       # when changing ID, reply with the new ID
        elif instr == feetech.CALIBRATE:
            if s.support_0b:
                s.recalibrate(2048 if len(p) < 2 else feetech.sign15(p[0] | p[1] << 8))
            self._reply(s)
        elif instr == feetech.REBOOT:
            s.r[40] = 0                                          # no reply packet; comes back with torque off
