# 05-评分 ｜ 公司面（company_score.py）

> 模块：05 评分引擎 ｜ 成分：公司 scorer ｜ 权重 25%（逐 ticker） ｜ 实施阶段：P5
> 来源：原方案 §6.1④

| 子项 | 权重 | 计算方式 |
|---|---|---|
| 成长 | 35% | 营收/净利 YoY（quarterly_financials），>30% 满分档 |
| 估值 | 30% | PE(TTM) 相对自身 5 年分位（用 history 自算分位，不用 .info 的 forwardPE），分位 <30% 高分；PEG 辅助 |
| 质量 | 20% | 毛利率、FCF 正负、ROE |
| 技术面 | 15% | 分层指标体系（见 [layered-technicals.md](layered-technicals.md)）：伤害度量=距52周高点回撤+乖离率；趋势=MA50 斜率；择时=MA20 回踩/RSI14/量比/事件日反应 |

- 数据来源：`get_daily_bars` / `get_financials`（[03-collectors/market.md](../03-collectors/market.md)）；指标由本模块自算（采集层不预置指标）。
- 估值分位注意：5 年历史 EPS 序列 yfinance 拿不全，实施时若无法自算则降级为"当前 PE vs 行业/自身价格分位"近似并标注。
