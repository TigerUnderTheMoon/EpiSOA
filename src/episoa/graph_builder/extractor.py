"""Mock stakeholder-centered evidence graph extraction."""

from __future__ import annotations

from dataclasses import dataclass

from episoa.graph_builder.graph_store import EvidenceGraph
from episoa.schemas.evidence import EvidenceRecord


def _metadata_text(evidence: EvidenceRecord, key: str, default: str) -> str:
    value = evidence.metadata.get(key, default)
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _node_id(prefix: str, value: str) -> str:
    normalized = " ".join(value.lower().split())
    return f"{prefix}:{normalized}"


@dataclass
class MockEvidenceGraphExtractor:
    """Rule-based placeholder for a future LLM evidence graph extractor."""

    default_event: str = "target_event"

    def extract(self, evidence_records: list[EvidenceRecord]) -> EvidenceGraph:
        """Build an EvidenceGraph from normalized evidence records."""
        evidence_graph = EvidenceGraph()

        previous_event_node: str | None = None
        for record in sorted(evidence_records, key=lambda item: item.timestamp):
            event = _metadata_text(record, "event", self.default_event)
            stakeholder = _metadata_text(record, "stakeholder", record.author_alias or "unknown_stakeholder")
            opinion = _metadata_text(record, "opinion", record.text)
            sentiment = _metadata_text(record, "sentiment", _metadata_text(record, "stance", "unknown"))
            rationale = _metadata_text(record, "rationale", f"Rationale derived from {record.evidence_id}")
            trigger_event = _metadata_text(record, "trigger_event", "")
            responds_to_event = _metadata_text(record, "responds_to", "")
            amplifies_event = _metadata_text(record, "amplifies", "")

            event_node = _node_id("event", event)
            stakeholder_node = _node_id("stakeholder", stakeholder)
            opinion_node = f"opinion:{record.evidence_id}"
            sentiment_node = _node_id("sentiment", sentiment)
            rationale_node = f"rationale:{record.evidence_id}"
            evidence_node = f"evidence:{record.evidence_id}"
            time_node = f"time:{record.timestamp.isoformat()}"

            evidence_graph.add_node(event_node, "Event", label=event)
            evidence_graph.add_node(stakeholder_node, "Stakeholder", label=stakeholder)
            evidence_graph.add_node(opinion_node, "Opinion", label=opinion, evidence_id=record.evidence_id)
            evidence_graph.add_node(sentiment_node, "Sentiment", label=sentiment)
            evidence_graph.add_node(rationale_node, "Rationale", label=rationale, evidence_id=record.evidence_id)
            evidence_graph.add_node(
                evidence_node,
                "Evidence",
                evidence_id=record.evidence_id,
                platform=record.platform,
                url=str(record.url),
                text=record.text,
                author_alias=record.author_alias,
                source_type=record.source_type,
                metadata=record.metadata,
            )
            evidence_graph.add_node(time_node, "Time", label=record.timestamp.isoformat())

            evidence_graph.add_edge(stakeholder_node, opinion_node, "expresses", evidence_id=record.evidence_id)
            evidence_graph.add_edge(opinion_node, sentiment_node, "has_sentiment", evidence_id=record.evidence_id)
            evidence_graph.add_edge(opinion_node, rationale_node, "caused_by", evidence_id=record.evidence_id)
            evidence_graph.add_edge(opinion_node, evidence_node, "evidenced_by", evidence_id=record.evidence_id)
            evidence_graph.add_edge(evidence_node, time_node, "appears_at", evidence_id=record.evidence_id)
            evidence_graph.add_edge(event_node, evidence_node, "evidenced_by", evidence_id=record.evidence_id)

            if previous_event_node and previous_event_node != event_node:
                evidence_graph.add_edge(previous_event_node, event_node, "precedes", evidence_id=record.evidence_id)

            if trigger_event:
                trigger_node = _node_id("event", trigger_event)
                evidence_graph.add_node(trigger_node, "Event", label=trigger_event)
                evidence_graph.add_edge(trigger_node, event_node, "triggers", evidence_id=record.evidence_id)

            if responds_to_event:
                response_node = _node_id("event", responds_to_event)
                evidence_graph.add_node(response_node, "Event", label=responds_to_event)
                evidence_graph.add_edge(event_node, response_node, "responds_to", evidence_id=record.evidence_id)

            if amplifies_event:
                amplified_node = _node_id("event", amplifies_event)
                evidence_graph.add_node(amplified_node, "Event", label=amplifies_event)
                evidence_graph.add_edge(event_node, amplified_node, "amplifies", evidence_id=record.evidence_id)

            previous_event_node = event_node

        return evidence_graph


def build_evidence_graph(evidence_records: list[EvidenceRecord]) -> EvidenceGraph:
    """Build a stakeholder-centered evidence graph with the default mock extractor."""
    return MockEvidenceGraphExtractor().extract(evidence_records)
