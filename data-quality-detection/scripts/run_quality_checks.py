#!/usr/bin/env python3
"""
对五张表执行行级数据质量检查：空值率、重复主键、枚举值分布、数值统计、异常值检测。
通过 DLC SDK 的 CreateTask + DescribeTaskResult 接口执行 SparkSQL。
"""
import os
import json
import time
from datetime import datetime
from tencentcloud.common import credential
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.dlc.v20210125 import dlc_client, models

secret_id = os.environ.get('DLC_USER')
secret_key = os.environ.get('DLC_PASSWORD')
region = 'ap-shanghai'

output_dir = '/Users/windwheel/.copaw/workspaces/12345/data-quality-report'
os.makedirs(output_dir, exist_ok=True)

def get_client():
    cred = credential.Credential(secret_id, secret_key)
    http_profile = HttpProfile()
    http_profile.endpoint = "dlc.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    return dlc_client.DlcClient(cred, region, client_profile)

def execute_sql(client, sql, database="data_ods", data_engine="spark", max_wait=120):
    """Execute SQL via DLC CreateTask and wait for result."""
    print(f"  [SQL] {sql[:120]}...")

    # Create task
    req = models.CreateTaskRequest()
    req.DatabaseName = database
    req.DataEngineName = data_engine
    task = models.SQLTask()
    task.SQL = sql
    req.Task = task

    try:
        resp = client.CreateTask(req)
        data = json.loads(resp.to_json_string())
        task_id = data.get('TaskResponse', {}).get('TaskId')
        if not task_id:
            # Try alternate paths
            task_id = data.get('TaskId')
        if not task_id:
            print(f"    Error: No TaskId returned. Response: {json.dumps(data, ensure_ascii=False)[:300]}")
            return None
        print(f"    TaskId: {task_id}")
    except Exception as e:
        print(f"    CreateTask error: {e}")
        return None

    # Poll for result
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(3)
        elapsed += 3

        try:
            req2 = models.DescribeTaskResultRequest()
            req2.TaskId = str(task_id)
            resp2 = client.DescribeTaskResult(req2)
            result = json.loads(resp2.to_json_string())

            # Check status
            task_info = result.get('TaskResult', result)
            state = task_info.get('State', '')

            if state in ('success', '0'):
                # Try to get data
                data_arr = task_info.get('Data', task_info.get('ResultSet', []))
                if data_arr:
                    return data_arr
                # Some results come in a different structure
                return task_info
            elif state in ('failed', 'error', '-1'):
                error_msg = task_info.get('Error', task_info.get('Message', 'Unknown error'))
                print(f"    Task failed: {error_msg}")
                return None
            else:
                if elapsed % 15 == 0:
                    print(f"    Waiting... state={state}, elapsed={elapsed}s")
        except Exception as e:
            if elapsed % 15 == 0:
                print(f"    Poll error: {e}")

    print(f"    Timeout after {max_wait}s")
    return None


def execute_sql_simple(client, sql, database="data_ods"):
    """Simplified: just print the SQL for manual execution, and attempt SDK execution."""
    return execute_sql(client, sql, database)


