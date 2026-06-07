"""Rerun paper experiment in a subprocess with output logging."""
import subprocess
import sys
import time
import os

log_path = r"D:\Workplace\EpiSOA\outputs\paper_rerun.log"
err_path = r"D:\Workplace\EpiSOA\outputs\paper_rerun_err.log"

print("Starting paper experiment rerun...")
print("Logging to:", log_path)

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

with open(log_path, "w", encoding="utf-8") as log_f, open(err_path, "w", encoding="utf-8") as err_f:
    proc = subprocess.Popen(
        [sys.executable, "scripts/run_paper_experiment.py", "--config", "configs/paper.yaml"],
        cwd=r"D:\Workplace\EpiSOA",
        stdout=log_f,
        stderr=err_f,
        env=env,
    )
    print(f"Process started with PID {proc.pid}")
    print("Waiting for completion...")
    
    start = time.time()
    while proc.poll() is None:
        elapsed = time.time() - start
        if elapsed > 1800:  # 30 min timeout
            print(f"Timeout after {elapsed:.0f}s, killing process")
            proc.kill()
            break
        time.sleep(10)
        # Print progress
        log_f.flush()
        err_f.flush()
        try:
            sz = os.path.getsize(log_path)
            esz = os.path.getsize(err_path)
            print(f"  [{elapsed:.0f}s] log={sz}B err={esz}B")
        except:
            pass
    
    elapsed = time.time() - start
    print(f"Process finished with return code {proc.returncode} after {elapsed:.0f}s")

# Print last few lines of log
with open(log_path, encoding="utf-8") as f:
    lines = f.readlines()
    print(f"\nLast 5 lines of log ({len(lines)} total):")
    for line in lines[-5:]:
        print("  ", line.rstrip())