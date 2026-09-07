# CLAUDE.md

이 리포에서 에이전트 도구(Claude Code 등)가 따를 운영 규칙. 도메인 개념 학습 노트는 [docs/concepts.md](docs/concepts.md), Phase 로드맵은 [ROADMAP.md](ROADMAP.md).

## 1. 리포 개요

AI 엔지니어로 취업하기 위해 AI 에이전트를 raw SDK로 직접 만들고 운영하며 학습하는 리포지토리.

- 프레임워크(LangGraph, CrewAI 등)는 의도적으로 배제. OpenAI SDK function calling(`tool_calls`) 위에 루프, 컨텍스트, 관측, 평가, 가드레일을 손으로 쌓는다.
- 프론트엔드는 Open WebUI 등 오픈소스 재사용. 배포/운영 인프라는 로컬 학습용에 한정.

## 2. 절대 지켜야 할 것

- 사용자가 명시적으로 트리거하기 전까지 구현 코드를 작성하지 않는다. 개념 문서와 설계 단계에서 `src/`, `pyproject.toml`, docker 파일 등 실 구현 산출물 생성 금지.
- Ponytail 원칙: 가장 라자한 해법 우선. 사다리(YAGNI, 기존 코드 재사용, 표준 라이브러리, 네이티브, 기존 의존성, 한 줄, 최소 구현)를 순서대로 밟고 필요할 때만 코드.
- 언어: 사용자와의 대화는 한국어. 코드, 주석, 커밋 메시지는 영어. 서브에이전트 프롬프트도 영어.
- 자동 서브에이전트 스폰 금지. 사용자가 명시적으로 요청할 때만 `Agent` 도구 사용.
- 자동 커밋, push 금지. 사용자 지시 후에만.
- destructive git 작업(`reset --hard`, `push --force`, 브랜치 삭제 등) 금지. 명시 요청 시에만.
- 사용자 지시 없는 새 의존성 추가 금지.
- 이 리포 스코프 밖 파일 수정 금지.
- 특수 기호 및 특수 문자 사용 금지. 이모지, 유니코드 화살표, 박스 그리기 문자, 가운뎃점, em dash, 기타 유니코드 장식 기호는 어떤 상황에서도 쓰지 않는다. 오로지 일반 텍스트, 표준 ASCII 구두점, 표준 마크다운 문법(제목, 리스트, 코드 블록, 표, 링크, 굵게, 기울임)만 허용. 코드, 문서, 커밋 메시지, 사용자 응답 모두 동일하게 적용.

## 3. 개발 도구

- 패키지: `uv add`, `uv sync`, `uv run`
- Lint 및 Format: `uv run ruff check .`, `uv run ruff format .`
- Type check: `uv run pyright` (strict)
- Test: `uv run pytest`

## 4. 코딩 스타일

- Python 3.12
- KISS, DRY, YAGNI
- 함수 50줄 미만, 파일 400줄 미만 권장
- immutable 패턴 우선 (기존 객체 mutate 금지)
- 명시적 에러 핸들링 (silent swallow 금지)
- 시크릿 하드코딩 금지, 반드시 env로 주입
- 명명: PEP 8. `snake_case` 변수 및 함수 및 모듈, `PascalCase` 클래스 및 타입, `UPPER_SNAKE_CASE` 상수, `is`, `has`, `should`, `can` 접두 boolean. ruff의 `N` 룰이 강제한다.

## 5. 커밋 및 PR 컨벤션

### 커밋

- 포맷: `<type>(<scope>): <description>` (Conventional Commits).
- 타입: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.
- 한 커밋 = 한 논리 단위. 여러 관심사를 섞지 않는다.
- description은 그 커밋이 실제로 무엇을 바꿨는지 구체적으로. `feat(phase-2): phase 2 작업 전체` 같은 두루뭉술한 요약 금지. `feat(api): expose /v1/chat/completions with SSE streaming` 처럼 결과물 자체를 명시.

### PR

- 본문 언어는 한국어. 제목은 커밋 컨벤션 그대로 영어(`type(scope): description`).
- Base 브랜치는 항상 `dev`. `main`으로 직접 PR 금지.
- 본문 헤더: Summary, Motivation, Changes, Approach, Test plan. 필요 시 Deferred, Follow-ups, Screenshots, References 추가.
- Summary는 결과물 자체 명시. 두루뭉술한 요약 금지.
- Test plan은 실제 돌린 명령과 결과 나열. 검증 못한 항목은 체크 안 된 상태로 남긴다.
- 한 PR = 한 논리 단위. 커밋 단위 리뷰 가능해야 한다.
- 본문에도 §2의 특수 기호 금지 규칙 그대로 적용.

## 6. 기술 스택

