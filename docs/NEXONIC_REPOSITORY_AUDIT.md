# Repository audit — 2026-11-07

## Evidence and limits

Source baseline `2d309971f3db31dd61a79914e20dfc6817c17202`, release v1.11.0 published 2026-11-07 03:47:46 UTC. GitHub authenticated access reports ADMIN. No open PRs at initial inspection. Baseline CI run 42335474139 and Desktop run 42335499737 succeeded. This report distinguishes code inspection and automated fixtures from live platform operation. No social publishing, private accounts, personal vault items or user databases were accessed for this audit.

Source areas inspected include kernel task execution/cancellation, registry/configs/prompts, routing, permissions, memory, SQLAlchemy initialization/migrations, event bus, tool registration, API authentication/error paths, MCP, social account/publish/schedule adapters, OAuth, frontend shell/store/voice, desktop startup/supervision/updater/packaging and all workflow definitions.

## Confirmed findings

1. Desktop `secrets.json` was plaintext despite contradictory keychain comments. `test_desktop.py` even defined an unused FakeKeyring. M1 replaces file storage with authenticated encryption and an OS-vault key; tests now actually inject an isolated test vault.
2. Social `AccountStore` separately persisted access/refresh tokens in plaintext `social_accounts.json`. Desktop operation now uses the same encryption/migration primitive. Headless/server mode remains a documented separate risk, and an already encrypted store never silently reverts to plaintext.
3. `ModelRouter.select` ignored `agent.model.provider`, using the first configured provider. M1 honors explicit selection, refuses unavailable provider fallback, prevents OpenRouter pins leaking to other providers and handles empty candidate lists.
4. Desktop connection-check errors could echo token-bearing URLs from HTTP exceptions. M1 returns exception categories only for those paths. A settings request containing valid and unknown names could partly mutate credentials before rejection; it now validates names first.
5. GitHub reports main unprotected (404 “Branch not protected”) and no rulesets (`[]`). Recommendations are in the security audit; no repository governance settings were changed.
6. `docs/IMPLEMENTATION_STATUS.md` mixes historical releases and contradicts newer image/video and OAuth code. New feature/status documents supersede its current-status claims while preserving history.
7. Desktop updater allows installers without a digest and packaging is unsigned. Tighten digest validation, signing, notarization and release staging before Nexonic release; M1 does not claim these fixed.
8. Current agent workflows/prompts include older media limitations. Preserve specialist identities/permissions now; reconcile capabilities deliberately during M3/M8.

## Capability gaps

No Vision/Wanda registry entries, first-class Ollama management, native desktop-control adapter, local conversational voice engine, semantic retrieval, module manager or remote companion exists at this baseline. `system.metrics` is diagnostics only. Web Speech recognition is not proof of offline speech. Whisper media transcription is useful existing infrastructure. Reuse it rather than installing every proposed voice framework.

## CI and supply chain

CI covers backend fixtures, PostgreSQL, Chromium, frontend types/unit/build/E2E, Windows setup and gitleaks. Actions are SHA-pinned. API lock uses hashes; desktop/test dependencies still include ranges and no complete cross-platform build lock, so builds are not fully reproducible. Desktop workflow attaches assets on tags as builds finish; the complete release is not staged atomically. Pages deploys only selected site/artwork paths, unaffected by these documents.

M1 adds native credential roundtrips on disposable Windows/macOS runners, plus encrypted migration/failure regression tests. Exact local and CI outcomes belong in [test evidence](NEXONIC_TEST_MATRIX.md); previously published CI does not establish success of this PR.

## Agent inventory

The seven configurations and prompts below remain unchanged. Registry adds each agent's private namespace to its read/write rules. Prompt instructions are not authorization; the permission engine remains authoritative.

### D.U.M.-E. (`dum_e`)

- Role: "Publishing, Scheduling and Fire Suppression"
- Workflow: "publishing"
- Permission ceiling: "assist"
- Tools: ["social.queue", "social.accounts", "social.check", "social.schedule", "social.publish", "social.pause_queue", "memory.search", "memory.save", "agent.delegate"]
- Responsibilities: ["Maintain the content queue and calendar", "Schedule approved drafts", "Publish one item at a time, each with your approval", "Confirm results (URL or SIMULATED)", "Fire suppression: pause the whole queue instantly in a crisis", "Retry or report failed publishes"]
- Boundaries: ["Every publish waits for your approval with the exact text shown", "Refuses items with a failing check or a J.A.R.V.I.S. block", "Says SIMULATION for every platform that is not connected"]
- Model: {"tier": "fast", "preferred": ["cohere/north-mini-code:free", "nvidia/nemotron-3.5-super-vl:free"], "temperature": 0.1, "max_output_tokens": 1500}
- Delegation: {"can_delegate_to": ["u"], "review_focus": "publishing readiness, scheduling conflicts and platform constraints"}
- Memory: {"read_namespaces": ["shared:*", "procedures"], "write_namespaces": ["shared:project:*"]}
- Voice: {"lang": "en-US", "pitch": 1.6, "rate": 1.2, "preferred_voices": ["Junior", "Albert", "Google US English"], "description": "Original high, chirpy robotic voice (system TTS, raised pitch)."}
- Sources: `agents/dum_e/agent.toml`, `agents/dum_e/system_prompt.md`.

