from episoa.attribution.tuple_parser import parse_attribution_tuple
from episoa.cfsm_collector.state_machine import build_collector_graph
from episoa.clients.search_client import SearchClient


def test_spec_facades_are_importable() -> None:
    graph = build_collector_graph()
    search = SearchClient({"query": [{"url": "https://example.test/item"}]})

    assert graph is not None
    assert search.search("query")[0]["url"] == "https://example.test/item"
    assert parse_attribution_tuple is not None
