from episoa.collector.coverage_extractor import classify_source, evaluate_event_coverage, extract_rule_evidence
from episoa.collector.coverage_extractor import STAKEHOLDER_RULES, STANCE_RULES, TEMPORAL_STAGE_RULES


def test_source_classifier_detects_source_types_over_requested_type():
    cases = [
        ("https://city.gov.cn/a", "市政府官网发布通告", "news", "official"),
        ("https://liuyan.people.com.cn/a", "领导留言板 12345 问政回复", "news", "public_interaction"),
        ("https://weibo.com/a", "微博网友讨论", "news", "public_social"),
        ("https://tieba.baidu.com/p/a", "业主论坛贴吧讨论", "news", "forum"),
        ("https://people.com.cn/a", "人民网新闻报道", "official", "news"),
    ]

    for url, title, requested, expected in cases:
        detected = classify_source({"url": url, "title": title, "requested_source_type": requested})
        assert detected["detected_source_type"] == expected
        assert detected["requested_source_type"] == requested


def test_official_classifier_handles_domains_and_interaction_pages():
    official = classify_source({"url": "https://www.sz.gov.cn/xxgk/a.html", "title": "金钻豪园项目批复"})
    assert official["detected_source_type"] == "official"
    assert official["parent_official_domain"] is True

    interaction = classify_source({"url": "https://www.sz.gov.cn/hdjl/ly/a.html", "title": "政民互动 留言 回复"})
    assert interaction["detected_source_type"] == "public_interaction"
    assert interaction["parent_official_domain"] is True

    local_interaction = classify_source({"url": "https://www.szlh.gov.cn/hdjlpt/detail?pid=1", "title": "互动交流 - 罗湖区人民政府门户网站"})
    assert local_interaction["detected_source_type"] == "public_interaction"
    assert local_interaction["parent_official_domain"] is True

    news_repost = classify_source({"url": "https://news.sohu.com/a/1", "title": "转载自然资源局公告"})
    assert news_repost["detected_source_type"] == "news"

    commercial_repost = classify_source({"url": "https://sz.news.fang.com/open/1.html", "title": "项目公示转载"})
    assert commercial_repost["detected_source_type"] == "news"

    unknown_commercial = classify_source(
        {"url": "https://xiaoqushuo.com/shenzhen/JHKSCUAIDF", "title": "金钻豪园小区", "snippet": "政务公开 信息公开"}
    )
    assert unknown_commercial["detected_source_type"] == "public_web"

    commercial_department_page = classify_source({"url": "https://www.ccoo.cn/ypinfo-363629.html", "title": "翠竹街道办事处"})
    assert commercial_department_page["detected_source_type"] == "public_web"


def test_stakeholder_extraction_covers_chinese_categories():
    text = "区政府和住建局回应，居民业主投诉，开发商施工单位说明，商户企业受影响，媒体记者采访，专家律师提出建议。"
    rows = extract_rule_evidence([raw(text)], STAKEHOLDER_RULES, "stakeholder_type")

    assert {"government", "resident", "developer", "enterprise", "media", "expert"} <= {
        row["stakeholder_type"] for row in rows
    }
    assert all(row["raw_id"] == "r1" and row["matched_text"] for row in rows)


def test_stance_extraction_covers_chinese_categories():
    text = "部分居民支持改善，也有人反对并质疑程序，随后投诉求助，部门回应通报处理，媒体发布报道。"
    rows = extract_rule_evidence([raw(text)], STANCE_RULES, "stance_type")

    assert {"support", "oppose", "question", "complaint", "response", "neutral_report"} <= {
        row["stance_type"] for row in rows
    }


def test_stance_extraction_covers_residual_chinese_phrases():
    rows = extract_rule_evidence(
        [
            raw("居民反映公共空间被占用，业主维权并要求整改。", raw_id="r1"),
            raw("相关部门表示已受理，经核实该问题已办结。", raw_id="r2"),
            raw("居民点赞改造效果，表示满意，认为改善环境。", raw_id="r3"),
            raw("媒体发布项目新闻通稿。", raw_id="r4"),
        ],
        STANCE_RULES,
        "stance_type",
    )
    by_raw = {}
    for row in rows:
        by_raw.setdefault(row["raw_id"], set()).add(row["stance_type"])

    assert {"complaint"} <= by_raw["r1"]
    assert {"response"} <= by_raw["r2"]
    assert {"support"} <= by_raw["r3"]
    assert by_raw["r4"] == {"neutral_report"}


