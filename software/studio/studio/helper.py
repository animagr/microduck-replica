"""Call the root helper (/usr/local/sbin/microduck-helper) to stop and start the main program robotd (servo bus handover).

Studio isn't root. sudoers only allows this one full path, microduck-helper, so here we use `sudo -n`
to call it and pass a JSON on stdin, with no other privileges at all. The helper accepts the fixed verbs bus-take / bus-give-back /
bus-abort / pad-pair / pad-forget / wifi-hotspot-down / wifi-hotspot-up / calib-read / calib-commit /
ssh-status / ssh-password / imu-recalibrate, validates each parameter,
and reads robotd's state itself rather than trusting what the web page sends (deploy/INSTALL.md).

- bus-take: stop robotd, raise the flag (robotd can't start), confirm the serial port is free → Studio opens the bus. Does not relax.
- bus-give-back {"soft": true}: Studio has already relaxed everything on the bus → lower the flag, start robotd, wait for the four startup steps to succeed.
- bus-give-back {"marker": {...}}: hand back without relaxing (write a handover marker; the fork's robotd reads it and takes over holding).
  Only recognized when the fork's robotd is installed and the drop-in enables Environment; old versions don't recognize it and relax everything as before (result=limp).
- pad-pair: run the official `robotctl pad pair --json` as root. On weird-ble boards robotctl first stops btd and power-cycles the adapter,
  so this main path can pair new Switch Pro-style gamepads. Old helpers reply bad_verb, and the caller then falls back to configd / bluetoothctl.
- pad-forget: run the official `robotctl pad forget MAC` as root.
- wifi-hotspot-down / wifi-hotspot-up: turn the duck's own hotspot off / on during Wi-Fi setup (nmcli connection down / up
  Microduck-Hotspot). Hotspot already off / already on counts as success; these two don't take the bus's helper.lock, they use wifi.lock.
- calib-read: read-only of the current calibration file, returns the parsed content and the current mode (commissioning / motion); takes no lock, writes nothing.
- calib-commit: write servo zero positions / directions / IMU orientation into robotd's calibration file (hd1910-calibration.toml);
  when the factory image runs commissioning mode it also deletes the commissioning drop-in, then restarts the main program into motion mode. Success requires
  mode=motion, phase=control, and calibration-status reading back identical item by item. It runs in a separate systemd unit,
  so a Studio restart only temporarily loses its output; the final result is in /run/microduck-helper/last-result.json.
  dry_run only returns the TOML to be written. Old helpers reply bad_verb, and the caller then prompts to reinstall.

Without the helper installed (development on a computer, bench, demo) it falls back gracefully: bus_take is treated as not done (left to servo.open's own
robotd_active check to report the error), bus_give_back is treated as not done (after handing back, the main program is started manually).
"""
import json
import os
import queue
import re
import stat
import subprocess
import sys
import threading
import time

HELPER = "/usr/local/sbin/microduck-helper"
FLAG = "/run/microduck-helper/bus-held"       # raised during takeover: robotd's drop-in sees it and refuses to start
LAST_RESULT = "/run/microduck-helper/last-result.json"
IMU_REDO_MANIFEST = "/var/lib/microduck-helper/imu-recalibrate/manifest.json"
NATIVE_UPDATE_JOURNAL = "/var/lib/microduck-helper/native-update/journal.json"
NATIVE_UPDATE_ACTIVE = "/var/lib/microduck-helper/native-update/active"
CONTROLLER_UPDATE_JOURNAL = "/var/lib/microduck-helper/controller-update/journal.json"
CONTROLLER_UPDATE_PREPARED = "/var/lib/microduck-helper/controller-update/prepared.json"
NATIVE_UPDATE_EXCLUSIONS = (NATIVE_UPDATE_ACTIVE, "/run/microduck-helper/native-update-restore",
    "/etc/systemd/system/robotd.service.d/zzzzzzz-microduck-native-update.conf", *(
        "/etc/systemd/system/"+unit+".service.d/zzzzzzz-microduck-native-update.conf"
        for unit in ("padd", "gamesir-xboxd", "duck-echo")))

_avail = None


def flag_present():
    """Whether the takeover flag is present (only checked on Linux; patch this function on a computer / in tests)."""
    if not sys.platform.startswith("linux"):
        return False
    return os.path.exists(FLAG)


