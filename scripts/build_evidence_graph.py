"""Build the Stakeholder-Event Evidence Graph from events and filtered evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from episoa.data.loader import read_jsonl
from episoa.graph.evidence_graph import build_stakeholder_event_evidence_graph, write_evidence_graph


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    events = read_jsonl(args.events)
    evidence = read_jsonl(args.evidence)
    graph = build_stakeholder_event_evidence_graph(events, evidence)
    paths = write_evidence_graph(graph, args.output_dir)

    print(f"nodes written: {paths['nodes']}")
    print(f"edges written: {paths['edges']}")
    print(f"num_events: {graph.summary['num_events']}")
    print(f"num_evidence: {graph.summary['num_evidence']}")
    print(f"num_stakeholder_candidates: {graph.summary['num_stakeholder_candidates']}")
    print("source_distribution:")
    print(json.dumps(graph.summary["source_distribution"], ensure_ascii=False, indent=2))
    print("stage_distribution:")
    print(json.dumps(graph.summary["stage_distribution"], ensure_ascii=False, indent=2))
    print(f"output_dir: {Path(args.output_dir)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build EpiSOA Stakeholder-Event Evidence Graph.")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_filtered.jsonl")
    parser.add_argument("--output-dir", default="data/pubevent_soa_lite/graph")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
