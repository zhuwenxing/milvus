# Milvus Chaos 故障注入验证报告

> 测试时间: 2025-12-16
> 测试实例: chaos-playground
> Milvus 版本: 2.6.7

---

## 一、测试环境

### 1.1 Chaos Mesh 环境

```bash
# Chaos Mesh 组件
- chaos-controller-manager: 3 replicas (Running)
- chaos-daemon: DaemonSet (每个节点一个)
- chaos-dashboard: 1 replica (Running)
```

### 1.2 Milvus 实例 (chaos-playground)

| 组件 | 副本数 | 命名空间 |
|-----|--------|---------|
| Proxy | 1 | chaos-testing |
| MixCoord | 1 | chaos-testing |
| DataNode | 3 | chaos-testing |
| QueryNode | 3 | chaos-testing |
| StreamingNode | 1 | chaos-testing |
| etcd | 3 | chaos-testing |
| Kafka | 3 | chaos-testing |
| MinIO | 4 | chaos-testing |

---

## 二、测试结果总结

| # | 故障类型 | 状态 | 验证结果 |
|---|---------|------|---------|
| 1 | PodChaos: container-kill | ✅ 成功 | 容器重启，RESTARTS 增加 |
| 2 | PodChaos: pod-kill (hard) | ✅ 成功 | Pod 删除并重建，IP 变化 |
| 3 | PodChaos: pod-kill (graceful) | ✅ 成功 | 优雅终止后重建 |
| 4 | PodChaos: pod-failure | ✅ 成功 | Pod 假死 (0/1 Running) |
| 5 | NetworkChaos: partition | ✅ 成功 | etcd 连接超时错误 |
| 6 | NetworkChaos: delay | ✅ 成功 | tc netem delay 规则已应用 |
| 7 | NetworkChaos: bandwidth | ✅ 成功 | tc tbf 限速规则已应用 |
| 8 | IOChaos: latency | ✅ 已修复 | volumePath 需指向实际挂载点 |
| 9 | IOChaos: fault | ✅ 已修复 | volumePath 需指向实际挂载点 |
| 10 | StressChaos: memory | ✅ 成功 | 内存增加 178MB → 438MB |
| 11 | StressChaos: cpu | ✅ 成功 | stress-ng 进程运行 |
| 12 | TimeChaos: timeOffset | ✅ 成功 | 应用日志时间戳偏移 5 分钟 |

**成功率: 12/12 (100%)**

---

## 三、详细测试记录

### 3.1 PodChaos: container-kill

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: chaos-playground-datanode-container-kill
  namespace: chaos-testing
spec:
  action: container-kill
  mode: one
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  containerNames:
    - datanode
  duration: "30s"
```

**验证结果:**
```
Before: chaos-playground-milvus-datanode-xxx   RESTARTS: 0
After:  chaos-playground-milvus-datanode-xxx   RESTARTS: 1 (20s ago)
```

**生效表现:** 容器被 kill 后由 Kubernetes 自动重启，RESTARTS 计数增加。

---

### 3.2 PodChaos: pod-kill (hard, gracePeriod=0)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: chaos-playground-pod-kill-hard
  namespace: chaos-testing
spec:
  action: pod-kill
  gracePeriod: 0  # 立即删除，不等待
  mode: one
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
```

**验证结果:**
```
Before: chaos-playground-milvus-datanode-544447fbbc-qshm7  IP: 10.104.19.36   Node: 4am-node28
After:  chaos-playground-milvus-datanode-544447fbbc-qgtdn  IP: 10.104.33.164  Node: 4am-node36
```

**生效表现:** Pod 被强制删除，Kubernetes 在新节点上重新调度创建新 Pod，IP 地址变化。

---

### 3.3 PodChaos: pod-kill (graceful, gracePeriod=30)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: chaos-playground-pod-kill-graceful
  namespace: chaos-testing
spec:
  action: pod-kill
  gracePeriod: 30  # 等待 30s
  mode: one
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: querynode
```

**验证结果:**
- Pod 收到 SIGTERM 信号
- 等待 gracePeriod 后终止
- 新 Pod 在新节点创建

**生效表现:** 优雅终止，允许应用完成清理工作后再重建。

---

### 3.4 PodChaos: pod-failure (进程假死)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: chaos-playground-pod-failure
  namespace: chaos-testing
spec:
  action: pod-failure
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
```

