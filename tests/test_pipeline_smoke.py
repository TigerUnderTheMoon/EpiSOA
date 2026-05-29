from episoa.config import load_config
from episoa.pipeline import ABLATION_SETTINGS, PIPELINE_FLAG_KEYS, paper_status


def test_paper_status_returns_valid_structure() -> None:
    status = paper_status()

    assert "paper_readiness" in status
    assert isinstance(status["paper_readiness"]["data_ready"], bool)
    assert isinstance(status["paper_readiness"]["events_ready"], bool)
    assert "dataset" in status
    assert "num_gold_tuples" in status["dataset"]
    assert status["next_commands"] is not None


def test_main_configs_use_soe_v3_coverage_optimized() -> None:
    paper = load_config("configs/paper.yaml")
    ablation = load_config("configs/ablation.yaml")

    assert paper.ablation["method_version"] == "soe_v3"
    assert paper.ablation["evidence_selector"]["mode"] == "coverage_optimized"
    assert paper.ablation["max_evidence_per_event"] == 16
    assert ablation.ablation["method_version"] == "soe_v3"
    assert ablation.ablation["evidence_selector"]["mode"] == "coverage_optimized"


def test_full_soe_v3_and_without_soe_graph_ablation_flags() -> None:
    full_soe = ABLATION_SETTINGS["full_soe"]
    full_soe_high_recall = ABLATION_SETTINGS["full_soe_high_recall"]
    without_soe_graph = ABLATION_SETTINGS["without_soe_graph"]

    assert full_soe["method_version"] == "soe_v3"
    assert full_soe["selector_mode"] == "coverage_optimized"
    assert full_soe["use_soe_graph"] is True
    assert full_soe["use_stage_attribution"] is True
    assert full_soe["verifier_mode"] == "decomposed"
    assert full_soe_high_recall["method_version"] == "soe_v3"
    assert full_soe_high_recall["max_evidence_per_event"] == 60
    assert without_soe_graph["method_version"] == "soe_v3"
    assert without_soe_graph["selector_mode"] == "coverage_optimized"
    assert without_soe_graph["use_soe_graph"] is False
    assert without_soe_graph["use_stage_attribution"] is False
    assert "use_stage_attribution" in PIPELINE_FLAG_KEYS
    assert "max_evidence_per_event" in PIPELINE_FLAG_KEYS
