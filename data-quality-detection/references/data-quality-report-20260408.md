# Data Quality Assessment Report

**Assessed:** 2026-04-08
**Platform:** TencentCloud DLC SparkSQL
**Database Layer:** data_ods / data_ads / data_dim
**Domain:** Marketing Content (抖音电商内容营销)
**Assessment Method:** Schema profiling via DLC SDK (Phase 1 Discovery)

---

## Executive Summary

**Assessment Scope:** 5 tables across 3 database layers (ODS, ADS, DIM) in the marketing content domain. All tables store Douyin (抖音) video marketing data, e-commerce gravity tasks, shop normalization info, and image file metadata.

**Overall Finding:** These tables exhibit systemic data quality risks that require immediate attention. The most critical issues are:

1. **Every column across all 5 tables is nullable** — zero NOT NULL constraints
2. **Severe type mismatch** — numeric metrics stored as `string` type instead of numeric types
3. **No column comments** on 3 of 5 tables (orphan column semantics)
4. **Questionable column classification** — metrics mislabeled as dimensions, temporal fields mislabeled as identifiers
5. **Tiny table size** for DIM reference data (100 rows) with potential PK uniqueness risk

> **Note:** This assessment is based on schema-level profiling (Phase 1 Discovery per the DDRMAP skill). Row-level statistical analysis (null rates, outliers, dirty values) requires direct query access to the DLC warehouse, which was not available during this session. The findings below are structural and architectural in nature.

---

## Table-by-Table Analysis

### Table 1: `data_ods.ods_rpa_douyin_compass_video`

| Attribute | Value |
|---|---|
| **Rows** | 203,568 |
| **Columns** | 50 |
| **Database Layer** | ODS (Operational Data Store) |
| **Purpose** | 抖音罗盘视频数据 (Douyin Compass video metrics) |

#### Schema Profile

| Category | Count | Columns |
|---|---|---|
| Identifier | 9 | id, douyin_unique_id, aweme_id, video_link, video_duration, video_create_time, product_id, local_video_url, *implicit* |
| Dimension | 8 | live_click_rate, finish_watch_rate, cart_type, account_type, time_type, avg_watch_duration, product_expose_click_rate, product_click_pay_rate, product_expose_pay_rate |
| Measure | 24 | pay_amt, watch_cnt, live_flow_cnt, other_user_pay_amt, like_cnt, comment_cnt, collect_cnt, share_cnt, follow_click_cnt, product_expose_cnt, product_click_cnt, user_pay_amt, order_cnt, pay_user_cnt, refund_amt, refund_order_cnt, product_thousand_expose_pay_amt, ad_cost, live_user_pay_amt, live_expose_cnt, live_order_cnt, live_thousand_expose_pay_amt, after_search_pay_amt, after_search_expose_cnt, after_search_click_cnt, after_search_order_cnt, shop_page_pay_amt, shop_page_order_cnt, other_order_cnt |
| Descriptive | 3 | shop_name, nick_name, title |
| Flag | 1 | is_ad |
| Temporal | 2 | update_time, create_time |

#### Critical Findings

**[CRITICAL] C1.1 — Rate/percentage fields stored as STRING type**
- Columns: `live_click_rate`, `finish_watch_rate`, `product_expose_click_rate`, `product_click_pay_rate`, `product_expose_pay_rate`, `avg_watch_duration`
- Impact: Cannot perform numeric aggregation, comparison, or filtering without CAST. Downstream BI tools will fail on SUM/AVG. RPA scraping dumps raw strings, but the ODS layer should normalize.
- Remediation: Add ETL step to CAST to `DECIMAL(10,4)` or `DOUBLE`. Validate that values are parseable numbers.

**[CRITICAL] C1.2 — `video_duration` classified as identifier, should be measure/dimension**
- The column stores video duration (a numeric metric), but was classified as `identifier` based on name heuristics.
- Impact: May be excluded from numeric quality checks. Duration analysis (avg watch time correlation) requires numeric treatment.

**[CRITICAL] C1.3 — `is_ad` is STRING type for a boolean flag**
- Stores "是否投放" (whether ad was placed) — inherently boolean.
- Impact: Risk of dirty values ("是"/"否"/"1"/"0"/"true"/"true"/null). No enum constraint.
- Remediation: Validate distinct values. Map to BOOLEAN in downstream layers.

