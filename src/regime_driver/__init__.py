"""regime_driver — L1 institutional-process robot.

Compiles the workflow-regime institutional process into a state machine and
drives a clean opencode worker (L2) to complete work, advancing through
reviewer (L0) judgements gated by a deterministic gate.

See the architecture doc: docs/ARCHITECTURE-regime-driver.md
"""

__version__ = "0.2.0"