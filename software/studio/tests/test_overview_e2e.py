"""End-to-end test for the overview reorg (overview-merge-plan.md §5, review overview-merge-review.md): fake robotd + real Studio + headless Edge.

tests/overview_e2e.mjs checks the board temperature cell, the onboarding checklist and the gamepad block on the overview, then does a few risky operations (switching pages / scrolling away while holding the joystick,
scrolling the wheel over the stage, on a phone swiping down starting from empty space on the gamepad diagram / an action button / the A on the diagram), and prints what the fake robotd received at each step;
this file checks the results (review O1, O2, O5, O8, O13, O14, O17, O18). It runs in two phases: main (Studio with no records); done (Studio restarted with
an onboarding.json saying "all 6 steps done", and the checklist collapses into one line).

Requires Node (≥ 22) and Edge on the computer; skipped if missing (e.g. on the duck). Also skipped with STUDIO_E2E=0.
Default ports: Studio 18090, fake robotd 17021 / configd 17022, Edge debug port 9343; if taken, free ones are used instead (without touching what others are running).
OVERVIEW_E2E_DIR=dir: logs, Edge profile and the fake robotd's records go here (default is a temp directory, deleted after the run); OVERVIEW_SHOTS=dir: take screenshots along the way.
To run on its own:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_overview_e2e'])"
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http, moves, nonzero  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
XBOX = "78:86:2E:BB:13:28"


def all_done_records():
    """A record of "5 steps done": fingerprints are computed from the calibration the fake robotd replays (same functions as onboard.py in Studio)."""
    from fake_robotd import FakeRobotd
    from studio import onboard as O
    from studio.imu import mount_of
    f = FakeRobotd(str(FIXTURE), posture="policy")
    src, mount = mount_of(f.bus, f.calib)
    now = time.time()
    fp = O.full_fp(f.bus, f.calib)
    return {"v": 1, "confirm_servo": {"at": now - 3600, "fp": O.joints_fp(f.calib), "by": "e2e"},
            # The IMU step was skipped (user Oct 18: "it was calibrated before, skipping should be fine"): when collapsed it shows "（跳过 1 步）" ((1 step skipped))
            "skipped": {"imu": {"at": now - 3000, "by": "e2e", "fp": O.mount_fp(src, mount["quat"])}},
            "estop": {"at": now - 2400, "ms": 186, "mac": XBOX, "name": "Xbox Wireless Controller", "build": f.bus["build"]},
            "stood": {"at": now - 1800, "fp": fp}, "walked": {"at": now - 1700, "fp": fp}}


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "没有 Node ≥ 22 或者 Edge（或者设了 STUDIO_E2E=0）：跳过总览的端到端测试")
class OverviewE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("OVERVIEW_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="overview-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        rec = cls.dir / "robotd-recv.jsonl"
        rec.unlink(missing_ok=True)
        p_rd, p_cfg, p_web, p_cdp = _port(17021), _port(17022), _port(18090), _port(9343)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}

        def studio(tag):
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② 二号鸭", "--dev-autologin", "--servo-sim",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out(f"studio-{tag}.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")

        def node(phase):
            args = [NODE, str(HERE / "overview_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp),
                    "--record", str(rec), "--fake", str(p_cfg), "--phase", phase]
            if os.environ.get("OVERVIEW_SHOTS"):
                args += ["--shots", os.environ["OVERVIEW_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=400, cwd=ROOT)
            (cls.dir / f"overview_e2e-{phase}.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Node 脚本（{phase}）出错（日志在 {cls.dir}）：{(r.stderr or '')[-3000:]}")
            (cls.dir / f"overview_e2e-{phase}.json").write_text(r.stdout, encoding="utf-8")
            return json.loads(r.stdout)

        try:
            # "Ready to walk": joystick, actions and skills can all be pressed (for the "should not send" steps, first prove that it normally does send)
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "policy", "--record", str(rec)],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            studio("main")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}", f"--user-data-dir={cls.dir / 'edge'}",
                 "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "无头 Edge 的调试口")
            cls.out = node("main")
            # Second phase: Studio restarts with a record of "5 steps done"; a physical gamepad is connected (the e-stop test record has this gamepad)
            _kill(procs.pop("studio"))
            (state / "onboarding.json").write_text(json.dumps(all_done_records(), ensure_ascii=False), encoding="utf-8")
            import socket
            for _ in range(20):           # at the end of the previous phase the fake robotd was "restarted" (refusing connections for 0.3 seconds): retry if no reply
                try:
                    with socket.create_connection(("127.0.0.1", p_cfg), 3) as s:
                        s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"fake.set","params":{"pad_connected":true}}\n')
                        if b"connected" in s.recv(4096):
                            break
                except OSError:
                    pass
                time.sleep(0.2)
            else:
                raise AssertionError("假 configd 没接受「手柄连着」")
            studio("done")
            cls.done = node("done")
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def recs(self, step):
        return self.out["steps"][step]["recs"]

    def test_page_has_no_errors(self):
        self.assertEqual(self.out["errors"], [])
        self.assertEqual(self.done["errors"], [])

    def test_overview_layout(self):
        d = self.out["desk"]
        self.assertEqual(d["cells"], 7)                                  # camera and ToF added, board last
        self.assertIn("°C", d["cpu"])
        self.assertEqual(d["rows"], 6)                                   # 6 checklist rows (task 11 added "写进主程序" (commit to main program))
        self.assertFalse(d["padActive"])                                 # top of the home page: the gamepad block isn't on screen
        self.assertEqual(d["nav"], "总览")
        self.assertEqual(d["now"], "1 舵机零位")                         # what to do now: the first unfinished one
        self.assertEqual(d["marks"][:3], ["●", "●", "✓"])
        tops = self.out["d1100"]["tops"]                                 # 1100 wide: 4 + 3
        self.assertEqual(len(set(tops[:4])), 1)
        self.assertGreater(tops[4], tops[0])
        self.assertEqual(len(set(tops[4:])), 1)
        for k in ("d1100", "phone", "phone_pad"):
            self.assertLessEqual(self.out[k]["sw"], self.out[k]["cw"], f"{k}：能左右滑")

    def test_wheel_on_stage_scrolls_page(self):
        self.assertGreater(self.out["wheel"], 100, "在舞台上滚滚轮，页面没动（被 3D 缩放吃掉了）")

    def test_pad_anchor(self):
        n = self.out["padNav"]
        self.assertTrue(n["active"])
        self.assertEqual(n["nav"], "手柄")
        self.assertEqual(n["topbar"], 0)                                 # the top bar is sticky (relax always on screen: O3)
        # The gauge strip sticks below the top bar and the sidebar sticks (user Oct 19: always visible while scrolling down); scrolled to the gamepad block, it stops below the gauge strip and isn't covered by it
        self.assertEqual(n["band"][0], 56, n)
        self.assertEqual(n["navTop"], 0, n)
        self.assertTrue(n["band"][1] <= n["top"] <= n["band"][1] + 30, n)

    def assert_released(self, st):
        self.assertTrue(any(nonzero(p) for p in moves(st["before"])), "按着摇杆时应该在走（不然这一步没测到东西）")
        self.assertIn({"vx": 0, "vy": 0, "vyaw": 0}, moves(st["atLeave" if "atLeave" in st else "atScroll"]))
        self.assertFalse(any(nonzero(p) for p in moves(st["after"])), "离开手柄区以后手还按着也不该再走")
        self.assertFalse(st["active"])
        self.assertTrue(st["offLogged"], "Studio 日志里没看到「离开了手柄区」（drive off）")

    def test_route_change_while_holding_stick_stops_and_drives_off(self):
        self.assert_released(self.out["steps"]["route_leave"])

    def test_scrolling_out_while_holding_stick_stops_and_drives_off(self):
        self.assert_released(self.out["steps"]["scroll_out"])

    def test_checklist_buttons_go_to_the_right_place(self):
        g = self.out["goto"]
        self.assertTrue(g["estop"]["inView"])
        self.assertIn(g["estop"]["focus"], ("pd-estop-btn", "pd-estop"))
        self.assertTrue(g["wizard"]["open"] and g["wizard"]["inView"])
        self.assertEqual(g["imu"], "#/imu")

    def test_swipes_on_phone_send_nothing(self):
        """O2: swiping up starting from empty space on the gamepad diagram, an action button, or the A on the diagram scrolls the page, and robotd receives nothing; holding still / tapping sends (control case)."""
        for step in ("swipe_pad_blank", "swipe_action", "press_right_after_scroll", "swipe_svg_a"):
            with self.subTest(step=step):
                self.assertEqual([r for r in self.recs(step) if r["method"] in ("robot.move", "robot.head", "robot.do", "robot.mouth",
                                                                                  "robot.sound", "robot.pose")], [])
        self.assertTrue(any(r["method"] == "robot.head" for r in self.recs("hold_action")), "按住「点头」不动，头没动")
        self.assertIn({"method": "robot.do", "params": {"skill": "ground_pick"}, "notify": False}, self.recs("tap_svg_a"))

    def test_board_temperature(self):
        c = self.out["cpu"]
        self.assertTrue(c["throttled"]["bad"])
        self.assertIn("降频了：1008 / 1800 MHz", c["throttled"]["text"])
        self.assertIn("主板过热降频了", c["throttled"]["todo"])
        self.assertIn("有点热", c["hot"])
        self.assertIn("—", c["stale"])                                   # health stale: shows "—", not "正常" (normal) (O5)
        self.assertNotIn("正常", c["stale"])

    def test_unknown_shows_question_marks(self):
        self.assertEqual(self.out["unknown"][:4], ["?", "?", "?", "?"])   # servos, IMU, commit to main program, pair gamepad
        self.assertIn("读不到 configd", self.out["unknownText"])

    def test_c3_keyboard_repeat_after_leaving_does_not_drive(self):
        """Code review C3: holding W and scrolling out of the gamepad area stops it; after scrolling back (W still held, focus still there) the browser's auto-repeat must not make it continue."""
        k = self.out["steps"]["kbd_repeat"]
        self.assertTrue(any(nonzero(p) for p in moves(k["held"])), "按住 W 时应该在走（不然这一步没测到东西）")
        self.assertIn({"vx": 0, "vy": 0, "vyaw": 0}, moves(k["out"]))
        self.assertTrue(k["activeBack"] and k["focus"])
        self.assertFalse(any(nonzero(p) for p in moves(k["back"])), "滚回来以后自动重复的按下让鸭子又走了")

    def test_c6_stage_canvas_keeps_pan_y_on_phone(self):
        self.assertEqual(self.out["phoneCanvas"]["computed"], "pan-y", self.out["phoneCanvas"])

    def test_c7_no_hold_after_fast_press_release_press(self):
        """Code review C7: receipts delayed 300 ms, quickly press, release, press again: not a single action_hold in the 2 seconds after the final release."""
        h = self.out["steps"]["hold_race"]
        self.assertGreater(h["holdsDuring"], 0, h)                     # while held it keeps renewing (control case)
        self.assertEqual(h["holdsAfter"], 0, h)

    def test_servo_session_kept_with_bar_on_other_pages(self):
        """User Oct 18: "when leaving the servo page, torque should stay enabled": with servos holding, leaving doesn't hand back or pop up a confirm dialog; other pages have a banner at the top,
        still there after a reload; "交还主程序" (hand back to main program) has two-step confirmation; after hand-back the banner changes to "已交还……sudo systemctl start robotd" (handed back… sudo systemctl start robotd), and disappears once the main program connects."""
        b = self.out["servoBar"]
        self.assertIn("调舵机中 · 2 颗保持着 · 主程序停着（手柄、遥控、站走都不能用）", b["text"])
        self.assertIn("回舵机页", b["text"])
        self.assertEqual(b["dialogs"], 0)
        self.assertTrue(b["afterReload"])
        self.assertIn("交还：马上把 15 颗全部松开，鸭子会软下来——先扶住或放平", b["armed"])      # review D7
        self.assertIn("急停用顶上红按钮或空格（手柄 Select 这时不管用）", b["text"])                # review D6
        self.assertIn("别手动起 robotd，先点「交还主程序」", b["text"])                               # review D9
        self.assertTrue(b["sticky"]["visible"], b["sticky"])                                         # still there when scrolled to the gamepad area (sticky)
        self.assertTrue(b["visualFits"], "有舵机提示条时，姿态和视频仍能一起显示或正常滚动")
        p = b["phone"]
        self.assertTrue(p["visible"], p)                                                             # also visible on a phone scrolled to the remote card
        self.assertEqual(p["badge"], "调舵机中")
        self.assertTrue(p["remote"])
        self.assertLessEqual(p["sw"], p["cw"])
        self.assertTrue(b["dbl"]["stillOpen"])                                                       # a double-click doesn't hand back (review D4)
        self.assertTrue(b["dbl"]["armed"])
        self.assertTrue(b["dbl"]["disarmed"])                                                        # restores after 3 seconds
        self.assertTrue(b["earlyIgnored"])                                                           # clicking confirm within 700 ms doesn't count
        self.assertTrue(b["stillThere"])                                                             # main program not connected, "已交还" (handed back) stays
        self.assertTrue(b["stillOpen"])                                # a single click doesn't hand back
        self.assertIn("sudo systemctl start robotd", b["after"])
        self.assertTrue(b["gone"])

    def test_pad_3d_left_of_sticks_and_pauses_out_of_view(self):
        """User Oct 24: on wide screens the left 3D view and camera stick together as a whole, cards don't overlap each other; stop drawing when scrolled out;
        the 3D card doesn't count as "in the gamepad area" (active is false after scrolling back to the top). Phone: 3D above the remote, shorter, not sticky, no horizontal swiping."""
        d = self.out["pad3d"]
        self.assertGreaterEqual(d["visFrac"], 0.6, d)
        self.assertTrue(d["left"], d)
        self.assertEqual(d["sticky"], "static")
        self.assertEqual(d["stackSticky"], "sticky")
        self.assertTrue(d["cameraBelow"])
        self.assertEqual(d["touch"], "pan-y")
        self.assertTrue(d["drawsInView"])
        self.assertFalse(d["drawsOutOfView"])
        self.assertFalse(d["activeAtTop"])
        p = self.out["phone3d"]
        self.assertTrue(p["above"], p)
        self.assertLessEqual(p["h"], 240)
        self.assertEqual(p["sticky"], "static")

    def test_all_done_collapses_to_one_line(self):
        self.assertIn("上手 6 步都完成了（跳过 1 步）", self.done["done"])

    def test_all_done_line_expands_and_remembers(self):
        e = self.done["expanded"]
        self.assertEqual(e["rows"], 6)
        self.assertEqual(e["redo"], 5)                                # all 5 ✓ rows have "重新做" (Redo)
        self.assertEqual(e["skip"], 1)
        self.assertIn("收起", e["head"])
        self.assertEqual(self.done["expandedAfterReload"], 6)        # expanded state is stored in localStorage
        self.assertTrue(self.done["collapsedAfterReload"])

    def test_every_row_has_three_buttons(self):
        """User Oct 20: every row always has "去做" (Go do it), "已完成" (Done), "跳过" (Skip) (✓ rows only have "重新做" (Redo))."""
        rows = self.out["threeButtons"]
        self.assertGreaterEqual(len(rows), 3, rows)
        for r in rows:
            with self.subTest(step=r["step"]):
                self.assertEqual(len(r["labels"]), 3, r)
                self.assertEqual(r["labels"][1:], ["已完成", "跳过"], r)

    def test_skip_unskip_and_redo(self):
        """Servo "已完成" (Done) → ✓ "你标了已完成（时间）" (you marked it done (time)), with "重新做" (Redo) and "取消" (Cancel); skip IMU → "跳过了" (skipped) (gray ↷), now the 4th row should be next;
        cancelling the skip restores it; a ✓ row's "重新做" (Redo) goes to the servo page; "取消" (Cancel) restores it."""
        m = self.out["marked"]
        self.assertTrue(m["text"].startswith("你标了已完成（"), m)
        self.assertEqual(m["buttons"], ["重新做", "取消"])
        sk = self.out["skip"]
        self.assertEqual(sk["imu"], "onb-skip")
        self.assertEqual(sk["mark"], "↷")
        self.assertIn("跳过了（先不做）", sk["imuText"])
        self.assertEqual(sk["now"], "pad")
        self.assertEqual(self.out["unskip"], {"imu": "onb-todo", "now": "imu"})
        self.assertEqual(self.out["redoHash"], "#/servos")
        self.assertEqual(self.out["undone"], "onb-todo")

    def test_estop_skip_needs_two_clicks_within_3s(self):
        self.assertIn("确定跳过", self.out["estopOnce"]["text"])
        self.assertEqual(self.out["estopOnce"]["skipStill"], ["跳过"])  # the original button doesn't change in place (review D4); the confirm button is a separate one
        self.assertEqual(self.out["estopOnce"]["state"], "onb-no")    # a single click has no effect
        self.assertEqual(self.out["estopDbl"], {"state": "onb-no", "armed": True},   # real mouse double-click: doesn't skip, just shows the confirm
                         {k: self.out.get(k) for k in ("estopDblGap", "estopArmed300", "estopClicks", "estopTargets", "estopArms", "dblAtRects")})
        self.assertEqual(self.out["estopTimeout"], {"text": "跳过", "state": "onb-no"})   # not clicked again within 3 seconds: restored
        self.assertEqual(self.out["estopTwice"], "onb-skip")

    def test_imu_unverified_skip_needs_two_clicks(self):
        """The main program explicitly says IMU orientation is unconfirmed: previously skip was grayed out; now it's clickable, the first click shows a confirm button stating the consequence, and nothing is skipped unless it's clicked."""
        b = self.out["imuBlocked"]
        self.assertFalse(b["disabled"])
        self.assertEqual(b["ask"], "确定跳过？主程序没确认 IMU 方向：跳过了鸭子也站不起来")
        self.assertEqual(b["state"], "onb-no")
        self.assertEqual(b["after"], "onb-no")


if __name__ == "__main__":
    unittest.main()
