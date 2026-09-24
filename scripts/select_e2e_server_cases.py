"""Recommend measured Python E2E cases for Go and C++ lines changed in a PR."""

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff):
    """Return added line numbers in the new revision of a zero-context diff."""
    changed = defaultdict(set)
    path = None
    new_line = None
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
            new_line = None
        elif raw.startswith("+++ /dev/null"):
            path = None
        elif raw.startswith("@@ "):
            match = HUNK.match(raw)
            if match is None:
                raise ValueError(f"invalid diff hunk: {raw}")
            new_line = int(match.group(1))
        elif path is not None and new_line is not None:
            if raw.startswith("+"):
                changed[path].add(new_line)
                new_line += 1
            elif raw.startswith(" "):
                new_line += 1
    return {path: lines for path, lines in changed.items() if lines}


def in_ranges(line, ranges):
    return any(start <= line <= end for start, end in ranges)


def in_go_blocks(line, blocks):
    return any(
        block["start"][0] <= line
        and (
            line < block["end"][0] or (line == block["end"][0] and block["end"][1] > 1)
        )
        for block in blocks
    )


def select_cases(changes, profiles):
    """Rank cases by the number of previously unrepresented changed lines hit."""
    executable = set()
    hits_by_case = {}
    for profile in profiles:
        case_id = profile["case_id"]
        if case_id in hits_by_case:
            raise ValueError(f"duplicate case profile: {case_id}")
        hits = set()
        for path, lines in changes.items():
            if path in profile["go"]:
                entry = profile["go"][path]
                executable.update(
                    (path, line)
                    for line in lines
                    if in_go_blocks(line, entry.get("executable_blocks", []))
                )
                hits.update(
                    (path, line)
                    for line in lines
                    if in_go_blocks(line, entry["covered_blocks"])
                )
            if path in profile["cpp"]:
                entry = profile["cpp"][path]
                executable.update(
                    (path, line)
                    for line in lines
                    if in_ranges(line, entry.get("executable_lines", []))
                )
                hits.update(
                    (path, line)
                    for line in lines
                    if in_ranges(line, entry["covered_lines"])
                )
        hits_by_case[case_id] = hits

    remaining = set().union(*hits_by_case.values()) if hits_by_case else set()
    selected = []
    while remaining:
        case_id, added = max(
            ((case_id, hits & remaining) for case_id, hits in hits_by_case.items()),
            key=lambda item: (len(item[1]), item[0]),
        )
        if not added:
            break
        selected.append(
            {
                "case_id": case_id,
                "new_lines": len(added),
                "covered_changed_lines": len(hits_by_case[case_id]),
                "lines": [list(item) for item in sorted(added)],
            }
        )
        remaining.difference_update(added)

    changed = {(path, line) for path, lines in changes.items() for line in lines}
    covered = set().union(*hits_by_case.values()) if hits_by_case else set()
    return {
        "selected": selected,
        "covered_changed_lines": len(covered),
        "uncovered_executable_lines": [
            list(item) for item in sorted(executable - covered)
        ],
        "unmeasured_or_nonexecutable_lines": [
            list(item) for item in sorted(changed - executable)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Git base branch or commit")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Write JSON recommendation here")
    args = parser.parse_args()

    head = subprocess.check_output(["git", "rev-parse", args.head], text=True).strip()
    diff = subprocess.check_output(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--no-renames",
            "--unified=0",
            f"{args.base}...{head}",
        ],
        text=True,
    )
    changes = {
        path: lines
        for path, lines in changed_lines(diff).items()
        if path.endswith((".go", ".cpp", ".cc", ".c", ".h", ".hpp"))
    }
    paths = sorted(args.reports.rglob("coverage-map.json"))
    if not paths:
        parser.error(f"no coverage-map.json files under {args.reports}")
    profiles = [json.loads(path.read_text()) for path in paths]
    for path, profile in zip(paths, profiles):
        if profile.get("server_commit") != head:
            parser.error(
                f"{path}: server commit differs from {head}; rebuild and recapture against this revision"
            )
        if profile.get("test_status") != "succeeded":
            parser.error(
                f"{path}: only successful E2E case profiles can be used for selection"
            )

    result = select_cases(changes, profiles)
    result.update(
        {
            "base": args.base,
            "head": head,
            "measured_cases": len(profiles),
            "changed_lines": sum(map(len, changes.values())),
        }
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
