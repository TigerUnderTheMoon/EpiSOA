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


def test_parse_stakeholder_canonical_tuple_keeps_audit_fields():
    payload = {
        "event_id": "E001",
        "tuples": [
            {
                "stakeholder_cluster_id": "SC_E001_001",
                "stakeholder": "三元里村居民",
                "stakeholder_aliases": ["居民", "村民"],
                "opinion": "要求说明项目影响并公开回应搬迁安排",
                "sentiment": "negative",
                "rationale": "两条证据均描述居民提出公开回应诉求。",
                "evidence_ids": ["ev-1", "ev-2"],
                "support_label": "supported",
                "canonical_tuple": True,
                "opinion_split_reason": "",
            }
        ],
    }

    parsed, error = script.parse_payload(
        json.dumps(payload, ensure_ascii=False),
        "E001",
        {"ev-1", "ev-2"},
        "tuple",
        tuple_mode="stakeholder_canonical",
    )

    assert error == ""
    assert parsed[0]["candidate_id"] == "LLM_CANON_E001_001"
    assert parsed[0]["stakeholder_cluster_id"] == "SC_E001_001"
    assert parsed[0]["stakeholder_aliases"] == ["居民", "村民"]
    assert parsed[0]["canonical_tuple"] is True


def test_parse_stakeholder_canonical_rejects_duplicate_cluster_without_split_reason():
    payload = {
        "event_id": "E001",
        "tuples": [
            canonical_tuple("ev-1", opinion="要求公开信息", split_reason=""),
            canonical_tuple("ev-2", opinion="要求补偿", split_reason=""),
        ],
    }

    parsed, error = script.parse_payload(
        json.dumps(payload, ensure_ascii=False),
        "E001",
        {"ev-1", "ev-2"},
        "tuple",
        tuple_mode="stakeholder_canonical",
    )

    assert parsed == []
    assert error.startswith("duplicate_stakeholder_cluster_without_split_reason:SC_E001_001")


def test_parse_stakeholder_canonical_allows_duplicate_cluster_with_split_reason():
    payload = {
        "event_id": "E001",
        "tuples": [
            canonical_tuple("ev-1", opinion="要求公开信息", split_reason="同一主体的信息公开诉求"),
            canonical_tuple("ev-2", opinion="要求补偿", split_reason="同一主体的补偿诉求"),
        ],
    }

    parsed, error = script.parse_payload(
        json.dumps(payload, ensure_ascii=False),
        "E001",
        {"ev-1", "ev-2"},
        "tuple",
        tuple_mode="stakeholder_canonical",
    )

    assert error == ""
    assert len(parsed) == 2


def test_parse_stakeholder_canonical_rejects_unknown_evidence_id():
    payload = {"event_id": "E001", "tuples": [canonical_tuple("ev-missing")]}

    parsed, error = script.parse_payload(
        json.dumps(payload, ensure_ascii=False),
        "E001",
        {"ev-1"},
        "tuple",
        tuple_mode="stakeholder_canonical",
    )

    assert parsed == []
    assert error == "tuple_candidate_1_missing_valid_evidence_ids"


def test_stakeholder_canonical_excludes_held_out_events(tmp_path):
    paths = write_inputs(tmp_path)
    output_dir = tmp_path / "annotation"
    output_dir.mkdir()
    write_jsonl(
        paths["events"],
        [
            {"event_id": "E001", "event_name": "train event", "held_out": False},
            {"event_id": "E002", "event_name": "test event", "split": "test", "held_out": False},
        ],
    )
    write_jsonl(
        paths["evidence"],
        [
            {"event_id": "E001", "evidence_id": "ev-1", "source": "news", "text": "text 1"},
            {"event_id": "E002", "evidence_id": "ev-2", "source": "news", "text": "text 2"},
        ],
    )
    write_jsonl(
        output_dir / "llm_gold_tuples.jsonl",
        [
            {"event_id": "E001", "candidate_id": "old-train", "stakeholder": "s", "opinion": "o", "sentiment": "neutral"},
            {"event_id": "E002", "candidate_id": "old-test", "stakeholder": "s", "opinion": "o", "sentiment": "neutral"},
        ],
    )
    run_args = args(tmp_path, paths)
    run_args.all_events = True
    run_args.dry_run = True
    run_args.tasks = "tuple"
    run_args.tuple_mode = "stakeholder_canonical"

    report = script.run_preannotation(run_args)

    assert report["num_events"] == 1
    assert report["held_out_events_excluded"] == ["E002"]
    assert report["max_evidence"] == 60
    assert report["max_evidence_chars"] == 450
    tuples = read_jsonl(output_dir / "llm_gold_tuples.jsonl")
    assert {row["event_id"] for row in tuples} == {"E001"}


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


def canonical_tuple(evidence_id: str, *, opinion: str = "要求公开信息", split_reason: str = ""):
    return {
        "stakeholder_cluster_id": "SC_E001_001",
        "stakeholder": "居民",
        "stakeholder_aliases": ["居民"],
        "opinion": opinion,
        "sentiment": "negative",
        "rationale": "证据支持该诉求。",
        "evidence_ids": [evidence_id],
        "support_label": "supported",
        "canonical_tuple": True,
        "opinion_split_reason": split_reason,
    }


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
        tasks="tuple,chain",
        reuse_raw_responses=False,
        parse_raw_only=False,
        tuple_mode="standard",
        include_held_out=False,
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
