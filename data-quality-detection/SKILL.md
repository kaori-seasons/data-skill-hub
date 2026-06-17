---
name: data-quality-detection
description: Use when you need to diagnose data quality problems in tables, SQL pipelines, bridge tables, path fields, enum fields, null-heavy dimensions, or frontend-vs-warehouse discrepancies. This skill traces issues to source pollution, SQL mapping mistakes, missing bridge keys, wrong grain selection, rule coverage gaps, or display-layer formatting.
---

# Data Quality Detection

Use this skill when the task is not just "run null checks", but "explain why the data cannot be trusted and where the break actually happens."

## What This Skill Solves

This skill is built for questions like:

- Which table is safe to use as the analysis base table?
- Is the bad value already present in ODS, or introduced by downstream SQL?
- Is the issue caused by source pollution, bridge-table failure, wrong field sourcing, or frontend formatting?
- Why do path fields, platform fields, or enum fields look wrong?
- Why do planned bridge keys exist in design docs but not in runtime tables?

## First Principles

Treat data quality as a decision-support problem, not a formatting problem.

The skill assumes:

1. A field is "high quality" only if it can still support stable business decisions.
2. A finding is incomplete unless it is attached to a concrete break point.
3. Single-table evidence is weak; cross-layer evidence is preferred.
4. High fill rate does not imply correct semantics.
5. Every major conclusion should be backed by representative samples.

## Workflow

### 1. Define the expected contract

Before querying, define:

- target grain
- key fields
- required dimensions
- required metrics
- derived metrics that should not be mistaken for physical columns

Read these when relevant:

- `references/four-table.pdf`
- `references/data-quality-report-20260408.md`

### 2. Confirm the runtime object

Do not trust only the planned table name.

Check:

- whether the table exists
- whether the runtime columns match the design
- whether a result table is missing and requires fallback to source tables
- whether same-name fields are actually sourced from different places

Useful scripts:

- `scripts/run_table124_quality_report.py`
- `scripts/run_total_hours_sql_field_probe.py`
- `scripts/build_sql_data_map.py`

### 3. Run six layers of checks

#### Structure

- schema completeness
- type mismatches
- comment/documentation gaps
- all-nullable design

#### Value quality

- null / blank rates
- dirty characters
- overlong values
- path suffix anomalies
- file-name vs full-path conflicts

#### Key and grain

- duplicate primary keys
- one-file-many-rows / one-order-many-rows / one-instance-many-rows
- distinct-count collapse

#### Enum and distribution

- mixed semantic/process/test values
- target/reference enum mismatches
- values that appear on only one side

#### Freshness and temporal sanity

- min/max timestamps
- future dates
- extreme stale dates
- fields that exist in schema but are empty in live runtime

#### Cross-layer and lineage

- source vs downstream consistency
- bridge-table breaks
- semantic miswrite such as `full_path` written into a folder-like field
- frontend display-layer formatting differences

## Root-Cause Buckets

Force each major issue into one of these buckets:

1. Source pollution
2. SQL mapping mistake
3. Missing bridge key or incomplete bridge table
4. Wrong grain or wrong key choice
5. Rule coverage gap
6. Frontend / interface formatting deviation

If a finding does not fit a bucket, the diagnosis is still incomplete.

## Script Selection Guide

Use the smallest relevant artifact set first.

### General row-level checks

- `scripts/run_quality_checks.py`
- `scripts/run_7table_quality.py`

### Planned-vs-runtime bridge validation

- `scripts/run_table124_quality_report.py`

### Image/path/source diagnostics

- `scripts/run_current_version_image_source_dq.py`
- `scripts/run_frontend_image_path_lineage_trace.py`
- `scripts/run_dim_picture_enum_gap_report.py`
- `scripts/run_platform_null_root_cause_probe.py`
- `scripts/run_platform_path_layer_scan.py`
- `scripts/run_sample_table01_platform_null_diagnosis.py`
- `scripts/run_pic_backup_video_content_type_probe.py`

### SQL / lineage / field-source diagnostics

- `scripts/build_sql_data_map.py`
- `scripts/run_total_hours_sql_field_probe.py`

## Bundled References

Read only the ones needed for the current question:

- `references/data-quality-report-20260408.md`
- `references/table124-quality-report-20260416.json`
- `references/current-version-image-source-dq-report-20260416.json`
- `references/four-table.pdf`
- `references/total-hours-field-mapping-report.pdf`

## Output Standard

A good result should include:

1. execution summary
2. target grain and key definition
3. structural findings
4. value-level findings
5. lineage/bridge findings
6. root-cause classification
7. representative samples
8. remediation priority
9. explicit uncertainty or counterarguments

## Self-Critique Checklist

Before finalizing, challenge your own diagnosis:

- Is the null actually invalid, or merely not applicable?
- Is the enum gap a bug, or a legitimate new business category?
- Is the issue in the source, or just in the target-field semantics?
- Is the sample biased toward recent data only?
- Does the lineage explain "where from" but not yet "why wrong"?

If those questions are unanswered, keep the diagnosis provisional.
