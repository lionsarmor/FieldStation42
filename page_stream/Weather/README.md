
########################################
# 0. Launch WeatherStar Web Stream
########################################

WEATHER_URL="https://weatherstar.netbymatt.com/?hazards-checkbox=true&current-weather-checkbox=true&latest-observations-checkbox=true&hourly-checkbox=true&hourly-graph-checkbox=true&travel-checkbox=true&regional-forecast-checkbox=true&local-forecast-checkbox=true&extended-forecast-checkbox=true&almanac-checkbox=true&spc-outlook-checkbox=true&radar-checkbox=true&settings-wide-checkbox=false&settings-kiosk-checkbox=true&settings-scanLines-checkbox=true&settings-speed-select=1.00&settings-units-select=us&latLonQuery=Rawlins%2C+WY&latLon=%7B%22lat%22%3A41.7890116%2C%22lon%22%3A-107.2304671%7D"



# FieldStation42 Webpage Streaming Module

---

## Overview

This module allows you to add and stream **live webpage channels** inside your FieldStation42 system. It uses a headless Chromium browser, captures its output with FFmpeg, and serves the stream via HTTP.

---

## Prerequisites

Make sure the following commands are installed on your system:

- `jq`
- `curl`
- `chromium-browser`
- `ffmpeg`
- `Xvfb`
- `python3`
- `wmctrl`

### Debian/Ubuntu Installation

