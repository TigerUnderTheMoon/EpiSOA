---
name: repo-map
description: Map a repository structure, identify important scripts, configs, data folders, outputs, and the likely execution workflow.
---

# Repo Map Skill

Use this skill at the beginning of a project session or when the user asks where something is.

## What to inspect

1. top-level files
2. `scripts/`
3. `configs/`
4. `data/`
5. `outputs/`
6. README or project notes
7. recent output directories
8. Python entry scripts
9. config files used by commands

## Output format

Return:

1. Project structure summary
2. Key scripts and their purpose
3. Data flow
4. Current likely stage
5. Suggested next command

## Safety

Do not modify files. This is a read-only skill.
