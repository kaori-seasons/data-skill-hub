# 图片中类-赛道缺口检测报告

生成时间：2026-04-20 16:00:40

## 一、链路溯源

- `source_mid_track_read`: 第 127 行，`dws.mid_cate,`
- `source_track_read`: 第 129 行，`dws.sub_track,`
- `dim_mid_write`: 第 298 行，`mid_cate,`
- `dim_track_write`: 第 300 行，`sub_track AS track_first_li_ning_bi,`
- `dim_reference_mid`: 第 328 行，`mid_cate AS reference_mid_cate,`
- `dim_reference_track`: 第 329 行，`sub_track AS reference_track,`

结论：`current-table-01.sql` 从 `data_dws.dws_platform_file_resource_label_id` 读取 `mid_cate` 与 `sub_track`，直接写入 `dim_picture_material_data_enriched.mid_cate` 与 `track_first_li_ning_bi/reference_track`。来源层缺失不会在当前链路内被补齐。

## 二、SPU 缺口概览

| metric | value |
|---|---:|
| video_spu_total | 2139 |
| video_spu_with_mid | 2116 |
| video_spu_with_track | 2139 |
| video_spu_hit_image_source | 2116 |
| video_spu_hit_dim | 2116 |
| missing_mid_in_source_spu | 1 |
| missing_track_in_source_spu | 23 |
| missing_mid_in_dim_spu | 1 |
| missing_track_in_dim_spu | 23 |
| any_gap_in_source_spu | 1 |
| any_gap_in_dim_spu | 1 |

## 三、缺失的中类 / 赛道取值

### missing_mid_values

| value | missing_in_source | missing_in_dim |
|---|---:|---:|

### missing_track_values

| value | missing_in_source | missing_in_dim |
|---|---:|---:|

## 四、视频侧存在但图片链路缺失的中类-赛道组合

| mid_cate | track | video_rows | video_spu_count | missing_in_source | missing_in_dim |
|---|---|---:|---:|---:|---:|

## 五、SPU 缺口样本

| spu | video_mid_cate | video_track | source_mid_cate | source_track | dim_mid_cate | dim_track | missing_mid_in_source | missing_track_in_source | missing_mid_in_dim | missing_track_in_dim |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ABAV073 | 其他鞋类 | 其他 |  |  |  |  | 1 | 1 | 1 | 1 |
| ABAV097 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| ABPV041 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| AFCW368 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| AFDV427 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| AGCV067 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| APRV003 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| APRV017 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| AVMV415 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| AWDV367 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| VKBS046 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| YKBC032 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| YKbv032 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| YWBU089 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| YYMY091 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| YYMY097 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| agcu275 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| caeb246 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| edaf308 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| ltra108 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| port171 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| xiao120 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |
| ykbv105 |  | 其他 |  |  |  |  | 0 | 1 | 0 | 1 |