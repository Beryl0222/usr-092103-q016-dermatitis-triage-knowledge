# 知识维护手册

本手册说明如何修订分流知识、发布预警、撤回错误内容并追溯影响。所有变更都以
**领域事件**表达（见 `contracts/domain.schema.json`），只追加、不改写历史。

## 1. 修订一个模块（最小变更）

模块各自带 `module_version`（如 `home-v2` → `home-v3`）。只改了居家步骤，就只提升
`home_steps.module_version`，其它模块保持不变。

1. 复制现行包为 `knowledge/kb-YYYY-NN.json`，更新：
   - `kb_version`、`status:"active"`、`effective_from`、`supersedes`、`change_summary`；
   - 仅提升被改模块的 `module_version`，在相关条目 `id` 上保留可追溯性。
2. 把旧包 `status` 改为 `superseded`、填 `superseded_by`。
3. 在 `data/seed-events.json` 追加一条 `KNOWLEDGE_PUBLISHED` 事件，
   `payload.module_versions` 列出各模块版本，便于回放时定位“当时用的是哪一版模块”。
4. `python3 -m src.cli rebuild && python3 -m unittest discover -s tests`。

> 条目 `id` 一经发布不得复用或改义；要改含义就新增 `id` 并撤回旧 `id`。

## 2. 新增/调整一条分流规则

规则在 `care_rules.items` 中，字段：

- `when`：`{"all": [...]} ` / `{"any": [...]}`，元素为案例事实（fact）名；
- `level`：命中后对应的严重程度；
- `priority_signal`：是否为“优先升级信号”，用于向坐席解释升级；
- `rationale` / `action` / `advised_within`：为什么、怎么做、多久内；
- `home_step_ids`：该级别允许的居家/就诊前步骤；
- `contraindication_ids`：该情形必须避免的做法；
- `source_ids`：权威来源（`sources` 模块）。

引擎对命中规则取**最高级别**；因此兜底轻症规则 `r-mild-local` 放在最后、级别最低。
新增红旗信号时务必给 `level` 与 `source_ids`，不要在引擎代码里写医学结论。

采集问题 `intake_questions` 通过 `establishes` 声明它能确认哪些事实；引擎据此判断
“这个问题问过没有”。新增事实后，要确保有问题能 `establishes` 它，否则该缺口无法被
自动追问。高风险事实见 `src/triage.py` 的 `HIGH_RISK_FACTS`。

## 3. 聚集信号与预警（多机构上报）

- 每家医疗机构的上报记一条 `RISK_SIGNAL_REPORTED`，`payload` 保留本院的
  `reported_by_facility`、`reporter`、`case_count`、`raw_note`、`source_doc_ref`，
  状态 `pending_review`。**不合并、不改写各来源原始数据。**
- 疾控复核前，`signals` 投影的 `public_alert` 为 `null`，对外不发布预警。
- 疾控确认后追加 `CLUSTER_REVIEWED`，`decision:"confirm_alert"`，在 `signal_ids` 中点名
  并入哪些来源，填 `reviewed_by` 与 `rationale`；此后才可经渠道发布预警内容。
- 不成立则 `decision:"no_alert"`；证据不足 `need_more_info`，信号继续内部留存。

## 4. 撤回错误内容

- 追加 `CONTENT_WITHDRAWN`，逐项列出 `item_id`、`origin_kb`、`reason`、`superseded_by`。
- 运行 `python3 -m src.cli impact` 扫描所有仍 `content_refs` 引用该条目的渠道发布
  （网页 `web` / 话术库 `script_library` / 合作渠道 `partner`）：
  - 无对应 `CHANNEL_TAKEDOWN_CONFIRMED` 的标记为 `STILL_LIVE`，即未闭环违规点；
  - 下线确认后追加 `CHANNEL_TAKEDOWN_CONFIRMED`（含 `confirmed_by`、替换版本、备注），
    再次扫描应全部为“已下线”。
- 撤回**不会删除历史咨询**。既往咨询仍绑定旧版本，可用 `replay` 看到当时的建议与撤回理由。

## 5. 版本回放（主管部门/质检）

```bash
python3 -m src.cli replay <case_id>
```

输出该咨询：当时绑定版本与级别 → 用现行版重放的级别 → 当时给出、后来被撤回的具体条目
及其原因与替代项。咨询案例文件中同时保存 `facts` 与 `negated_facts`（坐席问过且被否认
的信号），使重放结论可复现。

## 6. 发布渠道

`channels` 模块登记渠道台账；每次实际发布记 `CHANNEL_PUBLISHED`（含 `content_refs` 与
`locator`），下线记 `CHANNEL_TAKEDOWN_CONFIRMED`。公众门户给“简明当下指引”，话术库给
“分流卡片”，合作渠道仅可转发经疾控确认的预警与现行版内容。

## 7. 发布前检查清单

- [ ] 新/改条目均有权威 `source_ids`，且经疾控或皮肤科专家核校；
- [ ] 涉及儿童、面部、密集/大面积水疱、糜烂渗出、全身过敏的规则级别不降低；
- [ ] 居家步骤不含酒精、碘伏、挑破水疱、热水烫洗等二次刺激做法；
- [ ] `rebuild` 后全部事件通过 `validate_event_full`，测试全绿；
- [ ] 被替换的旧条目已发 `CONTENT_WITHDRAWN`，`impact` 无 `STILL_LIVE`；
- [ ] 聚集类对外内容仅在 `confirm_alert` 之后发布。
