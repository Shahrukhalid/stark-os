"""Real authenticated encryption with an isolated test vault, never the owner's keychain."""
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor

import pytest

from stark import credential_store as cs, desktop
from stark.tools.social import AccountStore
from .test_desktop import FakeKeyring


@pytest.fixture
def vault(monkeypatch):
    vault = FakeKeyring()
    monkeypatch.setattr(cs, "native_backend", lambda: vault)
    return vault


def test_migration_backup_restart_and_downgrade(tmp_path, vault):
    path = tmp_path / 'secrets.json'
    original = {'OPENROUTER_API_KEY': 'test-secret-اردو', 'future-key': 'preserve-me'}
    path.write_text(json.dumps(original))
    store = cs.EncryptedJSON(path)
    assert store.read() == original
    assert not path.exists()
    for file in (store.path, store.backup):
        assert b'preserve-me' not in file.read_bytes()
        if os.name != 'nt':
            assert file.stat().st_mode & 0o777 == 0o600
    assert cs.EncryptedJSON(path).read() == original
    store.write({**original, 'OPENROUTER_API_KEY': 'new-secret'})
    assert store._decode(store.backup.read_bytes(), store._key()) == original
    destination = tmp_path / 'downgrade.json'
    store.export_for_rollback(destination)
    assert json.loads(destination.read_text())['OPENROUTER_API_KEY'] == 'new-secret'
    with pytest.raises(FileExistsError):
        store.export_for_rollback(destination)


def test_fresh_store_does_not_access_keychain(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, 'native_backend', lambda: pytest.fail('unexpected native access'))
    assert cs.EncryptedJSON(tmp_path / 'secrets.json').read() == {}


@pytest.mark.parametrize('failure', ['locked', 'unverified', 'corrupt-legacy', 'write-failure'])
def test_failed_migration_preserves_original(tmp_path, vault, monkeypatch, failure):
    path = tmp_path / 'secrets.json'
    raw = '{broken' if failure == 'corrupt-legacy' else '{"token":"never-leak-this-value"}'
    path.write_text(raw)
    if failure == 'locked':
        def fail(*args):
            raise RuntimeError('never-leak-this-value')
        monkeypatch.setattr(vault, 'get_password', fail)
    elif failure == 'unverified':
        monkeypatch.setattr(vault, 'set_password', lambda *a: None)
    elif failure == 'write-failure':
        def fail(*args):
            raise OSError('never-leak-this-value')
        monkeypatch.setattr(cs, 'atomic_write', fail)
    with pytest.raises(cs.CredentialStoreError):
        try:
            cs.EncryptedJSON(path).read()
        except cs.CredentialStoreError:
            assert 'never-leak-this-value' not in traceback.format_exc()
            raise
    assert path.read_text() == raw


def test_interrupted_migration_retries_without_overwriting_backup(tmp_path, vault, monkeypatch):
    path = tmp_path / 'secrets.json'
    path.write_text('{"token":"secret"}')
    store = cs.EncryptedJSON(path)
    write = cs.atomic_write
    def fail_live(p, data):
        if p == store.path:
            raise OSError('disk full')
        write(p, data)
    monkeypatch.setattr(cs, 'atomic_write', fail_live)
    with pytest.raises(cs.CredentialStoreError):
        store.read()
    backup = store.backup.read_bytes()
    assert path.exists()
    monkeypatch.setattr(cs, 'atomic_write', write)
    assert store.read() == {'token': 'secret'}
    assert store.backup.read_bytes() == backup and not path.exists()


def test_missing_key_or_tampering_never_resets_credentials(tmp_path, vault):
    store = cs.EncryptedJSON(tmp_path / 'secrets.json')
    store.write({'token': 'important'})
    good = store.path.read_bytes()
    saved = dict(vault.store)
    vault.store.clear()
    with pytest.raises(cs.CredentialStoreError):
        store.write({'token': 'replacement'})
    assert store.path.read_bytes() == good and not vault.store
    vault.store.update(saved)
    store.path.write_bytes(good[:-4] + b'AAAA')
    with pytest.raises(cs.CredentialStoreError):
        store.read()
    assert not store.legacy.exists()


def test_files_cannot_be_swapped_and_nonces_change(tmp_path, vault):
    one = cs.EncryptedJSON(tmp_path / 'secrets.json')
    two = cs.EncryptedJSON(tmp_path / 'social_accounts.json')
    one.write({'token': 'a'})
    previous = one.path.read_bytes()
    one.write({'token': 'a'})
    assert one.path.read_bytes() != previous
    two.path.write_bytes(one.path.read_bytes())
    with pytest.raises(cs.CredentialStoreError):
        two.read()


def test_older_app_conflict_is_not_discarded(tmp_path, vault):
    store = cs.EncryptedJSON(tmp_path / 'secrets.json')
    store.write({'token': 'new'})
    store.legacy.write_text('{"token":"old-app-change"}')
    with pytest.raises(cs.CredentialStoreError):
        store.read()
    assert 'old-app-change' in store.legacy.read_text()


def test_concurrent_desktop_updates_preserve_values(tmp_path, vault, monkeypatch):
    monkeypatch.setenv('STARK_DATA_DIR', str(tmp_path))
    names = list(desktop.SECRETS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda name: desktop.set_secret(name, 'value-' + name), names))
    assert desktop._load_secrets() == {name: 'value-' + name for name in names}


def test_social_migration_large_token_and_failed_save(settings, vault, monkeypatch):
    monkeypatch.setenv('STARK_DESKTOP', '1')
    settings.data_dir.mkdir()
    path = settings.data_dir / 'social_accounts.json'
    original = {'bluesky': {'bluesky_handle': 'test.bsky.social',
                            'bluesky_app_password': 'secret-' + 'x' * 5000, 'connected_as': 'test'}}
    path.write_text(json.dumps(original))
    accounts = AccountStore(settings)
    assert accounts.data == original and not path.exists()
    assert settings.bluesky_app_password == original['bluesky']['bluesky_app_password']
    def fail(*args):
        raise cs.CredentialStoreError('locked')
    monkeypatch.setattr(accounts.secure_store, 'write', fail)
    with pytest.raises(cs.CredentialStoreError):
        accounts.save('bluesky', {'bluesky_handle': 'changed', 'bluesky_app_password': 'new'}, 'new')
    assert accounts.data == original and settings.bluesky_handle == 'test.bsky.social'
    with pytest.raises(cs.CredentialStoreError):
        accounts.remove('bluesky')
    assert settings.bluesky_app_password == original['bluesky']['bluesky_app_password']


def test_native_store_roundtrip_on_ci_only(tmp_path):
    if os.environ.get('STARK_TEST_NATIVE_VAULT') != '1':
        pytest.skip('opt-in native OS vault test on disposable CI runners')
    store = cs.EncryptedJSON(tmp_path / 'secrets.json')
    backend = cs.native_backend()
    try:
        store.write({'token': 'synthetic-ci-credential'})
        assert cs.EncryptedJSON(store.legacy).read() == {'token': 'synthetic-ci-credential'}
    finally:
        backend.delete_password(store.service, store.account)
