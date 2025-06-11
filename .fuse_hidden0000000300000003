#!/bin/bash
sleep 5
cd /mnt/fs42drive/FieldStation42 || exit 1
source env/bin/activate

export DISPLAY=:0
export XAUTHORITY=/home/roddy/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1000  # Replace 1000 with your actual UID

# Start video player in background FIRST
python3 field_player.py &

# Wait a few seconds to ensure mpv window is up
sleep 3

# Launch channel changer
python3 fs42/change_channel.py &

# Launch OSD
python3 fs42/osd/main.py &

# Give it time to create window, then raise
sleep 2
wmctrl -r "FieldStationOSD" -b add,above
wmctrl -a "FieldStationOSD"

# Optional: wait forever to keep the script "alive"
wait

