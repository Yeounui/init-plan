---
description: Use when authoring or editing skills, rules, agent prompts, or instruction docs across .claude, .codex, .llama, and CLAUDE.md.
paths:
  - "./CLAUDE.md"
  - "./.claude/**/*.md"
  - "./.codex/**/*.md"
  - "./.llama/**/*.md"
  - "./init-plan/skills/**/*.md"
  - "./init-plan/rules/**/*.md"
---

## Information-Only Authoring

Skills, rules, agent prompts, and instruction docs contain only directly-usable
information — the facts, patterns, commands, and steps a reader applies
immediately. Write them in plain present-tense statements, as trusted and ready
to use.

## Keep Meta-Explanation Out

Do not put meta-explanation in these documents:

- provenance or audit trail — "verified", "Source: <path>", "confirmed on
  <date>", "not guessed", "re-checkable", "sourced from a real file"
- verification or trust status — "this was tested", "partly verified",
  "unverified gap", "don't trust until X"
- rationale-for-existence narration — "this skill exists because…", "this
  example proves…", "found by diffing…"
- evidence tracking or confidence hedging

State the fact plainly instead. A pattern, command, or constant is written as
correct, not as "the confirmed value".

## Where Meta Goes Instead

Record provenance, what was or was not verified, why a pattern was added, and
when it was confirmed in **memory**, as the work happens. Memory is the audit
trail; the skill/rule is the clean result.

## Exception: Plan Progress Status

`plan/` documents may carry progress and status — and only there — to make the
next action visible (see `Edit_Workflow.md` § Status Language). This is the one
place status meta belongs in project documents; it is not an audit trail.
