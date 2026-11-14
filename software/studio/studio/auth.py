"""Login, sessions, origin checks.

Why Studio has its own password instead of the Linux radxa password:
- validating against the radxa password would turn the web page into an SSH password guessing oracle, and bypass sshd's PerSourcePenalties;
- the password is set in the installer (the hash is written over during that one SSH session), not "the first time the web page is opened",
  so that whoever on the LAN opens it first does not become the admin (DNS rebinding could also set it for you). During development use the command line:
      python -m studio.auth set-password --state-dir ./state

Sessions:
- 32-byte random token, cookie `HttpOnly; SameSite=Lax; Path=/` (Lax: login is carried even when following a link from a chat app;
  cross-site state-changing requests are blocked by the Origin check and the CSRF token);
- with "remember me" checked it is valid for 30 days, otherwise it expires after 12 hours of inactivity; sessions are saved to disk, so a Studio restart does not require logging in again;
- on password change or logout, the related sessions are invalidated immediately (the page's WebSocket is disconnected by the caller).

Wrong passwords: backoff per source IP; after 5 consecutive failures wait 30 seconds, doubling on each further failure, up to 5 minutes. Only affects the web page, not SSH.

Dangerous operations (direct bus access, writing EEPROM, changing system settings, installing programs): require the password to have been re-entered within 10 minutes, like sudo.

Origin checks (block DNS rebinding and cross-site requests):
- Host only accepts: the hostname, hostname.local, localhost, or "the local IP this connection actually reached";
- state-changing requests and WebSocket handshakes also require Origin to be same-origin with Host. SameSite cannot block other ports on the same duck
  (mediad's 8080 is same-site with Studio), so Origin must always be checked.
"""
import argparse
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

COOKIE = "studio_session"
REMEMBER_S = 30 * 24 * 3600
IDLE_S = 12 * 3600
RECENT_AUTH_S = 600
FAIL_FREE = 5
FAIL_BASE_S = 30
FAIL_MAX_S = 300
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
FLUSH_EVERY_S = 300


def _hash(password, salt, n, r, p, dklen):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen,
                          maxmem=64 * 1024 * 1024)


