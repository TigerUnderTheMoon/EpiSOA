"""Compare original full run vs P0 parse-repair run.

Reads:
  outputs/runs/ablation_full/          (original)
  outputs/runs_p0_parse_repair/ablation_full/  (P0 repaired)

Writes to outputs/diagnostics/parse_repair_comparison/:
  parse_repair_summary.json
  parse_repair_event_comparison.csv
  parse_repair_report.md
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

OLD_RUN_DIR = Path("outputs/runs/ablation_full")
NEW_RUN_DIR = Path("outputs/runs_p0_parse_repair/ablation_full")
OUTPUT_DIR = Path("outputs/diagnostics/parse_repair_comparison")

GOLD_PATH = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/"
    "llm_gold_tuples.jsonl"
)


def main() -> int:
    if not OLD_RUN_DIR.exists():
        print(f"ERROR: old run dir not found: {OLD_RUN_DIR}")
        return 1
    if not NEW_RUN_DIR.exists():
        print(f"ERROR: new run dir not found: {NEW_RUN_DIR}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    old_raw = _load_raw_by_event(OLD_RUN_DIR)
    new_raw = _load_raw_by_event(NEW_RUN_DIR)
    old_preds = _load_predictions_by_event(OLD_RUN_DIR)
    new_preds = _load_predictions_by_event(NEW_RUN_DIR)
    old_metrics = _load_json(OLD_RUN_DIR / "metrics.json")
    new_metrics = _load_json(NEW_RUN_DIR / "metrics.json")

    gold = _load_jsonl(GOLD_PATH)
    all_event_ids = sorted(
        set(old_raw) | set(new_raw) | {t["event_id"] for t in gold}
    )

    rows = _build_comparison_rows(all_event_ids, old_raw, new_raw, old_preds, new_preds, gold)
    _write_event_csv(rows)
    summary = _build_summary(rows, old_metrics, new_metrics)
    _write_summary_json(summary)
    _write_report_md(summary, rows, old_metrics, new_metrics)

    print(f"Comparison artifacts written to {OUTPUT_DIR}")
    print(f"  parse_repair_summary.json")
    print(f"  parse_repair_event_comparison.csv")
    print(f"  parse_repair_report.md")

    _print_key_comparison(old_metrics, new_metrics, summary)
    return 0


def _load_raw_by_event(run_dir: Path) -> dict[str, dict]:
    path = run_dir / "raw_llm_responses.jsonl"
    if not path.exists():
        return {}
    result: dict[str, dict] = {}
    for row in _load_jsonl(path):
        result[str(row.get("event_id", ""))] = row
    return result


def _load_predictions_by_event(run_dir: Path) -> dict[str, list[dict]]:
    path = run_dir / "predictions.jsonl"
    if not path.exists():
        return {}
    result: dict[str, list[dict]] = defaultdict(list)
    for row in _load_jsonl(path):
        result[str(row.get("event_id", ""))].append(row)
    return dict(result)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _build_comparison_rows(
    event_ids: list[str],
    old_raw: dict[str, dict],
    new_raw: dict[str, dict],
    old_preds: dict[str, list[dict]],
    new_preds: dict[str, list[dict]],
    gold: list[dict],
) -> list[dict[str, Any]]:
    gold_by_event = defaultdict(list)
    for t in gold:
        gold_by_event[str(t["event_id"])].append(t)

    rows: list[dict[str, Any]] = []
    for eid in event_ids:
        o_raw = old_raw.get(eid, {})
        n_raw = new_raw.get(eid, {})
        o_summary = o_raw.get("request_summary", {}) if isinstance(o_raw, dict) else {}
        n_summary = n_raw.get("request_summary", {}) if isinstance(n_raw, dict) else {}

        o_pred_count = len(old_preds.get(eid, []))
        n_pred_count = len(new_preds.get(eid, []))

        old_parse = o_raw.get("parse_success") if isinstance(o_raw, dict) else None
        new_parse = n_raw.get("parse_success") if isinstance(n_raw, dict) else None

        old_error = o_raw.get("parse_error") if isinstance(o_raw, dict) else None
        new_error = n_raw.get("parse_error") if isinstance(n_raw, dict) else None

        old_api = int(o_summary.get("api_calls_made", 0))
        new_api = int(n_summary.get("api_calls_made", 0))

        old_chars = int(o_summary.get("prompt_chars", 0))
        new_chars = int(n_summary.get("prompt_chars", 0))

        old_ev_count = len(o_summary.get("selected_evidence_ids", []))
        new_ev_count = len(n_summary.get("selected_evidence_ids", []))

        pred_delta = n_pred_count - o_pred_count
        parse_repaired = (
            old_parse is False and new_parse is True
        )

        rows.append({
            "event_id": eid,
            "gold_tuple_count": len(gold_by_event.get(eid, [])),
            "old_pred_count": o_pred_count,
            "new_pred_count": n_pred_count,
            "old_parse_success": old_parse if old_parse is not None else "no_record",
            "new_parse_success": new_parse if new_parse is not None else "no_record",
            "old_parse_error": old_error or "",
            "new_parse_error": new_error or "",
            "old_api_calls_made": old_api,
            "new_api_calls_made": new_api,
            "old_prompt_chars": old_chars,
            "new_prompt_chars": new_chars,
            "old_selected_evidence_count": old_ev_count,
            "new_selected_evidence_count": new_ev_count,
            "pred_count_delta": pred_delta,
            "parse_repaired": parse_repaired,
        })
    return rows


def _write_event_csv(rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event_id", "gold_tuple_count",
        "old_pred_count", "new_pred_count", "pred_count_delta",
        "old_parse_success", "new_parse_success",
        "old_parse_error", "new_parse_error",
        "old_api_calls_made", "new_api_calls_made",
        "old_prompt_chars", "new_prompt_chars",
        "old_selected_evidence_count", "new_selected_evidence_count",
        "parse_repaired",
    ]
    path = OUTPUT_DIR / "parse_repair_event_comparison.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _build_summary(
    rows: list[dict[str, Any]],
    old_metrics: dict[str, Any],
    new_metrics: dict[str, Any],
) -> dict[str, Any]:
    old_zero = sum(1 for r in rows if r["old_pred_count"] == 0)
    new_zero = sum(1 for r in rows if r["new_pred_count"] == 0)
    old_parse_fail = sum(
        1 for r in rows
        if r["old_parse_success"] is False
    )
    new_parse_fail = sum(
        1 for r in rows
        if r["new_parse_success"] is False
    )
    repaired = sum(1 for r in rows if r["parse_repaired"])
    old_empty = sum(
        1 for r in rows
        if "empty_llm_content" in str(r["old_parse_error"])
    )
    new_empty = sum(
        1 for r in rows
        if "empty_llm_content" in str(r["new_parse_error"])
    )
    old_malformed = sum(
        1 for r in rows
        if "incomplete_or_malformed_json" in str(r["old_parse_error"])
    )
    new_malformed = sum(
        1 for r in rows
        if "incomplete_or_malformed_json" in str(r["new_parse_error"])
    )

    old_total_preds = sum(r["old_pred_count"] for r in rows)
    new_total_preds = sum(r["new_pred_count"] for r in rows)

    return {
        "old_num_tuples": old_metrics.get("Num-Tuples", old_total_preds),
        "new_num_tuples": new_metrics.get("Num-Tuples", new_total_preds),
        "old_tuple_f1_soft": old_metrics.get("Tuple-F1-soft", 0.0),
        "new_tuple_f1_soft": new_metrics.get("Tuple-F1-soft", 0.0),
        "old_precision": old_metrics.get("Tuple-Precision", 0.0),
        "new_precision": new_metrics.get("Tuple-Precision", 0.0),
        "old_recall": old_metrics.get("Tuple-Recall", 0.0),
        "new_recall": new_metrics.get("Tuple-Recall", 0.0),
        "old_sentiment_acc": old_metrics.get("Sentiment-Acc", 0.0),
        "new_sentiment_acc": new_metrics.get("Sentiment-Acc", 0.0),
        "old_num_gold": old_metrics.get("Num-Gold", 0),
        "new_num_gold": new_metrics.get("Num-Gold", 0),
        "old_zero_pred_events": old_zero,
        "new_zero_pred_events": new_zero,
        "old_parse_failed_events": old_parse_fail,
        "new_parse_failed_events": new_parse_fail,
        "parse_repaired_events": repaired,
        "old_empty_llm_content": old_empty,
        "new_empty_llm_content": new_empty,
        "old_incomplete_json": old_malformed,
        "new_incomplete_json": new_malformed,
        "total_events": len(rows),
    }


def _write_summary_json(summary: dict[str, Any]) -> None:
    path = OUTPUT_DIR / "parse_repair_summary.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_report_md(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    old_metrics: dict[str, Any],
    new_metrics: dict[str, Any],
) -> None:
    lines: list[str] = []
    lines.append("# P0 Parse Repair 实验结果")
    lines.append("")
    lines.append("## 实验设置")
    lines.append("")
    lines.append("- 对照组（old）：`outputs/runs/ablation_full/`，max_tokens=3000，max_retries=1，无 malformed JSON retry")
    lines.append("- 实验组（new）：`outputs/runs_p0_parse_repair/ablation_full/`，max_tokens=8000，max_retries=2，增加 malformed JSON retry")
    lines.append("")
    lines.append("## 核心指标对比")
    lines.append("")
    lines.append("| 指标 | Old (full) | New (P0) | Delta |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Num-Gold | {summary['old_num_gold']} | {summary['new_num_gold']} "
        f"| {_delta_str(summary['new_num_gold'], summary['old_num_gold'])} |"
    )
    lines.append(
        f"| Num-Tuples | {summary['old_num_tuples']} | {summary['new_num_tuples']} "
        f"| {_delta_str(summary['new_num_tuples'], summary['old_num_tuples'])} |"
    )
    lines.append(
        f"| Tuple-F1-soft | {summary['old_tuple_f1_soft']:.4f} | {summary['new_tuple_f1_soft']:.4f} "
        f"| {_delta_str(summary['new_tuple_f1_soft'], summary['old_tuple_f1_soft'])} |"
    )
    lines.append(
        f"| Tuple-Precision | {summary['old_precision']:.4f} | {summary['new_precision']:.4f} "
        f"| {_delta_str(summary['new_precision'], summary['old_precision'])} |"
    )
    lines.append(
        f"| Tuple-Recall | {summary['old_recall']:.4f} | {summary['new_recall']:.4f} "
        f"| {_delta_str(summary['new_recall'], summary['old_recall'])} |"
    )
    lines.append(
        f"| Sentiment-Acc | {summary['old_sentiment_acc']:.4f} | {summary['new_sentiment_acc']:.4f} "
        f"| {_delta_str(summary['new_sentiment_acc'], summary['old_sentiment_acc'])} |"
    )
    lines.append("")
    lines.append("## 解析稳定性对比")
    lines.append("")
    lines.append("| 指标 | Old | New |")
    lines.append("|---|---|---|")
    lines.append(f"| 零预测事件数 | {summary['old_zero_pred_events']} | {summary['new_zero_pred_events']} |")
    lines.append(f"| parse 失败事件数 | {summary['old_parse_failed_events']} | {summary['new_parse_failed_events']} |")
    lines.append(f"| empty_llm_content 事件数 | {summary['old_empty_llm_content']} | {summary['new_empty_llm_content']} |")
    lines.append(f"| incomplete/malformed JSON 事件数 | {summary['old_incomplete_json']} | {summary['new_incomplete_json']} |")
    lines.append(f"| parse 修复事件数 | — | {summary['parse_repaired_events']} |")
    lines.append("")

    # Per-event detail for repaired events
    repaired_rows = [r for r in rows if r["parse_repaired"]]
    if repaired_rows:
        lines.append("## parse 修复事件明细")
        lines.append("")
        lines.append("| event_id | old_parse_error | new_pred_count | gold_tuple_count |")
        lines.append("|---|---|---|---|")
        for r in repaired_rows:
            lines.append(
                f"| {r['event_id']} | {r['old_parse_error']} "
                f"| {r['new_pred_count']} | {r['gold_tuple_count']} |"
            )
        lines.append("")

    # Still-failing events
    still_fail = [
        r for r in rows
        if r["new_parse_success"] is False
    ]
    if still_fail:
        lines.append("## 仍然 parse 失败的事件")
        lines.append("")
        lines.append("| event_id | new_parse_error | new_api_calls |")
        lines.append("|---|---|---|")
        for r in still_fail:
            lines.append(
                f"| {r['event_id']} | {r['new_parse_error']} "
                f"| {r['new_api_calls_made']} |"
            )
        lines.append("")

    # Diagnosis
    lines.append("## 诊断结论")
    lines.append("")

    old_empty = summary["old_empty_llm_content"]
    new_empty = summary["new_empty_llm_content"]
    if new_empty < old_empty:
        lines.append(f"1. ✅ empty_llm_content 从 {old_empty} 降至 {new_empty}，max_tokens 提升有效减少了空响应。")
    elif new_empty == old_empty and old_empty > 0:
        lines.append(f"1. ⚠️ empty_llm_content 仍为 {new_empty}（与 old 相同），max_tokens 提升未解决此问题，可能是模型侧 JSON mode 兼容性问题。")
    else:
        lines.append("1. ✅ empty_llm_content 在 old 和 new 中均无或已解决。")

    old_mal = summary["old_incomplete_json"]
    new_mal = summary["new_incomplete_json"]
    if new_mal < old_mal:
        lines.append(f"2. ✅ incomplete/malformed JSON 从 {old_mal} 降至 {new_mal}，max_tokens+retry 修复有效。")
    elif new_mal == old_mal and old_mal > 0:
        lines.append(f"2. ⚠️ incomplete/malformed JSON 仍为 {new_mal}，可能需要进一步增大 max_tokens 或缩短 evidence excerpt。")
    else:
        lines.append("2. ✅ incomplete/malformed JSON 在 old 和 new 中均无或已解决。")

    old_zero = summary["old_zero_pred_events"]
    new_zero = summary["new_zero_pred_events"]
    if new_zero < old_zero:
        lines.append(f"3. ✅ 零预测事件数从 {old_zero} 降至 {new_zero}，parse 修复直接减少了零输出事件。")
    else:
        lines.append(f"3. ⚠️ 零预测事件数仍为 {new_zero}（old={old_zero}），剩余零预测事件主要是 LLM 主动返回空 tuples 而非解析失败。")

    old_tuples = summary["old_num_tuples"]
    new_tuples = summary["new_num_tuples"]
    if new_tuples > old_tuples:
        lines.append(f"4. ✅ Num-Tuples 从 {old_tuples} 升至 {new_tuples}（+{new_tuples - old_tuples}）。")
    else:
        lines.append(f"4. ⚠️ Num-Tuples 未上升（old={old_tuples}, new={new_tuples}）。")

    old_f1 = summary["old_tuple_f1_soft"]
    new_f1 = summary["new_tuple_f1_soft"]
    if new_f1 > old_f1:
        lines.append(f"5. ✅ Tuple-F1-soft 从 {old_f1:.4f} 升至 {new_f1:.4f}（+{new_f1 - old_f1:.4f}）。")
    else:
        lines.append(f"5. ⚠️ Tuple-F1-soft 未上升（old={old_f1:.4f}, new={new_f1:.4f}）。")

    if new_empty > 0 or new_mal > 0:
        lines.append("6. ✅ 仍有必要继续调 max_tokens 或优化 prompt 长度。")
    else:
        lines.append("6. ❌ 当前 max_tokens=8000 已足够，无需继续增大。")

    if new_zero > 10:
        lines.append(
            f"7. ✅ 建议进入 P1 evidence selection 修复——零预测事件中仍有 {new_zero - summary['new_parse_failed_events']} "
            f"个是 LLM 主动空返回（非解析失败），这提示 evidence 与 gold 不对齐。"
        )
    else:
        lines.append("7. ⚠️ 零预测事件已大幅减少，可先稳定 P0 修复再考虑 P1。")

    lines.append("")
    lines.append("## 是否保留 schema_attributor.py retry 修复")
    lines.append("")
    if summary["parse_repaired_events"] > 0:
        lines.append(
            f"✅ 建议保留。新增的 malformed JSON retry 修复了 {summary['parse_repaired_events']} 个事件，"
            f"无负面效果。"
        )
    else:
        lines.append(
            "⚠️ 本次 run 中 malformed JSON retry 未修复任何事件（可能是 max_tokens=8000 已消除截断问题）。"
            " 建议保留 retry 逻辑作为防御性措施。"
        )

    path = OUTPUT_DIR / "parse_repair_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _delta_str(new_val: float | int, old_val: float | int) -> str:
    if isinstance(new_val, float) and isinstance(old_val, float):
        delta = new_val - old_val
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta:.4f}"
    delta = int(new_val) - int(old_val)
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta}"


def _print_key_comparison(
    old_metrics: dict[str, Any],
    new_metrics: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    print()
    print("=" * 60)
    print("P0 Parse Repair 实验结果")
    print("=" * 60)
    print()
    print(f"  {'指标':<24} {'Old (full)':>12} {'New (P0)':>12} {'Delta':>10}")
    print(f"  {'-'*24} {'-'*12} {'-'*12} {'-'*10}")
    keys = [
        ("Num-Gold", "old_num_gold", "new_num_gold"),
        ("Num-Tuples", "old_num_tuples", "new_num_tuples"),
        ("Tuple-F1-soft", "old_tuple_f1_soft", "new_tuple_f1_soft"),
        ("Tuple-Precision", "old_precision", "new_precision"),
        ("Tuple-Recall", "old_recall", "new_recall"),
        ("Sentiment-Acc", "old_sentiment_acc", "new_sentiment_acc"),
    ]
    for label, old_key, new_key in keys:
        ov = summary[old_key]
        nv = summary[new_key]
        if isinstance(ov, float):
            delta = nv - ov
            sign = "+" if delta >= 0 else ""
            print(f"  {label:<24} {ov:>12.4f} {nv:>12.4f} {sign}{delta:>9.4f}")
        else:
            delta = int(nv) - int(ov)
            sign = "+" if delta >= 0 else ""
            print(f"  {label:<24} {ov:>12} {nv:>12} {sign}{delta:>9}")

    print()
    print(f"  零预测事件数:   {summary['old_zero_pred_events']} → {summary['new_zero_pred_events']}")
    print(f"  parse 失败事件:  {summary['old_parse_failed_events']} → {summary['new_parse_failed_events']}")
    print(f"  empty_content:   {summary['old_empty_llm_content']} → {summary['new_empty_llm_content']}")
    print(f"  malformed JSON:  {summary['old_incomplete_json']} → {summary['new_incomplete_json']}")
    print(f"  parse 修复事件:  {summary['parse_repaired_events']}")
    print()

    if summary["parse_repaired_events"] > 0:
        print("  [OK] 建议保留 schema_attributor.py 的 malformed JSON retry 修复。")
    else:
        print("  [WARN] malformed JSON retry 本次未命中，但仍建议保留作为防御。")

    remaining_zero = summary["new_zero_pred_events"] - summary["new_parse_failed_events"]
    if remaining_zero > 5:
        print(f"  [OK] 仍有 {remaining_zero} 个事件 LLM 主动返回空 tuples，建议进入 P1 evidence selection 实验。")
    else:
        print("  [OK] 零预测问题已基本解决。")

    print()
    print(f"详细报告: {OUTPUT_DIR / 'parse_repair_report.md'}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
