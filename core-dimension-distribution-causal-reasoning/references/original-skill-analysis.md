# 核心维度分布与因果推理 Skill

## 1. Skill 定义

这个 skill 用来回答两类问题:

1. 一张表真正稳定、可用的核心维度是什么。
2. 这些维度一旦出现集中、缺口、多值映射或跨层不一致，根因最可能在哪里。

它的本质不是“看分布图”，而是用维度分布反推出业务粒度、表定位、规则覆盖度和归因路径是否成立。

## 2. 第一性原理

从已扫描脚本和报告看，所谓“核心维度分析”可以拆成四个原子判断:

1. 这个字段能不能稳定分组。
2. 这个字段能不能承载业务计算。
3. 这个字段和其他关键字段是 1:1、1:n 还是 n:n。
4. 这个字段缺失或偏斜时，问题来自源头、粒度、规则还是桥接。

因此，一个维度只有同时满足下面四点，才算“核心”:

- 可识别: 真实列能稳定命中
- 可覆盖: 空值率可接受
- 可解释: 业务语义明确
- 可连接: 能和其它关键维度形成稳定映射

## 3. 这个 Skill 的证据基础

主要抽象自以下资产:

- 核心维度探针
  - `run_live_core_dimension_probe.py`
  - `data-warehouse/data-quality-report/run_content_core_dimension_report.py`
  - `data-warehouse/data-quality-report/run_taobao_live_orders_core_dimension_report.py`
- 分布与聚类
  - `data-warehouse/data-quality-report/run_spu_cluster_distribution_report.py`
  - `data-warehouse/data-quality-report/run_spu_mid_track_cluster_report.py`
  - `data-warehouse/data-quality-report/spu-cluster-distribution-report-20260420.md`
  - `data-warehouse/data-quality-report/spu-mid-track-cluster-report-20260420.md`
- 差集与规则覆盖
  - `data-warehouse/data-quality-report/run_picture_mid_track_gap_report.py`
  - `data-warehouse/data-quality-report/run_picture_video_midcate_rule_gap_report.py`
  - `data-warehouse/data-quality-report/run_picture_video_midcate_action_plan_report.py`
  - `data-warehouse/data-quality-report/picture-mid-track-gap-report-20260420.md`
  - `data-warehouse/data-quality-report/picture-video-midcate-rule-gap-report-20260420.md`
  - `data-warehouse/data-quality-report/picture-video-midcate-action-plan-report-20260420.md`
- 单字段根因拆解
  - `data-warehouse/data-quality-report/run_sample_002_gender_gap_report.py`
  - `data-warehouse/data-quality-report/sample-002-gender-gap-report-20260421.md`
- 订单/直播间/SPU 粒度分析
  - `data-warehouse/data-quality-report/run_order_live_room_spu_distribution_probe.py`
  - `data-warehouse/data-quality-report/order-live-room-spu-distribution-probe-20260422.md`
- 参考方法论
  - `鞋服电商短视频报告.pdf`
  - `短视频五张表核心维度规整报告.pdf`

## 4. 适用场景

- 选底表: 两张或多张表看起来都能分析，但不知道哪张是真底表。
- 选主键: `session_id`、`live_room_id`、`child_order_id`、`spu`、`sku` 哪个才是该问题的主维度。
- 看偏斜: Top1/Top10 占比过高，想知道是业务集中还是数据塌缩。
- 看差集: 图片有、视频没有；来源有、结果没有；目标有、参考没有。
- 做根因: `gender='无'`、`mid_cate` 缺口、`track` 断层、多值映射，到底是取错字段还是本来就不稳定。

## 5. 核心方法

### Step 1. 先定义业务问题，而不是先选字段

维度必须服务于业务问题。

例如:

- 分析直播经营: `session_id`、`child_order_id`、`product_id`、`pay_amount`
- 分析内容归因: `file_id`、`platform_source_id`、`spu`、`sku`
- 分析商品语义: `big_cate`、`mid_cate`、`track`、`gender`、`scene`、`style`

如果问题没定义清楚，后面一定会把“增强维度”错当“核心维度”。

### Step 2. 先定粒度，再定核心维度

已扫描资产反复证明，维度分析最容易错在粒度。

必须先问:

- 一行代表什么
- 一个 key 代表什么
- 同一 key 是否会跨时间、跨平台、跨商品重复出现

典型反例:

- `live_room_id` 不能直接等于单一场次
- `spu` 不能直接代替 `sku`
- `detail_2` 不能因为字段名像就当成 `detail` 的等价替身

### Step 3. 做字段画像

每个候选维度都要先做最小画像:

- 命中到哪个物理列
- 总行数
- 空值数
- 空值率
- distinct 值数
- 是否存在明显脏枚举

