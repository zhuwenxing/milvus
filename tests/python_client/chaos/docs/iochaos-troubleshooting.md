# IOChaos 问题排查指南

## 概述

本文档总结了在 Milvus 混沌测试中使用 Chaos Mesh IOChaos 时遇到的问题、原因分析及解决方法。

---

## 问题 1：注入失败 - `toda startup takes too long`

### 现象

```
rpc error: code = Unknown desc = toda startup takes too long or an error occurs:
source: /var/lib/milvus/data, target: /var/lib/milvus/__chaosfs__data__
```

### 原因分析

IOChaos 的工作原理：
1. 使用 `ptrace` 系统调用暂停目标进程
2. 通过 FUSE 文件系统 (toda) 替换目标路径的文件描述符
3. 恢复进程运行

当目标进程有**大量打开的文件**或**密集 IO 操作**时：
- 替换过程耗时过长
- 进程被暂停期间，Kubernetes liveness probe 超时
- kubelet 判定容器不健康并终止容器

### 解决方法

**方案 1：禁用 liveness probe（推荐用于混沌测试）**

```yaml
# Helm values.yaml
queryNode:
  livenessProbe:
    enabled: false
```

**方案 2：增加 liveness probe 容忍度**

```yaml
queryNode:
  livenessProbe:
    failureThreshold: 20
    timeoutSeconds: 30
```

**方案 3：在低负载时注入**

在 Milvus 空闲时（无查询、无数据加载）应用 IOChaos。

---

## 问题 2：IOChaos 导致 Pod Crash

### 现象

- Pod 状态显示 `Restart: 1`
- 容器 `exitCode: 1`
- 日志中无明显错误，进程突然退出

### 原因分析

`ptrace` 暂停进程时间过长，导致 Milvus 内部组件超时：

| 组件 | 超时影响 |
|------|----------|
| etcd session | 会话断开，节点被认为离线 |
| pulsar 心跳 | 连接断开，消息丢失 |
| gRPC 请求 | 内部调用超时 |

Milvus 检测到这些异常后主动 crash。

### 解决方法

- 接受偶发重启作为混沌测试的预期行为
- 或使用 NetworkChaos 替代 IOChaos 模拟存储问题

---

## 问题 3：IOChaos 无法正常删除

### 现象

执行 `kubectl delete iochaos <name>` 后，资源一直处于 Terminating 状态：

```yaml
metadata:
  deletionTimestamp: "2025-12-19T06:52:48Z"
  finalizers:
  - chaos-mesh/records  # 卡在这里无法移除
```

### 原因分析

问题链：

```
1. IOChaos 注入 → toda 进程创建 FUSE 文件系统代理
                    ↓
2. IOChaos 导致 Pod 重启 → toda 进程随之消亡
                    ↓
3. 删除 IOChaos → chaos-daemon 尝试 kill toda
                    ↓
4. toda 进程已不存在 → 清理失败（os: process already finished）
                    ↓
5. FUSE 无法正常卸载 → finalizer 无法移除
                    ↓
6. IOChaos 卡在删除状态
```

### 解决方法

**强制移除 finalizer：**

```bash
kubectl patch iochaos <name> -n chaos-testing \
  -p '{"metadata":{"finalizers":null}}' --type=merge
```

**批量清理所有卡住的 IOChaos：**

```bash
kubectl get iochaos -n chaos-testing -o name | xargs -I {} \
  kubectl patch {} -n chaos-testing -p '{"metadata":{"finalizers":null}}' --type=merge

kubectl delete iochaos --all -n chaos-testing
```

---

## 问题 4：残留 `__chaosfs__` 目录

### 现象

Pod 内存在残留目录，后续 IOChaos 注入失败：

```bash
$ ls -la /var/lib/milvus/
drwxrwxrwx 3 root root 4096 __chaosfs__data__  ← 残留目录
drwxr-xr-x 3 root root 4096 data
```

### 原因分析

