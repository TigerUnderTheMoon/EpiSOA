"""Command line interface for the EpiSOA paper workflow."""

from __future__ import annotations

import argparse
import json

from episoa.ea.commands import (
    ea_status,
    evaluate_ea,
    prepare_ea,
    prepare_ea_evaluation,
    prepare_ea_gold,
    run_ea,
    run_ea_ablation,
)
from episoa.pipeline import paper_status, run_ablation_pipeline, run_paper_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EpiSOA reproducible paper workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("paper-status")
    status.set_defaults(handler=_paper_status)

    run = subparsers.add_parser("run-paper")
    run.add_argument("--config", default="configs/paper.yaml")
    _add_runtime_args(run, include_settings=False)
    run.set_defaults(handler=_run_paper)

    ablation = subparsers.add_parser("run-ablation")
    ablation.add_argument("--config", default="configs/ablation.yaml")
    ablation.add_argument(
        "--force",
        action="store_true",
        help="Remove existing setting directories before re-running all settings",
    )
    _add_runtime_args(ablation, include_settings=True)
    ablation.set_defaults(handler=_run_ablation)

    ea_status_parser = subparsers.add_parser("ea-status")
    ea_status_parser.add_argument("--config", default="configs/ea_pilot.yaml")
    ea_status_parser.set_defaults(handler=_ea_status)

    prepare_ea_parser = subparsers.add_parser("prepare-ea")
    prepare_ea_parser.add_argument("--config", default="configs/ea_pilot.yaml")
    prepare_ea_parser.set_defaults(handler=_prepare_ea)

    run_ea_parser = subparsers.add_parser("run-ea")
    run_ea_parser.add_argument("--config", default="configs/ea_pilot.yaml")
    run_ea_parser.add_argument(
        "--stage", choices=("m2", "m3", "fusion", "dossier", "baseline"), default=None
    )
    run_ea_parser.add_argument(
        "--fusion-method", choices=("exact", "embedding", "llm", "apcf"), default="apcf"
    )
    run_ea_parser.add_argument(
        "--method",
        choices=("long_context_event_llm", "long_context_event_llm_evidence"),
        default=None,
        help="Required only for --stage baseline",
    )
    run_ea_parser.set_defaults(handler=_run_ea)

    run_ea_ablation_parser = subparsers.add_parser("run-ea-ablation")
    run_ea_ablation_parser.add_argument("--config", default="configs/ea_ablation.yaml")
    run_ea_ablation_parser.set_defaults(handler=_run_ea_ablation)

    gold_parser = subparsers.add_parser("prepare-ea-gold")
    gold_parser.add_argument("--config", default="configs/ea_pilot.yaml")
    gold_parser.add_argument(
        "--phase",
        choices=(
            "initialize",
            "disagreements",
            "export",
            "fusion_initialize",
            "fusion_disagreements",
            "fusion_export",
        ),
        required=True,
    )
    gold_parser.add_argument("--workspace", default=None)
    gold_parser.add_argument(
        "--blocked-pairs",
        default=None,
        help="JSON object containing blocked_pair_ids for fusion_export",
    )
    gold_parser.set_defaults(handler=_prepare_ea_gold)

    evaluation_parser = subparsers.add_parser("prepare-ea-evaluation")
    evaluation_parser.add_argument("--config", default="configs/ea_pilot.yaml")
    evaluation_parser.add_argument(
        "--task", choices=("end_to_end", "fusion"), default="end_to_end"
    )
    evaluation_parser.set_defaults(handler=_prepare_ea_evaluation)

    evaluate_parser = subparsers.add_parser("evaluate-ea")
    evaluate_parser.add_argument("--gold", required=True)
    evaluate_parser.add_argument(
        "--task", choices=("end_to_end", "fusion"), default="end_to_end"
    )
    evaluate_parser.add_argument("--prediction", required=True)
    evaluate_parser.add_argument(
        "--rules", default="configs/ea_semantic_equivalence_v1.yaml"
    )
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument(
        "--explanation-span-threshold", type=float, default=0.5
    )
    evaluate_parser.set_defaults(handler=_evaluate_ea)
    return parser


