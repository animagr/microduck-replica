"""Copy this boot's system journal to the card in real time, fsync every second (Armbian's /var/log is in RAM and lost when power is pulled).
Skips the IMU settling spam robotd prints every 20 ms at startup. Usage: python3 duck_journal.py output_file"""
import os, subprocess, sys, threading, time
out = sys.argv[1]
p = subprocess.Popen(['journalctl', '-b', '-f', '-n', 'all', '-o', 'short-precise', '--no-pager'],
                     stdout=subprocess.PIPE, text=True, errors='replace')
f = open(out, 'a'); lock = threading.Lock()
def syncer():
    while True:
        time.sleep(1)
        with lock:
            f.flush(); os.fsync(f.fileno())
threading.Thread(target=syncer, daemon=True).start()
for line in p.stdout:
    if 'settling' in line:
        continue
    with lock:
        f.write(line)
