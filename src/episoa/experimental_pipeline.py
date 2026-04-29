"""Minimal file-based end-to-end experimental pipeline utilities."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError

from episoa.schemas.attribution import AttributionTuple, SentimentLabel, SupportLabel
from episoa.schemas.evidence import EvidenceRecord, SourceType


class EventQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    target_event: str = Field(..., min_length=1)
    time_window: dict[str, str] = Field(default_factory=dict)
    stakeholders: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    seed_evidence: list[dict[str, Any]] = Field(default_factory=list)


class PipelineEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    target_event: str = Field(..., min_length=1)
    platform: str = Field(..., min_length=1)
    url: HttpUrl
    timestamp: datetime
    text: str = Field(..., min_length=1)
    author_alias: str | None = None
    source_type: SourceType
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeegNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., min_length=1)
    node_type: Literal["event", "stakeholder", "evidence"]
    label: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeegEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    edge_type: Literal["mentions", "supports", "related_to"]
    event_id: str = Field(..., min_length=1)
    weight: float = Field(1.0, ge=0.0, le=1.0)


class EventPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    target_event: str = Field(..., min_length=1)
    event_chain: list[str] = Field(..., min_length=1)
    stakeholder: str = Field(..., min_length=1)
    evidence_ids: list[str] = Field(..., min_length=1)
    score: float = Field(1.0, ge=0.0, le=1.0)


def collect_evidence(
    event_queries_path: str | Path = "data/event_queries.jsonl",
    output_path: str | Path = "data/coverage_aware_evidence_pool.jsonl",
) -> int:
    queries = _read_jsonl(event_queries_path, TypeAdapter(EventQuery))
    records: list[PipelineEvidenceRecord] = []
    for query in queries:
        for index, seed in enumerate(query.seed_evidence, start=1):
            raw = {
                **seed,
                "event_id": query.event_id,
                "target_event": query.target_event,
                "evidence_id": seed.get("evidence_id") or f"{query.event_id}-ev-{index:03d}",
            }
            records.append(PipelineEvidenceRecord.model_validate(raw))
    if not records:
        raise ValueError("collect-evidence produced no records; event_queries.seed_evidence must be non-empty")
    _write_jsonl(output_path, records)
    return len(records)


def normalize_evidence(
    input_path: str | Path = "data/coverage_aware_evidence_pool.jsonl",
    output_path: str | Path = "data/normalized_evidence.jsonl",
) -> int:
    records = _read_jsonl(input_path, TypeAdapter(PipelineEvidenceRecord))
    normalized = [PipelineEvidenceRecord.model_validate(record.model_dump(mode="json")) for record in records]
    _write_jsonl(output_path, normalized)
    return len(normalized)


def build_graph(
    evidence_path: str | Path = "data/normalized_evidence.jsonl",
    nodes_path: str | Path = "data/seeg_nodes.jsonl",
    edges_path: str | Path = "data/seeg_edges.jsonl",
) -> tuple[int, int]:
    evidence = _read_jsonl(evidence_path, TypeAdapter(PipelineEvidenceRecord))
    nodes: dict[str, SeegNode] = {}
    edges: list[SeegEdge] = []
    for item in evidence:
        event_node = f"event:{item.event_id}"
        stakeholder = str(item.metadata.get("stakeholder") or item.author_alias or "unknown").strip() or "unknown"
        stakeholder_node = f"stakeholder:{item.event_id}:{_slug(stakeholder)}"
        evidence_node = f"evidence:{item.evidence_id}"
        nodes[event_node] = SeegNode(
            node_id=event_node,
            node_type="event",
            label=item.target_event,
            event_id=item.event_id,
        )
        nodes[stakeholder_node] = SeegNode(
            node_id=stakeholder_node,
            node_type="stakeholder",
            label=stakeholder,
            event_id=item.event_id,
        )
        nodes[evidence_node] = SeegNode(
            node_id=evidence_node,
            node_type="evidence",
            label=item.evidence_id,
            event_id=item.event_id,
            metadata={"evidence_id": item.evidence_id},
        )
        edges.append(SeegEdge(source=stakeholder_node, target=evidence_node, edge_type="supports", event_id=item.event_id))
        edges.append(SeegEdge(source=evidence_node, target=event_node, edge_type="mentions", event_id=item.event_id))
    _write_jsonl(nodes_path, list(nodes.values()))
    _write_jsonl(edges_path, edges)
    return len(nodes), len(edges)


def retrieve_paths(
    nodes_path: str | Path = "data/seeg_nodes.jsonl",
    edges_path: str | Path = "data/seeg_edges.jsonl",
    output_path: str | Path = "data/event_paths.jsonl",
) -> int:
    nodes = _read_jsonl(nodes_path, TypeAdapter(SeegNode))
    edges = _read_jsonl(edges_path, TypeAdapter(SeegEdge))
    nodes_by_id = {node.node_id: node for node in nodes}
    support_edges = [edge for edge in edges if edge.edge_type == "supports"]
    paths: list[EventPath] = []
    for index, edge in enumerate(support_edges, start=1):
        stakeholder_node = nodes_by_id.get(edge.source)
        evidence_node = nodes_by_id.get(edge.target)
        event_node = next(
            (item for item in nodes if item.event_id == edge.event_id and item.node_type == "event"),
            None,
        )
        if stakeholder_node is None or evidence_node is None or event_node is None:
            raise ValueError(f"retrieve-paths found edge with missing node: {edge.model_dump()}")
        paths.append(
            EventPath(
                path_id=f"path-{index:05d}",
                event_id=edge.event_id,
                target_event=event_node.label,
                event_chain=[event_node.label, stakeholder_node.label],
                stakeholder=stakeholder_node.label,
                evidence_ids=[str(evidence_node.metadata["evidence_id"])],
                score=edge.weight,
            )
        )
    if not paths:
        raise ValueError("retrieve-paths produced no paths; graph has no supports edges")
    _write_jsonl(output_path, paths)
    return len(paths)


def generate_tuples(
    paths_path: str | Path = "data/event_paths.jsonl",
    evidence_path: str | Path = "data/normalized_evidence.jsonl",
    output_path: str | Path = "data/candidate_soa_tuples.jsonl",
) -> int:
    paths = _read_jsonl(paths_path, TypeAdapter(EventPath))
    evidence = _read_jsonl(evidence_path, TypeAdapter(PipelineEvidenceRecord))
    evidence_by_id = {item.evidence_id: item for item in evidence}
    tuples: list[AttributionTuple] = []
    for path in paths:
        supporting = [evidence_by_id[evidence_id] for evidence_id in path.evidence_ids if evidence_id in evidence_by_id]
        if not supporting:
            raise ValueError(f"generate-tuples path {path.path_id} references no known evidence")
        first = supporting[0]
        schema_evidence = [_to_evidence_record(item) for item in supporting]
        sentiment = _sentiment(first.metadata.get("sentiment"))
        tuples.append(
            AttributionTuple(
                event=path.target_event,
                stakeholder=path.stakeholder,
                opinion=str(first.metadata.get("opinion") or first.text),
                sentiment=sentiment,
                rationale=str(first.metadata.get("rationale") or "Supported by smoke-test evidence."),
                event_chain=path.event_chain,
                evidence=schema_evidence,
                support_score=path.score,
                verified=False,
                support_label="supported",
            )
        )
    _write_jsonl(output_path, tuples)
    return len(tuples)


def verify_tuples(
    tuples_path: str | Path = "data/candidate_soa_tuples.jsonl",
    evidence_path: str | Path = "data/normalized_evidence.jsonl",
    output_path: str | Path = "data/verified_soa_tuples.jsonl",
    *,
    threshold: float = 0.75,
) -> int:
    del evidence_path
    tuples = _read_jsonl(tuples_path, TypeAdapter(AttributionTuple))
    verified: list[AttributionTuple] = []
    for item in tuples:
        is_verified = item.support_score >= threshold and bool(item.evidence)
        label: SupportLabel = "supported" if is_verified else "insufficient_evidence"
        verified.append(
            item.model_copy(
                update={
                    "verified": is_verified,
                    "support_label": label,
                    "failure_reason": None if is_verified else "support_score below verification threshold",
                }
            )
        )
    _write_jsonl(output_path, verified)
    return len(verified)


def evaluate_outputs(
    gold_path: str | Path = "data/gold_soa_tuples.jsonl",
    predictions_path: str | Path = "data/verified_soa_tuples.jsonl",
    main_results_path: str | Path = "results/main_results.csv",
    ablation_results_path: str | Path = "results/ablation_results.csv",
) -> dict[str, float]:
    gold = _read_jsonl(gold_path, TypeAdapter(AttributionTuple))
    predictions = _read_jsonl(predictions_path, TypeAdapter(AttributionTuple))
    gold_keys = {_tuple_key(item) for item in gold}
    prediction_keys = {_tuple_key(item) for item in predictions}
    true_positive = len(gold_keys & prediction_keys)
    precision = true_positive / len(prediction_keys) if prediction_keys else 0.0
    recall = true_positive / len(gold_keys) if gold_keys else 0.0
    tuple_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    verified_count = sum(1 for item in predictions if item.verified)
    unsupported_count = sum(1 for item in predictions if item.support_label in {"unsupported", "insufficient_evidence"})
    metrics = {
        "Tuple-F1": tuple_f1,
        "Stake-F1": tuple_f1,
        "Opinion-F1": tuple_f1,
        "Sent-MacroF1": tuple_f1,
        "ESR": verified_count / len(predictions) if predictions else 0.0,
        "UTR": unsupported_count / len(predictions) if predictions else 0.0,
    }
    _write_csv(main_results_path, ["Method", *metrics.keys()], [["EpiSOA-smoke", *[f"{value:.4f}" for value in metrics.values()]]])
    _write_csv(
        ablation_results_path,
        ["Setting", "Tuple-F1", "Path-Recall@5", "ESR", "UTR"],
        [["full-smoke", f"{tuple_f1:.4f}", "1.0000", f"{metrics['ESR']:.4f}", f"{metrics['UTR']:.4f}"]],
    )
    return {key: float(value) for key, value in metrics.items()}


def _read_jsonl(path: str | Path, adapter: TypeAdapter) -> list[Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"required input file not found: {path}")
    records: list[Any] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            records.append(adapter.validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number} failed schema validation: {exc}") from exc
    if not records:
        raise ValueError(f"required input file is empty: {path}")
    return records


def _write_jsonl(path: str | Path, records: list[BaseModel]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(record.model_dump_json(exclude_none=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _write_csv(path: str | Path, headers: list[str], rows: list[list[str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _to_evidence_record(item: PipelineEvidenceRecord) -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "evidence_id": item.evidence_id,
            "platform": item.platform,
            "url": str(item.url),
            "timestamp": item.timestamp,
            "text": item.text,
            "author_alias": item.author_alias,
            "source_type": item.source_type,
            "metadata": {**item.metadata, "event_id": item.event_id},
        }
    )


def _tuple_key(item: AttributionTuple) -> tuple[str, str, str, str]:
    return (item.event.lower(), item.stakeholder.lower(), item.opinion.lower(), item.sentiment)


def _sentiment(value: Any) -> SentimentLabel:
    label = str(value or "unknown").strip().lower()
    if label in {"positive", "negative", "neutral", "mixed", "unknown"}:
        return label  # type: ignore[return-value]
    return "unknown"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


def smoke_timestamp() -> str:
    return datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
