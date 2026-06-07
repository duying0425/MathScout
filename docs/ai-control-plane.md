# AI Control Plane

MathScout should feel like supervising an AI research operator rather than
clicking through crawler settings.

## User Interaction

Users primarily interact through:

- natural-language commands
- visual progress and quality dashboards
- review queues for conflicts and high-impact changes
- source/login management

Example commands:

```text
先集中抓北师大版七年级上册，优先补有理数和一元一次方程的解题技巧。
如果某个来源连续 50 篇没有新增方法，就暂停它。
```

```text
把公开官方来源优先级调高，教师个人博客只用于补充方法，不要作为教材版本依据。
```

```text
暂停所有需要登录的站点，先完成公开数据覆盖率报告。
```

## AI Responsibilities

- convert natural language into structured directives
- plan crawl/extract/reconcile jobs
- select source priority and crawl depth
- watch coverage, novelty rate, duplicate rate, conflict rate, and confidence
- pause low-yield or noisy sources
- request login/cookies when a source is blocked
- decide continue, pause, retry, or stop
- explain every action in an audit log

## Human Responsibilities

- set objectives and scope
- provide access for login-gated sources when appropriate
- approve risky updates, conflicts, or destructive changes
- correct strategy when the AI optimizes the wrong target
- inspect quality reports before using or exporting data

## Hard Guardrails

The AI can propose and execute normal work, but deterministic policy checks must
block actions that violate:

- access controls
- domain enable/disable settings
- rate limits and budgets
- copyright storage/publishing rules
- destructive deletion rules
- conflict publishing rules

## Minimum UI

- Command Center: chat-like natural-language control.
- Current Plan: active goal, scope, budgets, stop conditions, next actions.
- Agent Decisions: chronological audit log with rationale and policy checks.
- Quality Monitor: coverage, novelty, duplicate rate, conflicts, source yield.
- Review Queue: candidate creates/updates/conflicts requiring user decision.
- Source Access: blocked-login list and cookie profile status.
- Technique Editor: edit canonical methods, teacher variants, mappings, and lock curated records.
- Change Log: inspect human edits, AI proposals, before/after payloads, and rollback candidates.
