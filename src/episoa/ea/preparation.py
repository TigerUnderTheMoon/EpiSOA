"""M2 document normalization, source materialization, and quality gates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from episoa.ea.schema import (
    DocumentRecord,
    RawDocumentInput,
    SourceRecord,
    content_hash,
)


@dataclass(frozen=True)
class PreparedDocuments:
    sources: tuple[SourceRecord, ...]
    documents: tuple[DocumentRecord, ...]


def normalize_document_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    normalized = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)


def prepare_documents(rows: list[RawDocumentInput]) -> PreparedDocuments:
    """Build all records in memory so invalid input never produces partial files."""
    if not rows:
        raise ValueError("raw document input is empty")

    sources: dict[str, SourceRecord] = {}
    documents: list[DocumentRecord] = []
    seen_document_ids: set[str] = set()

    for row in rows:
        if row.document_id in seen_document_ids:
            raise ValueError(f"duplicate document_id: {row.document_id}")
        seen_document_ids.add(row.document_id)
        _register_source(sources, row.reporting_source)
        primary_source = row.primary_source or row.reporting_source
        _register_source(sources, primary_source)

        normalized_text = normalize_document_text(row.body_text)
        if not normalized_text:
            raise ValueError(
                f"{row.document_id}: document body is empty after normalization"
            )
        if row.content_kind != "full_text":
            raise ValueError(
                f"{row.document_id}: summary content cannot be used as full text"
            )
        if row.summary_text:
            normalized_summary = normalize_document_text(row.summary_text)
            if normalized_summary and normalized_summary == normalized_text:
                raise ValueError(
                    f"{row.document_id}: summary is masquerading as body text"
                )

        generated_hash = content_hash(normalized_text)
        if row.declared_content_hash and row.declared_content_hash != generated_hash:
            raise ValueError(
                f"{row.document_id}: declared_content_hash does not match normalized_text"
            )
        documents.append(
            DocumentRecord(
                document_id=row.document_id,
                event_id=row.event_id,
                reporting_source_id=row.reporting_source.source_id,
                primary_source_id=primary_source.source_id,
                parent_document_id=row.parent_document_id,
                publication_time=row.publication_time,
                content_hash=generated_hash,
                derivation_type=row.derivation_type,
                normalized_text=normalized_text,
                url=row.url,
            )
        )

    document_by_id = {row.document_id: row for row in documents}
    for document in documents:
        if not document.parent_document_id:
            continue
        parent = document_by_id.get(document.parent_document_id)
        if parent is None:
            raise ValueError(
                f"{document.document_id}: parent_document_id is not present: "
                f"{document.parent_document_id}"
            )
        if parent.event_id != document.event_id:
            raise ValueError(
                f"{document.document_id}: parent_document_id belongs to another event"
            )

    return PreparedDocuments(
        tuple(sorted(sources.values(), key=lambda row: row.source_id)),
        tuple(documents),
    )


def validate_document_registry(
    sources: list[SourceRecord], documents: list[DocumentRecord]
) -> None:
    source_ids = {row.source_id for row in sources}
    document_by_id = {row.document_id: row for row in documents}
    if len(source_ids) != len(sources):
        raise ValueError("sources.jsonl contains duplicate source_id values")
    if len(document_by_id) != len(documents):
        raise ValueError("documents.jsonl contains duplicate document_id values")
    for document in documents:
        if document.reporting_source_id not in source_ids:
            raise ValueError(f"{document.document_id}: reporting_source_id is dangling")
        if document.primary_source_id not in source_ids:
            raise ValueError(f"{document.document_id}: primary_source_id is dangling")
        if document.parent_document_id:
            parent = document_by_id.get(document.parent_document_id)
            if parent is None:
                raise ValueError(
                    f"{document.document_id}: parent_document_id is dangling"
                )
            if parent.event_id != document.event_id:
                raise ValueError(
                    f"{document.document_id}: parent_document_id belongs to another event"
                )


def _register_source(registry: dict[str, SourceRecord], source: SourceRecord) -> None:
    existing = registry.get(source.source_id)
    if existing is not None and existing != source:
        raise ValueError(f"conflicting source metadata for {source.source_id}")
    registry[source.source_id] = source
