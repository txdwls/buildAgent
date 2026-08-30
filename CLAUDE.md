# CLAUDE.md

이 리포에서 에이전트 도구(Claude Code 등)가 따를 규칙과, 리포가 다루는 AI 에이전트 개념, 로드맵 전부를 담는 문서.

---

## 1. 리포 개요

AI 엔지니어로 취업하기 위해 **AI 에이전트를 raw SDK로 직접 만들고 운영하며 학습**하는 리포지토리.

- 프레임워크 뒤에 숨은 원리를 이해하는 것이 목적이라 LangGraph, CrewAI 등은 의도적으로 배제한다.
- OpenAI SDK의 function calling(`tool_calls`) 위에 루프, 컨텍스트, 관측, 평가, 가드레일을 하나씩 손으로 쌓아 올린다.
- 프로덕션 관점(관측, 가드레일, 평가, 비용)까지 얹어 실무 서사를 확보한다.

### 학습 목표 (면접에서 답할 수 있어야 할 것)

- function calling 루프의 실제 동작 원리와 `finish_reason` / `tool_calls` 처리
- 여러 에이전트 패턴(**독립, reflection, planner-executor, multi-agent, router, HITL**)의 트레이드오프
- 컨텍스트 관리(대화 이력, 압축, 메모리) 전략과 한계
- RAG의 한계와 agentic RAG가 필요한 이유
- 가드레일 설계(입출력 검증, PII, jailbreak, 실행 샌드박스)와 트레이드오프
- 관측(trace, span, generation)과 평가(offline eval, LLM-as-judge)의 실전 흐름
- 안정성(retry, fallback, prompt caching)과 비용 관리

### 범위와 비범위

**포함**
- OpenAI API function calling 기반 에이전트 백엔드
- OpenAI 호환 엔드포인트로 노출 후 Open WebUI로 채팅
- Langfuse self-host (docker compose)로 관측
- 가드레일, 평가, 안정성 요소

**제외**
- 프론트엔드 자체 개발 (Open WebUI, LibreChat 등 오픈소스 재사용)
- 에이전트 프레임워크 (raw SDK 학습이 목표)
- 배포/운영 인프라 (로컬 학습용)

---

## 2. 작업 규칙 (Claude Code 대상)

### 절대 지켜야 할 것

- **사용자가 명시적으로 트리거하기 전까지 구현 코드를 작성하지 않는다.** 개념 문서와 설계 단계에서 `src/`, `pyproject.toml`, docker 파일 등 실 구현 산출물 생성 금지.
- **Ponytail 원칙**: 가장 라자한 해법 우선. 사다리(YAGNI, 기존 코드 재사용, 표준 라이브러리, 네이티브, 기존 의존성, 한 줄, 최소 구현)를 순서대로 밟고 필요할 때만 코드.
- **언어**: 사용자와의 대화는 한국어. 코드, 주석, 커밋 메시지는 영어. 서브에이전트 프롬프트도 영어.
- **자동 서브에이전트 스폰 금지**: 사용자가 명시적으로 요청할 때만 `Agent` 도구 사용.
- **자동 커밋, push 금지**: 사용자 지시 후에만.
- **destructive git 작업 금지**: `reset --hard`, `push --force`, 브랜치 삭제 등은 명시 요청 시에만.
- **특수 기호 및 특수 문자 사용 절대 금지**: 이모지, 유니코드 화살표, 박스 그리기 문자, 가운뎃점, em dash, 기타 유니코드 장식 기호는 어떤 상황에서도 쓰지 않는다. 오로지 일반 텍스트, 표준 ASCII 구두점, 표준 마크다운 문법(제목, 리스트, 코드 블록, 표, 링크, 굵게, 기울임)만 허용. 코드, 문서, 커밋 메시지, 사용자 응답 모두 동일하게 적용.

### 개발 도구

- 패키지: `uv add`, `uv sync`, `uv run`
- Lint 및 Format: `uv run ruff check .`, `uv run ruff format .`
- Type check: `uv run pyright` (strict 모드)
- Test: `uv run pytest`

### 코딩 스타일

