from argparse import Namespace
import json
from pathlib import Path
import importlib.util


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "filter_evidence_quality.py"
SPEC = importlib.util.spec_from_file_location("filter_evidence_quality_script", SCRIPT_PATH)
filter_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(filter_script)


def test_filter_evidence_quality_writes_filtered_copy_and_report(tmp_path):
    evidence = tmp_path / "evidence.jsonl"
    events = tmp_path / "events.jsonl"
    output = tmp_path / "evidence_filtered.jsonl"
    report_json = tmp_path / "report.json"
    report_csv = tmp_path / "report.csv"
    classification_csv = tmp_path / "classification.csv"
    recollection_plan = tmp_path / "recollection_plan.jsonl"
    original = "\n".join(
        [
            json.dumps(
                {
                    "evidence_id": "e1",
                    "event_id": "E1",
                    "source": "official",
                    "platform": "gov.cn",
                    "publish_time": "2025-01-01",
                    "url": "https://city.gov.cn/a",
                    "text": "某市居民反映旧城改造补偿争议，街道办回应并说明安置整改推进方案。" * 3,
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "evidence_id": "e2",
                    "event_id": "E1",
                    "source": "news",
                    "platform": "66law.cn",
                    "publish_time": "",
                    "url": "https://66law.cn/a",
                    "text": "什么是补偿标准是什么 律师告诉你 法律依据 全解析",
                },
                ensure_ascii=False,
            ),
        ]
    ) + "\n"
    evidence.write_text(original, encoding="utf-8")
    events.write_text(
        '{"event_id":"E1","event_name":"旧城改造补偿争议","seed_keywords":["旧城改造","补偿争议"]}\n',
        encoding="utf-8",
    )

    code = filter_script.filter_evidence(
        Namespace(
            input=str(evidence),
            events=str(events),
            output=str(output),
            report_json=str(report_json),
            report_csv=str(report_csv),
            classification_csv=str(classification_csv),
            recollection_plan=str(recollection_plan),
            max_per_event=1,
            min_per_event=1,
            max_per_domain=1,
            quality_threshold=0.45,
            max_domain_share=0.35,
        )
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert code == 0
    assert evidence.read_text(encoding="utf-8") == original
    assert rows[0]["evidence_id"] == "e1"
    assert rows[0]["selected_for_annotation"] is True
    assert "quality_score" in rows[0]
    assert report["total_input"] == 2
    assert report["total_output"] == 1
    assert report_csv.exists()
    assert classification_csv.exists()
    assert recollection_plan.exists()


def test_source_classification_rules():
    assert filter_script.classify_source_type("liuyan.people.com.cn", "", "", "news")[0] == "public_interaction"
    assert filter_script.classify_source_type("example.gov.cn", "", "", "news")[0] == "official"
    assert filter_script.classify_source_type("m.thepaper.cn", "", "", "news")[0] == "news"
    assert filter_script.classify_source_type("city-bbs.example.com", "", "", "news")[0] == "forum"


def test_source_type_mapping():
    assert filter_script.map_source_type("official", "example.gov.cn", "", "") == "official"
    assert filter_script.map_source_type("news", "thepaper.cn", "", "") == "mainstream_news"
    assert filter_script.map_source_type("public_social", "weibo.com", "", "") == "social_media"
    assert filter_script.map_source_type("forum", "bbs.example.com", "", "") == "forum"
    assert filter_script.map_source_type("public_interaction", "liuyan.people.com.cn", "", "") == "public_interaction"
    assert filter_script.map_source_type("public_web", "gov.cn", "", "") == "official"
    assert filter_script.map_source_type("public_web", "thepaper.cn", "", "") == "mainstream_news"
    assert filter_script.map_source_type("public_web", "example.com", "头条", "") == "social_media"
    assert filter_script.map_source_type("public_web", "example.com", "新浪投诉", "") == "social_media"
    assert filter_script.map_source_type("public_web", "unknown.com", "", "") == "public_web"
