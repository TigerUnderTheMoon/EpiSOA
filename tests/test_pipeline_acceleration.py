import json
import threading
import time
from pathlib import Path

import pytest

from episoa.attribution.schema_attributor import attribution_cache_key, run_schema_attribution
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.pipeline import run_ablation_pipeline
from episoa.verifier.faithfulness_verifier import verifier_cache_key, verify_tuples


class FakeLLMClient:
    def __init__(self, delay: float = 0.0):
        self.calls = 0
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.model_name = "fake-model"
        self.base_url = "https://fake.test/v1"

    def chat(self, **_kwargs):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            call_no = self.calls
        try:
            if self.delay:
                time.sleep(self.delay)
            payload = {
                "event_id": f"E{call_no:03d}",
                "tuples": [
                    {
                        "stakeholder_cluster_id": "stakeholder_001",
                        "stakeholder": "Residents",
                        "stakeholder_aliases": [],
                        "opinion": f"Residents report issue {call_no}",
                        "sentiment": "negative",
                        "rationale": "Evidence states the issue.",
                        "evidence_ids": [f"ev-{call_no:03d}"],
                        "event_chain_stage": "response",
                        "support_status": "candidate_supported",
                        "confidence": 0.9,
                        "canonical_tuple": True,
                        "opinion_split_reason": "",
                        "stakeholder_candidate_match_status": "matched",
                    }
                ],
            }
            return type(
                "Response",
                (),
                {"content": json.dumps(payload), "response_id": f"fake-{call_no}", "raw": {}},
            )()
        finally:
            with self.lock:
                self.active -= 1


class FakeVerifierClient:
    model_name = "fake-model"
    base_url = "https://fake.test/v1"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return type("Response", (), {"content": '{"score": 0.6, "reason": "partial"}'})()


def test_attribution_cache_key_changes_when_inputs_change():
    base = _cache_key_payload()

    first = attribution_cache_key(**base)
    assert attribution_cache_key(**{**base, "model_name": "other"}) != first
    assert attribution_cache_key(**{**base, "method_version": "direct_llm"}) != first
    assert attribution_cache_key(**{**base, "selector_mode": "quality_topk"}) != first
    changed_evidence = [dict(base["evidence_items"][0], text="changed")]
    assert attribution_cache_key(**{**base, "evidence_items": changed_evidence}) != first
    assert attribution_cache_key(**base) == first


def test_schema_attribution_uses_cache_and_resume_without_recalling_llm(tmp_path):
    events = [_event("E001")]
    evidence = [_evidence("E001", "ev-001")]
    cache_dir = tmp_path / "cache"
    first_client = FakeLLMClient()

    first = run_schema_attribution(
        events=events,
        evidence_rows=evidence,
        chains=[],
        graph_nodes=[],
        llm_client=first_client,
        model_name="fake-model",
        output_dir=tmp_path / "first",
        method_version="legacy",
        cache_dir=cache_dir,
        resume=True,
    )

    second_client = FakeLLMClient()
    second = run_schema_attribution(
        events=events,
        evidence_rows=evidence,
        chains=[],
        graph_nodes=[],
        llm_client=second_client,
        model_name="fake-model",
        output_dir=tmp_path / "second",
        method_version="legacy",
        cache_dir=cache_dir,
        resume=True,
    )

    assert first_client.calls == 1
    assert second_client.calls == 0
    assert first["cache"]["misses"] == 1
    assert second["cache"]["hits"] == 1
    progress = read_jsonl(tmp_path / "second" / "progress.jsonl")
    assert progress[0]["status"] == "cache_hit"


def test_schema_attribution_parallel_output_order_is_deterministic(tmp_path):
    events = [_event("E001"), _event("E002"), _event("E003"), _event("E004")]
    evidence = [_evidence(event["event_id"], f"ev-{index:03d}") for index, event in enumerate(events, start=1)]
    client = FakeLLMClient(delay=0.01)

    summary = run_schema_attribution(
        events=events,
        evidence_rows=evidence,
        chains=[],
        graph_nodes=[],
        llm_client=client,
        model_name="fake-model",
        output_dir=tmp_path,
        method_version="legacy",
        max_api_concurrency=4,
    )

    assert client.max_active > 1
    assert summary["num_api_calls"] == 4
    raw_event_ids = [row["event_id"] for row in read_jsonl(tmp_path / "raw_llm_responses.jsonl")]
    assert raw_event_ids == ["E001", "E002", "E003", "E004"]


