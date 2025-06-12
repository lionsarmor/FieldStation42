#!/bin/bash
set -e

# Optional delay before startup
sleep 5

cd /mnt/fs42drive/FieldStation42 || { echo "Could not cd to FieldStation42"; exit 1; }
source env/bin/activate

export DISPLAY=:0
export XAUTHORITY=/home/roddy/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1000

########################################
# 3. Start FieldStation42 Components
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
# 4. Keep Script Running
########################################

echo "[FS42] All systems launched. Waiting to keep session alive..."
wait


