# 订单表直播间/SPU映射分布探查报告

生成时间：2026-04-22 10:18:40

## 一、探查范围

- 表：`data_dwd.dwd_platform_order_detail_di`
- 过滤条件：`pay_time >= '2026-04-01'`
- 原始字段数：74

## 二、字段命中情况

- `shop_id` -> `erp_shop_id`
- `shop_name` -> `shop_nick`
- `product_id` -> `product_id`
- `spu` -> `spu`
- `sku_id` -> `sku_id`
- `child_order_id` -> `child_order_no`
- `live_room_id` -> `room_id`
- `pay_time` -> `pay_time`

## 三、概览

- 总行数：3236567
- 唯一店铺ID数：59
- 唯一 product_id 数：56366
- 唯一 SPU 数：8270
- 唯一 SKU 数：15831
- 唯一子订单数：3236567
- 唯一直播间数：1740
- 支付时间范围：`2026-04-01 00:00:00` ~ `2026-04-22 09:34:02`

## 四、字段分布

| logical_field | physical_column | total_rows | null_rows | null_ratio | distinct_values |
|---|---|---:|---:|---:|---:|

## 五、关键发现

- `live_room_id -> pay_date` 存在多值映射，约 43.74% 的直播间跨多个支付日，说明直播间ID不能直接等价于单一场次。
- `product_id -> spu` 存在多值映射，约 1.99% 的 product_id 对应多个 SPU，需求里必须明确以哪个字段作为商品主键。
- `spu -> sku_id` 明显是一对多，约 51.37% 的 SPU 对应多个 SKU，SPU维度汇总时不能直接按订单行数代替场次数。
- `spu -> live_room_id` 存在多值映射，约 35.00% 的 SPU 出现在多个直播间，SPU维度场次建议统计 distinct 场次键，而不是直接 count(order rows)。

## 六、核心映射关系

### shop_id_to_shop_name

- 映射：`shop_id -> shop_name`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：1.0000
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：0.00%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### product_id_to_spu

- 映射：`product_id -> spu`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：1.0342
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：1.99%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### spu_to_sku_id

- 映射：`spu -> sku_id`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：1.9143
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：51.37%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### child_order_id_to_spu

- 映射：`child_order_id -> spu`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：1.0000
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：0.00%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### child_order_id_to_live_room_id

- 映射：`child_order_id -> live_room_id`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：1.0000
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：0.00%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### live_room_id_to_pay_date

- 映射：`live_room_id -> pay_date`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：2.1080
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：43.74%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### live_room_id_to_spu

- 映射：`live_room_id -> spu`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：11.8695
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：68.51%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

### spu_to_live_room_id

- 映射：`spu -> live_room_id`
- 参与映射的 source key 数：0
- 覆盖订单行数：0
- 平均每个 source 对应 target 数：5.9743
- p50 / p90 / max：0 / 0 / 0
- 多值映射 source 占比：35.00%

| target_bucket | source_key_count | source_key_ratio |
|---|---:|---:|

## 七、直播间维度预览

说明：这里按 `live_room_id + pay_date` 展示预览，用于判断直播间ID是否足以代表单场。

