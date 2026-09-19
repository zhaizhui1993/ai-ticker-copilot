# 02 ｜ 数据模型（domain/ + config_files/）

> **职责**：定义跨模块共享的 pydantic 数据模型与两份用户 YAML 配置（股票池、X 博主）；纯数据结构，无业务逻辑。
> **对应代码**：domain/（stock.py / events.py / scoring.py / signal.py）、config_files/ ｜ **依赖模块**：01 ｜ **实施阶段**：P1
> **内容来源**：原方案 §5.1 / §5.2 / §5.4 / §5.5（§5.3 历史事件系列模型归入 [04-events/schema.md](../04-events/schema.md)）

## 成分文档

| 文档 | 内容 | 对应代码 | 来源 |
|---|---|---|---|
| [config-files.md](config-files.md) | 股票池与 X 博主两份用户 YAML（校验/空池处理/隐私约定） | config_files/ + domain/stock.py | 原方案 §5.1 / §5.2 |
| [event-signal-models.md](event-signal-models.md) | 当前事件模型（EventScope/CurrentEvent）与信号模型（Action/TickerSignal/AnalysisResult） | domain/events.py + domain/signal.py | 原方案 §5.4 / §5.5 |

## 模型文件分布索引

| 文件 | 模型 | 定义位置 |
|---|---|---|
| domain/stock.py | StockConfig / MarketQuote | 本文档目录 [config-files.md](config-files.md) |
| domain/events.py | EventScope / CurrentEvent | 本文档目录 [event-signal-models.md](event-signal-models.md) |
| domain/events.py | EventCategory / HistoricalEvent / TickerImpact / MarketMetrics | [04-events/schema.md](../04-events/schema.md) |
| domain/scoring.py | ScoreBreakdown / FourDimScores | [05-scoring/README.md](../05-scoring/README.md) |
| domain/signal.py | Action / TickerSignal / AnalysisResult | 本文档目录 [event-signal-models.md](event-signal-models.md) |
