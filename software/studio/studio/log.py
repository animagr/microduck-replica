"""Studio's logging: categories, levels, persistence to disk; errors state which step they got stuck at, to help people locate problems.

Each log entry goes to three places:
- the file `logs/studio-日期.log` (日期 = date): one entry per line, time to the millisecond with time zone, errors with traceback and context.
  When something goes wrong this file is the scene: exporting a diagnostics bundle, posting to the group, or having Claude read it directly all start from it;
- the latest 500 entries in memory: the page fetches these first when opened, then gets live pushes;
- stdout: systemd collects it into the journal (`journalctl -u microduck-studio`).

How to write an error clearly (the Chinese strings below are literal UI text: "stand-up failed", hint "the duck's main program is still starting, retry in 10 s"):
    log.error("站起来没成功", cat="robotd", step="robot.init",
              raw="bus not ready: waiting_for_bus", hint="鸭子主程序还在启动，等 10 秒再试",
              ctx={"mode": "motion", "phase": "waiting_for_bus"})
In the file it's one line: …[robotd][错误] 站起来没成功 · 卡在：robot.init · 原文：… · 建议：… · 现场：{…} ([error] stand-up failed · stuck at · raw · suggestion · context)
The page shows "站起来没成功 · 卡在 robot.init" (stand-up failed · stuck at robot.init), and expanding it shows the raw text, suggestion, and context.

Logging is built around "for each command, record the request, ack, and duration"; the code is our own;
on errors, the state at the time is kept together with robotd's system log; things like passwords are masked automatically; time to the millisecond.
A single TOF connection repeatedly disconnecting can spam 8700+ lines and bury the few useful ones, so here the same event
is logged only once per minute, with later occurrences merged into a count.

SD card lifetime: keep only the last 14 days, at most 50 MB total; debug level isn't persisted by default; file writes happen in a background thread,
so they don't block the event loop.
"""
import asyncio
import json
import os
import queue
import re
import threading
import time
import traceback
from collections import deque
from pathlib import Path

CATS = ["系统", "连接", "网络", "robotd", "命令", "安全", "总线", "校准", "IMU", "手柄", "页面", "电池", "调参"]
LEVELS = ["debug", "info", "warn", "error"]
_TAG = {"debug": "[调试]", "info": "", "warn": "[警告]", "error": "[错误]"}

KEEP_DAYS = 14
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024    # once a single file (one day) exceeds this, only warnings and errors are still logged
MAX_SECRETS = 64
RING = 500
DEDUP_WINDOW_S = 60
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Masking by key name: values of these keys never enter the logs (the home Wi-Fi psk goes through here)
SECRET_KEYS = frozenset({"psk", "password", "passwd", "secret", "token", "authorization"})


