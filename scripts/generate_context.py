#!/usr/bin/env python3
"""
Update claudechat.md with fresh dynamic content.

Patches two sections:
  1. File line counts — (NNN lines) annotations in FILE STRUCTURE
  2. Last 15 Git Commits — git log block in CURRENT STATE

Everything else (SCREENS, BRAND, DATA MODEL, BUSINESS LOGIC, etc.) is left
unchanged — those sections only need updating when major features land, which
warrants a full /claudeupdate run.

Usage:
    python3 scripts/generate_context.py
    SKIP_CONTEXT=1 git commit   # bypass the pre-commit hook
"""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTEXT_FILE = ROOT / "claudechat.md"


def get_git_log() -> str:
    result = subprocess.run(
        ["git", "log", "--oneline", "-15"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.stdout.strip()


def update_git_log(content: str) -> str:
    """Replace the git log block under '### Last 15 Git Commits'."""
    git_log = get_git_log()
    if not git_log:
        return content
    pattern = re.compile(
        r"(### Last 15 Git Commits\n```\n)(.*?)(\n```)",
        re.DOTALL,
    )
    return pattern.sub(rf"\g<1>{git_log}\g<3>", content)


def collect_line_counts() -> dict[str, int]:
    """
    Walk src/quayside/ and tests/ for .py, .html, .css files.
    Returns {basename: line_count}. Basenames are unique in this project.
    """
    counts: dict[str, int] = {}
    search_roots = [ROOT / "src" / "quayside", ROOT / "tests"]
    extensions = {".py", ".html", ".css"}

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob("*"):
            if path.suffix in extensions and path.is_file():
                try:
                    line_count = len(path.read_text(encoding="utf-8").splitlines())
                    counts[path.name] = line_count
                except (OSError, UnicodeDecodeError):
                    pass
    return counts


def update_file_line_counts(content: str) -> tuple[str, int]:
    """
    Replace (NNN lines) annotations in the content for known source files.
    Returns (updated_content, number_of_replacements).
    """
    counts = collect_line_counts()
    replacements = 0

    for name, count in counts.items():
        escaped = re.escape(name)
        # Matches: filename.ext<non-(chars>(<digits> lines)
        # e.g. "run.py                    # Pipeline orchestrator (460 lines)"
        # e.g. "`landing.html` (1494 lines)"
        pattern = re.compile(rf"({escaped}[^(\n]+\()\d+( lines\))")
        new_content, n = pattern.subn(rf"\g<1>{count}\g<2>", content)
        if n:
            content = new_content
            replacements += n

    return content, replacements


def main() -> None:
    if os.environ.get("SKIP_CONTEXT", "0") == "1":
        return

    if not CONTEXT_FILE.exists():
        print(f"claudechat.md not found at {CONTEXT_FILE}, skipping")
        return

    original = CONTEXT_FILE.read_text(encoding="utf-8")
    content = original

    content = update_git_log(content)
    content, count_updates = update_file_line_counts(content)

    if content == original:
        print("claudechat.md already up to date")
        return

    CONTEXT_FILE.write_text(content, encoding="utf-8")
    print(f"claudechat.md updated (git log + {count_updates} line count(s) refreshed)")


if __name__ == "__main__":
    main()
