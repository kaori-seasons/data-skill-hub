#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for _key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_key, None)

import requests

_orig_request = requests.Session.request


def _no_proxy(self, method, url, **kwargs):
    kwargs["proxies"] = {"http": "", "https": ""}
    return _orig_request(self, method, url, **kwargs)


requests.Session.request = _no_proxy

try:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.dlc.v20210125 import dlc_client, models
except ImportError as exc:
    raise SystemExit(
        "缺少 tencentcloud-sdk-python，请先安装：python -m pip install tencentcloud-sdk-python"
    ) from exc


REGION = "ap-shanghai"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "total-hours-field-probe-result.json"
CANDIDATE_DBS = [
    "data_db",
    "data_ods",
    "data_dwd",
    "data_dws",
    "data_dim",
    "data_dm",
    "data_ads",
    "tmp",
    "default",
]

SQL_FINAL_OUTPUT_GRAIN = (
    "cate.款号 + cate.上市季 + cate.性别 + cate.品牌分类 + cate.吊牌价 + cate.货源规整 + cate.新旧品 + "
    "cate.大类规整 + cate.中类规整 + cate.小类规整 + cate.款名规整 + cate.篮跑矩阵 + cate.赛道一级 + "
    "cate.赛道二级 + product_id + year + is_exclusive_price + is_official_flash_sale + is_category_coupon + gender"
)


@dataclass
class TableRef:
    logical_name: str
    table_name: str
    source_type: str
    fixed_db: str | None = None
    date_expr: str | None = None
    shop_filter: str | None = None


TABLES = [
    TableRef("fact_live_product", "dm_tmall_liveroom_category_di_2", "fact", None, "data_date", None),
    TableRef("cate_dim", "tmp_tm_bi_resource_conso_dc", "dim", None, None, None),
    TableRef(
        "tmall_live_good_detail",
        "rpa_tmall_live_good_detail",
        "detail",
        "data_db",
        "date(runtime)",
        "shop = '李宁官方旗舰店'",
    ),
]


FIELD_SPECS: list[dict[str, Any]] = [
    {"name": "商品曝光次数", "table": "fact_live_product", "exact": ["impression_count"]},
    {"name": "商品曝光人数", "table": "fact_live_product", "exact": ["impression_users"]},
    {"name": "商品点击次数", "table": "fact_live_product", "exact": ["click_count"]},
    {"name": "商品点击人数", "table": "fact_live_product", "exact": ["click_users"]},
    {"name": "加购人数", "table": "fact_live_product", "exact": ["add_to_cart_users"]},
    {"name": "加购商品件数", "table": "fact_live_product", "exact": ["add_to_cart_items"]},
    {"name": "成交人数", "table": "fact_live_product", "exact": ["transaction_users"]},
    {"name": "成交件数", "table": "fact_live_product", "exact": ["transaction_items"]},
    {"name": "店铺成交件数", "table": "fact_live_product", "exact": ["store_transaction_items"]},
    {"name": "店铺成交金额", "table": "fact_live_product", "exact": ["store_transaction_amount"]},
    {
        "name": "直播引导退款金额",
        "table": "fact_live_product",
        "exact": ["live_guided_refund_amount", "直播引导退款金额"],
        "approx": ["live_order_refund_amount"],
    },
    {"name": "店铺退款金额", "table": "fact_live_product", "exact": ["store_refund_amount"]},
    {
        "name": "渗透率",
        "table": "fact_live_product",
        "derived": "sum(transaction_amount) / sum(store_transaction_amount)",
        "components": ["transaction_amount", "store_transaction_amount"],
    },
    {
        "name": "退款率",
        "table": "fact_live_product",
        "derived": "sum(live_order_refund_amount) / sum(transaction_amount)",
        "components": ["live_order_refund_amount", "transaction_amount"],
    },
    {"name": "商品id", "table": "fact_live_product", "exact": ["product_id"]},
    {"name": "商品名称", "table": "fact_live_product", "exact": ["product_name"]},
    {"name": "spu", "table": "fact_live_product", "exact": ["spu", "spu_id"], "approx": ["款号"]},
    {"name": "上市季", "table": "cate_dim", "exact": ["上市季"]},
    {"name": "专享价", "table": "fact_live_product", "exact": ["exclusive_price", "专享价"], "approx": ["is_exclusive_price"]},
    {"name": "官方闪降", "table": "fact_live_product", "exact": ["official_flash_sale", "官方闪降"], "approx": ["is_official_flash_sale"]},
    {"name": "是否品类券", "table": "fact_live_product", "exact": ["is_category_coupon", "category_coupon", "是否品类券"]},
    {"name": "性别", "table": "fact_live_product", "exact": ["gender"], "approx": ["性别"]},
    {"name": "品牌分类", "table": "cate_dim", "exact": ["品牌分类"]},
    {"name": "品牌价", "table": "cate_dim", "exact": ["品牌价"], "approx": ["吊牌价"]},
    {"name": "货源规整", "table": "cate_dim", "exact": ["货源规整"]},
    {"name": "新旧品", "table": "cate_dim", "exact": ["新旧品"]},
    {"name": "大类规整", "table": "cate_dim", "exact": ["大类规整"]},
    {"name": "中类规整", "table": "cate_dim", "exact": ["中类规整"]},
    {"name": "小类规整", "table": "cate_dim", "exact": ["小类规整"]},
    {"name": "款名规整", "table": "cate_dim", "exact": ["款名规整"]},
    {"name": "篮跑矩阵", "table": "cate_dim", "exact": ["篮跑矩阵"]},
    {"name": "赛道一级", "table": "cate_dim", "exact": ["赛道一级"]},
    {"name": "赛道二级", "table": "cate_dim", "exact": ["赛道二级"]},
]


