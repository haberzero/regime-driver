"""Repetition / loop detection (pure domain logic).

Detects whether a cumulative text stream is trapped in a loop: the agent keeps
repeating the same words/phrases (a degenerate "dead loop" the model cannot
break out of on its own). This is a pure, deterministic computation over the
text; no I/O. Used by the monitor thread to decide when to escalate.

Two signals are combined:
  1. n-gram repetition rate: the fraction of n-grams in a recent window that
     appear more than once. High values indicate looping/phrase repetition.
  2. adjacent-block similarity: how much the newest chunk repeats the previous
     chunk (a "copy-paste" echo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_]+"
    r"|[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
    r"|[^\sA-Za-z0-9_\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
)


def tokenize(text: str) -> list[str]:
    """Split text into coarse tokens (words, CJK chars, or punctuation)."""
    return _TOKEN_RE.findall(text or "")


@dataclass
class RepetitionResult:
    """Outcome of a repetition check on a text window."""

    repeated: bool
    ngram_rate: float
    adjacent_similarity: float
    reason: str = ""


@dataclass
class RepetitionDetector:
    """Computes repetition signals over a sliding text window.

    Attr:
        n: n-gram size (default 4).
        window_tokens: max tokens considered in the n-gram rate window.
        rate_threshold: n-gram repetition rate at/above which we flag a loop.
        adjacency_threshold: adjacent-block similarity at/above which we flag.
    """

    n: int = 4
    window_tokens: int = 400
    rate_threshold: float = 0.35
    adjacency_threshold: float = 0.9

    def check(self, text: str) -> RepetitionResult:
        """Return whether the text shows loop-style repetition.

        Only looks at the last `window_tokens` tokens (the recent activity) —
        long history is not relevant to whether the model is currently looping.
        """
        tokens = tokenize(text)
        if len(tokens) < self.n * 2:
            return RepetitionResult(False, 0.0, 0.0, "not enough tokens")

        window = tokens[-self.window_tokens:]
        rate = self._ngram_repetition_rate(window)
        sim = self._adjacent_similarity(window)

        reasons: list[str] = []
        repeated = False
        if rate >= self.rate_threshold:
            repeated = True
            reasons.append(f"ngram_rate={rate:.2f}")
        if sim >= self.adjacency_threshold:
            repeated = True
            reasons.append(f"adjacent_sim={sim:.2f}")
        return RepetitionResult(repeated, rate, sim, "; ".join(reasons))

    def _ngram_repetition_rate(self, tokens: list[str]) -> float:
        """Fraction of n-grams that occur more than once in the window."""
        if len(tokens) < self.n:
            return 0.0
        counts: dict[tuple[str, ...], int] = {}
        for i in range(len(tokens) - self.n + 1):
            gram = tuple(tokens[i : i + self.n])
            counts[gram] = counts.get(gram, 0) + 1
        total = len(tokens) - self.n + 1
        repeated = sum(1 for c in counts.values() if c > 1)
        return repeated / total if total else 0.0

    def _adjacent_similarity(self, tokens: list[str]) -> float:
        """Similarity between the first half and second half of the window."""
        if len(tokens) < 2:
            return 0.0
        half = len(tokens) // 2
        a, b = tokens[:half], tokens[half:]
        if not a or not b:
            return 0.0
        set_a, set_b = set(a), set(b)
        if not set_a or not set_b:
            return 0.0
        inter = len(set_a & set_b)
        return inter / max(len(set_a), len(set_b))