"""Allow `python -m regime_driver.cli` (used by background job/task launchers).

Jobs (`infra/jobs.py`) and supervised tasks launch themselves via
``[sys.executable, "-m", "regime_driver.cli", ...]``; this module makes that
entry point work, matching the `regime` console-script behaviour.
"""

from . import app

if __name__ == "__main__":
    app()
