"""Export EpiSOA evidence graph JSONL files to Neo4j LOAD CSV artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any

from episoa.data.loader import read_jsonl


DEFAULT_GRAPH_DIR = Path("data/pubevent_soa_lite/graph")
DEFAULT_OUTPUT_DIR = DEFAULT_GRAPH_DIR / "neo4j_import"

NODE_LABELS = {
    "event": "Event",
    "evidence": "Evidence",
    "source": "Source",
    "domain": "Domain",
    "stakeholder_candidate": "StakeholderCandidate",
    "temporal_stage_candidate": "TemporalStageCandidate",
}

NODE_FIELDS = [
    "node_id",
    "node_type",
    "neo4j_label",
    "label",
    "event_id",
    "event_name",
    "evidence_id",
    "source",
    "domain",
    "url",
    "publish_time",
    "quality_score",
    "text",
    "attributes_json",
]

EDGE_FIELDS = [
    "source_node_id",
    "target_node_id",
    "edge_type",
    "weight",
    "evidence_id",
    "attributes_json",
]

RELATIONSHIP_TYPES = {
    "has_evidence": "HAS_EVIDENCE",
    "from_source": "FROM_SOURCE",
    "from_domain": "FROM_DOMAIN",
    "mentions_stakeholder": "MENTIONS_STAKEHOLDER",
    "indicates_stage": "INDICATES_STAGE",
    "involves_stakeholder": "INVOLVES_STAKEHOLDER",
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    graph_dir = Path(args.graph_dir)
    output_dir = Path(args.output_dir)
    nodes = read_jsonl(graph_dir / "evidence_graph_nodes.jsonl")
    edges = read_jsonl(graph_dir / "evidence_graph_edges.jsonl")

    output_dir.mkdir(parents=True, exist_ok=True)
    node_rows = [normalize_node(row) for row in nodes]
    edge_rows = [normalize_edge(row) for row in edges]

    write_csv(output_dir / "nodes.csv", NODE_FIELDS, node_rows)
    edge_files = write_edge_files(output_dir, edge_rows)
    importer_dir = output_dir / "data_importer"
    importer_node_files = write_data_importer_node_files(importer_dir, node_rows)
    importer_edge_files = write_data_importer_edge_files(importer_dir, edge_rows)
    write_data_importer_readme(
        importer_dir / "README.md",
        importer_node_files,
        importer_edge_files,
        len(node_rows),
        len(edge_rows),
    )
    write_cypher(output_dir / "import.cypher", edge_files)
    write_readme(output_dir / "README.md", graph_dir, edge_files, len(node_rows), len(edge_rows))

    print(f"nodes: {len(node_rows)} -> {output_dir / 'nodes.csv'}")
    print(f"edges: {len(edge_rows)} -> {len(edge_files)} relationship CSV files")
    print(f"data importer files: {importer_dir}")
    print(f"cypher: {output_dir / 'import.cypher'}")
    print(f"instructions: {output_dir / 'README.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export evidence graph JSONL to Neo4j CSV/Cypher import files.")
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def normalize_node(row: dict[str, Any]) -> dict[str, Any]:
    attrs = dict(row.get("attributes") or {})
    node_type = str(row.get("node_type") or "")
    return {
        "node_id": row.get("node_id", ""),
        "node_type": node_type,
        "neo4j_label": NODE_LABELS.get(node_type, "GraphNode"),
        "label": attrs.get("label") or row.get("label") or attrs.get("event_name") or attrs.get("evidence_id") or "",
        "event_id": attrs.get("event_id", ""),
        "event_name": attrs.get("event_name", ""),
        "evidence_id": attrs.get("evidence_id", ""),
        "source": attrs.get("source", ""),
        "domain": attrs.get("domain", ""),
        "url": attrs.get("url", ""),
        "publish_time": attrs.get("publish_time", ""),
        "quality_score": attrs.get("quality_score", ""),
        "text": attrs.get("text", ""),
        "attributes_json": json.dumps(attrs, ensure_ascii=False, sort_keys=True),
    }


def normalize_edge(row: dict[str, Any]) -> dict[str, Any]:
    attrs = dict(row.get("attributes") or {})
    edge_type = str(row.get("edge_type") or "")
    return {
        "source_node_id": row.get("source_node_id", ""),
        "target_node_id": row.get("target_node_id", ""),
        "edge_type": edge_type,
        "weight": row.get("weight", 1.0),
        "evidence_id": attrs.get("evidence_id", ""),
        "attributes_json": json.dumps(attrs, ensure_ascii=False, sort_keys=True),
    }


def write_edge_files(output_dir: Path, edge_rows: list[dict[str, Any]]) -> dict[str, Path]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in edge_rows:
        edge_type = str(row["edge_type"] or "related")
        grouped.setdefault(edge_type, []).append(row)

    edge_files: dict[str, Path] = {}
    for edge_type, rows in sorted(grouped.items()):
        file_name = f"edges_{safe_file_name(edge_type)}.csv"
        path = output_dir / file_name
        write_csv(path, EDGE_FIELDS, rows)
        edge_files[edge_type] = path
    return edge_files


def write_data_importer_node_files(output_dir: Path, node_rows: list[dict[str, Any]]) -> dict[str, Path]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in node_rows:
        label = str(row.get("neo4j_label") or "GraphNode")
        grouped.setdefault(label, []).append(row)

    node_files: dict[str, Path] = {}
    for label, rows in sorted(grouped.items()):
        path = output_dir / f"nodes_{safe_file_name(label)}.csv"
        write_csv(path, NODE_FIELDS, rows)
        node_files[label] = path
    return node_files


def write_data_importer_edge_files(output_dir: Path, edge_rows: list[dict[str, Any]]) -> dict[str, Path]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in edge_rows:
        edge_type = str(row["edge_type"] or "related")
        grouped.setdefault(edge_type, []).append(row)

    edge_files: dict[str, Path] = {}
    for edge_type, rows in sorted(grouped.items()):
        relationship_type = RELATIONSHIP_TYPES.get(edge_type, safe_relationship_type(edge_type))
        path = output_dir / f"relationships_{safe_file_name(relationship_type)}.csv"
        write_csv(path, EDGE_FIELDS, rows)
        edge_files[relationship_type] = path
    return edge_files


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: csv_value(value) for key, value in row.items()} for row in rows)


def csv_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return value


def write_cypher(path: Path, edge_files: dict[str, Path]) -> None:
    lines = [
        "// Neo4j import script generated by scripts/export_neo4j_graph.py",
        "// Copy the generated CSV files into Neo4j's import directory, then run this file in Neo4j Browser or cypher-shell.",
        "",
        "CREATE CONSTRAINT graph_node_id IF NOT EXISTS FOR (n:GraphNode) REQUIRE n.node_id IS UNIQUE;",
        "",
        "LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row",
        "MERGE (n:GraphNode {node_id: row.node_id})",
        "SET n.node_type = row.node_type,",
        "    n.label = row.label,",
        "    n.event_id = row.event_id,",
        "    n.event_name = row.event_name,",
        "    n.evidence_id = row.evidence_id,",
        "    n.source = row.source,",
        "    n.domain = row.domain,",
        "    n.url = row.url,",
        "    n.publish_time = row.publish_time,",
        "    n.quality_score = CASE row.quality_score WHEN '' THEN null ELSE toFloat(row.quality_score) END,",
        "    n.text = row.text,",
        "    n.attributes_json = row.attributes_json",
        "FOREACH (_ IN CASE WHEN row.neo4j_label = 'Event' THEN [1] ELSE [] END | SET n:Event)",
        "FOREACH (_ IN CASE WHEN row.neo4j_label = 'Evidence' THEN [1] ELSE [] END | SET n:Evidence)",
        "FOREACH (_ IN CASE WHEN row.neo4j_label = 'Source' THEN [1] ELSE [] END | SET n:Source)",
        "FOREACH (_ IN CASE WHEN row.neo4j_label = 'Domain' THEN [1] ELSE [] END | SET n:Domain)",
        "FOREACH (_ IN CASE WHEN row.neo4j_label = 'StakeholderCandidate' THEN [1] ELSE [] END | SET n:StakeholderCandidate)",
        "FOREACH (_ IN CASE WHEN row.neo4j_label = 'TemporalStageCandidate' THEN [1] ELSE [] END | SET n:TemporalStageCandidate);",
        "",
    ]

    for edge_type, csv_path in sorted(edge_files.items()):
        relationship_type = RELATIONSHIP_TYPES.get(edge_type, safe_relationship_type(edge_type))
        lines.extend(
            [
                f"LOAD CSV WITH HEADERS FROM 'file:///{csv_path.name}' AS row",
                "MATCH (source:GraphNode {node_id: row.source_node_id})",
                "MATCH (target:GraphNode {node_id: row.target_node_id})",
                f"MERGE (source)-[r:{relationship_type} {{edge_type: row.edge_type, evidence_id: coalesce(row.evidence_id, '')}}]->(target)",
                "SET r.weight = CASE row.weight WHEN '' THEN 1.0 ELSE toFloat(row.weight) END,",
                "    r.attributes_json = row.attributes_json;",
                "",
            ]
        )

    lines.extend(
        [
            "// Useful visualization queries:",
            "MATCH p=(e:Event)-[:HAS_EVIDENCE]->(:Evidence)-[]->() RETURN p LIMIT 100;",
            "MATCH p=(e:Event {event_id: 'E001'})-[*1..2]-() RETURN p LIMIT 200;",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(path: Path, graph_dir: Path, edge_files: dict[str, Path], node_count: int, edge_count: int) -> None:
    edge_names = "\n".join(f"- `{item.name}`" for item in edge_files.values())
    path.write_text(
        f"""# Neo4j Import for EpiSOA Evidence Graph

