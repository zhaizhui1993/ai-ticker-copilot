# 07-存储 ｜ 连接管理与 DDL

> 模块：07 存储层 ｜ 成分：连接池 + 建表 ｜ 对应代码：storage/db.py ｜ 实施阶段：P2
> 来源：原方案 §7（前半）

## 存储选型说明

按用户要求采用 MySQL 8，实际变化有三点——① 本地需要一个 MySQL 实例（复用本机已有实例，或 Docker 一键拉起）；② 备份从"复制一个文件"变为 `mysqldump`（README 提供一行备份命令）；③ 换来的是熟悉的运维工具链（Java 背景）、原生 JSON 类型、未来多端访问同一份数据的可能。仍坚持**不引 ORM**：薄 repository + 裸 SQL，控制层数。

## 连接管理（storage/db.py）

PyMySQL + DBUtils 连接池（池大小 5，个人单实例足够）；应用启动时**幂等建库建表**；健康检查失败时启动即报错并给出中文指引（MySQL 未启动 / 账号无权限 / 端口占用）。

## DDL（MySQL 8，InnoDB + utf8mb4）

```sql
-- 日度快照：每天每票一行，UPSERT（ON DUPLICATE KEY UPDATE）
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_date DATE NOT NULL,       -- 美东交易日
  ticker        VARCHAR(10) NOT NULL,
  close         DECIMAL(12,4),
  change_pct    DECIMAL(8,4),
  ma20          DECIMAL(12,4),
  ma50          DECIMAL(12,4),
  rsi14         DECIMAL(8,4),
  scores_json   JSON NOT NULL,       -- FourDimScores 序列化
  signal        VARCHAR(20),         -- accumulate/watch_add/watch/reduce
  confidence    DECIMAL(4,3),
  analysis_json JSON,                -- LLM 完整输出（理由/风险/免责声明）
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_date, ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_snapshots_ticker ON snapshots(ticker, snapshot_date);

-- 历史事件库（seed + user + auto）
CREATE TABLE IF NOT EXISTS events (
  event_id     VARCHAR(64) PRIMARY KEY,
  payload_json JSON NOT NULL,        -- HistoricalEvent 序列化
  source       VARCHAR(10) NOT NULL  -- 'seed' | 'user' | 'auto'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- X 帖子（去重 + 打标回填）
CREATE TABLE IF NOT EXISTS x_posts (
  post_id       VARCHAR(64) PRIMARY KEY,
  author        VARCHAR(64) NOT NULL,
  content       TEXT,
  url           VARCHAR(512),
  likes         INT,
  posted_at     DATETIME,
  collected_at  DATETIME,
  sentiment     TINYINT,             -- -1/0/1，打标后回填
  sentiment_note VARCHAR(500),
  tickers_mentioned VARCHAR(255)     -- 逗号分隔，打标后回填
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_x_posts_author_time ON x_posts(author, posted_at);

-- 抓取状态（X 每博主每天一次的节流依据）
CREATE TABLE IF NOT EXISTS crawl_state (
  state_key     VARCHAR(128) PRIMARY KEY,  -- 'x:{handle}'
  last_crawl_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分析日志（只追加，保留全量历史）
CREATE TABLE IF NOT EXISTS analysis_runs (
  run_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at DATETIME NOT NULL,
  input_json JSON,
  result_json JSON
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 注：events 表 `source` 含 `'auto'`，对应 [04-events/auto-sedimentation.md](../04-events/auto-sedimentation.md)（v1.1）。
