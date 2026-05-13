"""End-to-end failure-path test against real Modal.

Marked ``@pytest.mark.live``; the default ``pytest`` invocation skips it.
Run with ``pytest --live`` (or ``uv run pytest --live``) to execute. Drives
the sweep through a subprocess so it exercises the same Hydra plumbing
a real user hits.

Verifies that:
- a ``task_function`` that raises returns through Modal's
  ``return_exceptions=True`` channel without crashing the whole sweep
- the launcher maps each exception to ``JobReturn(status=FAILED)`` with
  the original exception attached
- Hydra's sweeper surfaces the original ``RuntimeError`` (one per job)
"""
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.live
def test_e2e_failure_path():
    repo_root = Path(__file__).resolve().parent.parent
    app_path = repo_root / "tests" / "e2e" / "failure_app.py"

    result = subprocess.run(
        [sys.executable, str(app_path), "--multirun", "lr=0.001,0.01"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=300,
    )

    output = result.stdout + result.stderr

    # Launcher submitted both jobs to Modal (full sweep started, not aborted).
    assert "ModalLauncher: launching 2 jobs" in output, output
    # Hydra's basic_sweeper eager-raises on the first FAILED JobReturn it
    # iterates (see hydra/_internal/core_plugins/basic_sweeper.py around line
    # 181 -- `_ = r.return_value`), so only one of the two failures surfaces
    # in stderr even though both jobs ran remotely and both returned
    # JobReturn(FAILED). We just assert at least one is reported.
    assert "Error executing job with overrides" in output, output
    # The deliberate exception type + message is preserved end-to-end --
    # from container -> return_exceptions=True -> _to_job_return ->
    # JobReturn(FAILED) -> sweeper -> stderr.
    assert "RuntimeError: Forced failure for lr=" in output, output
    # And the sweep exits nonzero so CI / scripts catch the failure.
    assert result.returncode != 0