def available(refresh=False):
    """Whether the helper is present and allowed by sudoers (result cached: installed or not doesn't change at runtime).
    Probed with `sudo -n microduck-helper bus-nope`: if callable it returns 2 (unknown verb, meaning the file exists and sudoers allows it);
    any other return = not installed / not allowed / not on Linux. refresh=True probes again (Wi-Fi setup checks on every connection)."""
    global _avail
    if refresh:
        _avail = None
    if _avail is not None:
        return _avail
    if not sys.platform.startswith("linux") or not os.path.exists(HELPER):
        _avail = False
        return False
    try:
        r = subprocess.run(["sudo", "-n", HELPER, "bus-nope"], capture_output=True, text=True, timeout=5)
        _avail = r.returncode == 2
    except (OSError, subprocess.TimeoutExpired):
        _avail = False
    return _avail


def _call(verb, payload, timeout, on_line=None):
    """Run `sudo -n microduck-helper <verb>` with JSON on stdin. Returns (ok, result, detail).
    ok = the exit of the final done line is 0; result / detail are the detail fields of the done line.
    If on_line is given, each progress line is handed over as it runs (calibration-write progress); otherwise wait for it to finish, then parse."""
    data = json.dumps(payload, ensure_ascii=False)
    if on_line is None:
        try:
            proc = subprocess.run(["sudo", "-n", HELPER, verb], input=data,
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"{type(e).__name__}", None
        result, detail = None, None
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("step") == "done":
                d = obj.get("detail") or {}
                result, detail = d.get("result"), d
        if result is None:
            err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            return False, err or f"exit {proc.returncode}", None
        return detail.get("exit") == 0, result, detail
    return _call_stream(verb, data, timeout, on_line)


def _call_stream(verb, data, timeout, on_line):
    """Same command, but hand over stdout line by line (the helper prints one line per step). stderr is merged into stdout:
    this way errors reported by sudo itself won't block the pipe either."""
    try:
        proc = subprocess.Popen(["sudo", "-n", HELPER, verb], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        return False, f"{type(e).__name__}", None
    try:
        proc.stdin.write(data)
        proc.stdin.close()
    except OSError:
        pass
    lines = queue.Queue()

    def reader():
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    result, detail, noise = None, None, []
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            try:
                proc.kill()
            except OSError:
                pass
            return False, "TimeoutExpired", None
        try:
            line = lines.get(timeout=min(0.2, left))
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            noise.append(line)
            continue
        if obj.get("step") == "done":
            d = obj.get("detail") or {}
            result, detail = d.get("result"), d
        elif on_line is not None:
            on_line(obj)
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
    if result is None:
        return False, "\n".join(noise[-5:]) or f"exit {proc.returncode}", None
    return detail.get("exit") == 0, result, detail


def bus_take(by, allow_seated=False, timeout=30):
    """Stop robotd and hand the servo bus to Studio (without relaxing). Returns (ok, result, detail)."""
    return _call("bus-take", {"by": by, "allow_seated": allow_seated}, timeout)


def bus_give_back(by, *, soft=True, marker=None, timeout=60):
    """Hand back the bus and start robotd. soft=True is a soft handback (Studio has relaxed everything); passing marker is a handback without relaxing (the fork takes over holding).
    Returns (ok, result, detail)."""
    payload = {"by": by, "soft": True} if soft else {"by": by, "marker": marker}
    return _call("bus-give-back", payload, timeout)


def bus_abort(by, timeout=10):
    """Abort the handover (the page pressed relax during the handover countdown): KILL robotd, delete the marker, give the bus back to Studio. Returns (ok, result, detail)."""
    return _call("bus-abort", {"by": by}, timeout)


def pad_pair(by, mac=None, timeout=60):
    """Official robotctl pad pair (run as root by the helper). Returns (ok, result, detail).
    detail["pair"] is a PadPairResult; detail["stderr"] is robotctl's few lines of messages (pausing btd, warnings, etc.)."""
    payload = {"by": by, "timeout": timeout}
    if mac:
        payload["mac"] = mac
    return _call("pad-pair", payload, timeout + 45)


def pad_forget(by, mac, timeout=60):
    """Official robotctl pad forget (run as root by the helper). Returns (ok, result, detail)."""
    return _call("pad-forget", {"by": by, "mac": mac}, timeout)


def wifi_hotspot_down(by, ssid=None, timeout=30):
    """Turn off the duck's own hotspot (the helper waits at most 10 s). Hotspot already off counts as success. ssid is written into the connection window file for netcheck."""
    payload = {"by": by}
    if ssid:
        payload["ssid"] = ssid
    return _call("wifi-hotspot-down", payload, timeout)


def wifi_hotspot_up(by, timeout=40):
    """Turn on the duck's own hotspot (the helper waits at most 30 s). Already on counts as success. Returns (ok, result, detail)."""
    return _call("wifi-hotspot-up", {"by": by}, timeout)


def calib_read(by=None, timeout=10):
    """Read-only of the main program's calibration file and the current mode (calib-read). Returns (ok, result, detail)."""
    payload = {"by": by} if by else {}
    return _call("calib-read", payload, timeout)


def imu_recalibrate(by, action, *, confirmed=None, session_id=None, source=None, quat=None, profile=None, timeout=180):
    """Fixed root verb; commands, services and file paths are never accepted."""
    payload = {"by": by, "action": action}
    for name, value in (("confirmed", confirmed), ("session_id", session_id), ("source", source), ("quat", quat), ("profile", profile)):
        if value is not None:
            payload[name] = value
    return _call("imu-recalibrate", payload, timeout)


def imu_redo_state(*, root="/"):
    """Read the persistent root-owned public manifest. No sudo in the 10 Hz view loop."""
    empty = {"active": False, "phase": "idle", "session_id": None, "source": None}
    path = os.path.join(root, IMU_REDO_MANIFEST.lstrip("/"))
    try:
        for target in (os.path.dirname(os.path.dirname(os.path.dirname(path))), os.path.dirname(os.path.dirname(path)),
                       os.path.dirname(path), path):
            st = os.lstat(target)
            if stat.S_ISLNK(st.st_mode) or (root == "/" and (st.st_uid != 0 or st.st_mode & 0o022)):
                raise ValueError("会话文件或目录的属主 / 权限不安全")
        if not stat.S_ISREG(st.st_mode) or st.st_size > 65536:
            raise ValueError("会话文件格式不正确")
        with open(path, encoding="utf-8") as stream:
            m = json.load(stream)
        if (m.get("schema") != "microduck-imu-recalibrate/1" or type(m.get("active")) is not bool
                or not re.fullmatch(r"[0-9a-f]{32}", m.get("session_id", ""))
                or m.get("source") not in ("bus", "bno08x", "lsm6dsv16x")):
            raise ValueError("会话文件内容不正确")
        if not m["active"]:
            return empty
        return {key: m.get(key) for key in ("active", "phase", "session_id", "source", "reason", "expected_quat", "profile", "original_mode")}
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, TypeError, AttributeError) as err:
        return {**empty, "active": True, "phase": "recovery_required", "reason": f"初次 IMU 校准会话读不回：{err}"}


def robotd_update(by, action, *, confirmed=None, timeout=180):
    """Separate fixed native update stage; no caller paths, binaries or commands."""
    payload = {"by": by, "action": action}
    if confirmed is not None:
        payload["confirmed"] = confirmed
    return _call("robotd-update", payload, timeout)


def native_update_state(*, root="/"):
    legacy=_native_update_state(root=root,journal=NATIVE_UPDATE_JOURNAL)
    path=CONTROLLER_UPDATE_PREPARED
    if not os.path.lexists(os.path.join(root,path.lstrip('/'))):path=CONTROLLER_UPDATE_JOURNAL
    if not os.path.lexists(os.path.join(root,path.lstrip('/'))):return legacy
    bundle=_native_update_state(root=root,journal=path)
    if legacy.get('active'):bundle['active']=True
    return bundle


def _native_update_state(*,root,journal):
    """Bounded persistent motion guard. Malformed/unreadable state fails closed."""
    empty = {"active": False, "phase": "idle", "running_verified": False}
    path = os.path.join(root, journal.lstrip("/"))
    exclusions = any(os.path.lexists(os.path.join(root,p.lstrip('/'))) for p in NATIVE_UPDATE_EXCLUSIONS)
    try:
        parts = journal.strip("/").split("/")
        for index in range(1, len(parts)+1):
            target = os.path.join(root, *parts[:index])
            st = os.lstat(target)
            if ((index < len(parts) and not stat.S_ISDIR(st.st_mode))
                    or (index == len(parts) and not stat.S_ISREG(st.st_mode))
                    or (root == "/" and (st.st_uid != 0 or st.st_mode & 0o022))):
                raise ValueError("更新记录的属主 / 权限不安全")
        if st.st_size > 65536:
            raise ValueError("更新记录超出大小限制")
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        bundle=journal in (CONTROLLER_UPDATE_JOURNAL,CONTROLLER_UPDATE_PREPARED)
        phases=("prepared","guarding","replacing","verifying","restoring","completed","restored","recovery_required") if bundle else (
            "prepared","guarding","guarded","replacing","replaced","verified_commissioning","restoring_normal","verified_motion",
            "factory_handoff_pending","completed","rolled_back","recovering","old_restored","recovery_required")
        if (not isinstance(value, dict) or value.get("schema") != ("microduck-controller-update/1" if bundle else "microduck-native-update/1")
                or type(value.get("active")) is not bool
                or type(value.get("restore_pending", False)) is not bool
                or type(value.get("cleanup_pending", False)) is not bool
                or not re.fullmatch(r"[0-9a-f]{32}", value.get("transaction_id", ""))
                or value.get("phase") not in phases
                or (value.get("reason") is not None and (not isinstance(value["reason"], str) or len(value["reason"]) > 300))):
            raise ValueError("更新记录格式不正确")
        public = ("active", "phase", "transaction_id", "available", "installed_sha256", "target_sha256", "running_verified", "mode", "reason","bundle_schema")
        result = {key:value.get(key) for key in public if key in value}
        result['active'] = result['active'] or value.get('restore_pending') is True or value.get('cleanup_pending') is True or exclusions
        return result
    except FileNotFoundError:
        if exclusions:
            return {**empty,"active":True,"phase":"recovery_required","reason":"主程序更新保护标记存在，记录缺失"}
        return empty
    except (OSError, ValueError, TypeError, AttributeError):
        return {**empty, "active": True, "phase": "recovery_required", "reason": "主程序更新记录读不回；先恢复主程序更新"}


def ssh_status(timeout=10):
    """Whether SSH password login is on, whether ssh is running, how many keys radxa has registered (ssh-status, read-only). Returns (ok, result, detail)."""
    return _call("ssh-status", {}, timeout)


def ssh_password(by, on, password=None, timeout=40):
    """Turn on (set the user's chosen password for radxa) / turn off SSH password login (ssh-password). The password only goes through the helper's stdin, never into logs."""
    payload = {"by": by, "on": bool(on)}
    if on:
        payload["password"] = password
    return _call("ssh-password", payload, timeout)


def last_result():
    """Read the complete result the helper last wrote (used after a Studio restart / call timeout). Returns None if unreadable."""
    try:
        with open(LAST_RESULT, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def calib_commit(by, joints, imu, dry_run=False, timeout=180, on_line=None):
    """Write servo zero positions / directions / IMU orientation into the main program (helper calib-commit). Returns (ok, result, detail).
    dry_run=True only returns the TOML to be written (detail["toml"]), without writing the file or restarting. on_line receives each step's progress."""
    payload = {"by": by, "joints": joints, "imu": imu, "dry_run": bool(dry_run)}
    return _call("calib-commit", payload, timeout, on_line=on_line)


_COMMIT_WHY = {
    "committed": "写进主程序了，主程序进了运动模式",
    "preview": "预览好了（没写文件）",
    "bus_held": "舵机页还占着总线：先在舵机页点「交还主程序」",
    "no_calibration": "鸭子上找不到主程序的标定文件",
    "bad_calibration": "主程序现在的标定文件读不出来",
    "joint_mismatch": "这次的 15 颗跟主程序的标定文件对不上",
    "invalid": "要写的内容没过校验",
    "bad_toml": "写出来的标定文件读回来对不上",
    "restart_failed": "写进去了，但主程序没起来：已经换回原来的文件",
    "not_motion": "写进去了，但主程序没在 30 秒内进运动模式",
    "calib_rejected": "标定没通过主程序的检查",
    "bus_unavailable": "主程序打不开舵机总线",
    "readback_mismatch": "主程序进了运动模式，但标定读回来不一致",
    "write_failed": "写到一半出错，已经换回原来的文件",
    "foreign_commissioning": "主程序的标定模式不是镜像设的，不敢自动切",
    "refused": "主程序现在不让写（鸭子可能在走 / 站着）",
    "backup_failed": "备份原来的标定失败",
    "read_failed": "读不到现在的标定文件",
    "bad_verb": "小助手太旧，重装 deploy/install.sh",
    "busy": "小助手正忙（另一个操作没做完）",
    "detach_failed": "小助手没能在独立单元里跑起来",
    "TimeoutExpired": "等了 180 秒小助手还没回最终结果",
}

_TAKE_WHY = {
    "taken": "主程序停了，总线交给你了",
    "refused": "主程序没停（策略在跑、正在回站姿，或者坐姿没放行）",
    "no_guard": "没装 robotd 的保护（drop-in），不肯停主程序",
    "busy": "小助手正忙（板端脚本在跑，或者另一个总线操作没跑完）",
    "stop_failed": "主程序停不下来（KILL 也没停）",
    "port_busy": "串口还被占着",
}

_GIVE_WHY = {
    "soft": "主程序起来了",
    "soft_failed": "主程序起不来",
    "adopted": "主程序接手保持了（没卸力）",
    "limp": "主程序没认交接标记，照老规矩全卸了",
    "retake": "主程序没起来，总线拿回来了（Studio 还保持着）",
    "retake_failed": "总线没拿回来",
    "aborted": "交还被中止了（按了卸力）",
    "refused": "串口还被占着",
    "no_session": "没有调舵机的会话（旗不在）",
    "detach_failed": "交还起不来（systemd-run 失败）",
}

_PAD_WHY = {
    "paired": "配上了",
    "pair_failed": "没配上（robotctl 说失败）",
    "no_robotctl": "鸭子上没有官方 robotctl（/usr/local/bin/robotctl）",
    "timeout": "robotctl 超时了，已经停下",
    "bad_output": "robotctl 的回包看不懂",
    "forgotten": "忘掉了",
    "forget_failed": "没忘掉",
    "busy": "小助手正忙（另一个配对或忘掉没做完）",
}

_WIFI_WHY = {
    "hotspot_down": "热点关了",
    "already_down": "热点本来就没开",
    "down_failed": "热点没关掉",
    "hotspot_up": "热点开回来了",
    "already_up": "热点本来就开着",
    "up_failed": "热点没开起来",
    "timeout": "等超时了",
    "nmcli_failed": "查不了现在的网络连接（nmcli 出错）",
    "busy": "小助手正忙（另一个 WiFi 操作没做完）",
    "bad_verb": "小助手太旧，重装 deploy/install.sh",
}

_COMMON = {
    "bad_args": "参数不对",
    "bad_marker": "交接标记不对",
    "bad_verb": "动词不认识",
    "not_root": "没权限（要用 root）",
    "error": "小助手自己出错",
}


def friendly(result, detail, verb):
    """Turn result into plain language (result values are in deploy/INSTALL.md §1). The helper's original message in detail is included too."""
    if verb == "imu-recalibrate":
        if result in ("bad_verb", "denied", "not_root") or "sudo" in str(result).lower():
            return "重做初次 IMU 校准需要新版 root 小助手（0.7.0 起）和 sudoers：请更新 deploy/install.sh"
        return ((detail or {}).get("reason") or (detail or {}).get("msg") or
                f"初次 IMU 校准切换没完成：{result}；会话可继续或取消")
    if verb in ("pad-pair", "pad-forget"):
        table = _PAD_WHY
    elif verb in ("wifi-hotspot-down", "wifi-hotspot-up"):
        table = _WIFI_WHY
    elif verb == "calib-commit":
        table = _COMMIT_WHY
    else:
        table = _TAKE_WHY if verb == "bus-take" else _GIVE_WHY
    msg = detail.get("msg") if isinstance(detail, dict) else None
    if verb in ("ssh-status", "ssh-password"):
        # The helper's original message is a complete sentence ("sshd 配置检查没过，已经退回去：…" (sshd config check failed, already reverted: …))
        if msg and result not in ("ssh_status", "ssh_password_on", "ssh_password_off"):
            return msg
        if result == "bad_verb":
            return "小助手太旧，不会开 SSH：重装 deploy/install.sh（0.6.0 起才有）"
        return _COMMON.get(result) or (result or "没成")
    # The helper's original message for calib-commit is already a complete sentence (with an ending like "已经换回原来的文件" (already swapped back to the original file)), use it directly;
    # other verbs keep the "result word: original message" format (test_helper's friendly convention).
    if msg and verb == "calib-commit" and result not in ("committed", "preview"):
        return msg
    # After handback the main program is responding but keeps reporting a startup phase (the old fork's commissioning mode): don't call it "won't start"; the helper's original message is a complete sentence
    if msg and verb == "bus-give-back" and isinstance(detail, dict) and detail.get("still_starting"):
        return msg
    text = table.get(result) or _COMMON.get(result) or (result or "没成")
    if result == "pair_failed" and isinstance(detail, dict) and detail.get("reason"):
        text = f"{text}（{detail['reason']}）"
    if msg and msg not in text:
        text = f"{text}：{msg}"
    return text
