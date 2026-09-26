import shutil
import subprocess
from pathlib import Path

import pytest


def test_vip_browser_regressions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for isolated member UI checks")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("vip_browser.test.cjs"))],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
