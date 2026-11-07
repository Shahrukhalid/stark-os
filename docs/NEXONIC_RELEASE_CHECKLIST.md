# Nexonic AI release gates

No Nexonic AI release is authorized or ready from M0/M1 alone.

- [ ] Review and merge foundation PR only after required tests pass and owner approval.
- [ ] Windows and Mac native vault tests pass; no plaintext desktop credentials after successful migration.
- [ ] Packaged v1.11.0 upgrade, keychain denial/lock/retry and credential preservation on Windows, Apple Silicon and Intel.
- [ ] Data/OS-vault backup and recovery tested; downgrade and data-directory compatibility accepted.
- [ ] Full API, PostgreSQL, browser, frontend type/unit/E2E, security and dependency checks pass.
- [ ] Existing seven agents, accounts, history, settings, social approvals, scheduling and emergency stop preserved.
- [ ] Vision/Wanda and local model paths pass their milestone acceptance tests.
- [ ] Voice/device and desktop-action behavior validated on real hardware, including cancellation and permissions.
- [ ] Performance/startup/RSS/CPU baselines measured, no decorative inactive controls.
- [ ] Personal/brand memory isolation and confidential-data cloud fallback policy verified.
- [ ] Sign/notarize installers, enforce update digests, retain third-party licenses and native notices.
- [ ] Stage complete build assets before public publication; verify checksums and update compatibility.
- [ ] Repository governance approved/configured, repository rename explicitly approved after compatibility checks.
- [ ] Product/docs/platform claims match tested behavior; external platform credentials/approval limitations disclosed.
- [ ] Explicit owner approval for public release and any live-site changes.
