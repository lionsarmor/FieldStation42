#!/bin/bash
sleep 5  # Optional, helps on slower boots
cd /mnt/fs42drive/FieldStation42 || exit 1
source env/bin/activate
DISPLAY=:0 
python3 field_player.py &
python3 fs42/change_channel.py &
python3 fs42/osd/main.py

