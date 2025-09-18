# CDC Sync Test Cases

重构后的 CDC 同步测试用例，按功能类别组织到不同的文件中。

## 文件结构

```
cdc/
├── conftest.py                     # pytest 配置和fixtures
├── testcases/
│   ├── __init__.py                 # Python 包初始化
│   ├── base.py                     # 基础测试类和工具函数
│   ├── test_database.py            # 数据库操作测试
│   ├── test_resource_group.py      # 资源组操作测试
│   ├── test_rbac.py                # RBAC 操作测试
│   ├── test_collection.py          # 集合 DDL 操作测试
│   ├── test_index.py               # 索引操作测试
│   ├── test_dml.py                 # 数据操作测试
│   ├── test_collection_management.py # 集合管理操作测试
│   ├── test_alias.py               # 别名操作测试
│   └── test_partition.py           # 分区操作测试
└── README.md                       # 本文档
```

## 主要改进

### 1. 代码结构优化
- **模块化设计**: 将大文件拆分为多个小文件，每个文件专注于一类操作
- **基础类抽离**: 公共工具和方法放在 `testcases/base.py` 中
- **配置统一**: pytest 配置和 fixtures 放在 `conftest.py` 中

### 2. 测试逻辑重构
- **移除冗余异常处理**: 删除所有不必要的 try-except-finally 结构
- **移除 assert True**: 让真正的错误被正确抛出，提高测试可靠性
- **统一资源管理**: 使用 setup_method 和 teardown_method 管理资源

### 3. 清理逻辑优化
- **只清理上游**: teardown 只清理上游资源，下游通过 CDC 自动同步
- **减少重复代码**: 统一的清理逻辑，避免代码重复

## 使用方法

### 运行所有测试
```bash
cd /Users/zilliz/workspace/milvus/tests/python_client/cdc
pytest testcases/ --upstream-uri http://localhost:19530 --upstream-token root:Milvus --downstream-uri http://localhost:19531 --downstream-token root:Milvus
```

### 运行特定类别的测试
```bash
# 数据库操作测试
pytest testcases/test_database.py --upstream-uri http://localhost:19530 --upstream-token root:Milvus --downstream-uri http://localhost:19531 --downstream-token root:Milvus

# RBAC 操作测试
pytest testcases/test_rbac.py --upstream-uri http://localhost:19530 --upstream-token root:Milvus --downstream-uri http://localhost:19531 --downstream-token root:Milvus

# 数据操作测试
pytest testcases/test_dml.py --upstream-uri http://localhost:19530 --upstream-token root:Milvus --downstream-uri http://localhost:19531 --downstream-token root:Milvus
```

### 运行特定测试方法
```bash
# 运行特定的测试方法
pytest testcases/test_database.py::TestCDCSyncDatabase::test_create_database --upstream-uri http://localhost:19530 --upstream-token root:Milvus --downstream-uri http://localhost:19531 --downstream-token root:Milvus
```

### 自定义同步超时时间
```bash
pytest testcases/test_database.py --upstream-uri http://localhost:19530 --upstream-token root:Milvus --downstream-uri http://localhost:19531 --downstream-token root:Milvus --sync-timeout 180
```

### 自定义 CDC 拓扑配置
```bash
# 自定义集群 ID 和通道数量
pytest testcases/test_database.py --source-cluster-id my-source --target-cluster-id my-target --pchannel-num 8

# 完整的自定义配置
pytest testcases/test_database.py \
  --upstream-uri http://localhost:19530 \
  --upstream-token root:Milvus \
  --downstream-uri http://localhost:19531 \
  --downstream-token root:Milvus \
  --source-cluster-id my-source \
  --target-cluster-id my-target \
  --pchannel-num 32 \
  --sync-timeout 180
```

### 使用默认配置运行（当前已配置的地址）
```bash
# 使用 conftest.py 中的默认配置
pytest testcases/test_database.py

# 或运行所有测试
pytest testcases/
```

