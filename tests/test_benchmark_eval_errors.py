import json

import scripts.run_benchmark_eval as run_benchmark_eval


def test_benchmark_eval_exits_nonzero_on_prediction_error(tmp_path, monkeypatch):
    benchmark_dir = _write_tuple_task(tmp_path)
    output_dir = tmp_path / "outputs"
    config_path = _write_config(tmp_path)

    _patch_client(monkeypatch)
    _patch_runner(monkeypatch, _error_runner)

    rc = run_benchmark_eval.main(
        [
            "--config",
            str(config_path),
            "--benchmark-dir",
            str(benchmark_dir),
            "--output-dir",
            str(output_dir),
            "--tasks",
            "tuple_identification",
        ]
    )

    assert rc == 1
    predictions = _read_jsonl(output_dir / "tuple_identification_predictions.jsonl")
    assert predictions[0]["prediction"]["_error"] == "boom"
    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["tuple_identification"]["prediction_error_count"] == 1


def test_benchmark_eval_allows_prediction_errors_when_explicit(tmp_path, monkeypatch):
    benchmark_dir = _write_tuple_task(tmp_path)
    output_dir = tmp_path / "outputs"
    config_path = _write_config(tmp_path)

    _patch_client(monkeypatch)
    _patch_runner(monkeypatch, _error_runner)

    rc = run_benchmark_eval.main(
        [
            "--config",
            str(config_path),
            "--benchmark-dir",
            str(benchmark_dir),
            "--output-dir",
            str(output_dir),
            "--tasks",
            "tuple_identification",
            "--allow-prediction-errors",
        ]
    )

    assert rc == 0
    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["tuple_identification"]["prediction_error_count"] == 1


def test_benchmark_eval_resume_retries_error_predictions(tmp_path, monkeypatch):
    benchmark_dir = _write_tuple_task(tmp_path)
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    config_path = _write_config(tmp_path)
    error_prediction = {
        "task_id": "TI_E001",
        "event_id": "E001",
        "task_type": "tuple_identification",
        "model_name": "fake",
        "input": {},
        "output": {"gold_tuples": []},
        "prediction": {"tuples": [], "_error": "old error"},
    }
    _write_jsonl(output_dir / "tuple_identification_predictions.jsonl", [error_prediction])

    calls = []

    def success_runner(client, rows, model_name, prompt_dir=None):
        calls.extend(row["task_id"] for row in rows)
        return ([_prediction(rows[0], {"tuples": []}, model_name)], {})

    _patch_client(monkeypatch)
    _patch_runner(monkeypatch, success_runner)

    rc = run_benchmark_eval.main(
        [
            "--config",
            str(config_path),
            "--benchmark-dir",
            str(benchmark_dir),
            "--output-dir",
            str(output_dir),
            "--tasks",
            "tuple_identification",
            "--resume",
        ]
    )

    assert rc == 0
    assert calls == ["TI_E001"]
    predictions = _read_jsonl(output_dir / "tuple_identification_predictions.jsonl")
    assert len(predictions) == 1
    assert "_error" not in predictions[0]["prediction"]


def _patch_client(monkeypatch):
    client = type("Client", (), {"base_url": "https://unit.test/v1"})()
    monkeypatch.setattr(run_benchmark_eval, "build_llm_client", lambda model_config: client)


def _patch_runner(monkeypatch, runner):
    monkeypatch.setattr(
        run_benchmark_eval,
        "TASK_CONFIG",
        {
            "tuple_identification": {
                "file": "tuple_identification.jsonl",
                "runner": runner,
                "output_prefix": "tuple_identification",
            }
        },
    )


def _error_runner(client, rows, model_name, prompt_dir=None):
    return ([_prediction(rows[0], {"tuples": [], "_error": "boom"}, model_name)], {})


def _prediction(row, prediction, model_name):
    return {
        "task_id": row["task_id"],
        "event_id": row["event_id"],
        "task_type": "tuple_identification",
        "model_name": model_name,
        "input": row.get("input", {}),
        "output": row["output"],
        "prediction": prediction,
    }


def _write_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
run_id: unit-test
mode: benchmark
model:
  model_name: fake
  llm_model: fake
""",
        encoding="utf-8",
    )
    return config_path


def _write_tuple_task(tmp_path):
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    row = {
        "task_id": "TI_E001",
        "event_id": "E001",
        "input": {},
        "output": {"gold_tuples": []},
    }
    _write_jsonl(benchmark_dir / "tuple_identification.jsonl", [row])
    return benchmark_dir


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
