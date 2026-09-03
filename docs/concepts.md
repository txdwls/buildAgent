# 핵심 개념 정리

이 문서는 리포에서 다루는 AI 에이전트 개념 학습 노트다. Claude Code에 대한 지시가 아니라 사용자(리포 오너)가 면접에서 답할 수 있어야 할 것들의 요약. 운영 규칙은 루트 `CLAUDE.md`에 있다.

## 1. 에이전트란 무엇인가

에이전트는 LLM 더하기 tools 더하기 loop로 정의된다.

- LLM 단독은 텍스트 생성만 한다. 도구를 호출할 수 있고, 도구 결과를 받아 다음 결정에 반영하는 루프가 있어야 에이전트다.
- 워크플로(사람이 짠 결정 트리)와의 차이는, 에이전트가 다음에 뭘 할지 LLM이 결정한다는 점이다. 결정권을 LLM에 위임한 만큼 관측과 가드레일이 필수가 된다.

## 2. Tool Use 프로토콜 (OpenAI function calling)

한 번의 API 호출이 한 번의 결정.

```
messages 전송, LLM 응답, choices[0].finish_reason 및 message.tool_calls 확인

finish_reason 처리:
- "stop":          최종 답. 루프 종료.
- "tool_calls":    어떤 function을 어떤 인자로 부를지 지정 (message.tool_calls 배열). 실행 후 결과 반환.
- "length":        max_tokens 소진. 잘라 처리하거나 재시도.
- "content_filter": 정책 필터 컷. 사용자에게 알리고 종료.
```

Tool 결과는 `role: "tool"` 메시지로 다음 요청에 실려 들어가며, 각 결과는 원 `tool_call`의 `id`를 `tool_call_id`로 참조해야 한다. 모델은 tool 결과를 봤다는 사실을 API가 아니라 messages 배열로만 안다. 이 인식이 컨텍스트 관리와 직결된다.

## 3. 에이전트 루프

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

## 4. 컨텍스트 관리

문제: messages 배열은 turn마다 계속 쌓인다. 토큰 예산, 비용, 품질 모두 저하.

전략:

- Sliding window: 최근 N개 turn만 유지, 그 이전은 요약.
- Summarization: 오래된 turn을 LLM으로 요약해 하나의 시스템 메시지로 접기.
- Selective retention: tool_result 중 부피 큰 것(HTML 덤프 등)을 요약 또는 삭제, 결정은 유지.
- External memory: 벡터 store에 넣고 필요할 때 검색 (agentic RAG와 연결).

조합 순서(권장): system prompt, tool 설명, 검색된 외부 메모리, 요약된 과거 turn, 최근 turn, 현재 user 입력 순. 최근 정보가 뒤에 올수록 모델이 잘 참조한다.

## 5. 에이전트 패턴

| 패턴 | 요지 | 언제 | 트레이드오프 |
|---|---|---|---|
| 독립 에이전트 (single-loop) | 하나의 LLM이 tools 다 부름 | 대부분의 시작점 | 단순. 복잡한 계획엔 약함 |
| Reflection | 응답 후 self-critique 뒤 재응답 | 품질 민감, 오답 비용 큼 | 지연과 비용 2배 |
| Planner-Executor | planner가 계획 세우고 executor가 실행 | 다단계 작업 | 조율 오버헤드 |
| Multi-agent (supervisor, worker) | supervisor가 특화 worker에게 위임 | 도메인이 뚜렷이 다름 | 통신 프로토콜 설계 부담 |
| Router | 첫 LLM이 어떤 하위 에이전트로 보낼지 판단 | 다양한 유형 요청 | 라우팅 오류 시 파장 |
| Human-in-the-loop | 위험 작업 전 사람 승인 | 파괴적 tool(fs write, exec) | UX 흐름 끊김 |

리포 시작점은 독립 에이전트다. 이걸 관측, 가드레일, 평가와 함께 완성한 뒤 다른 패턴을 얹는다.

## 6. RAG: naive vs agentic

- Naive RAG: 요청마다 검색하고 context 앞에 삽입. 항상 검색. 간단하지만 불필요한 검색과 잘못된 검색어 문제가 있다.
- Agentic RAG: 검색을 tool로 노출. LLM이 필요할 때 필요한 쿼리로 검색, 결과 부족하면 재검색. 다단계 질문에 강함.

이 리포는 Phase 7에서 naive 이후 agentic 순서로 밟는다. 인덱스 대상은 LLM이 모를 만한 자료(위키, 공개 문서 등)를 사후 결정.

## 7. 가드레일

층별로 나눠 사고한다.

