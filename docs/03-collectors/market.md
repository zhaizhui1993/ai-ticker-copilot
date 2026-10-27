# 03-采集 ｜ 行情采集（market.py）

> 模块：03 数据采集层 ｜ 成分：yfinance 行情源 ｜ 对应代码：collectors/market.py ｜ 实施阶段：P3
> 来源：原方案 §4 目录注释 + §6.4 + v1.1 扩充

## 职责

yfinance 单一来源提供：

| 数据 | 接口（契约见 [10-module-contracts §10.2①](../10-module-contracts.md)） | 消费方 |
|---|---|---|
| 个股日线 OHLCV | `get_daily_bars(symbol, window=300)`（MA/RSI/ATR/量比由消费方经 domain/technicals.py 自算） | 05 评分（company/industry）、08 个股详情 |
| 事件窗口日线 | `get_daily_bars_between(symbol, start, end)`（TTL 24h） | 04 量化回填/挖掘器/自动沉淀 |
| 实时报价 | `get_quote(symbol)` → MarketQuote（dashboard 支持 `?refresh=1` 实时拉取，默认读快照防限频） | 08 总览卡片 |
| **指数体制层（v1.1）** | `get_index_regime()` → IndexRegime：^GSPC/^NDX/^SOX 收盘与 MA200、^VIX、^SOX 的 ATR14 | 05 Engine（体制层硬约束）、04 破位×事件分级 |
| 财报/基本面 | `get_financials(symbol)`：季度营收与同季经营现金流、资本开支、自由现金流（最多五期），营收 YoY、毛利率、ROE、PE(TTM)；年度现金流及净债务另行保留 | 05 company_score |
| 财报日期 | `get_earnings_dates(symbol, limit=4)` | 04 经济日历（事件前降级依据） |

## 约定

- TTL 分级：行情/体制层 15min、financials/earnings 12h、bars_range 24h；
- 版本钉死 `yfinance==1.5.2` + `curl-cffi>=0.15,<0.16`（0.16 曾致断裂）；备用降级 Stooq CSV（预留未实现）；
- 防限频：串行 + 随机 sleep + tenacity 退避（见 [base-cache.md](base-cache.md)）。
- 季度报表按期末日期精确对齐；缺少当季经营现金流或资本开支时，季度自由现金流保持缺失，不用年度数值补齐。
