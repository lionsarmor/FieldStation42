import logging
import threading
import time

_l = logging.getLogger("X11Focus")


def _wm_name(display_conn, win, X):
    try:
        prop = win.get_full_property(display_conn.intern_atom("_NET_WM_NAME"), X.AnyPropertyType)
        if prop and prop.value:
            value = prop.value
            return value.decode() if isinstance(value, bytes) else value
    except Exception:
        pass
    try:
        return win.get_wm_name()
    except Exception:
        return None


def _find_window_by_title(display_conn, title, X):
    root = display_conn.screen().root

    try:
        prop = root.get_full_property(display_conn.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
        if prop:
            for window_id in prop.value:
                win = display_conn.create_resource_object("window", window_id)
                if _wm_name(display_conn, win, X) == title:
                    return win
    except Exception:
        pass

    # override-redirect windows (e.g. a Tk window with overrideredirect(True))
    # never show up in _NET_CLIENT_LIST since they bypass the window manager
    # entirely - fall back to walking the raw window tree to find them.
    def walk(node, depth=0):
        if depth > 6:
            return None
        try:
            children = node.query_tree().children
        except Exception:
            return None
        for child in children:
            if _wm_name(display_conn, child, X) == title:
                return child
        for child in children:
            found = walk(child, depth + 1)
            if found is not None:
                return found
        return None

    return walk(root)


def force_focus_by_title(title, attempts=20, delay_seconds=0.1):
    """Best-effort: find our own window by title and give it real X11
    keyboard focus.

    Window managers don't reliably hand focus to newly-created windows, and
    never do for override-redirect windows (e.g. the Tk guide) - so key
    bindings can silently receive nothing even though the window is visible
    on screen. This is a single bounded attempt, not a background loop: it
    retries briefly while the window finishes mapping, then returns.

    Safe no-op if X11/python-xlib aren't available (e.g. Wayland).
    """
    try:
        from Xlib import X, display
    except ImportError:
        return False

    try:
        d = display.Display()
    except Exception as e:
        _l.debug(f"Could not open X display, skipping focus for {title!r}: {e}")
        return False

    try:
        for _ in range(attempts):
            win = _find_window_by_title(d, title, X)
            if win is not None:
                win.set_input_focus(X.RevertToParent, X.CurrentTime)
                d.sync()
                _l.debug(f"Forced X11 focus onto window {title!r}")
                return True
            time.sleep(delay_seconds)
        _l.debug(f"Could not find window {title!r} to focus after {attempts} attempts")
        return False
    except Exception as e:
        _l.debug(f"Could not focus window {title!r}: {e}")
        return False


def force_focus_by_title_async(title, attempts=20, delay_seconds=0.1):
    """Run force_focus_by_title() in a short-lived background thread so it
    doesn't block window creation while waiting for the window to map. The
    thread makes a bounded number of attempts and then exits - it does not
    run continuously."""
    thread = threading.Thread(
        target=force_focus_by_title,
        args=(title,),
        kwargs={"attempts": attempts, "delay_seconds": delay_seconds},
        daemon=True,
    )
    thread.start()
    return thread


def keep_window_above_by_title(title, attempts=1, delay_seconds=0.1, remove_fullscreen=False):
    """Best-effort: raise a window and ask the WM to keep it above.

    Unlike force_focus_by_title(), this never takes keyboard focus. It is used
    for transparent overlay windows that need to sit over fullscreen media.
    """
    try:
        from Xlib import X, display, protocol
    except ImportError:
        return False

    try:
        d = display.Display()
    except Exception as e:
        _l.debug(f"Could not open X display, skipping raise for {title!r}: {e}")
        return False

    try:
        root = d.screen().root
        net_wm_state = d.intern_atom("_NET_WM_STATE")
        state_above = d.intern_atom("_NET_WM_STATE_ABOVE")
        state_stays_on_top = d.intern_atom("_NET_WM_STATE_STAYS_ON_TOP")
        state_fullscreen = d.intern_atom("_NET_WM_STATE_FULLSCREEN")

        for _ in range(attempts):
            win = _find_window_by_title(d, title, X)
            if win is not None:
                if remove_fullscreen:
                    event = protocol.event.ClientMessage(
                        window=win,
                        client_type=net_wm_state,
                        data=(32, [0, state_fullscreen, 0, 1, 0]),
                    )
                    root.send_event(
                        event,
                        event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
                    )
                for state_atom in (state_above, state_stays_on_top):
                    event = protocol.event.ClientMessage(
                        window=win,
                        client_type=net_wm_state,
                        data=(32, [1, state_atom, 0, 1, 0]),
                    )
                    root.send_event(
                        event,
                        event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
                    )
                win.configure(stack_mode=X.Above)
                d.sync()
                _l.debug(f"Raised X11 window above without focus: {title!r}")
                return True
            time.sleep(delay_seconds)
        _l.debug(f"Could not find window {title!r} to raise after {attempts} attempts")
        return False
    except Exception as e:
        _l.debug(f"Could not raise window {title!r}: {e}")
        return False
    finally:
        try:
            d.close()
        except Exception:
            pass


def keep_window_above_by_title_async(title, attempts=20, delay_seconds=0.1, remove_fullscreen=False):
    thread = threading.Thread(
        target=keep_window_above_by_title,
        args=(title,),
        kwargs={
            "attempts": attempts,
            "delay_seconds": delay_seconds,
            "remove_fullscreen": remove_fullscreen,
        },
        daemon=True,
    )
    thread.start()
    return thread
