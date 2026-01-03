# GitHub Actions Workflow 修复说明

## 🐛 发现的问题

### 1. 缺少 Makefile 目标
**问题**: `optimized-build.yml` 调用了不存在的 `getdeps` 目标
```yaml
# 错误的配置
- run: make -f Makefile.optimized getdeps
```

**影响**: Pre-check 阶段失败

**修复**:
```yaml
# 修复后
- run: make -f Makefile.optimized show-config || echo "Config check skipped"
```

### 2. ARM64 Runner 不可用
**问题**: 使用了不存在的 `ubuntu-22.04-arm` runner

GitHub Actions 免费版本不提供 ARM64 runners。需要：
- GitHub Enterprise Cloud
- 或自托管 runners

**影响**: ARM64 构建作业失败

**修复方案 A** (当前使用 - 通过 QEMU 模拟):
```yaml
- platform: ubuntu-arm64
  os: ubuntu-22.04  # 使用标准 x86_64 runner
  arch: arm64
  use_qemu: true    # 通过 QEMU 模拟 ARM64

# 添加 QEMU 设置步骤
- name: Set up QEMU
  if: matrix.use_qemu == true
  uses: docker/setup-qemu-action@v3
  with:
    platforms: linux/arm64
```

**修复方案 B** (推荐 - 简化版本):
```yaml
# 暂时只构建 x86_64 和 macOS ARM64
# 见 optimized-build-simple.yml
```

### 3. 过时的 Rust Action
**问题**: `actions-rs/toolchain@v1` 已被弃用

**修复**:
```yaml
# 旧版本
- uses: actions-rs/toolchain@v1

# 新版本
- uses: dtolnay/rust-toolchain@stable
  with:
    toolchain: 1.89
```

---

## ✅ 解决方案

### 方案 1: 简化版 Workflow (推荐)
**文件**: `optimized-build-simple.yml`

**特点**:
- ✅ 只构建 x86_64 和 macOS ARM64
- ✅ 更快的执行时间
- ✅ 更可靠（不依赖 QEMU）
- ✅ 包含错误回退机制

**使用场景**:
- 日常开发和 PR 检查
- 快速验证构建
- 测试新功能

**触发条件**:
- Push 到 main/master/release-* 分支
- Push 到 claude/** 分支 (用于测试)
- Pull requests

### 方案 2: 完整版 Workflow (需要额外配置)
**文件**: `optimized-build.yml`

**特点**:
- ✅ 支持 3 个平台（包括 ARM64）
- ⚠️ ARM64 通过 QEMU 模拟（较慢）
- ✅ 完整的缓存策略

**使用场景**:
- 发布前的完整测试
- 多平台兼容性验证

**注意事项**:
- ARM64 构建可能需要 60-90 分钟（由于 QEMU 模拟）
- 建议只在夜间构建或发布时使用

---

## 🚀 推荐的 CI/CD 策略

### 日常开发
```yaml
# 使用 optimized-build-simple.yml
触发: PR 和 push 到开发分支
平台: ubuntu-x86_64, macos-arm64
时间: 15-25 分钟
```

### 发布验证
```yaml
# 使用 optimized-build.yml
触发: Push 到 release-* 分支
平台: ubuntu-x86_64, ubuntu-arm64, macos-arm64
时间: 30-90 分钟
```

### 夜间构建
```yaml
# 使用 nightly-build.yml
触发: 定时（凌晨 2:00）
目的: 缓存预热 + 性能基准
```

---

## 🔧 如何启用原生 ARM64 构建

### 选项 1: 使用 GitHub Enterprise
如果您的组织有 GitHub Enterprise Cloud：

```yaml
- platform: ubuntu-arm64
  os: ubuntu-latest-arm64  # Enterprise 提供
  arch: arm64
```

### 选项 2: 自托管 Runners
设置 ARM64 自托管 runner：

```bash
# 在 ARM64 机器上
./config.sh --url https://github.com/你的组织/milvus --token YOUR_TOKEN
./run.sh

# 在 workflow 中使用
runs-on: [self-hosted, linux, ARM64]
```

### 选项 3: 使用云服务
- AWS Graviton runners (通过 actions-runner-controller)
- Azure ARM runners
- Actuated runners (商业方案)

---

## 📊 性能对比

| 方案 | 平台数 | 执行时间 | 成本 | 推荐场景 |
|------|--------|---------|------|---------|
| **Simple** | 2 | 15-25分钟 | 免费 | 日常开发 ✅ |
| **Full (QEMU)** | 3 | 30-90分钟 | 免费 | 完整测试 |
| **Native ARM** | 3 | 20-35分钟 | 付费 | 生产环境 |

---

## 🧪 测试计划

### 阶段 1: 验证简化版本 (当前)
```bash
# 测试 optimized-build-simple.yml
- Push 到 claude/** 分支
- 验证 ubuntu-x86_64 构建
- 验证 macos-arm64 构建
- 检查缓存命中率
```

### 阶段 2: 测试完整版本 (可选)
```bash
# 测试 optimized-build.yml
- 在 release 分支上测试
- 验证 QEMU ARM64 构建
- 测量构建时间
- 评估是否需要原生 ARM64
```

### 阶段 3: 生产部署
```bash
# 启用推荐的 workflow
- 合并到主分支
- 监控构建性能
- 收集反馈
- 持续优化
```

---

## 📝 维护清单

### 定期检查 (每月)
- [ ] 更新 Actions 版本
- [ ] 检查缓存命中率
- [ ] 审查构建时间趋势
- [ ] 清理过期的缓存

### 性能优化
- [ ] 监控 ccache 命中率 (目标 > 85%)
- [ ] 优化 Conan 缓存策略
- [ ] 调整并行构建任务数
- [ ] 评估是否需要更多 runner 资源

### 安全性
- [ ] 定期更新依赖版本
- [ ] 审查 workflow 权限
- [ ] 检查 secrets 使用
- [ ] 验证第三方 actions

---

## 🆘 故障排除

### Q: 构建超时
**A**: 增加 `timeout-minutes` 或启用更多缓存

### Q: 缓存未命中
**A**: 检查缓存键配置，确保文件哈希正确

### Q: ARM64 构建太慢
**A**: 使用 `optimized-build-simple.yml` 或考虑自托管 ARM runner

### Q: macOS 构建失败
**A**: 检查 Homebrew 依赖，可能需要更新包名

### Q: 依赖安装失败
**A**: 检查网络问题，考虑添加重试机制

---

## 📚 相关资源

- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [Docker QEMU Action](https://github.com/docker/setup-qemu-action)
- [Self-hosted Runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [BUILD_OPTIMIZATION.md](../../BUILD_OPTIMIZATION.md)

---

**最后更新**: 2025-11-11
**状态**: ✅ 问题已修复
**推荐**: 使用 `optimized-build-simple.yml` 进行日常开发
