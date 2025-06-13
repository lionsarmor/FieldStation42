#!/bin/bash
# start_web_stream.sh
# Launches Chromium & FFmpeg to stream a webpage channel defined by its config file

set -e

# ---------------------
# Dependency Check
# ---------------------
REQUIRED_CMDS=("jq" "curl" "chromium-browser" "ffmpeg" "Xvfb" "python3" "wmctrl")
for cmd in "${REQUIRED_CMDS[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] Required command '$cmd' is not installed or not in PATH."
    exit 1
  fi
done

# ---------------------
# Usage and Args
# ---------------------
usage() {
  echo "Usage: $0 <ChannelName>"
  echo "Example: $0 Weather"
  exit 1
}

if [[ $# -ne 1 ]]; then
  usage
fi

CHANNEL_NAME="$1"
CHANNEL_ID=$(echo "$CHANNEL_NAME" | tr '[:upper:] ' '[:lower:]_' | tr -cd 'a-z0-9_')

# ---------------------
# Set Paths Relative to This Script
# ---------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONF_FILE="$SCRIPT_DIR/../confs/web_${CHANNEL_ID}.json"
URL_FILE="$SCRIPT_DIR/web_urls/${CHANNEL_ID}.json"
HLS_DIR="$SCRIPT_DIR/../hls/${CHANNEL_ID}"
PORT=8090
XVFB_DISPLAY=:99
WIDTH=1280
HEIGHT=720
FRAMERATE=30

# ---------------------
# Validate Files
# ---------------------
if [[ ! -f "$CONF_FILE" ]]; then
  echo "[ERROR] Configuration file '$CONF_FILE' not found."
  exit 1
fi

if [[ ! -f "$URL_FILE" ]]; then
  echo "[ERROR] URL metadata file '$URL_FILE' not found."
  exit 1
fi

# ---------------------
# Load Source URL
# ---------------------
URL=$(jq -r '.source_url' "$URL_FILE")
if [[ -z "$URL" || "$URL" == "null" ]]; then
  echo "[ERROR] source_url not defined in $URL_FILE."
  exit 1
fi

# ---------------------
# Clean Chrome profile
# ---------------------
PROFILE_DIR="/tmp/chrome_${CHANNEL_ID}_profile"
rm -rf "$PROFILE_DIR"

mkdir -p "$HLS_DIR"

# ---------------------
# Start virtual display if needed
# ---------------------
if ! pgrep Xvfb >/dev/null; then
  echo "[INFO] Starting Xvfb virtual display on $XVFB_DISPLAY..."
  Xvfb $XVFB_DISPLAY -screen 0 ${WIDTH}x${HEIGHT}x24 &
  sleep 2
fi

export DISPLAY=$XVFB_DISPLAY

# ---------------------
# Launch Chromium in kiosk mode
# ---------------------
echo "[INFO] Launching Chromium in kiosk mode for URL: $URL"
chromium-browser "$URL" \
  --no-first-run \
  --no-default-browser-check \
  --disable-gpu \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --noerrdialogs \
  --disable-features=TranslateUI \
  --hide-scrollbars \
  --kiosk \
  --start-fullscreen \
  --window-position=0,0 \
  --window-size=${WIDTH},${HEIGHT} \
  --user-data-dir="$PROFILE_DIR" &

sleep 5

# ---------------------
# Start FFmpeg HLS stream
# ---------------------
echo "[INFO] Starting FFmpeg HLS streaming..."
ffmpeg -y -f x11grab -video_size ${WIDTH}x${HEIGHT} -framerate $FRAMERATE -i $DISPLAY \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -f hls -hls_time 2 -hls_list_size 5 -hls_flags delete_segments \
  "${HLS_DIR}/index.m3u8" &

# ---------------------
# Start local web server
# ---------------------
echo "[INFO] Starting local web server at port $PORT for HLS content..."
cd "$SCRIPT_DIR/../hls" && python3 -m http.server $PORT &

# ---------------------
# Stay alive
# ---------------------
echo "[INFO] Webpage streaming started for channel '$CHANNEL_NAME'. Press Ctrl+C to stop."
wait

