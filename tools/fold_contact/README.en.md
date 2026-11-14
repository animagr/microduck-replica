# fold_contact · At what angle each leg joint gets blocked by another part

**English** · [简体中文](README.md)

Zero-position calibration wants to use the "tucked" pose as its mechanical reference (holding the robot in the air and straightening it by hand, an error of one or two degrees will make it fall). For that, we first need to know: in the tucked pose, what blocks each joint, and at what angle it stops. This script computes that using the official simulation model.

**The final approach** (the "官方折叠（头颈摆正）" (official fold, head and neck straightened) reference in the debug console [`tools/servo-web`](../servo-web/) since 0.14.0): pose the legs in the official FOLD; fold the knee until the ankle just touches the thigh servo (the contact point in row 2 of the table below); set hip pitch vertical with a square; set hip yaw / roll, ankle, head, and neck straight (0°); close the mouth; calibrate all 15 servos together, with the zero still at the official 2048.

```bash
pip install mujoco python-fcl numpy
python fold_contact.py --mjcf <microduck_rl>/src/mjlab_microduck/robot/microduck/robot_walk.xml [--json result.json]
```

- MuJoCo is used only for forward kinematics (where each part is). Whether parts collide is determined by **fcl with exact intersection on the original triangle meshes**: MuJoCo's own collision treats meshes as convex hulls, which are "fatter" than the real parts, so contact angles would come out too small
- The 20 geometry pairs that already interpenetrate at the zero position (legs straight) are treated as assembly relationships (servo mounted in a bracket, bearing seated in a housing) and excluded from the scan
- The scan step is 0.25°; after contact is found, it bisects down to 0.05°

## Results (official original XL330 geometry, 2026-09-22, microduck_rl d424a0c)

Angles follow the model's conventions; the table lists the left leg. For the right leg, the knee and ankle values are the same with the opposite sign; **hip pitch is asymmetric** (the left and right shells differ), so both sides are listed.

| Joint · condition | Contact angle | What blocks what |
|---|---|---|
| Knee in the folding direction, hip 0°, ankle 0° | **±70.7°** | Sole hits the hip roll bracket |
| Knee in the folding direction, hip ±90° (official FOLD hip), ankle 0° | **±89.6°** | Ankle hits the servo on the thigh |
| Hip pitch in the folding direction, knee fully folded | Left **+126.0°**, right **−122.9°** | Ankle hits the torso shell |
| Ankle, after knee and hip are both fully folded | Only **+0.4 to −19.8°** of motion left | One end hits the shell, the other hits the thigh |
| Neck pitch in the official FOLD direction, legs folded | **+66.6°** (same for head pitch 0° and 57°) | The servo on the neck hits the torso shell |

The three official poses (`scene.xml` keyframes):

| Pose | Do parts press into each other? |
|---|---|
| STAND | No |
| SIT | No |
| FOLD (hip, knee ±90°) | **Yes**: the ankle presses into the thigh servo by about 0.36° (official knee 1.57 rad = 89.95°, contact at 89.59°). The FOLD knee is almost exactly the contact point; when the debug console sends the fold pose, the knee is folded only to 88° |

The FOLD neck / head pitch is 57° (1 rad), which is not a contact point: the neck has to turn to **66.6°** before it hits a part, and at 57° there is free space on both sides, so it cannot be posed accurately by eye. That is why, when the debug console uses the fold as the calibration reference, the head and neck are set straight (0°) instead.

During calibration the knee target is computed from the official 1.57 rad, but the pose actually reached is the contact point at 89.59°, so the zero is off by about 0.36° (4 steps), which is negligible.

## What this means for "using the tucked pose as the calibration reference"

1. **The joints are blocked by the feet and ankles**, not by each joint's own limit. So where each joint stops depends on the angles of the other joints: for the same "knee fully folded", it stops at 70.7° with the hip at 0°, and at 89.6° with the hip at 90°.
2. **The ankle is not constrained in the tucked pose**; it still has about 20° of play, so the tucked pose cannot be used to calibrate the ankle. Hip yaw / roll and the head are unconstrained to begin with.
3. If you really want to calibrate the hip and knee using the tucked pose, the **posing procedure has to be fixed** (first set the hip to a given angle, push the ankle in a given direction, then fold the knee), and the angles must be the values computed with that same procedure.
4. **These are the original XL330 geometries**. The Feetech version modified 8 parts that mate with the servo horns, so the contact angles will change: either export an STL for each link of the Feetech assembly at the zero position and run this again, or measure in SolidWorks using the same posing procedure.
5. A more robust route is a **calibration jig**: print a few clamps that fit between thigh, shank, and foot to hold the joints at well-defined angles (for example, straight at the zero position, sole vertical). This is better defined than "fully tucked" and consistent between left and right.

The debug console (`tools/servo-web`, since 0.13.0) can overlay the official poses in 3D and list, joint by joint, how many degrees "actual − official" differs, which shows how far the current zero is off; since 0.15.0 it can also overlay the "校准用折叠" (calibration fold) pose (legs in the official fold, head and neck straight), which is exactly the pose to hold during calibration.
