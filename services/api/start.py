"""Initialize a persistent API token before starting STARK AI."""

import fcntl
import os
import secrets
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("STARK_DATA_DIR", "/app/data"))
TOKEN_FILE = DATA_DIR / "api-token"
LOCK_FILE = DATA_DIR / "api-token.lock"


def get_api_token() -> str:
    configured = os.environ.get("STARK_API_TOKEN", "").strip()
    if configured:
        return configured

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(LOCK_FILE, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if len(token) >= 24:
                return token

        token = secrets.token_urlsafe(32)
        temporary_file = DATA_DIR / f".api-token-{os.getpid()}"

        try:
            fd = os.open(
                temporary_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(token + "\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_file, TOKEN_FILE)
        finally:
            temporary_file.unlink(missing_ok=True)

        print("Generated a persistent STARK API token.")
        return token


def main() -> None:
    token = get_api_token()

    if len(token) < 24:
        raise RuntimeError("STARK_API_TOKEN must be at least 24 characters")

    os.environ["STARK_API_TOKEN"] = token
    os.execv(
        sys.executable,
        [sys.executable, "-m", "stark.main"],
    )


if __name__ == "__main__":
    main()
