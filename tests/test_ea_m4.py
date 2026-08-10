from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from episoa.ea.ablations import (
    AblationControls,
    AblationMatrix,
    build_ablation_matrix,
)
from episoa.ea.baselines import (
    METHOD_SPECS,
    ComparisonManifest,
    FairnessProtocol,
    build_comparison_manifest,
)
from episoa.ea.commands import (
    evaluate_ea,
    prepare_ea_evaluation,
    prepare_ea_gold,
    run_ea_ablation,
)
from episoa.ea.evaluation import (
    EMOTION_LABELS,
    METHOD_IDS,
    STANCE_LABELS,
    EvaluationBundle,
    EvaluationClaim,
    EvaluationEffect,
    EvaluationEvidenceSpan,
    GoldEvaluationDataset,
    RelationDecisionItem,
    SemanticEquivalenceRules,
    VerificationDecisionItem,
    adapt_method_output,
    attribution_claim_metrics,
    effect_value_macro_f1,
    evaluate_method,
    evidence_span_character_f1,
    relation_decision_macro_f1,
    stakeholder_category_f1,
    unsupported_claim_rate,
    verification_error_rates,
)
from episoa.ea.gold_workflow import (
    build_disagreement_queue,
    export_gold_dataset,
    initialize_gold_workspace,
)
from episoa.ea.schema import (
    AttributionClaim,
    DocumentRecord,
    EvidenceLink,
    SourceRecord,
    ViewpointEffect,
    content_hash,
)

TEXT = "居民反对夜间施工，因为噪声令人愤怒。"


def _source() -> SourceRecord:
    return SourceRecord(source_id="SRC-1", source_name="测试来源", source_type="news")


def _document(document_id: str = "DOC-1") -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        event_id="EV-1",
        reporting_source_id="SRC-1",
        primary_source_id="SRC-1",
        derivation_type="original",
        normalized_text=TEXT,
        content_hash=content_hash(TEXT),
    )


def _effect(effect_id: str = "EF-1", target: str = "夜间施工") -> ViewpointEffect:
    return ViewpointEffect(
        effect_id=effect_id,
        event_id="EV-1",
        document_id="DOC-1",
        reporting_source_id="SRC-1",
        primary_source_id="SRC-1",
        derivation_type="original",
        stakeholder_category="affected_public",
        holder_surface="居民",
        effect_type="stance",
        effect_surface="反对夜间施工",
        effect_value="oppose",
        target=target,
        effect_stage="conflict",
    )


def _claim(claim_id: str = "CL-1", effect_id: str = "EF-1") -> AttributionClaim:
    return AttributionClaim(
        claim_id=claim_id,
        effect_id=effect_id,
        event_id="EV-1",
        document_id="DOC-1",
        reporting_source_id="SRC-1",
        primary_source_id="SRC-1",
        derivation_type="original",
        explanation_surface="因为噪声令人愤怒",
        normalized_explanation="噪声令人愤怒",
        relation_type="stance_rationale",
        attribution_holder_category="affected_public",
        attribution_holder_surface="居民",
        claim_stage="conflict",
        explicitness="explicit",
        certainty="certain",
        polarity="affirmed",
    )


