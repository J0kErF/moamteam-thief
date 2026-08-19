"""Build the two submission repositories (book ch.9, rule #49).

Exports the git-TRACKED tree (secrets and logs can never leak — they are not
tracked) into two sibling repos, each declaring its role and cross-linking the
other, then commits and tags ``v1.0-submission`` in each.

    uv run python scripts/split_repos.py [--tag v1.0-submission]

The architecture is symmetric (the book's own reference ships both roles in one
codebase): each repository carries the full role-parameterized engine and is
DOCUMENTED and configured as its agent; at league time each runs as its own
process on its own machine (rule #1).
"""

import argparse
import os
import shutil
import stat
import subprocess
from pathlib import Path


def _force_remove(func, path, _exc_info):
    """Windows: git object files are read-only — make writable, retry."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

ROOT = Path(__file__).resolve().parents[1]
REPOS = {
    "police": {
        "dir": ROOT.parent / "moamteam-police",
        "title": "moamteam — POLICE agent",
        "remote": "https://github.com/J0kErF/moamteam-police",
        "sibling": "https://github.com/J0kErF/moamteam-thief",
        "run": "uv run python -m moamteam peer --role police --gui",
    },
    "thief": {
        "dir": ROOT.parent / "moamteam-thief",
        "title": "moamteam — THIEF agent",
        "remote": "https://github.com/J0kErF/moamteam-thief",
        "sibling": "https://github.com/J0kErF/moamteam-police",
        "run": "uv run python -m moamteam peer --role thief --gui",
    },
}


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def tracked_files() -> list[str]:
    return git(ROOT, "ls-files").splitlines()


def role_banner(role: str, spec: dict) -> str:
    return (
        f"# {spec['title']}\n\n"
        f"> **This repository is the {role.upper()} agent** of moamteam's final\n"
        f"> project (rule #49: one repository per agent). The engine is symmetric\n"
        f"> and role-parameterized — run this side with:\n"
        f">\n"
        f"> ```powershell\n"
        f"> uv sync\n"
        f"> {spec['run']}\n"
        f"> ```\n"
        f">\n"
        f"> Sibling repository ({'thief' if role == 'police' else 'police'} agent):\n"
        f"> <{spec['sibling']}>\n\n"
    )


def build_repo(role: str, spec: dict, tag: str) -> None:
    target: Path = spec["dir"]
    if target.exists():
        shutil.rmtree(target, onerror=_force_remove)
    target.mkdir(parents=True)

    for relative in tracked_files():
        source = ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    # Role banner replaces the top title; the full academic report follows.
    readme = target / "README.md"
    original = readme.read_text(encoding="utf-8")
    body = original.split("\n", 1)[1] if original.startswith("# ") else original
    readme.write_text(role_banner(role, spec) + body.lstrip("\n"), encoding="utf-8")

    git(target, "init", "-q")
    git(target, "add", "-A")
    staged = git(target, "diff", "--cached", "--name-only")
    forbidden = [line for line in staged.splitlines()
                 if "local.toml" in line or "credentials" in line
                 or line.endswith("token.json") or line == ".env"]
    if forbidden:
        raise SystemExit(f"SECRETS STAGED in {target}: {forbidden}")
    git(target, "commit", "-q", "-m",
        f"moamteam {role} agent — final project submission\n\n"
        f"Distributed Cops-and-Robbers over P2P (FastMCP), commit-reveal\n"
        f"cryptography, scent/belief uncertainty, escape-area strategy.\n"
        f"See README.md for the academic report.")
    git(target, "tag", "-a", tag, "-m",
        f"Final submission: Police-Thief P2P, group moamteam ({role} agent)")
    git(target, "remote", "add", "origin", spec["remote"])
    print(f"{role}: {target}  ({len(staged.splitlines())} files, tag {tag}, "
          f"remote {spec['remote']})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v1.0-submission")
    args = parser.parse_args()
    for role, spec in REPOS.items():
        build_repo(role, spec, args.tag)
    print("\nNext: create the GitHub repos, add remotes and push (incl. --tags),\n"
          "then share both with rmisegal@gmail.com or make them public (rule #39\n"
          "still applies: never push secrets).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
