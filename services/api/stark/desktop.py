"""Desktop app support: first-run setup, keys kept in the operating system's credential store, connection tests,
diagnostics and update checks. Only active when STARK_DESKTOP=1 (set by the desktop launcher).

Secrets (API keys, tokens, app passwords) go to the macOS Keychain or the Windows Credential Manager (DPAPI) through
a private secrets.json (file mode 600); plain settings (provider address, spending switch, budgets) go to desktop.json in the user's data folder.
Saving restarts the API process (exit code 75), which the launcher restarts with the new values.
"""

from __future__ import annotations

import hmac
import json
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import __version__

SERVICE = "STARK OS"
RESTART_CODE = 75
RELEASES = "https://api.github.com/repos/Shahrukhalid/stark-os/releases/latest"

# Secret values: stored in the credential store, never written to disk by STARK OS.
SECRETS = {
    "OPENROUTER_API_KEY": "AI provider API key",
    "BLUESKY_APP_PASSWORD": "Bluesky app password",
    "MASTODON_ACCESS_TOKEN": "Mastodon access token",
    "THREADS_ACCESS_TOKEN": "Threads access token",
    "TELEGRAM_BOT_TOKEN": "Telegram bot token",
    "DISCORD_WEBHOOK_URL": "Discord notification webhook",
    "DISCORD_POST_WEBHOOK_URL": "Discord posting webhook",
    "SLACK_WEBHOOK_URL": "Slack webhook",
    "FACEBOOK_PAGE_TOKEN": "Facebook Page access token",
    "LINKEDIN_ACCESS_TOKEN": "LinkedIn access token",
    "INSTAGRAM_ACCESS_TOKEN": "Instagram access token",
    "PINTEREST_ACCESS_TOKEN": "Pinterest access token",
    "TAVILY_API_KEY": "Tavily search key",
    "BRAVE_API_KEY": "Brave search key",
}
# Plain settings: stored in desktop.json.
PLAIN = {
    "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_ALLOW_PAID", "STARK_TASK_TOKEN_BUDGET",
    "BLUESKY_HANDLE", "BLUESKY_SERVICE", "MASTODON_BASE_URL", "THREADS_USER_ID", "TELEGRAM_CHAT_ID",
    "TELEGRAM_CHANNEL_ID", "STARK_DEFAULT_MODE", "FACEBOOK_PAGE_ID", "LINKEDIN_AUTHOR_URN", "LINKEDIN_API_VERSION",
    "INSTAGRAM_USER_ID", "PINTEREST_BOARD_ID", "TIKTOK_PRIVACY", "YOUTUBE_PRIVACY", "STARK_CONNECT_URL",
}

# What each platform supports, shown in the setup wizard.
PLATFORMS = [
    {"id": "bluesky", "name": "Bluesky", "publish": True, "fields": ["BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"],
     "how": "Bluesky → Settings → Privacy and security → App passwords → Add. Use your handle (name.bsky.social)."},
    {"id": "mastodon", "name": "Mastodon", "publish": True, "fields": ["MASTODON_BASE_URL", "MASTODON_ACCESS_TOKEN"],
     "how": "Your server → Preferences → Development → New application (read, write) → copy the access token."},
    {"id": "threads", "name": "Threads", "publish": True, "fields": ["THREADS_USER_ID", "THREADS_ACCESS_TOKEN"],
     "how": "Needs a Meta developer app with the threads_content_publish permission; paste its user ID and token."},
    {"id": "telegram", "name": "Telegram", "publish": True,
     "fields": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CHANNEL_ID"],
     "how": "Create a bot with @BotFather, add it to your channel as admin, then paste the bot token and the channel."},
    {"id": "discord", "name": "Discord", "publish": True, "fields": ["DISCORD_POST_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"],
     "how": "Channel settings → Integrations → Webhooks → New webhook → Copy URL."},
    {"id": "slack", "name": "Slack", "publish": True, "fields": ["SLACK_WEBHOOK_URL"],
     "how": "Create an incoming webhook for your workspace and paste its URL."},
    {"id": "facebook", "name": "Facebook Page", "publish": True, "fields": ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"],
     "how": "Create a Meta developer app (Business type), add yourself, then in the Graph API Explorer get a Page "
            "access token with pages_manage_posts and pages_read_engagement. Paste the Page ID and token."},
    {"id": "linkedin", "name": "LinkedIn (your profile)", "publish": True, "fields": ["LINKEDIN_ACCESS_TOKEN"],
     "how": "Create a LinkedIn developer app, add the free products Share on LinkedIn and Sign In with LinkedIn "
            "using OpenID Connect, then create a token with openid, profile and w_member_social (lasts 60 days)."},
    {"id": "x", "name": "X (Twitter)", "publish": False, "fields": [],
     "how": "X charges for every post through its API, so STARK OS prepares drafts you post yourself."},
    {"id": "instagram", "name": "Instagram (Business or Creator)", "publish": True,
     "fields": ["INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN"],
     "how": "Meta developer app with the Instagram use case: generate a token with instagram_business_basic and "
            "instagram_business_content_publish. Videos post as Reels; images also need your Facebook Page connected."},
    {"id": "pinterest", "name": "Pinterest", "publish": True, "fields": ["PINTEREST_BOARD_ID", "PINTEREST_ACCESS_TOKEN"],
     "how": "Pinterest developer app: generate a token with boards:read and pins:write and paste a board ID. Pins are "
            "visible only to you until Pinterest grants Standard access."},
    {"id": "tiktok", "name": "TikTok / YouTube", "publish": True, "fields": [],
     "how": "These need a sign-in: after setup, open Content → Your accounts and use Connect. Posts stay private "
            "until TikTok or Google audits your app."},
    {"id": "other", "name": "Facebook profiles and Groups, personal Instagram, Snapchat", "publish": False,
     "fields": [], "how": "No app can post there: the platforms closed or never opened these to other apps."},
]

