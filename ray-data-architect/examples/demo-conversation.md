# Ray Data 架构设计 Skill 示例对话

## 对话一：Parquet Filter Pushdown 设计

**用户**：Ray Data 读取 Parquet 文件时是全量读取再过滤，对于高选择率的查询（比如只读 1% 的数据）性能很差。需要设计一个 filter pushdown 机制。代码库在 /Users/kaori/ray。

**架构师**：

先搜一下现有的 Parquet 读取实现。

```
🔍 代码搜索结果
├── python/ray/data/_internal/datasource/parquet_datasource.py — Parquet 读取入口
├── python/ray/data/_internal/logical/operators/read_operator.py — Read 逻辑算子
└── python/ray/data/_internal/planner/ — LogicalPlan → PhysicalPlan 转换
```

看完代码后，我来做一个系统性分析。

---

### 📋 需求解析

```
├── 核心问题: Parquet 读取未利用 row group 级别统计信息过滤，全量 I/O
├── 影响范围: ParquetDatasource → Read Operator → StreamingExecutor
├── 需求类型: 架构设计
└── 成功标准: 选择率 1% 时 I/O 减少 90%+
```

---

### 📊 四维度分析

**维度一：背景与动机**

现状：`ParquetDatasource` 调用 `pq.read_table()` 时未传入 `filters` 参数，所有 row group 都被完整读取。用户在 `map_batches()` 中添加的过滤条件在数据加载之后才执行。

驱动力：
- 高选择率查询（< 10%）在数据探索场景中非常常见
- Spark 从 1.x 就支持 Parquet predicate pushdown，这是行业标配
- 用户在 GitHub 上多次反馈此问题

对标系统：
| 系统 | Filter Pushdown | Projection Pushdown | Partition Pruning |
|------|----------------|--------------------|--------------------|
| Spark | ✅ Catalyst 自动下推 | ✅ | ✅ |
| Polars | ✅ 自动下推 | ✅ | ✅ |
| Dask | ⚠ 有限支持 | ⚠ | ⚠ |
| Ray Data | ❌ | ⚠ 部分 | ❌ |

**维度二：约束条件**

硬性约束：
- `map_batches()` API 不能破坏，用户现有的过滤逻辑必须继续工作
- pyarrow `filters` 参数不支持 UDF，只能下推可序列化的表达式
- 嵌套列的 filter 表达式需要特殊处理

软性约束：
- 与 StreamingExecutor 的流式模型兼容
- 不能显著增加简单查询（无 filter）的开销

**维度三：设计折中**

核心问题：**谁来负责识别可下推的 filter？**

选项A（LogicalPlan 层自动识别）：用户写 `map_batches(lambda df: df[df.x > 10])`，系统自动提取过滤条件并下推。优点是用户无感知，缺点是需要解析 lambda 函数，实现极其复杂。

选项B（Datasource 层 hint）：用户在 `read_parquet()` 中显式传入 `filter` 参数。优点是实现简单，缺点是需要用户手动指定。

选项C（混合模式）：支持显式 hint + 自动提取简单表达式。兼顾两者优点，但维护两套路径。

**维度四：已知问题与改进**

- pyarrow 的 filter 表达式能力有限，复杂条件（如 OR + 嵌套）可能无法下推
- 不同 Parquet writer 写出的统计信息完整度不同，下推效果依赖数据质量
- 未来 Delta Lake / Iceberg 集成时，需要统一的 filter 表达式抽象层

---

### 🔄 方案对比

| 维度 | 方案A: 自动识别 | 方案B: 显式 hint | 方案C: 混合模式 |
|------|----------------|-----------------|-----------------|
| 核心思路 | 解析 lambda 提取条件 | 用户传入 filter 参数 | hint 优先 + 自动降级 |
| 优势 | 用户无感知 | 实现简单、可控 | 兼顾两者 |
| 劣势 | 实现极复杂，Python lambda 难解析 | 需要用户改代码 | 两套路径维护成本 |
| 实现复杂度 | 🔴 高 | 🟢 低 | 🟡 中 |
| 性能影响 | 理论最优 | 取决于用户使用 | 接近最优 |
| 推荐度 | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

---

### 🔄 自我辩证

