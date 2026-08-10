"""Strict document-local M2 Effect candidate extraction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from episoa.ea.schema import (
    DocumentRecord,
    EffectCandidateRecord,
    EffectExtractionResponse,
    EvidenceLink,
    ExtractionAttemptRecord,
)
from episoa.llm.client import json_schema_response_format

EFFECT_EXTRACTION_SYSTEM_PROMPT = """你是EpiSOA-EA的文档级Effect抽取器。
每次请求只包含一篇文档的一个文本块。只能依据当前document_id的normalized_text抽取，禁止利用、补全或引用其他文档正文。

每条Effect必须原子化，只能包含一个有原文证据的EffectHolder surface及类别、一个Effect Type、一个Effect Value、一个Target和一个Effect Stage。
只允许stance、emotion、action三种Effect Type，并遵守以下硬约束：
1. 无立场表达时，不创建stance Effect。
2. 无情绪表达时，不创建emotion Effect。
3. uncertain仅表示确有立场或情绪表达但类别无法可靠判断，不能表示字段缺失。
4. emotion=neutral仅用于确有情绪状态但无明显正负极性；纯事实陈述不能创建Emotion Effect。

expression_present必须为true。Emotion还必须令emotion_state_present为true；其他Effect不得输出emotion_state_present。
每条Effect必须为holder_surface、stakeholder_category、effect_type、effect_value、target、effect_stage各提供且只提供一个Evidence Span。holder_surface必须是原文中明确出现的主体称谓，不得编造。偏移量相对于当前chunk_text，且span_text必须能精确回读。
不要输出Explanation Candidate、Relation Judgment、AttributionHolder、Claim或Canonical ID。"""

EFFECT_EXTRACTION_RESPONSE_FORMAT = json_schema_response_format(
    "ea_effect_extraction",
    EffectExtractionResponse.model_json_schema(),
)


class EffectExtractionClient(Protocol):
    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict | None = None,
    ): ...


@dataclass(frozen=True)
class DocumentChunk:
    document_id: str
    chunk_id: str
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class M2ExtractionResult:
    candidates: tuple[EffectCandidateRecord, ...]
    evidence_links: tuple[EvidenceLink, ...]
    attempts: tuple[ExtractionAttemptRecord, ...]


def chunk_document(
    document: DocumentRecord, *, chunk_size_chars: int, chunk_overlap_chars: int
) -> list[DocumentChunk]:
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be positive")
    if chunk_overlap_chars < 0 or chunk_overlap_chars >= chunk_size_chars:
        raise ValueError("chunk_overlap_chars must be within [0, chunk_size_chars)")
    text = document.normalized_text
    chunks: list[DocumentChunk] = []
    start = 0
    index = 1
    while start < len(text):
        end = min(len(text), start + chunk_size_chars)
        chunks.append(
            DocumentChunk(
                document_id=document.document_id,
                chunk_id=f"{document.document_id}-CH{index:04d}",
                char_start=start,
                char_end=end,
                text=text[start:end],
            )
        )
        if end == len(text):
            break
        start = end - chunk_overlap_chars
        index += 1
    return chunks


def extract_effect_candidates(
    documents: list[DocumentRecord],
    llm_client: EffectExtractionClient,
    *,
    chunk_size_chars: int = 6000,
    chunk_overlap_chars: int = 300,
    schema_retries: int = 1,
) -> M2ExtractionResult:
    if schema_retries < 0:
        raise ValueError("schema_retries must be non-negative")

    candidates: dict[str, EffectCandidateRecord] = {}
    evidence_links: dict[str, EvidenceLink] = {}
    attempts: list[ExtractionAttemptRecord] = []

    for document in documents:
        for chunk in chunk_document(
            document,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        ):
            parsed, chunk_attempts = _extract_chunk(
                document,
                chunk,
                llm_client,
                schema_retries=schema_retries,
            )
            attempts.extend(chunk_attempts)
            for extracted in parsed.effects:
                candidate_id = _stable_id(
                    "EF",
                    (
                        document.document_id,
                        extracted.holder_surface,
                        extracted.stakeholder_category,
                        extracted.effect_type,
                        extracted.effect_value,
                        extracted.target,
                        extracted.effect_stage,
                        extracted.effect_surface,
                    ),
                )
                candidate = EffectCandidateRecord(
                    effect_id=candidate_id,
                    event_id=document.event_id,
                    document_id=document.document_id,
                    reporting_source_id=document.reporting_source_id,
                    primary_source_id=document.primary_source_id,
                    derivation_type=document.derivation_type,
                    stakeholder_category=extracted.stakeholder_category,
                    holder_surface=extracted.holder_surface,
                    holder_role=extracted.holder_role,
                    effect_type=extracted.effect_type,
                    effect_surface=extracted.effect_surface,
                    effect_value=extracted.effect_value,
                    target=extracted.target,
                    effect_stage=extracted.effect_stage,
                )
                candidates[candidate_id] = candidate

                evidence_id = _stable_id(
                    "EV", (document.document_id, chunk.char_start, chunk.char_end)
                )
                for span in extracted.evidence_spans:
                    absolute_start = chunk.char_start + span.char_start
                    absolute_end = chunk.char_start + span.char_end
                    span_id = _stable_id(
                        "SP",
                        (
                            document.document_id,
                            absolute_start,
                            absolute_end,
                            span.span_text,
                        ),
                    )
                    link_id = _stable_id(
                        "EL", (candidate_id, span.support_field, span_id)
                    )
                    evidence_links[link_id] = EvidenceLink(
                        evidence_link_id=link_id,
                        target_type="effect",
                        target_id=candidate_id,
                        document_id=document.document_id,
                        evidence_id=evidence_id,
                        span_id=span_id,
                        char_start=absolute_start,
                        char_end=absolute_end,
                        span_text=span.span_text,
                        support_field=span.support_field,
                        support_label="supports",
                    )

    return M2ExtractionResult(
        tuple(candidates.values()),
        tuple(evidence_links.values()),
        tuple(attempts),
    )


def _extract_chunk(
    document: DocumentRecord,
    chunk: DocumentChunk,
    llm_client: EffectExtractionClient,
    *,
    schema_retries: int,
) -> tuple[EffectExtractionResponse, list[ExtractionAttemptRecord]]:
    attempts: list[ExtractionAttemptRecord] = []
    last_error = ""
    base_payload = {
        "document_id": document.document_id,
        "chunk_id": chunk.chunk_id,
        "chunk_char_start": chunk.char_start,
        "chunk_char_end": chunk.char_end,
        "chunk_text": chunk.text,
    }
    for attempt_number in range(1, schema_retries + 2):
        prompt_payload = dict(base_payload)
        if last_error:
            prompt_payload["previous_validation_error"] = last_error
            prompt_payload["instruction"] = (
                "修正输出，使其严格符合Schema和Evidence Span回读约束。"
            )
        response = llm_client.chat(
            system_prompt=EFFECT_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
            response_format=EFFECT_EXTRACTION_RESPONSE_FORMAT,
        )
        raw_response = str(getattr(response, "content", "") or "")
        response_id = str(getattr(response, "response_id", "") or "")
        try:
            parsed = EffectExtractionResponse.model_validate(json.loads(raw_response))
            _validate_chunk_response(parsed, chunk)
            attempts.append(
                _attempt_record(
                    document,
                    chunk,
                    attempt_number,
                    response_id,
                    raw_response,
                    valid=True,
                )
            )
            return parsed, attempts
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = _compact_error(exc)
            attempts.append(
                _attempt_record(
                    document,
                    chunk,
                    attempt_number,
                    response_id,
                    raw_response,
                    valid=False,
                    parse_error=last_error,
                )
            )
    raise ValueError(
        f"{document.document_id}/{chunk.chunk_id}: invalid Effect extraction "
        f"after {schema_retries + 1} deterministic attempts: {last_error}"
    )


def _validate_chunk_response(
    response: EffectExtractionResponse, chunk: DocumentChunk
) -> None:
    for effect in response.effects:
        if effect.holder_surface not in chunk.text:
            raise ValueError("holder_surface is not present in the current chunk")
        if effect.effect_surface not in chunk.text:
            raise ValueError("effect_surface is not present in the current chunk")
        for span in effect.evidence_spans:
            if span.char_end > len(chunk.text):
                raise ValueError("Evidence Span exceeds current chunk")
            if chunk.text[span.char_start : span.char_end] != span.span_text:
                raise ValueError(
                    f"Evidence Span is not exactly readable for {span.support_field}"
                )


def _attempt_record(
    document: DocumentRecord,
    chunk: DocumentChunk,
    attempt_number: int,
    response_id: str,
    raw_response: str,
    *,
    valid: bool,
    parse_error: str | None = None,
) -> ExtractionAttemptRecord:
    return ExtractionAttemptRecord(
        attempt_id=_stable_id(
            "ATT", (document.document_id, chunk.chunk_id, attempt_number)
        ),
        document_id=document.document_id,
        chunk_id=chunk.chunk_id,
        chunk_start=chunk.char_start,
        chunk_end=chunk.char_end,
        attempt_number=attempt_number,
        response_id=response_id,
        raw_response=raw_response,
        valid=valid,
        parse_error=parse_error,
    )


def _stable_id(prefix: str, value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _compact_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:1000]
