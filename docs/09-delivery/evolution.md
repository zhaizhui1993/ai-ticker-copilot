# 09-交付 ｜ 演进路径（本期不做，预留接口）

> 模块：09 交付与运维 ｜ 成分：演进预留 ｜ 实施阶段：后续版本
> 来源：原方案 §14

1. **事件库扩容后**（>200 条）：硬检索升级为 embedding 向量检索（matcher 接口不变，只换检索实现）。
2. **数据源切换**：yfinance → 付费行情（Polygon/Finnhub），采集层 DataSource 协议保证替换成本为单文件；X 采集已落地双通道切换（X_MODE=api/crawl/off，见 [03-collectors/x-api.md](../03-collectors/x-api.md)）。
3. **多资产扩展**：domain 层 currency/market 字段预留，未来可加 A 股/加密。
4. **信号回测**：snapshots 历史序列积累后可统计"信号准确率"，反哺权重调参（scoring_weights.yaml 已是数据驱动）。
5. **多端推送**：scheduler 已就位，macOS 系统通知已实现（NEW_EVENT_NOTIFY），加邮件等渠道即可。
6. **事件库增长路线**（部分已落地）：① 人工增补种子（31 条）✅；② 用户 Web 端新增（简化表单）✅；③ 当前事件自动沉淀（auto_sediment，T+60/T+180）✅；④ **价格反推挖掘器（mine/mine_events）✅ 2026-09 交付**——种子库"指数回调波段"批次即其产物，待雅虎通道恢复后对全库量化实测复核。
7. **对话助理演进**：服务端会话记忆与多轮上下文持久化（当前会话历史由浏览器持有、服务端截 20 轮）。
8. **X 情绪打标管线**：label_sentiment 批量打标 + 正帖占比聚合进事件面评分（存储接口已就绪，见 [03-collectors/x-crawler.md](../03-collectors/x-crawler.md)）。
