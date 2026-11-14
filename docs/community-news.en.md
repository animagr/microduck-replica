# Community News and Intelligence

**English** · [简体中文](社区动态.md)

**Recorded**: 2026-08-31
**Data sources**: X (public posts read through a logged-in session), GitHub API, public media reports

> ⚠️ This document distinguishes **verifiable facts** from **unconfirmed rumors**. Anything marked 🔴 is secondhand information;
> do not base decisions on it.

---

## 1. Timeline

| Date | Event |
|---|---|
| 2026-08-27 | Pollen Robotics × Hugging Face announce Microduck, preorders open at $399 |
| 2026-08-27 | The software stack (Rust runtime + RL training) is open sourced under Apache-2.0 |
| 2026-08-30 | The community starts asking on GitHub for STEP files, 3D printing source files, and the power board schematic |
| 2026-08-31 | Thomas Wolf: *"Microduck reached the Shopify UI limit"* |
| **Before Christmas 2026** | **First shipments (North America / Europe / UK)** |

> 📌 **Key premise: as of 2026-08-31, there are no physical units on the market.**
> So every public "teardown" so far is **inference from the software and specs**, not a physical teardown.

---

## 2. Popularity data (verifiable)

### Official announcement posts

| Account | Likes | Views |
|---|---|---|
| [@ClementDelangue](https://x.com/ClementDelangue/status/2092931447644442635) (HF CEO) | 11,974 | 4.49M |
| [@Thom_Wolf](https://x.com/Thom_Wolf/status/2092923071829049592) (HF co-founder) | 7,833 | 2.56M |
| [@pollenrobotics](https://x.com/pollenrobotics/status/2092915032052879425) | 4,761 | 1.56M |

### GitHub repo growth

| Repo | 2026-08-28 | 2026-08-31 |
|---|---|---|
| `pollen-robotics/microduck` | 938 ★ / 87 forks | **3,508 ★ / 418 forks** |
| `pollen-robotics/microduck_rl` | 280 ★ / 33 forks | **876 ★ / 152 forks** |

About 3.7× in three days.

### Sales

- 🔴 "Over $1M in sales in 7 hours" — from [@DataChaz](https://x.com/DataChaz/status/2094028777634533518) (826 likes),
  **unofficial data, not confirmed by Pollen**
- ✅ Thomas Wolf himself posted on 8/31 that *"Microduck reached the Shopify UI limit"* — indirect evidence that sales are high
- 🔴 A Chinese-language account claimed "$2.6M in 24 hours, one unit every 4 seconds on average"; **that account is also promoting a meme coin, so credibility is low**

---

## 3. ⭐ External validation: others independently reached the same controller conclusion

On 2026-08-31, [@tspy](https://x.com/tspy/status/2094249218735300630) posted a "Microduck physical architecture breakdown" (169 likes):

> Actuators 15 × Dynamixel XL330 · controller **Radxa ZERO 3W / Rockchip RK3566** ·
> 1 GB RAM + 32 GB · dual 6-axis IMU · 8×8 multizone ToF LiDAR · forward wide-angle camera ·
> 2× NFC antennas · battery NP-F550 · control frequency 50 Hz

**Fully consistent with the conclusions of this repo's [hardware reverse engineering](hardware-teardown.en.md)**, including the most crucial point,
the **Radxa Zero 3W**. Two independent paths reached the same answer.

In the same thread, @tspy's answer on cost also matched this repo's conclusion:
> **"The cost seems higher than just buying it"**

### Depth of this repo compared with community analysis

| Level | Public community analysis | This repo |
|---|---|---|
| Spec list | ✅ | ✅ |
| Controller model | ✅ | ✅ |
| **Bus electrical layer and protocol** | ❌ | ✅ TTL half-duplex 1 Mbps, Protocol V2 |
| **Chip I2C addresses** | ❌ | ✅ codec 0x18 / ToF 0x29 / BMI088 0x19 |
| **IMU data block layout** | ❌ | ✅ Register 124, 12 bytes, byte by byte |
| **Assembly geometry** | ❌ | ✅ Exploded view + CAD assembly |
| **Fasteners** | ❌ | ✅ M2 system, reverse engineered from hole scans |

---

## 4. What the community has already built (within 4 days of launch)

All verifiable public projects:

| Author | Content | Reception |
|---|---|---|
| [@onusoz](https://x.com/onusoz/status/2093763495846441348) | Trained a small 1.3M-parameter LLM to output emotion labels, then used a **Rust synthesizer** to procedurally generate R2D2-style sounds, running in the browser | 543 ♥ |
| [@Thom_Wolf](https://x.com/Thom_Wolf/status/2092959363992326236) | Vibe-coded an image detection integration so the robot **tracks a laser pointer** | 3,065 ♥ |
| [@cdngdev](https://x.com/cdngdev/status/2093721082582933639) | Trained it to play a "find a needle in 5 million stalks of hay" game | 852 ♥ |
| Anonymous | Trained a **somersault** (reposted by Clem) | 3,714 ♥ |
| [@__Rhodium__](https://x.com/__Rhodium__/status/2093404140454265205) | Trained **breakdancing** | 610 ♥ |

> This shows the platform really is fun to play with and has a low barrier for further development — all of these were built within days of getting the software stack.

---

## 5. What the community is asking for on GitHub

| Issue | Request | Official reply |
|---|---|---|
| [#175](https://github.com/pollen-robotics/microduck/issues/175) | **STEP files** — STLs have no normal information, so curved surfaces render as polygonal facets | ❌ None |
| [#173](https://github.com/pollen-robotics/microduck/issues/173) | **3D printing source files** | ❌ None |
| [#174](https://github.com/pollen-robotics/microduck/issues/174) | Whether the battery can be charged in place + **whether the power board schematic is in the open-source plans** | ❌ None |

We checked the last ~10 issues: **Pollen members have not replied to a single one**, yet the repo is still updated daily (dev releases were still being published on 8/30).

**Official position** (CNX Software's report verbatim):
> *"Pollen Robotics told the press not to refer to the robot as
> 'open-source hardware' **(for now)**."*

What the official team declined is the **label** "open-source hardware", which does not mean no board was released at all —
**the HAT board is actually fully open source** ([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT),
Apache-2.0). What has not been published is the `imu_to_dxl` board, editable mechanical CAD and the complete-robot BOM.
"(for now)" leaves the door open, with no timeline.

> Erratum 2026-09-03: the earlier summary here was wrong and has been corrected.

---

## 6. ⚠️ Noise and risks

### Meme coins riding the hype

Tokens such as `$microduck`, `$MACRODUCK` and `$Microdino` are heavily riding this wave of attention.
A considerable share of search results are token promotions, **unrelated to the project itself**.

### 🔴 "Microdino" — not recommended

On X, [@davidfeldt](https://x.com/davidfeldt/status/2093491570867884322) claimed to have built
a "same-spec" Microdino (550 likes). Looking at the replies:

- Several people accuse it of being a scam: *"Carefull this guys is scamer"*, *"Scam"*
- Someone asks: *"Why did you scrap the first token and mint another one?"*
- When asked *"does it have the full CAD design?"*, the answer is vague: *"You can generate the CAD after"*
- When asked whether there is a sim2real model: *"Not yet but soon!"*
- Someone in the replies directly posts the $Microdino contract address

**Conclusion: it is not a credible open-source hardware project, and this repo does not reference any of its content.**

### 🔴 Unconfirmed rumors

- "NVIDIA acquires Hugging Face for $12.9B" — posted by a meme-coin promotion account, **no reliable source whatsoever**
- "Buying via a Japanese proxy requires waiting about 10 months" — a single netizen's claim, unconfirmed

---

## 7. What this means for this project

1. **The reverse-engineering conclusions have been independently validated externally** — the most crucial judgment, the Radxa Zero 3W, was independently confirmed by someone else
2. **With no physical units on the market, this repo's analysis is at the frontier of public information** — one layer deeper than the community spec lists
3. **What the community is asking for (STEP, printing source files, schematics) is exactly the direction this repo is working in** —
   the target audience clearly exists
4. **Beware of fake open-source projects riding the hype** — this repo insists on citing the source of evidence for every conclusion,
   which sets it apart from them
