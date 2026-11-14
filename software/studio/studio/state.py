"""Aggregates raw robotd / configd data into one small object pushed to the page (always arrays; missing fields mean unknown).

Posture is determined per the table in review-impl-plan I2, looking at mode first, then phase:
    absent         robotd's socket missing / connection refused
    starting       phase is configuring_bus / waiting_for_bus / configuration_error (also the startup report before the first successful read in calibration mode;
                   the old fork stays here forever; after 30+ seconds in a row the page changes to "一直报启动中" (keeps reporting starting): starting_secs)
    commissioning  live snapshot with mode == "commissioning" (ready / moving / read_error / stop_unconfirmed / power_pending:
                   the main program is up; robotd is read-only at this point and rejects init/enable/do)
    sitting        robot.policies.sitting
    limp           native.torque_state_confirmed == False
    walking        policy_enabled, and move.applied is not 0
    policy         policy_enabled (standing, policy running)
    holding        torque on, homed, home_start_guard.ready, policy not enabled (holds HOME after init; joints have actually reached position too)
    homing         torque on, not at HOME yet
    unknown        not enough data

Only produces states for text, not buttons (buttons are in S1b).
"""
import math
import time

from .estop import STARTING_LONG_S, STARTING_PHASES
from .startup import startup_todo
from .startup_status import imu_context_current, imu_diagnostic, servo_observations, startup_wait

JOINT_NAMES = ["left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
               "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
               "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle"]
JOINT_CN = {"left_hip_yaw": "左髋转向", "left_hip_roll": "左髋横滚", "left_hip_pitch": "左髋俯仰", "left_knee": "左膝",
            "left_ankle": "左踝", "neck_pitch": "脖子", "head_pitch": "头俯仰", "head_yaw": "头转向", "head_roll": "头横滚",
            "mouth": "嘴", "right_hip_yaw": "右髋转向", "right_hip_roll": "右髋横滚", "right_hip_pitch": "右髋俯仰",
            "right_knee": "右膝", "right_ankle": "右踝"}
STALE_S = 3.0
# Maximum age for each kind of data (code review #18: after a query fails, stale values must not keep being used to judge "sitting / walking", battery and temperature)
MAX_AGE = {"health": 8.0, "policies": 6.0, "state": 1.5, "pad": 15.0}
CPU_WARN_C = 80          # this board idles at 78 °C; a 75 °C warning would be on all the time, and eventually nobody would look at it


def _fresh(sample, key, now):
    age = sample.age(now)
    return sample.value if age is not None and age <= MAX_AGE[key] else None


def _ms(age):
    return None if age is None else int(age * 1000)


def starting_secs(rd, bus, now=None):
    """How many seconds in a row the main program has reported a startup phase since this connection (robotd.Robotd.starting_since, recorded in polling). None when not in a startup phase / unknown.
    Beyond STARTING_LONG_S the page stops saying "通常 10 秒内完成" (usually done within 10 seconds) (Oct 20 real hardware: the old fork's calibration mode always reports configuring_bus)."""
    since = getattr(rd, "starting_since", None)
    if since is None or not isinstance(bus, dict) or bus.get("phase") not in STARTING_PHASES:
        return None
    return max(0, int((time.monotonic() if now is None else now) - since))


STILL_STARTING = "主程序可能其实起来了、只是状态没更新（旧版主程序的毛病），也可能卡在启动：去日志页看主程序最后说了什么"


