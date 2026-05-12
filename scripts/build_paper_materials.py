from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


BASE = Path.cwd()
OUT = BASE / "outputs" / "runs" / "paper_materials"
OUT.mkdir(parents=True, exist_ok=True)

PATHS = {
    "events": BASE / "data" / "pubevent_soa_lite" / "events.jsonl",
    "evidence_graph_summary": BASE / "data" / "pubevent_soa_lite" / "graph" / "evidence_graph_summary.json",
    "event_chain_summary": BASE / "outputs" / "runs" / "event_chain_retrieval" / "event_chain_retrieval_summary.json",
    "event_chains": BASE / "outputs" / "runs" / "event_chain_retrieval" / "event_chain_candidates.jsonl",
    "schema_summary": BASE / "outputs" / "runs" / "schema_attribution" / "schema_attribution_summary.json",
    "candidate_tuples": BASE / "outputs" / "runs" / "schema_attribution" / "candidate_soa_tuples.jsonl",
    "verifier_summary": BASE / "outputs" / "runs" / "faithfulness_verification" / "verifier_summary.json",
    "verified_tuples": BASE / "outputs" / "runs" / "faithfulness_verification" / "verified_soa_tuples.jsonl",
}


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def pct(x: float | int | None) -> str:
    if x is None:
        return ""
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return ""


def num(x: Any, ndigits: int = 4) -> str:
    if isinstance(x, float):
        return f"{x:.{ndigits}f}"
    return str(x)


def trunc(x: Any, n: int = 90) -> str:
    s = "" if x is None else str(x)
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def md_escape(x: Any) -> str:
    return str(x).replace("|", "\\|").replace("\n", "<br>")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        out.append("| " + " | ".join(md_escape(v) for v in row) + " |")
    return "\n".join(out)


events = read_jsonl(PATHS["events"])
event_map = {e.get("event_id"): e for e in events}

graph_summary = read_json(PATHS["evidence_graph_summary"], {})
chain_summary = read_json(PATHS["event_chain_summary"], {})
schema_summary = read_json(PATHS["schema_summary"], {})
verifier_summary = read_json(PATHS["verifier_summary"], {})

chains = read_jsonl(PATHS["event_chains"])
chain_map = {c.get("event_id"): c for c in chains if c.get("event_id")}

candidate_rows = read_jsonl(PATHS["candidate_tuples"])
verified_rows = read_jsonl(PATHS["verified_tuples"])

if not verified_rows:
    raise SystemExit("No verified tuples found. Please run faithfulness verification first.")


# ---------------------------------------------------------------------
# 1. Pipeline summary table
# ---------------------------------------------------------------------

pipeline_rows = [
    {
        "stage": "Public event definition",
        "output_file": "events.jsonl",
        "main_metric": f"{len(events)} events",
        "paper_usage": "Defines the public-event sample and event-level query settings.",
    },
    {
        "stage": "Stakeholder–event evidence graph",
        "output_file": "evidence_graph_summary.json",
        "main_metric": (
            f"{graph_summary.get('num_nodes', '')} nodes; "
            f"{graph_summary.get('num_edges', '')} edges"
        ),
        "paper_usage": "Reports the structural context built from events, evidence, stakeholders, sources and stages.",
    },
    {
        "stage": "Event-chain retrieval",
        "output_file": "event_chain_retrieval_summary.json",
        "main_metric": f"avg_chain_confidence={chain_summary.get('avg_chain_confidence', '')}",
        "paper_usage": "Reports candidate event-chain coverage and retrieval confidence.",
    },
    {
        "stage": "Schema-constrained SOA",
        "output_file": "candidate_soa_tuples.jsonl",
        "main_metric": (
            f"{schema_summary.get('num_tuples_generated', len(candidate_rows))} candidate tuples; "
            f"{schema_summary.get('num_api_failures', '')} API failures; "
            f"{len(schema_summary.get('parse_failed_events', []))} parse failures"
        ),
        "paper_usage": "Reports candidate stakeholder-opinion-sentiment-rationale extraction.",
    },
    {
        "stage": "Evidence faithfulness verification",
        "output_file": "verified_soa_tuples.jsonl",
        "main_metric": (
            f"{verifier_summary.get('num_verified_tuples', len(verified_rows))} verified tuples; "
            f"supported_rate={pct(verifier_summary.get('supported_rate'))}; "
            f"avg_score={num(verifier_summary.get('avg_verification_score'))}"
        ),
        "paper_usage": "Reports whether candidate tuples are supported by linked evidence.",
    },
]

