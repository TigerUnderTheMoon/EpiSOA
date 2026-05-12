"""Rule-based coverage extraction for collected public-event evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


SOURCE_ALIASES = {"social_media": "public_social"}
DEFAULT_SOURCE_TYPES = ["news", "official", "public_interaction", "forum", "public_social", "public_web"]
INTERACTION_SOURCE_TYPES = ("public_interaction", "forum", "public_social")
DEFAULT_SOURCE_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "source_detection.yaml"


@dataclass(frozen=True)
class Rule:
    label: str
    terms: tuple[str, ...]
    rule_id: str
    strength: str = "strong"
    confidence: float = 0.9


SOURCE_RULES: tuple[Rule, ...] = (
    Rule("public_interaction", ("领导留言板", "12345", "政民互动", "问政", "投诉咨询", "信访", "留言", "百姓呼声", "liuyan.people.com.cn", "people.rednet.cn", "people.lyd.com.cn"), "source_public_interaction"),
    Rule("public_social", ("weibo.com", "m.weibo.cn", "微博", "微信公众号", "抖音", "douyin", "快手", "小红书", "xiaohongshu", "bilibili", "b站", "视频号", "toutiao.com", "m.toutiao.com", "今日头条", "163.com/dy", "网易订阅"), "source_public_social"),
    Rule("forum", ("论坛", "社区", "贴吧", "tieba", "豆瓣小组", "知乎", "天涯", "猫扑", "业主论坛", "bbs"), "source_forum"),
    Rule("official", ("gov.cn", "政府官网", "住建局", "自然资源局", "发改委", "城管局", "街道办", "区政府", "市政府", "政务服务", "人民政府"), "source_official"),
    Rule("news", ("人民网", "新华网", "央视", "澎湃", "财新", "新京报", "日报", "晚报", "电视台", "报社", "新闻", "腾讯", "搜狐", "网易", "新浪", "东方财富", "房天下", "中华网", "荔枝网", "招标网", "thepaper.cn", "xinhuanet.com", "people.com.cn", "new.qq.com", "qq.com", "sohu.com", "eastmoney.com", "focus.cn", "fang.com", "bidcenter.com.cn", "gdtv.cn", "sina.com.cn", "china.com", "rednet.cn"), "source_news"),
)

STAKEHOLDER_RULES: tuple[Rule, ...] = (
    Rule("government", ("市政府", "区政府", "县政府", "街道办", "居委会", "住建局", "自然资源局", "规划局", "城管局", "发改委", "房管局", "监管部门", "政府", "官方", "政务"), "stakeholder_government"),
    Rule("government", ("相关部门", "主管部门", "职能部门"), "stakeholder_government_weak", "weak", 0.55),
    Rule("resident", ("居民", "业主", "市民", "群众", "村民", "租户", "住户", "老人", "周边居民", "小区居民"), "stakeholder_resident"),
    Rule("developer", ("开发商", "建设单位", "施工单位", "承建方", "投资方", "房地产公司", "项目公司", "物业公司"), "stakeholder_developer"),
    Rule("enterprise", ("企业", "商户", "店主", "经营户", "市场主体", "公司", "个体工商户"), "stakeholder_enterprise"),
    Rule("media", ("媒体", "记者", "新闻报道", "报道称", "报道", "采访", "电视台", "报社"), "stakeholder_media"),
    Rule("expert", ("专家", "学者", "研究员", "教授", "规划师", "律师", "分析人士", "业内人士"), "stakeholder_expert"),
)

STANCE_RULES: tuple[Rule, ...] = (
    Rule("support", ("支持", "赞成", "认可", "欢迎", "有利于", "改善", "提升", "方便", "期待", "满意", "居民点赞", "获得认可", "表示满意", "方便居民", "改善环境", "提升品质", "有助于", "得到支持"), "stance_support"),
    Rule("oppose", ("反对", "不同意", "抵制", "拒绝", "阻止", "强烈不满", "不接受", "要求停止", "引发不满", "认为不合理"), "stance_oppose"),
    Rule("question", ("质疑", "担忧", "不合理", "是否合规", "程序是否透明", "公开不足", "信息不明", "争议", "引发质疑", "引发争议", "担心影响", "要求公开", "要求解释"), "stance_question"),
    Rule("complaint", ("投诉", "反映", "举报", "留言", "上访", "维权", "求助", "要求解决", "居民反映", "业主反映", "群众反映", "市民反映", "被投诉", "要求处理", "要求整改", "多次反映", "反映无果", "业主维权"), "stance_complaint"),
    Rule("response", ("回应", "回复", "通报", "说明", "澄清", "辟谣", "整改", "已处理", "正在核实", "进一步调查", "负责人介绍", "有关负责人介绍", "表示", "相关部门表示", "工作人员表示", "官方回应称", "已回复", "已受理", "已办结", "正在协调", "正在处理", "将督促", "将整改", "已责令", "已约谈", "已核查", "经核实", "情况属实", "情况不属实"), "stance_response"),
    Rule("neutral_report", ("报道", "发布", "公示", "通知", "公告", "介绍", "披露"), "stance_neutral_report", "weak", 0.55),
)

TEMPORAL_STAGE_RULES: tuple[Rule, ...] = (
    Rule("planning", ("规划", "计划", "方案", "征求意见", "前期研究", "立项", "可研", "拟实施", "拟改造", "征集意见", "征求意见稿", "初步方案", "专项规划", "纳入计划", "列入改造计划"), "stage_planning"),
    Rule("announcement", ("公示", "公告", "通知", "发布", "招标", "批复", "审批", "信息公开", "项目公示", "批前公示", "批后公告", "招标计划"), "stage_announcement"),
    Rule("implementation", ("开工", "施工", "实施", "改造中", "拆迁", "建设", "推进", "进场", "完工", "已进场", "正在施工", "正在推进", "完成施工", "施工期间", "改造现场", "开展整治", "组织实施"), "stage_implementation"),
    Rule("conflict", ("争议", "质疑", "投诉", "反对", "不满", "矛盾", "冲突", "舆情", "维权", "协商", "引发争议", "引发投诉", "居民担忧", "群众反映", "业主维权", "协商未果", "产生矛盾"), "stage_conflict"),
    Rule("response", ("回应", "回复", "通报", "说明", "约谈", "核实", "调查", "处理", "整改", "部门回应", "街道回应", "平台回复", "已受理", "正在核实", "正在协调", "已派人处理", "将进一步处理"), "stage_response"),
    Rule("resolution", ("解决", "整改完成", "达成一致", "调整方案", "取消", "暂停", "恢复", "通过验收", "完成", "完成整改", "已整改", "整改到位", "问题解决", "暂停施工", "恢复施工", "已办结"), "stage_resolution"),
    Rule("follow_up", ("后续", "追踪", "回访", "长效机制", "持续推进", "后续安排", "效果评估", "后续跟进", "持续跟踪", "建立长效机制", "继续推进", "回访居民"), "stage_follow_up"),
)

LEGACY_STAGE_MAP = {
    "trigger": ["planning", "announcement"],
    "pre_event": ["planning", "announcement"],
    "process": ["implementation"],
    "conflict": ["conflict"],
    "response": ["response"],
    "resolution": ["resolution"],
    "follow_up": ["follow_up"],
}


def classify_source(record: dict[str, Any]) -> dict[str, Any]:
    requested = normalize_source_type(
        record.get("requested_source_type") or record.get("source_type") or record.get("source") or ""
    )
    existing_detected = normalize_source_type(record.get("detected_source_type") or "")
    url = str(record.get("url") or "")
    domain = extract_domain(url)
    title = str(record.get("title") or "")
    if existing_detected:
        return {
            "raw_id": record.get("raw_id"),
            "url": url,
            "domain": domain,
            "title": title,
            "requested_source_type": requested or "unknown",
            "detected_source_type": existing_detected,
            "matched_rule": str(record.get("source_detection_rule") or "source_existing_detected"),
            "matched_text": existing_detected,
            "confidence": 0.9,
            "rule_strength": "strong",
            "parent_official_domain": _is_config_domain(domain, load_source_detection_config()["official_domains"]),
        }
    snippet = str(record.get("snippet") or "")
    text = str(record.get("text") or "")
    haystack = f"{domain} {title} {snippet} {text}".lower()
    config = load_source_detection_config()
    parent_official_domain = _is_config_domain(domain, config["official_domains"])
    for label, domain_key, keyword_key in (
        ("public_interaction", "interaction_domains", "interaction_keywords"),
        ("public_social", "social_domains", "social_keywords"),
        ("forum", "forum_domains", "forum_keywords"),
    ):
        matched = _first_matched_term(haystack, [*config[domain_key], *config[keyword_key]])
        if matched:
            return _source_detection_row(
                record=record,
                requested=requested,
                url=url,
                domain=domain,
                title=title,
                detected_source_type=label,
                matched_rule=f"source_{label}",
                matched_text=matched,
                parent_official_domain=parent_official_domain,
            )
    if parent_official_domain:
        matched = _first_matched_term(haystack, config["official_domains"]) or domain
        return _source_detection_row(
            record=record,
            requested=requested,
            url=url,
            domain=domain,
            title=title,
            detected_source_type="official",
            matched_rule="source_official_domain",
            matched_text=matched,
            parent_official_domain=True,
        )
    matched_news = _first_matched_term(haystack, [*config["news_domains"], *config["news_keywords"]])
    if matched_news:
        return _source_detection_row(
            record=record,
            requested=requested,
            url=url,
            domain=domain,
            title=title,
            detected_source_type="news",
            matched_rule="source_news",
            matched_text=matched_news,
            parent_official_domain=False,
        )
    matched_official = _first_matched_term(f"{domain} {title}".lower(), config["official_title_keywords"])
    if matched_official:
        return _source_detection_row(
            record=record,
            requested=requested,
            url=url,
            domain=domain,
            title=title,
            detected_source_type="official",
            matched_rule="source_official_keyword",
            matched_text=matched_official,
            confidence=0.75,
            parent_official_domain=False,
        )
    return {
        "raw_id": record.get("raw_id"),
        "url": url,
        "domain": domain,
        "title": title,
        "requested_source_type": requested or "unknown",
        "detected_source_type": "public_web",
        "matched_rule": "source_fallback_public_web",
        "matched_text": "",
        "confidence": 0.2,
        "rule_strength": "weak",
        "parent_official_domain": parent_official_domain,
    }


def _source_detection_row(
    *,
    record: dict[str, Any],
    requested: str,
    url: str,
    domain: str,
    title: str,
    detected_source_type: str,
    matched_rule: str,
    matched_text: str,
    confidence: float = 0.9,
    rule_strength: str = "strong",
    parent_official_domain: bool = False,
) -> dict[str, Any]:
    return {
        "raw_id": record.get("raw_id"),
        "url": url,
        "domain": domain,
        "title": title,
        "requested_source_type": requested or "unknown",
        "detected_source_type": detected_source_type,
        "matched_rule": matched_rule,
        "matched_text": matched_text,
        "confidence": confidence,
        "rule_strength": rule_strength,
        "parent_official_domain": parent_official_domain,
    }


def enrich_record_source(record: dict[str, Any]) -> dict[str, Any]:
    debug = classify_source(record)
    output = dict(record)
    output["requested_source_type"] = debug["requested_source_type"]
    output["detected_source_type"] = debug["detected_source_type"]
    output["source_type"] = debug["detected_source_type"]
    output["source"] = debug["detected_source_type"]
    output["source_detection_rule"] = debug["matched_rule"]
    return output


def evaluate_event_coverage(
    event: dict[str, Any],
    posts: list[dict[str, Any]],
    default_sources: list[str] | None = None,
) -> dict[str, Any]:
    expected_sources = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    source_debug = [classify_source(post) for post in posts]
    source_counts = Counter(item["detected_source_type"] for item in source_debug)
    source_coverage = {source: source_counts.get(source, 0) > 0 for source in expected_sources}

    stakeholder_evidence = extract_rule_evidence(posts, STAKEHOLDER_RULES, "stakeholder_type")
    stance_evidence = extract_rule_evidence(posts, STANCE_RULES, "stance_type")
    temporal_stage_evidence = extract_rule_evidence(posts, TEMPORAL_STAGE_RULES, "stage_type")

    covered_stakeholders = sorted(_strong_labels(stakeholder_evidence, "stakeholder_type"))
    covered_stances = sorted(_strong_labels(stance_evidence, "stance_type"))
    covered_temporal_stages = sorted(_strong_labels(temporal_stage_evidence, "stage_type"))
    non_neutral_stances = [item for item in covered_stances if item != "neutral_report"]

    temporal_labels = _expected_temporal_labels(event)
    temporal_stage_coverage = {
        label: bool(set(mapped) & set(covered_temporal_stages))
        for label, mapped in temporal_labels.items()
    }
    missing_sources: list[str] = []
    if "official" in source_coverage and not source_coverage["official"]:
        missing_sources.append("official")
    expected_interactions = [source for source in INTERACTION_SOURCE_TYPES if source in source_coverage]
    if expected_interactions and not any(source_coverage[source] for source in expected_interactions):
        missing_sources.extend(expected_interactions)
    missing_stakeholders = [] if len(covered_stakeholders) >= 2 else ["minimum_stakeholder_categories"]
    missing_stances = [] if len(covered_stances) >= 2 and non_neutral_stances else ["minimum_non_neutral_stances"]
    missing_temporal = [] if len(covered_temporal_stages) >= 3 else ["minimum_temporal_stages"]
    need_repair = bool(missing_sources or missing_stakeholders or missing_stances or missing_temporal)
    urls = [post.get("url") for post in posts if post.get("url")]
    duplicate_urls = len(urls) - len(set(urls))

    return {
        "source_coverage": source_coverage,
        "source_counts": dict(source_counts),
        "source_detection": source_debug,
        "covered_stakeholders": covered_stakeholders,
        "stakeholder_evidence": stakeholder_evidence,
        "stakeholder_coverage": {label: label in covered_stakeholders for label in _labels(STAKEHOLDER_RULES)},
        "covered_stances": covered_stances,
        "stance_evidence": stance_evidence,
        "stance_coverage": {label: label in covered_stances for label in _labels(STANCE_RULES)},
        "covered_temporal_stages": covered_temporal_stages,
        "temporal_stage_evidence": temporal_stage_evidence,
        "temporal_stage_coverage": temporal_stage_coverage,
        "temporal_stage_coverage_mode": "rule_based_chinese_semantic",
        "traceability_rate": (len(urls) / len(posts)) if posts else 0.0,
        "redundancy_rate": (duplicate_urls / len(posts)) if posts else 0.0,
        "missing_sources": missing_sources,
        "missing_stakeholders": missing_stakeholders,
        "missing_stances": missing_stances,
        "missing_temporal_stages": missing_temporal,
        "need_query_repair": need_repair,
        "repair_reason": _repair_reason(missing_sources, missing_stakeholders, missing_stances, missing_temporal, posts),
    }


def extract_rule_evidence(posts: list[dict[str, Any]], rules: tuple[Rule, ...], label_key: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for post in posts:
        source_debug = classify_source(post)
        text = f"{post.get('title', '')} {post.get('snippet', '')} {post.get('text', '')}"
        text_lower = text.lower()
        for rule in rules:
            matched = _first_matched_term(text_lower, rule.terms)
            if not matched:
                continue
            evidence.append(
                {
                    label_key: rule.label,
                    "raw_id": post.get("raw_id"),
                    "matched_text": excerpt(text, matched),
                    "matched_rule": rule.rule_id,
                    "source_type": source_debug["detected_source_type"],
                    "confidence": rule.confidence,
                    "rule_strength": rule.strength,
                }
            )
    return evidence


def coverage_debug_rows(event_id: str, coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for kind, rows_key, label_key in (
        ("stakeholder", "stakeholder_evidence", "stakeholder_type"),
        ("stance", "stance_evidence", "stance_type"),
        ("temporal_stage", "temporal_stage_evidence", "stage_type"),
    ):
        for item in coverage.get(rows_key, []):
            rows.append({"event_id": event_id, "coverage_kind": kind, "label": item.get(label_key), **item})
    return rows


def extract_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().strip()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_source_scope(value: Any, default_sources: list[str] | None = None) -> list[str]:
    sources = as_list(value) or list(default_sources or DEFAULT_SOURCE_TYPES)
    return unique([normalize_source_type(source) for source in sources])


def normalize_source_type(source: Any) -> str:
    value = str(source or "").strip()
    return SOURCE_ALIASES.get(value.lower(), value)


@lru_cache(maxsize=1)
def load_source_detection_config() -> dict[str, Any]:
    if not DEFAULT_SOURCE_CONFIG_PATH.exists():
        return _default_source_detection_config()
    config = yaml.safe_load(DEFAULT_SOURCE_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    defaults = _default_source_detection_config()
    for key, value in defaults.items():
        config.setdefault(key, value)
    return config


def _default_source_detection_config() -> dict[str, Any]:
    return {
        "official_domains": ["gov.cn"],
        "local_gov_domains": {},
        "official_title_keywords": ["政府官网", "政务公开", "信息公开", "人民政府", "政务服务"],
        "official_department_keywords": ["自然资源局", "住房和城乡建设局", "住建局", "发改委", "街道办", "区政府", "市政府"],
        "official_intent_keywords": ["公示", "公告", "批复", "审批", "信息公开", "政务公开", "回应", "通报", "整改"],
        "interaction_domains": ["liuyan.people.com.cn"],
        "interaction_keywords": ["领导留言板", "12345", "政民互动", "问政", "投诉咨询", "信访", "留言"],
        "news_domains": ["people.com.cn", "xinhuanet.com", "thepaper.cn"],
        "news_keywords": ["新闻", "日报", "晚报", "电视台", "报社"],
        "forum_domains": ["tieba.baidu.com", "zhihu.com"],
        "forum_keywords": ["论坛", "社区", "贴吧", "知乎", "业主论坛", "bbs"],
        "social_domains": ["weibo.com", "douyin.com", "xiaohongshu.com", "bilibili.com"],
        "social_keywords": ["微博", "微信公众号", "抖音", "快手", "小红书", "B站", "视频号"],
        "official_first_pass_budget": 4,
        "official_repair_budget": 8,
        "official_query_templates": {"first_pass": [], "repair": []},
    }


def _is_config_domain(domain: str, configured_domains: list[str]) -> bool:
    domain = domain.lower().strip()
    return any(domain == item.lower().strip() or domain.endswith("." + item.lower().strip()) for item in configured_domains)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            output.append(item)
            seen.add(item)
    return output


def excerpt(text: str, matched: str, window: int = 28) -> str:
    index = text.lower().find(matched.lower())
    if index < 0:
        return matched
    start = max(0, index - window)
    end = min(len(text), index + len(matched) + window)
    return text[start:end].strip()


def _first_matched_term(text: str, terms: tuple[str, ...]) -> str:
    for term in terms:
        term_text = str(term).lower()
        if term_text in text:
            return str(term)
    return ""


def _strong_labels(rows: list[dict[str, Any]], label_key: str) -> set[str]:
    return {str(row[label_key]) for row in rows if row.get("rule_strength") == "strong"}


def _labels(rules: tuple[Rule, ...]) -> list[str]:
    return sorted({rule.label for rule in rules})


def _expected_temporal_labels(event: dict[str, Any]) -> dict[str, list[str]]:
    configured = as_list(event.get("temporal_stages"))
    if not configured:
        return {label: [label] for label in _labels(TEMPORAL_STAGE_RULES)}
    output: dict[str, list[str]] = {}
    for label in configured:
        output[label] = LEGACY_STAGE_MAP.get(label, [label])
    return output


def _repair_reason(
    sources: list[str], stakeholders: list[str], stances: list[str], temporal: list[str], posts: list[dict[str, Any]]
) -> str:
    if not posts:
        return "no posts collected"
    parts = []
    if sources:
        parts.append("missing sources")
    if stakeholders:
        parts.append("missing stakeholder coverage")
    if stances:
        parts.append("missing stance coverage")
    if temporal:
        parts.append("missing temporal-stage coverage")
    return "; ".join(parts) if parts else "coverage sufficient"