这一层在 `run_live_core_dimension_probe.py` 和 `run_taobao_live_orders_core_dimension_report.py` 中最完整。

### Step 4. 看分布，不只看 TopN

至少看四件事:

- Top1 占比
- Top10 累计占比
- 不同取值总数
- “无/其它/空值”占比

经验判断:

- `无` 高占比，通常说明上游标签缺失或取错字段
- Top1 过高，可能是业务集中，也可能是大量脏值塌缩到默认值
- 长尾过长，可能意味着类目粒度过细、未归并、或字典失控

### Step 5. 一定要做映射基数分析

维度本身的分布不够，关键是维度之间如何映射。

至少检查:

- `child_order_id -> session_id`
- `product_id -> spu`
- `spu -> sku_id`
- `live_room_id -> pay_date`
- `source_key -> target_key`

输出要包含:

- 平均每个 source 对应多少 target
- p50 / p90 / max
- 多值映射 source 占比

这是把“能不能分组”升级为“能不能归因”的关键一步。

### Step 6. 做跨层差集

如果一个维度在 A 层存在、B 层缺失，不能直接说 B 错了，要继续拆:

1. 来源层有没有
2. 结果层有没有
3. reference 集合里有没有
4. 历史规则有没有覆盖

所以差集至少分四类:

- 来源无，结果也无
- 来源有，结果无
- 图片有，视频无
- 历史规则有定义，但当前数据没覆盖

## 6. 因果推理模板

### 模板 A: 大量默认值“无”

优先判断:

1. 上游本来就是空
2. 取错来源字段
3. join 没对上
4. 规则把有效值误归成“无”

`sample-002-gender-gap-report-20260421.md` 的结论非常典型:

- 不是目标表天然缺性别
- 而是 `tb16.性别` 有值，但 `性别_李宁bi` 为空
- 所以真正根因是“取错字段来源”

### 模板 B: 图片有、视频没有

优先判断:

1. 视频来源层就没有
2. 视频结果层聚合丢值
3. 历史规则根本没覆盖
4. 其实应该作为新增枚举，不应硬归并

`picture-video-midcate-rule-gap-report-20260420.md` 和 `picture-video-midcate-action-plan-report-20260420.md` 证明了这个拆法最有效。

### 模板 C: 某 key 与多个 target 强多值映射

优先判断:

1. 这个 key 不是业务主键
2. 粒度选错
3. 需要桥接层
4. 需要增加时间窗或场次键

`order-live-room-spu-distribution-probe-20260422.md` 说明:

- `live_room_id` 不能直接代表单场
- `spu` 明显会落到多个直播间
- 所以汇总口径必须改成 distinct 场次键，而不是简单 count

### 模板 D: 两张表都能分析，但只能选一个主底表

优先看:

- 行数覆盖
- 核心字段命中数
- typed 时间字段数
- 是否具备关键增强维度

`taobao-live-orders-core-dimension-report-20260424.md` 给出的经验可直接复用:

- 字段覆盖更全者优先
- 关键锚点维度缺失者只能做辅助对照

## 7. 输出物标准

一个合格的“核心维度分布 + 因果推理”报告应包含:

1. 问题定义
2. 粒度定义
3. 核心字段命中表
4. 字段画像
5. Top 分布与累计占比
6. 关键映射基数
7. 跨层差集
8. 根因分类
9. 行动建议
10. 自我反思

## 8. 常用行动结论桶

根据已扫描资产，最终动作通常落入以下几类:

- 主分析底表
- 辅助对照表
- 新增枚举候选
- 归并候选
- 需补桥接表
- 需改单字段来源
- 需补场次键
- 需按 distinct 口径重算
- 需人工复核低置信边界值

## 9. 这套 Skill 最强调的三条纪律

1. 先看粒度，再看分布。
2. 先看映射关系，再谈归因。
3. 先给反例和样本，再下结论。

## 10. 自我辩证与反思

1. 分布偏斜不天然代表异常，爆款业务本来就会高度集中。
2. 枚举差集不天然代表缺陷，也可能代表新产品线或新赛道。
3. “无/其它”高占比有时是标签体系设计问题，不只是采集问题。
4. 多值映射不一定是坏事，可能只是说明这个字段不是主键。
5. 规则型归并有可追溯性，但会天然压扁边界语义。
6. 如果只看结果层，不看来源层，容易把“无数据”误判成“聚合丢值”。
7. 如果只看统计，不看业务语义，会把应该新增的类目错误地归并掉。

## 11. 一句话使用法

先锁定业务问题与粒度，再对候选维度做“画像-分布-映射-差集-根因”五步递进分析，最终把结论收敛为“选哪张表、认哪个 key、缺口来自哪里、应该新增还是归并”。
