# Mock and Placeholder Implementation Inventory

This document records current mock, placeholder, rule-based, or fake implementations in EpiSOA. These items are useful for pipeline smoke tests, but they should be replaced before using results as empirical evidence.

## `src/episoa/collector/fsm_graph.py`

### `event_understanding(state)`
- Input: `CollectorState` with `target_event`.
- Output: partial `CollectorState` with `event_summary` and `visited_states`.
- Current implementation: returns `Mock understanding for {target_event}`.
- Replace with: event understanding agent that extracts event type, actors, temporal bounds, entities, seed keywords, and ambiguity notes from the target event description.
- Affects experiments: Yes. It controls the semantic framing of the whole collection pipeline.

### `query_planning(state)`
- Input: `CollectorState` with `target_event` and optional existing `query_plan`.
- Output: partial `CollectorState` with query strings.
- Current implementation: creates simple string templates such as timeline, public opinion, and stakeholder reactions.
- Replace with: query planner using LLM or structured retrieval planning, including multilingual variants, platform-specific query syntax, entity aliases, time-window constraints, and iterative repair.
- Affects experiments: Yes. It directly affects recall and stakeholder coverage.

### `source_selection(state)`
- Input: `CollectorState`.
- Output: partial `CollectorState` with `selected_sources`.
- Current implementation: always returns `["news", "social_media", "official"]`.
- Replace with: source selector that chooses platforms and source classes based on event domain, geography, time window, availability, credibility, and collection budget.
- Affects experiments: Yes. It biases source diversity and evidence provenance.

### `search_and_page_collection(state)`
- Input: `CollectorState` with selected sources and query plan.
- Output: partial `CollectorState` with page metadata.
- Current implementation: returns two fixed example URLs.
- Replace with: real search/page collector using search APIs, RSS, platform APIs, crawlers, or browser automation, with deduplication and provenance capture.
- Affects experiments: Yes. Current output is synthetic and cannot support real-world conclusions.

### `browser_based_opinion_collection(state)`
- Input: `CollectorState` with collected pages.
- Output: partial `CollectorState` with opinion snippets.
- Current implementation: returns two fixed stakeholder opinions.
- Replace with: browser or API-based opinion extraction over collected pages/posts, with comment/thread expansion, quote extraction, author metadata, and timestamps.
- Affects experiments: Yes. It determines stakeholder/opinion coverage.

### `evidence_normalization(state)`
- Input: `CollectorState` with pages and opinions.
- Output: partial `CollectorState` with normalized evidence dicts.
- Current implementation: returns one fixed evidence item.
- Replace with: normalization into `EvidenceRecord`, including URL canonicalization, timestamp parsing, source typing, text cleaning, metadata enrichment, and duplicate detection.
- Affects experiments: Yes. It affects traceability, downstream graph construction, and verification.

### `_mock_coverage_status(scenario)`
- Input: coverage scenario string: `covered`, `stakeholder_missing`, or `not_enough_opinions`.
- Output: `CoverageStatus` dict with coverage metrics.
- Current implementation: returns fixed metric values and labels.
- Replace with: metric computation from collected evidence, including stakeholder coverage, stance entropy/diversity, temporal span coverage, traceability rate, and redundancy rate.
- Affects experiments: Yes. It controls whether collection loops continue or stop.

### `coverage_evaluation(state)`
- Input: `CollectorState` with evidence/opinions and optional `mock_coverage_scenario`.
- Output: partial `CollectorState` with `coverage_status` and `coverage_attempts`.
- Current implementation: uses `_mock_coverage_status`; after one remediation loop it forces a passing status.
- Replace with: real coverage evaluator with stopping criteria and loop budget.
- Affects experiments: Yes. It can falsely mark incomplete evidence as sufficient.

### `stop_and_handoff(state)`
- Input: final `CollectorState`.
- Output: partial `CollectorState` with `handoff_payload`.
- Current implementation: packages mock evidence and coverage status.
- Replace with: stable handoff object containing validated `EvidenceRecord` instances, collection diagnostics, failure reasons, and reproducibility metadata.
- Affects experiments: Partly. It is mostly plumbing, but current payload may omit necessary provenance.

