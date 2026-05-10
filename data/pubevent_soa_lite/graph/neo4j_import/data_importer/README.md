# Neo4j Desktop Data Importer Files

Use this folder when importing through the Neo4j Desktop visual Import tool.

## Contents

- Node rows: 2542
- Relationship rows: 14076

Node files:
- `nodes_domain.csv` -> node label `Domain`
- `nodes_event.csv` -> node label `Event`
- `nodes_evidence.csv` -> node label `Evidence`
- `nodes_source.csv` -> node label `Source`
- `nodes_stakeholdercandidate.csv` -> node label `StakeholderCandidate`
- `nodes_temporalstagecandidate.csv` -> node label `TemporalStageCandidate`

Relationship files:
- `relationships_from_domain.csv` -> relationship type `FROM_DOMAIN`
- `relationships_from_source.csv` -> relationship type `FROM_SOURCE`
- `relationships_has_evidence.csv` -> relationship type `HAS_EVIDENCE`
- `relationships_indicates_stage.csv` -> relationship type `INDICATES_STAGE`
- `relationships_involves_stakeholder.csv` -> relationship type `INVOLVES_STAKEHOLDER`
- `relationships_mentions_stakeholder.csv` -> relationship type `MENTIONS_STAKEHOLDER`

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
MATCH p=(e:Event {event_id: 'E001'})-[*1..2]-()
RETURN p
LIMIT 200;
```