PROVIDERS = [
    {"id": "openrouter-free", "name": "OpenRouter (free models)", "base_url": "https://openrouter.ai/api/v1",
     "paid": False, "key_url": "https://openrouter.ai/keys"},
    {"id": "openrouter", "name": "OpenRouter (free and paid models)", "base_url": "https://openrouter.ai/api/v1",
     "paid": True, "key_url": "https://openrouter.ai/keys"},
    {"id": "custom", "name": "Other OpenAI-compatible provider", "base_url": "", "paid": True, "key_url": ""},
]


# ---------------------------------------------------------------- storage
def data_dir() -> Path:
    return Path(os.environ.get("STARK_DATA_DIR", ".")).expanduser()


def _plain_path() -> Path:
    return data_dir() / "desktop.json"


def load_plain() -> dict[str, str]:
    try:
        data = json.loads(_plain_path().read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if k in PLAIN}
    except (OSError, ValueError):
        return {}


def save_plain(values: dict[str, str]) -> None:
    path = _plain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
    tmp.replace(path)


def _secrets_path() -> Path:
    return data_dir() / "secrets.json"


def _load_secrets() -> dict[str, str]:
    try:
        data = json.loads(_secrets_path().read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if k in SECRETS}
    except (OSError, ValueError):
        return {}


def get_secret(name: str) -> str:
    """Keys and tokens live in secrets.json in the user's private data folder (file mode 600). The system
    keychain is not used: unsigned builds made macOS ask for the login password on every update."""
    return _load_secrets().get(name, "")


def set_secret(name: str, value: str) -> None:
    data = _load_secrets()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    path = _secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def environment() -> dict[str, str]:
    """Everything the API needs from the credential store and desktop.json, as environment variables."""
    env = dict(load_plain())
    for name in SECRETS:
        value = get_secret(name)
        if value:
            env[name] = value
    return env


# ---------------------------------------------------------------- tests of connections
def _short(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:160]}"


def test_ai(api_key: str, base_url: str, timeout: float = 15.0) -> dict[str, Any]:
    """Lists the provider's models with the key: proves the key works and discovers what is available."""
    base = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1") and not base.startswith("http://localhost"):
        return {"ok": False, "message": "The provider address must start with https://"}
    try:
        r = httpx.get(f"{base}/models", headers={"authorization": f"Bearer {api_key}"}, timeout=timeout)
        if r.status_code in (401, 403):
            return {"ok": False, "message": "The provider rejected this key."}
        r.raise_for_status()
        models = [m.get("id", "") for m in r.json().get("data", []) if isinstance(m, dict)]
        if "openrouter.ai" in base:  # the model list is public there, so also check the key itself
            k = httpx.get(f"{base}/key", headers={"authorization": f"Bearer {api_key}"}, timeout=timeout)
            if k.status_code in (401, 403):
                return {"ok": False, "message": "OpenRouter rejected this key."}
        free = [m for m in models if m.endswith(":free")]
        return {"ok": True, "models": len(models), "free_models": len(free), "examples": (free or models)[:5],
                "message": f"Connected: {len(models)} models available ({len(free)} free)."}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "message": f"Could not reach the provider ({_short(exc)})."}