def _links(effect_ids: tuple[str, ...] = ("EF-1",), include_claim: bool = True):
    rows = []
    for effect_id in effect_ids:
        for index, field in enumerate(
            (
                "holder_surface",
                "stakeholder_category",
                "effect_type",
                "effect_value",
                "target",
                "effect_stage",
            )
        ):
            rows.append(
                EvidenceLink(
                    evidence_link_id=f"EL-{effect_id}-{index}",
                    target_type="effect",
                    target_id=effect_id,
                    document_id="DOC-1",
                    evidence_id=f"E-{effect_id}-{index}",
                    span_id=f"SP-{effect_id}-{index}",
                    char_start=0,
                    char_end=8,
                    span_text=TEXT[:8],
                    support_field=field,
                    support_label="supports",
                )
            )
    if include_claim:
        start = TEXT.index("因为")
        for index, field in enumerate(
            (
                "explanation_surface",
                "relation_type",
                "attribution_holder_surface",
                "attribution_holder_category",
                "explicitness",
                "certainty",
                "polarity",
            )
        ):
            rows.append(
                EvidenceLink(
                    evidence_link_id=f"EL-CL-1-{index}",
                    target_type="claim",
                    target_id="CL-1",
                    document_id="DOC-1",
                    evidence_id=f"E-CL-1-{index}",
                    span_id=f"SP-CL-1-{index}",
                    char_start=start,
                    char_end=len(TEXT) - 1,
                    span_text=TEXT[start:-1],
                    support_field=field,
                    support_label="supports",
                )
            )
    return rows


def _complete_sheet(path: Path, *, revise_effect_target: str | None = None) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = (
            list(rows[0])
            if rows
            else [
                "annotation_key",
                "item_type",
                "record_id",
                "document_id",
                "candidate_origin",
                "candidate_payload_json",
                "human_decision",
                "human_payload_json",
                "review_status",
                "annotator_id",
                "notes",
            ]
        )
    for row in rows:
        row["review_status"] = "completed"
        row["human_decision"] = "accept"
        if revise_effect_target and row["item_type"] == "effect":
            payload = json.loads(row["candidate_payload_json"])
            payload["target"] = revise_effect_target
            row["human_decision"] = "revise"
            row["human_payload_json"] = json.dumps(payload, ensure_ascii=False)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_gold_workflow_runs_from_empty_directory(tmp_path: Path):
    root = tmp_path / "gold"
    initialized = initialize_gold_workspace(root)
    assert initialized["candidate_count"] == 0
    assert build_disagreement_queue(root) == {
        "status": "document_disagreement_queue_ready",
        "agreements": 0,
        "needs_adjudication": 0,
    }
    exported = export_gold_dataset(root, sources=[], documents=[])
    assert exported["status"] == "gold_export_complete"
    assert (root / "gold" / "viewpoint_effects.jsonl").read_text() == ""


def test_llm_candidates_require_explicit_human_completion(tmp_path: Path):
    root = tmp_path / "gold"
    initialize_gold_workspace(root, effects=[_effect()])
    with pytest.raises(ValueError, match="candidates are not Gold"):
        build_disagreement_queue(root)