def posture(present, bus, policies, state):
    if present is False:
        return "absent"
    if not isinstance(bus, dict):
        return "unknown"
    mode, phase = bus.get("mode"), bus.get("phase")
    if phase in STARTING_PHASES:
        return "starting"
    if mode == "commissioning":
        return "commissioning"
    if mode != "motion":
        return "unknown"
    if isinstance(policies, dict) and policies.get("sitting") is True:
        return "sitting"
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    confirmed = native.get("torque_state_confirmed")
    if confirmed is False:
        return "limp"
    if bus.get("policy_enabled") is True:
        applied = ((state or {}).get("move") or {}).get("applied") if isinstance(state, dict) else None
        if isinstance(applied, list) and any(abs(v) > 0.01 for v in applied if isinstance(v, (int, float))):
            return "walking"
        return "policy"
    if confirmed is True:
        if bus.get("homed") is not True:
            return "homing"
        # homed only means "the control loop thinks it reached HOME"; the actual joint positions still lag a bit: only the main program's own home_start_guard
        # looks at both actual joint positions (≤ joint_tolerance_deg) and body tilt, and requires several consecutive stable ticks.
        # Only when robotd doesn't provide this field (old versions) do we fall back to looking at homed alone.
        guard = bus.get("home_start_guard")
        if isinstance(guard, dict) and isinstance(guard.get("ready"), bool):
            return "holding" if guard["ready"] else "homing"
        return "holding"
    return "unknown"


def tilt_deg(gravity):
    """Same algorithm as robotd's home_start.rs: the angle between gravity and straight down (0,0,-1)."""
    if not isinstance(gravity, (list, tuple)) or len(gravity) != 3:
        return None
    n = math.sqrt(sum(g * g for g in gravity))
    if n < 1e-6:
        return None
    c = max(-1.0, min(1.0, -gravity[2] / n))
    return math.degrees(math.acos(c))


def cpu_view(health, health_age, bus, present, servo=None, ob=None):
    """Board temperature cell (overview reorg review O8, O5). Fields:
        c          °C: the hottest of all thermal zones (robotd health's cpu_temp_c, fork soc.rs:25-64); None if unreadable
        throttled  the kernel's thermal control is throttling (cooling device level > 0) → page shows red "降频了 x / y MHz" (throttled x / y MHz); None = unreadable, **not "normal"**
        limited    level is 0 but the allowed frequency is below the maximum: frequency-capped, most likely not due to heat (original intent of fork lib.rs:3615-3651)
        khz / max_khz / level / max_level   passed through as is (khz is "how fast it is allowed to run", not the instantaneous frequency)
        hot        ≥ 80 °C (with hysteresis: cleared only below 77 °C; the hysteresis state is kept in onboard.Onboarding.cpu_hot; without it, no hysteresis)
        src        robotd / studio (when robotd doesn't report, Studio reads /sys/class/thermal itself: only exists on the duck; if missing during development on a computer, skip it)
        why        reason it is unreadable (main program didn't report / tuning servos / not reported in debug mode / not reported while waiting for bus / health check stale)
    robotd samples it once per second only in the motion-mode control loop (fork main.rs:117-120, 4148-4154); it doesn't sample in debug mode or while waiting for the bus."""
    out = {"c": None, "throttled": None, "limited": None, "khz": None, "max_khz": None, "level": None, "max_level": None,
           "hot": False, "src": None, "why": None}
    h = health if isinstance(health, dict) else None
    c = (h or {}).get("cpu_temp_c")
    thr = (h or {}).get("cpu_throttle") if isinstance((h or {}).get("cpu_throttle"), dict) else None
    src = "robotd" if isinstance(c, (int, float)) else None
    board = getattr(ob, "board", None) if ob is not None else None
    if not isinstance(c, (int, float)) and isinstance(board, dict) and isinstance(board.get("c"), (int, float)):
        c, thr, src = board["c"], board.get("throttle"), "studio"
    if isinstance(c, (int, float)):
        out.update(c=round(float(c), 1), src=src)
        out["hot"] = bool(ob.cpu_hot) if ob is not None else c >= CPU_WARN_C
    else:
        if servo is not None and getattr(servo, "state", None) in ("open", "opening"):
            why = "在调舵机：主程序按计划停着，不报温度"
        elif present is False:
            why = "主程序没在跑"
        elif (bus or {}).get("mode") == "commissioning":
            why = "调试模式下主程序不报温度"
        elif (bus or {}).get("phase") in STARTING_PHASES:
            wait = startup_wait(bus)
            why = f"主程序{wait['text'] if wait else '还在启动'}，这时不报温度"
        elif h is None:
            why = f"健康检查 {health_age:.0f} 秒没更新" if health_age is not None else "还没读到健康检查"
        else:
            why = "主程序没报温度"
        out["why"] = why
    if isinstance(thr, dict):
        lv, mx, khz, mk = thr.get("level"), thr.get("max_level"), thr.get("khz"), thr.get("max_khz")
        out.update(level=lv, max_level=mx, khz=khz, max_khz=mk)
        nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lv, khz, mk))
        if nums:
            out["throttled"] = lv > 0
            out["limited"] = lv == 0 and mk > 0 and khz < mk
    elif out["c"] is not None:
        out["throttled"] = None          # temperature known, no throttling data: unknown, don't write "normal"
    return out


