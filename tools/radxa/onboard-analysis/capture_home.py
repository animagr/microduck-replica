"""Runs on the board: from the most recent recording, take the joint angles and IMU gravity while the duck stands still at HOME (averaged), save as JSON, and hand it to sim_home_tilt.py.
Usage: python3 capture_home.py [output file]   (default home-capture.json; takes the last 100 frames with policy=held)
Prerequisites: duck_rec.py is recording; the duck stands at HOME on flat ground, hands off, still for at least 3 seconds."""
import json, glob, math, sys
out = sys.argv[1] if len(sys.argv) > 1 else 'home-capture.json'
R = []
for l in open(sorted(glob.glob('/home/duck/r17/rec/run-*.jsonl'))[-1], errors='replace'):
    try: R.append(json.loads(l))
    except ValueError: pass
H = [r for r in R if r.get('policy') == 'held'][-100:]
if len(H) < 50: sys.exit('站 HOME 的帧不够（要 ≥50 帧），先按 Start 站起来、静止几秒')
gy = max(math.sqrt(sum(x * x for x in r['imu']['gyro'])) for r in H)
if gy > 0.2: print('警告：这段里机身在动（角速度最大 %.2f rad/s），结果不可靠' % gy)
d = {'joints15': [sum(r['joints'][j] for r in H) / len(H) for j in range(15)],
     'gravity': [sum(r['safety']['gravity'][k] for r in H) / len(H) for k in range(3)],
     'frames': len(H), 'span_s': H[-1]['t'] - H[0]['t'], 'gyro_max': gy}
json.dump(d, open(out, 'w'))
print('已存', out, '：%d 帧，%.1f s' % (len(H), d['span_s']))
