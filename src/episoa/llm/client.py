"""Unified LLM client for EpiSOA.

All modules should depend on `LLMClient` instead of calling concrete provider
APIs directly.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import TypeAdapter

from episoa.experiment import get_logger
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain


LLMMode = Literal["mock", "real", "openai_compatible", "local"]

logger = get_logger("llm.client")


class StructuredLLMClient(Protocol):
    """Protocol consumed by EpiSOA modules."""

    def generate_structured_attribution(
        self,
        prompt: str,
        schema: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Generate structured attribution data."""

    def generate_structured_verification(
        self,
        prompt: str,
        schema: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Generate structured verification data."""


@dataclass(frozen=True)
class LLMClientConfig:
    """Runtime config for the unified LLM client."""

    mode: LLMMode = "mock"
    model: str = "mock-attribution"
    base_url: str = "http://localhost:8000/v1"
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    local_command: list[str] | None = None
    prompt_log_dir: str | None = None
    temperature: float = 0.0


class LLMClient:
    """Unified client supporting mock, OpenAI-compatible, and local modes."""

    def __init__(self, config: LLMClientConfig | dict[str, Any] | None = None) -> None:
        self.config = config if isinstance(config, LLMClientConfig) else config_from_dict(config or {})

    def generate_structured_attribution(
        self,
        prompt: str,
        schema: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Generate structured attribution data with retries, timeout, and logging."""
        self._record_prompt("generate_structured_attribution", prompt)
        return self._with_retries(
            "generate_structured_attribution",
            lambda: _validate_schema_output(
                self._generate_structured_attribution_once(prompt, schema, context=context),
                schema,
            ),
        )

    def generate_structured_verification(
        self,
        prompt: str,
        schema: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Generate structured verification data with retries and schema validation."""
        self._record_prompt("generate_structured_verification", prompt)
        return self._with_retries(
            "generate_structured_verification",
            lambda: _validate_schema_output(
                self._generate_structured_verification_once(prompt, schema, context=context),
                schema,
            ),
        )

    def _generate_structured_attribution_once(
        self,
        prompt: str,
        schema: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        if self.config.mode == "mock":
            return _mock_structured_attribution(context or {})
        if self.config.mode in {"real", "openai_compatible"}:
            return self._openai_compatible_json(prompt, schema)
        if self.config.mode == "local":
            return self._local_json(prompt, schema)
        raise ValueError(f"Unsupported LLM mode: {self.config.mode}")

    def _generate_structured_verification_once(
        self,
        prompt: str,
        schema: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        if self.config.mode == "mock":
            return _mock_structured_verification(context or {})
        if self.config.mode in {"real", "openai_compatible"}:
            return self._openai_compatible_json(prompt, schema)
        if self.config.mode == "local":
            return self._local_json(prompt, schema)
        raise ValueError(f"Unsupported LLM mode: {self.config.mode}")

    def _openai_compatible_json(self, prompt: str, schema: Any) -> Any:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        api_key = self.config.api_key or os.getenv(self.config.api_key_env)
        if not api_key and (self.config.mode == "real" or "api.openai.com" in self.config.base_url):
            raise RuntimeError(
                f"Real LLM mode requires an API key. Set llm.api_key in config or {self.config.api_key_env}."
            )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON matching the requested schema. "
                        "Do not include markdown, comments, or explanatory text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": _response_format_for_schema(schema),
            "temperature": self.config.temperature,
        }
        logger.info("Calling OpenAI-compatible LLM model=%s url=%s", self.config.model, url)
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return _loads_json_output(content)

    def _local_json(self, prompt: str, schema: Any) -> Any:
        if not self.config.local_command:
            raise ValueError("local mode requires llm.local_command")

        logger.info("Calling local LLM command=%s", self.config.local_command)
        completed = subprocess.run(
            self.config.local_command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.config.timeout_seconds,
            check=True,
        )
        return _loads_json_output(completed.stdout)

    def _with_retries(self, operation: str, func):
        attempts = max(1, self.config.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                logger.info("LLM operation=%s attempt=%s/%s mode=%s", operation, attempt, attempts, self.config.mode)
                return func()
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM operation=%s failed attempt=%s/%s error=%s",
                    operation,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(min(2 ** (attempt - 1), 5))
        detail = f": {last_error}" if last_error is not None else ""
        raise RuntimeError(f"LLM operation failed after {attempts} attempts: {operation}{detail}") from last_error

    def _record_prompt(self, operation: str, prompt: str) -> None:
        if not self.config.prompt_log_dir:
            return
        prompt_dir = Path(self.config.prompt_log_dir)
        prompt_dir.mkdir(parents=True, exist_ok=True)
        existing = len(list(prompt_dir.glob(f"{operation}_*.txt")))
        prompt_path = prompt_dir / f"{operation}_{existing + 1:04d}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")


def config_from_dict(raw: dict[str, Any]) -> LLMClientConfig:
    """Build LLMClientConfig from YAML-compatible config."""
    _load_dotenv()
    mode = raw.get("llm_mode") or raw.get("mode") or os.getenv("EPISOA_LLM_MODE", "mock")
    if mode not in {"mock", "real", "openai_compatible", "local"}:
        raise ValueError("llm.mode must be one of: mock, real, openai_compatible, local")

    local_command = raw.get("local_command")
    if isinstance(local_command, str):
        local_command = [local_command]

    return LLMClientConfig(
        mode=mode,
        model=str(raw.get("model") or raw.get("llm_model") or os.getenv("OPENAI_MODEL") or "mock-attribution"),
        base_url=str(raw.get("base_url") or os.getenv("OPENAI_BASE_URL") or "http://localhost:8000/v1"),
        api_key=raw.get("api_key") or os.getenv(str(raw.get("api_key_env", "OPENAI_API_KEY"))),
        api_key_env=str(raw.get("api_key_env", "OPENAI_API_KEY")),
        timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
        max_retries=int(raw.get("max_retries", 2)),
        local_command=local_command,
        prompt_log_dir=raw.get("prompt_log_dir"),
        temperature=float(raw.get("temperature", 0.0)),
    )


def build_llm_client(config: dict[str, Any] | None = None) -> LLMClient:
    """Create the configured unified LLM client."""
    raw = config or {}
    llm_config = dict(raw.get("llm", raw))
    if "llm_mode" in raw and "llm_mode" not in llm_config and "mode" not in llm_config:
        llm_config["llm_mode"] = raw["llm_mode"]
    return LLMClient(llm_config)


def _load_dotenv(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE pairs from .env without overriding the process env."""
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _response_format_for_schema(schema: Any) -> dict[str, Any]:
    """Build an OpenAI-compatible structured-output response format."""
    json_schema = TypeAdapter(schema).json_schema()
    if json_schema.get("type") == "array":
        defs = json_schema.pop("$defs", None)
        json_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "attributions": json_schema,
            },
            "required": ["attributions"],
        }
        if defs:
            json_schema["$defs"] = defs
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "attribution_tuples",
            "strict": True,
            "schema": json_schema,
        },
    }


