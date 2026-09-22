# 05-评分 ｜ 产业面（industry_score.py）

> 模块：05 评分引擎 ｜ 成分：产业 scorer ｜ 权重 25% ｜ 实施阶段：P5
> 来源：原方案 §6.1③

| 子项 | 权重 | 当前实现 | 规划增强 |
|---|---|---|---|
| 产业链相对强弱 | 40% | 按 stocks.yaml 的 segment 映射篮子（gpu→NVDA/AMD、foundry→TSM、equipment→ASML/AMAT/LRCX、cloud→MSFT/GOOGL/AMZN、software→MSFT/CRM、power→CEG/VST、etf→SMH/SOXX），近 21/63 日涨幅 vs SPY 超额收益 | SMH/SPY 比值 vs MA20（未实现） |
| 龙头财报动量 | 30% | 篮子公司营收 YoY 中位数（`financials` 参数；**pipeline 当前未喂数，恒计 50 中性并标注降级**） | 季度缓存 + pipeline 接线 |
| AI 景气度代理 | 30% | `ai_word_delta` 参数（**pipeline 当前未喂数，恒计 50 中性并标注降级**） | 新闻词频环比接入 |

- 篮子外的 `segment: other` 股票：相对强弱子项计中性并标注"无篮子映射"（降级协议）。
- 板块级风险仪表（费半 ATR / 板块宽度）不进本维分数，作为体制层参考（见 [layered-technicals.md](layered-technicals.md)）。