```bash
sudo apt update
sudo apt install -y jq curl chromium-browser ffmpeg xvfb python3 wmctrl


./add_web_channel.sh "<URL>" "<ChannelName>" <ChannelNumber> [--force]

./start_web_stream.sh "<ChannelName>"

example:

./add_web_channel.sh "https://weatherstar.netbymatt.com/?hazards-checkbox=true&current-weather-checkbox=true&latest-observations-checkbox=true&hourly-checkbox=true&hourly-graph-checkbox=true&travel-checkbox=true&regional-forecast-checkbox=true&local-forecast-checkbox=true&extended-forecast-checkbox=true&almanac-checkbox=true&spc-outlook-checkbox=true&radar-checkbox=true&settings-wide-checkbox=false&settings-kiosk-checkbox=true&settings-scanLines-checkbox=true&settings-speed-select=1.00&settings-units-select=us&latLonQuery=Rawlins%2C+WY&latLon=%7B%22lat%22%3A41.7890116%2C%22lon%22%3A-107.2304671%7D" "<Weather2" 99 

To Remove a Channel

    Kill relevant streaming processes:

pkill -f chromium-browser
pkill -f ffmpeg

    Delete the config and HLS files:

rm confs/web_<channel_id>_channel.json
rm -rf hls/<channel_id>

Troubleshooting

    If the script complains about missing dependencies, install them via your package manager.

    If streams do not load, verify the webpage URL works in Chromium manually.

    Check that no other application is using port 8090.




📺 Streaming Output

Once running, your stream is available at:

http://localhost:8090/<channel_id>/index.m3u8

Where <channel_id> is a lowercase, underscore-safe version of the channel name, e.g.:

    Weather → weather

    CNN Live → cnn_live

This can be played in FieldStation42 by using the matching conf file and URL in your media player logic (e.g., mpv or ffplay).
📄 Configuration Example

A generated conf file confs/web_weather_channel.json looks like:

{
  "station_conf": {
    "network_name": "Weather",
    "network_type": "streaming",
    "channel_number": 38,
    "runtime_dir": "runtime/weather",
    "content_dir": "catalog/weather_content",
    "catalog_path": "catalog/weather.bin",
    "schedule_path": "runtime/weather_schedule.bin",
    "network_long_name": "Weather Web Stream",
    "streams": [
      {
        "url": "http://localhost:8090/weather/index.m3u8",
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

This file will be automatically created by add_web_channel.sh.
🔁 Reusability

    You can run add_web_channel.sh multiple times to add different channels.

    Channels persist unless you manually delete their web_*.json files.

    Run start_web_stream.sh again to relaunch any stream.

❌ To Remove a Channel

Just delete the corresponding conf file and stop the stream:

rm confs/web_weather_channel.json
pkill -f chromium-browser
pkill -f ffmpeg

You may also want to remove its HLS output:

rm -rf hls/weather/

💡 Pro Tips

    Make sure no other app is using port 8090 — or change it in the script.

    Chromium will not show permission dialogs, so avoid pages needing microphone/webcam.

    Use wmctrl if you want to bring Chromium windows into focus under a real X session.

    You can integrate these with your existing field_player.py and channel switching system.

📚 Summary
Task	Command Example
Add new webpage channel	./add_web_channel.sh "https://site.com" "Site" 39
Start streaming it	./start_web_stream.sh "Site"
View stream	http://localhost:8090/site/index.m3u8
Remove channel	rm confs/web_site_channel.json

    Created for FieldStation42 — a retro-modern TV box simulator for hackers and tinkerers.


# 🌐 FieldStation42 Web Page Channel Streaming

This module enables **live webpage streaming** inside your [FieldStation42](https://github.com/your-org/FieldStation42) cable box simulator. You can treat any webpage — like weather, maps, or dashboards — as a TV channel, and it will stream in real-time using a full-screen Chromium browser and FFmpeg HLS encoding.

---

## 📁 Files Overview

| File                   | Purpose                                                                 |
|------------------------|-------------------------------------------------------------------------|
| `add_web_channel.sh`   | Creates a persistent, location-aware config for a new webpage channel   |
| `start_web_stream.sh`  | Launches a virtual display, opens Chromium, and starts FFmpeg streaming |
| `confs/web_*.json`     | Stores individual configuration for each webpage-based stream channel   |
| `hls/<channel>/`       | Folder where each stream’s video segments are written                    |

---

## ✅ Requirements

Make sure the following are installed on your system:

- `jq` (JSON parsing)
- `curl` (location fetching)
- `chromium-browser` (or equivalent browser)
- `ffmpeg` (video encoder)
- `Xvfb` (virtual display server)
- `python3` (to serve files via `http.server`)

On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install jq curl chromium-browser ffmpeg xvfb python3 -y

🚀 Step-by-Step Usage
🧱 1. Add a New Web Channel

Use add_web_channel.sh to create a configuration file for a streaming webpage.

./add_web_channel.sh "<URL>" "<ChannelName>" <ChannelNumber> [--force]

Arguments:

    <URL>: The full webpage address (must work in Chromium)

    <ChannelName>: A human-readable name (e.g., "Weather")

    <ChannelNumber>: Channel number used in FieldStation42 (e.g., 38)

    --force (optional): Overwrites existing conf file if present

Example:

./add_web_channel.sh "https://weatherstar.netbymatt.com" "Weather" 38

This will:

    Use your current location (via ipinfo.io) for metadata

    Create confs/web_weather_channel.json

    Set up the stream path at http://localhost:8090/weather/index.m3u8

▶️ 2. Start Streaming the Channel

Use start_web_stream.sh with the same channel name:

./start_web_stream.sh "Weather"

This will:

    Read from confs/web_weather_channel.json

    Launch Chromium in full-screen kiosk mode using Xvfb

    Capture video output using ffmpeg

    Save the stream to hls/weather/index.m3u8

    Serve it via python3 -m http.server 8090

    You can run multiple streams in parallel by using separate terminal tabs or backgrounding with &.

📺 Streaming Output

Once running, your stream is available at:

http://localhost:8090/<channel_id>/index.m3u8

Where <channel_id> is a lowercase, underscore-safe version of the channel name, e.g.:

    Weather → weather

    CNN Live → cnn_live

This can be played in FieldStation42 by using the matching conf file and URL in your media player logic (e.g., mpv or ffplay).
📄 Configuration Example

A generated conf file confs/web_weather_channel.json looks like:

{
  "station_conf": {
    "network_name": "Weather",
    "network_type": "streaming",
    "channel_number": 38,
    "runtime_dir": "runtime/weather",
    "content_dir": "catalog/weather_content",
    "catalog_path": "catalog/weather.bin",
    "schedule_path": "runtime/weather_schedule.bin",
    "network_long_name": "Weather Web Stream",
    "streams": [
      {
        "url": "http://localhost:8090/weather/index.m3u8",
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

This file will be automatically created by add_web_channel.sh.
🔁 Reusability

    You can run add_web_channel.sh multiple times to add different channels.

    Channels persist unless you manually delete their web_*.json files.

    Run start_web_stream.sh again to relaunch any stream.

❌ To Remove a Channel

Just delete the corresponding conf file and stop the stream:

rm confs/web_weather_channel.json
pkill -f chromium-browser
pkill -f ffmpeg

You may also want to remove its HLS output:

rm -rf hls/weather/

💡 Pro Tips

    Make sure no other app is using port 8090 — or change it in the script.

    Chromium will not show permission dialogs, so avoid pages needing microphone/webcam.

    Use wmctrl if you want to bring Chromium windows into focus under a real X session.

    You can integrate these with your existing field_player.py and channel switching system.

📚 Summary
Task	Command Example
Add new webpage channel	./add_web_channel.sh "https://site.com" "Site" 39
Start streaming it	./start_web_stream.sh "Site"
View stream	http://localhost:8090/site/index.m3u8
Remove channel	rm confs/web_site_channel.json
