# Test evidence

Baseline source main `2d309971f3db31dd61a79914e20dfc6817c17202`. Initial restricted local baseline: 301 passed, 5 failed, 8 skipped. Four failures involved restricted local sockets/system metrics; the transcription fixture also failed locally. Do not treat these as passing. Baseline published CI 42335474139 and desktop build 42335499737 passed separately.

## Foundation regression coverage

`test_credential_store.py` uses real AES-GCM and an isolated in-memory vault. Covers full legacy dictionary/Unicode retention, encrypted backup, restart, explicit downgrade export, no-overwrite export, fresh-install no-vault access, locked vault, readback failure, malformed JSON, disk-write failure, interrupted migration, missing key, tampering, file swapping, fresh nonces, old-version conflicts, concurrent desktop updates and large social tokens. It never accesses the owner's actual vault.

`test_desktop.py` covers authenticated settings, no secret values in status, keep/clear, unknown-name prevalidation, locked-store 503 and token-URL error redaction. `test_providers.py` adds provider selection, unavailable-provider refusal, provider-scoped pins and empty pool handling. Focused local result: **46 passed, 1 skipped** (native vault test is opt-in).

CI adds macOS and Windows `desktop-credentials` jobs that opt into a real native-vault roundtrip with random temporary service identity and synthetic data, deleting the test vault key afterward. The same job runs migration and router fixtures.

## Results to be finalized before review

Full local suite, frontend types/unit/build, dependency checks and new PR CI results will be recorded after completion. Browser/real-media/PostgreSQL skips require their existing CI environments. Native OS tests do not replace packaged upgrade, microphone, physical UI, cross-machine vault backup, performance or live social integration tests.
