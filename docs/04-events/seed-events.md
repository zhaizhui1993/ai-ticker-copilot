# 04-事件库 ｜ 种子事件清单

> 模块：04 历史事件库 ｜ 成分：种子库 ｜ 对应代码：events_lib/seed_events.yaml、events_lib/loader.py ｜ 实施阶段：P2 入库 / P4 回填
> 来源：原方案 §5.3；实施期扩充批次：10 → 26 → 31 条（2024+ 纳指指数回调波段批次 +5，经挖掘器流程产出，见 [mine.md](mine.md)）；v1.3 对照批次 +12（fizzled 5 + 机制类比 5 + V 型危机对照 1 + 正向宏观 1），防"全是咬人的狗"高估冲击

**种子事件清单（43 条）。量化数据两种来源**：tag 含"公开数据待复核"= 来自公开报道的硬数字，待 `backfill_events.py`/`mine_events.py` 实测复核；tag 含"2026-09复盘实测" = 本仓实测。正向事件 9 条配平（防类比永远偏空）。**pre-state 字段（事件前状态）由 `backfill_pre_state.py` 回填，人工不填**；fizzled=true 的对照事件参与检索与聚合，浅回撤样本修正平均冲击的高估。

| event_id | 事件 | 类别 | 方向 | 备注 |
|---|---|---|---|---|
| **宏观/贸易（5）** | | | | |
| 2018-03-us-china-tariff | 中美贸易摩擦启动（301 调查→多轮关税） | macro | 负 | 多轮事件取首轮 |
| 2019-05-trade-escalation | 谈判破裂与关税升级（5 月轮） | macro | 负 | 第二轮拆条 |
| 2025-04-liberation-day-tariffs | 对等关税冲击（Liberation Day） | macro | 负 | **深冲击原型**：指数破位、VIX 60 |
| 2025-04-tariff-pause-rally | 关税暂缓史诗级反弹（SPX 单日 +9.5%） | macro | **正** | 政策反转原型 |
| 2024-11-election-risk-on | 大选后风险偏好扩张 | macro | **正** | |
| **货币政策（5）** | | | | |
| 2022-03-fed-hike-cycle | 美联储激进加息周期启动 | monetary | 负 | 体制级原型 |
| 2018-12-fed-hawkish-bottom | 12 月鹰派加息（2018 熊市底） | monetary | 负 | 熊市底原型 |
| 2019-07-fed-cut-start | 十年首次降息（预防式） | monetary | **正** | |
| 2024-09-fed-cut-start | 降息周期启动（首次 50bp） | monetary | **正** | 与加息周期配平 |
| 2023-10-rates-surge | 美债收益率飙升（10Y 破 5%） | monetary | 负 | 利率冲击原型 |
| **监管/管制（3）** | | | | |
| 2022-10-chip-export-rule | 对华先进制程芯片管制（第一轮） | regulation | 负 | |
| 2023-10-chip-export-tighten | 管制收紧（A800/H800 禁售，第二轮） | regulation | 负 | 类比验收锚点 |
| 2024-12-chip-export-final | 管制扩围（HBM 等，第三轮） | regulation | 负 | 边际冲击递减 |
| **危机/流动性（4）** | | | | |
| 2020-02-covid-shock | 新冠疫情全球冲击 | crisis | 负 | SPX -33.9%、VIX 82.7 |
| 2018-02-volmageddon | VIX 暴涨事件（Volmageddon） | crisis | 负 | 波动率产品反噬 |
| 2023-03-svb-crisis | 硅谷银行事件 | crisis | 负 | 传导有限原型 |
| 2024-08-yen-carry-unwind | 日元套息平仓闪崩 | crisis | 负 | VIX 盘中 65、数日修复 |
| **技术/AI 叙事（5）** | | | | |
| 2022-11-gpt-launch | ChatGPT 发布开启生成式 AI 时代 | tech | **正** | 叙事起点原型 |
| 2023-05-ai-rally-start | NVDA 财报引爆 AI 行情启动 | tech | **正** | 正向基准 |
| 2024-07-growth-rotation | 成长/价值大轮动回调 | tech | 负 | 轮动回调原型 |
| 2025-01-deepseek-shock | DeepSeek 冲击算力叙事 | tech | 负 | NVDA 单日 -17% |
| 2026-07-ai-valuation-pullback | AI 变现疑虑+收益率上行的半导体集中回调 | tech | 负 | **深回调买点原型**（指数未破位、VIX 20.7），八标的实测（含 IXIC -10.1%/40 交易日） |
| **指数回调波段（2024+ 挖掘批次，5）** | | | | 纳指口径 ≥5% 波段；<5% 视为噪声不收录；量化待 `mine_events.py` 实测复核 |
| 2024-04-inflation-scare-pullback | 通胀反复引发的科技股回调 | macro | 负 | IXIC -7.5%/NVDA -20.4% |
| 2024-12-hawkish-fed-dip | 12 月鹰派点阵图年末回调 | monetary | 负 | NDX -5.2%，浅回调 |
| 2025-02-tariff-growth-scare | 关税与增长担忧第一轮冲击 | macro | 负 | IXIC -14% |
| 2025-10-late-october-selloff | 十月末高位回落 | tech | 负 | 归因待复核 |
| 2026-03-first-correction | 纳指 2026 年第一次回调（2 月→4 月初） | tech | 负 | 约 -10%；NVDA 实测破 MA200 12 交易日（3/20-4/7） |
| **公司事件（4）** | | | | |
| 2022-02-meta-earnings-crash | Meta 财报暴雷（单日 -26%） | tech | 负 | 业绩暴雷原型 |
| 2024-04-intc-earnings-crash | 英特尔财报暴雷与裁员 | tech | 负 | 业绩暴雷原型 |
| 2024-02-nvda-earnings-gap | 英伟达财报史诗级跳空（+24%） | tech | **正** | 财报超预期原型 |
| 2025-08-intc-stake-rally | 英特尔获财团入股大涨（+29%） | tech | **正** | 事件反转原型 |
| **fizzled 对照（v1.3，5）** | | | | 雷声大雨点小：浅回撤参与 base-rate 平均，修正冲击高估（fizzled=true） |
| 2023-10-ai-executive-order | 拜登 AI 行政令（监管冲击未兑现） | regulation | 负 | 预期落空原型 |
| 2024-04-iran-israel-strike | 伊朗本土袭以（地缘恐慌一日游） | crisis | 负 | 快速收复 |
| 2024-07-biden-withdraws | 拜登退选（政治冲击快速消化） | macro | 负 | 波动率事件而非盈利事件 |
| 2024-05-ai-bubble-debate | 高盛 AI 泡沫争论（叙事级回调） | tech | 负 | 叙事回调无盈利证据 |
| 2025-06-israel-iran-war | 以伊直接冲突（油价冲高股指收复） | crisis | 负 | 供给冲击未触科技链 |
| **正事件腿补充（v1.3，1）** | | | | |
| 2023-11-cpi-disinflation | 10 月 CPI 超预期降温（加息见顶交易） | monetary | **正** | 利率拐点原型 |
| **pre-2018 机制类比（v1.3，5）** | | | | 产业结构已变，仅机制层面可比（tags 标注"机制类比"） |
| 2000-03-dotcom-peak | 互联网泡沫见顶破裂 | crisis | 负 | 估值泡沫+盈利缺口；SOX -82% |
| 2008-09-lehman-collapse | 雷曼破产（流动性危机） | crisis | 负 | 相关性归一的历史原型 |
| 2011-08-us-downgrade | 美债降级叠加欧债危机 | macro | 负 | 波动率事件后盈利修复 |
| 2015-08-cny-devaluation | 人民币贬值引发量化平仓 | macro | 负 | 汇率冲击→被动去杠杆 |
| 2016-01-china-circuit-breaker | A 股熔断+油价崩盘 | macro | 负 | 全球增长恐慌、年内收复 |
| **V 型危机对照（v1.3，1）** | | | | 修正"恢复天数"的悲观估计 |
| 2023-03-regional-bank-crisis | 区域银行危机（SVB 破产） | crisis | 负 | 两周 -10% 后 V 型收复 |

## 入库约定

种子事件随仓库版本管理，启动时 upsert 进 MySQL events 表（`source='seed'`）；用户在 Web 端新增的事件 `source='user'`，自动沉淀的事件 `source='auto'`（见 [auto-sedimentation.md](auto-sedimentation.md)），代码升级不清掉。

## 数据纪律

1. 只收"可明确归因"的事件（单一公告日、传导机制公认），宁缺勿滥；
2. 带"公开数据待复核"tag 的量化字段，雅虎限频恢复后逐条跑 `backfill_events.py` 与实测对照，偏差大说明日期或口径有误，修正后去掉该 tag；
3. 库容增长路径：本表为种子保底，日常靠 [auto-sedimentation.md](auto-sedimentation.md) 滚雪球 + 人工增补（优先补原型缺口，不为凑数加事件）。
