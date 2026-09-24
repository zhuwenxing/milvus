# Python client 用例触发的 Milvus 服务端覆盖率：Go 与 C++ 采集方法

调研日期：2026-09-24。本文调查采集机制和本仓库接入点；同日使用 GCC gcov 实际构建、部署、运行单个 case 的结果见 [PoC 报告](e2e-server-coverage-poc.md)。下文的 Clang 路线仍是可选方案，PoC 使用了仓库已有的 GCC 工具链。

## 结论

Python client 的 `pytest --cov` 只记录 Python 进程中的代码，无法直接回答服务端执行了什么。要得到 **case → server 文件/函数/行** 的映射，需要把服务端编译为覆盖率插桩版本，在隔离的服务端进程或可清零的采集窗口中执行所选 Python case，然后从每个服务端组件收集计数并保留 case ID。Go 官方专门支持应用与集成测试覆盖率；Clang 官方支持 C/C++ 源码级覆盖率。这一流程是对两种机制的组合设计，并非 Milvus 已实现的现成功能。[Go 集成测试覆盖率](https://go.dev/doc/build-cover)；[Clang source-based coverage](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html)。

| 方案 | Go 服务端 | C++ Core | case 归因 | 适用阶段 |
| --- | --- | --- | --- | --- |
| 每个 case / 小 case 组启一套插桩 Milvus，运行后正常停止 | `go build -cover` + `GOCOVERDIR` | Clang 插桩 + `LLVM_PROFILE_FILE`，或现有 gcov 路线 | 最可信；一个目录对应一个 case / 组 | 首个 PoC，建立准确基线 |
| 复用长驻服务，按 case 快照并清零 | `runtime/coverage.WriteCountersDir` + `ClearCounters` | `__llvm_profile_write_file` + `__llvm_profile_reset_counters` 等运行时 API，需要自行接入 | 启动、后台任务、并发 case 会污染；须协调所有组件 | 优化运行成本后再做 |
| 整批 Python case 共用一个服务并在末尾汇总 | 退出时写 Go profile | 退出时写 LLVM/gcov profile | 只能归因到整批，无法得出单 case 映射 | 先看整体 E2E 覆盖率 |

Go 构建 `-cover` 后，`GOCOVERDIR` 指定的目录接收元数据与计数文件；默认在程序正常返回或调用 `os.Exit` 时写完整数据。未恢复的 panic、致命异常会丢失这次运行的完整结果。因此不能用 Kubernetes 强制杀进程作为可靠的收尾方法。[Go 官方文档：运行与 FAQ](https://go.dev/doc/build-cover#running-a-coverage-instrumented-binary)。C++ Clang 原生插桩在进程退出时写 `.profraw`；`LLVM_PROFILE_FILE` 中的 `%p` 可避免不同进程写同一路径，`%m`/`%Nm` 可按二进制签名合并进池。[Clang 官方文档：运行插桩程序](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html#running-the-instrumented-program)。

## Go：服务端进程覆盖率

1. 对实际部署的 Milvus 可执行文件运行 `go build -cover`，并显式指定 `-covermode=atomic`，以支持随后清零和并发服务进程的采集；构建时保持实际服务所需的 CGO、build tags、link flags。Go 默认只插桩 **main module** 内的包。Milvus 的 `pkg/` 是独立 Go module，因此不能假定它会自动进入 root module 的覆盖率；应按实际 `go list -deps`/构建目标检查并把所需 `github.com/milvus-io/milvus/pkg/v3/...` 包明确加入 `-coverpkg`。`-coverpkg` 指定的是 import path，不是包名。[Go 官方文档：包选择](https://go.dev/doc/build-cover#how-packages-are-selected-for-instrumentation)；[Go 官方文档：FAQ](https://go.dev/doc/build-cover#frequently-asked-questions)；本仓库 `pkg/go.mod`。
2. 给每个 server 进程配置可写的 `GOCOVERDIR`；容器部署需挂载可收集的 volume。关闭进程后，`go tool covdata percent -i=<dir>` 看 package 级 statement 覆盖率；`go tool covdata textfmt -i=<dir> -o=go.cov` 转成传统格式，再用 `go tool cover -func=go.cov` 或 `go tool cover -html=go.cov -o=go.html` 看函数/源码。来自多进程、多组件的目录可用 `go tool covdata merge -i=<dir1>,<dir2> -o=<merged>` 汇总。[Go 官方文档：报告与合并](https://go.dev/doc/build-cover#working-with-coverage-data-files)。
3. 若服务不退出，Go 标准库的 `runtime/coverage.WriteCountersDir` 可立即保存快照，`WriteMetaDir` 可写元数据，`ClearCounters` 可清零；清零要求 atomic counter mode。需要在**每个**独立进程中触发这些 API，不能只在 proxy 中触发而遗漏 coordinators、nodes。快照与清零周围若有并发业务/后台工作，不能保证 case 严格归因，最好用独立进程/部署隔离。[Go `runtime/coverage` 官方 API](https://pkg.go.dev/runtime/coverage)。

示意（路径、build tags、`-coverpkg` 列表须从实际构建命令确定；这不是可直接运行的 Milvus build 脚本）：

```bash
go build -cover -covermode=atomic -coverpkg=<server-import-paths> -o milvus-cover ./cmd
mkdir -p /coverage/case_a/go
GOCOVERDIR=/coverage/case_a/go ./milvus-cover run standalone
# Run only pytest <case_a>, then stop Milvus gracefully.
go tool covdata textfmt -i=/coverage/case_a/go -o=/coverage/case_a/go.cov
go tool cover -html=/coverage/case_a/go.cov -o=/coverage/case_a/go.html
```

Go 的 `covdata` 还支持 `-pkg` 限定报告 package 范围；不同 case 目录可以各自出 HTML，最后 `merge` 得到套件覆盖率。[Go 官方文档：包选择与合并](https://go.dev/doc/build-cover#working-with-coverage-data-files)。

## C++：Core、共享库与进程覆盖率

推荐为 E2E 单独使用 Clang source-based coverage：编译与链接插桩目标时传入 `-fprofile-instr-generate -fcoverage-mapping`；运行时给每个进程设置 `LLVM_PROFILE_FILE=/coverage/<case>/cpp/%m-%p.profraw`；收集所有 `.profraw` 后 `llvm-profdata merge -sparse`，再用 `llvm-cov report/show/export` 查看文件、函数、行/分支。`llvm-cov` 的输入可包括可执行文件、动态库、目标文件或 archive；若 Core 覆盖率映射留在 `.so`，报告时须把相关插桩 `.so` 作为 `-object` 纳入，且保留同一次构建的二进制。[Clang 官方构建/报告文档](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html)；[llvm-cov 官方命令说明](https://llvm.org/docs/CommandGuide/llvm-cov.html)；[llvm-profdata 官方命令说明](https://llvm.org/docs/CommandGuide/llvm-profdata.html)。

```bash
# After the instrumented server has exited and profiles are collected:
llvm-profdata merge -sparse /coverage/case_a/cpp/*.profraw -o /coverage/case_a/cpp.profdata
llvm-cov report ./libmilvus_core.so \
  -instr-profile=/coverage/case_a/cpp.profdata
llvm-cov show ./libmilvus_core.so \
  -instr-profile=/coverage/case_a/cpp.profdata -format=html \
  -output-dir=/coverage/case_a/cpp-html
llvm-cov export ./libmilvus_core.so \
  -instr-profile=/coverage/case_a/cpp.profdata -format=lcov \
  > /coverage/case_a/cpp.lcov
```

长驻服务需要主动写文件时，Clang profile runtime 提供 `__llvm_profile_write_file`（可多次调用，追加到现有 raw profile）和 `__llvm_profile_reset_counters`（清零计数）。这要求在进程内接线，并验证共享库中运行时及计数覆盖范围；不能假定 Go 的 `runtime/coverage` 会写 C++ 计数。文档还描述 `LLVM_PROFILE_FILE` 的 `%c` 连续模式，但明确仅在 Darwin 支持；Milvus 常见 Linux 容器不能以 `%c` 作为可靠收集策略。[Clang 官方 runtime API 与连续模式说明](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html#using-the-profiling-runtime-without-static-initializers)。

本仓库目前的 `BUILD_COVERAGE` CMake 条件还要求 `BUILD_UNIT_TEST=ON` 才添加 `-fprofile-arcs -ftest-coverage` 与链接 `--coverage`（`internal/core/CMakeLists.txt:374-388`）。`Makefile:465-479` 的 `codecov-go` 和 `codecov-cpp` 都是 UT 路径；`scripts/run_go_codecov.sh` 调用 `go test -coverprofile`。这些不能直接产出 Python client → server 的 E2E 覆盖率；E2E 构建需要独立插桩开关及 profile 收集。现有 GNU gcov 路线可以扩展，但 GCC 官方同样说明 `.gcda` 通常在插桩进程退出时保存，且需保留编译所得数据文件；对每 case 的容器化采集，Clang 的独立 `.profraw` 路径更便于归档。这是对仓库和工具机制的实现建议，未做实测比较。[GCC 插桩官方文档](https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html)。

Go+C++ 报告只覆盖已插桩的 Go package 与 C++ target；Milvus 构建还链接 Rust/Tantivy 等代码（见 `internal/core/src/CMakeLists.txt` 的 `tantivy_binding`）。若需要把 Rust 也纳入“全部 server 代码”，须另行用 Rust `-C instrument-coverage` 构建并用匹配版本的 LLVM 工具读取 profile；未插桩的第三方库不应计入覆盖率分母。[Rust 官方 instrumentation coverage 文档](https://doc.rust-lang.org/rustc/instrument-coverage.html)。

## case 归因与验证顺序

1. 先选少量现有 Python client case，在**同一提交**上构建一个 Go+C++ 插桩镜像。记录 Go/Clang/LLVM 版本、Git commit、实际编译与链接参数、server 二进制和共享库路径。Clang 官方说明 raw profile 格式不保证跨编译器版本兼容，因此报告工具与构建工具应匹配。[Clang 官方格式兼容说明](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html#format-compatibility-guarantees)。
2. 一个 case 运行在一套新服务或干净采集窗口中。启动完成后才进入 case 窗口；完成后等待该 case 导致的异步任务收敛，再快照/正常退出，分别归档 Go `covmeta/covcounters` 与 C++ `.profraw`。独立进程仍会包含启动/健康检查/后台任务的代码；要解释成“由这个 case 触发”，还需相同条件下的 **baseline-only** 运行作对照。这个归因控制是本调研提出的实验设计，而非工具自动提供的功能。
   Go `go tool covdata subtract -i=<case-dir>,<baseline-dir> -o=<new-only-dir>` 可以列出 case 运行相对于 baseline **新增覆盖** 的块；这不是该 case 执行过的完整集合：case 与 baseline 共同执行的代码会被减掉。因此它适合辅助解释增量，不能代替隔离采集所得的原始 per-case profile，也不能直接套用到 C++ profile。[Go `covdata` 官方命令说明](https://go.dev/cmd/covdata/)。
3. 每个 case 产出 Go `go.cov`、C++ `cpp.lcov` 或 LLVM JSON；按路径+行/函数生成 case → server 代码矩阵。Go statement 百分比与 LLVM line/region/branch 百分比的分母和语义不同，需分别展示，不应相加成一个数字。[Go 官方 statement 定义](https://go.dev/doc/build-cover#reporting-percent-statements-covered)；[Clang 官方报告指标](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html#interpreting-reports)。
4. 首轮以一条会调用 segcore 的 insert/search case 验证：Go `internal/...` 和 C++ `internal/core/src/...` 均出现预期非零区域；再运行空载 baseline 和另一个显著不同的 case，确认报告差异。只有采到 `.profraw`/`covcounters` 且能映射回正确的 server 源码，才算 PoC 成功。

本地已确认一个适合 PoC 的现有单节点用例：`milvus_client/test_milvus_client_collection.py::TestMilvusClientCollectionValid::test_milvus_client_array_insert_search`。在 `tests/python_client` 目录执行下列命令可精确选择该 case；`--collect-only` 已在 Python 3.12.12 / pytest 8.3.4 环境确认只收集 1 个节点。连接插桩 Milvus 的实际执行采用 Dev CLI，结果见 [PoC 报告](e2e-server-coverage-poc.md)。

```bash
source .venv/bin/activate
python -m pytest -q \
  milvus_client/test_milvus_client_collection.py::TestMilvusClientCollectionValid::test_milvus_client_array_insert_search \
  --host 127.0.0.1 --port 19530
```

实际检查发现，当前 `milvus-dev-cli` 的 `build` 命令没有直接暴露 Go/C++ coverage flags；PoC 在独立 worktree 中修改构建文件，以 Dev CLI 构建并部署插桩镜像。`pysdk-e2e` 可以选择现有部署、测试文件和 `-k` case；profile 需从 Pod 收集。执行证据和本地报告位置见 [PoC 报告](e2e-server-coverage-poc.md)。