**[WARNING] W1.1 — All 50 columns are nullable**
- Zero NOT NULL constraints on any column, including `id`, `aweme_id`, `create_time`.
- Impact: Primary key `id` could be null, making dedup impossible. Mandatory business fields have no enforcement.

**[WARNING] W1.2 — `video_create_time` classified as identifier, not temporal**
- This is a timestamp (视频发布时间). Misclassification means temporal consistency checks may skip it.

**[WARNING] W1.3 — Duplicate semantics: `pay_amt` vs `user_pay_amt` vs `live_user_pay_amt`**
- Three columns for "payment amount" with different scopes. Risk of misuse in downstream aggregations if consumers pick the wrong one.

**[INFO] I1.1 — No column comments on all 50 columns**
- All comments are empty strings. ODS tables should document the source system and field mapping.

---

### Table 2: `data_ods.ods_rpa_efficient_and_high_salary_douyin_video_df`

| Attribute | Value |
|---|---|
| **Rows** | 5,114,783 |
| **Columns** | 21 |
| **Database Layer** | ODS |
| **Purpose** | 高效高薪抖音视频数据 (RPA-crawled Douyin video performance) |

#### Schema Profile

| Category | Count | Columns |
|---|---|---|
| Identifier | 1 | id |
| Descriptive | 3 | title, live_room_name, shop_name |
| Dimension | 16 | publish_time, genre, status, play_count, finish, finish5s, cover_click_ratio, skip2s, play_avg_time, like_count, share_count, comment_count, collect_count, visit_count, increase_fans_count, update_time, dt |
| Measure | 0 | — |
| Temporal | 0 | — |

#### Critical Findings

**[CRITICAL] C2.1 — ALL metric columns stored as STRING type**
- Columns: `play_count`, `finish`, `finish5s`, `cover_click_ratio`, `skip2s`, `play_avg_time`, `like_count`, `share_count`, `comment_count`, `collect_count`, `visit_count`, `increase_fans_count`
- These are all numeric metrics (播放量, 完播率, 点赞数, etc.) but stored as strings.
- Impact: 5.1M rows of metrics that cannot be directly aggregated, sorted numerically, or used in statistical analysis without CAST. This is the largest table in the assessment and the type mismatch affects the most rows.

**[CRITICAL] C2.2 — `publish_time` is STRING type, not TIMESTAMP**
- The video publish time is stored as string. Temporal queries (date range, recency) require parsing.
- Impact: Cannot use DATE functions directly. Risk of inconsistent date formats across 5.1M rows.

**[CRITICAL] C2.3 — `dt` partition column is STRING type**
- Standard partition column should be DATE type. STRING partitions may have format inconsistencies ("2026-04-08" vs "20260408" vs "2026/04/08").

**[WARNING] W2.1 — No measure columns classified — everything is dimension**
- The auto-classifier treated all STRING-typed numeric columns as dimensions. This means 0 columns receive numeric quality checks (outlier detection, range validation).
- Impact: Data quality tooling will skip the most important validation step for the largest table.

**[WARNING] W2.2 — All 21 columns nullable, including `id`**
- Same systemic issue as Table 1.

**[WARNING] W2.3 — No column comments on any field**
- All 21 columns have empty comments. No documentation of what "finish", "finish5s", "skip2s" mean.

**[INFO] I2.1 — `status` column: unknown enum values**
- Without data access, cannot verify if status values conform to expected set.

---

### Table 3: `data_ads.ads_dewu_gravity_task_df`

| Attribute | Value |
|---|---|
| **Rows** | 3,903,537 |
| **Columns** | 35 |
| **Database Layer** | ADS (Application Data Store) |
| **Purpose** | 得物引力任务数据 (Dewu gravity/attraction task data) |

#### Schema Profile

| Category | Count | Columns |
|---|---|---|
| Identifier | 5 | parent_task_id, task_id, video_duration, video_avg_play_time, mid_category, guide_goods_fav_cnt |
| Dimension | 21 | data_date, right_sku, task_published_datetime, task_promote_type, task_mode, task_status, task_finished_datetime, task_amount_2, author, dynamic_published_datetime, play_ratio_3s, fullchainordcnt_2, fullchaingmv_2, time_type, sku, attribute_14d_gmv, attribute_14d_order, clothes_exposure_num, clothes_read_num, clothes_order_num |
| Measure | 5 | read_volume, visit_volume, page_viewer_volume, interact_volume, detail_access_amt, dynamic_click_rate, guide_detial_rate |
| Descriptive | 2 | shop_name, task_name, dynamic_link |

