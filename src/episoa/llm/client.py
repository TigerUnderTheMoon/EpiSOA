"""OpenAI-compatible LLM client used by EpiSOA modules."""

from __future__ import annotations

from dataclasses import dataclass
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
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, str] | None = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
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
        if response_format:
            payload["response_format"] = response_format
        last_error: Exception | None = None
        attempts = max(1, self.max_retries + 1)
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                    response = client.post(
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
        or "gpt-4o-mini"
    )
    return OpenAICompatibleClient(
        api_key=resolved["api_key"],
        base_url=resolved["base_url"],
        model_name=str(model_name),
        temperature=float(model_config.get("temperature", 0.0)),
        max_tokens=int(model_config.get("max_tokens", 3000)),
        timeout_seconds=float(model_config.get("timeout_seconds", 60)),
        max_retries=int(model_config.get("max_retries", 2)),
    )


def _looks_like_response_format_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "response_format" in text or "json_object" in text or "unsupported" in text
