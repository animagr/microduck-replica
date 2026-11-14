# Electronics Purchase List (China / Taobao)

**English** · [简体中文](电控采购清单.md)

> **The repo has four lists plus one printing guide, each with its own scope:**
>
> | Document | Covers | Does not cover |
> |---|---|---|
> | [BOM](../BOM.en.md) | **Master table**: all parts, quantities (counted from geom references in the MJCF), cost range, unresolved gaps | Which shop to buy from, how to print |
> | **Electronics purchase list** (this one) | **Where to buy** the electronics: main controller / camera / ToF / power / the two PCBs / cables, real Taobao links + pitfalls | Basis for quantities, mechanical parts |
> | [Mechanical purchase list](mechanical-purchase-list.en.md) | **Where to buy** the mechanical parts: bearings / fasteners / consumables, real Taobao links | Electronics |
> | [Hardware spec quick reference](hardware-spec-quick-reference.en.md) | **Parameters**: interfaces, voltages, protocols, values the software side must match | Prices and shops |
> | [print/README](../print/README.en.md) | **Printing entry point**: choose version, material and quantity in the CAD repo | Purchasing |
>
> The mapping between assembly part numbers and screws is in the [CAD repo](https://github.com/fanhao375/microduck-replica-cad#装配-bom).


> **Snapshot date: 2026-09-04.** Prices and sales volumes change and links may break; check prices yourself before ordering.
> **2026-10-12 correction**: the conclusion on the main-controller configuration has been changed to "1G or 2G without eMMC + microSD", and only official channels are recommended; see [Which configuration to buy](#该买哪个配置).
> For mechanical parts (bearings / fasteners / consumables), see the [mechanical purchase list](mechanical-purchase-list.en.md).
>
> This list is not an endorsement, just a record of search results. Shop information (sales, years in business) is what was displayed at the time of scraping.

---

## First, get this straight: where the boards are mounted

This directly affects which cable specs you buy, and **it is easy to get wrong**:

```
Head (the jaw_soft rigid body in the MJCF)
 ├── Raspberry Pi form-factor main controller   ← the controller is in the head, not the torso
 ├── RPI Robot HAT                              ← stacked 7.3 mm above the controller
 ├── IMX219 camera + M12 lens                   ← about 13 mm from the controller board center, same rigid body, no joint in between
 └── Speaker

Torso (trunk_base)
 ├── Two hip_yaw XL330                          ← these two basically fill the inner cavity
 ├── trunk_base bottom plate
 └── NP-F battery — mounted externally at the lower rear of the body; of its 71 mm length about 40 mm hangs outside the shell,
      clamped from the outside by two power_support pieces

What runs through the 3-DOF neck: the servo bus + the +BATT supply line coming up from the battery
```

**Evidence**: `robot_walk.xml:235` `mesh="elec_rpi_robot_hat_pcb"`, `:247` `mesh="pcb__raspberry_pi_zero_2_w"`.
Both geoms are inside the `jaw_soft` body; the two 65×30 boards are perfectly aligned in X/Y with a 7.3 mm Z gap, a standard Pi + HAT stack.

> ⚠️ **So the MIPI ribbon cable does not pass through the neck; the shortest one is enough.** The real harness fatigue risk is the **servo bus and power lines running through the neck**
> — those carry current, and that risk deserves more attention than the signal ribbon. And the official project **has not published any routing information**.

---

## 1. Main controller · Radxa Zero 3W

### Which configuration to buy

> 📌 **Erratum (2026-10-12)**: the original conclusion here was "2G / 16G eMMC". **That advice was wrong and made people spend more than necessary.**
> The official material only says **1 GB RAM, 32 GB storage**, and does not say eMMC; our own first unit uses a
> bare **2 GB board without eMMC, with a microSD card**. Running the full kissqy system, the hardware test used only 175 MB RAM and 3.3 GB storage.
> If you already bought a 2G/16G board under the old advice, it works fine; you just spent more. No need to swap it.

**Conclusion: a 1G or 2G bare board "without eMMC", plus a 32 GB microSD card.**

| Configuration | Enough? | Notes |
|---|---|---|
| **1G / no eMMC** + microSD | ✅ Enough | Same tier as the official build (official: 1 GB RAM, 32 GB storage) |
| **2G / no eMMC** + microSD | ✅ More headroom | Our first unit uses this; more comfortable later when enabling the camera and running detection models |
| With eMMC (8G / 16G / 32G…) | Works, but unnecessary | Noticeably more expensive; a card is enough for storage |

**Hardware test** (2026-10-12, first unit: 2G / no eMMC / 64 GB microSD, running the full kissqy stack + 50 Hz control loop + Bluetooth gamepad):
**175 MB** RAM used (1.79 GB available), **3.3 GB** storage used. No camera was connected then and the camera service was off;
once enabled, GStreamer and the detection model will take some more memory, but 1 GB still has margin.

**microSD card**: buy a 32 GB card from a reputable brand (SanDisk, Samsung, etc.) rated A1 or A2. Do not buy cheap no-name cards:
when the system disk has problems, the symptoms often look like some other fault and are hard to track down.

Below is the original process of estimating storage and memory separately. Its conclusion has been superseded by the hardware test above; it is kept for reference:

**Storage side**

| Item | Size | Basis |
|---|---|---|
| Armbian headless rootfs | ~2 GB | `deploy/README.md:144` confirms a headless image; **2 GB is an external rule of thumb, no basis in the repo** |
| **ONNX Runtime** | **~20 MB** | `docs/design/robotd-design.md:420` verbatim: "ONNX Runtime is a board prerequisite … **~20 MB** in every artifact would enlarge every update for nothing" — **preinstalled on the board, not in the release package** |
| **GStreamer stack** (used by `mediad`) | **~100 MB** | `docs/design/updater-design.md:901` "the GStreamer stack for `mediad`, which is **around 100 MB of apt**" |
| RKNN runtime `.so` | Unknown | No basis in the repo; not making up numbers |
| daemon artifacts + one retained old version | On the order of 10¹ MB | `Cargo.toml:79` "**model artifacts will dwarf a few MB of binary**"; `keep_previous = 1` |
| **9 locomotion policy ONNX files** — each **793,685 B ≈ 775 KiB** | **7 MB** | Measured. `alpha_stand` / `alpha_walking` / `alpha_sitstand` / `alpha_ground_pick` / `ball_kick_left` / `ball_kick_right` / `roller` / `roller_crouch` / `roulade` |
| `duck_detect.onnx` | 10.0 MB | Measured 10,477,940 B |
| `pet_detect.onnx` | 19 KB | Measured 20,201 B |
| journald cap `SystemMaxUse=200M` | **Takes no disk space with the default config** | `/var/log` is a zram device (`deploy/README.md:14/402/437`). But README:454 gives a fallback: after disabling `armbian-zram-config`, logs go to the eMMC |
| **Total** | **≈ 3 – 4 GB** | |

→ Originally estimated at 3–4 GB, **measured at 3.3 GB**. A 32 GB microSD is more than enough; **no eMMC needed**.

> 💡 **The update mechanism does not need a duplicate rootfs.** But **do not call it A/B** — upstream `docs/design/updater-design.md:46`
> clarifies this specifically: "Update granularity | **Application-level (not A/B image)** | Only daemon + model
> change; OS is static. A/B (RAUC/Mender) would be over-engineering."
> It is actually **version directories + atomic switch of a `current` symlink (`rename(2)`) + health gate + rollback**;
> `keep_previous = 1` keeps only one extra old daemon. (The actual value of `tag_prefix` in `updater.toml` is `daemon-v`.)

**Memory side**

| Item | Usage |
|---|---|
| Armbian headless | ~250 MB (external rule of thumb) |
| robotd + ONNX Runtime + RKNN | Small — each policy model is only 775 KiB |
| Camera / GStreamer buffers + `duck_detect` | ⚠️ **`duck_detect.onnx` runs on the CPU, not the NPU** (`robotd.toml:324` "a `.rknn` runs on the NPU, an `.onnx` on the CPU"; the NPU `.rknn` version is not in the repo). Also, **the RK3566 NPU shares DDR with the CPU; there is no dedicated VRAM** |
| ⚠️ The zram device for `/var/log` — **eats RAM, not disk** | Must be reserved |

→ Originally estimated as "1 GB runs but is tight"; **measured, the full stack uses only 175 MB**. 1 GB is enough, 2 GB gives more headroom, anything larger is unnecessary.

> **Official configuration**: the Pollen press kit says "**1 GB RAM, 32 GB storage**" without saying eMMC or SD card
> (this document previously wrote "1 GB / 32 GB eMMC", adding eMMC; this has been corrected). The board SKU cannot be found in the `microduck/` source code either.

### Channels — only buy from official channels, check stock first

The **official mainland China channels** listed on Radxa's [distributors page](https://radxa.com/distributors):

| Channel | Entry |
|---|---|
| ALLNET (安联新创) Taobao store | [allnetchina.taobao.com](https://allnetchina.taobao.com) |
| Radxa official Taobao store | Search Taobao for "瑞莎 Radxa" (Radxa) and make sure it is the official store |
| Radxa official JD store | Search JD for "瑞莎 Radxa" (Radxa) and make sure it is the official store |

Overseas official channels include the [ALLNET website](https://shop.allnetchina.cn/products/copy-of-radxa-zero-3w), [Arace](https://arace.tech/), etc.
**Check these shops for stock first and pick the "no eMMC" version**; if out of stock, wait for a restock rather than paying several times more at a small shop to get it faster.

ALLNET website actual prices (2026-09-04 snapshot, USD, about ¥7.2/$):

| Configuration | Price | Approx. |
|---|---|---|
| **1G / no eMMC** | **$18** | **¥130** ⭐ |
| 1G / 8G eMMC | $22 | ¥158 |
| 2G / 16G eMMC | $32.90 | ¥237 |
| 4G / 32G eMMC | $50 | ¥360 |
| 8G / 32G eMMC | $70 | ¥504 |

(+$1 with pin headers. ALLNET does not offer the 8G/64G spec. This snapshot did not include "2G / no eMMC", but that configuration does exist — our first unit is one; check the official store for the price.)

Prices at unofficial small shops at the time (counterexamples):

| Shop | Configuration | Price | Link |
|---|---|---|---|
| findboard旗舰店 (findboard flagship store) | 8G+64G "Bundle 6" (with camera/power supply/32G card/HDMI cable/heatsink) | **¥1469** | [tmall 752703346347](https://detail.tmall.com/item.htm?id=752703346347) |
| findboard旗舰店 (findboard flagship store) | 8G+64G bare board | ¥1149 | Same as above |
| 鹭控自动化工控 (Lukong Automation) | Not specified (negotiated price) | ¥690 | [taobao 1044607515575](https://item.taobao.com/item.htm?id=1044607515575) |

**A 3–6× markup, and all of them are large configurations with eMMC.** Only use the official channels above.

### Do not buy the bundles

| Accessory | Worth it? |
|---|---|
| Camera (Radxa's own IMX219, ¥129.99 separately) | ❌ A generic IMX219 costs ¥32.8 |
| 32G microSD | ⚠️ The no-eMMC version uses it as the system disk, so you need one; but the card in the bundle is not necessarily good, buy a branded A1/A2 card separately |
| Power adapter | ❌ The robot is battery powered; only for bench debugging |
| microHDMI cable | ❌ Microduck runs headless |
| Heatsink | ✅ Useful, but buy it separately for [¥19.99](https://item.taobao.com/item.htm?id=788387010174) |

---

## 2. Alternative main controller · LCSC TaiShanPi (evaluated, **does not fit**)

Also an **RK3566**, with stable domestic supply, and frequently asked about. **But the conclusion is that it cannot be used.**

**Actual prices** (the real price after selecting the "2G+16G single mainboard" SKU; the ¥22 / ¥45 / ¥195 on listing pages are all lowest-SKU bait):

| Channel | Configuration | Actual price | Link |
|---|---|---|---|
| RK开发板 (RK Dev Boards, 9-year-old shop) | 2G+16G single mainboard | **¥428** (+¥10 shipping) | [taobao 1017038620459](https://item.taobao.com/item.htm?id=1017038620459) |
| 电子元件shop (Electronic Components shop, 12-year-old shop, 46 purchases) | 2G+16G single board | **¥480.8** (free shipping) | [taobao 800894187326](https://item.taobao.com/item.htm?id=800894187326) |
| LCSC Mall official | 2G+16G | **¥580** (was ¥228, raised due to DDR price increases) | [item.szlcsc.com/20558171](https://item.szlcsc.com/20558171.html) |
| **Comparison: Radxa Zero 3W** | 1G / no eMMC (plus a microSD) | **≈¥130** | Official channels |

**All four points are against it:**

| | TaiShanPi | Radxa Zero 3W |
|---|---|---|
| **Does it fit?** | ❌ **It does not fit** — the controller is mounted **in the head**; the whole head shell is only 58.8 × 91.8 × 122.7 mm,<br>the controller slot is only 30 mm in X, and a HAT sits on top of it. The TaiShanPi at **70 × 45** has no room | ✅ 65 × 30, the slot was designed for exactly this |
| 2G+16G actual price | ¥428–580 | **≈¥237** |
| **Armbian image** | ❌ The official deployment scripts are entirely based on Radxa's Armbian image<br>(`overlay_prefix=rk35xx`, `armbian-zram-config`, netplan, updater) and would have to be rewritten | ✅ Use as is |
| **Device tree overlays** | ❌ All have to be rewritten — 40-pin pin muxing is a **board-level mapping**.<br>Microduck depends on `/dev/ttyS2`, `i2c3 @400kHz`, `i2s3_2ch`, MIPI CSI | ✅ Ready made |
| **HAT mechanical compatibility** | ❌ 70×45 vs Pi Zero 65×30; the header positions do not line up, **the HAT would have to be redrawn** | ✅ Both are Pi Zero form factor |
| SoC / NPU / rknn | ✅ Both RK3566; kernel and NPU work can be reused | ✅ |
| WiFi | AP6212 (WiFi4 / BT4.x) | WiFi6 / BT5.4 |

**But its open-source material is worth keeping** (downloadable without buying the board): the full schematic + PCB are in **JLCPCB EDA (EasyEDA) format**,
and you can open the power tree, DDR routing and AP6212 wiring of the same RK3566 directly — a ready-made, high-quality reference when drawing `imu_to_dxl`
or redrawing the HAT later.

- [LCSC open-source hardware platform · TaiShanPi project](https://oshwhub.com/li-chuang-kai-fa-ban/li-chuang-tai-shan-pai-kai-fa-ban)
- [Download center](https://openkits-wiki.easyeda.com/zh-hans/tspi-rk3566/download-center.html)

---

## 3. Camera · IMX219 (MIPI CSI)

The camera and the controller are **both in the head, on the same rigid body**. The overlay used by `setup-board.sh:748` is
`radxa-zero3-rpi-camera-v2`, and `setup-rkaiq.sh:147` has `SENSOR = imx219`.

> ⚠️ **It is rotated 90°, not flipped 180°.** `mediad/src/main.rs:82`:
> "**90, because the head camera is mounted a quarter turn off**, and this is the one place
> that fact is written down." The 180° in `docs/project/media-bringup.md:472` is outdated data from the **alpha unit**.

| Shop | Price | Sales | Link |
|---|---|---|---|
| DECXIN旗舰店 (DECXIN flagship store) | ¥32.8 | 100+ | [tmall 775872575316](https://detail.tmall.com/item.htm?id=775872575316) |
| 德创信摄像头 (Dechuangxin Camera) | ¥32.8 | 27 | [taobao 771618094322](https://item.taobao.com/item.htm?id=771618094322) |
| 盛成威科技 (Shengchengwei Tech, 11-year-old shop) | ¥38 | 84 | [taobao 596521821696](https://item.taobao.com/item.htm?id=596521821696) |
| 亚博智能 (Yahboom, 14-year-old shop, has technical docs) | ¥44 | 15 | [taobao 709927597121](https://item.taobao.com/item.htm?id=709927597121) |
| 树莓派零售商 (Raspberry Pi retailer, free shipping, ships within 48h) | ¥68 | 100+ | [taobao 760446989892](https://item.taobao.com/item.htm?id=760446989892) |
| findboard旗舰店 (findboard flagship store, official Radxa version) | ¥129.99 | 9 | [tmall 874789708454](https://detail.tmall.com/item.htm?id=874789708454) |

### Ribbon cable: 15-pin ⇄ 22-pin adapter (possibly needed, **buy the shortest**)

⚠️ **The official manual does not give the connector spec.** `Radxa ZERO 3W Product Brief` Rev 1.10 §6.3 only says:

> "The Radxa ZERO 3W is equipped with a **1x4-lane MIPI CSI** connector for camera integration.
> This interface is designed to be backward-compatible with standard industrial camera peripherals."

No pin count, no pitch. But the Zero 3W is a Raspberry Pi Zero form factor, with the CSI connector on the same edge as the Micro HDMI and a layout matching the Pi Zero,
so it is **very likely the narrow 22-pin 0.5 mm type**, whereas generic IMX219 modules ship with the **standard 15-pin 1.0 mm** cable.

> 💡 **A 15 cm or even shorter cable is enough** — the camera and controller are on the same rigid body about 13 mm apart,
> and the ribbon **does not pass through the neck**. Do not buy a 30 cm one.

| Shop | Description | Length | Price | Link |
|---|---|---|---|---|
| **汇博视捷科技工厂店 (Huibo Shijie Tech factory store)** | 15-to-22-pin gold-finger FPC, **4 cm short version** | 4cm | **¥1.88** | [taobao 654755002992](https://item.taobao.com/item.htm?id=654755002992) |
| 摄像头生产厂家 (camera manufacturer, 11-year-old shop) | Pi Zero Camera Cable | 16cm | ¥1.88 | [taobao 819560127110](https://item.taobao.com/item.htm?id=819560127110) |
| **Tytion (15-year-old shop)** | Title explicitly says **15P 1.0 to 22P 0.5** | 15cm | ¥2.5 | [taobao 678057486394](https://item.taobao.com/item.htm?id=678057486394) |
| 树莓派精品销售商 (Raspberry Pi premium seller, 13-year-old shop, free shipping) | Official cable, 135/200/300/500 mm options | Several | ¥5.8 | [taobao 784739658496](https://item.taobao.com/item.htm?id=784739658496) |

---

## 4. ToF ranging · VL53L5CX or VL53L8CX (8×8 multizone)

**The firmware recognizes only these two chips, no third.** `tof/src/sensor.rs` has a single match on the revision ID:

```rust
match revision_id {
    0x0C => L8cx,
    0x02 => L5cx,       // Official comment: "most ducks in use have this one"
    _    => Unknown,    // No driver; errors out and exits
}
```

When it cannot recognize the chip, the daemon says `… which is neither a VL53L5CX nor a VL53L8CX` and exits.
The firmware only compiles two ULD driver shims (`Driver::L5` / `Driver::L8`); other chips have no driver at all, and changing the ID will not fool it.

I²C address candidates are **`0x29` or `0x52`** (`tof/src/main.rs:107`; 0x52 is where the official prototype moved it to make room for the IMU address,
and a moved sensor stays at 0x52 after power loss), on i2c3 @ 400 kHz. On the HAT it connects via **JST SH 1.0 mm 4P** (Qwiic / Stemma QT) connectors J5–J8.

### Board size determines whether it fits in the face shell

Even among chips that work, module board sizes differ by more than 2×. The ToF opening in the face shell (`face_part`) is made for a specific board shape; a different board shape means changing the drawing:

| Module | Chip | Board size | Weight | Reference price | Verdict |
|---|---|---|---|---|---|
| **VL53L5X V2 module** | VL53L5CX | **15.8 × 10 mm** | 1.15 g | ¥44.5 (¥49.5 with cover) | ✅ **First choice**: recognized by the firmware, smallest board, and cheapest |
| VL53L8CX module (common domestic board) | VL53L8CX | 33.4 × 10.2 mm | 1.7 g | ¥75 | ⚠️ **Not recommended**: the chip is fine, but this board is 33.4 mm and does not fit the face shell (hardware test 2026-09-20). Unless you can find a shorter L8CX board or are willing to modify the shell |
| VL53L7CX module | VL53L7CX | 26 × 11.5 mm | 1.3 g | ¥75 | ❌ **Do not buy**: the firmware errors out and exits |

**The hole spacing on the printed part is 20 mm, and only the L5CX board matches it** (colleague's hardware test 2026-09-20: the printed part holes are 20 mm apart,
the L8CX board on hand is 28 mm, it does not fit). The holes are at the centers of the ears at both ends, about 2.3~2.4 mm from the ends,
so `24.7 − 2×2.35 ≈ 20` and `33.4 − 2×2.7 ≈ 28`. The official face shell was designed for the L5CX in the first place,
which also matches the comment in the firmware source: "most ducks in use have the L5CX".

**Selection order: first check whether the firmware recognizes the chip (only L5CX / L8CX), then whether the hole spacing matches (must be 20 mm).**
If you pick by size first, you end up like us: buying an L7CX because it was short, then returning it and starting over.

The "cover" (盖片) is a black optical shroud mounted above the sensor (¥5 separately) to prevent crosstalk; whether to fit it depends on the shell design.

| Shop | Model | Price | Sales | Link |
|---|---|---|---|---|
| 森科源电子 (Senkeyuan Electronics) | VL53L8CX | ¥70 | 1 | [taobao 1025775539663](https://item.taobao.com/item.htm?id=1025775539663) |
| 深圳市渱雯电子 (Shenzhen Hongwen Electronics) | VL53L8CX | ¥74.98 | 0 | [taobao 977907234039](https://item.taobao.com/item.htm?id=977907234039) |
| 都会明武电子 (Duhui Mingwu Electronics, free shipping, 20k repeat customers) | VL53L7CX / **L8CX** | ¥75 | 100+ | [taobao 942554129061](https://item.taobao.com/item.htm?id=942554129061) |
| 深圳优信电子 (Shenzhen Youxin Electronics, technical docs, free shipping, business invoicing) | VL53L8CX | ¥78.5 | 31 | [taobao 967946231167](https://item.taobao.com/item.htm?id=967946231167) |
| 勇泰发电子 (Yongtaifa Electronics, 11-year-old shop, free shipping) | VL53L8CX | ¥84.8 | 14 | [taobao 939165242465](https://item.taobao.com/item.htm?id=939165242465) |
| 归吉星旗舰店 (Guijixing flagship store) | ST official P-NUCLEO-53L8A1 evaluation kit | ¥98 | 1 | [tmall 725486284128](https://detail.tmall.com/item.htm?id=725486284128) |

> ⚠️ **Do not end up with a VL53L0X.** Most results when searching for "VL53L5CX" are **VL53L0X — single-point ranging**, which the firmware does not recognize.
> The `TOF050C / 200C / 400C` family (from ¥2.79) are also single-point L0X / L1X: cheap and small, but the firmware does not recognize them either.
>
> ⚠️ **The VL53L7CX is not a short version of the L8CX.** The L7 is a different chip with a 90° wide field of view; its revision ID does not match,
> and the firmware errors out and exits. On 2026-09-20 we bought an L7CX to avoid the 33.4 mm long L8CX board and had to return it.
> The short one that works is the **L5CX** (15.8 × 10 mm). Some listings mix L5 / L7 / L8 in one item, so **read the SKU carefully**.
>
> We saw a ¥8 "VL53L5CX" whose title also said "79GHz radar sensor" — keyword-stuffed junk;
> we also saw a ¥5 "VL53L5X V2" that turned out to be the **cover**, not the module.
>
> How to verify on arrival: connect it to the board and look at the model printed by the `tof` daemon, or read the revision ID directly. **Only `0x02` (L5CX)
> and `0x0C` (L8CX) are correct.**

---

## 5. Power

| Part | Shop | Price | Sales | Link |
|---|---|---|---|---|
| **NP-F battery holder (for power pickup)** | 腾壶旗舰店 (Tenghu flagship store) | ¥17.8 | 99 | [tmall 658975825526](https://detail.tmall.com/item.htm?id=658975825526) |
| **NP-F power plate** (Type-C fast charge) | 拓普赛旗舰店 (Tuopusai flagship store) | ¥19 | 58 | [tmall 926961598924](https://detail.tmall.com/item.htm?id=926961598924) |
| NP-F550 battery itself | 唯卓仕 (Viltrox, China CCC certified, with charge indicator) | ¥52.8 first order | 900+ | Search for "唯卓仕 NP-F550" (Viltrox NP-F550) |

> 💡 **These two items fill exactly the gap upstream left.** The official project only provides the printed part `power_support` (×2),
> with **no contact model**; the power pickup was originally left for you to solve — just buy a ready-made plate.
>
> ⚠️ **It is NP-F550, not F970.** The upstream mesh file name `np_f970` is misleading: the measured bounding box
> **38.6 × 20.6 × 70.8 mm** is exactly the F550 size (Sony official specs: F550 = 38.4×20.6×70.8,
> F970 = 38.4×**60.0**×70.8). A grep over the whole source tree has only 2 hits, **both NP-F550**
> (`robotd-design.md:572`, `duck-control/src/model.rs:108` "NP-F550, 2S Li-ion"), and zero hits for F970.
>
> The battery is **mounted externally at the lower rear of the body**; of its 71 mm length about 40 mm hangs past the lower edge of the torso shell, clamped from the outside
> by two 83.5 mm long `power_support` pieces.

### Buck converter module (supplies 5 V to the controller in the no-HAT build)

`U9 AP63205` on the HAT provides 5 V to the controller; in the [no-HAT build (without the HAT board)](no-HAT-build.en.md) you need to buy a ready-made module to take its place.

| Part | Spec | Price | Search term | Link |
|---|---|---|---|---|
| **UBEC 5V/3A** (first choice) | Input **≥ covering 6–8.4 V**, output 5 V 3 A, with shielding and ferrite ring | ¥10–15 | "UBEC 5V 3A 2S" | *TBD* |
| MP1584EN module (alternative) | Input 4.5–28 V, output 5 V fixed or adjustable, rated 3 A (~2 A in practice without heatsinking) | ¥3–5 | "MP1584EN 5V" | *TBD* |

**Before buying, look at these three numbers, not the brand:**

1. **Minimum input voltage ≤ 6 V** — a 2S battery under load can sag to 6.6 V, and lower when servos start simultaneously. Many UBECs say "2–6S" but list a 7 V minimum; **when the 2S battery is nearly empty, it drops out of regulation first and the controller reboots**. Find the "input voltage" line on the product page; the minimum must be ≤ 6 V
2. **Output current ≥ 2 A continuous** — the Radxa Zero 3W running NPU + camera + WiFi peaks a bit over 1 A, and the official HAT uses the 2 A AP63205. Small modules rated 3 A deliver 1.5–2 A in practice without heatsinking, so prefer a UBEC
3. **Synchronous buck** — 90%+ efficiency. **Do not buy an LM2596**: 150 kHz non-synchronous, needs more than 1.5 V of headroom; 6 V in / 5 V out is already marginal, and it runs hot

Put a **470 µF / 16 V** electrolytic across the input to buffer the voltage drop when all 15 servos start at once — see [no-HAT build · Step 3](no-HAT-build.en.md).

---

## 6. The two PCBs

### RPI Robot HAT — cannot be bought, only fabricated; but you may not need it

**Not sold separately by the official project.** Pollen only sells the complete Microduck; there is no retail page for the HAT. We found no replicas on oshwhub either.

**① Faithful fabrication** — the official project provides full production files (Gerber + BOM + pick-and-place, Apache-2.0).
Checked: **4-layer board** (`F_Cu / In1_Cu / In2_Cu / B_Cu`), outline **65.0 × 30.9 mm**, corner radius **R3.5**,
BOM **47 lines / 123 parts** (of which 5 lines / 9 parts are DNP), **113 placements** actually populated. With SMT the cost starts at several hundred yuan and there are minimum order quantities.

**② Replace it with ready-made modules — under ¥50**

What the HAT actually does (checked line by line against the schematic):

| Function | Still needed? | Ready-made replacement |
|---|---|---|
| **Servo bus half-duplex TTL** — U5 `74LVC1G08` + U6 `SN74LVC1G125` + U7 `SN74LVC1G126`,<br>direction controlled by `DynUART_Tx`/`DynUART_Rx`/`Dynamixel_dir` | ✅ Required | See table below |
| **Power distribution** — `+BATT` feeds the servos directly; U9 `AP63205` + L4 6.8µH → `+5V` onto the 40-pin header for the controller;<br>U3 `XC6206P182` → `+1V8` for the codec | ✅ Required | Ready-made UBEC (5V/3A or more) |
| **Audio** — U2 `TLV320AIC3104` (i2c3 0x18 + i2s3_2ch), U1 `PAM8406D` amplifier,<br>MK1 MEMS microphone, Wago terminals for a 5W speaker and external mic | ❓ Depends on your needs | **If you do not need recording/speaker, drop the whole thing** |
| **Sensor expansion** — J5–J8 JST SH 1mm 4P (Qwiic/Stemma) for the ToF | ✅ Needed | Hang it directly on i2c3, a few wires |
| Onboard U11 `BMI088` | ❌ **Populated but not used by the software** (`i2c3-pihat.dts:11` "dormant", `:31` "unused but still connected") | — |
| U4 `CAT24C32` EEPROM | ❌ **DNP, not populated** — so this board is **not a self-identifying HAT** | — |

**Servo connectors**: J13 / J14 = **JST EH 3P** (TTL, to `+BATT` via TH1 100R thermistor);
J3 / J11 = **JST EH 4P** (RS-485, driven by U8 `SIT3088E`, directly on `+BATT`), with the schematic note **"3A max"**.

**Half-duplex bus adapter boards** (a direct fit for the Feetech route):

| Shop | Description | Price | Link |
|---|---|---|---|
| Fashion脖子 (13-year-old shop, 90 purchases) | Serial bus servo driver board, **for ST/SC series** | **¥22** | [taobao 1005305041207](https://item.taobao.com/item.htm?id=1005305041207) |
| 众灵科技企业店 (Zhongling Tech business store, 200+ purchases) | ZLink USB/TTL debug board + bus servo adapter | ¥22.5 | [taobao 570100064201](https://item.taobao.com/item.htm?id=570100064201) |
| 芯板坊 (Xinbanfang, 7-year-old shop) | Waveshare serial bus servo driver board, for ST/SC | ¥24 | [taobao 954634564409](https://item.taobao.com/item.htm?id=954634564409) |
| 灵影智能企业店 (Lingying Intelligent business store, 200+ purchases) | ST/SC Feetech bus servo TTL driver board `TTL_Adapter_(A)` | ¥26 | [taobao 983866781632](https://item.taobao.com/item.htm?id=983866781632) |

> 💡 **On the Feetech route this option is especially worth considering.** `imu_to_dxl` has to be redrawn, the policy retrained, and the device tree changed —
> the HAT deserves re-evaluation as well. A ¥22 adapter board + a UBEC replaces both required functions, "servo bus" and "power distribution".
> The cost is losing the onboard audio.

### imu_to_dxl — draw it yourself

STM32G031F8P6 + LSM6DSV16X + half-duplex buffer, presenting itself externally as a bus slave (ID 200 on the Dynamixel side).
The protocol and register layout have been fully reconstructed; see [hardware reverse engineering](hardware-teardown.en.md).

- **Fabrication cost**: 2-layer board, about ¥25–40 at JLCPCB (without assembly)
- **Dual protocol**: to support both Feetech and Dynamixel, **same hardware, firmware branch** —
  the physical layers are identical (half-duplex single-wire TTL / 1 Mbps / 3 wires); the only difference is the packet format
  (V2 header `FF FF FD 00` + CRC-16; Feetech `FF FF` + `~sum`)
- ✅ **Connector and pinout confirmed by the official datasheet** — Feetech "HL-2915-C002 串型规格书" (HL-2915-C002 serial servo datasheet) A/0 (2026-02-27),
  page 4, items 6-7: connector **`AMP-3`**, **`1=GND / 2=Vcc / 3=Signal/TTL`**, same as Dynamixel.
  In `HD-1910-C001.stp` the connector part is named `AMP-3P`, and the assembly includes `HL-2915-C002_ASM`, so the two models share a platform.
  <br>The same datasheet also confirms: half-duplex asynchronous, 8bit/1stop/no parity, **factory default 1 Mbps**, ID 0–253 (default 1),
  signal high level **2–5 V** (this board's 74LVC output of 3.3 V is within the window; inputs tolerate 5.5 V, so the servo's 5 V is fine)
  <br>⚠️ That datasheet is for the HL-2915-C002 (**12 V**); its electrical parameters cannot be applied to the HD-1910 (5–8.4 V)
  <br>⚠️ "Feetech = single-wire TTL" only holds for STS/SCS/HL — the official manual states that the **SMS series uses RS485, default 115200**
- **Connector housings still need a physical test fit** — Feetech cables are labeled **5264 terminals**, while the official HAT uses **JST EH**;
  both are **2.5 mm pitch** but different series, with different latches and housing shapes. Once the servos and cables arrive, do one test fit;
  if it does not plug in, change J1/J2 from `B3B-EH-A` (`C160259`) to 5264-3P.
  The PR #12 layout uses JST PH 2.0 mm, **which is the wrong pitch and must be changed**
- **C6 (LDO input capacitor) voltage rating 10 V → 25 V** — the bus is 8.4 V fully charged; 10 V is not enough margin (and MLCCs also lose capacitance under DC bias)
- **C5 should be 4.7 µF, not 100 nF** — ST DS12992 Rev 3 Fig.13 requires
  `1 × 100 nF + 1 × 4.7 µF` on `VDD/VDDA`; two identical 100 nF in parallel do not do the job. Use `C19666` from the LCSC basic library
- **Leave an active oscillator footprint on pins 2 and 3 of U1 (not populated)** — the TSSOP20 does not bring out `OSC_OUT`, so a passive crystal cannot be used;
  HSI16 worst-case accuracy is −1.85%/+1.55% (Table 41), enough for 1 Mbps but without much margin
- **Add a TVS on the DATA line** — hot-plugging servos is normal
- **Detect the protocol automatically in software; no DIP switch/jumper** — both headers start with `FF FF`; Dynamixel V2 follows with `FD 00`, Feetech follows with `ID`+`LENGTH` (LENGTH is always ≥ 2, so `FD 00` is unambiguous). Vote on the first 3 packets to lock in, then send and receive using the locked protocol. On a walking robot a DIP switch is a vibration failure point, and this board is configured only once in its lifetime anyway
- **Use 6P, not 4P, for J3** — the extra pins 4/5 are `USART1_TX/RX` (U1 pins 16/17 remapped); plug in a 5-yuan USB-TTL adapter and you can see printf. The G031 has no USB peripheral, and adding a USB port would need an extra bridge chip; not worth it

---

## 7. Cables and tools

| Part | Shop | Description | Price | Link |
|---|---|---|---|---|
| **Servo bus cable** | 深圳飞特舵机工厂店 (Shenzhen Feetech servo factory store) | 3-pin / 4-pin **5264 connector** | **¥1.8** | [taobao 616460581906](https://item.taobao.com/item.htm?id=616460581906) |
| Servo cables | 鸿翊电子舵机工厂店 (Hongyi Electronics servo factory store) | Feetech serial bus, 3-pin/4-pin 5264 terminals | ¥2.5 | [taobao 769633088382](https://item.taobao.com/item.htm?id=769633088382) |
| Servo cables (multiple lengths) | 松甲科技 (Songjia Tech, 300+ purchases) | Female-to-female **5264-3P**, 10/15/20/30/50/70 cm | ¥2 | [taobao 587191439333](https://item.taobao.com/item.htm?id=587191439333) |
| **FE-URT-1 debug board** | 深圳飞特舵机工厂店 (Shenzhen Feetech servo factory store, official) | USB to 485/TTL | **¥45** | [taobao 603181554943](https://item.taobao.com/item.htm?id=603181554943) |
| URT-2 debug board | 深圳飞特舵机厂家 (Shenzhen Feetech servo manufacturer) | Same type | ¥45 | [taobao 575365901461](https://item.taobao.com/item.htm?id=575365901461) |
| URT debug board (third party) | 云驱者科技企业店 (Yunquzhe Tech business store) | Same type | ¥40 | [taobao 712781832610](https://item.taobao.com/item.htm?id=712781832610) |

> **The debug board is a must** — the first thing to do when the servos arrive is measure the bus timing on real hardware.
>
> ⚠️ **This is not a Feetech-only problem.** The official Dynamixel path also has a **response delay per device** —
> `duck-control/src/model.rs:84-86` says the XL330 ships with `return_delay_time = 250`,
> i.e. **500 µs/device**, "Across **16 devices** that is **8 ms per tick — 40% of a 20 ms budget**";
> the official fix is to write 0 to this register (it is in `EXPECTED_REGISTERS`).
> **The Feetech side has been checked**: STS/SCS has `SYNC READ` (`0x82`), and Return Delay Time is 0 from the factory —
> see [hardware reverse engineering · Feetech STS/SCS protocol comparison](hardware-teardown.en.md). All the more reason to measure rather than assume it must be slower.

---

## 8. Pitfalls

1. **Do not buy a long camera ribbon** — the controller and camera are both in the head on the same rigid body; the MIPI cable does not pass through the neck. 4–15 cm is enough.
2. **The camera is rotated 90°, not 180°** — see above.
3. **VL53L0X sold as VL53L5CX** — most search results are the single-point L0X, which the firmware does not recognize; and the L7CX is not an L8CX either.
4. **Do not overpay for the bare Radxa board** — 1G / no eMMC is about ¥130 through official channels (2026-09 snapshot), while small shops list it at ¥690–1469. Only use official channels; and there is no need to pay extra for eMMC, just insert a microSD.
5. **The TaiShanPi does not fit** — it is not just expensive; the head simply has no room for 70×45.
6. **The ¥8 Feetech STS3215 / ¥22 TaiShanPi** — both are SKU bait; click through and the lowest tier is an accessory.
7. **Beware of counterfeits of Loctite 243 below ¥15** (see the [mechanical purchase list](mechanical-purchase-list.en.md)).

---

## Unverified items

- All prices, sales, shop information and link validity (2026-09-04 snapshot)
- Whether Pollen sells the HAT separately
- Whether the Zero 3W CSI connector is actually 15P or 22P (not given in the official docs; this document marks it as "very likely 22P")
- The TaiShanPi's specs, prices and open-source project content
