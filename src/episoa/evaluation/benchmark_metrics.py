"""Metrics for benchmark task evaluation.

Shared between run_benchmark_eval.py and run_benchmark_baselines.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def _char_overlap(a: str, b: str) -> float:
    """Character-level Jaccard similarity between two strings."""
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


LLM_JUDGE_SYSTEM = """你是一个中文语义等价判断专家。你需要判断两个利益相关方-观点元组是否表达相同的含义。

规则：
1. stakeholder 语义等价：指代同一群体即可（如"三元里村村民"≈"三元里村支持改造的村民"）
2. opinion 语义等价：表达的核心观点/立场相同即可，措辞不必完全一致
3. 判定为 match=true 仅当 stakeholder 和 opinion 语义都等价
4. 某个 pred 可能不对应任何 gold（无匹配），标记 match=false"""

LLM_JUDGE_USER = """事件：{event_name}

Gold 元组：
{gold_tuples_text}

Pred 元组：
{pred_tuples_text}

对每个 Pred 元组，判断它与哪个 Gold 元组语义最匹配（或都不匹配），输出 JSON：
{{"matches": [{{"pred_index": 0, "gold_index": 1, "match": true, "reason": "简短理由"}}, ...]}}

注意：pred_index 和 gold_index 从 0 开始。如果一个 pred 不匹配任何 gold，gold_index 设为 -1。"""


def _load_judge_prompt(name: str, prompt_dir: str | None) -> str:
    """Load an LLM-judge prompt from file with fallback to in-module string constant."""
    file_map = {
        "LLM_JUDGE_SYSTEM": "benchmark_judge_system.md",
        "LLM_JUDGE_USER": "benchmark_judge_user.md",
    }
    if prompt_dir:
        file_name = file_map.get(name)
        if file_name:
            path = Path(prompt_dir) / file_name
            if path.exists():
                return path.read_text(encoding="utf-8")
    return globals().get(name, "")


def eval_tuple_identification_llm_judge(
    predictions: list[dict],
    llm_client=None,
    model_name: str = "",
    max_events: int = 0,
    prompt_dir: str | None = None,
) -> dict:
    """Evaluate tuple identification using LLM-as-judge for semantic equivalence.

    Calls LLM once per event to match pred tuples against gold tuples.
    Falls back to soft char-overlap if llm_client is None.
    """
    from episoa.evaluation.benchmark_metrics import eval_tuple_identification as _exact_eval

    if llm_client is None:
        return _exact_eval(predictions)

    total_gold = 0
    total_pred = 0
    total_tp = 0
    sentiment_correct = 0
    sentiment_total = 0
    events_processed = 0

    for p in predictions:
        if max_events and events_processed >= max_events:
            break

        gold_tuples = p["output"]["gold_tuples"]
        pred_data = p["prediction"]
        pred_tuples = pred_data.get("tuples", [])

        if not gold_tuples or not pred_tuples:
            continue

        total_gold += len(gold_tuples)
        total_pred += len(pred_tuples)
        events_processed += 1

        # Build prompt
        gold_lines = []
        for i, gt in enumerate(gold_tuples):
            gold_lines.append(
                f"{i}. [{gt.get('stakeholder', '')}] {gt.get('opinion', '')} "
                f"(sentiment={gt.get('sentiment', '')})"
            )
        pred_lines = []
        for j, pt in enumerate(pred_tuples):
            pred_lines.append(
                f"{j}. [{pt.get('stakeholder', '')}] {pt.get('opinion', '')} "
                f"(sentiment={pt.get('sentiment', '')})"
            )

        judge_system = _load_judge_prompt("LLM_JUDGE_SYSTEM", prompt_dir)
        judge_user_template = _load_judge_prompt("LLM_JUDGE_USER", prompt_dir)

        user_prompt = judge_user_template.format(
            event_name=p.get("event_id", ""),
            gold_tuples_text="\n".join(gold_lines),
            pred_tuples_text="\n".join(pred_lines),
        )

        try:
            resp = llm_client.chat(
                system_prompt=judge_system,
                user_prompt=user_prompt,
            )
            content = resp.content.strip()
            # Extract JSON
            import re
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group()) if m else {}
        except Exception:
            parsed = {}

        matches = parsed.get("matches", [])
        matched_gold_indices = set()

        for match in matches:
            gold_idx = match.get("gold_index", -1)
            pred_idx = match.get("pred_index", -1)
            is_match = match.get("match", False)

            if is_match and gold_idx >= 0 and gold_idx < len(gold_tuples) and pred_idx < len(pred_tuples):
                if gold_idx not in matched_gold_indices:
                    total_tp += 1
                    matched_gold_indices.add(gold_idx)
                    # Check sentiment match
                    gt = gold_tuples[gold_idx]
                    pt = pred_tuples[pred_idx]
                    if gt.get("sentiment") == pt.get("sentiment"):
                        sentiment_correct += 1

        sentiment_total += len(gold_tuples)
        time.sleep(0.1)

    precision = total_tp / total_pred if total_pred > 0 else 0
    recall = total_tp / total_gold if total_gold > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    sentiment_acc = sentiment_correct / sentiment_total if sentiment_total > 0 else 0

    return {
        "task": "tuple_identification",
        "gold_tuples": total_gold,
        "pred_tuples": total_pred,
        "true_positives_llm_judge": total_tp,
        "precision_llm_judge": round(precision, 4),
        "recall_llm_judge": round(recall, 4),
        "stakeholder_opinion_f1_llm_judge": round(f1, 4),
        "sentiment_accuracy_llm_judge": round(sentiment_acc, 4),
        "events_processed": events_processed,
        "judge_model": model_name,
    }


def eval_tuple_identification(predictions: list[dict]) -> dict:
    total_gold = 0
    total_pred = 0
    total_tp = 0
    total_tp_soft = 0
    sentiment_correct = 0
    sentiment_total = 0

    for p in predictions:
        gold_tuples = p["output"]["gold_tuples"]
        pred_data = p["prediction"]
        pred_tuples = pred_data.get("tuples", [])

        total_gold += len(gold_tuples)
        total_pred += len(pred_tuples)

        for gt in gold_tuples:
            sentiment_total += 1
            best_soft = 0.0
            for pt in pred_tuples:
                stakeholder_sim = _char_overlap(
                    gt.get("stakeholder", ""), pt.get("stakeholder", "")
                )
                opinion_sim = _char_overlap(
                    gt.get("opinion", ""), pt.get("opinion", "")
                )
                if (gt.get("stakeholder", "").strip() == pt.get("stakeholder", "").strip()
                        and gt.get("opinion", "").strip() == pt.get("opinion", "").strip()):
                    total_tp += 1
                    if gt.get("sentiment") == pt.get("sentiment"):
                        sentiment_correct += 1
                    break
                combined = 0.5 * stakeholder_sim + 0.5 * opinion_sim
                if combined > best_soft:
                    best_soft = combined
            if best_soft >= 0.5:
                total_tp_soft += 1

    precision = total_tp / total_pred if total_pred > 0 else 0
    recall = total_tp / total_gold if total_gold > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    precision_soft = total_tp_soft / total_pred if total_pred > 0 else 0
    recall_soft = total_tp_soft / total_gold if total_gold > 0 else 0
    f1_soft = 2 * precision_soft * recall_soft / (precision_soft + recall_soft) if (precision_soft + recall_soft) > 0 else 0

    sentiment_acc = sentiment_correct / sentiment_total if sentiment_total > 0 else 0

    return {
        "task": "tuple_identification",
        "gold_tuples": total_gold,
        "pred_tuples": total_pred,
        "true_positives": total_tp,
        "true_positives_soft": total_tp_soft,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "stakeholder_opinion_f1": round(f1, 4),
        "stakeholder_opinion_f1_soft": round(f1_soft, 4),
        "sentiment_accuracy": round(sentiment_acc, 4),
    }


def eval_evidence_support(predictions: list[dict]) -> dict:
    labels = ["supported", "partially_supported", "not_enough_info"]
    total = len(predictions)
    correct = 0
    confusion = {gold: {pred: 0 for pred in labels} for gold in labels}

    for p in predictions:
        gold = p["gold_label"]
        pred = p["prediction"].get("support_label", "not_enough_info")
        if gold == pred:
            correct += 1
        if gold in confusion and pred in confusion[gold]:
            confusion[gold][pred] += 1

    per_class = {}
    for label in labels:
        tp = confusion[label][label]
        pred_count = sum(confusion[g][label] for g in labels)
        gold_count = sum(confusion[label].values())
        prec = tp / pred_count if pred_count > 0 else 0
        rec = tp / gold_count if gold_count > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        per_class[label] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

    positive_rows = [p for p in predictions if p.get("sample_type") == "positive"]
    positive_correct = sum(1 for p in positive_rows if p["gold_label"] == p["prediction"].get("support_label"))

    return {
        "task": "evidence_support_classification",
        "total": total,
        "accuracy": round(correct / total, 4) if total > 0 else 0,
        "positive_accuracy": round(positive_correct / len(positive_rows), 4) if positive_rows else 0,
        "per_class": per_class,
        "confusion": confusion,
    }


def eval_chain_construction(predictions: list[dict]) -> dict:
    total_gold_chains = 0
    total_pred_chains = 0
    total_gold_evidence = 0
    total_pred_evidence = 0
    total_overlap_evidence = 0
    events_with_chain_match = 0
    total_events = len(predictions)

    for p in predictions:
        gold_chains = p["output"]["gold_chains"]
        pred_data = p["prediction"]
        pred_chains = pred_data.get("chains", [])

        total_gold_chains += len(gold_chains)
        total_pred_chains += len(pred_chains)

        gold_evidence_ids = set()
        for gc in gold_chains:
            for eid in gc.get("evidence_ids", []):
                gold_evidence_ids.add(eid)

        pred_evidence_ids = set()
        for pc in pred_chains:
            for eid in pc.get("evidence_ids", []):
                pred_evidence_ids.add(eid)

        total_gold_evidence += len(gold_evidence_ids)
        total_pred_evidence += len(pred_evidence_ids)
        total_overlap_evidence += len(gold_evidence_ids & pred_evidence_ids)

        if gold_evidence_ids and gold_evidence_ids & pred_evidence_ids:
            events_with_chain_match += 1

    ev_prec = total_overlap_evidence / total_pred_evidence if total_pred_evidence > 0 else 0
    ev_rec = total_overlap_evidence / total_gold_evidence if total_gold_evidence > 0 else 0
    ev_f1 = 2 * ev_prec * ev_rec / (ev_prec + ev_rec) if (ev_prec + ev_rec) > 0 else 0

    return {
        "task": "chain_construction",
        "events": total_events,
        "events_with_chain_match": events_with_chain_match,
        "gold_chains": total_gold_chains,
        "pred_chains": total_pred_chains,
        "gold_evidence_ids": total_gold_evidence,
        "pred_evidence_ids": total_pred_evidence,
        "overlap_evidence_ids": total_overlap_evidence,
        "evidence_precision": round(ev_prec, 4),
        "evidence_recall": round(ev_rec, 4),
        "evidence_f1": round(ev_f1, 4),
    }
