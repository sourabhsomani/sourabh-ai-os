#!/usr/bin/env bash
# Build a bootable Sourabh OS ISO with Debian live-build.
# Run on Debian/Ubuntu as root (sudo iso/build.sh), or use iso/build-in-docker.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-/var/tmp/sourabhos-build}"   # must be a Linux filesystem (not NTFS)
OUT="${OUT:-$ROOT/out}"
DIST="${DIST:-trixie}"
MIRROR="${MIRROR:-http://deb.debian.org/debian/}"
# AI options
PRELOAD_MODELS="${PRELOAD_MODELS-qwen2.5:0.5b}"   # space-separated; "" for none
NVIDIA="${NVIDIA:-0}"                              # 1 = add NVIDIA driver for GPU inference
AI_SERVER="${AI_SERVER:-0}"                        # 1 = serve the AI API to your network (port 11434)
CHROME="${CHROME:-1}"                              # 1 = include Google Chrome
# no "contrib": its firmware "installer" packages download from GitHub at build
# time and break the build on networks that can't reach it (VMs don't need them)
AREAS="main non-free-firmware"
if [ "$NVIDIA" = 1 ]; then AREAS="$AREAS non-free"; fi

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
command -v lb >/dev/null || { echo "install live-build: apt-get install live-build"; exit 1; }

echo ">> preparing $WORK"
if [ -d "$WORK" ]; then (cd "$WORK" && lb clean --purge >/dev/null 2>&1 || true); fi
rm -rf "$WORK"
mkdir -p "$WORK" "$OUT"
cd "$WORK"

lb config \
    --distribution "$DIST" \
    --architectures amd64 \
    --archive-areas "$AREAS" \
    --mirror-bootstrap "$MIRROR" \
    --mirror-chroot "$MIRROR" \
    --mirror-binary "$MIRROR" \
    --binary-images iso-hybrid \
    --debian-installer live \
    --debian-installer-gui false \
    --iso-application "Sourabh OS" \
    --iso-publisher "Sourabh OS" \
    --iso-volume "SOURABHOS" \
    --memtest none \
    --bootappend-live "boot=live components quiet username=sourabh hostname=sourabh-os splash" \
    --bootappend-install "auto=false priority=high"

echo ">> copying Sourabh OS config and code"
cp -a "$ROOT/iso/config/." config/
mkdir -p config/includes.chroot/opt/sourabhos
cp -a "$ROOT/sourabhos" "$ROOT/programs" "$ROOT/ai-examples" config/includes.chroot/opt/sourabhos/
find config/includes.chroot/opt -name '__pycache__' -prune -exec rm -rf {} +
chmod +x config/hooks/normal/*.hook.chroot config/includes.chroot/usr/local/bin/* config/includes.chroot/usr/local/sbin/*

echo ">> options: models='$PRELOAD_MODELS' nvidia=$NVIDIA ai_server=$AI_SERVER chrome=$CHROME"
mkdir -p config/includes.chroot/etc/sourabhos
echo "$PRELOAD_MODELS" | tr ' ' '\n' | sed '/^$/d' > config/includes.chroot/etc/sourabhos/preload-models
if [ "$CHROME" = 1 ]; then touch config/includes.chroot/etc/sourabhos/with-chrome; fi
if [ "$NVIDIA" = 1 ]; then
    printf 'linux-headers-amd64\nnvidia-driver\nfirmware-misc-nonfree\nnvidia-smi\n' \
        > config/package-lists/nvidia.list.chroot
fi
if [ "$AI_SERVER" = 1 ]; then
    mkdir -p config/includes.chroot/etc/systemd/system/ollama.service.d
    printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' \
        > config/includes.chroot/etc/systemd/system/ollama.service.d/listen.conf
fi

echo ">> branding the live boot menu"
mkdir -p config/bootloaders
for b in grub-pc grub-efi isolinux syslinux syslinux_common; do
    src="/usr/share/live/build/bootloaders/$b"
    if [ -d "$src" ] && [ ! -e "config/bootloaders/$b" ]; then cp -a "$src" config/bootloaders/; fi
done
find config/bootloaders -name 'splash.png' -exec cp "$ROOT/iso/branding/splash.png" {} \;
# ISOLINUX ships an SVG splash: swap it for our PNG
find config/bootloaders -name 'splash.svg' | while read -r svg; do
    rm -f "$svg"; cp "$ROOT/iso/branding/splash.png" "$(dirname "$svg")/splash.png"
done
grep -rlI -e 'Live system' -e 'Debian GNU/Linux' config/bootloaders 2>/dev/null | xargs -r sed -i \
    -e 's/Live system/Sourabh OS/g' -e 's/Debian GNU\/Linux/Sourabh OS/g'

echo ">> building (this takes 15-40 minutes)"
lb build 2>&1 | tee "$OUT/build.log"

ISO="$(ls -1 "$WORK"/*.iso | head -n1)"
cp "$ISO" "$OUT/sourabhos-amd64.iso"
( cd "$OUT" && sha256sum sourabhos-amd64.iso > sourabhos-amd64.iso.sha256 )
echo ">> done: $OUT/sourabhos-amd64.iso ($(du -h "$OUT/sourabhos-amd64.iso" | cut -f1))"
