import httpx

from episoa.collector.search_client import SearchClient, SearchConfig, load_search_config, normalize_search_response


def test_normalize_search_response_accepts_common_field_aliases():
    payload = {
        "results": [
            {
                "headline": "Public hearing announced",
                "link": "https://news.example/item",
                "description": "Residents discuss the proposal.",
                "body": "Full article text",
                "published_at": "2025-01-01",
                "site": "Local News",
            }
        ]
    }

    result = normalize_search_response(payload)[0]

    assert result["title"] == "Public hearing announced"
    assert result["url"] == "https://news.example/item"
    assert result["snippet"] == "Residents discuss the proposal."
    assert result["text"] == "Full article text"
    assert result["publish_time"] == "2025-01-01"
    assert result["platform"] == "Local News"


def test_placeholder_search_config_is_not_configured():
    config = load_search_config(
        {
            "provider": "custom",
            "api_key": "your-search-api-key",
            "base_url": "https://your-search-api-base-url/v1",
        }
    )

    assert config.configured is False


def test_search_client_caps_results_even_if_api_returns_more(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, headers, timeout):
            del json, headers, timeout
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "results": [
                        {"title": "one", "url": "https://example.test/1", "text": "one"},
                        {"title": "two", "url": "https://example.test/2", "text": "two"},
                    ]
                },
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = SearchClient(
        SearchConfig(
            provider="custom",
            api_key="key",
            api_key_source="yaml",
            base_url="https://search.example/v1",
            base_url_source="yaml",
            timeout_seconds=30,
            max_retries=0,
        )
    )

    assert len(client.search(query="q", max_results=1)) == 1


def test_search_client_returns_empty_debug_on_timeout(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, headers, timeout):
            del url, json, headers, timeout
            raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = SearchClient(
        SearchConfig(
            provider="custom",
            api_key="key",
            api_key_source="yaml",
            base_url="https://search.example/v1",
            base_url_source="yaml",
            timeout_seconds=1,
            max_retries=0,
        )
    )

    result = client.search_with_debug(query="q", max_results=1)

    assert result["results"] == []
    assert result["ok"] is False
    assert result["timeout"] is True
