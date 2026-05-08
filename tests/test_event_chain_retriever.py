import csv
import importlib.util
import json
from pathlib import Path

from episoa.retrieval.event_chain_retriever import (
    EventChainRetriever,
    chain_confidence,
    compute_event_relevance_score,
    detect_generic_policy_content,
    score_evidence_for_stage,
)


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "retrieve_event_chains.py"
SPEC = importlib.util.spec_from_file_location("retrieve_event_chains_script", SCRIPT_PATH)
retrieve_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(retrieve_script)


def test_stage_keywords_are_recognized():
    assert score_evidence_for_stage("发布征收公告并启动改造", "news", "trigger") > 0.25
    assert score_evidence_for_stage("居民投诉补偿争议并质疑方案", "forum", "conflict") > 0.25
    assert score_evidence_for_stage("官方回应称部门表示将说明情况", "official", "response") > 0.25


def test_source_prior_affects_scores():
    official_score = score_evidence_for_stage("部门回应项目情况", "official", "response")
    web_score = score_evidence_for_stage("部门回应项目情况", "public_web", "response")

    assert official_score > web_score


def test_generic_policy_content_is_detected_and_penalized():
    result = detect_generic_policy_content("2026拆迁新政落地", "一文看懂房屋征收补偿标准有哪些")

    assert result["is_generic"] is True
    assert result["penalty"] > 0
    assert "2026拆迁新政" in result["matched_terms"]


def test_generic_policy_text_does_not_pass_event_relevance():
    event = event_row()
    evidence = evidence_row("generic", "E001", "news", "2026拆迁新政落地，一文看懂旧城改造补偿标准有哪些。")

    relevance = compute_event_relevance_score(event, evidence)

    assert relevance["score"] < 0.30
    assert relevance["is_generic_penalized"] is True


def test_event_specific_evidence_passes_relevance_gate():
    event = event_row()
    evidence = evidence_row("specific", "E001", "official", "明府城片区旧城改造补偿争议中，居民投诉院落补偿，住建局回应处理结果。")

    relevance = compute_event_relevance_score(event, evidence)

    assert relevance["score"] >= 0.30
    assert relevance["matched_seed_keywords"] or relevance["matched_event_name_terms"]


def test_same_evidence_is_not_repeated_across_stages():
    events = [event_row()]
    evidence = [
        evidence_row("a", "E001", "official", "明府城片区发布征收公告，居民投诉补偿争议，官方回应并说明处理结果。"),
    ]

    result = EventChainRetriever(top_k_per_stage=3, min_stage_score=0.20, min_event_relevance=0.30).retrieve_for_event(events[0], evidence)
    selected_ids = [ev["evidence_id"] for stage in result["stages"] for ev in stage["evidence"]]

    assert selected_ids == ["a"]
    assert result["retrieval_diagnostics"]["deduplicated_evidence_count"] > 0


def test_resolution_requires_strong_resolution_signal():
    weak = score_evidence_for_stage("项目持续推进补偿安置工作。", "official", "resolution")
    strong = score_evidence_for_stage("部门答复后续处理结果，完成整改并解决问题。", "official", "resolution")

    assert weak < 0.25
    assert strong > weak


def test_chain_confidence_depends_on_event_relevance():
    high = fake_stage_output(0.9)
    low = fake_stage_output(0.2)

    assert chain_confidence(high) > chain_confidence(low)