def _validate_schema_output(raw_output: Any, schema: Any) -> Any:
    """Validate provider output inside the retry boundary."""
    return TypeAdapter(schema).validate_python(raw_output)


def _loads_json_output(content: str) -> Any:
    parsed = json.loads(_repair_json_output(content))
    if isinstance(parsed, dict) and "items" in parsed:
        return parsed["items"]
    if isinstance(parsed, dict) and "attributions" in parsed:
        return parsed["attributions"]
    if isinstance(parsed, dict) and "attribution_tuples" in parsed:
        return parsed["attribution_tuples"]
    if isinstance(parsed, dict) and "verification" in parsed:
        return parsed["verification"]
    return parsed


def _repair_json_output(content: str) -> str:
    """Repair common LLM JSON formatting issues without changing semantics."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    extracted = _extract_first_json_value(text)
    if extracted is not None:
        try:
            json.loads(extracted)
            return extracted
        except json.JSONDecodeError:
            repaired = _remove_trailing_commas(extracted)
            json.loads(repaired)
            return repaired

    repaired = _remove_trailing_commas(text)
    json.loads(repaired)
    return repaired


def _extract_first_json_value(text: str) -> str | None:
    starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
    if not starts:
        return None
    start = min(starts)
    opener = text[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _mock_structured_attribution(context: dict[str, Any]) -> list[dict[str, Any]]:
    event_chain: EventChain | None = context.get("event_chain")
    evidence_records: list[EvidenceRecord] = list(context.get("evidence_records", []))
    target_event_description = str(context.get("target_event_description") or "")
    min_evidence_for_verified = int(context.get("min_evidence_for_verified", 2))

    if event_chain is None or not evidence_records:
        return []

    grouped: dict[str, list[EvidenceRecord]] = {}
    for evidence in evidence_records:
        stakeholder = str(evidence.metadata.get("stakeholder") or evidence.author_alias or "unknown").strip() or "unknown"
        grouped.setdefault(stakeholder, []).append(evidence)

    output: list[dict[str, Any]] = []
    for stakeholder, stakeholder_evidence in grouped.items():
        verified = len(stakeholder_evidence) >= min_evidence_for_verified
        output.append(
            {
                "event": target_event_description.strip() or event_chain.target_event,
                "stakeholder": stakeholder,
                "opinion": _opinion_for(stakeholder_evidence),
                "sentiment": _sentiment_for(stakeholder_evidence),
                "rationale": _rationale_for(stakeholder_evidence, verified),
                "event_chain": event_chain.event_chain,
                "evidence": stakeholder_evidence,
                "support_score": min(1.0, len(stakeholder_evidence) / max(min_evidence_for_verified, 1)),
                "verified": verified,
            }
        )
    return output


def _opinion_for(evidence_records: list[EvidenceRecord]) -> str:
    for item in evidence_records:
        opinion = item.metadata.get("opinion")
        if opinion and str(opinion).strip():
            return str(opinion).strip()
    return evidence_records[0].text


def _sentiment_for(evidence_records: list[EvidenceRecord]) -> str:
    allowed = {"positive", "negative", "neutral", "mixed", "unknown"}
    labels = [
        str(item.metadata.get("sentiment") or item.metadata.get("stance") or "unknown").strip().lower()
        for item in evidence_records
    ]
    labels = [label for label in labels if label in allowed]
    if not labels:
        return "unknown"
    if len(set(labels)) > 1:
        return "mixed"
    return labels[0]


def _rationale_for(evidence_records: list[EvidenceRecord], verified: bool) -> str:
    if not verified:
        return "insufficient evidence"
    rationale = evidence_records[0].metadata.get("rationale")
    if rationale and str(rationale).strip():
        return str(rationale).strip()
    return "Supported by cited evidence."


def _mock_structured_verification(context: dict[str, Any]) -> dict[str, Any]:
    support_score = float(context.get("support_score", 0.0))
    threshold = float(context.get("threshold", 0.75))
    verified = support_score >= threshold
    return {
        "support_score": max(0.0, min(1.0, support_score)),
        "verified": verified,
        "failure_reason": None if verified else str(context.get("failure_reason") or "support_score below threshold"),
    }
