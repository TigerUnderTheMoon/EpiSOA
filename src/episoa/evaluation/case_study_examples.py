"""Deprecated compatibility module for case-study generation.

Deprecated: use src/episoa/evaluation/case_study.py instead.
"""

from episoa.evaluation.case_study import (  # noqa: F401
    generate_case_study_examples,
    load_jsonl,
    resolve_run_dir,
    write_case_study_examples,
)
