"""
RT Viewer Launcher
==================
Starts and monitors both the FastAPI backend (api_server.py) and the
Node.js frontend (frontend/dist server).  Shows a system tray icon with
status indicators for each service and a menu to open the browser, view
logs, and stop everything cleanly.

Build to EXE:
    pip install pyinstaller pystray pillow
    pyinstaller launcher.spec

Run directly (dev/debug):
    python launcher.py
"""

import sys
import os
import time
import threading
import subprocess
import webbrowser
import logging
import signal
import queue
from pathlib import Path
from datetime import datetime

# ─── Paths ───────────────────────────────────────────────────────────────────
# When running as a PyInstaller EXE, files are next to the executable.
# When running as a script, they're next to this file.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

BACKEND_SCRIPT  = BASE_DIR / "api_server.py"
FRONTEND_DIR    = BASE_DIR / "frontend"
FRONTEND_DIST   = FRONTEND_DIR / "dist" / "index.cjs"
LOG_DIR         = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

BACKEND_PORT  = 8000
FRONTEND_PORT = 5000
BROWSER_URL   = f"http://127.0.0.1:{FRONTEND_PORT}"

# ─── Logging ─────────────────────────────────────────────────────────────────
log_file = LOG_DIR / f"launcher_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("launcher")

# ─── Service state ───────────────────────────────────────────────────────────
class ServiceState:
    STOPPED  = "stopped"
    STARTING = "starting"
    RUNNING  = "running"
    CRASHED  = "crashed"

    ICONS = {
        STOPPED:  "⬜",
        STARTING: "🟡",
        RUNNING:  "🟢",
        CRASHED:  "🔴",
    }

