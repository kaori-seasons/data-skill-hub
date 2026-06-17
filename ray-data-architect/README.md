<div align="center">

# ray-data-architect.skill

> "先读代码再说话，先对比再推荐，先辩证再输出。"

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/code)

**以资深架构师视角分析 Ray Data 的数据下推与数据分发问题，输出生产可用的技术设计方案。**

</div>

---

## 效果示例

> **用户：** Ray Data 读取 Parquet 时全量加载再过滤，选择率 1% 时性能很差，需要设计 filter pushdown。
>
> **架构师：** 先搜一下现有的 Parquet 读取实现...
>
> 📋 需求解析：核心问题是 ParquetDatasource 未利用 row group 统计信息过滤
>
> 📊 四维度分析：
> - 背景：Spark/Polars 均已支持，这是行业标配
> - 约束：不能破坏 map_batches API，pyarrow filters 不支持 UDF
> - 折中：自动识别（复杂）vs 显式 hint（简单）vs 混合模式
> - 改进：短期 hint → 中期自动 → 长期统一抽象
>
> 🔄 自我辩证：假设用户愿意手动传入 filter 需要验证...
>
> 📝 推荐方案：Phase 1 显式 hint（1周），Phase 2 自动下推（2周）

## 安装

```bash
npx skills add <your-org>/ray-data-architect
```

## 蒸馏了什么

**5 个核心思维模型：**

1. **四维度分析框架** — 任何设计都从背景、约束、折中、改进四个维度审视
2. **多方案对比决策** — 不存在唯一正确方案，只有约束下的最优选择
3. **自我辩证循环** — 输出前必须从反对者角度攻击自己的设计
4. **行业对标法** — 先看 Spark/Dask/Polars 怎么做，再结合 Ray 特点适配
5. **渐进式落地** — 大方案拆小步骤，每步可验证、可回滚

**10 条工作原则：**

代码为证 / 多方案对比 / 自我辩证 / 可落地性 / 边界意识 / 向后兼容 / 简单优先 / 承认无知 / 行业对标 / 中文输出

**输出风格：**

- 表格化对比（方案矩阵、约束清单）
- 树形结构展示层次（需求解析、代码路径）
- 代码路径精确到行号
- emoji 前缀标记模块类型

## 调研来源

- Ray Data 源码 (`python/ray/data/_internal/`)
- Ray Data 官方文档与 RFC
- Spark Catalyst Optimizer 文档
- Polars LazyFrame 查询优化
- Apache Arrow / Parquet 规范

## 仓库结构

```
ray-data-architect/
  SKILL.md                  # 主 skill 文件
  README.md                 # 本文件
  DESIGN-MODELS.md          # 设计模型参考手册（行业基准/设计模式/陷阱）
  LICENSE                   # MIT 许可证
  examples/
    demo-conversation.md    # 示例对话（完整设计案例 + quick 调研案例）
  references/
    research.md             # 调研资料（Ray Data 架构知识库）
```

---

<div align="center">

MIT License

</div>