def test_verifier_cache_reuses_score_but_recomputes_threshold(tmp_path):
    prediction = PredictionTuple(
        event_id="E001",
        stakeholder="Residents",
        opinion="Residents report safety issue",
        sentiment="negative",
        rationale="Evidence states the issue.",
        evidence_ids=["ev-001"],
        support_label="supported",
    )
    evidence = [EvidenceRecord(event_id="E001", evidence_id="ev-001", source="news", text="Residents report safety issue.")]
    client = FakeVerifierClient()

    first = verify_tuples([prediction], evidence, threshold=0.75, llm_client=client, cache_dir=tmp_path)
    second = verify_tuples([prediction], evidence, threshold=0.5, llm_client=client, cache_dir=tmp_path)

    assert client.calls == 1
    assert first[0].verified is False
    assert first[0].support_label == "partially_supported"
    assert second[0].verified is True
    assert second[0].support_label == "supported"
    assert second[0].verification_diagnosis["cache_hit"] is True


def test_verifier_cache_key_changes_when_tuple_or_evidence_changes():
    prediction = PredictionTuple(
        event_id="E001",
        stakeholder="Residents",
        opinion="Residents report safety issue",
        sentiment="negative",
        rationale="Evidence states the issue.",
        evidence_ids=["ev-001"],
        support_label="supported",
    )
    evidence = {"ev-001": EvidenceRecord(event_id="E001", evidence_id="ev-001", text="Residents report safety issue.")}

    first = verifier_cache_key(prediction, evidence, model_name="fake", base_url="https://fake.test/v1", mode="decomposed")
    changed_prediction = prediction.model_copy(update={"opinion": "Residents report another issue"})
    changed_evidence = {"ev-001": EvidenceRecord(event_id="E001", evidence_id="ev-001", text="Changed evidence.")}

    assert verifier_cache_key(changed_prediction, evidence, model_name="fake", base_url="https://fake.test/v1", mode="decomposed") != first
    assert verifier_cache_key(prediction, changed_evidence, model_name="fake", base_url="https://fake.test/v1", mode="decomposed") != first
    assert verifier_cache_key(prediction, evidence, model_name="other", base_url="https://fake.test/v1", mode="decomposed") != first


def test_ablation_reuses_full_soe_attribution_for_id_only_verifier(monkeypatch, tmp_path):
    config_path = _write_minimal_config(tmp_path, ["full_soe", "without_decomposed_verifier"])
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr("episoa.pipeline.print_api_config_status", lambda _config: None)
    monkeypatch.setattr("episoa.pipeline._validate_pipeline_data", lambda _config: {"paper_data_ready": True})
    monkeypatch.setattr("episoa.pipeline._create_llm_client", lambda _config: object())
    monkeypatch.setattr("episoa.pipeline._get_git_commit", lambda: "test-sha")
    monkeypatch.setattr("episoa.pipeline.read_typed_jsonl", _fake_read_typed_jsonl)
    monkeypatch.setattr("episoa.pipeline.evaluate_ablation", lambda _gold, verified, verifier_enabled=True: {"Num-Tuples": len(verified), "Tuple-F1-soft": 1.0})
    monkeypatch.setattr("episoa.pipeline._write_scoring_artifacts", lambda *_args, **_kwargs: {"excluded_prediction_count": 0, "excluded_event_ids": []})
    monkeypatch.setattr("episoa.pipeline.write_ablation_delta_audits", lambda **_kwargs: {})
    monkeypatch.setattr("episoa.pipeline.write_ablation_audit_report", lambda **_kwargs: tmp_path / "audit.md")

    def fake_core(*_args, run_id=None, reuse_attribution_dir=None, output_dir=None, **_kwargs):
        calls.append((str(run_id), str(reuse_attribution_dir) if reuse_attribution_dir else None))
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        write_jsonl(
            out / "candidate_soa_tuples.jsonl",
            [PredictionTuple(event_id="E001", stakeholder="Residents", opinion="o", sentiment="negative", rationale="r", evidence_ids=["ev-001"], support_label="supported")],
        )
        write_jsonl(out / "verified_soa_tuples.jsonl", [])
        write_jsonl(out / "predictions.jsonl", [])
        return [], {}, {}

    monkeypatch.setattr("episoa.pipeline._run_core_pipeline", fake_core)

    summary = run_ablation_pipeline(config_path, force=True, resume=True, cache_dir=tmp_path / "cache")

    assert calls[0] == ("ablation_full_soe", None)
    assert calls[1][0] == "ablation_without_decomposed_verifier"
    assert calls[1][1].endswith("ablation_full_soe")
    assert summary["reuse"]["without_decomposed_verifier"]["source_setting"] == "full_soe"
    reuse_manifest = json.loads((tmp_path / "runs" / "ablation_without_decomposed_verifier" / "reuse_manifest.json").read_text())
    assert reuse_manifest["reuse_source_setting"] == "full_soe"