**验证结果:**
```
During Chaos: chaos-playground-milvus-datanode-xxx   0/1 Running   RESTARTS: 1
After Recovery: chaos-playground-milvus-datanode-xxx 1/1 Running   RESTARTS: 2
```

**Chaos 状态:**
```json
{
  "AllInjected": true,
  "AllRecovered": true  // 30s 后自动恢复
}
```

**生效表现:** 容器进入假死状态 (0/1 Running)，duration 结束后自动恢复。

---

### 3.5 NetworkChaos: partition (网络分区)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: chaos-playground-network-partition
  namespace: chaos-testing
spec:
  action: partition
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  direction: both
  target:
    mode: all
    selector:
      namespaces:
        - chaos-testing
      labelSelectors:
        app.kubernetes.io/instance: chaos-playground-etcd
        app.kubernetes.io/name: etcd
```

**验证结果 - 被隔离的 DataNode 日志:**
```
[2025/12/16 09:18:35] Chaos 注入时间
[2025/12/16 09:18:40] {"level":"warn","msg":"retrying of unary invoker failed",
  "error":"rpc error: code = DeadlineExceeded desc = context deadline exceeded"}
[2025/12/16 09:18:45] {"level":"warn","msg":"retrying of unary invoker failed",
  "error":"rpc error: code = DeadlineExceeded desc = context deadline exceeded"}
...
```

**验证结果 - 未被隔离的 DataNode 日志:**
```
[2025/12/16 09:18:59] [DEBUG] ["etcd refreshConfigurations"]  // 正常，无错误
[2025/12/16 09:19:09] [DEBUG] ["etcd refreshConfigurations"]  // 正常，无错误
```

**生效表现:**
- 被隔离的 DataNode 出现大量 `DeadlineExceeded` 错误
- 未被隔离的 DataNode 正常运行
- 对比明显证明网络分区生效

---

### 3.6 NetworkChaos: delay (网络延迟)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: chaos-playground-network-delay
  namespace: chaos-testing
spec:
  action: delay
  mode: all
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: querynode
  delay:
    latency: "500ms"
    jitter: "100ms"
    correlation: "50"
```

**Chaos 状态:**
```json
{
  "Selected": true,
  "AllInjected": true,
  "phase": "Injected"
}
```

**验证结果 - chaos-daemon 日志:**
```
tc qdisc add dev eth0 root handle 1: netem delay 500ms 100ms 50.000000
```

**生效表现:**
- tc netem 规则成功应用到所有 QueryNode
- 网络延迟 500ms ± 100ms (jitter)
- 50% 相关性 (correlation)

**环境要求:**
```bash
# 需要加载 sch_netem 内核模块
modprobe sch_netem
lsmod | grep netem
```

---

### 3.7 NetworkChaos: bandwidth (带宽限制)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: chaos-playground-network-bandwidth
  namespace: chaos-testing
spec:
  action: bandwidth
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  bandwidth:
    rate: "1mbps"
    limit: 100
    buffer: 10000
```

**Chaos 状态:**
```json
{
  "Selected": true,
  "AllInjected": true,
  "phase": "Injected"
}
```

**验证结果 - chaos-daemon 日志:**
```
tc qdisc add dev eth0 root handle 1: tbf rate 1mbps burst 10000 limit 100
```

**生效表现:**
- tc tbf (Token Bucket Filter) 规则成功应用
- 带宽限制为 1Mbps
- burst 10000 bytes, limit 100 packets

---

### 3.8 IOChaos: latency (IO 延迟) - 已修复

**原始错误配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: chaos-playground-io-latency
  namespace: chaos-testing
spec:
  action: latency
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  volumePath: /milvus          # ❌ 错误：这不是实际挂载点
  delay: "200ms"
  percent: 50
  methods:
    - read
    - write
```

**错误信息:**
```
rpc error: code = Unknown desc = toda startup takes too long or an error occurs:
source: /milvus, target: /__chaosfs__milvus__
```

**chaos-daemon 日志 (toda panic):**
```
thread '<unnamed>' panicked at 'Send through channel failed: SendError { .. }', src/jsonrpc.rs:74:22
```

#### 根本原因分析

**问题:** `volumePath: /milvus` 不是一个实际的挂载点，而是容器镜像内的目录。

**DataNode Pod 的卷挂载情况:**
```bash
$ kubectl exec <datanode-pod> -- mount | grep milvus

/dev/mapper/ubuntu--vg-ubuntu--lv on /milvus/tools type ext4 (rw,relatime)
/dev/mapper/ubuntu--vg-ubuntu--lv on /milvus/configs/operator type ext4 (ro,relatime)
```

