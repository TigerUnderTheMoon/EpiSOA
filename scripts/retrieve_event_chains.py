"""Retrieve candidate event chains from filtered evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from episoa.data.loader import read_jsonl, write_jsonl
from episoa.retrieval.event_chain_retriever import (
    EventChainRetriever,
    audit_sample_rows,
    build_retrieval_summary,
    flatten_candidates,
)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    events = read_jsonl(args.events)
    evidence = read_jsonl(args.evidence)
    graph_mode = graph_available(Path(args.graph_dir))
    retriever = EventChainRetriever(
        top_k_per_stage=args.top_k_per_stage,
        max_chain_length=6,
        min_stage_score=args.min_stage_score,
        min_event_relevance=args.min_event_relevance,
        deduplicate_evidence_across_stages=args.deduplicate_evidence_across_stages,
    )
    candidates = retriever.retrieve_all(events, evidence)
    for candidate in candidates:
        candidate["retrieval_diagnostics"]["graph_mode"] = graph_mode

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "event_chain_candidates.jsonl"
    summary_path = output_dir / "event_chain_retrieval_summary.json"
    table_path = output_dir / "event_chain_retrieval_table.csv"
    audit_path = output_dir / "event_chain_audit_sample.csv"

    write_jsonl(candidates_path, candidates)
    summary = build_retrieval_summary(candidates, str(candidates_path))
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_table(table_path, flatten_candidates(candidates))
    write_table(audit_path, audit_sample_rows(candidates, per_stage=20))

    print(f"num_events processed: {summary['num_events']}")
    print(f"event_chain_candidates written: {candidates_path}")
    print(f"avg_chain_confidence: {summary['avg_chain_confidence']}")
    print(f"events_with_all_core_stages: {len(summary['events_with_all_core_stages'])}")
    print(f"output_dir: {output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieve candidate EpiSOA event chains.")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_filtered.jsonl")
    parser.add_argument("--graph-dir", default="data/pubevent_soa_lite/graph")
    parser.add_argument("--output-dir", default="outputs/runs/event_chain_retrieval")
    parser.add_argument("--top-k-per-stage", type=int, default=3)
    parser.add_argument("--min-stage-score", type=float, default=0.25)
    parser.add_argument("--min-event-relevance", type=float, default=0.30)
    parser.add_argument(
        "--deduplicate-evidence-across-stages",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def graph_available(graph_dir: Path) -> str:
    required = ["evidence_graph_nodes.jsonl", "evidence_graph_edges.jsonl", "evidence_graph_summary.json"]
    return "graph_available" if all((graph_dir / name).exists() for name in required) else "evidence_only"


def write_table(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "event_id",
        "stage_order",
        "stage",
        "evidence_id",
        "score",
        "stage_score",
        "final_stage_score",
        "event_relevance_score",
        "matched_event_terms",
        "matched_seed_keywords",
        "matched_event_name_terms",
        "matched_description_terms",
        "matched_stage_keywords",
        "generic_penalty_terms",
        "stage_keyword_score",
        "quality_score_component",
        "source_prior_component",
        "stakeholder_signal_component",
        "source",
        "domain",
        "url",
        "title",
        "text_excerpt",
        "is_generic_penalized",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
