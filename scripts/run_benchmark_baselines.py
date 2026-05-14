"""Run baseline methods on EpiSOA benchmark tasks.

Baselines:
1. rule: keyword-matching baseline (no LLM needed)
   - tuple_identification: extract stakeholders from event hints, match opinions via keyword patterns
   - evidence_support: classify via keyword overlap between evidence and opinion
   - chain_construction: sort evidence by temporal stage keywords
2. direct_llm: LLM without event-chain retrieval (same as benchmark_eval but called "baseline")
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from episoa.config import load_config
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.evaluation.benchmark_metrics import (
    eval_tuple_identification,
    eval_evidence_support,
    eval_chain_construction,
)
from episoa.evaluation.benchmark_runner import (
    run_tuple_identification,
    run_evidence_support,
    run_chain_construction,
)
from episoa.llm.client import build_llm_client


# ---------------------------------------------------------------------------
# Rule-based baseline implementations
# ---------------------------------------------------------------------------

STAKEHOLDER_KEYWORDS = {
    "政府": ["政府", "区委", "市政府", "区政府", "街道", "部门", "官方", "住建", "规划"],
    "居民/村民": ["居民", "村民", "住户", "业主", "拆迁户", "老百姓", "群众"],
    "开发商": ["开发商", "房地产", "企业", "公司", "建设方", "项目方"],
    "媒体": ["媒体", "记者", "报道", "新闻"],
    "专家": ["专家", "学者", "研究院", "教授"],
}

OPINION_PATTERNS = [
    (["支持", "同意", "赞成", "满意", "期待", "欢迎", "配合"], "positive"),
    (["反对", "不满", "抗议", "质疑", "抵制", "拒绝", "抱怨"], "negative"),
    (["担忧", "担心", "顾虑", "矛盾", "犹豫", "观望", "复杂"], "mixed"),
    (["诉求", "要求", "期望", "希望", "呼吁", "建议"], "mixed"),
]


def _find_stakeholder(texts: list[str], event_hints: list[str]) -> list[str]:
    found = set()
    for text in texts:
        for category, keywords in STAKEHOLDER_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    found.add(category)
    for hint in event_hints:
        if hint:
            found.add(hint)
    return list(found)


def _classify_sentiment(text: str) -> str:
    for patterns, sentiment in OPINION_PATTERNS:
        for pat in patterns:
            if pat in text:
                return sentiment
    return "mixed"


def rule_tuple_identification(task_rows: list[dict]) -> tuple[list[dict], dict]:
    predictions = []
    for row in task_rows:
        inp = row["input"]
        event = inp["event"]
        ev_texts = [ev.get("text", "") for ev in inp["evidence_candidates"]]
        full_text = " ".join(ev_texts)

        stakeholders = _find_stakeholder(
            ev_texts, event.get("stakeholder_hints", [])
        )

        tuples = []
        for stakeholder in stakeholders[:5]:
            opinion = f"{stakeholder}对{event.get('event_name', '该事件')}表达了观点"
            sentiment = _classify_sentiment(full_text)
            evidence_ids = [
                ev["evidence_id"] for ev in inp["evidence_candidates"][:3]
            ]
            tuples.append({
                "stakeholder": stakeholder,
                "opinion": opinion,
                "sentiment": sentiment,
                "evidence_ids": evidence_ids,
                "rationale": "rule-based baseline",
            })

        predictions.append({
            "task_id": row["task_id"],
            "event_id": row["event_id"],
            "task_type": "tuple_identification",
            "model_name": "rule_baseline",
            "prediction": {"tuples": tuples},
            "output": row["output"],
        })

    metrics = eval_tuple_identification(predictions)
    return predictions, metrics


def rule_evidence_support(task_rows: list[dict]) -> tuple[list[dict], dict]:
    predictions = []
    for row in task_rows:
        inp = row["input"]
        tup = inp["tuple_claim"]
        evidence = inp["evidence"]
        ev_text = evidence.get("text", "").lower()
        opinion = tup.get("opinion", "").lower()
        stakeholder = tup.get("stakeholder", "").lower()

        overlap_stakeholder = any(ch in ev_text for ch in stakeholder[:3]) if len(stakeholder) >= 2 else False
        opinion_words = set(w for w in opinion if len(w) >= 2)
        overlap_opinion = sum(1 for w in opinion_words if w in ev_text)

        if overlap_stakeholder and overlap_opinion >= 2:
            label = "supported"
        elif overlap_stakeholder or overlap_opinion >= 1:
            label = "partially_supported"
        else:
            label = "not_enough_info"

        predictions.append({
            "task_id": row["task_id"],
            "event_id": row["event_id"],
            "candidate_id": row["candidate_id"],
            "evidence_id": row["evidence_id"],
            "task_type": "evidence_support_classification",
            "model_name": "rule_baseline",
            "prediction": {"support_label": label, "reason": "rule-based keyword overlap"},
            "gold_label": row["output"]["support_label"],
            "sample_type": row.get("metadata", {}).get("sample_type", "unknown"),
        })

    metrics = eval_evidence_support(predictions)
    return predictions, metrics


def rule_chain_construction(task_rows: list[dict]) -> tuple[list[dict], dict]:
    STAGE_KEYWORDS = {
        "trigger": ["发布", "启动", "公布", "印发", "签约", "开始"],
        "diffusion": ["关注", "讨论", "传播", "热议", "报道"],
        "conflict": ["冲突", "争议", "质疑", "反对", "不满", "投诉"],
        "response": ["回应", "表示", "解释", "称", "协调", "处理"],
        "resolution": ["解决", "完成", "达成", "推进", "通过", "安置"],
        "follow_up": ["后续", "进展", "批复", "盘活", "开工", "建设"],
    }

    predictions = []
    for row in task_rows:
        inp = row["input"]
        ev_candidates = inp["evidence_candidates"]

        stages: dict[str, list[str]] = {s: [] for s in STAGE_KEYWORDS}
        for ev in ev_candidates:
            text = ev.get("text", "")
            for stage, keywords in STAGE_KEYWORDS.items():
                if any(kw in text for kw in keywords):
                    stages[stage].append(ev["evidence_id"])
                    break

        chain_stages = []
        chain_ev_ids = []
        for stage, ev_ids in stages.items():
            if ev_ids:
                chain_stages.append(f"{stage}: {len(ev_ids)}条证据")
                chain_ev_ids.extend(ev_ids[:2])

        predictions.append({
            "task_id": row["task_id"],
            "event_id": row["event_id"],
            "task_type": "chain_construction",
            "model_name": "rule_baseline",
            "prediction": {"chains": [{"evidence_ids": chain_ev_ids[:8], "event_chain": chain_stages}] if chain_stages else []},
            "output": row["output"],
        })

    metrics = eval_chain_construction(predictions)
    return predictions, metrics


BASELINE_REGISTRY = {
    "rule": {
        "tuple_identification": rule_tuple_identification,
        "evidence_support_classification": rule_evidence_support,
        "chain_construction": rule_chain_construction,
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run baseline methods on benchmark tasks")
    parser.add_argument("--baseline", choices=["rule", "direct_llm"], default="rule")
    parser.add_argument("--config", default="configs/paper.yaml")
    parser.add_argument("--benchmark-dir", default="data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--task", default="all", help="Which task to run")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--prompt-dir", default="prompts", help="Directory with benchmark prompt .md files")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    benchmark_dir = Path(args.benchmark_dir)

    if args.baseline == "rule":
        run_label = "rule_baseline"
    else:
        model_name = args.model_name or cfg.model.get("model_name", "deepseek-v4-flash")
        run_label = f"direct_llm_{model_name}"

    output_dir = Path(args.output_dir) if args.output_dir else Path(f"outputs/benchmark_runs/{run_label}")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Baseline: {args.baseline}")
    print(f"Output: {output_dir}")

    if args.task == "all":
        task_names = ["tuple_identification", "evidence_support_classification", "chain_construction"]
    else:
        task_names = [args.task]

    file_map = {
        "tuple_identification": "tuple_identification.jsonl",
        "evidence_support_classification": "evidence_support_classification.jsonl",
        "chain_construction": "chain_construction.jsonl",
    }

    all_metrics = {}

    if args.baseline == "rule":
        for task_name in task_names:
            task_file = benchmark_dir / file_map[task_name]
            if not task_file.exists():
                print(f"[SKIP] {task_file} not found")
                continue
            rows = read_jsonl(task_file)
            if args.max_tasks and args.max_tasks < len(rows):
                rows = rows[:args.max_tasks]

            print(f"[{task_name}] Running rule baseline on {len(rows)} rows ...")
            t0 = time.time()
            runner = BASELINE_REGISTRY["rule"][task_name]
            predictions, metrics = runner(rows)
            elapsed = time.time() - t0

            pred_file = output_dir / f"{task_name}_predictions.jsonl"
            write_jsonl(pred_file, predictions)

            metrics["baseline"] = "rule"
            metrics["elapsed_seconds"] = round(elapsed, 1)
            metrics["rows_processed"] = len(rows)
            all_metrics[task_name] = metrics

            for k, v in metrics.items():
                print(f"  {k}: {v}")

    else:  # direct_llm
        model_name = args.model_name or cfg.model.get("model_name", "deepseek-v4-flash")
        client = build_llm_client(cfg.model)
        runner_map = {
            "tuple_identification": run_tuple_identification,
            "evidence_support_classification": run_evidence_support,
            "chain_construction": run_chain_construction,
        }

        for task_name in task_names:
            task_file = benchmark_dir / file_map[task_name]
            if not task_file.exists():
                print(f"[SKIP] {task_file} not found")
                continue
            rows = read_jsonl(task_file)
            if args.max_tasks and args.max_tasks < len(rows):
                rows = rows[:args.max_tasks]

            print(f"[{task_name}] Running direct LLM baseline on {len(rows)} rows ...")
            t0 = time.time()
            runner = runner_map[task_name]
            predictions, metrics = runner(client, rows, model_name, prompt_dir=args.prompt_dir)
            elapsed = time.time() - t0

            pred_file = output_dir / f"{task_name}_predictions.jsonl"
            write_jsonl(pred_file, predictions)

            metrics["baseline"] = "direct_llm"
            metrics["model_name"] = model_name
            metrics["elapsed_seconds"] = round(elapsed, 1)
            metrics["rows_processed"] = len(rows)
            all_metrics[task_name] = metrics

            for k, v in metrics.items():
                print(f"  {k}: {v}")

    metrics_file = output_dir / "metrics.json"
    metrics_file.write_text(json.dumps(all_metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nMetrics saved to {metrics_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
