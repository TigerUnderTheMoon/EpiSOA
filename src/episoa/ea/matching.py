"""Shared Explanation matching used by every EpiSOA-EA comparison method."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from episoa.ea.schema import EvidenceLink


class SemanticEquivalenceRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1)
    groups: list[list[str]] = Field(default_factory=list)


class ExplanationMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
    method: str
    score: float = 0.0
    rule_version: str


def load_semantic_equivalence_rules(path: str | Path) -> SemanticEquivalenceRules:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return SemanticEquivalenceRules.model_validate(payload)


def chinese_character_f1(left: str, right: str) -> float:
    """Multiset character F1 after dropping whitespace."""
    left_chars = [char for char in str(left) if not char.isspace()]
    right_chars = [char for char in str(right) if not char.isspace()]
    if not left_chars or not right_chars:
        return 0.0
    overlap = sum((Counter(left_chars) & Counter(right_chars)).values())
    precision = overlap / len(right_chars)
    recall = overlap / len(left_chars)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def match_explanation(
    *,
    gold_explanation: str,
    prediction_explanation: str,
    gold_links: list[EvidenceLink],
    prediction_links: list[EvidenceLink],
    rules: SemanticEquivalenceRules,
    span_f1_threshold: float = 0.5,
) -> ExplanationMatchResult:
    """Match by same-document span overlap or a shared versioned rule set."""
    best_span_score = 0.0
    for gold in _explanation_links(gold_links):
        for prediction in _explanation_links(prediction_links):
            if gold.document_id != prediction.document_id:
                continue
            best_span_score = max(
                best_span_score,
                chinese_character_f1(gold.span_text, prediction.span_text),
            )
    if best_span_score >= span_f1_threshold:
        return ExplanationMatchResult(
            matched=True,
            method="span_overlap",
            score=round(best_span_score, 6),
            rule_version=rules.version,
        )

    left = normalize_semantic_text(gold_explanation)
    right = normalize_semantic_text(prediction_explanation)
    if left and right and (left == right or _same_rule_group(left, right, rules)):
        return ExplanationMatchResult(
            matched=True,
            method="semantic_rule",
            score=1.0,
            rule_version=rules.version,
        )
    return ExplanationMatchResult(
        matched=False,
        method="none",
        score=round(best_span_score, 6),
        rule_version=rules.version,
    )


def normalize_semantic_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(
        char for char in text if not char.isspace() and not re.match(r"[\W_]", char)
    )


def _explanation_links(links: list[EvidenceLink]) -> list[EvidenceLink]:
    fields = {"explanation", "explanation_surface", "normalized_explanation"}
    return [
        link
        for link in links
        if link.target_type == "claim"
        and link.support_label == "supports"
        and link.support_field in fields
    ]


def _same_rule_group(left: str, right: str, rules: SemanticEquivalenceRules) -> bool:
    for group in rules.groups:
        normalized_group = {normalize_semantic_text(item) for item in group}
        if left in normalized_group and right in normalized_group:
            return True
    return False