def run_table_checks(client, table_name, database, columns_info):
    """Run all quality checks for a single table."""
    full_name = f"{database}.{table_name}"
    results = {"table": table_name, "database": database, "checks": {}}

    print(f"\n{'='*70}")
    print(f"检查表: {full_name}")
    print(f"{'='*70}")

    # 1. 总行数
    sql = f"SELECT COUNT(*) AS total_rows FROM {full_name}"
    r = execute_sql(client, sql, database)
    results["checks"]["total_rows"] = {"sql": sql, "result": r}
    print(f"    结果: {r}")

    # 2. 空值率检查 — 对所有字段
    null_cases = []
    for col in columns_info:
        col_name = col["name"]
        col_type = col["type"].lower()
        if col_type == "boolean":
            null_cases.append(
                f"ROUND(SUM(CASE WHEN `{col_name}` IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS `{col_name}_null_pct`"
            )
        elif col_type in ("int", "bigint", "decimal", "double", "float"):
            null_cases.append(
                f"ROUND(SUM(CASE WHEN `{col_name}` IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS `{col_name}_null_pct`"
            )
        else:  # string
            null_cases.append(
                f"ROUND(SUM(CASE WHEN `{col_name}` IS NULL OR TRIM(`{col_name}`) = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS `{col_name}_null_pct`"
            )

    # Split into chunks of 10 columns to avoid overly long SQL
    chunk_size = 10
    null_results = {}
    for i in range(0, len(null_cases), chunk_size):
        chunk = null_cases[i:i+chunk_size]
        sql = f"SELECT {', '.join(chunk)} FROM {full_name}"
        r = execute_sql(client, sql, database)
        if r:
            null_results.update(r[0] if isinstance(r, list) and len(r) > 0 else r)

    results["checks"]["null_rates"] = null_results
    print(f"    空值率结果: {json.dumps(null_results, ensure_ascii=False)[:300]}")

    # 3. 主键重复检查 (基于 columns_info 中 category=identifier 的字段)
    id_cols = [c["name"] for c in columns_info if c.get("category") == "identifier" and c["name"] in ("id", "task_id", "erp_shop_id", "file_id")]
    for pk in id_cols:
        sql = f"SELECT `{pk}`, COUNT(*) AS dup_cnt FROM {full_name} WHERE `{pk}` IS NOT NULL GROUP BY `{pk}` HAVING COUNT(*) > 1 ORDER BY dup_cnt DESC LIMIT 20"
        r = execute_sql(client, sql, database)
        results["checks"][f"duplicate_{pk}"] = {"sql": sql, "result": r}
        print(f"    重复主键 {pk}: {r}")

    # 4. 数值字段统计画像 (MIN, MAX, AVG, STDDEV)
    numeric_cols = [c["name"] for c in columns_info if any(t in c["type"].lower() for t in ["int", "bigint", "decimal", "double", "float"])]
    if numeric_cols:
        stat_cases = []
        for col in numeric_cols:
            stat_cases.extend([
                f"MIN(`{col}`) AS `{col}_min`",
                f"MAX(`{col}`) AS `{col}_max`",
                f"ROUND(AVG(CAST(`{col}` AS DOUBLE)), 2) AS `{col}_avg`",
                f"ROUND(STDDEV(CAST(`{col}` AS DOUBLE)), 2) AS `{col}_stddev`",
            ])
        chunk_size = 12
        stat_results = {}
        for i in range(0, len(stat_cases), chunk_size):
            chunk = stat_cases[i:i+chunk_size]
            sql = f"SELECT {', '.join(chunk)} FROM {full_name}"
            r = execute_sql(client, sql, database)
            if r:
                stat_results.update(r[0] if isinstance(r, list) and len(r) > 0 else r)
        results["checks"]["numeric_stats"] = stat_results
        print(f"    数值统计: {json.dumps(stat_results, ensure_ascii=False)[:400]}")

    # 5. IQR 异常值检测 — 对数值字段
    for col in numeric_cols:
        sql = f"""
        WITH stats AS (
          SELECT
            PERCENTILE(CAST(`{col}` AS DOUBLE), 0.25) AS q1,
            PERCENTILE(CAST(`{col}` AS DOUBLE), 0.75) AS q3
          FROM {full_name}
          WHERE `{col}` IS NOT NULL
        ),
        fences AS (
          SELECT q1 - 1.5 * (q3 - q1) AS lower_fence, q3 + 1.5 * (q3 - q1) AS upper_fence FROM stats
        )
        SELECT
          (SELECT q1 FROM stats) AS q1,
          (SELECT q3 FROM stats) AS q3,
          (SELECT lower_fence FROM fences) AS lower_fence,
          (SELECT upper_fence FROM fences) AS upper_fence,
          SUM(CASE WHEN CAST(`{col}` AS DOUBLE) < (SELECT lower_fence FROM fences)
                    OR CAST(`{col}` AS DOUBLE) > (SELECT upper_fence FROM fences) THEN 1 ELSE 0 END) AS outlier_count,
          ROUND(SUM(CASE WHEN CAST(`{col}` AS DOUBLE) < (SELECT lower_fence FROM fences)
                    OR CAST(`{col}` AS DOUBLE) > (SELECT upper_fence FROM fences) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 4) AS outlier_pct
        FROM {full_name}
        WHERE `{col}` IS NOT NULL
        """
        r = execute_sql(client, sql, database)
        results["checks"][f"outlier_{col}"] = {"sql": sql, "result": r}
        print(f"    异常值 {col}: {r}")

    # 6. 字符串字段脏值检测 — 控制字符、过长值
    string_cols = [c["name"] for c in columns_info if "string" in c["type"].lower()]
    for col in string_cols[:8]:  # 限制检查前8个字符串字段
        sql = f"""
        SELECT
          SUM(CASE WHEN `{col}` RLIKE '[\\\\x00-\\\\x08\\\\x0B\\\\x0C\\\\x0E-\\\\x1F]' THEN 1 ELSE 0 END) AS control_chars,
          SUM(CASE WHEN `{col}` RLIKE '\\\\s{{3,}}' THEN 1 ELSE 0 END) AS excess_whitespace,
          SUM(CASE WHEN LENGTH(`{col}`) > 1000 THEN 1 ELSE 0 END) AS overlong_values,
          SUM(CASE WHEN `{col}` != TRIM(`{col}`) THEN 1 ELSE 0 END) AS trim_issues
        FROM {full_name}
        WHERE `{col}` IS NOT NULL AND TRIM(`{col}`) != ''
        """
        r = execute_sql(client, sql, database)
        results["checks"][f"dirty_{col}"] = {"sql": sql, "result": r}
        print(f"    脏值 {col}: {r}")

    # 7. 时间字段异常检测
    time_cols = [c["name"] for c in columns_info if "timestamp" in c["type"].lower()]
    # Also check string columns that look like dates
    time_like_cols = [c["name"] for c in columns_info if "string" in c["type"].lower()
                      and any(k in c["name"].lower() for k in ["time", "date", "dt"])]
    all_time_cols = time_cols + time_like_cols

    for col in all_time_cols:
        # Check for future dates (if timestamp)
        if "timestamp" in [c["type"].lower() for c in columns_info if c["name"] == col][0]:
            sql = f"""
            SELECT
              SUM(CASE WHEN `{col}` > CURRENT_TIMESTAMP() THEN 1 ELSE 0 END) AS future_dates,
              SUM(CASE WHEN `{col}` < '2020-01-01' THEN 1 ELSE 0 END) AS ancient_dates,
              MIN(`{col}`) AS earliest,
              MAX(`{col}`) AS latest
            FROM {full_name}
            WHERE `{col}` IS NOT NULL
            """
        else:
            # String date — just check distribution
            sql = f"""
            SELECT
              MIN(`{col}`) AS earliest,
              MAX(`{col}`) AS latest,
              COUNT(DISTINCT `{col}`) AS distinct_values
            FROM {full_name}
            WHERE `{col}` IS NOT NULL AND TRIM(`{col}`) != ''
            """
        r = execute_sql(client, sql, database)
        results["checks"][f"time_check_{col}"] = {"sql": sql, "result": r}
        print(f"    时间检查 {col}: {r}")

    # 8. 枚举值分布 — 检查 flag 和 dimension 字段
    enum_cols = [c["name"] for c in columns_info if c.get("category") in ("flag", "dimension") and "string" in c["type"].lower()]
    for col in enum_cols[:5]:  # 限制5个
        sql = f"SELECT `{col}`, COUNT(*) AS cnt FROM {full_name} WHERE `{col}` IS NOT NULL GROUP BY `{col}` ORDER BY cnt DESC LIMIT 20"
        r = execute_sql(client, sql, database)
        results["checks"][f"enum_{col}"] = {"sql": sql, "result": r}
        print(f"    枚举分布 {col}: {r}")

    return results


