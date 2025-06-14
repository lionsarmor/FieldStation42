#!/bin/bash
# start_web_stream.sh
# Launch Chromium + ffmpeg + Python HTTP to stream a webpage channel via HLS

set -euo pipefail

########################################
# 1. Validate Arguments
########################################

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <ChannelName>"
  exit 1
fi

CHANNEL_NAME="$1"
CHANNEL_ID=$(echo "$CHANNEL_NAME" | tr '[:upper:] ' '[:lower:]_' | tr -cd 'a-z0-9_')

########################################
# 2. Paths & Configs
########################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_FILE="$SCRIPT_DIR/../confs/web_${CHANNEL_ID}.json"
URL_FILE="$SCRIPT_DIR/web_urls/${CHANNEL_ID}.json"
HLS_DIR="$SCRIPT_DIR/../page_stream/hls/${CHANNEL_ID}"
PROFILE_DIR="/tmp/chrome_${CHANNEL_ID}_profile"

if [[ ! -f "$CONF_FILE" ]]; then
  echo "[ERROR] Missing config file: $CONF_FILE"
  exit 1
fi

if [[ ! -f "$URL_FILE" ]]; then
  echo "[ERROR] Missing URL metadata file: $URL_FILE"
  exit 1
fi

CHANNEL_NUM=$(jq -r '.station_conf.channel_number' "$CONF_FILE")
PORT=$((8000 + CHANNEL_NUM))
URL=$(jq -r '.source_url' "$URL_FILE")

if [[ -z "$URL" || "$URL" == "null" ]]; then
  echo "[ERROR] source_url missing or invalid in $URL_FILE"
  exit 1
fi

########################################
# 3. Prepare Environment
########################################

DISPLAY_NUM=$((100 + (CHANNEL_NUM % 50)))
XVFB_DISPLAY=":$DISPLAY_NUM"
LOCK_FILE="/tmp/.X${DISPLAY_NUM}-lock"

export DISPLAY=$XVFB_DISPLAY

WIDTH=1280
HEIGHT=1024
FRAMERATE=30

echo "[INFO] Channel: $CHANNEL_NAME"
echo "[INFO] URL: $URL"
echo "[INFO] Display: $XVFB_DISPLAY"
echo "[INFO] HLS directory: $HLS_DIR"
echo "[INFO] HTTP server port: $PORT"

# Check if display lock file exists
if [[ -e "$LOCK_FILE" ]]; then
  echo "[WARN] Removing stale X lock: $LOCK_FILE"
  rm -f "$LOCK_FILE"
fi

# Check if port is in use
if lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null; then
  echo "[ERROR] Port $PORT already in use. Cannot continue."
  exit 1
fi

########################################
# 4. Cleanup old processes & state
########################################

cleanup() {
  echo "[CLEANUP] Stopping processes..."
  kill "${CHROMIUM_PID:-}" "${FFMPEG_PID:-}" "${HTTP_PID:-}" "${XVFB_PID:-}" 2>/dev/null || true
  rm -rf "$PROFILE_DIR"
  echo "[CLEANUP] Done."
}

trap cleanup EXIT

pkill -f "chromium-browser.*$PROFILE_DIR" || true
pkill -f "ffmpeg.*$XVFB_DISPLAY" || true
pkill -f "python3 -m http.server $PORT" || true
pkill -f "Xvfb $XVFB_DISPLAY" || true

rm -rf "$PROFILE_DIR"
sleep 2

########################################
# 5. Start Xvfb
########################################

echo "[XVFB] Starting Xvfb on $XVFB_DISPLAY"
Xvfb "$XVFB_DISPLAY" -screen 0 "${WIDTH}x${HEIGHT}x24" &
XVFB_PID=$!
sleep 3

########################################
# 6. Start Chromium
########################################

echo "[CHROMIUM] Launching Chromium..."

chromium-browser \
  --no-sandbox \
  --disable-gpu \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --no-first-run \
  --kiosk \
  --start-fullscreen \
  --hide-scrollbars \
  --window-size="${WIDTH},${HEIGHT}" \
  --window-position=0,0 \
  --user-data-dir="$PROFILE_DIR" \
  "$URL" &
CHROMIUM_PID=$!

sleep 8  # Let Chromium fully load

########################################
# 7. Prepare HLS directory
########################################

mkdir -p "$HLS_DIR"

########################################
# 8. Start ffmpeg capture to HLS
########################################

echo "[FFMPEG] Starting capture to $HLS_DIR"

ffmpeg -y \
  -f x11grab -video_size "${WIDTH}x${HEIGHT}" -i "${XVFB_DISPLAY}" \
  -r "$FRAMERATE" \
  -codec:v libx264 -preset veryfast -tune zerolatency -b:v 2000k \
  -pix_fmt yuv420p \
  -f hls \
  -hls_time 4 \
  -hls_list_size 10 \
  -hls_flags program_date_time+append_list \
  -hls_segment_filename "$HLS_DIR/index%d.ts" \
  "$HLS_DIR/index.m3u8" &
FFMPEG_PID=$!

########################################
# 9. Start Python HTTP Server
########################################

echo "[HTTP] Serving HLS on port $PORT"
cd "$SCRIPT_DIR/../page_stream"
python3 -m http.server "$PORT" &
HTTP_PID=$!

########################################
# 10. Warm-Up Delay
########################################

echo "[INFO] Warming up stream for 10 seconds..."
sleep 10

########################################
# 11. Wait
########################################

wait

