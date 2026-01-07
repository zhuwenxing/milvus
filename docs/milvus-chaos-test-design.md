# Milvus 稳定性 Chaos 测试设计方案

> 基于 Milvus 2.6 架构和 Chaos Mesh 能力设计

## 核心思路

**从 Milvus 作为向量数据库的特点出发，分析需要注入什么类型的故障。**

---

## 一、Milvus 特点及对应故障类型

### 1.1 Segment 状态机 (有状态转换)

**Milvus 特点**:
- 数据按 Segment 组织：Growing → Sealed → Flushed → Indexed → Compacted
- 每个状态转换都有失败风险
- 状态存储在 etcd，实际数据在对象存储

**需要的故障类型**:

| 状态转换 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| Growing → Sealed | **DataNode Kill** (无 graceful shutdown) | 验证 checkpoint 机制是否有效 |
| Sealed → Flushed | **存储 IO 错误** | 验证 flush 重试和幂等性 |
| Flushed → Indexed | **IndexNode 资源耗尽** (OOM/CPU) | 验证索引任务恢复机制 |
| Indexed → Compacted | **DataNode Kill during compaction** | 验证 compaction 状态机回滚 |

```yaml
# 故障类型 1: 状态转换期间的进程终止
kind: PodChaos
action: pod-kill
gracePeriod: 0  # 关键: 不给 graceful shutdown

# 故障类型 2: 存储层 IO 错误
kind: IOChaos
action: fault
errno: 5  # EIO
methods: [write, fsync]

# 故障类型 3: 资源耗尽
kind: StressChaos
stressors:
  memory:
    size: "90%"
```

---

### 1.2 分布式时间戳 (Timetick 机制)

**Milvus 特点**:
- 使用 timetick 保证分布式一致性
- 所有 Proxy 向 RootCoord 报告时间戳
- RootCoord 计算全局最小时间戳并广播
- 查询只能读取 timetick 之前的数据

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| Proxy 停止发送 timetick | **Proxy ↔ RootCoord 网络分区** | 验证 idle session 检测和排除 |
| 时钟不同步 | **TimeChaos (时钟偏移)** | 验证对时钟偏移的容忍度 |
| Timetick 消息延迟 | **网络延迟注入** | 验证延迟对一致性的影响 |

```yaml
# 故障类型 1: 单向网络分区 (阻断 timetick 发送)
kind: NetworkChaos
action: partition
direction: to
selector: {component: proxy}
target: {component: rootcoord}

# 故障类型 2: 时钟偏移
kind: TimeChaos
timeOffset: "-5m"  # 时钟回拨
clockIds: [CLOCK_REALTIME]

# 故障类型 3: 网络延迟
kind: NetworkChaos
action: delay
delay:
  latency: "500ms"
  jitter: "100ms"
```

---

### 1.3 内存密集型 (QueryNode 加载 Segment)

**Milvus 特点**:
- QueryNode 将 Segment 加载到内存进行查询
- 向量数据量大，内存占用高
- 多 Collection 场景下内存竞争

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| 内存不足 | **Memory Stress** | 验证 OOM 处理和 Segment 卸载策略 |
| 加载过程中内存耗尽 | **Memory Stress + Load 操作** | 验证加载失败后的状态回滚 |
| 内存泄漏累积 | **长时间低内存压力** | 验证内存管理的健壮性 |

```yaml
# 故障类型: 内存压力
kind: StressChaos
selector: {component: querynode}
stressors:
  memory:
    workers: 4
    size: "80%"  # 占用 80% 内存
duration: "300s"
```

---

### 1.4 CPU 密集型 (索引构建/向量计算)

**Milvus 特点**:
- 索引构建 (HNSW, IVF) 是 CPU 密集型
- 向量距离计算在搜索时消耗 CPU
- IndexNode 和 QueryNode 都是 CPU 敏感

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| CPU 饱和 | **CPU Stress** | 验证索引构建超时处理 |
| CPU 限流 | **CPU Throttle** | 验证 QPS 降级行为 |
| CPU 争抢 | **多进程 CPU Stress** | 验证优先级和调度 |

```yaml
# 故障类型: CPU 压力
kind: StressChaos
selector: {component: indexnode}
stressors:
  cpu:
    workers: 8
    load: 95
duration: "600s"
```

---

### 1.5 IO 密集型 (Flush/Compaction/Load)

