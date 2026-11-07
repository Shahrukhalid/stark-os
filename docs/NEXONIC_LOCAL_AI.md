# Local AI adapter — M2 in progress

Set STARK_OLLAMA_URL=http://127.0.0.1:11434, STARK_OLLAMA_MODEL to an already installed local model and STARK_DEFAULT_PROVIDER=ollama. Individual agent TOML model.provider/model.model overrides remain supported. Cloud provider remains unchanged by default. No automatic cross-provider fallback is implemented.

This increment implements bounded local HTTP requests, discovery, health, model inspection, text/tool protocol conversion and tool-capability rejection. Literal loopback addresses only, proxies and redirects disabled, cloud names/remote model metadata rejected. The owner must disable cloud features in their independently managed Ollama daemon; a local service remains part of the trusted boundary.

28 adapter/router tests pass using recorded HTTP fixtures. No Ollama installation was found on this machine. Actual model transfer/inference, model management UI/download jobs, license review per selected model and full offline acceptance remain pending. M2 is not complete.

Protocol references: https://docs.ollama.com/api/openai-compatibility and https://docs.ollama.com/api/tags.

## Model management increment

The Models screen now includes installed local models, explicit per-agent selection and owner-approved downloads. Selection persists in the existing settings table and reloads on restart without modifying agent TOML. Downloads require license acknowledgment, expose real layer-byte progress, allow one active request, enforce a requested size budget and time limit, support cancellation, and verify model metadata before reporting success. Closing the API cancels its download requests. Partial layers may remain in the independently managed Ollama cache. Restarted download requests can reuse those layers through Ollama.

Management endpoints under `/api/models/local` require owner bearer authentication. Agents receive no model-download or selection tool. Download names cannot specify registry hostnames. Generation permits two concurrent local requests and bounded time/body sizes. Downloads are internet operations explicitly approved through the UI, while inference uses the loopback server.

Focused tests: 38 passed. Full backend regression before the final added cancellation tests: 339 passed, 9 skipped. TypeScript passed. Browser coverage checks that the local configuration panel remains available alongside OpenRouter. Actual inference remains pending while a local runtime is prepared. No milestone-complete claim is made.

## Real local acceptance — 2026-11-07

An isolated Ollama 0.40.15 server on Apple M5, bound to 127.0.0.1:11439 with OLLAMA_NO_CLOUD=1, downloaded Qwen3 0.6B through the model manager into a temporary store. Layer declarations totaled 522,653,767 bytes, below its approved 1 GiB limit. The manager reported done only after model inspection. The upstream Qwen3 0.6B model card declares Apache-2.0: https://huggingface.co/Qwen/Qwen3-0.6B.

Real text and structured tool inference acceptance passed using the native /api/chat interface with thinking disabled. The initial compatibility-endpoint tool probe returned no content, and an arithmetic prompt containing repeated thinking-control tokens produced an incorrect answer. Ordinary prompts through native chat returned 2 + 2 = 4 and invoked local_test_answer with answer=4. This tiny model is a protocol acceptance fixture, not a production quality recommendation. Added regression coverage for native tool-result replay, token accounting and rejecting empty responses.

Runtime/provider/model-manager regression: 65 passed, 1 opt-in skip before the final replay fixture. All-local team reviews now skip OpenRouter quota checks. No external model provider was registered in the real acceptance kernel, and cloud functionality was disabled in the test daemon. This does not prove every supported operating system's offline/package behavior. Windows real inference, desktop first-run local configuration and full milestone acceptance remain pending.

## Desktop setup and reproducible Windows acceptance

Desktop first-run now offers Ollama without an OpenRouter key. Local URL/model preferences survive restart in desktop.json, are validated before credential mutations, and can be checked against the installed local server. An empty secret clear no longer creates a vault record unnecessarily. Existing cloud keys are retained through keep semantics. Actual model capability and generation failures remain visible; a saved configuration alone does not assert the model is online.

`scripts/test_local_ollama.py` starts a temporary cloud-disabled loopback daemon, downloads the same licensed test model under the manager's 1 GiB limit, runs real text/tool acceptance, and terminates its own process. CI adds Windows acceptance using official Ollama 0.40.15 with its pinned SHA-256. The workflow installs no persistent service. Pending result must pass before claiming Windows inference acceptance.