- Python 3.12
- KISS, DRY, YAGNI
- 함수 50줄 미만, 파일 400줄 미만 권장
- immutable 패턴 우선 (기존 객체 mutate 금지)
- 명시적 에러 핸들링 (silent swallow 금지)
- 시크릿 하드코딩 금지, 반드시 env로 주입
- 명명: Python은 PEP 8 준수. `snake_case` 변수 및 함수 및 모듈, `PascalCase` 클래스 및 타입, `UPPER_SNAKE_CASE` 상수, `is`, `has`, `should`, `can` 접두 boolean. ruff의 `N` 룰이 강제한다.

### 하지 말 것

- 사용자 지시 없는 새 의존성 추가
- 이 리포 스코프 밖 파일 수정
- 개념 문서가 확정되기 전 구현 산출물 생성

### 커밋 컨벤션

- 포맷: `<type>(<scope>): <description>` (Conventional Commits 준수).
- 타입: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.
- 한 커밋 = 한 논리 단위. 여러 관심사를 한 커밋에 섞지 않는다. 리팩터, 신규 기능, 테스트, 설정 변경은 각각 별도 커밋.
- description은 그 커밋이 실제로 무엇을 바꿨는지 구체적으로 서술. `feat(phase-2): phase 2 작업 전체` 같은 두루뭉술한 요약 금지. `feat(api): expose /v1/chat/completions with SSE streaming` 처럼 결과물 자체를 명시.
- 여러 커밋으로 나눠서 PR에서 커밋 단위로 리뷰가 가능하게 한다. squash merge 금지 (또는 신중), 기본은 merge commit으로 히스토리 보존.

### PR 컨벤션

- 본문 언어는 한국어. 제목은 커밋 컨벤션을 그대로 따르므로 영어(`type(scope): description`)를 유지한다.
- Base 브랜치는 항상 `dev`. `main`으로 직접 PR을 열지 않는다.
- 본문은 길고 자세하게 쓴다. 요약 한 문단으로 끝내지 말고 목적별 헤더로 섹션을 나눠 서술한다. 기본 헤더는 Summary, Motivation, Changes, Approach, Test plan을 쓰고, 필요에 따라 Deferred, Follow-ups, Screenshots, References 등을 추가한다.
- Summary는 이 변경이 무엇을 했는지 결과물 자체로 명시한다. `feat(phase-3): phase 3 작업` 같은 두루뭉술한 요약은 금지한다.
- Motivation은 이 변경이 왜 필요한지, 어떤 문제나 결함을 해결하는지 서술한다.
- Changes는 추가, 삭제, 수정된 파일 또는 모듈을 항목별로 나열한다.
- Approach는 채택한 접근법과 대안, 라자한 선택의 근거, 남긴 트레이드오프를 설명한다.
- Test plan은 실제로 돌린 명령과 결과를 나열한다. 예: `uv run pytest 결과 13 중 13 통과`. 검증 못한 항목은 체크 안 된 상태로 남긴다.
- 한 PR은 한 논리 단위. 커밋은 커밋 컨벤션대로 분리해서 커밋 단위 리뷰가 가능해야 한다.
- 본문에 특수문자와 특수기호를 쓰지 않는다. 이모지, 유니코드 화살표, 박스 그리기 문자, 가운뎃점, em dash, 기타 유니코드 장식 기호는 어떤 상황에서도 사용 금지. 오로지 일반 텍스트, 표준 ASCII 구두점, 표준 마크다운 문법(제목, 리스트, 코드 블록, 표, 링크, 굵게, 기울임)만 허용. 이 규칙은 2절의 전역 특수 기호 금지 규칙을 PR 본문에도 그대로 적용한 것이다.

---

## 3. 기술 스택

| 층위 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.12 | AI 엔지니어 생태계 표준 |
| 패키지 | `uv` | 빠르고 pyproject.toml 표준 |
| Lint, Format | `ruff` | uv와 궁합, 속도 |
| Type check | `pyright` (strict) | 협업 시 표준 |
| Test | `pytest` | 표준 |
| 웹 | FastAPI, SSE | 스트리밍, OpenAI 호환 구현 용이 |
| LLM | OpenAI (기본), Anthropic Claude (fallback 후보) | function calling 명세 학습 목적 |
| 에이전트 | raw SDK loop | 프레임워크 배제 |
| 프론트 | Open WebUI (docker) | 검증된 오픈소스 재사용 |
| 관측 | Langfuse self-host (docker) | trace, eval 표준, self-host 경험 |
| Vector store | 미정 (Chroma, LanceDB, pgvector 후보) | Phase 7 진입 시 결정 |

---

## 4. 핵심 개념 정리

