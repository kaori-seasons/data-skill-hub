# 设计模型参考手册

本文档是 `ray-data-architect` Skill 的补充参考，包含四维度分析框架的详细方法论、行业对标基准和方案评估模板。

---

## 1. 行业对标基准

### 1.1 数据下推能力对比

| 能力 | Spark | Dask | Polars | Ray Data (当前) |
|------|-------|------|--------|-----------------|
| Predicate Pushdown | ✅ 完整 | ⚠ 有限 | ✅ 完整 | ❌ 未实现 |
| Filter Pushdown | ✅ 完整 | ❌ 无 | ✅ 完整 | ❌ 未实现 |
| Projection Pushdown | ✅ 完整 | ⚠ 有限 | ✅ 完整 | ⚠ 部分 |
| Partition Pruning | ✅ 完整 | ⚠ 有限 | ✅ 完整 | ❌ 未实现 |
| Predicate Pushdown to Storage | ✅ Parquet/ORC | ❌ 无 | ✅ Parquet | ❌ 未实现 |

### 1.2 Shuffling 机制对比

| 机制 | Spark | Dask | Ray Data (当前) |
|------|-------|------|-----------------|
| Hash Shuffle | ✅ | ✅ | ✅ (repartition) |
| Sort-based Shuffle | ✅ | ❌ | ❌ |
| Streaming Shuffle | ✅ (3.0+) | ⚠ 有限 | ⚠ 部分 |
| Shuffle 背压 | ✅ | ❌ | ❌ |
| 外部排序 | ✅ | ❌ | ❌ |

### 1.3 性能基准参考

| 场景 | Spark 3.x | Ray Data | 差距分析 |
|------|-----------|----------|----------|
| Parquet 读取 + 过滤 | 接近存储层速度 | 全量读取后过滤 | 10-100x 差距（取决于选择率） |
| 大规模 repartition | 流式执行，内存可控 | 全物化，内存峰值高 | 2-5x 内存差距 |
| 多表 join | 自动优化 | 手动优化 | 取决于数据分布 |

---

## 2. 四维度分析框架

### 2.1 背景分析模板

```
输入: 用户需求描述

分析步骤:
  1. 现状梳理
     - 当前实现是什么？（代码级描述）
     - 性能指标现状（延迟、吞吐、内存）
     - 用户反馈或 issue 列表

  2. 驱动力分析
     - 性能瓶颈：[具体瓶颈描述]
     - 用户需求：[issue/feature request 编号]
     - 架构演进：[与 roadmap 的关系]

  3. 上下游影响
     - 上游：[数据来源、API 调用方]
     - 下游：[消费者、依赖模块]
     - 横向：[同类系统对比]

  4. 行业对标
     - Spark 方案: [简述]
     - Dask 方案: [简述]
     - Polars 方案: [简述]
     - 可借鉴之处: [具体点]
```

### 2.2 约束分析模板

```
硬性约束（不可违反）:
  - [ ] API 向后兼容性: [具体 API 列表]
  - [ ] 内存限制: [上界]
  - [ ] 网络带宽: [集群配置]
  - [ ] Python 版本: [最低支持版本]
  - [ ] Arrow 版本: [依赖版本]

软性约束（尽量满足）:
  - [ ] 代码风格一致性
  - [ ] 测试覆盖率 ≥ 80%
  - [ ] 文档完整性
  - [ ] 社区 review 通过

资源约束:
  - 开发人力: [人/周]
  - 测试环境: [集群规模]
  - 时间窗口: [deadline]
```

### 2.3 方案对比评估矩阵

```
评估维度（权重可根据场景调整）:

| 维度 | 权重 | 评分标准 |
|------|------|----------|
| 性能提升 | 30% | 1: <10%, 2: 10-30%, 3: 30-50%, 4: 50-80%, 5: >80% |
| 实现复杂度 | 25% | 1: 极复杂, 2: 复杂, 3: 中等, 4: 较简单, 5: 简单 |
| 兼容性影响 | 20% | 1: 破坏性变更, 2: 需迁移, 3: 有 workaround, 4: 无影响, 5: 增强兼容 |
| 可维护性 | 15% | 1: 难以维护, 2: 需持续投入, 3: 一般, 4: 较好, 5: 优秀 |
| 可测试性 | 10% | 1: 无法测试, 2: 仅集成测试, 3: 单元+集成, 4: 完整覆盖, 5: 形式化验证 |

综合得分 = Σ(维度得分 × 权重)
```

---

## 3. 数据下推设计模式

### 3.1 Filter Pushdown 架构模式

```
模式一：LogicalPlan 层下推
  优势: 优化器自动处理，用户无感知
  劣势: 需要修改 planner，复杂度高
  适用: 长期方案，与 Spark 对齐

模式二：Datasource 层下推
  优势: 实现简单，影响范围小
  劣势: 需要用户手动指定，不够智能
  适用: 短期快速方案

模式三：混合模式
  LogicalPlan 层自动下推 + Datasource 层 hint
  优势: 兼顾自动优化和用户控制
  劣势: 两套路径的维护成本
  适用: 中期演进方案
```

### 3.2 Projection Pushdown 架构模式