## 测试类别

### 1. 数据库操作 (test_database.py)
- CREATE_DATABASE
- DROP_DATABASE
- ALTER_DATABASE_PROPERTIES
- DROP_DATABASE_PROPERTIES

### 2. 资源组操作 (test_resource_group.py)
- CREATE_RESOURCE_GROUP
- DROP_RESOURCE_GROUP
- TRANSFER_NODE
- TRANSFER_REPLICA

### 3. RBAC 操作 (test_rbac.py)
- CREATE_ROLE / DROP_ROLE
- CREATE_USER / DROP_USER
- GRANT_ROLE / REVOKE_ROLE
- GRANT_PRIVILEGE / REVOKE_PRIVILEGE

### 4. 集合 DDL 操作 (test_collection.py)
- CREATE_COLLECTION
- DROP_COLLECTION
- RENAME_COLLECTION

### 5. 索引操作 (test_index.py)
- CREATE_INDEX
- DROP_INDEX

### 6. 数据操作 (test_dml.py)
- INSERT
- DELETE
- UPSERT
- BULK_INSERT

### 7. 集合管理操作 (test_collection_management.py)
- LOAD_COLLECTION
- RELEASE_COLLECTION
- FLUSH
- COMPACT

### 8. 别名操作 (test_alias.py)
- CREATE_ALIAS
- DROP_ALIAS
- ALTER_ALIAS

### 9. 分区操作 (test_partition.py)
- CREATE_PARTITION / DROP_PARTITION
- LOAD_PARTITION / RELEASE_PARTITION
- 分区数据操作 (INSERT, DELETE)

## 配置参数

### 命令行参数

#### 连接配置
- `--upstream-uri`: 上游 Milvus URI（默认: http://10.104.21.33:19530）
- `--upstream-token`: 上游 Milvus 认证 token（默认: root:Milvus）
- `--downstream-uri`: 下游 Milvus URI（默认: http://10.104.23.111:19530）
- `--downstream-token`: 下游 Milvus 认证 token（默认: root:Milvus）

#### CDC 拓扑配置
- `--source-cluster-id`: 源集群 ID（默认: cdc-test-source）
- `--target-cluster-id`: 目标集群 ID（默认: cdc-test-target）
- `--pchannel-num`: 物理通道数量（默认: 16）

#### 测试配置
- `--sync-timeout`: 同步超时时间（秒，默认: 120）

## 要求

- pymilvus >= 2.6.0
- pytest
- numpy
- 两个运行中的 Milvus 实例（上游和下游）
- 在实例之间配置 CDC 复制

## 特性

- **自动 CDC 拓扑设置**: 测试开始时自动创建 CDC 复制拓扑
- **标准日志输出**: 无表情符号，清晰的日志格式
- **基于查询的验证**: 数据操作通过实际查询验证同步结果
- **可配置超时**: 支持自定义同步超时时间，带进度日志
- **完善资源管理**: 每次测试后的全面清理，只清理上游资源
- **详细错误处理**: 移除了掩盖问题的异常处理，真实错误会被正确抛出
- **灵活认证**: 支持 URI + token 认证方式

## CDC 拓扑自动配置

测试框架会在 session 开始时自动设置 CDC 拓扑：

1. **集群配置**:
   - 源集群 ID: 可通过 `--source-cluster-id` 配置（默认: `cdc-test-source`）
   - 目标集群 ID: 可通过 `--target-cluster-id` 配置（默认: `cdc-test-target`）
   - 物理通道数量: 可通过 `--pchannel-num` 配置（默认: 16）

2. **复制拓扑**:
   - 从源集群到目标集群的单向复制
   - 使用命令行参数中指定的集群 ID

3. **初始化**:
   - 配置完成后等待 5 秒让 CDC 初始化
   - 详细的拓扑设置日志记录

这个过程对用户透明，支持通过命令行参数灵活配置。