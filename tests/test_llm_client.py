from datetime import datetime, timezone

import pytest

from episoa.llm.client import LLMClient, _loads_json_output, config_from_dict
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain


def make_evidence(evidence_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        platform="Example",
        url=f"https://example.com/{evidence_id}",
        timestamp=datetime(2026, 4, 26, tzinfo=timezone.utc),
        text="Customers opposed the policy change.",
        author_alias="Customers",
        source_type="news",
        metadata={
            "stakeholder": "Customers",
            "sentiment": "negative",
            "opinion": "Customers opposed the policy change.",
        },
    )


def test_mock_llm_client_generates_structured_attribution() -> None:
    evidence = [make_evidence("ev-1"), make_evidence("ev-2")]
    event_chain = EventChain(
        target_event="Policy change",
        event_chain=["Public criticism", "Policy change"],
        stakeholders=["Customers"],
        evidence=evidence,
    )
    client = LLMClient({"mode": "mock"})

    result = client.generate_structured_attribution(
        "prompt",
        list,
        context={
            "event_chain": event_chain,
            "evidence_records": evidence,
            "target_event_description": "Policy change",
        },
    )

    assert result[0]["stakeholder"] == "Customers"
    assert result[0]["verified"] is True


def test_config_from_dict_supports_local_command_string() -> None:
    config = config_from_dict({"mode": "local", "local_command": "dummy", "timeout_seconds": 1})

    assert config.mode == "local"
    assert config.local_command == ["dummy"]
    assert config.timeout_seconds == 1


def test_config_from_dict_supports_real_mode() -> None:
    config = config_from_dict({"mode": "real", "model": "example-model"})

    assert config.mode == "real"
    assert config.model == "example-model"


def test_llm_json_repair_extracts_json_without_explanatory_text() -> None:
    content = 'Here is the JSON:\n```json\n{"attributions": [{"stakeholder": "Customers",}],}\n```'

    result = _loads_json_output(content)

    assert result == [{"stakeholder": "Customers"}]


def test_llm_client_retries_and_raises_after_failures() -> None:
    client = LLMClient({"mode": "local", "local_command": ["missing-command"], "max_retries": 1, "timeout_seconds": 1})

    with pytest.raises(RuntimeError):
        client.generate_structured_attribution("prompt", list)


def test_real_llm_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = LLMClient(
        {
            "mode": "real",
            "model": "example-model",
            "base_url": "https://api.openai.com/v1",
            "max_retries": 0,
        }
    )

    with pytest.raises(RuntimeError, match="Real LLM mode requires an API key"):
        client.generate_structured_attribution("prompt", list)
