import asyncio
import os
from pathlib import Path

import pytest

from examples.live_suite import run


@pytest.mark.live
def test_real_sdk_langchain_toolnode_structured_and_multiagent():
    directory = Path(os.environ.get("CODEX_LIVE_OUTPUT", "private/live-pytest"))
    result = asyncio.run(run(directory))
    assert result["status"] == "PASS" and result["sdk_tasks"] == 4 and result["unknown_tasks"] == 0
