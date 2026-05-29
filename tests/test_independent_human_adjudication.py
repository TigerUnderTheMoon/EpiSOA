import csv
from pathlib import Path

from scripts.build_independent_human_adjudication import (
    audit_independent_annotations,
    fleiss_kappa,
    materialize_consensus_sheets,
    prepare_independent_sheets,
    tuple_sheet_filename,
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_fleiss_kappa_identifies_perfect_agreement():
    assert fleiss_kappa([[3, 0, 0], [0, 3, 0]]) == 1.0


def test_prepare_and_audit_independent_sheets(tmp_path):
    tuple_sheet = tmp_path / "tuple.csv"
    chain_sheet = tmp_path / "chain.csv"
    write_csv(tuple_sheet, [{"event_id": "E1", "tuple_id": "T1", "review_decision": "uncertain"}])
    write_csv(chain_sheet, [{"event_id": "E1", "chain_id": "C1", "review_decision": "uncertain"}])

    prepared = prepare_independent_sheets(
        tuple_sheet=tuple_sheet,
        chain_sheet=chain_sheet,
        output_dir=tmp_path / "independent",
        annotators=("annotator_A", "annotator_B", "annotator_C"),
    )

    assert prepared["tuple_rows"] == 1
    tuple_paths = []
    chain_paths = []
    for annotator in ("annotator_A", "annotator_B", "annotator_C"):
        tuple_path = tmp_path / "independent" / annotator / tuple_sheet_filename(annotator)
        chain_path = tmp_path / "independent" / annotator / "human_chain_adjudication_sheet.csv"
        tuple_paths.append(tuple_path)
        chain_paths.append(chain_path)
        rows = list(csv.DictReader(tuple_path.open(encoding="utf-8-sig", newline="")))
        rows[0]["review_decision"] = "accept" if annotator != "annotator_C" else "drop"
        write_csv(tuple_path, rows)
        chain_rows = list(csv.DictReader(chain_path.open(encoding="utf-8-sig", newline="")))
        chain_rows[0]["review_decision"] = "accept"
        write_csv(chain_path, chain_rows)

    report = audit_independent_annotations(
        tuple_sheets=tuple_paths,
        chain_sheets=chain_paths,
        output_dir=tmp_path / "audit",
    )

    assert report["conflict_count"] == 1
    assert report["chain_iaa"]["fleiss_kappa"] == 1.0
    assert (tmp_path / "audit" / "adjudication_conflict_sheet.csv").exists()


def test_independent_tuple_sheet_names_are_annotator_specific():
    assert tuple_sheet_filename("annotator_A") == "humanA_tuple_adjudication_sheet.csv"
    assert tuple_sheet_filename("annotator_B") == "humanB_tuple_adjudication_sheet.csv"
    assert tuple_sheet_filename("annotator_C") == "humanC_tuple_adjudication_sheet.csv"


def test_materialize_consensus_sheets_writes_final_inputs(tmp_path):
    tuple_paths = []
    chain_paths = []
    for annotator in ("annotator_A", "annotator_B", "annotator_C"):
        annotator_dir = tmp_path / annotator
        tuple_path = annotator_dir / tuple_sheet_filename(annotator)
        chain_path = annotator_dir / "human_chain_adjudication_sheet.csv"
        tuple_paths.append(tuple_path)
        chain_paths.append(chain_path)
        write_csv(tuple_path, [{
            "event_id": "E1",
            "tuple_id": "T1",
            "stakeholder": "stakeholder",
            "opinion": "opinion",
            "sentiment": "neutral",
            "rationale": "rationale",
            "evidence_ids": "ev1",
            "review_decision": "accept",
            "reviewer_id": annotator,
            "annotator_id": annotator,
            "adjudication_status": "adjudicated_final",
            "reviewer_note": "agreed",
        }])
        write_csv(chain_path, [{
            "event_id": "E1",
            "chain_id": "C1",
            "event_chain": "start -> end",
            "evidence_ids": "ev1",
            "review_decision": "accept",
            "reviewer_id": annotator,
            "annotator_id": annotator,
            "adjudication_status": "adjudicated_final",
            "reviewer_note": "agreed",
        }])

    report = materialize_consensus_sheets(
        tuple_sheets=tuple_paths,
        chain_sheets=chain_paths,
        output_dir=tmp_path / "human_gold_v2",
    )

    assert report["tuple_rows"] == 1
    rows = list(csv.DictReader((tmp_path / "human_gold_v2" / "adjudicated_human_tuple_sheet.csv").open(encoding="utf-8-sig", newline="")))
    assert rows[0]["reviewer_id"] == "consensus_ABC"
    assert rows[0]["annotator_id"] == "consensus_ABC"
    assert rows[0]["adjudication_status"] == "adjudicated_final"
    assert rows[0]["reviewer_note"] == "agreed"


def test_materialize_consensus_sheets_blocks_conflicting_revisions(tmp_path):
    tuple_paths = []
    chain_paths = []
    for annotator in ("annotator_A", "annotator_B"):
        annotator_dir = tmp_path / annotator
        tuple_path = annotator_dir / tuple_sheet_filename(annotator)
        chain_path = annotator_dir / "human_chain_adjudication_sheet.csv"
        tuple_paths.append(tuple_path)
        chain_paths.append(chain_path)
        write_csv(tuple_path, [{
            "event_id": "E1",
            "tuple_id": "T1",
            "stakeholder": "stakeholder",
            "opinion": "opinion",
            "sentiment": "neutral",
            "rationale": "rationale",
            "evidence_ids": "ev1",
            "review_decision": "revise",
            "revised_stakeholder": "stakeholder",
            "revised_opinion": f"opinion {annotator}",
            "revised_sentiment": "neutral",
            "revised_rationale": "rationale",
            "revised_evidence_ids": "ev1",
            "adjudication_status": "adjudicated_final",
        }])
        write_csv(chain_path, [{
            "event_id": "E1",
            "chain_id": "C1",
            "event_chain": "start -> end",
            "evidence_ids": "ev1",
            "review_decision": "accept",
            "adjudication_status": "adjudicated_final",
        }])

    try:
        materialize_consensus_sheets(
            tuple_sheets=tuple_paths,
            chain_sheets=chain_paths,
            output_dir=tmp_path / "human_gold_v2",
        )
    except ValueError as exc:
        assert "conflicting revised_opinion" in str(exc)
    else:
        raise AssertionError("expected conflicting consensus rows to fail")
