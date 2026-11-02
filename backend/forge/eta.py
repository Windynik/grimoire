"""Time estimate for the forge, based on measured model speed."""

from typing import Dict, List, Tuple

from backend.core.ollama_client import CallStats

_ALPHA = 0.5

_BASE_OUTPUT_TOKENS = {
    "backbones": 1200,
    "borderline": 600,
    "explanation": 700,
    "reasons": 500,
}
_THINK_FACTOR = {"low": 1.3, "medium": 2.0, "high": 3.0}


def estimate_output_tokens(kind: str, think: str) -> int:
    """Estimate the output tokens of one model call.

    Args:
        kind: Call kind: backbones, borderline, explanation or reasons.
        think: Think level: low, medium or high.

    Returns:
        The base output tokens for the kind, times the think factor.
    """
    return int(round(_BASE_OUTPUT_TOKENS[kind] * _THINK_FACTOR[think]))


def prompt_tokens(prompt: str) -> int:
    """Estimate the prompt tokens as one token per four characters."""
    return len(prompt) // 4


class EtaEstimator:
    """Estimates the seconds left from planned model calls and measured speed."""

    def __init__(self, prompt_tps: float = 400.0, gen_tps: float = 40.0,
                 engine_seconds: float = 2.0):
        self.prompt_tps = prompt_tps
        self.gen_tps = gen_tps
        self.engine_seconds = engine_seconds
        self.waiting = False
        self._pending: Dict[str, Tuple[int, int]] = {}

    def plan(self, calls: List[Tuple[str, int, int]]) -> None:
        """Replace the plan with calls of (name, prompt tokens, output tokens)."""
        self._pending = {name: (p, o) for name, p, o in calls}

    def update_estimate(self, name: str, prompt_tokens: int, output_tokens: int) -> None:
        """Change the token estimate of a pending call. An unknown name is added."""
        self._pending[name] = (prompt_tokens, output_tokens)

    def observe(self, name: str, stats: CallStats) -> None:
        """Mark a call done and update the speeds by moving average."""
        self._pending.pop(name, None)
        if stats.prompt_tokens > 0 and stats.prompt_seconds > 0:
            observed = stats.prompt_tokens / stats.prompt_seconds
            self.prompt_tps = _ALPHA * observed + (1 - _ALPHA) * self.prompt_tps
        if stats.output_tokens > 0 and stats.output_seconds > 0:
            observed = stats.output_tokens / stats.output_seconds
            self.gen_tps = _ALPHA * observed + (1 - _ALPHA) * self.gen_tps

    def set_waiting(self, waiting: bool) -> None:
        """Set the waiting flag. The session sends no ETA while it is set."""
        self.waiting = waiting

    def remaining_seconds(self, stages_left: int) -> float:
        """Return the seconds left: pending model time plus engine time."""
        model = sum(p / self.prompt_tps + o / self.gen_tps
                    for p, o in self._pending.values())
        return max(0.0, model + self.engine_seconds * stages_left)
