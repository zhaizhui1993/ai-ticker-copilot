# 05-评分 ｜ 公司面（company_score.py）

> 模块：05 评分引擎 ｜ 成分：公司 scorer ｜ 权重 25%（逐 ticker） ｜ 实施阶段：P5
> 来源：原方案 §6.1④ + v1.2 估值口径修复（P0-1/P1-4）

| 子项 | 权重 | 当前实现 | 规划增强 |
|---|---|---|---|
| 成长 | 40% | 营收 YoY 分桶（`get_financials.revenue_yoy`；净利 YoY 字段预留恒 None） | 净利 YoY 并入 |
| 估值 | 15% | **类 PEG 口径（v1.2）**：正增长时按 PE/营收 YoY 分桶（<1.5 高分 / <2.5 / <3.5 / ≥3.5 低分）；周期段（equipment/foundry）低 PE 封顶 55（盈利峰值特征）；无正增长支撑时绝对 PE 仅作参考且 ≤55；PE 缺失/亏损 → 估值腿剔除（权重重归一化） | PE 5 年分位 + PEG（净利口径） |
| 质量 | 30% | 毛利率 + ROE 分桶（FCF 正负字段预留恒 None） | FCF 并入 |
| 技术面 | 15% | 伤害=距 52 周高点回撤；趋势=MA50 斜率；择时=RSI14 区间打分（内部子权重：伤害 25%/趋势 40%/择时 35%） | 乖离率、MA20 回踩、量比、事件日反应（见 [layered-technicals.md](layered-technicals.md)） |

- v1.2 变更（P0-1）：估值权重 30%→15%（让渡给质量），**不再用绝对 PE 直接驱动总分**——半导体设备/代工等深周期股低 PE 常伴盈利峰值（2018 年中 AMAT 个位数 PE 即周期顶），绝对 PE 分桶在该股票池近似反向指标。
- v1.2 变更（P1-4）：任何子腿数据缺失（营收/PE/基本面/K 线）→ 剔除该腿并对剩余腿权重显式重归一化（rationale 标注比例），不再塞中性 50。
- 数据来源：`get_daily_bars` / `get_financials`（[03-collectors/market.md](../03-collectors/market.md)）；技术指标由 domain/technicals.py 纯函数计算（采集层不预置指标）；`segment` 由 pipeline 传入（周期封顶判定用）。
- 估值恒为简化口径，rationale 标注具体口径（类 PEG / 绝对参考 / 剔除），LLM 研判可见。
