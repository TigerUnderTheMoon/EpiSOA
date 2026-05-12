"""Create the human annotation sheet from normalized evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl


DEFAULT_EVIDENCE_PATH = Path("data/pubevent_soa_lite/evidence.jsonl")
DEFAULT_SHEET_PATH = Path("data/pubevent_soa_lite/annotation/annotation_sheet.csv")
DEFAULT_GUIDELINE_PATH = Path("data/pubevent_soa_lite/annotation/annotation_guideline.md")
DEFAULT_SUMMARY_PATH = Path("data/pubevent_soa_lite/annotation/annotation_summary.json")

FIELDNAMES = [
    "event_id",
    "evidence_id",
    "source",
    "platform",
    "domain",
    "url",
    "publish_time",
    "quality_score",
    "text",
    "candidate_stakeholder",
    "candidate_opinion",
    "candidate_sentiment",
    "candidate_rationale",
    "is_relevant",
    "annotated_stakeholder",
    "annotated_opinion",
    "annotated_sentiment",
    "annotated_rationale",
    "support_label",
    "event_chain_step",
    "event_chain_order",
    "notes",
]

STAKEHOLDER_RULES = [
    ("居民/公众", ["居民", "村民", "业主", "群众", "网友"]),
    ("政府部门", ["政府", "街道办", "住建局", "自然资源局", "教育局", "官方", "部门"]),
    ("企业/开发商", ["企业", "开发商", "物业", "建设单位", "项目方"]),
    ("媒体/专家", ["媒体", "记者", "专家", "律师"]),
]
SENTIMENT_RULES = [
    ("positive", ["支持", "认可", "满意", "点赞"]),
    ("negative", ["质疑", "反对", "不满", "投诉", "担忧", "争议"]),
    ("neutral", ["回应", "通报", "说明", "介绍", "推进"]),
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return make_annotation_sheet(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create PubEvent-SOA human annotation CSV from normalized evidence.")
    parser.add_argument("--input", default=str(DEFAULT_EVIDENCE_PATH))
    parser.add_argument("--output", default=str(DEFAULT_SHEET_PATH))
    parser.add_argument("--guideline-output", default=str(DEFAULT_GUIDELINE_PATH))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_PATH))
    return parser


def make_annotation_sheet(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    guideline_path = Path(args.guideline_output)
    summary_path = Path(args.summary_output)

    evidence = read_jsonl(input_path) if input_path.exists() else []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    guideline_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for item in evidence:
            writer.writerow(annotation_row(item))

    guideline_path.write_text(annotation_guideline(), encoding="utf-8")
    summary = annotation_summary(evidence, output_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not evidence:
        print(f"WARNING: {input_path} is empty; annotation_sheet.csv contains headers only.")
    else:
        print(f"wrote annotation sheet with {len(evidence)} evidence rows to {output_path}")
    print(f"wrote annotation guideline to {guideline_path}")
    print(f"wrote annotation summary to {summary_path}")
    return 0


def annotation_row(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or "")
    return {
        "event_id": item.get("event_id", ""),
        "evidence_id": item.get("evidence_id", ""),
        "source": item.get("source", ""),
        "platform": item.get("platform", ""),
        "domain": item.get("domain", ""),
        "url": item.get("url", ""),
        "publish_time": item.get("publish_time", ""),
        "quality_score": item.get("quality_score", ""),
        "text": text,
        "candidate_stakeholder": infer_candidate_stakeholder(text),
        "candidate_opinion": "",
        "candidate_sentiment": infer_candidate_sentiment(text),
        "candidate_rationale": "",
        "is_relevant": "",
        "annotated_stakeholder": "",
        "annotated_opinion": "",
        "annotated_sentiment": "",
        "annotated_rationale": "",
        "support_label": "",
        "event_chain_step": "",
        "event_chain_order": "",
        "notes": "",
    }


def infer_candidate_stakeholder(text: str) -> str:
    matched = [label for label, terms in STAKEHOLDER_RULES if any(term in text for term in terms)]
    return ";".join(matched)


def infer_candidate_sentiment(text: str) -> str:
    matches = [label for label, terms in SENTIMENT_RULES if any(term in text for term in terms)]
    return matches[0] if len(matches) == 1 else ""


def annotation_summary(evidence: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
    rows_per_event = dict(Counter(str(item.get("event_id") or "unknown") for item in evidence))
    return {
        "total_rows": len(evidence),
        "num_events": len(rows_per_event),
        "rows_per_event": rows_per_event,
        "source_distribution": dict(Counter(str(item.get("source") or "unknown") for item in evidence)),
        "output_path": str(output_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def annotation_guideline() -> str:
    return """# PubEvent-SOA Annotation Guideline

