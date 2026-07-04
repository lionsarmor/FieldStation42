import json
import os
import signal
from PySide6.QtCore import QPoint, QUrl, QTimer, Qt
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

from fs42.window_titles import WEB_WINDOW_TITLE
from fs42.channel_control import write_channel_command
from fs42.station_manager import StationManager
from fs42.x11_focus import force_focus_by_title_async

class WebRender(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WEB_WINDOW_TITLE)
        self.browser = QWebEngineView()
        self._bind_channel_key_controls()

        # Configure QWebEngineSettings to enable autoplay
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        # Set custom user agent for identification
        self.browser.page().profile().setHttpUserAgent("FieldStation42-WebRender/1.0")

        # Set black background color
        self.browser.page().setBackgroundColor(Qt.black)
        if hasattr(self.browser.page(), "setAudioMuted"):
            self.browser.page().setAudioMuted(False)

        self.setCentralWidget(self.browser)

        # Hide cursor
        self.setCursor(Qt.BlankCursor)

        # Retry logic for handling web server startup races
        self.current_url = None
        self.retry_count = 0
        self.max_retries = 3
        self.retry_delay = 2000  # 2 seconds in milliseconds
        self.trusted_click_attempts = 0

    def _bind_channel_key_controls(self):
        # QShortcut with ApplicationShortcut context fires regardless of
        # which child widget has focus - needed since QWebEngineView (the
        # embedded browser) normally owns keyboard focus over this window.
        self._channel_shortcuts = []
        for key, command in ((Qt.Key_Up, "up"), (Qt.Key_Down, "down")):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(
                lambda command=command: write_channel_command(
                    command,
                    channel_socket=StationManager().server_conf["channel_socket"],
                )
            )
            self._channel_shortcuts.append(shortcut)
        shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(self._request_player_exit)
        self._channel_shortcuts.append(shortcut)

    def _request_player_exit(self):
        write_channel_command(
            "exit",
            channel_socket=StationManager().server_conf["channel_socket"],
        )
        try:
            os.kill(os.getppid(), signal.SIGINT)
        except OSError:
            pass

    def navigate(self, URL: str):
        # Initialize retry tracking for new URL
        self.current_url = URL
        self.retry_count = 0
        self.trusted_click_attempts = 0
        print(f"WebRender navigating to: {URL}")

        self.browser.setUrl(QUrl(URL))
        # Connect to loadFinished to simulate user interaction after page loads
        self.browser.loadFinished.connect(self._on_load_finished)

    def _retry_load(self):
        """Retry loading the current URL"""
        print(f"WebRender retrying URL: {self.current_url} (attempt {self.retry_count + 1}/{self.max_retries})")
        self.browser.setUrl(QUrl(self.current_url))

    def _on_load_finished(self, success):
        if success:
            print(f"WebRender successfully loaded: {self.current_url}")
            # Reset retry count on success
            self.retry_count = 0

            for delay in (0, 500, 1500, 3000, 6000, 10000, 15000, 20000):
                QTimer.singleShot(delay, self._run_autoplay_script)
        else:
            # Load failed - hide any error content and show black screen
            hide_error_code = """
            document.body.style.backgroundColor = 'black';
            document.body.innerHTML = '';
            """
            self.browser.page().runJavaScript(hide_error_code)

            # Check if we should retry
            if self.retry_count < self.max_retries:
                self.retry_count += 1
                print(f"WebRender load failed for: {self.current_url}, will retry in {self.retry_delay/1000}s...")
                # Schedule retry after delay
                QTimer.singleShot(self.retry_delay, self._retry_load)
            else:
                print(f"WebRender load failed for: {self.current_url} after {self.max_retries} retries, giving up.")

    def _run_autoplay_script(self):
        js_code = r"""
        (() => {
            const params = new URLSearchParams(window.location.search);
            const explicitText = (params.get('fs42_start_click_text') || '').trim().toLowerCase();
            const wantsAutoStart = params.get('fs42_auto_start') === '1' || explicitText;
            const forceAudio = params.get('fs42_force_audio') === '1';
            let clicked = 0;
            const soundStateKeys = ['$ssound-enabled', 'sound-enabled'];
            let soundStateForced = false;

            try {
                document.body && document.body.click();
            } catch (e) {}

            const forceStateObject = (state) => {
                if (!state || typeof state !== 'object') {
                    return;
                }
                soundStateKeys.forEach((key) => {
                    try {
                        state[key] = true;
                        soundStateForced = true;
                    } catch (e) {}
                });
            };
            const forceNuxtState = (candidate) => {
                if (!candidate || typeof candidate !== 'object') {
                    return;
                }
                try {
                    forceStateObject(candidate.state);
                    forceStateObject(candidate.payload && candidate.payload.state);
                    forceStateObject(candidate._payload && candidate._payload.state);
                } catch (e) {}
            };

            if (forceAudio) {
                try {
                    forceNuxtState(window.__NUXT__);
                    forceNuxtState(window.$nuxt);
                    const vueApp = document.getElementById('__nuxt') && document.getElementById('__nuxt').__vue_app__;
                    forceNuxtState(vueApp);
                    const provides = vueApp && vueApp._context && vueApp._context.provides;
                    if (provides && typeof provides === 'object') {
                        Object.keys(provides).forEach((key) => forceNuxtState(provides[key]));
                        Object.getOwnPropertySymbols(provides).forEach((key) => forceNuxtState(provides[key]));
                    }
                    localStorage.setItem('sound-enabled', 'true');
                    localStorage.setItem('$ssound-enabled', 'true');
                    sessionStorage.setItem('sound-enabled', 'true');
                    sessionStorage.setItem('$ssound-enabled', 'true');
                } catch (e) {}
            }

            if ('wakeLock' in navigator) {
                navigator.wakeLock.request('screen').catch(() => {});
            }

            let howlerState = null;
            if (window.Howler && typeof window.Howler.mute === 'function') {
                try {
                    window.Howler.mute(false);
                    if (typeof window.Howler.volume === 'function') {
                        window.Howler.volume(1);
                    }
                    if (window.Howler.ctx && typeof window.Howler.ctx.resume === 'function') {
                        window.Howler.ctx.resume().catch(() => {});
                    }

                    let howls = 0;
                    let playing = 0;
                    let playAttempts = 0;
                    (window.Howler._howls || []).forEach((howl) => {
                        howls += 1;
                        try {
                            if (typeof howl.mute === 'function') {
                                howl.mute(false);
                            }
                            if (typeof howl.volume === 'function') {
                                howl.volume(1);
                            }
                            if (typeof howl.playing === 'function' && howl.playing()) {
                                playing += 1;
                            }
                        } catch (e) {}
                    });

                    if (forceAudio && howls && playing === 0) {
                        const musicHowl = (window.Howler._howls || []).find((howl) => {
                            const src = String(howl && howl._src || '');
                            return howl && (howl._loop || src.includes('/music/'));
                        });
                        if (musicHowl && typeof musicHowl.play === 'function') {
                            try {
                                musicHowl.play();
                                playAttempts += 1;
                            } catch (e) {}
                        }
                    }

                    howlerState = {
                        howls,
                        playing,
                        playAttempts,
                        muted: !!window.Howler._muted,
                        volume: typeof window.Howler.volume === 'function' ? window.Howler.volume() : null,
                        context: window.Howler.ctx ? window.Howler.ctx.state : null,
                    };
                } catch (e) {
                    howlerState = {error: String(e)};
                }
            }

            window.focus();

            const elements = Array.from(document.querySelectorAll(
                'button, a, [role="button"], input[type="button"], input[type="submit"], [tabindex], div, span'
            ));
            const elementText = (element) => (
                element.innerText ||
                element.value ||
                element.getAttribute('aria-label') ||
                element.getAttribute('title') ||
                ''
            ).trim().toLowerCase();

            const buttons = elements.filter((element) => {
                const text = elementText(element);
                if (!text) {
                    return false;
                }
                if (explicitText) {
                    return text.includes(explicitText);
                }
                return wantsAutoStart && /start|play|listen|audio|begin/.test(text);
            });

            const audioButtons = forceAudio ? elements.filter((element) => {
                const text = elementText(element);
                if (!text) {
                    return false;
                }
                return /unmute|enable sound|sound on|turn sound on|audio on|enable audio|volume up/.test(text);
            }) : [];

            const buttonTargets = [];
            const captureTarget = (button) => {
                const rect = button.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    const target = {
                        x: Math.round(rect.left + rect.width / 2),
                        y: Math.round(rect.top + rect.height / 2),
                    };
                    if (!buttonTargets.some((existing) => existing.x === target.x && existing.y === target.y)) {
                        buttonTargets.push(target);
                    }
                }
            };

            buttons.slice(0, 5).forEach((button) => {
                captureTarget(button);
                button.click();
                button.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
                button.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
                clicked += 1;
            });

            audioButtons.slice(0, 3).forEach((button) => {
                captureTarget(button);
                button.click();
                button.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
                button.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
                clicked += 1;
            });

            const visibleAudioControls = elements.slice(0, 80).map((element) => {
                const text = elementText(element);
                return text ? text.slice(0, 60) : null;
            }).filter((text) => text && /audio|sound|volume|mute|unmute|start retrocast|toggle/.test(text));

            let mediaCount = 0;
            document.querySelectorAll('video, audio').forEach((element) => {
                mediaCount += 1;
                element.muted = false;
                element.volume = 1.0;
                element.autoplay = true;
                element.play().catch(() => {});
            });

            return JSON.stringify({
                clicked,
                candidates: buttons.length,
                audioCandidates: audioButtons.length,
                mediaCount,
                soundStateForced,
                howlerState,
                clickTarget: buttonTargets[0] || null,
                clickTargets: buttonTargets.slice(0, 3),
                visibleAudioControls,
            });
        })();
        """
        self.browser.page().runJavaScript(
            js_code,
            self._handle_autoplay_result,
        )

    def _handle_autoplay_result(self, result):
        try:
            parsed = json.loads(result) if isinstance(result, str) and result else result
        except (TypeError, json.JSONDecodeError):
            parsed = None

        print(f"WebRender autoplay result: {parsed}")
        if not isinstance(parsed, dict) or self.trusted_click_attempts >= 3:
            return

        targets = parsed.get("clickTargets") or [parsed.get("clickTarget")]
        if not isinstance(targets, list):
            return

        clicked_any = False
        for target in targets:
            if not isinstance(target, dict) or self.trusted_click_attempts >= 3:
                continue
            try:
                x = int(target.get("x", -1))
                y = int(target.get("y", -1))
            except (TypeError, ValueError):
                continue

            if x < 0 or y < 0:
                continue

            self.trusted_click_attempts += 1
            clicked_any = True
            QTest.mouseClick(self.browser, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))

        if clicked_any:
            QTimer.singleShot(100, self._run_autoplay_script)

