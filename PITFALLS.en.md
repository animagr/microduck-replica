# Pitfalls

**English** · [简体中文](踩坑记录.md)

Pitfalls we actually hit while building the replica, **three sentences each: symptom, cause, what to do**. Organized by stage; skim it before you start.

Analysis and evidence live in other documents; only the conclusions are recorded here. When you hit a new pitfall, add it to the relevant stage and write it plainly.

> The mechanical process is in the [build log](构建日志.md), the electrical and software process in the [debug log](调试记录.md). Recent additions: Oct 20–21, 2026, acceptance testing of the replica image on real hardware: the fork's calibration mode always shows "starting up", `.local` won't open while Clash is on, the image's SSH host keys were not generated, skipping every step won't enter motion mode, the robot can't stand up in calibration mode (added hold-home), the hotspot comes up slowly, and two items were added under Tools on GitHub releases and the front-page cards; evening of Oct 15, 2026, the root cause of "falls after two or three steps" was the BNO085's own orientation jumping erratically, fixed with gyro integration; when debugging, first check whether the data is self-consistent; the yardstick for detecting jumps must be aligned with the latency; weak turning (not solved yet); one item each added on full-robot reboots and G50 pairing; evening of Oct 14, 2026, kissqy's V167 now writes D=0 and torque 1000 when torque is enabled (if you use an IMU module, don't upgrade directly); Oct 14, 2026 daytime, servo parameters are written to RAM (they linger if robotd restarts while torque is on), the two feet aren't coplanar laterally because both hip rolls splay outward (presumably pushed by body weight), the mouth servo runs hot, the new "repair gamepad connection" only supports GameSir, don't click "install / upgrade firmware", TPU 95A soles are on the hard side, align scale, filtering and weight before comparing with simulation; night of Oct 13 – Oct 14, 2026, servo D makes walking jittery, V164 doesn't write D or torque limits, full-robot brownouts while walking are a power issue, the G50 Pro disconnects right after pairing on the new card, switching cards requires re-pairing the gamepad, the static IP got taken, Armbian logs are lost on power loss, the joint model's scale and filtering are not in robotd.toml, work out foot scuffing before tuning; Oct 13, 2026, kissqy's install package uses `packaging/padd.service`, cross-compiling padd needs arm64 libudev, the official and kissqy interface version numbers increment independently, the part number of Feetech's AMP2.0 board-side connector; night of Oct 12, 2026, the IMU being mounted 8.5° off is the real reason the model lurches as soon as it takes over (with a zero-calibration method), four layers of causes behind the web gamepad, the SSH welcome script, ToF reconnects, Bluetooth gamepad pairing, IMU wiring with a bad contact, knees collapsing, the power bank falling back to 5 V, TPU soles; afternoon of Oct 12, 2026, taking apart kissqy's one-click image R1 (won't boot on V1.12, only supports the bus IMU board, preinstalled prototype calibration), editing armbianEnv has no effect under the Radxa bootloader, addresses when connecting an IMU module to HAT J5, Python on Windows turning files into CRLF; Oct 12, 2026, switching to kissqy's full stack (pinning official install.sh to 0.15.1, the audio setup hangs when the sound card isn't enabled, R17 copies the prototype's calibration, mediad/tofd overheating the board, vent holes and airflow ducts, installing R17 releases torque, check IMU orientation after standing up, HOME rejected after another program enabled torque, `service.sh init` can't send HOME, overheating breaking the web joystick); Oct 11, 2026, kissqy's walking model on the robot (gait can't be tested while held by hand, undervoltage protection and full-body torque release, power headroom, soft start, board thermal throttling, Clash TUN blocking the board, freezing after boot); Sep 28, 2026, HAT power, USB ports, the camera ribbon cable and comparison with the official image.

---

## Buying parts

**Don't buy an NP-F970 battery; it's the NP-F550**
The upstream mesh file is named `np_f970.stl`, but it measures 39 × 21 × 71 mm, which is the F550's size. A real F970 is about 60 mm thick, **won't fit**, and its 300 g would eat a third of the robot's weight budget.
→ Buy an NP-F550 (2S, 6.6–8.4 V). See the [BOM](BOM.md).

**The Feetech HD-1910's cable is 2.0 mm, the Feetech debug board's port isn't; assigning IDs needs a jumper-wired cable**
The HD-1910's stock cable is AMP2.0-3P (2.0 mm pitch). The TTL port on the FE-URT-2 debug board is bigger, so it **won't plug in**, and the board has no 2.0 port.
→ If you need to assign IDs the same day, **cut a servo cable** (sacrifice one of the 15) and connect the three bare wires like this:

