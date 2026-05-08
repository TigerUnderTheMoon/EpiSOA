"""Filter normalized evidence and generate targeted recollection plans."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from episoa.data.loader import read_jsonl, write_jsonl


DEFAULT_INPUT = Path("data/pubevent_soa_lite/evidence.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_OUTPUT = Path("data/pubevent_soa_lite/evidence_filtered.jsonl")
DEFAULT_REPORT_JSON = Path("data/pubevent_soa_lite/interim/evidence_quality_report.json")
DEFAULT_REPORT_CSV = Path("data/pubevent_soa_lite/interim/evidence_quality_report.csv")
DEFAULT_CLASSIFICATION_CSV = Path("data/pubevent_soa_lite/interim/source_classification_report.csv")
DEFAULT_RECOLLECTION_PLAN = Path("data/pubevent_soa_lite/interim/recollection_plan.jsonl")

SUBJECT_TERMS = ["居民", "村民", "业主", "网友", "政府", "街道办", "住建局", "开发商", "企业", "专家", "媒体"]
ACTION_TERMS = ["质疑", "反映", "投诉", "回应", "通报", "说明", "支持", "反对", "争议", "补偿", "安置", "整改", "推进"]
SEO_TERMS = ["什么是", "一文看懂", "律师告诉你", "法律依据", "补偿标准是什么", "怎么赔偿", "政策解读", "全解析"]
LOW_QUALITY_DOMAINS = {
    "66law.cn",
    "findlaw.cn",
    "lawtime.cn",
    "book118.com",
    "doc88.com",
    "wenku.baidu.com",
    "m.fang.com",
}
NEWS_DOMAINS = (
    "thepaper.cn",
    "news.qq.com",
    "chinanews.com",
    "chinanews.com.cn",
    "gmw.cn",
    "xinhuanet.com",
    "people.com.cn",
    "163.com",
    "sohu.com",
)
PUBLIC_INTERACTION_DOMAINS = ("liuyan.people.com.cn",)
PUBLIC_SOCIAL_DOMAINS = ("weibo.com", "m.weibo.cn", "douyin.com", "xiaohongshu.com", "xhslink.com")
TRUSTED_TEXT_HINTS = ["人民政府", "政府办公室", "住建局", "教育局", "卫健委", "生态环境局", "融媒体", "日报", "晚报", "新闻网"]
OFFICIAL_TEXT_HINTS = ["住建局", "自然资源局", "发改委", "区政府", "街道办", "人民政府", "政府办公室", "教育局", "卫健委"]
INTERACTION_TEXT_HINTS = ["问政", "留言板", "领导留言", "投诉建议", "人民网领导留言板", "办理回复", "处理结果"]
FORUM_TEXT_HINTS = ["地方论坛", "业主论坛", "社区讨论", "网友发帖", "跟帖", "论坛"]
PLACE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}(市|区|县|镇|村|街道|社区|小区|学校|医院|公司|项目|地块)")
TIME_PATTERN = re.compile(r"(\d{4}[-年]\d{1,2}[-月]\d{1,2}|20\d{2}年|\d{1,2}月\d{1,2}日)")
TARGET_RECOLLECTION_TERMS = [
    "官方回应",
    "政府通报",
    "住建局回应",
    "街道办说明",
    "业主投诉",
    "居民反映",
    "问政留言",
    "处理结果",
    "最新进展",
]
DEFAULT_SITE_SCOPE = ["gov.cn", "liuyan.people.com.cn", "people.com.cn", "地方政府官网", "地方住建局官网", "地方问政平台"]
INTERACTION_SOURCES = {"public_interaction", "forum", "public_social"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return filter_evidence(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Filter normalized evidence by quality for later annotation.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--report-csv", default=str(DEFAULT_REPORT_CSV))
    parser.add_argument("--classification-csv", default=str(DEFAULT_CLASSIFICATION_CSV))
    parser.add_argument("--recollection-plan", default=str(DEFAULT_RECOLLECTION_PLAN))
    parser.add_argument("--max-per-event", type=int, default=30)
    parser.add_argument("--min-per-event", type=int, default=15)
    parser.add_argument("--max-per-domain", type=int, default=5)
    parser.add_argument("--quality-threshold", type=float, default=0.45)
    parser.add_argument("--max-domain-share", type=float, default=0.35)
    return parser


def filter_evidence(args: argparse.Namespace) -> int:
    evidence = read_jsonl(args.input)
    events = read_jsonl(args.events) if Path(args.events).exists() else []
    event_terms = load_event_terms(events)
    duplicate_keys = find_duplicate_keys(evidence)
    scored = [score_evidence(item, event_terms.get(str(item.get("event_id", "")), []), duplicate_keys) for item in evidence]
    selected, drop_reasons = select_evidence(
        scored,
        max_per_event=args.max_per_event,
        min_per_event=args.min_per_event,
        max_per_domain=args.max_per_domain,
        quality_threshold=args.quality_threshold,
    )

    report = build_report(evidence, scored, selected, drop_reasons, args.min_per_event, args.max_domain_share)
    recollection_plan = build_recollection_plan(events, selected, report["events_need_recollection"])

    write_jsonl(args.output, selected)
    write_json_report(Path(args.report_json), report)
    write_csv_report(Path(args.report_csv), report)
    write_source_classification_report(Path(args.classification_csv), scored)
    write_jsonl(args.recollection_plan, recollection_plan)
    print(f"wrote {len(selected)} filtered evidence records to {args.output}")
    print(f"wrote quality report to {args.report_json}")
    print(f"wrote source classification report to {args.classification_csv}")
    print(f"wrote {len(recollection_plan)} recollection plan rows to {args.recollection_plan}")
    return 0


def score_evidence(item: dict[str, Any], event_terms: list[str], duplicate_keys: set[str]) -> dict[str, Any]:
    text = str(item.get("text") or "")
    url = str(item.get("url") or "")
    original_source = str(item.get("source") or "")
    platform = str(item.get("platform") or "")
    domain = extract_domain(url, platform)
    classified_source, classification_reason = classify_source_type(domain, platform, text, original_source)
    flags: list[str] = []
    score = 0.0

    score = _add(score, flags, bool(url), 0.12, "has_url")
    score = _add(score, flags, bool(text.strip()) and len(text.strip()) > 80, 0.16, "text_len_gt_80")
    score = _add(score, flags, is_trusted_platform(platform, domain, text, classified_source), 0.14, "trusted_or_local_media")
    score = _add(score, flags, contains_any(text, event_terms), 0.12, "contains_event_terms")
    score = _add(score, flags, contains_any(text, SUBJECT_TERMS), 0.12, "contains_subject_terms")
    score = _add(score, flags, contains_any(text, ACTION_TERMS), 0.12, "contains_action_terms")
    score = _add(score, flags, has_time_info(item, text), 0.10, "has_time_info")
    score = _add(score, flags, classified_source in {"official", "forum", "public_social", "public_interaction"}, 0.08, f"source_weight_{classified_source}")

    if is_low_quality_domain(domain):
        score -= 0.25
        flags.append("low_quality_domain")
    if contains_any(text, SEO_TERMS):
        score -= 0.18
        flags.append("seo_or_generic_title")
    if not has_specific_place_or_subject(text):
        score -= 0.10
        flags.append("no_specific_place_or_subject")
    if looks_policy_only(text):
        score -= 0.15
        flags.append("policy_explanation_without_event_dispute")
    if duplicate_key(item) in duplicate_keys:
        score -= 0.15
        flags.append("high_duplicate_risk")

    output = dict(item)
    output["original_source"] = original_source
    output["source"] = classified_source
    output["source_classification_reason"] = classification_reason
    output["quality_score"] = round(max(0.0, min(1.0, score)), 4)
    output["quality_flags"] = flags
    output["domain"] = domain
    output["selected_for_annotation"] = True
    return output


def classify_source_type(domain: str, platform: str, text: str, original_source: str = "") -> tuple[str, str]:
    domain = domain.lower()
    joined = f"{platform} {domain} {text}"
    platform_domain = f"{platform} {domain}"
    original = original_source.lower()
    if domain == "liuyan.people.com.cn" or contains_any(joined, INTERACTION_TEXT_HINTS):
        return "public_interaction", "public interaction domain or text hint"
    if domain.endswith("gov.cn") or contains_any(platform_domain, OFFICIAL_TEXT_HINTS):
        return "official", "government domain or official platform hint"
    if "bbs" in domain or "forum" in domain or contains_any(joined, FORUM_TEXT_HINTS):
        return "forum", "forum domain or discussion text hint"
    if any(domain == item or domain.endswith("." + item) for item in PUBLIC_SOCIAL_DOMAINS) or original == "public_social":
        return "public_social", "public social web clue"
    if any(domain == item or domain.endswith("." + item) for item in NEWS_DOMAINS):
        return "news", "news domain"
    return "public_web", "default public web"


def select_evidence(
    scored: list[dict[str, Any]],
    *,
    max_per_event: int,
    min_per_event: int,
    max_per_domain: int,
    quality_threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scored:
        by_event[str(item.get("event_id", ""))].append(item)

    selected: list[dict[str, Any]] = []
    drop_reasons: dict[str, str] = {}
    for items in by_event.values():
        items = sorted(items, key=lambda row: (float(row["quality_score"]), source_priority(str(row.get("source")))), reverse=True)
        event_selected: list[dict[str, Any]] = []
        domain_counts: Counter[str] = Counter()
        domain_limited: set[str] = set()

        for item in items:
            if len(event_selected) >= max_per_event:
                break
            domain = str(item.get("domain") or "unknown")
            if domain_counts[domain] >= max_per_domain:
                domain_limited.add(str(item.get("evidence_id")))
                continue
            if float(item["quality_score"]) >= quality_threshold:
                event_selected.append(item)
                domain_counts[domain] += 1

        if len(event_selected) < min_per_event:
            selected_ids = {str(item.get("evidence_id")) for item in event_selected}
            for item in items:
                if len(event_selected) >= min(max_per_event, min_per_event):
                    break
                evidence_id = str(item.get("evidence_id"))
                domain = str(item.get("domain") or "unknown")
                if evidence_id in selected_ids or domain_counts[domain] >= max_per_domain:
                    continue
                event_selected.append(item)
                selected_ids.add(evidence_id)
                domain_counts[domain] += 1

        selected_ids = {str(item.get("evidence_id")) for item in event_selected}
        for item in items:
            evidence_id = str(item.get("evidence_id"))
            if evidence_id in selected_ids:
                continue
            drop_reasons[evidence_id] = "domain_limit" if evidence_id in domain_limited else "low_quality"
        selected.extend(event_selected)

    return selected, drop_reasons


def source_priority(source: str) -> int:
    return {"official": 5, "public_interaction": 4, "forum": 3, "public_social": 2, "news": 1}.get(source, 0)


def build_report(
    evidence: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    drop_reasons: dict[str, str],
    min_per_event: int,
    max_domain_share: float,
) -> dict[str, Any]:
    before_counts = count_by_event(evidence)
    after_counts = count_by_event(selected)
    events_need_recollection = []
    selected_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        selected_by_event[str(item.get("event_id") or "unknown")].append(item)

    for event_id in sorted(before_counts):
        rows = selected_by_event.get(event_id, [])
        reasons = recollection_reasons(rows, min_per_event, max_domain_share)
        if reasons:
            events_need_recollection.append(
                {
                    "event_id": event_id,
                    "before": before_counts.get(event_id, 0),
                    "after": after_counts.get(event_id, 0),
                    "need_recollection": True,
                    "missing_sources": missing_sources(rows),
                    "reason": reasons,
                    "top_domain_share": top_domain_share(rows),
                }
            )

    return {
        "total_input": len(evidence),
        "total_output": len(selected),
        "dropped_by_low_quality": sum(1 for reason in drop_reasons.values() if reason == "low_quality"),
        "dropped_by_domain_limit": sum(1 for reason in drop_reasons.values() if reason == "domain_limit"),
        "event_coverage_before": before_counts,
        "event_coverage_after": after_counts,
        "source_distribution_before": dict(Counter(str(item.get("source") or "unknown") for item in scored)),
        "source_distribution_after": dict(Counter(str(item.get("source") or "unknown") for item in selected)),
        "top_domains_before": top_domains(scored),
        "top_domains_after": top_domains(selected),
        "events_need_recollection": events_need_recollection,
    }


def recollection_reasons(rows: list[dict[str, Any]], min_per_event: int, max_domain_share: float) -> list[str]:
    counts = Counter(str(item.get("source") or "unknown") for item in rows)
    reasons: list[str] = []
    if len(rows) < min_per_event:
        reasons.append("filtered evidence fewer than minimum")
    if counts.get("official", 0) == 0:
        reasons.append("official evidence missing")
    if sum(counts.get(source, 0) for source in INTERACTION_SOURCES) < 3:
        reasons.append("public_interaction/forum/public_social evidence fewer than 3")
    if top_domain_share(rows) > max_domain_share:
        reasons.append("top domain share too high")
    return reasons


def missing_sources(rows: list[dict[str, Any]]) -> list[str]:
    counts = Counter(str(item.get("source") or "unknown") for item in rows)
    missing = []
    if counts.get("official", 0) == 0:
        missing.append("official")
    if counts.get("public_interaction", 0) == 0:
        missing.append("public_interaction")
    if counts.get("forum", 0) == 0:
        missing.append("forum")
    if counts.get("public_social", 0) == 0:
        missing.append("public_social")
    return missing


def top_domain_share(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    counts = Counter(str(item.get("domain") or "unknown") for item in rows)
    return max(counts.values()) / len(rows)


def build_recollection_plan(
    events: list[dict[str, Any]], selected: list[dict[str, Any]], need_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    events_by_id = {str(item.get("event_id")): item for item in events}
    selected_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        selected_by_event[str(item.get("event_id"))].append(item)

    plan = []
    for row in need_rows:
        event_id = str(row["event_id"])
        event = events_by_id.get(event_id, {"event_id": event_id})
        missing = list(row.get("missing_sources") or [])
        target_sources = [source for source in ["official", "public_interaction", "forum", "public_social"] if source in missing]
        if not target_sources:
            target_sources = ["official", "public_interaction"]
        plan.append(
            {
                "event_id": event_id,
                "event_name": event.get("event_name"),
                "missing_sources": missing,
                "target_sources": target_sources,
                "source_scope": target_sources,
                "repair_keywords": build_repair_keywords(event),
                "site_scope": list(DEFAULT_SITE_SCOPE),
                "reason": row.get("reason", []),
                "existing_filtered_evidence": len(selected_by_event.get(event_id, [])),
            }
        )
    return plan


def build_repair_keywords(event: dict[str, Any]) -> list[str]:
    base_terms = []
    for value in [event.get("event_name"), *(event.get("seed_keywords") or [])]:
        if value:
            base_terms.append(str(value))
    if not base_terms:
        base_terms.append(str(event.get("event_id", "")))
    keywords = []
    for base in base_terms[:4]:
        for target in TARGET_RECOLLECTION_TERMS:
            keywords.append(f"{base} {target}")
    return list(dict.fromkeys(keywords))


def load_event_terms(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    terms: dict[str, list[str]] = {}
    for event in events:
        event_id = str(event.get("event_id", ""))
        values = [event.get("event_name"), event.get("event_description")]
        values.extend(event.get("seed_keywords") or [])
        terms[event_id] = tokenize_terms(values)
    return terms


def tokenize_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    for value in values:
        if not value:
            continue
        text = str(value)
        terms.append(text)
        terms.extend([part for part in re.split(r"\s+|，|,|、|。|：|:", text) if len(part) >= 2])
    return list(dict.fromkeys(terms))


def find_duplicate_keys(evidence: list[dict[str, Any]]) -> set[str]:
    counts = Counter(duplicate_key(item) for item in evidence)
    return {key for key, count in counts.items() if count > 1}


def duplicate_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return "url:" + url
    text = re.sub(r"\s+", "", str(item.get("text") or ""))[:300]
    return "text:" + hashlib.sha1(text.encode("utf-8")).hexdigest()


def extract_domain(url: str, platform: str | None = None) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or str(platform or "")
    host = host.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def is_trusted_platform(platform: str, domain: str, text: str, source: str) -> bool:
    if source in {"official", "public_interaction", "news"}:
        return True
    joined = f"{platform} {domain} {text}"
    return contains_any(joined, TRUSTED_TEXT_HINTS)


def is_low_quality_domain(domain: str) -> bool:
    return any(domain == bad or domain.endswith("." + bad) for bad in LOW_QUALITY_DOMAINS)


def has_time_info(item: dict[str, Any], text: str) -> bool:
    publish_time = str(item.get("publish_time") or "")
    return bool(publish_time.strip()) or bool(TIME_PATTERN.search(text))


def has_specific_place_or_subject(text: str) -> bool:
    return bool(PLACE_PATTERN.search(text)) or contains_any(text, SUBJECT_TERMS)


def looks_policy_only(text: str) -> bool:
    has_policy = contains_any(text, ["条例", "办法", "规定", "政策", "法律", "标准", "指南"])
    has_dispute = contains_any(text, ["争议", "投诉", "反映", "质疑", "不满", "回应", "通报", "整改", "维权"])
    return has_policy and not has_dispute


def contains_any(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    if not terms:
        return False
    return any(term and term in text for term in terms)


def _add(score: float, flags: list[str], condition: bool, weight: float, flag: str) -> float:
    if condition:
        flags.append(flag)
        return score + weight
    return score


def count_by_event(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(item.get("event_id") or "unknown") for item in rows))


def top_domains(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("domain") or extract_domain(str(item.get("url") or ""), str(item.get("platform") or ""))) for item in rows)
    return [{"domain": domain, "count": count} for domain, count in counts.most_common(limit)]


def write_json_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    before = report["event_coverage_before"]
    after = report["event_coverage_after"]
    need = {item["event_id"] for item in report["events_need_recollection"]}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["event_id", "before_count", "after_count", "need_recollection"])
        for event_id in sorted(before):
            writer.writerow([event_id, before.get(event_id, 0), after.get(event_id, 0), str(event_id in need).lower()])


def write_source_classification_report(path: Path, scored: list[dict[str, Any]]) -> None:
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scored:
        by_domain[str(item.get("domain") or "unknown")].append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["domain", "count", "classified_source", "original_sources", "classification_reason"])
        for domain, rows in sorted(by_domain.items(), key=lambda pair: len(pair[1]), reverse=True):
            sources = Counter(str(item.get("source") or "unknown") for item in rows)
            original_sources = Counter(str(item.get("original_source") or "unknown") for item in rows)
            reason = Counter(str(item.get("source_classification_reason") or "") for item in rows).most_common(1)[0][0]
            writer.writerow(
                [
                    domain,
                    len(rows),
                    sources.most_common(1)[0][0],
                    json.dumps(dict(original_sources), ensure_ascii=False),
                    reason,
                ]
            )


if __name__ == "__main__":
    raise SystemExit(main())