## `src/episoa/retrieval/diversity_retriever.py`

### `relevance_score(query, evidence, selected=None, evidence_pool=None)`
- Input: query string and an `EvidenceRecord`.
- Output: float relevance score.
- Current implementation: mock embedding similarity using token overlap.
- Replace with: dense embedding similarity, hybrid BM25+dense retrieval, or learned reranker score.
- Affects experiments: Yes. It determines retrieval quality and candidate evidence ranking.

### `stakeholder_coverage_score(query, evidence, selected, evidence_pool=None)`
- Input: query, candidate evidence, already selected evidence.
- Output: float diversity reward.
- Current implementation: reads `metadata["stakeholder"]` and rewards unseen stakeholder labels.
- Replace with: stakeholder entity linker and coverage objective using canonical stakeholder IDs, stakeholder classes, and salience weights.
- Affects experiments: Yes. It can overcount aliases or miss implicit stakeholders.

### `stance_diversity_score(query, evidence, selected, evidence_pool=None)`
- Input: query, candidate evidence, already selected evidence.
- Output: float stance diversity reward.
- Current implementation: reads `metadata["stance"]`; falls back to unknown.
- Replace with: stance classifier or LLM/NLI stance extraction with calibrated labels.
- Affects experiments: Yes. Stance diversity is currently only as reliable as metadata.

### `temporal_coverage_score(query, evidence, selected, evidence_pool)`
- Input: query, candidate evidence, selected evidence, full pool.
- Output: float temporal coverage reward.
- Current implementation: rewards spread over min/max timestamps.
- Replace with: event-aware temporal coverage over event phases, bursts, and time-window constraints.
- Affects experiments: Moderate. It can improve spread but does not know event semantics.

### `redundancy_penalty(query, evidence, selected, evidence_pool=None)`
- Input: query, candidate evidence, selected evidence.
- Output: float redundancy penalty.
- Current implementation: token-overlap similarity against selected evidence.
- Replace with: near-duplicate detection using embeddings, URL canonicalization, quote matching, semantic similarity, and source clustering.
- Affects experiments: Yes. Duplicate evidence can inflate support if not handled robustly.

## `src/episoa/graph_builder/extractor.py`

### `MockEvidenceGraphExtractor.extract(evidence_records)`
- Input: list of `EvidenceRecord`.
- Output: `EvidenceGraph`.
- Current implementation: rule-based metadata reader that creates Event, Stakeholder, Opinion, Sentiment, Rationale, Evidence, and Time nodes from existing metadata and simple defaults.
- Replace with: LLM or IE extractor that identifies events, stakeholders, opinions, sentiments, rationales, causal/temporal relations, and evidence grounding from raw text.
- Affects experiments: Yes. The current graph mostly mirrors metadata and cannot discover latent relations from text.

### `build_evidence_graph(evidence_records)`
- Input: list of `EvidenceRecord`.
- Output: `EvidenceGraph`.
- Current implementation: thin wrapper around `MockEvidenceGraphExtractor`.
- Replace with: production graph builder that can choose between LLM extraction, rule extraction, and persisted graph backends.
- Affects experiments: Yes, because it currently uses the mock extractor by default.

## `src/episoa/eventrag/query_to_event.py`

### `parse_query_to_event(query)`
- Input: natural-language query string.
- Output: `QueryEvent` with `query`, `target_event`, and keyword set.
- Current implementation: strips the query and treats the full query as the target event; keywords are whitespace tokens.
- Replace with: event parser that extracts event trigger, entities, time constraints, location, event type, and disambiguation candidates.
- Affects experiments: Yes. Anchor selection depends on this parse.

## `src/episoa/eventrag/anchor_selection.py`

### `select_anchor_events(query_event, evidence_graph, top_k=3)`
- Input: `QueryEvent`, `EvidenceGraph`, and top-k.
- Output: list of event node IDs.
- Current implementation: ranks Event nodes by token overlap with the query.
- Replace with: event-node retrieval using embeddings, lexical search, entity linking, temporal filtering, and graph priors.
- Affects experiments: Yes. Poor anchors cause irrelevant or missing event chains.

