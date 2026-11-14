#!/bin/bash
# Modify kissqy's "一键系统镜像 R1" (one-click system image R1) into a card that also boots on V1.12 boards.
#   sudo bash kissqy-r1-v112.sh <microduck-zero3w-0.15.1-R1.img.xz> [--no-camera] [--no-tof] [--overlay i2c4-m0 ...]
#
# Why the change: R1 uses Armbian's bundled mainline U-Boot 2025.10 + DRAM init firmware v1.21,
# and our V1.12 board (AIC8800 Wi-Fi) can't boot with that; it only works after switching to Radxa's bootloader (see the README and the pitfall log).
#
# Only these few things change; everything else (his firmware, models, first-boot hotspot WiFi setup, account lockout, SSH keys generated on first boot) is kept as is:
#   1. Write idbloader.img / u-boot.itb from Radxa's u-boot-rk2410 at sectors 64 / 16384 (same version and sha256 as build-armbian-card.sh)
#   2. Write /boot/extlinux/extlinux.conf: Radxa U-Boot only reads this, not boot.scr. Overlays, fdt and kernel parameters
#      are all carried over from the image's own armbianEnv.txt, so his HAT audio, camera and NPU still work
#   3. Optional --overlay NAME: add more overlays, e.g. i2c4-m0 (I²C4 on pins 27/28 of the 40-pin header, where the IMU module is jumper-wired)
#   4. Optional --no-camera / --no-tof: don't autostart mediad / tofd. Without a camera or ToF they keep crashing and restarting,
#      and mediad rescans the GStreamer plugins on every restart, which can max out a core and heat the board until it throttles
#
# Note: after switching to Radxa's bootloader, editing armbianEnv.txt no longer takes effect; to add overlays later, edit extlinux.conf.
# This script only replaces the bootloader and boot config; it can't make his programs recognize the IMU module (R1 only recognizes the IMU board with ID 200 on the bus).
set -euo pipefail
export LC_ALL=C.UTF-8

R1_SHA=75da978b5d56acd9e4146256431732381de84523bb683e4ab7ac9f0580a7bce5   # checksum published on kissqy's release page
UBOOT_DEB_URL=https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/u-boot-rk2410_2017.09-64-39cd993_arm64.deb
UBOOT_DEB_SHA=fb319203ab7d568aac77505504c05698385aea8a0e8f895c226c6bc557a1bce7

XZ="${1:?用法: sudo bash $0 <microduck-zero3w-0.15.1-R1.img.xz> [--no-camera] [--no-tof] [--overlay NAME ...]}"
shift
NO_CAMERA=0; NO_TOF=0; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-camera) NO_CAMERA=1 ;;
    --no-tof) NO_TOF=1 ;;
    --overlay) EXTRA+=("${2:?--overlay 后面要跟名字，比如 i2c4-m0}"); shift ;;
    *) echo "不认识的参数：$1"; exit 1 ;;
  esac
  shift
done
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" = 0 ] || { echo "要 root：sudo bash $0 ..."; exit 1; }
[ -f "$XZ" ] || { echo "找不到 $XZ"; exit 1; }

echo "[1/7] 核对 R1 原包校验值"
GOT=$(sha256sum "$XZ" | cut -d' ' -f1)
[ "$GOT" = "$R1_SHA" ] || { echo "校验值不对：$GOT（应为 $R1_SHA）。别的版本先核对再改脚本。"; exit 1; }

OUT="${XZ%.img.xz}-V112.img"
WORK=$(mktemp -d /root/r1v112.XXXX); trap 'umount -q "$WORK/m" 2>/dev/null; rm -rf "$WORK"' EXIT

echo "[2/7] 瑞莎引导程序"
DEB="$HERE/$(basename "$UBOOT_DEB_URL")"
[ -f "$DEB" ] || curl -fL --retry 3 -o "$DEB" "$UBOOT_DEB_URL"
echo "$UBOOT_DEB_SHA  $DEB" | sha256sum -c - >/dev/null || { echo "u-boot 包校验失败"; exit 1; }
mkdir -p "$WORK/deb"; dpkg-deb -x "$DEB" "$WORK/deb"
UB="$WORK/deb/usr/lib/u-boot/radxa-zero3"; ls "$UB/idbloader.img" "$UB/u-boot.itb" >/dev/null

echo "[3/7] 解压镜像（放本地盘，/mnt 下 loop 挂不了）"
xz -dkc "$XZ" > "$WORK/card.img"