### 4.1 에이전트란 무엇인가

에이전트는 **LLM 더하기 tools 더하기 loop**로 정의된다.

- LLM 단독은 텍스트 생성만 한다. 도구를 호출할 수 있고, 도구 결과를 받아 **다음 결정에 반영하는 루프**가 있어야 에이전트다.
- 워크플로(사람이 짠 결정 트리)와의 차이는, 에이전트가 **다음에 뭘 할지 LLM이 결정**한다는 점이다. 결정권을 LLM에 위임한 만큼 관측과 가드레일이 필수가 된다.

### 4.2 Tool Use 프로토콜 (OpenAI function calling)

한 번의 API 호출이 한 번의 결정.

```
messages 전송, LLM 응답, choices[0].finish_reason 및 message.tool_calls 확인

finish_reason 처리:
- "stop":          최종 답. 루프 종료.
- "tool_calls":    어떤 function을 어떤 인자로 부를지 지정 (message.tool_calls 배열). 실행 후 결과 반환.
- "length":        max_tokens 소진. 잘라 처리하거나 재시도.
- "content_filter": 정책 필터 컷. 사용자에게 알리고 종료.
```

Tool 결과는 `role: "tool"` 메시지로 다음 요청에 실려 들어가며, 각 결과는 원 `tool_call`의 `id`를 `tool_call_id`로 참조해야 한다. **모델은 tool 결과를 봤다는 사실을 API가 아니라 messages 배열로만 안다.** 이 인식이 컨텍스트 관리와 직결된다.

### 4.3 에이전트 루프

```python
messages = [system, user]
while True:
    resp = client.chat.completions.create(model=..., tools=..., messages=messages)  # retry, fallback, caching 적용
    msg = resp.choices[0].message
    messages.append(msg)
    if not msg.tool_calls:
        return msg.content
    for call in msg.tool_calls:
        result = dispatch(call.function.name, call.function.arguments)
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
```

이 20줄이 모든 에이전트의 뼈대다. 이후 챕터는 이 루프의 어떤 위치에 무엇을 끼우느냐의 문제.

### 4.4 컨텍스트 관리

**문제**: messages 배열은 turn마다 계속 쌓인다. 토큰 예산, 비용, 품질 모두 저하.

전략:
- **Sliding window**: 최근 N개 turn만 유지, 그 이전은 요약.
- **Summarization**: 오래된 turn을 LLM으로 요약해 하나의 시스템 메시지로 접기.
- **Selective retention**: tool_result 중 부피 큰 것(HTML 덤프 등)을 요약 또는 삭제, 결정은 유지.
- **External memory**: 벡터 store에 넣고 필요할 때 검색 (agentic RAG와 연결).

**조합 순서(권장)**: system prompt, tool 설명, 검색된 외부 메모리, 요약된 과거 turn, 최근 turn, 현재 user 입력 순. 최근 정보가 뒤에 올수록 모델이 잘 참조한다.

### 4.5 에이전트 패턴

| 패턴 | 요지 | 언제 | 트레이드오프 |
|---|---|---|---|
| **독립 에이전트 (single-loop)** | 하나의 LLM이 tools 다 부름 | 대부분의 시작점 | 단순. 복잡한 계획엔 약함 |
| **Reflection** | 응답 후 self-critique 뒤 재응답 | 품질 민감, 오답 비용 큼 | 지연과 비용 2배 |
| **Planner-Executor** | planner가 계획 세우고 executor가 실행 | 다단계 작업 | 조율 오버헤드 |
| **Multi-agent (supervisor, worker)** | supervisor가 특화 worker에게 위임 | 도메인이 뚜렷이 다름 | 통신 프로토콜 설계 부담 |
| **Router** | 첫 LLM이 어떤 하위 에이전트로 보낼지 판단 | 다양한 유형 요청 | 라우팅 오류 시 파장 |
| **Human-in-the-loop** | 위험 작업 전 사람 승인 | 파괴적 tool(fs write, exec) | UX 흐름 끊김 |

**리포 시작점은 독립 에이전트**다. 이걸 관측, 가드레일, 평가와 함께 완성한 뒤 다른 패턴을 얹는다.

### 4.6 RAG: naive vs agentic

