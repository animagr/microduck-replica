# HAT servo intermittent timeouts: head-side connection comparison and circuit review

**English** · [简体中文](HAT舵机偶发超时排查-20260928.md)

Dates follow the debug PC. The board's log clock is not used as an authoritative on-site time reference.

## Confirmed on-site wiring

The user confirmed: the **same pair of positive/negative output terminals** of the adjustable power supply is split into two branches; one feeds the HAT directly, the other powers the servos through the Feetech debug board; the debug board's USB is not connected to a PC. From the HAT to servo 33 (head tilt left/right / head_roll), only DATA is currently connected. The mouth, ID 29, is excluded from testing at the user's request.

The negative leads of the two supply branches already provide a common reference ground, so this cannot be called "completely no common ground". However, the signal return current detours through the supply negative leads and the debug board; local ground offset, loop area, and common impedance still need to be compared. The debug board's USB being unplugged does not necessarily mean its DATA circuitry is disconnected or high-impedance; the debug board's model, internal power supply, and whether DATA passes through still need to be verified.

## Software misdiagnosis and measurements

After reboot, the web service was initially inactive. After confirming the serial port was not in use, a standalone test sent only PING / READ / SYNC_READ. No parameter writes, torque enable, or motion commands were sent. The web service was then restored; still no motion commands were sent.

| Head-side connection test | Result |
|---|---|
| Read servo by servo, 20 times each | Servo 33: 19/20; the other 13 servos: 20/20 each |
| Old program, sync read 200 rounds, 10Hz | Application reported 43 servo read failures; at the low level, 6 parsing timeouts, and 37 complete reply packets with correct checksums were rejected because they did not match the ID expected in sequence |
| Raw replies saved by actual ID, normal order, 200 rounds | Servo 31 missing once, all others 200/200 |
| Raw replies saved by actual ID, reverse order, 200 rounds | Servo 33 missing 3 times, all others 200/200 |
| Web console 0.15.3 after the fix, 200 frames, about 20 seconds | All 14 servos 200/200, no timeouts, checksum errors, or ID errors within the window |

"Missing response" only means that no valid reply for that ID was obtained within the test window; it does not prove that the physical cable dropped frames. Changing the read order does not change the physical wiring.

In the earlier servo-by-servo test with the foot-side connection, servo 23 was 18/20 and all others were 20/20. However, the timing, pose, timeout settings, etc. of the two tests were not fully identical, so these small samples cannot establish "whichever side you connect, that side will fail" or quantitatively claim that the head-side connection is more reliable.

An independent agent reproduced it with the protocol byte stream: omitting just one packet from servo 23 caused the old sync read implementation to report 23 and the 10 servos after it as all failing. The cause was that it called `_read_status(expected_id)` in sequence, and when it actually received a later valid packet it discarded it as an ID mismatch. 0.15.3 now files each reply by the reply packet's own ID and keeps None only for those actually missing; it does not rely on retries to mask missed reads, and single-servo reads still strictly check the ID. On a receive timeout it ends that group, avoiding repeated waits for each servo.

Verification: the new protocol regression test failed first and passed after the fix; the 38 related tests and the simulation self-check passed; byte-stream replays of 4 actual anomalous transactions each reported only the IDs that were really missing. Independent review passed. The existing simulation tests have a ResourceWarning about an unclosed temporary read file, which does not affect this round's results. The implementation still limits reading to at most as many frames as requests, and does not implement full recovery from arbitrary noise, duplicate packets, or unrequested IDs.

On the board, `/home/duck/servo-web` was updated to 0.15.3 and `microduck-servo-web` restored; the startup scan identified 14 servos. The three old runtime files are saved in this session's backup directory under `/home/duck/servo-web-backups/` on the board. The service is still started manually; the test records do not mean anything has been released to the repo or the image.

## Cross-check of schematic, PCB, and datasheet

Based on pages 4/6 of the official HAT schematic, the actual PCB pad nets, the production BOM, and the HD-1910-C001 datasheet 2026-09-07 A/0:

