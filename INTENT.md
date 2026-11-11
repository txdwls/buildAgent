# Current Intent

Updated: 2026-11-11
Branch: `feature/context-management-design`
Base commit: `641cbdf` (`dev`, Merge pull request #7 from txdwls/feature/browser-extract-screenshot)
Working tree: Phase 5 implementation and its budget/metrics correction committed on this branch on 2026-11-11 at the user's request, pushed, with a PR to `dev`; design, ADR, and handoff stay under ignored `docs/`. Do not commit or push further without an explicit request.

## Project intent

Build and operate an AI agent with raw SDKs so that real failures can be reproduced, diagnosed, fixed, and reverified. The portfolio outcome is a working agent plus evidence based troubleshooting records. Open WebUI is the interface; the backend loop that selects tools, consumes results, and decides whether to continue or finish is the agent.

## Completed

### Implemented and merged into `dev`

- Phase 0: uv project, Python 3.12 tooling, settings, Docker Compose, and self-hosted Langfuse setup.
- Phase 1: raw OpenAI function calling loop, `web_search` with Tavily, CLI multi-turn flow, and Langfuse tracing.
- Phase 2: OpenAI compatible `/v1/chat/completions`, JSON and SSE responses, and Open WebUI integration.
- Phase 3 partial: filesystem read, write, list, and root jail. `code_exec` and `http_fetch` are not implemented.
- Phase 4 code side: lazy Playwright session plus `browser_open`, `browser_click`, `browser_type`, `browser_extract`, and `browser_screenshot`. Extract has attribute mode plus limit and total-char caps. Screenshot writes into the shared filesystem root-jail via the exposed `resolve_under_root` helper. Live provider verification is still deferred.
- Observability: request traces carry source, task, session, request ID, tool tags, final status, input, and output. The trace path no longer captures the client object or its API key.
- Test suite: default pytest excludes `integration` and `e2e`; `BUILDAGENT_RUN_LIVE_TESTS=1` gate enables live runs. Unit coverage across API dependencies and health, CLI, domain errors, prompts loader, OpenAI client, tool registry and dispatch, web_search, filesystem edges, browser session, and every browser action. Opt-in integration exercises the real Playwright flow end to end (open + type + click + extract + screenshot).
- Docs handoff: `INTENT.md` adopted as the per-session state file. `CLAUDE.md` explains the split.

### Design baseline

Phase 5 design was finalized by Codex Astra and implemented by Opus on 2026-09-12. [Design and Opus execution steps](docs/phases/phase-5-context-design.md) and [ADR 0001](docs/adr/0001-context-management-boundaries.md) are local ignored files. The 16,384 Settings minimum supersedes the original 8,192 floor and is implemented.

### Earlier design-session evidence

The results in this subsection predate Opus's Phase 5 implementation. Current Opus-reported results and Astra's independent reproductions are recorded below; do not use these older counts as current verification.

Design-session checks on 2026-09-12: local document links and new-file whitespace, language, and placeholder checks passed; `git diff --check` passed. No changes under `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `docker-compose.yml`, or `.env.example`.

- Latest merge on `dev`: `641cbdf Merge pull request #7 from txdwls/feature/browser-extract-screenshot`.
- `uv run pytest -q`: 81 passed, 4 integration/e2e tests deselected.
- `uv run pytest -m integration -q`: 1 passed (real Playwright flow including extract and screenshot with PNG header check), 1 skipped (Langfuse health, gated).
- `uv run ruff check .` and `uv run pyright` clean (0 errors, 0 warnings, 0 informations).

## Current work

Active phase: Phase 5 context management. Implementation plus the budget and metrics correction are done and verified on this branch.

Active task: review and merge the Phase 5 PR into `dev`. The estimator decision is closed (see open question 1).

Review on 2026-11-11 (Codex plus two Sonnet reviewers): HIGH 1 to 3 and MEDIUM 4 and 5 fixed in `410cb91` and `e952e62` (`uv run pytest -q`: 142 passed; ruff and pyright clean). Remaining findings are tracked in issue #9.

### Implemented on 2026-09-12 (Claude Code Opus, implementation session)

New files:

- `src/buildagent/context/__init__.py`, `src/buildagent/context/assembler.py`: pure estimate, validation, tool-content reduction, turn window, summary insertion.
- `src/buildagent/llm/summarizer.py`: one bounded non-streaming summary call.
- `tests/unit/context/test_assembler.py`, `tests/unit/llm/test_summarizer.py`.

Changed files:

- `src/buildagent/agent/loop.py`: one assembly point per iteration, `max_completion_tokens=4096`, `stream_options={"include_usage": True}`, finish_reason gate before tool dispatch, `context.assemble` and `model.usage` spans, per-call message snapshot.
- `src/buildagent/api/routes/openai_compat/chat.py`: assistant `tool_calls` preserved and validated, budget forwarded, JSON 400/413/502 and SSE error-event contract.
- `src/buildagent/cli/main.py`: budget forwarded, failed turn removed from history, non-zero exit for `--single`.
- `src/buildagent/config/settings.py`: `context_budget_tokens` range knob.
- `src/buildagent/prompts.py`: `context_summary` fallback text.
- `src/buildagent/domain/__init__.py`: `GuardrailBlocked` exported.
- `.env.example`: `CONTEXT_BUDGET_TOKENS` documented.
- Existing loop, API, CLI, config, and prompt tests extended with finish_reason, budget, and failure cases.

### Corrected on 2026-09-12 (Claude Code Opus, follow-up session)

Applied the four bounded corrections from the [Astra follow-up record](docs/troubleshooting/2026-09-12-context-budget-and-metrics.md):

1. `MIN_CONTEXT_BUDGET_TOKENS` raised to 16,384 in `context/assembler.py`; Settings validation, `.env.example`, and the config test follow. Default and maximum stay 32,768. Schemas are still charged against the limit. The summary input ceiling of 8,192 is unchanged.
2. `assemble` takes `can_summarize`; `agent/loop.py` passes `not summary_attempted`. A call that cannot summarize reserves only the omission-notice cost instead of 2,048.
3. `_fit_summary` now sizes by the fully serialized message cost with a binary search on UTF-8 byte boundaries, so escape-heavy summaries stay within the 2,048 reserve.
4. `_assemble_iteration` records `estimate(prepared, schemas)` as `input_estimate_after`, so the trace value is the request actually sent.

`message_cost` was made public for the reserve assertion in tests. No estimator change, no default-budget change, no new dependency.

### Verified evidence on 2026-09-12 (after the correction)

Commands actually run:

- `uv run pytest -q`: 131 passed, 4 integration/e2e deselected.
- `BUILDAGENT_RUN_LIVE_TESTS=1 uv run pytest -m "integration or e2e" -q`: 4 passed.
- `uv run ruff check .`: all checks passed.
- `uv run pyright`: 0 errors, 0 warnings, 0 informations.
- `git diff --check`: clean.

Offline reproductions of Astra's five checks, rerun against the corrected source:

| Check | Result after the fix |
|---|---|
| Minimum budget | `schema_bytes` 4,605, fallback system plus hello E 5,038. Blocked at 8,192 (limit 3,072); accepted at 12,288, 16,384 (limit 11,264), and 32,768 |
| Large protected input | Still blocked with `layer=context` at 16,384 |
| Post-summary metric | Stale pre-summary value 236 versus real final E 943. The loop now records the final value; a unit test asserts it equals the E of the sent messages |
| Repeat-iteration reservation | `can_summarize=True` drops 3 turns (E 1,124); `can_summarize=False` drops 1 turn (E 2,918, limit 3,072) |
| Escape-heavy summary | `message_cost` 2,048 exactly at the cap, down from 3,709. Total E 16,270, status success |

Live rerun of the same 45 KB Korean payload used in the implementation session (same file, so the same condition):

- JSON `/v1/chat/completions`: HTTP 200. SSE with `X-OpenWebUI-Chat-Id`: HTTP 200, 137 data events, no error event, final `finish_reason=stop`.
- Langfuse, JSON request: `input_estimate_before=50702`, `input_estimate_after=22981`, `dropped_turns=5`, `summary_status=success`, `summary_source_omitted_turns=4`, `actual_prompt_tokens=4996`.
- Langfuse, SSE request: `input_estimate_after=22936`, same reduction shape, `actual_prompt_tokens=4980`.
- The pre-fix runs recorded 22,319 for the same payload, which was the pre-summary value.

Manual Open WebUI verification, now complete:

- API served on port 8000 to match `OPENAI_API_BASE_URLS`; browser driven against `http://localhost:3001`, model `gpt-5.6-luna`, one Korean question about the vector-store candidates.
- The UI rendered a three-line Korean answer that names Chroma, LanceDB, and pgvector and states that the reference link content could not be inspected.
- Langfuse session `43f63b48-5568-44ba-9f61-cb8cdcc40355` holds four traces: `agent.openwebui.chat`, `.title`, `.followup`, `.tags`. The chat trace shows `input_estimate_after=5270`, `summary_status=not_needed`, `actual_prompt_tokens=894`.

### Re-measured estimate versus usage

Final-input estimate against provider-reported prompt tokens, using corrected metrics. Prose samples come from the long-history reruns and the Open WebUI conversation; tool samples come from dedicated `fs_read` requests added on 2026-09-12.

| Sample | Dominant content | `input_estimate_after` | `actual_prompt_tokens` | Bytes per token |
|---|---|---|---|---|
| fs_read of a 19,342 byte ASCII JSON file | tool result, ASCII JSON | 27,544 | 6,904 | 4.0 |
| JSON long history | Korean prose plus schemas | 22,981 | 4,996 | 4.6 |
| SSE long history | Korean prose plus schemas | 22,936 | 4,980 | 4.6 |
| fs_read of a 15,960 byte Korean file | tool result, Korean prose | 21,377 | 4,560 | 4.7 |
| fs_read of a 94,999 byte Korean file, truncated | truncated tool result | 9,511 | 1,839 | 5.2 |
| Open WebUI title | English task prompt plus Korean | 6,342 | 1,125 | 5.6 |
| Open WebUI chat | short Korean plus schemas | 5,270 | 894 | 5.9 |
| First iteration, schemas plus one question | ASCII tool schemas | 5,131 | 865 | 5.9 |

The earlier "4.4 times too conservative" reading does not hold. The ratio is a bytes-per-token property of the estimator, and the full measured range is 4.0 to 5.9.

The tool-result sample that was missing is now captured, and it moves the floor rather than the average. ASCII JSON tool output is the densest content measured at 4.0 bytes per token, so it is where the byte budget has the least margin, not the most. The JSON request estimated 27,544 against the 27,648 limit, 104 units of headroom, and would have been reduced by a slightly larger file.

Live tool-content truncation ran for the first time in the 94,999 byte case: `truncated_tool_results=1`, the final estimate fell to 9,511, and the model still answered from the truncated content. A 189,040 byte file was refused by `fs_read`'s own 100,000 byte cap before assembly saw it, and the agent reported that limit to the user instead of failing.

Reproduction fixtures live in the gitignored root jail: `data/workspace/phase5-tool-sample-ko.txt`, `-json.txt`, and `-big.txt`. The pre-existing `agent-test.txt` was not touched.

### Open questions for the next session

1. Whether to introduce a bytes-per-token divisor. The measured range is 4.0 to 5.9, so any divisor must be safe at 4.0; dividing by the 4.8 average would under-estimate ASCII JSON tool results by about 20 percent and could push a real request past the provider's input ceiling. Dividing by 4 would roughly quadruple usable history while staying conservative for every sample so far. Recommendation: either divide by 4 or leave the byte budget alone; do not use an average. Decided by the user on 2026-11-11: leave the byte budget unchanged. Revisit only when a reproduced request loses a fact the answer needed.
2. No request has yet lost a fact the answer needed. Every reduction so far still produced a correct answer, so there is no quality-driven reason to loosen the budget.
3. Registering `context_summary` in Langfuse with label `production` remains a user operation. The local fallback is the intended path and was in use for every run above.

## Boundaries and handoff

- Both implementation sessions are complete and were committed and pushed on 2026-11-11 at the user's request. The earlier design documentation is preserved.
- `.graphify/` (local graphify knowledge graph) was added to `.gitignore` on 2026-11-11 at the user's request. The `docs/` ignore rule is unchanged.
- No new dependencies, runtime model migration, or automatic Phase advancement. Design and implementation now both belong to Claude Code; record the evidence for any design change here and get the user's go-ahead before acting on it.
- `docs/` is gitignored, so use this local checkout for the handoff. Do not change ignore rules or force-add design files. Promoting the ADR for publication remains a separate user request.
- A new AI must compare this file with `git status`, the current source, and the latest runtime results. This file is a handoff and work target, not implementation authorization.
- Do not commit or push without an explicit user request.

### Deferred but still on the roadmap

- Phase 4 manual browser-tool verification in the UI. The Phase 5 UI conversation is done, but no UI session exercised the Playwright browser tools end to end.
- Phase 3 remainder: `code_exec`, `http_fetch`.

See [CLAUDE.md](CLAUDE.md) for operating rules, [ROADMAP.md](ROADMAP.md) for planned phases, and [docs/workflow.md](docs/workflow.md) for troubleshooting and handoff procedure.