**Milvus 特点**:
- Flush: DataNode 写入对象存储
- Compaction: 读取多个 Segment，合并后写入
- Load: QueryNode 从对象存储读取 Segment

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| 存储慢 | **IO Latency** | 验证超时和重试策略 |
| 存储错误 | **IO Fault (EIO)** | 验证错误处理和重试 |
| 存储带宽受限 | **Network Bandwidth Limit** | 验证大 Segment 场景 |
| 存储不可用 | **MinIO Pod Kill** | 验证依赖服务故障处理 |

```yaml
# 故障类型 1: IO 延迟
kind: IOChaos
action: latency
delay: "200ms"
percent: 50  # 50% 的 IO 受影响
methods: [read, write]

# 故障类型 2: IO 错误
kind: IOChaos
action: fault
errno: 28  # ENOSPC (磁盘满)
percent: 10
methods: [write]

# 故障类型 3: 网络带宽限制 (对象存储连接)
kind: NetworkChaos
action: bandwidth
bandwidth:
  rate: "10mbps"
  limit: 100
target: {app: minio}
```

---

### 1.6 消息队列依赖 (数据管道)

**Milvus 特点**:
- Insert/Delete 通过 DML Channel 传播
- Timetick 通过专用 Channel 广播
- Delete 通过 Delta Channel 同步到 QueryNode

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| MQ 延迟 | **Pulsar/Kafka 网络延迟** | 验证消息积压处理 |
| MQ 分区不可用 | **Broker Pod Kill** | 验证 partition failover |
| 消息乱序 | **网络 duplicate + delay** | 验证消息去重和排序 |

```yaml
# 故障类型 1: MQ 网络延迟
kind: NetworkChaos
action: delay
selector: {component: broker, app: pulsar}
delay:
  latency: "1s"

# 故障类型 2: MQ 部分不可用
kind: PodChaos
action: pod-kill
selector: {component: broker}
mode: fixed
value: "1"  # 只杀一个 broker
```

---

### 1.7 元数据存储依赖 (etcd)

**Milvus 特点**:
- Collection/Partition/Segment 元数据存储在 etcd
- Coordinator 选举依赖 etcd Session
- 服务发现依赖 etcd

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| etcd 少数派故障 | **Kill 1/3 etcd** | 验证多数派仍可用 |
| etcd 网络分区 | **Milvus ↔ etcd 网络分区** | 验证 session 过期和重连 |
| etcd 慢响应 | **etcd IO/CPU 压力** | 验证超时处理 |

```yaml
# 故障类型 1: etcd 单节点故障
kind: PodChaos
action: pod-kill
selector: {app.kubernetes.io/name: etcd}
mode: fixed
value: "1"

# 故障类型 2: 网络分区
kind: NetworkChaos
action: partition
selector: {component: rootcoord}
target: {app.kubernetes.io/name: etcd}
duration: "30s"
```

---

### 1.8 Coordinator 单点 (Leader 选举)

**Milvus 特点**:
- RootCoord/DataCoord/QueryCoord 通常单实例
- 通过 etcd Session 实现 Active-Standby
- Leader 切换期间有短暂不可用

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| Leader 崩溃 | **Coord Pod Kill** | 验证 Standby 接管 |
| Leader 假死 (etcd 断连) | **Coord ↔ etcd 网络分区** | 验证脑裂防护 |
| Leader 处理慢 | **Coord CPU/Memory Stress** | 验证健康检查和切换 |

```yaml
# 故障类型 1: Coordinator 崩溃
kind: PodChaos
action: pod-kill
selector: {component: mixcoord}

# 故障类型 2: 网络隔离导致假死
kind: NetworkChaos
action: partition
selector: {component: rootcoord}
target: {app.kubernetes.io/name: etcd}
```

---

### 1.9 Handoff 机制 (Segment 迁移)

**Milvus 特点**:
- QueryCoord 负责 Segment 在 QueryNode 间迁移
- 迁移流程：新节点 Load → 旧节点 Unload
- 迁移期间 Delete 数据需要同步

**需要的故障类型**:

| 风险场景 | 注入什么故障 | 为什么 |
|---------|-------------|--------|
| 迁移过程中目标节点崩溃 | **QueryNode Kill during Load** | 验证迁移回滚 |
| 迁移过程中源节点崩溃 | **QueryNode Kill during Unload** | 验证 Segment 不丢失 |
| 迁移过程网络问题 | **QueryNode ↔ Storage 网络分区** | 验证超时和重试 |