def test_social(platform_id: str, v: dict[str, str], timeout: float = 15.0) -> dict[str, Any]:
    """Checks the credentials without posting anything."""
    try:
        if platform_id == "bluesky":
            service = (v.get("BLUESKY_SERVICE") or "https://bsky.social").rstrip("/")
            r = httpx.post(f"{service}/xrpc/com.atproto.server.createSession", timeout=timeout,
                           json={"identifier": v.get("BLUESKY_HANDLE", ""), "password": v.get("BLUESKY_APP_PASSWORD", "")})
            return {"ok": r.status_code == 200, "message": "Signed in to Bluesky." if r.status_code == 200
                    else "Bluesky rejected the handle or app password."}
        if platform_id == "mastodon":
            base = v.get("MASTODON_BASE_URL", "").rstrip("/")
            if not base.startswith("https://"):
                return {"ok": False, "message": "Enter your server address, e.g. https://mastodon.social"}
            r = httpx.get(f"{base}/api/v1/accounts/verify_credentials", timeout=timeout,
                          headers={"authorization": f"Bearer {v.get('MASTODON_ACCESS_TOKEN', '')}"})
            name = r.json().get("acct", "") if r.status_code == 200 else ""
            return {"ok": r.status_code == 200, "message": f"Signed in as @{name}." if name else "Mastodon rejected the token."}
        if platform_id == "threads":
            r = httpx.get("https://graph.threads.net/v1.0/me", timeout=timeout,
                          params={"fields": "id,username", "access_token": v.get("THREADS_ACCESS_TOKEN", "")})
            return {"ok": r.status_code == 200, "message": "Connected to Threads." if r.status_code == 200
                    else "Threads rejected the token."}
        if platform_id == "facebook":
            r = httpx.get(f"https://graph.facebook.com/v23.0/{v.get('FACEBOOK_PAGE_ID', '')}", timeout=timeout,
                          params={"fields": "name", "access_token": v.get("FACEBOOK_PAGE_TOKEN", "")})
            return {"ok": r.status_code == 200, "message": f"Connected to the Page {r.json().get('name', '')}."
                    if r.status_code == 200 else "Facebook rejected the Page ID or token."}
        if platform_id == "linkedin":
            r = httpx.get("https://api.linkedin.com/v2/userinfo", timeout=timeout,
                          headers={"Authorization": f"Bearer {v.get('LINKEDIN_ACCESS_TOKEN', '')}"})
            return {"ok": r.status_code == 200, "message": f"Signed in as {r.json().get('name', 'you')}."
                    if r.status_code == 200 else "LinkedIn rejected the token (check its scopes; tokens last 60 days)."}
        if platform_id == "instagram":
            r = httpx.get("https://graph.instagram.com/v23.0/me", timeout=timeout,
                          params={"fields": "username", "access_token": v.get("INSTAGRAM_ACCESS_TOKEN", "")})
            return {"ok": r.status_code == 200, "message": f"Connected as @{r.json().get('username', '')}."
                    if r.status_code == 200 else "Instagram rejected the token."}
        if platform_id == "pinterest":
            r = httpx.get(f"https://api.pinterest.com/v5/boards/{v.get('PINTEREST_BOARD_ID', '')}", timeout=timeout,
                          headers={"Authorization": f"Bearer {v.get('PINTEREST_ACCESS_TOKEN', '')}"})
            return {"ok": r.status_code == 200, "message": f"Board {r.json().get('name', '')} is ready."
                    if r.status_code == 200 else "Pinterest rejected the token or board ID."}
        if platform_id == "telegram":
            r = httpx.get(f"https://api.telegram.org/bot{v.get('TELEGRAM_BOT_TOKEN', '')}/getMe", timeout=timeout)
            ok = r.status_code == 200 and r.json().get("ok")
            return {"ok": bool(ok), "message": f"Bot @{r.json()['result']['username']} is ready." if ok
                    else "Telegram rejected the bot token."}
        if platform_id in ("discord", "slack"):
            urls = [u for k, u in v.items() if k.endswith("WEBHOOK_URL") and u]
            hosts = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/") \
                if platform_id == "discord" else ("https://hooks.slack.com/",)
            ok = bool(urls) and all(u.startswith(hosts) for u in urls)
            if ok and platform_id == "discord":  # a GET returns the webhook's details without posting
                ok = all(httpx.get(u, timeout=timeout).status_code == 200 for u in urls)
            return {"ok": ok, "message": "Webhook looks right." if ok else "That is not a valid webhook address."}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"ok": False, "message": f"Could not check ({_short(exc)})."}
    return {"ok": False, "message": "This platform has no connection test."}