| live_room_id | pay_date | row_count | child_order_count | spu_count | product_id_count | sku_id_count | shop_id_count |
|---|---|---:|---:|---:|---:|---:|---:|
| 7625771643868138240 | 2026-04-07 | 22319 | 22319 | 1 | 1 | 5 | 1 |
| 7630227912981023503 | 2026-04-19 | 13513 | 13513 | 5 | 4 | 19 | 1 |
| 7630974906922044175 | 2026-04-21 | 12457 | 12457 | 4 | 3 | 14 | 1 |
| 0 | 2026-04-19 | 10808 | 10808 | 952 | 1400 | 1655 | 17 |
| 7630596110662355727 | 2026-04-20 | 10788 | 10788 | 9 | 7 | 34 | 1 |
| 7626146473561869091 | 2026-04-08 | 10130 | 10130 | 7 | 5 | 25 | 1 |
| 0 | 2026-04-18 | 9563 | 9563 | 949 | 1433 | 1651 | 19 |
| 0 | 2026-04-15 | 9452 | 9452 | 909 | 1356 | 1586 | 18 |
| 0 | 2026-04-14 | 9275 | 9275 | 913 | 1381 | 1607 | 18 |
| 0 | 2026-04-12 | 9187 | 9187 | 968 | 1438 | 1657 | 19 |
| 0 | 2026-04-13 | 8064 | 8064 | 876 | 1304 | 1547 | 17 |
| 0 | 2026-04-01 | 7968 | 7968 | 824 | 1181 | 1441 | 18 |
| 0 | 2026-04-11 | 7841 | 7841 | 901 | 1309 | 1558 | 18 |
| 0 | 2026-04-16 | 7791 | 7791 | 784 | 1177 | 1385 | 18 |
| 0 | 2026-04-02 | 7587 | 7587 | 749 | 1077 | 1344 | 17 |
| 0 | 2026-04-17 | 7446 | 7446 | 816 | 1187 | 1403 | 18 |
| 0 | 2026-04-05 | 7301 | 7301 | 784 | 1121 | 1349 | 19 |
| 0 | 2026-04-21 | 7274 | 7274 | 782 | 1117 | 1338 | 18 |
| 7629668201072249636 | 2026-04-18 | 7253 | 7253 | 28 | 28 | 108 | 1 |
| 0 | 2026-04-07 | 7119 | 7119 | 771 | 1107 | 1372 | 18 |

## 八、SPU维度预览

| spu | row_count | child_order_count | sku_id_count | product_id_count | live_room_count | pay_date_count | shop_id_count |
|---|---:|---:|---:|---:|---:|---:|---:|
| AHSV369 | 52792 | 52792 | 6 | 68 | 39 | 22 | 11 |
| ATSV509 | 51390 | 51390 | 9 | 85 | 136 | 22 | 12 |
| AHSWC47 | 47220 | 47220 | 2 | 32 | 49 | 22 | 9 |
| ARPW015 | 42741 | 42741 | 6 | 99 | 125 | 22 | 9 |
| ATSW351 | 41524 | 41524 | 6 | 71 | 211 | 22 | 13 |
| ATSV594 | 33345 | 33345 | 5 | 52 | 82 | 22 | 12 |
| AYKV483 | 28591 | 28591 | 2 | 38 | 105 | 22 | 12 |
| ARSW035 | 27105 | 27105 | 8 | 92 | 128 | 22 | 13 |
| ARPW019 | 26810 | 26810 | 4 | 81 | 88 | 22 | 10 |
| ARSV023 | 24755 | 24755 | 5 | 93 | 86 | 22 | 11 |
| AKLV727 | 22739 | 22739 | 2 | 35 | 50 | 22 | 9 |
| ARPW001 | 22042 | 22042 | 17 | 155 | 111 | 22 | 9 |
| ARPW018 | 21956 | 21956 | 3 | 57 | 93 | 22 | 10 |
| AKSV525 | 21935 | 21935 | 5 | 55 | 41 | 22 | 10 |
| YTSW123 | 19280 | 19280 | 6 | 63 | 54 | 22 | 8 |
| AHSW395 | 18727 | 18727 | 5 | 53 | 96 | 22 | 12 |
| YKFR024 | 17979 | 17979 | 13 | 86 | 80 | 22 | 9 |
| ARST019 | 16725 | 16725 | 3 | 47 | 0 | 22 | 6 |
| ARSV024 | 16412 | 16412 | 4 | 61 | 64 | 22 | 11 |
| YHSW151 | 16190 | 16190 | 4 | 47 | 75 | 22 | 7 |

## 九、需求梳理建议

- 若 `live_room_id -> pay_date` 或更细时间粒度存在明显多值映射，应优先补“场次维表”或定义 `直播间 + 时间窗` 为场次键。
- 若 `product_id -> spu` 不是稳定 1:1，直播间维度和 SPU 维度的统计口径必须分别定义，不能互相替代。
- 若 `child_order_id -> live_room_id` 不是稳定 1:1，需要先确认订单明细是否存在重复归因或回流补数。
- 若 `spu -> live_room_id` 明显一对多，SPU维度的“场次数”应统计 distinct 场次键，而不是 count(distinct child_order_id)。