# Python client E2E 对 Milvus 服务端 Go 与 C++ 的覆盖率 PoC

执行日期：2026-09-24。本文记录一次**实际运行**，对应插桩源码提交 `643cda56de`，服务端 `get_server_version(detail=True).git_commit` 返回 `643cda5`。本地方法调研见 [server-e2e-coverage-methods.md](server-e2e-coverage-methods.md)。

## 用例和结果

- 用例：`tests/python_client/milvus_client/test_milvus_client_collection.py::TestMilvusClientCollectionValid::test_milvus_client_array_insert_search`
- Dev CLI 测试任务：`pysdk-e2e-local-wenxing-e2e-server-covera-643cda5-566e6206-u482`，状态 `succeeded`，目标文件和 `-k` 表达式均与上述用例一致。部署模式为 standalone。
- 服务端覆盖率窗口：04:09:19 UTC 重置计数器；04:09:52–04:10:31 UTC 运行 E2E 任务；04:10:54 UTC 写快照。
- Go：`26,324 / 239,396` statements，`11.0%`；1,830 个已插桩源码文件中有 811 个产生非零计数。
- C++ Core：`3,662 / 123,413` executable lines，`3.0%`；580 个报告源码文件中有 121 个产生非零计数。`gcov` 成功处理 285 个对象文件，0 个失败。

| 路径 | 本次窗口覆盖 |
| --- | ---: |
| Go `internal/proxy/task_insert.go` | 101 / 152 statements |
| Go `internal/proxy/dql/task_search.go` | 305 / 850 statements |
| Go `internal/querynodev2/tasks/search_task.go` | 94 / 187 statements |
| Go `internal/util/segcore/segment.go` | 70 / 232 statements |
| C++ `internal/core/src/segcore/SegmentGrowingImpl.cpp` | 128 / 1,404 lines |
| C++ `internal/core/src/query/SearchOnGrowing.cpp` | 70 / 169 lines |
| C++ `internal/core/src/exec/operator/VectorSearchNode.cpp` | 52 / 77 lines |

完整的 case→文件→Go block / C++ line 映射位于本地 `artifacts/e2e-server-coverage-643cda5/coverage-map.json`；同目录的 `coverage-summary.md` 列出全部非零文件。`go-raw/`、`go.cov` 和 `cpp-json.tar.gz` 保留了本次报告的原始或中间数据。该目录由 `.gitignore` 忽略，避免把运行产物提交进源码仓库。

## 采集方法

1. `milvus-dev-cli build local . -b master --debug` 构建插桩镜像 `harbor.tencent-stage.zilliz.cn/manta/milvus:local-u482-e2e-server-coverage-643cda5-nostrip`。Go 主程序由 `go build -cover -covermode=atomic -coverpkg=... ./cmd` 构建，`-coverpkg` 根据服务端依赖生成，并覆盖独立 `pkg/v3` module。C++ Core 使用 GCC `-fprofile-arcs -ftest-coverage -fprofile-update=atomic`，同时保留同次构建的 `.gcno` 和 `gcov 12.3.0`。
2. `milvus-dev-cli deploy create <build-id> --name e2e-cov-0924 --cu 2` 部署专用 standalone。启动完成后向 Milvus 主进程发 `SIGUSR2`：Go `runtime/coverage.ClearCounters` 和 C++ `__gcov_reset` 清零。
3. `milvus-dev-cli pysdk-e2e local . -b master --deploy e2e-cov-0924 -t tests/python_client/milvus_client/test_milvus_client_collection.py -k test_milvus_client_array_insert_search` 运行现有用例。完成后向同一进程发 `SIGUSR1`：Go `WriteMetaDir`、`WriteCountersDir` 和 C++ `__gcov_dump` 写快照。本次得到 Go `covmeta`、`covcounters` 和 616 个 C++ `.gcda` 文件。
4. `go tool covdata textfmt -i=<go-raw> -o=go.cov` 转换 Go 原始数据。容器内用 `scripts/prepare_e2e_cpp_gcov.sh <coverage-root> /milvus/lib/milvus-e2e-gcov` 将同次构建的 `.gcno` 与 `.gcda` 合并为 GCC JSON。最后用 `scripts/report_e2e_server_coverage.py` 生成映射和摘要。

Go 的百分比使用语句数，C++ 使用可执行行数，两者不能相加。报告分母包含已插桩范围内的生成代码；C++ 报告仅覆盖 Milvus Core 的 `internal/core/src`，不包括 Rust、未插桩的外部依赖。此采集窗口也包含服务端后台任务、健康检查以及用例结束后的异步工作，因此“非零”表示**该时间窗口执行过**，不能单凭计数断言每一行都由该 case 独自触发。严格归因应给每个 case 隔离服务实例，并做相同时间长度的空载基线对照；集群部署还需对每个 Milvus 进程分别重置、快照和合并。
