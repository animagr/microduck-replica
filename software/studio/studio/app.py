"""Studio's web service: static pages, login, logs, diagnostic bundle, WebSocket hub.

WebSocket /ws (the handshake checks Host and Origin first and rejects the handshake if wrong; if not logged in, accept first and then close with 4401,
so the page can see 4401 and jump to the login page; closing during the handshake makes the browser see only 1006 and reconnect forever):
    Studio → page: {"t":"hello",...}  {"t":"state",...} (10 Hz while the page is visible)  {"t":"hb"} (1 Hz while not visible)
                   {"t":"log","entry":{...}}  {"t":"result","id":...,"ok":...,"reason":...}
    page → Studio: {"t":"hb","seq":N,"visible":true,"route":"/","pad_visible":false} (once per second)  {"t":"cmd","id":...,"name":"relax"}
pad_visible: whether the gamepad section is on screen (overview re-layout review O1: the gamepad was merged into the overview, so an address of #/pad does not mean it is visible). Pages where it is get gamepad snapshots at 10 Hz,
others at 1 Hz (needed by the gamepad cell in the instrument strip); only if an old page's heartbeat lacks this field do we fall back to route == "/pad".

Servo session (third code review batch D1, D2, D3, D9):
- **Studio exiting does not relax**: on exit only the serial port is closed, and servos that were holding keep holding (the user decided "leaving the servo page keeps torque enabled", and exiting is the same).
  When the bus is opened, servo-session.json (serial port, start time, who opened it) is written atomically in the state directory and deleted only after a successful hand-back; if Studio finds it on startup
  and robotd is not running → automatically retake the bus (opened read-only, torque unchanged), restoring the session and the hint bar; if the takeover fails → the hint bar says "servos may still be holding
  since the last exit; take over on the servo page before you can relax", and the relax button leads to the servo page. If robotd is running → it already released everything when it started, so delete the marker.
- Leaving / hand-back: servo operations are booked in the event loop first (op_begin); hand-back first sets closing, waits for in-flight operations to finish, and reads torque right then (servo.py);
  on leaving, if another page is still on the servo page, calibration / motion is running, or torque cannot be read, do not hand back.
- During a session, check robotd's socket every 5 seconds: if it connects = it was started manually (it will release all servos and fight Studio for the serial port),
  so log an error, Studio closes the bus (without writing to the servos), and the hint bar turns red.
"""
import asyncio
import contextlib
import gzip
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .auth import COOKIE, REMEMBER_S, Auth, OriginGuard
from . import helper
from .rpc import open_conn
from .servo import boot_id, view_from_robotd
from .sshkeys import BadKey, SshKeys
try:                      # two features the phone needs after https; see the comments in phone_bridge
    from . import phone_bridge
except Exception:         # if the module is missing only these two features are absent; do not drag down the whole web page
    phone_bridge = None
from .state import summarize
from .pad import Refused as PadRefused, robot_view  # gamepad page
from .ai_connections import AiError
from .ai_service import AiService
from .updates import Updates, UpdateError, handle as handle_updates, safe_during_update

VERSION = "0.1.0-dev"
RUNTIME_ROOT = Path(__file__).resolve().parents[2]
try:
    SUITE_VERSION = json.loads((RUNTIME_ROOT / 'suite-version.json').read_bytes())['version']
except (OSError,ValueError,KeyError):
    SUITE_VERSION = None
MODEL_UPLOAD_LIMIT = 64 * 1024 * 1024
MODEL_OP_LIMIT = 32768
STATE_HZ = 10
COMMANDS = {"relax", "servo.open", "servo.close", "servo.op", "servo.ports", "imu.op", "calib.op", "pad.op", "onboard.op", "battery.op", "tune.op", "net.op"}
HB_QUIET_S = 5.0         # page has sent no heartbeat for this long: treat as not visible (stop pushing state, maybe unsubscribe)
HB_DEAD_S = 30.0         # no message at all for this long: treat as a half-open connection (phone walked out of Wi-Fi) and close it
MUSIC_PONG_TIMEOUT_S = 5.0
SERVO_IDLE_S = 60.0      # nobody watching the servo page (page closed, network lost, switched away without handing back) for this long and no servo holding: automatically hand back to the main program
ONBOARD_TICK_S = 0.5     # how often the getting-started checklist is evaluated (stood for 3 seconds, walked for 2 seconds are counted at this granularity)
SERVO_MARKER = "servo-session.json"   # marker that a servo session is open (state directory; deleted only after a successful hand-back: review D1)
ROBOTD_PROBE_S = 5.0     # how often to check whether robotd has started during a servo session (review D9)
# Long lists with descriptive text in the gamepad snapshot: not pushed every frame if unchanged (overview re-layout review O12: one frame is 4.8 KB, and Wi-Fi and Bluetooth share one chip).
# The whole thing is still pushed once every 1 second, and the page keeps the previous copy for whatever is missing
PAD_HEAVY = ("skills", "actions", "combos", "sounds")


class HostGuard:
    """ASGI middleware: requests with an unrecognized Host get 421 immediately (blocks DNS rebinding). Unrecognized WebSockets are closed."""

    def __init__(self, app, guard, log):
        self.app, self.guard, self.log = app, guard, log

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and (scope.get('path') == '/api/ai' or scope.get('path','').startswith('/api/updates')):
            original_send = send
            async def private_send(message):
                if message['type'] == 'http.response.start':
                    message = {**message, 'headers':[(k,v) for k,v in message.get('headers',[])
                        if k.lower() != b'cache-control'] + [(b'cache-control',b'no-store')]}
                await original_send(message)
            send = private_send
        if scope["type"] in ("http", "websocket"):
            host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
            local_ip = (scope.get("server") or (None,))[0]
            if not self.guard.host_ok(host, local_ip):
                # Fixed wording with the Host value in the original text: even if someone floods with changing Hosts, it gets deduplicated into one line
                self.log.warn("拒绝了一个 Host 不对的请求", cat="连接", raw=repr(host[:100]),
                              hint="正常用不会遇到；如果你用的是新地址，在启动参数 --name 里加上它")
                if scope["type"] == "http":
                    await PlainTextResponse("Host 不对", status_code=421)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 4403})
                return
        await self.app(scope, receive, send)


class AppStatic(StaticFiles):
    """The page's own files are revalidated every time (changes take effect immediately); unchanging vendor and model files are cached for a day."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        path = scope.get("path", "")
        if path.startswith(("/vendor/", "/model/")):
            resp.headers["Cache-Control"] = "public, max-age=86400"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def _client_desc(conn):
    ip = conn.client.host if conn.client else "?"
    ua = conn.headers.get("user-agent", "")
    kind = "手机" if any(k in ua for k in ("iPhone", "Android", "Mobile")) else "电脑"
    return f"{kind} {ip}"


def _bus_take(by, servo=None):
    """Stop the main program and take over the servo bus (called when entering the servo page, in a thread). If the helper is present, call it (bus-take: no relaxing, raise the flag);
    if absent (development on a computer, bench, demo) treat it as a no-op; servo.open's own robotd_active check will report the error next. Returns (ok, reason)."""
    if not helper.available():
        if servo is not None:
            servo.helper_available = False
        return True, None
    if servo is not None:
        servo.helper_available = True
    ok, result, detail = helper.bus_take(by)
    if ok:
        return True, None
    return False, helper.friendly(result, detail, "bus-take")


def _bus_give_back(by, servo=None):
    """Start the main program after hand-back (called on "Hand back to the main program" / leaving the servo page, in a thread). If the helper is present, call it
    (bus-give-back soft: clear the flag, start robotd, wait for the four startup steps to succeed); if absent, treat it as a no-op. Returns (ok, reason)."""
    if not helper.available():
        if servo is not None:
            servo.helper_available = False
        return True, None
    if servo is not None:
        servo.helper_available = True
    ok, result, detail = helper.bus_give_back(by, soft=True, timeout=60)
    if servo is not None:
        # The main program is actually replying but keeps reporting a startup phase (the old fork's calibration mode): the post-hand-back hint must not tell people to start robotd manually
        servo.giveback_stuck = bool(isinstance(detail, dict) and detail.get("still_starting"))
    if ok:
        return True, None
    return False, helper.friendly(result, detail, "bus-give-back")


