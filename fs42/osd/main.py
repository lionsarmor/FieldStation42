import json
import sys
from collections import defaultdict
from pathlib import Path
import argparse
import glfw
from pydantic import BaseModel
from enum import Enum

try:
    from .render import Text, create_window, clear_screen
    from .logo_display import LogoDisplay, LogoDisplayConfig
except ImportError:
    from render import Text, create_window, clear_screen
    from logo_display import LogoDisplay, LogoDisplayConfig
from OpenGL.GL import *

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fs42.station_manager import StationManager
from fs42.channel_control import write_channel_command
from fs42.config import apply_cli_overrides
from fs42.process_wipe import wipe_runtime_processes
from fs42.window_titles import OSD_WINDOW_TITLE
from fs42.x11_focus import keep_window_above_by_title, keep_window_above_by_title_async
from fs42.osd.content_classifier import (
    ContentClassifier,
    ContentType,
    classify_current_content,
)

SOCKET_FILE = StationManager().server_conf["status_socket"]
CONFIG_FILE_PATH = Path("osd/osd.json")


class HAlignment(Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    CENTER = "CENTER"


class VAlignment(Enum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    CENTER = "CENTER"


class StatusDisplayConfig(BaseModel):
    display_time: float = 2.0
    halign: HAlignment = HAlignment.LEFT
    valign: VAlignment = VAlignment.TOP
    format_text: str = "{channel_number} - {network_name}"
    text_color: tuple[int, int, int, int] = (0, 255, 0, 200)
    font_size: int = 40
    expansion_factor: float = 1.0
    font: str | None = None
    x_margin: float = 0.1
    y_margin: float = 0.1
    delay: float = 0.0


class StatusDisplay(object):
    def __init__(self, window, config: StatusDisplayConfig):
        self.config = config
        self.window = window

        self._text = Text(
            window,
            "",
            font_size=self.config.font_size,
            color=self.config.text_color,
            expansion_factor=self.config.expansion_factor,
            font=self.config.font,
        )

        self.time_since_change = 0
        self.last_status = None  # Track the last status to detect changes

        self.check_status()

    def check_status(self, socket_file=SOCKET_FILE):
        with open(socket_file, "r") as f:
            status = f.read()
            if not status.strip():
                return
            try:
                status = json.loads(status)
            except:
                print(f"Unable to parse player status, {status}")

            else:
                # Check if status field changed (e.g., from "stopped" to "playing")
                status_changed = self.last_status is None or status.get("status") != self.last_status.get("status")
                self.last_status = status

                new_string = self.config.format_text.format_map(defaultdict(str, status))
                # Reset timer if text changed OR if status changed (like stopped->playing)
                if new_string != self._text.string or status_changed:
                    self.time_since_change = -self.config.delay
                    if new_string:
                        self._text.string = new_string

    def update(self, dt):
        self.time_since_change += dt
        self.check_status()

    def draw(self):
        if self.time_since_change < self.config.display_time:
            # Screen coords are -1 to 1 with 0 in the center, -1,-1 is bottom left.
            # text draw origin is at bottom left
            if self.config.halign == HAlignment.LEFT:
                x = -1 + self.config.x_margin
            elif self.config.halign == HAlignment.RIGHT:
                x = 1 - self._text.width - self.config.x_margin
            else:  # CENTER
                x = -self._text.width / 2

            if self.config.valign == VAlignment.BOTTOM:
                y = -1 + self.config.y_margin
            elif self.config.valign == VAlignment.TOP:
                y = 1 - self._text.height - self.config.y_margin
            else:  # CENTER
                y = -self._text.height / 2

            self._text.draw(x, y)


objects = []

parser = argparse.ArgumentParser(description="FieldStation42 OSD")
parser.add_argument("--windowed", action="store_true", help="Render OSD in a desktop window.")
parser.add_argument("--fullscreen", action="store_true", help="Render OSD fullscreen.")
parser.add_argument("--window-width", type=int, help="Window width for windowed OSD.")
parser.add_argument("--window-height", type=int, help="Window height for windowed OSD.")
parser.add_argument("--window-x", type=int, help="Window x position for windowed OSD.")
parser.add_argument("--window-y", type=int, help="Window y position for windowed OSD.")
window_group = parser.add_mutually_exclusive_group()
window_group.add_argument(
    "--combined-window",
    dest="combined_window",
    action="store_true",
    default=None,
    help="Stack the OSD over the MPV window in windowed mode.",
)
window_group.add_argument(
    "--separate-osd-window",
    dest="combined_window",
    action="store_false",
    help="Use a separate decorated OSD window in windowed mode.",
)
args = parser.parse_args()

manager = StationManager()
manager.server_conf.update(apply_cli_overrides({}, args))
osd_scale = float(manager.server_conf.get("osd_scale", 1.0))
fullscreen = bool(manager.server_conf.get("fullscreen", True))
window_width = int(manager.server_conf.get("window_width", 1280))
window_height = int(manager.server_conf.get("window_height", 720))
window_x = int(manager.server_conf.get("window_x", 80))
window_y = int(manager.server_conf.get("window_y", 60))
combined_window = bool(manager.server_conf.get("combined_window", True))
overlay_window = fullscreen or ((not fullscreen) and combined_window)

window = create_window(
    fullscreen=fullscreen,
    width=window_width,
    height=window_height,
    resizable=(not fullscreen) and (not combined_window),
    overlay=overlay_window,
    position=(window_x, window_y) if overlay_window else None,
)


def key_callback(window, key, scancode, action, mods):
    if action != glfw.PRESS:
        return
    if key == glfw.KEY_UP:
        write_channel_command("up", channel_socket=manager.server_conf["channel_socket"])
    elif key == glfw.KEY_DOWN:
        write_channel_command("down", channel_socket=manager.server_conf["channel_socket"])
    elif key == glfw.KEY_ESCAPE:
        write_channel_command("exit", channel_socket=manager.server_conf["channel_socket"])
        wipe_runtime_processes(stop_units=True, stop_player_unit=True)
        glfw.set_window_should_close(window, True)
    elif key == glfw.KEY_S:
        write_channel_command(
            "mpv_command",
            channel_socket=manager.server_conf["channel_socket"],
            action="toggle_subtitles",
        )


glfw.set_key_callback(window, key_callback)
if overlay_window:
    keep_window_above_by_title_async(
        OSD_WINDOW_TITLE,
        attempts=30,
        delay_seconds=0.2,
        remove_fullscreen=fullscreen,
    )

if CONFIG_FILE_PATH.exists():
    with open(CONFIG_FILE_PATH, "r") as f:
        config_dict = json.load(f)
        for obj in config_dict:
            if "type" not in obj:
                obj["type"] = "StatusDisplay"
            if obj["type"] == "StatusDisplay":
                del obj["type"]
                if "font_size" in obj:
                    obj["font_size"] = max(1, int(obj["font_size"] * osd_scale))
                config = StatusDisplayConfig.model_validate(obj)
                osd = StatusDisplay(window, config)
                objects.append(osd)
            elif obj["type"] == "LogoDisplay":
                del obj["type"]
                config = LogoDisplayConfig.model_validate(obj)
                logo = LogoDisplay(window, config)
                objects.append(logo)
            elif obj["type"] == "HybridDisplay":
                del obj["type"]
                config_status = StatusDisplayConfig.model_validate(obj)
                config_logo = LogoDisplayConfig.model_validate(obj)
                status_osd = StatusDisplay(window, config_status)
                status_logo = LogoDisplay(window, config_logo)
                objects.append(status_logo)
                objects.append(status_osd)
            else:
                print(f"Unrecognized osd object type: {obj['type']}")

else:
    config = StatusDisplayConfig()
    objects.append(StatusDisplay(window, config))


# --------------------------
# Main loop

try:
    now = glfw.get_time()
    last_raise = 0.0
    while not glfw.window_should_close(window):
        glfw.wait_events_timeout(1.0 / 30.0)  # ~30 FPS, low CPU
        now, last = glfw.get_time(), now
        delta_time = now - last
        if overlay_window and now - last_raise >= 1.0:
            keep_window_above_by_title(
                OSD_WINDOW_TITLE,
                attempts=1,
                delay_seconds=0,
                remove_fullscreen=fullscreen,
            )
            last_raise = now

        clear_screen()

        for obj in objects:
            obj.update(delta_time)

        # Draw objects with StatusDisplay on top
        for obj in sorted(objects, key=lambda x: isinstance(x, StatusDisplay)):
            obj.draw()

        glfw.swap_buffers(window)
except KeyboardInterrupt:
    pass

# Cleanup
glfw.terminate()