class WebRenderApp(QApplication):
    def __init__(self, user_conf, queue=None):
        super().__init__([])

        self.queue = queue

        self.window = WebRender()

        # Set window properties
        if "width" in user_conf and "height" in user_conf:
            # Use specified dimensions
            width = user_conf["width"]
            height = user_conf["height"]

            # Always use frameless window (no decorations)
            self.window.setWindowFlags(Qt.FramelessWindowHint)
            self.window.resize(width, height)

            # Calculate position
            if "x" in user_conf and "y" in user_conf:
                # Use specified position
                x = user_conf["x"]
                y = user_conf["y"]
            else:
                # Center on screen
                screen = self.primaryScreen().availableGeometry()
                x = screen.center().x() - width // 2
                y = screen.center().y() - height // 2

            # Show window and position it (delay needed for X11 window managers)
            self.window.show()

            # Store position for delayed move
            def delayed_move():
                if self.window and not self.window.isHidden():
                    self.window.move(x, y)

            QTimer.singleShot(100, delayed_move)
        else:
            # Go fullscreen by default (no decorations)
            self.window.showFullScreen()

        # window managers don't always hand focus to a freshly-mapped window -
        # claim it explicitly or the channel/exit key shortcuts get nothing.
        force_focus_by_title_async(WEB_WINDOW_TITLE)

        # Set up timer for queue processing
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)  # Check every 250ms

        # Set up page refresh timer if configured
        if user_conf.get("refresh_interval", 0) > 0:
            self.refresh_timer = QTimer()
            self.refresh_timer.timeout.connect(self.window.browser.reload)
            self.refresh_timer.start(int(user_conf["refresh_interval"] * 1000))

    def tick(self):
        if self.queue and self.queue.qsize() > 0:
            msg = self.queue.get_nowait()
            print(f"WebRender received message: {msg}")
            # Handle queue messages similar to GuideApp
            if hasattr(msg, 'hide_window') or msg == "hide_window":
                print("WebRender window is shutting down now.")
                print("Stopping timer...")
                self.timer.stop()
                if hasattr(self, 'refresh_timer'):
                    self.refresh_timer.stop()
                print("Closing window...")
                self.window.close()
                print("Quitting application...")
                self.quit()
                print("WebRender shutdown complete")
                return
            # Handle key injection commands
            if isinstance(msg, str) and msg.startswith("key:"):
                key_name = msg[4:]
                if key_name not in {"PageUp", "PageDown", "Enter"}:
                    print(f"WebRender: rejected disallowed key '{key_name}'")
                    return
                js = f"""
                document.dispatchEvent(new KeyboardEvent('keydown', {{
                    key: '{key_name}',
                    code: '{key_name}',
                    bubbles: true,
                    cancelable: true
                }}));
                """
                self.window.browser.page().runJavaScript(js)
                return

