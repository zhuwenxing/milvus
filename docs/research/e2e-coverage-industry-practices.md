# E2E 服务端覆盖率的业界使用方式：对 Milvus Go + C++ 的建议

调研日期：2026-09-24。这里的覆盖率指 Python client case 运行时，插桩 Milvus 服务端实际执行的 Go statement/block 与 C++ line/branch。已完成的一次采集见 [PoC 报告](e2e-server-coverage-poc.md)。下文将**已有实践/工具事实**与**Milvus 建议**分开；不能把其他公司整套测试流水线的覆盖率门槛直接当成 Milvus 单个 E2E case 的门槛。

**适用范围提醒：**Google 2019 年的《Code Coverage at Google》虽然展示了变更行覆盖率的代码评审实践，但论文明确只研究单机（通常单进程）的测试，排除了跨机器的集成/系统测试，并指出行覆盖不是这种测试最合适的度量。因此“PR diff 展示执行行”可以借鉴，不能将该论文当成“Google 用服务端行覆盖率衡量跨服务 E2E 测试质量”的证据。[论文原文，第 2.3 节](https://homes.cs.washington.edu/~rjust/publ/google_coverage_fse_2019.pdf)。

## 业界怎样让覆盖率可行动

| 使用场景 | 一手资料中的实践或事实 | 对 Milvus 的建议（推论） |
| --- | --- | --- |
| 代码评审中的风险缺口 | Google 的覆盖率基础设施将信息应用于 changeset 和代码评审，但该论文仅研究单机测试；其测试博客强调评审具体未覆盖的代码及行为，比只看总百分比更有价值。GitLab 可在 MR diff 标注逐行覆盖，Azure Pipelines 可在 PR 中显示变更行覆盖与状态。[Google 论文](https://homes.cs.washington.edu/~rjust/publ/google_coverage_fse_2019.pdf)；[Google 测试博客](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)；[GitLab 文档](https://docs.gitlab.com/ci/testing/code_coverage/)；[Azure 文档](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/review-code-coverage-results?view=azure-devops) | 对 PR 的 Go/C++ 变更行展示“哪个 Python E2E case 的采集窗口命中了它”及未命中行，并让评审者判断错误分支、跨组件路径是否需要新 case。先作为提示，避免只因单次 E2E 百分比低就阻断 PR。 |
| 端点/调用链覆盖 | Uber BITS 对每次 E2E 运行强制采样 trace，以此建立“case→服务与端点”和反向索引，向团队展示端点覆盖并为服务变更选测；使用按变更隔离的测试 sandbox，且对主分支做并行 placebo 运行以区分变更引起的失败。另一篇原始研究提出微服务 E2E 的端点覆盖度量。[Uber BITS](https://www.uber.com/us/en/blog/shifting-e2e-testing-left/)；[Elsayed 等，2023](https://arxiv.org/abs/2308.09257) | 先为 Python case 建立 RPC/组件调用链索引，优先回答“哪些用户行为到达了 proxy、querynode、segcore 的哪些操作”。将 Go/C++ 源码命中作为深入查分支的第二层证据。追踪索引与源码覆盖互补；Uber 文章没有宣称使用服务端源码级 case 覆盖。 |
| 按变更选回归测试 | 微软 Test Impact Analysis 以变更相关性选部分测试，同时包含以往失败/新测试，未知变更回退到全量，并可定期全量运行；其官方支持范围是单机托管代码，**明确不支持测试与 SUT 分处多机**，因此不能直接套用到 Milvus。Meta 也将测试选择与历史变更/结果数据结合，并持续验证漏检率。Google 的研究显示选测效果依赖真实失败转移、数据和 flaky 测试处理；测试选择仍是开放难题。[微软 TIA](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/test-impact-analysis?view=azure-devops)；[Meta 工程文章](https://engineering.fb.com/2018/11/21/developer-tools/predictive-test-selection/)；[Google 选测研究](https://research.google/pubs/assessing-transition-based-test-selection-algorithms-at-google/) | 自建 `changed Go block/C++ line → 历史命中 case` 候选映射，用测试耗时、失败历史、稳定性给候选排序。把它作为**优先执行列表**，不要把未命中当成“不必测试”；新代码、构建/协议变更、未插桩代码和没有历史映射时回退到更广测试集，并定期全量校验漏检。 |
| 识别值得补的缺口 | Google Productive Coverage 指出并非所有未覆盖代码同等重要，简单展示所有未覆盖行难以行动；其方法结合相似的已测试代码和生产执行频率来提示有价值的缺口，曾在 C++、Go 等语言评估。[Google Productive Coverage](https://research.google/pubs/productive-coverage-improving-the-actionability-of-code-coverage/) | 优先看与用户行为相关且频繁变更或曾出问题的路径，如 proxy→querynode→segcore 搜索链、错误码、超时/取消、资源不足、恢复路径。将这些路径的未覆盖分支关联到具体测试计划；对生成代码、日志与很少访问的辅助代码单独展示。 |
| 评估断言是否有效 | Google 明确指出覆盖只证明执行，不能证明结果被正确检查，E2E 的覆盖有时只是附带执行；其差异化 mutation testing 用有限的变更位置检验测试能否发现人为错误。[Google 测试博客](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)；[Google mutation 论文](https://research.google/pubs/state-of-mutation-testing-at-google/) | 对关键已命中路径审查 Python case 是否断言返回内容、错误码及服务端状态。对少量高风险改动试用故障注入或定向 mutation：有覆盖且测试仍绿，表明断言/输入不足。不要把“覆盖了错误分支所在文件”等同于“验证了该错误分支”。 |
| 套件与阶段汇总 | Google 建议合并流水线中 UT、集成/系统测试的覆盖视图，以辨认自动化总体缺口，同时提醒集成/E2E 可能产生偶然覆盖。Go 官方支持集成测试的插桩构建、运行和报告，以及多个数据目录的合并。[Google 测试博客](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)；[Go 集成测试覆盖率](https://go.dev/doc/build-cover) | 分别保存 UT、Python SDK E2E、REST/Go SDK E2E 的来源，再给出 Go 与 C++ 各自的并集和新增覆盖。按模块/功能展示增量，避免把不同语言或分母相加。 |

## 采集数据可信度：工具事实与实验约束

1. **单 case 必须有可识别的采集窗口。**Go `runtime/coverage` 为长驻 server 提供 `ClearCounters` 和写计数快照的 API；清零只支持 atomic counter mode。GCC 的 `__gcov_reset` / `__gcov_dump` 可将长驻 C++ 程序的采集限制在感兴趣的时间段。[Go runtime API](https://pkg.go.dev/runtime/coverage)；[GCC gcov 文档](https://gcc.gnu.org/onlinedocs/gcc/Gcov-and-Optimization.html)。对 Milvus 而言，要在每个服务端进程上执行同样的窗口操作；集群模式只采 standalone/proxy 进程会漏掉节点。
2. **窗口隔离不等于请求归因。**计数器记录进程内所有线程的执行；因此健康检查、后台调度、其他请求和 case 结束后的异步工作都可能进入窗口。这是计数器机制与 Milvus 并发架构的推论，不是 `gcov`/Go 自动识别的“case 覆盖”。建议使用专用部署、一次只跑一个 case、同长度空载基线，并在报告中保留原始窗口覆盖与“相对基线新增覆盖”两个视图。基线相减只显示新增区域，**共同执行的代码也会被消去**；Go `covdata` 支持 `merge`、`subtract`、`intersect`，C++ 需在相同构建的 JSON/行集合层独立实现相应运算。[Go covdata](https://pkg.go.dev/cmd/covdata)。
3. **为每个构建保存身份和分母。**Go 只报告已选中的插桩包，`-coverpkg` 决定范围；GCC `gcov` 将 `.gcno` 与 `.gcda` 对应到同次构建，重复运行时既有 `.gcda` 的计数会累加。不同提交、编译参数、Go package 列表、C++ target 或工具版本的百分比不可直接比较。[Go 构建覆盖率文档](https://go.dev/doc/build-cover)；[GCC gcov 文档](https://gcc.gnu.org/onlinedocs/gcc/Invoking-Gcov.html)。建议记录服务端实际 git commit、镜像 digest、编译器版本、case ID、拓扑、计数窗口和插桩清单；每次 case 使用新的输出目录，确保旧 `.gcda` 不混入。
   当前 PoC 的容器输出路径是固定的，因此复用同一进程时须先归档并清理上轮 Go `covcounters` 与 C++ `.gcda`，再执行下一轮 reset→case→dump；或者为每个 case 创建新进程。当前 Pod 已验证 reset 后第二次 C++ dump 能写出文件，但尚未验证自动化的多 case 隔离。
4. **按所需问题选择粒度。**GCC `gcov --json-format` 可输出函数和行的计数；`-b` 包含分支数据。行命中不能证明条件的 true/false 都走过；若要验证错误路径或多条件决策，应进一步看分支、条件和真实断言。编译优化、内联也会使行计数解释复杂。[GCC JSON/branch 文档](https://gcc.gnu.org/onlinedocs/gcc/Invoking-Gcov.html)；[GCC 优化说明](https://gcc.gnu.org/onlinedocs/gcc/Gcov-and-Optimization.html)。
5. **过程/接口覆盖是另一张图。**Uber 的 trace 索引是更接近 Milvus 跨进程 E2E 的直接行业实例：每条 case 可关联服务与端点，并用于选测；微服务 E2E 端点覆盖的研究也强调它有别于单体代码行覆盖。[Uber BITS](https://www.uber.com/us/en/blog/shifting-e2e-testing-left/)；[Elsayed 等，2023](https://arxiv.org/abs/2308.09257)。Milvus 可按 SDK 操作/RPC 方法记录 case→调用链，再和源码覆盖交叉查看：某操作到达某组件但未触及关键错误路径，或者服务端路径执行了但没有与之对应的用户可观察断言。这一关联方式是 Milvus 建议，不是当前 PoC 已实现的能力。

## 门槛如何设

Google 建议根据代码重要性、变更频率等确定目标，重视新代码与未覆盖的具体行，也提醒统一百分比目标可能诱导“刷覆盖”。其博客讨论的覆盖率范围与建议针对**产品/流水线整体**，并非某条跨进程 E2E 用例。[Google 测试博客](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)。Azure 的 PR diff coverage 阈值和 GitLab 的覆盖率下降审批说明门槛可在代码评审工作流落地，但这两者也不意味着“单 case E2E 11% Go/3% C++”应当与统一阈值比较。[Azure 差异覆盖](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/review-code-coverage-results?view=azure-devops)；[GitLab 覆盖率](https://docs.gitlab.com/ci/testing/code_coverage/)。
Azure 当前的 PR coverage 状态校验只接受 Visual Studio `.coverage` 格式；GitLab 的逐行显示接受 Cobertura 或 JaCoCo XML。Milvus 的 Go/C++ PoC 产物需要另行转换或接入，不能把这些产品的功能理解为现成可用的 Milvus 集成。[Azure 格式限制](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/review-code-coverage-results?view=azure-devops)；[GitLab 报告格式](https://docs.gitlab.com/ci/testing/code_coverage/)。

建议 Milvus 分阶段采用：

1. **先观察。**选 10–20 个行为互补的 Python case，重复采集以测波动，形成空载基线和 case→Go/C++ 映射。度量报告缺失/损坏率、采集耗时、case 运行变化及覆盖波动。
2. **再辅助评审。**对 PR 展示变更行是否被任一 E2E 命中、命中 case、相关关键分支与断言证据。标注“有覆盖但缺断言/失败模式未触发”与“未采集到”两种不同风险。
3. **最后验证选测。**离线回放历史 PR 与失败结果，统计候选集耗时、漏掉失败的次数/比例；和全量运行比对一段时间。保留定期全量、未知变更回退和人工覆盖。仅在数据质量与漏检率可接受后考虑自动化门槛；门槛优先针对高风险路径及新变更代码，不针对单 case 的全仓百分比。

### 当前 PoC 能支持的结论

现有[单 case 报告](e2e-server-coverage-poc.md)能证实某时间窗口内 Go/C++ 服务端执行了哪些源码区域，是构建矩阵与查缺口的起点。它没有空载基线、重复性样本或逐请求 trace，因而目前不能可靠地将每个命中行归因于这条 Python case，也不能以其 11.0% Go 与 3.0% C++ 给 Milvus E2E 质量设门槛。