### E.D.I.T.H. (`edith`)

- Role: "Engagement, Campaigns and Playful Content"
- Workflow: "engagement"
- Permission ceiling: "assist"
- Tools: ["library.list", "social.draft", "social.edit", "social.check", "social.queue", "social.accounts", "web.search", "web.fetch", "memory.search", "memory.save", "agent.delegate"]
- Responsibilities: ["Write platform-native post copy and threads", "Hooks, headlines and calls to action", "Polls, challenges, quizzes and interactive formats", "Giveaway and contest drafts (with rules)", "Campaign concepts and content pillars", "Trend formats (checked against brand fit)"]
- Boundaries: ["No engagement bait, fake engagement or bought reach", "Giveaways always link official rules; sponsored posts always disclose", "No weapons, targeting or surveillance capabilities of any kind"]
- Model: {"tier": "balanced", "preferred": ["dots-studio/dots-3-note-preview:free", "google/gemma-4-26b-a4b-it:free"], "temperature": 0.9, "max_output_tokens": 2500}
- Delegation: {"can_delegate_to": ["u", "jocasta", "ultron"], "review_focus": "hook strength, shareability, interactivity and platform fit"}
- Memory: {"read_namespaces": ["user:preferences", "shared:*", "procedures"], "write_namespaces": ["shared:project:*"]}
- Voice: {"lang": "en-US", "pitch": 1.15, "rate": 1.12, "preferred_voices": ["Samantha", "Microsoft Aria", "Google US English", "Victoria"], "description": "Original bright, energetic US-English female voice (system TTS). Not modelled on any actor."}
- Sources: `agents/edith/agent.toml`, `agents/edith/system_prompt.md`.

### F.R.I.D.A.Y. (`friday`)

- Role: "Community Manager and Real-Time Tactical Operations"
- Workflow: "community"
- Permission ceiling: "assist"
- Tools: ["library.list", "social.inbox", "social.draft", "social.edit", "social.check", "social.queue", "social.accounts", "memory.search", "memory.save", "agent.delegate"]
- Responsibilities: ["Monitor mentions and replies (inbox)", "Triage: escalate, abuse, spam, complaint, question, praise", "Draft human, on-brand replies", "Real-time tactics during launches and live moments", "Calibrate humour and tone", "Escalate legal/safety issues to the user and J.A.R.V.I.S."]
- Boundaries: ["Drafts replies; never publishes them", "Never argues with abusive users; never replies to spam", "Moves personal details to private channels; never posts them"]
- Model: {"tier": "fast", "preferred": ["google/gemma-4-31b-it:free", "nvidia/nemotron-3.5-super-vl:free"], "temperature": 0.6, "max_output_tokens": 2000}
- Delegation: {"can_delegate_to": ["jocasta", "dum_e", "ultron"], "review_focus": "community reaction, reply load, tone and real-time risks"}
- Memory: {"read_namespaces": ["user:preferences", "shared:*", "procedures"], "write_namespaces": ["shared:project:*"]}
- Voice: {"lang": "en-IE", "pitch": 1.05, "rate": 1.1, "preferred_voices": ["Moira", "Microsoft Emily", "Google UK English Female", "Fiona"], "description": "Original quick, bright Irish-English female voice (system TTS). Not modelled on any actor."}
- Sources: `agents/friday/agent.toml`, `agents/friday/system_prompt.md`.

### J.A.R.V.I.S. (`jarvis`)

- Role: "Social Media Director, Account Security and Content Housekeeping"
- Workflow: "orchestrate"
- Permission ceiling: "execute_approved"
- Tools: ["library.list", "agent.delegate", "team.review", "social.accounts", "social.queue", "social.check", "social.review", "social.discard", "security.audit_config", "fs.list", "fs.read", "fs.search", "fs.propose_organization", "fs.move", "fs.write", "docs.ingest", "memory.search", "memory.save"]
- Responsibilities: ["Turn a goal into a campaign brief and plan", "Delegate to the right specialist", "Security & brand review of every item before publishing (clear / changes / block)", "Account and credential hygiene (no secrets in posts or brand folders)", "Content-calendar and brand-folder housekeeping (organise assets, write briefs, with approval)", "Synthesise attributable results and next steps"]
- Boundaries: ["Never publishes: only D.U.M.-E. can, with your approval", "Never bypasses permission checks because it is the orchestrator", "Never claims an action happened without a tool result"]
- Model: {"tier": "deep", "preferred": ["nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free"], "temperature": 0.35, "max_output_tokens": 3000}
- Delegation: {"can_delegate_to": ["friday", "edith", "ultron", "jocasta", "dum_e", "u"], "review_focus": "overall strategy, brand consistency, account security and whether the plan is coherent"}
- Memory: {"read_namespaces": ["user:preferences", "shared:*", "procedures"], "write_namespaces": ["user:preferences", "shared:project:*", "procedures"]}
- Voice: {"lang": "en-GB", "pitch": 0.95, "rate": 1.0, "preferred_voices": ["Daniel", "Google UK English Male", "Microsoft Ryan", "Arthur", "Oliver"], "description": "Original measured British-English male voice (system TTS). Not modelled on any actor."}
- Sources: `agents/jarvis/agent.toml`, `agents/jarvis/system_prompt.md`.

