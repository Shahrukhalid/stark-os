"""Authenticated local credential files with a key held only by the native OS vault.

No configurable keyring backend or plaintext fallback. Existing files are migrated
only after an encrypted backup and the live encrypted file both decrypt correctly.
The desktop launcher is single-instance; the lock also serializes API threads.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

LOCK = threading.RLock()
MESSAGE = ("Credential storage is unavailable or damaged. Unlock your OS credential store and restart. "
           "Keep the data folder and its encrypted backups. See docs/CREDENTIAL_MIGRATION.md.")


class CredentialStoreError(RuntimeError):
    pass


def native_backend():
    # Instantiate only trusted OS implementations, never keyring's plugin discovery.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
        return Keyring()
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    raise CredentialStoreError("Desktop credential storage currently supports Windows and macOS only.")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class EncryptedJSON:
    def __init__(self, legacy: Path):
        self.legacy = legacy
        self.path = legacy.with_suffix(legacy.suffix + ".encrypted")
        self.backup = legacy.with_suffix(legacy.suffix + ".backup.encrypted")
        identity = hashlib.sha256(str(legacy.parent.resolve()).encode()).hexdigest()[:32]
        self.service = "STARK OS credentials " + identity  # keychain entry name kept from STARK OS: existing keys stay readable
        self.account = "aes256-v1"
        self.aad = ("stark-credentials-v1/" + legacy.name).encode()

    def _key(self) -> bytes:
        backend = native_backend()
        encoded = backend.get_password(self.service, self.account)
        if encoded is None:
            # Never replace a missing key if any encrypted credential file exists.
            if any(self.legacy.parent.glob("*.encrypted")):
                raise CredentialStoreError(MESSAGE)
            encoded = base64.b64encode(os.urandom(32)).decode("ascii")
            backend.set_password(self.service, self.account, encoded)
            if backend.get_password(self.service, self.account) != encoded:
                raise CredentialStoreError(MESSAGE)
        key = base64.b64decode(encoded, validate=True)
        if len(key) != 32:
            raise CredentialStoreError(MESSAGE)
        return key

    def _encode(self, data: dict, key: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        cipher = AESGCM(key).encrypt(nonce, json.dumps(data, ensure_ascii=False).encode(), self.aad)
        return b"STARK-CREDENTIALS-1\n" + base64.b64encode(nonce + cipher)

    def _decode(self, raw: bytes, key: bytes) -> dict:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        prefix = b"STARK-CREDENTIALS-1\n"
        if not raw.startswith(prefix):
            raise CredentialStoreError(MESSAGE)
        payload = base64.b64decode(raw[len(prefix):], validate=True)
        data = json.loads(AESGCM(key).decrypt(payload[:12], payload[12:], self.aad))
        if not isinstance(data, dict):
            raise CredentialStoreError(MESSAGE)
        return data

    def read(self) -> dict:
        with LOCK:
            try:
                if self.path.exists():
                    data = self._decode(self.path.read_bytes(), self._key())
                    # Resume an interrupted migration, but never silently discard a
                    # different plaintext file created by an older application.
                    if self.legacy.exists():
                        old = json.loads(self.legacy.read_text(encoding="utf-8"))
                        if old != data or self._decode(self.backup.read_bytes(), self._key()) != old:
                            raise CredentialStoreError(MESSAGE)
                        self.legacy.unlink()
                    return data
                if not self.legacy.exists():
                    if self.backup.exists():
                        raise CredentialStoreError(MESSAGE)  # explicit recovery, no silent stale restore
                    return {}
                data = json.loads(self.legacy.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise CredentialStoreError(MESSAGE)
                key = self._key()
                if not self.backup.exists():
                    atomic_write(self.backup, self._encode(data, key))
                if self._decode(self.backup.read_bytes(), key) != data:
                    raise CredentialStoreError(MESSAGE)
                atomic_write(self.path, self._encode(data, key))
                if self._decode(self.path.read_bytes(), key) != data:
                    raise CredentialStoreError(MESSAGE)
                self.legacy.unlink()
                return data
            except Exception:
                # Native exceptions can include account names or secret material.
                raise CredentialStoreError(MESSAGE) from None

    def write(self, data: dict) -> None:
        with LOCK:
            try:
                self.read()  # validate/migrate before replacing any existing state
                key = self._key()
                raw = self._encode(data, key)
                if self._decode(raw, key) != data:
                    raise CredentialStoreError(MESSAGE)
                atomic_write(self.path, raw)
            except Exception:
                raise CredentialStoreError(MESSAGE) from None

    def export_for_rollback(self, destination: Path) -> None:
        """Explicit owner-only offline downgrade export. Never overwrite a file.

        Contains plaintext by necessity for v1.11.0. No API or agent tool exposes it.
        Stop both app versions before calling and protect/remove the export afterward.
        """
        with LOCK:
            data = self.read()
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Offline credential export for an explicitly requested downgrade")
    parser.add_argument("legacy_path", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--confirm-plaintext-export", action="store_true", required=True)
    args = parser.parse_args()
    EncryptedJSON(args.legacy_path).export_for_rollback(args.destination)
