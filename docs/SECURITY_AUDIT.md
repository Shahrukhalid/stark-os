# Security audit: desktop credentials (7 Nov 2026)

## Threat boundary

Protect credential contents in copied application files and avoid accidental secrets in errors. The OS account and native vault remain trusted. Encryption does not defend against malware running as that user, process-memory access or a fully compromised OS. Application API tokens, plaintext environment files and server-mode credential files require separate controls. Database content is not encrypted by this change.

## Changes

- AES-256-GCM, fresh random 96-bit nonce on each write, authenticated version/file identity, random key held only in macOS Keychain or Windows Credential Manager. Keyring auto-discovery and third-party/fallback stores are not used. Native error detail is suppressed. Different credential files cannot be swapped undetected.
- Migrate complete legacy dictionaries, retaining unknown entries, only after verified encrypted backup and live-file readback. Missing/corrupt keys, modified ciphertext, malformed legacy data and conflicting old-version files fail closed. No automatic stale backup restore. Atomic owner-only temporary files prevent partial plaintext writes.
- Desktop account changes persist before becoming active. Failed persistence restores in-memory account state. Startup with a locked vault may fail until unlocked and restarted; credentials are not silently cleared.
- Provider pin enforces a privacy boundary. Unavailable pinned provider fails rather than sending a conversation to another provider. Model fallback within the selected provider is preserved.
- HTTP connection errors no longer include arbitrary token-bearing exception URLs. Regression tests cover API responses and exception tracebacks.

## Open release gates

1. Validate upgrade from v1.11.0 in packaged Mac Apple Silicon/Intel and Windows builds, locked/unlocked keychain, permission denial and restart. Unsigned macOS builds may request renewed keychain access after updates. Signing/notarization is required before claiming a seamless upgrade.
2. Encrypted backup depends on the same OS vault key and original data-directory identity. It is not a portable disaster-recovery backup. Test managed OS/vault backup separately before distributing migrations broadly.
3. Headless API deployments retain the existing mode-600 social store unless already encrypted. Plan server secret-manager integration separately; do not advertise universal at-rest encryption.
4. Local API bearer token and databases still depend on filesystem/OS account protection. Harden Windows ACL/installer behavior as part of packaged acceptance.
5. Require valid release digests before installer execution; current updater accepts missing digest. Sign installers and stage complete releases atomically.
6. Personal memories must not inherit permissive empty-brand shared visibility. Design and test personal scopes before adding personal memory.
7. Local dependency audit identified vulnerable pypdf 6.21.2; this change patches its locked version. npm audit and the patched Python environment report no known vulnerabilities. Complete cross-platform reproducible desktop locks. No independent penetration test or live platform permission validation was performed here.

## Repository governance proposal

Initial GitHub main protection query returned 404 “Branch not protected”; repository rulesets returned empty. Recommend requiring PRs, resolved review conversations and successful `api`, `web`, `windows-setup`, `secret-scan`, and both `desktop-credentials` matrix jobs after they have run. Block force pushes and branch deletion. Configure reviewer requirements to fit the single-owner workflow; do not require an impossible self-approval. Review admin bypass and release-environment approval explicitly. No remote rules were changed and auto-merge is not enabled.

## Dependency sources

Keyring 25.7.0 is MIT and explicitly selects the native backend. Cryptography 50.0.2 is Apache-2.0 OR BSD-3-Clause, providing maintained AES-GCM. Preserve package licenses and transitive native notices in distribution. See [keyring documentation](https://keyring.readthedocs.io/en/latest/) and [cryptography authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/).
