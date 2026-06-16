"""End-to-end EpiSOA paper pipeline."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import yaml

from episoa.attribution.schema_attributor import (
    ALLOWED_SENTIMENT,
    ALLOWED_SUPPORT,
    ATTRIBUTION_MODE,
    MAX_OPINION_CHARS,
    MAX_RATIONALE_CHARS,
    MAX_TUPLES_PER_EVENT,
    PROMPT_VERSION,
    SOE_V3_METHOD_VERSION,
    assert_no_total_api_failure,
    run_schema_attribution,
)
from episoa.collector.cfsm_collector import collect_evidence
from episoa.config import api_config_status, load_config, print_api_config_status, resolve_api_config
from episoa.data.loader import read_jsonl, read_typed_jsonl, write_jsonl
from episoa.data.schema import EventRecord, EvidenceRecord, GoldEventChain, GoldTuple, PredictionTuple
from episoa.data.validator import validate_formal_event_record, validate_paper_data
from episoa.evaluation.evaluate_ablation import evaluate_ablation
from episoa.evaluation.evaluate_main import evaluate_main
from episoa.evaluation.evaluate_retrieval import evaluate_retrieval
from episoa.evaluation.evaluate_verifier import evaluate_verifier
from episoa.evaluation.ablation_audit import (
    CHAIN_ABLATION_SETTINGS,
    write_ablation_audit_report,
    write_ablation_delta_audits,
)
from episoa.evaluation.metrics import (
    filter_predictions_to_gold_events,
    match_tuples,
    opinion_recall,
    semantic_tuple_f1,
    soft_tuple_f1,
    tuple_match_threshold_sweep,
    tuple_pair_score,
)
from episoa.graph.evidence_graph import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    build_event_soa_graph,
    build_stakeholder_event_evidence_graph,
    write_evidence_graph,
)
from episoa.llm.client import OpenAICompatibleClient
from episoa.retrieval.event_chain_retriever import retrieve_event_chains
from episoa.verifier.faithfulness_verifier import verify_tuples
from episoa.verification.faithfulness_verifier import chain_stages_by_event


def _create_llm_client(config) -> OpenAICompatibleClient:
    """Build an LLM client from config.model dict, resolving api_key/base_url via env vars."""
    resolved = resolve_api_config(config.model, label="model")
    return OpenAICompatibleClient(
        api_key=resolved["api_key"],
        base_url=resolved["base_url"],
        model_name=config.model.get("llm_model", "gpt-5.5"),
        temperature=config.model.get("temperature", 0.1),
        max_tokens=config.model.get("max_tokens", 3000),
        timeout_seconds=config.model.get("timeout_seconds", 60),
        max_retries=config.model.get("max_retries", 2),
    )


def _resolved_model_status(config) -> dict[str, object]:
    resolved = resolve_api_config(config.model, label="model")
    return {
        "provider": str(config.model.get("provider", "openai_compatible")),
        "model_name": str(config.model.get("llm_model", "unknown")),
        "base_url": str(resolved["base_url"]),
        "base_url_source": str(resolved["base_url_source"]),
        "base_url_env": str(config.model.get("base_url_env", "")),
        "temperature": config.model.get("temperature", 0.1),
        "max_tokens": config.model.get("max_tokens", 3000),
    }


def _get_git_commit() -> str:
    """Return current git HEAD commit hash, or 'unknown' on failure."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _validate_pipeline_data(config) -> dict:
    """Validate configured pipeline inputs while preserving the legacy default gate."""
    validation = validate_paper_data()
    if validation["paper_data_ready"]:
        return validation

    configured = _validate_configured_data_paths(config)
    if configured["paper_data_ready"]:
        return configured
    return validation


def _validate_configured_data_paths(config) -> dict:
    required_keys = {
        "events": "events_path",
        "evidence": "evidence_path",
        "gold_tuples": "gold_tuples_path",
        "gold_event_chains": "gold_event_chains_path",
    }
    errors: list[str] = []
    records: dict[str, list[dict]] = {}

    for name, key in required_keys.items():
        raw_path = config.data.get(key)
        if not raw_path:
            errors.append(f"missing config data path: data.{key}")
            records[name] = []
            continue
        path = Path(raw_path)
        if not path.exists():
            errors.append(f"missing required data file: {path}")
            records[name] = []
            continue
        try:
            records[name] = read_jsonl(path)
        except ValueError as exc:
            errors.append(str(exc))
            records[name] = []
        if not records[name]:
            errors.append(f"{path} is empty")

    raw_posts = []
    raw_posts_path = config.data.get("raw_posts_path")
    if raw_posts_path and Path(raw_posts_path).exists():
        raw_posts = read_jsonl(Path(raw_posts_path))

    events = records.get("events", [])
    for index, event in enumerate(events, start=1):
        errors.extend(validate_formal_event_record(event, f"events:{index}"))

    return {
        "paper_data_ready": not errors,
        "dataset": {
            "is_formal_dataset": not errors,
            "num_events": len(events),
            "num_raw_posts": len(raw_posts),
            "num_evidence": len(records.get("evidence", [])),
            "num_gold_tuples": len(records.get("gold_tuples", [])),
            "num_gold_event_chains": len(records.get("gold_event_chains", [])),
            "errors": errors,
            "warnings": [],
            "source": "configured_data_paths",
        },
    }


