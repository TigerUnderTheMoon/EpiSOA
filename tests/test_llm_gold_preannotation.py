from argparse import Namespace
import importlib.util
import json
from pathlib import Path

from episoa.annotation.gold_annotation import validate_gold_dataset
from episoa.data.loader import write_jsonl


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_llm_gold_preannotation.py"
SPEC = importlib.util.spec_from_file_location("run_llm_gold_preannotation_script", SCRIPT_PATH)
script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(script)


class FakeResponse:
    def __init__(self, content: str):
        self.content = content
        self.response_id = "fake-response"


class FailingClient:
    model_name = "fake"

    def chat(self, **_kwargs):
        raise TimeoutError("read operation timed out")


class InvalidJsonClient:
    model_name = "fake"

    def chat(self, **_kwargs):
        return FakeResponse("not json")


class EventAwareClient:
    model_name = "fake"

    def chat(self, *, user_prompt, **_kwargs):
        payload = json.loads(user_prompt)
        event_id = payload["event"]["event_id"]
        evidence_id = payload["evidence"][0]["evidence_id"]
        if '"tuples"' in _kwargs.get("system_prompt", ""):
            pass
        if "tuples" in user_prompt:
            return FakeResponse("{}")
        return FakeResponse(
            json.dumps(
                {
                    "event_id": event_id,
                    "tuples": [
                        {
                            "stakeholder": f"s-{event_id}",
                            "opinion": f"o-{event_id}",
                            "sentiment": "neutral",
                            "rationale": "r",
                            "evidence_ids": [evidence_id],
                            "support_label": "supported",
                        }
                    ],
                    "event_chains": [{"event_chain": [f"c-{event_id}"], "evidence_ids": [evidence_id]}],
                }
            )
        )


def test_failed_api_audit(tmp_path, monkeypatch):
    paths = write_inputs(tmp_path)
    monkeypatch.setattr(script, "build_llm_client", lambda _config: FailingClient())

    report = script.run_preannotation(args(tmp_path, paths))
    audit = read_jsonl(tmp_path / "annotation" / "llm_preannotation_audit.jsonl")

    assert report["api_failures"] == 2
    assert audit[0]["request_status"] == "failed"
    assert audit[0]["parse_status"] == "not_run"
    assert audit[0]["error_type"] == "api_timeout"
    assert Path(audit[0]["raw_response_path"]).exists()


def test_parse_failure_audit(tmp_path, monkeypatch):
    paths = write_inputs(tmp_path)
    monkeypatch.setattr(script, "build_llm_client", lambda _config: InvalidJsonClient())

    report = script.run_preannotation(args(tmp_path, paths))
    audit = read_jsonl(tmp_path / "annotation" / "llm_preannotation_audit.jsonl")

    assert report["parse_failures"] == 2
    assert audit[0]["request_status"] == "ok"
    assert audit[0]["parse_status"] == "failed"
    assert audit[0]["error_type"] == "invalid_json"


def test_select_events_respects_max_events_and_start_index():
    events = [{"event_id": f"E{i:03d}"} for i in range(5)]

    selected = script.select_events(events, "", max_events=2, start_index=1)

    assert [row["event_id"] for row in selected] == ["E001", "E002"]


def test_select_events_respects_event_ids():
    events = [{"event_id": "E001"}, {"event_id": "E002"}, {"event_id": "E003"}]

    selected = script.select_events(events, "E003,E001", max_events=None)

    assert [row["event_id"] for row in selected] == ["E001", "E003"]