```
模式一：Schema 裁剪
  在读取前根据 select 列裁剪 schema
  实现: 修改 Read operator，传递 column 列表
  复杂度: 低

模式二：Arrow RecordBatch 裁剪
  在 Arrow 层面按列索引裁剪
  实现: 在 PhysicalOperator 层添加裁剪逻辑
  复杂度: 中

模式三：存储层裁剪
  直接传递 column 列表给 Parquet reader
  实现: 修改 ParquetDatasource
  复杂度: 低，但仅限 Parquet
```

### 3.3 Predicate Pushdown 到存储层

```
Parquet 过滤下推:
  1. 将 Ray Data filter 表达式转换为 pyarrow 表达式
  2. 传递给 pq.read_table(filters=...)
  3. 利用 Parquet 的 row group 级别过滤

表达式转换规则:
  Ray Data: col("x") > 10
  → pyarrow: ds.field("x") > 10

  Ray Data: col("x") > 10 AND col("y") < 20
  → pyarrow: (ds.field("x") > 10) & (ds.field("y") < 20)

  Ray Data: col("x").isin([1, 2, 3])
  → pyarrow: ds.field("x").isin([1, 2, 3])
```

---

## 4. Shuffling 设计模式

### 4.1 Sort-based Shuffle 架构

```
核心思想: 用排序替代哈希，天然支持范围查询和有序输出

组件:
  1. Map-side Sort: 每个 partition 内排序
  2. Shuffle Write: 按范围分区写入中间文件
  3. Shuffle Read: 有序读取并归并
  4. Reduce-side Merge: 多路归并排序

内存控制:
  - 使用外部排序（external sort）处理超大数据集
  - 内存缓冲区大小可配置
  - 溢写到磁盘的阈值策略
```

### 4.2 Streaming Shuffle 架构

```
核心思想: 不物化完整的 shuffle 数据，流式传递

组件:
  1. Push-based Shuffle: Map 完成即推送，不等待全部完成
  2. 背压机制: 下游处理不过来时暂停上游
  3. 缓冲管理: 内存 + 磁盘两级缓冲
  4. 容错: 基于 lineage 的重算

与 Spark 3.0 对比:
  Spark: External Shuffle Service + Push-based
  Ray: Actor-based + Streaming Executor
```

### 4.3 数据倾斜处理模式

```
检测:
  1. 采样估算 key 分布
  2. 计算 skewness 指标
  3. 识别热点 key（top-K by count）

处理策略:
  策略一: 两阶段聚合
    - 第一阶段: 对热点 key 局部聚合
    - 第二阶段: 全局聚合

  策略二: 加盐（Salting）
    - 对热点 key 添加随机后缀
    - 局部聚合后去除后缀再全局聚合

  策略三: 自适应分区
    - 根据数据分布动态调整分区数
    - 热点 key 单独分区处理
```

---

## 5. 评估与验证方法

### 5.1 性能基准测试设计

```
测试维度:
  1. 吞吐量: records/sec 或 bytes/sec
  2. 延迟: P50 / P95 / P99
  3. 内存峰值: RSS 峰值
  4. CPU 利用率: 平均和峰值
  5. 网络 I/O: shuffle 数据量

测试数据集:
  - 小规模: 1GB, 10 个 partition
  - 中规模: 100GB, 100 个 partition
  - 大规模: 1TB, 1000 个 partition

测试场景:
  - 理想情况: 均匀分布，无数据倾斜
  - 压力测试: 数据倾斜 90/10 分布
  - 极端测试: 单 partition 超大数据
```

### 5.2 正确性验证

```
验证方法:
  1. 与 Spark 结果对比（golden standard）
  2. 与优化前结果对比（no regression）
  3. 边界条件测试（空数据、单条、超大值）
  4. 随机数据 fuzz 测试

验证指标:
  - 结果完全一致（exact match）
  - 浮点误差在允许范围内（relative error < 1e-6）
  - 行数一致，列数一致
```

### 5.3 兼容性测试

```
测试矩阵:
  - Python: 3.9, 3.10, 3.11, 3.12
  - Ray: 2.x, latest
  - Arrow: 12.x, 14.x, latest
  - OS: Linux, macOS
  - 存储: 本地文件系统, S3, GCS, HDFS

回归测试:
  - 所有现有 test suite 必须通过
  - 性能不能退化超过 5%
  - API 签名不变
```

---

## 6. 常见陷阱与反模式

### 6.1 数据下推陷阱

```
❌ 反模式: 在 LogicalPlan 层做过滤但不裁剪 schema
  问题: 数据量减少了，但仍然读取所有列
  正确: filter + projection 同时下推

❌ 反模式: 对非 Parquet 格式强行下推
  问题: CSV/JSON 不支持 row group 过滤
  正确: 检测数据源类型，仅对支持的格式下推

❌ 反模式: 下推包含 UDF 的过滤条件
  问题: UDF 无法序列化到存储层
  正确: 仅下推可序列化的表达式，UDF 过滤留在计算层
```

### 6.2 Shuffling 陷阱

```
❌ 反模式: 盲目增加 partition 数量
  问题: 小 partition 导致调度开销大于计算
  正确: partition 大小建议 128MB-1GB

❌ 反模式: 忽略数据倾斜
  问题: 热点 partition 成为瓶颈
  正确: 采样检测 + 自适应分区

❌ 反模式: shuffle 后不 coalesce
  问题: 大量小 partition 影响下游性能
  正确: 根据下游需求适当 coalesce
```