#### Critical Findings

**[CRITICAL] C3.1 — Revenue/metric columns stored as STRING in an ADS layer**
- Columns: `task_amount_2`, `fullchainordcnt_2`, `fullchaingmv_2`, `attribute_14d_gmv`, `attribute_14d_order`, `clothes_exposure_num`, `clothes_read_num`, `clothes_order_num`
- This is the ADS (application) layer, the final serving layer for BI dashboards. Storing GMV, order counts, and exposure metrics as strings is a fundamental design flaw.
- Impact: Dashboard queries must CAST at read time. Performance degradation. Risk of parse failures.

**[CRITICAL] C3.2 — All datetime fields are STRING type**
- Columns: `data_date`, `task_published_datetime`, `task_finished_datetime`, `dynamic_published_datetime`
- None are TIMESTAMP or DATE type.
- Impact: Cannot do temporal consistency checks (e.g., task_finished > task_published). Cannot partition efficiently.

**[CRITICAL] C3.3 — `guide_detial_rate` — typo in column name**
- "detial" should be "detail". If downstream code references the correct spelling, queries will fail silently.

**[WARNING] W3.1 — Column classification errors**
- `video_duration` and `video_avg_play_time` classified as `identifier` — these are measures.
- `guide_goods_fav_cnt` (引导商品收藏数) classified as `identifier` — this is a measure.
- `play_ratio_3s` classified as `dimension` — this is a ratio metric.
- Impact: Quality checks will miss these columns.

**[WARNING] W3.2 — `task_id` and `parent_task_id` — no PK constraint**
- Task IDs should be unique primary keys. Without constraints, duplicate task IDs could corrupt aggregations.

**[WARNING] W3.3 — `mid_category` classified as identifier**
- This is a dimension (商品中类), not an identifier.

**[INFO] I3.1 — `fullchaingmv_2` and `fullchainordcnt_2` — cryptic naming**
- The `_2` suffix suggests a versioned or derived metric. No comments explain the distinction.

---

### Table 4: `data_dim.dim_shop_normalized_info`

| Attribute | Value |
|---|---|
| **Rows** | 100 |
| **Columns** | 5 |
| **Database Layer** | DIM (Dimension) |
| **Purpose** | 店铺规整维度表 (Normalized shop dimension table) |

#### Schema Profile

| Category | Count | Columns |
|---|---|---|
| Identifier | 1 | erp_shop_id |
| Dimension | 2 | platform, shop_nick |
| Descriptive | 2 | normalized_shop_name, brand_name |

#### Critical Findings

**[CRITICAL] C4.1 — Only 100 rows for a dimension table**
- A shop normalization dimension covering multiple platforms (抖音, 得物, etc.) with only 100 entries is extremely small.
- Risk: Either the coverage is incomplete, or this is a filtered/stale snapshot.
- Remediation: Verify against source system. Compare row count against expected shop count.

**[WARNING] W4.1 — `erp_shop_id` nullable and not enforced as PK**
- The shop ID is the natural primary key. If nullable, null shops will join incorrectly.

**[WARNING] W4.2 — No unique constraint on `erp_shop_id`**
- Duplicate shop IDs would cause fanout in downstream joins with fact tables.

**[WARNING] W4.3 — `platform` column: potential enum consistency risk**
- Values like "抖音"/"douyin"/"Douyin" or "得物"/"dewu" need to be consistent with how fact tables reference the platform.

**[INFO] I4.1 — Small table, low statistical significance**
- With only 100 rows, many statistical quality checks (outlier detection, distribution analysis) are not meaningful.

---

### Table 5: `data_ods.ods_t_image_file_information`

| Attribute | Value |
|---|---|
| **Rows** | 278 |
| **Columns** | 22 |
| **Database Layer** | ODS |
| **Purpose** | 图片文件信息表 (Image file metadata) |

#### Schema Profile

| Category | Count | Columns |
|---|---|---|
| Identifier | 4 | id, file_id, width, height |
| Dimension | 11 | file_format, file_type, create_time, last_modify_time, config_staff, platform, store, live_room, spu, sku, data_fetch_time, data_update_time |
| Measure | 1 | file_size |
| Descriptive | 4 | folder_path, file_name, full_path, business_path |
| Flag | 1 | is_delete |
| Temporal | 0 | — |

