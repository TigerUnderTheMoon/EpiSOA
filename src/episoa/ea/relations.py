"""Relation-decision and evaluation-label contracts for EpiSOA-EA."""

from __future__ import annotations

from episoa.ea.schema import (
    RELATION_BY_EFFECT_TYPE,
    EffectType,
    RelationDecision,
    RelationEvaluationLabel,
)


def relation_evaluation_label(
    effect_type: EffectType,
    relation_decision: RelationDecision,
) -> RelationEvaluationLabel:
    """Map the internal binary decision to the frozen evaluation label."""
    if relation_decision == "no_relation":
        return "no_relation"
    return RELATION_BY_EFFECT_TYPE[effect_type]  # type: ignore[return-value]
