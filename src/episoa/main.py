"""EpiSOA end-to-end pipeline entrypoint."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from episoa.collector.fsm_graph import build_collector_graph
from episoa.config import load_runtime_config
from episoa.evaluation.case_study import write_case_study_examples
from episoa.evaluation.faithfulness_metrics import evaluate_jsonl
from episoa.eventrag.path_reranking import retrieve_event_chains
from episoa.experiment import (
    RunContext,
    configure_logging,
    create_run_context,
    get_logger,
    run_metadata_from_config,
    save_config_snapshot,
    set_random_seed,
    write_run_readme,
)
from episoa.graph_builder.extractor import build_evidence_graph
from episoa.llm.client import build_llm_client
from episoa.reasoner.attribution_reasoner import reason_attribution
from episoa.retrieval.diversity_retriever import relevance_score
from episoa.retrieval.diversity_retriever import DiversityAwareEvidenceRetriever, EmbeddingRelevanceScorer
from episoa.retrieval.diversity_retriever import retrieve as retrieve_evidence
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain
from episoa.verifier.evidence_support import verify_attributions


DEFAULT_CONFIG_PATH = Path("configs/default.yaml")
DEFAULT_DEMO_EVENT_PATH = Path("examples/demo_event.json")
DEFAULT_DEMO_EVIDENCE_PATH = Path("examples/demo_evidence.jsonl")
DEFAULT_ABLATION_FLAGS = {
    "use_fsm_collector": True,
    "use_feedback_transitions": True,
    "use_diversity_retriever": True,
    "use_evidence_graph": True,
    "use_event_chain_retriever": True,
    "use_verifier": True,
    "use_temporal_information": True,
}
logger = get_logger("main")


def log_step(message: str, active_logger=None) -> None:
    """Print a pipeline log message."""
    (active_logger or logger).info(message)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load YAML configuration."""
    config_path = Path(path)
    if not config_path.exists():
        return {}
    return load_runtime_config(config_path)