## `src/episoa/eventrag/path_reranking.py`

### `score_path(query, evidence_graph, path, ...)`
- Input: query, `EvidenceGraph`, `EvidenceBackedPath`, and lambda weights.
- Output: `ScoredEventPath`.
- Current implementation: formula is present, but each feature is rule-based: token overlap relevance, count-based evidence support, count-based stakeholder coverage, timestamp sortedness, allowed-edge causal plausibility, and exact-text redundancy.
- Replace with: calibrated path reranker using semantic relevance, evidence entailment, stakeholder canonicalization, temporal reasoning, causal plausibility model, and redundancy clustering.
- Affects experiments: Yes. Current scores are heuristic and should not be interpreted as calibrated confidence.

### `_path_relevance(query, evidence_graph, path)`
- Input: query, graph, evidence-backed path.
- Output: float relevance.
- Current implementation: token overlap between query and event labels.
- Replace with: dense/hybrid path relevance model.
- Affects experiments: Yes.

### `_temporal_coherence(path)`
- Input: evidence-backed path.
- Output: float temporal coherence.
- Current implementation: checks whether evidence timestamps are sorted.
- Replace with: event-time reasoning that handles publication time vs event time, ranges, uncertainty, and relation-specific temporal constraints.
- Affects experiments: Yes.

### `_causal_plausibility(path)`
- Input: evidence-backed path.
- Output: float causal plausibility.
- Current implementation: all allowed expansion edge types are treated as plausible.
- Replace with: causal relation verifier or NLI model that checks whether the edge relation is supported by evidence.
- Affects experiments: Yes.

### `_redundancy(path)`
- Input: evidence-backed path.
- Output: float redundancy.
- Current implementation: exact lowercased text uniqueness.
- Replace with: semantic redundancy and provenance-aware clustering.
- Affects experiments: Moderate to high.

## `src/episoa/reasoner/attribution_reasoner.py`

### `AttributionLLMClient.generate_structured_attribution(prompt, schema)`
- Input: prompt string and schema object.
- Output: structured attribution data.
- Current implementation: protocol only; no concrete production client.
- Replace with: real schema-constrained LLM call, such as OpenAI structured outputs or another validated generation backend.
- Affects experiments: No by itself, because it is an interface. It affects results once wired to a concrete client.

### `RuleBasedAttributionLLMClient.generate_structured_attribution(prompt, schema)`
- Input: prompt string and schema object.
- Output: none; raises `NotImplementedError`.
- Current implementation: placeholder interface class.
- Replace with: remove or implement as a deterministic test double; production should use a real LLM client.
- Affects experiments: No unless instantiated directly.

### `AttributionReasoner._mock_attribution(event_chain, evidence_records, target_event_description)`
- Input: `EventChain`, list of `EvidenceRecord`, and target event description.
- Output: list of raw dicts validated into `AttributionTuple`.
- Current implementation: groups evidence by stakeholder metadata and copies first opinion/sentiment; marks verified based on evidence count.
- Replace with: schema-constrained attribution reasoner that infers event, stakeholder, opinion, sentiment, rationale, event chain support, and evidence citations from the evidence package.
- Affects experiments: Yes. This is the core attribution result generator.

### `_opinion_for(evidence_records)`, `_sentiment_for(evidence_records)`, `_rationale_for(evidence_records, verified)`, `_support_score(...)`
- Input: stakeholder-specific evidence records and support settings.
- Output: opinion text, sentiment label, rationale text, or support score.
- Current implementation: metadata-first heuristics and evidence count.
- Replace with: opinion extraction, sentiment/stance classification, rationale generation with citations, and calibrated support estimation.
- Affects experiments: Yes.

## `src/episoa/verifier/evidence_support.py`

### `evidence_support_score(attribution, evidence_records)`
- Input: `AttributionTuple` and list of `EvidenceRecord`.
- Output: float support score.
- Current implementation: token overlap between attribution fields and evidence text/metadata.
- Replace with: NLI or entailment model checking whether cited evidence supports the attribution claim.
- Affects experiments: Yes. It determines support and feeds `verified`.