class DlcRunner:
    def __init__(self, secret_id: str | None, secret_key: str | None, max_wait: int = 300):
        if not secret_id or not secret_key:
            raise SystemExit("缺少 DLC_USER / DLC_PASSWORD 环境变量。")
        cred = credential.Credential(secret_id, secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = "dlc.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        self.client = dlc_client.DlcClient(cred, REGION, client_profile)
        self.max_wait = max_wait

    def exec_sql(self, sql: str, db: str) -> list[list[Any]]:
        preview = " ".join(sql.strip().split())[:180]
        print(f"[SQL] {db}: {preview}...", flush=True)
        task = models.Task()
        task.SparkSQLTask = {"SQL": base64.b64encode(sql.encode("utf-8")).decode("utf-8")}
        req = models.CreateTaskRequest()
        req.DatabaseName = db
        req.DataEngineName = "SparkSQL"
        req.Task = task
        resp = self.client.CreateTask(req)
        task_id = json.loads(resp.to_json_string()).get("TaskId")
        if not task_id:
            raise RuntimeError("CreateTask 未返回 TaskId")

        elapsed = 0
        while elapsed < self.max_wait:
            time.sleep(3)
            elapsed += 3
            req2 = models.DescribeTaskResultRequest()
            req2.TaskId = str(task_id)
            result = json.loads(self.client.DescribeTaskResult(req2).to_json_string())
            task_info = result.get("TaskInfo", result)
            state = task_info.get("State", "")
            if state == 2:
                result_set = task_info.get("ResultSet", "[]")
                if isinstance(result_set, str):
                    try:
                        return json.loads(base64.b64decode(result_set).decode("utf-8"))
                    except Exception:
                        return json.loads(result_set)
                return result_set or []
            if state == 3:
                raise RuntimeError(task_info.get("OutputMessage", "SQL failed"))
        raise TimeoutError(f"SQL 执行超时，等待了 {self.max_wait}s")

    def describe_table(self, db: str, table: str) -> list[str]:
        req = models.DescribeTableRequest()
        req.DatabaseName = db
        req.TableName = table
        resp = self.client.DescribeTable(req)
        data = json.loads(resp.to_json_string())
        table_info = data.get("Table", data)
        columns = table_info.get("Columns") or []
        names: list[str] = []
        for item in columns:
            if isinstance(item, dict) and item.get("Name"):
                names.append(item["Name"])
        return names

    def list_databases(self) -> list[str]:
        names: list[str] = []
        offset = 0
        limit = 100
        while True:
            req = models.DescribeDatabasesRequest()
            req.Limit = limit
            req.Offset = offset
            req.DatasourceConnectionName = "DataLakeCatalog"
            resp = self.client.DescribeDatabases(req)
            data = json.loads(resp.to_json_string())
            rows = data.get("DatabaseList") or []
            total_count = int(data.get("TotalCount") or 0)
            for item in rows:
                if isinstance(item, dict) and item.get("DatabaseName"):
                    names.append(item["DatabaseName"])
            offset += limit
            if offset >= total_count or not rows:
                break
        return names


def normalize_expr(column_name: str) -> str:
    raw = f"TRIM(CAST(`{column_name}` AS STRING))"
    return f"CASE WHEN `{column_name}` IS NULL OR {raw} = '' THEN NULL ELSE {raw} END"


def field_expr(column_name: str) -> str:
    raw = f"TRIM(CAST(`{column_name}` AS STRING))"
    return f"COALESCE({raw}, 'NULL_VALUE')"


def build_database_candidates(runner: DlcRunner) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for name in CANDIDATE_DBS:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    try:
        for name in runner.list_databases():
            if name not in seen:
                ordered.append(name)
                seen.add(name)
    except Exception:
        pass
    return ordered


def find_table_db(runner: DlcRunner, ref: TableRef, db_candidates: list[str]) -> tuple[str | None, list[str], str | None]:
    if ref.fixed_db:
        try:
            cols = runner.describe_table(ref.fixed_db, ref.table_name)
            return ref.fixed_db, cols, None
        except Exception as exc:
            last_error = str(exc)
        search_dbs = [db for db in db_candidates if db != ref.fixed_db]
    else:
        last_error = None
        search_dbs = db_candidates

    for db in search_dbs:
        try:
            cols = runner.describe_table(db, ref.table_name)
            return db, cols, None
        except Exception as exc:
            last_error = str(exc)
    return None, [], last_error


def build_where_clause(ref: TableRef, date_value: str | None) -> str:
    parts = ["1 = 1"]
    if ref.shop_filter:
        parts.append(ref.shop_filter)
    if date_value and ref.date_expr:
        parts.append(f"{ref.date_expr} = '{date_value}'")
    return " AND ".join(parts)


def fetch_latest_date(runner: DlcRunner, db: str, ref: TableRef) -> str | None:
    if not ref.date_expr:
        return None
    sql = f"SELECT MAX({ref.date_expr}) FROM {db}.{ref.table_name}"
    rows = runner.exec_sql(sql, db)
    if not rows or not rows[0] or rows[0][0] in (None, ""):
        return None
    return str(rows[0][0])


def candidate_grains(ref: TableRef, columns: set[str]) -> list[tuple[str, list[str]]]:
    items: list[tuple[str, list[str]]] = []
    if ref.logical_name == "fact_live_product":
        if "product_id" in columns:
            items.append(("product_id", ["product_id"]))
        if {"product_id", "year"}.issubset(columns):
            items.append(("product_id+year", ["product_id", "year"]))
        if {"product_id", "data_date"}.issubset(columns):
            items.append(("product_id+data_date", ["product_id", "data_date"]))
        if {"product_id", "year", "data_date"}.issubset(columns):
            items.append(("product_id+year+data_date", ["product_id", "year", "data_date"]))
        extra = [c for c in ["is_exclusive_price", "is_official_flash_sale", "is_category_coupon", "gender"] if c in columns]
        if "product_id" in columns and extra:
            items.append(("product_id+flags", ["product_id", *extra]))
        if {"product_id", "data_date"}.issubset(columns) and extra:
            items.append(("product_id+data_date+flags", ["product_id", "data_date", *extra]))
    elif ref.logical_name == "cate_dim":
        if "商品ID" in columns:
            items.append(("商品ID", ["商品ID"]))
        if "商品id" in columns:
            items.append(("商品id", ["商品id"]))
        if "款号" in columns:
            items.append(("款号", ["款号"]))
        if {"商品ID", "款号"}.issubset(columns):
            items.append(("商品ID+款号", ["商品ID", "款号"]))
        if {"商品id", "款号"}.issubset(columns):
            items.append(("商品id+款号", ["商品id", "款号"]))
    elif ref.logical_name == "tmall_live_good_detail":
        if "item_id" in columns:
            items.append(("item_id", ["item_id"]))
        if {"item_id", "runtime"}.issubset(columns):
            items.append(("item_id+runtime", ["item_id", "runtime"]))
    return items


def build_uniqueness_sql(table_fqn: str, where_clause: str, field_col: str, grain_cols: list[str]) -> str:
    grain_expr = ", ".join([normalize_expr(col) + f" AS `{col}`" for col in grain_cols])
    grain_group = ", ".join([f"`{col}`" for col in grain_cols])
    return f"""
    WITH base AS (
        SELECT
            {grain_expr},
            {field_expr(field_col)} AS field_value
        FROM {table_fqn}
        WHERE {where_clause}
          AND `{field_col}` IS NOT NULL
    ),
    agg AS (
        SELECT
            {grain_group},
            COUNT(DISTINCT field_value) AS field_distinct_cnt
        FROM base
        GROUP BY {grain_group}
    )
    SELECT
        COUNT(*) AS key_count,
        MAX(field_distinct_cnt) AS max_distinct_per_key,
        percentile_approx(field_distinct_cnt, 0.5) AS p50_distinct_per_key,
        percentile_approx(field_distinct_cnt, 0.9) AS p90_distinct_per_key
    FROM agg
    """


def infer_min_grain(
    runner: DlcRunner,
    db: str,
    ref: TableRef,
    columns: list[str],
    field_col: str,
    latest_date: str | None,
) -> dict[str, Any]:
    where_clause = build_where_clause(ref, latest_date if ref.source_type in {"fact", "detail"} else None)
    table_fqn = f"{db}.{ref.table_name}"
    for grain_name, grain_cols in candidate_grains(ref, set(columns)):
        rows = runner.exec_sql(build_uniqueness_sql(table_fqn, where_clause, field_col, grain_cols), db)
        row = rows[0] if rows else [None, None, None, None]
        max_distinct = int(str(row[1])) if row[1] not in (None, "") else None
        result = {
            "grain": grain_name,
            "grain_cols": grain_cols,
            "key_count": row[0],
            "max_distinct_per_key": row[1],
            "p50_distinct_per_key": row[2],
            "p90_distinct_per_key": row[3],
        }
        if max_distinct == 1:
            return {"resolved": True, **result}
    return {"resolved": False, "grain": None, "grain_cols": [], "key_count": None, "max_distinct_per_key": None}


def find_first_hit(columns: list[str], candidates: list[str]) -> str | None:
    column_set = set(columns)
    for name in candidates:
        if name in column_set:
            return name
    return None


def resolve_field(
    spec: dict[str, Any],
    table_meta: dict[str, dict[str, Any]],
    runner: DlcRunner,
) -> dict[str, Any]:
    primary = table_meta[spec["table"]]
    primary_cols = primary.get("columns", [])
    exact_hit = find_first_hit(primary_cols, spec.get("exact", []))
    approx_hit = find_first_hit(primary_cols, spec.get("approx", []))

    if not exact_hit and spec.get("fallback"):
        for item in spec["fallback"]:
            meta = table_meta[item["table"]]
            hit = find_first_hit(meta.get("columns", []), item.get("columns", []))
            if hit:
                grain = infer_min_grain(runner, meta["db"], meta["ref"], meta["columns"], hit, meta.get("latest_date"))
                return {
                    "field_name": spec["name"],
                    "status": "fallback",
                    "source_table": f"{meta['db']}.{meta['ref'].table_name}",
                    "source_column": hit,
                    "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
                    "source_min_grain": grain,
                    "reason": f"主表未命中，回退到 {meta['db']}.{meta['ref'].table_name}.{hit}",
                }

    if exact_hit:
        grain = infer_min_grain(runner, primary["db"], primary["ref"], primary_cols, exact_hit, primary.get("latest_date"))
        return {
            "field_name": spec["name"],
            "status": "exact",
            "source_table": f"{primary['db']}.{primary['ref'].table_name}",
            "source_column": exact_hit,
            "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
            "source_min_grain": grain,
            "reason": "字段在源表中直接存在，可按 SQL 当前逻辑取数。",
        }

    if spec.get("derived"):
        missing_components = [c for c in spec.get("components", []) if c not in set(primary_cols)]
        if missing_components:
            return {
                "field_name": spec["name"],
                "status": "missing",
                "source_table": f"{primary['db']}.{primary['ref'].table_name}",
                "source_column": None,
                "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
                "source_min_grain": None,
                "reason": f"派生公式依赖字段缺失: {', '.join(missing_components)}",
            }
        grain_parts = []
        for component in spec["components"]:
            grain_parts.append(
                {
                    "component": component,
                    "grain": infer_min_grain(runner, primary["db"], primary["ref"], primary_cols, component, primary.get("latest_date")),
                }
            )
        return {
            "field_name": spec["name"],
            "status": "derived",
            "source_table": f"{primary['db']}.{primary['ref'].table_name}",
            "source_column": spec["derived"],
            "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
            "source_min_grain": grain_parts,
            "reason": "字段为聚合派生指标，可在 SQL 中直接计算。",
        }

    if approx_hit:
        grain = infer_min_grain(runner, primary["db"], primary["ref"], primary_cols, approx_hit, primary.get("latest_date"))
        return {
            "field_name": spec["name"],
            "status": "approx_only",
            "source_table": f"{primary['db']}.{primary['ref'].table_name}",
            "source_column": approx_hit,
            "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
            "source_min_grain": grain,
            "reason": f"源表没有精确同名字段，只命中近似字段 `{approx_hit}`。",
        }

    return {
        "field_name": spec["name"],
        "status": "missing",
        "source_table": f"{primary['db']}.{primary['ref'].table_name}" if primary.get("db") else primary["ref"].table_name,
        "source_column": None,
        "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
        "source_min_grain": None,
        "reason": f"在候选字段 {spec.get('exact', []) + spec.get('approx', [])} 中均未命中，当前 SQL 不能直接取到。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="探测 total-hours-stats.sql 的字段可得性与最小归因粒度。")
    parser.add_argument("--max-wait", type=int, default=300)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), args.max_wait)
    database_candidates = build_database_candidates(runner)
    table_meta: dict[str, dict[str, Any]] = {}
    discovery_errors: list[dict[str, Any]] = []

    for ref in TABLES:
        db, columns, error = find_table_db(runner, ref, database_candidates)
        if not db:
            discovery_errors.append({"table_name": ref.table_name, "error": error})
            table_meta[ref.logical_name] = {"ref": ref, "db": None, "columns": [], "latest_date": None}
            continue
        latest_date = fetch_latest_date(runner, db, ref)
        table_meta[ref.logical_name] = {
            "ref": ref,
            "db": db,
            "columns": columns,
            "latest_date": latest_date,
        }

    results = []
    for spec in FIELD_SPECS:
        meta = table_meta.get(spec["table"])
        if not meta or not meta.get("db"):
            results.append(
                {
                    "field_name": spec["name"],
                    "status": "table_not_found",
                    "source_table": spec["table"],
                    "source_column": None,
                    "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
                    "source_min_grain": None,
                    "reason": "源表未定位到具体数据库，无法进一步探测。",
                }
            )
            continue
        results.append(resolve_field(spec, table_meta, runner))

    payload = {
        "sql_file": str(SCRIPT_DIR / "total-hours-stats.sql"),
        "sql_final_output_grain": SQL_FINAL_OUTPUT_GRAIN,
        "database_candidates": database_candidates,
        "table_meta": {
            key: {
                "db": value.get("db"),
                "table_name": value["ref"].table_name,
                "columns": value.get("columns", []),
                "latest_date": value.get("latest_date"),
            }
            for key, value in table_meta.items()
        },
        "discovery_errors": discovery_errors,
        "field_results": results,
    }

    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n结果已写入: {output_path}")


if __name__ == "__main__":
    main()