def load_demo_inputs(
    event_path: str | Path = DEFAULT_DEMO_EVENT_PATH,
    evidence_path: str | Path = DEFAULT_DEMO_EVIDENCE_PATH,
) -> tuple[str, dict[str, Any], list[EvidenceRecord]]:
    """Load demo event and evidence records."""
    with Path(event_path).open("r", encoding="utf-8") as file:
        event_payload = json.load(file)

    evidence_records: list[EvidenceRecord] = []
    with Path(evidence_path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                evidence_records.append(EvidenceRecord.model_validate_json(line))

    return (
        str(event_payload["event_description"]),
        dict(event_payload.get("time_window", {})),
        evidence_records,
    )


def run_pipeline(
    event_description: str,
    time_window: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
    evidence_pool: list[EvidenceRecord] | None = None,
    output_path: str | Path | None = None,
    run_context: RunContext | None = None,
) -> list[AttributionTuple]:
    """Run the complete EpiSOA pipeline and write JSONL output."""
    config = config or {}
    if run_context is None:
        run_context = create_run_context()
        configure_logging(run_context.log_path)
    config = _config_with_run_context(config, run_context)
    seed = int(config.get("reproducibility", {}).get("seed", config.get("seed", 13)))
    set_random_seed(seed)
    config["reproducibility"] = run_metadata_from_config(config, seed)
    save_config_snapshot(config, run_context.config_path)

    pipeline_config = config.get("pipeline", {})
    collector_config = config.get("collector", {})
    ablation_config = _ablation_flags(config)
    llm_client = build_llm_client(config)
    relevance_scorer = _build_relevance_scorer(config)
    time_window = time_window or {}

    log_step(f"Run ID: {run_context.run_id}")
    if ablation_config["use_fsm_collector"]:
        log_step("1/8 Running FSM-style Agentic Evidence Collector")
        collector_graph = build_collector_graph()
        collector_input = {
            **collector_config,
            "target_event": event_description,
            "time_window": time_window,
            "mock_coverage_scenario": (
                collector_config.get("mock_coverage_scenario", "covered")
                if ablation_config["use_feedback_transitions"]
                else "covered"
            ),
        }
        if not ablation_config["use_feedback_transitions"]:
            collector_input["max_coverage_attempts"] = 1
        collector_state = collector_graph.invoke(
            collector_input,
            config={"recursion_limit": int(collector_config.get("recursion_limit", 30))},
        )
        if evidence_pool is None:
            evidence_pool = _evidence_from_collector_state(event_description, collector_state)
    else:
        log_step("1/8 Skipping FSM-style Agentic Evidence Collector")
        if evidence_pool is None:
            evidence_pool = _evidence_from_collector_state(event_description, {})

    if not ablation_config["use_temporal_information"]:
        log_step("Ablation active: removing temporal information from evidence records")
        evidence_pool = _without_temporal_information(evidence_pool)
    log_step(f"Collected {len(evidence_pool)} evidence records")

    top_k_evidence = int(pipeline_config.get("top_k_evidence", 5))
    if ablation_config["use_diversity_retriever"]:
        log_step("2/8 Running Diversity-aware Evidence Retriever")
        if "retrieval" in config:
            candidate_evidence = DiversityAwareEvidenceRetriever(relevance_scorer=relevance_scorer).retrieve(
                event_description,
                evidence_pool,
                top_k=top_k_evidence,
            )
        else:
            candidate_evidence = retrieve_evidence(event_description, evidence_pool, top_k=top_k_evidence)
    else:
        log_step("2/8 Running relevance-only evidence retrieval")
        candidate_evidence = _relevance_only_retrieve(event_description, evidence_pool, top_k_evidence, relevance_scorer)
    log_step(f"Selected {len(candidate_evidence)} candidate evidence records")

    evidence_graph = None
    if ablation_config["use_evidence_graph"]:
        log_step("3/8 Building Stakeholder-centered Evidence Graph")
        evidence_graph = build_evidence_graph(candidate_evidence)
        log_step(f"Evidence graph has {evidence_graph.node_count} nodes and {evidence_graph.edge_count} edges")
    else:
        log_step("3/8 Skipping Stakeholder-centered Evidence Graph")

    if ablation_config["use_event_chain_retriever"] and evidence_graph is not None:
        log_step("4/8 Running EventRAG-style Event-chain Retriever")
        event_chains = retrieve_event_chains(
            event_description,
            evidence_graph,
            depth=int(pipeline_config.get("eventrag_depth", 2)),
            top_k=int(pipeline_config.get("eventrag_top_k", 3)),
        )
    else:
        log_step("4/8 Skipping EventRAG-style Event-chain Retriever")
        event_chains = [_fallback_event_chain(event_description, candidate_evidence)]
    if not event_chains:
        event_chains = [_fallback_event_chain(event_description, candidate_evidence)]
    log_step(f"Generated {len(event_chains)} event evidence packages")

    log_step("5/8 Running Schema-constrained Attribution Reasoner")
    raw_attributions: list[AttributionTuple] = []
    for event_chain in event_chains:
        chain_evidence = event_chain.evidence or candidate_evidence
        raw_attributions.extend(
            reason_attribution(
                event_chain,
                chain_evidence,
                event_description,
                llm_client=llm_client,
            )
        )
    log_step(f"Generated {len(raw_attributions)} attribution tuples")

    if ablation_config["use_verifier"]:
        log_step("6/8 Running Evidence Verifier")
        verified_attributions = verify_attributions(
            raw_attributions,
            candidate_evidence,
            llm_client=llm_client,
            threshold=float(config.get("verifier", {}).get("threshold", 0.75)),
        )
        verified_count = sum(item.verified for item in verified_attributions)
        log_step(f"Verified {verified_count}/{len(verified_attributions)} attribution tuples")
    else:
        log_step("6/8 Skipping Evidence Verifier")
        verified_attributions = raw_attributions

    log_step("7/8 Writing JSONL output")
    write_jsonl(verified_attributions, run_context.predictions_path)
    resolved_output_path = Path(output_path) if output_path else Path(
        pipeline_config.get("output_path", run_context.predictions_path)
    )
    if resolved_output_path != run_context.predictions_path:
        write_jsonl(verified_attributions, resolved_output_path)
    log_step(f"Wrote run predictions to {run_context.predictions_path}")
    if resolved_output_path != run_context.predictions_path:
        log_step(f"Wrote compatibility output to {resolved_output_path}")

    _write_or_compute_metrics(config, run_context)
    write_run_readme(config, run_context)
    _write_case_studies(config, run_context)

    log_step("8/8 Pipeline complete")
    return verified_attributions


def write_jsonl(attributions: list[AttributionTuple], output_path: str | Path) -> None:
    """Write attribution tuples to JSONL."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for attribution in attributions:
            file.write(json.dumps(attribution.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _ablation_flags(config: dict[str, Any]) -> dict[str, bool]:
    flags = dict(DEFAULT_ABLATION_FLAGS)
    flags.update({key: bool(value) for key, value in config.get("ablation", {}).items() if key in flags})
    return flags


def _config_with_run_context(config: dict[str, Any], run_context: RunContext) -> dict[str, Any]:
    effective = dict(config)
    llm_config = dict(effective.get("llm", {}))
    llm_config["prompt_log_dir"] = str(run_context.prompts_dir)
    effective["llm"] = llm_config
    effective["run"] = {
        "run_id": run_context.run_id,
        "run_dir": str(run_context.run_dir),
        "predictions_path": str(run_context.predictions_path),
        "metrics_path": str(run_context.metrics_path),
        "log_path": str(run_context.log_path),
        "prompts_dir": str(run_context.prompts_dir),
    }
    return effective


def _write_or_compute_metrics(config: dict[str, Any], run_context: RunContext) -> None:
    evaluation_config = config.get("evaluation", {})
    gold_path = evaluation_config.get("gold_path")
    if gold_path and Path(gold_path).exists():
        metrics = evaluate_jsonl(
            run_context.predictions_path,
            gold_path,
            run_context.metrics_path,
            k=int(evaluation_config.get("k", 5)),
        )
        log_step(f"Wrote metrics to {run_context.metrics_path}: {metrics}")
        return

    run_context.metrics_path.write_text("{}\n", encoding="utf-8")
    log_step(f"Wrote empty metrics file to {run_context.metrics_path}")


def _write_case_studies(config: dict[str, Any], run_context: RunContext) -> None:
    evaluation_config = config.get("evaluation", {})
    gold_path = evaluation_config.get("gold_path")
    if not gold_path:
        gold_path = run_context.run_dir / "gold_tuples.jsonl"
    output_path = write_case_study_examples(
        run_context.run_dir,
        gold_tuples_path=gold_path,
        max_cases=int(evaluation_config.get("case_study_max_cases", 5)),
    )
    log_step(f"Wrote case study examples to {output_path}")


def _relevance_only_retrieve(
    query: str,
    evidence_pool: list[EvidenceRecord],
    top_k: int,
    scorer=relevance_score,
) -> list[EvidenceRecord]:
    return sorted(
        evidence_pool,
        key=lambda item: (scorer(query, item), item.timestamp, item.evidence_id),
        reverse=True,
    )[: max(top_k, 0)]


def _build_relevance_scorer(config: dict[str, Any]):
    retrieval_config = config.get("retrieval")
    if not retrieval_config:
        return relevance_score
    return EmbeddingRelevanceScorer(
        mode=str(retrieval_config.get("embedding_mode", "mock")),
        model_name=str(retrieval_config.get("embedding_model_name", "mock-embedding")),
        cache_dir=str(retrieval_config.get("cache_dir", "outputs/cache/embeddings")),
        reranker_mode=str(retrieval_config.get("reranker_mode", "mock")),
        reranker_model_name=str(retrieval_config.get("reranker_model_name", "mock-reranker")),
    )


def _without_temporal_information(evidence_pool: list[EvidenceRecord]) -> list[EvidenceRecord]:
    neutral_time = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return [item.model_copy(update={"timestamp": neutral_time}) for item in evidence_pool]


def _evidence_from_collector_state(
    event_description: str,
    collector_state: dict[str, Any],
) -> list[EvidenceRecord]:
    raw_evidence = collector_state.get("evidence") or []
    now = datetime.now(timezone.utc)
    records: list[EvidenceRecord] = []

    for index, item in enumerate(raw_evidence, start=1):
        evidence_id = str(item.get("evidence_id", f"collector-{index}"))
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                platform=str(item.get("platform", "collector_mock")),
                url=str(item.get("url", f"https://example.com/{evidence_id}")),
                timestamp=now,
                text=str(item.get("text", f"Mock evidence for {event_description}")),
                author_alias=str(item.get("author_alias", "mock_stakeholder")),
                source_type=item.get("source_type", "other"),
                metadata={
                    "event": event_description,
                    "stakeholder": item.get("stakeholder", "mock_stakeholder"),
                    "sentiment": item.get("sentiment", "unknown"),
                    "opinion": item.get("text", f"Mock opinion about {event_description}"),
                },
            )
        )

    if records:
        return records

    return [
        EvidenceRecord(
            evidence_id="collector-mock-1",
            platform="collector_mock",
            url="https://example.com/collector-mock-1",
            timestamp=now,
            text=f"Customers discussed {event_description} with mixed reactions.",
            author_alias="Customers",
            source_type="social_media",
            metadata={
                "event": event_description,
                "stakeholder": "Customers",
                "sentiment": "mixed",
                "opinion": f"Customers discussed {event_description}.",
            },
        )
    ]


def _fallback_event_chain(event_description: str, evidence: list[EvidenceRecord]) -> EventChain:
    stakeholders = sorted(
        {
            str(item.metadata.get("stakeholder") or item.author_alias or "unknown")
            for item in evidence
        }
    ) or ["unknown"]
    events = [
        str(item.metadata.get("event"))
        for item in evidence
        if item.metadata.get("event")
    ] or [event_description]
    return EventChain(
        target_event=event_description,
        event_chain=list(dict.fromkeys(events)),
        stakeholders=stakeholders,
        candidate_rationales=["Fallback event chain generated from candidate evidence."],
        evidence=evidence,
    )


def parse_time_window(value: str | None) -> dict[str, Any]:
    """Parse a JSON time window passed on the CLI."""
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("--time-window must be a JSON object")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the EpiSOA pipeline.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to YAML config.")
    parser.add_argument("--demo", action="store_true", help="Use examples/demo_event.json and demo_evidence.jsonl.")
    parser.add_argument("--event-description", help="Target event description.")
    parser.add_argument("--time-window", help="JSON object with start/end time window.")
    parser.add_argument("--output", help="Output JSONL path.")
    parser.add_argument("--run-name", help="Optional human-readable run name included in run_id.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    run_context = create_run_context(args.run_name)
    configure_logging(run_context.log_path)

    if args.demo:
        event_description, time_window, evidence_pool = load_demo_inputs()
    else:
        if not args.event_description:
            parser.error("--event-description is required unless --demo is used")
        event_description = args.event_description
        time_window = parse_time_window(args.time_window)
        evidence_pool = None

    run_pipeline(
        event_description,
        time_window,
        config=config,
        evidence_pool=evidence_pool,
        output_path=args.output,
        run_context=run_context,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
