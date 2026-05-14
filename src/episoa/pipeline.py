"""End-to-end EpiSOA paper pipeline."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import yaml

from episoa.attribution.schema_attributor import run_schema_attribution
from episoa.collector.cfsm_collector import collect_evidence
from episoa.config import api_config_status, load_config, print_api_config_status, resolve_api_config
from episoa.data.loader import read_jsonl, read_typed_jsonl, write_jsonl
from episoa.data.schema import EventRecord, EvidenceRecord, GoldEventChain, GoldTuple, PredictionTuple
from episoa.data.validator import validate_formal_event_record, validate_paper_data
from episoa.evaluation.evaluate_ablation import evaluate_ablation
from episoa.evaluation.evaluate_main import evaluate_main
from episoa.evaluation.evaluate_retrieval import evaluate_retrieval
from episoa.evaluation.evaluate_verifier import evaluate_verifier
from episoa.graph.evidence_graph import write_evidence_graph
from episoa.graph.graph_builder import build_graph
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


def _run_core_pipeline(events, evidence, gold, gold_chains, config, run_dir, llm_client, skip_graph, skip_chains, skip_verifier):
    """Run one pipeline variant. Returns (predictions, retrieval_metrics, verifier_metrics)."""
    collected = collect_evidence(events, evidence)

    if skip_graph:
        graph_nodes = []
    else:
        graph = build_graph(events, collected)
        write_evidence_graph(graph, run_dir / "evidence_graph")
        graph_nodes = graph.node_records()
    chains = [] if skip_chains else retrieve_event_chains(events, collected, int(config.retrieval.get("top_k", 5)))

    model_name = config.model.get("llm_model", "deepseek-v4-flash")
    run_schema_attribution(
        events=[e.model_dump() for e in events],
        evidence_rows=[e.model_dump() for e in collected],
        chains=chains,
        graph_nodes=graph_nodes,
        llm_client=llm_client,
        model_name=model_name,
        output_dir=run_dir,
        max_evidence_per_event=12,
    )

    candidates = _attribution_to_predictions(
        read_jsonl(run_dir / "candidate_soa_tuples.jsonl")
    )
    write_jsonl(run_dir / "candidate_soa_tuples.jsonl", candidates)

    if skip_verifier:
        verified = candidates
        verifier_metrics = {"verifier_skipped": 1.0}
    else:
        verified = verify_tuples(candidates, collected, float(config.verifier.get("threshold", 0.75)), llm_client=llm_client)
        verifier_metrics = evaluate_verifier(verified)

    write_jsonl(run_dir / "verified_soa_tuples.jsonl", verified)
    write_jsonl(run_dir / "predictions.jsonl", verified)

    retrieval_metrics = evaluate_retrieval([item.model_dump() for item in gold_chains], chains)
    return verified, retrieval_metrics, verifier_metrics


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
        skip_graph=False, skip_chains=False, skip_verifier=False,
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
    "full":                  {"skip_graph": False, "skip_chains": False, "skip_verifier": False},
    "without_graph":         {"skip_graph": True,  "skip_chains": False, "skip_verifier": False},
    "without_event_chain":   {"skip_graph": False, "skip_chains": True,  "skip_verifier": False},
    "without_verifier":      {"skip_graph": False, "skip_chains": False, "skip_verifier": True},
}


def run_ablation_pipeline(config_path: str | Path) -> dict:
    config = load_config(config_path)
    print_api_config_status(config)
    validation = validate_paper_data()
    run_dir = config.run_dir
    if not validation["paper_data_ready"]:
        return {"status": "blocked", "reason": "paper data is not ready", "validation": validation}
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, run_dir / "config.yaml")

    events = read_typed_jsonl(config.data["events_path"], EventRecord)
    evidence = read_typed_jsonl(config.data["evidence_path"], EvidenceRecord)
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)
    gold_chains = read_typed_jsonl(config.data["gold_event_chains_path"], GoldEventChain)

    llm_client = _create_llm_client(config)

    all_metrics: dict[str, dict[str, float]] = {}
    settings = config.ablation.get("settings", list(ABLATION_SETTINGS))

    for setting in settings:
        flags = ABLATION_SETTINGS.get(setting)
        if flags is None:
            print(f"  [SKIP] unknown ablation setting: {setting}")
            continue

        setting_dir = run_dir / setting
        setting_dir.mkdir(parents=True, exist_ok=True)

        verified, retrieval_metrics, verifier_metrics = _run_core_pipeline(
            events, evidence, gold, gold_chains, config, setting_dir, llm_client,
            **flags,
        )

        metrics = evaluate_ablation(gold, verified)
        all_metrics[setting] = metrics

        (setting_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  [{setting}] Tuple-F1={metrics.get('Tuple-F1', 'N/A')}")

    _write_ablation_csv(run_dir / "ablation_results.csv", all_metrics)
    summary = {"status": "completed", "settings": list(all_metrics.keys()), "metrics": all_metrics}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


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


def _write_ablation_csv(path: Path, all_metrics: dict[str, dict[str, float]]) -> None:
    """Write ablation comparison CSV: rows = settings, columns = metrics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    metric_names = sorted({k for m in all_metrics.values() for k in m})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Setting", *metric_names])
        for setting in sorted(all_metrics):
            row = [setting]
            for name in metric_names:
                value = all_metrics[setting].get(name, "")
                row.append(f"{value:.4f}" if isinstance(value, (int, float)) else str(value))
            writer.writerow(row)
