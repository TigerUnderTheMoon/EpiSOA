"""OpenAI-compatible LLM client used by EpiSOA modules."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import httpx

from episoa.config import resolve_api_config


@dataclass(frozen=True)
class LLMResponse:
    content: str
    response_id: str
    raw: dict[str, Any]


class OpenAICompatibleClient:
    """Small chat-completions client.

    The client intentionally accepts only prompt strings and returns raw text.
    Schema validation belongs to the caller.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        timeout_seconds: float = 60,
        max_retries: int = 2,
        thinking_mode: str | None = None,
        response_format_mode: str = "json_schema",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        # DeepSeek V4 defaults to thinking=enabled, which silently ignores
        # temperature and burns token budget on CoT. Set to "disabled" (or
        # "enabled") to emit the top-level `thinking` field in the payload.
        # None = do not emit (safe for providers that do not recognize it).
        self.thinking_mode = thinking_mode
        # "json_schema" (default, OpenAI-native) emits response_format as-is.
        # "json_object" auto-converts {type: json_schema, json_schema: {...}}
        # to {type: json_object} and injects the schema into system_prompt,
        # for providers that support only json_object (e.g. DeepSeek V4).
        self.response_format_mode = response_format_mode
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=httpx.Timeout(self.timeout_seconds))
        return self._client

    def _adapt_response_format(
        self,
        response_format: dict[str, Any] | None,
        system_prompt: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """Adapt json_schema response_format to json_object for providers that
        support only json_object (e.g. DeepSeek V4). Injects the schema as a
        JSON string into system_prompt so the model still gets structural
        guidance. No-op when response_format_mode == "json_schema" or when
        response_format is absent / already json_object.
        """
        if not response_format or self.response_format_mode != "json_object":
            return response_format, system_prompt
        if response_format.get("type") != "json_schema":
            return response_format, system_prompt
        wrapper = response_format.get("json_schema", {})
        name = wrapper.get("name", "response")
        schema = wrapper.get("schema", {})
        schema_json = json.dumps(schema, ensure_ascii=False)
        schema_instruction = (
            f"\n\n你的输出必须是一个 JSON 对象，且严格符合以下 JSON Schema（名称：{name}）：\n{schema_json}"
        )
        return {"type": "json_object"}, system_prompt + schema_instruction

    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        response_format, system_prompt = self._adapt_response_format(
            response_format, system_prompt
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.thinking_mode:
            payload["thinking"] = {"type": self.thinking_mode}
        if response_format:
            payload["response_format"] = response_format
        last_error: Exception | None = None
        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            try:
                response = self._get_client().post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                raw = response.json()
                content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                return LLMResponse(
                    content=str(content or ""),
                    response_id=str(raw.get("id", "")),
                    raw=raw,
                )
            except (httpx.HTTPStatusError, httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if response_format and attempt == 0 and _looks_like_response_format_error(exc):
                    payload.pop("response_format", None)
                    continue
        raise RuntimeError(f"LLM API call failed after retries: {last_error}") from last_error


def build_llm_client(model_config: dict[str, Any]) -> OpenAICompatibleClient:
    resolved = resolve_api_config(model_config, label="model")
    model_name = (
        model_config.get("model_name")
        or model_config.get("llm_model")
        or model_config.get("model")
        or "gpt-5.5"
    )
    thinking_mode_raw = model_config.get("thinking_mode")
    response_format_mode = str(model_config.get("response_format_mode", "json_schema"))
    return OpenAICompatibleClient(
        api_key=resolved["api_key"],
        base_url=resolved["base_url"],
        model_name=str(model_name),
        temperature=float(model_config.get("temperature", 0.0)),
        max_tokens=int(model_config.get("max_tokens", 3000)),
        timeout_seconds=float(model_config.get("timeout_seconds", 60)),
        max_retries=int(model_config.get("max_retries", 2)),
        thinking_mode=str(thinking_mode_raw) if thinking_mode_raw else None,
        response_format_mode=response_format_mode,
    )


def json_schema_response_format(name: str, schema: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": strict,
            "schema": schema,
        },
    }


def _looks_like_response_format_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "response_format" in text or "json_object" in text or "json_schema" in text or "unsupported" in text
