---
name: core-dimension-distribution-causal-reasoning
description: Use when you need to identify the real core dimensions of a table, compare competing base tables, analyze field distributions, evaluate mapping cardinality, explain gaps between image/video or source/result layers, or perform causal reasoning about why a dimension becomes '无', missing, skewed, or multi-mapped.
---

# Core Dimension Distribution And Causal Reasoning

Use this skill when the main question is not merely "what are the top values", but:

- which dimensions are truly stable enough to drive analysis
- which key should be treated as the business anchor
- why a dimension is missing, skewed, or inconsistent across layers
- whether a value gap should be merged, added, or traced back upstream

## What This Skill Solves

- choose the real base table among multiple candidates
- choose the right key among `session_id`, `live_room_id`, `child_order_id`, `spu`, `sku`, `product_id`
- explain heavy default values like `无` or `其他`
- analyze image-vs-video dimension gaps
- analyze source-vs-result layer loss
- decide whether a dimension difference means new enum, merge candidate, or pipeline loss

## First Principles

A field is a core dimension only if it is:

1. identifiable in runtime schema
2. sufficiently covered
3. semantically interpretable
4. stably connectable to other important fields

Always analyze in this order:

1. business question
2. grain
3. field profile
4. value distribution
5. mapping cardinality
6. cross-layer gap
7. causal explanation

If grain is unclear, the rest of the analysis is likely misleading.

## Workflow

### 1. Define the business question first

Examples:

- live-commerce operations: `session_id`, `child_order_id`, `product_id`, `pay_amount`
- content attribution: `file_id`, `platform_source_id`, `spu`, `sku`
- product semantics: `big_cate`, `mid_cate`, `track`, `gender`, `scene`, `style`

Do not start from field names alone.

### 2. Lock the grain before selecting dimensions

Ask:

- what does one row represent?
- what does one key represent?
- can this key recur across date, platform, session, or product?

Typical anti-patterns seen in the bundled evidence:

- `live_room_id` assumed to equal one session
- `spu` used where `sku` is required
- a light result table treated as equivalent to a richer fact table

### 3. Profile candidate dimensions

For each candidate dimension, collect:

- physical-column hit
- total rows
- null rows
- null ratio
- distinct count
- obvious dirty/default values

Start with:

- `scripts/run_live_core_dimension_probe.py`
- `scripts/run_taobao_live_orders_core_dimension_report.py`
- `scripts/run_content_core_dimension_report.py`

### 4. Read the distribution correctly

Check at minimum:

- Top1 ratio
- Top10 cumulative ratio
- total distinct values
- ratio of `无` / `其他` / blanks

Interpretation rules:

- high `无` often implies missing upstream labels or wrong field sourcing
- very high Top1 may be real business concentration, or collapsed dirty defaults
- extreme long tail may indicate uncontrolled dictionary granularity or missing merge rules

### 5. Evaluate mapping cardinality

Distribution alone is not enough. Measure relationships between dimensions.

Key examples:

- `child_order_id -> session_id`
- `product_id -> spu`
- `spu -> sku_id`
- `live_room_id -> pay_date`
- `spu -> live_room_id`

Include:

- average targets per source
- p50 / p90 / max
- multi-mapping source ratio

Use:

- `scripts/run_order_live_room_spu_distribution_probe.py`
- `scripts/run_live_core_dimension_probe.py`

### 6. Compare layers and rule coverage

When a value appears in one layer but not another, split the cause:

1. missing already in source
2. lost in result layer
3. absent from reference enum set
4. uncovered by historical rule set

Use:

- `scripts/run_picture_mid_track_gap_report.py`
- `scripts/run_picture_video_midcate_rule_gap_report.py`
- `scripts/run_picture_video_midcate_action_plan_report.py`
- `scripts/run_sample_002_gender_gap_report.py`

## Causal Reasoning Templates

### A. Large `无` bucket

Test in order:

1. upstream field truly empty
2. wrong source field selected
3. join miss
4. rule collapses valid values into `无`

`scripts/run_sample_002_gender_gap_report.py` is the reference pattern for this kind of diagnosis.

### B. Image has it, video does not

Test in order:

1. video source layer has no such data
2. video result layer dropped it
3. historical rules never covered it
4. it should be a legitimate new enum rather than a merge target

### C. Strong one-to-many or many-to-many mapping

Interpretation:

- the key is probably not the business anchor
- grain may be wrong
- a bridge layer may be required
- a time-window/session key may be required

### D. Competing base tables

Prefer the table with stronger evidence on:

- row coverage
- core-field hit count
- typed time fields
- presence of key enhancement dimensions

## Bundled Scripts

- `scripts/run_live_core_dimension_probe.py`
- `scripts/run_content_core_dimension_report.py`
- `scripts/run_taobao_live_orders_core_dimension_report.py`
- `scripts/run_spu_cluster_distribution_report.py`
- `scripts/run_spu_mid_track_cluster_report.py`
- `scripts/run_picture_mid_track_gap_report.py`
- `scripts/run_picture_video_midcate_rule_gap_report.py`
- `scripts/run_picture_video_midcate_action_plan_report.py`
- `scripts/run_sample_002_gender_gap_report.py`
- `scripts/run_order_live_room_spu_distribution_probe.py`

## Bundled References

Read only what the current task needs:

- `references/spu-cluster-distribution-report-20260420.md`
- `references/spu-mid-track-cluster-report-20260420.md`
- `references/picture-mid-track-gap-report-20260420.md`
- `references/picture-video-midcate-rule-gap-report-20260420.md`
- `references/picture-video-midcate-action-plan-report-20260420.md`
- `references/sample-002-gender-gap-report-20260421.md`
- `references/order-live-room-spu-distribution-probe-20260422.md`
- `references/鞋服电商短视频报告.pdf`
- `references/短视频五张表核心维度规整报告.pdf`

## Output Standard

A good result should contain:

1. question definition
2. grain definition
3. core-field hit table
4. field profile
5. distribution summary
6. cardinality summary
7. cross-layer gap summary
8. causal conclusion
9. action bucket
10. explicit residual uncertainty

## Action Buckets

Most conclusions should land in one of these:

- primary analysis base table
- auxiliary comparison table
- new enum candidate
- merge candidate
- wrong source field
- missing bridge layer
- need stronger session key
- should aggregate by distinct key instead of row count
- requires manual review because confidence is low

## Self-Critique Checklist

- Is the skew real business concentration or dirty-value collapse?
- Is the gap a bug or a legitimate new category?
- Is the mapping problem actually proof that the chosen key is not a key?
- Is a merge recommendation flattening meaningful business semantics?
- Did the analysis separate source absence from downstream loss?

If not, keep the final recommendation conditional.