This sheet is for human annotation only. It must not be treated as gold data until annotators review and complete the required fields.

## Task

For each evidence row, decide whether the text supports an evidence-grounded stakeholder opinion attribution tuple:

`<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>`

## Fields To Annotate

- `is_relevant`: evidence-level screening only. Use `yes`, `no`, `duplicate`, or `irrelevant`.
- `annotated_stakeholder`: the actor whose opinion, stance, concern, response, or action is expressed. Examples: residents, property owners, government departments, enterprises, developers, platforms, media, experts.
- `annotated_opinion`: the concrete opinion, demand, concern, response, explanation, action, or position expressed by the stakeholder.
- `annotated_sentiment`: use `positive`, `negative`, `neutral`, `mixed`, or `unknown`.
- `annotated_rationale`: the short evidence-grounded reason for the annotation. Quote or summarize the part of the evidence that supports the tuple.
- `support_label`: tuple-level support only. Choose one of `supported`, `partially_supported`, `unsupported`, `insufficient_evidence`.
- `event_chain_step`: choose one of `trigger`, `diffusion`, `conflict`, `response`, `resolution`, `follow_up`.
- `event_chain_order`: integer order of this evidence in the event chain when applicable.
- `notes`: optional annotation comments, uncertainty, duplicate notes, or exclusion reasons.

## Concepts

Stakeholder means the public actor that holds or expresses the opinion or action. Do not use a vague stakeholder if the text clearly names a more specific actor.

Opinion means the stakeholder's claim, attitude, concern, demand, explanation, response, or action regarding the event.

Sentiment describes the polarity or stance of the opinion. Use `neutral` for factual official notices or procedural updates without clear support or opposition.

Rationale is the evidence-grounded justification for your label. It should be traceable to the text in the same row.

Support label describes how well this evidence supports the annotated tuple:

- `supported`: the row clearly supports the stakeholder, opinion, sentiment, and rationale.
- `partially_supported`: the row supports part of the tuple but lacks some detail.
- `unsupported`: the row is related but does not support the proposed tuple.
- `insufficient_evidence`: the row or cited evidence is related, but does not contain enough information to make the final tuple.

Event chain step describes the role of the evidence in the event development:

- `trigger`: initial cause or announcement.
- `diffusion`: wider reporting, sharing, or spread.
- `conflict`: explicit dispute, complaint, disagreement, or controversy.
- `response`: official, organizational, or stakeholder response.
- `resolution`: handling result, correction, settlement, or decision.
- `follow_up`: later update, monitoring, secondary discussion, or longer-term effect.

## Irrelevant Evidence

Use `is_relevant=irrelevant` when evidence is unrelated to the configured event, only explains a general policy, is a generic SEO article, lacks a concrete event or stakeholder, or contains no usable stakeholder opinion/action. Use `is_relevant=duplicate` when it repeats an already captured item without new stakeholder, source, timeline, or factual detail. Do not use `irrelevant` as a final tuple-level `support_label`.

## Gold Review Sheets

Use `gold_tuple_review_sheet.csv` and `gold_chain_review_sheet.csv` for final gold review. LLM and system candidates are preannotation only.

`human_decision` values:

- `accept`: candidate is correct as written.
- `edit`: candidate is usable after editing `gold_*` fields.
- `reject`: candidate must not enter gold.
- `add_new`: human adds a missing tuple.
- `merge`: candidate is merged with another candidate; export the merged final `gold_*` fields once.

Only final human-confirmed rows are exported. Unreviewed rows and `reject` rows are excluded.

## Special Cases

Official responses should usually be annotated as `政府部门` or the specific agency if they directly respond, announce, explain, investigate, or report handling results.

Media reports should be annotated for the stakeholder opinion they report. If the article only summarizes facts without a stakeholder view, mark the stakeholder as media only when the media itself makes an evaluative claim.

Media paraphrase should be attributed to the stakeholder being paraphrased, not to the media outlet, unless the media outlet itself makes the claim.

Generic policy explanations should usually be `is_relevant=irrelevant` unless they directly describe the event, affected stakeholders, or an official handling result.

Duplicate reports may be marked relevant only when they add a distinct stakeholder, source, timeline step, or detail. Otherwise mark them as duplicate in `notes`.
"""


if __name__ == "__main__":
    raise SystemExit(main())
