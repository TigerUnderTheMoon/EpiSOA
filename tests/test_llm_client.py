import httpx
import tomllib
from pathlib import Path

from episoa.llm import client as llm_client_module
from episoa.llm.client import OpenAICompatibleClient


class FakeHttpxResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"id": "fake-response", "choices": [{"message": {"content": "ok"}}]}


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


def test_project_declares_socks_proxy_support_for_httpx():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any("httpx" in dependency and "socks" in dependency for dependency in dependencies)