def main():
    print("=" * 70)
    print("数据质量行级检查 — 五张表全面分析")
    print(f"执行时间: {datetime.now().isoformat()}")
    print("=" * 70)

    client = get_client()

    # 加载表结构画像
    with open(os.path.join(output_dir, 'all-profiles-20260408.json'), 'r') as f:
        profiles = json.load(f)

    all_results = {}

    # 表定义
    tables = [
        ("ods_rpa_douyin_compass_video", "data_ods"),
        ("ods_rpa_efficient_and_high_salary_douyin_video_df", "data_ods"),
        ("ads_dewu_gravity_task_df", "data_ads"),
        ("dim_shop_normalized_info", "data_dim"),
        ("ods_t_image_file_information", "data_ods"),
    ]

    for table_name, database in tables:
        profile = profiles.get(table_name, {})
        columns = profile.get("columns", [])

        if not columns:
            print(f"\nSkipping {table_name} — no column info found")
            continue

        try:
            result = run_table_checks(client, table_name, database, columns)
            all_results[table_name] = result
        except Exception as e:
            print(f"\nError checking {table_name}: {e}")
            import traceback
            traceback.print_exc()
            all_results[table_name] = {"error": str(e)}

    # 保存结果
    output_file = os.path.join(output_dir, f'quality-check-results-{datetime.now().strftime("%Y%m%d-%H%M")}.json')
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n结果已保存: {output_file}")

    # 打印汇总
    print("\n" + "=" * 70)
    print("检查完成汇总")
    print("=" * 70)
    for table, data in all_results.items():
        if "error" in data:
            print(f"  {table}: 错误 — {data['error']}")
        else:
            checks = data.get("checks", {})
            print(f"  {table}: {len(checks)} 项检查完成")


if __name__ == '__main__':
    main()
