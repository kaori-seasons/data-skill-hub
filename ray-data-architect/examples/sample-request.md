# 示例设计请求

## 请求 1：Parquet Filter Pushdown

**需求描述**：
Ray Data 当前读取 Parquet 文件时，即使用户在 `map_batches()` 中添加了过滤条件，也会先读取全量数据再过滤。对于高选择率的查询（例如只读取 1% 的数据），这会导致大量不必要的 I/O 和内存开销。

需要设计一个 filter pushdown 机制，将过滤条件下推到 Parquet 读取层，利用 Parquet 的 row group 级别统计信息跳过不需要的数据块。

**约束条件**：
- 不能破坏现有的 API 兼容性
- 需要支持嵌套列的过滤
- 需要与现有的 streaming execution 模型兼容
- 目标：选择率 1% 时，性能提升 10x 以上

**期望输出**：
- 完整的架构设计方案
- 包含代码修改路径
- 性能基准测试方案

---

## 请求 2：Streaming Shuffle 优化

**需求描述**：
Ray Data 的 `repartition()` 操作在处理大规模数据集时存在内存问题——它会将所有 shuffle 数据物化到内存中，导致 OOM。需要设计一个基于 streaming 的 shuffle 机制，支持溢写到磁盘，并实现背压控制。

**参考系统**：
- Spark 3.0 的 Push-based Shuffle
- Dask 的 Task-based Shuffle

**性能目标**：
- 1TB 数据 repartition 时内存峰值 < 10GB
- 吞吐量不低于现有实现的 80%
- 支持 1000+ partition 的 shuffle

---

## 请求 3：快速技术调研（quick 深度）

**需求描述**：
想了解 Ray Data 的 LogicalPlan 到 PhysicalPlan 的转换过程，以及 StreamingExecutor 的调度逻辑。不需要完整的设计方案，只需要梳理现有架构和核心代码路径。

**代码库**：`/path/to/ray/python/ray/data/`

**期望输出**：
- 核心组件和调用关系
- 关键代码文件路径
- 现有架构的优缺点简评
