"""State of the relax (torque-off) button, derived entirely from data, not from "was it pressed" (review-impl-plan I5).

In motion mode robot.relax only puts the request into a slot and immediately replies accepted:true —— **the reply does not mean torque is already off**.
So confirmation looks at busStatus:

Motion mode (all 5 conditions met; the rules are the same as our install script imu-module-install.sh:165-170):
    mode == "motion"
    torque_off_pending is not true
    native.torque_state_confirmed is False
    native.hd1910.restore_pending is False
    native.hd1910.temporary_gains_applied is False
Debug mode:
    torque_state == "off" and torque_off_pending is empty

The course of one "press" (driven by robotd.py; this only records facts):
    press()        pressed: start an attempt. With repeated presses the last one counts: wait again for both the ack and the readback
    sent()         robotd acked the relax (record the time sent_at). Only sends that started after this press (at most 0.3 s earlier)
                   count: an old send already on its way while robotd was stuck doesn't count (re-review #3)
    on_bus()       polling got a busStatus. **Only a query issued after sent_at and after the last press**
                   that sees torque OFF counts as confirmation —— a query issued earlier may reflect the state before relaxing (code review #3, re-review #2)
    finish()       confirmed / not confirmed in 8 s / not sent: this attempt ends and pressed_at is cleared.
                   After it ends it won't resend on its own (code review #1: previously pressed_at wasn't cleared after confirmation,
                   and when someone else made it stand up with the gamepad, Studio would automatically send another relax)
Resending (once if not confirmed in 2 s) and the timeout (8 s) are done on a timer by the watcher task in robotd.py, regardless of whether anyone is looking at the page.

The button's four states (status() is read-only and changes nothing):
    ready        can be pressed
    pending      pressed, not confirmed yet
    confirmed    confirmed OFF (fresh readback within 1.5 s; goes back to ready if someone else enables torque again; also this if it was already limp)
    unavailable  main program missing or still starting, or the last attempt wasn't sent / not confirmed in 8 s (the notice returns to ready after 6 s)
When the state can't be read (busStatus is stale) it is still ready: pressing still sends, confirmation just waits for readback to recover.
"""
import time

STARTING_PHASES = ("configuring_bus", "waiting_for_bus", "configuration_error")
# Commissioning mode is up: robot.busStatus returns the live snapshot from feetech_commissioning.rs (Status, around line 1083 in the fork), and phase is one of these.
# The phase of the startup report ({"mode":"commissioning","phase":"configuring_bus",...}) is in STARTING_PHASES;
# the old fork never clears it, so Studio always sees "starting" (10-20 real-hardware acceptance check); the new fork clears it after the first successful read (around line 1497)
# holding: commissioning-mode "stance enable" (fork hold-home) is standing; torque is at torque_state=all_enabled, relaxing goes through robot.relax as usual
COMMISSIONING_UP = ("ready", "moving", "holding", "read_error", "stop_unconfirmed", "power_pending")
STARTING_LONG_S = 30.0       # main program keeps reporting a startup phase for this long (counted by Studio from this connection): switch to saying "keeps reporting starting" (the old fork's problem, or really stuck)
CONFIRM_TIMEOUT_S = 8.0
RESEND_AT_S = 2.0
CONFIRMED_FRESH_S = 2.5      # showing "relaxed" requires the readback to be no older than this (polling is once a second; 1.5 s flickers back and forth when queries are slow, re-review #7)
OUTCOME_SHOW_S = 6.0
JOIN_S = 0.3                 # a send already on its way at press time, started less than 0.3 s earlier, counts for this press


def robotd_up(bus):
    """Is the main program up (standing or not): motion mode has entered control, or commissioning mode returns a live snapshot (phase in COMMISSIONING_UP;
    read_error also counts as up, just that reading servos failed). Startup phases and anything unrecognized are False."""
    if not isinstance(bus, dict):
        return False
    mode, phase = bus.get("mode"), bus.get("phase")
    return (mode == "motion" and phase == "control") or (mode == "commissioning" and phase in COMMISSIONING_UP)


def relaxed(bus):
    """Does busStatus say torque is confirmed OFF? True / False / None (not enough data, unknown)."""
    if not isinstance(bus, dict):
        return None
    mode = bus.get("mode")
    if mode == "motion":
        native = bus.get("native")
        if not isinstance(native, dict) or "torque_state_confirmed" not in native:
            return None
        hd = native.get("hd1910") or {}
        return (bus.get("torque_off_pending") is not True
                and native.get("torque_state_confirmed") is False
                and hd.get("restore_pending") is False
                and hd.get("temporary_gains_applied") is False)
    if mode == "commissioning":
        if "torque_state" not in bus:
            return None
        return bus.get("torque_state") == "off" and not bus.get("torque_off_pending")
    return None


def torque_off(bus):
    """Is torque itself confirmed OFF (ignoring the hd1910 flag). Used to decide whether to resend."""
    if not isinstance(bus, dict):
        return False
    if bus.get("mode") == "commissioning":
        return bus.get("torque_state") == "off"
    native = bus.get("native")
    return isinstance(native, dict) and native.get("torque_state_confirmed") is False