def test_temporal_stage_extraction_covers_chinese_categories():
    text = "项目规划方案公示后开工实施，居民投诉引发争议，街道回应处理并整改完成，后续追踪效果评估。"
    rows = extract_rule_evidence([raw(text)], TEMPORAL_STAGE_RULES, "stage_type")

    assert {"planning", "announcement", "implementation", "conflict", "response", "resolution", "follow_up"} <= {
        row["stage_type"] for row in rows
    }


def test_temporal_stage_extraction_covers_residual_chinese_phrases():
    rows = extract_rule_evidence(
        [
            raw("项目批前公示并列入改造计划。", raw_id="r1"),
            raw("现场正在施工，由街道组织实施。", raw_id="r2"),
            raw("调整引发投诉，居民担忧施工影响。", raw_id="r3"),
            raw("部门回应称正在核实。", raw_id="r4"),
            raw("完成整改后已办结。", raw_id="r5"),
            raw("后续跟进并建立长效机制。", raw_id="r6"),
        ],
        TEMPORAL_STAGE_RULES,
        "stage_type",
    )
    by_raw = {}
    for row in rows:
        by_raw.setdefault(row["raw_id"], set()).add(row["stage_type"])

    assert {"planning", "announcement"} <= by_raw["r1"]
    assert {"implementation"} <= by_raw["r2"]
    assert {"conflict"} <= by_raw["r3"]
    assert {"response"} <= by_raw["r4"]
    assert {"resolution"} <= by_raw["r5"]
    assert {"follow_up"} <= by_raw["r6"]


def test_rule_based_coverage_uses_detected_source_and_semantic_evidence():
    event = {
        "event_id": "E001",
        "source_scope": ["official", "news", "forum", "public_social", "public_interaction"],
        "temporal_stages": ["trigger", "conflict", "response", "resolution", "follow_up"],
    }
    posts = [
        raw("市政府公告发布规划方案，住建局回应居民投诉并说明整改完成。", "https://city.gov.cn/a", "news", "r1"),
        raw("人民网新闻报道，业主质疑程序是否透明，专家支持后续追踪。", "https://people.com.cn/a", "official", "r2"),
        raw("业主论坛讨论施工实施和补偿争议。", "https://tieba.baidu.com/p/a", "news", "r3"),
        raw("微博网友反对并要求解决。", "https://weibo.com/a", "news", "r4"),
        raw("领导留言板显示12345投诉咨询已处理。", "https://liuyan.people.com.cn/a", "news", "r5"),
    ]

    coverage = evaluate_event_coverage(event, posts)

    assert coverage["source_coverage"]["official"] is True
    assert coverage["source_coverage"]["news"] is True
    assert coverage["source_coverage"]["public_interaction"] is True
    assert coverage["source_coverage"]["forum"] is True
    assert coverage["source_coverage"]["public_social"] is True
    assert "government" in coverage["covered_stakeholders"]
    assert "resident" in coverage["covered_stakeholders"]
    assert "response" in coverage["covered_stances"]
    assert "complaint" in coverage["covered_stances"]
    assert "planning" in coverage["covered_temporal_stages"]
    assert "conflict" in coverage["covered_temporal_stages"]
    assert coverage["missing_stakeholders"] == []
    assert coverage["missing_stances"] == []
    assert coverage["missing_temporal_stages"] == []
    assert coverage["source_detection"][0]["detected_source_type"] == "official"


def test_rule_based_coverage_still_flags_semantic_gaps():
    event = {"event_id": "E001", "source_scope": ["news"]}
    posts = [raw("新闻报道项目进展。", "https://people.com.cn/a", "news", "r1")]

    coverage = evaluate_event_coverage(event, posts)

    assert coverage["missing_stakeholders"]
    assert coverage["missing_stances"]
    assert coverage["missing_temporal_stages"]
    assert coverage["need_query_repair"] is True


def raw(text, url="https://example.test/a", requested="news", raw_id="r1"):
    return {
        "raw_id": raw_id,
        "event_id": "E001",
        "requested_source_type": requested,
        "source_type": requested,
        "source": requested,
        "url": url,
        "title": text,
        "snippet": text,
        "text": text,
    }
