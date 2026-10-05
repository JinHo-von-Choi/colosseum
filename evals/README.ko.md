# Colosseum 평가

[English](README.md)

`claude plugin eval`(Claude Code v2.1.269 이상)용 사례다. 사례마다 플러그인을 켠 경우와 끈 경우를 모두 돌리고, 보고서에 차이를 보여 준다.

| 묶음 | 사례 수 | 확인 내용 | 채점 |
|------|--------|----------|------|
| `trig-pos-*` | 5 | 토론, 비판적 분석, 팩트체크 요청에 스킬이 실행되는가 | `tool_used: Skill` |
| `trig-neg-*` | 5 | 검색, 요약, 번역, 코드, 계산 요청에는 실행되지 않는가 | Skill과 Agent가 호출되지 않음 |
| `acc-*` | 10 | 답이 알려진 흔한 오해 | 정답 기준 LLM 채점, URL 포함, 보고서 형식, 기준선 기록 |
| `con-*` | 4 | 논쟁적 질문 | 균형과 거짓 합의 여부 LLM 채점, URL 포함, 반대 논거 섹션 |

태그: `smoke`(호출 여부 사례 전체), `trigger`, `negative`, `accuracy`, `factual`, `contested`, `decision`

## 실행

```bash
claude plugin eval . --tag smoke --runs 1 --ablation none
claude plugin eval . --allow-tools WebSearch WebFetch --judge-model sonnet -j 2 --max-cost-usd 60
```

- Sonnet 기준으로 토론 사례 한 번에 약 1달러가 든다. `acc-*`와 `con-*` 14개를 3회씩, 플러그인 없는 비교군까지 돌리면 50~90달러 정도다.
- `Bash`를 허용하려면 샌드박스 백엔드(Linux에서는 bubblewrap과 socat)가 있어야 한다. 없으면 실행이 거부된다.
- 평가 샌드박스 안에서는 외부 에이전트 CLI가 대개 실패한다(임시 HOME, 인증 정보 없음). 그래서 평가는 Claude만으로 된 명단을 측정한다.
- 긴 한국어 보고서의 LLM 채점에는 `--judge-model sonnet`을 쓴다.

## 버전 비교

두 버전에서 모두 돌리고 JSON 출력의 `aggregates`와 `costUsd`를 비교한다.

```bash
git worktree add ../colosseum-old <이전-태그>
claude plugin eval ../colosseum-old --allow-tools WebSearch WebFetch --json old.json
claude plugin eval . --allow-tools WebSearch WebFetch --json new.json
```

비용을 맞춰 비교한다. 돈을 더 써서 점수가 오른 버전이 더 나은 것은 아니다.