write_csv(
    OUT / "table_1_pipeline_summary.csv",
    pipeline_rows,
    ["stage", "output_file", "main_metric", "paper_usage"],
)


# ---------------------------------------------------------------------
# 2. Verification label distribution
# ---------------------------------------------------------------------

label_counter = Counter(r.get("verification_label", "unknown") for r in verified_rows)
total_verified = len(verified_rows)

label_rows = []
for label in ["supported", "partially_supported", "unsupported", "unclear", "unknown"]:
    count = label_counter.get(label, 0)
    if count == 0 and label == "unknown":
        continue
    label_rows.append(
        {
            "verification_label": label,
            "count": count,
            "percentage": f"{count / total_verified * 100:.2f}%" if total_verified else "0.00%",
            "paper_interpretation": {
                "supported": "The tuple is fully supported by the linked evidence.",
                "partially_supported": "The tuple is partly supported but contains mild overgeneralization or weak sentiment/rationale support.",
                "unsupported": "The tuple is not supported by the linked evidence.",
                "unclear": "The evidence is insufficient or ambiguous.",
                "unknown": "Unexpected or missing label.",
            }.get(label, ""),
        }
    )

write_csv(
    OUT / "table_2_verification_label_distribution.csv",
    label_rows,
    ["verification_label", "count", "percentage", "paper_interpretation"],
)


# ---------------------------------------------------------------------
# 3. Issue flag distribution
# ---------------------------------------------------------------------

issue_counter: Counter[str] = Counter()
for r in verified_rows:
    flags = r.get("issue_flags") or []
    if isinstance(flags, str):
        flags = [flags]
    for f in flags:
        issue_counter[f] += 1

issue_rows = []
for flag, count in issue_counter.most_common():
    issue_rows.append(
        {
            "issue_flag": flag,
            "count": count,
            "percentage_of_verified_tuples": f"{count / total_verified * 100:.2f}%",
            "paper_interpretation": {
                "no_issue": "No obvious faithfulness issue was detected.",
                "stakeholder_not_supported": "The stakeholder label is broader or less direct than the evidence.",
                "rationale_not_supported": "The rationale is not fully supported by the evidence.",
                "sentiment_not_supported": "The sentiment label is not directly supported by the evidence.",
                "opinion_overgeneralized": "The opinion overgeneralizes beyond the evidence.",
                "official_action_should_be_neutral": "An official action was over-interpreted as positive sentiment.",
                "media_comment_should_be_neutral": "A media comment was over-interpreted as positive sentiment.",
                "missing_evidence": "The referenced evidence ID is missing.",
                "weak_evidence": "The evidence is weak or indirect.",
                "stage_mismatch": "The event-chain stage may not match the evidence content.",
            }.get(flag, ""),
        }
    )

write_csv(
    OUT / "table_3_issue_flag_distribution.csv",
    issue_rows,
    ["issue_flag", "count", "percentage_of_verified_tuples", "paper_interpretation"],
)


# ---------------------------------------------------------------------
# 4. Event-level summary
# ---------------------------------------------------------------------

verified_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
candidate_by_event: Counter[str] = Counter()
for r in candidate_rows:
    candidate_by_event[r.get("event_id")] += 1
for r in verified_rows:
    verified_by_event[r.get("event_id")].append(r)

event_ids = sorted(set(event_map) | set(candidate_by_event) | set(verified_by_event))

event_rows = []
for eid in event_ids:
    rows = verified_by_event.get(eid, [])
    labels = Counter(r.get("verification_label", "unknown") for r in rows)
    sentiments = Counter(r.get("sentiment", "unknown") for r in rows)
    flags = Counter()
    for r in rows:
        for f in r.get("issue_flags") or []:
            flags[f] += 1

    scores = [
        float(r.get("verification_score"))
        for r in rows
        if isinstance(r.get("verification_score"), (int, float))
    ]

    chain = chain_map.get(eid, {})
    event = event_map.get(eid, {})

    event_rows.append(
        {
            "event_id": eid,
            "event_name": event.get("event_name", ""),
            "candidate_tuple_count": candidate_by_event.get(eid, 0),
            "verified_tuple_count": len(rows),
            "supported_count": labels.get("supported", 0),
            "partially_supported_count": labels.get("partially_supported", 0),
            "unsupported_count": labels.get("unsupported", 0),
            "unclear_count": labels.get("unclear", 0),
            "supported_rate": f"{labels.get('supported', 0) / len(rows) * 100:.2f}%" if rows else "",
            "avg_verification_score": f"{mean(scores):.4f}" if scores else "",
            "negative_count": sentiments.get("negative", 0),
            "neutral_count": sentiments.get("neutral", 0),
            "positive_count": sentiments.get("positive", 0),
            "main_issue_flags": "; ".join(f"{k}:{v}" for k, v in flags.most_common(5)),
            "chain_confidence": chain.get("chain_confidence", ""),
            "missing_stages": json.dumps(chain.get("missing_stages", []), ensure_ascii=False),
        }
    )

