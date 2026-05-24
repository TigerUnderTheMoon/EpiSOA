import csv
from pathlib import Path

from scripts.build_independent_human_adjudication import (
    audit_independent_annotations,
    fleiss_kappa,
    prepare_independent_sheets,
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
        tuple_path = tmp_path / "independent" / annotator / "human_tuple_adjudication_sheet.csv"
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
