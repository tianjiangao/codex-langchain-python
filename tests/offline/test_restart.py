import json
import os
import subprocess
import sys
from pathlib import Path


def test_two_process_checkpoint_new_thread_replay_without_completed_tool_repeat(tmp_path):
    root = Path(__file__).resolve().parents[2]
    helper = root / "tests/helpers/restart_worker.py"
    for mode in ["prepare", "resume"]:
        # Use installed package, with only synthetic test modules explicitly on the child path.
        subprocess.run(
            [
                sys.executable,
                "-c",
                'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_path(sys.argv.pop(1),run_name="__main__")',
                str(root),
                str(helper),
                mode,
                str(tmp_path),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
    first = json.loads((tmp_path / "prepare_pid.json").read_text())
    second = json.loads((tmp_path / "resume_pid.json").read_text())
    assert first["pid"] != second["pid"] and first["pid"] != os.getpid()
    assert (tmp_path / "tool_runs.txt").read_text().splitlines() == ["OFFLINE_EXECUTION"]
