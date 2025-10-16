#!/usr/bin/env bash
set -euo pipefail

echo "[build] apt-get update"
apt-get update

echo "[build] install ffmpeg"
DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg

echo "[build] python deps"
pip install --upgrade pip
pip install -r requirements.txt

echo "[build] ffmpeg version:"
ffmpeg -version | head -n1 || true