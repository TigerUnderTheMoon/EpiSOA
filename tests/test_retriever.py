from pathlib import Path

from episoa.experimental_pipeline import build_graph, collect_evidence, normalize_evidence, retrieve_paths


def test_retrieve_paths_requires_graph_inputs(tmp_path: Path) -> None:
    missing_nodes = tmp_path / "missing_nodes.jsonl"
    missing_edges = tmp_path / "missing_edges.jsonl"

    try:
        retrieve_paths(missing_nodes, missing_edges, tmp_path / "paths.jsonl")
    except FileNotFoundError as exc:
        assert "required input file not found" in str(exc)
    else:
        raise AssertionError("retrieve_paths should fail when graph inputs are missing")


def test_retrieve_paths_outputs_event_paths(tmp_path: Path) -> None:
    event_queries = tmp_path / "event_queries.jsonl"
    event_queries.write_text(
        '{"event_id":"evt-1","target_event":"Transit hearing","seed_evidence":['
        '{"evidence_id":"ev-1","platform":"News","url":"https://smoke.test/a",'
        '"timestamp":"2026-01-01T00:00:00Z","text":"Riders opposed the fare increase.",'
        '"author_alias":"Riders","source_type":"news","metadata":{"stakeholder":"Riders"}}]}\n',
        encoding="utf-8",
    )
    pool = tmp_path / "pool.jsonl"
    normalized = tmp_path / "normalized.jsonl"
    nodes = tmp_path / "nodes.jsonl"
    edges = tmp_path / "edges.jsonl"
    paths = tmp_path / "paths.jsonl"

    collect_evidence(event_queries, pool)
    normalize_evidence(pool, normalized)
    build_graph(normalized, nodes, edges)
    count = retrieve_paths(nodes, edges, paths)

    assert count == 1
    assert '"path_id":"path-00001"' in paths.read_text(encoding="utf-8")
