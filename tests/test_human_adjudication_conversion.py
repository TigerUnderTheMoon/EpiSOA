import csv
import json
import subprocess
import sys
from pathlib import Path

from episoa.annotation.gold_annotation import infer_iaa_summary


ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def base_files(tmp_path: Path) -> tuple[Path, Path]:
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    write_jsonl(events, [{"event_id": "E1", "domain": "education"}])
    write_jsonl(evidence, [{"event_id": "E1", "evidence_id": "ev1", "text": "supporting evidence text"}])
    return events, evidence


def run_convert(
    tmp_path: Path,
    tuple_rows: list[dict],
    chain_rows: list[dict],
    check: bool = True,
    dataset_version: str | None = None,
    include_evidence_spans: bool = False,
    iaa_report: Path | None = None,
):
    events, evidence = base_files(tmp_path)
    tuple_sheet = tmp_path / "tuple.csv"
    chain_sheet = tmp_path / "chain.csv"
    write_csv(tuple_sheet, tuple_rows)
    write_csv(chain_sheet, chain_rows)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "convert_adjudication_to_human_gold.py"),
        "--tuple-sheet",
        str(tuple_sheet),
        "--chain-sheet",
        str(chain_sheet),
        "--events",
        str(events),
        "--evidence",
        str(evidence),
        "--output-dir",
        str(tmp_path / "human_gold"),
    ]
    if dataset_version:
        command.extend(["--dataset-version", dataset_version])
    if include_evidence_spans:
        command.append("--include-evidence-spans")
    if iaa_report:
        command.extend(["--iaa-report", str(iaa_report)])
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def test_convert_handles_accept_revise_drop_add_missing_and_uncertain(tmp_path):
    tuple_rows = [
        row("T_accept", "accept", stakeholder="old", opinion="keep", sentiment="neutral", evidence_ids="ev1"),
        row("T_revise", "revise", revised_stakeholder="new", revised_opinion="changed", revised_sentiment="positive", revised_rationale="new rationale", revised_evidence_ids="ev1"),
        row("T_drop", "drop", stakeholder="drop", opinion="drop", sentiment="negative", evidence_ids="ev1"),
        row("T_uncertain", "uncertain", stakeholder="uncertain", opinion="uncertain", sentiment="neutral", evidence_ids="ev1"),
        row("", "add_missing", revised_stakeholder="added", revised_opinion="missing tuple", revised_sentiment="mixed", revised_rationale="added rationale", revised_evidence_ids="ev1"),
    ]
    chain_rows = [
        {"event_id": "E1", "chain_id": "C1", "event_chain": "start -> end", "evidence_ids": "ev1", "review_decision": "accept", "adjudication_status": "adjudicated_final"}
    ]

    run_convert(tmp_path, tuple_rows, chain_rows)

    tuples = read_jsonl(tmp_path / "human_gold" / "human_gold_tuples_v1.jsonl")
    assert [item["review_decision"] for item in tuples] == ["accept", "revise", "add_missing"]
    assert tuples[1]["stakeholder"] == "new"
    assert tuples[1]["opinion"] == "changed"
    assert tuples[2]["tuple_id"].startswith("HG_E1_")
    log_text = (tmp_path / "human_gold" / "rejected_or_uncertain_log.csv").read_text(encoding="utf-8-sig")
    assert "T_drop" in log_text
    assert "T_uncertain" in log_text
    manifest = json.loads((tmp_path / "human_gold" / "human_gold_manifest_v1.json").read_text(encoding="utf-8"))
    assert manifest["dataset_level"] == "human_gold"
    assert manifest["human_verified"] is True
    assert manifest["ready_for_main_experiment"] is False


def test_invalid_evidence_id_fails_conversion(tmp_path):
    tuple_rows = [row("T_bad", "accept", stakeholder="x", opinion="y", sentiment="neutral", evidence_ids="missing")]
    chain_rows = [{"event_id": "E1", "chain_id": "C1", "event_chain": "start", "evidence_ids": "ev1", "review_decision": "accept", "adjudication_status": "adjudicated_final"}]

    result = run_convert(tmp_path, tuple_rows, chain_rows, check=False)

    assert result.returncode != 0
    assert "unknown evidence_id missing" in (result.stderr + result.stdout)


def test_non_final_rows_are_excluded_from_human_gold(tmp_path):
    tuple_rows = [row("T1", "accept", stakeholder="x", opinion="y", sentiment="neutral", evidence_ids="ev1")]
    tuple_rows[0]["adjudication_status"] = "independent_review"
    chain_rows = [{"event_id": "E1", "chain_id": "C1", "event_chain": "start", "evidence_ids": "ev1", "review_decision": "accept", "adjudication_status": "independent_review"}]

    run_convert(tmp_path, tuple_rows, chain_rows)

    assert read_jsonl(tmp_path / "human_gold" / "human_gold_tuples_v1.jsonl") == []
    log_text = (tmp_path / "human_gold" / "rejected_or_uncertain_log.csv").read_text(encoding="utf-8-sig")
    assert "excluded_by_not_adjudicated_final" in log_text