def test_empty_gold_schema_valid_but_not_ready(tmp_path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    gold_tuples = tmp_path / "gold_tuples.jsonl"
    gold_chains = tmp_path / "gold_event_chains.jsonl"
    write_jsonl(events, [{"event_id": "E001", "event_name": "event"}])
    write_jsonl(evidence, [{"event_id": "E001", "evidence_id": "ev-1", "source": "news", "text": "text"}])
    gold_tuples.write_text("", encoding="utf-8")
    gold_chains.write_text("", encoding="utf-8")

    report = validate_gold_dataset(gold_tuples, gold_chains, evidence, events)

    assert report["schema_valid"] is True
    assert report["nonempty_gold"] is False
    assert report["ready_for_paper"] is False


def test_retry_failed_preserves_existing_candidates(tmp_path, monkeypatch):
    paths = write_inputs(tmp_path)
    output_dir = tmp_path / "annotation"
    output_dir.mkdir()
    write_jsonl(output_dir / "llm_gold_tuples.jsonl", [{"event_id": "E001", "stakeholder": "s", "opinion": "o", "sentiment": "neutral"}])
    write_jsonl(output_dir / "llm_gold_event_chains.jsonl", [{"event_id": "E001", "event_chain": ["a"], "evidence_ids": ["ev-1"]}])
    write_jsonl(
        output_dir / "llm_preannotation_audit.jsonl",
        [{"event_id": "E001", "task_type": "tuple", "request_status": "failed", "parse_status": "not_run"}],
    )
    monkeypatch.setattr(script, "build_llm_client", lambda _config: FailingClient())
    run_args = args(tmp_path, paths)
    run_args.retry_failed = True

    script.run_preannotation(run_args)
    tuples = read_jsonl(output_dir / "llm_gold_tuples.jsonl")
    chains = read_jsonl(output_dir / "llm_gold_event_chains.jsonl")

    assert tuples == [{"event_id": "E001", "stakeholder": "s", "opinion": "o", "sentiment": "neutral"}]
    assert chains == [{"event_id": "E001", "event_chain": ["a"], "evidence_ids": ["ev-1"]}]


def test_batch_run_merges_existing_outputs_by_default(tmp_path, monkeypatch):
    paths = write_multi_event_inputs(tmp_path)
    output_dir = tmp_path / "annotation"
    output_dir.mkdir()
    write_jsonl(
        output_dir / "llm_gold_tuples.jsonl",
        [
            {"event_id": f"E{i:03d}", "candidate_id": f"old-{i}", "stakeholder": f"s-old-{i}", "opinion": "o", "sentiment": "neutral"}
            for i in range(1, 6)
        ],
    )
    write_jsonl(
        output_dir / "llm_gold_event_chains.jsonl",
        [
            {"event_id": f"E{i:03d}", "candidate_chain_id": f"old-c-{i}", "event_chain": ["old"], "evidence_ids": [f"ev-{i}"]}
            for i in range(1, 6)
        ],
    )
    write_jsonl(output_dir / "llm_preannotation_audit.jsonl", [{"event_id": "E001", "task_type": "tuple"}])
    monkeypatch.setattr(script, "build_llm_client", lambda _config: EventAwareClient())
    run_args = args(tmp_path, paths)
    run_args.start_index = 5
    run_args.max_events = 5

    report = script.run_preannotation(run_args)
    tuples = read_jsonl(output_dir / "llm_gold_tuples.jsonl")
    chains = read_jsonl(output_dir / "llm_gold_event_chains.jsonl")
    audit = read_jsonl(output_dir / "llm_preannotation_audit.jsonl")

    assert {row["event_id"] for row in tuples} == {f"E{i:03d}" for i in range(1, 11)}
    assert {row["event_id"] for row in chains} == {f"E{i:03d}" for i in range(1, 11)}
    assert report["existing_tuple_events_before_run"] == 5
    assert report["merged_tuple_events_after_run"] == 10
    assert any(row["event_id"] == "E001" for row in audit)


def test_overwrite_output_keeps_only_current_batch(tmp_path, monkeypatch):
    paths = write_multi_event_inputs(tmp_path)
    output_dir = tmp_path / "annotation"
    output_dir.mkdir()
    write_jsonl(
        output_dir / "llm_gold_tuples.jsonl",
        [{"event_id": "E001", "candidate_id": "old", "stakeholder": "old", "opinion": "old", "sentiment": "neutral"}],
    )
    write_jsonl(output_dir / "llm_gold_event_chains.jsonl", [{"event_id": "E001", "candidate_chain_id": "old", "event_chain": ["old"], "evidence_ids": ["ev-1"]}])
    write_jsonl(output_dir / "llm_preannotation_audit.jsonl", [{"event_id": "E001", "task_type": "tuple"}])
    monkeypatch.setattr(script, "build_llm_client", lambda _config: EventAwareClient())
    run_args = args(tmp_path, paths)
    run_args.start_index = 5
    run_args.max_events = 5
    run_args.overwrite_output = True

    report = script.run_preannotation(run_args)
    tuples = read_jsonl(output_dir / "llm_gold_tuples.jsonl")
    audit = read_jsonl(output_dir / "llm_preannotation_audit.jsonl")

    assert {row["event_id"] for row in tuples} == {f"E{i:03d}" for i in range(6, 11)}
    assert report["existing_tuple_events_before_run"] == 0
    assert report["merged_tuple_events_after_run"] == 5
    assert all(row["event_id"] != "E001" for row in audit)


def write_inputs(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    config = tmp_path / "config.yaml"
    tuple_prompt = tmp_path / "tuple.md"
    chain_prompt = tmp_path / "chain.md"
    write_jsonl(events, [{"event_id": "E001", "event_name": "event"}])
    write_jsonl(evidence, [{"event_id": "E001", "evidence_id": "ev-1", "source": "news", "text": "text"}])
    config.write_text("model: {}\n", encoding="utf-8")
    tuple_prompt.write_text("{{EVENT_CONTEXT_JSON}}", encoding="utf-8")
    chain_prompt.write_text("{{EVENT_CONTEXT_JSON}}", encoding="utf-8")
    return {
        "events": events,
        "evidence": evidence,
        "config": config,
        "tuple_prompt": tuple_prompt,
        "chain_prompt": chain_prompt,
    }


def write_multi_event_inputs(tmp_path: Path):
    paths = write_inputs(tmp_path)
    write_jsonl(paths["events"], [{"event_id": f"E{i:03d}", "event_name": f"event {i}"} for i in range(1, 11)])
    write_jsonl(
        paths["evidence"],
        [{"event_id": f"E{i:03d}", "evidence_id": f"ev-{i}", "source": "news", "text": f"text {i}"} for i in range(1, 11)],
    )
    return paths


def args(tmp_path: Path, paths: dict[str, Path]) -> Namespace:
    return Namespace(
        config=str(paths["config"]),
        events=str(paths["events"]),
        evidence=str(paths["evidence"]),
        output_dir=str(tmp_path / "annotation"),
        tuple_prompt=str(paths["tuple_prompt"]),
        chain_prompt=str(paths["chain_prompt"]),
        event_ids="",
        max_events=1,
        start_index=0,
        all_events=False,
        retry_failed=False,
        merge_existing=True,
        overwrite_output=False,
        audit_file=str(tmp_path / "annotation" / "llm_preannotation_audit.jsonl"),
        max_evidence=8,
        max_evidence_chars=500,
        temperature=0.0,
        timeout_seconds=1.0,
        max_retries=0,
        dry_run=False,
    )


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