def web_render_runner(user_conf, queue):
    # Set up signal handler for web process - just exit cleanly
    def web_sigint_handler(sig, frame):
        print("WebRender process received SIGINT, exiting...")
        import sys
        sys.exit(0)

    signal.signal(signal.SIGINT, web_sigint_handler)

    # Set environment variables to enable autoplay
    import os
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--autoplay-policy=no-user-gesture-required --disable-web-security --allow-running-insecure-content --disable-features=VizDisplayCompositor'

    # Set graphics API before creating QApplication
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)

    app = WebRenderApp(user_conf, queue)

    # Navigate to URL after a short delay to ensure Qt is fully initialized
    def delayed_navigate():
        url = user_conf.get("web_url", "http://localhost:4242/static/diagnostics.html")
        if "url" in user_conf:
            app.window.navigate(user_conf["url"])
        else:
            app.window.navigate(url)

    QTimer.singleShot(100, delayed_navigate)

    app.exec()

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.getcwd())

    # Simple test config - customize as needed
    test_conf = {
        "url": "http://localhost:4242/static/diagnostics.html",
        "width": 800,
        "height": 600,
        # Uncomment to test specific positioning:
        # "x": 100,
        # "y": 100,
    }

    # Or load a station config by name
    # Uncomment and modify to use a station config:
    # from fs42.station_manager import StationManager
    # test_conf = StationManager().station_by_name("diagnostic")

    web_render_runner(test_conf, None)
