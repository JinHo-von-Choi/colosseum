---
schema_version: "1.1"
name: con-rag-vs-finetuning
description: "Contested question: rag-vs-finetuning"
tags: [contested, decision]
max_turns: 150
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, TaskCreate, TaskUpdate]
---

colosseum: 프로덕션 LLM 앱에서 RAG와 파인튜닝 중 어느 쪽이 더 나은가?
