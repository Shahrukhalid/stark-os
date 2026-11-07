# Nexonic AI master plan

Audit baseline 2026-11-07. Repository `Shahrukhalid/stark-os`, main `2d309971f3db31dd61a79914e20dfc6817c17202`, latest published release v1.11.0. Publisher Nexonic Technologies. Preserve the existing kernel, seven agents, social workflows, identifiers and user data.

## Milestones and acceptance gates

- M0 Repository audit. Source inventory, test baseline, architecture and migration plan with explicit evidence gaps.
- M1 Foundation. Protect desktop credentials, exercise migration/failure/rollback paths, honor provider pins, document governance and remaining risks. Native OS and packaged upgrade acceptance gates remain mandatory before release.
- M2 Local AI. Add one Ollama provider through ModelProvider. Discover models, test tool support, bound downloads/requests and cancellation. Explicit per-agent configuration and no implicit local-to-cloud fallback. Prove offline text/tool conversation without paid providers. Preserve OpenRouter free mode. Models downloaded only on request, with model license/size shown.
- M3 Vision and Wanda. Register two agents through the existing registry/kernel, with equivalent capability policies, distinct personalities/history/voice preferences. Test delegation, addressing and memory isolation. Preserve all seven specialists and ULTRON's restrictions.
- M4 Voice. Compare a minimal local STT/TTS stack against already bundled whisper.cpp. Keep Web Speech fallback. Test push-to-talk, wake phrases, interruption, VAD/echo handling, device changes and consent. Validate English and Urdu separately. Never call browser recognition offline without evidence.
- M5 Control. Native Windows/macOS adapters behind existing tools and permissions. Structured verified results, cancellation and reversible operations. No unrestricted shell. Linux interface only until validated.
- M6 Memory. Benchmark SQLite FTS before optional local embeddings. Personal/project/brand boundaries, provenance, editing, export, expiry, contradiction handling and recovery.
- M7 Interface. Personal-assistant home, model/task status, accessible motion and themes. Prototype floating companion without replacing pywebview. Every visible control must work.
- M8 Modules. Versioned manifests with dependencies, permissions, health and enable/disable. Wrap existing social features as Nexonic Social. Stage other modules only when functional.
- M9 Productivity. Calendar, reminders, research, knowledge and communication drafts using verified integrations and authorization.
- M10 Developer/project intelligence. Repository/issue/PR/CI tracking with narrow permissions and evidence-based status.
- M11 Teach Nexonic. Authorized workflow recording, explicit replay plans, parameter validation, cancellation and step verification.
- M12 Mission Control. Real feeds and system/task activity, optional globe, bounded refresh and clear stale/offline states.
- M13 Ecosystem. Verify APIs for Download Manager, Catcut, ReForge and MCP services before integrating.
- M14 Remote. Authenticated local-network pairing first. Encryption, revocation and threat review before internet connectivity.
- M15 Release. Complete security, performance, device/installer and upgrade checklist before public branding/release.

Each milestone uses a feature branch and reviewable PR with tests and limitations. Do not rename the repository, publish a release, or migrate real user databases without owner authorization. No site changes are included here. Preserve legal notices and the owner's configured Git identity.

See [status](NEXONIC_MILESTONE_STATUS.md), [architecture](NEXONIC_ARCHITECTURE.md), [audit](NEXONIC_REPOSITORY_AUDIT.md), [migration](NEXONIC_MIGRATION_PLAN.md) and [release gates](NEXONIC_RELEASE_CHECKLIST.md).