Generated from `{graph_dir}`.

## Contents

- `nodes.csv`: {node_count} graph nodes
{edge_names}
- `import.cypher`: Cypher script for Neo4j Browser or `cypher-shell`

## Import Steps

1. Copy every CSV file in this directory into Neo4j's configured `import` directory. Neo4j `LOAD CSV FROM 'file:///nodes.csv'` reads from that database `import` directory, not from this repository folder.
2. Optional helper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\\copy_neo4j_import_files.ps1 -ImportDir "C:\\path\\to\\neo4j\\import"
```

3. Open Neo4j Browser or `cypher-shell`.
4. If a previous import failed halfway, clear the partial graph before retrying:

```cypher
MATCH (n:GraphNode)
DETACH DELETE n;
```

5. Run the statements in `import.cypher`.
6. Visualize with:

```cypher
MATCH p=(e:Event)-[:HAS_EVIDENCE]->(:Evidence)-[]->()
RETURN p
LIMIT 100;
```

For one event:

```cypher
MATCH p=(e:Event {{event_id: 'E001'}})-[*1..2]-()
RETURN p
LIMIT 200;
```

## Notes

- The import uses a common `GraphNode` label plus type-specific labels such as `Event`, `Evidence`, `Source`, `Domain`, `StakeholderCandidate`, and `TemporalStageCandidate`.
- Relationship CSV files are split by edge type, so Neo4j can display typed relationships such as `HAS_EVIDENCE`, `FROM_SOURCE`, and `MENTIONS_STAKEHOLDER` without APOC.
- `attributes_json` preserves the original nested JSON attributes for traceability.
- If Neo4j reports `Cannot load from URL 'file:///nodes.csv'`, the CSV files are not in that database's `import` directory yet.
""",
        encoding="utf-8",
    )


def write_data_importer_readme(
    path: Path,
    node_files: dict[str, Path],
    edge_files: dict[str, Path],
    node_count: int,
    edge_count: int,
) -> None:
    node_names = "\n".join(f"- `{item.name}` -> node label `{label}`" for label, item in node_files.items())
    edge_names = "\n".join(f"- `{item.name}` -> relationship type `{relationship_type}`" for relationship_type, item in edge_files.items())
    path.write_text(
        f"""# Neo4j Desktop Data Importer Files

Use this folder when importing through the Neo4j Desktop visual Import tool.

## Contents

- Node rows: {node_count}
- Relationship rows: {edge_count}

Node files:
{node_names}

Relationship files:
{edge_names}

## Required Setup

1. In Neo4j Desktop, create or start a local DBMS/database first.
2. Make sure the top bar no longer says `No instance connected`.
3. In the Import tool, click `Browse` and select all CSV files in this folder.

## Data Model Mapping

Create nodes first:

1. Drag each `nodes_*.csv` file to the canvas.
2. Set the node label to the label shown above, for example `Event`, `Evidence`, `Domain`, `Source`, `StakeholderCandidate`, or `TemporalStageCandidate`.
3. Set `node_id` as the unique ID/key property for every node type.
4. Keep useful properties such as `label`, `event_id`, `event_name`, `evidence_id`, `source`, `domain`, `url`, `quality_score`, and `text`.

Create relationships after all node files are mapped:

1. Drag each `relationships_*.csv` file to the canvas.
2. Set the relationship type to the type shown above, for example `HAS_EVIDENCE`.
3. Map `source_node_id` to the source node's `node_id`.
4. Map `target_node_id` to the target node's `node_id`.
5. Keep `weight`, `evidence_id`, and `attributes_json` as relationship properties.

Relationship endpoint pairs:

- `HAS_EVIDENCE`: `Event` -> `Evidence`
- `FROM_SOURCE`: `Evidence` -> `Source`
- `FROM_DOMAIN`: `Evidence` -> `Domain`
- `MENTIONS_STAKEHOLDER`: `Evidence` -> `StakeholderCandidate`
- `INDICATES_STAGE`: `Evidence` -> `TemporalStageCandidate`
- `INVOLVES_STAKEHOLDER`: `Event` -> `StakeholderCandidate`

## After Import

Run this in Neo4j Query:

```cypher
MATCH p=(e:Event)-[:HAS_EVIDENCE]->(:Evidence)-[]->()
RETURN p
LIMIT 100;
```

For one event:

```cypher
MATCH p=(e:Event {{event_id: 'E001'}})-[*1..2]-()
RETURN p
LIMIT 200;
```
""",
        encoding="utf-8",
    )


def safe_file_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().lower()) or "related"


def safe_relationship_type(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip().upper())
    if not cleaned:
        return "RELATED"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


if __name__ == "__main__":
    raise SystemExit(main())
