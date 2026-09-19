"""Web 服务层（FastAPI）。

P0 最小实现 + P2 lifespan：启动时建库建表、种子事件幂等 upsert。
五个路由组（dashboard / stocks / events / analysis / config）在 P8 补齐，
设计见 docs/08-web/api.md 与 docs/10-module-contracts.md §10.4。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from events_lib.loader import upsert_seed_events
from storage.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MySQL 是全系统唯一不降级的依赖：启动即健康检查，失败抛中文指引
    init_db()
    seed_count = upsert_seed_events()
    print(f"[startup] 数据库就绪，种子事件 upsert {seed_count} 条")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ai-ticker-copilot", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "app": "ai-ticker-copilot",
            "mock_mode": settings.mock_mode,
            "scheduler_enabled": settings.scheduler_enabled,
            "llm_model": settings.llm_model or "(未配置)",
            "db_host": settings.db_host,
        }

    return app
