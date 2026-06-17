#!/usr/bin/env python3
"""Comprehensive quality checks for 7 tables: missing rates, dirty values, outliers."""
import os, json, time, base64
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'
for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','ALL_PROXY','all_proxy']:
    os.environ.pop(k, None)
import requests
_orig = requests.Session.request
def _patch(self, method, url, **kw):
    kw['proxies'] = {'http':'','https':''}
    return _orig(self, method, url, **kw)
requests.Session.request = _patch

from datetime import datetime
from tencentcloud.common import credential
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.dlc.v20210125 import dlc_client, models

cred = credential.Credential(os.environ.get('DLC_USER'), os.environ.get('DLC_PASSWORD'))
hp = HttpProfile()
hp.endpoint = 'dlc.tencentcloudapi.com'
cp = ClientProfile()
cp.httpProfile = hp
client = dlc_client.DlcClient(cred, 'ap-shanghai', cp)
output_dir = '/Users/windwheel/.copaw/workspaces/data-warehouse/data-quality-report'

def exec_sql(sql, db='data_ods', max_wait=120):
    sql_b64 = base64.b64encode(sql.encode('utf-8')).decode('utf-8')
    task = models.Task()
    task.SparkSQLTask = {'SQL': sql_b64}
    req = models.CreateTaskRequest()
    req.DatabaseName = db
    req.DataEngineName = 'SparkSQL'
    req.Task = task
    try:
        resp = client.CreateTask(req)
        data = json.loads(resp.to_json_string())
        tid = data.get('TaskId')
        if not tid: return None
    except Exception as e:
        print(f'    CreateTask err: {e}')
        return None
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(3)
        elapsed += 3
        try:
            req2 = models.DescribeTaskResultRequest()
            req2.TaskId = str(tid)
            resp2 = client.DescribeTaskResult(req2)
            result = json.loads(resp2.to_json_string())
            ti = result.get('TaskInfo', result)
            state = ti.get('State', '')
            if state == 2:
                rs = ti.get('ResultSet', '[]')
                if isinstance(rs, str):
                    try: return json.loads(base64.b64decode(rs).decode('utf-8'))
                    except Exception:
                        try: return json.loads(rs)
                        except Exception: return []
                return rs
            elif state == 3:
                print(f'    SQL failed: {ti.get("OutputMessage","")}')
                return None
        except Exception:
            pass
    print(f'    Timeout after {max_wait}s')
    return None

def safe_val(res, row=0, col=0):
    """Extract a value from DLC result safely."""
    try:
        if res and isinstance(res, list) and len(res) > row:
            r = res[row]
            if isinstance(r, list) and len(r) > col:
                return r[col]
            return r
    except: pass
    return '?'

# Load schemas
with open(os.path.join(output_dir, 'new-table-schemas-20260408.json')) as f:
    schemas = json.load(f)
with open(os.path.join(output_dir, 'all-profiles-20260408.json')) as f:
    profiles = json.load(f)

all_cols = {}
for tbl, info in profiles.items():
    db = info.get('database', 'data_ods')
    all_cols[tbl] = {'db': db, 'cols': [{'name':c['name'],'type':c['type']} for c in info.get('columns',[])]}
for tbl, info in schemas.items():
    if tbl not in all_cols:
        all_cols[tbl] = {'db': info['db'], 'cols': info['columns']}

tables = [
    ('ods_t_file_information', 'data_ods', 'file_id'),
    ('ods_pic_for_up_new_backup', 'data_ods', 'id'),
    ('ods_t_image_file_information', 'data_ods', 'file_id'),
    ('ods_rpa_douyin_compass_video', 'data_ods', 'id'),
    ('tb16_dim_product_sale_dimension', 'data_dim', None),
    ('ods_dy_product_top_crowd_ays', 'data_ods', 'id'),
    ('ods_rpa_material_data', 'data_ods', None),
]

results = {}