def redact(value):
    """Replace values of sensitive keys in a dict with "[已隐藏]" ([hidden]); nested dicts and lists too (raw text that is JSON goes through here as well)."""
    if isinstance(value, dict):
        return {k: ("[已隐藏]" if isinstance(k, str) and k.lower() in SECRET_KEYS else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def _stamp(ts):
    """2026-10-18T09:41:07.123+08:00"""
    lt = time.localtime(ts)
    off = time.strftime("%z", lt)
    return time.strftime("%Y-%m-%dT%H:%M:%S", lt) + f".{int(ts * 1000) % 1000:03d}" + (off[:3] + ":" + off[3:] if off else "")


class Log:
    def __init__(self, directory, prefix="studio", echo=True, background=True):
        self.dir = Path(directory)
        self.prefix = prefix
        self.echo = echo
        self.debug_to_file = False
        self._lock = threading.Lock()
        self._ring = deque(maxlen=RING)
        self._n = 0
        self._day = None
        self._day_bytes = 0
        self._capped = False
        self._listeners = set()      # (loop, queue): the page's WebSocket subscriptions
        self._secrets = set()
        self._seen = {}              # (cat, level, msg) -> [time of first occurrence, how many more times since]
        self.counts = {lv: 0 for lv in LEVELS}
        self.write_errors = 0        # number of times writing the log itself failed (visible in the diagnostics bundle)
        self._q = queue.SimpleQueue() if background else None
        if background:
            threading.Thread(target=self._writer, name="studio-log", daemon=True).start()

    # ---- Writing ----

    def hide(self, value):
        """From now on, any occurrence of this string in the logs is replaced with "[已隐藏]" ([hidden]) (passwords, tokens)."""
        if value and len(value) >= 4:
            with self._lock:
                if len(self._secrets) < MAX_SECRETS:
                    self._secrets.add(str(value))

    def write(self, msg, cat="系统", level="info", step=None, raw=None, hint=None, ctx=None,
              exc=False, dedup=True):
        """cat: see CATS; level: see LEVELS.
        step: which step it got stuck at (API name, which step of the flow); raw: the raw error or returned text; hint: suggested fix;
        ctx: context (mode, pose, battery at the time…, a dict); exc=True writes the current exception's traceback to the file;
        dedup=False: log every time (e.g. a command's request and ack).

        **Never raises**: a line must be logged before relax is sent, and a logging error must not block relaxing (re-review #1)."""
        try:
            return self._write(msg, cat, level, step, raw, hint, ctx, exc, dedup)
        except Exception:  # noqa: BLE001
            self.write_errors += 1
            return None

    def _write(self, msg, cat, level, step, raw, hint, ctx, exc, dedup):
        if level not in LEVELS:
            level = "info"
        now = time.time()
        msg, raw, hint, step = (self._clean(x) for x in (msg, raw, hint, step))
        tb = self._clean(traceback.format_exc()) if exc else ""
        ctx_text = self._clean(json.dumps(redact(ctx), ensure_ascii=False, default=str)) if ctx else None
        with self._lock:
            if dedup:
                key = (cat, level, msg)
                seen = self._seen.get(key)
                if seen and now - seen[0] < DEDUP_WINDOW_S:
                    seen[1] += 1
                    return None
                if seen and seen[1]:
                    self._emit_locked(now, cat, level, f"（上一条「{msg}」在 1 分钟内又出现了 {seen[1]} 次，已合并）")
                self._seen[key] = [now, 0]
                if len(self._seen) > 2000:
                    self._seen = {k: v for k, v in self._seen.items() if now - v[0] < DEDUP_WINDOW_S}
            return self._emit_locked(now, cat, level, msg, step, raw, hint, ctx_text, tb)

    def _emit_locked(self, now, cat, level, msg, step=None, raw=None, hint=None, ctx=None, tb=""):
        parts = [f"{_stamp(now)} [{cat}]{_TAG[level]} {msg}"]
        if step:
            parts.append(f"卡在：{step}" if level in ("warn", "error") else f"步骤：{step}")
        if raw:
            parts.append(f"原文：{raw}")
        if hint:
            parts.append(f"建议：{hint}")
        if ctx:
            parts.append(f"现场：{ctx}")
        line = " · ".join(parts)
        self.counts[level] += 1
        if level != "debug" or self.debug_to_file:
            self._to_file(now, line + "\n" + tb, level in ("warn", "error"))
        entry = None
        if level != "debug":
            self._n += 1
            entry = {"n": self._n, "ts": now, "t": time.strftime("%H:%M:%S", time.localtime(now)),
                     "cat": cat, "level": level, "msg": msg, "step": step, "raw": raw, "hint": hint, "ctx": ctx}
            self._ring.append(entry)
            for loop, q in list(self._listeners):
                try:
                    loop.call_soon_threadsafe(_offer, q, entry)
                except RuntimeError:      # the event loop is already closed
                    pass
        if self.echo:
            try:
                # stdout may no longer be writable (SSH window closed, journald stuck): drop this copy, the file and page copies are still there
                print(line + ("\n" + tb.rstrip() if tb else ""), flush=True)
            except Exception:  # noqa: BLE001
                self.write_errors += 1
        return entry

    def debug(self, msg, **kw):
        return self.write(msg, level="debug", **kw)

    def info(self, msg, **kw):
        return self.write(msg, level="info", **kw)

    def warn(self, msg, **kw):
        return self.write(msg, level="warn", **kw)

    def error(self, msg, **kw):
        return self.write(msg, level="error", **kw)

    # ---- Reading ----

    def recent(self, limit=200, cats=None, min_level="info"):
        floor = LEVELS.index(min_level) if min_level in LEVELS else 1
        with self._lock:
            items = [e for e in self._ring
                     if LEVELS.index(e["level"]) >= floor and (not cats or e["cat"] in cats)]
        return items[-limit:]

    def subscribe(self, loop=None, maxsize=200):
        """Live log for the page: returns an asyncio.Queue that drops the oldest when full (a slow page doesn't hold up whoever is logging)."""
        loop = loop or asyncio.get_running_loop()
        q = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._listeners.add((loop, q))
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._listeners = {(lp, qq) for lp, qq in self._listeners if qq is not q}

    def files(self, days=2):
        """For the diagnostics bundle: log files from the last `days` days, newest last."""
        self.flush()
        if not self.dir.is_dir():
            return []
        return sorted(self.dir.glob(f"{self.prefix}-*.log"))[-days:]

    def snapshot(self):
        with self._lock:
            return {"counts": dict(self.counts), "last_n": self._n, "dir": str(self.dir),
                    "write_errors": self.write_errors}

    def flush(self, timeout=2.0):
        """Wait for the background thread to finish writing queued lines (used when exporting a diagnostics bundle and before exiting)."""
        if self._q is None:
            return
        done = threading.Event()
        self._q.put(done)
        done.wait(timeout)

    # ---- Files ----

    def _clean(self, text):
        if text is None:
            return None
        text = _ANSI.sub("", str(text))
        for s in self._secrets:
            text = text.replace(s, "[已隐藏]")
        return text

    def _to_file(self, now, text, important=False):
        if self._q is not None:
            self._q.put((now, text, important))
        else:
            self._append(now, text, important)

    def _writer(self):
        while True:
            item = self._q.get()
            if isinstance(item, threading.Event):
                item.set()
                continue
            self._append(*item)

    def _append(self, now, text, important=False):
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{self.prefix}-{day}.log"
            if day != self._day:
                self._day = day
                self._prune()
                self._day_bytes = _size(path)
                self._capped = False
            if self._day_bytes > MAX_FILE_BYTES:
                # Spam protection: 20 MB already written today, ordinary lines are no longer written to the file (the page shows them as usual), warnings and errors are still written
                if not important:
                    if not self._capped:
                        self._capped = True
                        text = f"（今天的日志超过 {MAX_FILE_BYTES >> 20} MB，后面只记警告和错误）\n"
                    else:
                        return
                elif self._day_bytes > MAX_FILE_BYTES * 2:
                    return
            data = text.encode("utf-8")
            with open(path, "ab") as f:
                f.write(data)
            self._day_bytes += len(data)
        except OSError:
            # Failing to write the file (card full, read-only) must not make the caller fail either; the stdout copy is still there
            pass

    def _prune(self):
        """Keep only the last KEEP_DAYS days; when the total exceeds MAX_TOTAL_BYTES, delete starting from the oldest (today's is never deleted)."""
        logs = sorted(self.dir.glob(f"{self.prefix}-*.log"))
        today = self.dir / f"{self.prefix}-{self._day}.log"
        old = [p for p in logs if p != today]
        excess = len(old) - (KEEP_DAYS - 1)
        for p in old[:max(excess, 0)]:
            _unlink(p)
        logs = sorted(self.dir.glob(f"{self.prefix}-*.log"))
        total = sum(_size(p) for p in logs)
        for p in logs:
            if total <= MAX_TOTAL_BYTES:
                break
            if p == today:      # when the clock is stuck at 1970, today's file sorts first: skip it and keep deleting, don't stop here
                continue
            total -= _size(p)
            _unlink(p)


def _offer(q, entry):
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(entry)


def _size(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _unlink(p):
    try:
        p.unlink()
    except OSError:
        pass


class Timer:
    """Log one command's round trip ("站起来" = stand up):
        with log_cmd(log, "站起来", "robot.init", ctx=...) as t:
            reply = await ...
            t.ok(reply)        # or t.fail("reason", raw=..., hint=...)
    One line each for request, ack, and duration (not merged), with context on failure."""

    def __init__(self, log, what, step, who=None, args=None, ctx=None):
        self.log, self.what, self.step, self.ctx = log, what, step, ctx
        self.t0 = time.monotonic()
        self.done = False
        detail = f"（{who}）" if who else ""
        self.log.write(f"→ {what}{detail}", cat="命令", step=step,
                       raw=json.dumps(redact(args), ensure_ascii=False) if args else None, dedup=False)

    def ms(self):
        return int((time.monotonic() - self.t0) * 1000)

    def ok(self, reply=None, note=""):
        self.done = True
        self.log.write(f"← {self.what} 成功 · {self.ms()} ms{(' · ' + note) if note else ''}", cat="命令",
                       step=self.step, raw=_brief(reply), dedup=False)

    def fail(self, why, raw=None, hint=None, ctx=None):
        self.done = True
        self.log.write(f"← {self.what} 没成功：{why} · {self.ms()} ms", cat="命令", level="error",
                       step=self.step, raw=_brief(raw), hint=hint, ctx=ctx or self.ctx, dedup=False)

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is not None and not self.done:
            self.fail(f"{et.__name__}: {ev}")
        elif not self.done:
            self.ok()
        return False


def _brief(x, limit=600):
    if x is None:
        return None
    s = x if isinstance(x, str) else json.dumps(redact(x), ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + f"…（共 {len(s)} 字）"


def log_cmd(log, what, step, **kw):
    return Timer(log, what, step, **kw)


def to_json(entry):
    return json.dumps(entry, ensure_ascii=False)


_default = None


def setup(directory, **kw):
    """Only one is created per process; each module does `from studio.log import get; log = get()`."""
    global _default
    _default = Log(directory, **kw)
    return _default


def get():
    if _default is None:
        return setup(os.path.join(os.getcwd(), "logs"))
    return _default
