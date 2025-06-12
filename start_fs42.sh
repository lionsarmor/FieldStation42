#!/bin/bash
set -e

########################################
# 0. Launch WeatherStar Web Stream
########################################

WEATHER_URL="https://weatherstar.netbymatt.com/?hazards-checkbox=true&current-weather-checkbox=true&latest-observations-checkbox=true&hourly-checkbox=true&hourly-graph-checkbox=true&travel-checkbox=true&regional-forecast-checkbox=true&local-forecast-checkbox=true&extended-forecast-checkbox=true&almanac-checkbox=true&spc-outlook-checkbox=true&radar-checkbox=true&settings-wide-checkbox=false&settings-kiosk-checkbox=true&settings-scanLines-checkbox=true&settings-speed-select=1.00&settings-units-select=us&latLonQuery=Rawlins%2C+WY&latLon=%7B%22lat%22%3A41.7890116%2C%22lon%22%3A-107.2304671%7D"

XVFB_DISPLAY=:99
WIDTH=1280
HEIGHT=720
FRAMERATE=30
HLS_DIR="/mnt/fs42drive/FieldStation42/hls/weather"
PORT=8090

# Create HLS output directory
mkdir -p "$HLS_DIR"

# Start virtual display
if ! pgrep Xvfb >/dev/null; then
    echo "[WEATHER] Launching Xvfb virtual display..."
    Xvfb $XVFB_DISPLAY -screen 0 ${WIDTH}x${HEIGHT}x24 &
    sleep 2
fi
export DISPLAY=$XVFB_DISPLAY

# Launch Chromium
echo "[WEATHER] Launching Chromium in kiosk mode..."
chromium-browser --no-sandbox --disable-gpu --kiosk "$WEATHER_URL" &
sleep 5  # Let Chromium load

# Start HLS stream
echo "[WEATHER] Starting ffmpeg HLS stream..."
ffmpeg -y -f x11grab -video_size ${WIDTH}x${HEIGHT} -framerate $FRAMERATE -i $DISPLAY \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -f hls -hls_time 2 -hls_list_size 5 -hls_flags delete_segments \
  "$HLS_DIR/index.m3u8" &

# Serve HLS stream
echo "[WEATHER] Starting local web server for HLS..."
cd /mnt/fs42drive/FieldStation42/hls && python3 -m http.server $PORT &

########################################
# 1. Delay to let everything initialize
########################################

sleep 5

cd /mnt/fs42drive/FieldStation42 || { echo "Could not cd to FieldStation42"; exit 1; }
source env/bin/activate

export DISPLAY=:0
export XAUTHORITY=/home/roddy/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1000

########################################
# 2. Start FieldStation42 Components
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
# 3. Keep Script Running
########################################

echo "[FS42] All systems launched. Waiting to keep session alive..."
wait