- **Naive RAG**: 요청마다 검색하고 context 앞에 삽입. 항상 검색. 간단하지만 불필요한 검색과 잘못된 검색어 문제가 있다.
- **Agentic RAG**: 검색을 **tool로** 노출. LLM이 필요할 때 필요한 쿼리로 검색, 결과 부족하면 재검색. 다단계 질문에 강함.

이 리포는 Phase 7에서 naive 이후 agentic 순서로 밟는다. 인덱스 대상은 LLM이 모를 만한 자료(위키, 공개 문서 등)를 사후 결정.

### 4.7 가드레일

층별로 나눠 사고한다.

| 층 | MVP (rule 기반) | 심화 |
|---|---|---|
| 입력 | PII regex(주민번호, 전화, 이메일), jailbreak 키워드 리스트 | LLM classifier(prompt injection), rate limit |
| 출력 | PII 마스킹, 금칙어 | groundedness judge, structured output 검증 |
| 실행 | tool 타임아웃, filesystem root-jail | Docker 샌드박스, network 차단 |

**핵심 원칙**: 가드레일은 품질 검사가 아니라 **신뢰 경계**다. 신뢰 경계(사용자 입력, 외부 API 응답, tool 결과)에서만 검증. 내부 함수 호출마다 검증하면 코드가 방어로 도배된다.

### 4.8 관측 (Observability)

Langfuse의 계층:

- **Trace**: 하나의 대화 세션 (혹은 하나의 요청).
- **Span**: turn, tool call, guardrail 검사 등 논리 단위.
- **Generation**: 실제 LLM 호출 (모델, 토큰, 비용, 프롬프트, 응답).

관측이 없으면 왜 이 답이 나왔는지 재현 불가, 어떤 tool이 자주 실패하는지 모름, 프롬프트 개선 효과를 정량화 못 함. 관측이 있으면 evaluation, regression, 비용 대시보드가 자연스럽게 붙는다.

### 4.9 평가 (Evaluation)

**Offline eval**
- 작은 dataset (YAML): `{input, expected_tools, expected_criteria}`.
- 각 케이스 실행, 결과를 **LLM-as-judge**로 채점, Langfuse score 저장.
- 프롬프트나 모델 변경 시 회귀 감시.

**Online eval**
- production trace에 score attach (사용자 피드백, heuristic score).
- 프롬프트 A/B, cohort 비교.

**LLM-as-judge의 한계**: judge 자신이 편향과 환각을 가진다. rubric을 좁게, 결정적으로. 필요하면 판정 근거를 함께 저장해 사후 검증.

### 4.10 안정성 및 비용

- **Retry**: 429, 5xx, timeout에 exponential backoff 및 jitter.
- **Fallback**: primary(gpt-5 등) 실패 시 secondary(gpt-4.1 mini 등)로 자동 전환. 필요 시 Anthropic Claude로도 우회.
- **Prompt caching**: OpenAI는 1024+ 토큰 프리픽스에 대해 자동 캐싱. 시스템 프롬프트와 tool 정의를 messages 앞쪽에 고정해 hit율 유지.
- **Rate limit 대응**: token bucket으로 요청 페이싱.
- **비용 관측**: 모든 generation에 model, input_tokens, output_tokens, usd 기록.

### 4.11 Browser 자동화 및 Computer Use

- **왜 필요한가**: 현대 웹의 상당수는 JS 렌더링, 로그인, 인터랙션 없이는 접근 불가. 단순 HTTP fetch로 못 얻는 정보를 에이전트 tool로 노출한다. RPA, 스크래핑, UI 조작이 모두 여기 얹힌다.
- **두 갈래**:
  - **DOM 기반 (Playwright, Puppeteer, CDP)**: 헤드리스 브라우저 자동화. 페이지 이동, 셀렉터 클릭, form 입력, HTML 추출. 결정적이고 재현 가능. 대부분의 스크래핑, 자동화에 우선 선택.
  - **화면 기반 (Anthropic Computer Use)**: 모델이 스크린샷을 보고 좌표로 클릭, 타자. DOM 접근이 막히거나 시각 UI 위주인 경우에 강함. 지연과 비용 크고 오답 확률 높음. DOM 갈래 실패 시의 fallback 성격.
