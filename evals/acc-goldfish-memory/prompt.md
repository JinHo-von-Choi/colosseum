---
schema_version: "1.1"
name: acc-goldfish-memory
description: "Stable misconception check: goldfish-memory"
tags: [accuracy, factual]
max_turns: 150
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, TaskCreate, TaskUpdate]
---

colosseum: 금붕어의 기억력은 3초라는 말이 사실인가? 근거와 함께 판정해줘.
