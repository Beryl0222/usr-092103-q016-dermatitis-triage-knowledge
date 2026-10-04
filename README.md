# 虫媒皮炎分流知识台

市级健康热线使用的**虫媒皮炎知识管理与分流系统**。它不替代医生诊断，只根据来电中已知的
信息，给出**带不确定性与缺失问题**的分级分流建议；儿童、面部密集水疱、大面积水疱、
糜烂渗出等信号优先升级。

## 要解决的问题

旧话术把“孩子手臂一小片红斑”和“面部已有密集水疱”都归为居家观察，还保留酒精、碘伏、
挑破水疱等会造成二次刺激的做法。本系统把知识拆成可独立修订的模块并版本化，使两类场景
得到**不同且能说明理由**的处置，并能在知识被修正后：

- 让既往咨询**绑定当时的知识版本**，回放某条建议后来为何被修正；
- 撤回错误条目后，**扫描仍在使用它的网页、话术库、合作渠道**并确认下线；
- 多家医疗机构上报增多时**先各自保留来源**，由疾控确认后才发布聚集预警；
- 公众得到简明当下指引，坐席看到升级原因与依据来源。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `contracts/domain.schema.json` | 领域事件公共信封 + 按事件类型区分的载荷契约 |
| `knowledge/kb-2026-01.json` | 旧版话术稿（保留错误，供回放与撤回追溯），状态 `superseded` |
| `knowledge/kb-2026-02.json` | 现行版，状态 `active` |
| `data/cases/*.json` | 来电案例（原始描述 + 已确认/否认事实 + 绑定知识版本） |
| `data/seed-events.json` | 人工登记事件：知识发布、信号上报、聚集评审、撤回、渠道发布/下线 |
| `events/domain-events.jsonl` | 由种子事件 + 引擎评估结果重建出的完整事件账本 |
| `src/knowledge_store.py` | 知识版本包与模块装载 |
| `src/triage.py` | 数据驱动分流引擎（规则、级别、缺失问题、不确定性） |
| `src/views.py` | 公众简明视图 / 坐席升级理由视图 |
| `src/ledger.py` | 账本投影：聚集信号、撤回影响扫描、版本回放 |
| `src/cli.py` | 命令行入口 |

## 知识如何版本化

每个知识包内，下列模块**各自带 `module_version`**，可单独修订而不必整包重写：

`sources`（权威来源）、`populations`（适用人群）、`exposure_routes`（暴露方式）、
`symptom_patterns`（症状组合）、`severity_levels`（严重程度）、
`contraindications`（禁忌处理）、`home_steps`（居家步骤）、`care_rules`（就医条件/规则）、
`intake_questions`（采集问题）、`seasonal_risks`（季节风险）、`channels`（发布渠道）。

- 分流结论由 `care_rules` 数据驱动：命中多条时取**最高级别**，`priority_signal` 规则
  解释“为什么升级”。级别：`emergency_now`（立即急诊/120）、`urgent_same_day`（当日就医）、
  `reassess_24_48`（24–48 小时复诊）、`home_observe`（居家护理观察）、
  `indeterminate`（信息不足，先补问题）。
- 规则全部标注权威来源；**系统不作诊断**，每条输出都附免责声明与“还需确认”的问题。
- 关键问题没问清时不允许给出居家结论，按**就高不就低**处理。

维护流程（新增版本、撤回条目、渠道下线、聚集预警）见
[`docs/KNOWLEDGE_MAINTENANCE.md`](docs/KNOWLEDGE_MAINTENANCE.md)。

## 命令行

```bash
# 由案例重算并重建事件账本（种子事件 + 引擎评估）
python3 -m src.cli rebuild

# 单个咨询分流：公众视图（默认）/ 坐席视图；--kb 可指定其它知识版本重放
python3 -m src.cli triage case-2026-09-26-face-blisters
python3 -m src.cli triage case-2026-09-25-arm-redpatch --view agent

python3 -m src.cli assess-all   # 全部案例的级别一览
python3 -m src.cli signals      # 分来源信号 + 疾控预警状态
python3 -m src.cli impact       # 被撤内容在各渠道的影响/下线扫描
python3 -m src.cli replay case-2026-09-13-face-blisters  # 建议为何被修正
python3 -m src.cli season --month 9                       # 当月季节风险
python3 -m src.cli sources                                # 现行版权威来源
```

## 两个锚点场景（现行版 kb-2026-02）

| 场景 | 级别 | 决定规则 | 处置要点 |
| --- | --- | --- | --- |
| 孩子手臂一小片红斑、无破溃无全身症状 | `home_observe` | `r-mild-local` | 清水冲洗、冷湿敷、炉甘石（完整皮肤）等护理并观察，列明禁忌与升级条件 |
| 面部密集水疱（夜间拍虫后） | `urgent_same_day` | `r-face-dense-vesicles` | 当日皮肤科/急诊；不可挑破、不可涂酒精碘伏或强效激素 |

同一两个场景在旧版 `kb-2026-01` 下都被判为 `home_observe` 并下发酒精/碘伏/挑破水疱——
这正是要修正的错误，可通过 `replay` 回放。

## 本地检查

```bash
python3 -m unittest discover -s tests
```

> 医学口径为演示用通用健康科普框架，落地前须由疾控与皮肤科专家按最新权威来源核校；
> 文中机构、URL、单据号均为示例。
