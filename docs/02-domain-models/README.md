# 02 ｜ 数据模型（domain/ + config_files/）

> **职责**：定义跨模块共享的 Pydantic 数据模型与用户 YAML 配置（股票池、X 博主、四维权重）；`domain/technicals.py` 与 `domain/asof.py` 另提供纯计算和决策时钟。
> **对应代码**：domain/（stock.py / events.py / scoring.py / technicals.py / signal.py）、config_files/ ｜ **依赖模块**：01 ｜ **实施阶段**：P1
> **内容来源**：原方案 §5.1 / §5.2 / §5.4 / §5.5（§5.3 历史事件系列模型归入 [04-events/schema.md](../04-events/schema.md)）

## 成分文档

| 文档 | 内容 | 对应代码 | 来源 |
|---|---|---|---|
| [core-models.md](core-models.md) | 核心领域对象关系、字段语义与持久化边界 | domain/ | 当前实现 |
| [config-files.md](config-files.md) | 股票池与 X 博主两份用户 YAML（校验/空池处理/隐私约定），scoring_weights.yaml 交叉引用 | config_files/ + domain/stock.py | 原方案 §5.1 / §5.2 |
| [event-signal-models.md](event-signal-models.md) | 当前事件模型（EventScope/PriceReaction/CurrentEvent）与信号模型（Action/TickerSignal/AnalysisResult） | domain/events.py + domain/signal.py | 原方案 §5.4 / §5.5 |

## 模型文件分布索引

| 文件 | 模型 | 定义位置 |
|---|---|---|
| domain/stock.py | StockConfig / MarketQuote / InfluencerConfig / Segment / Position / DailyBar / QuarterlyFinancials / Financials | [core-models.md](core-models.md)、[config-files.md](config-files.md) |
| domain/events.py | EventScope / PriceReaction / CurrentEvent / XPost / SentimentLabel / RawArticle | 本文档目录 [event-signal-models.md](event-signal-models.md)；XPost 字段映射见 [03-collectors/x-api.md](../03-collectors/x-api.md) |
| domain/events.py | EventCategory / HistoricalEvent / TickerImpact / MarketMetrics / EventMatchResult / AnalogyConclusion | [04-events/schema.md](../04-events/schema.md)、[04-events/matcher.md](../04-events/matcher.md) |
| domain/scoring.py | ScoreBreakdown / FourDimScores / MacroPoint / IndexLevel / IndexRegime / EngineOutput | [05-scoring/README.md](../05-scoring/README.md)、[05-scoring/layered-technicals.md](../05-scoring/layered-technicals.md) |
| domain/technicals.py | sma / ma_slope_pct / rsi / atr_pct / volume_ratio / drawdown_from_high_pct / bias_vs_ma200_pct / closed_below_ma200（纯函数） | [05-scoring/layered-technicals.md](../05-scoring/layered-technicals.md) |
| domain/signal.py | Action / TickerSignal / AnalysisResult | 本文档目录 [event-signal-models.md](event-signal-models.md) |
