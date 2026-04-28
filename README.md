# EpiSOA

`src/episoa/experimental/` contains optional components not used in the main EpiSOA paper experiments.

## Minimal Experiment

Run the default mock smoke experiment from the project root:

```powershell
python -m pip install -e .
python scripts/run_experiment.py --config configs/default.yaml
```

The run writes reproducible artifacts under `outputs/runs/{run_id}/`, including `config.yaml`, `predictions.jsonl`, `metrics.json`, and `summary.json`.

## Pytest Diagnostics

Default pytest runs are mock-only and exclude integration, slow, real model, and browser tests.

Useful commands:

```powershell
$env:PYTHONPATH='src'; pytest -m unit -q
$env:PYTHONPATH='src'; pytest -m "not integration and not slow and not real_model and not browser" -q
$env:PYTHONPATH='src'; pytest --durations=20 -vv -s -x
```