def evidence(bus):
    """The context logged when confirmation fails: the fields used to judge relaxing."""
    if not isinstance(bus, dict):
        return {"busStatus": None}
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    hd = native.get("hd1910") if isinstance(native.get("hd1910"), dict) else {}
    return {"mode": bus.get("mode"), "phase": bus.get("phase"), "torque_off_pending": bus.get("torque_off_pending"),
            "torque_state": bus.get("torque_state"), "torque_state_confirmed": native.get("torque_state_confirmed"),
            "restore_pending": hd.get("restore_pending"), "temporary_gains_applied": hd.get("temporary_gains_applied")}


class EStop:
    def __init__(self):
        self.pressed_at = None       # when the attempt in progress started (monotonic); None = none
        self.sent_at = None          # time of robotd's first ack in this attempt
        self.resent = False
        self.saw_off = False         # a readback after the ack showed torque confirmed OFF (after that only the hd1910 flag is missing, no need to resend)
        self.send_error = None       # the first send went out, but a later resend / re-press failed to send: the reason (logged on timeout)
        self.press_count = 0
        self.last_by = None
        self.confirm_ms = None       # how many milliseconds the latest press-to-confirm took
        self.outcome = None          # result of the latest attempt: confirmed / timeout / send_failed / refused
        self.outcome_at = None
        self.outcome_why = ""

    @property
    def active(self):
        return self.pressed_at is not None

    def press(self, by=None, now=None):
        """Each press restarts the timer and waits again for both ack and readback (holding space to repeat, tapping repeatedly on a phone: the last one counts)."""
        now = time.monotonic() if now is None else now
        self.sent_at = None
        self.resent = False
        self.saw_off = False
        self.send_error = None
        self.pressed_at = now
        self.press_count += 1
        self.last_by = by
        self.outcome = None

    def belongs(self, started):
        """Whether a send (started = start time) counts for this attempt."""
        return self.active and started >= self.pressed_at - JOIN_S

    def sent(self, started, now=None):
        now = time.monotonic() if now is None else now
        if self.belongs(started) and self.sent_at is None:
            self.sent_at = now

    def send_failed(self, started, why, now=None):
        """A send in this attempt failed. With no ack at all yet: the attempt counts as failed;
        with an ack already (the first one went out, and a resend or re-press failed): keep waiting for readback, and keep the reason for the timeout log."""
        if not self.belongs(started):
            return
        if self.sent_at is None:
            self.finish("send_failed", why, now=now)
        else:
            self.send_error = why

    def on_bus(self, bus, asked_at, now=None):
        """Polling got a busStatus (asked_at = when this query was issued). Returns True if confirmed."""
        now = time.monotonic() if now is None else now
        if not self.active or self.sent_at is None or asked_at < max(self.sent_at, self.pressed_at):
            return False
        if torque_off(bus):
            self.saw_off = True
        if relaxed(bus) is True:
            self.confirm_ms = round((now - self.pressed_at) * 1000)
            self.finish("confirmed", now=now)
            return True
        return False

    def finish(self, outcome, why="", now=None):
        now = time.monotonic() if now is None else now
        self.outcome, self.outcome_at, self.outcome_why = outcome, now, why
        self.pressed_at = None

    def elapsed(self, now=None):
        if not self.active:
            return None
        return (time.monotonic() if now is None else now) - self.pressed_at

    def status(self, *, present, bus, bus_age_s, now=None):
        """Returns {"state": ..., "why": a sentence for humans}. Read-only."""
        now = time.monotonic() if now is None else now
        mode = bus.get("mode") if isinstance(bus, dict) else None
        phase = bus.get("phase") if isinstance(bus, dict) else None
        no_pad = "只能关电源" if (not present or phase in STARTING_PHASES or mode == "commissioning") \
            else "用手柄 − 或关电源"
        if self.active:
            # Before "main program missing": pressed just as robotd came back while polling was still sleeping in backoff, and the ack has already arrived, so don't show "missing" (re-review #6)
            return {"state": "pending", "why": "卸力中…"}
        if not present:
            return {"state": "unavailable", "why": f"主程序不在，{no_pad}"}
        fresh = bus is not None and bus_age_s is not None and bus_age_s <= CONFIRMED_FRESH_S
        if fresh and phase in STARTING_PHASES:
            return {"state": "unavailable", "why": f"主程序还在启动，{no_pad}"}
        if fresh and relaxed(bus) is True:
            return {"state": "confirmed", "why": "15 颗都已卸力"}
        recent = self.outcome_at is not None and now - self.outcome_at < OUTCOME_SHOW_S
        if recent and self.outcome in ("timeout", "send_failed", "refused"):
            return {"state": "unavailable", "why": f"{self.outcome_why}，{no_pad}"}
        if not fresh:
            return {"state": "ready", "why": "读不到鸭子的状态，按了照样会发"}
        return {"state": "ready", "why": ""}
