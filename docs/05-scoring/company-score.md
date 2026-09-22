# 05-评分 ｜ 公司面（company_score.py）

> 模块：05 评分引擎 ｜ 成分：公司 scorer ｜ 权重 25%（逐 ticker） ｜ 实施阶段：P5
> 来源：原方案 §6.1④

| 子项 | 权重 | 当前实现 | 规划增强 |
|---|---|---|---|
| 成长 | 35% | 营收 YoY 分桶（`get_financials.revenue_yoy`；净利 YoY 字段预留恒 None） | 净利 YoY 并入 |
| 估值 | 30% | **绝对 PE(TTM) 分桶降级版**：<20 高分、20~35 中性偏正、35~60 偏负、>60/负值低分（5 年分位与 PEG 因历史 EPS 拿不全暂未实现） | PE 5 年分位 + PEG |
| 质量 | 20% | 毛利率 + ROE 分桶（FCF 正负字段预留恒 None） | FCF 并入 |
| 技术面 | 15% | 伤害=距 52 周高点回撤；趋势=MA50 斜率；择时=RSI14 区间打分（内部子权重：伤害 25%/趋势 40%/择时 35%） | 乖离率、MA20 回踩、量比、事件日反应（见 [layered-technicals.md](layered-technicals.md)） |

- 数据来源：`get_daily_bars` / `get_financials`（[03-collectors/market.md](../03-collectors/market.md)）；技术指标由 domain/technicals.py 纯函数计算（采集层不预置指标）；`get_financials` 失败时基本面子项整体计中性。
- 估值为简化口径时在 rationale 中标注，LLM 研判可见"估值分位为近似"。