def build_app(*, auth, robotd, log, web_dir, duck, names=(), state_dir=None, dev_autologin=False, servo=None, imu=None, pad=None,
              onboard=None, battery=None, tune=None, net=None, commit=None, ssh_home=None, models=None, sensors=None, updates=None,
              ca_cert=None):
    guard = OriginGuard(names=names)
    ai = AiService(state_dir)
    updates = updates or Updates()
    if pad is not None:
        pad.update_guard=updates.installing
    update_commands = set()
    mapping_requests = set()

    def update_readiness(*,native_transaction=None):
        busy = any(not task.done() for task in update_commands) or model_upload_gate.locked()
        motion = getattr(pad,'motion_studio',None)
        native=updates.native_state() if native_transaction is not None else {}
        own_prepared=(native.get('bundle_schema')=='microduck-controller-payload/1' and native.get('active') is True
            and native.get('phase')=='prepared' and isinstance(native_transaction,str)
            and native.get('transaction_id')==native_transaction)
        guarded=updates.marker.exists() or (updates.installing() and not own_prepared)
        if (guarded or busy or (servo is not None and servo.state != 'closed')
            or mapping_requests or (pad is not None and getattr(getattr(pad,'mapping',None),'blocked',False))
            or (motion is not None and (motion.state != 'idle' or motion.session is not None))
            or (imu is not None and (getattr(imu,'_redo_busy',False)
                or getattr(imu,'blocks_updates',lambda:False)()))):
            return {'ready':False,'error':'请结束舵机、标定、录制、回放和动作会话后重试'}
        return {'ready':True}
    if imu is not None and commit is not None:
        imu.commit = commit                          # calibration mode "Enable standing": the same orientation set as writing to the main program
    if onboard is not None:
        # The two getting-started checklist records come from these two places: e-stop test passed (pad.py e-stop test thread), checked standing on the IMU page (imu.py)
        if pad is not None:
            pad.on_estop_passed = onboard.note_estop
        if imu is not None:
            imu.on_check = onboard.note_imu_check
        if commit is not None:
            onboard.commit_service = commit          # readiness / completion check for step 3, "Write to main program"
            commit.onboard = onboard                 # when the user marks steps 1 / 2 "done" or "skipped", those two readiness items need to know
    web_dir = Path(web_dir)
    clients = {}           # websocket -> {"visible": bool, "by": str, "hb_at": monotonic}
    login_gate = asyncio.Semaphore(1)
    servo_gate = asyncio.Lock()         # opening / closing the servo bus one at a time
    model_upload_gate = asyncio.Lock()
    def mapping_readiness():
        # Called in a pad worker: cached flags only. Robot poll latency must
        # not hide a servo takeover or an active IMU calibration session.
        from .pad_mapping import MappingError
        if (servo_gate.locked() or model_upload_gate.locked()
                or (models is not None and getattr(models,'_lock',None) is not None and models._lock.locked())
                or (commit is not None and getattr(commit,'_writing',None) is not None and commit._writing.locked())
                or (servo is not None and servo.state!='closed')
                or (imu is not None and (getattr(imu,'_redo_busy',False)
                    or getattr(imu,'blocks_updates',lambda:False)()))):
            raise MappingError('请先结束舵机、标定和模型更新会话，再重新映射手柄')
    if pad is not None:pad.mapping_guard=mapping_readiness
    # Servo session marker (review D1): not written if no state directory is given (tests)
    marker = Path(state_dir) / SERVO_MARKER if state_dir and servo is not None else None   # logins one at a time: backoff cannot be bypassed by concurrency, and scrypt will not eat several 16 MB at once

    dev_sess = {"csrf": "dev", "auth_at": time.time(), "remember": False}
    # User, 10-18: "no need to set an admin password, just start it and connect". No password set = open: anyone opening it on the same network can use it (same as servo-web).
    # Login is only required once a password is set (can be added in settings later). Host / Origin checks still apply: other websites cannot use your browser to control the duck
    open_sess = {"csrf": "open", "auth_at": time.time(), "remember": False}
    if dev_autologin:
        log.warn("开发模式：本机来的请求不用登录", cat="系统", hint="只在电脑上截图测试用，鸭子上不要开")

    def session_of(conn, touch=True):
        token = conn.cookies.get(COOKIE)
        if dev_autologin and conn.client and conn.client.host == "127.0.0.1":
            return token or "dev", dev_sess
        if not auth.has_password():
            return token or "open", open_sess
        return token, auth.session(token, touch=touch)

    def origin_ok(conn):
        return guard.origin_ok(conn.headers.get("origin"), conn.headers.get("host", ""))

    # ---- HTTP ----

    async def api_updates(request):
        try:
            _,sess=session_of(request)
            result=await handle_updates(request,updates,sess,auth.has_password(),
                dev_autologin and request.client and request.client.host=='127.0.0.1',origin_ok(request))
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except UpdateError as error:
            return JSONResponse({'ok':False,'code':error.code,'error':str(error)},status_code=error.status,headers={'Cache-Control':'no-store'})
        except Exception:
            return JSONResponse({'ok':False,'code':'service','error':'更新服务未完成请求，请稍后重试'},status_code=503,headers={'Cache-Control':'no-store'})

    async def api_ai(request):
        def response(data, status=200):
            return JSONResponse(data, status_code=status, headers={'Cache-Control':'no-store'})
        _, sess = session_of(request)
        local_dev = dev_autologin and request.client and request.client.host == '127.0.0.1'
        # The general Studio open session is unsuitable for billable external requests.
        if not auth.has_password() and not local_dev:
            return response({'ok':False,'code':'password_required','error':'请先在设置中配置网页密码，再使用 AI 连接'},403)
        if not sess:
            return response({'ok':False,'code':'unauthorized','error':'请先登录'},401)
        if request.method == 'POST' and (not origin_ok(request) or request.headers.get('x-csrf') != sess['csrf']):
            return response({'ok':False,'code':'csrf','error':'请求来源或登录令牌不正确'},403)
        try:
            if request.method == 'GET':
                result = await ai.view()
            else:
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise AiError('oversize','AI 请求过大',413)
                try:
                    body = json.loads(raw)
                except (ValueError,RecursionError):
                    raise AiError('validation','请求不是有效 JSON') from None
                result = await ai.handle(body)
            return response({'ok':True,**result})
        except AiError as error:
            return response({'ok':False,'code':error.code,'error':str(error)},error.status)
        except Exception:
            # Do not log exception details: network libraries may include request credentials.
            return response({'ok':False,'code':'internal','error':'AI 请求未完成，请稍后重试'},500)

    async def healthz(request):
        return JSONResponse({"ok": True, "version": VERSION,"suite_version":SUITE_VERSION,"runtime_root":str(RUNTIME_ROOT)})

    async def api_session(request):
        token, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False, "has_password": auth.has_password()}, status_code=401)
        return JSONResponse({"ok": True, "csrf": sess["csrf"], "duck": duck, "version": VERSION})

    async def api_login(request):
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "请求来源不对"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        ip = request.client.host if request.client else "?"
        if not isinstance(body, dict):
            body = {}
        pw = str(body.get("password", ""))
        # Request bodies are never logged, so log.hide(pw) is unnecessary (code review #12: every attempted password went into the redaction table,
        # and after trying "true" every true in the log became [已隐藏] (hidden))
        async with login_gate:
            token, why, wait = await asyncio.to_thread(auth.login, pw, ip, bool(body.get("remember")))
        if not token:
            return JSONResponse({"ok": False, "error": why, "wait": wait}, status_code=401)
        resp = JSONResponse({"ok": True})
        # SameSite=Lax: login is carried even when following a link from WeChat or chat apps (Strict would require logging in again every time);
        # cross-site requests are blocked by the Origin check and the CSRF token
        resp.set_cookie(COOKIE, token, max_age=REMEMBER_S if body.get("remember") else None,
                        httponly=True, samesite="lax", path="/")
        return resp

    async def api_logout(request):
        token, sess = session_of(request)
        if sess and origin_ok(request) and request.headers.get("x-csrf") == sess["csrf"]:
            auth.logout(token)
            log.info(f"退出登录（{_client_desc(request)}）", cat="连接")
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    async def api_password(request):
        """Set / change / clear the admin password on the web page. Writes the same password.json used by run.py set-password."""
        token, sess = session_of(request)
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "请求来源不对"}, status_code=403)
        if not sess:
            return JSONResponse({"ok": False, "error": "先登录才能改密码"}, status_code=401)
        if request.headers.get("x-csrf") != sess["csrf"]:
            return JSONResponse({"ok": False, "error": "请求校验失败，刷新页面再试"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        action = body.get("action", "set")
        ip = request.client.host if request.client else "?"
        if action == "clear":
            if auth.has_password():
                await asyncio.to_thread(auth.clear_password)
                log.info(f"管理员密码已清掉（{_client_desc(request)}）", cat="连接")
            resp = JSONResponse({"ok": True, "has_password": False})
            resp.delete_cookie(COOKIE, path="/")
            return resp
        if action != "set":
            return JSONResponse({"ok": False, "error": "不认识的操作"}, status_code=400)
        pw = body.get("password")
        confirm = body.get("confirm")
        if not isinstance(pw, str) or len(pw) < 6:
            return JSONResponse({"ok": False, "error": "密码至少 6 位"}, status_code=400)
        if pw != confirm:
            return JSONResponse({"ok": False, "error": "两次输入不一样"}, status_code=400)
        had_password = auth.has_password()
        keep = token if had_password and token and token != "open" else None
        try:
            await asyncio.to_thread(auth.set_password, pw, keep)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        resp = JSONResponse({"ok": True, "has_password": True})
        if not had_password:
            new_token, _, _ = await asyncio.to_thread(auth.login, pw, ip, False)
            if new_token:
                resp.set_cookie(COOKIE, new_token, httponly=True, samesite="lax", path="/")
        log.info(f"管理员密码已{'设置' if not had_password else '修改'}（{_client_desc(request)}）", cat="连接")
        return resp

    ssh_gate = asyncio.Lock()
    ssh_keys = SshKeys(ssh_home)        # Studio runs as radxa: ~/.ssh/authorized_keys is its own file, no helper needed

    async def ssh_view(detail=None):
        """Whether password login is on, the ssh service (helper ssh-status; None if unreadable) + registered keys (read by Studio itself)."""
        if detail is None and await asyncio.to_thread(helper.available):
            ok, _, d = await asyncio.to_thread(helper.ssh_status)
            detail = d if ok else None
        d = detail if isinstance(detail, dict) else {}
        try:
            keys = await asyncio.to_thread(ssh_keys.list)
        except OSError:
            keys = []
        return {"password_login": d.get("password_login") if isinstance(d.get("password_login"), bool) else None,
                "ssh_active": d.get("ssh_active"), "keys": len(keys), "key_list": keys, "user": d.get("user") or "radxa"}

    async def api_ssh(request):
        """SSH on the "More" page: status / on (with the user's own password) / off / add_key (paste your own public key) / remove_key.
        The factory image accepts keys only, ships with nobody's key, and has no default password known to everyone. Enabling password login or registering keys both require the web login password to be set first:
        otherwise anyone on the hotspot (whose password is public) could open the web page and turn on SSH to get root. The password is only passed to the helper's stdin, never logged."""
        _, sess = session_of(request)
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "请求来源不对"}, status_code=403)
        if not sess:
            return JSONResponse({"ok": False, "error": "先登录"}, status_code=401)
        if request.headers.get("x-csrf") != sess["csrf"]:
            return JSONResponse({"ok": False, "error": "请求校验失败，刷新页面再试"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        action = body.get("action", "status")
        if action not in ("status", "on", "off", "add_key", "remove_key"):
            return JSONResponse({"ok": False, "error": "不认识的操作"}, status_code=400)
        if action in ("on", "add_key") and not auth.has_password():
            what = "打开 SSH" if action == "on" else "登记钥匙"
            return JSONResponse({"ok": False, "error": f"先在上面设网页登录密码，再{what}：不然连上热点的人都能打开网页、"
                                                     "顺手把 SSH 打开"}, status_code=403)
        if action == "on":
            pw, confirm = body.get("password"), body.get("confirm")
            if not isinstance(pw, str) or not 8 <= len(pw) <= 64:
                return JSONResponse({"ok": False, "error": "SSH 密码要 8–64 位"}, status_code=400)
            if pw != confirm:
                return JSONResponse({"ok": False, "error": "两次输入不一样"}, status_code=400)
        by = _client_desc(request)
        async with ssh_gate:
            if action == "status":
                return JSONResponse({"ok": True, "ssh": await ssh_view()})
            if action in ("add_key", "remove_key"):
                try:
                    if action == "add_key":
                        added, k = await asyncio.to_thread(ssh_keys.add, body.get("key"))
                    else:
                        gone = await asyncio.to_thread(ssh_keys.remove, body.get("fp"))
                except BadKey as e:
                    return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
                except OSError as e:
                    log.error("SSH 钥匙没写进去", cat="系统", raw=f"{type(e).__name__}: {e}", step=action,
                              hint="看看 /home/radxa/.ssh 的权限；还不行就导出诊断包")
                    return JSONResponse({"ok": False, "error": f"写不进 authorized_keys：{e}"}, status_code=500)
                if action == "add_key":
                    what = f"{k['type']} {k['comment'] or '（没注释）'} {k['fp']}"
                    log.info(f"SSH 钥匙{'登记了' if added else '本来就在'}：{what}（{by}）", cat="系统")
                    return JSONResponse({"ok": True, "added": added, "fp": k["fp"], "ssh": await ssh_view()})
                if gone:
                    log.info(f"SSH 钥匙删掉了：{body.get('fp')}（{by}）", cat="系统")
                return JSONResponse({"ok": True, "removed": gone, "ssh": await ssh_view()})
            if not await asyncio.to_thread(helper.available):
                return JSONResponse({"ok": False, "error": "这只鸭子没装 root 小助手，网页里开不了 SSH 密码登录"},
                                    status_code=503)
            if action == "on":
                ok, result, detail = await asyncio.to_thread(helper.ssh_password, by, True, body["password"])
            else:
                ok, result, detail = await asyncio.to_thread(helper.ssh_password, by, False)
            word = "打开" if action == "on" else "关掉"
            if not ok:
                why = helper.friendly(result, detail, "ssh-password")
                log.warn(f"SSH 密码登录没{word}：{why}", cat="系统", step=f"ssh-password {action}",
                         hint="照提示改；还不行就导出诊断包")
                return JSONResponse({"ok": False, "error": why},
                                    status_code=400 if result in ("bad_password", "bad_args") else 502)
            log.info(f"SSH 密码登录{word}了（{by}）", cat="系统")
            return JSONResponse({"ok": True, "ssh": await ssh_view()})

    async def api_logs(request):
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False}, status_code=401)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 200)), 500))
        except ValueError:
            return JSONResponse({"ok": False, "error": "limit 要是数字"}, status_code=400)
        return JSONResponse({"ok": True, "items": log.recent(limit=limit)})

    async def api_diag(request):
        """Diagnostic bundle: the last two days of logs + current state + versions + robotd's system log. For asking for help in the group chat."""
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False}, status_code=401)
        log.info(f"导出诊断包（{_client_desc(request)}）", cat="系统")
        # Grab the state in the event loop before handing off to the thread (do not read changing things across threads)
        snap = summarize(robotd, duck, servo, ob=onboard, bat=battery, net=net, commit=commit, auth=auth)
        raw = {"hello": robotd.hello.value, "health": robotd.health.value, "busStatus": robotd.bus.value,
               "policies": robotd.policies.value, "calibration": robotd.calib.value,
               "pad": robotd.pad.value, "system": robotd.sysinfo.value}
        if onboard is not None:
            raw["onboarding_records"] = dict(onboard.rec)        # what the getting-started checklist recorded (time, which gamepad, fingerprint)
        if pad is not None:
            try:
                raw["pad_page"] = pad.diag()
            except Exception as e:  # noqa: BLE001
                raw["pad_page"] = f"出错：{type(e).__name__}: {e}"
        if tune is not None:
            try:
                raw["tune"] = tune.diag()                          # tuning snapshot (tuning plan §5: files, readback)
            except Exception as e:  # noqa: BLE001
                raw["tune"] = f"出错：{type(e).__name__}: {e}"
        data = await asyncio.to_thread(_diag_zip, log, snap, raw)
        name = f"studio-diag-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def api_profile(request):
        """Export the duck profile (for training, tuning plan T3): read-only summary, downloaded as JSON."""
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False}, status_code=401)
        if tune is None:
            return JSONResponse({"ok": False, "error": "这只鸭子没开调参卡的后端"}, status_code=404)
        log.info(f"导出鸭子档案（{_client_desc(request)}）", cat="调参")
        data = json.dumps(tune.profile(), ensure_ascii=False, indent=1, default=str).encode("utf-8")
        name = f"duck-profile-{time.strftime('%Y%m%d-%H%M%S')}.json"
        return Response(data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def sensor_read(request, kind):
        headers = {"Cache-Control": "no-store"}
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False, "error": "先登录才能查看传感器"}, status_code=401, headers=headers)
        if sensors is None:
            return JSONResponse({"ok": False, "error": "当前未开启传感器页面的后端"}, status_code=503, headers=headers)
        try:
            data = await getattr(sensors, kind)()
            return JSONResponse({"ok": True, "data": data}, headers=headers)
        except Exception as e:
            label = "摄像头" if kind == "camera" else "ToF"
            log.error(f"读取{label}状态失败", cat="传感器", raw=f"{type(e).__name__}: {e}", exc=True)
            return JSONResponse({"ok": False, "error": f"暂时无法读取{label}状态，请稍后重试或查看日志"},
                                status_code=503, headers=headers)

    async def api_camera(request):
        return await sensor_read(request, "camera")

    async def api_tof(request):
        return await sensor_read(request, "tof")

    def model_response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def model_access(request, *, write=False):
        _, sess = session_of(request)
        if not sess:
            return model_response({"ok": False, "error": "先登录才能管理模型"}, 401)
        if write and (not origin_ok(request) or request.headers.get("x-csrf") != sess["csrf"]):
            return model_response({"ok": False, "error": "请求校验失败，刷新页面再试"}, 403)
        if write and updates.installing():
            return model_response({'ok':False,'error':'软件更新正在进行，请等待完成'},409)
        if write and (mapping_requests or (pad is not None and pad.mapping.blocked)):
            return model_response({'ok':False,'error':'请先完成或取消手柄映射并回中，再修改模型'},409)
        if models is None:
            return model_response({"ok": False, "error": "当前模式没有开启模型管理"}, 503)
        return None

    async def model_result(operation):
        try:
            return model_response({"ok": True, "data": await operation()})
        except ValueError as e:
            return model_response({"ok": False, "error": str(e), "code": getattr(e, "code", "invalid")},
                                  getattr(e, "status", 400))
        except Exception as e:  # do not write uploaded content to the log
            log.error("模型管理操作失败", cat="模型", raw=f"{type(e).__name__}: {e}", exc=True)
            return model_response({"ok": False, "error": "模型管理暂时出错，请查看日志后重试"}, 500)

    async def limited_body(request, limit):
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) < 0:
                    raise ValueError()
                if int(length) > limit:
                    raise OverflowError()
            except ValueError:
                raise ValueError("请求大小不正确") from None
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise OverflowError()
            data.extend(chunk)
        return data

    async def api_models(request):
        refused = model_access(request)
        if refused is not None:
            return refused
        return await model_result(models.view)

    async def api_model_op(request):
        refused = model_access(request, write=True)
        if refused is not None:
            return refused
        try:
            body = json.loads(await limited_body(request, MODEL_OP_LIMIT))
            if not isinstance(body, dict):
                raise ValueError()
        except OverflowError:
            return model_response({"ok": False, "error": "操作请求过大"}, 413)
        except (ValueError, UnicodeError, RecursionError):
            return model_response({"ok": False, "error": "操作请求格式不正确"}, 400)
        task=asyncio.current_task();update_commands.add(task)
        try:
            refused=model_access(request,write=True)
            if refused is not None:return refused
            return await model_result(lambda: models.handle(body, by=_client_desc(request)))
        finally:update_commands.discard(task)

    async def api_model_import(request):
        refused = model_access(request, write=True)
        if refused is not None:
            return refused
        # The original file name is only used to determine the format. Staged files use random system names and never concatenate user paths.
        filename = request.query_params.get("filename", "")
        if not filename or len(filename) > 200 or any(c in filename for c in ("/", "\\", ":", "\x00")):
            return model_response({"ok": False, "error": "请选择模型部署包文件"}, 400)
        suffix = next((s for s in (".tar.gz", ".tgz", ".zip") if filename.lower().endswith(s)), None)
        if suffix is None:
            return model_response({"ok": False, "error": "请选择 ZIP、tar.gz 或 tgz 模型部署包"}, 400)
        name = request.query_params.get("name", "")
        if len(name) > 80:
            return model_response({"ok": False, "error": "模型名称最多 80 个字符"}, 400)
        async with model_upload_gate:
            temporary = None
            try:
                refused=model_access(request,write=True)
                if refused is not None:return refused
                length = request.headers.get("content-length")
                if length is not None and int(length) > MODEL_UPLOAD_LIMIT:
                    raise OverflowError()
                upload_dir = Path(state_dir or auth.dir) / "model-uploads"
                await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(suffix=suffix, dir=upload_dir)
                total = 0
                with os.fdopen(fd, "wb") as output:
                    async for chunk in request.stream():
                        total += len(chunk)
                        if total > MODEL_UPLOAD_LIMIT:
                            raise OverflowError()
                        await asyncio.to_thread(output.write, chunk)
                if not total:
                    raise ValueError("模型部署包是空的")
                return await model_result(lambda: models.import_package(Path(temporary), name=name))
            except OverflowError:
                return model_response({"ok": False, "error": "模型部署包不能超过 64 MiB"}, 413)
            except ValueError as e:
                return model_response({"ok": False, "error": str(e) or "请求格式不正确"}, 400)
            finally:
                if temporary is not None:
                    await asyncio.to_thread(Path(temporary).unlink, missing_ok=True)

    async def meshes(request):
        """The 3D model is 2.8 MB: serve the pre-compressed .gz directly (no compressing on the board), browser-cached for a day."""
        raw = web_dir / "model" / "meshes.bin"
        gz = raw.with_suffix(".bin.gz")
        headers = {"Cache-Control": "public, max-age=86400", "Vary": "Accept-Encoding"}
        if gz.is_file() and "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
            return FileResponse(gz, media_type="application/octet-stream", headers=headers)
        return FileResponse(raw, media_type="application/octet-stream", headers=headers)

    # ---- WebSocket ----

    def update_viewers():
        robotd.set_viewers(sum(1 for c in clients.values() if c["visible"]))

    tune_err = {"logged": False}

    def tune_view():
        """Tuning card snapshot; on error log once and return None (it must not break the whole page connection)."""
        try:
            v = tune.view()
            tune_err["logged"] = False
            return v
        except Exception as e:  # noqa: BLE001
            if not tune_err["logged"]:
                tune_err["logged"] = True
                log.error("拼调参卡的数据时出错", cat="调参", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来；不影响站和走")
            return None

    async def ws_endpoint(ws: WebSocket):
        token, sess = session_of(ws)
        if not origin_ok(ws):
            log.warn(f"拒绝了一个来源不对的页面连接（{_client_desc(ws)}）", cat="连接",
                     raw=f"Origin={ws.headers.get('origin')!r} Host={ws.headers.get('host')!r}",
                     hint="正常打开鸭子的网页不会遇到；如果是别的网站在偷连，这样拒掉是对的")
            await ws.close(code=4403)
            return
        if not sess:
            log.info(f"页面连接没带有效登录，让它重新登录（{_client_desc(ws)}）", cat="连接")
            await ws.accept()
            await ws.close(code=4401)
            return
        await ws.accept()
        by = _client_desc(ws)
        pad_conn = pad.new_conn() if pad is not None else None
        me = {"visible": True, "by": by, "hb_at": time.monotonic(), "route": None, "pad_visible": None}
        clients[ws] = me
        update_viewers()
        log.info(f"页面连上（{by}，现在 {len(clients)} 个）", cat="连接", dedup=False)
        logq = log.subscribe()
        send_lock = asyncio.Lock()

        async def send(obj):
            async with send_lock:
                await ws.send_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        loop = asyncio.get_running_loop()      # writing to the main program runs in a background thread; progress is pushed back to the page from here

        async def sender():
            await send({"t": "hello", "version": VERSION, "duck": duck})
            last_check = time.monotonic()
            last_imu = 0.0
            last_tune = 0.0
            pad_tick = 0
            pad_lists = None                    # the gamepad long lists last pushed (not pushed again if unchanged: review O12)
            state_tick = 0
            onb_sent = None                     # the getting-started checklist last pushed (not carried again if unchanged: code review C5)
            while True:
                quiet = time.monotonic() - me["hb_at"]
                if quiet > HB_DEAD_S:
                    # Background timer throttling must not end server-owned music.
                    # A matched native Pong renews transport liveness only: it never
                    # changes hb_at, visible viewers, drive-area state or ownership.
                    music = pad is not None and pad.motion_studio.background_music(pad_conn)
                    ping = ws.scope.get("extensions", {}).get("studio.websocket.ping")
                    transport_alive = music and time.monotonic() - me.get("pong_at", 0.) <= HB_DEAD_S
                    if music and not transport_alive and callable(ping):
                        transport_alive = await ping(MUSIC_PONG_TIMEOUT_S)
                        if transport_alive:
                            me["pong_at"] = time.monotonic()
                    if not transport_alive:
                        log.info(f"页面 {HB_DEAD_S:.0f} 秒没消息且连接未确认，当作断了（{by}）", cat="连接")
                        await ws.close(code=4408)
                        return
                if me["visible"] and quiet > HB_QUIET_S:
                    me["visible"] = False          # no heartbeat: treat as not visible for now, so robotd does not assemble frames for nothing
                    update_viewers()
                if me["visible"]:
                    st = summarize(robotd, duck, servo, ob=onboard, bat=battery, net=net, commit=commit, auth=auth)
                    # The getting-started checklist is about 1 KB: not carried every frame if unchanged (the page keeps the previous copy), but still carried in full once per second (code review C5,
                    # same approach as the gamepad snapshot's long lists)
                    state_tick += 1
                    onb = st.get("onboarding")
                    if onb is not None and onb == onb_sent and state_tick % STATE_HZ != 0:
                        del st["onboarding"]
                        st["onboarding_same"] = True
                    else:
                        onb_sent = onb
                    await send(st)
                    # The servo table is 5.6 KB per frame and only used by the servo page: only pushed while on the servo page or while the bus is taken over (overview re-layout review O12)
                    if servo is not None and (me.get("route") == "/servos" or servo.state in ("open", "opening")):
                        # Bus taken over: push the whole table read from the bus; not taken over: assemble a read-only table from the main program's data
                        await send(servo.snapshot() if servo.state == "open"
                                   else view_from_robotd(robotd, servo.directions, servo.state,
                                                         servo.error, servo.sim))
                    if imu is not None and time.monotonic() - last_imu >= 0.5:
                        last_imu = time.monotonic()        # chip, mounting orientation and reading status for the IMU page: twice a second is enough
                        await send(imu.view())
                    if (tune is not None and time.monotonic() - last_tune >= 1.0
                            and me.get("route") in ("/", "/pad", "/settings")):     # no heartbeat received yet (page unknown): do not push yet
                        last_tune = time.monotonic()       # "Run and tuning" below the overview, the model on the settings page: once per second (tuning plan T1–T3)
                        tv = tune_view()
                        if tv is not None:
                            await send(tv)
                    if pad is not None:
                        # Pages with the gamepad section on screen get 10 Hz, others 1 Hz (enough for the instrument strip's gamepad cell). Only pad_visible in the heartbeat is used;
                        # only old pages lacking it fall back to the route (review O1: #/pad is now an anchor on the overview, so that address does not mean it is visible)
                        pad_tick += 1
                        hot = me["pad_visible"] if me.get("pad_visible") is not None else me.get("route") == "/pad"
                        full = pad_tick % STATE_HZ == 0
                        if hot or full:
                            try:
                                snap = pad.safe_snapshot(conn=pad_conn)    # never raises itself; the same kind of error is logged only once
                            except Exception:  # noqa: BLE001
                                snap = None
                            if snap is not None:
                                m = snap.get("motion") if isinstance(snap.get("motion"), dict) else None
                                if m is not None:
                                    lists = {k: m.get(k) for k in PAD_HEAVY}
                                    if not full and lists == pad_lists:
                                        snap = dict(snap, motion={k: v for k, v in m.items() if k not in PAD_HEAVY},
                                                    lists_same=True)
                                    else:
                                        pad_lists = lists
                                await send(snap)
                    await asyncio.sleep(1 / STATE_HZ)
                else:
                    await send({"t": "hb"})
                    await asyncio.sleep(1.0)
                if time.monotonic() - last_check > 5:
                    last_check = time.monotonic()
                    # Check only, do not renew: a page being open does not mean someone is using it; 12 hours without activity still expires
                    if session_of(ws, touch=False)[1] is None:
                        await ws.close(code=4401)
                        return

        async def log_forwarder():
            while True:
                entry = await logq.get()
                await send({"t": "log", "entry": entry})

        cmd_tasks = set()

        async def run_relax(cid):
            if pad is not None:
                pad.note_relax(by)
            try:
                if servo is not None and servo.state == "open":
                    # robotd is stopped during servo tuning: relax goes straight over the bus with readback confirmation (servo.relax_all)
                    accepted, reason = await asyncio.to_thread(servo.relax_all, by)
                elif servo is not None and servo.orphan and robotd.present is not True:
                    # The session was open at the last exit and was not taken over this time (review D1): robotd is not running so sending to it is useless; relaxing over the bus requires taking over first
                    log.warn("卸力：上次退出时舵机会话开着、这次没接管上，没法在总线上卸", cat="安全", raw=f"by={by}",
                             hint="去舵机页接管总线后再按卸力；急的话关电源")
                    accepted, reason = False, "上次 Studio 退出时可能还有舵机保持着：先去舵机页接管总线才能卸力（急的话关电源）"
                else:
                    accepted, reason = await robotd.relax(by)
            except Exception as e:  # noqa: BLE001 — should not happen; if it does, the page still gets an acknowledgment
                log.error("处理卸力命令时 Studio 出错", cat="命令", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 自己的 bug；先用手柄 − 或关电源，再把诊断包发出来")
                accepted, reason = False, f"Studio 出错：{type(e).__name__}"
            try:
                await send({"t": "result", "id": cid, "ok": accepted, "reason": reason})
            except Exception:  # noqa: BLE001 — the page has already disconnected: the relax was sent anyway, so it does not matter if the acknowledgment cannot be delivered
                pass

        async def run_servo(name, cid, args=None):
            if servo is None:
                await send({"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没配舵机总线"})
                return
            async with servo_gate:
                if name == "servo.open":
                    # User, 10-18: entering the servo page takes over automatically. Do not take over while the duck is walking / the policy is running / it is standing up: the joints would freeze mid-step
                    pose = summarize(robotd, duck, net=net, auth=auth)["posture"] if servo.state != "open" else None
                    if pose in ("walking", "policy", "homing"):
                        ok, why = False, "鸭子在走或者策略在跑：先停下或坐下，再进舵机页（现在只读）"
                    else:
                        was_open = servo.state == "open"
                        if was_open:
                            # The session has stayed open and is already paused: do not touch polling on success or failure (review #3)
                            ok, why = await asyncio.to_thread(servo.open, by, (args or {}).get("port"))
                        else:
                            # One-click takeover: stop the main program first (helper bus-take, no relaxing, raise the flag). If the helper is not installed, leave it to
                            # servo.open's own robotd_active check to report the error
                            robotd.set_paused(True, "调舵机")
                            taken, take_why = await asyncio.to_thread(_bus_take, by, servo)
                            if not taken:
                                ok, why = False, take_why
                                if helper.flag_present():
                                    why = f"{why}。主程序现在被旗挡着起不来：处理好以后再点「连接」接管、用完点交还；或者重启鸭子"
                                robotd.set_paused(False)
                            else:
                                ok, why = await asyncio.to_thread(servo.open, by, (args or {}).get("port"))
                                if not ok:
                                    robotd.set_paused(False)
                                    # The main program stopped but the bus failed to open: start it back up, do not leave a flag that keeps the main program from starting
                                    asyncio.create_task(asyncio.to_thread(_bus_give_back, by, servo))
                                else:
                                    servo.orphan = servo.conflict_at = None
                                    servo.handed_back_at = None
                                    servo.handback_note = servo.giveback_error = servo.giveback_hint = None
                                    await remember_marker(by)
                elif (args or {}).get("if_idle"):
                    # Leaving the servo page: do not hand back if any servo is holding (read right then), torque cannot be read, calibration / motion is running, or another page is still on the servo page
                    # (user, 10-18: "when leaving the servo page torque should stay enabled, it should not go limp"; review D2, D3).
                    # The fork's robotd relaxes everything as soon as it starts (duck-control feetech.rs:1495 confirm_startup_limp), so a hand-back is always soft,
                    # so the only option is to keep the bus session; to hand back, click "Hand back to the main program" (without if_idle)
                    done, kept = await leave_servos(f"离开舵机页（{by}）", ws, by)
                    if done:
                        ok, why = True, None
                    else:
                        log.info(f"离开舵机页：{kept}，不交还（总线会话留着；点「交还主程序」才交还）", cat="总线",
                                 raw=f"by={by}", dedup=False)
                        ok, why = True, f"{kept}：没交还，会话留着"
                else:
                    ok, why = await hand_back(f"点了「交还主程序」（{by}）", by)
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": why})
            except Exception:  # noqa: BLE001
                pass

        async def run_servo_op(cid, args):  # noqa: C901
            """Servo page operations (torque, sliders, motion, calibration, scan, registers…): servo_ops.handle runs in a thread."""
            from .servo_ops import Refused
            data, ok, reason = None, True, None
            ops = servo.ops if servo is not None else None
            if ops is None:
                ok, reason = False, "舵机总线还没接管：刷新舵机页重试"
            else:
                # Book it in the event loop before entering the thread (review D2): "hold" and "leave" arrive in the same packet, and hand-back also waits for it to finish before reading torque
                try:
                    tok = servo.op_begin(args.get("op"))
                except Refused as e:
                    ok, reason, tok = False, str(e), None
                if tok is not None:
                    try:
                        data = await asyncio.to_thread(ops.handle, args, tok)
                    except Refused as e:
                        ok, reason = False, str(e)
                    except Exception as e:  # noqa: BLE001
                        ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                        log.error(f"舵机操作出错：{args.get('op')}", cat="总线", raw=f"{type(e).__name__}: {e}", exc=True,
                                  hint="这是 Studio 的问题，导出诊断包发出来")
                    finally:
                        servo.op_end(tok)
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_imu_op(cid, args):
            """IMU page operations: currently only solve (compute the mounting orientation); writing, coarse calibration and chip switching will be hooked up on the duck."""
            from .imu import Refused as ImuRefused
            data, ok, reason = None, True, None
            if imu is None:
                ok, reason = False, "这只鸭子没开 IMU 页的后端"
            else:
                try:
                    data = await imu.handle(args, by)
                except ImuRefused as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"IMU 操作出错：{args.get('op')}", cat="IMU", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_calib_op(cid, args):
            """Step 3 of the getting-started checklist: "preview what will be written" = helper dry_run; "Write to main program" = check readiness, then hand to the helper to write and restart the main program."""
            from .commit import Refused as CommitRefused
            op = args.get("op") if isinstance(args, dict) else None
            if commit is None:
                await send({"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没开「写进主程序」"})
                return
            if op == "preview":
                try:
                    data = await asyncio.to_thread(commit.preview, by)
                except CommitRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                except Exception as e:  # noqa: BLE001
                    log.error("算「要写什么」时出错", cat="校准", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False,
                                "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                    return
                await send({"t": "result", "id": cid, "ok": True, "data": data})
                return
            if op != "commit":
                await send({"t": "result", "id": cid, "ok": False, "reason": f"不认识的写入操作：{op}"})
                return
            try:
                view = commit.view(robotd, servo)
            except Exception as e:  # noqa: BLE001
                log.error("查「写进主程序」的准备情况时出错", cat="校准", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来")
                await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                return
            if not view.get("ready"):
                missing = [i for i in view.get("items") or [] if not i.get("ok")]
                reason = "还没准备好：" + "；".join(f"{i.get('label')}：{i.get('text')}" for i in missing[:3])
                if len(missing) > 3:
                    reason += "…"
                await send({"t": "result", "id": cid, "ok": False, "reason": reason, "data": {"readiness": view}})
                return
            # Acknowledge "writing started" first; everything after runs in a background thread: the page must not be stuck behind a 90-second restart, and relax stays clickable
            await send({"t": "commit", "phase": "started", "msg": "开始写进主程序：会重启主程序（约 20 秒），鸭子会先卸力"})
            await send({"t": "result", "id": cid, "ok": True, "data": {"started": True, "readiness": view}})

            def progress(msg, detail=None):
                item = {"t": "commit", "phase": "running", "msg": msg}
                if isinstance(detail, dict):
                    item["detail"] = detail
                try:
                    asyncio.run_coroutine_threadsafe(send(item), loop)
                except Exception:  # noqa: BLE001 — the page disconnecting does not affect the write
                    pass

            try:
                res = await asyncio.to_thread(commit.commit, by, progress)
            except Exception as e:  # noqa: BLE001
                log.error("写进主程序的后台任务出错", cat="校准", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="看看主程序有没有起来；原来的文件有没有换回去，日志里有")
                res = {"ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}", "detail": {}}
            await send({"t": "commit", "phase": "done" if res.get("ok") else "failed", "ok": bool(res.get("ok")),
                        "reason": res.get("reason"), "detail": res.get("detail") or {}})

        async def run_tune_op(cid, args):
            """Tuning card / settings page model operations: this version only has save_body (weight for the exported profile, stored only in Studio); anything changing the duck is refused."""
            from .tune import Refused as TuneRefused
            data, ok, reason = None, True, None
            if tune is None:
                ok, reason = False, "这只鸭子没开调参卡的后端"
            else:
                try:
                    data = await tune.handle(args, by)
                except TuneRefused as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"调参操作出错：{args.get('op')}", cat="调参", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_pad_op(cid, args):
            """Gamepad page operations: pad.handle runs in a thread (scan, pairing and actions start their own background threads, so this returns immediately)."""
            data, ok, reason = None, True, None
            if pad is None:
                ok, reason = False, "这只鸭子没开手柄页的后端（台架模式）"
            else:
                try:
                    data = await asyncio.get_running_loop().run_in_executor(
                        pad.executor_for(args), lambda: pad.handle(args, by, pad_conn))
                except PadRefused as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"手柄操作出错：{args.get('op')}", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def onboard_op(cid, args):
            """Buttons on the getting-started checklist (only record a mark, never touch the duck):
                confirm_servo              servo zero position "already calibrated, check it" (review O4; the page now uses "done", the old interface is kept)
                done {step, confirmed}     "done": I did this before (user, 10-20: "do it, done, skip, three options is fine")
                skip {step, confirmed}     "skip": not now (user, 10-18: "skipping and redoing should be allowed")
                undone / unskip {step, confirmed}   cancel
            Every row can be clicked at any time; ones with consequences (main program explicitly says not done, unreadable, a problem was found, e-stop test, during servo tuning) need two clicks,
            the page only sends confirmed: true on the second, and the backend re-judges by the current situation and refuses without it (cannot rely on the page alone)"""
            op = args.get("op")
            if onboard is None:
                return {"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没开上手清单"}
            what = {"confirm_servo": "「已经校过，核对一下」", "done": "「已完成」", "skip": "跳过", "unskip": "取消跳过",
                    "undone": "取消「已完成」"}.get(op)
            if what is None:
                return {"t": "result", "id": cid, "ok": False, "reason": f"不认识的指令：{op}"}
            step = str(args.get("step") or "")
            confirmed = args.get("confirmed") is True
            if op == "confirm_servo":
                ok, why = onboard.confirm_servo(robotd, by)
            elif op in ("done", "skip"):
                ok, why = onboard.mark(step, op, robotd, pad, servo, by, confirmed)
            else:
                ok, why = onboard.unmark(step, "skip" if op == "unskip" else "done", by, servo, confirmed)
            if ok:
                onboard.tick(robotd, pad, servo)               # re-judge right away so the page need not wait for the next tick
                await asyncio.to_thread(onboard.save)
            else:
                log.info(f"上手清单{what}没记：{why}", cat="校准", step=step or "上手清单")
            return {"t": "result", "id": cid, "ok": ok, "reason": why}

        async def run_battery_op(cid, args):
            """The settings page "Battery" section: get / set / calibrate (studio/battery_svc.py). Only changes Studio's own settings, never touches the duck."""
            data, ok, reason = None, True, None
            if battery is None:
                ok, reason = False, "这只鸭子没开电量估算"
            else:
                try:
                    data = await battery.handle(args, by)
                except ValueError as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"电池设置出错：{args.get('op')}", cat="电池", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_net_op(cid, args):
            """Network setup page: scan / connect / forget. connect first replies "switching started"; actually shutting the hotspot and connecting Wi-Fi happen in the background."""
            from .net import Refused as NetRefused, validate_connect
            if net is None:
                await send({"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没开配网"})
                return
            op = args.get("op")
            if op == "scan":
                try:
                    data = await net.scan()
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                except Exception as e:  # noqa: BLE001
                    log.error("扫 WiFi 出错", cat="网络", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                    return
                await send({"t": "result", "id": cid, "ok": True, "data": data})
                return
            if op == "connect":
                try:
                    ssid, psk = validate_connect(args.get("ssid"), args.get("psk"))
                    started = net.begin_connect()
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                if not started:
                    await send({"t": "result", "id": cid, "ok": False, "reason": "正在连，等一下"})
                    return
                # Let the page receive the acknowledgment first (showing "switching…"); Net.connect only touches the hotspot after 2 seconds
                await send({"t": "result", "id": cid, "ok": True, "reason": "开始切换",
                            "data": {"ssid": ssid}})

                async def do_connect():
                    try:
                        await net.connect(ssid, psk, by)
                    except Exception as e:  # noqa: BLE001
                        net.busy = None
                        log.error("连 WiFi 的后台任务出错", cat="网络", raw=f"{type(e).__name__}: {e}", exc=True,
                                  hint="这是 Studio 的问题，导出诊断包发出来")
                # The reference hangs on net, not on this page's cmd_tasks: after the phone disconnects (it will as soon as the hotspot closes) the page's handler ends,
                # but this background path still has to finish connecting and write last-try
                net.connect_task = asyncio.create_task(do_connect())
                return
            if op == "forget":
                try:
                    data = await net.forget(args.get("ssid"))
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                except Exception as e:  # noqa: BLE001
                    log.error("忘掉 WiFi 出错", cat="网络", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                    return
                await send({"t": "result", "id": cid, "ok": True, "data": data})
                return
            if op in ("hotspot-up", "hotspot-down"):
                try:
                    started = net.begin_hotspot()
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                if not started:
                    await send({"t": "result", "id": cid, "ok": False, "reason": "正在处理 WiFi，等一下"})
                    return
                what = "开热点" if op == "hotspot-up" else "关热点"
                # Acknowledge first: switching to AP mode will drop this phone's connection, so the acknowledgment must go out before that
                await send({"t": "result", "id": cid, "ok": True, "reason": f"正在{what}"})
                ssid = args.get("ssid") if isinstance(args.get("ssid"), str) else None

                async def do_hotspot():
                    try:
                        if op == "hotspot-up":
                            ok, reason = await net.hotspot_up(by)
                        else:
                            ok, reason = await net.hotspot_down(by, ssid)
                        if not ok:
                            log.info(f"{what}没成：{reason}", cat="网络", step=op)
                    except Exception as e:  # noqa: BLE001
                        net.busy = None
                        log.error(f"{what}的后台任务出错", cat="网络", raw=f"{type(e).__name__}: {e}", exc=True,
                                  hint="这是 Studio 的问题，导出诊断包发出来")
                # Same as connect: after the phone disconnects the page's handler ends, but this background path still has to run to completion
                net.connect_task = asyncio.create_task(do_hotspot())
                return
            await send({"t": "result", "id": cid, "ok": False, "reason": f"不认识的配网操作：{op}"})

        async def run_onboard_op(cid, args):
            try:
                out = await onboard_op(cid, args)
            except Exception as e:  # noqa: BLE001
                log.error("上手清单的按钮出错", cat="系统", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来")
                out = {"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}"}
            try:
                await send(out)
            except Exception:  # noqa: BLE001
                pass

        async def receiver():
            while True:
                msg = await ws.receive_json()
                me["hb_at"] = time.monotonic()
                if not isinstance(msg, dict):
                    continue
                t = msg.get("t")
                if t == "hb":
                    me["route"] = msg.get("route")
                    if isinstance(msg.get("pad_visible"), bool):
                        me["pad_visible"] = msg["pad_visible"]
                    vis = bool(msg.get("visible", True))
                    if vis != me["visible"]:
                        me["visible"] = vis
                        update_viewers()
                elif t == "cmd":
                    name, cid = msg.get("name"), msg.get("id")
                    args = msg.get('args') or {}
                    if updates.installing() and not safe_during_update(name,args):
                        await send({'t':'result','id':cid,'ok':False,'reason':'软件更新正在进行，请等待完成；急停仍可使用'})
                        continue
                    if (imu is not None and getattr(imu, 'blocks_updates', lambda: False)()
                            and name in {'pad.op', 'tune.op', 'servo.open', 'servo.op', 'calib.op'}
                            and not safe_during_update(name, args)):
                        await send({'t':'result','id':cid,'ok':False,
                                    'reason':'IMU 标定 / 类型切换会话未结束：先验证完成或取消；卸力仍可使用'})
                        continue
                    if ((mapping_requests or (pad is not None and getattr(getattr(pad, 'mapping', None), 'blocked', False)))
                            and name in {'tune.op', 'servo.open', 'servo.op', 'calib.op', 'imu.op'}
                            and not safe_during_update(name, args)):
                        await send({'t':'result','id':cid,'ok':False,
                                    'reason':'请先完成或取消手柄映射并回中；网页卸力仍可使用'})
                        continue
                    if name not in COMMANDS:
                        await send({"t": "result", "id": cid, "ok": False, "reason": f"这一版还不支持「{name}」"})
                        continue
                    if name == "imu.op":
                        task = asyncio.create_task(run_imu_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "calib.op":
                        task = asyncio.create_task(run_calib_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "tune.op":
                        task = asyncio.create_task(run_tune_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "pad.op":
                        task = asyncio.create_task(run_pad_op(cid, msg.get("args") or {}))
                        if args.get('op')=='mapping' and args.get('action')=='begin':
                            # Reserve on the event loop before another command
                            # from the same WebSocket packet can start takeover.
                            mapping_requests.add(task)
                            task.add_done_callback(mapping_requests.discard)
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "onboard.op":
                        # Not awaited here: a slow disk write must not block a relax arriving later (same reasoning as code review #6)
                        task = asyncio.create_task(run_onboard_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "net.op":
                        # Wi-Fi scan takes about 10 seconds at worst and Wi-Fi connect runs in the background: neither blocks relax from the same page
                        task = asyncio.create_task(run_net_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "servo.op":
                        task = asyncio.create_task(run_servo_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "servo.ports":
                        from .servo import list_ports
                        ports = await asyncio.to_thread(list_ports)
                        await send({"t": "result", "id": cid, "ok": True, "data": {
                            "ports": ports, "port": servo.port if servo else None, "sim": bool(servo and servo.sim),
                            "state": servo.state if servo else None}})
                        continue
                    if name in ("servo.open", "servo.close"):
                        task = asyncio.create_task(run_servo(name, cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "battery.op":
                        task = asyncio.create_task(run_battery_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "relax":
                        # Relax is not awaited here (code review #6): repeated presses on the same page do not queue, and a page disconnecting does not cancel it
                        task = asyncio.create_task(run_relax(cid))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    # Added to COMMANDS but the branch was forgotten: say so explicitly rather than defaulting to relax (gamepad page review: 10 moves per second would all become relaxes)
                    log.error(f"指令「{name}」在 COMMANDS 里但没有处理分支", cat="系统", hint="这是 Studio 的 bug，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 没写「{name}」怎么处理（bug）"})

        tasks = [asyncio.create_task(f()) for f in (sender, log_forwarder, receiver)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                    log.warn("页面连接出错", cat="连接", raw=f"{type(exc).__name__}: {exc}")
        finally:
            for t in tasks:
                t.cancel()
            log.unsubscribe(logq)
            clients.pop(ws, None)
            if pad is not None:
                pad.mark_gone(pad_conn)
                asyncio.get_running_loop().run_in_executor(None, pad.drop_client, pad_conn, by)
            update_viewers()
            log.info(f"页面断开（{by}，还剩 {len(clients)} 个）", cat="连接", dedup=False)

    # ---- Servo session: marker file (review D1), hand-back, leaving, watching robotd (review D9) ----

    def marker_write(by):
        """Written when the bus opens (called in a thread): write a temp file then rename. Returns True / False; if it cannot be written, only log a warn
        (after a restart we would not know it was still open last time, but the session cannot be closed because of this: servos may be holding)."""
        if marker is None:
            return True
        data = {"v": 1, "port": servo.port, "sim": bool(servo.sim), "at": time.time(), "by": by,
                "boot_id": boot_id()}
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            tmp = marker.with_name(marker.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, marker)
            return True
        except OSError as e:
            log.warn("舵机会话的标记没写进去", cat="总线", step=str(marker), raw=f"{type(e).__name__}: {e}",
                     hint="Studio 重启以后就不知道上次还有舵机保持着；看看 state 目录满没满、有没有权限")
            return False

    async def remember_marker(by):
        """Write the session marker and record whether it was written into servo.marker_error (for the page's hint bar)."""
        ok = await asyncio.to_thread(marker_write, by)
        servo.marker_error = None if ok else (
            "会话标记没写进去：Studio 重启后不知道这里还开着。别重启 Studio，用完点「交还主程序」")
        return ok

    def marker_drop():
        if marker is None:
            return
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warn("舵机会话的标记删不掉", cat="总线", step=str(marker), raw=f"{type(e).__name__}: {e}",
                     hint="下次 Studio 起来会以为上次还开着、去接管一次总线；看看 state 目录的权限")

    def marker_read():
        """(present or not, content): content None = file corrupt (unreadable, not a JSON object)."""
        if marker is None:
            return False, None
        try:
            raw = marker.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, None
        except OSError:
            return True, None
        try:
            d = json.loads(raw)
        except ValueError:
            return True, None
        return True, d if isinstance(d, dict) else None

    async def robotd_up():
        """Can robotd's socket be connected (close right after connecting, without talking). Bench mode has no robotd."""
        addr = getattr(robotd, "addr", "none")
        if not addr or addr == "none":
            return False
        try:
            _, w = await asyncio.wait_for(open_conn(addr), 1.0)
        except Exception:  # noqa: BLE001 — connection failure or timeout both count as absent
            return False
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass
        return True

    async def handed_back(why, by=None):
        """The bus has been relaxed and closed: resume polling of the main program, start the main program, delete / keep the marker by the result, log one line (always logged: review D13)."""
        servo.handed_back_at = time.monotonic()
        servo.orphan = None
        servo.marker_error = None
        servo.giveback_error = servo.giveback_hint = None
        robotd.set_paused(False)
        log.info(f"交还主程序：{why}", cat="总线", dedup=False)
        # One-click hand-back: start the main program (helper bus-give-back soft: clear the flag, start robotd, wait for the four startup steps to succeed).
        # Delete the marker only after startup completes: if it did not start and the flag is still there, keep it so a Studio restart can carry on managing it (review #4)
        ok, gb_why = await asyncio.to_thread(_bus_give_back, by or "Studio", servo)
        if ok:
            await asyncio.to_thread(marker_drop)
            if servo.helper_available is False:
                log.warn("交还了；没装小助手，主程序要手动起：sudo systemctl start robotd", cat="总线", dedup=False)
            else:
                log.info("主程序起来了", cat="总线", dedup=False)
        else:
            servo.giveback_error = gb_why
            flag = await asyncio.to_thread(helper.flag_present)
            if flag:
                servo.giveback_hint = ("旗还在：手动 start robotd 会被挡住。再进一次舵机页、再点交还；"
                                       "或者重启鸭子（旗在 /run，重启就没了）")
            elif getattr(servo, "giveback_stuck", False):
                servo.giveback_hint = "主程序在回话，只是一直报启动阶段：多半是旧版主程序的毛病，去日志页看它最后说了什么"
                await asyncio.to_thread(marker_drop)
            else:
                servo.giveback_hint = "手动 sudo systemctl start robotd，或者再进一次舵机页再交还"
                await asyncio.to_thread(marker_drop)
            log.error(f"主程序没起来：{gb_why}", cat="总线", dedup=False, hint=servo.giveback_hint)

    async def hand_back(why, by=None):
        """Clicking "Hand back to the main program": first set closing and wait for in-flight servo operations to finish (no hand-back if that times out), then relax everything on the bus and confirm by readback
        (not relying on the main program relaxing at startup, review S1), then close the bus and start the main program (handed_back, review D2)."""
        if servo is None or servo.state != "open":
            return True, None
        ok, reason = await asyncio.to_thread(servo.hand_back_bus, why, before_close=lambda: robotd.set_paused(False))
        if not ok:
            log.error("没交还主程序", cat="总线", raw=reason, hint="等校准 / 动作做完再点「交还主程序」", dedup=False)
            return False, reason
        servo.handback_note = reason          # on success the second value is a note on "which servos were not confirmed relaxed"; None if all confirmed
        await handed_back(why, by)
        return True, None

    async def leave_servos(why, ws=None, by=None):
        """Leaving the servo page / nobody watching: if another page is still on the servo page, calibration / motion is running, or servos read right then are holding or unreadable → no hand-back, return (False, reason);
        otherwise relax, close the bus, start the main program, return (True, None) (review D2, D3)."""
        others = sum(1 for w, c in clients.items() if w is not ws and c.get("route") == "/servos")
        if others:
            return False, f"还有 {others} 个页面在舵机页"
        verdict, info = await asyncio.to_thread(servo.leave, why, before_close=lambda: robotd.set_paused(False))
        if verdict == "handed_back":
            await handed_back(why, by)
            return True, None
        if verdict == "closed":
            return True, None
        return False, info["why"]

    async def robotd_conflict():
        """robotd was started manually during the session (review D9): when it starts it releases all servos and fights Studio for the same serial port.
        Studio closes the bus (without writing to the servos), deletes the marker, resumes polling, and the hint bar turns red."""
        async with servo_gate:
            if servo.state != "open" or servo.closing:
                return
            await asyncio.to_thread(servo.close)
            servo.conflict_at = time.monotonic()
            await asyncio.to_thread(marker_drop)
            servo.marker_error = None
            robotd.set_paused(False)
        log.error("主程序被手动起来了：它会把舵机全部松开、跟 Studio 抢串口", cat="总线", step="会话期间查 robotd 的 socket",
                  hint="Studio 已经关掉舵机总线（没写舵机）。下次别手动起 robotd：先在页面上点「交还主程序」", dedup=False)

    async def servo_restore():
        """When Studio starts: the servo session was open at the last exit (marker present) → if robotd is not running, retake the bus (opened read-only, torque unchanged) and restore the session
        and hint bar; if the takeover fails → record as orphan (hint bar and relax button lead to the servo page); if robotd is running → it already released everything at startup, delete the marker (review D1)."""
        if servo is None:
            return
        if updates.installing():
            log.warn('主程序更新保护仍在：暂停自动恢复舵机会话，请先在软件更新页恢复主程序更新',cat='总线')
            return
        there, data = await asyncio.to_thread(marker_read)
        if not there:
            return
        if data is None:
            log.warn("舵机会话的标记坏了：照上次开着处理（用默认的串口）", cat="总线", step=str(marker),
                     hint="多半是写到一半断电了；不影响用")
            data = {}
        here = boot_id()
        if isinstance(data, dict) and data.get("boot_id") and here and data["boot_id"] != here:
            log.info("上次开机留下的舵机会话标记：断过电，舵机早就松了，作废", cat="总线", dedup=False)
            await asyncio.to_thread(marker_drop)
            return
        if await robotd_up():
            log.info("上次 Studio 退出时舵机会话开着；主程序现在在跑（它起来时会把舵机全部松开）：不接管", cat="总线",
                     dedup=False)
            await asyncio.to_thread(marker_drop)
            return
        port = "sim" if data.get("sim") is True else (data.get("port") if isinstance(data.get("port"), str) else None)
        async with servo_gate:
            if servo.state == "open":
                return
            robotd.set_paused(True, "调舵机（接着上次的会话）")
            # Restoring the session works the same as the web page entering the servo page: first bus_take raises the flag (robotd cannot start, management lock held, serial port confirmed free), then open the serial port.
            # Opening the serial port without raising the flag would make robotd fight Studio for the same bus as soon as it starts
            taken, take_why = await asyncio.to_thread(_bus_take, "Studio 重启后接着管", servo)
            if not taken:
                ok, why = False, take_why
                servo.orphan = {"why": take_why, "at": time.monotonic()}
                robotd.set_paused(False)
                # bus-take failing midway may already have raised the flag: start the main program to roll back (clear the flag + start robotd), do not leave a flag that keeps the main program from starting
                asyncio.create_task(asyncio.to_thread(_bus_give_back, "Studio 重启后接着管", servo))
            else:
                ok, why = await asyncio.to_thread(servo.open, "Studio 重启后接着管", port, True)
                if ok:
                    servo.orphan = None
                    servo.handed_back_at = None
                    servo.handback_note = servo.giveback_error = servo.giveback_hint = None
                    await remember_marker(data.get("by") if isinstance(data.get("by"), str) else "Studio 重启后接着管")
                else:
                    servo.orphan = {"why": why, "at": time.monotonic()}
                    robotd.set_paused(False)
                    # The main program stopped but the bus failed to open: start it back up, do not leave a flag that keeps the main program from starting
                    asyncio.create_task(asyncio.to_thread(_bus_give_back, "Studio 重启后接着管", servo))
        if ok:
            log.info(f"会话恢复：上次 Studio 退出时舵机会话开着，重新接管了总线（只读打开，没改扭矩；{servo.holding()} 颗保持着）",
                     cat="总线", dedup=False)
        else:
            log.error("上次 Studio 退出时舵机会话开着，这次没接管上：可能还有舵机保持着", cat="总线", raw=why, dedup=False,
                      hint="去舵机页接管后才能卸力；急的话关电源")

    async def servo_watch():
        """One tick per second:
        - nobody has watched the servo page for more than SERVO_IDLE_S: if no servo is holding (read right then; unreadable counts as holding), hand back automatically (when the page is closed or the network drops, the main program
          should not stay stopped and the gamepad unusable forever). If some are holding: no hand-back and no relaxing (the user decided "no automatic relaxing when nobody is operating"; a hand-back would make robotd
          release everything when it starts), only log a warn line (the same sentence at most once per minute);
        - during a session, check every 5 seconds whether robotd has started (review D9);
        - after hand-back / a marker that failed to take over: only clear the hint once the main program connects (new replies after the hand-back) (review D12)."""
        since = None
        last_probe = last_try = 0.0
        while True:
            await asyncio.sleep(1.0)
            if servo is None:
                continue
            now = time.monotonic()
            if servo.state != "open":
                since = None
                fresh = robotd.present is True and robotd.bus.at is not None
                if servo.handed_back_at is not None and fresh and robotd.bus.at > servo.handed_back_at and not robotd.paused:
                    servo.handed_back_at = None                    # the main program connected: put away the "handed back… start robotd manually" line
                    servo.handback_note = None
                    servo.giveback_error = servo.giveback_hint = None
                if servo.orphan and fresh and robotd.bus.at > servo.orphan["at"] and not robotd.paused:
                    servo.orphan = None                            # the main program is up (it will release everything): no need to take over anymore
                    await asyncio.to_thread(marker_drop)
                    log.info("上次退出时开着的舵机会话：主程序起来了（它会把舵机全部松开），不用再接管", cat="总线", dedup=False)
                continue
            probe = servo.probe_robotd if servo.probe_robotd is not None else not servo.sim
            if probe and now - last_probe >= ROBOTD_PROBE_S and not servo.closing:
                last_probe = now
                if await robotd_up():
                    await robotd_conflict()
                    continue
            here = sum(1 for c in clients.values() if c.get("route") == "/servos")
            if here:
                since = None
            elif since is None:
                since = now
            elif now - since > SERVO_IDLE_S and now - last_try >= 5.0:
                last_try = now                                     # when some are holding, check again in 5 seconds (reading torque right then)
                async with servo_gate:
                    if servo.state != "open":
                        continue
                    done, kept = await leave_servos(f"舵机页 {SERVO_IDLE_S:.0f} 秒没人在看，也没有舵机保持着", by="Studio 自动交还")
                if done:
                    since = None
                else:
                    log.warn(f"舵机页没人在看，但{kept}：不自动交还、不卸力", cat="总线", raw=kept,
                             hint="要交还点页面顶上的「交还主程序」；交还以后舵机会全部松开，先扶住")

    async def pad_feed():
        """robotd readback at 10 Hz is handed to the gamepad page backend whether or not any page is watching (the e-stop test, actions and the 2-second protection after relax all depend on it)."""
        while True:
            await asyncio.sleep(1 / STATE_HZ)
            try:
                # A server-owned music lease consumes real robot.state frames
                # even after the last browser viewer leaves the drive area.
                robotd.set_background_music(pad.motion_studio.background_music())
                pad.feed_robot(robot_view(robotd))
            except Exception as e:  # noqa: BLE001
                log.error("把主程序的状态交给手柄页时出错", cat="手柄", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来")
                await asyncio.sleep(1.0)

    async def onboard_loop():
        """Hysteresis for the getting-started checklist and board temperature: evaluated every 0.5 seconds (memory only), with records written to disk in a thread when they change (review O6: judged only here, written only here)."""
        while True:
            await asyncio.sleep(ONBOARD_TICK_S)
            try:
                # File reads (the servo-calib directory, /sys/class/thermal when robotd does not report temperature) go in a thread: an SD card stall must not block
                # relax in the same event loop (code review C9-1). tick itself uses only memory
                await asyncio.to_thread(onboard.io, onboard.need_board(robotd))
                if pad is not None:
                    pad.battery_shutdown = onboard.battery_shutdown   # the gamepad page's low-battery wording follows robotd's configuration (task 1 addendum)
                if onboard.tick(robotd, pad, servo):
                    await asyncio.to_thread(onboard.save)
            except Exception as e:  # noqa: BLE001
                log.error("上手清单判的时候出错", cat="系统", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来；不影响站和走")
                await asyncio.sleep(5.0)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        await updates.start_readiness(update_readiness)
        watch = asyncio.create_task(servo_watch())
        feed = asyncio.create_task(pad_feed()) if pad is not None else None
        ob_task = asyncio.create_task(onboard_loop()) if onboard is not None else None
        bat_task = asyncio.create_task(battery.loop()) if battery is not None else None   # battery estimation at 1 Hz (review B-R7)
        tune_task = asyncio.create_task(tune.loop()) if tune is not None else None     # tuning cards read files every 2 seconds (in a thread)
        robotd.start()
        if net is not None:
            net.start()
        restore = asyncio.create_task(servo_restore())        # the servo session was open at the last exit: carry on managing it (review D1)
        if phone_bridge is not None:
            # Load the voice model in the background first: the first utterance should not come with a 5~25 second cold start
            asr_warm = asyncio.create_task(asyncio.to_thread(phone_bridge.warmup))
        log.info(f"Studio {VERSION} 启动 · Python {platform.python_version()} · {platform.node()}", cat="系统",
                 dedup=False)
        yield
        await updates.stop_readiness()
        restore.cancel()
        watch.cancel()
        if tune_task is not None:
            tune_task.cancel()
        if bat_task is not None:
            bat_task.cancel()
        if ob_task is not None:
            ob_task.cancel()
            await asyncio.to_thread(onboard.save)
        if feed is not None:
            feed.cancel()
            await asyncio.to_thread(pad.close)
        if servo is not None and servo.state != "closed":
            # Studio exiting does not relax (review D1): only close the serial port, holding servos keep holding; the marker stays so the next startup carries on managing it
            n = servo.holding()
            await asyncio.to_thread(servo.close)
            log.info(f"Studio 退出：舵机会话开着（{n} 颗保持着），不卸力；下次起来会接着管", cat="总线", dedup=False)
        if net is not None:
            await net.stop()
        await robotd.stop()
        auth.flush()
        log.info("Studio 停止", cat="系统", dedup=False)
        log.flush()

    # ---- Two things that must be added once the phone uses https ----
    # Camera: mediad's signaling is plaintext ws, and an https page connecting directly gets blocked as mixed content.
    # So a same-origin, same-protocol /media-ws is mounted here, which Studio forwards to the local mediad signaling port.
    async def media_ws_proxy(ws: WebSocket):
        if phone_bridge is None:
            await ws.close(code=1011)
            return
        if not origin_ok(ws):
            await ws.close(code=4403)
            return
        _, sess = session_of(ws)
        if not sess:
            await ws.accept()
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            port = getattr(sensors, "camera_signaling_port", None)
            upstream = phone_bridge.MEDIA_UPSTREAM if port is None else f"ws://127.0.0.1:{port}"
            await phone_bridge.pump_media(ws, upstream=upstream)
        except Exception as exc:
            log.info(f"摄像头信令转发结束（{_client_desc(ws)}）：{exc}", cat="连接")

    # Phone speech: browser speech recognition on Android goes through Google services, which are mostly unreachable in mainland China. Send the PCM recorded on the phone back here
    # and recognize it with the same Vosk Chinese model as the onboard duck-echo, so results match speaking to the duck directly.
    async def api_asr(request):
        no_store = {"Cache-Control": "no-store"}
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False, "error": "登录过期了，重新登录再试"}, 401, headers=no_store)
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "请求校验失败，刷新页面再试"}, 403, headers=no_store)
        if phone_bridge is None:
            return JSONResponse({"ok": False, "error": "这块板子没有装语音识别模块"}, 503, headers=no_store)
        body = await request.body()
        if len(body) < 3200:          # 16 kHz / 16 bit: under 0.1 seconds, nothing can be recognized
            return JSONResponse({"ok": False, "error": "这段太短了，再说一次"}, 400, headers=no_store)
        if len(body) > 12 * 1024 * 1024:
            return JSONResponse({"ok": False, "error": "这段录音太长了"}, 413, headers=no_store)
        # free=1: no command vocabulary, general decoding. The self-check page uses it to see "what the board actually hears",
        # and to tell "not heard clearly" from "word not in the vocabulary". Much slower, for troubleshooting only.
        free = (request.query_params.get("free") or "").lower() in ("1", "true", "yes")
        detail = await asyncio.get_running_loop().run_in_executor(
            None, phone_bridge.transcribe_detail, body, not free)
        if detail.get("error"):
            return JSONResponse({"ok": False, "error": f"识别没跑起来：{detail['error']}"},
                                503, headers=no_store)
        return JSONResponse({"ok": True, "data": {"text": detail.get("text") or "",
                                                    "info": detail.get("info") or {}}},
                            headers=no_store)

    # The phone must install the local CA once before it trusts https://10.42.0.1:8000 and grants the microphone. This file must be downloadable before login.
    async def api_ca(request):
        no_store = {"Cache-Control": "no-store"}
        if not ca_cert:
            return Response("这块板子没有本地 CA", status_code=404, headers=no_store)
        try:
            body = await asyncio.to_thread(Path(ca_cert).read_bytes)
        except OSError:
            return Response("这块板子没有本地 CA", status_code=404, headers=no_store)
        return Response(body, media_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="Microduck-Local-CA.crt"',
                                 **no_store})

    routes = [
        Route("/healthz", healthz),
        Route("/api/session", api_session),
        Route("/api/ai", api_ai, methods=["GET", "POST"]),
        Route('/api/updates',api_updates,methods=['GET','POST']),
        Route('/api/updates/upload',api_updates,methods=['POST']),
        Route("/api/login", api_login, methods=["POST"]),
        Route("/api/logout", api_logout, methods=["POST"]),
        Route("/api/password", api_password, methods=["POST"]),
        Route("/api/ssh", api_ssh, methods=["POST"]),
        Route("/api/logs", api_logs),
        Route("/api/diag", api_diag),
        Route("/api/profile", api_profile),
        Route("/api/camera", api_camera),
        Route("/api/tof", api_tof),
        Route("/api/models", api_models),
        Route("/api/models/op", api_model_op, methods=["POST"]),
        Route("/api/models/import", api_model_import, methods=["POST"]),
        Route("/model/meshes.bin", meshes),
        Route("/m", lambda request: RedirectResponse("/m.html", status_code=307)),
        # Only useful once the phone uses https: local CA download, same-origin forwarding of camera signaling, phone recording to text
        Route("/ca.crt", api_ca),
        Route("/api/asr", api_asr, methods=["POST"]),
        WebSocketRoute("/media-ws", media_ws_proxy),
        WebSocketRoute("/ws", ws_endpoint),
        Mount("/", AppStatic(directory=str(web_dir), html=True)),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    return HostGuard(app, guard, log)


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"（没拿到：{type(e).__name__}: {e}）"


def _diag_zip(log, snap, raw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("先看我.txt", "Microduck Studio 诊断包\n\n"
                   "里面有：最近两天的 Studio 日志、导出时的状态、robotd 原始回包、版本、robotd/padd 的系统日志。\n"
                   "注意：含鸭子的序列号和局域网 IP。发到公开的群之前，介意的话先删掉 system.txt 和 robotd-raw.json。\n")
        for p in log.files(days=2):
            z.write(p, f"logs/{p.name}")
        z.writestr("state.json", json.dumps(snap, ensure_ascii=False, indent=1, default=str))
        z.writestr("robotd-raw.json", json.dumps(raw, ensure_ascii=False, indent=1, default=str))
        info = {"studio": VERSION, "python": sys.version, "platform": platform.platform(),
                "log": log.snapshot(), "time": time.strftime("%F %T %z")}
        z.writestr("versions.json", json.dumps(info, ensure_ascii=False, indent=1))
        deps = Path(__file__).resolve().parents[1] / "deps" / "VERSIONS.txt"
        if deps.is_file():
            z.write(deps, "deps-VERSIONS.txt")
        if sys.platform.startswith("linux"):
            z.writestr("journal-robotd.txt", _run(["journalctl", "-u", "robotd", "-n", "300", "--no-pager", "-o", "short-iso"]))
            z.writestr("journal-padd.txt", _run(["journalctl", "-u", "padd", "-n", "100", "--no-pager", "-o", "short-iso"]))
            z.writestr("system.txt", "\n".join(_run(c) for c in (["uptime"], ["free", "-m"], ["df", "-h", "/"], ["ip", "-brief", "addr"])))
    return buf.getvalue()


def precompress(web_dir):
    """Pre-compress meshes.bin to a .gz (recompressed only when the .gz is older than the original)."""
    raw = Path(web_dir) / "model" / "meshes.bin"
    gz = raw.with_suffix(".bin.gz")
    try:
        if raw.is_file() and (not gz.is_file() or gz.stat().st_mtime < raw.stat().st_mtime):
            with open(raw, "rb") as f, gzip.open(gz, "wb", compresslevel=9) as g:
                g.write(f.read())
    except OSError:
        # Web directory is read-only (after installing to /opt and switching to a dedicated user): skip compressing and serve the original file
        return None
    return gz
