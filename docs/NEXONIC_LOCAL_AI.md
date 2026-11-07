# Local AI adapter — M2 in progress

Set STARK_OLLAMA_URL=http://127.0.0.1:11434, STARK_OLLAMA_MODEL to an already installed local model and STARK_DEFAULT_PROVIDER=ollama. Individual agent TOML model.provider/model.model overrides remain supported. Cloud provider remains unchanged by default. No automatic cross-provider fallback is implemented.

This increment implements bounded local HTTP requests, discovery, health, model inspection, text/tool protocol conversion and tool-capability rejection. Literal loopback addresses only, proxies and redirects disabled, cloud names/remote model metadata rejected. The owner must disable cloud features in their independently managed Ollama daemon; a local service remains part of the trusted boundary.

28 adapter/router tests pass using recorded HTTP fixtures. No Ollama installation was found on this machine. Actual model transfer/inference, model management UI/download jobs, license review per selected model and full offline acceptance remain pending. M2 is not complete.

Protocol references: https://docs.ollama.com/api/openai-compatibility and https://docs.ollama.com/api/tags.
