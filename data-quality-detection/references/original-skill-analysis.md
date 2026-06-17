# 数据质量检测 Skill

## 1. Skill 定义

这个 skill 用来回答一个更底层的问题:

数据为什么“不可信”，到底是源头脏了、加工错了、桥接断了、口径歪了，还是前台把一个本来正确的值解释错了。

它不是单纯跑空值率，而是把“应然模型”和“实然数据”逐层对齐，然后给出可落地的根因拆解与治理优先级。

## 2. 扫描后提炼出的第一性原理

从已扫描的 Python 脚本与 PDF/Markdown 报告看，这个仓库里的高质量数据质检都遵循同一个底层逻辑:

1. 数据质量不是字段本身的属性，而是“数据是否还能稳定支撑业务决策”的属性。
2. 一条异常不能只被描述成“有问题”，必须被定位到具体断点:
   - 源表污染
   - SQL 映射错位
   - 维度桥接缺失
   - 粒度设计错误
   - 枚举规则缺口
   - 前台展示/接口格式化偏差
3. 任何单表结论都不够，必须做跨层核对:
   - ODS 是否脏
   - DWD/DWS 是否放大了脏值
   - DIM/ADS 是否把脏值固化为“正式事实”
4. “高填充率”不等于“高质量”，很多字段恰恰是 100% 填充但语义混写。
5. 质量检测必须带样本，否则结论不可辩护。

## 3. 这个 Skill 的证据基础

这个 skill 主要抽象自以下资产:

- 结构与通用质检
  - `data-warehouse/data-quality-report/run_quality_checks.py`
  - `data-warehouse/data-quality-report/run_7table_quality.py`
  - `data-warehouse/data-quality-report/data-quality-report-20260408.md`
- 规划对照与桥接表质检
  - `data-warehouse/data-quality-report/run_table124_quality_report.py`
  - `four-table.pdf`
  - `data-warehouse/data-quality-report/table124-quality-report-20260416.json`
- 图片链路质检
  - `data-warehouse/data-quality-report/run_current_version_image_source_dq.py`
  - `data-warehouse/data-quality-report/run_dim_picture_enum_gap_report.py`
  - `data-warehouse/data-quality-report/run_frontend_image_path_lineage_trace.py`
  - `data-warehouse/data-quality-report/current-version-image-source-dq-report-20260416.json`
- 平台空值与路径根因
  - `run_platform_null_root_cause_probe.py`
  - `run_platform_path_layer_scan.py`
  - `run_sample_table01_platform_null_diagnosis.py`
  - `run_pic_backup_video_content_type_probe.py`
- 血缘与 SQL 结构补证
  - `build_sql_data_map.py`
  - `run_total_hours_sql_field_probe.py`
  - `total-hours-field-mapping-report.pdf`

## 4. 适用场景

- 想知道某张表能不能作为正式分析底表。
- 业务说“这个字段不对”，但还不知道错在源头还是加工。
- 同一个逻辑字段在不同表里看起来都有，想判定哪个才是可信口径。
- 图片/视频/订单/商品链路里出现空值、脏枚举、路径错位、桥接失败、血缘不清。
- 要输出能给业务、研发、数据仓库三方同时看的诊断报告。

## 5. 输入要求

- 至少有一个待检对象:
  - 目标表
  - 目标 SQL
  - 目标报表
  - 前台异常样例
- 最好同时具备三类参照:
  - 规划文档或 PDF
  - 运行中的表 schema / 行级数据
  - 上下游 SQL / 血缘关系

## 6. 标准工作流

### Step 1. 先定义“应然合同”

不要先跑 SQL，先定义这张表理论上应该满足什么。

合同通常来自四类来源:

- 规划稿/业务 PDF
- Excel 字段设计
- 建表 SQL
- 下游消费口径

先明确:

- 表的目标粒度是什么
- 核心主键是什么
- 哪些字段是必须可用的
- 哪些字段只是增强信息
- 哪些字段是派生指标，不应该被误当作物理字段

典型例子:

- `four-table.pdf` 把 `file_id + platform_source_id + sku` 定义成桥接核心。
- `run_taobao_live_orders_core_dimension_report.py` 明确 `pay_cnt` 应视为派生口径，不是物理列。

### Step 2. 再确认“实然对象”

不能只信规划表名，要确认真实运行表。

要检查:

- 表是否存在
- 列是否存在
- 真实列名是否和规划一致
- 同名字段是否被换源
- 结果表不存在时，是否要回退到源表核验

