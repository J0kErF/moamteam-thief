"""Step-0: the pre-game computational-fairness declaration (book §5.5, rule #24,
rule #53). Before the first move each peer declares — sealed — its machine spec,
code version, the EXACT git commit hash being played, team identity and game number,
so nobody can later deny what hardware or code fought the match.
"""

import os
import platform
import subprocess
from pathlib import Path

from moamteam import __version__


def git_commit_hash(repo_root: str | Path | None = None) -> str:
    """The commit hash of the code being played (rule #53); 'unknown' outside git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True, text=True, timeout=10, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def machine_spec() -> dict:
    """OS / CPU / GPU-presence snapshot (stdlib only; RAM and GPU details are added
    when the psutil/GPU tooling question is settled — absent keys mean 'undeclared')."""
    return {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count() or 0,
        "python": platform.python_version(),
    }


def build_step0(*, group_id: str, group_name: str, sub_game_number: int,
                llm_model: str, repo_root: str | Path | None = None) -> dict:
    return {
        "type": "step0",
        "group_id": group_id,
        "group_name": group_name,
        "sub_game_number": sub_game_number,
        "llm_model": llm_model,
        "code_version": __version__,
        "git_commit": git_commit_hash(repo_root),
        "hardware": machine_spec(),
    }