| 路径 | 类型 | 是否挂载点 |
|------|------|-----------|
| `/milvus` | 容器镜像目录 | ❌ 否 |
| `/milvus/tools` | emptyDir | ✅ 是 |
| `/milvus/configs/operator` | configMap | ✅ 是 (只读) |

**IOChaos 工作原理:**
1. toda 使用 FUSE 创建代理文件系统
2. 将 `volumePath` 绑定挂载到 `/__chaosfs__<path>__`
3. 当 `volumePath` 不是实际挂载点时，FUSE 绑定挂载失败，导致 toda panic

#### 修复方案

**修正后的配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: chaos-playground-io-latency
  namespace: chaos-testing
spec:
  action: latency
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  volumePath: /milvus/tools    # ✅ 正确：使用实际挂载点 (emptyDir)
  delay: "200ms"
  percent: 50
  methods:
    - read
    - write
```

**修复后验证结果:**
```json
{
  "Selected": true,
  "AllInjected": true,
  "AllRecovered": true
}
```

**chaos-daemon 日志 (成功):**
```
toda::jsonrpc: rpc update called
toda::jsonrpc: rpc get_status called
toda::replacer::fd_replacer: running fd replacer
toda::replacer::mmap_replacer: running mmap replacer
toda: replace result: Ok(())
toda: recover successfully
```

#### 最佳实践

对于 Milvus IOChaos 测试，建议：

1. **使用 emptyDir 挂载点** (如 `/milvus/tools`)
2. **为 DataNode 添加专门的数据卷** 用于 chaos 测试
3. **测试 MinIO 的 IO 故障** 应在 MinIO Pod 上注入，而非 Milvus 组件

---

### 3.9 IOChaos: fault (IO 错误) - 已修复

**根本原因:** 同 IOChaos: latency，`volumePath` 必须指向实际挂载点

**修复方案:**
```yaml
spec:
  action: fault
  volumePath: /milvus/tools    # ✅ 使用实际挂载点
  errno: 5  # EIO
  percent: 10
  methods:
    - write
    - fsync
```

---

### 3.10 StressChaos: memory (内存压力)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: chaos-playground-stress-memory
  namespace: chaos-testing
spec:
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: querynode
  stressors:
    memory:
      workers: 2
      size: "256MB"
```

**验证结果:**

| 指标 | Before | After |
|------|--------|-------|
| kubectl top | 178Mi | - |
| cgroup memory | ~178 MB | **438 MB** |

**memStress 进程:**
```
root  201  memStress --workers 2 --size 256MB
root  206  memStress --size 256MB --workers 2 --time 0s --client 1
root  211  memStress --size 256MB --workers 2 --time 0s --client 1
```

**生效表现:**
- memStress 进程运行
- 2 个 workers 各占用约 128MB
- Pod 内存从 178MB 增加到 438MB

---

### 3.11 StressChaos: cpu (CPU 压力)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: chaos-playground-stress-cpu
  namespace: chaos-testing
spec:
  mode: one
  duration: "30s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  stressors:
    cpu:
      workers: 2
      load: 80
```

**验证结果 - stress-ng 进程:**
```
root  1219  stress-ng --cpu-load-slice 10 --cpu-method sqrt --cpu 2 --cpu-load 80
root  1220  58.4%  stress-ng-cpu [run]
root  1221  61.5%  stress-ng-cpu [run]
```

**生效表现:**
- stress-ng 进程运行
- 2 个 workers 各占用约 60% CPU
- 总 CPU 负载显著增加

---

### 3.12 TimeChaos: timeOffset (时钟偏移)

**测试配置:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: TimeChaos
metadata:
  name: chaos-playground-time-offset
  namespace: chaos-testing
spec:
  mode: one
  duration: "120s"
  selector:
    namespaces:
      - chaos-testing
    labelSelectors:
      app.kubernetes.io/instance: chaos-playground
      app.kubernetes.io/component: datanode
  timeOffset: "-5m"
  clockIds:
    - CLOCK_REALTIME
```

**Chaos 状态:**
```json
{
  "Selected": true,
  "AllInjected": true,
  "AllRecovered": true,
  "phase": "Injected → Not Injected (duration 结束后)"
}
```