```yaml
# 故障类型: Handoff 期间节点崩溃
kind: PodChaos
action: pod-kill
selector: {component: querynode}
mode: one
# 配合测试脚本在 balance 触发后注入
```

---

## 二、进程终止类型详解：Pod Kill vs Container Kill

### 2.1 核心区别

| 特性 | Pod Kill | Container Kill |
|-----|----------|----------------|
| **作用范围** | 删除整个 Pod | 只杀死 Pod 内的特定容器 |
| **K8s 行为** | 重新调度创建新 Pod | 原地重启容器 |
| **恢复时间** | 较长 (调度+拉取镜像) | 较短 (容器重启) |
| **网络 IP** | 变化 (新 Pod 新 IP) | 不变 (同一 Pod) |
| **emptyDir** | 丢失 | 保留 |
| **gracePeriod** | 支持 (0=强杀) | 不支持 (直接 SIGKILL) |

### 2.2 Milvus 场景选择

| 测试目标 | 推荐方式 | 原因 |
|---------|---------|------|
| **验证 checkpoint 机制** | Container Kill | 快速触发，无调度延迟 |
| **验证完全故障恢复** | Pod Kill (gracePeriod=0) | 完全重建，测试全流程 |
| **验证优雅关闭** | Pod Kill (gracePeriod=30) | 测试 graceful shutdown |
| **验证服务发现** | Pod Kill | IP 变化，测试重新注册 |
| **验证进程级重启** | Container Kill | 环境保留，只测应用恢复 |

### 2.3 配置示例

```yaml
# Container Kill - 测试进程级恢复 (推荐用于 checkpoint 测试)
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: datanode-container-kill
spec:
  action: container-kill
  selector:
    labelSelectors:
      component: datanode
  containerNames:
    - datanode  # 必须指定容器名

# Pod Kill (强杀) - 测试完全故障恢复
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: datanode-pod-kill-hard
spec:
  action: pod-kill
  gracePeriod: 0  # 立即删除，不等待
  selector:
    labelSelectors:
      component: datanode

# Pod Kill (优雅) - 测试 graceful shutdown
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: datanode-pod-kill-graceful
spec:
  action: pod-kill
  gracePeriod: 30  # 等待 30s
  selector:
    labelSelectors:
      component: datanode
```

### 2.4 各组件推荐终止方式

| 组件 | 首选方式 | 原因 |
|------|---------|------|
| **DataNode** | Container Kill | 快速验证 checkpoint，无需等调度 |
| **QueryNode** | Container Kill | 快速验证 segment 重新加载 |
| **IndexNode** | Container Kill | 验证索引任务恢复 |
| **Coordinator** | Pod Kill | 验证 Leader 选举和服务发现 |
| **Proxy** | Pod Kill | 验证客户端重连和 IP 变化 |
| **etcd** | Pod Kill | 验证 Raft 成员变更 |
| **MinIO** | Pod Kill | 验证存储服务恢复 |

---

## 三、故障类型总结

### 3.1 按故障类别分类

| 故障类别 | Chaos Mesh 类型 | 适用场景 |
|---------|----------------|---------|
| **容器终止** | PodChaos (container-kill) | 进程崩溃，快速恢复 |
| **Pod 终止** | PodChaos (pod-kill) | 完全故障，调度恢复 |
| **进程暂停** | PodChaos (pod-failure) | 假死场景 |
| **网络分区** | NetworkChaos (partition) | 组件隔离、脑裂 |
| **网络延迟** | NetworkChaos (delay) | 超时、消息积压 |
| **网络带宽** | NetworkChaos (bandwidth) | 大数据传输 |
| **IO 延迟** | IOChaos (latency) | 存储慢响应 |
| **IO 错误** | IOChaos (fault) | 存储故障 |
| **内存压力** | StressChaos (memory) | OOM、内存不足 |
| **CPU 压力** | StressChaos (cpu) | 计算资源争抢 |
| **时钟偏移** | TimeChaos | 分布式时间问题 |

### 3.2 按 Milvus 组件分类 (含终止方式)

