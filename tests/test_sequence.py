import time

from app.automation.matching import DetectionHit
from app.automation.sequence import SequenceController
from app.core.models import TargetSpec


def make_hit(target_id: str) -> DetectionHit:
    return DetectionHit(
        target=TargetSpec(id=target_id, name=target_id, target_type="image", value="x.png", threshold=0.8),
        score=0.95,
        x=10,
        y=10,
    )


def test_parallel_mode_returns_all_hits():
    controller = SequenceController()
    controller.update_config("parallel", [], 2.0)
    hits = [make_hit("a"), make_hit("b")]
    decision = controller.choose(hits)
    assert len(decision.hits_to_click) == 2
    assert decision.reset_happened is False


def test_sequence_mode_clicks_only_expected_order():
    controller = SequenceController()
    controller.update_config("sequence", ["a", "b"], 2.0)

    decision_1 = controller.choose([make_hit("a"), make_hit("b")])
    assert len(decision_1.hits_to_click) == 1
    assert decision_1.hits_to_click[0].target.id == "a"

    decision_2 = controller.choose([make_hit("a"), make_hit("b")])
    assert len(decision_2.hits_to_click) == 1
    assert decision_2.hits_to_click[0].target.id == "b"


def test_sequence_mode_resets_when_expected_missing_for_timeout():
    controller = SequenceController()
    controller.update_config("sequence", ["a", "b"], 0.01)
    controller.choose([make_hit("a")])  # progress to expecting "b"
    time.sleep(0.02)
    decision = controller.choose([])  # should reset quickly
    assert decision.reset_happened is True

