"""STARK OS desktop app.

Opens a native window with the dashboard and runs the API in a background process that nobody has to start or see.

    stark_desktop.py            the app (window + API process it manages)
    stark_desktop.py --backend  the API process itself (started by the app)

Everything lives in the user's own data folder (macOS: ~/Library/Application Support/STARK OS, Windows:
%LOCALAPPDATA%\\STARK OS). The API token for the window and every key the user enters are kept in the macOS
Keychain / Windows Credential Manager, never in files.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

APP = "STARK OS"
FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
RESTART_CODE = 75
MAX_CRASHES = 5          # restarts allowed within CRASH_WINDOW before giving up
CRASH_WINDOW = 300
INSTANCE_PORT = 47821    # local-only: a second launch asks the running app to come to the front instead
HELLO, ACK = b"STARK-OS-SHOW\n", b"STARK-OS-OK\n"


def resource(*parts: str) -> Path:
    """Bundled files: next to the code when frozen, the repository layout when run from source."""
    if FROZEN:
        return BUNDLE.joinpath(*parts)
    root = Path(__file__).resolve().parent.parent
    mapping = {"agents": root / "agents", "web": root / "apps" / "web" / "out"}
    return mapping.get(parts[0], root / parts[0]).joinpath(*parts[1:])


def data_dir() -> Path:
    override = os.environ.get("STARK_DESKTOP_DATA")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "stark-os"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def api_token() -> str:
    """One random token per computer, kept in the credential store (falls back to a private file)."""
    try:
        import keyring

        token = keyring.get_password(APP, "STARK_API_TOKEN")
        if not token:
            token = secrets.token_urlsafe(32)
            keyring.set_password(APP, "STARK_API_TOKEN", token)
        return token
    except Exception:  # noqa: BLE001 - no credential store (e.g. some Linux desktops)
        path = data_dir() / ".token"
        if path.exists():
            return path.read_text().strip()
        token = secrets.token_urlsafe(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token)
        os.chmod(path, 0o600)
        return token


def backend_env(port: int, token: str) -> dict[str, str]:
    data = data_dir()
    sandbox = data / "workspace"
    for p in (data, sandbox, data / "logs"):
        p.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if FROZEN:  # never inherit a developer's .env or keys when running the packaged app
        for k in [k for k in env if k.startswith(("OPENROUTER_", "BLUESKY_", "MASTODON_", "THREADS_", "TELEGRAM_",
                                                    "DISCORD_", "SLACK_", "STARK_"))]:
            env.pop(k)
    env.update({
        "STARK_DESKTOP": "1", "STARK_API_TOKEN": token, "STARK_HOST": "127.0.0.1", "STARK_PORT": str(port),
        "STARK_WEB_ORIGIN": f"http://127.0.0.1:{port}", "STARK_DATA_DIR": str(data),
        "STARK_AGENTS_DIR": str(resource("agents")), "STARK_WORKSPACE_ROOTS": str(sandbox),
        "STARK_WEB_DIR": str(resource("web")), "PYTHONUNBUFFERED": "1",
    })
    return env


# ---------------------------------------------------------------- the API process
def run_backend() -> None:
    import uvicorn

    sys.path.insert(0, str(BUNDLE / "services" / "api")) if not FROZEN else None
    from stark import desktop
    from stark.config import Settings
    from stark.main import create_app

    os.environ.update(desktop.environment())  # keys from the credential store, settings from desktop.json
    settings = Settings.from_env()
    app = create_app(settings)
    app.include_router(desktop.router(settings.api_token))
    web = Path(os.environ.get("STARK_WEB_DIR", ""))
    if web.is_dir():
        from fastapi.staticfiles import StaticFiles

        @app.middleware("http")
        async def security_headers(request, call_next):  # the same headers the web server sends
            response = await call_next(request)
            if not request.url.path.startswith("/api/"):
                response.headers.setdefault("Content-Security-Policy",
                                            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' "
                                            "'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; "
                                            "connect-src 'self'; media-src 'self' blob:; object-src 'none'; "
                                            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
                response.headers.setdefault("X-Content-Type-Options", "nosniff")
                response.headers.setdefault("Referrer-Policy", "no-referrer")
            return response

        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", access_log=False)


# ---------------------------------------------------------------- one app at a time
class SingleInstance:
    """Holds a local port while the app runs. A second launch finds it taken, asks the first app to show its window
    and exits, so two engines never share one database. If the port belongs to something else, the app just runs."""

    def __init__(self, port: int = INSTANCE_PORT) -> None:
        self.port = port
        self.sock: socket.socket | None = None
        self.on_show = lambda: None

    def acquire(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        try:
            s.bind(("127.0.0.1", self.port))
            s.listen(4)
        except OSError:
            s.close()
            return not self.notify_running()
        self.sock = s
        threading.Thread(target=self._serve, daemon=True).start()
        return True

    def notify_running(self) -> bool:
        """True when a STARK OS app answered on the port (and was asked to show itself)."""
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=2) as c:
                c.sendall(HELLO)
                return c.recv(32) == ACK
        except OSError:
            return False

    def _serve(self) -> None:
        while self.sock is not None:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    if conn.recv(32) == HELLO:
                        conn.sendall(ACK)
                        self.on_show()
                except OSError:
                    pass

    def release(self) -> None:
        if self.sock is not None:
            s, self.sock = self.sock, None
            s.close()


# ---------------------------------------------------------------- the app
class Backend:
    """Starts, watches and stops the API process. Restarts it after a settings change or a crash."""

    def __init__(self) -> None:
        self.port = free_port()
        self.token = api_token()
        self.proc: subprocess.Popen | None = None
        self.stopping = False
        self.crashes: list[float] = []
        self.failed = ""
        self.log = data_dir() / "logs" / "backend.log"

    def command(self) -> list[str]:
        return [sys.executable, "--backend"] if FROZEN else [sys.executable, str(Path(__file__).resolve()), "--backend"]

    def start(self) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        out = open(self.log, "ab")  # noqa: SIM115 - kept open for the child's lifetime
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no console window
        self.proc = subprocess.Popen(self.command(), env=backend_env(self.port, self.token), stdout=out,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)

    def url(self, path: str = "") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def wait_ready(self, timeout: float = 90) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.proc and self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(self.url("/api/health"), timeout=2) as r:
                    if r.status == 200:
                        return True
            except OSError:
                pass
            time.sleep(0.4)
        return False

    def watch(self) -> None:
        while not self.stopping:
            code = self.proc.wait() if self.proc else 0
            if self.stopping:
                return
            if code != RESTART_CODE:
                now = time.time()
                self.crashes = [t for t in self.crashes if now - t < CRASH_WINDOW] + [now]
                with open(data_dir() / "logs" / "crash.log", "a", encoding="utf-8") as fh:
                    fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} API stopped with code {code}; restarting\n")
                if len(self.crashes) > MAX_CRASHES:
                    self.failed = f"The STARK OS engine keeps stopping. Details: {self.log}"
                    return
                time.sleep(1)
            self.start()

    def stop(self) -> None:
        self.stopping = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def error_page(message: str) -> str:
    from html import escape

    return (f"<html><body style='font-family:-apple-system,Segoe UI,sans-serif;background:#0b0f17;color:#e6edf3;"
            f"padding:40px'><h2>STARK OS could not start</h2><p>{escape(message)}</p>"
            f"<p>Log files: {escape(str(data_dir() / 'logs'))}</p></body></html>")


def run_app() -> None:
    import webview

    instance = SingleInstance()
    if not instance.acquire():
        return  # STARK OS is already open; its window was brought to the front
    backend = Backend()
    backend.start()
    window = webview.create_window(APP, html="<body style='background:#0b0f17'></body>", width=1440, height=920,
                                   min_size=(1024, 680), background_color="#0b0f17")

    def boot() -> None:
        if backend.wait_ready():
            threading.Thread(target=backend.watch, daemon=True).start()
            # The token travels in the address fragment: it never reaches a server log and is removed at once.
            window.load_url(backend.url(f"/?desktop=1#stark-token={backend.token}"))
        else:
            window.load_html(error_page(f"The engine did not start. Details: {backend.log}"))

    def show() -> None:
        for step in (window.restore, window.show):
            try:
                step()
            except Exception:  # noqa: BLE001 - not every platform supports both
                pass

    instance.on_show = show
    window.events.closed += backend.stop
    try:
        webview.start(boot, private_mode=False, storage_path=str(data_dir() / "webview"))
    finally:
        backend.stop()
        instance.release()


def single_instance_check() -> bool:
    port = free_port()
    first, second = SingleInstance(port), SingleInstance(port)
    shown: list[bool] = []
    first.on_show = lambda: shown.append(True)
    try:
        if not first.acquire() or second.acquire():
            return False
        time.sleep(0.2)
        return shown == [True]
    finally:
        first.release()
        second.release()


def video_check() -> str:
    """The bundled FFmpeg makes a 1-second clip and reads it back ("" = fine, else what failed)."""
    import tempfile

    if not FROZEN:
        sys.path.insert(0, str(BUNDLE / "services" / "api"))
    from stark import video

    exe = video.ffmpeg_path()
    if not exe:
        return "FFmpeg not found"
    with tempfile.TemporaryDirectory() as tmp:
        res = video.self_check(exe, Path(tmp))
    print("self-test: video", {**video.status(), **res})
    if not res["ok"]:
        return res["error"]
    if not res["transcribe"]:
        return "speech-to-text (whisper.cpp) is not bundled"
    return ""


def self_test() -> int:
    """Used by the release build: start the engine without a window, check the API and the dashboard, stop."""
    if not single_instance_check():
        print("self-test: single-instance guard failed")
        return 1
    problem = video_check()
    if problem:
        print("self-test: video studio:", problem)
        return 1
    backend = Backend()
    backend.start()
    try:
        if not backend.wait_ready(120):
            print("engine did not start; log:\n" + backend.log.read_text(errors="replace")[-3000:])
            return 1
        with urllib.request.urlopen(backend.url("/"), timeout=10) as r:
            page = r.read().decode("utf-8", "replace")
        ok = "STARK" in page
        print("self-test:", "OK" if ok else "dashboard missing")
        return 0 if ok else 1
    finally:
        backend.stop()


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--backend" in sys.argv:
        try:
            run_backend()
        except Exception:  # noqa: BLE001 - recorded for the diagnostics page, then the app restarts the API
            (data_dir() / "logs").mkdir(parents=True, exist_ok=True)
            with open(data_dir() / "logs" / "crash.log", "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
            raise
        return
    run_app()


if __name__ == "__main__":
    if FROZEN and sys.platform == "win32":
        import multiprocessing

        multiprocessing.freeze_support()
    main()
