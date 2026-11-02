import pytest

from backend.core.ollama_client import CallStats
from backend.forge.eta import EtaEstimator, estimate_output_tokens, prompt_tokens


def test_remaining_from_plan():
    eta = EtaEstimator()
    eta.plan([("a", 4000, 400), ("b", 800, 200)])
    # a: 4000/400 + 400/40 = 20; b: 800/400 + 200/40 = 7; plus 3 stages * 2 s.
    assert eta.remaining_seconds(3) == pytest.approx(33.0)


def test_observe_updates_speed_and_drops_call():
    eta = EtaEstimator()
    eta.plan([("a", 4000, 400), ("b", 800, 200)])
    eta.observe("a", CallStats(4000, 5.0, 400, 4.0))
    # prompt speed: 0.5 * 800 + 0.5 * 400 = 600; gen speed: 0.5 * 100 + 0.5 * 40 = 70.
    assert eta.remaining_seconds(0) == pytest.approx(800 / 600 + 200 / 70)


def test_observe_skips_zero_rates():
    eta = EtaEstimator()
    eta.plan([("a", 400, 40)])
    eta.update_estimate("b", 800, 80)
    eta.observe("a", CallStats(0, 0.0, 100, 0.0))
    assert eta.remaining_seconds(0) == pytest.approx(800 / 400 + 80 / 40)


def test_update_estimate_and_replan():
    eta = EtaEstimator()
    eta.plan([("a", 400, 40)])
    eta.update_estimate("a", 800, 80)
    assert eta.remaining_seconds(0) == pytest.approx(4.0)
    eta.plan([("c", 400, 40)])
    assert eta.remaining_seconds(0) == pytest.approx(2.0)


def test_engine_only_is_seconds():
    eta = EtaEstimator(engine_seconds=2.0)
    eta.plan([])
    assert eta.remaining_seconds(4) == pytest.approx(8.0)
    assert eta.remaining_seconds(0) == 0.0


def test_waiting_flag():
    eta = EtaEstimator()
    eta.plan([("a", 400, 40)])
    eta.set_waiting(True)
    assert eta.waiting is True
    assert eta.remaining_seconds(0) == pytest.approx(2.0)
    eta.set_waiting(False)
    assert eta.waiting is False


def test_token_helpers():
    assert estimate_output_tokens("backbones", "medium") == 2400
    assert estimate_output_tokens("borderline", "low") == 780
    assert estimate_output_tokens("explanation", "high") == 2100
    assert estimate_output_tokens("reasons", "medium") == 1000
    assert prompt_tokens("x" * 103) == 25
