# Colosseum 데이터 계약

이 문서는 Python 스크립트와 네 Workflow가 함께 따르는 자료 형식과 정책 버전을 정한다. 모든 산출물에는 아래 버전 문자열이 들어가며, 버전이 다른 자료는 변환 없이 섞지 않는다.

## 1. 버전

| 이름 | 현재 값 | 바뀌면 |
|------|---------|--------|
| 그래프 형식 | `colosseum.arggraph/v2` | `schema`가 없는 그래프는 v1로 읽는다. v1과 v2는 같은 필드를 쓰며, v2는 아래 선택 필드를 더한다 |
| 인용 대조기 | `quote-match/2` | 인용 대조 결과(v, n, u)를 다시 계산한다 |
| 근거 정책 | `evidence-policy/2` | 점수와 근거 자격이 바뀌므로 판정을 다시 계산한다. `verdict` 출력의 `policy`에 기록된다 |
| 실행 상태 | `colosseum.state/v2` | 다른 버전의 체크포인트는 `resume`이 거부한다. `restart`로 새 실행을 연다 |
| 예측 저장소 | `colosseum.forecasts/v1` (sqlite) | `forecast import`가 JSONL을 한 번 가져온다 |
| 결정 기록 | `colosseum.decision/v1` | `adr` 출력 |

## 2. 다섯 가지 기록

자료를 다음 다섯 가지로 나눈다. 현재 그래프의 evidence 레코드는 아래 source, quote, assessment를 한 줄에 펼친 형태이며, 각 필드가 어느 기록에 속하는지 표에 적었다.

### source (원문)

| 필드 | 뜻 |
|------|----|
| `url` | 인용한 원래 URL |
| `url_normalized` | 정규화한 URL: 소문자 scheme과 host, IDNA(punycode) host, 기본 포트 제거, fragment 제거. 정규화는 문자열 비교용이며 출처 독립성 판단을 대신하지 않는다 |
| `acquisition` | `full_page`(페이지를 가져옴), `snippet`(검색 스니펫만 있음), `unavailable`(어느 쪽도 없음) |
| `reliability`, `origin`, `publisher`, `published`, `freshness` | 출처 속성. `freshness`를 판단할 수 없으면 `unknown`이며 최신으로 가정하지 않는다 |
| `match.content_hash` | 대조에 쓴 원문 텍스트의 해시 |

### quote (인용 대조)

| 필드 | 뜻 |
|------|----|
| `quote` | 참가자가 제출한 인용 원문 |
| `quote_status` | `v`, `snippet`, `n`, `u` |
| `match.matcher` | 대조기 버전 |
| `match.reason` | 판정 사유. 예: `exact`, `negation or comparison differs from the page`, `quote leaves out part of its sentence that carries a condition or scope: if` |
| `match.span` | 원문 토큰 기준 일치 위치 `[시작, 끝)` |

`n`은 사람의 검토가 필요하다는 뜻이다. 모델이 의미가 같다고 판단해도 등급을 올리지 않는다.

### claim (주장)

| 필드 | 뜻 |
|------|----|
| `id` | 안정 ID. Workflow는 `r<라운드>.i<쟁점>.<역할>.<라벨>.<순번>`을 쓴다(쟁점이 없으면 `i-`). 표시용 라벨 A, B, C만으로 ID를 만들지 않는다 |
| `round`, `issue`, `role`, `participant`, `ordinal` | ID를 이루는 필드를 따로 보관한다 |
| `text`, `kind`, `status`, `author` | 주장 문장, 종류, active 또는 withdrawn, 작성자 라벨 |

### assessment (지지 판정)

| 필드 | 뜻 |
|------|----|
| `claim_id` | 판정 대상 주장 |
| `support` | `full`, `partial`, `none`, `unknown` |
| `support_reason` | 한 문장 이유 |
| `assessment_key` | claim ID, 주장 텍스트 해시, 인용 키, 문맥 해시, 정책 버전을 이은 키. 이 중 하나라도 바뀌면 새로 판정한다 |

한 evidence 레코드는 인용 하나를 주장 하나에 묶는다. 같은 인용을 두 주장이 쓰면 레코드도 둘이다. 원문 획득은 재사용하지만 지지 판정은 주장마다 따로 한다.

### run (실행)

`sessions/<session>/state.json`이 현재 실행의 체크포인트이고, 실행의 모든 파일은 `sessions/<session>/runs/<run_id>/`에 둔다.

| 필드 | 뜻 |
|------|----|
| `run_id` | `<UTC 시각>-<질문 해시 8자>` |
| `question_sha256` | 질문 원문의 SHA-256 앞 16자 |
| `status` | `running`, `completed`, `failed`, `cancelled`, `interrupted` |
| `phase`, `round`, `budget`, `used`, `history` | 단계 기계의 상태 |

기본 입력 파일은 현재 실행의 디렉터리에서만 읽는다. 다른 실행의 파일은 `--run <run_id>`로 명시해야 읽을 수 있다.

## 3. 근거 자격 (evidence-policy/2)

하나의 함수(`graph.eligible`, Workflow의 `LIB.eligible`)가 점수, undercut 예외, 점검표의 "검증됨" 판단에 모두 쓰인다.

```
eligible(e) = quote_status ∈ {v, snippet}
              and support ∈ {full, partial}
              and freshness ≠ superseded
score(e)    = eligible(e) ? reliability × quote × support × freshness : 0
```

| 값 | 가중치 |
|----|--------|
| quote_status | v 1.0, snippet 0.5, n 0, u 0 |
| support | full 1.0, partial 0.5, none 0, unknown 0 |
| freshness | fresh 1.0, na 1.0, unknown 0.75, stale 0.5, superseded 0 |

관계는 `(type, subtype, from, to)`로 중복을 지운다. 같은 공격을 두 번 넣어도 판정과 강도는 같다. 독립된 새 반론은 다른 주장에서 나오므로 키가 다르다.

## 4. 사람의 수정

사람이 판정을 고칠 때는 원자료를 덮어쓰지 않는다. `whatif`에 넘기는 변경(근거 하나 제외, 주장 하나를 미입증으로 표시)은 별도 입력이며, 결과는 원래 판정과 나란히 보고한다.
