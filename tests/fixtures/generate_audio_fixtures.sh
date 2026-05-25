#!/usr/bin/env bash
# Generate small test audio files. Re-run safe (overwrites).
# Requires: ffmpeg in PATH.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)/audio"
mkdir -p "$DIR"

ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=440:duration=2" \
  -metadata title="Test Title" \
  -metadata artist="Test Artist" \
  -metadata album="Test Album" \
  -ab 128k "$DIR/test_tagged.mp3"

ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=523:duration=2" \
  -ab 128k "$DIR/test_untagged.mp3"

echo "Generated fixtures in $DIR"
ls -la "$DIR"
