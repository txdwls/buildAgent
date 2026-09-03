# Roadmap

각 Phase는 독립적으로 굴러가는 상태로 끝난다. 완성 기준은 CLI 혹은 UI로 실제 대화가 되고 Langfuse에 trace가 남는 상태.

## Phase 0. 인프라 세팅

- uv 프로젝트, pyproject.toml
- ruff, pyright, pytest 설정
- docker-compose: Langfuse self-host (Postgres, Clickhouse, langfuse-server)
- `.env.example`, pydantic-settings 기반 config 로딩

## Phase 1. 독립 에이전트 MVP

- OpenAI SDK function calling loop 구현 (`tool_calls` 처리, `role: "tool"` 메시지 반환)
- Tool 1개: `web_search` (Tavily)
- FastAPI 및 Langfuse trace 연결
- CLI로 다중 turn 대화 테스트

## Phase 2. OpenAI 호환 및 Open WebUI 연결

- `POST /v1/chat/completions` (SSE streaming) 엔드포인트 노출
- 내부 에이전트 loop의 최종 assistant 응답을 chunk로 스트리밍, tool 실행 진행 상황은 assistant 메시지에 인라인 표시
- Open WebUI docker-compose 연결
- 채팅창에서 tool 실행 진행 상황 노출

## Phase 3. Tools 확장

- `filesystem` (read, write, list, root-jail)
- `code_exec` (Python subprocess, 타임아웃)
- `http_fetch` (URL allowlist)
- 각 tool 별 Langfuse span

## Phase 4. Browser 자동화 tools

- Playwright 헤드리스 세션 관리 (컨텍스트 재사용, 타임아웃, 리소스 정리)
- Tool: `browser_open`, `browser_click`, `browser_type`, `browser_extract`, `browser_screenshot`
- 가드레일: URL allowlist, action budget, 세션 격리
- Langfuse span에 스크린샷 또는 HTML 스냅샷 attach
- 선택 사항으로 Anthropic Computer Use API 실험. 스크린샷 기반 조작과 DOM 갈래의 지연, 비용 비교

## Phase 5. 컨텍스트 관리 심화

- Turn 요약 압축
- Tool 결과 축약 (부피 큰 응답: HTML 덤프, 검색 결과)
- system, tool, 대화, 현재 입력 조합 순서 실험

## Phase 6. Reflection 패턴

- self-critique 뒤 revise 루프
- reflection이 도움되는 케이스와 낭비되는 케이스 벤치
- Langfuse trace로 지연과 비용 시각화

## Phase 7. RAG (naive 이후 agentic)

- Vector store 결정 (Chroma, LanceDB, pgvector)
- Naive RAG: 항상 검색 후 context 삽입
- Agentic RAG: 검색을 tool로 노출, 다단계 재검색
- 인덱스 대상: 위키, 공개 문서 중 LLM이 모를 만한 자료

## Phase 8. Planner-Executor 패턴

- planner tool로 `spawn_executor(task, tools_allowed)`
- executor의 sub-loop (같은 loop 코드 재귀)
- context 격리 이유 실험 (context 오염 vs 정보 손실)

## Phase 9. Multi-agent (supervisor, worker)

- supervisor 및 특화 worker(researcher, coder, writer 등)
- worker 간 통신 프로토콜 (message envelope)
- 라우팅 오류 시 폴백

## Phase 10. 가드레일 강화

- Input: PII regex 이후 LLM classifier
- Output: PII 마스킹, groundedness judge
- Execution: subprocess 이후 Docker 샌드박스, network 차단
- Browser: URL allowlist 정교화, credential vault

## Phase 11. Eval Harness

- YAML dataset, `expected_tools`, judge prompt
- `evals/run.py`: 회귀 실행 후 Langfuse score attach
- 프롬프트 변경 시 자동 회귀 리포트

## Phase 12. 안정성 및 비용

- Retry (tenacity), fallback model
- Prompt caching 적용 및 효과 측정
- Rate limit token bucket
- 비용 대시보드