class Service:
    def __init__(self, name: str, cmd: list, cwd: Path, env: dict = None):
        self.name    = name
        self.cmd     = cmd
        self.cwd     = cwd
        self.env     = env
        self.proc: subprocess.Popen | None = None
        self.state   = ServiceState.STOPPED
        self.restarts = 0
        self.log_file = LOG_DIR / f"{name.lower().replace(' ', '_')}.log"
        self._log_fh  = None
        self._lock    = threading.Lock()

    def start(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return  # already running
            self._log_fh = open(self.log_file, "a", encoding="utf-8")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log_fh.write(f"\n{'='*60}\n[{ts}] Starting {self.name}\n{'='*60}\n")
            self._log_fh.flush()

            env = os.environ.copy()
            if self.env:
                env.update(self.env)

            self.proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                env=env,
                stdout=self._log_fh,
                stderr=self._log_fh,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self.state = ServiceState.STARTING
            log.info(f"{self.name}: started (pid {self.proc.pid})")

    def stop(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                log.info(f"{self.name}: stopping (pid {self.proc.pid})...")
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.state = ServiceState.STOPPED
            if self._log_fh:
                self._log_fh.close()
                self._log_fh = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def check(self) -> bool:
        """Returns True if still alive, False if it exited."""
        if self.proc is None:
            return False
        rc = self.proc.poll()
        if rc is not None:
            log.warning(f"{self.name}: exited with code {rc}")
            if self._log_fh:
                self._log_fh.close()
                self._log_fh = None
            self.state = ServiceState.CRASHED
            return False
        return True


# ─── Service definitions ─────────────────────────────────────────────────────

def make_services() -> list[Service]:
    python = sys.executable  # use the same Python that's running this launcher

    backend = Service(
        name = "Backend",
        cmd  = [python, str(BACKEND_SCRIPT)],
        cwd  = BASE_DIR,
        env  = {"PYTHONUNBUFFERED": "1"},
    )

    # Frontend: prefer pre-built dist/index.cjs (production Node server)
    # Falls back to `npm run dev` if no dist present
    node = _find_node()
    if FRONTEND_DIST.exists() and node:
        frontend_cmd = [node, str(FRONTEND_DIST)]
        frontend_env = {"NODE_ENV": "production", "PORT": str(FRONTEND_PORT)}
    elif node:
        npm = _find_npm()
        frontend_cmd = [npm, "run", "dev"] if npm else [node, "node_modules/.bin/vite"]
        frontend_env = {"NODE_ENV": "development", "PORT": str(FRONTEND_PORT)}
    else:
        frontend_cmd = None
        frontend_env = None

    services = [backend]
    if frontend_cmd:
        services.append(Service(
            name = "Frontend",
            cmd  = frontend_cmd,
            cwd  = FRONTEND_DIR,
            env  = frontend_env,
        ))
    else:
        log.warning("Node.js not found — frontend service will not be started.")
        log.warning("Install Node.js from https://nodejs.org/ and re-run.")

    return services


def _find_node() -> str | None:
    import shutil
    return shutil.which("node")

def _find_npm() -> str | None:
    import shutil
    return shutil.which("npm")


# ─── Supervisor thread ────────────────────────────────────────────────────────
# Polls services every 2 s, restarts crashed ones with back-off.

MAX_RESTARTS  = 10
RESTART_DELAY = [2, 5, 10, 30, 60]  # seconds between successive restarts

class Supervisor:
    def __init__(self, services: list[Service]):
        self.services  = services
        self._stop_evt = threading.Event()
        self._thread   = threading.Thread(target=self._run, daemon=True, name="supervisor")

    def start_all(self):
        for svc in self.services:
            svc.start()
            time.sleep(0.5)  # stagger starts slightly
        self._thread.start()

    def stop_all(self):
        self._stop_evt.set()
        for svc in self.services:
            svc.stop()

    def _run(self):
        # Give services a moment to come up before first health check
        time.sleep(3)

        while not self._stop_evt.is_set():
            for svc in self.services:
                if svc.state == ServiceState.STOPPED:
                    continue
                alive = svc.check()
                if alive:
                    svc.state = ServiceState.RUNNING
                else:
                    if svc.restarts < MAX_RESTARTS:
                        delay = RESTART_DELAY[min(svc.restarts, len(RESTART_DELAY)-1)]
                        log.info(f"{svc.name}: restart #{svc.restarts+1} in {delay}s...")
                        time.sleep(delay)
                        svc.restarts += 1
                        svc.start()
                    else:
                        log.error(f"{svc.name}: exceeded max restarts ({MAX_RESTARTS}), giving up.")
                        svc.state = ServiceState.CRASHED

            self._stop_evt.wait(timeout=2)


# ─── System tray ─────────────────────────────────────────────────────────────

def build_tray_icon(supervisor: Supervisor):
    """
    Builds and returns a pystray Icon.  The menu shows live status for
    each service and provides Open, View Logs, Restart, and Quit actions.
    """
    try:
        import pystray
        from PIL import Image as PILImage, ImageDraw
    except ImportError:
        log.warning("pystray or pillow not installed — no tray icon.")
        log.warning("Run: pip install pystray pillow")
        return None

    def make_icon_image(color=(30, 180, 120)) -> "PILImage.Image":
        """Draw a small coloured circle as the tray icon."""
        size = 64
        img  = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
        dc   = ImageDraw.Draw(img)
        dc.ellipse([4, 4, size-4, size-4], fill=color)
        return img

    def status_color():
        states = {svc.state for svc in supervisor.services}
        if ServiceState.CRASHED in states:  return (220, 60, 60)
        if ServiceState.STARTING in states: return (220, 180, 0)
        if all(s == ServiceState.RUNNING for s in states): return (30, 180, 120)
        return (120, 120, 120)

    def update_icon(icon):
        icon.icon = make_icon_image(status_color())
        lines = ["RT Viewer"]
        for svc in supervisor.services:
            symbol = ServiceState.ICONS.get(svc.state, "?")
            lines.append(f"  {symbol} {svc.name}  (restarts: {svc.restarts})")
        icon.title = "\n".join(lines)

    def on_open(icon, item):
        webbrowser.open(BROWSER_URL)

    def on_open_logs(icon, item):
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))
        else:
            subprocess.Popen(["xdg-open", str(LOG_DIR)])

    def on_restart_backend(icon, item):
        svc = next((s for s in supervisor.services if s.name == "Backend"), None)
        if svc:
            svc.stop()
            time.sleep(1)
            svc.restarts = 0
            svc.start()

    def on_restart_frontend(icon, item):
        svc = next((s for s in supervisor.services if s.name == "Frontend"), None)
        if svc:
            svc.stop()
            time.sleep(1)
            svc.restarts = 0
            svc.start()

    def on_quit(icon, item):
        log.info("Quit requested via tray menu.")
        icon.stop()
        supervisor.stop_all()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open RT Viewer in Browser", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart Backend",  on_restart_backend),
        pystray.MenuItem("Restart Frontend", on_restart_frontend),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("View Logs Folder", on_open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon(
        name  = "RTViewer",
        icon  = make_icon_image(),
        title = "RT Viewer",
        menu  = menu,
    )

    # Background thread to keep the icon colour updated
    def _updater():
        while True:
            try:
                update_icon(icon)
            except Exception:
                pass
            time.sleep(2)

    threading.Thread(target=_updater, daemon=True, name="tray-updater").start()
    return icon


# ─── Console-only fallback (no tray) ─────────────────────────────────────────

def run_console(supervisor: Supervisor):
    """Blocking loop for headless / no-tray environments."""
    log.info("Running in console mode. Press Ctrl+C to stop.")
    log.info(f"Frontend: {BROWSER_URL}")
    try:
        while True:
            time.sleep(5)
            parts = []
            for svc in supervisor.services:
                parts.append(f"{svc.name}={svc.state}")
            log.info("Status: " + "  |  ".join(parts))
    except KeyboardInterrupt:
        log.info("Stopping...")
        supervisor.stop_all()


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    log.info(f"RT Viewer Launcher starting — base dir: {BASE_DIR}")
    log.info(f"Log dir: {LOG_DIR}")

    services   = make_services()
    supervisor = Supervisor(services)
    supervisor.start_all()

    # Small delay then open browser
    def _open_browser():
        time.sleep(3)
        log.info(f"Opening browser: {BROWSER_URL}")
        webbrowser.open(BROWSER_URL)
    threading.Thread(target=_open_browser, daemon=True).start()

    # Try tray icon first, fall back to console
    icon = build_tray_icon(supervisor)
    if icon:
        log.info("System tray icon active. Right-click the tray icon to manage services.")
        icon.run()  # blocks until icon.stop() is called
    else:
        run_console(supervisor)


if __name__ == "__main__":
    main()
