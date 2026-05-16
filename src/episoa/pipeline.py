"""End-to-end EpiSOA paper pipeline."""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

from episoa.attribution.schema_attributor import (
    ALLOWED_SENTIMENT,
    ALLOWED_SUPPORT,
    MAX_OPINION_CHARS,
    MAX_RATIONALE_CHARS,
    MAX_TUPLES_PER_EVENT,
    PROMPT_VERSION,
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
from episoa.evaluation.metrics import soft_tuple_f1
from episoa.graph.evidence_graph import EvidenceGraph, build_stakeholder_event_evidence_graph, write_evidence_graph
from episoa.llm.client import OpenAICompatibleClient
from episoa.retrieval.event_chain_retriever import retrieve_event_chains
from episoa.verifier.faithfulness_verifier import verify_tuples


def _create_llm_client(config) -> OpenAICompatibleClient:
    """Build an LLM client from config.model dict, resolving api_key/base_url via env vars."""
    resolved = resolve_api_config(config.model, label="model")
    return OpenAICompatibleClient(
        api_key=resolved["api_key"],
        base_url=resolved["base_url"],
        model_name=config.model.get("llm_model", "deepseek-v4-flash"),
        temperature=config.model.get("temperature", 0.1),
        max_tokens=config.model.get("max_tokens", 3000),
        timeout_seconds=config.model.get("timeout_seconds", 60),
        max_retries=config.model.get("max_retries", 2),
    )


def _get_git_commit() -> str:
    """Return current git HEAD commit hash, or 'unknown' on failure."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


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
    flags: dict[str, bool],
) -> None:
    manifest = {
        "run_id": run_id,
        "timestamp": timestamp,
        "git_commit": git_commit,
        "setting": setting,
        "mode": "ablation",
        "model": {
            "provider": config.model.get("provider", "openai_compatible"),
            "model_name": config.model.get("llm_model", "unknown"),
            "base_url": os.environ.get(config.model.get("base_url_env", ""), config.model.get("base_url", "")),
            "base_url_env": config.model.get("base_url_env", ""),
            "temperature": config.model.get("temperature", 0.1),
            "max_tokens": config.model.get("max_tokens", 3000),
        },
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
    }
    (setting_dir / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_prompt_manifest(setting_dir: Path, config) -> None:
    manifest = {
        "prompt_version": PROMPT_VERSION,
        "max_tuples_per_event": MAX_TUPLES_PER_EVENT,
        "max_opinion_chars": MAX_OPINION_CHARS,
        "max_rationale_chars": MAX_RATIONALE_CHARS,
        "allowed_sentiment": sorted(ALLOWED_SENTIMENT),
        "allowed_support": sorted(ALLOWED_SUPPORT),
        "verifier_threshold": float(config.verifier.get("threshold", 0.75)),
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
        pred_by_event[p.event_id].append(p)

    all_event_ids = sorted(set(gold_by_event) | set(pred_by_event))
    fieldnames = [
        "event_id", "precision", "recall", "f1", "tp",
        "num_gold", "num_pred", "sentiment_acc",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for event_id in all_event_ids:
            gt = gold_by_event.get(event_id, [])
            pt = pred_by_event.get(event_id, [])
            soft = soft_tuple_f1(gt, pt, threshold=0.5)
            writer.writerow({
                "event_id": event_id,
                "precision": soft["precision"],
                "recall": soft["recall"],
                "f1": soft["f1"],
                "tp": soft["true_positives"],
                "num_gold": len(gt),
                "num_pred": len(pt),
                "sentiment_acc": soft["sentiment_accuracy"],
            })


def _run_core_pipeline(events, evidence, gold, gold_chains, config, run_dir, llm_client, use_graph, use_event_chain, use_verifier, hide_chain_in_prompt=False, skip_chain_ranking=False, oracle_evidence=False):
    """Run one pipeline variant. Returns (predictions, retrieval_metrics, verifier_metrics)."""
    collected = collect_evidence(events, evidence)

    if use_graph:
        graph = build_stakeholder_event_evidence_graph(
            [event.model_dump() for event in events],
            [item.model_dump() for item in collected],
        )
        write_evidence_graph(graph, run_dir / "evidence_graph")
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
        chains = retrieve_event_chains(events, collected, int(config.retrieval.get("top_k", 5)))
    else:
        chains = []

    model_name = config.model.get("llm_model", "deepseek-v4-flash")
    max_evidence_per_event = int(config.ablation.get("max_evidence_per_event", 12))
    oracle_evidence_ids_by_event = _oracle_evidence_ids_by_event(gold) if oracle_evidence else None
    run_schema_attribution(
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
    )

    candidates = _attribution_to_predictions(
        read_jsonl(run_dir / "candidate_soa_tuples.jsonl")
    )
    write_jsonl(run_dir / "candidate_soa_tuples.jsonl", candidates)

    if use_verifier:
        verified = verify_tuples(candidates, collected, float(config.verifier.get("threshold", 0.75)), llm_client=llm_client)
        verifier_metrics = evaluate_verifier(verified)
    else:
        verified = candidates
        verifier_metrics = {"verifier_skipped": 1.0}

    write_jsonl(run_dir / "verified_soa_tuples.jsonl", verified)
    write_jsonl(run_dir / "predictions.jsonl", verified)

    retrieval_metrics = evaluate_retrieval([item.model_dump() for item in gold_chains], chains)
    return verified, retrieval_metrics, verifier_metrics


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


def run_paper_pipeline(config_path: str | Path) -> dict:
    config = load_config(config_path)
    print_api_config_status(config)
    validation = validate_paper_data()
    run_dir = config.run_dir
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

    llm_client = _create_llm_client(config)

    verified, retrieval_metrics, verifier_metrics = _run_core_pipeline(
        events, evidence, gold, gold_chains, config, run_dir, llm_client,
        use_graph=True, use_event_chain=True, use_verifier=True,
    )

    metrics = evaluate_main(gold, verified)

    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(run_dir / "main_results.csv", "Method", "EpiSOA", metrics)
    _write_csv(run_dir / "retrieval_results.csv", "Method", "EpiSOA", retrieval_metrics)
    _write_csv(run_dir / "verifier_results.csv", "Method", "EpiSOA", verifier_metrics)
    write_jsonl(run_dir / "case_studies.jsonl", [item.model_dump() for item in verified[:3]])

    summary = {
        "status": "completed",
        "num_events": len(events),
        "num_evidence": len(evidence),
        "num_predictions": len(verified),
        "metrics": metrics,
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
                stakeholder=row.get("stakeholder", ""),
                opinion=row.get("opinion", ""),
                sentiment=row.get("sentiment", "unknown"),
                rationale=row.get("rationale", ""),
                evidence_ids=row.get("evidence_ids", []),
                support_label=_map_support_label(row.get("support_status", "candidate_unclear")),
                support_score=row.get("confidence", 0.5),
                verified=False,
            )
        )
    return predictions


ABLATION_SETTINGS = {
    "full":                       {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False},
    "full_oracle_evidence":       {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False, "oracle_evidence": True},
    "without_graph":              {"use_graph": False, "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": False},
    "without_event_chain":        {"use_graph": True,  "use_event_chain": False, "use_verifier": True,  "hide_chain_in_prompt": True,  "skip_chain_ranking": True},
    "without_verifier":           {"use_graph": True,  "use_event_chain": True,  "use_verifier": False, "hide_chain_in_prompt": False, "skip_chain_ranking": False},
    "without_event_chain_prompt":  {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": True,  "skip_chain_ranking": False},
    "without_event_chain_ranking": {"use_graph": True,  "use_event_chain": True,  "use_verifier": True,  "hide_chain_in_prompt": False, "skip_chain_ranking": True},
}


def run_ablation_pipeline(config_path: str | Path, force: bool = False) -> dict:
    """Run ablation experiments for every setting in config.ablation.settings.

    Each setting runs the full pipeline independently in its own output directory
    under outputs/runs/ablation_{setting}/.  Paper-final mode never reuses cached
    results; every configured setting always runs from scratch.

    When force=True, existing setting directories are removed before running.
    """
    config = load_config(config_path)
    print_api_config_status(config)
    validation = validate_paper_data()
    if not validation["paper_data_ready"]:
        return {"status": "blocked", "reason": "paper data is not ready", "validation": validation}

    runs_dir = Path(config.output.get("runs_dir", "outputs/runs"))

    events = read_typed_jsonl(config.data["events_path"], EventRecord)
    evidence = read_typed_jsonl(config.data["evidence_path"], EvidenceRecord)
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)
    gold_chains = read_typed_jsonl(config.data["gold_event_chains_path"], GoldEventChain)

    llm_client = _create_llm_client(config)
    timestamp = datetime.now(timezone.utc).isoformat()
    git_commit = _get_git_commit()

    all_metrics: dict[str, dict[str, float]] = {}
    settings: list[str] = config.ablation.get("settings", list(ABLATION_SETTINGS))

    for setting in settings:
        flags = ABLATION_SETTINGS.get(setting)
        if flags is None:
            print(f"  [SKIP] unknown ablation setting: {setting}")
            continue

        setting_dir = runs_dir / f"ablation_{setting}"

        if force:
            if setting_dir.exists():
                shutil.rmtree(setting_dir)
                print(f"  [FORCE] removed {setting_dir}")

        setting_dir.mkdir(parents=True, exist_ok=True)

        # Always write manifests before running (paper-final: never skip)
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
        )
        _write_prompt_manifest(setting_dir, config)

        print(f"  [RUN] {setting} → {setting_dir}")
        verified, _retrieval_metrics, _verifier_metrics = _run_core_pipeline(
            events, evidence, gold, gold_chains, config, setting_dir, llm_client,
            **flags,
        )

        metrics = evaluate_ablation(gold, verified, verifier_enabled=bool(flags["use_verifier"]))
        all_metrics[setting] = metrics

        (setting_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_event_level_csv(setting_dir / "event_level_metrics.csv", gold, verified)

        print(f"  [{setting}] Tuple-F1-soft={metrics.get('Tuple-F1-soft', 'N/A')}, "
              f"Num-Tuples={metrics.get('Num-Tuples', 'N/A')}")

    # Aggregate only from the current run (never reads old cache)
    _write_ablation_csv(runs_dir / "ablation_results.csv", all_metrics)

    delta_paths = write_ablation_delta_audits(
        runs_dir=runs_dir,
        gold_tuples=gold,
        settings=[setting for setting in CHAIN_ABLATION_SETTINGS if setting in settings],
    )
    audit_report_path = write_ablation_audit_report(
        runs_dir=runs_dir,
        settings=settings,
        flags_by_setting={setting: ABLATION_SETTINGS.get(setting, {}) for setting in settings},
    )

    summary = {
        "status": "completed",
        "run_id": "ablation",
        "timestamp": timestamp,
        "git_commit": git_commit,
        "force": force,
        "settings": list(all_metrics.keys()),
        "metrics": all_metrics,
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
    validation = validate_paper_data()
    events_status = _events_status(Path(config.data["events_path"]))
    latest_run = Path("outputs/runs/pubevent-soa-lite-paper")
    artifacts = {
        name: (latest_run / name).exists()
        for name in (
            "main_results.csv",
            "ablation_results.csv",
            "retrieval_results.csv",
            "verifier_results.csv",
            "case_studies.jsonl",
        )
    }
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
        writer.writerow([label, *[f"{value:.4f}" for value in metrics.values()]])


def _write_ablation_csv(path: Path, all_metrics: dict[str, dict[str, float | None]]) -> None:
    """Write ablation comparison CSV: rows = settings, columns = metrics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    preferred = [
        "Num-Gold",
        "Num-Tuples",
        "Tuple-F1-soft",
        "Tuple-Precision",
        "Tuple-Recall",
        "Sentiment-Acc",
        "Stakeholder-Recall",
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
