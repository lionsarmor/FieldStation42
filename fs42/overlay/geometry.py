def window_rect_from_geometry(screen_rect, geometry):
    """Resolve the QRect an OSD overlay should cover.

    Overlays default to covering the whole physical screen (matching
    fullscreen playback, and the "separate OSD window" windowed mode where
    there's no single player rect to match). Only when running windowed with
    combined_window (mpv + OSD explicitly stacked together) do we shrink the
    overlay down to the player's own rect, so it stops blocking clicks to
    whatever else is on the desktop.
    """
    if not geometry or geometry.get("fullscreen", True):
        return screen_rect
    if "x" not in geometry or "y" not in geometry:
        return screen_rect

    from PySide6.QtCore import QRect

    return QRect(
        geometry["x"],
        geometry["y"],
        geometry.get("width", screen_rect.width()),
        geometry.get("height", screen_rect.height()),
    )
