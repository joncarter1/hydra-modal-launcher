"""End-to-end env_passthrough test against real Modal.

Marked ``@pytest.mark.live``; default ``pytest`` invocation skips it. Run
with ``pytest --live`` to execute.

Sets a one-shot ``HML_E2E_TOKEN`` env var on the host with a unique
marker, configures ``env_passthrough: [HML_E2E_TOKEN]``, and asserts the
container reads back the same value. Proves the full host -> ephemeral
``modal.Secret.from_dict`` -> container ``os.environ`` chain.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


@pytest.mark.live
def test_e2e_env_passthrough():
    repo_root = Path(__file__).resolve().parent.parent
    app_path = repo_root / "tests" / "e2e" / "env_passthrough_app.py"

    expected = f"e2e-marker-{uuid.uuid4().hex}"
    env = {**os.environ, "HML_E2E_TOKEN": expected}

    result = subprocess.run(
        # --multirun forces the launcher path; without it Hydra runs in-process
        # locally and the test would tautologically read the host's own env.
        [sys.executable, str(app_path), "--multirun", "+nonce=1"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
        timeout=300,
    )

    output = result.stdout + result.stderr

    # The container saw the host-snapshotted value and logged it back.
    assert f"HML_E2E_TOKEN_ON_CONTAINER={expected}" in output, output
    assert result.returncode == 0