- **Tool 노출 방식**: `browser.open(url)`, `browser.click(selector)`, `browser.type(selector, text)`, `browser.extract(selector)`, `browser.screenshot()` 처럼 원자적 tool로 쪼갠다. LLM에게 큰 tool 하나(`browser.do_task`)만 주면 무엇을 했는지 추적 불가.
- **위험 요소**: 사이트 ToS, robots.txt, rate limiting, 로그인 credential 관리, headless 탐지, 무한 리다이렉트. 가드레일 층에서 **URL allowlist, action budget(최대 클릭 횟수), 세션 격리** 필수.
- **관측**: 각 action은 Langfuse span으로. 스크린샷, HTML 스냅샷을 attach하면 실패 재현 쉬움.

---

## 5. 로드맵

각 Phase는 독립적으로 굴러가는 상태로 끝난다. 완성 기준은 **CLI 혹은 UI로 실제 대화가 되고 Langfuse에 trace가 남는 상태**.

### Phase 0. 인프라 세팅
- uv 프로젝트, pyproject.toml
- ruff, pyright, pytest 설정
- docker-compose: Langfuse self-host (Postgres, Clickhouse, langfuse-server)
- `.env.example`, pydantic-settings 기반 config 로딩

### Phase 1. 독립 에이전트 MVP
- OpenAI SDK function calling loop 구현 (`tool_calls` 처리, `role: "tool"` 메시지 반환)
- Tool 1개: `web_search` (Tavily)
- FastAPI 및 Langfuse trace 연결
- CLI로 다중 turn 대화 테스트

### Phase 2. OpenAI 호환 및 Open WebUI 연결
- `POST /v1/chat/completions` (SSE streaming) 엔드포인트 노출
- 내부 에이전트 loop의 최종 assistant 응답을 chunk로 스트리밍, tool 실행 진행 상황은 assistant 메시지에 인라인 표시
- Open WebUI docker-compose 연결
- 채팅창에서 tool 실행 진행 상황 노출

### Phase 3. Tools 확장
- `filesystem` (read, write, list, root-jail)
- `code_exec` (Python subprocess, 타임아웃)
- `http_fetch` (URL allowlist)
- 각 tool 별 Langfuse span

### Phase 4. Browser 자동화 tools
- Playwright 헤드리스 세션 관리 (컨텍스트 재사용, 타임아웃, 리소스 정리)
- Tool: `browser_open`, `browser_click`, `browser_type`, `browser_extract`, `browser_screenshot`
- 가드레일: URL allowlist, action budget, 세션 격리
- Langfuse span에 스크린샷 또는 HTML 스냅샷 attach
- 선택 사항으로 Anthropic Computer Use API 실험. 스크린샷 기반 조작과 DOM 갈래의 지연, 비용 비교

### Phase 5. 컨텍스트 관리 심화
- Turn 요약 압축
- Tool 결과 축약 (부피 큰 응답: HTML 덤프, 검색 결과)
- system, tool, 대화, 현재 입력 조합 순서 실험

### Phase 6. Reflection 패턴
- self-critique 뒤 revise 루프
- reflection이 도움되는 케이스와 낭비되는 케이스 벤치
- Langfuse trace로 지연과 비용 시각화

### Phase 7. RAG (naive 이후 agentic)
- Vector store 결정 (Chroma, LanceDB, pgvector)
- Naive RAG: 항상 검색 후 context 삽입
- Agentic RAG: 검색을 tool로 노출, 다단계 재검색
- 인덱스 대상: 위키, 공개 문서 중 LLM이 모를 만한 자료

### Phase 8. Planner-Executor 패턴
- planner tool로 `spawn_executor(task, tools_allowed)`
- executor의 sub-loop (같은 loop 코드 재귀)
- context 격리 이유 실험 (context 오염 vs 정보 손실)

### Phase 9. Multi-agent (supervisor, worker)
- supervisor 및 특화 worker(researcher, coder, writer 등)
- worker 간 통신 프로토콜 (message envelope)
- 라우팅 오류 시 폴백

### Phase 10. 가드레일 강화
- Input: PII regex 이후 LLM classifier
- Output: PII 마스킹, groundedness judge
- Execution: subprocess 이후 Docker 샌드박스, network 차단
- Browser: URL allowlist 정교화, credential vault

### Phase 11. Eval Harness
- YAML dataset, `expected_tools`, judge prompt
- `evals/run.py`: 회귀 실행 후 Langfuse score attach
- 프롬프트 변경 시 자동 회귀 리포트

### Phase 12. 안정성 및 비용
- Retry (tenacity), fallback model
- Prompt caching 적용 및 효과 측정
- Rate limit token bucket
- 비용 대시보드

---

