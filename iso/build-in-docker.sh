#!/usr/bin/env bash
# Build the ISO inside Docker (works on any Linux, macOS, or Windows+WSL2).
set -euo pipefail
cd "$(dirname "$0")/.."
docker info >/dev/null 2>&1 || { echo "ERROR: Docker is not running. Start Docker, then run this again."; exit 1; }
docker build -t sourabhos-builder iso
docker run --rm --privileged \
    -e PRELOAD_MODELS="${PRELOAD_MODELS-qwen2.5:0.5b}" -e NVIDIA="${NVIDIA:-0}" -e AI_SERVER="${AI_SERVER:-0}" -e CHROME="${CHROME:-1}" \
    -v "$PWD":/src sourabhos-builder
[ -f out/sourabhos-amd64.iso ] || { echo "ERROR: ISO was not created, see out/build.log"; exit 1; }
echo "ISO ready: $PWD/out/sourabhos-amd64.iso"