这一步在仓库里反复出现:

- `run_content_core_dimension_report.py` 会先探测结果表，再降级到源表。
- `run_total_hours_sql_field_probe.py` 会跨库搜索候选表。

### Step 3. 六层质检

#### 3.1 结构层

- 列是否齐全
- 类型是否合理
- 注释是否缺失
- 是否全字段可空
- 关键字段是否被错误建成 string

#### 3.2 值层

- 空值率
- 空串率
- 脏值
- 控制字符
- 过长值
- 路径后缀异常
- 文件名与路径基名冲突

#### 3.3 主键与粒度层

- 主键是否唯一
- 是否一文件多行 / 一订单多行 / 一平台实例多行
- 去重后行数与总行数差多少

#### 3.4 枚举与分布层

- 枚举全集是否合理
- 是否混入流程词、测试词、临时目录名
- target/ref 枚举是否一致
- 哪些枚举只在一侧存在

#### 3.5 时序与新鲜度层

- 最早/最晚时间
- 是否有未来时间
- 是否有明显脏时间
- 是否存在“字段存在但实时库全空”

#### 3.6 跨层与血缘层

- 上游能否对上
- 中间桥接是否断裂
- 下游是否把完整路径写进 folder 语义字段
- 前台异常是否只是展示层格式化造成

## 7. 根因推理框架

拿到异常后，按下面顺序判断，不要跳步。

### A. 如果源表已经脏

特征:

- ODS 就出现视频后缀、错枚举、路径缺平台、时间脏值

结论:

- 这是源污染，DWD/DWS/DIM 只是继承或放大

### B. 如果源表不脏，但目标语义错位

特征:

- 字段本身有值
- 但 SQL 把 `full_path` 写进 `folder_path` 一类语义字段

结论:

- 这是加工映射错误，不是源污染

`run_current_version_image_source_dq.py` 就是这种典型。

### C. 如果值缺失只发生在桥接层

特征:

- 上游两边都有值
- 中间 `platform_source_id` / `sku` / `weight_factor` 这类桥接键丢失

结论:

- 是关联设计或桥接表建设不完整

### D. 如果 target/ref 枚举全集不一致

特征:

- 一边有，一边没有
- 且来源层与结果层是否同步缺失可进一步拆根因

结论:

- 可能是:
  - 规则未覆盖
  - 来源周期没有样本
  - 结果层聚合丢值

### E. 如果前台值异常、数据库值正常

特征:

- 去分隔符、URL decode 后同源
- 只有前台多了 `///`、`%20`

结论:

- 更像接口/展示格式化问题

## 8. 输出物标准

一个合格的输出必须同时包含:

- 结论摘要
- 关键指标
- 根因分桶
- 代表样本
- 自我反证
- 治理建议

建议输出格式:

1. 执行摘要
2. 检查范围与粒度定义
3. 结构问题
4. 值问题
5. 关系/血缘问题
6. 根因拆解
7. 样本
8. 修复优先级
9. 反思与剩余不确定性

## 9. 高价值检查清单

优先检查以下问题，因为它们在已扫描资产里反复出现:

- string 类型承载金额、比率、数量
- 主键不唯一
- 平台字段空值但路径里其实有平台信息
- 图片集合混入视频后缀
- `folder_path` / `full_path` / `file_name` 语义错位
- 结果字段取错来源列
- 枚举标准值和 reference 值集合不一致
- 规划文档要求的桥接字段在实表中缺失

## 10. 自我辩证与反思

这个 skill 也有边界，必须主动反驳自己:

1. 空值不一定是坏数据，也可能是真正的不适用。
2. 枚举差集不一定意味着错误，也可能代表新业务。
3. 单次抽样很容易被近期增量偏差误导。
4. 结果层异常不一定来自最近 SQL，也可能是历史存量没回刷。
5. 血缘图能说明“从哪来”，但不自动说明“为什么错”。
6. 如果只看统计不看样本，容易把语义问题误诊成分布问题。
7. 如果只看规划文档不看实库，容易把“未落地设计”误当成“线上回归”。

## 11. 一句话使用法

先定义应然合同，再核对运行对象，然后按“结构-值-粒度-枚举-时序-血缘”六层递进检查，最后把异常强制归入“源污染 / 映射错位 / 桥接缺失 / 规则缺口 / 展示偏差”五类根因之一。