- IOChaos 注入时创建 `__chaosfs__<原目录名>__` 作为 FUSE 代理
- IOChaos 清理失败后，代理目录残留
- 后续 IOChaos 尝试再次创建代理时失败

### 解决方法

**重启受影响的 Pod：**

```bash
kubectl delete pod <pod-name> -n chaos-testing
```

**批量重启所有 querynode：**

```bash
kubectl delete pod -l component=querynode -n chaos-testing
```

---

## 问题汇总表

| 问题 | 错误信息 | 原因 | 解决方法 |
|------|----------|------|----------|
| 注入失败 | `toda startup takes too long` | ptrace 暂停进程超时 | 禁用 liveness probe |
| Pod crash | `exitCode: 1` | 内部组件超时 | 低负载时注入 / 接受重启 |
| 无法删除 | 卡在 Terminating | toda 进程已消亡 | 移除 finalizer |
| 残留目录 | `__chaosfs__` 存在 | 清理失败 | 重启 pod |

---

## 验证 IOChaos 生效

### 1. 检查 IOChaos 注入状态

```bash
# 查看 IOChaos 状态
kubectl get iochaos <name> -n chaos-testing -o jsonpath='{.status.conditions}' | python3 -m json.tool

# 预期输出（注入成功）：
# {
#     "status": "True",
#     "type": "AllInjected"
# }
```

### 2. 查看注入的 Pod

```bash
# 获取被注入的 Pod ID
kubectl get iochaos <name> -n chaos-testing -o jsonpath='{.status.experiment.containerRecords[0].id}'

# 输出示例：chaos-testing/longrun-chaos-test-milvus-querynode-xxx/querynode
```

### 3. 验证 IO 延迟效果

```bash
# 进入被注入的 pod 测试写入延迟
kubectl exec <pod-name> -n chaos-testing -- bash -c '
echo "=== 测试注入目录 (应有延迟) ==="
time dd if=/dev/zero of=/var/lib/milvus/data/test_write bs=1k count=1 2>&1

echo ""
echo "=== 测试读取延迟 ==="
time dd if=/var/lib/milvus/data/test_write of=/dev/null bs=1k 2>&1

echo ""
echo "=== 对比：非注入目录 (无延迟) ==="
time dd if=/dev/zero of=/tmp/test_write bs=1k count=1 2>&1

rm -f /var/lib/milvus/data/test_write /tmp/test_write
'
```

**预期输出示例（配置 200ms 延迟）：**

```
=== 测试注入目录 (应有延迟) ===
1+0 records in
1+0 records out
1024 bytes (1.0 kB, 1.0 KiB) copied, 0.202 s, 5.1 kB/s   ← 约 200ms

=== 测试读取延迟 ===
1+0 records in
1+0 records out
1024 bytes (1.0 kB, 1.0 KiB) copied, 0.201 s, 5.1 kB/s   ← 约 200ms

=== 对比：非注入目录 (无延迟) ===
1+0 records in
1+0 records out
1024 bytes (1.0 kB, 1.0 KiB) copied, 0.000036 s, 28.3 MB/s   ← 无延迟
```

### 4. 检查 chaosfs 代理目录

```bash
# 注入成功后会创建 __chaosfs__ 代理目录
kubectl exec <pod-name> -n chaos-testing -- ls -la /var/lib/milvus/

# 预期输出：
# drwxrwxrwx 3 root root 4096 __chaosfs__data__   ← FUSE 代理目录
# drwxr-xr-x 3 root root 4096 data                ← 原始目录
```

### 5. 完整验证脚本