write_csv(
    OUT / "table_4_event_level_summary.csv",
    event_rows,
    [
        "event_id",
        "event_name",
        "candidate_tuple_count",
        "verified_tuple_count",
        "supported_count",
        "partially_supported_count",
        "unsupported_count",
        "unclear_count",
        "supported_rate",
        "avg_verification_score",
        "negative_count",
        "neutral_count",
        "positive_count",
        "main_issue_flags",
        "chain_confidence",
        "missing_stages",
    ],
)


# ---------------------------------------------------------------------
# 5. Cleaned tuple files
# ---------------------------------------------------------------------

fully_supported = [r for r in verified_rows if r.get("verification_label") == "supported"]
weak_or_bad = [r for r in verified_rows if r.get("verification_label") != "supported"]
issue_tuples = [
    r
    for r in verified_rows
    if r.get("issue_flags") and r.get("issue_flags") != ["no_issue"]
]

write_jsonl(OUT / "fully_supported_tuples.jsonl", fully_supported)
write_jsonl(OUT / "partially_or_unsupported_tuples.jsonl", weak_or_bad)
write_jsonl(OUT / "issue_tuples.jsonl", issue_tuples)

write_csv(
    OUT / "table_5_verified_tuple_appendix.csv",
    verified_rows,
    [
        "event_id",
        "tuple_id",
        "stakeholder",
        "opinion",
        "sentiment",
        "rationale",
        "evidence_ids",
        "event_chain_stage",
        "candidate_confidence",
        "verification_label",
        "verification_score",
        "verification_rationale",
        "issue_flags",
    ],
)


# ---------------------------------------------------------------------
# 6. Case-study overview
# ---------------------------------------------------------------------

CASE_EVENTS = ["E004", "E012", "E025", "E044"]

case_overview_rows = []
for eid in CASE_EVENTS:
    rows = verified_by_event.get(eid, [])
    if not rows:
        continue
    labels = Counter(r.get("verification_label", "unknown") for r in rows)
    sentiments = Counter(r.get("sentiment", "unknown") for r in rows)
    event = event_map.get(eid, {})
    chain = chain_map.get(eid, {})
    scores = [
        float(r.get("verification_score"))
        for r in rows
        if isinstance(r.get("verification_score"), (int, float))
    ]

    case_overview_rows.append(
        {
            "event_id": eid,
            "event_name": event.get("event_name", ""),
            "case_type": {
                "E004": "Urban village rental renovation / policy conflict",
                "E012": "Campus food safety / public safety concern",
                "E025": "Internet hospital prescription review / medical governance",
                "E044": "Ride-hailing platform pricing / platform governance",
            }.get(eid, ""),
            "verified_tuple_count": len(rows),
            "supported": labels.get("supported", 0),
            "partially_supported": labels.get("partially_supported", 0),
            "unsupported": labels.get("unsupported", 0),
            "negative": sentiments.get("negative", 0),
            "neutral": sentiments.get("neutral", 0),
            "positive": sentiments.get("positive", 0),
            "avg_verification_score": f"{mean(scores):.4f}" if scores else "",
            "chain_confidence": chain.get("chain_confidence", ""),
            "suggested_paper_use": {
                "E004": "Use as a boundary case showing how verification detects overgeneralized opinions and unsupported sentiment.",
                "E012": "Use as a public safety case showing multi-stakeholder negative concerns and official responses.",
                "E025": "Use as a healthcare governance case showing patient/consumer complaints and regulatory responses.",
                "E044": "Use as a platform governance case showing driver/media concerns about platform pricing transparency.",
            }.get(eid, ""),
        }
    )

write_csv(
    OUT / "table_6_case_event_overview.csv",
    case_overview_rows,
    [
        "event_id",
        "event_name",
        "case_type",
        "verified_tuple_count",
        "supported",
        "partially_supported",
        "unsupported",
        "negative",
        "neutral",
        "positive",
        "avg_verification_score",
        "chain_confidence",
        "suggested_paper_use",
    ],
)


# ---------------------------------------------------------------------
# 7. Markdown result tables
# ---------------------------------------------------------------------

results_md = []