## 6. 디렉토리 구조

전체 Phase(1~12)를 예상해 계층을 앞에서 잡되, **각 Phase 진입 시점에 그 슬롯에만 파일을 채운다. 빈 스텁 폴더는 만들지 않는다.**

```
buildAgent/
├── src/buildagent/                # src-layout
│   ├── __init__.py
│   ├── __main__.py                # python -m buildagent → CLI
│   ├── config/
│   │   ├── settings.py            # pydantic-settings Settings
│   │   ├── logging.py             # stdlib logging + JSON formatter
│   │   └── constants.py
│   ├── domain/                    # 순수 도메인. I/O·SDK 임포트 금지
│   │   ├── messages.py            # Message, Role, ToolCall, ToolResult (frozen)
│   │   ├── tool.py                # Tool Protocol
│   │   ├── agent_state.py
│   │   └── errors.py
│   ├── llm/                       # OpenAI SDK가 임포트되는 유일한 층
│   │   ├── base.py                # LLMClient Protocol
│   │   ├── openai_client.py
│   │   ├── retry.py               # tenacity 정책
│   │   ├── fallback.py
│   │   └── caching.py             # prompt-cache prefix 정렬
│   ├── tools/
│   │   ├── registry.py            # 등록/lookup, OpenAI function schema 익스포트
│   │   ├── dispatch.py            # tool_call → ToolResult (span 자동)
│   │   ├── web_search.py          # Phase 1: Tavily
│   │   ├── filesystem.py          # Phase 3
│   │   ├── code_exec.py           # Phase 3
│   │   ├── http_fetch.py          # Phase 3
│   │   └── browser/               # Phase 4
│   │       ├── session.py
│   │       ├── actions.py
│   │       └── budget.py
│   ├── agent/
│   │   ├── loop.py                # 코어 function-calling loop
│   │   ├── runner.py              # loop + tools + context + guardrails 조립
│   │   ├── reflection.py          # Phase 6
│   │   ├── planner_executor.py    # Phase 8
│   │   └── supervisor.py          # Phase 9
│   ├── context/                   # Phase 5
│   │   ├── window.py
│   │   ├── summarizer.py
│   │   ├── selective.py
│   │   └── assembler.py           # system|tools|memory|summary|recent|input 순
│   ├── memory/                    # Phase 7+
│   │   ├── base.py
│   │   ├── vector/{base,chroma}.py
│   │   └── retriever.py
│   ├── rag/                       # Phase 7
│   │   ├── naive.py
│   │   ├── agentic.py
│   │   └── indexer.py
│   ├── guardrails/                # Phase 10 (Phase 1부터 최소 스캐폴드)
│   │   ├── base.py
│   │   ├── input/{pii,jailbreak}.py
│   │   ├── output/{pii_mask,groundedness}.py
│   │   └── execution/{timeout,sandbox}.py
│   ├── observability/             # Langfuse
│   │   ├── tracer.py
│   │   ├── generation.py          # LLM 호출 wrap (토큰·비용)
│   │   ├── cost.py                # 모델별 USD 테이블
│   │   └── spans.py
│   ├── prompts.py                 # Langfuse prompt management 래퍼 (get_prompt, 캐시, fallback)
│   ├── api/
│   │   ├── app.py                 # FastAPI factory
│   │   ├── dependencies.py        # DI: FastAPI Depends
│   │   ├── errors.py
│   │   └── routes/
│   │       ├── health.py
│   │       └── openai_compat/{chat,models,streaming}.py   # Phase 2
│   └── cli/
│       ├── main.py                # argparse 기반
│       ├── chat.py                # 다중 turn REPL
│       └── eval.py
├── tests/
│   ├── conftest.py                # LLM stub, Tool stub 픽스처
│   ├── unit/                      # 네트워크·파일 없음
│   ├── integration/               # 실 Langfuse, LLM은 vcr/stub
│   └── e2e/                       # 실 OpenAI (opt-in env flag)
├── evals/                         # Phase 11
│   ├── datasets/*.yaml            # {input, expected_tools, criteria}
│   ├── judges/                    # LLM-as-judge 프롬프트도 Langfuse에 두되, run.py가 fetch
│   ├── run.py
│   └── reports/                   # gitignored
├── scripts/
│   ├── bootstrap.sh               # uv sync + docker up + wait-healthy
│   └── langfuse_smoke.py
├── ops/
│   ├── docker/                    # compose.override 예시
│   └── openwebui/                 # Phase 2 add-on
├── docs/
│   ├── adr/                       # 결정 기록 (면접용 서사)
│   ├── phases/                    # Phase별 회고 (트레이드오프·수치·트레이스 캡처)
│   ├── concepts/                  # §4 요약본
│   └── observability/             # 트레이스 스크린샷 + 해설
├── .github/workflows/
│   ├── ci.yml                     # ruff + pyright + pytest
│   └── eval.yml                   # 야간 eval (Phase 11 이후)
├── .env / .env.example
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── README.md
├── CLAUDE.md
├── AGENTS.md
└── LICENSE
```

