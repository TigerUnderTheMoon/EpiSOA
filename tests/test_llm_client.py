import httpx
import copy
import tomllib
from pathlib import Path

from episoa.llm import client as llm_client_module
from episoa.llm.client import OpenAICompatibleClient


class FakeHttpxResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"id": "fake-response", "choices": [{"message": {"content": "ok"}}]}


class FailingHttpxResponse:
    text = '{"error":{"message":"bad request detail"}}'

    def raise_for_status(self):
        request = httpx.Request("POST", "https://example.test/v1/chat/completions")
        response = httpx.Response(400, request=request, text=self.text)
        raise httpx.HTTPStatusError("400 Bad Request", request=request, response=response)


class ResponseFormatFailingHttpxResponse(FailingHttpxResponse):
    text = '{"error":{"message":"This response_format type is unavailable now"}}'


class CountingHttpxClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.posts = []
        CountingHttpxClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        return FakeHttpxResponse()

    def close(self):
        return None


def test_openai_compatible_client_reuses_httpx_client(monkeypatch):
    CountingHttpxClient.instances = []
    monkeypatch.setattr(llm_client_module.httpx, "Client", CountingHttpxClient)
    monkeypatch.setattr(llm_client_module.httpx, "Timeout", lambda value: value)

    client = OpenAICompatibleClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model_name="fake-model",
    )

    first = client.chat(system_prompt="system", user_prompt="user")
    second = client.chat(system_prompt="system", user_prompt="user")

    assert first.content == "ok"
    assert second.content == "ok"
    assert len(CountingHttpxClient.instances) == 1
    assert len(CountingHttpxClient.instances[0].posts) == 2


def test_http_status_errors_include_provider_response_body(monkeypatch):
    class FailingHttpxClient:
        def post(self, *args, **kwargs):
            return FailingHttpxResponse()

    monkeypatch.setattr(llm_client_module.httpx, "Client", lambda *args, **kwargs: FailingHttpxClient())
    monkeypatch.setattr(llm_client_module.httpx, "Timeout", lambda value: value)

    client = OpenAICompatibleClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model_name="fake-model",
        max_retries=0,
    )

    try:
        client.chat(system_prompt="system", user_prompt="user")
    except RuntimeError as exc:
        assert "bad request detail" in str(exc)
    else:
        raise AssertionError("expected provider HTTP error to be raised")


def test_response_format_error_body_triggers_retry_without_response_format(monkeypatch):
    class RetryHttpxClient:
        def __init__(self):
            self.posts = []

        def post(self, *args, **kwargs):
            self.posts.append((args, copy.deepcopy(kwargs)))
            if len(self.posts) == 1:
                return ResponseFormatFailingHttpxResponse()
            return FakeHttpxResponse()

    retry_client = RetryHttpxClient()
    monkeypatch.setattr(llm_client_module.httpx, "Client", lambda *args, **kwargs: retry_client)
    monkeypatch.setattr(llm_client_module.httpx, "Timeout", lambda value: value)

    client = OpenAICompatibleClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model_name="fake-model",
        max_retries=1,
    )

    response = client.chat(
        system_prompt="system",
        user_prompt="user",
        response_format={"type": "json_object"},
    )

    assert response.content == "ok"
    assert "response_format" in retry_client.posts[0][1]["json"]
    assert "response_format" not in retry_client.posts[1][1]["json"]


def test_project_declares_socks_proxy_support_for_httpx():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any("httpx" in dependency and "socks" in dependency for dependency in dependencies)
