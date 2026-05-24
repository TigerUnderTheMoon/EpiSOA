import pytest

from scripts.build_benchmark_tasks import build_event_split


def test_benchmark_split_comes_from_stage1_registry():
    split, policy = build_event_split(
        [
            {"event_id": "E1", "split": "train", "held_out": False},
            {"event_id": "E2", "split": "dev", "held_out": False},
            {"event_id": "E3", "split": "test", "held_out": True},
        ],
        train_ratio=0.8,
        dev_ratio=0.1,
        seed=42,
    )

    assert split == {"train": ["E1"], "dev": ["E2"], "test": ["E3"]}
    assert policy["strategy"] == "event_registry"


def test_benchmark_rejects_unheldout_test_event():
    with pytest.raises(ValueError, match="held_out=true"):
        build_event_split(
            [{"event_id": "E1", "split": "test", "held_out": False}],
            train_ratio=0.8,
            dev_ratio=0.1,
            seed=42,
        )
