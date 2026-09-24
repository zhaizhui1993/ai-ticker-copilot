# 07-存储 ｜ 事务约定

> **v1.4 修订优先**：当前契约见 [AI 产业链研究方案修订](../11-ai-investment-revision.md)；下文保留早期设计背景，冲突处以修订为准。

> 模块：07 存储层 ｜ 成分：事务与幂等规则 ｜ 对应代码：storage/repository.py ｜ 实施阶段：P2
> 来源：原方案 §7（后半）

## 连接模式

连接池为 **autocommit**（无显式 BEGIN/COMMIT）；repository 均为单语句写入（INSERT/UPDATE/executemany 单批），单批原子性由单语句语义保证，不依赖跨语句事务。

## 事务与幂等约定

1. **快照 UPSERT 幂等**：`INSERT ... ON DUPLICATE KEY UPDATE` 单条语句保证幂等，同日重复分析覆盖旧值。
2. **帖子批量入库**：`put_x_posts` 单条 executemany 批量插入（post_id 主键去重）；情绪打标 `mark_sentiment` 为独立的后续回填操作（返回更新条数），两者不捆在同一事务。
3. **analysis_runs 只 INSERT 不 UPDATE**：分析日志只追加，保留全量历史。
4. **当前事件去重（幂等入库）**：三层防线——入库前 `has_title_hashes` 预查（title_hash = SHA-256(raw_url|title)）→ `INSERT IGNORE` + title_hash 唯一键兜底 → event_id 主键防覆盖；轮询中断重跑不会产生重复事件。
5. **X 抓取节流**：`try_crawl_lock`（REPLACE INTO crawl_state 单语句）**先拿锁再抓取**——同一博主同日（美东日界）只抓一次，抓取失败当日额度不退还；节流与新闻轮询无关、不同事务。
