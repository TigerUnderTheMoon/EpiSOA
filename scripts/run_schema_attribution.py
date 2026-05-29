"""Run schema-constrained stakeholder opinion attribution."""

from __future__ import annotations

import argparse
from pathlib import Path

from episoa.attribution.schema_attributor import (
    assert_no_total_api_failure,
    read_chains,
    read_graph_nodes,
    run_schema_attribution,
)
from episoa.config import load_config, resolve_api_config
from episoa.data.loader import read_jsonl
from episoa.llm.client import build_llm_client


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    model_config = dict(config.model)
    model_name = str(model_config.get("model_name") or model_config.get("llm_model") or "unknown-model")

    events = read_jsonl(args.events)
    evidence = read_jsonl(args.evidence)
    chains_path = Path(args.chains)
    if args.dry_run and not chains_path.exists():
        print(f"dry-run warning: chains file not found; using empty chain context: {chains_path}")
        chains = []
    else:
        chains = read_chains(chains_path)
    graph_nodes = read_graph_nodes(args.graph_dir)
    event_ids = parse_event_ids(args.event_ids)
    selector_config = config.ablation.get("evidence_selector", {}) or {}
    selector_mode = args.selector_mode or selector_config.get("mode") or config.ablation.get("evidence_selector_mode") or "chain_aware"
    method_version = args.method_version or config.ablation.get("method_version", "soe_v2")
    max_evidence_per_event = args.max_evidence_per_event
    if max_evidence_per_event is None:
        max_evidence_per_event = int(config.ablation.get("max_evidence_per_event", 12))

    llm_client = None
    if args.dry_run:
        print("dry-run enabled: LLM API will not be called.")
    else:
        resolved = resolve_api_config(model_config, label="model")
        print(
            f"model: api_key={resolved['api_key_source']}:{resolved['api_key_masked']} "
            f"base_url={resolved['base_url_source']}:{resolved['base_url']}"
        )
        llm_client = build_llm_client(model_config)

    summary = run_schema_attribution(
        events=events,
        evidence_rows=evidence,
        chains=chains,
        graph_nodes=graph_nodes,
        llm_client=llm_client,
        model_name=model_name,
        output_dir=args.output_dir,
        event_ids=event_ids,
        max_events=args.max_events,
        max_evidence_per_event=max_evidence_per_event,
        dry_run=args.dry_run,
        selector_mode=selector_mode,
        method_version=method_version,
        use_stage_attribution=True if args.use_stage_attribution else None,
    )

    output_dir = Path(args.output_dir)
    print(f"num_events_requested: {summary['num_events_requested']}")
    print(f"num_events_processed: {summary['num_events_processed']}")
    print(f"num_tuples_generated: {summary['num_tuples_generated']}")
    print(f"num_api_calls: {summary['num_api_calls']}")
    print(f"num_api_failures: {summary['num_api_failures']}")
    print(f"candidate_soa_tuples: {output_dir / 'candidate_soa_tuples.jsonl'}")
    print(f"summary: {output_dir / 'schema_attribution_summary.json'}")
    if not args.dry_run:
        assert_no_total_api_failure(summary, output_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LLM schema-constrained EpiSOA attribution.")
    parser.add_argument("--config", default="configs/paper.yaml")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
    parser.add_argument("--chains", default="outputs/runs/event_chain_retrieval/event_chain_candidates.jsonl")
    parser.add_argument("--graph-dir", default="data/pubevent_soa_lite/graph")
    parser.add_argument("--output-dir", default="outputs/runs/schema_attribution")
    parser.add_argument("--event-ids", default="")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-evidence-per-event", type=int, default=None)
    parser.add_argument("--selector-mode", default="")
    parser.add_argument("--method-version", default="")
    parser.add_argument("--use-stage-attribution", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_event_ids(value: str) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