def test_diagnostic_mode_writes_isolated_diagnostic_metadata(monkeypatch, tmp_path):
    config_path = _write_minimal_config(tmp_path, ["full_soe"])

    monkeypatch.setattr("episoa.pipeline.print_api_config_status", lambda _config: None)
    monkeypatch.setattr("episoa.pipeline._validate_pipeline_data", lambda _config: {"paper_data_ready": True})
    monkeypatch.setattr("episoa.pipeline._create_llm_client", lambda _config: object())
    monkeypatch.setattr("episoa.pipeline._get_git_commit", lambda: "test-sha")
    monkeypatch.setattr("episoa.pipeline.read_typed_jsonl", _fake_read_typed_jsonl)
    monkeypatch.setattr("episoa.pipeline.evaluate_ablation", lambda _gold, verified, verifier_enabled=True: {"Num-Tuples": len(verified), "Tuple-F1-soft": 1.0})
    monkeypatch.setattr("episoa.pipeline._write_scoring_artifacts", lambda *_args, **_kwargs: {"excluded_prediction_count": 0, "excluded_event_ids": []})
    monkeypatch.setattr("episoa.pipeline.write_ablation_delta_audits", lambda **_kwargs: {})
    monkeypatch.setattr("episoa.pipeline.write_ablation_audit_report", lambda **_kwargs: tmp_path / "audit.md")
    monkeypatch.setattr("episoa.pipeline._run_core_pipeline", lambda *args, **kwargs: ([], {}, {}))

    summary = run_ablation_pipeline(
        config_path,
        force=True,
        diagnostic=True,
        max_events=1,
        event_ids=["E001"],
        settings=["full_soe"],
    )

    assert summary["diagnostic_only"] is True
    assert summary["runs_dir"].endswith("_diagnostic")
    manifest = json.loads((Path(summary["runs_dir"]) / "runtime_manifest.json").read_text())
    assert manifest["diagnostic_only"] is True
    assert manifest["max_events"] == 1
    assert manifest["event_ids"] == ["E001"]


def _cache_key_payload():
    return {
        "event": _event("E001"),
        "chain": {},
        "evidence_items": [_evidence("E001", "ev-001")],
        "stakeholder_candidates": ["Residents"],
        "model_name": "fake-model",
        "base_url": "https://fake.test/v1",
        "method_version": "legacy",
        "selector_mode": "coverage_optimized",
        "max_tuples_per_event": 8,
        "flags": {"hide_chain_in_prompt": False},
    }


def _event(event_id: str):
    return {
        "event_id": event_id,
        "event_name": f"Event {event_id}",
        "event_description": "A public event.",
        "query_seeds": ["seed"],
        "stakeholder_hints": ["Residents"],
    }


def _evidence(event_id: str, evidence_id: str):
    return {"event_id": event_id, "evidence_id": evidence_id, "text": "Residents report safety issue.", "source": "news"}


def _write_minimal_config(tmp_path: Path, settings: list[str]) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "run_id: paper",
                "mode: ablation",
                "data:",
                "  events_path: events.jsonl",
                "  evidence_path: evidence.jsonl",
                "  gold_tuples_path: gold.jsonl",
                "  gold_event_chains_path: chains.jsonl",
                "output:",
                f"  runs_dir: {str(tmp_path / 'runs').replace(chr(92), '/')}",
                "model:",
                "  api_key: test-key",
                "  base_url: https://fake.test/v1",
                "  llm_model: fake-model",
                "search: {}",
                "retrieval:",
                "  top_k: 5",
                "verifier:",
                "  threshold: 0.75",
                "ablation:",
                "  method_version: soe_v3",
                "  max_evidence_per_event: 24",
                "  settings:",
                *[f"    - {setting}" for setting in settings],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _fake_read_typed_jsonl(_path, model):
    name = model.__name__
    if name == "EventRecord":
        return []
    if name == "EvidenceRecord":
        return []
    if name == "GoldTuple":
        return []
    if name == "GoldEventChain":
        return []
    raise AssertionError(name)