### 6.1 구조 원칙

- **의존성 방향**: `domain` ← `llm`/`tools`/`observability`/`prompts` ← `agent` ← `api`/`cli`. domain은 어떤 SDK도 안 본다. OpenAI SDK는 `llm/` 안에만.
- **한 Phase가 한 폴더**: Phase 진입 시 그 폴더만 커지고 나머지는 손대지 않음.
- **`prompts/` 로컬 폴더 없음**: 시스템 프롬프트, tool 설명, judge rubric, reflection critique 등 모든 프롬프트는 **Langfuse prompt management**에 등록·버저닝. 코드는 `src/buildagent/prompts.py`의 얇은 래퍼(`get_prompt(name, label="production")`, 캐시, fallback 문자열)로 fetch.
- **`docs/adr/` + `docs/phases/`**: 면접 서사가 여기 쌓임. 코드만 남기면 학습 증거가 없음.

### 6.2 확정된 구현 결정 (Phase 1 진입 전)

| 항목 | 선택 | 이유 |
|---|---|---|
| 프롬프트 관리 | Langfuse prompt management | 코드와 프롬프트 커밋 분리, 버전 diff·성능 대비 UI 지원, eval 회귀 대상과 정합 |
| CLI 프레임워크 | stdlib `argparse` | 옵션 손 아플 때만 typer 도입 |
| 로깅 | stdlib `logging` + JSON formatter | structlog은 정말 필요할 때 |
| DI | FastAPI `Depends` | 별도 컨테이너 미도입 |
| 테스트 층 분리 | `@pytest.mark.integration`, `@pytest.mark.e2e` | 기본 `pytest` 실행에서 e2e 제외 |

### 6.3 Git 브랜치 전략

- `main`: 항상 배포 가능한 안정 상태. 직접 커밋 금지. `dev`로부터의 merge만 받는다.
- `dev`: 통합 브랜치. 모든 feature 브랜치가 여기로 PR merge된다. 릴리스 시점에 `dev` → `main`.
- `feature/<slug>`: 단위 작업 브랜치. `dev`에서 분기, 완료 후 PR로 `dev`에 merge, merge 즉시 로컬과 원격에서 삭제한다.
- Phase 단위 브랜치 이름 (`phase/N-...`)은 사용하지 않는다. 브랜치 이름은 그 작업이 무엇을 만드는지 짧게 표현한다 (예: `feature/openai-compat-api`, `feature/filesystem-tool`).

## 7. 실행 방법

Phase 0 완료 상태. 로컬 환경 준비 순서.

1. Python 3.12 및 uv 설치
2. `uv sync`로 의존성 설치
3. `.env.example`을 `.env`로 복사
4. `docker compose up -d`로 Langfuse 자체 호스트 기동
5. `http://localhost:3000` 접속, 초기 계정 생성, 프로젝트 생성 후 public key 및 secret key를 `.env`에 반영
6. `OPENAI_API_KEY`, `TAVILY_API_KEY`를 `.env`에 채움
7. Phase 1 트리거는 사용자가 명시 지시

---

## 8. 참고 자료

- Anthropic, Building Effective Agents: [https://www.anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
- OpenAI Docs, Function calling: [https://platform.openai.com/docs/guides/function-calling](https://platform.openai.com/docs/guides/function-calling)
- OpenAI Docs, Prompt caching: [https://platform.openai.com/docs/guides/prompt-caching](https://platform.openai.com/docs/guides/prompt-caching)
- Langfuse, self-hosting: [https://langfuse.com/docs/deployment/self-host](https://langfuse.com/docs/deployment/self-host)
- Open WebUI, openai-compatible endpoints: [https://docs.openwebui.com/](https://docs.openwebui.com/)
