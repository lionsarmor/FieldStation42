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
# 1. Start WeatherStar 4000+ Web Server
########################################

cd ws4kp || { echo "Missing ws4kp directory"; exit 1; }

if ! lsof -i:8080 > /dev/null; then
    echo "[WS4KP] Starting WeatherStar 4000+ server..."
    nohup node index.mjs > ../weatherstar.log 2>&1 &
    sleep 2
else
    echo "[WS4KP] Server already running on port 8080."
fi

cd ..

########################################
# 2. Start weatherstar-headless Docker container
########################################

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^weatherstar$"; then
    echo "[DOCKER] Starting weatherstar-headless container..."
    
    # Remove stopped container with same name if exists
    if docker ps -a --format '{{.Names}}' | grep -q "^weatherstar$"; then
        docker rm -f weatherstar > /dev/null
    fi

    docker run -d \
        --name weatherstar \
        --network=host \
        -v "$(pwd)/weather/output:/app/output" \
        weatherstar-headless
else
    echo "[DOCKER] weatherstar container already running."
fi

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


