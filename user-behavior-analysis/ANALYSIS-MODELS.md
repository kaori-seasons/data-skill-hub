# 分析模型参考手册

本文档是 `user-behavior-analysis` Skill 的补充参考，包含各分析模型的详细算法和行业基准。

---

## 1. 行业基准数据

| 指标 | B2B SaaS | B2C App | 电商 | 社交 |
|------|----------|---------|------|------|
| DAU/MAU | 15-25% | 20-35% | 10-20% | 40-60% |
| 次日留存 | 35-45% | 25-35% | 20-30% | 40-55% |
| 7日留存 | 25-40% | 15-25% | 10-20% | 30-45% |
| 30日留存 | 15-25% | 8-15% | 5-12% | 20-35% |
| 月流失率 | 3-5% | 5-10% | 8-15% | 2-4% |

---

## 2. RFM 评分算法

### 2.1 五分位数法

```
输入: N 个用户的 R/F/M 原始值
步骤:
  1. 对每个维度排序
  2. 计算 20%、40%、60%、80% 分位点
  3. 根据分位点映射 1-5 分

R 评分（反向，天数越少越好）:
  R ≤ P20 → 5分
  P20 < R ≤ P40 → 4分
  P40 < R ≤ P60 → 3分
  P60 < R ≤ P80 → 2分
  R > P80 → 1分

F 评分（正向，次数越多越好）:
  F ≥ P80 → 5分
  P60 ≤ F < P80 → 4分
  P40 ≤ F < P60 → 3分
  P20 ≤ F < P40 → 2分
  F < P20 → 1分

M 评分: 同 F 评分逻辑
```

### 2.2 分群决策矩阵

```
输入: R_score, F_score, M_score (各 1-5)

决策树:
  if R ≥ 4:
    if F ≥ 4:
      if M ≥ 4: → "重要价值客户" (高R高F高M)
      else:     → "重要保持客户" (高R高F低M)
    else:
      → "一般活跃客户" (高R低F)
  else:  # R < 4
    if F ≥ 4 and M ≥ 4:
      → "重要挽回客户" (低R高F高M — 曾经很好，现在不行了)
    else:
      → "流失风险客户" (低R)
```

---

## 3. 流失风险评分模型

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
  recent_count = 近30天行为次数
  previous_count = 前30天行为次数
  if previous_count > 0:
    change_rate = (recent_count - previous_count) / previous_count
    if change_rate < -0.5:
      factor_score = min(1.0, abs(change_rate))
    else:
      factor_score = 0.0

因素3: 使用时长变化 (weight = 0.2)
  计算逻辑同因素2，用 duration 替代 count

因素4: 功能多样性 (weight = 0.1)
  unique_features = 用户使用过的不同功能数
  if unique_features < 3:
    factor_score = (3 - unique_features) / 3
  else:
    factor_score = 0.0

判定:
  risk_score ≥ 0.6 → 高风险
  0.3 ≤ risk_score < 0.6 → 中风险
  risk_score < 0.3 → 低风险
```

### 3.2 模型评估指标

```
准确率 (Accuracy): 预测正确的比例
  target: ≥ 85%

召回率 (Recall): 实际流失用户中被正确识别的比例
  target: ≥ 80%

精确率 (Precision): 预测为流失的用户中实际流失的比例
  target: ≥ 70%

F1 Score: 精确率和召回率的调和平均
  target: ≥ 75%
```

---

## 4. 洞察生成规则

### 4.1 趋势洞察

```
触发: 留存率 vs 行业基准
  gap = industry_benchmark - actual_retention
  if gap > 20%:
    severity = "high"
  elif gap > 10%:
    severity = "medium"
  else:
    severity = "low"

置信度 = 0.95 (基于统计显著性)
```

### 4.2 异常洞察

```
触发: 流失率超阈值
  if churn_rate > 0.15:
    severity = "critical"
  elif churn_rate > 0.10:
    severity = "high"
  elif churn_rate > 0.05:
    severity = "medium"

置信度 = 模型准确率
```

### 4.3 模式洞察

```
触发: 功能使用与留存率的关联性
  for each feature:
    retention_with = 使用该功能用户的留存率
    retention_without = 未使用该功能用户的留存率
    lift = retention_with / retention_without
    if lift > 1.5 and p_value < 0.01:
      → 生成洞察: "使用{feature}的用户留存率显著更高"
      severity = "medium"
      confidence = 1 - p_value
```

### 4.4 机会洞察

```
触发: VIP客户占比 vs 行业优秀水平
  gap = industry_excellent - actual_vip_ratio
  if gap > 5%:
    → 生成洞察: "VIP客户占比有提升空间"
    severity = "medium"
    impact_score = gap × 2
```

---

## 5. 建议模板库

### 5.1 流失挽回 (Critical)

```
触发: churn_rate > 10%
行动: 针对流失风险用户推送个性化挽回内容
KPI: 挽回率 ≥ 38%
时间线: 立即执行，3天内完成触达
负责人: 用户运营团队

实施步骤:
1. 导出高风险用户清单，按风险等级排序
2. 分析每个用户的历史行为偏好
3. 设计分层挽回策略:
   - 高价值用户: 专属客服 + 限时折扣
   - 中价值用户: 功能推荐 + 使用教程
   - 低价值用户: 产品更新通知
4. 通过邮件/短信/APP推送多渠道触达
5. 7天后评估挽回效果，优化策略
```

### 5.2 留存优化 (High)

```
触发: day7_retention < 50%
行动: 优化新用户引导流程，突出高留存功能
KPI: 7日留存提升至50%
时间线: 2周设计 + 1周开发 + 1周测试
负责人: 产品团队 + 设计团队

实施步骤:
1. 分析新用户首日行为路径
2. 识别"aha moment"（留存率拐点行为）
3. 重新设计 onboarding 流程:
   - Step 1: 引导创建第一个内容
   - Step 2: 邀请团队成员协作
   - Step 3: 使用核心功能完成任务
4. 增加成就系统和进度激励
5. A/B 测试验证效果
```

### 5.3 功能优化 (Medium)

```
触发: 冷门功能 ≥ 3个
行动: 评估冷门功能，优化或下线
KPI: 节省20%开发资源
时间线: 1个月评估 + 2个月执行
负责人: 产品团队 + 研发团队

实施步骤:
1. 分析冷门功能的使用场景和用户画像
2. 调研用户不使用的原因
3. 评估功能的战略价值
4. 制定优化或下线方案
5. 制定用户迁移和沟通计划
```