def test_dataset_version_v2_changes_output_filenames(tmp_path):
    tuple_rows = [row("T1", "accept", stakeholder="x", opinion="y", sentiment="neutral", evidence_ids="ev1")]
    chain_rows = [{"event_id": "E1", "chain_id": "C1", "event_chain": "start", "evidence_ids": "ev1", "review_decision": "accept", "adjudication_status": "adjudicated_final"}]

    run_convert(tmp_path, tuple_rows, chain_rows, dataset_version="v2")

    output_dir = tmp_path / "human_gold"
    assert (output_dir / "human_gold_tuples_v2.jsonl").exists()
    assert (output_dir / "human_gold_event_chains_v2.jsonl").exists()
    assert (output_dir / "human_gold_manifest_v2.json").exists()
    assert not (output_dir / "human_gold_tuples_v1.jsonl").exists()
    manifest = json.loads((output_dir / "human_gold_manifest_v2.json").read_text(encoding="utf-8"))
    assert manifest["dataset_name"] == "pubevent_soa_lite_human_gold_v2"
    assert manifest["dataset_version"] == "v2"


def test_include_evidence_spans_writes_tuple_spans(tmp_path):
    tuple_rows = [row("T1", "accept", stakeholder="x", opinion="y", sentiment="neutral", evidence_ids="ev1")]
    chain_rows = [{"event_id": "E1", "chain_id": "C1", "event_chain": "start", "evidence_ids": "ev1", "review_decision": "accept", "adjudication_status": "adjudicated_final"}]

    run_convert(tmp_path, tuple_rows, chain_rows, dataset_version="v2", include_evidence_spans=True)

    tuples = read_jsonl(tmp_path / "human_gold" / "human_gold_tuples_v2.jsonl")
    assert tuples[0]["evidence_spans"] == [{
        "evidence_id": "ev1",
        "char_start": 0,
        "char_end": len("supporting evidence text"),
        "text": "supporting evidence text",
    }]
    manifest = json.loads((tmp_path / "human_gold" / "human_gold_manifest_v2.json").read_text(encoding="utf-8"))
    assert manifest["paper_grade_metadata"]["include_evidence_spans"] is True
    assert manifest["counts"]["tuples_with_evidence_spans"] == 1


def test_iaa_report_embeds_annotation_quality(tmp_path):
    tuple_rows = [row("T1", "accept", stakeholder="x", opinion="y", sentiment="neutral", evidence_ids="ev1")]
    chain_rows = [{"event_id": "E1", "chain_id": "C1", "event_chain": "start", "evidence_ids": "ev1", "review_decision": "accept", "adjudication_status": "adjudicated_final"}]
    iaa_report = tmp_path / "iaa.json"
    iaa_report.write_text(json.dumps({
        "status": "completed",
        "conflict_count": 0,
        "tuple_iaa": {"items": 1, "fleiss_kappa": 0.91, "krippendorff_alpha": 0.92},
    }), encoding="utf-8")

    run_convert(tmp_path, tuple_rows, chain_rows, dataset_version="v2", iaa_report=iaa_report)

    tuples = read_jsonl(tmp_path / "human_gold" / "human_gold_tuples_v2.jsonl")
    quality = tuples[0]["annotation_provenance"]["annotation_quality"]
    assert quality["cohen_kappa"] == 0.91
    assert quality["tuple_cohen_kappa"] == 0.91
    assert quality["support_label_cohen_kappa"] == 0.91
    assert quality["krippendorff_alpha"] == 0.92
    assert infer_iaa_summary(tuples)["meets_minimum"] is True


def row(tuple_id: str, decision: str, **kwargs) -> dict:
    base = {
        "event_id": "E1",
        "tuple_id": tuple_id,
        "stakeholder": kwargs.pop("stakeholder", ""),
        "opinion": kwargs.pop("opinion", ""),
        "sentiment": kwargs.pop("sentiment", ""),
        "rationale": kwargs.pop("rationale", "rationale"),
        "evidence_ids": kwargs.pop("evidence_ids", ""),
        "review_decision": decision,
        "adjudication_status": "adjudicated_final",
        "revised_stakeholder": "",
        "revised_opinion": "",
        "revised_sentiment": "",
        "revised_rationale": "",
        "revised_evidence_ids": "",
    }
    base.update(kwargs)
    return base
