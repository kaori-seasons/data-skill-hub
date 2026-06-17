# 用户行为深度分析 Skill 调研资料

## 一、RFM 模型理论基础

### 1.1 模型起源

RFM 模型最早由数据库营销领域提出，用于客户价值分层。三个维度：
- **Recency (R)**：最近一次购买/活跃的时间
- **Frequency (F)**：购买/活跃的频率
- **Monetary (M)**：购买金额/使用时长

### 1.2 评分方法

**五分位数法**：
1. 对 R/F/M 各自排序
2. 计算 20%、40%、60%、80% 分位点
3. R 评分反向（天数越少越好），F/M 评分正向

**分群决策矩阵**：
```
R≥4, F≥4, M≥4 → 重要价值客户 (~10%)
R≥4, F≥4      → 重要保持客户 (~24%)
R≤2, F≥4, M≥4 → 重要挽回客户 (~6.5%)
R≥3           → 一般活跃客户 (~45%)
R≤2           → 流失风险客户 (~15%)
```

### 1.3 模型局限性

- 基于历史行为，预测未来能力有限
- 对新用户（历史数据不足）分层不准确
- 三个维度权重相等，可能不符合实际业务
- 不考虑用户生命周期阶段

## 二、留存分析方法论

### 2.1 留存率定义

**次日留存率**：第1天新增用户中第2天仍活跃的比例
**7日留存率**：第1天新增用户中第7天仍活跃的比例
**30日留存率**：第1天新增用户中第30天仍活跃的比例

### 2.2 计算方法

```
1. 找到每个用户首次出现的日期 (first_seen)
2. 对于 D+N 留存率：
   - cohort = first_seen 为 D 天前的用户集合
   - retained = cohort 中今天仍有行为的用户
   - retention_rate = |retained| / |cohort|
```

### 2.3 行业基准

| 指标 | B2B SaaS | B2C App | 电商 | 社交 |
|------|----------|---------|------|------|
| 次日留存 | 35-45% | 25-35% | 20-30% | 40-55% |
| 7日留存 | 25-40% | 15-25% | 10-20% | 30-45% |
| 30日留存 | 15-25% | 8-15% | 5-12% | 20-35% |

## 三、流失预测模型

### 3.1 多因素加权模型

```
risk_score = Σ (factor_score × weight)

因素1: 最近活动时间 (weight = 0.4)
  days_since_last = today - last_activity_date
  if days_since_last ≥ threshold:
    factor_score = 1.0
  else:
    factor_score = days_since_last / threshold

因素2: 活动频次变化 (weight = 0.3)
  change_rate = (recent_count - previous_count) / previous_count
  if change_rate < -0.5:
    factor_score = min(1.0, abs(change_rate))

因素3: 使用时长变化 (weight = 0.2)
  计算逻辑同因素2

因素4: 功能多样性 (weight = 0.1)
  unique_features = 用户使用过的不同功能数
  if unique_features < 3:
    factor_score = (3 - unique_features) / 3
```

### 3.2 模型评估

- 准确率 (Accuracy) ≥ 85%
- 召回率 (Recall) ≥ 80%
- 精确率 (Precision) ≥ 70%
- F1 Score ≥ 75%

## 四、洞察生成规则

### 4.1 趋势洞察

触发：留存率 vs 行业基准
- gap > 20% → severity = "high"
- gap > 10% → severity = "medium"

### 4.2 异常洞察

触发：流失率超阈值
- churn_rate > 15% → severity = "critical"
- churn_rate > 10% → severity = "high"

### 4.3 模式洞察

触发：功能使用与留存率的关联性
- lift > 1.5 and p_value < 0.01 → 生成洞察

### 4.4 机会洞察

触发：VIP客户占比 vs 行业优秀水平
- gap > 5% → 生成洞察

## 五、建议模板库

### 5.1 流失挽回 (Critical)

触发：churn_rate > 10%
KPI：挽回率 ≥ 38%
时间线：立即执行，3天内完成触达

### 5.2 留存优化 (High)

触发：day7_retention < 50%
KPI：7日留存提升至50%
时间线：2周设计 + 1周开发 + 1周测试

### 5.3 功能优化 (Medium)

触发：冷门功能 ≥ 3个
KPI：节省20%开发资源
时间线：1个月评估 + 2个月执行

## 六、调研方法说明

本调研基于以下方法：
1. 收集 RFM 模型的经典论文和行业实践
2. 分析多家 SaaS 分析机构的用户行为基准数据
3. 参考产品分析工具（Mixpanel、Amplitude）的方法论
4. 研究客户流失预测的学术论文
5. 对比不同行业的用户行为特征

注意：行业基准数据会随时间变化，以最新报告为准。