for tbl, db, pk in tables:
    full = f'{db}.{tbl}'
    print(f"\n{'='*60}")
    print(f'  {full}')
    print(f"{'='*60}")

    ci = all_cols.get(tbl, {}).get('cols', [])
    if not ci:
        print('  NO SCHEMA'); continue

    r = {'table': tbl, 'db': db, 'num_cols': len(ci)}

    # 1. Row count
    res = exec_sql(f'SELECT COUNT(*) FROM {full}', db)
    total = safe_val(res)
    r['total_rows'] = str(total)
    print(f'  Rows: {total}')

    # 2. Null rates (all cols, chunk 8)
    null_rates = {}
    for i in range(0, len(ci), 8):
        chunk = ci[i:i+8]
        parts = []
        for c in chunk:
            ct = c['type'].lower()
            if 'string' in ct:
                parts.append(f"ROUND(SUM(CASE WHEN `{c['name']}` IS NULL OR TRIM(`{c['name']}`)='' THEN 1 ELSE 0 END)*100.0/COUNT(*),2) AS `{c['name']}`")
            else:
                parts.append(f"ROUND(SUM(CASE WHEN `{c['name']}` IS NULL THEN 1 ELSE 0 END)*100.0/COUNT(*),2) AS `{c['name']}`")
        res = exec_sql(f"SELECT {', '.join(parts)} FROM {full}", db)
        if res and isinstance(res, list) and len(res) > 0 and isinstance(res[0], list):
            for j, c in enumerate(chunk):
                null_rates[c['name']] = res[0][j] if j < len(res[0]) else '?'

    r['null_rates'] = {k: str(v) for k, v in null_rates.items()}
    high = [(k,v) for k,v in null_rates.items() if str(v) not in ('?','0','0.0','0.00') and float(str(v)) > 30]
    high.sort(key=lambda x: -float(str(x[1])))
    if high:
        print(f'  High null (>30%): {len(high)} cols')
        for k,v in high[:8]: print(f'    {k}: {v}%')
        if len(high)>8: print(f'    ... +{len(high)-8} more')
    else:
        print(f'  High null (>30%): none')

    # 3. Dirty values (string cols, first 8)
    scols = [c['name'] for c in ci if 'string' in c['type'].lower()]
    dirty = {}
    for sc in scols[:8]:
        res = exec_sql(
            f"SELECT "
            f"SUM(CASE WHEN `{sc}` RLIKE '[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F]' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN `{sc}` != TRIM(`{sc}`) THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN LENGTH(`{sc}`) > 500 THEN 1 ELSE 0 END) "
            f"FROM {full} WHERE `{sc}` IS NOT NULL AND TRIM(`{sc}`)!=''", db)
        if res and isinstance(res, list) and len(res)>0 and isinstance(res[0], list):
            ctrl, tri, ol = str(res[0][0]), str(res[0][1]), str(res[0][2])
            if ctrl!='0' or tri!='0' or ol!='0':
                dirty[sc] = {'ctrl':ctrl,'trim':tri,'overlong':ol}
                print(f'  Dirty {sc}: ctrl={ctrl} trim={tri} overlong={ol}')
    if not dirty: print(f'  Dirty values: none (first 8 str cols)')
    r['dirty_values'] = dirty

    # 4. Numeric stats
    ncols = [c['name'] for c in ci if any(t in c['type'].lower() for t in ['int','bigint','decimal','double','float'])]
    nstats = {}
    for nc in ncols[:5]:
        res = exec_sql(f"SELECT MIN(`{nc}`),MAX(`{nc}`),ROUND(AVG(CAST(`{nc}` AS DOUBLE)),2),ROUND(STDDEV(CAST(`{nc}` AS DOUBLE)),2) FROM {full} WHERE `{nc}` IS NOT NULL", db)
        if res and isinstance(res,list) and len(res)>0 and isinstance(res[0],list):
            nstats[nc] = {'min':str(res[0][0]),'max':str(res[0][1]),'avg':str(res[0][2]),'stddev':str(res[0][3])}
            print(f'  Numeric {nc}: min={res[0][0]} max={res[0][1]} avg={res[0][2]} stddev={res[0][3]}')
    r['numeric_stats'] = nstats

    # 5. Time ranges
    tcols = [c['name'] for c in ci if any(t in c['type'].lower() for t in ['timestamp','date'])]
    tlike = [c['name'] for c in ci if 'string' in c['type'].lower() and any(k in c['name'].lower() for k in ['time','date','dt'])]
    tranges = {}
    for tc in list(set(tcols+tlike))[:5]:
        res = exec_sql(f"SELECT MIN(`{tc}`),MAX(`{tc}`) FROM {full} WHERE `{tc}` IS NOT NULL AND TRIM(CAST(`{tc}` AS STRING))!=''", db)
        if res and isinstance(res,list) and len(res)>0 and isinstance(res[0],list):
            tranges[tc] = {'earliest':str(res[0][0]),'latest':str(res[0][1])}
            print(f'  Time {tc}: {res[0][0]} -> {res[0][1]}')
    r['time_ranges'] = tranges

    # 6. PK dup rate
    if pk:
        res = exec_sql(f"SELECT COUNT(DISTINCT `{pk}`),COUNT(*) FROM {full} WHERE `{pk}` IS NOT NULL", db)
        if res and isinstance(res,list) and len(res)>0 and isinstance(res[0],list):
            d,t = int(str(res[0][0])),int(str(res[0][1]))
            dup = round((t-d)*100.0/t,2) if t>0 else 0
            r['pk'] = {'distinct':d,'total':t,'dup_rate':dup}
            print(f'  PK({pk}): {d}/{t} = {dup}% dup')

    # 7. Enum distribution for key dims
    ecols = [c['name'] for c in ci if 'string' in c['type'].lower() and any(k in c['name'].lower() for k in ['type','status','platform','brand','delete','gender','category'])]
    enums = {}
    for ec in ecols[:3]:
        res = exec_sql(f"SELECT `{ec}`,COUNT(*) FROM {full} WHERE `{ec}` IS NOT NULL AND TRIM(`{ec}`)!='' GROUP BY `{ec}` ORDER BY 2 DESC LIMIT 10", db)
        if res and isinstance(res,list) and len(res)>0:
            enums[ec] = res
            top3 = json.dumps(res[:3], ensure_ascii=False)[:120]
            print(f'  Enum {ec}: {top3}')
    r['enums'] = enums

    results[tbl] = r

out = os.path.join(output_dir, f'quality-check-7tables-{datetime.now().strftime("%Y%m%d-%H%M")}.json')
with open(out,'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f'\nSaved: {out}')
