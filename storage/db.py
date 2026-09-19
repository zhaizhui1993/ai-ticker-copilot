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
      snapshot_date DATE NOT NULL,
      ticker        VARCHAR(10) NOT NULL,
      close         DECIMAL(12,4),
      change_pct    DECIMAL(8,4),
      ma20          DECIMAL(12,4),
      ma50          DECIMAL(12,4),
      rsi14         DECIMAL(8,4),
      scores_json   JSON NOT NULL,
      signal        VARCHAR(20),
      confidence    DECIMAL(4,3),
      analysis_json JSON,
      updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (snapshot_date, ticker)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    "CREATE INDEX idx_snapshots_ticker ON snapshots(ticker, snapshot_date)",
    # 历史事件库（seed + user + auto）
    """
    CREATE TABLE IF NOT EXISTS events (
      event_id     VARCHAR(64) PRIMARY KEY,
      payload_json JSON NOT NULL,
      source       VARCHAR(10) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # X 帖子（去重 + 打标回填）
    """
    CREATE TABLE IF NOT EXISTS x_posts (
      post_id       VARCHAR(64) PRIMARY KEY,
      author        VARCHAR(64) NOT NULL,
      content       TEXT,
      url           VARCHAR(512),
      likes         INT,
      posted_at     DATETIME,
      collected_at  DATETIME,
      sentiment     TINYINT,
      sentiment_note VARCHAR(500),
      tickers_mentioned VARCHAR(255)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    "CREATE INDEX idx_x_posts_author_time ON x_posts(author, posted_at)",
    # 抓取状态（X 每博主每天一次的节流依据）
    """
    CREATE TABLE IF NOT EXISTS crawl_state (
      state_key     VARCHAR(128) PRIMARY KEY,
      last_crawl_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 当前事件（新闻管道产物，准实时；去重键 = raw_url+标题 hash）
    """
    CREATE TABLE IF NOT EXISTS current_events (
      event_id      VARCHAR(64) PRIMARY KEY,
      payload_json  JSON NOT NULL,
      title_hash    CHAR(64) NOT NULL,
      raw_url       VARCHAR(512),
      fetched_at    DATETIME NOT NULL,
      occurred_date DATE,
      scope         VARCHAR(20),
      UNIQUE KEY uq_current_events_hash (title_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    "CREATE INDEX idx_current_events_date ON current_events(occurred_date)",
    # 分析日志（只追加，保留全量历史）
    """
    CREATE TABLE IF NOT EXISTS analysis_runs (
      run_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at DATETIME NOT NULL,
      input_json JSON,
      result_json JSON
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
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
