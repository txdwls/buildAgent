# Current Intent

Updated: 2026-09-07
Branch: `feature/browser-extract-screenshot`
Base commit: `4bd1b5f` (`dev`, Merge pull request #6 from txdwls/feature/browser-interact)
Working tree: clean. `data/` is now gitignored and stays local. Do not commit or push without an explicit request.

## Project intent

Build and operate an AI agent with raw SDKs so that real failures can be reproduced, diagnosed, fixed, and reverified. The portfolio outcome is a working agent plus evidence based troubleshooting records. Open WebUI is the interface; the backend loop that selects tools, consumes results, and decides whether to continue or finish is the agent.

## Completed

### Implemented and merged into `dev`

- Phase 0: uv project, Python 3.12 tooling, settings, Docker Compose, and self-hosted Langfuse setup.
- Phase 1: raw OpenAI function calling loop, `web_search` with Tavily, CLI multi-turn flow, and Langfuse tracing.
- Phase 2: OpenAI compatible `/v1/chat/completions`, JSON and SSE responses, and Open WebUI integration.
- Phase 3 partial: filesystem read, write, list, and root jail. `code_exec` and `http_fetch` are not implemented.
- Phase 4 partial: lazy Playwright session plus `browser_open`, `browser_click`, and `browser_type`. `browser_extract` and `browser_screenshot` are not implemented.
- Observability: request traces carry source, task, session, request ID, tool tags, final status, input, and output. The trace path no longer captures the client object or its API key.
- Test suite: default pytest excludes `integration` and `e2e`; `BUILDAGENT_RUN_LIVE_TESTS=1` gate enables live runs. Unit coverage added for API dependencies and health, CLI, domain errors, prompts loader, OpenAI client, tool registry and dispatch, web_search, filesystem edges, and browser session/actions. Opt-in integration and e2e suites live under `tests/integration/` and `tests/e2e/`.
- Docs handoff: `INTENT.md` adopted as the per-session state file. `CLAUDE.md` explains the split.

### Verified evidence

- Latest merges on `dev`: `a166a7d Merge pull request #5 from txdwls/feature/browser-tool` and `4bd1b5f Merge pull request #6 from txdwls/feature/browser-interact`. Both source branches deleted.
- `uv run pytest -q`: 72 passed, 4 integration/e2e tests deselected.
- `uv run ruff check .` and `uv run pyright` clean (0 errors, 0 warnings, 0 informations).
- Playwright Chromium installed locally. Browser integration test uses a deterministic local HTML server; it does not prove the running API/Open WebUI journey.
- Live OpenAI, Tavily, and Langfuse checks after credential rotation are still pending. No credential values belong in this file or in logs.

## Current work

Active phase: Phase 4 browser automation.

Active task: finish Phase 4 by implementing `browser_extract` (structured DOM extraction) and `browser_screenshot` (page capture) on the existing lazy Playwright session, with unit coverage and one opt-in integration path.

Done when:

- `browser_extract` returns a bounded, deterministic representation (text or attribute) of one or more elements matched by a CSS selector on the current page, and rejects when the current page URL is not in the allowlist.
- `browser_screenshot` writes a PNG under the filesystem root jail (via existing `filesystem_root`) and returns the relative path, with an option for full-page vs viewport, and honors the allowlist check on the current page URL.
- Both tools are registered in the CLI and API tool sets, appear in Langfuse traces as their own spans, and use the shared `get_page` session.
- Unit tests cover: success, empty match, allowlist rejection, and Playwright failure for each tool. Integration test extends `tests/integration/test_browser_flow.py` to exercise the new tools against the local HTML server.
- `uv run pytest -q`, `uv run ruff check .`, `uv run pyright` all pass.

Next action: implement `browser_extract` first (pure read, no filesystem write), add its unit + integration coverage, then implement `browser_screenshot` reusing the filesystem root jail from `config/settings.py`.

## Boundaries and handoff

- Do not advance to the next Phase (Phase 5 context management) while Phase 4 tools remain incomplete.
- Do not open a PR until both tools plus tests are green.
- Keep detailed troubleshooting in local ignored `docs/`; remove secrets before any portfolio version is made public.
- A new AI must compare this file with `git status`, the current source, and the latest runtime results. This file is a handoff and work target, not implementation authorization.
- Keep default unit tests external-free; live tests require the explicit `BUILDAGENT_RUN_LIVE_TESTS=1` gate.
- Do not commit or push without an explicit user request.

### Deferred but still on the roadmap

- Live provider verification after credential rotation: `BUILDAGENT_RUN_LIVE_TESTS=1 uv run pytest -m "integration or e2e" -q`, plus a manual Open WebUI -> API -> Langfuse browser flow, logged into local ignored `docs/troubleshooting/`. Blocks calling Phase 4 truly complete.
- Phase 3 remainder: `code_exec`, `http_fetch`.

See [CLAUDE.md](CLAUDE.md) for operating rules, [ROADMAP.md](ROADMAP.md) for planned phases, and [docs/workflow.md](docs/workflow.md) for troubleshooting and handoff procedure.
