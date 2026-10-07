# 개발

## 구조

| 경로 | 내용 |
|------|------|
| `skills/colosseum/SKILL.md` | 스킬 본체: 규칙, 질문 유형별 분기, 단계별 명령 |
| `skills/colosseum/references/` | 스킬이 실행 중에 읽는 절차, 프롬프트, 형식, 보고서 양식 |
| `skills/colosseum/scripts/` | 실행 관리, 판정 엔진, 인용 대조, 예측 저장소, 에이전트 중계와 등록부 (Python 표준 라이브러리만 사용) |
| `workflows/` | Workflow 도구용 `debate.js`, `forecast.js` |
| `experimental/` | 플러그인이 읽지 않는 유지보수 중단 워크플로 |
| `agents/` | `participant`(웹 도구만 사용), `cli-proxy`(외부 에이전트 실행) |
| `hooks/hooks.json` | 예산, 메시지 차단, 응답 형식 훅 |
| `tests/` | 단위, 언어 간 일치, 경계, 워크플로 시험 |
| `evals/` | `claude plugin eval` 평가 사례 |

워크플로는 파일을 가져올 수 없어서 각 파일이 같은 `colosseum-lib`, `colosseum-runtime` 블록을 각자 들고 있다. `workflows/debate.js`에서 고친 뒤 나머지에 복사한다.

```bash
python3 tools/sync_workflow_blocks.py
```

복사본이 다르면 시험이 실패한다.

## 방어 코드를 넣는 조건

검사, 대체 경로, 예외 처리는 다음 중 하나일 때만 넣는다.

- 그 코드가 막는 실패를 재현하는 시험이 있다
- 이름을 댈 수 있는 신뢰 경계에 있다: 사용자 입력, 외부 에이전트 출력, 웹 원문, 파일 시스템, 셸

검증은 그 경계에서 한 번만 하고, 안쪽에서는 데이터를 믿는다. 앞 단계에서 이미 걸러진 상태를 다시 막지 않는다. 실험 기능은 동작하는 가장 작은 형태로 만든다. 휴리스틱 단어 목록은 실제 실패 사례가 있을 때만 늘린다. 시험은 사용자가 보는 동작을 확인하고 내부 구조를 고정하지 않는다.

## 시험

```bash
python3 -m unittest discover -s tests
```

JavaScript 검사는 Node 18 이상이 있어야 돌고, 없으면 건너뛴다. CI처럼 `COLOSSEUM_REQUIRE_NODE=1`을 주면 Node가 없을 때 오류로 처리한다.

| 파일 | 대상 |
|------|------|
| `test_scripts.py` | 판정 엔진, 인용 표본, 기준선, 점검표, 응답 형식, 단계 기계, 훅 |
| `test_p0.py` | 인용 의미 반전, 주장별 지지 판정, 스니펫 대조, 주장 ID, 실행 격리, 동시 쓰기에서의 예측 저장소 |
| `test_contract.py` | 근거 규칙, 관계를 중복으로 넣거나 목록 순서를 바꿔도 결과가 같은지, 4개 노드 그래프 4,096개 전부를 참조 구현과 대조, Python과 JavaScript 일치 |
| `test_js_parity.py` | 워크플로 JavaScript 라이브러리와 Python 스크립트의 일치 |
| `test_boundaries.py` | 에이전트 중계, 기록의 비밀값 가림, 설치 스크립트 |
| `test_agents.py` | 에이전트 등록부, 탐지, 응답 확인, 명단 |
| `test_decision.py` | 결정 기록과 가정 바꿔 보기 |
| `test_materials.py` | 자료 사본, 자료 인용 대조, 토론 워크플로에서의 자료 사용 |
| `test_modes.py` | 모드별 집계와 예측 채점 |

`tests/workflow_harness.py`는 `agent()`를 정해진 응답으로 바꿔 워크플로 전체를 Node에서 돌린다. 모델 호출 없이 진행 로직을 시험할 때 쓴다.

## 평가

```bash
claude plugin eval . --tag smoke --runs 1 --ablation none          # 호출 여부 사례만
claude plugin eval . --allow-tools WebSearch WebFetch --judge-model sonnet -j 2 --max-cost-usd 60
```

| 묶음 | 사례 수 | 확인 내용 |
|------|--------|----------|
| `trig-pos-*` | 5 | 토론, 비판적 분석, 팩트체크 요청에 스킬이 실행되는가 |
| `trig-neg-*` | 5 | 검색, 요약, 번역, 코드, 계산 요청에는 실행되지 않는가 |
| `acc-*` | 10 | 답이 알려진 흔한 오해 |
| `con-*` | 4 | 논쟁적 질문: 균형, 거짓 합의 여부 |

Sonnet 기준으로 토론 사례 한 번에 약 1달러가 든다. 평가 샌드박스 안에서는 외부 에이전트 CLI가 대개 실패하므로, 평가는 Claude만으로 된 명단을 측정한다. 버전을 비교할 때는 비용을 맞춰 비교한다.