**验证结果 - 时间戳对比:**
```
=== 注入期间 (09:53:13 - 09:55:13 UTC) ===
宿主机时间 (UTC): 2025-12-16 09:55:12
DataNode 日志时间戳: 2025/12/16 09:50:06
时间差: ~5 分钟 (与配置的 -5m 偏移一致)

=== 恢复后 ===
宿主机时间 (UTC): 2025-12-16 09:55:40
DataNode 日志时间戳: 2025/12/16 09:55:36
时间差: ~4 秒 (恢复正常)
```

**生效表现:**
- DataNode 进程感知到的时间落后宿主机约 5 分钟
- 应用日志时间戳明显偏移
- duration 结束后时间自动恢复正常

**重要说明:**
| 验证方法 | 有效性 | 说明 |
|---------|--------|------|
| `kubectl exec -- date` | ❌ 无效 | 新启动的进程不被 hook |
| 应用日志时间戳对比 | ✅ 有效 | 已存在的应用进程被 hook |

**验证原理:**
- TimeChaos 通过 ptrace 机制 hook 已存在进程的 `clock_gettime` 系统调用
- `kubectl exec` 启动的是新进程，不在 hook 范围内
- 正确的验证方式是对比应用日志时间戳与宿主机时间

---

## 四、验证方法总结

### 4.1 PodChaos 验证方法

```bash
# 验证 container-kill / pod-kill
kubectl get pod -n <namespace> -l <labels> -w

# 检查 RESTARTS 变化
kubectl get pod -n <namespace> <pod-name> -o jsonpath='{.status.containerStatuses[0].restartCount}'

# 检查 Pod IP 变化 (pod-kill)
kubectl get pod -n <namespace> -l <labels> -o wide
```

### 4.2 NetworkChaos 验证方法

```bash
# 方法1: 检查应用日志中的连接错误
kubectl logs -n <namespace> <pod-name> --tail=50 | grep -i "error\|timeout\|deadline"

# 方法2: 从 Pod 内部测试连通性
kubectl exec -n <namespace> <pod-name> -- nc -zv <target-host> <port>

# 方法3: 对比被隔离和未隔离的 Pod 日志
```

### 4.3 StressChaos 验证方法

```bash
# 验证 stress 进程
kubectl exec -n <namespace> <pod-name> -- ps aux | grep -E "stress|memStress"

# 检查内存使用 (cgroup)
kubectl exec -n <namespace> <pod-name> -- cat /sys/fs/cgroup/memory.current

# 检查资源使用 (metrics-server)
kubectl top pod -n <namespace> -l <labels>
```

### 4.4 IOChaos 验证方法

```bash
# 检查 IOChaos 状态
kubectl get iochaos -n <namespace> <name> -o jsonpath='{.status.conditions}' | jq .

# 检查 chaos-daemon 日志确认 toda 运行
kubectl logs -n chaos-testing -l app.kubernetes.io/component=chaos-daemon --tail=50 | grep -i toda

# 验证 Pod 内的挂载点
kubectl exec -n <namespace> <pod-name> -- mount | grep <volumePath>
```

**成功标志:**
```
toda::jsonrpc: rpc update called
toda: replace result: Ok(())
```

### 4.5 TimeChaos 验证方法

**重要:** `kubectl exec -- date` 无法验证 TimeChaos 效果，因为新启动的进程不被 hook。

```bash
# 步骤1: 检查 Chaos 状态确认注入成功
kubectl get timechaos -n <namespace> <name> -o jsonpath='{.status.conditions}' | jq .

# 步骤2: 对比宿主机时间和应用日志时间戳
echo "宿主机时间 (UTC): $(date -u '+%Y-%m-%d %H:%M:%S')"
kubectl logs -n <namespace> <pod-name> --tail=1

# 步骤3: 计算时间差
# 时间差应该接近配置的 timeOffset 值
```

**验证示例:**
```
# 配置 timeOffset: "-5m" 时
宿主机时间: 2025-12-16 09:55:12 UTC
应用日志时间: 2025-12-16 09:50:06 UTC
时间差: ~5 分钟 ✅ TimeChaos 生效
```

**注意事项:**
- 必须在 duration 期间验证，过期后时间会恢复正常
- 只影响已存在的进程，不影响新启动的进程

---

## 五、阻塞问题及解决方案

### 5.1 NetworkChaos delay/bandwidth 阻塞

**问题:** `Error: Specified qdisc kind is unknown`

**原因:** K8s 节点缺少 `sch_netem` 内核模块

**解决方案:**
```bash
# 在每个 K8s 节点上执行
sudo modprobe sch_netem

# 持久化配置 (添加到 /etc/modules-load.d/)
echo "sch_netem" | sudo tee /etc/modules-load.d/netem.conf

# 验证
lsmod | grep netem
```

