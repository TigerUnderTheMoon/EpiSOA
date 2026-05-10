# Neo4j Import for EpiSOA Evidence Graph

Generated from `data\pubevent_soa_lite\graph`.

## Contents

- `nodes.csv`: 2542 graph nodes
- `edges_from_domain.csv`
- `edges_from_source.csv`
- `edges_has_evidence.csv`
- `edges_indicates_stage.csv`
- `edges_involves_stakeholder.csv`
- `edges_mentions_stakeholder.csv`
- `import.cypher`: Cypher script for Neo4j Browser or `cypher-shell`

## Import Steps

1. Copy every CSV file in this directory into Neo4j's configured `import` directory. Neo4j `LOAD CSV FROM 'file:///nodes.csv'` reads from that database `import` directory, not from this repository folder.
2. Optional helper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\copy_neo4j_import_files.ps1 -ImportDir "C:\path\to\neo4j\import"
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
MATCH p=(e:Event {event_id: 'E001'})-[*1..2]-()
RETURN p
LIMIT 200;
```

## Notes

- The import uses a common `GraphNode` label plus type-specific labels such as `Event`, `Evidence`, `Source`, `Domain`, `StakeholderCandidate`, and `TemporalStageCandidate`.
- Relationship CSV files are split by edge type, so Neo4j can display typed relationships such as `HAS_EVIDENCE`, `FROM_SOURCE`, and `MENTIONS_STAKEHOLDER` without APOC.
- `attributes_json` preserves the original nested JSON attributes for traceability.
- If Neo4j reports `Cannot load from URL 'file:///nodes.csv'`, the CSV files are not in that database's `import` directory yet.
