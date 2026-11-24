"""Parity: every `merge.treeChecks` entry must be a command line in check-ci.sh.

`merge.treeChecks` in .loom/config.json is run by merge-pr.sh against the real
merge tree; the same commands live in check-ci.sh stage bodies for PR CI. They
are kept in step by hand, so this test fails if one copy changes alone
(issue #237). Stdlib only.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def stage_body_lines(script: str) -> set[str]:
    """Stripped, non-comment lines inside `stage_*() { ... }` bodies."""
    lines: set[str] = set()
    in_stage = False
    for raw in script.splitlines():
        if not in_stage:
            in_stage = re.match(r"^stage_\w+\(\)\s*\{\s*$", raw) is not None
            continue
        if raw.rstrip() == "}":
            in_stage = False
            continue
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.add(line)
    return lines


class TreeChecksParity(unittest.TestCase):
    def test_tree_checks_match_check_ci(self):
        config = json.loads((ROOT / ".loom" / "config.json").read_text())
        entries = config.get("merge", {}).get("treeChecks")
        self.assertTrue(
            isinstance(entries, list) and entries,
            "merge.treeChecks missing or empty in .loom/config.json",
        )
        body = stage_body_lines((ROOT / "check-ci.sh").read_text())
        for entry in entries:
            self.assertIn(
                entry.strip(),
                body,
                f"merge.treeChecks entry not found as a command line in a "
                f"check-ci.sh stage body: {entry!r}",
            )


if __name__ == "__main__":
    unittest.main()
