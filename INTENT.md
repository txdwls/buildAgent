# Current Intent

Updated: 2026-09-07
Branch: `feature/browser-interact`
Base commit: `9dab40d`
Working tree: test-suite changes are uncommitted. Preserve the existing `CLAUDE.md` change, user `data/`, and this handoff. Do not commit or push without an explicit request.

## Project intent

Build and operate an AI agent with raw SDKs so that real failures can be reproduced, diagnosed, fixed, and reverified. The portfolio outcome is a working agent plus evidence based troubleshooting records. Open WebUI is the interface; the backend loop that selects tools, consumes results, and decides whether to continue or finish is the agent.

## Completed

### Implemented and pushed

- Phase 0: uv project, Python 3.12 tooling, settings, Docker Compose, and self-hosted Langfuse setup.
- Phase 1: raw OpenAI function calling loop, `web_search` with Tavily, CLI multi-turn flow, and Langfuse tracing.
- Phase 2: OpenAI compatible `/v1/chat/completions`, JSON and SSE responses, and Open WebUI integration.
- Phase 3 partial: filesystem read, write, list, and root jail. `code_exec` and `http_fetch` are not implemented.
- Phase 4 partial: lazy Playwright session plus `browser_open`, `browser_click`, and `browser_type`. `browser_extract` and `browser_screenshot` are not implemented.
- Observability: request traces now carry source, task, session, request ID, tool tags, final status, input, and output. The new trace path no longer captures the client object or its API key.

### Verified evidence

- Latest pushed commit: `9dab40d feat(observability): organize request traces with sessions and task tags`.
- The default external-free check is `uv run pytest -q`: 72 passed and 4 integration/e2e tests were deselected.
- The non-e2e coverage run reported 73 passed, 1 skipped, and 2 deselected with 98% branch-inclusive coverage (684 statements, 9 missed, 138 branches, 7 partial).
- `uv run pytest -m integration -q` passed the local Playwright browser flow and skipped the gated Langfuse health test. `uv run pytest -m e2e -q` skipped both live-provider tests because the live gate was not enabled.
- `uv run ruff check .`, `uv run pyright`, `docker compose config --quiet`, and `git diff --check` passed. `pyright` reported 0 errors, 0 warnings, and 0 informations.
- Playwright Chromium is installed locally. The browser integration test uses a deterministic local HTML server; it does not prove the running API/Open WebUI journey.
- The live OpenAI, Tavily, and Langfuse checks have not been executed after credential rotation. The user reported that all three provider credentials were reissued; no credential values belong in this file or in logs.
- Direct API and Open WebUI checks confirmed new Langfuse traces, session grouping, task tags, tool error status, and string input and output.
- The old trace records and their historical captured data were not rewritten. The user has rotated and deleted the old API key outside this repository.

### Local test-suite work (uncommitted)

- Added unit coverage for API dependencies and health, CLI, domain errors, prompts, OpenAI client behavior, tool dispatch and registry, web search, filesystem edges, and browser session/actions.
- Added opt-in integration and e2e tests under `tests/integration/` and `tests/e2e/`.
- `pyproject.toml` excludes `integration` and `e2e` by default. `tests/conftest.py` injects dummy provider settings only when `BUILDAGENT_RUN_LIVE_TESTS` is not `1`.
- The live suite must be explicitly enabled and can contact external services. Do not paste keys or raw provider responses into the handoff.

## Current work

Active phase: Phase 4 browser automation.

Active task: verify the real running API/Open WebUI browser flow and live provider health after credential rotation, while separating the passing local browser integration from external-service verification.

Done when:

- New provider credential variables are confirmed non-empty without printing values, then the explicit live test command is run.
- The effective allowlist is confirmed from `.env`, settings, and the running API process; one permitted and one rejected URL are tested in the same process.
- Langfuse health and `tool:browser_open` observations, including final status, identify the failure or successful navigation.
- The real browser flow is verified through the running API/Open WebUI path, not only through the local Playwright test.
- The symptom, facts, rejected hypotheses, root cause, fix, and same-condition recheck are recorded in local ignored `docs/troubleshooting/` without secrets.

Next action: check only that the new credential variables are non-empty without printing values, then run `BUILDAGENT_RUN_LIVE_TESTS=1 uv run pytest -m "integration or e2e" -q`; record sanitized failures and do not paste keys.

## Boundaries and handoff

- Do not advance to the next Phase while this task is unresolved.
- Do not claim Phase 4 complete until the required real browser flow and allowlist behavior are verified. `browser_extract` and `browser_screenshot` are still not implemented and must not be represented as complete.
- Keep detailed troubleshooting in local ignored `docs/`; remove secrets before any portfolio version is made public.
- A new AI must compare this file with `git status`, the current source, and the latest runtime results. This file is a handoff and work target, not implementation authorization.
- Keep default unit tests external-free; live tests require the explicit `BUILDAGENT_RUN_LIVE_TESTS=1` gate.
- Preserve all current uncommitted files, including user test data. No commit or push.
- Do not commit or push without an explicit user request.

See [CLAUDE.md](CLAUDE.md) for operating rules, [ROADMAP.md](ROADMAP.md) for planned phases, and [docs/workflow.md](docs/workflow.md) for troubleshooting and handoff procedure.
