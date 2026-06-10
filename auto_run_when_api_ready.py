#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Auto-run EpiSOA experiments when API becomes available.

Runs independently without user intervention. Tests API every 10 minutes.
Once API recovers, executes main experiment + ablation automatically.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from episoa.llm.client import OpenAICompatibleClient
from episoa.config import load_config, resolve_api_config

API_CHECK_INTERVAL = 600  # 10 minutes
MAX_WAIT_HOURS = 4

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open("auto_run_api_recovery.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

def test_api():
    try:
        config = load_config("configs/paper.yaml")
        resolved = resolve_api_config(config.model, label="model")
        client = OpenAICompatibleClient(
            api_key=resolved["api_key"],
            base_url=resolved["base_url"],
            model_name="gpt-5.5",
            timeout_seconds=30,
            max_retries=1,
        )
        resp = client.chat(system_prompt="You are a test.", user_prompt="Say hello.")
        return resp.content.strip() != ""
    except Exception as e:
        log(f"API test failed: {e}")
        return False

def run_paper_experiment():
    log("Starting paper experiment...")
    result = subprocess.run(
        [sys.executable, "scripts/run_paper_experiment.py", "--config", "configs/paper.yaml"],
        capture_output=True,
        text=True,
        timeout=7200,
    )
    log(f"Paper experiment return code: {result.returncode}")
    if result.returncode != 0:
        log(f"Paper experiment STDERR: {result.stderr[-500:]}")
    return result.returncode == 0

def run_ablation():
    log("Starting ablation experiment...")
    result = subprocess.run(
        [sys.executable, "scripts/run_ablation.py", "--config", "configs/ablation.yaml", "--force"],
        capture_output=True,
        text=True,
        timeout=36000,
    )
    log(f"Ablation experiment return code: {result.returncode}")
    if result.returncode != 0:
        log(f"Ablation experiment STDERR: {result.stderr[-500:]}")
    return result.returncode == 0

def evaluate_results():
    log("Evaluating results...")
    result = subprocess.run(
        [sys.executable, "scripts/rerun_and_evaluate.py"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    log(f"Evaluation return code: {result.returncode}")
    log(f"Evaluation output:\n{result.stdout[-2000:]}")
    return result.returncode == 0

def main():
    log("=" * 60)
    log("Auto-run script started. Waiting for API recovery...")
    log("=" * 60)

    start_time = time.time()
    max_wait_seconds = MAX_WAIT_HOURS * 3600

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            log("Max wait time exceeded. Giving up.")
            break

        log(f"Testing API... (elapsed: {elapsed/60:.0f} minutes)")
        if test_api():
            log("API IS AVAILABLE! Starting experiments...")
            success = True
            success &= run_paper_experiment()
            success &= run_ablation()
            if success:
                evaluate_results()
            log("Experiments complete.")
            break
        else:
            log(f"API still down. Waiting {API_CHECK_INTERVAL//60} minutes...")
            time.sleep(API_CHECK_INTERVAL)

    log("Auto-run script finished.")

if __name__ == "__main__":
    raise SystemExit(main())
