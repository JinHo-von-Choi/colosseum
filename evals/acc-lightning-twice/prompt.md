---
schema_version: "1.1"
name: acc-lightning-twice
description: "Stable misconception check: lightning-twice"
tags: [accuracy, factual]
max_turns: 150
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, TaskCreate, TaskUpdate]
---

colosseum: 번개는 같은 곳에 두 번 치지 않는다는 말이 맞는가? 근거와 함께 판정해줘.
