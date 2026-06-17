# sample-002 性别字段异常检测报告

- 生成时间：2026-04-21 16:27:46
- SQL 文件：`/Users/windwheel/.copaw/workspaces/sample-002.sql`
- 目标表：`data_dwd.dwd_file_label_id_spu`

## 一、关键结论

- 目标表 data_dwd.dwd_file_label_id_spu 中 gender='无' 共 889755 行，占目标表 13.8575% 。
- tb16 按 SPU 看，`性别` 空值 SPU 数为 2316，`性别_李宁bi` 空值 SPU 数为 82532。如果后者显著更高，说明 sample-002 当前取错了性别来源字段。
- `gender='无'` 的主因是 TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY，涉及 623264 行、17133 个 SPU。
- 存在大量样本在 tb16.性别 有值，但 tb16.性别_李宁bi 为空，说明当前 SQL 取 `性别_李宁bi` 会把本可映射的 SPU 误写成 `无`。
- 存在一批 `dwd_file_label_id_spu` 的 SPU 在 tb16 完全对不上，这部分即使改映射规则也仍会落成 `无`，需要补查上游 SPU 对齐。

## 二、目标表 gender 分布

| gender | row_cnt | spu_cnt |
| --- | ---: | ---: |
| 男性 | 2485358 | 14659 |
| 女性 | 1216911 | 7564 |
| 中性 | 1075888 | 5984 |
| 无 | 889755 | 23590 |
| 童 | 752840 | 3581 |

## 三、tb16 原始字段分布

### 3.1 `性别`

| gender_tb16 | row_cnt | spu_cnt |
| --- | ---: | ---: |
| 男 | 348823 | 47361 |
| 女 | 205153 | 38604 |
| 中性 | 173899 | 19143 |
| 童 | 49238 | 2028 |
| 其它 | 7244 | 4205 |
| <<EMPTY>> | 3854 | 2316 |

### 3.2 `性别_李宁bi`

| gender_lining_bi | row_cnt | spu_cnt |
| --- | ---: | ---: |
| 男 | 274308 | 16224 |
| <<EMPTY>> | 242292 | 82532 |
| 女 | 124230 | 9528 |
| 中 | 106567 | 6660 |
| 男童 | 27830 | 2467 |
| 童 | 9195 | 548 |
| 女童 | 2324 | 592 |
| 婴幼儿 | 820 | 62 |
| 中性 | 617 | 118 |
| 无 | 28 | 8 |

## 四、`gender=无` 根因拆解

| root_cause | row_cnt | spu_cnt |
| --- | ---: | ---: |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 623264 | 17133 |
| NO_TB16_MATCH | 265008 | 6444 |
| LINING_BI_IS_WU | 1326 | 8 |
| TB16_BOTH_EMPTY | 157 | 5 |

## 五、抽样

| root_cause | file_id | spu | final_gender | gender_tb16 | gender_lining_bi |
| --- | --- | --- | --- | --- | --- |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 8dbe335dc1ee8b84802949852fe0bec3 | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 855507e4c36c4b726f77e4dce9ec9c4b | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 39444d16a8bbdf1ab084326f5d1d7bb7 | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 5331db9da3da66c0f351100d90aa385f | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | eaa911bdfaf1002b4baec301e27080c5 | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | b827c25bdf0b6ddfef8a476b93a1a155 | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 5acc410911a848551fa213c7b475f3e9 | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 20415199b66fb90cd68cad268850785a | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 8165127b59585a58197a8b35b062aeaa | 100349 | 无 | 女 | <<EMPTY>> |
| TB16_GENDER_PRESENT_BUT_LINING_BI_EMPTY | 9a3e4c2b590c1aa30d9e7f637d82a425 | 100349 | 无 | 女 | <<EMPTY>> |
| NO_TB16_MATCH | c26578d3f37d0521215ad31a88375a7f | 319005 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | 1da4db3303c6a5c5406ee47becbdd3b5 | 319005 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | 96e97ac7c31fc90bdeeb15ca94d02090 | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | a6785923aa2d2c9fa982ffb6774d3bc2 | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | ec4e72b78a298fbcb56b2581a002ba23 | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | 4235318d75db7cc9b4f1bd279382db0b | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | b9df5f95f1119ebb0e6c7615a4379e7d | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | 600e99ba2ba0afef04e16a2c488f1346 | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | e5bdf95bdafd5da48150c509e1cebe56 | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| NO_TB16_MATCH | ce1ab601aa5d38141d0850b676a4822b | 664094 | 无 | <<EMPTY>> | <<EMPTY>> |
| LINING_BI_IS_WU | c10ee3ad6309f14206eef21a6d7ee7b8 | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | 2ae69b6ea140b6cd8ae615f2ef699bf2 | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | 013eff6decaa4fbdcb7ae8d53003fa0b | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | a51a8fc6778d530677b8b0a423cd633d | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | f061836246f9ededf90018b48a7f3b44 | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | 564ee49ce61ba325a87d1e3bf4e8a44d | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | ad3f79977a158937ccd8281727998c21 | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | 751ff80ae538e70c4ed78e8bf83e3835 | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | 314173e44661e3132bb3b5cbf9a97108 | AYTS016 | 无 | 中性 | 无 |
| LINING_BI_IS_WU | af51dde505a7e1907f5f877801e1ef47 | AYTS016 | 无 | 中性 | 无 |
| TB16_BOTH_EMPTY | dbf15eed8c0286f91d920d67b48beab5 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | 032bef297ec71f04550e67df4f7b96e5 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | 6ec274419cca5779def7a2de37998543 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | f52c278a9fc4225603271b60399e7276 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | acb52b0d754e36d67a1fe237092ae262 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | 26ea7ba14fcccc688f1e05988d7035f3 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | 175ccd12cdbfadd7d412b0fbf8bafbb6 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | c238fc3f646733968f2bbdc4ca157c64 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | c5e4e406cb287a9654340970c884f52d | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |
| TB16_BOTH_EMPTY | eb7ed4e2a2a539b375602f400c47c871 | AMBW102 | 无 | <<EMPTY>> | <<EMPTY>> |