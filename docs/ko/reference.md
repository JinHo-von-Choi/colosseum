# 레퍼런스

스킬이 이 스크립트들을 직접 호출한다. 실행 상태를 보거나, 판정을 다시 계산하거나, 예측과 에이전트를 관리할 때 직접 실행한다. 경로는 `skills/colosseum/scripts/` 기준이다. 모든 명령은 JSON 하나를 출력하고, 성공하면 0, 거부나 잘못된 입력이면 2로 끝난다.

## colosseum.py

공통 옵션: `--data DIR`로 데이터 디렉터리를 지정한다.

### 실행 관리

| 명령 | 용도 |
|------|------|
| `start --session S [--question-file -] [--stakes low\|medium\|high] [--max-rounds 1-3] [--search-budget N] [--fetch-budget N]` | 실행을 연다. 같은 세션에 열린 실행이 있으면 거부한다. 질문은 표준입력으로 `{"question": "..."}` 형태로 넘긴다 |
| `resume --session S [--expect-question-sha H]` | 열려 있거나 중단된 실행을 마지막 단계부터 이어 간다 |
| `restart --session S [--question-file -]` | 현재 실행을 중단 상태로 닫고 새 실행을 연다 |
| `cancel --session S`, `fail --session S --reason TEXT`, `finish --session S` | 실행을 취소, 실패, 완료로 닫는다 |
| `runs --session S` | 세션의 실행 목록 |
| `materials add --session S [--file -]` | 자료를 실행에 고정한다. 입력: `{"materials": [{"path": ...} \| {"url": ...} \| {"text": ..., "title": ...}]}`. 출력의 `workflow_arg`를 워크플로의 `materials` 인자로 넘긴다 |
| `materials list --session S` | 실행의 자료 목록 |
| `status --session S` | 단계, 라운드, 예산 사용량, 다음에 갈 수 있는 단계 |
| `advance --session S --to PHASE` | 다음 단계로 이동: `fact_base`, `drafts`, `baseline`, `issues`, `round`, `verdict`, `done` |
| `round-result --session S --verified-changes N --open-issues N [--conformity-flips N]` | 라운드 결과를 기록하고, 다음 라운드를 허용할지 정한다 |
| `fetch-failed --session S --url URL` | 가져오기 실패를 기록한다. 서로 다른 호스트 3곳에서 실패하면 스니펫 수준 검증으로 바꾼다 |

### 계산

입력은 `--file PATH`, 표준입력(`--file -`), 또는 현재 실행 디렉터리에서 읽는다. `--run RUN_ID`를 주면 그 세션의 닫힌 실행에서 읽는다.

| 명령 | 입력 | 출력 |
|------|------|------|
| `quote --stdin` | `{"id", "quote", "page"}` | `v`, `n`, `u`와 사유, 일치 위치 |
| `baseline [--extremize A]` | `drafts.json` | 투표, `P0`, 토론 생략 여부와 반대자 필요 여부 |
| `verdict [--theta T]` | `graph.json` | 라벨, 상태, 강도, 충돌 판정. `material_checks`에는 사본과 다시 대조해 상태가 바뀐 자료 인용이 나온다 |
| `metrics` | `graph.json` | 증거 품질 점검표 |
| `whatif --exclude-evidence E \| --unprove-claim C` | `graph.json` | 바뀐 것과 변화가 퍼진 관계 |
| `adr [--status S] [--out DIR]` | debate 워크플로 결과 | `decision.md`와 `decision.json` |

### 예측

| 명령 | 용도 |
|------|------|
| `forecast add [--file PATH] [--event-id K]` | 예측 기록 저장(기본은 표준입력 JSON). 같은 기록을 다시 넣으면 아무 일도 없다 |
| `forecast resolve --id ID --outcome 0\|1` | 결과 기록. 같은 결과를 다시 넣으면 아무 일도 없고, 다른 결과면 오류다 |
| `forecast list`, `forecast score`, `forecast fit`, `forecast status` | 목록, 채점(Brier, 로그 손실, 구간), 풀링 계수 맞추기, 저장소 상태 |
| `forecast import [--file PATH]` | `forecasts.jsonl`을 한 번 가져온다. 원본은 백업한다 |
| `forecast export [--file PATH]` | 모든 기록을 JSON 줄로 내보낸다 |

## relay.py

| 명령 | 용도 |
|------|------|
| `list` | 등록부의 모든 에이전트와 설치 여부 |
| `detect [--probe] [--refresh] [--brief]` | 설치된 에이전트를 선호 순서대로. `--probe`는 실제로 답하는지 확인한다 |
| `roster [--size 3] [--prefer a,b] [--only a,b] [--max-cli N] [--probe] [--seed N]` | 실행에 쓸 명단 |
| `mktemp` | 프롬프트 파일을 둘 전용 디렉터리 |
| `run --cli ID --prompt-file PATH [--timeout 180] [--max-output 200000] [--cleanup]` | 에이전트 하나에 프롬프트 하나를 보낸다 |

