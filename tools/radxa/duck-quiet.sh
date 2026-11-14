#!/bin/bash
# Cool down the board: see who is generating heat, record temperature curves, turn off services not needed for walking (one-click restore).
#   sudo bash duck-quiet.sh status                 # current temperature, frequency, top CPU processes, status of related services
#   sudo bash duck-quiet.sh measure 120 idle       # record every 5 s for 120 s, with label "idle"
#   sudo bash duck-quiet.sh quiet                  # turn off the services in the QUIET list below that are enabled at boot, and record their original state
#   sudo bash duck-quiet.sh restore                # restore the turned-off services exactly as recorded
#
# Why this exists: on 2026-10-12, after installing the full kissqy stack on the first unit, the board ran at 85–92°C with the CPU stuck at the lowest step, 408 MHz,
# so the web joystick couldn't respond in time. With no camera attached, mediad kept crashing and restarting, and GStreamer scanning maxed out a core.
# Walking only needs robotd (control), padd and the web gamepad (joystick), SSH, and networking.
# Logs: /var/log/duck-quiet/<date>.log (by category and level); temperature curves: /var/log/duck-quiet/thermal-<time>-<label>.csv
set -euo pipefail
export LC_ALL=C.UTF-8

# Not needed for walking. Bluetooth (bluetooth.service) isn't in the default list: it'll be needed for a Bluetooth gamepad later.
QUIET=(mediad tofd btd configd gamesir-xboxd updaterd robot-boot-check.timer)
STATE=/var/lib/duck-quiet/disabled.txt
LOGDIR=/var/log/duck-quiet
mkdir -p "$LOGDIR" "$(dirname "$STATE")"
LOG="$LOGDIR/$(date +%F).log"
log(){ printf '%s [%s][%s] %s\n' "$(date '+%F %T')" "$1" "$2" "$3" | tee -a "$LOG" >&2; }
[ "$(id -u)" = 0 ] || { echo "要 root：sudo bash $0 ..."; exit 1; }

temp_c(){ awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp; }
freq_mhz(){ awk '{printf "%d", $1/1000}' /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq; }
unit_name(){ case "$1" in *.*) echo "$1" ;; *) echo "$1.service" ;; esac; }

status(){
  log 温度 INFO "CPU $(temp_c)°C，频率 $(freq_mhz) MHz（408 = 最低档，在降频）"
  log 负载 INFO "1/5/15 分钟负载 $(cut -d' ' -f1-3 /proc/loadavg)"
  # Sample twice and take the second; the first CPU usage reading is the average since boot
  top -b -n 2 -d 2 -o %CPU | awk '/^top/{n++} n==2' | sed -n '7,14p' | while read -r line; do log 进程 INFO "$line"; done
  for u in robotd padd microduck-webpad.socket "${QUIET[@]}" bluetooth; do
    n=$(unit_name "$u")
    # is-enabled also returns non-zero for disabled, so || can't be used as a fallback, otherwise an extra 「无」 (none) would follow 「disabled」
    en=$(systemctl is-enabled "$n" 2>/dev/null || true); [ -n "$en" ] || en=无
    log 服务 INFO "$(printf '%-24s 开机自启=%-8s 现在=%s' "$n" "$en" "$(systemctl is-active "$n" 2>/dev/null || true)")"
  done
}

measure(){
  local secs="${1:-120}" label="${2:-未命名}" out
  out="$LOGDIR/thermal-$(date +%Y%m%d-%H%M%S)-${label}.csv"
  echo "秒,温度C,频率MHz,负载1分钟" > "$out"
  log 测温 INFO "开始：$label，$secs 秒，每 5 秒一次 → $out"
  local t=0
  while [ "$t" -le "$secs" ]; do
    echo "$t,$(temp_c),$(freq_mhz),$(cut -d' ' -f1 /proc/loadavg)" >> "$out"
    sleep 5; t=$((t + 5))
  done
  awk -F, 'NR>1 {n++; s+=$2; if($2>mx)mx=$2; if(mn==""||$2<mn)mn=$2; if($3<=408)low++}
           END {printf "温度 最低 %.1f / 平均 %.1f / 最高 %.1f °C；%d/%d 次在 408 MHz\n", mn, s/n, mx, low, n}' "$out" \
    | while read -r line; do log 测温 INFO "$label：$line"; done
}

quiet(){
  [ -f "$STATE" ] && { log 服务 WARN "已经有关闭记录 $STATE，先 restore 再 quiet，免得记录被覆盖"; exit 1; }
  : > "$STATE"
  for u in "${QUIET[@]}"; do
    n=$(unit_name "$u")
    if [ "$(systemctl is-enabled "$n" 2>/dev/null || true)" = enabled ]; then
      systemctl disable --now "$n" >/dev/null 2>&1 && { echo "$n" >> "$STATE"; log 服务 INFO "已关：$n"; } \
        || log 服务 ERROR "关不掉：$n"
    else
      systemctl stop "$n" >/dev/null 2>&1 || true
      log 服务 INFO "本来就没开机自启，只停一下：$n"
    fi
  done
  log 服务 INFO "记录在 $STATE；恢复：sudo bash $0 restore"
}

restore(){
  [ -f "$STATE" ] || { log 服务 WARN "没有关闭记录，什么都不用恢复"; exit 0; }
  while read -r n; do
    [ -n "$n" ] || continue
    systemctl enable --now "$n" >/dev/null 2>&1 && log 服务 INFO "已恢复：$n" || log 服务 ERROR "恢复失败：$n"
  done < "$STATE"
  mv "$STATE" "$STATE.restored-$(date +%Y%m%d-%H%M%S)"
}

case "${1:-status}" in
  status) status ;;
  measure) measure "${2:-120}" "${3:-未命名}" ;;
  quiet) quiet ;;
  restore) restore ;;
  *) echo "用法：sudo bash $0 status | measure [秒] [标签] | quiet | restore"; exit 1 ;;
esac
