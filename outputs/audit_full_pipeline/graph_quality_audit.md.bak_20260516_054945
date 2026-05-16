# Graph Quality Audit

- Actual graph builder: `src/episoa/graph/evidence_graph.py::build_stakeholder_event_evidence_graph`.
- Node type distribution: {'event': 50, 'evidence': 1767, 'source': 6, 'domain': 598, 'stakeholder_candidate': 263, 'temporal_stage_candidate': 6}
- Stakeholder candidate nodes: True
- Temporal stage candidate nodes: True
- Opinion/relation nodes: False

## Diagnosis
- The current graph is a lightweight event-evidence-source-domain graph plus rule-derived stakeholder/stage candidate nodes.
- It does not extract opinion nodes or stakeholder-opinion relations, and graph content is passed only as candidate hints to schema attribution.
- `without_graph` mainly removes the stakeholder_candidates prompt block; it does not remove a structured reasoning module.
- The graph is therefore too weak to support strong causal claims from the graph ablation.

## Recommended Graph Experiment
| Setting | Builder | Inputs | Outputs | Purpose |
|---|---|---|---|---|
| no_graph | disabled | events/evidence | empty graph artifacts | baseline |
| graph_rule_based | current evidence_graph.py | events/evidence | stakeholder/stage candidate graph | current approach |
| graph_llm_extracted | proposed model_graph_builder.py | events/evidence + extraction model | stakeholder/opinion/stage/relation graph | test stronger structure |

A future `model_graph_builder.py` should extract stakeholder, opinion, stage, relation, confidence, and evidence span fields, then feed them as structured constraints instead of loose hints.
