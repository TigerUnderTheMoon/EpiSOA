from episoa.graph.evidence_graph import (
    build_stakeholder_event_evidence_graph,
    extract_stakeholder_candidates,
    infer_temporal_stage_candidates,
)


def test_stakeholder_rule_extraction_normalizes_candidates():
    text = "居民投诉补偿争议，住建局回应，开发商说明，记者报道称专家提出建议。"

    stakeholders = extract_stakeholder_candidates(text, ["回迁居民"])

    assert stakeholders == ["居民/公众", "政府部门", "企业/开发商", "媒体", "专家/律师"]


def test_temporal_stage_inference_limits_to_two_priority_ordered():
    text = "项目发布公告后引发关注，居民质疑并投诉，官方回应称将整改。"

    stages = infer_temporal_stage_candidates(text)

    assert stages == ["trigger", "diffusion"]


def test_build_evidence_graph_from_small_sample():
    events = [
        {
            "event_id": "E1",
            "event_name": "旧改补偿争议",
            "event_description": "旧城改造补偿争议",
            "seed_keywords": ["旧改 补偿"],
            "stakeholder_hints": ["回迁居民"],
            "stance_hints": ["质疑"],
        }
    ]
    evidence = [
        {
            "evidence_id": "ev1",
            "event_id": "E1",
            "source": "official",
            "platform": "city.gov.cn",
            "domain": "city.gov.cn",
            "url": "https://city.gov.cn/a",
            "publish_time": "2025-01-01",
            "text": "政府发布征收公告，住建局回应居民投诉并推进安置处理。",
            "quality_score": 0.9,
        },
        {
            "event_id": "E1",
            "source": "forum",
            "platform": "bbs.example.com",
            "domain": "bbs.example.com",
            "url": "https://bbs.example.com/t",
            "publish_time": "2025-01-02",
            "text": "业主论坛热议补偿争议，网友质疑开发商方案。",
            "quality_score": 0.8,
        },
    ]

    graph = build_stakeholder_event_evidence_graph(events, evidence)
    node_records = graph.node_records()
    edge_records = graph.edge_records()
    node_types = {item["node_type"] for item in node_records}
    edge_types = {item["edge_type"] for item in edge_records}

    assert {"event", "evidence", "stakeholder_candidate", "source", "domain", "temporal_stage_candidate"} <= node_types
    assert {
        "has_evidence",
        "mentions_stakeholder",
        "from_source",
        "from_domain",
        "indicates_stage",
        "involves_stakeholder",
    } <= edge_types
    assert graph.summary["num_events"] == 1
    assert graph.summary["num_evidence"] == 2
    assert "stakeholder_distribution" in graph.summary
    assert "source_distribution" in graph.summary
    assert "stage_distribution" in graph.summary
    assert not graph.summary["events_without_stakeholder"]
    assert not graph.summary["events_without_stage"]