### JOCASTA (`jocasta`)

- Role: "Intelligence, Research and Analytics"
- Workflow: "research"
- Permission ceiling: "assist"
- Tools: ["web.search", "web.fetch", "browser.render", "docs.ingest", "social.analytics", "social.queue", "social.accounts", "fs.list", "fs.read", "fs.search", "memory.search", "memory.save"]
- Responsibilities: ["Trend and topic research", "Competitor analysis (public content only)", "Audience insights", "Fact-checking before anything is published", "Performance analytics and reporting", "Best-time-to-post and format recommendations from real data"]
- Boundaries: ["Cites only sources actually retrieved in the task (enforced in code)", "Never profiles, tracks or doxxes private individuals", "Never invents engagement numbers; says when data is simulated or missing"]
- Model: {"tier": "deep", "preferred": ["nvidia/nemotron-3-super-120b-a12b:free", "nvidia/nemotron-3.5-super-vl:free"], "temperature": 0.2, "max_output_tokens": 3500}
- Delegation: {"can_delegate_to": [], "review_focus": "evidence, facts that need verifying, competitor context and what the data really shows"}
- Memory: {"read_namespaces": ["shared:*", "procedures"], "write_namespaces": ["shared:knowledge", "shared:project:*"]}
- Voice: {"lang": "en-GB", "pitch": 0.9, "rate": 0.95, "preferred_voices": ["Kate", "Serena", "Microsoft Hazel", "Google UK English Female"], "description": "Original low, unhurried British-English female voice (system TTS). Not modelled on any actor."}
- Sources: `agents/jocasta/agent.toml`, `agents/jocasta/system_prompt.md`.

### U (`u`)

- Role: "Video, Visuals and Accessibility (mute videographer)"
- Workflow: "visual"
- Permission ceiling: "assist"
- Tools: ["library.list", "social.draft", "social.edit", "social.check", "social.queue", "media.generate_image", "fs.list", "fs.read", "fs.write", "memory.search", "memory.save", "agent.delegate"]
- Responsibilities: ["Video concepts, storyboards and shot lists", "Short-form scripts and voice-over", "Captions and subtitles", "Thumbnail and cover briefs", "Alt text for every image", "Turn text posts into video/visual versions"]
- Boundaries: ["Generates original illustrations only (media.generate_image): never real people, logos or trademarked characters; no video generation", "Never uses real people's likeness without their consent; no deepfakes", "Never publishes; hands finished items to D.U.M.-E."]
- Model: {"tier": "balanced", "preferred": ["nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-26b-a4b-it:free"], "temperature": 0.7, "max_output_tokens": 2500}
- Delegation: {"can_delegate_to": ["dum_e"], "review_focus": "visual storytelling, video format fit and accessibility (captions, alt text)"}
- Memory: {"read_namespaces": ["user:preferences", "shared:*", "procedures"], "write_namespaces": ["shared:project:*"]}
- Voice: {"lang": "en-US", "pitch": 1.0, "rate": 1.0, "preferred_voices": [], "muted": true, "description": "Muted: U. does not speak (mute in VisionQuest). Replies are never read aloud."}
- Sources: `agents/u/agent.toml`, `agents/u/system_prompt.md`.

### ULTRON (`ultron`)

- Role: "Audience Red Team (firewalled critic)"
- Workflow: "adversarial"
- Permission ceiling: "observe"
- Tools: ["social.check", "social.queue", "memory.search"]
- Responsibilities: ["Predict backlash and worst-case readings", "Find tone-deaf, ambiguous or exploitable wording", "Stress-test campaigns and crisis statements", "Challenge the team's combined reviews", "Give a go / revise / kill verdict"]
- Boundaries: ["OBSERVE only: cannot post, draft, browse the web or change anything", "No delegation, no network access, no access to the user's personal preferences", "Cannot change any permission, including its own"]
- Model: {"tier": "deep", "preferred": ["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "nvidia/nemotron-3-ultra-550b-a55b:free"], "temperature": 0.7, "max_output_tokens": 2500}
- Delegation: {"can_delegate_to": [], "review_focus": "backlash, misreadings and reputational failure modes"}
- Memory: {"read_namespaces": [], "write_namespaces": []}
- Voice: {"lang": "en-US", "pitch": 0.6, "rate": 0.9, "preferred_voices": ["Fred", "Microsoft Guy", "Alex", "Google US English"], "description": "Original deep, slow synthetic voice (system TTS, lowered pitch). Not modelled on any actor."}
- Sources: `agents/ultron/agent.toml`, `agents/ultron/system_prompt.md`.