## 환경변수

| 변수 | 효과 |
|------|------|
| `COLOSSEUM_DATA` | 데이터 디렉터리 |
| `COLOSSEUM_AGENTS` | 선호 에이전트, 쉼표로 구분 |
| `COLOSSEUM_AGENTS_FILE` | 에이전트 설정 파일 경로 |
| `COLOSSEUM_DEBUG_LOG=1` | 출처 기록에 가린 질의와 응답 원문을 남긴다 |

## 데이터 디렉터리

다음 중 먼저 지정된 것을 쓴다: `--data`, `COLOSSEUM_DATA`, 플러그인 데이터 디렉터리, `~/.claude/colosseum`

```
<data>/
  agents.json                 에이전트 설정 (선택)
  agents-probe.json           확인 결과
  forecasts.sqlite3           예측 저장소
  sessions/<session>/
    state.json                현재 실행의 체크포인트
    runs/<run_id>/            실행 하나가 만든 모든 파일
      materials.json          자료 목록과 사본별 SHA-256
      materials/M1.txt        자료 사본
      drafts.json, graph.json, baseline.json, verdict.json, result.json
      decision.md, decision.json
      quotes.jsonl            인용 대조 기록
      sources.jsonl           검색과 가져오기 기록
```

디렉터리는 0700, 파일은 0600 권한으로 만든다. 출처 기록에는 이벤트 ID, 도구, 성공 여부, 지연 시간, 인증 정보를 지운 URL, 질의와 응답의 해시가 남는다. 실행 디렉터리를 지우면 그 기록도 지워진다.

## 파일 형식

### drafts.json

```json
{
  "drafts": [
    {"label": "A", "family": "claude", "position": "P1", "probability": 0.78},
    {"label": "B", "family": "openai", "position": "P2", "probability": 0.60}
  ],
  "verified_counter": false
}
```

`position`은 같은 뜻의 초안을 묶는 ID다. `probability`는 작성자가 자기 입장이 옳다고 본 확률이다. `verified_counter`는 초안의 가장 강한 반론이 인정된 근거로 뒷받침될 때 true다.

### graph.json

```json
{
  "schema": "colosseum.arggraph/v2",
  "evidence": [
    {"id": "E1", "url": "https://...", "quote": "...", "reliability": "high",
     "quote_status": "v", "support": "full", "freshness": "fresh", "origin": "doi:10.1000/xyz"}
  ],
  "claims": [
    {"id": "r0.i-.draft.A.0", "author": "A", "text": "...", "kind": "fact", "evidence": ["E1"]}
  ],
  "relations": [
    {"type": "attack", "subtype": "rebut", "from": "r1.i1.pro.B.0", "to": "r0.i-.draft.A.0"}
  ],
  "conflicts": [{"a": "r0.i-.draft.A.0", "b": "r0.i-.draft.B.0"}],
  "final": [{"claim": "r0.i-.draft.A.0", "weight": 3}]
}
```

| 필드 | 값 |
|------|----|
| `reliability` | `high`(1차 자료, 공식 문서, 동료 심사), `medium`(주요 언론, 전문가 블로그), `low` |
| `quote_status` | `v`, `snippet`, `n`, `u` |
| `support` | `full`, `partial`, `none`, `unknown` (이 주장 기준) |
| `freshness` | `fresh`, `stale`, `superseded`, `na`(시점 무관), `unknown` |
| `url` | 페이지 URL. 사용자가 준 파일이나 붙여 넣은 글은 `material:M1` |
| `origin` | 원출처 ID. 사본들은 같은 값을 쓴다. 비우면 URL 호스트로 묶는다 |
| `kind` | `fact`, `statistic`, `causal`, `forecast`, `value`, `recommendation` |
| `status` | `active` 또는 `withdrawn` |
| `subtype` | `rebut`(결론 공격), `undercut`(추론 공격), `undermine`(근거 공격) |
| `final.weight` | 3 결론을 좌우, 2 보조, 1 주변 |

근거 레코드 하나는 인용 하나를 주장 하나에 묶는다. 두 주장이 같은 인용을 쓰면 레코드도 둘이고 지지 판정도 따로 한다. 주장 ID는 `r<라운드>.i<쟁점>.<역할>.<라벨>.<순번>` 형식이다. `schema`가 없는 그래프는 같은 필드를 쓰는 버전 1로 읽는다.
