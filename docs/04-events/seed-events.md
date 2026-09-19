# 04-事件库 ｜ 种子事件清单

> 模块：04 历史事件库 ｜ 成分：种子库 ｜ 对应代码：events_lib/seed_events.yaml、events_lib/loader.py ｜ 实施阶段：P2 入库 / P4 回填
> 来源：原方案 §5.3（种子清单部分）

**种子事件清单（10 条，量化数据实施时用 yfinance 按日期实测回填）**：

| event_id | 事件 | 类别 | 方向 | 需回填的量化字段 |
|---|---|---|---|---|
| 2018-03-us-china-tariff | 中美贸易摩擦启动（301 调查→多轮关税） | macro | 负 | 各轮对 SMH/NVDA 回撤与恢复 |
| 2020-02-covid-shock | 新冠疫情全球冲击 | crisis | 负 | SPX/IXIC 1w/1m、VIX 峰值 |
| 2022-03-fed-hike-cycle | 美联储激进加息周期启动 | monetary | 负 | 利率变动 bps、成长股回撤 |
| 2022-10-chip-export-rule | 对华先进制程芯片出口管制（10 月 7 日规则） | regulation | 负 | 半导体板块回撤/恢复 |
| 2023-03-svb-crisis | 硅谷银行事件 | crisis | 负 | 区域银行→科技股传导 |
| 2023-05-ai-rally-start | NVDA 财报引爆 AI 行情启动 | tech | **正** | NVDA 与板块涨幅（正向基准，防止类比永远偏空） |
| 2023-10-chip-export-tighten | 对华芯片管制收紧（A800/H800 禁售） | regulation | 负 | NVDA 回撤与恢复 |
| 2024-12-chip-export-final | 管制进一步扩围（HBM 等） | regulation | 负 | 板块反应 |
| 2025-01-deepseek-shock | DeepSeek V3/R1 发布冲击算力叙事 | tech | 负 | NVDA 单日 -17%、达底/恢复天数 |
| 2026-07-ai-valuation-pullback | AI 变现疑虑+美债收益率上行引发半导体集中回调（无离散政策冲击） | tech | 负 | ^SOX -28.6%、BE -52.7%/COHR -47.8%/MRVL -47.4%；7/29 集体见底后 V 型反转；指数全程未破 MA200、VIX 峰值仅 20.7 |

## 入库约定

种子事件随仓库版本管理，启动时 upsert 进 MySQL events 表（`source='seed'`）；用户在 Web 端新增的事件 `source='user'`，自动沉淀的事件 `source='auto'`（见 [auto-sedimentation.md](auto-sedimentation.md)），代码升级不清掉。
