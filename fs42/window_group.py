import logging
import threading
import time

from fs42.window_titles import (
    PLAYER_WINDOW_TITLE,
    OSD_WINDOW_TITLE,
    TICKER_WINDOW_TITLE,
    NOW_PLAYING_WINDOW_TITLE,
    NFO_WINDOW_TITLE,
    WEB_WINDOW_TITLE,
    GUIDE_WINDOW_TITLE,
)

ROLE_TITLES = {
    "player": PLAYER_WINDOW_TITLE,
    "osd": OSD_WINDOW_TITLE,
    "ticker": TICKER_WINDOW_TITLE,
    "now_playing": NOW_PLAYING_WINDOW_TITLE,
    "nfo": NFO_WINDOW_TITLE,
    "web": WEB_WINDOW_TITLE,
    "guide": GUIDE_WINDOW_TITLE,
}

# Depth limit for the raw window-tree walk used to find override-redirect
# windows (e.g. the Tk guide) that window managers don't add to
# _NET_CLIENT_LIST. Desktops don't nest windows anywhere near this deep.
_TREE_WALK_MAX_DEPTH = 6


class WindowGroupCoordinator:
    """Keeps FS42's windows (mpv player, OSD overlays, web channel, guide)
    positioned together in windowed + combined_window mode, and lets you
    drag the whole group with Alt+Left-click (matching this desktop's own
    "move window" modifier).

    Important: this does NOT rely on the window manager's own move gesture.
    Testing showed the window manager does not actually reposition these
    windows via its normal Alt+drag handling (confirmed with synthetic
    input - the WM-reported allowed actions include move, but the window
    never actually moves), so there is nothing to observe/mirror from the
    outside. Instead this grabs Alt+Button1 directly on each tracked window
    and performs the drag itself: on press it snapshots every window's
    starting position, on motion it applies the same pointer delta to all
    of them, on release it lets go. A plain click (no Alt held) is never
    intercepted and reaches the application normally.
    """

    RESOLVE_INTERVAL_SECONDS = 0.75
    EVENT_POLL_INTERVAL_SECONDS = 0.02

    # X11 grabs must be registered per exact modifier-mask combination -
    # Alt alone won't match if NumLock/CapsLock happen to be on, so we grab
    # Alt combined with every lock-key state.
    _LOCK_MASK_COMBINATIONS = None  # filled in once X is imported

    def __init__(self, roles_to_titles=None):
        self._l = logging.getLogger("WindowGroup")
        self._roles_to_titles = dict(roles_to_titles or ROLE_TITLES)
        self._window_ids = {role: None for role in self._roles_to_titles}
        self._grabbed = set()
        self._group_pos = None
        self._thread = None
        self._stop = threading.Event()
        self._display = None
        self._X = None
        self._last_resolve = 0.0
        self._last_positions = {}

        self._drag_active = False
        self._drag_start_mouse = None
        self._drag_start_positions = {}
        self._drag_last_delta = (0, 0)

    def start(self):
        try:
            from Xlib import X, display
        except ImportError as e:
            self._l.info(f"python-xlib not available, window group drag disabled: {e}")
            return
        try:
            self._display = display.Display()
        except Exception as e:
            self._l.warning(f"Could not open X display, window group drag disabled: {e}")
            return

        self._X = X
        self._LOCK_MASK_COMBINATIONS = [
            X.Mod1Mask,
            X.Mod1Mask | X.LockMask,
            X.Mod1Mask | X.Mod2Mask,
            X.Mod1Mask | X.LockMask | X.Mod2Mask,
        ]
        self._thread = threading.Thread(target=self._run_loop, name="WindowGroup", daemon=True)
        self._thread.start()
        self._l.info(f"Window group coordinator started for roles: {list(self._roles_to_titles)}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._release_grabs()

    # -- main loop ---------------------------------------------------------

    def _run_loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                self._l.warning(f"Window group tick failed: {e}")
            self._stop.wait(self.EVENT_POLL_INTERVAL_SECONDS)

    def _tick(self):
        now = time.time()
        if now - self._last_resolve >= self.RESOLVE_INTERVAL_SECONDS:
            self._last_resolve = now
            self._resolve_missing()

        try:
            while self._display.pending_events():
                self._handle_event(self._display.next_event())
        except Exception as e:
            self._l.debug(f"Error draining X events: {e}")

        if not self._drag_active:
            self._sync_group_position()

    def _resolve_missing(self):
        self._drop_stale_windows()
        for role, title in self._roles_to_titles.items():
            if self._window_ids.get(role) is not None:
                continue
            win = self._find_window_by_title(title)
            if win is None:
                continue

            self._window_ids[role] = win
            self._grab_drag_button(win)

            pos = self._safe_abs_pos(win)
            if pos is None:
                continue

            if self._group_pos is not None and pos != self._group_pos:
                self._safe_move(win, self._group_pos)
            elif self._group_pos is None:
                self._group_pos = pos

            self._l.debug(f"Resolved window for role={role} title={title!r} id={win.id}")

    def _sync_group_position(self):
        """Mirror a WM-driven move of any tracked window to the whole group.

        Some desktops claim Alt+drag before our passive grab sees the event.
        In that case the top window (usually the OSD) moves by itself; this
        observer keeps mpv and every overlay coupled to that moved window.
        """
        positions = {}
        for role, win in self._window_ids.items():
            if win is None:
                continue
            pos = self._safe_abs_pos(win)
            if pos is not None:
                positions[role] = pos

        if not positions:
            return

        if self._group_pos is None:
            anchor_role = "player" if "player" in positions else next(iter(positions))
            self._group_pos = positions[anchor_role]
            self._last_positions = dict(positions)
            return

        moved_roles = [
            role
            for role, pos in positions.items()
            if self._last_positions.get(role) is not None and self._last_positions.get(role) != pos
        ]
        if not moved_roles:
            self._last_positions = dict(positions)
            return

        anchor_role = moved_roles[0]
        for role in moved_roles:
            if role != "player":
                anchor_role = role
                break

        anchor_pos = positions[anchor_role]
        if anchor_pos == self._group_pos:
            self._last_positions = dict(positions)
            return

        for role, win in self._window_ids.items():
            if win is None or role == anchor_role:
                continue
            if positions.get(role) != anchor_pos:
                self._safe_move(win, anchor_pos)

        self._display.flush()
        self._group_pos = anchor_pos
        self._last_positions = {role: anchor_pos for role in positions}

    # -- drag handling -------------------------------------------------------

    def _grab_drag_button(self, win):
        key = win.id
        if key in self._grabbed:
            return
        try:
            for mods in self._LOCK_MASK_COMBINATIONS:
                win.grab_button(
                    1,  # Button1
                    mods,
                    False,  # owner_events - always deliver to us, never passthrough
                    self._X.ButtonPressMask | self._X.ButtonReleaseMask | self._X.PointerMotionMask,
                    self._X.GrabModeAsync,
                    self._X.GrabModeAsync,
                    0,
                    0,
                )
            self._grabbed.add(key)
            self._display.flush()
        except Exception as e:
            self._l.debug(f"Could not grab drag button on window {win.id}: {e}")

    def _handle_event(self, event):
        X = self._X
        if event.type == X.ButtonPress:
            self._start_drag(event)
        elif event.type == X.MotionNotify and self._drag_active:
            self._continue_drag(event)
        elif event.type == X.ButtonRelease and self._drag_active:
            self._end_drag(event)

    def _start_drag(self, event):
        X = self._X
        if getattr(event, "detail", 1) != 1:
            return
        self._resolve_missing()
        self._drag_start_mouse = (event.root_x, event.root_y)
        self._drag_start_positions = {}
        self._drag_last_delta = (0, 0)
        for role, win in self._window_ids.items():
            if win is None:
                continue
            pos = self._safe_abs_pos(win)
            if pos is not None:
                self._drag_start_positions[role] = (win, pos)

        if not self._drag_start_positions:
            self._drag_start_mouse = None
            return

        self._l.debug(
            "Starting grouped drag with roles=%s from mouse=%s",
            list(self._drag_start_positions.keys()),
            self._drag_start_mouse,
        )
        self._drag_active = True
        try:
            status = self._root().grab_pointer(
                False,  # owner_events - always deliver to us for the duration of the drag
                X.PointerMotionMask | X.ButtonReleaseMask,
                X.GrabModeAsync,
                X.GrabModeAsync,
                0,
                0,
                X.CurrentTime,
            )
            if status != X.GrabSuccess:
                self._l.debug(f"Pointer grab returned status {status}; continuing with passive grab events")
        except Exception as e:
            self._l.debug(f"Could not start drag (grab_pointer failed): {e}")

    def _continue_drag(self, event):
        if not self._drag_start_mouse:
            return
        dx = event.root_x - self._drag_start_mouse[0]
        dy = event.root_y - self._drag_start_mouse[1]
        self._drag_last_delta = (dx, dy)
        self._move_drag_windows(dx, dy)
        self._display.flush()

    def _end_drag(self, event=None):
        if event is not None and self._drag_start_mouse:
            self._drag_last_delta = (
                event.root_x - self._drag_start_mouse[0],
                event.root_y - self._drag_start_mouse[1],
            )

        try:
            self._display.ungrab_pointer(self._X.CurrentTime)
        except Exception:
            pass

        # Align every tracked window to the intended pointer delta on release.
        # Some clients accept live move requests later than others; this final
        # pass keeps mpv/OSD/web/guide coupled even if one skipped a motion.
        dx, dy = self._drag_last_delta
        self._move_drag_windows(dx, dy)
        try:
            self._display.sync()
        except Exception:
            pass

        # Record the intended final group position so newly-opened windows
        # (guide, OSD, web) line up here instead of at their original spawn
        # position.
        for role, (_win, (start_x, start_y)) in self._drag_start_positions.items():
            self._group_pos = (start_x + dx, start_y + dy)
            break
        self._drag_active = False
        self._drag_start_positions = {}
        self._drag_start_mouse = None
        self._drag_last_delta = (0, 0)

    def _move_drag_windows(self, dx, dy):
        for role, (win, (start_x, start_y)) in self._drag_start_positions.items():
            target = (start_x + dx, start_y + dy)
            moved = self._safe_move(win, target)
            self._l.debug("Drag move role=%s id=%s target=%s moved=%s", role, win.id, target, moved)

    # -- X11 helpers ---------------------------------------------------------

    def _root(self):
        return self._display.screen().root

    def _atom(self, name):
        return self._display.intern_atom(name)

    def _wm_name(self, win):
        try:
            prop = win.get_full_property(self._atom("_NET_WM_NAME"), self._X.AnyPropertyType)
            if prop and prop.value:
                value = prop.value
                return value.decode() if isinstance(value, bytes) else value
        except Exception:
            pass
        try:
            return win.get_wm_name()
        except Exception:
            return None

    def _find_in_client_list(self, title):
        try:
            prop = self._root().get_full_property(self._atom("_NET_CLIENT_LIST"), self._X.AnyPropertyType)
            if not prop:
                return None
            for window_id in prop.value:
                win = self._display.create_resource_object("window", window_id)
                if self._wm_name(win) == title:
                    return win
        except Exception:
            pass
        return None

    def _find_in_tree(self, title, node=None, depth=0):
        if node is None:
            node = self._root()
        if depth > _TREE_WALK_MAX_DEPTH:
            return None
        try:
            children = node.query_tree().children
        except Exception:
            return None
        for child in children:
            if self._wm_name(child) == title:
                return child
        for child in children:
            found = self._find_in_tree(title, child, depth + 1)
            if found is not None:
                return found
        return None

    def _find_window_by_title(self, title):
        # cheap path first: works for any normally WM-managed window (mpv,
        # the Qt web/OSD windows). Override-redirect windows (Tk guide) never
        # show up here, so fall back to walking the raw window tree.
        return self._find_in_client_list(title) or self._find_in_tree(title)

    def _drop_stale_windows(self):
        for role, win in list(self._window_ids.items()):
            if win is None:
                continue
            try:
                win.get_geometry()
            except Exception:
                self._grabbed.discard(win.id)
                self._window_ids[role] = None
                self._l.debug(f"Dropped stale window for role={role}")

    def _release_grabs(self):
        if not self._display:
            return
        try:
            self._display.ungrab_pointer(self._X.CurrentTime)
        except Exception:
            pass
        for win in list(self._window_ids.values()):
            if win is None:
                continue
            try:
                for mods in self._LOCK_MASK_COMBINATIONS or []:
                    win.ungrab_button(1, mods)
            except Exception:
                pass
        try:
            self._display.flush()
            self._display.close()
        except Exception:
            pass

    def _safe_abs_pos(self, win):
        try:
            coords = win.translate_coords(self._root(), 0, 0)
            return (-coords.x, -coords.y)
        except Exception:
            return None

    def _safe_move(self, win, pos):
        try:
            win.configure(x=int(pos[0]), y=int(pos[1]))
            return True
        except Exception as e:
            self._l.debug(f"Could not move window {getattr(win, 'id', '?')} to {pos}: {e}")
            return False