**假设检验**：
- 假设 pyarrow `filters` 能覆盖大部分场景 → 验证：支持 `==`, `!=`, `<`, `>`, `in`, `and`, `or`，覆盖 80%+ 场景
- 假设用户愿意手动传入 filter → 需要验证，可能降低易用性

**红队思维**：
- "为什么不直接建议用户用 Polars？" → Ray Data 的价值在于分布式执行和与其他 Ray 生态的集成，不是单机性能
- "如果 filter 条件很复杂怎么办？" → 降级为全量读取 + 后过滤，与现状一致

**边界条件**：
- 空 filter → 正常读取，无额外开销
- 全量 filter（选择率 100%）→ 等价于无 filter
- 嵌套列 filter → pyarrow 支持 `ds.field("struct.col")` 语法

**简单性检验**：
- 方案B 能覆盖 80% 场景，实现复杂度低，是否值得做方案A？
- 结论：Phase 1 做方案B，Phase 2 根据用户反馈决定是否做方案A

---

### 📝 推荐方案：方案B — 显式 hint

**Phase 1: Datasource 层 filter 参数**

修改文件：
- `python/ray/data/_internal/datasource/parquet_datasource.py` — 添加 `filter` 参数
- `python/ray/data/read_api.py` — 暴露 `filter` 给用户 API

关键代码：
```python
# parquet_datasource.py
def __init__(self, paths, filter=None, columns=None, ...):
    self._filter = filter
    ...

def _read_pieces(self, pieces):
    import pyarrow.parquet as pq
    table = pq.read_table(
        pieces,
        filters=self._filter,  # 新增：传入 filter
        columns=self._columns,
    )
    return table
```

用户 API：
```python
# 新增 filter 参数
ds = ray.data.read_parquet(
    "s3://bucket/data/",
    filter=ds.field("date") > "2024-01-01",  # pyarrow 表达式
)
```

**Phase 2: 自动下推（如果 Phase 1 用户反馈积极）**

- 在 LogicalPlan 层分析 `map_batches` 的 filter 逻辑
- 自动提取可下推的条件
- 与显式 hint 合并

---

### 📝 实施计划

| Phase | 任务 | 验收标准 | 工期 |
|-------|------|----------|------|
| 1 | ParquetDatasource 添加 filter 参数 | 单元测试通过，pyarrow filters 生效 | 1 周 |
| 2 | 用户 API 暴露 + 文档 | `read_parquet(filter=...)` 可用 | 3 天 |
| 3 | 性能基准测试 | 选择率 1% 时 I/O 减少 90%+ | 3 天 |
| 4 | 自动下推（可选） | lambda 中的简单条件自动下推 | 2 周 |

---

### 执行摘要

推荐 **Phase 1 显式 hint 方案**，在 `ParquetDatasource` 中添加 `filter` 参数直接传递给 pyarrow。实现简单（1 周），效果显著（选择率 1% 时 I/O 减少 90%+），不破坏现有 API。Phase 2 根据用户反馈决定是否投入自动下推。

---

## 对话二：StreamingExecutor 调度逻辑（quick 深度）

**用户**：Ray Data 的 StreamingExecutor 是怎么调度的？quick 深度即可。

**架构师**：

搜索相关代码后，简要梳理如下：

```
python/ray/data/_internal/execution/streaming_executor.py — 调度主循环
python/ray/data/_internal/execution/streaming_executor_state.py — 状态管理
python/ray/data/_internal/execution/resource_manager.py — 资源管理
```

**核心调度逻辑**：

1. **主循环**：`StreamingExecutor.run()` 持续调度直到所有 Operator 完成
2. **调度决策**：每轮从所有就绪 Operator 中选择一个执行，选择依据是资源可用性和优先级
3. **背压机制**：当下游 Operator 的输入队列满时，暂停上游调度
4. **内存控制**：通过 `ResourceManager` 跟踪内存使用，超过阈值时触发 backpressure

**优点**：
- 流式执行，不需要物化完整中间结果
- 背压机制避免 OOM

**不足**：
- 调度粒度是 Operator 级别，不够细粒度
- 背压是全局的，无法针对单个 Operator 精细控制
- 没有基于 cost-based 的优化

如果需要更深入的分析（如具体的调度算法、资源管理策略），请告诉我。