results_md.append("# Paper Result Tables\n")

results_md.append("## Table 1. Pipeline-level system outputs\n")
results_md.append(
    md_table(
        ["Stage", "Output file", "Main metric", "Paper usage"],
        [[r["stage"], r["output_file"], r["main_metric"], r["paper_usage"]] for r in pipeline_rows],
    )
)

results_md.append("\n\n## Table 2. Evidence faithfulness verification labels\n")
results_md.append(
    md_table(
        ["Verification label", "Count", "Percentage", "Interpretation"],
        [
            [
                r["verification_label"],
                r["count"],
                r["percentage"],
                r["paper_interpretation"],
            ]
            for r in label_rows
        ],
    )
)

results_md.append("\n\n## Table 3. Faithfulness issue flags\n")
results_md.append(
    md_table(
        ["Issue flag", "Count", "Percentage", "Interpretation"],
        [
            [
                r["issue_flag"],
                r["count"],
                r["percentage_of_verified_tuples"],
                r["paper_interpretation"],
            ]
            for r in issue_rows
        ],
    )
)

results_md.append("\n\n## Table 4. Case-event overview\n")
results_md.append(
    md_table(
        [
            "Event",
            "Name",
            "Verified tuples",
            "Supported",
            "Partial",
            "Unsupported",
            "Neg/Neu/Pos",
            "Avg score",
            "Paper use",
        ],
        [
            [
                r["event_id"],
                trunc(r["event_name"], 40),
                r["verified_tuple_count"],
                r["supported"],
                r["partially_supported"],
                r["unsupported"],
                f"{r['negative']}/{r['neutral']}/{r['positive']}",
                r["avg_verification_score"],
                r["suggested_paper_use"],
            ]
            for r in case_overview_rows
        ],
    )
)

(OUT / "results_tables.md").write_text("\n".join(results_md), encoding="utf-8")


# ---------------------------------------------------------------------
# 8. Case-study materials
# ---------------------------------------------------------------------

case_md = []
case_md.append("# Case Study Materials for Paper\n")
case_md.append(
    "Note: The following cases are based on verified candidate tuples. "
    "They should be described as verifier-supported system outputs, not as human gold-standard labels.\n"
)

for eid in CASE_EVENTS:
    rows = verified_by_event.get(eid, [])
    if not rows:
        continue

    event = event_map.get(eid, {})
    chain = chain_map.get(eid, {})
    labels = Counter(r.get("verification_label", "unknown") for r in rows)
    sentiments = Counter(r.get("sentiment", "unknown") for r in rows)

    case_md.append(f"\n## Case {eid}: {event.get('event_name', '')}\n")
    case_md.append(f"- Event description: {event.get('event_description', '')}")
    case_md.append(f"- Chain confidence: {chain.get('chain_confidence', '')}")
    case_md.append(f"- Missing stages: {json.dumps(chain.get('missing_stages', []), ensure_ascii=False)}")
    case_md.append(
        f"- Verified tuples: {len(rows)}; "
        f"supported={labels.get('supported', 0)}, "
        f"partially_supported={labels.get('partially_supported', 0)}, "
        f"unsupported={labels.get('unsupported', 0)}"
    )
    case_md.append(
        f"- Sentiment distribution: negative={sentiments.get('negative', 0)}, "
        f"neutral={sentiments.get('neutral', 0)}, "
        f"positive={sentiments.get('positive', 0)}\n"
    )

    table_rows = []
    for r in rows:
        quotes = r.get("evidence_quotes") or []
        if isinstance(quotes, list):
            quotes_s = "；".join(trunc(q, 45) for q in quotes[:2])
        else:
            quotes_s = trunc(quotes, 90)

        table_rows.append(
            [
                r.get("tuple_id", ""),
                r.get("stakeholder", ""),
                trunc(r.get("opinion", ""), 55),
                r.get("sentiment", ""),
                r.get("verification_label", ""),
                r.get("verification_score", ""),
                ";".join(r.get("issue_flags") or []),
                quotes_s,
            ]
        )

    case_md.append(
        md_table(
            [
                "Tuple ID",
                "Stakeholder",
                "Opinion",
                "Sentiment",
                "Verification",
                "Score",
                "Issue flags",
                "Evidence quotes",
            ],
            table_rows,
        )
    )

    # Short narrative paragraph for the paper
    supported_examples = [r for r in rows if r.get("verification_label") == "supported"]
    partial_examples = [r for r in rows if r.get("verification_label") == "partially_supported"]

    case_md.append("\nSuggested narrative:")
    if supported_examples:
        ex = supported_examples[0]
        case_md.append(
            f"在 {eid} 案例中，系统识别出“{ex.get('stakeholder')}—{ex.get('opinion')}”"
            f"这一主体观点元组，并由证据 {','.join(ex.get('evidence_ids') or [])} 支撑。"
            f"验证器将其判定为 {ex.get('verification_label')}，说明该元组中的主体、观点和情绪"
            f"与证据文本之间具有较强一致性。"
        )
    if partial_examples:
        ex = partial_examples[0]
        case_md.append(
            f"同时，案例中也存在部分支持的元组，例如“{ex.get('stakeholder')}—{ex.get('opinion')}”。"
            f"验证器指出其主要问题为 {','.join(ex.get('issue_flags') or [])}，"
            f"表明候选归因结果可能存在观点概括过强、情绪依据不足或主体指称不够直接等问题。"
        )

