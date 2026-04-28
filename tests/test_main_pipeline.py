import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from episoa.experiment import configure_logging, create_run_context
from episoa.main import main, run_pipeline
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


def make_evidence(
    evidence_id: str,
    event: str,
    stakeholder: str,
    sentiment: str,
    day: int,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        platform="Example",
        url=f"https://example.com/{evidence_id}",
        timestamp=datetime(2026, 4, day, tzinfo=timezone.utc),
        text=f"{stakeholder} expressed {sentiment} views about {event} after public criticism.",
        author_alias=stakeholder,
        source_type="news",
        metadata={
            "event": event,
            "stakeholder": stakeholder,
            "sentiment": sentiment,
            "opinion": f"{stakeholder} expressed {sentiment} views about {event}.",
            "rationale": f"{stakeholder} evidence supports the attribution.",
        },
    )


def test_main_pipeline_runs_end_to_end_with_mock_data() -> None:
    output_path = Path(f"outputs/test_attributions_{uuid.uuid4().hex}.jsonl")
    evidence_pool = [
        make_evidence("ev-1", "Public criticism", "Customers", "negative", 1),
        make_evidence("ev-2", "Company response", "Employees", "mixed", 2),
        make_evidence("ev-3", "Policy change", "Company", "neutral", 3),
    ]

    results = run_pipeline(
        "Policy change after public criticism",
        {"start": "2026-04-01", "end": "2026-04-30"},
        config={"pipeline": {"top_k_evidence": 3, "eventrag_depth": 2, "eventrag_top_k": 2}},
        evidence_pool=evidence_pool,
        output_path=output_path,
    )

    assert results
    assert output_path.exists()

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    parsed = [AttributionTuple.model_validate(json.loads(line)) for line in lines]

    assert len(parsed) == len(results)
    assert all(item.event for item in parsed)


def test_main_demo_smoke_outputs_valid_jsonl() -> None:
    output_path = Path("outputs/demo_result.jsonl")

    exit_code = main(
        [
            "--demo",
            "--config",
            "configs/default.yaml",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.exists()

    lines = [line for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 1

    required_fields = {
        "event",
        "stakeholder",
        "opinion",
        "sentiment",
        "rationale",
        "evidence",
        "verified",
    }
    for line in lines:
        payload = json.loads(line)
        tuple_ = AttributionTuple.model_validate(payload)

        assert required_fields.issubset(payload)
        assert tuple_.event
        assert tuple_.stakeholder
        assert tuple_.opinion
        assert tuple_.sentiment
        assert tuple_.rationale
        assert tuple_.evidence
        assert isinstance(tuple_.verified, bool)


def test_main_pipeline_writes_run_artifacts() -> None:
    run_context = create_run_context("pytest-run-artifacts")
    configure_logging(run_context.log_path)
    evidence_pool = [
        make_evidence("ev-1", "Public criticism", "Customers", "negative", 1),
        make_evidence("ev-2", "Policy change", "Company", "neutral", 2),
    ]

    run_pipeline(
        "Policy change after public criticism",
        {"start": "2026-04-01", "end": "2026-04-30"},
        config={
            "pipeline": {"top_k_evidence": 2, "eventrag_depth": 2, "eventrag_top_k": 1},
            "llm": {"mode": "mock", "model": "mock-attribution", "prompt_version": "pytest-v1"},
            "reproducibility": {"seed": 123},
            "verifier": {"threshold": 0.75},
            "evaluation": {"gold_path": "data/pubevent_soa_lite/gold_tuples.jsonl", "k": 5},
        },
        evidence_pool=evidence_pool,
        run_context=run_context,
    )

    assert run_context.config_path.exists()
    assert run_context.predictions_path.exists()
    assert run_context.metrics_path.exists()
    assert run_context.log_path.exists()
    assert run_context.prompts_dir.exists()
    assert (run_context.run_dir / "README.md").exists()
    assert list(run_context.prompts_dir.glob("*.txt"))

    saved_config = yaml.safe_load(run_context.config_path.read_text(encoding="utf-8"))
    assert saved_config["run"]["run_id"] == run_context.run_id
    assert saved_config["reproducibility"]["seed"] == 123
    assert saved_config["reproducibility"]["model_name"] == "mock-attribution"
    assert saved_config["reproducibility"]["prompt_version"] == "pytest-v1"
    assert saved_config["reproducibility"]["top_k"] == 2
    assert saved_config["reproducibility"]["path_depth"] == 2
    assert saved_config["reproducibility"]["verifier_threshold"] == 0.75

    readme = (run_context.run_dir / "README.md").read_text(encoding="utf-8")
    assert "Random seed" in readme
    assert "mock-attribution" in readme
    assert "pytest-v1" in readme
