"""Desktop app support: first-run setup, keys kept in the operating system's credential store, connection tests,
diagnostics and update checks. Only active when STARK_DESKTOP=1 (set by the desktop launcher).

Secrets (API keys, tokens, app passwords) go to the macOS Keychain or the Windows Credential Manager (DPAPI) through
`keyring`; plain settings (provider address, spending switch, budgets) go to desktop.json in the user's data folder.
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
    "TAVILY_API_KEY": "Tavily search key",
    "BRAVE_API_KEY": "Brave search key",
}
# Plain settings: stored in desktop.json.
PLAIN = {
    "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_ALLOW_PAID", "STARK_TASK_TOKEN_BUDGET",
    "BLUESKY_HANDLE", "BLUESKY_SERVICE", "MASTODON_BASE_URL", "THREADS_USER_ID", "TELEGRAM_CHAT_ID",
    "TELEGRAM_CHANNEL_ID", "STARK_DEFAULT_MODE",
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
    {"id": "x", "name": "X (Twitter)", "publish": False, "fields": [],
     "how": "Publishing needs a paid developer plan, so STARK OS prepares drafts you post yourself."},
    {"id": "linkedin", "name": "LinkedIn", "publish": False, "fields": [],
     "how": "Posting needs a LinkedIn partner app, so STARK OS prepares drafts you post yourself."},
    {"id": "instagram", "name": "Instagram / Facebook", "publish": False, "fields": [],
     "how": "Publishing needs a reviewed Meta business app, so STARK OS prepares drafts and images for you."},
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


def _keyring():
    import keyring

    return keyring


def get_secret(name: str) -> str:
    try:
        return _keyring().get_password(SERVICE, name) or ""
    except Exception:  # noqa: BLE001 - a locked or missing credential store must not stop the app
        return ""


def set_secret(name: str, value: str) -> None:
    kr = _keyring()
    if value:
        kr.set_password(SERVICE, name, value)
    else:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:  # noqa: BLE001 - nothing stored
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


def check_update(current: str = __version__, timeout: float = 8.0) -> dict[str, Any]:
    try:
        r = httpx.get(RELEASES, timeout=timeout, headers={"accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
        latest = str(data.get("tag_name", "")).lstrip("v")

        def parts(s: str) -> list[int]:
            return [int("".join(c for c in p if c.isdigit()) or 0) for p in s.split(".")]

        newer = bool(latest) and parts(latest) > parts(current)
        return {"current": current, "latest": latest, "update": newer, "url": data.get("html_url", "")}
    except (httpx.HTTPError, ValueError):
        return {"current": current, "latest": None, "update": False, "url": ""}


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
    try:
        backend = _keyring().get_keyring()
        checks.append({"name": "Credential store", "ok": "fail" not in type(backend).__name__.lower(),
                       "detail": type(backend).__name__})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "Credential store", "ok": False, "detail": _short(exc)})
    free = shutil.disk_usage(d if d.exists() else Path.home()).free
    checks.append({"name": "Free disk space", "ok": free > 500_000_000, "detail": f"{free // 1_000_000} MB"})
    checks.append({"name": "AI key saved", "ok": bool(get_secret("OPENROUTER_API_KEY")), "detail": ""})
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

    return r
