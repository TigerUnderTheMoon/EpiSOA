"""Evidence selection strategies for Event-SOA attribution prompts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import random
import re
from typing import Any


SELECTOR_MODES = {"random", "quality_topk", "bm25_keyword", "chain_aware", "coverage_optimized", "oracle"}
STAGE_PRIORITY = ["conflict", "response", "resolution", "trigger", "diffusion", "follow_up"]


@dataclass(frozen=True)
class SelectionResult:
    evidence: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def select_evidence_for_prompt(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    max_evidence: int,
    mode: str = "chain_aware",
    oracle_evidence_ids: list[str] | None = None,
    seed: int = 42,
    stakeholder_candidates: list[str] | None = None,
) -> SelectionResult:
    """Select prompt evidence and return per-event diagnostics.

    The implementation is deterministic for a given event and seed, and never
    reads gold tuple text. Oracle mode only accepts explicit evidence IDs from
    the caller for upper-bound diagnostics.
    """
    mode = mode or "chain_aware"
    candidates = normalize_stakeholder_candidates(stakeholder_candidates or [])
    if mode not in SELECTOR_MODES:
        raise ValueError(f"unknown evidence selector mode: {mode}")
    if max_evidence <= 0:
        diagnostics = base_diagnostics(mode, [])
        diagnostics.update(stakeholder_coverage_diagnostics(candidates, []))
        return SelectionResult([], diagnostics)

    if mode == "oracle":
        selected = select_oracle_first(
            event=event,
            chain=chain,
            evidence_rows=evidence_rows,
            oracle_evidence_ids=oracle_evidence_ids or [],
            max_evidence=max_evidence,
        )
        selected = prioritize_stakeholder_coverage(
            event=event,
            chain=chain,
            evidence_rows=evidence_rows,
            base_selected=selected,
            max_evidence=max_evidence,
            stakeholder_candidates=candidates,
            preserve_existing=True,
        )
        diagnostics = base_diagnostics(mode, selected)
        selected_ids = {str(item.get("evidence_id", "")) for item in selected}
        oracle_ids = dedupe([str(eid) for eid in oracle_evidence_ids or [] if str(eid).strip()])
        diagnostics.update(
            {
                "oracle_evidence": True,
                "oracle_gold_evidence_ids": oracle_ids,
                "oracle_gold_evidence_in_prompt": [eid for eid in oracle_ids if eid in selected_ids],
                "oracle_gold_evidence_missing": [eid for eid in oracle_ids if eid not in selected_ids],
                "oracle_gold_evidence_truncated": any(eid not in selected_ids for eid in oracle_ids),
            }
        )
        diagnostics.update(stakeholder_coverage_diagnostics(candidates, selected))
        return SelectionResult(selected, diagnostics)

    if mode == "random":
        rnd = random.Random(stable_seed(event.get("event_id", ""), seed))
        rows = list(evidence_rows)
        rnd.shuffle(rows)
        selected_rows = rows[:max_evidence]
        selected = [normalize_prompt_evidence(row=row, chain_item={}, stage="unknown") for row in selected_rows]
        selected = annotate_matched_stakeholders(selected, candidates)
        diagnostics = base_diagnostics(mode, selected)
        diagnostics.update(stakeholder_coverage_diagnostics(candidates, selected))
        return SelectionResult(selected, diagnostics)

    if mode == "quality_topk":
        selected_rows = sorted(
            evidence_rows,
            key=lambda row: (safe_float(row.get("quality_score"), 0.0), lexical_event_score(event, row)),
            reverse=True,
        )[:max_evidence]
        selected = [
            normalize_prompt_evidence(
                row=row,
                chain_item=chain_metadata_by_evidence(chain).get(str(row.get("evidence_id", "")), {}),
                stage=chain_metadata_by_evidence(chain).get(str(row.get("evidence_id", "")), {}).get("stage", "unknown"),
            )
            for row in selected_rows
        ]
        selected = prioritize_stakeholder_coverage(
            event=event,
            chain=chain,
            evidence_rows=evidence_rows,
            base_selected=selected,
            max_evidence=max_evidence,
            stakeholder_candidates=candidates,
        )
        diagnostics = base_diagnostics(mode, selected)
        diagnostics.update(stakeholder_coverage_diagnostics(candidates, selected))
        return SelectionResult(selected, diagnostics)

    if mode == "bm25_keyword":
        selected_rows = sorted(
            evidence_rows,
            key=lambda row: (lexical_event_score(event, row), safe_float(row.get("quality_score"), 0.0)),
            reverse=True,
        )[:max_evidence]
        selected = [
            normalize_prompt_evidence(
                row=row,
                chain_item=chain_metadata_by_evidence(chain).get(str(row.get("evidence_id", "")), {}),
                stage=chain_metadata_by_evidence(chain).get(str(row.get("evidence_id", "")), {}).get("stage", "unknown"),
            )
            for row in selected_rows
        ]
        selected = prioritize_stakeholder_coverage(
            event=event,
            chain=chain,
            evidence_rows=evidence_rows,
            base_selected=selected,
            max_evidence=max_evidence,
            stakeholder_candidates=candidates,
        )
        diagnostics = base_diagnostics(mode, selected)
        diagnostics.update(stakeholder_coverage_diagnostics(candidates, selected))
        return SelectionResult(selected, diagnostics)

    if mode == "coverage_optimized":
        selected, coverage_diagnostics = select_coverage_optimized(
            event=event,
            chain=chain,
            evidence_rows=evidence_rows,
            max_evidence=max_evidence,
            stakeholder_candidates=candidates,
        )
        diagnostics = base_diagnostics(mode, selected)
        diagnostics.update(stakeholder_coverage_diagnostics(candidates, selected))
        diagnostics.update(coverage_diagnostics)
        return SelectionResult(selected, diagnostics)

    selected = select_chain_aware(event=event, chain=chain, evidence_rows=evidence_rows, max_evidence=max_evidence)
    selected = prioritize_stakeholder_coverage(
        event=event,
        chain=chain,
        evidence_rows=evidence_rows,
        base_selected=selected,
        max_evidence=max_evidence,
        stakeholder_candidates=candidates,
    )
    diagnostics = base_diagnostics(mode, selected)
    diagnostics.update(stakeholder_coverage_diagnostics(candidates, selected))
    return SelectionResult(selected, diagnostics)


def select_oracle_first(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    oracle_evidence_ids: list[str],
    max_evidence: int,
) -> list[dict[str, Any]]:
    by_id = {str(row.get("evidence_id", "")): row for row in evidence_rows if row.get("evidence_id")}
    chain_scores = chain_metadata_by_evidence(chain)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for evidence_id in dedupe([str(eid) for eid in oracle_evidence_ids if str(eid).strip()]):
        if len(selected) >= max_evidence:
            break
        row = by_id.get(evidence_id)
        if not row or evidence_id in seen:
            continue
        metadata = chain_scores.get(evidence_id, {})
        stage = str(metadata.get("stage") or row.get("temporal_stage") or "oracle_gold")
        selected.append(
            normalize_prompt_evidence(
                row=row,
                chain_item={
                    "evidence_id": evidence_id,
                    "stage": stage,
                    "final_stage_score": metadata.get("final_stage_score", "oracle"),
                    "event_relevance_score": metadata.get("event_relevance_score", "oracle"),
                    "selection_score": "oracle",
                },
                stage=stage,
            )
        )
        seen.add(evidence_id)

    if len(selected) >= max_evidence:
        return selected

    fallback = select_chain_aware(event=event, chain=chain, evidence_rows=evidence_rows, max_evidence=max_evidence)
    for item in fallback:
        if len(selected) >= max_evidence:
            break
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen:
            selected.append(item)
            seen.add(evidence_id)
    return selected


def select_chain_aware(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    max_evidence: int,
) -> list[dict[str, Any]]:
    chain_scores = chain_metadata_by_evidence(chain)
    remaining: list[tuple[dict[str, float], dict[str, Any]]] = []
    for row in evidence_rows:
        components = score_components(event=event, row=row, chain_metadata=chain_scores.get(str(row.get("evidence_id", "")), {}))
        remaining.append((components, row))

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    stage_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    while remaining and len(selected) < max_evidence:
        best_idx = -1
        best_score = -1.0
        best_components: dict[str, float] | None = None
        best_row: dict[str, Any] | None = None
        for idx, (components, row) in enumerate(remaining):
            evidence_id = str(row.get("evidence_id", ""))
            if not evidence_id or evidence_id in seen:
                continue
            stage = str(chain_scores.get(evidence_id, {}).get("stage") or row.get("temporal_stage") or "unknown")
            source = source_family(row)
            stage_bonus = 0.16 if stage != "unknown" and stage_counts[stage] == 0 else 0.0
            source_bonus = 0.12 if source_counts[source] == 0 else 0.0
            adjusted = components["base_score"] + stage_bonus + source_bonus
            if adjusted > best_score:
                best_idx = idx
                best_score = adjusted
                best_components = dict(components)
                best_components["source_diversity_bonus"] = source_bonus
                best_components["temporal_stage_coverage_bonus"] = stage_bonus
                best_components["selection_score"] = round(min(1.0, adjusted), 4)
                best_row = row
        if best_idx < 0 or best_row is None or best_components is None:
            break
        remaining.pop(best_idx)
        evidence_id = str(best_row.get("evidence_id", ""))
        metadata = dict(chain_scores.get(evidence_id, {}))
        stage = str(metadata.get("stage") or best_row.get("temporal_stage") or "unknown")
        metadata.update(best_components)
        selected.append(normalize_prompt_evidence(row=best_row, chain_item=metadata, stage=stage))
        seen.add(evidence_id)
        stage_counts[stage] += 1
        source_counts[source_family(best_row)] += 1

    return selected


def select_coverage_optimized(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    max_evidence: int,
    stakeholder_candidates: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chain_scores = chain_metadata_by_evidence(chain)
    remaining = [row for row in evidence_rows if str(row.get("evidence_id", "")).strip()]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    covered_stages: set[str] = set()
    covered_sources: set[str] = set()
    covered_stakeholders: set[str] = set()
    redundancy_penalty_count = 0
    selected_components: list[dict[str, float]] = []

    while remaining and len(selected) < max_evidence:
        best_idx = -1
        best_score = -999.0
        best_row: dict[str, Any] | None = None
        best_metadata: dict[str, Any] = {}
        best_components: dict[str, float] = {}

        for idx, row in enumerate(remaining):
            evidence_id = str(row.get("evidence_id", ""))
            if evidence_id in seen:
                continue
            metadata = dict(chain_scores.get(evidence_id, {}))
            components = score_components(event=event, row=row, chain_metadata=metadata)
            stage = str(metadata.get("stage") or row.get("temporal_stage") or "unknown")
            source = source_family(row)
            matched = {
                candidate
                for candidate in stakeholder_candidates
                if candidate not in covered_stakeholders and evidence_mentions_stakeholder(row, candidate)
            }
            stage_bonus = 0.10 if stage != "unknown" and stage not in covered_stages else 0.0
            source_bonus = 0.06 if source and source not in covered_sources else 0.0
            stakeholder_bonus = min(0.48, 0.24 * len(matched))
            redundancy_penalty = max_redundancy_penalty(row, selected)
            objective = (
                components["base_score"]
                + stage_bonus
                + source_bonus
                + stakeholder_bonus
                - redundancy_penalty
            )
            if objective > best_score:
                best_idx = idx
                best_score = objective
                best_row = row
                best_components = dict(components)
                best_components.update(
                    {
                        "temporal_stage_coverage_bonus": round(stage_bonus, 4),
                        "source_family_coverage_bonus": round(source_bonus, 4),
                        "stakeholder_coverage_bonus": round(stakeholder_bonus, 4),
                        "redundancy_penalty": round(redundancy_penalty, 4),
                        "coverage_objective_score": round(max(0.0, min(1.0, objective)), 4),
                        "matched_stakeholder_count": float(len(matched)),
                    }
                )
                best_metadata = metadata

        if best_idx < 0 or best_row is None:
            break
        remaining.pop(best_idx)
        evidence_id = str(best_row.get("evidence_id", ""))
        stage = str(best_metadata.get("stage") or best_row.get("temporal_stage") or "unknown")
        metadata = dict(best_metadata)
        metadata.update(best_components)
        metadata["selection_score"] = best_components["coverage_objective_score"]
        selected.append(normalize_prompt_evidence(row=best_row, chain_item=metadata, stage=stage))
        selected_components.append(best_components)
        seen.add(evidence_id)
        if stage != "unknown":
            covered_stages.add(stage)
        covered_sources.add(source_family(best_row))
        covered_stakeholders.update(
            candidate
            for candidate in stakeholder_candidates
            if evidence_mentions_stakeholder(best_row, candidate)
        )
        if best_components.get("redundancy_penalty", 0.0) > 0:
            redundancy_penalty_count += 1

    selected = annotate_matched_stakeholders(selected, stakeholder_candidates)
    diagnostics = {
        "coverage_objective_components": summarize_objective_components(selected_components),
        "redundancy_penalty_count": redundancy_penalty_count,
        "coverage_objective": "greedy_event_stage_stakeholder_source_opinion_quality_minus_redundancy",
    }
    return selected, diagnostics


def prioritize_stakeholder_coverage(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    base_selected: list[dict[str, Any]],
    max_evidence: int,
    stakeholder_candidates: list[str],
    preserve_existing: bool = False,
) -> list[dict[str, Any]]:
    if max_evidence <= 0:
        return []
    if not stakeholder_candidates:
        return annotate_matched_stakeholders(base_selected[:max_evidence], [])

    chain_scores = chain_metadata_by_evidence(chain)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_item(item: dict[str, Any]) -> None:
        if len(selected) >= max_evidence:
            return
        evidence_id = str(item.get("evidence_id", ""))
        if not evidence_id or evidence_id in seen:
            return
        selected.append(item)
        seen.add(evidence_id)

    if preserve_existing:
        for item in base_selected:
            add_item(item)

    covered = covered_stakeholder_candidates(selected, stakeholder_candidates)
    for candidate in stakeholder_candidates:
        if len(selected) >= max_evidence:
            break
        if candidate in covered:
            continue
        row = best_evidence_for_stakeholder(
            candidate=candidate,
            event=event,
            evidence_rows=evidence_rows,
            chain_scores=chain_scores,
            seen_evidence_ids=seen,
        )
        if row is None:
            continue
        evidence_id = str(row.get("evidence_id", ""))
        metadata = dict(chain_scores.get(evidence_id, {}))
        components = score_components(event=event, row=row, chain_metadata=metadata)
        metadata.update(components)
        metadata["selection_score"] = metadata.get("selection_score", metadata.get("base_score", ""))
        stage = str(metadata.get("stage") or row.get("temporal_stage") or "unknown")
        add_item(normalize_prompt_evidence(row=row, chain_item=metadata, stage=stage))
        covered = covered_stakeholder_candidates(selected, stakeholder_candidates)

    for item in base_selected:
        if len(selected) >= max_evidence:
            break
        add_item(item)

    return annotate_matched_stakeholders(selected, stakeholder_candidates)


def best_evidence_for_stakeholder(
    *,
    candidate: str,
    event: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    chain_scores: dict[str, dict[str, Any]],
    seen_evidence_ids: set[str],
) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in evidence_rows:
        evidence_id = str(row.get("evidence_id", ""))
        if not evidence_id or evidence_id in seen_evidence_ids:
            continue
        if not evidence_mentions_stakeholder(row, candidate):
            continue
        metadata = chain_scores.get(evidence_id, {})
        components = score_components(event=event, row=row, chain_metadata=metadata)
        score = (
            0.40 * components["base_score"]
            + 0.25 * safe_float(row.get("quality_score"), 0.5)
            + 0.20 * components["opinion_bearing_signal"]
            + 0.15 * components["chain_stage_score"]
        )
        scored.append((score, row))
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def normalize_stakeholder_candidates(values: list[str]) -> list[str]:
    return dedupe([str(value).strip() for value in values if str(value).strip()])


def annotate_matched_stakeholders(
    selected: list[dict[str, Any]],
    stakeholder_candidates: list[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in selected:
        row = dict(item)
        row["matched_stakeholder_candidates"] = [
            candidate
            for candidate in stakeholder_candidates
            if evidence_mentions_stakeholder(row, candidate)
        ]
        row["unmatched_candidate_allowed"] = bool(stakeholder_candidates and not row["matched_stakeholder_candidates"])
        output.append(row)
    return output


def stakeholder_coverage_diagnostics(
    stakeholder_candidates: list[str],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    covered = sorted(covered_stakeholder_candidates(selected, stakeholder_candidates))
    uncovered = [candidate for candidate in stakeholder_candidates if candidate not in set(covered)]
    total = len(stakeholder_candidates)
    return {
        "stakeholder_candidate_count": total,
        "covered_stakeholder_candidates": covered,
        "uncovered_stakeholder_candidates": uncovered,
        "stakeholder_candidate_coverage": round(len(covered) / total, 4) if total else 0.0,
        "stakeholder_coverage_strategy": "stakeholder_first_then_selector_fill",
    }


def covered_stakeholder_candidates(
    selected: list[dict[str, Any]],
    stakeholder_candidates: list[str],
) -> set[str]:
    covered: set[str] = set()
    for item in selected:
        for candidate in stakeholder_candidates:
            if evidence_mentions_stakeholder(item, candidate):
                covered.add(candidate)
    return covered


def evidence_mentions_stakeholder(row: dict[str, Any], stakeholder: str) -> bool:
    candidate = compact_text(stakeholder)
    if not candidate:
        return False
    text = compact_text(
        " ".join(
            str(row.get(key) or "")
            for key in (
                "stakeholder_hint",
                "matched_stakeholder_candidates",
                "stance_hint",
                "title",
                "text",
                "text_excerpt",
            )
        )
    )
    if not text:
        return False
    if candidate in text or text in candidate:
        return True
    return char_overlap(candidate, text[: max(80, len(candidate) * 8)]) >= 0.45


def compact_text(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def char_overlap(left: str, right: str) -> float:
    left_set = set(str(left or ""))
    right_set = set(str(right or ""))
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def max_redundancy_penalty(row: dict[str, Any], selected: list[dict[str, Any]]) -> float:
    if not selected:
        return 0.0
    text = evidence_signature(row)
    if not text:
        return 0.0
    max_similarity = max(text_similarity(text, evidence_signature(item)) for item in selected)
    if max_similarity >= 0.85:
        return 0.45
    if max_similarity >= 0.65:
        return 0.22
    return 0.0


def evidence_signature(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("title", "text", "text_excerpt")
    ).lower()[:500]


def text_similarity(left: str, right: str) -> float:
    left_tokens = word_tokens(left)
    right_tokens = word_tokens(right)
    if len(left_tokens) >= 3 and len(right_tokens) >= 3:
        left_set = set(left_tokens)
        right_set = set(right_tokens)
        return len(left_set & right_set) / len(left_set | right_set) if left_set and right_set else 0.0
    return char_overlap(left, right)


def word_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").lower())


def summarize_objective_components(rows: list[dict[str, float]]) -> dict[str, Any]:
    keys = [
        "event_relevance",
        "stakeholder_signal",
        "opinion_bearing_signal",
        "chain_stage_score",
        "quality_score_component",
        "source_balance_component",
        "temporal_stage_coverage_bonus",
        "source_family_coverage_bonus",
        "stakeholder_coverage_bonus",
        "redundancy_penalty",
        "coverage_objective_score",
    ]
    if not rows:
        return {"selected_count": 0, "averages": {}}
    averages = {
        key: round(sum(float(row.get(key, 0.0) or 0.0) for row in rows) / len(rows), 4)
        for key in keys
    }
    return {"selected_count": len(rows), "averages": averages}


def score_components(
    *,
    event: dict[str, Any],
    row: dict[str, Any],
    chain_metadata: dict[str, Any],
) -> dict[str, float]:
    event_relevance = lexical_event_score(event, row)
    stakeholder_signal = evidence_stakeholder_signal(row, event)
    opinion_signal = opinion_bearing_signal(row, event)
    quality = safe_float(row.get("quality_score"), 0.5)
    chain_score = safe_float(chain_metadata.get("final_stage_score"), 0.0)
    base = (
        0.28 * event_relevance
        + 0.18 * stakeholder_signal
        + 0.18 * opinion_signal
        + 0.16 * chain_score
        + 0.12 * quality
        + 0.08 * source_prior(row)
    )
    return {
        "event_relevance": round(event_relevance, 4),
        "stakeholder_signal": round(stakeholder_signal, 4),
        "opinion_bearing_signal": round(opinion_signal, 4),
        "chain_stage_score": round(chain_score, 4),
        "quality_score_component": round(quality, 4),
        "source_balance_component": round(source_prior(row), 4),
        "base_score": round(min(1.0, base), 4),
    }


def normalize_prompt_evidence(*, row: dict[str, Any], chain_item: dict[str, Any], stage: str) -> dict[str, Any]:
    text = str(row.get("text") or chain_item.get("text_excerpt") or "")
    evidence_id = str(chain_item.get("evidence_id") or row.get("evidence_id") or "")
    item = {
        "evidence_id": evidence_id,
        "stage": stage,
        "source": row.get("source") or chain_item.get("source", ""),
        "source_type": row.get("source_type") or row.get("original_source") or row.get("source") or "",
        "domain": row.get("domain") or chain_item.get("domain", ""),
        "url": row.get("url") or chain_item.get("url", ""),
        "title": row.get("title") or chain_item.get("title", ""),
        "text_excerpt": chain_item.get("text_excerpt") or text[:500],
        "final_stage_score": chain_item.get("final_stage_score", chain_item.get("score", "")),
        "event_relevance_score": chain_item.get("event_relevance_score", ""),
        "selection_score": chain_item.get("selection_score", chain_item.get("base_score", "")),
        "selection_components": {
            key: chain_item[key]
            for key in (
                "event_relevance",
                "stakeholder_signal",
                "opinion_bearing_signal",
                "chain_stage_score",
                "quality_score_component",
                "source_balance_component",
                "source_diversity_bonus",
                "temporal_stage_coverage_bonus",
                "source_family_coverage_bonus",
                "stakeholder_coverage_bonus",
                "redundancy_penalty",
                "coverage_objective_score",
                "matched_stakeholder_count",
            )
            if key in chain_item
        },
        "evidence_spans": [
            {
                "evidence_id": evidence_id,
                "char_start": 0,
                "char_end": min(len(text), 500),
                "text": text[:500],
            }
        ],
    }
    return item


def base_diagnostics(mode: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    stages = [str(item.get("stage") or "unknown") for item in selected]
    sources = [source_family(item) for item in selected]
    scores = [safe_float(item.get("selection_score"), 0.0) for item in selected if item.get("selection_score") != "oracle"]
    return {
        "selector_mode": mode,
        "selected_evidence_ids": [str(item.get("evidence_id", "")) for item in selected if item.get("evidence_id")],
        "selected_evidence_count": len(selected),
        "stage_coverage": round(len({stage for stage in stages if stage != "unknown"}) / len(STAGE_PRIORITY), 4),
        "covered_stages": sorted({stage for stage in stages if stage != "unknown"}),
        "source_type_distribution": dict(Counter(sources)),
        "avg_selection_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
    }


def chain_metadata_by_evidence(chain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for stage in chain.get("stages", []) or []:
        stage_name = str(stage.get("stage", "unknown"))
        for item in stage.get("evidence", []) or []:
            eid = str(item.get("evidence_id", ""))
            if not eid:
                continue
            score = safe_float(item.get("final_stage_score", item.get("score", 0.0)), 0.0)
            current = metadata.get(eid)
            if current is None or score > safe_float(current.get("final_stage_score"), 0.0):
                metadata[eid] = {
                    "evidence_id": eid,
                    "stage": stage_name,
                    "event_relevance_score": item.get("event_relevance_score", ""),
                    "final_stage_score": item.get("final_stage_score", item.get("score", "")),
                    "score": item.get("score", ""),
                    "source": item.get("source", ""),
                    "domain": item.get("domain", ""),
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "text_excerpt": item.get("text_excerpt", ""),
                }
    return metadata


def lexical_event_score(event: dict[str, Any], row: dict[str, Any]) -> float:
    text = " ".join(str(row.get(key) or "") for key in ("title", "text", "snippet", "stakeholder_hint", "stance_hint"))
    terms = event_terms(event)
    if not terms:
        return safe_float(row.get("quality_score"), 0.5)
    hits = 0.0
    for term in terms:
        if term and term in text:
            hits += 1.25 if term in str(row.get("title") or "") else 1.0
    if str(event.get("event_id", "")) and str(row.get("event_id", "")) == str(event.get("event_id", "")):
        hits += 1.0
    return round(min(1.0, hits / max(2.0, len(terms) * 0.7)), 4)


def evidence_stakeholder_signal(row: dict[str, Any], event: dict[str, Any]) -> float:
    text = " ".join(str(row.get(key) or "") for key in ("stakeholder_hint", "stance_hint", "title", "text"))
    hints = [str(item).strip() for item in event.get("stakeholder_hints", []) if str(item).strip()]
    hits = sum(1 for hint in hints if hint in text)
    if row.get("stakeholder_hint"):
        hits += 1
    return round(min(1.0, hits / max(1, min(4, len(hints) or 1))), 4)


def opinion_bearing_signal(row: dict[str, Any], event: dict[str, Any]) -> float:
    text = " ".join(str(row.get(key) or "") for key in ("stance_hint", "title", "text"))
    hints = [str(item).strip() for item in event.get("stance_hints", []) if str(item).strip()]
    hits = sum(1 for hint in hints if hint and hint in text)
    if row.get("stance_hint"):
        hits += 1
    # Treat direct first-party interaction records as more likely to carry SOA.
    if source_family(row) in {"forum", "public_social", "public_interaction", "social_media"}:
        hits += 0.5
    return round(min(1.0, hits / max(1.0, min(4, len(hints) or 1))), 4)


def source_prior(row: dict[str, Any]) -> float:
    source = source_family(row)
    if source in {"official", "mainstream_news", "news"}:
        return 0.85
    if source in {"forum", "public_social", "social_media", "public_interaction"}:
        return 0.75
    if source == "public_web":
        return 0.65
    return 0.5


def source_family(row: dict[str, Any]) -> str:
    return str(row.get("source_type") or row.get("original_source") or row.get("source") or "unknown")


def event_terms(event: dict[str, Any]) -> list[str]:
    raw: list[Any] = []
    raw.extend([event.get("event_name", ""), event.get("event_description", ""), event.get("trigger", "")])
    raw.extend(event.get("seed_keywords", []) or [])
    raw.extend(event.get("query_seeds", []) or [])
    raw.extend(event.get("stakeholder_hints", []) or [])
    terms: list[str] = []
    for value in raw:
        for part in str(value or "").replace("|", " ").replace(",", " ").split():
            part = part.strip()
            if len(part) >= 2:
                terms.append(part)
    return dedupe(terms)[:24]


def stable_seed(value: Any, seed: int) -> int:
    digest = hashlib.sha1(f"{seed}:{value}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