def _write_input_manifest(
    setting_dir: Path,
    *,
    run_id: str,
    timestamp: str,
    git_commit: str,
    setting: str,
    config,
    events_count: int,
    evidence_count: int,
    gold_count: int,
    flags: dict[str, object],
    mode: str = "ablation",
    diagnostic_only: bool = False,
    runtime_options: dict[str, object] | None = None,
) -> None:
    manifest = {
        "run_id": run_id,
        "timestamp": timestamp,
        "git_commit": git_commit,
        "setting": setting,
        "mode": mode,
        "model": _resolved_model_status(config),
        "data": {
            "events_path": config.data.get("events_path", ""),
            "evidence_path": config.data.get("evidence_path", ""),
            "gold_tuples_path": config.data.get("gold_tuples_path", ""),
            "gold_event_chains_path": config.data.get("gold_event_chains_path", ""),
            "num_events": events_count,
            "num_evidence": evidence_count,
            "num_gold_tuples": gold_count,
        },
        "flags": flags,
        "diagnostic_only": bool(diagnostic_only),
        "runtime_options": runtime_options or {},
    }
    (setting_dir / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_prompt_manifest(setting_dir: Path, config, flags: dict | None = None) -> None:
    flags = flags or {}
    manifest = {
        "prompt_version": PROMPT_VERSION,
        "method_version": flags.get("method_version", config.ablation.get("method_version", "legacy")),
        "attribution_mode": ATTRIBUTION_MODE,
        "tuple_limit_policy": "none",
        "max_tuples_per_event_deprecated_noop": int(flags.get("max_tuples_per_event", config.ablation.get("max_tuples_per_event", MAX_TUPLES_PER_EVENT))),
        "max_opinion_chars": MAX_OPINION_CHARS,
        "max_rationale_chars": MAX_RATIONALE_CHARS,
        "allowed_sentiment": sorted(ALLOWED_SENTIMENT),
        "allowed_support": sorted(ALLOWED_SUPPORT),
        "verifier_threshold": float(config.verifier.get("threshold", 0.75)),
        "verifier_mode": flags.get("verifier_mode", config.verifier.get("mode", "decomposed")),
        "evidence_selector_mode": flags.get("selector_mode", (config.ablation.get("evidence_selector", {}) or {}).get("mode", "chain_aware")),
        "max_evidence_per_event": int(flags.get("max_evidence_per_event", config.ablation.get("max_evidence_per_event", 12))),
        "retrieval_top_k": int(config.retrieval.get("top_k", 5)),
    }
    (setting_dir / "prompt_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_event_level_csv(path: Path, gold, predictions) -> None:
    """Write per-event soft-match metrics as CSV."""
    gold_by_event: dict[str, list] = defaultdict(list)
    pred_by_event: dict[str, list] = defaultdict(list)
    for g in gold:
        gold_by_event[g.event_id].append(g)
    for p in predictions:
        if p.event_id in gold_by_event:
            pred_by_event[p.event_id].append(p)

    all_event_ids = sorted(gold_by_event)
    fieldnames = [
        "event_id", "precision", "recall", "f1", "tp",
        "num_gold", "num_pred", "sentiment_acc", "semantic_f1", "opinion_recall",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for event_id in all_event_ids:
            gt = gold_by_event.get(event_id, [])
            pt = pred_by_event.get(event_id, [])
            soft = soft_tuple_f1(gt, pt, threshold=0.5)
            semantic = semantic_tuple_f1(gt, pt, threshold=0.5)
            writer.writerow({
                "event_id": event_id,
                "precision": soft["precision"],
                "recall": soft["recall"],
                "f1": soft["f1"],
                "tp": soft["true_positives"],
                "num_gold": len(gt),
                "num_pred": len(pt),
                "sentiment_acc": soft["sentiment_accuracy"],
                "semantic_f1": semantic["f1"],
                "opinion_recall": opinion_recall(gt, pt),
            })


def _write_excluded_predictions_csv(path: Path, gold, predictions) -> dict[str, object]:
    _scored, excluded, excluded_event_ids = filter_predictions_to_gold_events(gold, predictions)
    fieldnames = ["event_id", "tuple_id", "stakeholder", "opinion", "sentiment", "exclusion_reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in excluded:
            writer.writerow(
                {
                    "event_id": getattr(row, "event_id", ""),
                    "tuple_id": getattr(row, "tuple_id", ""),
                    "stakeholder": getattr(row, "stakeholder", ""),
                    "opinion": getattr(row, "opinion", ""),
                    "sentiment": getattr(row, "sentiment", ""),
                    "exclusion_reason": "heldout_no_gold",
                }
            )
    return {
        "excluded_prediction_count": len(excluded),
        "excluded_event_ids": excluded_event_ids,
    }


def _write_threshold_sensitivity_csv(path: Path, gold, predictions) -> None:
    scored, _excluded, _excluded_event_ids = filter_predictions_to_gold_events(gold, predictions)
    rows = tuple_match_threshold_sweep(gold, scored)
    fieldnames = ["matcher", "threshold", "precision", "recall", "f1", "true_positives"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_tuple_match_diagnostics_csv(path: Path, gold, predictions) -> None:
    scored, excluded, _excluded_event_ids = filter_predictions_to_gold_events(gold, predictions)
    match_result = match_tuples(gold, scored, matcher="char_jaccard", threshold=0.5)
    scored_by_event: dict[str, list] = defaultdict(list)
    for index, row in enumerate(scored):
        scored_by_event[str(row.event_id)].append((index, row))
    fieldnames = [
        "event_id",
        "row_type",
        "gold_index",
        "pred_index",
        "score",
        "stakeholder_sim",
        "opinion_sim",
        "gold_stakeholder",
        "pred_stakeholder",
        "gold_opinion",
        "pred_opinion",
        "gold_sentiment",
        "pred_sentiment",
        "failure_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for gold_index in match_result["unmatched_gold_indices"]:
            gold_row = gold[int(gold_index)]
            best_index, best_pred, score, field_scores = _best_same_event_candidate(gold_row, scored_by_event)
            writer.writerow(
                {
                    "event_id": gold_row.event_id,
                    "row_type": "unmatched_gold",
                    "gold_index": gold_index,
                    "pred_index": "" if best_index is None else best_index,
                    "score": round(score, 4),
                    "stakeholder_sim": round(field_scores.get("stakeholder", 0.0), 4),
                    "opinion_sim": round(field_scores.get("opinion", 0.0), 4),
                    "gold_stakeholder": gold_row.stakeholder,
                    "pred_stakeholder": "" if best_pred is None else best_pred.stakeholder,
                    "gold_opinion": gold_row.opinion,
                    "pred_opinion": "" if best_pred is None else best_pred.opinion,
                    "gold_sentiment": gold_row.sentiment,
                    "pred_sentiment": "" if best_pred is None else best_pred.sentiment,
                    "failure_reason": _tuple_failure_reason(gold_row, best_pred, field_scores),
                }
            )
        for pred_index in match_result["unmatched_pred_indices"]:
            pred = scored[int(pred_index)]
            writer.writerow(
                {
                    "event_id": pred.event_id,
                    "row_type": "unmatched_pred",
                    "gold_index": "",
                    "pred_index": pred_index,
                    "score": "",
                    "stakeholder_sim": "",
                    "opinion_sim": "",
                    "gold_stakeholder": "",
                    "pred_stakeholder": pred.stakeholder,
                    "gold_opinion": "",
                    "pred_opinion": pred.opinion,
                    "gold_sentiment": "",
                    "pred_sentiment": pred.sentiment,
                    "failure_reason": "unmatched_prediction",
                }
            )
        for pred in excluded:
            writer.writerow(
                {
                    "event_id": pred.event_id,
                    "row_type": "excluded_prediction",
                    "gold_index": "",
                    "pred_index": "",
                    "score": "",
                    "stakeholder_sim": "",
                    "opinion_sim": "",
                    "gold_stakeholder": "",
                    "pred_stakeholder": pred.stakeholder,
                    "gold_opinion": "",
                    "pred_opinion": pred.opinion,
                    "gold_sentiment": "",
                    "pred_sentiment": pred.sentiment,
                    "failure_reason": "heldout_no_gold",
                }
            )


def _best_same_event_candidate(gold_row: GoldTuple, scored_by_event: dict[str, list]) -> tuple[int | None, PredictionTuple | None, float, dict[str, float]]:
    best_index: int | None = None
    best_pred: PredictionTuple | None = None
    best_score = 0.0
    best_fields: dict[str, float] = {}
    for pred_index, pred in scored_by_event.get(str(gold_row.event_id), []):
        score, field_scores = tuple_pair_score(gold_row, pred, matcher="char_jaccard")
        if score > best_score:
            best_index = pred_index
            best_pred = pred
            best_score = score
            best_fields = field_scores
    return best_index, best_pred, best_score, best_fields


def _tuple_failure_reason(gold_row: GoldTuple, pred_row: PredictionTuple | None, field_scores: dict[str, float]) -> str:
    if pred_row is None:
        return "no_same_event_prediction"
    if field_scores.get("stakeholder", 0.0) < 0.5:
        return "stakeholder_mismatch"
    if gold_row.sentiment == "mixed" and pred_row.sentiment != "mixed":
        return "sentiment_schema_gap"
    if len(str(pred_row.opinion)) < min(40, len(str(gold_row.opinion)) / 2):
        return "opinion_too_short"
    if field_scores.get("opinion", 0.0) < 0.5:
        return "opinion_mismatch"
    return "below_threshold"


def _write_tuple_failure_audit_csv(path: Path, diagnostics_path: Path) -> None:
    counter: Counter[str] = Counter()
    if diagnostics_path.exists():
        with diagnostics_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                reason = str(row.get("failure_reason") or "").strip()
                if reason:
                    counter[reason] += 1
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["failure_reason", "count"])
        writer.writeheader()
        for reason, count in counter.most_common():
            writer.writerow({"failure_reason": reason, "count": count})


def _write_scoring_artifacts(run_dir: Path, gold, predictions) -> dict[str, object]:
    _write_event_level_csv(run_dir / "event_level_metrics.csv", gold, predictions)
    excluded_summary = _write_excluded_predictions_csv(run_dir / "excluded_predictions.csv", gold, predictions)
    _write_threshold_sensitivity_csv(run_dir / "metric_threshold_sensitivity.csv", gold, predictions)
    diagnostics_path = run_dir / "tuple_match_diagnostics.csv"
    _write_tuple_match_diagnostics_csv(diagnostics_path, gold, predictions)
    _write_tuple_failure_audit_csv(run_dir / "tuple_failure_audit.csv", diagnostics_path)
    return excluded_summary


def _run_core_pipeline(
    events,
    evidence,
    gold,
    gold_chains,
    config,
    run_dir,
    llm_client,
    use_graph,
    use_event_chain,
    use_verifier,
    hide_chain_in_prompt=False,
    skip_chain_ranking=False,
    oracle_evidence=False,
    use_soe_graph=False,
    selector_mode=None,
    verifier_mode="decomposed",
    method_version="legacy",
    max_tuples_per_event=None,
    max_evidence_per_event=None,
    enforce_candidate_constraints=None,
    use_stage_attribution=None,
    use_ner_extraction=False,
    use_event_level_safety_net=False,
    use_hybrid_refinement=False,
    use_verifier_quality_gate=False,
    cache_dir: str | Path | None = None,
    resume: bool = False,
    max_api_concurrency: int = 1,
    reuse_attribution_dir: str | Path | None = None,
    run_id: str | None = None,
    output_dir: str | Path | None = None,
    diagnostic_only: bool = False,
):
    """Run one pipeline variant. Returns (predictions, retrieval_metrics, verifier_metrics)."""
    run_dir = Path(output_dir or run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    phase_timings: list[dict[str, object]] = []

    def timed_phase(name: str, func):
        started = time.perf_counter()
        value = func()
        phase_timings.append({"phase": name, "elapsed_seconds": round(time.perf_counter() - started, 4)})
        return value

    collected = collect_evidence(events, evidence)

    if use_graph:
        graph = _load_or_build_graph(
            cache_dir=cache_dir,
            run_dir=run_dir,
            events=events,
            collected=collected,
            enabled=True,
            phase_timings=phase_timings,
        )
        graph_nodes = graph.node_records()
    else:
        write_evidence_graph(
            EvidenceGraph(
                nodes=[],
                edges=[],
                summary={
                    "graph_disabled": True,
                    "num_stakeholder_candidates": 0,
                    "num_stage_candidates": 0,
                    "num_nodes": 0,
                    "num_edges": 0,
                    "events_without_stakeholder": [event.event_id for event in events],
                },
            ),
            run_dir / "evidence_graph",
        )
        graph_nodes = []

    if use_event_chain:
        chains = _load_or_build_chains(
            cache_dir=cache_dir,
            run_dir=run_dir,
            events=events,
            collected=collected,
            top_k=int(config.retrieval.get("top_k", 5)),
            phase_timings=phase_timings,
        )
    else:
        chains = []

    model_name = config.model.get("llm_model", "gpt-5.5")
    selector_config = config.ablation.get("evidence_selector", {}) or {}
    configured_selector_mode = selector_config.get("mode") or config.ablation.get("evidence_selector_mode")
    selector_mode = selector_mode or configured_selector_mode or "chain_aware"
    if use_stage_attribution is None:
        use_stage_attribution = bool(use_soe_graph and method_version == SOE_V3_METHOD_VERSION)
    max_evidence_per_event = int(max_evidence_per_event or config.ablation.get("max_evidence_per_event", 12))
    max_tuples = int(max_tuples_per_event or config.ablation.get("max_tuples_per_event", MAX_TUPLES_PER_EVENT))
    oracle_evidence_ids_by_event = _oracle_evidence_ids_by_event(gold) if oracle_evidence else None
    if reuse_attribution_dir is not None:
        attribution_summary = _reuse_attribution_artifacts(Path(reuse_attribution_dir), run_dir)
    else:
        attribution_summary = timed_phase(
            "schema_attribution",
            lambda: run_schema_attribution(
                events=[e.model_dump() for e in events],
                evidence_rows=[e.model_dump() for e in collected],
                chains=chains,
                graph_nodes=graph_nodes,
                llm_client=llm_client,
                model_name=model_name,
                output_dir=run_dir,
                max_evidence_per_event=max_evidence_per_event,
                oracle_evidence_ids_by_event=oracle_evidence_ids_by_event,
                hide_chain_in_prompt=hide_chain_in_prompt,
                skip_chain_ranking=skip_chain_ranking,
                selector_mode=selector_mode,
                method_version=method_version,
                max_tuples_per_event=max_tuples,
                seed=int(config.ablation.get("seed", 42)),
                enforce_candidate_constraints=enforce_candidate_constraints,
                use_stage_attribution=use_stage_attribution,
                use_ner_extraction=use_ner_extraction,
                use_event_level_safety_net=use_event_level_safety_net,
                use_hybrid_refinement=use_hybrid_refinement,
                cache_dir=cache_dir,
                resume=resume,
                max_api_concurrency=max_api_concurrency,
            ),
        )
        assert_no_total_api_failure(attribution_summary, run_dir)

    candidates = _attribution_to_predictions(
        read_jsonl(run_dir / "candidate_soa_tuples.jsonl")
    )
    write_jsonl(run_dir / "candidate_soa_tuples.jsonl", candidates)
    if use_soe_graph and use_graph:
        soe_graph = build_event_soa_graph(
            [event.model_dump() for event in events],
            [item.model_dump() for item in collected],
            [candidate.model_dump() for candidate in candidates],
        )
        write_evidence_graph(soe_graph, run_dir / "soe_graph")

    if use_verifier:
        verified_all = verify_tuples(
            candidates,
            collected,
            float(config.verifier.get("threshold", 0.75)),
            llm_client=llm_client,
            mode=verifier_mode,
            cache_dir=cache_dir,
            max_api_concurrency=max_api_concurrency,
            chain_stages_by_event=chain_stages_by_event(chains),
        )
        verifier_metrics = evaluate_verifier(verified_all)
        verified, gate_summary = _apply_verifier_quality_gate(
            verified_all,
            enabled=bool(use_verifier_quality_gate and verifier_mode == "decomposed"),
        )
        write_jsonl(run_dir / "verifier_diagnostics_all.jsonl", verified_all)
        (run_dir / "verifier_quality_gate.json").write_text(
            json.dumps(gate_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    else:
        verified = candidates
        verifier_metrics = {"verifier_skipped": 1.0}

    write_jsonl(run_dir / "verified_soa_tuples.jsonl", verified)
    write_jsonl(run_dir / "predictions.jsonl", verified)

    retrieval_metrics = evaluate_retrieval([item.model_dump() for item in gold_chains], chains)
    _write_phase_timings(run_dir / "phase_timings.csv", phase_timings)
    _write_runtime_manifest(
        run_dir,
        {
            "run_id": run_id or run_dir.name,
            "diagnostic_only": bool(diagnostic_only),
            "resume": bool(resume),
            "cache_dir": str(cache_dir or ""),
            "max_api_concurrency": int(max_api_concurrency or 1),
            "reuse_attribution_dir": str(reuse_attribution_dir or ""),
            "attribution_cache": attribution_summary.get("cache", {}) if isinstance(attribution_summary, dict) else {},
        },
    )
    return verified, retrieval_metrics, verifier_metrics


def _load_or_build_graph(
    *,
    cache_dir: str | Path | None,
    run_dir: Path,
    events,
    collected,
    enabled: bool,
    phase_timings: list[dict[str, object]],
) -> EvidenceGraph:
    del enabled
    key = _phase_cache_key(
        "graph",
        {
            "events": [event.model_dump() for event in events],
            "evidence": [item.model_dump() for item in collected],
        },
    )
    cache_path = Path(cache_dir) / "graph" / f"{key}.json" if cache_dir is not None else None
    started = time.perf_counter()
    if cache_path is not None and cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            graph = _graph_from_cache_payload(payload)
            write_evidence_graph(graph, run_dir / "evidence_graph")
            phase_timings.append({"phase": "graph", "elapsed_seconds": round(time.perf_counter() - started, 4), "cache": "hit"})
            return graph
        except (OSError, ValueError, TypeError):
            pass
    graph = build_stakeholder_event_evidence_graph(
        [event.model_dump() for event in events],
        [item.model_dump() for item in collected],
    )
    write_evidence_graph(graph, run_dir / "evidence_graph")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(_graph_cache_payload(graph), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    phase_timings.append({"phase": "graph", "elapsed_seconds": round(time.perf_counter() - started, 4), "cache": "miss"})
    return graph


def _graph_cache_payload(graph: EvidenceGraph) -> dict[str, object]:
    return {
        "schema_version": 1,
        "nodes": graph.node_records(),
        "edges": graph.edge_records(),
        "summary": graph.summary,
    }


def _graph_from_cache_payload(payload: dict[str, object]) -> EvidenceGraph:
    nodes = []
    for row in payload.get("nodes", []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        attributes = row.get("attributes", {}) if isinstance(row.get("attributes"), dict) else {}
        nodes.append(
            GraphNode(
                node_id=str(row.get("node_id", "")),
                node_type=str(row.get("node_type", "")),
                label=str(attributes.get("label", "")),
                attributes=attributes,
            )
        )
    edges = []
    for row in payload.get("edges", []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        attributes = row.get("attributes", {}) if isinstance(row.get("attributes"), dict) else {}
        edges.append(
            GraphEdge(
                source=str(row.get("source_node_id", "")),
                target=str(row.get("target_node_id", "")),
                relation=str(row.get("edge_type", "")),
                evidence_id=attributes.get("evidence_id"),
                weight=float(row.get("weight", 1.0) or 1.0),
                attributes=attributes,
            )
        )
    return EvidenceGraph(nodes=nodes, edges=edges, summary=dict(payload.get("summary", {})))


def _load_or_build_chains(
    *,
    cache_dir: str | Path | None,
    run_dir: Path,
    events,
    collected,
    top_k: int,
    phase_timings: list[dict[str, object]],
) -> list[dict]:
    key = _phase_cache_key(
        "chains",
        {
            "top_k": top_k,
            "events": [event.model_dump() for event in events],
            "evidence": [item.model_dump() for item in collected],
        },
    )
    cache_path = Path(cache_dir) / "chains" / f"{key}.jsonl" if cache_dir is not None else None
    output_path = run_dir / "retrieved_event_chains.jsonl"
    started = time.perf_counter()
    if cache_path is not None and cache_path.exists():
        try:
            chains = read_jsonl(cache_path)
            write_jsonl(output_path, chains)
            phase_timings.append({"phase": "event_chains", "elapsed_seconds": round(time.perf_counter() - started, 4), "cache": "hit"})
            return chains
        except (OSError, ValueError):
            pass
    chains = retrieve_event_chains(events, collected, top_k)
    write_jsonl(output_path, chains)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(cache_path, chains)
    phase_timings.append({"phase": "event_chains", "elapsed_seconds": round(time.perf_counter() - started, 4), "cache": "miss"})
    return chains


def _phase_cache_key(phase: str, payload: dict[str, object]) -> str:
    encoded = json.dumps({"phase": phase, **payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reuse_attribution_artifacts(source_dir: Path, target_dir: Path) -> dict[str, object]:
    required = [
        "candidate_soa_tuples.jsonl",
        "stage_soa_candidates.jsonl",
        "raw_llm_responses.jsonl",
        "schema_attribution_table.csv",
        "stakeholder_candidate_scope.csv",
        "canonicalization_map.csv",
        "schema_attribution_summary.json",
        "progress.jsonl",
        "cache_manifest.json",
    ]
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in required:
        src = source_dir / name
        if src.exists():
            shutil.copyfile(src, target_dir / name)
    summary_path = target_dir / "schema_attribution_summary.json"
    summary = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
    summary["attribution_reused"] = True
    summary["reuse_source_dir"] = str(source_dir)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _write_phase_timings(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["phase", "elapsed_seconds", "cache"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_runtime_manifest(run_dir: Path, payload: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    (run_dir / "runtime_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_setting_resume_artifacts(
    setting_dir: Path,
    *,
    run_id: str,
    runtime_options: dict[str, object],
    phase: str,
    reuse_info: dict[str, object] | None = None,
) -> None:
    """Record diagnostics when a setting is satisfied without running core phases."""
    cache_dir = Path(str(runtime_options.get("cache_dir") or _default_cache_dir(None)))
    _write_phase_timings(
        setting_dir / "phase_timings.csv",
        [{"phase": phase, "elapsed_seconds": 0.0, "cache": "hit"}],
    )
    cache_manifest = {
        "cache_dir": str(cache_dir),
        "resume": bool(runtime_options.get("resume", False)),
        "cache": {
            "hits": 1,
            "misses": 0,
            "resume_hits": 1 if phase == "setting_resume" else 0,
            "invalid": 0,
        },
        "max_api_concurrency": int(runtime_options.get("max_api_concurrency") or 1),
        "setting_cache": {"phase": phase, **(reuse_info or {})},
    }
    (setting_dir / "cache_manifest.json").write_text(
        json.dumps(cache_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_runtime_manifest(
        setting_dir,
        {
            "run_id": run_id,
            "diagnostic_only": bool(runtime_options.get("diagnostic_only", False)),
            "resume": bool(runtime_options.get("resume", False)),
            "cache_dir": str(cache_dir),
            "max_api_concurrency": int(runtime_options.get("max_api_concurrency") or 1),
            "setting_cache": {"phase": phase, **(reuse_info or {})},
        },
    )


def _default_cache_dir(cache_dir: str | Path | None) -> Path:
    return Path(cache_dir) if cache_dir is not None else Path("outputs/cache/pipeline")


def _resolve_runtime_options(
    config,
    *,
    resume: bool | None,
    max_api_concurrency: int | None,
    cache_dir: str | Path | None,
    diagnostic: bool | None,
    max_events: int | None,
    event_ids: list[str] | None,
    skip_llm_verifier: bool | None,
) -> dict[str, object]:
    runtime = dict(getattr(config, "runtime", {}) or {})
    resolved_max_events = max_events if max_events is not None else runtime.get("max_events")
    return {
        "resume": bool(runtime.get("resume", False) if resume is None else resume),
        "max_api_concurrency": max(1, int(max_api_concurrency if max_api_concurrency is not None else runtime.get("max_api_concurrency", 4))),
        "cache_dir": _default_cache_dir(cache_dir if cache_dir is not None else runtime.get("cache_dir")),
        "diagnostic": bool(runtime.get("diagnostic", False) if diagnostic is None else diagnostic),
        "max_events": None if resolved_max_events is None else int(resolved_max_events),
        "event_ids": _normalize_id_list(event_ids if event_ids is not None else runtime.get("event_ids")),
        "skip_llm_verifier": bool(runtime.get("skip_llm_verifier", False) if skip_llm_verifier is None else skip_llm_verifier),
    }


def _normalize_id_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value if str(item)]


def _diagnostic_run_dir(path: Path) -> Path:
    return path.with_name(path.name + "_diagnostic")


def _filter_events(events, *, event_ids: list[str] | None = None, max_events: int | None = None) -> list:
    selected = list(events)
    if event_ids:
        wanted = {str(event_id) for event_id in event_ids}
        selected = [
            event
            for event in selected
            if str(getattr(event, "event_id", event.get("event_id") if isinstance(event, dict) else "")) in wanted
        ]
    if max_events is not None:
        selected = selected[: max(0, int(max_events))]
    return selected


ATTRIBUTION_FINGERPRINT_KEYS = (
    "use_graph",
    "use_event_chain",
    "hide_chain_in_prompt",
    "skip_chain_ranking",
    "oracle_evidence",
    "use_soe_graph",
    "selector_mode",
    "method_version",
    "max_tuples_per_event",
    "max_evidence_per_event",
    "enforce_candidate_constraints",
    "use_stage_attribution",
    "use_ner_extraction",
    "use_event_level_safety_net",
    "use_hybrid_refinement",
)


def _attribution_fingerprint(flags: dict[str, object]) -> str:
    payload = {key: flags.get(key) for key in ATTRIBUTION_FINGERPRINT_KEYS if key in flags}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _setting_fingerprint(flags: dict[str, object]) -> str:
    payload = {key: flags.get(key) for key in sorted(PIPELINE_FLAG_KEYS) if key in flags}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _attribution_reuse_source(setting: str, completed_setting_dirs: dict[str, Path]) -> str | None:
    if setting == "without_decomposed_verifier" and "full_soe" in completed_setting_dirs:
        return "full_soe"
    return None


def _write_reuse_manifest(
    setting_dir: Path,
    *,
    setting: str,
    source_setting: str,
    source_dir: Path,
    reason: str,
) -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "setting": setting,
        "reuse_source_setting": source_setting,
        "reuse_source_dir": str(source_dir),
        "reason": reason,
    }
    (setting_dir / "reuse_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _copy_setting_artifacts(source_dir: Path, target_dir: Path) -> None:
    excluded = {"config_snapshot.yaml", "input_manifest.json", "prompt_manifest.json", "reuse_manifest.json"}
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.iterdir():
        if source.name in excluded:
            continue
        target = target_dir / source.name
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)


def _load_setting_resume(
    setting_dir: Path,
    *,
    setting: str,
    flags: dict[str, object],
    diagnostic_only: bool,
) -> tuple[list[PredictionTuple], dict[str, object]] | None:
    required = [
        "metrics.json",
        "verified_soa_tuples.jsonl",
        "candidate_soa_tuples.jsonl",
        "scoring_scope.json",
        "metric_threshold_sensitivity.csv",
        "tuple_failure_audit.csv",
        "input_manifest.json",
        "schema_attribution_summary.json",
    ]
    if any(not (setting_dir / name).exists() for name in required):
        return None
    try:
        manifest = json.loads((setting_dir / "input_manifest.json").read_text(encoding="utf-8"))
        summary = json.loads((setting_dir / "schema_attribution_summary.json").read_text(encoding="utf-8"))
        metrics = json.loads((setting_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("setting") != setting:
        return None
    if bool(manifest.get("diagnostic_only", False)) != bool(diagnostic_only):
        return None
    manifest_flags = manifest.get("flags", {}) if isinstance(manifest.get("flags"), dict) else {}
    if _setting_fingerprint(manifest_flags) != _setting_fingerprint(flags):
        return None
    if _setting_attribution_failed(summary):
        return None
    try:
        verified = _attribution_to_predictions(read_jsonl(setting_dir / "verified_soa_tuples.jsonl"))
    except (OSError, ValueError):
        return None
    return verified, metrics


def _setting_attribution_failed(summary: dict[str, object]) -> bool:
    api_calls = int(summary.get("num_api_calls", 0) or 0)
    tuples = int(summary.get("num_tuples_generated", 0) or 0)
    requested = int(summary.get("num_events_requested", 0) or 0)
    skipped = int(summary.get("num_events_skipped", 0) or 0)
    parse_failed = summary.get("parse_failed_events", [])
    parse_failed_count = len(parse_failed) if isinstance(parse_failed, list) else 0
    prompted = max(0, requested - skipped)
    return api_calls > 0 and tuples == 0 and prompted > 0 and parse_failed_count >= prompted


def _oracle_evidence_ids_by_event(gold: list[GoldTuple]) -> dict[str, list[str]]:
    """Return ordered gold evidence IDs without exposing gold tuple text.

    The first pass keeps one unseen evidence item per tuple where possible, so
    truncation still covers more distinct tuple supports.
    """
    grouped: dict[str, list[GoldTuple]] = defaultdict(list)
    for row in gold:
        grouped[str(row.event_id)].append(row)

    output: dict[str, list[str]] = {}
    for event_id, rows in grouped.items():
        seen: set[str] = set()
        ordered: list[str] = []
        for row in rows:
            for evidence_id in row.evidence_ids:
                evidence_id = str(evidence_id)
                if evidence_id and evidence_id not in seen:
                    seen.add(evidence_id)
                    ordered.append(evidence_id)
                    break
        for row in rows:
            for evidence_id in row.evidence_ids:
                evidence_id = str(evidence_id)
                if evidence_id and evidence_id not in seen:
                    seen.add(evidence_id)
                    ordered.append(evidence_id)
        output[event_id] = ordered
    return output


def run_paper_pipeline(
    config_path: str | Path,
    *,
    resume: bool | None = None,
    max_api_concurrency: int | None = None,
    cache_dir: str | Path | None = None,
    diagnostic: bool | None = None,
    max_events: int | None = None,
    event_ids: list[str] | None = None,
    skip_llm_verifier: bool | None = None,
) -> dict:
    config = load_config(config_path)
    print_api_config_status(config)
    validation = _validate_pipeline_data(config)
    runtime = _resolve_runtime_options(
        config,
        resume=resume,
        max_api_concurrency=max_api_concurrency,
        cache_dir=cache_dir,
        diagnostic=diagnostic,
        max_events=max_events,
        event_ids=event_ids,
        skip_llm_verifier=skip_llm_verifier,
    )
    run_dir = _diagnostic_run_dir(config.run_dir) if runtime["diagnostic"] else config.run_dir
    if not validation["paper_data_ready"]:
        return {
            "status": "blocked",
            "reason": "paper data is not ready",
            "validation": validation,
        }

    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, run_dir / "config.yaml")

    events = read_typed_jsonl(config.data["events_path"], EventRecord)
    evidence = read_typed_jsonl(config.data["evidence_path"], EvidenceRecord)
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)
    gold_chains = read_typed_jsonl(config.data["gold_event_chains_path"], GoldEventChain)
    events = _filter_events(
        events,
        event_ids=runtime["event_ids"],
        max_events=runtime["max_events"],
    )

    llm_client = _create_llm_client(config)
    effective_cache_dir = Path(runtime["cache_dir"])
    paper_flags = {
        "use_graph": True,
        "use_event_chain": True,
        "use_verifier": True,
        "hide_chain_in_prompt": False,
        "skip_chain_ranking": False,
        "use_soe_graph": True,
        "selector_mode": "coverage_optimized",
        "verifier_mode": "id_only" if runtime["skip_llm_verifier"] else "decomposed",
        "method_version": SOE_V3_METHOD_VERSION,
        "use_stage_attribution": True,
        "use_event_level_safety_net": True,
        "use_hybrid_refinement": True,
        "use_verifier_quality_gate": True,
    }
    timestamp = datetime.now(timezone.utc).isoformat()
    git_commit = _get_git_commit()
    shutil.copyfile(config_path, run_dir / "config_snapshot.yaml")
    _write_input_manifest(
        run_dir,
        run_id=config.run_id,
        timestamp=timestamp,
        git_commit=git_commit,
        setting="paper_main",
        config=config,
        events_count=len(events),
        evidence_count=len(evidence),
        gold_count=len(gold),
        flags=paper_flags,
        mode="paper",
        diagnostic_only=bool(runtime["diagnostic"]),
        runtime_options={
            "resume": bool(runtime["resume"]),
            "max_api_concurrency": int(runtime["max_api_concurrency"]),
            "cache_dir": str(effective_cache_dir),
            "diagnostic_only": bool(runtime["diagnostic"]),
            "max_events": runtime["max_events"],
            "event_ids": runtime["event_ids"],
            "skip_llm_verifier": bool(runtime["skip_llm_verifier"]),
        },
    )
    _write_prompt_manifest(run_dir, config, paper_flags)

    verified, retrieval_metrics, verifier_metrics = _run_core_pipeline(
        events, evidence, gold, gold_chains, config, run_dir, llm_client,
        **paper_flags,
        cache_dir=effective_cache_dir,
        resume=bool(runtime["resume"]),
        max_api_concurrency=int(runtime["max_api_concurrency"]),
        run_id=config.run_id,
        diagnostic_only=bool(runtime["diagnostic"]),
    )

    metrics = evaluate_main(gold, verified)
    scoring_scope = _write_scoring_artifacts(run_dir, gold, verified)
    (run_dir / "scoring_scope.json").write_text(
        json.dumps(scoring_scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(run_dir / "main_results.csv", "Method", "EpiSOA", metrics)
    _write_csv(run_dir / "retrieval_results.csv", "Method", "EpiSOA", retrieval_metrics)
    _write_csv(run_dir / "verifier_results.csv", "Method", "EpiSOA", verifier_metrics)
    write_jsonl(run_dir / "case_studies.jsonl", [item.model_dump() for item in verified[:3]])

    summary = {
        "status": "completed",
        "diagnostic_only": bool(runtime["diagnostic"]),
        "resume": bool(runtime["resume"]),
        "run_dir": str(run_dir),
        "cache_dir": str(effective_cache_dir),
        "max_api_concurrency": int(runtime["max_api_concurrency"]),
        "max_events": runtime["max_events"],
        "event_ids": runtime["event_ids"],
        "skip_llm_verifier": bool(runtime["skip_llm_verifier"]),
        "num_events": len(events),
        "num_evidence": len(evidence),
        "num_predictions": len(verified),
        "metrics": metrics,
        "scoring_scope": scoring_scope,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _map_support_label(raw: str) -> str:
    """Map schema-attribution support_status to valid PredictionTuple support_label."""
    label = (raw or "candidate_unclear").replace("candidate_", "")
    if label == "unclear":
        return "insufficient_evidence"
    return label


def _attribution_to_predictions(attribution_results: list[dict]) -> list[PredictionTuple]:
    """Convert schema attribution output to PredictionTuple format."""
    predictions: list[PredictionTuple] = []
    for row in attribution_results:
        predictions.append(
            PredictionTuple(
                event_id=row.get("event_id", ""),
                tuple_id=row.get("tuple_id", ""),
                stakeholder=row.get("stakeholder", ""),
                opinion=row.get("opinion", ""),
                sentiment=row.get("sentiment", "unknown"),
                rationale=row.get("rationale", ""),
                evidence_ids=row.get("evidence_ids", []),
                evidence_spans=row.get("evidence_spans", []),
                event_chain_stage=row.get("event_chain_stage", "unknown"),
                stage_id=row.get("stage_id"),
                stakeholder_id=row.get("stakeholder_id"),
                opinion_id=row.get("opinion_id"),
                support_label=_map_support_label(row.get("support_status", "candidate_unclear")),
                support_score=row.get("confidence", 0.5),
                verified=False,
                confidence=row.get("confidence", 0.0),
                support_status=row.get("support_status", ""),
                selection_diagnostics=row.get("selection_diagnostics"),
                stakeholder_cluster_id=row.get("stakeholder_cluster_id"),
                stakeholder_aliases=row.get("stakeholder_aliases", []),
                canonical_tuple=row.get("canonical_tuple", True),
                opinion_split_reason=row.get("opinion_split_reason", ""),
                stakeholder_candidate_match_status=row.get("stakeholder_candidate_match_status", ""),
                matched_stakeholder_candidate=row.get("matched_stakeholder_candidate", ""),
                stage_candidate_ids=row.get("stage_candidate_ids", []),
                attribution_pass=row.get("attribution_pass", ""),
            )
        )
    return predictions


def _apply_verifier_quality_gate(
    predictions: list[PredictionTuple],
    *,
    enabled: bool,
) -> tuple[list[PredictionTuple], dict[str, int | bool]]:
    if enabled:
        kept = [row for row in predictions if row.verified]
    else:
        kept = list(predictions)
    return kept, {
        "verifier_quality_gate_enabled": bool(enabled),
        "num_before_quality_gate": len(predictions),
        "num_after_quality_gate": len(kept),
        "num_removed_by_quality_gate": len(predictions) - len(kept),
    }


ABLATION_SETTINGS = {
    "full_soe":                       {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "use_soe_graph": True,  "use_stage_attribution": True,  "use_event_level_safety_net": True,  "use_hybrid_refinement": True,  "use_verifier_quality_gate": True,  "selector_mode": "coverage_optimized", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "full_soe_high_recall":           {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "use_soe_graph": True,  "use_stage_attribution": True,  "use_event_level_safety_net": True,  "use_hybrid_refinement": True,  "use_verifier_quality_gate": True,  "selector_mode": "coverage_optimized", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8, "max_evidence_per_event": 60},
    "full_oracle_evidence":            {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "oracle_evidence": True, "selector_mode": "oracle", "verifier_mode": "decomposed"},
    "oracle_evidence":                 {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "oracle_evidence": True, "use_soe_graph": True, "use_stage_attribution": True, "use_event_level_safety_net": True, "use_hybrid_refinement": True, "use_verifier_quality_gate": True, "selector_mode": "oracle", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "direct_llm":                      {"use_graph": False, "use_event_chain": False, "use_verifier": True,  "hide_chain_in_prompt": True,  "skip_chain_ranking": True,  "use_verifier_quality_gate": True, "selector_mode": "quality_topk", "verifier_mode": "decomposed", "method_version": "direct_llm"},
    "without_soe_graph":               {"use_graph": False, "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "use_soe_graph": False, "use_stage_attribution": True,  "use_event_level_safety_net": True,  "use_hybrid_refinement": True,  "use_verifier_quality_gate": True,  "selector_mode": "coverage_optimized", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "without_chain_aware_selection":   {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": True, "use_soe_graph": True, "use_stage_attribution": True, "use_event_level_safety_net": True, "use_hybrid_refinement": True, "use_verifier_quality_gate": True, "selector_mode": "quality_topk", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "quality_topk_selector":          {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": True, "use_soe_graph": True, "use_stage_attribution": True, "use_event_level_safety_net": True, "use_hybrid_refinement": True, "use_verifier_quality_gate": True, "selector_mode": "quality_topk", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "bm25_selector":                   {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": True, "use_soe_graph": True, "use_stage_attribution": True, "use_event_level_safety_net": True, "use_hybrid_refinement": True, "use_verifier_quality_gate": True, "selector_mode": "bm25_keyword", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "random_selector":                 {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": True, "use_soe_graph": True, "use_stage_attribution": True, "use_event_level_safety_net": True, "use_hybrid_refinement": True, "use_verifier_quality_gate": True, "selector_mode": "random", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "without_decomposed_verifier":     {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "use_soe_graph": True,  "use_stage_attribution": True,  "use_event_level_safety_net": True,  "use_hybrid_refinement": True,  "use_verifier_quality_gate": False, "selector_mode": "coverage_optimized", "verifier_mode": "id_only", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "without_graph":                   {"use_graph": False, "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "use_soe_graph": False, "use_stage_attribution": False, "selector_mode": "coverage_optimized", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "without_event_chain":             {"use_graph": True,  "use_event_chain": False, "use_verifier": True,  "hide_chain_in_prompt": True,  "skip_chain_ranking": True, "use_soe_graph": False, "use_stage_attribution": False, "selector_mode": "quality_topk", "verifier_mode": "decomposed", "method_version": "soe_v3", "max_tuples_per_event": 8},
    "without_verifier":                {"use_graph": True,  "use_event_chain": True,  "use_verifier": False, "hide_chain_in_prompt": False, "skip_chain_ranking": False, "use_soe_graph": True, "use_stage_attribution": True, "selector_mode": "coverage_optimized", "verifier_mode": "id_only", "method_version": "soe_v3", "max_tuples_per_event": 8},
}

PIPELINE_FLAG_KEYS = {
    "use_graph",
    "use_event_chain",
    "use_verifier",
    "hide_chain_in_prompt",
    "skip_chain_ranking",
    "oracle_evidence",
    "use_soe_graph",
    "use_stage_attribution",
    "use_event_level_safety_net",
    "use_hybrid_refinement",
    "use_verifier_quality_gate",
    "selector_mode",
    "verifier_mode",
    "method_version",
    "max_tuples_per_event",
    "max_evidence_per_event",
    "enforce_candidate_constraints",
    "use_ner_extraction",
}


def run_ablation_pipeline(
    config_path: str | Path,
    force: bool = False,
    *,
    resume: bool | None = None,
    max_api_concurrency: int | None = None,
    cache_dir: str | Path | None = None,
    diagnostic: bool | None = None,
    max_events: int | None = None,
    event_ids: list[str] | None = None,
    settings: list[str] | None = None,
    skip_llm_verifier: bool | None = None,
) -> dict:
    """Run ablation experiments for every setting in config.ablation.settings.

    Each setting runs the full pipeline independently in its own output directory
    under the configured runs directory as ablation_{setting}/. With resume enabled,
    complete healthy setting outputs and equivalent-setting artifacts may be reused.

    When force=True, existing setting directories are removed before running.
    """
    config = load_config(config_path)
    print_api_config_status(config)
    validation = _validate_pipeline_data(config)
    if not validation["paper_data_ready"]:
        return {"status": "blocked", "reason": "paper data is not ready", "validation": validation}

    runtime = _resolve_runtime_options(
        config,
        resume=resume,
        max_api_concurrency=max_api_concurrency,
        cache_dir=cache_dir,
        diagnostic=diagnostic,
        max_events=max_events,
        event_ids=event_ids,
        skip_llm_verifier=skip_llm_verifier,
    )
    configured_runs_dir = Path(config.output.get("runs_dir", "outputs/runs"))
    runs_dir = _diagnostic_run_dir(configured_runs_dir) if runtime["diagnostic"] else configured_runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)

    events = read_typed_jsonl(config.data["events_path"], EventRecord)
    evidence = read_typed_jsonl(config.data["evidence_path"], EvidenceRecord)
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)
    gold_chains = read_typed_jsonl(config.data["gold_event_chains_path"], GoldEventChain)
    events = _filter_events(
        events,
        event_ids=runtime["event_ids"],
        max_events=runtime["max_events"],
    )

    llm_client = _create_llm_client(config)
    timestamp = datetime.now(timezone.utc).isoformat()
    git_commit = _get_git_commit()
    effective_cache_dir = Path(runtime["cache_dir"])
    runtime_options = {
        "resume": bool(runtime["resume"]),
        "max_api_concurrency": int(runtime["max_api_concurrency"]),
        "cache_dir": str(effective_cache_dir),
        "diagnostic_only": bool(runtime["diagnostic"]),
        "max_events": runtime["max_events"],
        "event_ids": runtime["event_ids"],
        "skip_llm_verifier": bool(runtime["skip_llm_verifier"]),
    }

    all_metrics: dict[str, dict[str, float]] = {}
    selected_settings = _normalize_id_list(settings if settings is not None else config.ablation.get("settings", list(ABLATION_SETTINGS)))
    completed_setting_dirs: dict[str, Path] = {}
    completed_attribution_fingerprints: dict[str, str] = {}
    completed_setting_fingerprints: dict[str, str] = {}
    reuse: dict[str, dict[str, object]] = {}
    _write_runtime_manifest(
        runs_dir,
        {
            "run_id": "ablation",
            "diagnostic_only": bool(runtime["diagnostic"]),
            "resume": bool(runtime["resume"]),
            "cache_dir": str(effective_cache_dir),
            "max_api_concurrency": int(runtime["max_api_concurrency"]),
            "max_events": runtime["max_events"],
            "event_ids": runtime["event_ids"],
            "settings": selected_settings,
        },
    )

    for setting in selected_settings:
        flags = dict(ABLATION_SETTINGS.get(setting) or {})
        if flags is None:
            print(f"  [SKIP] unknown ablation setting: {setting}")
            continue
        if not flags:
            print(f"  [SKIP] unknown ablation setting: {setting}")
            continue
        if runtime["skip_llm_verifier"]:
            flags["verifier_mode"] = "id_only"
            flags["use_verifier_quality_gate"] = False

        setting_dir = runs_dir / f"ablation_{setting}"
        attribution_fingerprint = _attribution_fingerprint(flags)
        setting_fingerprint = _setting_fingerprint(flags)

        if force:
            if setting_dir.exists():
                shutil.rmtree(setting_dir)
                print(f"  [FORCE] removed {setting_dir}")

        setting_dir.mkdir(parents=True, exist_ok=True)

        current_manifests_written = False

        def write_current_manifests() -> None:
            nonlocal current_manifests_written
            if current_manifests_written:
                return
            shutil.copyfile(config_path, setting_dir / "config_snapshot.yaml")
            _write_input_manifest(
                setting_dir,
                run_id=f"ablation_{setting}",
                timestamp=timestamp,
                git_commit=git_commit,
                setting=setting,
                config=config,
                events_count=len(events),
                evidence_count=len(evidence),
                gold_count=len(gold),
                flags=flags,
                diagnostic_only=bool(runtime["diagnostic"]),
                runtime_options=runtime_options,
            )
            _write_prompt_manifest(setting_dir, config, flags)
            current_manifests_written = True

        setting_reuse_source = completed_setting_fingerprints.get(setting_fingerprint)
        setting_reuse_dir = completed_setting_dirs.get(setting_reuse_source) if setting_reuse_source else None
        if setting_reuse_source and setting_reuse_dir is not None:
            _copy_setting_artifacts(setting_reuse_dir, setting_dir)
            write_current_manifests()
            reuse[setting] = _write_reuse_manifest(
                setting_dir,
                setting=setting,
                source_setting=setting_reuse_source,
                source_dir=setting_reuse_dir,
                reason="same_setting_fingerprint",
            )
            reuse[setting]["source_setting"] = setting_reuse_source
            reuse[setting]["reason"] = "same_setting_fingerprint"
            loaded = _load_setting_resume(
                setting_dir,
                setting=setting,
                flags=flags,
                diagnostic_only=bool(runtime["diagnostic"]),
            )
            if loaded is not None:
                verified, metrics = loaded
                all_metrics[setting] = metrics
                completed_setting_dirs[setting] = setting_dir
                completed_attribution_fingerprints.setdefault(attribution_fingerprint, setting)
                completed_setting_fingerprints.setdefault(setting_fingerprint, setting)
                _write_setting_resume_artifacts(
                    setting_dir,
                    run_id=f"ablation_{setting}",
                    runtime_options=runtime_options,
                    phase="setting_reuse",
                    reuse_info={
                        "source_setting": setting_reuse_source,
                        "source_dir": str(setting_reuse_dir),
                        "reason": "same_setting_fingerprint",
                    },
                )
                _write_ablation_csv(runs_dir / "ablation_results.csv", all_metrics)
                print(f"  [REUSE] {setting} <- {setting_reuse_source}")
                continue

        if bool(runtime["resume"]) and not force:
            loaded = _load_setting_resume(
                setting_dir,
                setting=setting,
                flags=flags,
                diagnostic_only=bool(runtime["diagnostic"]),
            )
            if loaded is not None:
                verified, metrics = loaded
                all_metrics[setting] = metrics
                completed_setting_dirs[setting] = setting_dir
                completed_attribution_fingerprints.setdefault(attribution_fingerprint, setting)
                completed_setting_fingerprints.setdefault(setting_fingerprint, setting)
                _write_setting_resume_artifacts(
                    setting_dir,
                    run_id=f"ablation_{setting}",
                    runtime_options=runtime_options,
                    phase="setting_resume",
                )
                _write_ablation_csv(runs_dir / "ablation_results.csv", all_metrics)
                print(f"  [RESUME] {setting} <- {setting_dir}")
                continue

        reuse_source_setting = _attribution_reuse_source(setting, completed_setting_dirs)
        reuse_reason = "same_attribution_inputs_verifier_only_change"
        if reuse_source_setting is None:
            reuse_source_setting = completed_attribution_fingerprints.get(attribution_fingerprint)
            reuse_reason = "same_attribution_fingerprint"
        reuse_source_dir = completed_setting_dirs.get(reuse_source_setting) if reuse_source_setting else None
        if reuse_source_setting and reuse_source_dir is not None:
            write_current_manifests()
            reuse[setting] = _write_reuse_manifest(
                setting_dir,
                setting=setting,
                source_setting=reuse_source_setting,
                source_dir=reuse_source_dir,
                reason=reuse_reason,
            )
            reuse[setting]["source_setting"] = reuse_source_setting
            reuse[setting]["reason"] = reuse_reason

        write_current_manifests()
        print(f"  [RUN] {setting} → {setting_dir}")
        verified, _retrieval_metrics, _verifier_metrics = _run_core_pipeline(
            events, evidence, gold, gold_chains, config, setting_dir, llm_client,
            cache_dir=effective_cache_dir,
            resume=bool(runtime["resume"]),
            max_api_concurrency=int(runtime["max_api_concurrency"]),
            reuse_attribution_dir=reuse_source_dir,
            run_id=f"ablation_{setting}",
            output_dir=setting_dir,
            diagnostic_only=bool(runtime["diagnostic"]),
            **{key: value for key, value in flags.items() if key in PIPELINE_FLAG_KEYS},
        )

        metrics = evaluate_ablation(gold, verified, verifier_enabled=bool(flags["use_verifier"]))
        scoring_scope = _write_scoring_artifacts(setting_dir, gold, verified)
        all_metrics[setting] = metrics
        completed_setting_dirs[setting] = setting_dir
        completed_attribution_fingerprints.setdefault(attribution_fingerprint, setting)
        completed_setting_fingerprints.setdefault(setting_fingerprint, setting)

        (setting_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (setting_dir / "scoring_scope.json").write_text(
            json.dumps(scoring_scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_ablation_csv(runs_dir / "ablation_results.csv", all_metrics)

        print(f"  [{setting}] Tuple-F1-soft={metrics.get('Tuple-F1-soft', 'N/A')}, "
              f"Num-Tuples={metrics.get('Num-Tuples', 'N/A')}")

    # Aggregate only from the current run (never reads old cache)
    _write_ablation_csv(runs_dir / "ablation_results.csv", all_metrics)

    delta_paths = write_ablation_delta_audits(
        runs_dir=runs_dir,
        gold_tuples=gold,
        settings=[setting for setting in CHAIN_ABLATION_SETTINGS if setting in selected_settings],
    )
    audit_report_path = write_ablation_audit_report(
        runs_dir=runs_dir,
        settings=selected_settings,
        flags_by_setting={setting: ABLATION_SETTINGS.get(setting, {}) for setting in selected_settings},
    )

    summary = {
        "status": "completed",
        "run_id": "ablation",
        "timestamp": timestamp,
        "git_commit": git_commit,
        "force": force,
        "resume": bool(runtime["resume"]),
        "diagnostic_only": bool(runtime["diagnostic"]),
        "runs_dir": str(runs_dir),
        "cache_dir": str(effective_cache_dir),
        "max_api_concurrency": int(runtime["max_api_concurrency"]),
        "max_events": runtime["max_events"],
        "event_ids": runtime["event_ids"],
        "skip_llm_verifier": bool(runtime["skip_llm_verifier"]),
        "settings": list(all_metrics.keys()),
        "metrics": all_metrics,
        "reuse": reuse,
        "delta_audits": {setting: str(path) for setting, path in delta_paths.items()},
        "audit_report": str(audit_report_path),
    }
    (runs_dir / "ablation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print("=== Ablation Results ===")
    print((runs_dir / "ablation_results.csv").read_text(encoding="utf-8"))
    print()
    print(f"=== Delta Audit ===\n{runs_dir / 'ablation_delta'}")
    print(f"=== Audit Report ===\n{runs_dir / 'ablation_audit_report.md'}")
    return summary


def _write_event_level_deltas(runs_dir: Path, gold: list[GoldTuple], settings: list[str]) -> None:
    """Compute per-event deltas between 'full' and chain-prompt/chain-ranking settings.

    Outputs event_level_deltas.json and event_level_deltas.csv to runs_dir.
    """
    target_settings = [s for s in ("without_event_chain_prompt", "without_event_chain_ranking") if s in settings]
    if "full" not in settings or not target_settings:
        return

    def _load_setting_data(setting_name: str) -> dict:
        sd = runs_dir / f"ablation_{setting_name}"
        raw_path = sd / "raw_llm_responses.jsonl"
        tuples_path = sd / "candidate_soa_tuples.jsonl"
        raw_by_event: dict[str, dict] = {}
        if raw_path.exists():
            for rec in read_jsonl(raw_path):
                raw_by_event[str(rec.get("event_id", ""))] = rec
        tuples_by_event: dict[str, list[dict]] = defaultdict(list)
        if tuples_path.exists():
            for t in read_jsonl(tuples_path):
                tuples_by_event[str(t.get("event_id", ""))].append(t)
        return {"raw": raw_by_event, "tuples": tuples_by_event}

    def _count_matched_gold(gold_tuples: list, pred_tuples: list) -> int:
        if not gold_tuples or not pred_tuples:
            return 0
        soft = soft_tuple_f1(gold_tuples, pred_tuples, threshold=0.5)
        return int(soft.get("true_positives", 0))

    full_data = _load_setting_data("full")
    deltas: list[dict] = []

    for event_id, full_raw in full_data["raw"].items():
        full_eids = set(full_raw.get("request_summary", {}).get("selected_evidence_ids", []))
        full_chars = int(full_raw.get("request_summary", {}).get("prompt_chars", 0))
        gold_for_event = [g for g in gold if str(g.event_id) == event_id]
        full_tuples = full_data["tuples"].get(event_id, [])
        full_matched = _count_matched_gold(
            [g.model_dump() for g in gold_for_event], full_tuples
        )

        for setting_name in target_settings:
            sd = _load_setting_data(setting_name)
            setting_raw = sd["raw"].get(event_id)
            if setting_raw is None:
                continue
            setting_eids = set(setting_raw.get("request_summary", {}).get("selected_evidence_ids", []))
            setting_chars = int(setting_raw.get("request_summary", {}).get("prompt_chars", 0))
            setting_tuples = sd["tuples"].get(event_id, [])
            setting_matched = _count_matched_gold(
                [g.model_dump() for g in gold_for_event], setting_tuples
            )

            overlap = len(full_eids & setting_eids)
            gold_count = len(gold_for_event)

            deltas.append({
                "event_id": event_id,
                "setting": setting_name,
                "full_selected_count": len(full_eids),
                "setting_selected_count": len(setting_eids),
                "overlap_count": overlap,
                "full_prompt_chars": full_chars,
                "setting_prompt_chars": setting_chars,
                "prompt_chars_delta": setting_chars - full_chars,
                "full_matched_tuples": full_matched,
                "setting_matched_tuples": setting_matched,
                "matched_tuple_delta": setting_matched - full_matched,
                "gold_tuple_count": gold_count,
                "full_missed_gold": gold_count - full_matched,
                "setting_missed_gold": gold_count - setting_matched,
            })

    if deltas:
        (runs_dir / "event_level_deltas.json").write_text(
            json.dumps(deltas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_deltas_csv(runs_dir / "event_level_deltas.csv", deltas)


def _write_deltas_csv(path: Path, deltas: list[dict]) -> None:
    fieldnames = [
        "event_id", "setting",
        "full_selected_count", "setting_selected_count", "overlap_count",
        "full_prompt_chars", "setting_prompt_chars", "prompt_chars_delta",
        "full_matched_tuples", "setting_matched_tuples", "matched_tuple_delta",
        "gold_tuple_count", "full_missed_gold", "setting_missed_gold",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for d in deltas:
            writer.writerow(d)


def paper_status() -> dict:
    config = load_config("configs/paper.yaml")
    ablation_config = load_config("configs/ablation.yaml")
    validation = validate_paper_data()
    events_status = _events_status(Path(config.data["events_path"]))
    latest_run = config.run_dir
    artifacts = {
        name: (latest_run / name).exists()
        for name in (
            "main_results.csv",
            "retrieval_results.csv",
            "verifier_results.csv",
            "case_studies.jsonl",
        )
    }
    artifacts["ablation_results.csv"] = (
        Path(ablation_config.output.get("runs_dir", "outputs/runs")) / "ablation_results.csv"
    ).exists()
    return {
        "dataset": validation["dataset"],
        "artifacts": artifacts,
        "paper_readiness": {
            "data_ready": validation["paper_data_ready"],
            "events_ready": events_status["events_ready"],
            "main_results_ready": artifacts["main_results.csv"],
            "ablation_ready": artifacts["ablation_results.csv"],
            "retrieval_ready": artifacts["retrieval_results.csv"],
            "verifier_ready": artifacts["verifier_results.csv"],
            "case_study_ready": artifacts["case_studies.jsonl"],
        },
        "api_config": api_config_status(config),
        "next_commands": _next_commands(validation["paper_data_ready"], artifacts, events_status),
    }


def _events_status(events_path: Path) -> dict[str, object]:
    try:
        events = read_jsonl(events_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"num_events": 0, "hard_errors": [str(exc)], "events_ready": False}
    errors = [
        error
        for index, event in enumerate(events, start=1)
        for error in validate_formal_event_record(event, f"events:{index}")
    ]
    return {"num_events": len(events), "hard_errors": errors, "events_ready": bool(events) and not errors}


def _next_commands(data_ready: bool, artifacts: dict[str, bool], events_status: dict[str, object] | None = None) -> list[str]:
    if events_status is not None and not events_status.get("events_ready", False):
        return [
            "populate data/pubevent_soa_lite/events.jsonl with accepted concrete public events",
            "python scripts/validate_events.py",
        ]
    if not data_ready:
        return [
            "python scripts/collect_evidence.py",
            "python scripts/normalize_evidence.py",
            "python scripts/make_annotation_sheet.py",
            "python scripts/validate_paper_data.py",
        ]
    commands = []
    if not artifacts["main_results.csv"]:
        commands.append("python scripts/run_paper_experiment.py --config configs/paper.yaml")
    if not artifacts["ablation_results.csv"]:
        commands.append("python scripts/run_ablation.py --config configs/ablation.yaml")
    return commands


def _write_csv(path: Path, label_name: str, label: str, metrics: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([label_name, *metrics.keys()])
        writer.writerow([label, *[_format_csv_value(value) for value in metrics.values()]])


def _write_ablation_csv(path: Path, all_metrics: dict[str, dict[str, float | None]]) -> None:
    """Write ablation comparison CSV: rows = settings, columns = metrics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    preferred = [
        "Metric-Scope",
        "Num-Gold",
        "Num-Tuples",
        "Num-Tuples-All",
        "Excluded-Predictions",
        "Excluded-Event-Count",
        "Tuple-F1-soft",
        "Tuple-F1-char@0.5",
        "Tuple-F1-exact",
        "Tuple-F1-semantic",
        "Tuple-Precision",
        "Tuple-Recall",
        "Tuple-Precision-semantic",
        "Tuple-Recall-semantic",
        "Sentiment-Acc",
        "Stakeholder-Recall",
        "Opinion-Recall",
        "ESR",
        "UTR",
        "Candidate-UTR",
    ]
    available = {k for m in all_metrics.values() for k in m}
    metric_names = [name for name in preferred if name in available]
    metric_names.extend(sorted(available - set(metric_names)))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Setting", *metric_names])
        for setting in all_metrics:
            row = [setting]
            for name in metric_names:
                value = all_metrics[setting].get(name, "")
                if value is None:
                    row.append("N/A")
                elif isinstance(value, (int, float)):
                    row.append(f"{value:.4f}")
                else:
                    row.append(str(value))
            writer.writerow(row)


def _format_csv_value(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int):
        return f"{value:.4f}"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
