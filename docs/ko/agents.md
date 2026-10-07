# 외부 에이전트

모델 계열이 다르면 틀리는 지점도 다르다. 그래서 Colosseum은 사용자 컴퓨터에 설치된 AI 에이전트 CLI를 호스트의 기본 모델과 함께 참가자로 쓴다.

## 지원 에이전트

| id | 도구 | 실행 방식 |
|----|------|----------|
| `codex` | OpenAI Codex CLI | `codex exec --sandbox read-only --skip-git-repo-check -`, 프롬프트는 표준입력 |
| `gemini` | Gemini CLI | `gemini`, 프롬프트는 표준입력 |
| `kimi` | Kimi Code CLI | `kimi -p <프롬프트>` |
| `mcode` | MiniMax Code | `mcode exec <프롬프트>` |
| `qwen` | Qwen Code | `qwen`, 프롬프트는 표준입력 |
| `opencode` | OpenCode | `opencode run <프롬프트>` |
| `hermes` | Hermes Agent | `hermes -z <프롬프트>` |
| `openclaw` | OpenClaw | `openclaw agent --agent main --message <프롬프트>`. 게이트웨이가 켜져 있어야 한다 |
| `cursor-agent` | Cursor CLI | `cursor-agent -p --output-format text <프롬프트>` |
| `copilot` | GitHub Copilot CLI | `copilot -p <프롬프트>` |
| `crush` | Crush | `crush run <프롬프트>` |
| `amp` | Amp | `amp -x <프롬프트>` |
| `goose` | Goose | `goose run --no-session -i -`, 프롬프트는 표준입력 |
| `llm` | llm | `llm`, 프롬프트는 표준입력 |
| `aichat` | aichat | `aichat`, 프롬프트는 표준입력 |
| `ollama` | Ollama | `ollama run <모델>`, 프롬프트는 표준입력. 모델 이름은 에이전트 설정 파일에 적는다 |
| `claude` | Claude Code CLI | `claude -p`, 쓰기 도구 차단 |

`cursor-agent`, `copilot`, `crush`, `amp`, `goose`, `qwen`, `aichat`은 등록부에 미검증으로 표시되어 있다. 쓰기 전에 아래 확인(probe)을 돌린다.

## 사용 가능한 에이전트 확인

```bash
relay.py detect            # 설치된 에이전트, 선호 순서대로
relay.py detect --probe    # 각 에이전트에 한 단어 시험 프롬프트도 보낸다
```

설치되어 있고 시험 프롬프트에 답하는 에이전트만 사용 가능으로 친다. 확인 결과는 24시간 동안 다시 쓰며, `--refresh`로 새로 확인한다.

## 명단 구성 규칙

```bash
relay.py roster --size 3 --probe --prefer codex,kimi
```

1. 사용자가 지정한 에이전트(`--prefer`)를 지정한 순서대로 먼저 넣는다. `--only`를 쓰면 다른 외부 에이전트는 넣지 않는다.
2. 남은 자리는 사용 가능한 에이전트를 우선순위 순서로 채우되, 모델 계열마다 하나만 넣는다.
3. 외부 에이전트는 최대 2자리다. 토론 중에 웹 검색을 맡을 호스트 기본 모델 참가자 한 자리를 남긴다. `--max-cli`로 바꿀 수 있다.
4. Claude Code CLI는 Claude Code 안에서 기본 참가자와 같은 계열이므로 사용자가 지정할 때만 넣는다.
5. 명단에 들지 않은 에이전트 중 명단에 없는 계열의 것을 배심원으로 세운다.
6. 라벨 A, B, C는 무작위 순서로 붙인다.

결과의 `transmission`에는 프롬프트를 받게 될 제공자가, `notes`에는 주의 사항이 나온다.

## 에이전트 설정 파일

Colosseum 데이터 디렉터리([레퍼런스](reference.md#데이터-디렉터리) 참고)에 `agents.json`을 만들거나, `COLOSSEUM_AGENTS_FILE`로 다른 경로를 지정한다. 내용은 기본 등록부에 덮어써진다.

```json
{
  "prefer": ["kimi", "codex"],
  "agents": {
    "opencode": {"family": "zhipu", "family_uncertain": false},
    "ollama": {"vars": {"model": "qwen3"}},
    "gemini": {"disabled": true},
    "my-agent": {
      "name": "My agent",
      "provider": "Mistral",
      "family": "mistral",
      "argv": ["my-agent", "--ask", "{prompt}"],
      "prompt": "arg"
    }
  }
}
```

| 필드 | 뜻 |
|------|----|
| `argv` | 실행 파일과 인자. `prompt`가 `"arg"`이면 `{prompt}` 자리에 프롬프트가 들어가고, `{이름}`에는 `vars.이름` 값이 들어간다. 자리표시자는 인자 하나 전체여야 한다 |
| `prompt` | `"stdin"` 또는 `"arg"` |
| `family` | 모델 제공사. 같은 계열의 에이전트는 투표에서 한 표로 묶인다 |
| `family_uncertain` | `family`를 실제 쓰는 모델에 맞췄으면 `false` |
| `provider` | 프롬프트를 보내기 전에 사용자에게 보여 줄 제공자 이름 |
| `vars` | `{model}`, `{agent}` 같은 자리표시자에 넣을 값 |
| `priority` | 선호 순서가 없을 때 작은 값이 먼저 |
| `disabled` | `true`면 쓰지 않는다 |

`COLOSSEUM_AGENTS=codex,kimi`로 한 셸 세션 동안의 선호 순서를 정할 수 있다.

OpenCode, Hermes, OpenClaw처럼 어떤 모델이든 붙일 수 있는 에이전트는 `family`를 설정한 모델의 제공사로 바꿔 둔다. 그러지 않으면 같은 모델을 쓰는 두 에이전트가 서로 독립된 표로 계산된다.

## 데이터 전송과 안전

- 질문과 토론 프롬프트는 선택된 에이전트의 모델 제공자에게 전송된다. 실행 전에 제공자를 알려 주고, 질문에 소스 코드, 내부 문서, 개인정보가 있으면 외부 에이전트를 넣기 전에 사용자에게 묻는다.
- 프롬프트는 셸을 거치지 않는다. 표준입력으로 보내거나, 필요한 에이전트에는 실행 인자 하나로 보낸다.
- 에이전트는 빈 임시 디렉터리에서 실행되므로 코딩 에이전트라도 고칠 프로젝트가 없다. Codex는 읽기 전용 샌드박스로, Claude CLI는 쓰기 도구를 막고 실행한다.
- 시간이 초과되면 에이전트와 그 자식 프로세스를 모두 종료한다. 프롬프트 파일은 실행 뒤 지운다.

`relay.py`는 플러그인의 `skills/colosseum/scripts/relay.py`다.
