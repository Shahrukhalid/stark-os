# Local AI adapter — M2 in progress

Set STARK_OLLAMA_URL=http://127.0.0.1:11434, STARK_OLLAMA_MODEL to an already installed local model and STARK_DEFAULT_PROVIDER=ollama. Individual agent TOML model.provider/model.model overrides remain supported. Cloud provider remains unchanged by default. No automatic cross-provider fallback is implemented.

This increment implements bounded local HTTP requests, discovery, health, model inspection, text/tool protocol conversion and tool-capability rejection. Literal loopback addresses only, proxies and redirects disabled, cloud names/remote model metadata rejected. The owner must disable cloud features in their independently managed Ollama daemon; a local service remains part of the trusted boundary.

28 adapter/router tests pass using recorded HTTP fixtures. No Ollama installation was found on this machine. Actual model transfer/inference, model management UI/download jobs, license review per selected model and full offline acceptance remain pending. M2 is not complete.

Protocol references: https://docs.ollama.com/api/openai-compatibility and https://docs.ollama.com/api/tags.

## Model management increment

The Models screen now includes installed local models, explicit per-agent selection and owner-approved downloads. Selection persists in the existing settings table and reloads on restart without modifying agent TOML. Downloads require license acknowledgment, expose real layer-byte progress, allow one active request, enforce a requested size budget and time limit, support cancellation, and verify model metadata before reporting success. Closing the API cancels its download requests. Partial layers may remain in the independently managed Ollama cache. Restarted download requests can reuse those layers through Ollama.

Management endpoints under `/api/models/local` require owner bearer authentication. Agents receive no model-download or selection tool. Download names cannot specify registry hostnames. Generation permits two concurrent local requests and bounded time/body sizes. Downloads are internet operations explicitly approved through the UI, while inference uses the loopback server.

Focused tests: 38 passed. Full backend regression before the final added cancellation tests: 339 passed, 9 skipped. TypeScript passed. Browser coverage checks that the local configuration panel remains available alongside OpenRouter. Actual inference remains pending while a local runtime is prepared. No milestone-complete claim is made.