def servo_session_view(servo):
    """A few words about the servo session (for the banner); None if not open. unknown = number of servos whose torque can't be read (they may also be holding: review D3c);
    restored = taken over again after a Studio restart (review D1)."""
    if servo is None or getattr(servo, "state", None) not in ("open", "opening"):
        return None
    holding = servo.holding() if hasattr(servo, "holding") else None
    return {"state": servo.state, "holding": holding, "latched": bool(getattr(servo, "latched", False)),
            "unknown": servo.unknown() if hasattr(servo, "unknown") else 0,
            "restored": bool(getattr(servo, "restored", False)), "closing": bool(getattr(servo, "closing", False)),
            "port": "演示（没接舵机）" if getattr(servo, "sim", False) else getattr(servo, "port", None)}


def servo_orphan_view(servo):
    """The servo session was open when Studio last exited and wasn't taken over this time (review D1): some servos may still be holding; to relax, first take over on the servo page."""
    o = getattr(servo, "orphan", None) if servo is not None else None
    if not o or getattr(servo, "state", None) in ("open", "opening"):
        return None
    return {"why": o.get("why")}


def summarize(rd, duck, servo=None, now=None, ob=None, bat=None, net=None, commit=None, auth=None):
    """bat: battery estimate (studio/battery_svc.BatteryService, fed in the 1 Hz loop); this only reads its result. If not given, use robotd's linear mapping (the old way)."""
    now = time.monotonic() if now is None else now
    bus = rd.bus.value
    health, pol, st = _fresh(rd.health, "health", now), _fresh(rd.policies, "policies", now), _fresh(rd.state, "state", now)
    bus_age, st_age = rd.bus.age(now), rd.state.age(now)
    native = (bus or {}).get("native") if isinstance((bus or {}).get("native"), dict) else {}

    # Freshness: how long since Studio itself got new data (the browser side adds the transport age on top)
    freshest = min([a for a in (bus_age, st_age) if a is not None], default=None)
    robotd_ok = rd.present is True and bus_age is not None and bus_age < STALE_S

    # Gauge strip
    b = (health or {}).get("battery") or {}
    battery = {"pct": b.get("percent"), "volts": b.get("volts")}
    joints = native.get("joints") if isinstance(native.get("joints"), list) else []
    fresh = [j for j in joints if isinstance(j, dict) and j.get("feedback_fresh") is True]
    motors = (health or {}).get("motors") or {}
    hottest = None
    if isinstance(motors.get("max_c"), (int, float)):
        hottest = {"name": JOINT_CN.get(motors.get("hottest"), motors.get("hottest")), "c": motors.get("max_c")}
    servos = {"online": len(fresh) if joints else None, "total": len(joints) or 15, "hottest": hottest,
              "stale": [JOINT_CN.get(j.get("name"), j.get("name")) for j in joints
                        if isinstance(j, dict) and j.get("feedback_fresh") is False]}
    observations = servo_observations(bus, present=rd.present, bus_age_s=bus_age,
                                      bus_error=getattr(rd.bus, "error", None))
    if observations is not None:
        rows = observations["rows"]
        temperatures = [r for r in rows if r["temperature_c"] is not None]
        hot = max(temperatures, key=lambda r: r["temperature_c"]) if temperatures else None
        servos = {"online": observations["online"], "total": len(rows) or 15,
                  "hottest": {"name": JOINT_CN.get(hot["name"], hot["name"]), "c": hot["temperature_c"]} if hot else None,
                  "stale": [JOINT_CN.get(r["name"], r["name"]) for r in rows if r["responding"] is False]}
    imu_h = (health or {}).get("imu") or {}
    if imu_h.get("ready") is False:
        imu_status = "missing"
    elif (imu_h.get("consecutive_stale_blocks") or 0) >= 25:
        imu_status = "frozen"
    elif native.get("imu_mount_verified") is False:
        imu_status = "unverified"      # orientation not confirmed: if mounted crooked, walking lunges forward (root cause of the Oct 12 lunge)
    elif imu_h.get("ready") is True:
        imu_status = "ok"
    else:
        imu_status = None
    pad_v = _fresh(rd.pad, "pad", now)
    pads = (pad_v.get("pads") or []) if isinstance(pad_v, dict) else None
    pad = {"known": pads is not None, "connected": bool(pads and any(p.get("connected") for p in pads if isinstance(p, dict))),
           "name": next((p.get("name") for p in (pads or []) if isinstance(p, dict) and p.get("connected")), None),
           "driver": pad_v.get("driver") if isinstance(pad_v, dict) else None}
    pad["estop_ok"] = bool(pad["connected"] and pad["driver"] == "active" and (bus or {}).get("mode") == "motion")

    cpu = cpu_view(health, rd.health.age(now), bus, rd.present, servo, ob)
    loop = (health or {}).get("control_loop") or {}

    # 3D: joint radians given as-is in JOINT_NAMES order (direction not applied), gravity from safety.gravity.
    # Stale ones are passed too (the page desaturates them by joints_age_ms); posture determination only uses the fresh st
    st_any = rd.state.value if isinstance(rd.state.value, dict) else {}
    js = st_any.get("joints")
    grav = (st_any.get("safety") or {}).get("gravity")

    st_age_live = st_age
    state_t_ns = st_any.get("t_ns")
    hold = (bus or {}).get("hold") if isinstance((bus or {}).get("hold"), dict) else None
    if (bus or {}).get("mode") == "commissioning":
        # Calibration mode has no robot.state: IMU readings come from busStatus.last_sample (10 Hz polling in calibration mode),
        # so the IMU page's "now" and standing calibration both get live data (user Oct 21: calibration mode can also hold a standing pose and calibrate while standing)
        ls = (bus or {}).get("last_sample") if isinstance((bus or {}).get("last_sample"), dict) else {}
        s_imu = ls.get("imu") if isinstance(ls.get("imu"), dict) else {}
        g = s_imu.get("gravity")
        if s_imu.get("valid") is True and isinstance(g, list) and len(g) == 3:
            grav = g
            st_age_live = bus_age
            state_t_ns = ls.get("at_us") * 1000 if isinstance(ls.get("at_us"), int) else None
    pose = posture(rd.present, bus, pol, st)
    est = rd.estop.status(present=rd.present is not False, bus=bus, bus_age_s=bus_age, now=now)
    if servo_orphan_view(servo) is not None and rd.present is not True:
        # The session was open at last exit and wasn't taken over this time (review D1): robotd isn't there and the bus isn't taken over either; to relax, first take over on the servo page
        est = {"state": "unavailable", "why": "上次 Studio 退出时可能还有舵机保持着：去舵机页接管后才能卸力"}
    if servo is not None and servo.state in ("open", "opening"):
        # Tuning servos: robotd is stopped on purpose. Relax is judged by bus readback; battery uses the average voltage of the 15 servos (same algorithm as official)
        pose = "servo_session"
        robotd_ok = True
        freshest = 0.0                  # main program polling is paused on purpose: freshness follows the servo bus (read at 50 Hz)
        est = servo.estop_status()
        snap = servo.snapshot()
        if snap.get("avg_volts"):
            battery = {"pct": snap.get("battery_pct"), "volts": snap.get("avg_volts")}
        servos = {"online": snap.get("online"), "total": snap.get("total"), "hottest": None, "stale": []}
    if bat is not None:
        battery = bat.view(now)         # estimate from a voltage lookup table (while tuning servos it takes Studio's own bus readings): battery-plan.md v2
    starting_s = starting_secs(rd, bus, now) if pose == "starting" else None
    return {
        "t": "state",
        "robotd_ok": robotd_ok,
        "robotd_age_ms": _ms(freshest),
        "health_age_ms": _ms(rd.health.age(now)),
        "present": rd.present,
        "mode": (bus or {}).get("mode"),
        "phase": (bus or {}).get("phase"),
        "build": (bus or {}).get("build"),
        "posture": pose,
        "start_error": (bus or {}).get("error") if pose == "starting" else None,
        "start_wait": startup_wait(bus) if pose == "starting" else None,
        # How many seconds in a row a startup phase has been reported (counted from this connection) and whether it exceeds 30 seconds: overview hero, top bar and to-do switch to "一直报启动中" (keeps reporting starting)
        "starting_s": starting_s,
        "starting_long": starting_s is not None and starting_s >= STARTING_LONG_S,
        "battery": battery,
        "servos": servos,
        "imu": {"status": imu_status, "source": native.get("imu_source"),
                "configured_imu_profile": native.get("configured_imu_profile", (bus or {}).get("configured_imu_profile")),
                "context_current": imu_context_current(rd, now),
                "generation": getattr(getattr(rd, "hello", None), "at", None),
                "diagnostic": imu_diagnostic(rd, now)},
        "pad": pad,
        "cpu": cpu,
        "loop": {"hz": loop.get("achieved_hz"), "target": loop.get("target_hz"), "missed": loop.get("missed")},
        "joints": js if isinstance(js, list) and len(js) == 15 else None,
        "joints_age_ms": _ms(st_age_live),
        "state_t_ns": state_t_ns,   # timestamp of this robotd frame: the IMU page uses it to dedupe (don't count the same frame as two readings)
        "gravity": grav if isinstance(grav, list) and len(grav) == 3 else None,
        "tilt_deg": tilt_deg(grav),
        "guard": (bus or {}).get("home_start_guard"),
        "hold": hold,                  # standing-pose enable in calibration mode: {stage: ramping|holding, max_error_deg, directions}
        "estop": est,
        # startup_todo (tuning plan T1): replace "还在启动" (still starting) with the current step's original message, add "走路模型没加载" (walking model not loaded)
        "todo": startup_todo(rd, todo(health, bus, servos, imu_status, cpu, loop, battery, pose, rd.health.age(now),
                     battery_shutdown=getattr(ob, "battery_shutdown", None) if ob is not None else None,
                     starting_s=starting_s), pol, bus),
        # Onboarding checklist: the backend evaluates it every 0.5 s (onboard.Onboarding.tick); here we only take the cache (review O6: this runs 10 times per second × each page)
        "onboarding": ob.view() if ob is not None else None,
        # Commit to main program: readiness + background task progress (CommitService; None when there is no such backend)
        "commit": (commit.view(rd, servo) if commit is not None else None),
        # Servo session (for the banner at the top of every page): included while open; leaving the servo page with servos still holding doesn't hand back, so the session stays open (user Oct 18)
        "servo_session": servo_session_view(servo),
        # How long since hand-back: if the main program was stopped manually it has to be started on the duck; the page keeps prompting until the main program connects (cleared by the app's servo_watch on connect: review D12)
        "servo_handback_s": (int(now - servo.handed_back_at) if servo is not None and servo.state == "closed"
                             and getattr(servo, "handed_back_at", None) is not None else None),
        "servo_helper": bool(getattr(servo, "helper_available", False)),   # root helper available: hand-back prompt says "正在把主程序起回来…" (bringing the main program back…) (review D12)
        # Servos whose relax wasn't confirmed / baseline didn't respond after a successful hand-back (F6); why the main program didn't come up after hand-back and how to recover (F7)
        "servo_handback_note": getattr(servo, "handback_note", None) if servo is not None else None,
        "servo_giveback_error": getattr(servo, "giveback_error", None) if servo is not None else None,
        "servo_giveback_hint": getattr(servo, "giveback_hint", None) if servo is not None else None,
        # Session marker wasn't written (F10): after a Studio restart it won't know the session is still open
        "servo_marker_error": getattr(servo, "marker_error", None) if servo is not None else None,
        # The session was open at last exit and wasn't taken over this time (review D1); the main program was started manually during the session (review D9, within 10 minutes)
        "servo_orphan": servo_orphan_view(servo),
        "servo_conflict_s": (int(now - servo.conflict_at) if servo is not None and getattr(servo, "conflict_at", None) is not None
                             and servo.state == "closed" and now - servo.conflict_at < 600 else None),
        # Network setup (studio/net.py): net.json missing = known False, the whole WiFi block on the page is hidden
        "net": net.view(now) if net is not None else {"known": False},
        "auth": {"has_password": auth.has_password() if auth is not None else None},
        "duck": duck,
        "name_on_duck": (rd.sysinfo.value or {}).get("name"),
    }


