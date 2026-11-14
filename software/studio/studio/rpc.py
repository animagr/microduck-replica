"""JSON-RPC client for robotd / configd.

Wire format (top of duck-ipc-proto/src/lib.rs): JSON-RPC 2.0, one object per line (NDJSON).
    → {"jsonrpc":"2.0","id":1,"method":"robot.health","params":{}}
    ← {"jsonrpc":"2.0","id":1,"result":{...}}
Messages without an id are notifications (the subscribed robot.state is one).

robotd handles **only one request at a time** per connection: read a line, answer a line. Therefore:
- A Conn has only one request waiting for a reply at any time (queued with a lock);
- On timeout, close the connection and reconnect on next use. Otherwise the timed-out request keeps blocking the front,
  and late replies don't match up either;
- Relax gets its own connection (see robotd.py) and doesn't queue behind slow requests.

Addresses are always written as strings, so the rest of the code doesn't care which kind is used:
    unix:/run/robotd.sock      on the duck
    tcp:127.0.0.1:17001        on a computer (Python on Windows has no AF_UNIX), connecting to a fake robotd

"Main program missing" and "slow to answer" must be kept apart: socket file missing, connection refused → Unreachable;
connected but no reply in time → Timeout. The UI shows "主程序不在" (main program missing) for one and "主程序没回话" (main program not responding) for the other.
"""
import asyncio
import itertools
import json
import os

LINE_LIMIT = 1 << 20      # busStatus measured at 16.9 KB; the default 64 KiB limit would be hit sooner or later, so raise it to 1 MiB


class RpcError(Exception):
    """The peer replied with an error. For code see error_code in lib.rs (-32602 invalid params, 1 busy, ...)."""

    def __init__(self, method, code, message, data=None):
        super().__init__(f"{method}：{message}（code {code}）")
        self.method, self.code, self.message, self.data = method, code, message, data


class Unreachable(Exception):
    """Cannot connect: socket missing, connection refused, connection closed by the peer."""


class Timeout(Exception):
    """Connected, but no reply in time."""


def parse_addr(addr):
    if addr.startswith("unix:"):
        return ("unix", addr[5:])
    if addr.startswith("tcp:"):
        host, _, port = addr[4:].rpartition(":")
        return ("tcp", host or "127.0.0.1", int(port))
    raise ValueError(f"地址要写成 unix:/路径 或 tcp:主机:端口，现在是 {addr!r}")


async def open_conn(addr):
    kind, *rest = parse_addr(addr)
    try:
        if kind == "unix":
            path = rest[0]
            if not hasattr(asyncio, "open_unix_connection"):
                raise Unreachable("这台电脑的 Python 不支持 unix socket，地址改用 tcp:")
            if not os.path.exists(path):
                raise Unreachable(f"{path} 不在（主程序没在跑）")
            return await asyncio.open_unix_connection(path, limit=LINE_LIMIT)
        host, port = rest
        return await asyncio.open_connection(host, port, limit=LINE_LIMIT)
    except Unreachable:
        raise
    except (ConnectionRefusedError, FileNotFoundError) as e:
        raise Unreachable(f"连不上 {addr}：拒绝连接") from e
    except OSError as e:
        raise Unreachable(f"连不上 {addr}：{type(e).__name__}: {e}") from e


def encode(rid, method, params):
    return (json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                       ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


async def read_message(reader, timeout):
    """Read one line and parse it as JSON. Over-long lines and the peer closing the connection count as Unreachable; garbage returns None (caller skips it)."""
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout)
    except asyncio.TimeoutError:
        raise
    except (ValueError, asyncio.LimitOverrunError) as e:      # a line longer than LINE_LIMIT
        raise Unreachable(f"对方发来的一行太长（超过 {LINE_LIMIT} 字节）") from e
    except (ConnectionError, OSError, asyncio.IncompleteReadError) as e:
        raise Unreachable(f"连接断了：{type(e).__name__}: {e}") from e
    if not raw:
        raise Unreachable("对方关了连接")
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None      # things like [1,2,3] or "x" are also skipped as garbage


class Conn:
    """One serial connection. call() runs queued; timeouts and disconnects close the connection, and the next call() reconnects automatically."""

    def __init__(self, addr, name="rpc", log=None):
        self.addr, self.name, self.log = addr, name, log
        self._r = self._w = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)
        self.connected = False
        self.reconnects = 0
        self.bad_lines = 0

    @property
    def busy(self):
        return self._lock.locked()

    async def call(self, method, params=None, timeout=2.0):
        """timeout includes connecting (the connection may hang forever when robotd is stuck)."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            if self._w is None:
                try:
                    await asyncio.wait_for(self._connect(), timeout)
                except asyncio.TimeoutError:
                    self._close()
                    raise Timeout(f"{method}：{timeout:g} 秒没连上") from None
            rid = next(self._ids)
            try:
                self._w.write(encode(rid, method, params))
                await self._w.drain()
                while True:
                    left = deadline - loop.time()
                    if left <= 0:
                        raise asyncio.TimeoutError
                    msg = await read_message(self._r, left)
                    if msg is None:
                        self.bad_lines += 1
                        continue
                    if msg.get("id") == rid:
                        break
                    # A notification, or a late reply to an earlier timed-out request: drop it
            except asyncio.TimeoutError:
                self._close()
                raise Timeout(f"{method} {timeout:g} 秒没回话") from None
            except Unreachable:
                self._close()
                raise
            except (ConnectionError, OSError) as e:
                self._close()
                raise Unreachable(f"连接断了：{type(e).__name__}: {e}") from e
            except asyncio.CancelledError:
                # When the caller is cancelled, the request may already have been sent: robotd will still process it in order and send a late reply.
                # Close the connection so later requests don't queue behind it or read its reply
                self._close()
                raise
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            raise RpcError(method, err.get("code"), err.get("message", ""), err.get("data"))
        return msg.get("result")

    async def _connect(self):
        self._r, self._w = await open_conn(self.addr)
        if self.connected is False and self.reconnects:
            # Fixed wording, with the count in the raw text: repeated reconnects within 1 minute are deduplicated and merged, so they don't flood the log
            self._note("info", f"跟主程序的 {self.name} 连接恢复", raw=f"第 {self.reconnects} 次重连")
        self.connected = True

    def _close(self):
        if self._w is not None:
            try:
                self._w.close()
            except Exception:  # noqa: BLE001 -- no error matters when closing the connection
                pass
        self._r = self._w = None
        if self.connected:
            self.reconnects += 1
        self.connected = False

    def close(self):
        self._close()

    def _note(self, level, msg, raw=None):
        if self.log:
            self.log.write(msg, cat="robotd", level=level, raw=raw)


async def call_once(addr, method, params=None, timeout=2.0, name="once", log=None):
    """Open a new connection, ask once, close it. Relax uses this: with no long-lived connection, it never hits an old connection that died after robotd restarted.
    Connecting to a local socket takes under 1 millisecond."""
    c = Conn(addr, name, log)
    try:
        return await c.call(method, params, timeout)
    finally:
        c.close()