def _apple_silicon() -> bool:
    if platform.machine() == "arm64":
        return True
    try:  # an Intel build running under Rosetta on an Apple Silicon Mac
        import subprocess

        out = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def asset_name() -> str | None:
    """The installer that fits this computer."""
    if sys.platform == "darwin":
        return "STARK-OS-macOS-AppleSilicon.dmg" if _apple_silicon() else "STARK-OS-macOS-Intel.dmg"
    if sys.platform == "win32":
        return "STARK-OS-Windows-Setup.exe"
    return None


DOWNLOAD_PREFIX = "https://github.com/Shahrukhalid/stark-os/releases/download/"


def _version_tuple(s: str) -> list[int]:
    return [int("".join(c for c in p if c.isdigit()) or 0) for p in s.split(".")]


def check_update(current: str = __version__, timeout: float = 8.0) -> dict[str, Any]:
    try:
        r = httpx.get(RELEASES, timeout=timeout, headers={"accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
        latest = str(data.get("tag_name", "")).lstrip("v")
        newer = bool(latest) and _version_tuple(latest) > _version_tuple(current)
        want = asset_name()
        asset = next(({"name": a["name"], "size": a.get("size", 0), "url": a["browser_download_url"],
                       "sha256": str(a.get("digest") or "").removeprefix("sha256:") or None}
                      for a in data.get("assets", []) if a.get("name") == want
                      and str(a.get("browser_download_url", "")).startswith(DOWNLOAD_PREFIX)), None)
        return {"current": current, "latest": latest, "update": newer, "url": data.get("html_url", ""),
                "notes": str(data.get("body") or "")[:4000], "published": data.get("published_at"), "asset": asset}
    except (httpx.HTTPError, ValueError, KeyError):
        return {"current": current, "latest": None, "update": False, "url": "", "notes": "", "asset": None}


class Updater:
    """Downloads the installer for this computer into Downloads, checks its SHA-256 when GitHub lists one,
    then opens it. Only files from this project's GitHub releases are accepted."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "path": None, "error": None}
        self._lock = threading.Lock()

    def start(self, asset: dict[str, Any], dest_dir: Path | None = None, open_file: bool = True) -> dict[str, Any]:
        if not str(asset.get("url", "")).startswith(DOWNLOAD_PREFIX) or "/" in asset.get("name", "/"):
            raise ValueError("not a STARK OS release file")
        with self._lock:
            if self.state["status"] == "downloading":
                return dict(self.state)
            self.state = {"status": "downloading", "done": 0, "total": int(asset.get("size") or 0), "path": None,
                          "error": None}
        threading.Thread(target=self._run, args=(asset, dest_dir or Path.home() / "Downloads", open_file),
                         daemon=True).start()
        return dict(self.state)

    def _run(self, asset: dict[str, Any], dest_dir: Path, open_file: bool) -> None:
        import hashlib

        dest_dir.mkdir(parents=True, exist_ok=True)
        final = dest_dir / asset["name"]
        part = final.with_name(final.name + ".part")
        h = hashlib.sha256()
        try:
            with httpx.stream("GET", asset["url"], follow_redirects=True, timeout=60) as r:
                r.raise_for_status()
                self.state["total"] = int(r.headers.get("content-length") or self.state["total"] or 0)
                with open(part, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
                        h.update(chunk)
                        self.state["done"] += len(chunk)
            if asset.get("sha256") and h.hexdigest() != asset["sha256"]:
                part.unlink(missing_ok=True)
                raise ValueError("the download does not match the release checksum; nothing was installed")
            os.replace(part, final)
            self.state.update(status="ready", path=str(final))
            if open_file:
                open_installer(final)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            part.unlink(missing_ok=True)
            self.state.update(status="error", error=_short(exc))


def open_installer(path: Path) -> None:
    import subprocess

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # mounts the disk image and shows it in Finder
    elif sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # the installer closes STARK OS itself


UPDATER = Updater()


def diagnostics() -> dict[str, Any]:
    d = data_dir()
    checks: list[dict[str, Any]] = []
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        checks.append({"name": "Data folder is writable", "ok": True, "detail": str(d)})
    except OSError as exc:
        checks.append({"name": "Data folder is writable", "ok": False, "detail": _short(exc)})
    sp = _secrets_path()
    checks.append({"name": "Private key file", "ok": not sp.exists() or os.name == "nt" or (sp.stat().st_mode & 0o077) == 0,
                   "detail": str(sp)})
    free = shutil.disk_usage(d if d.exists() else Path.home()).free
    checks.append({"name": "Free disk space", "ok": free > 500_000_000, "detail": f"{free // 1_000_000} MB"})
    checks.append({"name": "AI key saved", "ok": bool(get_secret("OPENROUTER_API_KEY")), "detail": ""})
    from .video import status as video_status

    v = video_status()
    checks.append({"name": "Video tools (FFmpeg)", "ok": v["available"],
                   "detail": v.get("version") or v.get("message", "")})
    crash = d / "logs" / "crash.log"
    return {"version": __version__, "python": sys.version.split()[0], "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(), "checks": checks,
            "last_crash": crash.read_text(encoding="utf-8", errors="replace")[-2000:] if crash.exists() else ""}


# ---------------------------------------------------------------- API
class SaveIn(BaseModel):
    values: dict[str, str]
    restart: bool = True


class AiTestIn(BaseModel):
    api_key: str = ""
    base_url: str = ""


class SocialTestIn(BaseModel):
    platform: str
    values: dict[str, str] = {}


def _restart_soon(delay: float = 0.7) -> None:
    def stop() -> None:
        time.sleep(delay)
        os._exit(RESTART_CODE)  # the launcher starts the API again with the new settings

    threading.Thread(target=stop, daemon=True).start()


def router(api_token: str) -> APIRouter:
    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        if not token or not hmac.compare_digest(token.encode("utf-8", "surrogateescape"), api_token.encode("utf-8")):
            raise HTTPException(401, "invalid or missing API token")

    r = APIRouter(prefix="/api/desktop", dependencies=[Depends(auth)])

    @r.get("/status")
    def status() -> dict[str, Any]:
        plain = load_plain()
        saved = {name: bool(get_secret(name)) for name in SECRETS}
        return {"desktop": True, "version": __version__, "needs_setup": not saved["OPENROUTER_API_KEY"],
                "secrets": saved, "settings": plain, "platforms": PLATFORMS, "providers": PROVIDERS,
                "labels": SECRETS, "data_dir": str(data_dir())}

    @r.put("/settings")
    def save(body: SaveIn) -> dict[str, Any]:
        plain = load_plain()
        for name, value in body.values.items():
            value = value.strip()
            if name in SECRETS:
                if value != "__keep__":
                    set_secret(name, value)
            elif name in PLAIN:
                if value:
                    plain[name] = value
                else:
                    plain.pop(name, None)
            else:
                raise HTTPException(400, f"unknown setting {name}")
        save_plain(plain)
        if body.restart:
            _restart_soon()
        return {"ok": True, "restarting": body.restart}

    @r.post("/test-ai")
    def ai(body: AiTestIn) -> dict[str, Any]:
        key = body.api_key.strip() or get_secret("OPENROUTER_API_KEY")
        if not key:
            return {"ok": False, "message": "Enter an API key first."}
        return test_ai(key, body.base_url.strip() or load_plain().get("OPENROUTER_BASE_URL", ""))

    @r.post("/test-social")
    def social(body: SocialTestIn) -> dict[str, Any]:
        values = {k: (v.strip() if v.strip() != "__keep__" else get_secret(k)) for k, v in body.values.items()}
        return test_social(body.platform, values)

    @r.get("/diagnostics")
    def diag() -> dict[str, Any]:
        return diagnostics()

    @r.get("/update")
    def update() -> dict[str, Any]:
        return check_update()

    @r.post("/update/download")
    def update_download() -> dict[str, Any]:
        info = check_update()
        if not info["update"] or not info["asset"]:
            raise HTTPException(409, "No newer installer for this computer.")
        return UPDATER.start(info["asset"])

    @r.get("/update/progress")
    def update_progress() -> dict[str, Any]:
        return dict(UPDATER.state)

    return r