| 층위 | 선택 |
|---|---|
| 언어 | Python 3.12 |
| 패키지 | uv |
| Lint, Format | ruff |
| Type check | pyright (strict) |
| Test | pytest |
| 웹 | FastAPI, SSE |
| LLM | OpenAI (기본), Anthropic Claude (fallback 후보) |
| 에이전트 | raw SDK loop (프레임워크 없음) |
| 프론트 | Open WebUI (docker) |
| 관측 | Langfuse self-host (docker) |
| Vector store | 미정 (Chroma, LanceDB, pgvector 후보. Phase 7 진입 시 결정) |

## 7. 디렉토리 구조

전체 Phase(1~12)를 예상해 계층을 앞에서 잡되, 각 Phase 진입 시점에 그 슬롯에만 파일을 채운다. 빈 스텁 폴더는 만들지 않는다.

주요 계층:

- `src/buildagent/domain/`: 순수 도메인. I/O 및 SDK 임포트 금지.
- `src/buildagent/llm/`: OpenAI SDK가 임포트되는 유일한 층.
- `src/buildagent/tools/`: registry, dispatch, 개별 tool (web_search, filesystem, code_exec, http_fetch, browser/).
- `src/buildagent/agent/`: 코어 loop, runner, reflection, planner_executor, supervisor.
- `src/buildagent/context/`: window, summarizer, selective, assembler (Phase 5).
- `src/buildagent/memory/`, `src/buildagent/rag/`: Phase 7+.
- `src/buildagent/guardrails/`: input, output, execution 층별 (Phase 10).
- `src/buildagent/observability/`: Langfuse tracer, generation, cost, spans.
- `src/buildagent/prompts.py`: Langfuse prompt management 래퍼.
- `src/buildagent/api/`: FastAPI app, dependencies, routes/openai_compat/.
- `src/buildagent/cli/`: argparse 기반 REPL.
- `tests/{unit,integration,e2e}/`: `@pytest.mark.integration`, `@pytest.mark.e2e`로 층 분리. 기본 pytest에서 e2e 제외.
- `evals/`: Phase 11.
- `docs/{adr,phases,concepts,observability}/`: 결정 기록, Phase 회고, 개념 요약, 트레이스 캡처.

### 의존성 방향

`domain` <- `llm` / `tools` / `observability` / `prompts` <- `agent` <- `api` / `cli`.

domain은 어떤 SDK도 안 본다. OpenAI SDK는 `llm/` 안에만.

## 8. 확정된 구현 결정 (Phase 1 진입 전)

| 항목 | 선택 | 이유 |
|---|---|---|
| 프롬프트 관리 | Langfuse prompt management | 코드와 프롬프트 커밋 분리, 버전 diff와 성능 대비 UI 지원, eval 회귀 대상과 정합 |
| CLI 프레임워크 | stdlib argparse | 옵션 손 아플 때만 typer 도입 |
| 로깅 | stdlib logging + JSON formatter | structlog은 정말 필요할 때 |
| DI | FastAPI Depends | 별도 컨테이너 미도입 |
| 테스트 층 분리 | `@pytest.mark.integration`, `@pytest.mark.e2e` | 기본 pytest 실행에서 e2e 제외 |
| 프롬프트 저장 위치 | Langfuse 전용, 로컬 `prompts/` 폴더 없음 | 코드 `src/buildagent/prompts.py`가 fetch, 캐시, fallback 문자열 담당 |

## 9. Git 브랜치 전략

- `main`: 항상 배포 가능한 안정 상태. 직접 커밋 금지. `dev`로부터의 merge만 받는다.
- `dev`: 통합 브랜치. 모든 feature 브랜치가 여기로 PR merge된다. 릴리스 시점에 `dev` -> `main`.
- `feature/<slug>`: 단위 작업 브랜치. `dev`에서 분기, 완료 후 PR로 `dev`에 merge, merge 즉시 로컬과 원격에서 삭제. 브랜치 이름은 작업 결과물 자체 (예: `feature/openai-compat-api`, `feature/filesystem-tool`). Phase 단위 브랜치 이름(`phase/N-...`) 금지.

## 10. 실행 방법

Phase 0 완료 상태. 로컬 환경 준비 순서.

1. Python 3.12 및 uv 설치
2. `uv sync`로 의존성 설치
3. `.env.example`을 `.env`로 복사
4. `docker compose up -d`로 Langfuse 자체 호스트 기동
5. `http://localhost:3000` 접속, 초기 계정 생성, 프로젝트 생성 후 public key 및 secret key를 `.env`에 반영
6. `OPENAI_API_KEY`, `TAVILY_API_KEY`를 `.env`에 채움
7. 이후 Phase 진입은 사용자가 명시 지시

## 관련 문서

- [ROADMAP.md](ROADMAP.md): Phase 0~12 상세 계획
- [docs/concepts.md](docs/concepts.md): 에이전트, tool use, 컨텍스트, RAG, 가드레일, 관측, 평가, 안정성, browser 자동화 학습 노트
- `docs/adr/`: 결정 기록
- `docs/phases/`: Phase별 회고
