"""Run evidence faithfulness verification for candidate SOA tuples."""

from __future__ import annotations

import argparse
from pathlib import Path

from episoa.config import load_config, resolve_api_config
from episoa.data.loader import read_jsonl
from episoa.llm.client import build_llm_client
from episoa.verification.faithfulness_verifier import run_faithfulness_verification


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    model_config = dict(config.model)
    model_name = str(model_config.get("model_name") or model_config.get("llm_model") or "unknown-model")

    candidates = read_jsonl(args.candidates)
    evidence = read_jsonl(args.evidence)
    chains = read_jsonl(args.chains)
    tuple_ids = parse_csv_arg(args.tuple_ids)
    event_ids = parse_csv_arg(args.event_ids)

    llm_client = None
    if args.dry_run:
        print("dry-run enabled: verifier LLM API will not be called.")
    else:
        resolved = resolve_api_config(model_config, label="model")
        print(
            f"model: api_key={resolved['api_key_source']}:{resolved['api_key_masked']} "
            f"base_url={resolved['base_url_source']}:{resolved['base_url']}"
        )
        llm_client = build_llm_client(model_config)

    summary = run_faithfulness_verification(
        candidates=candidates,
        evidence_rows=evidence,
        chains=chains,
        llm_client=llm_client,
        model_name=model_name,
        output_dir=args.output_dir,
        tuple_ids=tuple_ids,
        event_ids=event_ids,
        max_tuples=args.max_tuples,
        dry_run=args.dry_run,
    )

    output_dir = Path(args.output_dir)
    print(f"num_candidate_tuples: {summary['num_candidate_tuples']}")
    print(f"num_verified_tuples: {summary['num_verified_tuples']}")
    print(f"num_api_calls: {summary['num_api_calls']}")
    print(f"num_api_failures: {summary['num_api_failures']}")
    print(f"parse_failed_tuples: {summary['parse_failed_tuples']}")
    print(f"verified_soa_tuples: {output_dir / 'verified_soa_tuples.jsonl'}")
    print(f"summary: {output_dir / 'verifier_summary.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA evidence faithfulness verification.")
    parser.add_argument("--config", default="configs/paper.yaml")
    parser.add_argument("--candidates", default="outputs/runs/schema_attribution/candidate_soa_tuples.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_filtered.jsonl")
    parser.add_argument("--chains", default="outputs/runs/event_chain_retrieval/event_chain_candidates.jsonl")
    parser.add_argument("--output-dir", default="outputs/runs/faithfulness_verification")
    parser.add_argument("--tuple-ids", default="")
    parser.add_argument("--event-ids", default="")
    parser.add_argument("--max-tuples", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_csv_arg(value: str) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