| 층 | MVP (rule 기반) | 심화 |
|---|---|---|
| 입력 | PII regex(주민번호, 전화, 이메일), jailbreak 키워드 리스트 | LLM classifier(prompt injection), rate limit |
| 출력 | PII 마스킹, 금칙어 | groundedness judge, structured output 검증 |
| 실행 | tool 타임아웃, filesystem root-jail | Docker 샌드박스, network 차단 |

핵심 원칙: 가드레일은 품질 검사가 아니라 신뢰 경계다. 신뢰 경계(사용자 입력, 외부 API 응답, tool 결과)에서만 검증. 내부 함수 호출마다 검증하면 코드가 방어로 도배된다.

## 8. 관측 (Observability)

Langfuse의 계층:

- Trace: 하나의 대화 세션 (혹은 하나의 요청).
- Span: turn, tool call, guardrail 검사 등 논리 단위.
- Generation: 실제 LLM 호출 (모델, 토큰, 비용, 프롬프트, 응답).

관측이 없으면 왜 이 답이 나왔는지 재현 불가, 어떤 tool이 자주 실패하는지 모름, 프롬프트 개선 효과를 정량화 못 함. 관측이 있으면 evaluation, regression, 비용 대시보드가 자연스럽게 붙는다.

## 9. 평가 (Evaluation)

Offline eval

- 작은 dataset (YAML): `{input, expected_tools, expected_criteria}`.
- 각 케이스 실행, 결과를 LLM-as-judge로 채점, Langfuse score 저장.
- 프롬프트나 모델 변경 시 회귀 감시.

Online eval

- production trace에 score attach (사용자 피드백, heuristic score).
- 프롬프트 A/B, cohort 비교.

LLM-as-judge의 한계: judge 자신이 편향과 환각을 가진다. rubric을 좁게, 결정적으로. 필요하면 판정 근거를 함께 저장해 사후 검증.

## 10. 안정성 및 비용

- Retry: 429, 5xx, timeout에 exponential backoff 및 jitter.
- Fallback: primary(gpt-5 등) 실패 시 secondary(gpt-4.1 mini 등)로 자동 전환. 필요 시 Anthropic Claude로도 우회.
- Prompt caching: OpenAI는 1024+ 토큰 프리픽스에 대해 자동 캐싱. 시스템 프롬프트와 tool 정의를 messages 앞쪽에 고정해 hit율 유지.
- Rate limit 대응: token bucket으로 요청 페이싱.
- 비용 관측: 모든 generation에 model, input_tokens, output_tokens, usd 기록.

## 11. Browser 자동화 및 Computer Use

- 왜 필요한가: 현대 웹의 상당수는 JS 렌더링, 로그인, 인터랙션 없이는 접근 불가. 단순 HTTP fetch로 못 얻는 정보를 에이전트 tool로 노출한다. RPA, 스크래핑, UI 조작이 모두 여기 얹힌다.
- 두 갈래:
  - DOM 기반 (Playwright, Puppeteer, CDP): 헤드리스 브라우저 자동화. 페이지 이동, 셀렉터 클릭, form 입력, HTML 추출. 결정적이고 재현 가능. 대부분의 스크래핑, 자동화에 우선 선택.
  - 화면 기반 (Anthropic Computer Use): 모델이 스크린샷을 보고 좌표로 클릭, 타자. DOM 접근이 막히거나 시각 UI 위주인 경우에 강함. 지연과 비용 크고 오답 확률 높음. DOM 갈래 실패 시의 fallback 성격.
- Tool 노출 방식: `browser.open(url)`, `browser.click(selector)`, `browser.type(selector, text)`, `browser.extract(selector)`, `browser.screenshot()` 처럼 원자적 tool로 쪼갠다. LLM에게 큰 tool 하나(`browser.do_task`)만 주면 무엇을 했는지 추적 불가.
- 위험 요소: 사이트 ToS, robots.txt, rate limiting, 로그인 credential 관리, headless 탐지, 무한 리다이렉트. 가드레일 층에서 URL allowlist, action budget(최대 클릭 횟수), 세션 격리 필수.
- 관측: 각 action은 Langfuse span으로. 스크린샷, HTML 스냅샷을 attach하면 실패 재현 쉬움.

## 참고 자료

- Anthropic, Building Effective Agents: https://www.anthropic.com/research/building-effective-agents
- OpenAI Docs, Function calling: https://platform.openai.com/docs/guides/function-calling
- OpenAI Docs, Prompt caching: https://platform.openai.com/docs/guides/prompt-caching
- Langfuse, self-hosting: https://langfuse.com/docs/deployment/self-host
- Open WebUI, openai-compatible endpoints: https://docs.openwebui.com/
