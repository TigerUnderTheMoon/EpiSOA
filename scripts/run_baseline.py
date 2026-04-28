"""Run EpiSOA baselines and write AttributionTuple JSONL outputs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from episoa.baselines import direct_llm, diversity_rag, episoa_full, graph_retrieval, vanilla_rag
from episoa.config import load_runtime_config
from episoa.main import load_demo_inputs, write_jsonl
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


BaselineRunner = Callable[[str, list[EvidenceRecord], dict[str, Any] | None], list[AttributionTuple]]

BASELINE_RUNNERS: dict[str, BaselineRunner] = {
    "direct_llm": direct_llm.run,
    "vanilla_rag": vanilla_rag.run,
    "diversity_rag": diversity_rag.run,
    "graph_retrieval": graph_retrieval.run,
    "episoa_full": episoa_full.run,
}


def load_config(path: str | Path) -> dict[str, Any]:
    return load_runtime_config(path)


def run_named_baseline(
    name: str,
    config: dict[str, Any],
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Run one configured baseline and return the output path."""
    if name not in BASELINE_RUNNERS:
        known = ", ".join(sorted(BASELINE_RUNNERS))
        raise ValueError(f"Unknown baseline '{name}'. Expected one of: {known}")

    data_config = dict(config.get("data", {}))
    baseline_config = dict(config.get("methods", {}).get(name, {}))
    output_config = dict(config.get("output", {}))
    event_path = baseline_config.get("event_path", data_config.get("event_query_path"))
    evidence_path = baseline_config.get("evidence_path", data_config.get("evidence_path"))
    event_description, _, evidence_pool = load_demo_inputs(event_path, evidence_path)

    attributions = BASELINE_RUNNERS[name](event_description, evidence_pool, baseline_config)
    resolved_output = Path(
        output_path
        or baseline_config.get("output_path")
        or Path(output_config["run_dir"]) / "predictions" / f"{name}.jsonl"
    )
    write_jsonl(attributions, resolved_output)
    print(f"[baseline:{name}] wrote {len(attributions)} tuples to {resolved_output}")
    return resolved_output


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA baseline systems.")
    parser.add_argument("--config", default="configs/baselines.yaml", help="Baseline YAML config path.")
    parser.add_argument(
        "--baseline",
        choices=[*BASELINE_RUNNERS.keys(), "all"],
        default="all",
        help="Baseline to run.",
    )
    parser.add_argument("--output", help="Override output path when running a single baseline.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.baseline == "all":
        if args.output:
            parser.error("--output can only be used with a single baseline")
        for name in BASELINE_RUNNERS:
            run_named_baseline(name, config)
    else:
        run_named_baseline(args.baseline, config, output_path=args.output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