def _write_private(path, data):
    """Atomic write, mode 0600: write a temp file first and then rename, so a power loss halfway never leaves a broken file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


class Auth:
    def __init__(self, state_dir, log=None):
        self.dir = Path(state_dir)
        self.pw_path = self.dir / "password.json"
        self.sess_path = self.dir / "sessions.json"
        self.log = log
        self._lock = threading.Lock()
        self._sessions = {}
        self._fails = {}
        self._dirty_at = None
        self._load_sessions()

    # ---- Password ----

    def has_password(self):
        return self.pw_path.is_file()

    def set_password(self, password, keep_token=None):
        if len(password) < 6:
            raise ValueError("密码至少 6 位")
        salt = secrets.token_bytes(16)
        digest = _hash(password, salt, **SCRYPT)
        _write_private(self.pw_path, {"scrypt": {**SCRYPT, "salt": salt.hex(), "hash": digest.hex()},
                                      "set_at": int(time.time())})
        kept = False
        with self._lock:
            if keep_token and keep_token in self._sessions:
                self._sessions = {keep_token: self._sessions[keep_token]}
                kept = True
                self._flush_locked()
            else:
                self._sessions.clear()
                self._flush_locked()
        self._log("info", "管理员密码已更新，其他登录全部作废" if kept else "管理员密码已更新，旧的登录全部作废")

    def clear_password(self):
        """Clear the admin password, back to "usable by anyone who opens it on the same network". Like set_password, only touches Studio's own files."""
        try:
            self.pw_path.unlink()
        except FileNotFoundError:
            pass
        self.revoke_all()
        self._log("info", "管理员密码已清掉，Studio 回到不用登录的模式")

    def check_password(self, password):
        try:
            rec = json.loads(self.pw_path.read_text(encoding="utf-8"))["scrypt"]
            want = bytes.fromhex(rec["hash"])
            got = _hash(password, bytes.fromhex(rec["salt"]), rec["n"], rec["r"], rec["p"], rec["dklen"])
        except (OSError, ValueError, KeyError):
            return False
        return hmac.compare_digest(want, got)

    # ---- Login ----

    def login(self, password, ip, remember=False):
        """Returns (token, None, 0); on failure returns (None, reason, seconds still to wait)."""
        now = time.time()
        with self._lock:
            f = self._fails.get(ip)
            if f and f["until"] > now:
                wait = int(f["until"] - now) + 1
                return None, f"输错太多次了，{wait} 秒后再试", wait
        if not self.has_password():
            return None, "还没设管理员密码：用安装器设，或者在鸭子上运行 set-password", 0
        # Record a failure first, then compute the hash: even with concurrent attempts, every one is already on the books (cleared again on success)
        with self._lock:
            if len(self._fails) > 1000:
                self._fails = {k: v for k, v in self._fails.items() if v["until"] > now or now - v["at"] < 3600}
            f = self._fails.setdefault(ip, {"n": 0, "until": 0, "at": now})
            f["n"] += 1
            f["at"] = now
            wait = 0
            if f["n"] >= FAIL_FREE:
                wait = min(FAIL_BASE_S * 2 ** (f["n"] - FAIL_FREE), FAIL_MAX_S)
                f["until"] = now + wait
            n = f["n"]
        if not self.check_password(password):
            self._log("warn", "登录失败", cat="连接", raw=f"来自 {ip}，连续第 {n} 次")
            return None, "密码不对" + (f"，{wait} 秒后再试" if wait else ""), wait
        token = secrets.token_urlsafe(32)
        sess = {"created": now, "last": now, "remember": bool(remember), "ip": ip,
                "csrf": secrets.token_urlsafe(24), "auth_at": now}
        with self._lock:
            self._fails.pop(ip, None)
            self._sessions = {t: v for t, v in self._sessions.items() if not self._expired(v, now)}
            self._sessions[token] = sess
            self._flush_locked()
        self._log("info", f"登录成功（来自 {ip}{'，记住 30 天' if remember else ''}）", cat="连接")
        return token, None, 0

    def session(self, token, touch=True):
        """Return the session if valid, otherwise None. touch=True also updates the last activity time (when there is a real request);
        the WebSocket periodic check uses touch=False, since a page being open does not mean someone is using it."""
        if not token:
            return None
        now = time.time()
        with self._lock:
            s = self._sessions.get(token)
            if not s:
                return None
            if self._expired(s, now):
                self._sessions.pop(token, None)
                self._flush_locked()
                return None
            if not touch:
                return dict(s)
            s["last"] = now
            if self._dirty_at is None:
                self._dirty_at = now
            elif now - self._dirty_at > FLUSH_EVERY_S:
                self._flush_locked()
            return dict(s)

    def reauth(self, token, password):
        """Re-enter the password before a dangerous operation."""
        if not self.check_password(password):
            return False
        with self._lock:
            s = self._sessions.get(token)
            if not s:
                return False
            s["auth_at"] = time.time()
            self._flush_locked()
        return True

    @staticmethod
    def recent_auth(sess):
        return bool(sess) and time.time() - sess.get("auth_at", 0) < RECENT_AUTH_S

    def logout(self, token):
        with self._lock:
            if self._sessions.pop(token, None) is not None:
                self._flush_locked()

    def revoke_all(self):
        with self._lock:
            self._sessions.clear()
            self._flush_locked()

    def flush(self):
        with self._lock:
            self._flush_locked()

    # ---- Internal ----

    @staticmethod
    def _expired(s, now):
        created = s.get("created") or 0
        if s.get("remember"):
            return now - created > REMEMBER_S
        return now - (s.get("last") or created) > IDLE_S

    def _load_sessions(self):
        try:
            data = json.loads(self.sess_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        now = time.time()
        if not isinstance(data, dict):
            return
        self._sessions = {t: s for t, s in data.items()
                          if isinstance(s, dict) and isinstance(s.get("created"), (int, float))
                          and isinstance(s.get("csrf"), str) and not self._expired(s, now)}

    def _flush_locked(self):
        try:
            _write_private(self.sess_path, self._sessions)
        except OSError as e:
            self._log("warn", "会话存盘失败，Studio 重启后要重新登录", cat="系统", raw=str(e))
        self._dirty_at = None

    def _log(self, level, msg, cat="连接", **kw):
        if self.log:
            self.log.write(msg, cat=cat, level=level, **kw)


# ---- Origin checks ----

def _split_host(host):
    """'microduck-2.local:80' -> ('microduck-2.local', '80'); '[fe80::1]:80' -> ('fe80::1', '80')."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end], host[end + 2:] if end != -1 and host[end + 1:end + 2] == ":" else ""
    if host.count(":") == 1:
        name, port = host.split(":")
        return name, port
    return host, ""


class OriginGuard:
    def __init__(self, names=None):
        hn = socket.gethostname().lower()
        self.names = {"localhost", hn, f"{hn}.local"} | {n.lower() for n in (names or [])}

    def host_ok(self, host_header, local_ip=None):
        name, _ = _split_host(host_header)
        if not name:
            return False
        if name in self.names:
            return True
        try:
            ip = ipaddress.ip_address(name)
        except ValueError:
            return False
        if ip.is_loopback:
            return True
        # IPs are only accepted if they are "the local address this connection actually reached": DNS rebinding uses a domain name and cannot pass the check above,
        # and anyone using the IP directly must have connected to the duck at this IP
        return local_ip is not None and name == str(local_ip).lower()

    def origin_ok(self, origin_header, host_header):
        """State-changing requests, WebSocket handshakes: Origin must be same-origin with Host. Requests without Origin (same-origin GETs
        from old browsers) are up to the caller; state-changing ones are always required to carry it."""
        if not origin_header:
            return False
        try:
            u = urlsplit(origin_header)
        except ValueError:
            return False
        if u.scheme not in ("http", "https"):
            return False
        o_name, o_port = _split_host(u.netloc)
        h_name, h_port = _split_host(host_header)
        default = "443" if u.scheme == "https" else "80"
        return o_name == h_name and (o_port or default) == (h_port or default)


def main():
    ap = argparse.ArgumentParser(description="Studio 管理员密码")
    ap.add_argument("cmd", choices=["set-password"])
    ap.add_argument("--state-dir", required=True)
    a = ap.parse_args()
    pw = getpass.getpass("新密码（至少 6 位）：")
    if pw != getpass.getpass("再输一次："):
        raise SystemExit("两次不一样，没改")
    Auth(a.state_dir).set_password(pw)
    print("已设好。旧的登录全部作废。")


if __name__ == "__main__":
    main()