def _add_runtime_args(
    parser: argparse.ArgumentParser, *, include_settings: bool
) -> None:
    parser.add_argument("--resume", action="store_true", default=None)
    parser.add_argument("--max-api-concurrency", type=int, default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--diagnostic", action="store_true", default=None)
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument(
        "--event-ids",
        default=None,
        help="Comma-separated event IDs for diagnostic runs",
    )
    parser.add_argument("--skip-llm-verifier", action="store_true", default=None)
    if include_settings:
        parser.add_argument(
            "--settings", default=None, help="Comma-separated ablation settings to run"
        )


def _paper_status(args: argparse.Namespace) -> int:
    del args
    print(json.dumps(paper_status(), ensure_ascii=False, indent=2))
    return 0


def _run_paper(args: argparse.Namespace) -> int:
    result = run_paper_pipeline(
        args.config,
        resume=args.resume,
        max_api_concurrency=args.max_api_concurrency,
        cache_dir=args.cache_dir,
        diagnostic=args.diagnostic,
        max_events=args.max_events,
        event_ids=_split_csv(args.event_ids),
        skip_llm_verifier=args.skip_llm_verifier,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_ablation(args: argparse.Namespace) -> int:
    result = run_ablation_pipeline(
        args.config,
        force=args.force,
        resume=args.resume,
        max_api_concurrency=args.max_api_concurrency,
        cache_dir=args.cache_dir,
        diagnostic=args.diagnostic,
        max_events=args.max_events,
        event_ids=_split_csv(args.event_ids),
        settings=_split_csv(args.settings),
        skip_llm_verifier=args.skip_llm_verifier,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _ea_status(args: argparse.Namespace) -> int:
    return _print_ea_result(ea_status(args.config))


def _prepare_ea(args: argparse.Namespace) -> int:
    return _print_ea_result(prepare_ea(args.config))


def _run_ea(args: argparse.Namespace) -> int:
    return _print_ea_result(
        run_ea(
            args.config,
            stage=args.stage,
            fusion_method=args.fusion_method,
            baseline_method=args.method,
        )
    )


def _run_ea_ablation(args: argparse.Namespace) -> int:
    return _print_ea_result(run_ea_ablation(args.config))


def _prepare_ea_gold(args: argparse.Namespace) -> int:
    return _print_ea_result(
        prepare_ea_gold(
            args.config,
            phase=args.phase,
            workspace=args.workspace,
            blocked_pairs_path=args.blocked_pairs,
        )
    )


def _prepare_ea_evaluation(args: argparse.Namespace) -> int:
    return _print_ea_result(prepare_ea_evaluation(args.config, task=args.task))


def _evaluate_ea(args: argparse.Namespace) -> int:
    return _print_ea_result(
        evaluate_ea(
            gold_path=args.gold,
            prediction_path=args.prediction,
            rules_path=args.rules,
            output_path=args.output,
            explanation_span_threshold=args.explanation_span_threshold,
            task=args.task,
        )
    )


def _print_ea_result(result: dict[str, object]) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    successful = {
        "m1_ready",
        "m1_effect_gate_complete",
        "m2_ready_for_preparation",
        "m2_documents_ready",
        "m2_documents_prepared",
        "m2_effect_candidates_ready",
        "m2_effect_extraction_complete",
        "m3_core_complete",
        "m3_core_outputs_ready",
        "fusion_outputs_ready",
        "fusion_complete",
        "dossier_outputs_ready",
        "dossier_complete",
        "ea_full_pipeline_complete",
        "baseline_adapter_ready",
        "gold_workspace_initialized",
        "document_disagreement_queue_ready",
        "gold_export_complete",
        "fusion_gold_initialized",
        "fusion_gold_disagreements_ready",
        "fusion_gold_exported",
        "needs_canonical_adjudication",
        "m4_end_to_end_evaluation_manifest_ready",
        "m4_fusion_evaluation_manifest_ready",
        "m4_evaluation_complete",
        "m4_fusion_evaluation_complete",
        "m4_ablation_matrix_ready",
    }
    return 0 if result.get("status") in successful else 2


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
