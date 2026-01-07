# Chaos Mesh 故障注入教程

> 本文档介绍如何使用 Chaos Mesh 对 Milvus 进行故障注入测试，包括 YAML 配置详解和验证方法。

---

## 目录

1. [基础概念](#一基础概念)
2. [通用配置字段](#二通用配置字段)
   - [duration 字段详解](#21-duration-字段详解)
   - [mode 字段详解](#22-mode-字段详解)
   - [selector 字段详解](#23-selector-字段详解)
   - [Schedule 定时调度](#24-schedule-定时调度)
3. [PodChaos - Pod 故障](#三podchaos---pod-故障)
4. [NetworkChaos - 网络故障](#四networkchaos---网络故障)
5. [IOChaos - IO 故障](#五iochaos---io-故障)
6. [StressChaos - 资源压力](#六stresschaos---资源压力)
7. [TimeChaos - 时钟偏移](#七timechaos---时钟偏移)
8. [验证方法汇总](#八验证方法汇总)
9. [常见问题](#九常见问题)

---

## 一、基础概念

### 1.1 Chaos Mesh 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Chaos Mesh 组件                           │
├─────────────────────────────────────────────────────────────┤
│  chaos-controller-manager  │  控制器，处理 CRD，调度故障      │
│  chaos-daemon (DaemonSet)  │  每个节点一个，执行实际故障注入   │
│  chaos-dashboard           │  Web UI (可选)                  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 故障类型概览

| 类型 | 用途 | 典型场景 |
|------|------|---------|
| **PodChaos** | Pod/容器级故障 | 进程崩溃、节点故障 |
| **NetworkChaos** | 网络故障 | 网络分区、延迟、丢包 |
| **IOChaos** | 存储 IO 故障 | 磁盘慢、IO 错误 |
| **StressChaos** | 资源压力 | CPU/内存耗尽 |
| **TimeChaos** | 时钟偏移 | 时间敏感逻辑测试 |

---

## 二、通用配置字段

所有 Chaos 类型都包含以下通用字段：

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: <ChaosType>          # PodChaos, NetworkChaos, IOChaos, StressChaos, TimeChaos
metadata:
  name: my-chaos           # Chaos 实验名称
  namespace: chaos-testing # Chaos 资源所在命名空间 (非目标 Pod 命名空间)
spec:
  # === 目标选择器 (必填) ===
  selector:
    namespaces:            # 目标 Pod 所在的命名空间
      - milvus-namespace
    labelSelectors:        # 通过标签选择目标 Pod
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
    # 可选：通过节点选择
    fieldSelectors:
      spec.nodeName: node-1

  # === 影响模式 (必填) ===
  mode: one                # 影响模式，见下表
  value: "2"               # 配合 mode 使用 (fixed/fixed-percent/random-max-percent 时需要)

  # === 持续时间 (可选) ===
  duration: "30s"          # 见下方说明
```

### 2.1 duration 字段详解

Chaos 分为**一次性**和**持续性**两类，`duration` 的作用不同：

| 类型 | Chaos 动作 | duration 作用 |
|------|-----------|--------------|
| **一次性** | `pod-kill`, `container-kill` | 实验窗口期，**不影响故障本身**。Pod 被杀后立即重建，duration 只控制 Chaos 资源何时标记为完成 |
| **持续性** | `pod-failure`, 所有 `NetworkChaos`, `IOChaos`, `StressChaos`, `TimeChaos` | **故障持续时间**，到期后自动恢复正常状态 |

**示例说明：**

```yaml
# 一次性：pod-kill
duration: "30s"  # Pod 被杀死后立即重建，30s 后 Chaos 状态变为 Recovered
                 # duration 对 Pod 重启速度没有任何影响

# 持续性：network delay
duration: "30s"  # 网络延迟持续 30s，30s 后延迟自动移除，网络恢复正常
```

**设置 duration：**
- 一次性 Chaos：duration 只控制 Chaos 资源状态，不影响故障本身
- 持续性 Chaos：duration 到期后**自动恢复**，故障解除

**不设置 duration：**
- 一次性 Chaos：执行一次后状态变为完成
- 持续性 Chaos：**永久生效**，直到手动删除 Chaos 资源

**一次性 Chaos 周期执行：** 使用 `Schedule` 资源，见 [2.4 Schedule 定时调度](#24-schedule-定时调度)

### 2.2 mode 字段详解

| mode | 说明 | value 示例 |
|------|------|-----------|
| `one` | 随机选择 1 个 Pod | 不需要 |
| `all` | 选择所有匹配的 Pod | 不需要 |
| `fixed` | 选择固定数量的 Pod | `"3"` |
| `fixed-percent` | 选择百分比的 Pod | `"50"` (50%) |
| `random-max-percent` | 随机选择最多 N% 的 Pod | `"30"` (最多30%) |

### 2.2 selector 字段详解

```yaml
selector:
  # 命名空间过滤
  namespaces:
    - ns1
    - ns2

  # 标签选择器 (AND 关系)
  labelSelectors:
    app: milvus
    component: datanode

  # 表达式选择器 (支持 In, NotIn, Exists, DoesNotExist)
  expressionSelectors:
    - key: app.kubernetes.io/component
      operator: In
      values:
        - datanode
        - querynode

  # 字段选择器
  fieldSelectors:
    spec.nodeName: node-1
    metadata.name: specific-pod-name

  # Pod 名称列表 (直接指定)
  pods:
    my-namespace:
      - pod-name-1
      - pod-name-2
```

### 2.4 Schedule 定时调度

对于**一次性动作** (如 `pod-kill`, `container-kill`)，可以使用 `Schedule` 资源实现周期性执行。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: Schedule
metadata:
  name: scheduled-pod-kill
  namespace: chaos-testing
spec:
  schedule: "*/5 * * * *"       # Cron 表达式：每 5 分钟执行一次
  startingDeadlineSeconds: 60   # 错过调度后的最大延迟执行时间
  concurrencyPolicy: Forbid     # 并发策略
  historyLimit: 3               # 保留的历史记录数
  type: PodChaos                # Chaos 类型
  podChaos:                     # 对应类型的配置 (小驼峰命名)
    action: pod-kill
    mode: one
    selector:
      namespaces:
        - chaos-testing
      labelSelectors:
        app.kubernetes.io/instance: my-milvus
        app.kubernetes.io/component: datanode
```

**字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `schedule` | 是 | Cron 表达式，支持 5 位 (分 时 日 月 周) 或 6 位 (秒 分 时 日 月 周) |
| `startingDeadlineSeconds` | 否 | 错过调度时间后，最多延迟多少秒仍可执行 |
| `concurrencyPolicy` | 否 | `Forbid` (默认): 跳过并发执行；`Allow`: 允许并发 |
| `historyLimit` | 否 | 保留多少条历史 Chaos 记录，默认 1 |
| `type` | 是 | Chaos 类型：`PodChaos`, `NetworkChaos`, `IOChaos`, `StressChaos`, `TimeChaos` 等 |

**Cron 表达式示例：**

| 表达式 | 说明 |
|--------|------|
| `*/5 * * * *` | 每 5 分钟 |
| `0 */1 * * *` | 每小时整点 |
| `0 0 * * *` | 每天 0 点 |
| `30 9 * * 1-5` | 工作日 9:30 |
| `@every 2m` | 每 2 分钟 (简化语法) |
| `@every 30s` | 每 30 秒 |

**完整示例 - 每 2 分钟随机杀死一个 DataNode：**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: Schedule
metadata:
  name: datanode-periodic-kill
  namespace: chaos-testing
spec:
  schedule: "@every 2m"
  concurrencyPolicy: Forbid
  historyLimit: 5
  type: PodChaos
  podChaos:
    action: pod-kill
    mode: one
    gracePeriod: 0
    selector:
      namespaces:
        - chaos-testing
      labelSelectors:
        app.kubernetes.io/instance: my-milvus
        app.kubernetes.io/component: datanode
```

**Schedule 也支持持续性 Chaos：**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: Schedule
metadata:
  name: periodic-network-delay
  namespace: chaos-testing
spec:
  schedule: "0 */1 * * *"       # 每小时执行一次
  type: NetworkChaos
  networkChaos:
    action: delay
    mode: all
    duration: "5m"              # 每次持续 5 分钟
    selector:
      namespaces:
        - chaos-testing
      labelSelectors:
        app.kubernetes.io/instance: my-milvus
        app.kubernetes.io/component: querynode
    delay:
      latency: "200ms"
      jitter: "50ms"
```

**验证 Schedule：**

```bash
# 查看 Schedule 状态
kubectl get schedule -n chaos-testing

# 查看 Schedule 详情
kubectl describe schedule -n chaos-testing <name>

# 查看由 Schedule 创建的 Chaos 历史
kubectl get podchaos -n chaos-testing -l chaos-mesh.org/schedule=<schedule-name>
```

---

## 三、PodChaos - Pod 故障

### 3.1 container-kill (容器重启)

杀死容器进程，Kubernetes 会自动重启容器。**一次性动作**。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: datanode-container-kill
  namespace: chaos-testing
spec:
  action: container-kill   # 杀死容器
  mode: one
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  containerNames:          # 指定要杀死的容器 (Pod 中可能有多个容器)
    - datanode
  # duration: "30s"        # 一次性动作，duration 可省略
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `action` | 是 | 固定为 `container-kill` |
| `containerNames` | 否 | 要杀死的容器名，不指定则杀死第一个容器 |

**验证方法：**
```bash
# 观察 RESTARTS 计数增加
kubectl get pod -n <namespace> -l <labels> -w

# 检查容器重启时间
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].restartCount}'
```

---

### 3.2 pod-kill (Pod 删除重建)

删除 Pod，由 Deployment/StatefulSet 重新创建。**一次性动作**。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: datanode-pod-kill
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: one
  gracePeriod: 0           # 0 = 立即删除 (--force)，>0 = 等待优雅终止
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  # duration 对一次性动作无实际作用，可省略
```

**字段说明：**
| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `gracePeriod` | 否 | 0 | 优雅终止等待时间 (秒)。0=强制删除，30=等待30s |

**验证方法：**
```bash
# 观察 Pod 名称和 IP 变化
kubectl get pod -n <namespace> -l <labels> -o wide -w
```

---

### 3.3 pod-failure (Pod 假死)

使 Pod 进入不可用状态 (容器被暂停)，但不删除 Pod。**持续性动作**，duration 结束后自动恢复。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: datanode-pod-failure
  namespace: chaos-testing
spec:
  action: pod-failure
  mode: one
  duration: "60s"          # 60s 后自动恢复
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
```

**验证方法：**
```bash
# 观察 Pod 状态变为 0/1 Running
kubectl get pod -n <namespace> -l <labels> -w

# 故障期间
NAME                     READY   STATUS    RESTARTS
my-datanode-xxx          0/1     Running   1

# 恢复后
NAME                     READY   STATUS    RESTARTS
my-datanode-xxx          1/1     Running   2
```

---

## 四、NetworkChaos - 网络故障

### 4.1 partition (网络分区)

阻断两组 Pod 之间的网络通信。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: datanode-etcd-partition
  namespace: chaos-testing
spec:
  action: partition
  mode: one
  duration: "30s"
  selector:                # 源：被隔离的 Pod
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  direction: both          # 双向隔离
  target:                  # 目标：被隔离的对端
    mode: all
    selector:
      namespaces:
        - chaos-testing
      labelSelectors:
        app.kubernetes.io/instance: my-milvus-etcd
        app.kubernetes.io/name: etcd
```

**字段说明：**
| 字段 | 必填 | 可选值 | 说明 |
|------|------|--------|------|
| `direction` | 否 | `to`, `from`, `both` | 隔离方向。`both`=双向 |
| `target` | 是 | - | 隔离的对端 Pod 选择器 |

**验证方法：**
```bash
# 检查应用日志中的连接错误
kubectl logs -n <namespace> <pod-name> --tail=50 | grep -i "error\|timeout\|deadline"

# 典型错误：
# rpc error: code = DeadlineExceeded desc = context deadline exceeded
```

---

### 4.2 delay (网络延迟)

为网络流量添加延迟。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: querynode-network-delay
  namespace: chaos-testing
spec:
  action: delay
  mode: all
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: querynode
  delay:
    latency: "500ms"       # 基础延迟
    jitter: "100ms"        # 延迟抖动 (随机 ±100ms)
    correlation: "50"      # 相关性 (0-100)，连续包的延迟相似度
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `latency` | 是 | 基础延迟，支持 `ms`, `s`, `m` 单位 |
| `jitter` | 否 | 延迟抖动范围 |
| `correlation` | 否 | 0-100，值越大连续包延迟越相似 |

**环境要求：**
```bash
# 需要加载内核模块
modprobe sch_netem
```

**验证方法：**
```bash
# 检查 chaos-daemon 日志
kubectl logs -n chaos-testing -l app.kubernetes.io/component=chaos-daemon --tail=20 | grep netem

# 成功标志：
# tc qdisc add dev eth0 root handle 1: netem delay 500ms 100ms 50.000000
```

---

### 4.3 bandwidth (带宽限制)

限制网络带宽。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: datanode-bandwidth-limit
  namespace: chaos-testing
spec:
  action: bandwidth
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  bandwidth:
    rate: "1mbps"          # 带宽限制
    limit: 100             # 队列长度 (packets)
    buffer: 10000          # 缓冲区大小 (bytes)
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `rate` | 是 | 带宽限制，支持 `bps`, `kbps`, `mbps`, `gbps` |
| `limit` | 是 | 等待队列长度 (packets) |
| `buffer` | 是 | 令牌桶缓冲区大小 (bytes) |

**验证方法：**
```bash
# 检查 chaos-daemon 日志
kubectl logs -n chaos-testing -l app.kubernetes.io/component=chaos-daemon --tail=20 | grep tbf

# 成功标志：
# tc qdisc add dev eth0 root handle 1: tbf rate 1mbps burst 10000 limit 100
```

---

### 4.4 loss (丢包)

随机丢弃网络包。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: datanode-packet-loss
  namespace: chaos-testing
spec:
  action: loss
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  loss:
    loss: "25"             # 丢包率 25%
    correlation: "50"      # 相关性
```

---

### 4.5 duplicate (包重复)

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: datanode-packet-duplicate
  namespace: chaos-testing
spec:
  action: duplicate
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  duplicate:
    duplicate: "30"        # 30% 的包会被重复发送
    correlation: "50"
```

---

### 4.6 corrupt (包损坏)

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: datanode-packet-corrupt
  namespace: chaos-testing
spec:
  action: corrupt
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  corrupt:
    corrupt: "20"          # 20% 的包会损坏
    correlation: "50"
```

---

## 五、IOChaos - IO 故障

> **重要：** `volumePath` 必须是 Pod 中的**实际挂载点** (PVC, emptyDir, hostPath)，不能是容器镜像内的目录。

### 5.1 latency (IO 延迟)

为文件 IO 操作添加延迟。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: datanode-io-latency
  namespace: chaos-testing
spec:
  action: latency
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  volumePath: /milvus/tools   # ⚠️ 必须是实际挂载点
  delay: "200ms"              # IO 延迟
  percent: 50                 # 影响 50% 的 IO 操作
  methods:                    # 影响的 IO 方法
    - read
    - write
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `volumePath` | 是 | **必须是实际挂载点**，如 PVC 或 emptyDir 的挂载路径 |
| `delay` | 是 | IO 延迟时间 |
| `percent` | 否 | 影响的 IO 操作百分比 (1-100) |
| `methods` | 否 | 影响的 IO 方法列表 |

**可用的 methods：**
```
read, write, open, mkdir, rmdir, opendir, fsync, flush,
release, truncate, getattr, chown, chmod, utimens,
allocate, getlk, setlk, setlkw, statfs, readlink,
symlink, create, access, link, mknod, rename, unlink
```

**如何找到正确的 volumePath：**
```bash
# 查看 Pod 的挂载点
kubectl exec -n <namespace> <pod-name> -- mount | grep -v "proc\|sys\|dev"

# 查看 Pod 的卷配置
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes}' | jq .

# Milvus 常用挂载点
# DataNode/QueryNode: /milvus/tools (emptyDir)
# MinIO: /export (PVC)
```

---

### 5.2 fault (IO 错误)

使 IO 操作返回错误。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: datanode-io-fault
  namespace: chaos-testing
spec:
  action: fault
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  volumePath: /milvus/tools
  errno: 5                    # EIO (I/O error)
  percent: 10                 # 10% 的 IO 返回错误
  methods:
    - write
    - fsync
```

**常用 errno 值：**
| errno | 名称 | 说明 |
|-------|------|------|
| 1 | EPERM | 操作不允许 |
| 2 | ENOENT | 文件不存在 |
| 5 | EIO | I/O 错误 |
| 12 | ENOMEM | 内存不足 |
| 28 | ENOSPC | 磁盘空间不足 |

**验证方法：**
```bash
# 检查 Chaos 状态
kubectl get iochaos -n chaos-testing <name> -o jsonpath='{.status.conditions}' | jq .

# 检查 chaos-daemon 日志
kubectl logs -n chaos-testing -l app.kubernetes.io/component=chaos-daemon --tail=50 | grep toda

# 成功标志：
# toda::jsonrpc: rpc update called
# toda: replace result: Ok(())
```

---

### 5.3 attrOverride (属性覆盖)

修改文件属性返回值。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: datanode-attr-override
  namespace: chaos-testing
spec:
  action: attrOverride
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  volumePath: /milvus/tools
  attr:
    perm: 0000               # 权限设为 0000 (无权限)
```

---

## 六、StressChaos - 资源压力

### 6.1 memory (内存压力)

消耗容器内存。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: querynode-memory-stress
  namespace: chaos-testing
spec:
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: querynode
  stressors:
    memory:
      workers: 2             # 并发 worker 数
      size: "256MB"          # 每个 worker 占用的内存
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `workers` | 否 | 并发压力 worker 数量 |
| `size` | 是 | 每个 worker 占用的内存，支持 `MB`, `GB` |

**验证方法：**
```bash
# 检查 memStress 进程
kubectl exec -n <namespace> <pod-name> -- ps aux | grep memStress

# 检查内存使用
kubectl exec -n <namespace> <pod-name> -- cat /sys/fs/cgroup/memory.current

# 或使用 metrics-server
kubectl top pod -n <namespace> -l <labels>
```

---

### 6.2 cpu (CPU 压力)

消耗容器 CPU。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: datanode-cpu-stress
  namespace: chaos-testing
spec:
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  stressors:
    cpu:
      workers: 2             # 并发 worker 数
      load: 80               # 每个 worker 的 CPU 负载 (%)
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `workers` | 否 | 并发压力 worker 数量 |
| `load` | 否 | 每个 worker 的目标 CPU 负载 (0-100) |

**验证方法：**
```bash
# 检查 stress-ng 进程
kubectl exec -n <namespace> <pod-name> -- ps aux | grep stress

# 检查进程 CPU 使用
kubectl exec -n <namespace> <pod-name> -- top -b -n 1 | head -20
```

---

## 七、TimeChaos - 时钟偏移

修改容器内进程感知的系统时间。

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: TimeChaos
metadata:
  name: datanode-time-offset
  namespace: chaos-testing
spec:
  mode: one
  duration: "120s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  timeOffset: "-5m"          # 时间偏移：向过去偏移 5 分钟
  clockIds:                  # 影响的时钟类型
    - CLOCK_REALTIME
```

**字段说明：**
| 字段 | 必填 | 说明 |
|------|------|------|
| `timeOffset` | 是 | 时间偏移，支持 `s`, `m`, `h`。正数=未来，负数=过去 |
| `clockIds` | 否 | 影响的时钟类型，默认 `CLOCK_REALTIME` |

**可用的 clockIds：**
```
CLOCK_REALTIME           # 系统实时时钟 (最常用)
CLOCK_MONOTONIC          # 单调时钟
CLOCK_PROCESS_CPUTIME_ID # 进程 CPU 时钟
CLOCK_THREAD_CPUTIME_ID  # 线程 CPU 时钟
```

**验证方法：**

> **重要：** `kubectl exec -- date` **无法验证** TimeChaos，因为新启动的进程不被 hook。

```bash
# 正确方法：对比应用日志时间戳与宿主机时间
echo "宿主机时间 (UTC): $(date -u '+%Y-%m-%d %H:%M:%S')"
kubectl logs -n <namespace> <pod-name> --tail=1

# 示例输出 (timeOffset: -5m)：
# 宿主机时间 (UTC): 2025-12-16 10:00:00
# [2025/12/16 09:55:00] [DEBUG] ... ← 应用日志落后 5 分钟
```

---

## 八、验证方法汇总

### 8.1 通用验证步骤

```bash
# 1. 检查 Chaos 资源状态
kubectl get <chaostype> -n chaos-testing <name>

# 2. 查看详细状态
kubectl describe <chaostype> -n chaos-testing <name>

# 3. 检查 conditions
kubectl get <chaostype> -n chaos-testing <name> -o jsonpath='{.status.conditions}' | jq .
```

**成功标志：**
```json
{
  "AllInjected": true,
  "AllRecovered": false,  // 注入中
  "Selected": true
}
```

### 8.2 各类型验证方法速查表

| 类型 | 验证命令 | 成功标志 |
|------|---------|---------|
| **container-kill** | `kubectl get pod -w` | RESTARTS 增加 |
| **pod-kill** | `kubectl get pod -o wide -w` | Pod 名称/IP 变化 |
| **pod-failure** | `kubectl get pod -w` | `0/1 Running` |
| **partition** | `kubectl logs <pod>` | `DeadlineExceeded` 错误 |
| **delay** | `kubectl logs chaos-daemon` | `netem delay` 命令成功 |
| **bandwidth** | `kubectl logs chaos-daemon` | `tbf rate` 命令成功 |
| **IOChaos** | `kubectl logs chaos-daemon \| grep toda` | `replace result: Ok(())` |
| **memory** | `kubectl exec <pod> -- ps aux \| grep memStress` | memStress 进程存在 |
| **cpu** | `kubectl exec <pod> -- ps aux \| grep stress` | stress-ng 进程存在 |
| **timeOffset** | 对比应用日志时间戳 | 时间戳偏移符合配置 |

### 8.3 chaos-daemon 日志查看

```bash
# 找到目标 Pod 所在节点的 chaos-daemon
NODE=$(kubectl get pod -n <namespace> <pod-name> -o jsonpath='{.spec.nodeName}')
DAEMON=$(kubectl get pods -n chaos-testing -l app.kubernetes.io/component=chaos-daemon \
  --field-selector spec.nodeName=$NODE -o jsonpath='{.items[0].metadata.name}')

# 查看日志
kubectl logs -n chaos-testing $DAEMON --tail=50
```

---

## 九、常见问题

### 9.1 NetworkChaos delay/bandwidth 失败

**错误：** `Error: Specified qdisc kind is unknown`

**原因：** 节点缺少 `sch_netem` 内核模块

**解决：**
```bash
# 在每个 K8s 节点上执行
modprobe sch_netem

# 持久化
echo "sch_netem" | sudo tee /etc/modules-load.d/netem.conf
```

---

### 9.2 IOChaos 注入失败

**错误：** `toda startup takes too long or an error occurs`

**原因：** `volumePath` 不是实际挂载点

**解决：**
```bash
# 查找实际挂载点
kubectl exec -n <namespace> <pod-name> -- mount | grep -v "proc\|sys\|dev"

# 使用正确的挂载点
# ❌ volumePath: /milvus        (容器镜像目录)
# ✅ volumePath: /milvus/tools  (emptyDir 挂载点)
```

---

### 9.3 TimeChaos 用 date 命令验证无效

**现象：** `kubectl exec -- date` 显示正常时间

**原因：** TimeChaos 通过 ptrace hook 已存在进程的 `clock_gettime`，新启动的进程不受影响

**解决：** 通过应用日志时间戳验证，而非 `date` 命令

---

### 9.4 Chaos 删除卡住

**现象：** `kubectl delete` 一直等待

**解决：**
```bash
# 强制删除
kubectl delete <chaostype> -n chaos-testing <name> --force --grace-period=0

# 如果仍然卡住，移除 finalizer
kubectl patch <chaostype> -n chaos-testing <name> -p '{"metadata":{"finalizers":[]}}' --type=merge
```

---

### 9.5 selector 没有匹配到任何 Pod

**诊断：**
```bash
# 检查 Chaos 状态
kubectl describe <chaostype> -n chaos-testing <name> | grep -A5 "Status:"

# 如果 Selected: false，检查 selector 配置
# 手动验证 selector
kubectl get pods -n <target-namespace> -l <label-selector>
```

---

## 附录：完整示例

### A. Milvus DataNode 综合故障测试

```yaml
# 1. 容器崩溃测试
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: milvus-datanode-crash
  namespace: chaos-testing
spec:
  action: container-kill
  mode: one
  selector:
    namespaces:
      - milvus
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  containerNames:
    - datanode
  duration: "30s"
---
# 2. 与 etcd 网络分区
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: milvus-datanode-etcd-partition
  namespace: chaos-testing
spec:
  action: partition
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - milvus
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  direction: both
  target:
    mode: all
    selector:
      namespaces:
        - milvus
      labelSelectors:
        app.kubernetes.io/name: etcd
---
# 3. IO 延迟
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: milvus-datanode-io-latency
  namespace: chaos-testing
spec:
  action: latency
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - milvus
    labelSelectors:
      app.kubernetes.io/instance: my-milvus
      app.kubernetes.io/component: datanode
  volumePath: /milvus/tools
  delay: "200ms"
  percent: 50
  methods:
    - read
    - write
```

---

> **文档版本:** 1.0
> **更新日期:** 2025-12-16
> **适用版本:** Chaos Mesh 2.x, Milvus 2.x
