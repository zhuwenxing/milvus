"""Check coverage selection against real diff and profile boundary conditions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report_e2e_server_coverage import go_module_roots, go_source_path
from select_e2e_server_cases import changed_lines, select_cases


class E2EServerCoverageSelectionTest(unittest.TestCase):
    def test_module_versions_map_to_checkout_paths(self):
        modules = go_module_roots()
        for import_path, expected in [
            (
                "github.com/milvus-io/milvus/pkg/v3/util/merr/errors.go",
                "pkg/util/merr/errors.go",
            ),
            (
                "github.com/milvus-io/milvus/client/v3/column/array.go",
                "client/column/array.go",
            ),
            (
                "github.com/milvus-io/milvus/internal/proxy/task.go",
                "internal/proxy/task.go",
            ),
        ]:
            with self.subTest(import_path=import_path):
                self.assertEqual(go_source_path(import_path, modules), expected)

    def test_diff_counts_only_added_lines_in_new_revision(self):
        diff = """diff --git a/internal/proxy/task.go b/internal/proxy/task.go
--- a/internal/proxy/task.go
+++ b/internal/proxy/task.go
@@ -10,2 +10,3 @@
-old
+new
+extra
 context
@@ -30 +31,0 @@
-removed
diff --git a/internal/core/src/query/Search.cpp b/internal/core/src/query/Search.cpp
--- /dev/null
+++ b/internal/core/src/query/Search.cpp
@@ -0,0 +1,2 @@
+first
+second
"""
        self.assertEqual(
            changed_lines(diff),
            {
                "internal/proxy/task.go": {10, 11},
                "internal/core/src/query/Search.cpp": {1, 2},
            },
        )

    def test_selects_cases_that_cover_changed_go_and_cpp_lines(self):
        changes = {
            "internal/proxy/task.go": {10, 11},
            "internal/core/src/query/Search.cpp": {20},
        }
        block_10 = {"start": [10, 1], "end": [11, 1]}
        block_11 = {"start": [11, 1], "end": [12, 1]}
        profiles = [
            {
                "case_id": "insert",
                "go": {
                    "internal/proxy/task.go": {
                        "executable_blocks": [block_10, block_11],
                        "covered_blocks": [block_10],
                    }
                },
                "cpp": {
                    "internal/core/src/query/Search.cpp": {
                        "executable_lines": [[20, 20]],
                        "covered_lines": [[20, 20]],
                    }
                },
            },
            {
                "case_id": "search",
                "go": {
                    "internal/proxy/task.go": {
                        "executable_blocks": [block_10, block_11],
                        "covered_blocks": [block_11],
                    }
                },
                "cpp": {
                    "internal/core/src/query/Search.cpp": {
                        "executable_lines": [[20, 20]],
                        "covered_lines": [],
                    }
                },
            },
        ]
        result = select_cases(changes, profiles)
        self.assertEqual(
            [item["case_id"] for item in result["selected"]], ["insert", "search"]
        )
        self.assertEqual(result["covered_changed_lines"], 3)
        self.assertEqual(result["uncovered_executable_lines"], [])


if __name__ == "__main__":
    unittest.main()
