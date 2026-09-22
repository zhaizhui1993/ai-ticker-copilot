"""MySQL 连接池、幂等建库建表与健康检查。

规格：docs/07-storage/db-ddl.md
- PyMySQL + DBUtils 连接池（池大小 5，个人单实例足够）
- 启动时幂等建库建表（CREATE ... IF NOT EXISTS）
- 健康检查失败即启动报错，并给出中文指引（MySQL 未启动 / 账号无权限 / 端口占用）——
  MySQL 是全系统唯一不降级的依赖（docs/10-module-contracts.md §10.5）
"""

from contextlib import contextmanager

import pymysql
from dbutils.pooled_db import PooledDB

from config.settings import settings

_POOL: PooledDB | None = None

POOL_SIZE = 5

# docs/07-storage/db-ddl.md 的五张表（InnoDB + utf8mb4）
DDL_STATEMENTS = [
    # 日度快照：每天每票一行，UPSERT
    """
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='日度快照：每天每票一行，UPSERT'
    """,
    "CREATE INDEX idx_snapshots_ticker ON snapshots(ticker, snapshot_date)",
    # 历史事件库（seed + user + auto）
    """
    CREATE TABLE IF NOT EXISTS events (
      event_id     VARCHAR(64) PRIMARY KEY COMMENT '事件唯一标识（如 2025-04-liberation-day-tariffs）',
      payload_json JSON NOT NULL COMMENT 'HistoricalEvent 完整序列化（日期/机制/关键词/联动标的等）',
      source       VARCHAR(10) NOT NULL COMMENT '事件来源：seed 种子 | user 用户录入 | auto 自动沉淀'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='历史事件库（seed + user + auto）'
    """,
    # X 帖子（去重 + 打标回填）
    """
    CREATE TABLE IF NOT EXISTS x_posts (
      post_id       VARCHAR(64) PRIMARY KEY COMMENT 'X 帖子 id（去重键）',
      author        VARCHAR(64) NOT NULL COMMENT '作者 handle',
      content       TEXT COMMENT '帖子正文',
      url           VARCHAR(512) COMMENT '原帖链接',
      likes         INT COMMENT '点赞数',
      posted_at     DATETIME COMMENT '发帖时间',
      collected_at  DATETIME COMMENT '抓取入库时间',
      reply_to      VARCHAR(64) COMMENT '回复对象 handle（原创帖为 NULL）',
      sentiment     TINYINT COMMENT '打标情绪：-1 看空 / 0 中性 / 1 看多（打标后回填）',
      sentiment_note VARCHAR(500) COMMENT '打标依据备注（打标后回填）',
      tickers_mentioned VARCHAR(255) COMMENT '提及的股票代码，逗号分隔（打标后回填）'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='X 帖子（去重 + 打标回填）'
    """,
    "CREATE INDEX idx_x_posts_author_time ON x_posts(author, posted_at)",
    # 抓取状态（X 每博主每天一次的节流依据）
    """
    CREATE TABLE IF NOT EXISTS crawl_state (
      state_key     VARCHAR(128) PRIMARY KEY COMMENT '状态键（如 x:{handle}）',
      last_crawl_at DATETIME NOT NULL COMMENT '该键上次抓取时间（每博主每天一次的节流依据）'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='抓取状态（X 每博主每天一次的节流依据）'
    """,
    # 当前事件（新闻管道产物，准实时；去重键 = raw_url+标题 hash）
    """
    CREATE TABLE IF NOT EXISTS current_events (
      event_id      VARCHAR(64) PRIMARY KEY COMMENT '事件唯一标识',
      payload_json  JSON NOT NULL COMMENT '新闻事件完整序列化（标题/摘要/关键词/联动标的等）',
      title_hash    CHAR(64) NOT NULL COMMENT '去重键：raw_url+标题的 hash（SHA-256 十六进制）',
      raw_url       VARCHAR(512) COMMENT '新闻原文链接',
      fetched_at    DATETIME NOT NULL COMMENT '抓取时间（UTC）',
      occurred_date DATE COMMENT '事件发生日期',
      scope         VARCHAR(20) COMMENT '事件层级：macro_policy 宏观政策 / geopolitical 国际热点 / industry 行业 / company 企业',
      UNIQUE KEY uq_current_events_hash (title_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='当前事件（新闻管道产物，准实时）'
    """,
    "CREATE INDEX idx_current_events_date ON current_events(occurred_date)",
    # 分析日志（只追加，保留全量历史）
    """
    CREATE TABLE IF NOT EXISTS analysis_runs (
      run_id     BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
      created_at DATETIME NOT NULL COMMENT '分析发起时间',
      input_json JSON COMMENT '分析输入（ticker/日期等）',
      result_json JSON COMMENT '分析完整结果'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析日志（只追加，保留全量历史）'
    """,
]


def _connect(database: str | None = None) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=database,
        charset="utf8mb4",
        connect_timeout=5,
    )


def check_health() -> None:
    """启动健康检查：失败抛 RuntimeError 并附中文指引。"""
    try:
        conn = _connect()
        conn.close()
    except pymysql.err.OperationalError as exc:
        code = exc.args[0] if exc.args else None
        if code in (1044, 1045):
            raise RuntimeError(
                f"MySQL 账号无权限（{code}）：请检查 .env 的 DB_USER / DB_PASSWORD 是否正确"
            ) from exc
        if code in (2003, 2001, 1042):
            raise RuntimeError(
                "MySQL 连接失败：服务未启动或端口不对。"
                "可选处理：brew services start mysql / docker compose up -d mysql"
            ) from exc
        raise RuntimeError(f"MySQL 健康检查失败：{exc}") from exc


# 增量列迁移（个人项目轻量方案）：已存在的旧表补新列，重复列(1060)静默跳过
MIGRATION_STATEMENTS = [
    "ALTER TABLE x_posts ADD COLUMN reply_to VARCHAR(64) NULL",
]


def init_schema(database: str | None = None) -> None:
    """幂等建库建表（database 为 None 时用 settings.db_name；测试可指向独立库）。"""
    database = database or settings.db_name
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    with _connect(database) as conn, conn.cursor() as cursor:
        for ddl in DDL_STATEMENTS:
            cursor.execute(ddl)
        for stmt in MIGRATION_STATEMENTS:
            try:
                cursor.execute(stmt)
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "args", [None])[0] != 1060:  # 列已存在
                    raise
        conn.commit()


def init_pool(database: str | None = None) -> PooledDB:
    """创建连接池（全局唯一；测试可用独立 database）。"""
    global _POOL
    _POOL = PooledDB(
        creator=pymysql,
        mincached=1,
        maxcached=POOL_SIZE,
        maxconnections=POOL_SIZE,
        blocking=True,
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=database or settings.db_name,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    return _POOL


def get_pool() -> PooledDB:
    global _POOL
    if _POOL is None:
        init_pool()
    return _POOL


def reset_pool() -> None:
    global _POOL
    _POOL = None


@contextmanager
def get_conn():
    """从池中取连接的上下文管理器。autocommit=True：单条语句天然幂等/原子，
    多语句事务场景由 repository 显式控制（docs/07-storage/transactions.md）。
    """
    conn = get_pool().connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """应用启动入口：健康检查 + 幂等建库建表。"""
    check_health()
    init_schema()