```bash
#!/bin/bash
# 验证 IOChaos 是否生效的完整脚本

IOCHAOS_NAME=${1:-"test-iochaos"}
NAMESPACE=${2:-"chaos-testing"}

echo "=== 1. 检查 IOChaos 状态 ==="
kubectl get iochaos $IOCHAOS_NAME -n $NAMESPACE -o jsonpath='{.status.conditions}' | python3 -m json.tool

echo ""
echo "=== 2. 获取注入的 Pod ==="
POD_ID=$(kubectl get iochaos $IOCHAOS_NAME -n $NAMESPACE -o jsonpath='{.status.experiment.containerRecords[0].id}')
POD_NAME=$(echo $POD_ID | cut -d'/' -f2)
echo "Injected Pod: $POD_NAME"

echo ""
echo "=== 3. 检查 chaosfs 目录 ==="
kubectl exec $POD_NAME -n $NAMESPACE -- ls -la /var/lib/milvus/ 2>/dev/null | grep -E "chaosfs|data"

echo ""
echo "=== 4. 验证 IO 延迟 ==="
kubectl exec $POD_NAME -n $NAMESPACE -- bash -c '
echo "写入测试:"
time dd if=/dev/zero of=/var/lib/milvus/data/test bs=1k count=1 2>&1
echo ""
echo "读取测试:"
time dd if=/var/lib/milvus/data/test of=/dev/null bs=1k 2>&1
rm -f /var/lib/milvus/data/test
'

echo ""
echo "=== 5. Pod 状态 ==="
kubectl get pod $POD_NAME -n $NAMESPACE -o wide
```

### 6. Pod 重启后 IOChaos 仍然生效

IOChaos 是持续性的 CRD，当目标 Pod 重启后：
- chaos-mesh controller 会检测到新 Pod
- 自动重新注入 IOChaos
- IO 延迟继续生效

**验证方法：**

```bash
# 1. 创建 IOChaos 并验证生效
# 2. 检查 Pod 是否有重启
kubectl get pod <pod-name> -n chaos-testing
# 输出示例：Restarts: 1 (58s ago)

# 3. 再次验证 IO 延迟（重启后仍应有延迟）
kubectl exec <pod-name> -n chaos-testing -- bash -c \
  'time dd if=/dev/zero of=/var/lib/milvus/data/test bs=1k count=1 2>&1; rm -f /var/lib/milvus/data/test'
```

---

## 最佳实践

### 1. Jenkins Pipeline 清理逻辑

```groovy
// 在每次 IOChaos 测试后添加清理步骤
sh '''
# 移除所有 IOChaos 的 finalizer
kubectl get iochaos -n chaos-testing -o name 2>/dev/null | xargs -I {} \
  kubectl patch {} -n chaos-testing -p '{"metadata":{"finalizers":null}}' --type=merge || true

# 删除所有 IOChaos
kubectl delete iochaos --all -n chaos-testing || true

# 可选：重启有残留的 pod
# kubectl delete pod -l component=querynode -n chaos-testing
'''
```

### 2. Helm Values 配置

```yaml
# 混沌测试专用配置
queryNode:
  livenessProbe:
    enabled: false  # 禁用 liveness probe 以支持 IOChaos

dataNode:
  livenessProbe:
    enabled: false
```

### 3. IOChaos 配置建议

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: example-io-latency
spec:
  action: latency
  delay: 100ms          # 延迟不宜过大
  duration: 5m          # 持续时间不宜过长
  mode: one             # 建议从单个 pod 开始测试
  percent: 50           # 不要 100%，留有余地
  methods:
    - read
  selector:
    labelSelectors:
      component: querynode
    namespaces:
      - chaos-testing
  volumePath: /var/lib/milvus/data
```

---

## 相关资源

### GitHub Issues

- [#4550 - IOChaos latency experiment - toda startup takes too long](https://github.com/chaos-mesh/chaos-mesh/issues/4550)
- [#2445 - IOChaos unavailable](https://github.com/chaos-mesh/chaos-mesh/issues/2445)
- [#2143 - Error in IO Experiments](https://github.com/chaos-mesh/chaos-mesh/issues/2143)

### 状态

- 问题仍 **Open**，暂无官方修复
- 影响版本：Chaos Mesh v2.7.0+

---

## 更新记录

| 日期 | 更新内容 |
|------|----------|
| 2025-12-19 | 初始版本，总结 IOChaos 常见问题及解决方法 |
| 2025-12-19 | 添加验证 IOChaos 生效的脚本和方法 |