def test_single_event_generates_candidate_chain_with_top_k():
    events = [event_row()]
    evidence = [
        evidence_row("a", "E001", "news", "明府城片区发布征收公告并启动旧城改造。"),
        evidence_row("b", "E001", "forum", "明府城片区居民投诉补偿争议并质疑方案。"),
        evidence_row("c", "E001", "official", "明府城片区官方回应称部门表示将说明情况。"),
        evidence_row("d", "E001", "official", "明府城片区部门答复处理结果并完成整改。"),
    ]

    result = EventChainRetriever(top_k_per_stage=1, min_stage_score=0.25, min_event_relevance=0.30).retrieve_for_event(events[0], evidence)

    assert result["event_id"] == "E001"
    assert result["chain_id"] == "E001_CHAIN_CANDIDATE"
    assert result["chain_confidence"] > 0
    assert all(len(stage["evidence"]) <= 1 for stage in result["stages"])
    assert result["retrieval_diagnostics"]["num_evidence_considered"] == 4
    assert "trigger" not in result["missing_stages"]
    assert "conflict" not in result["missing_stages"]
    assert "response" not in result["missing_stages"]


def test_script_writes_outputs_and_does_not_create_gold(tmp_path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    output_dir = tmp_path / "run"
    gold = tmp_path / "gold_event_chains.jsonl"
    events.write_text(json.dumps(event_row(), ensure_ascii=False) + "\n", encoding="utf-8")
    evidence.write_text(
        "\n".join(
            [
                json.dumps(evidence_row("a", "E001", "news", "明府城片区发布征收公告并启动旧城改造。"), ensure_ascii=False),
                json.dumps(evidence_row("b", "E001", "forum", "明府城片区居民投诉补偿争议并质疑方案。"), ensure_ascii=False),
                json.dumps(evidence_row("c", "E001", "official", "明府城片区官方回应称部门表示将说明情况。"), ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code = retrieve_script.main(
        [
            "--events",
            str(events),
            "--evidence",
            str(evidence),
            "--graph-dir",
            str(tmp_path / "missing_graph"),
            "--output-dir",
            str(output_dir),
            "--top-k-per-stage",
            "2",
            "--min-stage-score",
            "0.25",
            "--min-event-relevance",
            "0.30",
            "--deduplicate-evidence-across-stages",
        ]
    )

    candidates = [json.loads(line) for line in (output_dir / "event_chain_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((output_dir / "event_chain_retrieval_summary.json").read_text(encoding="utf-8"))
    with (output_dir / "event_chain_retrieval_table.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with (output_dir / "event_chain_audit_sample.csv").open("r", encoding="utf-8", newline="") as handle:
        audit_rows = list(csv.DictReader(handle))

    assert code == 0
    assert candidates[0]["retrieval_diagnostics"]["graph_mode"] == "evidence_only"
    assert summary["num_events"] == 1
    assert "avg_chain_confidence" in summary
    assert "avg_event_relevance" in summary
    assert "event_relevance_score" in rows[0]
    assert "matched_event_name_terms" in rows[0]
    assert "generic_penalty_terms" in rows[0]
    assert audit_rows
    assert "stage_keyword_score" in audit_rows[0]
    assert not gold.exists()


def event_row() -> dict:
    return {
        "event_id": "E001",
        "event_name": "明府城片区旧城改造补偿争议",
        "event_description": "围绕明府城片区旧城改造补偿标准、院落补偿和居民利益表达形成的公共事件。",
        "seed_keywords": ["明府城 旧城改造 补偿", "院落补偿 争议"],
        "stakeholder_hints": ["居民", "住建局"],
    }


def evidence_row(evidence_id: str, event_id: str, source: str, text: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "event_id": event_id,
        "source": source,
        "domain": "example.test",
        "url": f"https://example.test/{evidence_id}",
        "title": text[:40],
        "text": text,
        "publish_time": "2025-01-01T00:00:00+08:00",
        "quality_score": 0.8,
    }


def fake_stage_output(relevance: float) -> list[dict]:
    evidence = {
        "evidence_id": "x",
        "final_stage_score": 0.7,
        "event_relevance_score": relevance,
        "source": "official",
        "domain": "example.test",
        "is_generic_penalized": False,
    }
    return [
        {"stage": "trigger", "evidence": [evidence]},
        {"stage": "conflict", "evidence": [evidence | {"evidence_id": "y"}]},
        {"stage": "response", "evidence": [evidence | {"evidence_id": "z"}]},
    ]
