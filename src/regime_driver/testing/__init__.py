"""regime_driver.testing — reusable offline doubles for deterministic debugging.

The mock layer lets state-machine / concurrency / timeout / watchdog logic
run fast and deterministically with NO network and NO LLM, so a debug run never
depends on provider latency or model randomness. See docs/DESIGN-mock.md.
"""

from .mock_client import MockClient, MockRule

__all__ = ["MockClient", "MockRule"]