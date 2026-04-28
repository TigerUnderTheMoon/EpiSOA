"""Case-study example generation for EpiSOA experiment outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load JSONL rows, returning an empty list when the file is absent."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def resolve_run_dir(run_dir: str | Path | None = None) -> Path:
    """Resolve a run directory from an explicit path or outputs/latest_run.txt."""
    if run_dir is not None:
        return Path(run_dir)
    latest_path = Path("outputs/latest_run.txt")
    if not latest_path.exists():
        raise FileNotFoundError("outputs/latest_run.txt not found; pass --run-dir explicitly")
    return Path(latest_path.read_text(encoding="utf-8").strip())


def generate_case_study_examples(
    run_dir: str | Path,
    *,
    gold_tuples_path: str | Path = "data/pubevent_soa_lite/gold_tuples.jsonl",
    max_cases: int = 5,
) -> dict[str, Any]:
    """Build a compact case-study payload from predictions, gold, and errors."""
    resolved_run_dir = Path(run_dir)
    gold_rows = load_jsonl(gold_tuples_path)
    error_rows = _load_error_rows(resolved_run_dir)
    errors_by_prediction = _errors_by_prediction(error_rows)
    selected_cases = _paper_case_studies(resolved_run_dir, gold_rows, errors_by_prediction)
    if selected_cases:
        return _payload(selected_cases[:max_cases])
    cases: list[dict[str, Any]] = []

    for prediction_file in _prediction_files(resolved_run_dir):
        method = _method_name(resolved_run_dir, prediction_file)
        for index, prediction in enumerate(load_jsonl(prediction_file), start=1):
            gold = _best_gold(prediction, gold_rows)
            case_errors = errors_by_prediction.get((str(prediction_file), index), [])
            cases.append(
                {
                    "case_id": f"{method}-{index:04d}",
                    "case_type": _case_type(case_errors, prediction),
                    "input_text": _input_text(prediction),
                    "gold_label": _compact_gold_label(gold),
                    "prediction": _compact_prediction(prediction),
                    "analysis": _analysis_text(case_errors, prediction, gold),
                    "source": str(prediction_file),
                }
            )
            if len(cases) >= max_cases:
                return _payload(cases)
    return _payload(cases)


def write_case_study_examples(
    run_dir: str | Path,
    *,
    gold_tuples_path: str | Path = "data/pubevent_soa_lite/gold_tuples.jsonl",
    max_cases: int = 5,
) -> Path:
    """Write case_study_examples.json into the run root."""
    resolved_run_dir = resolve_run_dir(run_dir)
    payload = generate_case_study_examples(
        resolved_run_dir,
        gold_tuples_path=gold_tuples_path,
        max_cases=max_cases,
    )
    output_path = resolved_run_dir / "case_study_examples.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _load_error_rows(run_dir: Path) -> list[dict[str, Any]]:
    json_path = run_dir / "error_analysis.json"
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("errors"), list):
            return [row for row in payload["errors"] if isinstance(row, dict)]
    return load_jsonl(run_dir / "error_analysis.jsonl")


def _payload(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "description": "Representative EpiSOA case study examples generated from run predictions and gold annotations.",
        "num_cases": len(cases),
        "cases": cases,
    }


def _prediction_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    if (run_dir / "predictions.jsonl").exists():
        files.append(run_dir / "predictions.jsonl")
    files.extend(sorted((run_dir / "predictions").glob("*.jsonl")))
    files.extend(sorted((run_dir / "predictions" / "ablations").glob("*.jsonl")))
    files.extend(sorted((run_dir / "baselines").glob("*/predictions.jsonl")))
    files.extend(sorted((run_dir / "ablations").glob("*/predictions.jsonl")))
    return files


def _method_name(run_dir: Path, prediction_file: Path) -> str:
    if prediction_file.name == "predictions.jsonl":
        if prediction_file.parent.parent.name == "baselines":
            return f"baseline_{prediction_file.parent.name}"
        if prediction_file.parent.parent.name == "ablations":
            return f"ablation_{prediction_file.parent.name}"
        return "episoa_pipeline"
    if prediction_file.parent.name == "ablations":
        return f"ablation_{prediction_file.stem}"
    try:
        return prediction_file.relative_to(run_dir / "predictions").with_suffix("").as_posix().replace("/", "_")
    except ValueError:
        return prediction_file.stem


def _errors_by_prediction(error_rows: list[dict[str, Any]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in error_rows:
        try:
            index = int(row.get("prediction_index", 0))
        except (TypeError, ValueError):
            continue
        grouped.setdefault((str(row.get("prediction_file", "")), index), []).append(row)
    return grouped


def _case_type(error_rows: list[dict[str, Any]], prediction: dict[str, Any]) -> str:
    if error_rows:
        return str(error_rows[0].get("error_type") or "error_case")
    if prediction.get("verified") is False:
        return "unverified_prediction"
    return "representative_prediction"


def _input_text(row: dict[str, Any]) -> str:
    direct = _first_text(row, ["input_text", "text", "social_media_text"])
    if direct:
        return direct
    evidence = row.get("evidence") or []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                text = _first_text(item, ["input_text", "text", "social_media_text"])
                if text:
                    return text
    return str(row.get("opinion") or row.get("rationale") or "")


def _compact_gold_label(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return json.dumps(
        {
            "event": _first_text(row, ["event", "target_event"]),
            "stakeholder": _first_text(row, ["stakeholder"]),
            "sentiment": _first_text(row, ["sentiment", "gold", "gold_label", "label"]),
            "evidence_ids": _evidence_ids(row),
            "event_chain": row.get("event_chain", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _compact_prediction(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "event": _first_text(row, ["event", "target_event"]),
            "stakeholder": _first_text(row, ["stakeholder"]),
            "opinion": _first_text(row, ["opinion", "pred", "prediction", "model_output"]),
            "sentiment": _first_text(row, ["sentiment"]),
            "evidence_ids": _evidence_ids(row),
            "verified": row.get("verified", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _analysis_text(error_rows: list[dict[str, Any]], prediction: dict[str, Any], gold: dict[str, Any] | None) -> str:
    if error_rows:
        types = ", ".join(sorted({str(row.get("error_type")) for row in error_rows if row.get("error_type")}))
        return f"Error types: {types}. Rationale: {prediction.get('rationale', '')}"
    if gold:
        return "Prediction is included as a representative case with an available gold annotation."
    return "Prediction is included as a representative case without a matched gold annotation."


def _paper_case_studies(
    run_dir: Path,
    gold_rows: list[dict[str, Any]],
    errors_by_prediction: dict[tuple[str, int], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    episoa_path = run_dir / "predictions.jsonl"
    vanilla_path = run_dir / "baselines" / "vanilla_rag" / "predictions.jsonl"
    if not episoa_path.exists():
        return []

    episoa_rows = load_jsonl(episoa_path)
    vanilla_rows = load_jsonl(vanilla_path)
    cases: list[dict[str, Any]] = []

    episoa_good = [row for row in episoa_rows if _is_supported(row) and _best_gold(row, gold_rows)]
    vanilla_good_keys = {_claim_key(row) for row in vanilla_rows if _is_supported(row) and _best_gold(row, gold_rows)}
    for index, row in enumerate(episoa_rows, start=1):
        if row in episoa_good and _claim_key(row) not in vanilla_good_keys:
            cases.append(_case("episoa_correct_vanilla_rag_wrong", episoa_path, index, row, gold_rows, errors_by_prediction))
            break

    vanilla_support = max((float(row.get("support_score") or 0.0) for row in vanilla_rows), default=0.0)
    for index, row in enumerate(episoa_rows, start=1):
        if float(row.get("support_score") or 0.0) > vanilla_support:
            cases.append(_case("episoa_stronger_evidence_support", episoa_path, index, row, gold_rows, errors_by_prediction))
            break

    for index, row in enumerate(episoa_rows, start=1):
        if not _is_supported(row) or errors_by_prediction.get((str(episoa_path), index)):
            cases.append(_case("episoa_failure_case", episoa_path, index, row, gold_rows, errors_by_prediction))
            break

    return cases


def _case(
    case_type: str,
    prediction_file: Path,
    index: int,
    prediction: dict[str, Any],
    gold_rows: list[dict[str, Any]],
    errors_by_prediction: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    gold = _best_gold(prediction, gold_rows)
    case_errors = errors_by_prediction.get((str(prediction_file), index), [])
    return {
        "case_id": f"{case_type}-{index:04d}",
        "case_type": case_type,
        "input_text": _input_text(prediction),
        "gold_label": _compact_gold_label(gold),
        "prediction": _compact_prediction(prediction),
        "analysis": _analysis_text(case_errors, prediction, gold),
        "source": str(prediction_file),
    }


def _is_supported(row: dict[str, Any]) -> bool:
    return bool(row.get("verified")) and float(row.get("support_score") or 0.0) >= 0.75 and bool(_evidence_ids(row))


def _claim_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (_normalize(row.get("event")), _normalize(row.get("stakeholder")), _normalize(row.get("opinion")))


def _best_gold(prediction: dict[str, Any], gold_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    pred_stakeholder = _normalize(prediction.get("stakeholder"))
    pred_event = _normalize(prediction.get("event"))
    for gold in gold_rows:
        if _normalize(gold.get("stakeholder")) == pred_stakeholder and _normalize(gold.get("event")) == pred_event:
            return gold
    for gold in gold_rows:
        if _normalize(gold.get("stakeholder")) == pred_stakeholder:
            return gold
    return None


def _evidence_ids(row: dict[str, Any]) -> list[str]:
    if isinstance(row.get("evidence_ids"), list):
        return [str(item) for item in row["evidence_ids"] if str(item).strip()]
    ids: list[str] = []
    evidence = row.get("evidence") or []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("evidence_id"):
                ids.append(str(item["evidence_id"]))
    return ids


def _first_text(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()
