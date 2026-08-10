"""CLI-facing EA milestone commands."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from episoa.data.loader import read_typed_jsonl
from episoa.ea.ablations import (
    AblationControls,
    build_ablation_matrix,
    build_fusion_ablation_matrix,
)
from episoa.ea.baselines import FairnessProtocol, build_comparison_manifest
from episoa.ea.config import (
    EA_ABLATION_SETTINGS,
    EA_FUSION_ABLATION_SETTINGS,
    load_ea_config,
)
from episoa.ea.evaluation import (
    EVALUATOR_VERSION,
    NORMALIZATION_VERSION,
    EvaluationBundle,
    GoldEvaluationDataset,
    evaluate_method,
)
from episoa.ea.extraction import EffectExtractionClient
from episoa.ea.fusion_evaluation import (
    FusionComparisonManifest,
    FusionMethodRunSpec,
    canonicalization_metrics,
)
from episoa.ea.fusion_gold import (
    build_fusion_gold_disagreements,
    export_fusion_gold,
    initialize_fusion_gold_workspace,
)
from episoa.ea.gold_workflow import (
    build_disagreement_queue,
    export_gold_dataset,
    initialize_gold_workspace,
)
from episoa.ea.m3 import M3Clients
from episoa.ea.matching import load_semantic_equivalence_rules
from episoa.ea.pipeline import (
    prepare_m2_documents,
    run_dossier_pipeline,
    run_fusion_pipeline,
    run_m2_effect_extraction,
    run_m3_pipeline,
)
from episoa.ea.schema import (
    AttributionClaim,
    DocumentRecord,
    EvidenceLink,
    SourceRecord,
    ViewpointEffect,
)
from episoa.llm.client import build_llm_client


def ea_status(config_path: str | Path) -> dict[str, object]:
    config = load_ea_config(config_path)
    source_status = _typed_file_status(config.data["sources_path"], SourceRecord)
    document_status = _typed_file_status(config.data["documents_path"], DocumentRecord)
    process_outputs = {
        key: Path(config.data[key]).is_file()
        for key in (
            "effect_candidates_path",
            "evidence_links_path",
            "extraction_attempts_path",
        )
    }
    documents_ready = bool(source_status["ready"] and document_status["ready"])
    extraction_ready = documents_ready and all(process_outputs.values())
    m3_inputs_ready = documents_ready and all(
        Path(config.data[key]).is_file()
        for key in ("effect_candidates_path", "evidence_links_path")
    )
    m3_outputs = {
        key: Path(config.data[key]).is_file()
        for key in (
            "explanation_candidates_path",
            "relation_judgments_path",
            "verification_diagnostics_path",
            "viewpoint_effects_path",
            "attribution_claims_path",
            "m3_attempts_path",
        )
    }
    m3_ready = m3_inputs_ready and all(m3_outputs.values())
    fusion_outputs = {
        key: Path(config.data[key]).is_file()
        for key in (
            "canonical_effects_path",
            "canonical_claim_groups_path",
            "claim_pair_relations_path",
            "fusion_pair_judgments_path",
            "fusion_cluster_diagnostics_path",
            "canonical_adjudication_queue_path",
        )
    }
    fusion_ready = m3_ready and all(fusion_outputs.values())
    dossier_ready = fusion_ready and Path(config.data["event_dossiers_path"]).is_file()
    if dossier_ready:
        status = "dossier_outputs_ready"
    elif fusion_ready:
        status = "fusion_outputs_ready"
    elif m3_ready:
        status = "m3_core_outputs_ready"
    elif m3_inputs_ready:
        status = "m2_effect_candidates_ready"
    elif documents_ready:
        status = "m2_documents_ready"
    else:
        status = "m2_ready_for_preparation"
    return {
        "status": status,
        "run_id": config.run_id,
        "mode": config.mode,
        "legacy_paths_isolated": True,
        "schema_ready": True,
        "sources": source_status,
        "documents": document_status,
        "ready_for_effect_extraction": documents_ready,
        "m2_process_outputs_ready": extraction_ready,
        "process_outputs": process_outputs,
        "ready_for_m3": m3_inputs_ready,
        "m3_outputs_ready": m3_ready,
        "m3_outputs": m3_outputs,
        "fusion_outputs_ready": fusion_ready,
        "fusion_outputs": fusion_outputs,
        "dossier_output_ready": dossier_ready,
        "m4_offline_tools_ready": True,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
        "blocking_stages": [
            "M5_six_event_pilot",
        ],
    }


def prepare_ea(config_path: str | Path) -> dict[str, object]:
    config = load_ea_config(config_path)
    raw_path = Path(config.data["raw_posts_path"])
    if not raw_path.is_file():
        return {
            "status": "blocked",
            "run_id": config.run_id,
            "reason": "missing M2 raw document input",
            "missing_paths": [str(raw_path)],
            "ready_for_pilot": False,
            "ready_for_formal_collection": False,
        }
    try:
        return prepare_m2_documents(config)
    except (OSError, ValueError) as exc:
        return {
            "status": "invalid_input",
            "run_id": config.run_id,
            "reason": str(exc),
            "ready_for_pilot": False,
            "ready_for_formal_collection": False,
        }


def run_ea(
    config_path: str | Path,
    *,
    stage: str | None = None,
    fusion_method: str = "apcf",
    baseline_method: str | None = None,
    llm_client: EffectExtractionClient | None = None,
    m3_clients: M3Clients | None = None,
) -> dict[str, object]:
    config = load_ea_config(config_path)
    if stage not in {None, "m2", "m3", "fusion", "dossier", "baseline"}:
        raise ValueError("run-ea stage must be m2, m3, fusion, dossier, or baseline")
    if stage is None:
        required = [config.data["sources_path"], config.data["documents_path"]]
        missing = [path for path in required if not Path(path).is_file()]
        if missing:
            return {
                "status": "blocked",
                "run_id": config.run_id,
                "reason": "missing prepared Documents; run prepare-ea first",
                "missing_paths": missing,
                "ready_for_pilot": False,
                "ready_for_formal_collection": False,
            }
        client = llm_client or build_llm_client(config.model)
        m2 = run_m2_effect_extraction(config, client)
        shared = m3_clients or M3Clients(client, client, client)
        m3 = run_m3_pipeline(config, shared)
        fusion = run_fusion_pipeline(config, method=fusion_method)
        dossier = run_dossier_pipeline(config)
        return {
            "status": "ea_full_pipeline_complete",
            "run_id": config.run_id,
            "stages": {"m2": m2, "m3": m3, "fusion": fusion, "dossier": dossier},
            "ready_for_pilot": False,
            "ready_for_formal_collection": False,
        }
    if stage == "fusion":
        return run_fusion_pipeline(config, method=fusion_method)
    if stage == "dossier":
        return run_dossier_pipeline(config)
    if stage == "baseline":
        if baseline_method not in {
            "long_context_event_llm",
            "long_context_event_llm_evidence",
        }:
            raise ValueError(
                "baseline stage requires --method long_context_event_llm or "
                "long_context_event_llm_evidence"
            )
        return {
            "status": "baseline_adapter_ready",
            "run_id": config.run_id,
            "method_id": baseline_method,
            "reason": "run requires a frozen Long-context capacity manifest and client",
            "ready_for_pilot": False,
            "ready_for_formal_collection": False,
        }
    if stage == "m3":
        required = [
            config.data["sources_path"],
            config.data["documents_path"],
            config.data["effect_candidates_path"],
            config.data["evidence_links_path"],
        ]
        missing = [path for path in required if not Path(path).is_file()]
        if missing:
            return {
                "status": "blocked",
                "run_id": config.run_id,
                "reason": "missing prepared M3 document/Effect inputs",
                "missing_paths": missing,
                "ready_for_pilot": False,
                "ready_for_formal_collection": False,
            }
        if m3_clients is None:
            shared_client = llm_client or build_llm_client(config.model)
            m3_clients = M3Clients(shared_client, shared_client, shared_client)
        return run_m3_pipeline(config, m3_clients)
    required = [
        config.data["sources_path"],
        config.data["documents_path"],
    ]
    missing = [path for path in required if not Path(path).is_file()]
    if missing:
        return {
            "status": "blocked",
            "run_id": config.run_id,
            "reason": "missing prepared M2 SourceRecord/DocumentRecord inputs",
            "missing_paths": missing,
            "ready_for_pilot": False,
            "ready_for_formal_collection": False,
        }
    client = llm_client or build_llm_client(config.model)
    return run_m2_effect_extraction(config, client)


def run_ea_ablation(config_path: str | Path) -> dict[str, object]:
    config = load_ea_config(config_path)
    controls = _ablation_controls(config)
    matrix = build_ablation_matrix(controls, output_root=config.output["runs_dir"])
    resource_id = str(
        config.evaluation.get("judgment_resource_id", "pending-m5-pair-resource")
    )
    fusion_matrix = build_fusion_ablation_matrix(
        controls,
        judgment_resource_id=resource_id,
        output_root=f"{config.output['runs_dir']}/fusion",
    )
    target = Path(config.output["runs_dir"]) / "m4_ablation_matrix.json"
    _write_json(target, matrix.model_dump(mode="json"))
    fusion_target = Path(config.output["runs_dir"]) / "m4_fusion_ablation_matrix.json"
    _write_json(fusion_target, fusion_matrix.model_dump(mode="json"))
    return {
        "status": "m4_ablation_matrix_ready",
        "run_id": config.run_id,
        "settings": list(config.ablation.get("settings", []))
        or [*EA_ABLATION_SETTINGS, *EA_FUSION_ABLATION_SETTINGS],
        "matrix_path": str(target),
        "fusion_matrix_path": str(fusion_target),
        "execution_started": False,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
    }


def prepare_ea_gold(
    config_path: str | Path,
    *,
    phase: str,
    workspace: str | Path | None = None,
    blocked_pairs_path: str | Path | None = None,
) -> dict[str, object]:
    """Run one explicit phase of the A/B/C Gold workflow without an API."""
    config = load_ea_config(config_path)
    root = Path(
        workspace
        or config.evaluation.get("gold_workspace", "data/pubevent_soa_ea/gold_workflow")
    )
    if phase == "initialize":
        effects = _optional_typed(
            config.data["viewpoint_effects_path"], ViewpointEffect
        )
        claims = _optional_typed(
            config.data["attribution_claims_path"], AttributionClaim
        )
        links = _optional_typed(config.data["evidence_links_path"], EvidenceLink)
        return initialize_gold_workspace(
            root, effects=effects, claims=claims, evidence_links=links
        )
    if phase == "disagreements":
        return build_disagreement_queue(root)
    if phase == "export":
        sources = _require_typed(config.data["sources_path"], SourceRecord)
        documents = _require_typed(config.data["documents_path"], DocumentRecord)
        return export_gold_dataset(root, sources=sources, documents=documents)
    if phase == "fusion_initialize":
        return initialize_fusion_gold_workspace(
            root,
            effects=_require_typed(config.data["viewpoint_effects_path"], ViewpointEffect),
            claims=_require_typed(config.data["attribution_claims_path"], AttributionClaim),
        )
    if phase == "fusion_disagreements":
        return build_fusion_gold_disagreements(root)
    if phase == "fusion_export":
        if blocked_pairs_path is None:
            raise ValueError("fusion_export requires --blocked-pairs")
        payload = _read_json(blocked_pairs_path)
        blocked_pair_ids = payload.get("blocked_pair_ids")
        if not isinstance(blocked_pair_ids, list) or not all(
            isinstance(value, str) for value in blocked_pair_ids
        ):
            raise ValueError(
                "blocked-pairs JSON must contain a string list named blocked_pair_ids"
            )
        return export_fusion_gold(
            root,
            blocked_pair_ids=set(blocked_pair_ids),
            threshold=float(config.evaluation.get("blocking_recall_threshold", 0.98)),
        )
    raise ValueError(
        "Gold phase must be initialize, disagreements, export, fusion_initialize, "
        "fusion_disagreements, or fusion_export"
    )


def prepare_ea_evaluation(
    config_path: str | Path, *, task: str = "end_to_end"
) -> dict[str, object]:
    """Write the task-appropriate fairness manifest; do not execute any method."""
    config = load_ea_config(config_path)
    evaluation = config.evaluation
    if task not in {"end_to_end", "fusion"}:
        raise ValueError("evaluation task must be end_to_end or fusion")
    document_set_hash = _document_set_hash(config.data["documents_path"])
    gold_version = str(evaluation.get("gold_version", "pending-m5-gold"))
    model_name = str(config.model.get("llm_model", "unconfigured-model"))
    model_release = str(config.model.get("model_version", model_name))
    model_version = f"{model_name}@{model_release}"
    temperature = float(config.model.get("temperature", 0.0))
    token_budget = int(config.model.get("max_tokens", 0))
    prompt_version = str(
        evaluation.get("semantic_pair_prompt_version", "ea-fusion-semantic-v1")
    )
    decoding_version = str(evaluation.get("decoding_version", "temperature-0-v1"))
    if task == "fusion":
        shared = {
            "candidate_set_hash": str(
                evaluation.get("fusion_candidate_set_hash", document_set_hash)
            ),
            "normalization_version": NORMALIZATION_VERSION,
            "gold_version": gold_version,
            "judgment_resource_id": str(
                evaluation.get("judgment_resource_id", "pending-m5-pair-resource")
            ),
            "model_version": model_version,
            "prompt_version": prompt_version,
            "decoding_version": decoding_version,
            "temperature": temperature,
            "token_budget": token_budget,
        }
        manifest = FusionComparisonManifest(
            runs=[
                FusionMethodRunSpec(method_id=method_id, **shared)
                for method_id in ("exact", "embedding", "llm_pairwise", "apcf")
            ]
        )
        target = Path(config.output["runs_dir"]) / "m4_fusion_comparison_manifest.json"
        _write_json(target, manifest.model_dump(mode="json"))
        return {
            "status": "m4_fusion_evaluation_manifest_ready",
            "task": task,
            "run_id": config.run_id,
            "method_count": len(manifest.runs),
            "manifest_path": str(target),
            "execution_started": False,
            "ready_for_pilot": False,
            "ready_for_formal_collection": False,
        }
    protocol = FairnessProtocol(
        document_set_hash=document_set_hash,
        gold_version=gold_version,
        split_version=str(evaluation.get("split_version", "pending-m5-split")),
    )
    manifest = build_comparison_manifest(
        protocol,
        model_name=model_version,
        prompt_version=str(
            evaluation.get("prompt_version", "ea-m4-prompt-contract-v1")
        ),
        decoding_version=str(evaluation.get("decoding_version", "temperature-0-v1")),
        seed=int(evaluation.get("seed", 0)),
        output_root=f"{config.output['runs_dir']}/methods",
        token_budget=token_budget,
    )
    target = Path(config.output["runs_dir"]) / "m4_comparison_manifest.json"
    _write_json(target, manifest.model_dump(mode="json"))
    return {
        "status": f"m4_{task}_evaluation_manifest_ready",
        "task": task,
        "run_id": config.run_id,
        "method_count": len(manifest.runs),
        "manifest_path": str(target),
        "execution_started": False,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
    }


def evaluate_ea(
    *,
    gold_path: str | Path,
    prediction_path: str | Path,
    rules_path: str | Path,
    output_path: str | Path,
    explanation_span_threshold: float = 0.5,
    task: str = "end_to_end",
) -> dict[str, object]:
    """Evaluate one adapted method bundle with the shared frozen evaluator."""
    if task == "fusion":
        gold_payload = _read_json(gold_path)
        prediction_payload = _read_json(prediction_path)
        result = canonicalization_metrics(
            dict(gold_payload.get("membership", {})),
            dict(prediction_payload.get("membership", {})),
            excluded_pairs={
                tuple(sorted(pair)) for pair in gold_payload.get("excluded_pairs", [])
            },
        )
        _write_json(Path(output_path), result)
        return {
            "status": "m4_fusion_evaluation_complete",
            "output_path": str(output_path),
        }
    if task != "end_to_end":
        raise ValueError("evaluation task must be end_to_end or fusion")
    gold = GoldEvaluationDataset.model_validate(_read_json(gold_path))
    prediction = EvaluationBundle.model_validate(_read_json(prediction_path))
    rules = load_semantic_equivalence_rules(rules_path)
    result = evaluate_method(
        gold,
        prediction,
        semantic_rules=rules,
        explanation_span_threshold=explanation_span_threshold,
    )
    _write_json(Path(output_path), result)
    return {
        "status": "m4_evaluation_complete",
        "method_id": prediction.method_id,
        "output_path": str(output_path),
    }


def _typed_file_status(path: str, record_type) -> dict[str, object]:
    target = Path(path)
    if not target.is_file():
        return {"ready": False, "path": path, "count": 0, "error": "missing"}
    try:
        rows = read_typed_jsonl(target, record_type)
    except (OSError, ValueError) as exc:
        return {"ready": False, "path": path, "count": 0, "error": str(exc)}
    return {"ready": bool(rows), "path": path, "count": len(rows), "error": None}


def _optional_typed(path: str, record_type):
    return read_typed_jsonl(path, record_type) if Path(path).is_file() else []


def _require_typed(path: str, record_type):
    if not Path(path).is_file():
        raise FileNotFoundError(f"required M4 input not found: {path}")
    return read_typed_jsonl(path, record_type)


def _document_set_hash(path: str) -> str:
    documents = _optional_typed(path, DocumentRecord)
    serialized = "\n".join(
        f"{row.document_id}:{row.content_hash}"
        for row in sorted(documents, key=lambda item: item.document_id)
    )
    if not serialized:
        return "pending-m5-document-set"
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _ablation_controls(config) -> AblationControls:
    evaluation = config.evaluation
    return AblationControls(
        document_set_hash=_document_set_hash(config.data["documents_path"]),
        gold_version=str(evaluation.get("gold_version", "pending-m5-gold")),
        model_name=str(config.model.get("llm_model", "unconfigured-model")),
        prompt_base_version=str(
            evaluation.get("prompt_version", "ea-m4-prompt-contract-v1")
        ),
        decoding_version=str(evaluation.get("decoding_version", "temperature-0-v1")),
        normalization_version=NORMALIZATION_VERSION,
        evaluator_version=EVALUATOR_VERSION,
        seed=int(evaluation.get("seed", 0)),
    )


def _read_json(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
