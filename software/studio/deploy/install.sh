#!/bin/sh
# Install Studio's root helper (including the fixed imu-recalibrate session verb) + robotd's protective drop-in + one sudoers line.
# Usage (on the duck, in the deploy directory): sudo sh install.sh [user running Studio, default radxa]
# Does not restart robotd and does not touch /dev/ttyS2. See INSTALL.md for details.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
user=${1:-radxa}

[ "$(id -u)" -eq 0 ] || { echo "要 root：sudo sh install.sh [用户]" >&2; exit 1; }
case $user in
    *[!a-z0-9_-]*|"") echo "用户名只能是小写字母、数字、_、-：$user" >&2; exit 1 ;;
esac
id "$user" >/dev/null 2>&1 || { echo "没有用户 $user" >&2; exit 1; }
[ -f /etc/systemd/system/robotd.service ] || echo "提醒：/etc/systemd/system/robotd.service 不在，drop-in 装了也没对象" >&2

# 1. Helper: root:root 0755, every level on its path writable only by root
install -o root -g root -m 0755 "$here/microduck-helper" /usr/local/sbin/microduck-helper
install -d -o root -g root -m 0755 /var/lib/microduck-helper /var/lib/microduck-helper/imu-recalibrate
for d in /usr /usr/local /usr/local/sbin; do
    if [ "$(stat -c %u "$d")" != 0 ]; then
        echo "警告：$d 的属主不是 root，小助手可能被换掉" >&2
    fi
    if [ -n "$(find "$d" -maxdepth 0 -perm /022 2>/dev/null)" ]; then
        echo "警告：$d 组或其他人可写，小助手可能被换掉" >&2
    fi
done

# 2. robotd's protective drop-in (step 1 only has the Condition flag; the Environment line is enabled manually after the step 3 acceptance check)
install -d -o root -g root -m 0755 /etc/systemd/system/robotd.service.d
install -o root -g root -m 0644 "$here/zzzz-studio-bus.conf" /etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf
systemctl daemon-reload

# 3. sudoers: only allow the helper's one full path; validate with visudo -cf before installing
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
{
    echo "# 由 Microduck Studio deploy/install.sh 写入；只放行 root 小助手。见 deploy/INSTALL.md"
    echo "$user ALL=(root) NOPASSWD: /usr/local/sbin/microduck-helper"
} >"$tmp"
visudo -cf "$tmp" >/dev/null
install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/microduck-studio

# 4. Check
echo "--- 核对 ---"
systemctl show robotd -p DropInPaths
ls -l /usr/local/sbin/microduck-helper /etc/sudoers.d/microduck-studio /etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf
echo "用 $user 试：echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-nope ; echo \$?   （应该是 2：动词不认识）"
echo "装好了。robotd 没重启。"
