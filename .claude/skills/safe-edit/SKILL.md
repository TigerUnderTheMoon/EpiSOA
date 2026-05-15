---
name: safe-edit
description: Make safe, minimal code edits. Always inspect files first, explain the intended change, avoid broad rewrites, and preserve existing project conventions.
---

# Safe Edit Skill

Use this skill whenever modifying code, configuration, scripts, or data-processing logic.

## Rules

1. Always inspect the relevant files before editing.
2. Before changing code, summarize:
   - the target file
   - the bug or improvement
   - the minimal change plan
3. Prefer small patches over large rewrites.
4. Do not rename files, move directories, delete data, or overwrite outputs unless explicitly instructed.
5. Preserve existing CLI arguments, output paths, logging style, and project conventions.
6. After editing, suggest a concrete verification command.
7. If the change affects data outputs, remind the user to back up or write to a new output directory.

## Especially important for this project

This project contains JSONL data, evidence collection outputs, coverage reports, annotation inputs, and quality checks. Avoid destructive operations on `data/` and `outputs/` unless the user explicitly requests them.
