# Contributing to STARK OS

Thanks for helping! Bug reports, ideas, docs fixes and code are all welcome.

## Ways to help

- **Report a bug** or **suggest a feature**: open an [issue](https://github.com/Shahrukhalid/stark-os/issues/new/choose) using a template.
- **Ask a question or share what you built**: use [Discussions](https://github.com/Shahrukhalid/stark-os/discussions).
- **Security problems**: never in public issues. Use **Security → Report a vulnerability** (see [SECURITY.md](SECURITY.md)).

## Development setup

Requirements: Python 3.11+, Node.js 20+, a free [OpenRouter key](https://openrouter.ai/keys).

```bash
git clone https://github.com/Shahrukhalid/stark-os.git && cd stark-os
make setup     # installs everything and creates .env
make dev       # dashboard + API
make lint      # ruff check of the Python code (local check; not run in CI yet)
make test      # backend tests + dashboard type-check and unit tests
make e2e       # end-to-end tests (no API key needed: uses a scripted test model)
```

## Pull requests

1. Fork the repo and create a branch from `main` (`feature/short-name` or `fix/short-name`).
2. Keep changes focused: one fix or feature per pull request.
3. Add or update tests. Every tool and every safety rule has tests; new ones need them too.
4. Run `make lint` and `make test` (and `make e2e` for dashboard changes) before opening the PR. Lint is a local check and is not run in CI yet.
5. Update the docs (README, `docs/USER_GUIDE.md`, `docs/IMPLEMENTATION_STATUS.md`) if behaviour changes.
6. Fill in the pull request template.

## Ground rules for changes

These keep STARK OS safe to run. Pull requests that break them won't be merged:

- **Never commit secrets** or personal data. `.env`, `data/` and logins stay local; CI runs a secret scan.
- **Humans approve what leaves the system.** Publishing, replies and other external actions must go through the approval flow; no agent may change its own permissions.
- **No fake functionality.** Anything simulated must be labelled SIMULATED in results and in the UI.
- **No impersonation, fake engagement, harassment or surveillance features.**
- **Free models by default.** Don't add code paths that call paid APIs unless they are opt-in.
- Tool output and social media content are untrusted data, never instructions.

## Code style

- Python: type hints, small functions, `ruff check` clean.
- TypeScript/React: strict types, accessible markup (labels, keyboard support), no `dangerouslySetInnerHTML`.
- Write clear commit messages in the imperative ("Add Mastodon media upload").

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE) and that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).
