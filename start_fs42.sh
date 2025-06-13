#!/bin/bash
# launch_fs42_with_web.sh
# Auto-launch all web channels, then FieldStation42 core

set -e

########################################
# 0. Environment Setup
########################################

cd /mnt/fs42drive/FieldStation42 || { echo "Could not cd to FieldStation42"; exit 1; }

# Activate Python virtual environment
source env/bin/activate

export DISPLAY=:0
export XAUTHORITY=/home/roddy/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1000

########################################
# 1. Launch All Web Channels
########################################

CONF_DIR="./confs"
echo "[FS42] Searching for web_* channel configs in $CONF_DIR..."

for conf in "$CONF_DIR"/web_*.json; do
  [[ -e "$conf" ]] || continue  # Skip if no match
  CHANNEL_ID=$(basename "$conf" | sed -E 's/^web_(.+)\.json$/\1/')
  CHANNEL_NAME=$(echo "$CHANNEL_ID" | tr '_' ' ')
  echo "[FS42] Launching web stream: $CHANNEL_NAME"
  ./page_stream/start_web_stream.sh "$CHANNEL_NAME" &
  sleep 1
done

########################################
# 2. Launch FieldStation42 Core
########################################

echo "[FS42] Launching FieldPlayer..."
python3 field_player.py &

sleep 3  # Let MPV initialize

echo "[FS42] Launching channel changer..."
python3 fs42/change_channel.py &

echo "[FS42] Launching OSD..."
python3 fs42/osd/main.py &

sleep 2

# Raise and focus the OSD window
wmctrl -r "FieldStationOSD" -b add,above || echo "[OSD] Failed to raise window"
wmctrl -a "FieldStationOSD" || echo "[OSD] Failed to focus window"

########################################
# 3. Wait Indefinitely
########################################

echo "[FS42] All systems launched. Waiting to keep session alive..."
wait

