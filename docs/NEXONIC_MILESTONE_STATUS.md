# Milestone status — 2026-11-07

## M0 — audit and baseline

Source inspection and inventory documented against v1.11.0/main `2d309971f3db31dd61a79914e20dfc6817c17202`. Existing seven agents, runtime, permissions, provider, social, memory, frontend, desktop and CI identified. Architecture, risk register, compatibility plan and M0–M15 roadmap prepared. Live social operations and hardware/performance acceptance remain unverified; historical CI is distinguished from current local results.

## M1 — foundation implementation under review

Implemented encrypted desktop setup/social stores with native-vault key, verified migration backup, failure-safe behavior and explicit downgrade export. Fixed provider pin handling, provider-scoped model pins, empty candidate error, desktop connection-error secret leakage and settings-name prevalidation. Added unit/integration/security fixtures and native macOS/Windows CI jobs. Prepared branch protection recommendations without changing remote rules.

No database schema, application identifier, agent config, runtime permission policy, version, repository name or live site changed. Existing server-mode social storage remains a documented risk. Native packaging/upgrade, signing, digest hardening, portable recovery and performance remain release gates. This is a foundation increment, not a claim that all Nexonic security requirements are complete.

Review PR and final test evidence to be added after checks. No merge or release is performed.

## Proposed M2

Implement Ollama behind ModelProvider, bounded local discovery/health/download operations, explicit independent per-agent provider/model choices and tool-call capability checks. Local failure must not cause cloud fallback unless the owner configured it. Verify offline text/tool conversation, cancellation, unavailable-model behavior and free-only cloud compatibility. Keep paid providers disabled by default. Proceed after reviewing M1 evidence and remaining release gates.

M3–M15 remain planned, not implemented. See [master plan](NEXONIC_MASTER_PLAN.md).
