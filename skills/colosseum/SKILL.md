---
name: colosseum
description: "Runs a web-search-grounded adversarial review of a contested question. Three independent agents, ideally from different model families, draft blind answers; a family-weighted vote and pooled probability set the baseline; only evidence backed by verified verbatim quotes can move the verdict. Use whenever the user asks to fact-check a claim (including popular beliefs and health myths), for contested factual claims, 'is X true?' checks, decisions with trade-offs, or when the user asks for multiple AI perspectives or critical analysis. Not for simple lookups, summaries, translation, or coding tasks. Triggers: 'colosseum', '여러 AI에게 물어봐', 'AI 토론', '비판적으로 분석', '다양한 관점', '팩트체크'"
license: MIT
metadata:
  author: "최진호"
  version: "3.0.0-alpha.1"
  updated: "2026-09-30"
  category: "Research"
  tags: "multi-ai, critical-thinking, adversarial-debate, fact-checking, web-search, argumentation"
---

# COLOSSEUM

> 독립 초안의 투표로 기준선을 세우고, 원문 인용으로 검증된 증거만이 그 기준선을 움직이며, 판정은 논증 그래프 위에서 계산한다.

## 핵심 규칙 (진행 중 어떤 경우에도 우선한다)

1. 중재자(이 스킬을 실행하는 Claude 본체)는 참가자 입장을 쓰지도, 연기하지도 않는다. 진행, 검색 대행, 인용 검증, 기록, 판정만 한다.
2. 참가자는 기본 3명이다. 가능하면 최소 1명은 Claude가 아닌 모델 계열로 채운다. 전원이 같은 계열이면 결과에 "동종 명단"이라고 표기한다.
3. 참가자는 익명 라벨(A, B, C)로만 서로를 본다. 모델명, 관점, 확률은 다른 참가자와 배심원에게 공개하지 않는다. 라벨은 라운드마다 다시 섞는다.
4. 초안은 병렬로, 서로 모르는 상태에서 쓴다. 초안이 모이면 먼저 투표 기준선과 풀링 확률 P0를 계산해 기록한다.
5. 팩트 클레임에는 URL과 50단어 이하 원문 인용이 붙어야 한다. 인용은 페이지와 대조해 v(일치), n(근접), u(미확인)로 분류하고, u는 증거로 0점이다. 환경 문제로 페이지 가져오기가 전부 실패하면 "원문 대조 불가" 모드로 전환해 검색 스니펫에 들어 있는 인용을 약한 증거로 인정한다.
6. 입장 변경은 v 또는 n 인용 증거(원문 대조 불가 모드에서는 스니펫 인용 포함), 혹은 이름을 댈 수 있는 논리 오류를 근거로 할 때만 인정한다. 그 밖의 변경은 CONFORMITY_FLIP으로 기록하고 수렴에 세지 않는다.
7. 토론은 기본 1라운드, 상한 3라운드다. 새 검증 증거로 바뀐 입장이 없는 라운드가 나오면 즉시 끝낸다.
8. 최종 답이 투표 기준선과 다르려면 세 조건이 모두 필요하다: 소수 핵심 주장의 인용 재확인(v), 다수 반박의 검증 실패, 다른 계열(없으면 새) 배심원의 독립 동의.
9. 공격 전에 상대 주장을 3문장 이내로 재진술한다(스틸맨). 상대가 왜곡이라고 판정하면 그 공격은 무효다.
10. CONVERGENCE는 진단 지표일 뿐 성공 신호가 아니다. 교착은 조건부 답으로 명시하고 합의로 포장하지 않는다.
11. 세션 검색 상한은 25회, 페이지 가져오기 상한은 15회다. 판정을 좌우하는 주장, 논쟁 중인 주장, 시간에 민감한 주장에 먼저 쓴다.
12. 사용자 질문과 프롬프트를 셸 인자에 직접 넣지 않는다. API 키와 토큰은 출력하지도, 프롬프트에 넣지도 않는다.
13. 스크립트가 거부(`"refused"`)하면 그 결정을 따른다. 단계 순서, 라운드 종료, 예산은 스크립트와 훅이 정한다.

---

## 실행 환경

사용 가능한 도구:

!`command -v python3 gemini llm aichat 2>/dev/null || true`

- 위 목록에 `python3`가 있고 Bash를 쓸 수 있으면 아래 "스크립트 모드"로 진행한다.
- 그렇지 않으면 "수동 모드"로 진행하고, 결과 머리에 "스크립트 없음: 수동 계산"을 명시한다.
- `gemini`, `llm`, `aichat`이 보이면 참가자 명단에 넣을 수 있다(명단 규칙과 호출 방법은 [references/protocol.md](references/protocol.md) §1.2~§2.3).

이 문서에서 `CTL`은 다음 명령을 뜻한다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/colosseum.py" --data "${CLAUDE_PLUGIN_DATA}"
```

세션 ID는 `${CLAUDE_SESSION_ID}`다. `CTL`의 모든 명령은 JSON 하나를 출력한다.

JSON 입력은 파일 도구로 쓰지 않고, 따옴표 친 heredoc으로 표준입력에 넘긴다. 스크립트가 받은 입력을 실행 디렉터리에 저장한다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/colosseum.py" --data "${CLAUDE_PLUGIN_DATA}" baseline --session "${CLAUDE_SESSION_ID}" --file - <<'COLOSSEUM_JSON'
{"drafts": [...]}
COLOSSEUM_JSON
```

## 스크립트 모드

