# 데이터 형식

중재자와 스크립트가 주고받는 데이터는 세 가지다. 중재자는 JSON을 heredoc 표준입력(`--file -`)으로 넘기고, 스크립트가 실행 디렉터리(`colosseum.py start`가 알려 주는 `run_dir`)에 같은 이름으로 저장한다.

## 1. 참가자 턴 (참가자 → 중재자)

참가자는 매 턴 JSON 객체 하나를 ```json 블록으로 반환한다. 플러그인으로 설치되어 `colosseum:participant` 에이전트를 쓰면 이 형식이 에이전트 정의에 들어 있고, 훅이 형식을 검사해 틀린 턴을 한 번 되돌려 보낸다. general-purpose 에이전트를 쓸 때는 아래 형식을 프롬프트에 그대로 넣는다.

```json
{
  "label": "A",
  "role": "draft | prosecutor | defender | adverse_witness | premortem | dissenter",
  "position": "한 문장",
  "claims": [
    {"text": "원자 명제 하나", "kind": "fact | statistic | causal | forecast | value | recommendation",
     "url": "https://...", "quote": "페이지에서 그대로 옮긴 50단어 이하 구절"}
  ]
}
```

역할별 추가 필드:

| role | 필수 필드 |
|------|----------|
| draft | `key_assumptions`(최대 3), `cruxes`(최대 2, empirical/value 표시), `strongest_counter`, `probability`(0.02~0.98) |
| prosecutor | `steelman`(3문장 이하), `target_claim`, `attack`(300단어 이하), `position_update` |
| defender | `steelman_check`("faithful" 또는 "distorted"로 시작), `response`(300단어 이하), `change_basis`(증거 ID, 논리 오류 이름, 또는 "no change") |
| adverse_witness | `premise`, `verdict`(holds / fails / partly holds), `if_false` |
| premortem | `causes`(원인 3개와 각각의 확인 방법), `underconfidence` |
| dissenter | `claims`에 결론에 대한 가장 강한 반대 증거 |

`kind`가 fact, statistic, causal인 주장은 `url`과 `quote`가 모두 있어야 한다.

프롬프트 서술의 대문자 항목은 JSON 필드와 일대일로 대응한다: POSITION → `position`, CLAIMS → `claims`, KEY_ASSUMPTIONS → `key_assumptions`, CRUXES → `cruxes`, STRONGEST_COUNTER → `strongest_counter`, PROBABILITY → `probability`, STEELMAN → `steelman`, TARGET_CLAIM → `target_claim`, POSITION_UPDATE → `position_update`, STEELMAN_CHECK → `steelman_check`, CHANGE_BASIS → `change_basis`, PREMISE → `premise`, VERDICT → `verdict`, IF_FALSE → `if_false`.

## 2. drafts.json (중재자 → `colosseum.py baseline`)

```json
{
  "drafts": [
    {"label": "A", "family": "claude", "position": "P1", "probability": 0.78},
    {"label": "B", "family": "gemini", "position": "P1", "probability": 0.70},
    {"label": "C", "family": "claude", "position": "P2", "probability": 0.60}
  ],
  "verified_counter": false
}
```

- `family`: 모델 계열. Claude 서브에이전트는 모두 `claude`다.
- `position`: 중재자가 붙인 입장 묶음 ID. 의미가 같은 초안은 같은 ID를 받는다.
- `probability`: 그 참가자가 자기 입장이 옳다고 본 확률.
- `verified_counter`: 근거 자격(v, support full/partial)을 갖춘 인용으로 뒷받침되는 STRONGEST_COUNTER가 하나라도 있으면 true.

결과의 `baseline_vote`, `p0`, `skip_debate`, `needs_dissenter`를 그대로 따른다.

## 3. graph.json (중재자 → `colosseum.py verdict`, `metrics`)

```json
{
  "schema": "colosseum.arggraph/v2",
  "evidence": [
    {"id": "E1", "url": "https://...", "quote": "...", "reliability": "high",
     "quote_status": "v", "support": "full", "freshness": "fresh", "origin": "nature:bloom2024",
     "claim_id": "A.c1", "acquisition": "full_page"}
  ],
  "claims": [
    {"id": "A.c1", "author": "A", "text": "...", "kind": "fact", "evidence": ["E1"]}
  ],
  "relations": [
    {"type": "attack", "subtype": "rebut", "from": "B.c2", "to": "A.c1"},
    {"type": "support", "from": "C.c1", "to": "A.c1"}
  ],
  "conflicts": [{"a": "A.c1", "b": "B.c2"}],
  "final": [{"claim": "A.c1", "weight": 3}]
}
```

필드 값:

| 필드 | 값 |
|------|----|
| `reliability` | high(1차 자료, 공식 문서, 동료 심사) / medium(주요 언론, 전문가 블로그) / low(커뮤니티, 출처 불명) |
| `quote_status` | v(연속 구간 일치) / snippet(스니펫 텍스트에 그대로 있음) / n(검토 필요, 가중치 0) / u(원문에 없음) |
| `support` | full / partial / none / unknown (이 claim과 이 인용, 그 문맥만 보고 판단한 지지 수준) |
| `freshness` | fresh / stale / superseded / na(시점과 무관) / unknown(판단 불가, 최신으로 가정하지 않음) |
| `acquisition` | full_page / snippet / unavailable (선택. 원문을 어떻게 얻었는지) |
| `origin` | 원출처 군집 ID. 같은 통신 기사, 보도자료, 논문, 데이터셋을 옮긴 증거는 같은 ID. 비우면 URL 호스트로 묶인다 |
| `subtype` | rebut(결론 반박) / undercut(추론 무력화) / undermine(근거 약화) |
| `final.weight` | 3 판정을 좌우 / 2 보조 사실 / 1 주변 |

만드는 방법:

1. 참가자 턴의 `claims`마다 claim 하나와 evidence 하나를 만든다. evidence 하나는 인용 하나를 claim 하나에 묶는다. 같은 인용을 두 주장이 쓰면 evidence도 둘이고 support도 각자 판정한다. claim ID는 라운드, 쟁점, 역할, 라벨, 순번을 담는다(예: `r1.i2.pro.B.0`, 초안은 `r0.i-.draft.A.0`). 같은 라운드에 쟁점이 둘이어도 겹치지 않아야 한다.
2. 공격은 공격자의 주장에서 대상 주장으로 가는 attack 관계다. 겨냥한 부분이 결론이면 rebut, 근거와 결론을 잇는 추론이면 undercut, 인용된 근거 자체면 undermine이다.
3. 같은 관계를 두 번 넣어도 결과는 같다(엔진이 type, subtype, from, to로 중복을 지운다). 스틸맨 관문에서 무효가 된 공격은 넣지 않는다. 증거에 근거해 철회된 주장은 `"status": "withdrawn"`으로 표시한다.
4. `conflicts`에는 판정할 쟁점의 대표 주장 쌍을 넣는다.
5. `final`에는 최종 답에 남긴 팩트 주장을 넣는다.

판정 결과의 라벨은 출력에서 다음처럼 쓴다: A_WINS → A 우세, B_WINS → B 우세, PARTIAL_BOTH_SURVIVE → 쌍방 부분 인정, CONDITIONAL / VALUE_CONDITIONAL → 조건부, LOSER_REFUTED_WINNER_UNPROVEN → 한쪽 반박됨·다른 쪽 미입증, UNRESOLVED / NEITHER_ESTABLISHED → 판정 불가.