### `verify_attribution(attribution, evidence_records=None)`
- Input: `AttributionTuple` and optional evidence pool.
- Output: updated `AttributionTuple` with `support_score` and `verified`.
- Current implementation: weighted average of four rule-based checks; `verified=True` when score >= 0.75.
- Replace with: calibrated verifier combining NLI support, stakeholder/entity consistency, stance consistency, event-chain relation verification, and source reliability.
- Affects experiments: Yes. It controls final acceptance/rejection.

## `src/episoa/verifier/stakeholder_consistency.py`

### `stakeholder_consistency_score(attribution, evidence_records)`
- Input: `AttributionTuple` and evidence records.
- Output: float consistency score.
- Current implementation: exact stakeholder metadata/author match or substring in evidence text.
- Replace with: entity linking, alias resolution, coreference resolution, and stakeholder taxonomy matching.
- Affects experiments: Yes.

## `src/episoa/verifier/sentiment_consistency.py`

### `sentiment_consistency_score(attribution, evidence_records)`
- Input: `AttributionTuple` and evidence records.
- Output: float consistency score.
- Current implementation: metadata lookup or small keyword lists for positive/negative inference.
- Replace with: sentiment/stance classifier grounded in the attributed stakeholder opinion.
- Affects experiments: Yes.

### `_infer_sentiment(evidence)`
- Input: one `EvidenceRecord`.
- Output: sentiment label string.
- Current implementation: metadata lookup or keyword matching.
- Replace with: calibrated sentiment/stance model.
- Affects experiments: Yes.

## `src/episoa/verifier/event_chain_consistency.py`

### `event_chain_consistency_score(attribution, evidence_records)`
- Input: `AttributionTuple` and evidence records.
- Output: float event-chain consistency score.
- Current implementation: checks token overlap between event-chain labels and evidence text/metadata.
- Replace with: event mention linker and relation verifier that checks whether each event and relation is actually supported.
- Affects experiments: Yes.

## `src/episoa/main.py`

### `_evidence_from_collector_state(event_description, collector_state)`
- Input: event description and collector FSM state.
- Output: list of `EvidenceRecord`.
- Current implementation: converts mock collector dicts into `EvidenceRecord`; if no evidence exists, emits a synthetic `collector-mock-1` record.
- Replace with: strict conversion from real collector output only; no synthetic evidence fallback for experimental runs.
- Affects experiments: Yes if used outside demo/testing. It can introduce synthetic evidence into outputs.

### `_fallback_event_chain(event_description, evidence)`
- Input: event description and candidate evidence.
- Output: `EventChain`.
- Current implementation: creates an event chain from evidence metadata if EventRAG returns no paths.
- Replace with: explicit failure/handoff state, or a separately flagged low-confidence fallback that is excluded from core metrics.
- Affects experiments: Yes. It can mask EventRAG failures and produce attribution results without graph paths.

## Empty Placeholder Files

The following files currently exist as empty scaffolding and have no implementation:

- `src/episoa/collector/event_understanding.py`
- `src/episoa/collector/query_planning.py`
- `src/episoa/collector/source_selection.py`
- `src/episoa/collector/page_collection.py`
- `src/episoa/collector/opinion_collection.py`
- `src/episoa/collector/normalization.py`
- `src/episoa/collector/coverage_evaluation.py`
- `src/episoa/retrieval/vector_index.py`
- `src/episoa/retrieval/reranker.py`
- `src/episoa/graph_builder/neo4j_store.py`
- `src/episoa/storage/evidence_db.py`
- `src/episoa/storage/models.py`
- `src/episoa/evaluation/tuple_metrics.py`
- `src/episoa/evaluation/retrieval_metrics.py`
- `src/episoa/evaluation/path_metrics.py`

These do not affect current smoke tests because the implemented pipeline imports the working modules directly. They will affect experiments once the project expects persistent storage, Neo4j export, vector indexing, reranking, or metric reporting.
