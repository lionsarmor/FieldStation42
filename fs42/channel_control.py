import json
from pathlib import Path

from fs42.station_manager import StationManager


def write_channel_command(
    command: str,
    channel: int | None = None,
    channel_socket: str | None = None,
    **fields,
):
    payload = {"command": command}
    if channel is not None:
        payload["channel"] = channel
    payload.update(fields)

    socket_path = channel_socket or StationManager().server_conf["channel_socket"]
    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)
    with open(socket_path, "w", encoding="utf-8") as fp:
        fp.write(json.dumps(payload))
