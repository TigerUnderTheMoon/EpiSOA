---
name: python-debug
description: Debug Python scripts, CLI arguments, path problems, package issues, and runtime errors with minimal reproducible fixes.
---

# Python Debug Skill

Use this skill for Python errors, command-line execution problems, path issues, package issues, and script behavior debugging.

## Debugging steps

1. Identify the exact command the user ran.
2. Identify working directory.
3. Check relative paths against project root.
4. Inspect argparse parameters if the script uses CLI arguments.
5. Check whether the error is caused by:
   - missing file
   - wrong working directory
   - Windows vs WSL path mismatch
   - encoding problem
   - JSON/JSONL parse problem
   - missing package
   - schema mismatch
6. Propose the smallest fix.
7. Give a direct command to rerun.

## Style

Prefer Windows PowerShell commands when the user is in PowerShell.
Prefer WSL Bash commands when the path starts with `/mnt/`.
