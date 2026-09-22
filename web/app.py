"""Web 服务层（FastAPI）：六个路由组 + 静态前端 + lifespan。

- lifespan：建库建表 + 种子 upsert；SKIP_DB_CHECK=true 时 DB 失败仅警告
  （开发逃生门，默认保持"启动即失败"的严格语义，docs/07-storage/db-ddl.md）
- 全局分析锁在各路由模块内（analysis.py 409）
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from web.api import analysis, chat, config_api, dashboard, events, stocks

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from events_lib.loader import upsert_seed_events
    from storage.db import init_db

    if os.environ.get("SKIP_DB_CHECK", "").lower() in ("1", "true"):
        try:
            init_db()
            print(f"[startup] 数据库就绪，种子事件 upsert {upsert_seed_events()} 条")
        except Exception as exc:
            print(f"[startup][警告] 数据库不可用（SKIP_DB_CHECK 生效，继续启动）：{exc}")
    else:
        init_db()  # MySQL 不可达 → 启动即失败并给中文指引（唯一不降级依赖）
        print(f"[startup] 数据库就绪，种子事件 upsert {upsert_seed_events()} 条")

    scheduler = None
    if settings.scheduler_enabled:
        from scheduler import build_scheduler
        scheduler = build_scheduler()
        scheduler.start()
        print(f"[startup] 调度器已启动：{', '.join(j.name for j in scheduler.get_jobs())}")
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="ai-ticker-copilot", version="0.1.0", lifespan=lifespan)

    app.include_router(dashboard.router)
    app.include_router(stocks.router)
    app.include_router(events.router)
    app.include_router(analysis.router)
    app.include_router(config_api.router)
    app.include_router(chat.router)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

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
