#!/bin/bash
# add_web_channel.sh
# Creates a new web streaming channel configuration with location awareness
set -e

# ---------------------
# Dependency Check
# ---------------------
REQUIRED_CMDS=("jq" "curl" "chromium-browser" "ffmpeg" "Xvfb" "python3" "wmctrl")
for cmd in "${REQUIRED_CMDS[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] Required command '$cmd' is not installed or not in PATH."
    echo "Please install it before running this script."
    exit 1
  fi
done

# ---------------------
# Usage and Args
# ---------------------
usage() {
  echo "Usage: $0 <URL> <ChannelName> <ChannelNumber> [--force]"
  echo "Example: $0 \"https://weatherstar.netbymatt.com\" Weather 38"
  exit 1
}

if [[ $# -lt 3 ]]; then
  usage
fi

URL="$1"
CHANNEL_NAME="$2"
CHANNEL_NUMBER="$3"
FORCE=false
if [[ "$4" == "--force" ]]; then
  FORCE=true
fi

# Sanitize channel name for file/URL use
CHANNEL_ID=$(echo "$CHANNEL_NAME" | tr '[:upper:] ' '[:lower:]_' | tr -cd 'a-z0-9_')

# Paths
CONF_DIR="../confs"
HLS_DIR="../hls/${CHANNEL_ID}"
CONF_FILE="${CONF_DIR}/web_${CHANNEL_ID}.json"
URL_STORE_DIR="./web_urls"
URL_STORE_FILE="${URL_STORE_DIR}/${CHANNEL_ID}.json"

# Create necessary directories
mkdir -p "$CONF_DIR"
mkdir -p "$HLS_DIR"
mkdir -p "$URL_STORE_DIR"

# Check if config already exists
if [[ -f "$CONF_FILE" && "$FORCE" == false ]]; then
  echo "[ERROR] Configuration file '$CONF_FILE' already exists. Use --force to overwrite."
  exit 1
fi

# ---------------------
# Get Location (lat/lon)
# ---------------------
echo "[INFO] Retrieving location data..."
LOCATION_JSON=$(curl -s https://ipinfo.io/json)
if [[ -z "$LOCATION_JSON" ]]; then
  echo "[WARNING] Could not retrieve location data. Proceeding without location."
  LAT="null"
  LON="null"
else
  LOC=$(echo "$LOCATION_JSON" | jq -r '.loc' || echo "")
  if [[ "$LOC" == "" || "$LOC" == "null" ]]; then
    echo "[WARNING] Location data not found in response."
    LAT="null"
    LON="null"
  else
    LAT=$(echo "$LOC" | cut -d',' -f1)
    LON=$(echo "$LOC" | cut -d',' -f2)
  fi
fi

# ---------------------
# Write Full Channel Config
# ---------------------
cat > "$CONF_FILE" << EOF
{
  "station_conf": {
    "network_name": "$CHANNEL_NAME",
    "network_type": "streaming",
    "channel_number": $CHANNEL_NUMBER,
    "runtime_dir": "runtime/${CHANNEL_ID}",
    "content_dir": "catalog/${CHANNEL_ID}_content",
    "catalog_path": "catalog/${CHANNEL_ID}.bin",
    "schedule_path": "runtime/${CHANNEL_ID}_schedule.bin",
    "network_long_name": "${CHANNEL_NAME} Channel",
    "streams": [
      {
        "url": "http://localhost:8090/${CHANNEL_ID}/index.m3u8",
        "duration": 36000
      }
    ]
  }
}
EOF

# ---------------------
# Write URL Info for page_stream/start_web_stream.sh
# ---------------------
cat > "$URL_STORE_FILE" << EOF
{
  "channel_id": "$CHANNEL_ID",
  "channel_name": "$CHANNEL_NAME",
  "source_url": "$URL",
  "location": {
    "lat": "$LAT",
    "lon": "$LON"
  }
}
EOF

# ---------------------
# Final Output
# ---------------------
echo "[SUCCESS] Configuration file created at: $CONF_FILE"
echo "[INFO] HLS output will be saved to: $HLS_DIR"
echo "[INFO] Web stream URL stored at: $URL_STORE_FILE"
echo "[INFO] Use start_web_stream.sh \"$CHANNEL_NAME\" to launch the stream."