def test_ab_agreement_exports_valid_gold_and_hides_canonical_ids(tmp_path: Path):
    root = tmp_path / "gold"
    initialize_gold_workspace(
        root, effects=[_effect()], claims=[_claim()], evidence_links=_links()
    )
    sheet_text = (root / "annotator_A" / "document_annotations.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "canonical_effect_id" not in sheet_text
    assert "canonical_claim_group_id" not in sheet_text
    _complete_sheet(root / "annotator_A" / "document_annotations.csv")
    _complete_sheet(root / "annotator_B" / "document_annotations.csv")
    result = build_disagreement_queue(root)
    assert result["needs_adjudication"] == 0
    exported = export_gold_dataset(root, sources=[_source()], documents=[_document()])
    assert exported["status"] == "gold_export_complete"
    effect_payload = json.loads(
        (root / "gold" / "viewpoint_effects.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert effect_payload["canonical_effect_id"].startswith("ce_")


def test_only_ab_disagreement_goes_to_c(tmp_path: Path):
    root = tmp_path / "gold"
    initialize_gold_workspace(
        root, effects=[_effect()], claims=[_claim()], evidence_links=_links()
    )
    _complete_sheet(root / "annotator_A" / "document_annotations.csv")
    _complete_sheet(
        root / "annotator_B" / "document_annotations.csv",
        revise_effect_target="夜间作业",
    )
    result = build_disagreement_queue(root)
    assert result["needs_adjudication"] == 1
    c_path = root / "annotator_C" / "document_disagreements.csv"
    with c_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    assert rows[0]["item_type"] == "effect"
    rows[0]["c_decision"] = "choose_a"
    rows[0]["review_status"] = "completed"
    with c_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    exported = export_gold_dataset(root, sources=[_source()], documents=[_document()])
    assert exported["status"] == "gold_export_complete"


def test_gold_export_rejects_invalid_span(tmp_path: Path):
    root = tmp_path / "gold"
    links = _links(include_claim=False)
    links[0] = links[0].model_copy(update={"span_text": "错误证据"})
    initialize_gold_workspace(root, effects=[_effect()], evidence_links=links)
    _complete_sheet(root / "annotator_A" / "document_annotations.csv")
    _complete_sheet(root / "annotator_B" / "document_annotations.csv")
    build_disagreement_queue(root)
    with pytest.raises(ValueError, match="span_text_mismatch"):
        export_gold_dataset(root, sources=[_source()], documents=[_document()])


def test_gold_export_rejects_duplicate_record_ids(tmp_path: Path):
    root = tmp_path / "gold"
    initialize_gold_workspace(
        root,
        effects=[_effect()],
        evidence_links=_links(include_claim=False),
    )
    for annotator in ("A", "B"):
        path = root / f"annotator_{annotator}" / "document_annotations.csv"
        _complete_sheet(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            fields = list(rows[0])
        duplicate = dict(rows[0], annotation_key="effect:EF-1-duplicate")
        rows.append(duplicate)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    build_disagreement_queue(root)
    with pytest.raises(ValueError, match="duplicate_id"):
        export_gold_dataset(root, sources=[_source()], documents=[_document()])


def test_only_ambiguous_canonical_records_enter_queue(tmp_path: Path):
    root = tmp_path / "gold"
    effects = [_effect("EF-1", "夜间施工"), _effect("EF-2", "夜间施工噪声")]
    initialize_gold_workspace(
        root,
        effects=effects,
        evidence_links=_links(("EF-1", "EF-2"), include_claim=False),
    )
    _complete_sheet(root / "annotator_A" / "document_annotations.csv")
    _complete_sheet(root / "annotator_B" / "document_annotations.csv")
    build_disagreement_queue(root)
    result = export_gold_dataset(root, sources=[_source()], documents=[_document()])
    assert result["status"] == "needs_canonical_adjudication"
    queue = [
        json.loads(line)
        for line in (root / "annotator_C" / "canonical_adjudication_queue.jsonl")
        .read_text()
        .splitlines()
    ]
    assert queue and {row["status"] for row in queue} == {"needs_adjudication"}
    c_path = root / "annotator_C" / "canonical_adjudication.csv"
    with c_path.open("r", encoding="utf-8-sig", newline="") as handle:
        c_rows = list(csv.DictReader(handle))
        fields = list(c_rows[0])
    c_rows[0]["c_decision"] = "merge"
    c_rows[0]["review_status"] = "completed"
    with c_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(c_rows)
    completed = export_gold_dataset(root, sources=[_source()], documents=[_document()])
    assert completed["status"] == "gold_export_complete"
    exported_effects = [
        json.loads(line)
        for line in (root / "gold" / "viewpoint_effects.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len({row["canonical_effect_id"] for row in exported_effects}) == 1


def _eval_effect(
    effect_id: str,
    *,
    effect_type: str = "stance",
    effect_value: str = "support",
    category: str = "government",
) -> EvaluationEffect:
    return EvaluationEffect(
        effect_id=effect_id,
        document_id="DOC-1",
        stakeholder_category=category,
        effect_type=effect_type,
        effect_value=effect_value,
        target="项目",
    )


def _eval_claim(
    claim_id: str,
    *,
    holder: str | None = "government",
    explanation: str = "保障安全",
) -> EvaluationClaim:
    return EvaluationClaim(
        claim_id=claim_id,
        document_id="DOC-1",
        stakeholder_category="affected_public",
        effect_type="stance",
        effect_value="oppose",
        relation_type="stance_rationale",
        attribution_holder_category=holder,
        explanation=explanation,
    )


def _eval_span(target_id: str, start: int, end: int, text: str):
    return EvaluationEvidenceSpan(
        target_type="claim",
        target_id=target_id,
        document_id="DOC-1",
        support_field="explanation_surface",
        char_start=start,
        char_end=end,
        span_text=text,
    )


def test_exact_five_methods_share_one_adapter_and_protocol():
    assert tuple(row.method_id for row in METHOD_SPECS) == METHOD_IDS
    raw = {
        "effects": [
            {
                "effect_id": "EF-1",
                "document_id": "DOC-1",
                "stakeholder_category": "居民",
                "effect_type": "stance",
                "effect_value": "反对",
                "target": "项目",
            }
        ],
        "claims": [],
    }
    bundles = [
        adapt_method_output(method_id, document_ids=["DOC-1"], raw=raw)
        for method_id in METHOD_IDS
    ]
    assert {row.effects[0].stakeholder_category for row in bundles} == {
        "affected_public"
    }
    protocol = FairnessProtocol(
        document_set_hash="sha256:test",
        gold_version="gold-v1",
        split_version="split-v1",
    )
    manifest = build_comparison_manifest(
        protocol,
        model_name="mock",
        prompt_version="prompt-v1",
        decoding_version="decode-v1",
        seed=0,
        output_root="out",
    )
    assert len(manifest.runs) == 5
    broken = manifest.model_dump()
    broken["runs"][0]["protocol"]["gold_version"] = "different"
    with pytest.raises(ValidationError, match="all methods must share"):
        ComparisonManifest.model_validate(broken)


def test_original_episoa_missing_holder_is_preserved_not_imputed():
    bundle = adapt_method_output(
        "original_episoa",
        document_ids=["DOC-1"],
        raw={
            "effects": [],
            "claims": [
                {
                    "claim_id": "CL-1",
                    "document_id": "DOC-1",
                    "stakeholder_category": "政府",
                    "effect_type": "stance",
                    "effect_value": "支持",
                    "relation_type": "stance_rationale",
                    "explanation": "安全",
                }
            ],
        },
    )
    assert bundle.claims[0].attribution_holder_category is None
    with pytest.raises(KeyError):
        adapt_method_output(
            "long_context_event_llm",
            document_ids=["DOC-1"],
            raw={"effects": [{"effect_id": "EF-MISSING"}], "claims": []},
        )


def test_hand_calculated_effect_metrics_cover_duplicates_empty_and_macro_labels():
    gold = [_eval_effect("G")]
    duplicate_predictions = [_eval_effect("P1"), _eval_effect("P2")]
    assert stakeholder_category_f1(gold, duplicate_predictions)["f1"] == 0.666667
    assert stakeholder_category_f1(gold, [])["f1"] == 0.0
    stance = effect_value_macro_f1(
        gold, [_eval_effect("P")], effect_type="stance", labels=STANCE_LABELS
    )
    assert stance["macro_f1"] == 0.2
    emotion_gold = [_eval_effect("GE", effect_type="emotion", effect_value="positive")]
    emotion = effect_value_macro_f1(
        emotion_gold,
        [_eval_effect("PE", effect_type="emotion", effect_value="positive")],
        effect_type="emotion",
        labels=EMOTION_LABELS,
    )
    assert emotion["macro_f1"] == 0.25


def test_relation_macro_f1_uses_fixed_candidate_set():
    gold = [
        RelationDecisionItem(
            candidate_id=f"C-{index}", document_id="DOC-1", label=label
        )
        for index, label in enumerate(
            ("stance_rationale", "emotion_trigger", "action_motivation", "no_relation")
        )
    ]
    result = relation_decision_macro_f1(gold, gold[:3])
    assert result["macro_f1"] == 0.75
    with pytest.raises(ValueError, match="fixed Gold candidate set"):
        relation_decision_macro_f1(
            gold,
            [
                RelationDecisionItem(
                    candidate_id="EXTRA", document_id="DOC-1", label="no_relation"
                )
            ],
        )
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        relation_decision_macro_f1(gold, [gold[0], gold[0]])


def test_claim_f1_matches_span_or_semantic_rule_and_penalizes_duplicates():
    rules = SemanticEquivalenceRules(
        version="rules-v1", groups=[["保障安全", "出于安全考虑"]]
    )
    gold = [_eval_claim("G")]
    span_prediction = [_eval_claim("P", explanation="别的表述")]
    span_result = attribution_claim_metrics(
        gold,
        span_prediction,
        [_eval_span("G", 0, 4, "保障安全")],
        [_eval_span("P", 2, 6, "安全措施")],
        rules=rules,
    )
    assert span_result["matches"][0]["explanation_match_method"] == "span_overlap"
    semantic_result = attribution_claim_metrics(
        gold,
        [_eval_claim("P2", explanation="出于安全考虑")],
        [],
        [],
        rules=rules,
    )
    assert semantic_result["matches"][0]["explanation_match_method"] == "semantic_rule"
    duplicate_result = attribution_claim_metrics(
        gold,
        [_eval_claim("P3"), _eval_claim("P4")],
        [],
        [],
        rules=rules,
    )
    assert duplicate_result["f1"] == 0.666667
    assert attribution_claim_metrics(gold, [], [], [], rules=rules)["f1"] == 0.0


def test_holder_metrics_align_independently_from_claim_f1():
    rules = SemanticEquivalenceRules(version="rules-v1", groups=[])
    gold_claim = _eval_claim("G", holder="government")
    pred_claim = _eval_claim("P", holder="affected_public")
    gold = GoldEvaluationDataset(
        dataset_version="v1",
        document_ids=["DOC-1"],
        claims=[gold_claim],
    )
    prediction = EvaluationBundle(
        method_id="episoa_ea",
        document_ids=["DOC-1"],
        claims=[pred_claim],
    )
    result = evaluate_method(gold, prediction, semantic_rules=rules)
    assert result["attribution_claim"]["f1"] == 0.0
    assert result["attribution_holder_category_accuracy"]["accuracy"] == 0.0
    assert result["holder_category_mismatch_rate"]["rate"] == 1.0


def test_hand_calculated_span_unsupported_and_verifier_metrics():
    span = evidence_span_character_f1(
        [_eval_span("G", 0, 4, "abcd")], [_eval_span("P", 2, 6, "cdef")]
    )
    assert span["f1"] == 0.5
    unsupported = unsupported_claim_rate(
        [_eval_claim("C1"), _eval_claim("C2")], [_eval_span("C1", 0, 2, "ab")]
    )
    assert unsupported["rate"] == 0.5
    errors = verification_error_rates(
        [
            VerificationDecisionItem(
                candidate_id="1", gold_accept=True, predicted_status="rejected"
            ),
            VerificationDecisionItem(
                candidate_id="2", gold_accept=True, predicted_status="verified"
            ),
            VerificationDecisionItem(
                candidate_id="3", gold_accept=False, predicted_status="verified"
            ),
            VerificationDecisionItem(
                candidate_id="4", gold_accept=False, predicted_status="insufficient"
            ),
        ]
    )
    assert errors["false_acceptance_rate"] == 0.5
    assert errors["false_rejection_rate"] == 0.5
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        verification_error_rates(
            [
                VerificationDecisionItem(
                    candidate_id="duplicate",
                    gold_accept=True,
                    predicted_status="verified",
                ),
                VerificationDecisionItem(
                    candidate_id="duplicate",
                    gold_accept=False,
                    predicted_status="rejected",
                ),
            ]
        )


def test_ablation_matrix_changes_exactly_one_mechanism_and_no_controls():
    controls = AblationControls(
        document_set_hash="hash",
        gold_version="gold-v1",
        model_name="mock",
        prompt_base_version="prompt-v1",
        decoding_version="decode-v1",
        normalization_version="norm-v1",
        evaluator_version="eval-v1",
        seed=0,
    )
    matrix = build_ablation_matrix(controls, output_root="out")
    full = matrix.runs[0]
    for variant in matrix.runs[1:]:
        changed = [
            field
            for field in type(full.mechanisms).model_fields
            if getattr(full.mechanisms, field) != getattr(variant.mechanisms, field)
        ]
        assert len(changed) == 1
        assert variant.controls == full.controls
    broken = matrix.model_dump()
    broken["runs"][1]["controls"]["seed"] = 1
    with pytest.raises(ValidationError, match="changes controls"):
        AblationMatrix.model_validate(broken)


def test_m4_commands_materialize_tools_without_api_or_real_data(tmp_path: Path):
    payload = yaml.safe_load(
        Path("configs/ea_ablation.yaml").read_text(encoding="utf-8")
    )
    payload["output"] = {
        "runs_dir": str(tmp_path / "runs"),
        "cache_dir": str(tmp_path / "cache"),
    }
    payload["evaluation"]["gold_workspace"] = str(tmp_path / "gold-workflow")
    for key in payload["data"]:
        payload["data"][key] = str(tmp_path / "data" / f"{key}.jsonl")
    config_path = tmp_path / "ea_m4.yaml"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    gold = prepare_ea_gold(config_path, phase="initialize")
    evaluation = prepare_ea_evaluation(config_path)
    fusion_evaluation = prepare_ea_evaluation(config_path, task="fusion")
    ablation = run_ea_ablation(config_path)

    gold_path = tmp_path / "gold_eval.json"
    prediction_path = tmp_path / "prediction.json"
    rules_path = tmp_path / "rules.yaml"
    metrics_path = tmp_path / "metrics.json"
    gold_path.write_text(
        GoldEvaluationDataset(
            dataset_version="synthetic-v1", document_ids=["DOC-1"]
        ).model_dump_json(),
        encoding="utf-8",
    )
    prediction_path.write_text(
        EvaluationBundle(
            method_id="long_context_event_llm", document_ids=["DOC-1"]
        ).model_dump_json(),
        encoding="utf-8",
    )
    rules_path.write_text("version: rules-v1\ngroups: []\n", encoding="utf-8")
    evaluated = evaluate_ea(
        gold_path=gold_path,
        prediction_path=prediction_path,
        rules_path=rules_path,
        output_path=metrics_path,
    )

    assert gold["status"] == "gold_workspace_initialized"
    assert evaluation["method_count"] == 5
    assert evaluation["execution_started"] is False
    assert fusion_evaluation["method_count"] == 4
    fusion_manifest = json.loads(
        Path(fusion_evaluation["manifest_path"]).read_text(encoding="utf-8")
    )
    assert {row["method_id"] for row in fusion_manifest["runs"]} == {
        "exact",
        "embedding",
        "llm_pairwise",
        "apcf",
    }
    llm_runs = {
        row["method_id"]: row
        for row in fusion_manifest["runs"]
        if row["method_id"] in {"llm_pairwise", "apcf"}
    }
    assert llm_runs["llm_pairwise"]["judgment_resource_id"] == (
        llm_runs["apcf"]["judgment_resource_id"]
    )
    assert ablation["status"] == "m4_ablation_matrix_ready"
    assert ablation["execution_started"] is False
    assert evaluated["status"] == "m4_evaluation_complete"
    assert json.loads(metrics_path.read_text(encoding="utf-8"))["method_id"] == (
        "long_context_event_llm"
    )
