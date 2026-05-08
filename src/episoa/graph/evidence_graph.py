"""Stakeholder-Event Evidence Graph construction."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from episoa.data.loader import write_jsonl


STAGE_ORDER = ["trigger", "diffusion", "conflict", "response", "resolution", "follow_up"]
STAKEHOLDER_RULES = [
    ("居民/公众", ["居民", "村民", "群众", "业主", "住户", "网友", "市民"]),
    ("政府部门", ["政府", "官方", "部门", "街道办", "住建局", "自然资源局", "教育局", "城管", "管委会", "镇政府", "区政府", "市政府"]),
    ("企业/开发商", ["企业", "开发商", "物业", "建设单位", "项目方", "施工方"]),
    ("媒体", ["媒体", "记者", "报道称"]),
    ("专家/律师", ["专家", "学者", "律师"]),
]
STAGE_RULES = {
    "trigger": ["发生", "启动", "开始", "发布", "启动改造", "征收", "拆迁", "公告", "通知", "规划", "立项"],
    "diffusion": ["传播", "关注", "热议", "引发关注", "网传", "舆论", "媒体报道", "网友讨论"],
    "conflict": ["争议", "质疑", "反对", "不满", "投诉", "举报", "维权", "冲突", "阻挠", "纠纷", "矛盾"],
    "response": ["回应", "通报", "说明", "答复", "澄清", "回应称", "部门表示", "官方回应"],
    "resolution": ["整改", "解决", "处理", "协调", "补偿", "安置", "达成一致", "完成", "落实", "推进"],
    "follow_up": ["后续", "进展", "持续", "再次", "复查", "回访", "跟进", "最新"],
}


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    label: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        attributes = dict(self.attributes)
        if self.label and "label" not in attributes:
            attributes["label"] = self.label
        return {"node_id": self.node_id, "node_type": self.node_type, "attributes": attributes}


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    evidence_id: str | None = None
    weight: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def source_node_id(self) -> str:
        return self.source

    @property
    def target_node_id(self) -> str:
        return self.target

    @property
    def edge_type(self) -> str:
        return self.relation

    def to_record(self) -> dict[str, Any]:
        attributes = dict(self.attributes)
        if self.evidence_id and "evidence_id" not in attributes:
            attributes["evidence_id"] = self.evidence_id
        return {
            "source_node_id": self.source,
            "target_node_id": self.target,
            "edge_type": self.relation,
            "weight": self.weight,
            "attributes": attributes,
        }


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    summary: dict[str, Any] = field(default_factory=dict)

    def node_records(self) -> list[dict[str, Any]]:
        return [node.to_record() for node in self.nodes]

    def edge_records(self) -> list[dict[str, Any]]:
        return [edge.to_record() for edge in self.edges]


def build_stakeholder_event_evidence_graph(events: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> EvidenceGraph:
    nodes: dict[str, GraphNode] = {}
    edges: dict[tuple[str, str, str], GraphEdge] = {}
    event_by_id = {str(event.get("event_id")): event for event in events if event.get("event_id")}
    evidence_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stakeholder_by_event: dict[str, set[str]] = defaultdict(set)
    stage_by_event: dict[str, set[str]] = defaultdict(set)
    stakeholder_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    stage_counter: Counter[str] = Counter()

    for event in events:
        event_id = str(event.get("event_id", ""))
        nodes[f"event:{event_id}"] = GraphNode(
            node_id=f"event:{event_id}",
            node_type="event",
            label=str(event.get("event_name") or event_id),
            attributes={
                "event_id": event_id,
                "event_name": event.get("event_name"),
                "event_description": event.get("event_description"),
                "seed_keywords": event.get("seed_keywords") or [],
                "stakeholder_hints": event.get("stakeholder_hints") or [],
                "stance_hints": event.get("stance_hints") or [],
            },
        )

    for index, item in enumerate(evidence, start=1):
        event_id = str(item.get("event_id", ""))
        evidence_id = str(item.get("evidence_id") or f"{event_id}_EV{index:04d}")
        text = str(item.get("text") or "")
        source = str(item.get("source") or "unknown")
        domain = str(item.get("domain") or domain_from_url(str(item.get("url") or ""), str(item.get("platform") or "")))
        event = event_by_id.get(event_id, {})
        stakeholders = extract_stakeholder_candidates(text, as_list(event.get("stakeholder_hints")))
        stages = infer_temporal_stage_candidates(text, source)
        evidence_node_id = f"evidence:{evidence_id}"

        evidence_by_event[event_id].append(item)
        nodes[evidence_node_id] = GraphNode(
            node_id=evidence_node_id,
            node_type="evidence",
            label=evidence_id,
            attributes={
                "evidence_id": evidence_id,
                "event_id": event_id,
                "source": source,
                "platform": item.get("platform"),
                "domain": domain,
                "url": item.get("url"),
                "publish_time": item.get("publish_time"),
                "text": text,
                "quality_score": item.get("quality_score"),
            },
        )
        add_edge(edges, f"event:{event_id}", evidence_node_id, "has_evidence", evidence_id=evidence_id)

        source_node_id = f"source:{source}"
        nodes.setdefault(source_node_id, GraphNode(source_node_id, "source", source, {"source": source}))
        add_edge(edges, evidence_node_id, source_node_id, "from_source", evidence_id=evidence_id)
        source_counter[source] += 1

        domain_node_id = f"domain:{domain}"
        nodes.setdefault(domain_node_id, GraphNode(domain_node_id, "domain", domain, {"domain": domain}))
        add_edge(edges, evidence_node_id, domain_node_id, "from_domain", evidence_id=evidence_id)

        for stakeholder in stakeholders:
            stakeholder_node_id = f"stakeholder:{normalize_node_token(stakeholder)}"
            nodes.setdefault(
                stakeholder_node_id,
                GraphNode(stakeholder_node_id, "stakeholder_candidate", stakeholder, {"stakeholder": stakeholder}),
            )
            add_edge(edges, evidence_node_id, stakeholder_node_id, "mentions_stakeholder", evidence_id=evidence_id)
            stakeholder_by_event[event_id].add(stakeholder)
            stakeholder_counter[stakeholder] += 1

        for stage in stages:
            stage_node_id = f"stage:{stage}"
            nodes.setdefault(stage_node_id, GraphNode(stage_node_id, "temporal_stage_candidate", stage, {"stage": stage}))
            add_edge(edges, evidence_node_id, stage_node_id, "indicates_stage", evidence_id=evidence_id)
            stage_by_event[event_id].add(stage)
            stage_counter[stage] += 1

    for event_id, stakeholders in stakeholder_by_event.items():
        for stakeholder in stakeholders:
            add_edge(edges, f"event:{event_id}", f"stakeholder:{normalize_node_token(stakeholder)}", "involves_stakeholder")

    node_types = Counter(node.node_type for node in nodes.values())
    summary = {
        "num_events": len(events),
        "num_evidence": len(evidence),
        "num_stakeholder_candidates": node_types.get("stakeholder_candidate", 0),
        "num_sources": node_types.get("source", 0),
        "num_domains": node_types.get("domain", 0),
        "num_stage_candidates": node_types.get("temporal_stage_candidate", 0),
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "stakeholder_distribution": dict(stakeholder_counter),
        "source_distribution": dict(source_counter),
        "stage_distribution": dict(stage_counter),
        "events_without_stakeholder": sorted(
            event_id for event_id in event_by_id if not stakeholder_by_event.get(event_id)
        ),
        "events_without_stage": sorted(event_id for event_id in event_by_id if not stage_by_event.get(event_id)),
    }
    return EvidenceGraph(nodes=list(nodes.values()), edges=list(edges.values()), summary=summary)


def extract_stakeholder_candidates(text: str, stakeholder_hints: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    for normalized, keywords in STAKEHOLDER_RULES:
        if any(keyword in text for keyword in keywords):
            candidates.append(normalized)
    for hint in stakeholder_hints or []:
        hint = str(hint).strip()
        if hint and hint in text:
            candidates.append(hint)
    return unique(candidates)


def infer_temporal_stage_candidates(text: str, source: str = "") -> list[str]:
    del source
    matches = [stage for stage in STAGE_ORDER if any(keyword in text for keyword in STAGE_RULES[stage])]
    return matches[:2]


def write_evidence_graph(graph: EvidenceGraph, output_dir: str | Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = output_dir / "evidence_graph_nodes.jsonl"
    edges_path = output_dir / "evidence_graph_edges.jsonl"
    summary_path = output_dir / "evidence_graph_summary.json"
    write_jsonl(nodes_path, graph.node_records())
    write_jsonl(edges_path, graph.edge_records())
    summary_path.write_text(json.dumps(graph.summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"nodes": nodes_path, "edges": edges_path, "summary": summary_path}


def add_edge(
    edges: dict[tuple[str, str, str], GraphEdge],
    source: str,
    target: str,
    relation: str,
    *,
    evidence_id: str | None = None,
    weight: float = 1.0,
    attributes: dict[str, Any] | None = None,
) -> None:
    key = (source, target, relation)
    edges.setdefault(key, GraphEdge(source, target, relation, evidence_id=evidence_id, weight=weight, attributes=attributes or {}))


def domain_from_url(url: str, platform: str = "") -> str:
    match = re.match(r"https?://([^/]+)", url)
    host = match.group(1) if match else platform
    host = host.lower().strip()
    return host[4:] if host.startswith("www.") else host or "unknown"


def normalize_node_token(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip())


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    return [str(value)]


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output
