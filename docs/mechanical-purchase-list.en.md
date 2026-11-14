# Mechanical purchase list (China / Taobao)

**English** · [简体中文](机械采购清单.md)

> **The repo has four lists plus one printing guide, each covering its own area:**
>
> | Document | Covers | Does not cover |
> |---|---|---|
> | [BOM](../BOM.md) | **Master list**: all materials, quantities (counted from geom references in the MJCF), cost range, unresolved gaps | Which shop to buy from, how to print |
> | [Electronics purchase list](电控采购清单.md) | **Where to buy** electronics: controller / camera / ToF / power / the two PCBs / wiring, real Taobao links + pitfalls | Basis for quantities, mechanical parts |
> | **Mechanical purchase list** (this one) | **Where to buy** mechanical parts: bearings / fasteners / consumables, real Taobao links | Electronics |
> | [Hardware spec quick reference](硬件规格速查.md) | **Parameters**: interfaces, voltages, protocols, values the software side must match | Prices and shops |
> | [print/README](../print/README.md) | **Printing entry point**: choose version, material and quantity in the CAD repo | Purchasing |
>
> The mapping of part numbers to screws for assembly is in the [CAD repo](https://github.com/fanhao375/microduck-replica-cad#装配-bom).


> **Snapshot date: 2026-09-04.** Prices and sales numbers change and links may go dead; check prices yourself before ordering.
> For electronic and electrical parts (controller / camera / ToF / power / PCB / wiring), see the [Electronics purchase list](电控采购清单.md).
>
> Quantities are derived from mesh instance counts and hole features in the MJCF `robot_walk.xml`; **they are derived values, not official drawings**.

---

## 1. Bearings (14 in total, two sizes)

Quantities are counted directly from the mesh references in `robot_walk.xml`; the counts are identical across all six MJCF variants.
**The sizes come from measuring the mesh geometry, not from the file names**:

| Size | Qty | Measured (OD / bore / width) | Mesh |
|---|---|---|---|
| **Ø22 × 16 × 4** | **11** | 22.0 / **16.0** / 4.0 mm | `seeed_bearing__configuration__22x16x4` |
| **Ø15 × 10 × 3** | **3** | 15.0 / **10.0** / 3.0 mm | `seeed_bearing__configuration_default` |

| Shop | Description | Price | Link |
|---|---|---|---|
| **NBZH 永天轴承** (Yongtian Bearings, 16-year-old shop) | Stainless steel ultra-thin-wall `ET2216ZZ` / `MR16224` / `SET2216` / `DDA2216`, 16×22×4 | **¥2.2** | [taobao 539024647147](https://item.taobao.com/item.htm?id=539024647147) |
| **鑫燚轴承** (Xinyi Bearings, 7-year-old shop) | NSK miniature bearings, **one link has both 10×15×3 and 16×22×4** | **¥5** | [taobao 670727787832](https://item.taobao.com/item.htm?id=670727787832) |

> 💡 With the Xinyi listing you can buy both sizes from one link, which is convenient.

**What 机械行者Robo actually bought when building the Feetech version** (2026-09-16, works): 10×15×3 at [Taobao 963037239628](https://item.taobao.com/item.htm?id=963037239628&skuId=6069280211062), 16×22×4 at [Tmall 978199812185](https://detail.tmall.com/item.htm?id=978199812185&skuId=6245616343131). They are also in the [assembly BOM](https://github.com/fanhao375/microduck-replica-cad#装配-bom) of the drawings repo.

> ⚠️ **`bearing_roll` is not a bearing, and not a purchased part.** The MJCF also has a mesh that appears twice, called
> `bearing_roll`; measured, it is a **23 × 3 × 40 mm flat plate with a center hole of Ø≈18** (volume 625 mm³, fill ratio 23%),
> and it comes from the **same Onshape Part Studio** as `trunk_base` / `yaw2roll` / the shell
> (elementId `d6fcdccc8b25aaa256e7e213`), while the two real bearings are in a separate standard parts library with configuration strings.
> It is the **retaining cover** for the Ø22 bearing on the hip_roll axis; **print it, do not buy it**. See [Printed parts](#四打印件).

---

## 2. Fasteners (M2 system, about 325 pieces)

Across the whole robot, M2-class holes (Ø1.9–2.5 mm, wrap angle ≥300°) **total 237, weighted by usage in the assembly**:
60 on the servo bodies (15 × 4), 21 on standard parts such as bearings/PCB/battery, and about 156 on structural parts.
The list below is for 325 pieces, a **1.37×** margin over the 237 hole positions.

| Size | Suggested qty | Use |
|---|---|---|
| M2×4 socket head cap | 60 | Thin-wall positions |
| **M2×6 socket head cap** | **80** (main size) | |
| M2×8 socket head cap | 40 | Hole depth 3–5 mm |
| M2×12 socket head cap | 15 | A few deep holes |
| M2 nut | 50 | Where there is no tapped thread |
| **M2 heat-set insert** | **60** | Recommended for printed parts, much stronger than tapping directly |
| M2.5×6 | 20 | A few Ø2.7 hole positions |

See [Fastener reconstruction](紧固件反推.md) for the derivation.

### Screw assortment kits

| Shop | Description | Price | Sales | Link |
|---|---|---|---|---|
| **广州信邦电子** (Guangzhou Xinbang Electronics, 10-year-old shop, free shipping) | **600 pcs** boxed stainless steel countersunk/flat-head hex socket **M2/M2.5/M3** assortment, **wrench included** | **¥26.8** | 42 | [taobao 842110292995](https://item.taobao.com/item.htm?id=842110292995) |
| 宏顺通五金工厂店 (Hongshuntong Hardware factory shop, 8-year-old shop) | 600 pcs M2/M2.5/M3 countersunk hex socket + nuts + tools included | ¥23 | 2 | [taobao 842400332284](https://item.taobao.com/item.htm?id=842400332284) |
| 广州信邦电子 (Guangzhou Xinbang Electronics, 10-year-old shop, free shipping) | 304 stainless M2–M8 pan-head hex socket + nuts + washers kit | ¥19.8 | 71 | [taobao 888186264852](https://item.taobao.com/item.htm?id=888186264852) |

**What 机械行者Robo actually bought** (2026-09-16): M2×5 / M2×6 / M2.5×6 are all at [Tmall 637524754721](https://detail.tmall.com/item.htm?id=637524754721); choose the SKU by size.

> 💡 **Prefer kits that explicitly state they include M2.** Many "M2M3M4M5M6M8 complete set" titles mention M2, but the smallest is actually M3 —
> check the SKU before ordering. In this project **M2 is by far the main size**; M3 is basically unused.

### Heat-set inserts + press tips

| Shop | Description | Price | Sales | Link |
|---|---|---|---|---|
| **深圳市榕誉微电子** (Shenzhen Rongyu Microelectronics, 6-year-old shop) | **400 PCS M2 + M3** heat-set brass inserts, double knurled | **¥22** | 200+ | [taobao 1000673642588](https://item.taobao.com/item.htm?id=1000673642588) |
| 深圳市榕誉微电子 (Shenzhen Rongyu Microelectronics, 6-year-old shop) | 80/220 PCS M2–M6 heat-set brass inserts | ¥18 | 1000+ | [taobao 922318148975](https://item.taobao.com/item.htm?id=922318148975) |
| 天卓五金官方旗舰店 (Tianzhuo Hardware official flagship store, free shipping) | Tuba heat-set inserts M1–M8, sold individually by size | from ¥0.77 | 40k+ | [tmall 809364062256](https://detail.tmall.com/item.htm?id=809364062256) |

> ⚠️ **Do not forget the press tips.** Heat-set inserts must be pressed in with a **dedicated soldering iron press tip**; a normal soldering iron tip will not press them in straight, and they end up crooked.

| Shop | Description | Price | Sales | Link |
|---|---|---|---|---|
| **烙铁工具** (Soldering Iron Tools, 7-year-old shop) | 3D heat-set insert press tip kit M2–M8, fits **936 / T12 / T65** | **¥13** | 800+ | [taobao 902798112263](https://item.taobao.com/item.htm?id=902798112263) |
| 外茂优品 (Waimao Youpin, free shipping) | Similar M2–M8 press tip kit | ¥11.5 | 200+ | [taobao 966212633086](https://item.taobao.com/item.htm?id=966212633086) |

### Threadlocker (prevents loosening of metal-to-metal screw joints)

Medium-strength threadlocker is recommended on servo output shafts and metal-to-metal joints.

| Shop | Description | Price | Sales | Link |
|---|---|---|---|---|
| **LOCTITE 乐泰旗舰店** (LOCTITE flagship store) | Henkel Loctite **243** medium-strength removable threadlocker | **¥19.11** | 10k+ | [tmall 653848839737](https://detail.tmall.com/item.htm?id=653848839737) |
| LOCTITE 乐泰企业店 (LOCTITE business store) | 243 / 263 threadlocker | ¥18.4 | 700+ | [taobao 663963768247](https://item.taobao.com/item.htm?id=663963768247) |
| 工业胶厂家直销 (industrial adhesive factory direct, free shipping) | Loctite 243 / 242 / 263 | ¥16.8 | 600+ | [taobao 925965306702](https://item.taobao.com/item.htm?id=925965306702) |

> ⚠️ **Be careful with anything under ¥15.** Search results include "Loctite 243" at ¥8 or ¥10; the genuine product never sells that cheap.
> Stick to the official LOCTITE store or authorized dealers.

---

## 3. Consumables

| Material | Amount | Used for |
|---|---|---|
| **PLA / PETG** | about 300–500 g | Most structural parts |
| **TPU** | A small amount | `jaw_soft_软下巴` (soft jaw), `soft_mouth_top_软嘴顶部` (soft mouth top) — soft material suggested, judging from the names and use |

> Printing process and tolerance evaluation have not been done yet; see the risk list in [PROGRESS.md](../PROGRESS.md).
> **Simulation STL ≠ printable engineering part** — it only guarantees shape and inertia, with no fit tolerances, threaded holes or heat-set insert bosses.

---

## 4. Printed parts

**Always check the [CAD repo](https://github.com/fanhao375/microduck-replica-cad#装配-bom) for the latest models, materials and print quantities; do not order based on upstream simulation reference counts.** The mating parts differ between the two servo models; see the [printing entry point](../print/README.md) for details.

<details>
<summary>Historical upstream model counts and naming errata (for analysis only, not the current print list)</summary>


**30 types / 41 pieces.**

**In the old model, 9 meshes are referenced more than once:**

| Part | References in old model |
|---|---|
| `leg_腿部` (leg) | **×4** |
| `hip_l_髋部左` (hip left) | ×2 |
| `neck_颈部` (neck) | ×2 |
| `power_support_电源支架` (power support bracket) | ×2 |
| `sole_left_左脚底` (left sole) | ×2 |
| `sole_right_右脚底` (right sole) | ×2 |
| `upper_leg_rigidity_plate_上腿加固板` (upper leg stiffening plate) | ×2 |
| `yaw2roll_偏航转横滚` (yaw-to-roll) | ×2 |
| **`bearing_roll_横滚轴承压盖`** (roll bearing retaining cover) | **×2** ← see errata below |
| Remaining 21 types | ×1 each |

> ⚠️ **Errata (2026-09-04)**: `bearing_roll` was previously classified in this repo as "standard part - no printing needed"; **that was wrong**.
> Criteria: ① measured as a 23×3×40 mm flat plate with a center hole of Ø≈18, which is not the shape of any standard bearing (a real bearing is a body of revolution);
> ② it comes from the same Onshape Part Studio as `trunk_base` / `yaw2roll` / the shell;
> ③ in the assembly it shares a body and position with `yaw2roll`, and is a cover plate attached to its side.
> The Chinese translation "轴承滚轮" (bearing roller) was also wrong — it is neither a bearing nor a roller; it has been renamed "横滚轴承压盖" (roll bearing retaining cover).
> The printed part count was therefore corrected from 29 types / 39 pieces to **30 types / 41 pieces**.

⚠️ **Do not mix up left and right**: `upper_leg_left` and `upper_leg_right` are mirrored parts
(center of mass **±0.006766 m = ±6.77 mm**); you need to print both;
the same applies to `ankle_left`/`ankle_right`, `sole_left`/`sole_right` and `foot_left`/`foot_right`.

---

</details>

## 5. Not to be bought (in the official model but in other categories)

| Mesh | What it is | What to do |
|---|---|---|
| `xl330` ×15 | Servo | See [Actuator selection](执行器选型.md) |
| `np_f970` | NP-F battery (**actually F550**) | See the [Electronics purchase list](电控采购清单.md#五电源) |
| `elec_rpi_robot_hat_pcb` | HAT circuit board | Have it fabricated, see the [Electronics purchase list](电控采购清单.md#六两块-pcb) |
| `pcb__raspberry_pi_zero_2_w` | Controller board placeholder | Buy a Radxa Zero 3W |
| `lens` / `m12_lens_holder` | Lens and lens holder | ⚠️ Both come from the same Onshape Part Studio;<br>this repo classifies `lens` as a standard part and `m12_lens_holder` as a printed part; **this split is questionable** and awaits a physical re-check |
| `speaker` | Speaker | 5W, connects to the HAT's Wago terminal |

---

## Unverified items

- All prices, sales numbers, shop information and link validity (2026-09-04 snapshot)
- Screw lengths are estimated from hole depths and **are ranges, not measured values**; FDM print shrinkage also changes the actual hole diameter
  (Ø2.2 usually comes out 0.1–0.3 mm small)
- The TPU parts are judged from names and use; the official model does not specify materials
- Purchase/print classification of `lens` / `m12_lens_holder`