| 단계 | 중재자가 할 일 | 명령 |
|------|--------------|------|
| 시작 | 질문을 파싱한다(TYPE, STAKES, AS_OF, 명단). 결과의 `run_dir`을 기억한다 | `CTL start --session "${CLAUDE_SESSION_ID}" --stakes <low/medium/high>` |
| Phase 1 | 사실 기반 검색 3회, 상위 페이지 가져오기, 인용 대조 | `CTL advance --session ... --to fact_base` |
| Phase 2 | 참가자 3명을 병렬 호출해 초안(role: draft)을 받는다. 인용을 대조한다 | `CTL advance --session ... --to drafts` |
| Phase 2a | 초안을 drafts 형식으로 정리해 기준선을 계산한다 | `CTL baseline --session ... --file -` (heredoc) |
| Phase 2b | `skip_debate`가 true면 판정으로 간다. `needs_dissenter`면 반대자(role: dissenter) 1명을 먼저 돌린다. 그 밖에는 쟁점 지도를 만든다 | `CTL advance --session ... --to issues` 또는 `--to verdict` |
| Phase 3 | 라운드를 연다. 검사, 반대증인, 변호인 턴을 받고 인용을 대조한 뒤 논증 그래프를 갱신한다. 라운드 결과를 기록한다 | `CTL advance --session ... --to round`, 끝나면 `CTL round-result --session ... --verified-changes N --open-issues M --conformity-flips K` |
| 다음 라운드 | 다시 `--to round`를 시도한다. 거부되면 그 사유가 종료 사유(해소, 안정, 상한)다 | `CTL advance --session ... --to round` |
| Phase 4 | 배심원 판정(두 순서), 논증 그래프 확정, 판정 계산, 역전 규칙, 사전부검, 점검표 | `CTL advance --session ... --to verdict`, `CTL verdict --session ... --file -` (heredoc), `CTL metrics --session ...` |
| 종료 | [references/output.md](references/output.md) 형식으로 보고서를 쓴다 | `CTL finish --session ...` |

세부 규칙:

- 참가자 호출: Agent 도구의 subagent_type으로 `colosseum:participant`를 쓴다. 목록에 없으면(수동 설치) `general-purpose`를 쓰고 [references/formats.md](references/formats.md) §1의 JSON 턴 형식과 Prime Directive([references/protocol.md](references/protocol.md) §3)를 프롬프트에 넣는다. 같은 단계의 참가자는 한 메시지에서 병렬로 호출한다.
- 인용 대조: WebFetch 프롬프트는 "다음 구절이나 거의 같은 구절이 페이지에 있으면 원문 그대로 반환하고, 없으면 NOT FOUND라고만 답하라: [인용]"으로 한다. 반환된 텍스트와 인용을 `CTL quote --session ... --stdin`에 heredoc으로 `{"id": "E1", "quote": "...", "page": "..."}` 형태로 넘겨 분류한다. 가져오기가 실패하면 `CTL fetch-failed --session ... --url <URL>`을 실행한다. 결과에 `"degraded": true`가 나오면 원문 대조 불가 모드로 전환한다.
- 판정: `CTL verdict`의 `conflicts[].verdict`를 충돌 판정으로 쓰고, 표기는 [references/formats.md](references/formats.md) §3 끝의 대응표를 따른다. LLM이 판단하는 몫은 관계 유형과 지지 수준(`support`)을 정하는 일, 그리고 배심원의 두 순서 판정뿐이다. 엔진 판정과 배심원 판정이 다르면 둘 다 보고하고 조건부로 표기한다.
- 점검표: `CTL metrics`의 결과를 증거 품질 점검표에 그대로 옮긴다. 단일 가중 점수는 만들지 않는다.
- 훅: 플러그인으로 설치된 경우 검색과 페이지 가져오기 예산, 블라인드 단계의 메시지 차단, 참가자 턴 형식 검사를 훅이 강제한다. 훅이 거부한 호출은 다시 시도하지 않는다.

## 수동 모드

[references/protocol.md](references/protocol.md)의 Phase 0~4를 그대로 수행한다. 기준선 P0는 각 확률을 0.02~0.98로 자른 뒤 ln(p/(1-p))의 평균 m을 구해 1/(1+e^(-m))로 계산하고, 계산 과정을 기록한다. 충돌 판정은 [references/formats.md](references/formats.md) §3의 규칙(공격 유형, 증거 강도)을 참고해 중재자가 내리되, 판정 근거가 된 증거 ID를 모두 적는다.

## 참고 문서

| 문서 | 내용 |
|------|------|
| [references/protocol.md](references/protocol.md) | 구성 요소, 명단, CLI 호출, Prime Directive, Phase 0~4 상세와 프롬프트 |
| [references/formats.md](references/formats.md) | 참가자 JSON 턴, drafts.json, graph.json 형식과 판정 라벨 |
| [references/output.md](references/output.md) | 최종 보고서와 진행 중 투명성 출력 형식 |

## 금지 사항

- 검색 근거와 원문 인용 없이 팩트 클레임을 반박하는 것
- u 인용을 판정 근거로 쓰는 것
- 증거 없는 입장 변화를 인정이나 합의로 세는 것
- 역전 규칙의 세 조건 없이 최종 답을 기준선과 다르게 내는 것
- "모두 일리 있다" 식의 무판정 합성. 쟁점은 판정하거나 조건부로 명시한다
- 교착을 합의로 포장하는 것
- 중재자가 참가자 입장을 대신 쓰거나 한 컨텍스트에서 여러 참가자를 연기하는 것
- 공개 단계 전에 다른 참가자의 초안을, 또는 어느 단계에서든 모델명이나 확률을 참가자와 배심원에게 보여 주는 것
- 사용자 질문을 따옴표 없는 셸 인자로 CLI에 넘기는 것
- API 키, 토큰, 인증 정보를 출력하거나 프롬프트에 넣는 것
- 스크립트나 훅의 거부를 우회하는 것
- 토론 라운드 3회 초과, 검색 25회 초과, 페이지 가져오기 15회 초과
