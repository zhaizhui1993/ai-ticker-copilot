# 07 ｜ 存储层（storage/）

> **职责**：MySQL 8 连接池管理、启动时幂等建库建表与轻量列迁移、六张核心表的 repository（快照 UPSERT / 事件 CRUD / 当前事件去重入库 / 帖子去重 / 抓取节流 / 日志追加）、事务约定——支撑"一切落库可回放"。
> **对应代码**：storage/（db.py / repository.py） ｜ **依赖模块**：02（序列化模型） ｜ **实施阶段**：P2（current_events 为 P3 事件管道配套）
> **内容来源**：原方案 §7

## 成分文档

| 文档 | 内容 | 对应代码 | 来源 |
|---|---|---|---|
| [db-ddl.md](db-ddl.md) | 选型说明、连接管理、六张表 DDL、轻量列迁移 | storage/db.py | 原方案 §7（前半） |
| [transactions.md](transactions.md) | 事务约定与幂等规则 | storage/repository.py | 原方案 §7（后半） |

接口签名见 [10-module-contracts.md §10.2⑤](../10-module-contracts.md)。
