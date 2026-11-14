# 2026-10-13 · Following official 0.17: porting "UDP gamepad" and "auto sit-down on gamepad disconnect" onto kissqy's base

**English** · [简体中文](HD1910-20261013-官方更新与UDP手柄.md)

**Status**: code written, integration-tested on the PC, 6 rounds of independent review completed (the last round found nothing that must be fixed). **Not yet on the robot.** The patch only lives on the local branch `hd1910-v164-udp-pad`; how to publish it will be decided after real-hardware verification.
**Base**: kissqy V164 (control.40, official 0.15.1 + his Feetech HD-1910 adaptation), plus our I²C IMU patch; see the [10-12 night on-robot log](HD1910-20261012-night-IMU-calibration-and-first-steps.en.md).

**One-line conclusion**: on 10-12 the official team released robotd 0.16.2 through 0.17.1 in quick succession; the main new feature is the "UDP gamepad": plug a gamepad into a PC and control the duck over the LAN. We're not upgrading wholesale; we only picked out two items, the UDP gamepad and "sit down automatically 1 second after the gamepad disconnects", and ported them into kissqy's padd. The wire protocol is byte-for-byte identical to the official one, so the official `duckctl` can be used directly on the PC side.

---

## 1. What the official update changed, and whether it matters to us

| Official update | Relevance to us | Action |
|---|---|---|
| robotd 0.17: **UDP gamepad** (`netpadd` + PC-side `duckctl udp-pad`) | Can replace the trouble-prone web gamepad ([10-12 night §1](HD1910-20261012-night-IMU-calibration-and-first-steps.en.md)); also usable by people without a Bluetooth gamepad | **Port it** |
| Gamepad disconnect: after 1 second disconnected, make a sound and sit down; dropouts shorter than 1 second are silent (PR #372, #398) | Safety item; benefits the Bluetooth gamepad too | **Port it** |
| Stick axes are configurable | Our gamepad works with the default mapping | Don't port |
| Beta board features from 0.16 on: NFC, head IMU, face lights, SPI-interface ToF, new camera | Our hardware can't use them | Don't port |
| Pause the model when picked up | Useful, but not urgent | Later |
| Training repo: VelStand turning improvements; new VelStand walking model | The new model is trained for XL330 servos and can't be used with the HD-1910; the turning improvements will be used when we train our own model | Noted |

## 2. Why not upgrade wholesale to 0.17

- From 0.15.1 to 0.17.1 the official team changed **153 files, over twenty thousand lines**. kissqy's base is 0.15.1, and his own padd has about 700 more lines changed relative to the official one (wheel test, input settings, gamepad priority, web gamepad). A wholesale upgrade would mean redoing his adaptation.
- **Both sides bumped their interface version numbers independently, so the numbers don't line up**: kissqy went from 37 to 40, official from 37 to 41, and the same number means different things. Dropping in the official 0.17 gamepad code directly would call interfaces kissqy's robotd doesn't have.

## 3. What we did

### 3.1 UDP gamepad

**Approach**: officially, it's a separate service `netpadd` that shares a newly split-out mapping library with padd. kissqy's padd has its own button mapping, so instead of copying that we **added a second input source inside padd**. Buttons in the datagrams are translated into the same button events as a Bluetooth gamepad, and the same goes for sticks and triggers; anything the Bluetooth gamepad can do, the UDP gamepad can too, through the same code. The benefit is no new service, no web console changes and no install package changes.

**How to use it**:
1. Add to `/etc/robot/feetech-ft5/robotd.toml`:
   ```toml
   [netpad]
   enabled = true
   port = 4210       # official default port; duckctl sends here by default
   timeout_ms = 250  # how long without packets counts as disconnected; must be less than [safety] deadman_ms (default 500)
   ```
2. `sudo systemctl restart padd`. Seeing `netpad on — reading the pad from UDP` in the log means it's on.
3. Install [uv](https://docs.astral.sh/uv/) on the PC, plug in a gamepad, and run `uvx duckctl@0.17.1 udp-pad <duck IP>`. Windows, macOS and Linux all work.

**Things to watch out for**:
- **While the UDP gamepad is on, neither the Bluetooth gamepad nor the web console's gamepad is read**; padd reads only one source. Set it back to `enabled = false` and restart padd to restore.
- **There's no authentication on the LAN**: anyone on the same network who can send to this port can start the duck, turn its torque off, or shut it down. Only turn it on in a trusted network and while you're using it.
- If `timeout_ms` is 0 or not less than deadman, or `port` is 0, the newly built robotd rejects the whole config file and won't start, same as official.
- padd's systemd sandbox originally only allowed `AF_UNIX AF_NETLINK`; receiving UDP requires adding `AF_INET`. On boards that are already installed, patch it with a drop-in: write `[Service]` and `RestrictAddressFamilies=AF_INET` to `/etc/systemd/system/padd.service.d/zzzz-udp-pad.conf`.

### 3.2 Auto sit-down on gamepad disconnect

**1 second** after the active gamepad (Bluetooth or UDP) disappears, the duck makes a sound (a questioning call), first asks robotd "am I already sitting?", and if not sends `sit_toggle` to sit down; if rejected, it keeps retrying for 5 seconds. When the gamepad comes back, it greets you. Dropouts under 1 second produce no sound and no sit.

- `sit_toggle` is the action bound to D-pad down by default. **Before trying it on the robot, press D-pad down manually once** to confirm the HD-1910 can actually sit down.
- When the model isn't running (standing at HOME, second Start not pressed), robotd replies "the policy is not driving", padd treats it as nothing to do, and the duck doesn't move.
- If it's already sitting, it won't send `sit_toggle`, since that would make it "stand up".

## 4. Issues found in review (symptom → cause → fix)

After the changes, as agreed, we started a subagent for independent review, 6 rounds in total. Below are the issues each round found, all fixed; every one was reproduced with a script during review:

| Symptom | Cause | Fix |
|---|---|---|
| On the real robot, enabling the UDP gamepad makes padd fail to start, restarting every 5 seconds, and Bluetooth isn't read either | kissqy's install package actually installs `packaging/padd.service`, but I had only changed `padd/systemd/padd.service` | Add `AF_INET` to both, and update `packaging/SHA256SUMS` |
| Holding Select while Wi-Fi stalls briefly, then releasing after it recovers, makes the duck go limp and collapse (8 out of 24 times) | On reconnect the baseline for "keys already held" was taken wrong: it used the state from the first frame instead of the reconnect packet | Use the reconnect packet's buttons as the baseline; now 0/24 |
| When robotd answers slowly (over 250 ms), padd thinks the gamepad disconnected, all modes get reset, and the next Start turns into "stand up" again | When deciding it was disconnected, it didn't first drain packets queued during the stall | Drain first, then decide |
| You released the controls and walked away during a stall, but after the stall the duck kept walking with the pre-stall stick input for about 0.7 seconds | Old queued packets were treated as new data | Packets read after a stall are "untrusted": sticks treated as centered until packets are received in real time again |
| Every normal disconnect left an extra false "main loop stalled" warning in the log | The stall criterion was wrong (it looked at how long the client hadn't sent; it should look at how long padd hadn't read the socket) | Changed to the time since "the socket was last drained"; 0 false warnings |
| Holding Select and leaving during a stall triggers shutdown after the stall ends; holding X keeps re-sending the forward roll | The "held" state in queued packets was taken at face value, and the stall time was counted toward the 2-second long press | During the untrusted period, long press and repeat only keep time and don't trigger |
| Releasing and re-pressing Select during a stall turns two short presses into one shutdown | Old `SelectButton` logic: when "release + press" happen in the same tick, the release is swallowed. kissqy's and the official Bluetooth paths are written the same way | Process the release first (e-stop), then restart timing from the current moment |

We also fixed: several files had been written with Windows line endings ([Pitfall log · Software](../PITFALLS.en.md) already had this entry, and we hit it again); the docs now describe the consequences of a misconfigured `[netpad]`; requests sent during auto sit-down no longer show up as "your request was rejected".

## 5. Test results (on the PC)

- Unit tests: padd 79/79 (new tests for UDP, sit-down on disconnect, stalls, etc.), stable over 8 consecutive runs; robotd-params 106/106.
- End to end: a fake robotd plus a simulated duckctl, covering 14 items (reply packets, per-second health report, Start to stand, stick to walk, triggers, a second PC can't take over, Select for torque off, stop sending after disconnect, sound and sit-down after 1 second, greeting on return, held keys don't misfire on reconnect, silent short dropouts, garbage packets have no effect): 14/14.
- Compatibility with official: using the official 0.17.1 decoder (the same code duckctl uses) to receive our reply packets and health reports, **not a single packet failed to decode**.
- The Windows build of the official `duckctl` 0.17.1 runs on the PC (`uvx duckctl@0.17.1 udp-pad --help`); it only sends packets with a gamepad plugged in, so the "PC → duck" leg has to be tested on the robot.
- padd for the board: aarch64, highest glibc requirement 2.30 (the board has 2.41); the only new dynamic library is `libudev.so.1`, which the board already has.

## 6. Known limitations

- **On a tick where robotd answers especially slowly**: the stick input read before the stall gets sent once more, so robotd's deadman may let it through for up to 0.5 seconds longer. The Bluetooth gamepad has always behaved this way, as have kissqy's and the official versions; not changed this time.
- The UDP gamepad has no stick clicks (L3/R3), so kissqy's L3 wheel stand-up test only works with a Bluetooth gamepad.

## 7. On-robot steps (once the new card boots)

1. Install the new padd with the deployment script: back up the original first, then update the release manifest and add the `AF_INET` permission. If anything goes wrong, one command rolls back.
2. **Use the Bluetooth gamepad first** to confirm standing and walking are the same as before.
3. Press D-pad down manually and see whether it can sit down.
4. Turn off the gamepad and see whether after 1 second it makes a sound and sits down.
5. Turn on the UDP gamepad and run `uvx duckctl@0.17.1 udp-pad <duck IP>` on the PC. If the PC is running something like Clash in TUN mode, it may intercept packets bound for the LAN; if it can't connect, turn off TUN first or set the LAN to direct.

## 8. Next steps

- Run through section 7 on the robot and add the results here.
- After real-hardware verification passes, decide how to publish the patch and deployment script (our own fork, or file an Issue with kissqy with a link).
