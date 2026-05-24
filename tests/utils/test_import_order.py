"""Verify that the utils ↔ agent_eval import cycle is broken.

utils.run_tracker must be importable without agent_eval being loaded first.
This test runs in a subprocess so the module cache can't hide ordering bugs.
"""

import subprocess
import sys


def test_utils_imports_without_agent_eval():
    """utils.run_tracker must not require agent_eval to be importable."""
    result = subprocess.run(
        [sys.executable, "-c", "import utils.run_tracker"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_agent_eval_imports_without_utils_run_tracker():
    """agent_eval must be importable independently."""
    result = subprocess.run(
        [sys.executable, "-c", "import agent_eval"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