#### Critical Findings

**[CRITICAL] C5.1 — `width` and `height` classified as identifier, should be measure**
- Image dimensions are numeric metrics. Classifying them as identifiers excludes them from range validation.
- Impact: Cannot detect corrupted images (width=0 or height=99999).

**[CRITICAL] C5.2 — `create_time` and `last_modify_time` are STRING type, not TIMESTAMP**
- Same temporal query issues as other tables.

**[CRITICAL] C5.3 — `is_delete` is BOOLEAN type but nullable**
- A soft-delete flag should default to `false`. If nullable, queries filtering `WHERE is_delete = false` will miss null rows.

**[WARNING] W5.1 — `width` and `height` are STRING type, not INT**
- Image dimensions should be integer pixels. String storage prevents arithmetic (e.g., aspect ratio = width/height).

**[WARNING] W5.2 — `file_size` is the only measure, and it's nullable**
- File size should never be null for an existing file record.

**[WARNING] W5.3 — Only 278 rows — very small ODS table**
- May indicate a filtered snapshot, a test dataset, or an incomplete ETL load.

**[INFO] I5.1 — `business_path` vs `folder_path` vs `full_path` — three path columns**
- Three different path columns could cause confusion. Verify they serve distinct purposes.

---

## Cross-Table Analysis

### Systemic Issues

| Issue | Affected Tables | Severity |
|---|---|---|
| All columns nullable | All 5 | Critical |
| Numeric metrics stored as STRING | 4 of 5 (all except dim_shop) | Critical |
| No column comments | 3 of 5 | Warning |
| Temporal fields as STRING | 4 of 5 | Critical |
| Auto-classifier mislabels | All 5 | Warning |
| No PK/unique constraints | All 5 | Warning |

### Data Flow Integrity

```
                    ┌─────────────────────────┐
                    │  ods_rpa_douyin_compass  │ (203K rows)
                    │  ods_rpa_efficient_...   │ (5.1M rows)
                    │  ods_t_image_file_info   │ (278 rows)
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  ads_dewu_gravity_task   │ (3.9M rows)
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  dim_shop_normalized     │ (100 rows)
                    └─────────────────────────┘
```

**Cross-table join risk:** `shop_name` appears in `ods_rpa_douyin_compass_video`, `ads_dewu_gravity_task_df`, and `ods_rpa_efficient_and_high_salary_douyin_video_df` as a descriptive string. The DIM table uses `shop_nick` and `normalized_shop_name`. Without a shared `erp_shop_id` key in the fact tables, shop name matching will rely on fuzzy string matching, which is error-prone.

**`sku` field appears in both `ads_dewu_gravity_task_df` and `ods_t_image_file_information`** — potential join path, but no foreign key validation possible.

---

## DDRMAP Dimension Scores (Schema-Level Assessment)

Since row-level data was not accessible, these scores reflect structural/architectural quality only. They represent "design quality" rather than "data quality."

| Dimension | Score | Rationale |
|---|---|---|
| **Completeness** | 40/100 | All columns nullable. No mandatory field enforcement. Missing column comments on 3 tables. |
| **Accuracy** | 50/100 | Type mismatches (string for numeric) make accuracy validation structurally impossible without CAST. Auto-classifier mislabels hide columns from quality checks. |
| **Consistency** | 45/100 | Shop name used as join key across tables but no normalization key. Column naming inconsistent (`_2` suffixes, typos like "detial"). |
| **Conformity** | 35/100 | Temporal fields not using TIMESTAMP type. Numeric fields stored as STRING. Boolean flags as STRING. Partition columns as STRING. |
| **Integrity** | 50/100 | No PK constraints. No FK constraints. No referential integrity enforcement. Row counts seem reasonable but unverified. |
| **Timeliness** | 60/100 | ODS tables have `update_time`/`create_time` columns. ADS table has `data_date`. But all are STRING type, preventing freshness SLA calculations. |

**Composite Score: 46/100 — Critical**

> This score reflects structural/architectural quality only. Actual row-level quality (null rates, outlier detection, dirty values) requires direct query access to the DLC warehouse and was not performed in this session.

---

## Prioritized Recommendations

### Immediate (Critical — fix this week)