```
Servo cable             FE-URT-2
Pin 1  Signal    →   S    solder to the S-pin pad of the white port on the back of the board (temporarily you can also tin the wire and insert it directly into the S hole)
Pin 2  Vcc       →   V1   blue screw terminal
Pin 3  GND       →   G    blue screw terminal
```

**The middle wire is always V** (Feetech and Dynamixel agree on this); swapping S and G won't burn anything, it just won't communicate, swap them back.
**Only getting V wrong will burn something.** For ID assignment with no load, USB 5 V is enough (the HD-1910 works from 4 V); first check with a multimeter whether there's 5 V across G–V1 on the blue terminal; if not, flip that switch.
→ The proper way is to buy a few "PH2.0 3P terminal cables" plus a few terminal cables of the board's connector type and splice them into adapter cables. Check the servo packaging before buying; sometimes one is included.
→ This is worth telling Feetech directly: whether the retail version should include an adapter cable.

**Feetech's pin order is the exact opposite of Dynamixel's**
Feetech HD-1910: `1=Signal 2=Vcc 3=GND`. Dynamixel XL330: `1=GND 2=Vcc 3=Signal`.
→ Fortunately the two have different pitches (2.0 vs 2.5 mm), so they can't plug into each other. The only remaining risk is "crimping your own cable backwards"; after crimping, check it with a multimeter first.

**Don't use the HL-2915 as a reference**
The Feetech HL-2915-C002 is a 9–14 V servo; a 2S battery (max 8.4 V) **can't drive it**, and its pin order is again the opposite of the HD-1910's.
→ This design only supports the HD-1910-C001.

**A fully charged battery at 8.4 V is exactly the HD-1910's voltage limit**
The HD-1910's operating range is 4–8.4 V. A fully charged NP-F550 is 8.4 V, **zero margin**. Only when the voltage sags under load to 6.6–8.2 V is it back in the safe zone.
→ Don't do stall tests right after a full charge. For long-term storage, store at 3.8 V/cell. Enable the servos' overvoltage protection before assembly.

**The low-end Radxa Zero 3W is a bare board**
The 2 GB version without eMMC **has no pin header soldered and no storage**; it can only boot from microSD.
→ Buy your own 2×20 pin header (2.54 mm, vertical; colored ones make counting pins easier) and a **high-endurance** microSD (SanDisk High Endurance / Hikvision PLUS, 32 or 64 GB; buy two, one as a backup).

**Don't feed external power into the URT-2's V1 terminal**
The DIP switch on the board selects the TTL level (3.3 / 5 V); it is **not** a power selector. With USB plugged in, V1 has 5 V; how it connects to USB is unclear and it may be a direct connection. Feeding 7.4 V into V1 risks backfeeding into the PC or the Radxa.
→ Connect external power directly to the servos' V and G, connect the URT-2's G to the negative as well for a common ground, and leave V1 unconnected. The URT-2 only handles the signal.