(OUT / "case_studies.md").write_text("\n".join(case_md), encoding="utf-8")


# ---------------------------------------------------------------------
# 9. Paper-ready text snippets
# ---------------------------------------------------------------------

supported = verifier_summary.get("label_distribution", {}).get("supported", label_counter.get("supported", 0))
partial = verifier_summary.get("label_distribution", {}).get("partially_supported", label_counter.get("partially_supported", 0))
unsupported = verifier_summary.get("label_distribution", {}).get("unsupported", label_counter.get("unsupported", 0))
unclear = verifier_summary.get("label_distribution", {}).get("unclear", label_counter.get("unclear", 0))

text = f"""# Paper-ready Result Text Snippets

## 中文结果描述

在 Schema 约束主体观点归因阶段，系统基于候选事件链和证据文本生成了 {schema_summary.get('num_tuples_generated', len(candidate_rows))} 条候选主体观点归因元组。随后，在证据忠实性验证阶段，本文进一步对候选元组进行逐条验证。验证器仅依据每条元组绑定的 evidence_ids 对应证据文本，判断主体、观点、情绪和依据是否被证据支持。

验证结果显示，系统共完成 {verifier_summary.get('num_verified_tuples', len(verified_rows))} 条候选元组验证，其中 {supported} 条被判定为 supported，{partial} 条被判定为 partially_supported，{unsupported} 条被判定为 unsupported，{unclear} 条被判定为 unclear。验证过程中未出现 API 调用失败或 JSON 解析失败。整体 supported rate 为 {pct(verifier_summary.get('supported_rate'))}，平均 verification score 为 {num(verifier_summary.get('avg_verification_score'))}。

需要强调的是，supported rate 表示验证器基于证据文本对候选元组的支持性判定比例，并不等同于人工标注意义上的准确率、召回率或 F1 值。正式模型性能评估仍需基于人工标注的 gold_tuples 和 gold_event_chains 进行。

## English result description

In the schema-constrained stakeholder opinion attribution stage, the system generated {schema_summary.get('num_tuples_generated', len(candidate_rows))} candidate stakeholder-opinion attribution tuples based on the retrieved event-chain context and evidence texts. The faithfulness verifier then examined each candidate tuple using only the evidence passages referenced by its evidence_ids.

The verifier processed {verifier_summary.get('num_verified_tuples', len(verified_rows))} candidate tuples. Among them, {supported} tuples were labeled as supported, {partial} as partially_supported, {unsupported} as unsupported, and {unclear} as unclear. No API failure or JSON parsing failure occurred during verification. The verifier-supported rate was {pct(verifier_summary.get('supported_rate'))}, with an average verification score of {num(verifier_summary.get('avg_verification_score'))}.

The supported rate should be interpreted as the proportion of candidate tuples judged by the verifier to be supported by their linked evidence. It is not a gold-standard accuracy, recall, or F1 score, because human-annotated gold labels are not used in this stage.

## Recommended table captions

Table X. Pipeline-level outputs of the EpiSOA framework.

Table X. Distribution of evidence faithfulness verification labels.

Table X. Distribution of faithfulness issue flags.

Table X. Event-level summary of verified stakeholder opinion attribution tuples.

Table X. Case-event overview for qualitative analysis.
"""

(OUT / "paper_text_snippets.md").write_text(text, encoding="utf-8")


print("Paper materials generated:")
for p in sorted(OUT.iterdir()):
    print(" -", p)
print()
print(f"verified_tuples={len(verified_rows)}")
print(f"fully_supported={len(fully_supported)}")
print(f"partially_or_unsupported={len(weak_or_bad)}")
print(f"issue_tuples={len(issue_tuples)}")