1. **Add NOT NULL constraints on primary key columns**
   - `ods_rpa_douyin_compass_video.id`
   - `ods_rpa_efficient_and_high_salary_douyin_video_df.id`
   - `ads_dewu_gravity_task_df.task_id`
   - `dim_shop_normalized_info.erp_shop_id`
   - `ods_t_image_file_information.file_id`

2. **Convert STRING metric columns to numeric types in ETL**
   - All rate/percentage columns: CAST to `DECIMAL(10,4)`
   - All count columns: CAST to `BIGINT`
   - All amount columns: keep as `DECIMAL(10,2)` (already correct in some tables)

3. **Convert STRING temporal columns to TIMESTAMP/DATE**
   - `publish_time`, `dt`, `data_date`, `task_published_datetime`, `task_finished_datetime`, `dynamic_published_datetime`, `create_time`, `last_modify_time`, `data_fetch_time`, `data_update_time`

4. **Fix typo: `guide_detial_rate` → `guide_detail_rate`**

### This Sprint (Warning)

5. **Add column comments** to all tables, especially ODS tables with empty comments
6. **Validate `is_ad` enum values** — ensure only valid boolean representations
7. **Add unique constraints** on task_id, erp_shop_id, file_id (at ETL level if not at DDL level)
8. **Reclassify columns** — fix the auto-classifier so rate fields, dimensions, and measures are correctly categorized
9. **Verify `dim_shop_normalized_info` coverage** — 100 rows seems too small for a multi-platform dimension

### Backlog (Info)

10. **Standardize shop_name** — add `erp_shop_id` to fact tables to enable proper dimension joins
11. **Resolve triple-path columns** in `ods_t_image_file_information` (folder_path, full_path, business_path)
12. **Document `_2` suffix columns** in `ads_dewu_gravity_task_df`
13. **Consider adding `dt` partition** to `ods_rpa_douyin_compass_video` and `ods_t_image_file_information` for partition pruning

---

## Recommended Quality Monitoring Queries

Run these queries on the DLC warehouse to complete the assessment:

```sql
-- 1. Null rate on primary key columns
SELECT
  'ods_rpa_douyin_compass_video.id' AS check,
  SUM(CASE WHEN id IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS null_rate
FROM data_ods.ods_rpa_douyin_compass_video;

-- 2. Duplicate PK check
SELECT task_id, COUNT(*) AS cnt
FROM data_ads.ads_dewu_gravity_task_df
GROUP BY task_id
HAVING COUNT(*) > 1
LIMIT 20;

-- 3. String-to-numeric parse validation
SELECT
  play_count,
  COUNT(*) AS cnt
FROM data_ods.ods_rpa_efficient_and_high_salary_douyin_video_df
WHERE play_count IS NOT NULL
  AND play_count NOT RLIKE '^-?[0-9]+\\.?[0-9]*$'
GROUP BY play_count
ORDER BY cnt DESC
LIMIT 20;

-- 4. is_ad enum validation
SELECT is_ad, COUNT(*) AS cnt
FROM data_ods.ods_rpa_douyin_compass_video
GROUP BY is_ad
ORDER BY cnt DESC;

-- 5. Temporal consistency
SELECT COUNT(*) AS future_dates
FROM data_ods.ods_rpa_douyin_compass_video
WHERE video_create_time > CURRENT_TIMESTAMP();

-- 6. DIM coverage check
SELECT platform, COUNT(DISTINCT erp_shop_id) AS shop_count
FROM data_dim.dim_shop_normalized_info
GROUP BY platform;
```

---

## Assessment Limitations

1. **No row-level data access** — This assessment was performed via schema metadata only. Null rates, outlier detection, dirty value analysis, and statistical profiling were not computed.
2. **Auto-classifier confidence** — All column classifications are marked `assumed` (heuristic-based), not `confirmed` (human-verified).
3. **No historical data** — Cannot assess data freshness, partition gaps, or row count trends without time-series data.
4. **Cross-table joins unverified** — Referential integrity between tables could not be validated without query execution.

**Recommended next step:** Execute the monitoring queries above via DLC query console, then re-run the full DDRMAP assessment with row-level data.

---

*Report generated by data-quality-test skill (DDRMAP framework)*
*Assessment timestamp: 2026-04-08T11:00+08:00*
*Platform: TencentCloud DLC SparkSQL (ap-shanghai)*