- The two 3-pin connectors J13/J14 are fully in parallel and share one TTL transceiver circuit: pin1 GND, pin2 +BATT, pin3 DATA. There are no separate drivers for the left and right limbs.
- U7 is an SN74LVC1G126 and U6 is an SN74LVC1G125, both powered from 3.3V; Q1 is an MMBT3906, and R27 10k and R28 20k take part in automatic direction control.
- In steady state, TX low turns Q1 on, DIR goes high, U7 is enabled and drives low; with TX high, DIR is pulled low, U7's output goes high-impedance, and the bus returns high via R32 10k and any pull-ups that external devices may have. Switching transients and Q1 delay have not been measured; the schematic alone cannot establish that the stop bit is truncated.
- The DATA path is transceiver node → R33 150Ω → D4 clamp node → TH1 → J13.3/J14.3. TH1's BOM part number is Murata PRG18BB101MB1RB, a nominal 100Ω thermistor; its actual resistance varies with conditions and cannot be treated as a constant resistor. **TH1 is not in the +BATT supply path**; the opposite claim in older docs has been corrected.
- The HD-1910 datasheet lists an operating voltage of 4–8.4V, default baud rate 1Mbps (about 1µs per bit), signal high level 2–5V, low level 0–0.45V. A nominal 3.3V high level matches, but this does not guarantee an acceptable waveform at the far end with the wiring harness attached.
- The `3A max` note on the schematic sits next to the 4-pin J11; neither it nor TH1 can be taken as evidence that the 3-pin servo supply already has current limiting / fuse protection.

An independent agent parsed the PCB pin nets again and checked them against the original schematic, confirming the topology above. Edges, ringing, ground offset, and supply transients have not yet been measured, so **it cannot be concluded that a HAT chip is damaged, a pull-up value is unsuitable, a particular servo is faulty, or a ferrite core is needed**.

## Next: change only one condition at a time

For later progress, see the [3000-round hold-pose state readback summary](50Hz-hold-pose-read-state-20260928.en.md): the debug console was updated to 0.15.4 with a 50 Hz target, and within a roughly 64-second window all 14 servos had no missing responses, at an actual rate of about 46.87 Hz. The following is the single-variable troubleshooting plan drawn up at the time; it does not mean none of the items have been done since, and that window also does not independently prove that any particular wiring change was the cause of the fix.

1. Shut down normally and cut power. Keeping the existing reliable supply positive/negative leads, add a short GND wire routed along the same path as DATA, from HAT GND to servo GND. Adding only this local reference/return path, retest with the same IDs, 1Mbps, 10Hz, 200 rounds, and a longer window. A newly added thin ground wire cannot replace the servo's high-current supply negative lead.
2. If reads are still missed, separately isolate the Feetech debug board's DATA, keeping only its confirmed power and ground; with the HAT as the only communication interface, retest with the same statistics. Even with USB unplugged, the debug board may still alter the bus load through its transceiver, pull-ups, or protection structures, but there is currently no evidence that it is contending for the bus.
3. If it persists, compare using a short known-good cable, or after powering off and reconnecting, connect the same group of servos to the Feetech adapter alone and compare the adapter with the HAT. When switching the controlling side, disconnect DATA on the other side to avoid mixing two topologies into one set of results.
4. With an oscilloscope, measure in turn DATA at the HAT connector side relative to local GND and DATA at the servo 33 side relative to local GND, and observe the ground offset between the two ends, servo VCC, and TX and DIR switching. Focus on whether the low level falls within spec, whether the high level crosses 2V in time, rise time, ringing, and the end of the request / start of the reply. A read-back 7.4–7.5V cannot rule out very short supply dips.

The HAT and the Feetech servo datasheet number connector pins differently; check by **DATA / VCC / GND function and the actual connector orientation**, and do not copy pin numbers directly.

A ferrite core is only suitable as a comparison measure after high-frequency common-mode interference has been found; it cannot replace a ground reference, nor fix software mismatches, driver contention, slow rising edges, or supply voltage drop. If ferrite cores are tested later, first evaluate passing the whole harness together through a clip-on ferrite; do not add magnetic series impedance on DATA alone without measurement. Changing R32, shorting TH1, or adding a termination resistor is not recommended for now: each of these changes current, edges, or protection conditions.

## Sources and raw records

- [Official HAT project](https://github.com/pollen-robotics/elec_RPI_Robot_HAT): checked the local `dynamixel.kicad_sch`, `elec_RPI_Robot_HAT.kicad_pcb`, and page 4 of the production PDF; the drawing is marked Rev B1, 2026-05-06.
- [HD-1910-C001 datasheet](../FeeTech_HD1910M_Servo/HD-1910-C001串型规格书20260907.pdf), PDF pages 3, 4, 8.
- [TI SN74LVC1G126](https://www.ti.com/lit/ds/symlink/sn74lvc1g126.pdf), [TI SN74LVC1G125](https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf): enable polarity, tri-state, and logic levels.
- Private record directory on the debug PC, `Radxa-Zero3W/调试记录/`: `HAT头部接入只读对比-20260928.json`, `HAT头部实际回包顺序-20260928.json`, `HAT头部修复后网页200帧-20260928.json`, `同步读修复部署-20260928.json`. The records were not uploaded as public attachments.