**Feetech servos all ship with ID 1**
Connect all 15 at once and they all respond; you can't tell which is which.
→ **When setting IDs, connect only one at a time.** After changing it, stick on a label (joint name + ID), unplug it, take the next one. Steps and the ID table are in [Debug log · Servo configuration](调试记录.md#舵机配置--拿到货一步一步做).

---

**ToF module: the L8CX board won't fit in the face shell, and the firmware doesn't support the L7CX**
Symptom: we first bought a VL53L8CX; the board commonly sold in China is **33.4 × 10.2 mm** and won't fit in the face shell (`face_part`);
to get something shorter we switched to an L7CX (26 mm), but the firmware errors out and quits on startup. Both purchases were wasted.
Cause: the L7CX is **a different chip** with a 90° wide field of view, and its revision ID doesn't match. The official `tof` firmware only accepts `0x02` (L5CX)
and `0x0C` (L8CX); anything else gets `neither a VL53L5CX nor a VL53L8CX` and the firmware exits.
Only those two ULD drivers are compiled into the firmware; it's not something you can get around by changing an ID.
→ Buy a **VL53L5CX (VL53L5X V2 module)**: the firmware supports it, **its 20 mm hole spacing matches the printed part exactly** (a colleague measured the printed part's holes at 20 mm;
the L8CX board is 28 mm and simply can't be mounted), and the board is also the smallest (**15.8 × 10 mm** board body / 24.7 mm including mounting ears),
and it's 25 yuan cheaper. **The selection order is: first check whether the firmware supports the chip (only L5CX / L8CX), then whether the board fits**;
picking by size first is how this happened. The L8CX chip itself is fine; it's that board that's too long.
If you can find a short L8CX board, it will work too; measure the hole spacing and lens position from the actual part.
A size comparison of the three board types is in the [electronics purchase list](docs/电控采购清单.md#四tof-测距--vl53l5cx-或-vl53l8cx8×8-多区).

## PCB design / fabrication

**"Replace" on the JLCPCB order page doesn't write back to the project**
Clicking 「替换」 (Replace) on the order page to swap a part number only applies to that order. The component in the EasyEDA project still has the old part number, so **the next BOM export reverts it**, and you get "private stock 0" again.
→ Replace the component in the EasyEDA project (delete it and re-place it at the same coordinates), not just on the order page.

**Active oscillators and passive crystals in 3225 4-pin packages look exactly the same**
On a passive crystal, pins 2 and 4 are the same metal lid and are shorted internally. X1 on this board is drawn as an active oscillator (2=GND, 4=VDD), so fitting a passive one **shorts 3.3 V to ground the moment it powers up**. Searching JLCPCB for "3225" mostly returns passive parts, and `C13738` (basic library, no part-change fee) is the easiest one to click by mistake.
→ Only accept parts labeled 「有源晶振 / OSC」 (active oscillator / OSC). This board uses `C5917307`.

**Xingtong Shipin C387369 isn't in JLCPCB's SMT assembly stock**
At ordering it was classed under 「使用私有库存的元器件」 (components using private stock), with private stock 0.
→ Switch to `C5917307` (Yajingxin, 5 mA, same package).

**After adding components, the Gerber / BOM / pick-and-place files all have to be re-exported**
After changing the schematic (e.g. adding J4/J5), all three files change. If you fabricate with the old Gerber, the board won't have holes for those two connectors.
→ Export the full set after every change, with a timestamp in the file names, and go by the latest one.

**The PH2.0 connectors chosen for J4/J5 have the right pitch, but the housing doesn't match the Feetech cable plug, so it won't plug in**
The Feetech HD-1910's cable has an AMP2.0-3P plug; the 2.0 mm pitch is right, but the plug's shape doesn't match the housing of a JST PH connector (`B3B-PH-K-S`). Someone warned during review that "the board-side connector hasn't been verified with a real part", and sure enough.
→ First board: shave off the connector housing, leaving just the pins; it plugs in and works. v2: match the connector against a real Feetech cable (ask Feetech for the board-side connector part number, or buy a few kinds of 2.0 mm 3P connectors and test-fit them); **test-fit with real parts before sending the board out**.
→ Addendum (2026-10-13): Feetech's datasheet only gives the cable-side `AMP2.0-3P`; the board-side part number is not public, and we found no verified right-angle part number online; another replica project simply lists it as "PH2.0", likewise untested. But Feetech's dimension drawing shows **two of the same connector right on the bottom of the servo body**, which means Feetech itself uses the matching board-side connector; the fastest route is to ask Feetech directly for the part number, whether it can be bought separately, and whether a right-angle version exists.

**Chinese characters in GitHub Release asset names get stripped**
Uploading `SolidWorks图纸.zip` stored it as `SolidWorks.zip`. The download link in the README no longer matched.
→ Use English names for Release assets.

---

## Jumper wiring (no-HAT build)

> The full wiring is in [No-HAT build](docs/不打HAT.md); only the parts that bite are listed here.

**The adapter board's logic supply must be taken from 3.3 V**
The half-duplex adapter board has a VCC on the MCU side. If you take it from 5 V, its TX drives 5 V levels into the controller's 3.3 V RX pin.
→ Take it from 40-pin header pin 1 (3.3 V). The ToF takes power from pin 17, so the two don't compete.

**Feeding 5 V into the 40-pin header is unprotected**
Feeding 5 V via pins 2/4 bypasses the board's own USB input protection. **Reverse it and the board burns on the spot.**
→ Measure the polarity and voltage of the buck module's output before plugging in.

**Don't use Dupont wires for the servo power trunk**
15 servos peak at several amps; 24–28 AWG Dupont wires only handle about 1 A and will get hot or even melt their insulation.
→ Use 18–20 AWG silicone wire for the trunk.

**Put a fuse and a switch in series between the battery and the servos**
A shorted lithium battery can spit fire. The official HAT's path has a thermistor and a "3A max" marking; the jumper-wire build connected bare has none of that.
→ Put a 5 A fuse + power switch in series.

**There's no shutdown signal**
On the HAT, the LM5050-1 gives the controller a shutdown signal; the jumper-wire build has none. Every power-off is a hard pull, **which is hardest on the microSD**.
→ First run `make shutdown` or use the gamepad shutdown gesture, wait for the system to shut down cleanly, then cut power.


---