START=$(python3 - "$WORK/card.img" <<'PY'
import struct,sys
f=open(sys.argv[1],'rb'); f.seek(512); h=f.read(512)
elba=struct.unpack('<Q',h[72:80])[0]; esz=struct.unpack('<I',h[84:88])[0]
f.seek(elba*512); e=f.read(esz); print(struct.unpack('<Q',e[32:40])[0])
PY
)
# The bootloader must sit in sectors 64..32767; the partition must start at 32768 or later
[ "$START" -ge 32768 ] || { echo "根分区从扇区 $START 开始，放不下瑞莎引导，停止"; exit 1; }

echo "[4/7] 写入引导程序（idbloader @64，u-boot.itb @16384）"
dd if="$UB/idbloader.img" of="$WORK/card.img" bs=512 seek=64 conv=notrunc status=none
dd if="$UB/u-boot.itb"   of="$WORK/card.img" bs=512 seek=16384 conv=notrunc status=none

UUID=$(python3 - "$WORK/card.img" "$START" <<'PY'
import sys,uuid
f=open(sys.argv[1],'rb'); f.seek(int(sys.argv[2])*512+1024); sb=f.read(1024); print(uuid.UUID(bytes=sb[104:120]))
PY
)
echo "      根分区起始扇区 $START，UUID $UUID"
mkdir -p "$WORK/m"; mount -o loop,offset=$((START*512)) "$WORK/card.img" "$WORK/m"; R="$WORK/m"
KVER=$(ls "$R/lib/modules" | head -1)
ENV="$R/boot/armbianEnv.txt"
val(){ sed -n "s/^$1=//p" "$ENV" | tr -d '\r' | tail -1; }
PREFIX=$(val overlay_prefix); FDT=$(val fdtfile); ARGS=$(val extraargs)
read -r -a OVERLAYS <<< "$(val overlays)"
for o in "${EXTRA[@]}"; do [[ " ${OVERLAYS[*]} " == *" $o "* ]] || OVERLAYS+=("$o"); done

echo "[5/7] extlinux（瑞莎 U-Boot 认这个，不认 boot.scr）"
FILES=()
for o in "${OVERLAYS[@]}"; do
  f="/boot/dtb/rockchip/overlay/${PREFIX}-${o}.dtbo"
  [ -f "$R$f" ] || { echo "镜像里没有 overlay 文件 $f，停止"; exit 1; }
  FILES+=("$f")
done
[ -f "$R/boot/vmlinuz-$KVER" ] && [ -f "$R/boot/initrd.img-$KVER" ] && [ -f "$R/boot/dtb/$FDT" ] \
  || { echo "内核、initrd 或 $FDT 缺失，停止"; exit 1; }
mkdir -p "$R/boot/extlinux"
cat > "$R/boot/extlinux/extlinux.conf" <<CONF
default armbian
timeout 3
menu title kissqy R1 (Radxa U-Boot)

label armbian
  linux /boot/vmlinuz-$KVER
  initrd /boot/initrd.img-$KVER
  fdt /boot/dtb/$FDT
  fdtoverlays ${FILES[*]}
  append root=UUID=$UUID rootwait rw console=tty1 consoleblank=0 ${ARGS}
CONF
# armbianEnv only syncs the overlay list, for scripts that read it later; what actually takes effect is extlinux
sed -i "s/^overlays=.*/overlays=${OVERLAYS[*]}/" "$ENV"

echo "[6/7] 服务"
off(){ rm -f "$R/etc/systemd/system/multi-user.target.wants/$1.service"; echo "      $1 不再开机自启（以后接上：sudo systemctl enable --now $1）"; }
[ "$NO_CAMERA" = 1 ] && off mediad
[ "$NO_TOF" = 1 ] && off tofd
cat > "$R/etc/microduck-v112-image.txt" <<NOTE
本卡由 microduck-replica tools/radxa/kissqy-r1-v112.sh 从 kissqy Public Image R1 改出（$(date -u +%F)）。
原包 sha256: $R1_SHA
改动：瑞莎 u-boot-rk2410 2017.09-64 引导；/boot/extlinux/extlinux.conf；overlays=${OVERLAYS[*]}；no-camera=$NO_CAMERA no-tof=$NO_TOF
换引导后改 overlay 要改 extlinux.conf，armbianEnv.txt 不再生效。
NOTE

echo "[7/7] 收尾"
umount "$WORK/m"
mv "$WORK/card.img" "$OUT"
echo "做好了：$OUT"
sha256sum "$OUT"
