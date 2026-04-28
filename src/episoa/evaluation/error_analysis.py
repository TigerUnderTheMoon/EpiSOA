"""Rule-based error analysis for EpiSOA experiment outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ERROR_TYPES = [
    "stakeholder_error",
    "sentiment_error",
    "evidence_missing_error",
    "unsupported_attribution_error",
    "event_chain_error",
    "wrong_stakeholder",
    "wrong_sentiment",
    "unsupported_rationale",
    "missing_evidence",
    "wrong_event_chain",
]


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


def analyze_run(
    run_dir: str | Path | None = None,
    *,
    gold_tuples_path: str | Path = "data/pubevent_soa_lite/gold_tuples.jsonl",
    gold_event_chains_path: str | Path = "data/pubevent_soa_lite/gold_event_chains.jsonl",
) -> list[dict[str, Any]]:
    """Analyze prediction JSONL files under a run directory."""
    resolved_run_dir = resolve_run_dir(run_dir)
    gold_tuples = load_jsonl(gold_tuples_path)
    gold_chains = load_jsonl(gold_event_chains_path)
    prediction_files = _prediction_files(resolved_run_dir)

    rows: list[dict[str, Any]] = []
    for prediction_file in prediction_files:
        method = _method_name(prediction_file)
        for index, prediction in enumerate(load_jsonl(prediction_file), start=1):
            rows.extend(
                analyze_prediction(
                    prediction,
                    gold_tuples,
                    gold_chains,
                    method=method,
                    prediction_file=prediction_file,
                    prediction_index=index,
                )
            )
    return rows


def analyze_prediction(
    prediction: dict[str, Any],
    gold_tuples: list[dict[str, Any]],
    gold_chains: list[dict[str, Any]],
    *,
    method: str,
    prediction_file: str | Path,
    prediction_index: int,
) -> list[dict[str, Any]]:
    """Return error rows for one prediction tuple."""
    matched_gold = _best_gold_tuple(prediction, gold_tuples)
    matched_chain = _best_gold_chain(prediction, gold_chains)
    errors: list[dict[str, Any]] = []

    gold_stakeholders = {_normalize(row.get("stakeholder")) for row in gold_tuples}
    pred_stakeholder = _normalize(prediction.get("stakeholder"))
    if pred_stakeholder not in gold_stakeholders:
        errors.extend(_error_rows("stakeholder_error", "wrong_stakeholder", prediction, matched_gold, matched_chain, method, prediction_file, prediction_index))

    if matched_gold and _normalize(prediction.get("sentiment")) != _normalize(matched_gold.get("sentiment")):
        errors.extend(_error_rows("sentiment_error", "wrong_sentiment", prediction, matched_gold, matched_chain, method, prediction_file, prediction_index))

    predicted_evidence = set(_evidence_ids(prediction))
    gold_evidence = set(_evidence_ids(matched_gold or {}))
    if not predicted_evidence:
        errors.extend(_error_rows("evidence_missing_error", "missing_evidence", prediction, matched_gold, matched_chain, method, prediction_file, prediction_index))
    elif matched_gold and not (predicted_evidence & gold_evidence):
        errors.extend(_error_rows("evidence_missing_error", "missing_evidence", prediction, matched_gold, matched_chain, method, prediction_file, prediction_index))

    if _is_unsupported(prediction, matched_gold):
        errors.extend(_error_rows("unsupported_attribution_error", "unsupported_rationale", prediction, matched_gold, matched_chain, method, prediction_file, prediction_index))

    if _wrong_event_chain(prediction, matched_gold, matched_chain):
        errors.extend(_error_rows("event_chain_error", "wrong_event_chain", prediction, matched_gold, matched_chain, method, prediction_file, prediction_index))

    return errors


def write_error_analysis(rows: list[dict[str, Any]], run_dir: str | Path | None = None) -> dict[str, Path]:
    """Write canonical JSON plus compatibility CSV/JSONL files into the run root."""
    resolved_run_dir = resolve_run_dir(run_dir)
    resolved_run_dir.mkdir(parents=True, exist_ok=True)
    json_path = resolved_run_dir / "error_analysis.json"
    csv_path = resolved_run_dir / "error_analysis.csv"
    jsonl_path = resolved_run_dir / "error_analysis.jsonl"
    summary = _summary(rows)
    payload = {
        "description": "Rule-based EpiSOA error analysis.",
        "num_errors": len(rows),
        "summary": summary,
        "errors": rows,
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fieldnames = [
        "method",
        "prediction_file",
        "prediction_index",
        "error_type",
        "event",
        "stakeholder",
        "predicted_sentiment",
        "gold_sentiment",
        "predicted_evidence_ids",
        "gold_evidence_ids",
        "predicted_event_chain",
        "gold_event_chain",
        "rationale",
        "verified",
        "support_score",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with jsonl_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"json": json_path, "csv": csv_path, "jsonl": jsonl_path}


def run_error_analysis(
    run_dir: str | Path | None = None,
    *,
    gold_tuples_path: str | Path = "data/pubevent_soa_lite/gold_tuples.jsonl",
    gold_event_chains_path: str | Path = "data/pubevent_soa_lite/gold_event_chains.jsonl",
) -> dict[str, Path]:
    """Analyze a run and write error analysis artifacts."""
    resolved_run_dir = resolve_run_dir(run_dir)
    rows = analyze_run(
        resolved_run_dir,
        gold_tuples_path=gold_tuples_path,
        gold_event_chains_path=gold_event_chains_path,
    )
    return write_error_analysis(rows, resolved_run_dir)


def _prediction_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    if (run_dir / "predictions.jsonl").exists():
        files.append(run_dir / "predictions.jsonl")
    files.extend(sorted((run_dir / "predictions").glob("*.jsonl")))
    files.extend(sorted((run_dir / "predictions" / "ablations").glob("*.jsonl")))
    files.extend(sorted((run_dir / "baselines").glob("*/predictions.jsonl")))
    files.extend(sorted((run_dir / "ablations").glob("*/predictions.jsonl")))
    return files


def _method_name(prediction_file: Path) -> str:
    if prediction_file.name == "predictions.jsonl":
        if prediction_file.parent.parent.name == "baselines":
            return f"baseline:{prediction_file.parent.name}"
        if prediction_file.parent.parent.name == "ablations":
            return f"ablation:{prediction_file.parent.name}"
        return "episoa_pipeline"
    if prediction_file.parent.name == "ablations":
        return f"ablation:{prediction_file.stem}"
    return prediction_file.stem


def _error_rows(
    paper_error_type: str,
    legacy_error_type: str,
    prediction: dict[str, Any],
    matched_gold: dict[str, Any] | None,
    matched_chain: dict[str, Any] | None,
    method: str,
    prediction_file: str | Path,
    prediction_index: int,
) -> list[dict[str, Any]]:
    paper_row = _error_row(
        paper_error_type,
        prediction,
        matched_gold,
        matched_chain,
        method,
        prediction_file,
        prediction_index,
    )
    legacy_row = _error_row(
        legacy_error_type,
        prediction,
        matched_gold,
        matched_chain,
        method,
        prediction_file,
        prediction_index,
    )
    return [paper_row, legacy_row]


def _summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    total = len(rows)
    counts: dict[str, int] = {}
    for row in rows:
        error_type = str(row.get("error_type", "unknown"))
        counts[error_type] = counts.get(error_type, 0) + 1
    return {
        key: {"count": count, "rate": (count / total if total else 0.0)}
        for key, count in sorted(counts.items())
    }


def _best_gold_tuple(prediction: dict[str, Any], gold_tuples: list[dict[str, Any]]) -> dict[str, Any] | None:
    pred_stakeholder = _normalize(prediction.get("stakeholder"))
    pred_event = _normalize(prediction.get("event"))
    for gold in gold_tuples:
        if _normalize(gold.get("stakeholder")) == pred_stakeholder and _normalize(gold.get("event")) == pred_event:
            return gold
    for gold in gold_tuples:
        if _normalize(gold.get("stakeholder")) == pred_stakeholder:
            return gold
    return None


def _best_gold_chain(prediction: dict[str, Any], gold_chains: list[dict[str, Any]]) -> dict[str, Any] | None:
    predicted_chain = _chain_items(prediction)
    if not predicted_chain:
        return None
    predicted_set = set(predicted_chain)
    best: dict[str, Any] | None = None
    best_overlap = 0
    for gold in gold_chains:
        overlap = len(predicted_set & set(_chain_items(gold)))
        if overlap > best_overlap:
            best = gold
            best_overlap = overlap
    return best


def _is_unsupported(prediction: dict[str, Any], matched_gold: dict[str, Any] | None) -> bool:
    rationale = _normalize(prediction.get("rationale"))
    if rationale == "insufficient evidence":
        return True
    if prediction.get("verified") is False:
        return True
    if float(prediction.get("support_score") or 0.0) < 0.75:
        return True
    if matched_gold and not (set(_evidence_ids(prediction)) & set(_evidence_ids(matched_gold))):
        return True
    return False


def _wrong_event_chain(
    prediction: dict[str, Any],
    matched_gold: dict[str, Any] | None,
    matched_chain: dict[str, Any] | None,
) -> bool:
    predicted_chain = _chain_items(prediction)
    if not predicted_chain:
        return True
    candidate_chains = [_chain_items(row) for row in (matched_gold, matched_chain) if row]
    return not any(predicted_chain == chain for chain in candidate_chains)


def _error_row(
    error_type: str,
    prediction: dict[str, Any],
    matched_gold: dict[str, Any] | None,
    matched_chain: dict[str, Any] | None,
    method: str,
    prediction_file: str | Path,
    prediction_index: int,
) -> dict[str, Any]:
    return {
        "method": method,
        "prediction_file": str(prediction_file),
        "prediction_index": prediction_index,
        "error_type": error_type,
        "event": prediction.get("event", ""),
        "stakeholder": prediction.get("stakeholder", ""),
        "predicted_sentiment": prediction.get("sentiment", ""),
        "gold_sentiment": (matched_gold or {}).get("sentiment", ""),
        "predicted_evidence_ids": "|".join(_evidence_ids(prediction)),
        "gold_evidence_ids": "|".join(_evidence_ids(matched_gold or {})),
        "predicted_event_chain": " > ".join(_chain_items(prediction)),
        "gold_event_chain": " > ".join(_chain_items(matched_gold or matched_chain or {})),
        "rationale": prediction.get("rationale", ""),
        "verified": prediction.get("verified", ""),
        "support_score": prediction.get("support_score", ""),
    }


def _evidence_ids(row: dict[str, Any]) -> list[str]:
    if "evidence_ids" in row:
        return [str(item) for item in row.get("evidence_ids", []) if str(item).strip()]
    ids: list[str] = []
    for item in row.get("evidence", []) or []:
        if isinstance(item, dict) and item.get("evidence_id"):
            ids.append(str(item["evidence_id"]))
    return ids


def _chain_items(row: dict[str, Any]) -> list[str]:
    return [_normalize(item) for item in row.get("event_chain", []) or [] if _normalize(item)]


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()
