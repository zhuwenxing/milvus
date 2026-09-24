"""Summarize Go and C++ server coverage captured for one E2E case."""

import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

GO_BLOCK = re.compile(r"^(.+):(\d+)\.(\d+),(\d+)\.(\d+) (\d+) (\d+)$")
GO_PREFIX = "github.com/milvus-io/milvus/"
CPP_PREFIX = "/internal/core/src/"


def compact_ranges(numbers):
    values = sorted(numbers)
    if not values:
        return []
    ranges = []
    start = end = values[0]
    for value in values[1:]:
        if value == end + 1:
            end = value
            continue
        ranges.append([start, end])
        start = end = value
    ranges.append([start, end])
    return ranges


def read_go(profile):
    files = defaultdict(
        lambda: {"covered_statements": 0, "total_statements": 0, "covered_blocks": []}
    )
    for line in profile.read_text().splitlines():
        if line.startswith("mode:"):
            continue
        match = GO_BLOCK.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid Go coverage block: {line}")
        path, start_line, start_col, end_line, end_col, statements, hits = (
            match.groups()
        )
        if not path.startswith(GO_PREFIX):
            continue
        entry = files[path.removeprefix(GO_PREFIX)]
        statement_count = int(statements)
        entry["total_statements"] += statement_count
        if int(hits) > 0:
            entry["covered_statements"] += statement_count
            entry["covered_blocks"].append(
                {
                    "start": [int(start_line), int(start_col)],
                    "end": [int(end_line), int(end_col)],
                }
            )
    return dict(files)


def read_cpp(json_dir):
    files = defaultdict(lambda: {"executable_lines": set(), "covered_lines": set()})
    for profile in json_dir.rglob("*.gcov.json.gz"):
        with gzip.open(profile, "rt") as data:
            payload = json.load(data)
        for source in payload.get("files", []):
            path = source.get("file", "")
            if CPP_PREFIX not in path:
                continue
            entry = files["internal/core/src/" + path.split(CPP_PREFIX, 1)[1]]
            for line in source.get("lines", []):
                number = line.get("line_number", 0)
                if number <= 0:
                    continue
                entry["executable_lines"].add(number)
                if line.get("count", 0) > 0:
                    entry["covered_lines"].add(number)
    return {
        path: {
            "covered_lines": compact_ranges(entry["covered_lines"]),
            "covered_line_count": len(entry["covered_lines"]),
            "executable_line_count": len(entry["executable_lines"]),
        }
        for path, entry in files.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--go-profile", type=Path, required=True)
    parser.add_argument("--cpp-json-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    go_files = read_go(args.go_profile)
    cpp_files = read_cpp(args.cpp_json_dir)
    if not go_files or not cpp_files:
        raise SystemExit("both Go and C++ coverage data are required")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = {"case_id": args.case_id, "go": go_files, "cpp": cpp_files}
    (args.output_dir / "coverage-map.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )

    go_covered = sum(item["covered_statements"] for item in go_files.values())
    go_total = sum(item["total_statements"] for item in go_files.values())
    cpp_covered = sum(item["covered_line_count"] for item in cpp_files.values())
    cpp_total = sum(item["executable_line_count"] for item in cpp_files.values())
    lines = [
        f"# Server coverage for `{args.case_id}`",
        "",
        (
            f"Go: {go_covered}/{go_total} statements ({go_covered / go_total:.1%}); "
            f"C++ Core: {cpp_covered}/{cpp_total} executable lines ({cpp_covered / cpp_total:.1%})."
        ),
        "",
        "Go and C++ percentages use different denominators. The JSON file lists covered Go blocks and C++ lines.",
        "",
        "| Language | Source file | Covered / total |",
        "| --- | --- | ---: |",
    ]
    for path, entry in sorted(go_files.items()):
        if entry["covered_statements"]:
            lines.append(
                f"| Go | `{path}` | {entry['covered_statements']} / {entry['total_statements']} statements |"
            )
    for path, entry in sorted(cpp_files.items()):
        if entry["covered_line_count"]:
            lines.append(
                f"| C++ | `{path}` | {entry['covered_line_count']} / {entry['executable_line_count']} lines |"
            )
    (args.output_dir / "coverage-summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