def todo(health, bus, servos, imu_status, cpu, loop, battery, pose, health_age=None, battery_shutdown=None, starting_s=None):
    """Translates the health verdict into plain language, most urgent first. Only "things to deal with"; nothing for normal state.
    Each item has a key: things the overview onboarding checklist already says (the card header's "连上鸭子" (connect to the duck), IMU orientation) are deduped by key on the page, so the same thing is said only once (review O15).
    starting_s: how many seconds in a row a startup phase has been reported; beyond 30 seconds the "还在启动" (still starting) item changes to "一直报启动中" (keeps reporting starting) and no longer says "通常 10 秒内完成" (usually done within 10 seconds)."""
    items = []
    # Battery: if battery is the estimator's result (has mode) use battery.todo_items; very low voltage / red line goes first, also shown while tuning servos (review B-R6).
    # Without the estimator (battery has only pct / volts) keep using the old robotd linear approach below
    bat_items = None
    if isinstance(battery, dict) and "mode" in battery:
        from .battery import todo_items as battery_todo
        bat_items = battery_todo(battery)
        items += [i for i in bat_items if i["level"] == "error"]
    if health is None and pose not in ("absent", "unknown", "servo_session"):   # while tuning servos the main program is stopped on purpose; that doesn't count as unreadable
        # Health check stale or unreadable: must not show "没有要处理的事" (nothing to deal with); that would be false reassurance
        when = f"{health_age:.0f} 秒没更新" if health_age is not None else "一直没读到"
        items.append({"key": "health", "level": "warn", "msg": "读不到健康检查",
                      "hint": f"电量、温度、IMU 这些{when}；看日志里的 robotd 那几行"})
    if pose == "starting":
        raw = (bus or {}).get("error")
        wait = startup_wait(bus)
        if wait:
            items.append({"key": "starting", "level": "warn", "msg": wait["text"],
                          "hint": f"原文：{raw}" if raw else "去日志页看主程序最后说了什么"})
        elif starting_s is not None and starting_s >= STARTING_LONG_S:
            items.append({"key": "starting", "level": "warn", "msg": "主程序一直报「启动中」",
                          "hint": f"已经 {starting_s} 秒了。" + (f"原文：{raw}。去日志页看主程序最后说了什么" if raw
                                                                  else STILL_STARTING)})
        else:
            items.append({"key": "starting", "level": "warn", "msg": "鸭子主程序还在启动",
                          "hint": f"原文：{raw}" if raw else "通常 10 秒内完成"})
    if pose == "servo_session":
        items.append({"key": "servo_session", "level": "warn", "msg": "正在调舵机",
                      "hint": "主程序停着，手柄、遥控、站走都不能用；离开舵机页舵机照样保持，点「交还主程序」才交还"})
        if bat_items is not None:
            items += [i for i in bat_items if i["level"] != "error"]
        else:
            # Without the estimator: battery to-do is also shown while tuning servos (review D8); voltage is the average of Studio's own 15 bus readings (swapped in by summarize).
            # robotd is stopped then, so whether auto-shutdown is enabled in its config doesn't matter
            pct = battery.get("pct") if isinstance(battery, dict) else None
            if isinstance(pct, (int, float)) and pct < 15:
                items.append({"key": "battery", "level": "error", "msg": f"电量只剩 {pct:.0f}%",
                              "hint": "该充电了；robotd 停着，没电它不会自己坐下"})
            elif isinstance(pct, (int, float)) and pct < 30:
                items.append({"key": "battery", "level": "warn", "msg": f"电量 {pct:.0f}%",
                              "hint": "快没电了；robotd 停着，没电它不会自己坐下"})
        return items
    if pose == "absent":
        items.append({"key": "absent", "level": "error", "msg": "鸭子主程序没在跑", "hint": "停掉 robotd 不会卸力，舵机可能还顶着"})
    items += [i for i in bat_items or () if i["level"] != "error"]
    pct = battery.get("pct") if bat_items is None else None
    if isinstance(pct, (int, float)):
        if pct < 15:
            # Whether it sits down and shuts off on its own when the battery is empty depends on robotd's config [safety] battery_empty_shutdown (read in a thread by onboard.py):
            # duck #2's real hardware config is false: nothing makes it stop when the battery is empty. If unreadable, say "it won't" (better to make people stop it first)
            empty = ("到 6.6 V 它会自己坐下关机" if battery_shutdown is True
                     else "没电时它不会自己坐下，先停下、坐下再充")
            items.append({"key": "battery", "level": "error", "msg": f"电量只剩 {pct:.0f}%", "hint": f"该充电了；{empty}"})
        elif pct < 30:
            items.append({"key": "battery", "level": "warn", "msg": f"电量 {pct:.0f}%", "hint": "快没电了"})
    if imu_status == "frozen":
        items.append({"key": "imu_frozen", "level": "error", "msg": "IMU 读数冻住了", "hint": "姿态数据不更新，别走路；检查 IMU 的线"})
    elif imu_status == "missing":
        items.append({"key": "imu_missing", "level": "error", "msg": "读不到 IMU", "hint": "检查 IMU 模块的接线"})
    elif imu_status == "unverified":
        items.append({"key": "imu_unverified", "level": "warn", "msg": "IMU 的安装方向还没确认",
                      "hint": "装歪了走路会往前冲；先去「IMU」页校准（fork 上没确认连站都不让）"})
    if servos.get("stale"):
        items.append({"key": "servo_stale", "level": "warn", "msg": f"{'、'.join(servos['stale'][:3])} 读数没更新",
                      "hint": "多半是线松了或者没电"})
    khz, mk = cpu.get("khz"), cpu.get("max_khz")
    if cpu.get("throttled"):
        mhz = f"：{khz // 1000} / {mk // 1000} MHz" if isinstance(khz, int) and isinstance(mk, int) and mk else ""
        items.append({"key": "cpu", "level": "warn", "msg": f"主板过热降频了{mhz}", "hint": "控制会变慢；加散热片或小风扇"})
    elif cpu.get("hot") and isinstance(cpu.get("c"), (int, float)):
        # Use the same hysteresis hot as the board cell (on at ≥ 80 °C, off only below 77 °C: review O8); otherwise at 78–80 °C idle it would flip back and forth
        items.append({"key": "cpu", "level": "warn", "msg": f"主板 {cpu['c']:.0f} °C，有点热", "hint": "再热就会降频，控制会变慢；加散热片或小风扇"})
    elif cpu.get("limited") and isinstance(khz, int):
        items.append({"key": "cpu", "level": "warn", "msg": f"主板被限频到 {khz // 1000} MHz（不是热的）",
                      "hint": "有程序（或系统设置）把 CPU 最高频率压低了；控制可能变慢"})
    hz, target = loop.get("achieved_hz") or loop.get("hz"), loop.get("target_hz") or loop.get("target")
    if isinstance(hz, (int, float)) and isinstance(target, (int, float)) and target and hz < 0.95 * target:
        items.append({"key": "loop", "level": "warn", "msg": f"控制频率只有 {hz:.1f} Hz", "hint": f"目标 {target:.0f} Hz；看主板温度和负载"})
    return items
