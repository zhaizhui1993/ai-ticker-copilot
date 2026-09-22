# 03-采集 ｜ 新闻事件增量管道（news.py）

> 模块：03 数据采集层 ｜ 成分：准实时事件管道 ｜ 对应代码：collectors/news.py ｜ 实施阶段：P3
> 来源：原方案 §6.4（事件管道部分）

## 管道流程

```
轮询触发 ──► 各源抓取（内置 RSS / NEWS_RSS_FEEDS 追加 / Google News 主题流+股票池关键词流）
        ──► 48h 年龄过滤（超龄旧文抓取阶段即丢弃）
        ──► 去重：raw_url + 标题 hash（article_hash=sha256(raw_url|title)）预查 + 唯一键兜底
        ──► 规则预过滤：命中四类事件关键词库，或提及股票池 ticker（analyzer/rule_extract.py）
        ──► LLM 批量抽取（仅预过滤后的新文章，一次调用处理一批）
        ──► 价格反应富化（events_lib/reaction.py，每事件 ≤3 只标的五项指标）
        ──► 新事件入库（current_events 表，INSERT IGNORE 去重）
        ──► 变化检测：本轮有新增 → Web 未读徽章 + 可选 macOS 系统通知（osascript，零依赖）
```

类比匹配**不在管道内**——发生在分析时（analyzer/pipeline.run_analysis），见 [04-events/matcher.md](../04-events/matcher.md)。

## 约定

- **单源失败**（限频/失效）只跳过该源并打印状态，不影响其他源与整体管道；
- DB 去重查询/入库失败时返回带 `db_error` 的摘要结构，不抛异常中断轮询；
- 新闻源内置默认清单（CNBC/MarketWatch/YahooFinance 通用 RSS + Google News 主题流；Reuters 公开 RSS 已停服不列入），`NEWS_RSS_FEEDS` 可追加；Google News 主题流免 key 且天然支持关键词（`news.google.com/rss/search?q=NVDA`），是**企业事件**的主要来源。
- 准实时只做**采集与事件化**，不触发完整四维分析；完整分析仍按需触发或收盘后自动跑。
- LLM 抽取走 [06-analyzer/calls.md](../06-analyzer/calls.md) 的 extract_events（批量一次调用控成本；无 key 自动降级规则版）；CurrentEvent 模型见 [02-domain-models/event-signal-models.md](../02-domain-models/event-signal-models.md)。
- **价格反应富化（实施期增补）**：入库前对每条事件提及的标的（≤3 只）计算事件日涨跌/前 5·20 日趋势/距 52 周回撤/量比，随事件落库——见 [04-events/reaction.md](../04-events/reaction.md)。
- 类比匹配环节归 [04-events/matcher.md](../04-events/matcher.md)。
- 事件轮询频率与调度归 [scheduler.md](scheduler.md)。
