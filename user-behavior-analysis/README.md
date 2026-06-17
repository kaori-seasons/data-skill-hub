<div align="center">

# user-behavior-analysis.skill

> "我不做决策，但我让决策者看到真相。"

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/code)

**以数据驱动洞察，用 RFM 分层、留存分析、流失预测构建用户全景画像，输出可执行的业务建议。**

</div>

---

## 效果示例

> **用户：** 请分析这份用户行为数据，重点关注流失风险。
>
> **分析师：**
>
> 📊 数据质量检查：52,341 条记录，质量分数 92.5/100 ✅
>
> 📈 活跃度：DAU 8,542 / WAU 38,762 / MAU 52,341
> 7日留存 38.7% ⚠ 低于行业均值(60%)
>
> 👥 RFM 分层：重要价值客户 10% / 流失风险客户 14.5%
>
> ⚠️ 流失预测：高风险用户 7,851 (15%)
> 主要因素：连续7天+未登录 (45%)
>
> 💡 建议：① 立即启动流失用户挽回计划 ② 优化新用户引导流程 ③ 评估冷门功能价值

## 安装

```bash
npx skills add <your-org>/user-behavior-analysis
```

## 蒸馏了什么

**4 个核心思维模型：**

1. **RFM 用户价值模型** — 通过 Recency/Frequency/Monetary 三维量化用户价值
2. **留存分析漏斗** — 追踪不同时间窗口的回访率，衡量产品粘性
3. **多因素流失预测** — 综合最近活动、频次变化、时长变化、功能多样性加权计算风险
4. **洞察生成引擎** — 自动发现趋势、异常、模式、机会四类洞察

**10 条工作原则：**

数据质量先行 / 过程透明 / 量化驱动 / 行业对标 / 可执行建议 / 置信度诚实 / 边界意识 / 参数可调 / 降级可用 / 中文输出

**输出风格：**

- 树形结构展示分析层次
- emoji 前缀标记模块类型（📊📈👥⚠️💡）
- 百分比量化一切
- 每步输出中间结果，过程透明可追踪

## 调研来源

- RFM 模型经典论文与行业实践
- SaaS 行业用户行为基准数据（KeyBench、Bessemer）
- 产品分析方法论（Mixpanel、Amplitude、GrowingIO）
- 客户流失预测学术研究

## 仓库结构

```
user-behavior-analysis/
  SKILL.md                  # 主 skill 文件
  README.md                 # 本文件
  ANALYSIS-MODELS.md        # 分析模型参考手册（行业基准/算法细节/建议模板）
  LICENSE                   # MIT 许可证
  examples/
    demo-conversation.md    # 示例对话（完整分析 / 指定维度 / 参数定制）
    sample-input.json       # 示例输入数据
  references/
    research.md             # 调研资料
```

---

<div align="center">

MIT License

</div>
