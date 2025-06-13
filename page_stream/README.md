🌐 FieldStation42 Web Page Channel Streaming

This module enables live webpage streaming inside your FieldStation42 cable box simulator. It allows you to treat any live or dynamic webpage — such as weather maps, dashboards, or streaming sites — as a simulated TV channel. Pages are streamed using a headless Chromium browser and FFmpeg, encoded into HLS format.
🧩 Features

    Converts live websites into TV-style channels

    Streams output to http://localhost:8090/<channel>/index.m3u8

    Integrates directly with FieldStation42’s channel switcher

    Auto-generates configuration files and uses location metadata

    Supports multiple simultaneous web streams

📁 File Overview
File	Purpose
add_web_channel.sh	Creates a persistent, location-aware config for a new webpage channel
start_web_stream.sh	Launches a virtual display, opens Chromium, and starts FFmpeg streaming
confs/web_*.json	Stores configuration for each web stream channel
hls/<channel>/	Temporary HLS output directory (auto-created)
✅ Requirements

Make sure the following are installed:

sudo apt update
sudo apt install -y jq curl chromium-browser ffmpeg xvfb python3 wmctrl

    ⚠️ Chromium must be launchable as chromium-browser. If you're on a distro that uses chromium, edit the script accordingly.

🚀 How to Use
🧱 Step 1: Add a New Web Channel

Use the add_web_channel.sh script to generate a new channel configuration file.

./add_web_channel.sh "<URL>" "<ChannelName>" <ChannelNumber> [--force]

    "<URL>" – Full webpage address to stream (must work in Chromium)

    "<ChannelName>" – Name for the channel (e.g., Weather)

    <ChannelNumber> – Channel number for FieldStation42

    --force – (Optional) Overwrites existing configuration if it exists

Example:

./add_web_channel.sh "https://weatherstar.netbymatt.com/?hazards-checkbox=true&...&latLon=%7B%22lat%22%3A41.7890116%2C%22lon%22%3A-107.2304671%7D" "Weather2" 99

✅ What happens:

    A config file is generated at: confs/web_weather2_channel.json

    Location is auto-detected via ipinfo.io (or embedded in the URL)

    The stream will be accessible at: http://localhost:8090/weather2/index.m3u8

▶️ Step 2: Start Streaming the Channel

./start_web_stream.sh "Weather2"

✅ This will:

    Open Chromium in kiosk mode with a virtual display (Xvfb)

    Capture the window output using FFmpeg

    Save the stream as HLS in: hls/weather2/index.m3u8

    Serve it at http://localhost:8090/weather2/index.m3u8 via python3 -m http.server

🔁 Step 3: Connect It to FieldStation42

After creating the channel and starting the stream, you must update FieldStation42:

    Rebuild the station catalog using your preferred tool or script
    (e.g., rebuild or update catalog/*.bin and runtime/*_schedule.bin as needed)

    Make sure your station_conf includes the new stream:

Example confs/web_weather2_channel.json:

{
  "station_conf": {
    "network_name": "Weather2",
    "network_type": "streaming",
    "channel_number": 99,
    "runtime_dir": "runtime/weather2",
    "content_dir": "catalog/weather2_content",
    "catalog_path": "catalog/weather2.bin",
    "schedule_path": "runtime/weather2_schedule.bin",
    "network_long_name": "Weather Web Stream",
    "streams": [
      {
        "url": "http://localhost:8090/weather2/index.m3u8",
        "duration": 36000
      }
    ],
    "source_url": "https://weatherstar.netbymatt.com",
    "location": {
      "lat": "41.79",
      "lon": "-107.23"
    }
  }
}

    Then relaunch FieldStation42, or reload channels in field_player.py.

❌ Remove a Channel

To remove a web-based channel:

pkill -f chromium-browser
pkill -f ffmpeg

rm confs/web_<channel>_channel.json
rm -rf hls/<channel>

Example:

rm confs/web_weather2_channel.json
rm -rf hls/weather2

📺 Stream Access

Each stream is available at:

http://localhost:8090/<channel>/index.m3u8

Where <channel> is a lowercase, underscore-safe version of your channel name (e.g., Weather2 → weather2).

Test using mpv or ffplay:

mpv http://localhost:8090/weather2/index.m3u8

💡 Tips and Notes

    Make sure no other app is using port 8090. Change it in the script if needed.

    Chromium runs in headless/kiosk mode — no interaction possible.

    Don't use pages that require mic/camera permissions.

    You can run multiple streams in background terminal tabs or with &.

    For integration with FieldStation42’s player, make sure the new config is scanned into your catalog.

🧪 Troubleshooting

    No video: Make sure Chromium is launching inside a working Xvfb session.

    Missing dependencies: Use apt install to fix missing tools.

    URL not displaying: Test it in Chromium manually first.

    Port 8090 conflict: Change the port in the script and update station_conf accordingly.

🧾 Summary
Task	Command Example
Add new channel	./add_web_channel.sh "https://site.com" "Site" 39
Start streaming it	./start_web_stream.sh "Site"
View the stream	http://localhost:8090/site/index.m3u8
Remove the channel	rm confs/web_site_channel.json && rm -rf hls/site && pkill -f chromium
Rebuild catalog/schedule	After adding: remember to regenerate FieldStation42's catalog and schedule
