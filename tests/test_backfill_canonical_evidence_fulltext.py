from __future__ import annotations

import pytest

from scripts.backfill_canonical_evidence_fulltext import (
    FetchOutcome,
    backfilled_row,
    deleted_row,
    extract_text,
    find_ids,
    is_binary_response,
    unusable_text_reason,
    validate_output,
)


def test_extract_text_removes_script_and_keeps_body_text():
    html = """
    <html><head><script>alert(1)</script><style>p{}</style></head>
    <body><nav>menu</nav><article><h1>标题</h1><p>第一段正文。</p><p>第二段正文。</p></article></body></html>
    """

    text = extract_text(html)

    assert "alert" not in text
    assert "menu" not in text
    assert "第一段正文。" in text
    assert "第二段正文。" in text


def test_backfilled_row_replaces_text_and_keeps_legacy_text():
    row = {"evidence_id": "ev-1", "event_id": "E001", "url": "https://example.test", "text": "old"}
    outcome = FetchOutcome(status="ok", text="new full text", final_url="https://example.test/a")

    output = backfilled_row(row, outcome, "2026-05-26T00:00:00+00:00")

    assert output["text"] == "new full text"
    assert output["legacy_text"] == "old"
    assert output["fulltext_backfill_status"] == "ok"
    assert output["fulltext_chars"] == len("new full text")
    assert len(output["fulltext_sha256"]) == 64


def test_deleted_row_records_reason_and_legacy_text():
    row = {"evidence_id": "ev-1", "event_id": "E001", "url": "https://example.test", "text": "old"}
    outcome = FetchOutcome(status="deleted", reason="http_status_404", http_status=404)

    output = deleted_row(row, "http_status_404", outcome)

    assert output["evidence_id"] == "ev-1"
    assert output["delete_reason"] == "http_status_404"
    assert output["http_status"] == 404
    assert output["legacy_text"] == "old"


def test_validate_output_rejects_empty_text_and_duplicate_ids():
    with pytest.raises(SystemExit):
        validate_output([{"evidence_id": "ev-1", "text": ""}])

    with pytest.raises(SystemExit):
        validate_output(
            [
                {"evidence_id": "ev-1", "text": "a"},
                {"evidence_id": "ev-1", "text": "b"},
            ]
        )


def test_find_ids_extracts_common_evidence_reference_shapes():
    payload = {
        "evidence_id": "ev-1",
        "evidence_ids": ["ev-2", "ev-3"],
        "nested": {"gold_evidence_ids": ["ev-4"], "selected_evidence_ids": ["ev-5"]},
    }

    assert find_ids(payload) == {"ev-1", "ev-2", "ev-3", "ev-4", "ev-5"}


def test_binary_content_type_is_rejected_before_text_extraction():
    assert is_binary_response(b"%PDF-1.7", "application/pdf")
    assert is_binary_response(b"PK\x03\x04data", "text/html")
    assert not is_binary_response("<html>正文</html>".encode("utf-8"), "text/html; charset=utf-8")


def test_unusable_text_reason_flags_captcha_navigation_and_short_noise():
    assert unusable_text_reason("安全验证 请拖动滑块完成验证", ["小区"]) == "captcha_or_verification"
    assert unusable_text_reason("首页 登录 注册 联系我们 友情链接", ["小区"]) == "navigation_only"
    assert unusable_text_reason("欢迎访问", ["小区"]) == "too_short"
    assert unusable_text_reason("2026年5月26日 居民投诉小区整改进展。", ["小区"]) == ""
