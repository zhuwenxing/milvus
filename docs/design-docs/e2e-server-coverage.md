# Per-case Go and C++ server coverage from Python E2E tests

## Purpose

Associate existing Python client cases with executed Milvus server code, then
compare that map with changed source lines. The primary output is a reproducible
case-to-source map. Regression recommendations use only successful, measured
cases from the compared server revision.

## Instrumented server

The coverage development branch builds the Go executable with `-cover`, atomic
counters, and all linked Milvus Go modules selected by `-coverpkg`. The
`e2e_coverage` build tag adds a signal handler to the server lifecycle.

C++ Core uses GCC gcov instrumentation with atomic counter updates. The image
contains matching `.gcno` metadata and the build's gcov executable. Dump/reset
functions are exported through the existing C interface and called from Go.

- `SIGUSR2`: clear Go counters and reset C++ counters; acknowledge with
  `/tmp/milvus-e2e-coverage/reset.done`.
- `SIGUSR1`: write Go metadata/counters and dump C++ counters; acknowledge with
  `/tmp/milvus-e2e-coverage/snapshot.done`.

Signals execute in a Go goroutine rather than an asynchronous C signal handler.
Marker files are written through temporary files followed by rename. Go runtime
errors prevent acknowledgement. C++ conversion also requires actual counter
files and successful gcov processing.

This is a dedicated QA build profile. The branch currently enables coverage in
its Makefile builds; it must not be promoted as an ordinary release build.
Default-off release integration and a first-class remote builder coverage option
remain separate integration work.

## Capture protocol

Each case uses a fresh standalone deployment, giving it its own server process,
etcd, MinIO, and data. Once the instance is ready, capture clears old coverage
files and waits for reset acknowledgement. It then executes the existing Python
client case, including setup and teardown, and waits for a snapshot acknowledgement.

Collectors must verify source/image identity, Pod identity and restart count,
test outcome, and the presence of both language profiles. The TC Stage Jenkins
collector additionally checks the running server's detailed git commit and
requires JUnit to contain exactly one passing test. Skipped and xfailed items
are not successful coverage measurements.

The reusable transport and conversion helpers live in
[`run_e2e_server_coverage.py`](../../scripts/run_e2e_server_coverage.py).
Its standalone command uses the developer's Dev CLI deployment environment.
CI deployment adapters can reuse the collection functions with their own
Kubernetes environment; the TC Stage pipeline uses direct Helm deployment in
the existing `chaos-testing` namespace.

The C++ metadata archive is copied from the image before conversion. Raw C++
archives are transferred in bounded chunks to tolerate API proxy connection
limits. Go raw data is converted with `go tool covdata textfmt`.

## Map and recommendations

[`report_e2e_server_coverage.py`](../../scripts/report_e2e_server_coverage.py)
writes a machine-readable map and a Markdown summary. The map includes case ID,
server commit, image, test execution identity, and test status.

- Go: executable and covered blocks, retaining start/end columns, plus statement
  counts. Versioned module paths are resolved through the repository's go.mod
  declarations, so `pkg/v3/...` maps to `pkg/...`.
- C++: executable and covered source line ranges. Untracked generated protobuf
  files are excluded. Source paths must exist in the checkout.

Go statement percentages and C++ line percentages have different denominators
and are reported separately. Raw data is retained for reprocessing.

[`select_e2e_server_cases.py`](../../scripts/select_e2e_server_cases.py)
compares the new side of `base...head` and greedily chooses measured cases that
cover the largest number of remaining changed lines. It separately lists known
uncovered executable lines and unmeasured/nonexecutable lines. It rejects failed
profiles, duplicate case profiles, and profiles from another server commit.

## Boundaries

- The association is a process window, including fixtures and background work;
  it is not request-level causality.
- Hits prove execution, not assertion quality or semantic correctness.
- Current automation targets standalone deployments and non-parameterized cases.
- Rust and uninstrumented third-party libraries are outside the map.
- Pure deletions cannot execute on the new revision and require separate analysis.
- Historical profiles are not remapped across commits. Current recommendations
  explain coverage of a measured revision and do not yet provide pre-execution
  selection from an older baseline.
- The full regression suite remains necessary. An uncovered changed line is a
  test gap candidate; an unknown line is not silently treated as covered.

## Validation

The signal protocol was exercised with a real Python client array insertion and
search case. Go/C++ raw data and mapping were collected from the instrumented
server. Selection checks exercise diff hunk coordinates, Go block endpoints,
module path normalization, and joint Go/C++ case selection. Deployment-specific
validation records remain with the corresponding CI workflow and artifacts.