| 组件 | 核心故障类型 | 推荐终止方式 | 原因 |
|------|------------|-------------|------|
| **DataNode** | IO 故障、进程终止 | Container Kill | 快速验证 checkpoint |
| **QueryNode** | Memory Stress、进程终止 | Container Kill | 快速验证 segment 重载 |
| **IndexNode** | CPU Stress、进程终止 | Container Kill | 验证索引任务恢复 |
| **Proxy** | 网络分区、进程终止 | Pod Kill | 验证服务发现和 IP 变化 |
| **Coordinator** | etcd 网络分区、进程终止 | Pod Kill | 验证 Leader 选举 |
| **etcd** | Pod Kill (少数派) | Pod Kill | 验证 Raft 成员变更 |
| **MinIO** | IO 故障、进程终止 | Pod Kill | 验证存储服务恢复 |
| **Pulsar/Kafka** | 网络延迟、进程终止 | Pod Kill | 验证分区 failover |

### 3.3 按优先级排序

**P0 - 数据安全** (必须测试):
1. DataNode **Container Kill** → 验证 checkpoint (快速验证)
2. DataNode **Pod Kill** (gracePeriod=0) → 验证完全恢复
3. MinIO IO 故障 → 验证数据持久性
4. Coordinator ↔ etcd 网络分区 → 验证无脑裂

**P1 - 服务可用** (高优先级):
5. QueryNode **Container Kill** + Memory Stress → 验证 OOM 处理
6. Coordinator **Pod Kill** → 验证 Leader 选举
7. Pulsar/Kafka 延迟/故障 → 验证消息队列容错
8. etcd **Pod Kill** (少数派) → 验证元数据服务 HA

**P2 - 性能稳定** (中优先级):
9. IndexNode **Container Kill** + CPU Stress → 验证索引构建容错
10. 网络延迟注入 → 验证超时和重试
11. TimeChaos → 验证时钟容忍度

**P3 - 优雅关闭** (完整性测试):
12. 各组件 **Pod Kill** (gracePeriod=30) → 验证 graceful shutdown

---

## 四、故障组合策略

### 4.1 单故障 vs 组合故障

**单故障 (基础)**:
- 每次只注入一种故障
- 用于验证基本恢复能力
- 先验证单故障再测组合

**组合故障 (进阶)**:
- 多种故障同时或顺序发生
- 模拟真实生产环境
- 测试级联故障处理

### 4.2 推荐的故障组合

| 组合 | 故障 1 | 故障 2 | 模拟场景 |
|-----|--------|--------|---------|
| A | IO 延迟 | Memory Stress | 存储慢导致内存积压 |
| B | 网络分区 | Pod Kill | 分区后节点崩溃 |
| C | CPU Stress | 网络延迟 | 高负载下网络抖动 |
| D | etcd 故障 | Coord Kill | 元数据服务 + 协调器双故障 |

---

## 五、验收标准

| 故障类型 | 验收标准 |
|---------|---------|
| **Container Kill** | 恢复时间 ≤ 30s，无数据丢失 |
| **Pod Kill** (gracePeriod=0) | 恢复时间 ≤ 60s，无数据丢失 |
| **Pod Kill** (gracePeriod=30) | 优雅关闭成功，无数据丢失 |
| IO 故障 | 操作重试成功，无数据损坏 |
| 网络分区 | 分区节点被隔离，无脑裂 |
| Memory Stress | 优雅降级，不 OOM crash |
| CPU Stress | QPS 降级，不超时雪崩 |
| 时钟偏移 | 容忍 ±5min，超出告警 |

---

## 六、总结

本方案从 Milvus 9 个核心特点出发，设计对应的故障类型:

| Milvus 特点 | 推荐故障类型 | 终止方式选择 |
|------------|-------------|-------------|
| **Segment 状态机** | 进程终止 + IO 故障 | Container Kill (快速验证) |
| **Timetick 机制** | 网络分区 + TimeChaos | - |
| **内存密集** | Memory Stress | Container Kill + Stress |
| **CPU 密集** | CPU Stress | Container Kill + Stress |
| **IO 密集** | IO Chaos | - |
| **MQ 依赖** | MQ 网络故障 | Pod Kill (验证 failover) |
| **etcd 依赖** | etcd 故障 | Pod Kill (验证 Raft) |
| **Coordinator 单点** | 进程终止 + 网络分区 | Pod Kill (验证选举) |
| **Handoff 机制** | 定向进程终止 | Container Kill |

**核心原则**:
- **Worker 节点** (DataNode, QueryNode, IndexNode): 优先 **Container Kill**，快速验证应用层恢复
- **协调节点** (Coordinator, etcd): 优先 **Pod Kill**，验证服务发现和 Leader 选举
- **存储/MQ** (MinIO, Pulsar): 优先 **Pod Kill**，验证依赖服务 failover
