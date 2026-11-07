# Compatibility, credential migration and rollback

This change touches credential storage only. Python package `stark`, STARK_* environment names, data directories, database tables/records, Mac bundle ID `com.nexonic.starkos`, Windows installer identity, release URLs and all seven agent IDs remain unchanged.

## Before installing a migration build

Stop the old application and API. Back up the complete application data directory using an access-controlled, encrypted OS backup. Include the OS vault in your normal recovery policy. Test with a COPY and synthetic credentials first. Do not run old and new binaries concurrently. No real user data is migrated by development tests.

## Forward migration

Desktop `secrets.json` and `social_accounts.json` each gain `.encrypted` files. The random encryption key is stored in the native credential vault, under `STARK AI credentials <hash of resolved data directory>`, account `aes256-v1`. New installs with no saved credentials do not touch the vault until saving.

The first read validates legacy JSON, stores and reads back the native key, writes an encrypted `.backup.encrypted` snapshot, decrypts and compares it, writes/decrypts/compares the live encrypted file, then removes the legacy plaintext file. An interrupted migration retries safely. An existing conflicting encrypted/plaintext pair stops for manual recovery. No schema or directory move occurs.

All operations use synthetic data in tests. Native adapter tests run only when explicitly enabled on disposable CI runners. Never delete the vault key to fix a lock prompt. Unlock the OS vault and restart. If unavailable, the app reports an error rather than using a plaintext fallback or replacing credentials. macOS may ask for keychain access after an unsigned app update. Packaging/signing acceptance remains pending.

## Recovery

Stop the application before any recovery. Preserve all existing files in a protected backup. If the live ciphertext is damaged but the key is available, an owner can copy the matching `.backup.encrypted` file over `.encrypted` in the ORIGINAL data directory after preserving the damaged copy. This restores the migration-time state, not later token refreshes. Verify sign-ins afterward. Do not automatically restore backups; stale refresh tokens can be revoked.

If the vault key is lost, the encrypted file cannot be decrypted. Restore the matching OS vault backup and data folder or reconnect accounts. Moving the data directory changes its vault identity, so do not move/rename it as a branding change. A portable encrypted export/recovery UX is a later release gate.

## Explicit downgrade to v1.11.0

Stop both app versions. In a source environment with the desktop-security extra installed, export each CURRENT store to a separate protected folder. Example using synthetic paths:

```sh
python -m stark.credential_store /original/data/secrets.json /protected/export/secrets.json --confirm-plaintext-export
python -m stark.credential_store /original/data/social_accounts.json /protected/export/social_accounts.json --confirm-plaintext-export
```

The destination must not already exist. These exports deliberately contain plaintext for the old version, are never printed, and are never exposed through an API or agent tool. Keep them private. Back up the encrypted stores and native key, then place the exported files in the old application's unchanged data directory. Use only the old version until the next planned upgrade. Before re-upgrading, preserve both versions' data and reconcile changed legacy values rather than deleting conflicting ciphertext blindly.

The automated downgrade test verifies current values (including Unicode), owner-only POSIX mode and refusal to overwrite an export. Windows ACLs, actual installer downgrade, vault recovery across machines and user-facing recovery remain manual release gates.

## Configuration and database roadmap

Before any database schema/data-location migration, create a consistent SQLite backup via the backup API or PostgreSQL backup, test forward migration against v1.11.0 fixtures, test rollback/restoration and account/approval/history counts. This PR makes no such database change.
