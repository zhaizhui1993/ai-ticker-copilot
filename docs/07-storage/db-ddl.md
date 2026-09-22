# 07-存储 ｜ 连接管理与 DDL

> 模块：07 存储层 ｜ 成分：连接池 + 建表 ｜ 对应代码：storage/db.py ｜ 实施阶段：P2
> 来源：原方案 §7（前半）

## 存储选型说明

按用户要求采用 MySQL 8，实际变化有三点——① 本地需要一个 MySQL 实例（复用本机已有实例，或 Docker 一键拉起）；② 备份从"复制一个文件"变为 `mysqldump`（README 提供一行备份命令）；③ 换来的是熟悉的运维工具链（Java 背景）、原生 JSON 类型、未来多端访问同一份数据的可能。仍坚持**不引 ORM**：薄 repository + 裸 SQL，控制层数。

## 连接管理（storage/db.py）

PyMySQL + DBUtils 连接池（池大小 5，个人单实例足够）；应用启动时**幂等建库建表 + 轻量列迁移**；健康检查失败时启动即报错并给出中文指引（MySQL 未启动 / 账号无权限 / 端口占用）。开发逃生门：环境变量 `SKIP_DB_CHECK=true` 时 DB 失败仅警告继续启动（web/app.py 直读 os.environ，默认保持"启动即失败"的严格语义）。连接为 autocommit 模式（无显式 BEGIN/COMMIT，事务语义见 [transactions.md](transactions.md)）。

## DDL（MySQL 8，InnoDB + utf8mb4）

```sql
-- 日度快照：每天每票一行，UPSERT（ON DUPLICATE KEY UPDATE）
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_date DATE NOT NULL COMMENT '快照日期（美东交易日）',
  ticker        VARCHAR(10) NOT NULL COMMENT '股票代码（如 NVDA）',
  close         DECIMAL(12,4) COMMENT '收盘价（USD）',
  change_pct    DECIMAL(8,4) COMMENT '当日涨跌幅（%）',
  ma20          DECIMAL(12,4) COMMENT '20 日均线收盘价',
  ma50          DECIMAL(12,4) COMMENT '50 日均线收盘价',
  rsi14         DECIMAL(8,4) COMMENT '14 日 RSI（0-100）',
  scores_json   JSON NOT NULL COMMENT '四维评分 FourDimScores 序列化',
  signal        VARCHAR(20) COMMENT '操作信号：accumulate 建仓/watch_add 观望偏加仓/watch 观望/reduce 减仓',
  confidence    DECIMAL(4,3) COMMENT '信号置信度（0-1）',
  analysis_json JSON COMMENT 'LLM 完整分析输出（理由/风险/免责声明）',
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '行更新时间（UPSERT 自动刷新）',
  PRIMARY KEY (snapshot_date, ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='日度快照：每天每票一行，UPSERT';
CREATE INDEX idx_snapshots_ticker ON snapshots(ticker, snapshot_date);

-- 历史事件库（seed + user + auto）
CREATE TABLE IF NOT EXISTS events (
  event_id     VARCHAR(64) PRIMARY KEY COMMENT '事件唯一标识（如 2025-04-liberation-day-tariffs）',
  payload_json JSON NOT NULL COMMENT 'HistoricalEvent 完整序列化（日期/机制/关键词/联动标的等）',
  source       VARCHAR(10) NOT NULL COMMENT '事件来源：seed 种子 | user 用户录入 | auto 自动沉淀'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='历史事件库（seed + user + auto）';

-- X 帖子（去重 + 打标回填）
CREATE TABLE IF NOT EXISTS x_posts (
  post_id       VARCHAR(64) PRIMARY KEY COMMENT 'X 帖子 id（去重键）',
  author        VARCHAR(64) NOT NULL COMMENT '作者 handle',
  content       TEXT COMMENT '帖子正文',
  url           VARCHAR(512) COMMENT '原帖链接',
  likes         INT COMMENT '点赞数',
  posted_at     DATETIME COMMENT '发帖时间',
  collected_at  DATETIME COMMENT '抓取入库时间',
  reply_to      VARCHAR(64) COMMENT '回复对象 handle（原创帖为 NULL；with_replies 页抓取）',
  sentiment     TINYINT COMMENT '打标情绪：-1 看空 / 0 中性 / 1 看多（打标后回填）',
  sentiment_note VARCHAR(500) COMMENT '打标依据备注（打标后回填）',
  tickers_mentioned VARCHAR(255) COMMENT '提及的股票代码，逗号分隔（打标后回填）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='X 帖子（去重 + 打标回填）';
CREATE INDEX idx_x_posts_author_time ON x_posts(author, posted_at);

-- 抓取状态（X 每博主每天一次的节流依据）
CREATE TABLE IF NOT EXISTS crawl_state (
  state_key     VARCHAR(128) PRIMARY KEY COMMENT '状态键（如 x:{handle}）',
  last_crawl_at DATETIME NOT NULL COMMENT '该键上次抓取时间（每博主每天一次的节流依据）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='抓取状态（X 每博主每天一次的节流依据）';

-- 当前事件（新闻管道产物，准实时；payload 含 price_reactions）
CREATE TABLE IF NOT EXISTS current_events (
  event_id      VARCHAR(64) PRIMARY KEY COMMENT '事件唯一标识',
  payload_json  JSON NOT NULL COMMENT 'CurrentEvent 完整序列化（含价格反应）',
  title_hash    CHAR(64) NOT NULL COMMENT '去重键：raw_url+标题的 SHA-256',
  raw_url       VARCHAR(512) COMMENT '新闻原文链接',
  fetched_at    DATETIME NOT NULL COMMENT '抓取时间（UTC）',
  occurred_date DATE COMMENT '事件发生日期',
  scope         VARCHAR(20) COMMENT '事件层级：macro_policy 宏观政策/geopolitical 国际热点/industry 行业/company 企业',
  UNIQUE KEY uq_current_events_hash (title_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='当前事件（新闻管道产物，准实时）';
CREATE INDEX idx_current_events_date ON current_events(occurred_date);

-- 分析日志（只追加，保留全量历史）
CREATE TABLE IF NOT EXISTS analysis_runs (
  run_id     BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  created_at DATETIME NOT NULL COMMENT '分析发起时间',
  input_json JSON COMMENT '分析输入（ticker/日期等）',
  result_json JSON COMMENT '分析完整结果'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析日志（只追加，保留全量历史）';
```

## 轻量列迁移（个人项目方案）

升级时旧表补新列走 `MIGRATION_STATEMENTS`（当前仅一条：`ALTER TABLE x_posts ADD COLUMN reply_to`）；列已存在（MySQL 1060）静默跳过，其余异常照常抛出。新增列优先直接改 DDL_STATEMENTS（新库一步到位），迁移语句兜底旧库。

> 注：events 表 `source` 含 `'auto'`，对应 [04-events/auto-sedimentation.md](../04-events/auto-sedimentation.md)（v1.1）；current_events 的入库/去重接口见 [10-module-contracts.md §10.2⑤](../10-module-contracts.md)。
