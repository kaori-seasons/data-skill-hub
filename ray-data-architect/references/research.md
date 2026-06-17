# Ray Data 架构设计 Skill 调研资料

## 一、Ray Data 架构概览

### 核心组件

| 组件 | 路径 | 职责 |
|------|------|------|
| Dataset | `python/ray/data/dataset.py` | 用户 API 层，提供 `map_batches`/`filter`/`select` 等接口 |
| LogicalPlan | `python/ray/data/_internal/logical/` | 逻辑执行计划，描述数据处理的逻辑步骤 |
| PhysicalPlan | `python/ray/data/_internal/physical_operator/` | 物理算子，逻辑计划的物理实现 |
| Planner | `python/ray/data/_internal/planner/` | LogicalPlan → PhysicalPlan 的转换器 |
| StreamingExecutor | `python/ray/data/_internal/execution/streaming_executor.py` | 流式执行引擎 |
| ResourceManager | `python/ray/data/_internal/execution/resource_manager.py` | 资源（内存/CPU）管理 |
| Datasource | `python/ray/data/_internal/datasource/` | 数据源抽象（Parquet/CSV/JSON 等） |

### 数据流

```
用户 API (Dataset)
    ↓
LogicalPlan (逻辑优化)
    ↓
Planner (逻辑→物理转换)
    ↓
PhysicalPlan (物理算子图)
    ↓
StreamingExecutor (流式调度执行)
    ↓
结果输出
```

## 二、数据下推现状分析

### 当前实现

Ray Data 目前的数据处理流程：
1. `read_parquet()` 调用 `ParquetDatasource` 读取全量数据
2. 数据加载为 Arrow Table 后进入 StreamingExecutor
3. 用户的 `map_batches(filter_fn)` 在数据加载之后执行
4. 没有任何下推优化

### 问题所在

```
当前: Read (全量) → 传输 → map_batches(filter) → 输出
优化: Read (带filter) → 传输(少量) → 输出

选择率 1% 时:
- 当前: I/O = 100%, 内存 = 100%, 传输 = 100%
- 优化后: I/O ≈ 1-5% (取决于 row group 统计), 内存 ≈ 1%, 传输 ≈ 1%
```

### 行业对标

**Spark Parquet Filter Pushdown:**
- Catalyst Optimizer 自动识别可下推的 filter
- 转换为 Parquet 的 `FilterCompat.Filter`
- 利用 row group 的 min/max 统计信息跳过不需要的 block
- 支持 partition pruning

**Polars LazyFrame:**
- 查询优化器自动下推 filter 和 projection
- 利用 Parquet 的 column statistics
- 支持谓词合并和简化

**Dask:**
- 有限的 filter pushdown 支持
- 主要依赖 partition pruning
- 不支持 row group 级别的过滤

## 三、Shuffling 机制分析

### 当前实现

Ray Data 的 `repartition()` 实现：
1. 基于 hash 的分区策略
2. 全物化中间数据到内存
3. 没有溢写到磁盘的机制
4. 没有背压控制

### 问题所在

```
大数据集 repartition (如 1TB):
- 内存峰值: 需要物化完整 shuffle 数据
- OOM 风险: 单节点内存不足时直接失败
- 无背压: 上游不停产出，下游处理不过来
```

### 行业对标

**Spark Sort-based Shuffle:**
- Map-side sort + Spill to disk
- 基于索引的 shuffle write
- External Shuffle Service
- Push-based Shuffle (Spark 3.0+)

**Dask:**
- Task-based shuffle
- 中间结果写入磁盘
- 依赖 task graph 优化

## 四、关键代码路径

### Parquet 读取路径

```
read_parquet()
  → Dataset.from_parquet()
    → ParquetDatasource()
      → pq.read_table()  # 全量读取，无 filter
        → Arrow Table
          → StreamingExecutor 调度
            → map_batches(filter_fn)  # 后过滤
```

### Repartition 路径

```
Dataset.repartition()
  → Repartition logical operator
    → RandomShuffle physical operator
      → StreamingExecutor 调度
        → 全物化 → 重新分区 → 输出
```

### StreamingExecutor 调度循环

```
StreamingExecutor.run()
  → while not all_done:
      → select_operator_to_run()  # 选择就绪的 operator
      → execute_one_step()        # 执行一步
      → update_resource_usage()   # 更新资源使用
      → check_backpressure()      # 检查背压
```

## 五、已知 Issue 和社区讨论

### Filter Pushdown 相关

- GitHub Issue: 多次请求 Parquet filter pushdown
- 社区讨论: 是否应该在 LogicalPlan 层自动提取 filter
- 核心争议: 自动提取 lambda 的复杂度 vs 用户手动指定的易用性

### Shuffle 相关

- GitHub Issue: 大数据集 repartition OOM
- 社区讨论: 是否引入 sort-based shuffle
- 核心争议: 简单 hash shuffle 足够 vs 需要更复杂的 streaming shuffle

### 内存管理

- StreamingExecutor 的背压机制是全局的
- 无法针对单个 Operator 精细控制内存
- 缺少基于 cost 的资源分配

## 六、技术决策参考

### Filter Expression 抽象

```
Ray Data 内部需要一个 filter expression 抽象层:
- 用户 API 层: col("x") > 10
- 内部表示: FilterExpression(Column("x"), GT, Literal(10))
- Parquet 层: pyarrow ds.field("x") > 10
- 未来 Delta/Iceberg 层: 各自的 filter 表达式
```

### Shuffle 中间存储

```
选项:
1. 纯内存: 当前方案，简单但 OOM 风险
2. 内存 + 磁盘溢写: Spark 方案，复杂但可靠
3. 基于 Ray Object Store: 利用 Ray 的分布式内存，但序列化开销
4. External Shuffle Service: 独立进程管理 shuffle 数据
```

## 七、调研方法说明

本调研基于以下方法：
1. 阅读 Ray Data 源码（最新 stable 版本）
2. 分析 Ray Data 官方文档和 API reference
3. 搜索 Ray GitHub 的 issues 和 PRs
4. 对比 Spark/Polars/Dask 的官方文档
5. 参考 Ray Summit 的架构分享

注意：Ray Data 的内部实现在版本间变化较大，本文档以分析时的最新 stable 版本为准。