### 5.2 IOChaos latency/fault - 已修复

**问题:** `toda startup takes too long or an error occurs`

**错误日志:**
```
thread '<unnamed>' panicked at 'Send through channel failed: SendError { .. }', src/jsonrpc.rs:74:22
```

**根本原因:** `volumePath` 指向了容器镜像目录而非实际挂载点

| 配置 | 路径 | 结果 |
|------|------|------|
| ❌ 错误 | `volumePath: /milvus` | toda panic |
| ✅ 正确 | `volumePath: /milvus/tools` | 注入成功 |

**IOChaos 要求:**
- `volumePath` 必须是 Pod 中的**实际挂载点** (PVC、emptyDir、hostPath 等)
- 不能是容器镜像内的普通目录

**检查 Pod 挂载点的方法:**
```bash
# 查看 Pod 的卷挂载
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes}' | jq .

# 查看容器内的挂载情况
kubectl exec <pod-name> -- mount | grep -v "proc\|sys\|dev"
```

**Milvus 组件常用挂载点:**

| 组件 | 可用挂载点 | 卷类型 |
|------|-----------|--------|
| DataNode | `/milvus/tools` | emptyDir |
| QueryNode | `/milvus/tools` | emptyDir |
| MinIO | `/export` | PVC |

**修复后的配置示例:**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: milvus-io-latency
spec:
  action: latency
  volumePath: /milvus/tools    # ✅ 使用实际挂载点
  delay: "200ms"
  percent: 50
  methods:
    - read
    - write
```

---

## 六、测试 YAML 文件

所有测试 YAML 文件位于: `/tmp/chaos-tests/`

```
/tmp/chaos-tests/
├── 01-pod-kill-hard.yaml
├── 02-pod-kill-graceful.yaml
├── 03-pod-failure.yaml
├── 04-network-partition.yaml
├── 05-network-delay.yaml
├── 06-network-bandwidth.yaml
├── 07-io-latency.yaml
├── 08-io-fault.yaml
├── 09-stress-memory.yaml
├── 10-stress-cpu.yaml
└── 11-time-offset.yaml
```

---

## 七、结论

### 7.1 可用的故障类型

| 故障类型 | 适用场景 | 注意事项 |
|---------|---------|---------|
| **PodChaos: container-kill** | 验证进程级恢复、checkpoint 机制 | - |
| **PodChaos: pod-kill** | 验证完全故障恢复、服务发现、IP 变化 | - |
| **PodChaos: pod-failure** | 验证假死检测、健康检查 | - |
| **NetworkChaos: partition** | 验证网络分区、脑裂防护 | - |
| **IOChaos: latency** | 验证存储慢响应、超时重试 | volumePath 必须是实际挂载点 |
| **IOChaos: fault** | 验证 IO 错误处理、数据持久性 | volumePath 必须是实际挂载点 |
| **StressChaos: memory** | 验证 OOM 处理、内存管理 | - |
| **StressChaos: cpu** | 验证 CPU 饱和、超时处理 | - |
| **TimeChaos: timeOffset** | 验证时钟容忍度 | 通过应用日志时间戳验证，不能用 `kubectl exec date` |

### 7.2 环境要求

| 故障类型 | 环境要求 |
|---------|---------|
| NetworkChaos: delay | 需加载 `sch_netem` 内核模块 |
| NetworkChaos: bandwidth | 需加载 `sch_netem` 内核模块 |

**加载方法:**
```bash
# 临时加载
modprobe sch_netem

# 持久化 (开机自动加载)
echo "sch_netem" | sudo tee /etc/modules-load.d/netem.conf
```

### 7.3 IOChaos 配置要点

**关键配置:** `volumePath` 必须指向 Pod 中的实际挂载点

```yaml
# ❌ 错误 - /milvus 是容器镜像目录
volumePath: /milvus

# ✅ 正确 - /milvus/tools 是 emptyDir 挂载点
volumePath: /milvus/tools
```

**查找可用挂载点:**
```bash
kubectl exec <pod-name> -- mount | grep -E "emptyDir|pvc"
```

### 7.4 建议

1. **优先使用已验证可用的故障类型** 进行 Milvus 稳定性测试
2. **修复节点环境** 以支持更多故障类型
3. **结合应用日志验证** 确认故障真正生效
4. **先单故障后组合** 逐步增加测试复杂度
