---
name: git-review
description: Review git status and diffs, summarize changes, identify risky edits, and draft clear commit messages.
---

# Git Review Skill

Use this skill before committing or after a repair round.

## Steps

1. Run or request:
   - `git status`
   - `git diff --stat`
   - `git diff`
2. Summarize changed files.
3. Classify changes:
   - code
   - config
   - data
   - outputs
   - documentation
4. Identify risky or accidental changes.
5. Draft a commit message.

## Commit message style

Use concise conventional style when possible:

- `fix: repair evidence coverage check`
- `feat: add recollection plan validation`
- `chore: update collector config`
- `docs: update dataset workflow notes`
