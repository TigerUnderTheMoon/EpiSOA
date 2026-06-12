"""Rerun paper experiment + key ablation settings."""
import subprocess
import sys
import time
import os
import json

def run_command(cmd, label, timeout=3600):
    print(f"\n{'='*60}")
    print(f"Starting: {label}")
    print(f"Command: {cmd}")
    print(f"{'='*60}")
    start = time.time()
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=r"D:\Workplace\EpiSOA",
    )
    elapsed = time.time() - start
    print(f"\n{label} completed in {elapsed:.0f}s")
    print(f"Return code: {result.returncode}")
    if result.stdout:
        print(f"STDOUT (last 500 chars): {result.stdout[-500:]}")
    if result.stderr:
        print(f"STDERR (last 500 chars): {result.stderr[-500:]}")
    return result

# 1. Rerun paper experiment (full_soe)
r1 = run_command(
    f"{sys.executable} scripts/run_paper_experiment.py --config configs/paper.yaml",
    "Paper experiment (full_soe)",
    timeout=7200,
)

# 2. Rerun ablation (without_soe_graph + direct_llm only)
r2 = run_command(
    f"{sys.executable} scripts/run_ablation.py --config configs/ablation.yaml --force",
    "Ablation experiment (all settings)",
    timeout=36000,
)

# 3. Evaluate results
print("\n" + "="*60)
print("EVALUATING RESULTS")
print("="*60)

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.evaluate_main import evaluate_main

golds_path = r"D:\Workplace\EpiSOA\data\pubevent_soa_lite\human_gold_v2\human_gold_tuples_v2.jsonl"
golds = [GoldTuple(**json.loads(l)) for l in open(golds_path, encoding="utf-8")]

settings = {
    "full_soe": r"D:\Workplace\EpiSOA\outputs\runs_human_gold_v2\pubevent-soa-lite-human-gold-v2-paper\predictions.jsonl",
    "without_soe_graph": r"D:\Workplace\EpiSOA\outputs\runs_human_gold_v2\ablation_without_soe_graph\predictions.jsonl",
    "direct_llm": r"D:\Workplace\EpiSOA\outputs\runs_human_gold_v2\ablation_direct_llm\predictions.jsonl",
}

for name, path in settings.items():
    if os.path.exists(path):
        preds = [PredictionTuple(**json.loads(l)) for l in open(path, encoding="utf-8")]
        m = evaluate_main(golds, preds, verifier_enabled=True)
        f1 = m.get("Tuple-F1-semantic@0.3", 0)
        p = m.get("Tuple-Precision-semantic@0.3", 0)
        r = m.get("Tuple-Recall-semantic@0.3", 0)
        sh_r = m.get("Stakeholder-Recall-semantic@0.3", 0)
        op_r = m.get("Opinion-Recall-semantic@0.3", 0)
        generic = sum(1 for pd in [json.loads(l) for l in open(path, encoding="utf-8")]
                      if pd.get("stakeholder") in {"居民/公众", "公众", "网友", "社会", "社会公众"})
        total = len([json.loads(l) for l in open(path, encoding="utf-8")])
        print(f"\n{name}:")
        print(f"  F1@0.3={f1:.4f}  P@0.3={p:.4f}  R@0.3={r:.4f}")
        print(f"  SH-R@0.3={sh_r:.4f}  OP-R@0.3={op_r:.4f}  Tuples={total}")
        print(f"  Generic labels: {generic}/{total} ({100*generic/total:.1f}%)")
        print(f"  TARGET MET: {'YES' if f1 >= 0.7 else 'NO (gap=%.3f)' % (0.7-f1)}")
    else:
        print(f"\n{name}: FILE NOT FOUND")

print("\nDone!")