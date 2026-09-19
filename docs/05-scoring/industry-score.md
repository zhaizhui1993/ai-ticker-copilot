# 05-评分 ｜ 产业面（industry_score.py）

> 模块：05 评分引擎 ｜ 成分：产业 scorer ｜ 权重 25% ｜ 实施阶段：P5
> 来源：原方案 §6.1③

| 子项 | 权重 | 计算方式 |
|---|---|---|
| 产业链相对强弱 | 40% | 按 stocks.yaml 的 segment 映射篮子（gpu→NVDA/AMD、foundry→TSM、equipment→ASML/AMAT/LRCX、cloud→MSFT/GOOGL/AMZN、etf→SMH/SOXX），近 1M/3M 涨幅 vs SPY 超额收益；SMH/SPY 比值 vs MA20 |
| 龙头财报动量 | 30% | 篮子中已发财报公司的营收 YoY 中位数（季度缓存） |
| AI 景气度代理 | 30% | 近期新闻标题中 AI/capex/datacenter 等词命中率环比变化 |

- 篮子外的 `segment: other` 股票：相对强弱子项计中性并标注"无篮子映射"（降级协议）。
- 板块级风险仪表（费半 ATR / 板块宽度）不进本维分数，作为体制层参考（见 [layered-technicals.md](layered-technicals.md)）。
