"""analysis 路由：触发分析（全局锁 409）与历史记录。"""

import threading
from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# 全局分析锁：手动触发与调度并发时后到者 409（docs/08-web/api.md）
_ANALYSIS_LOCK = threading.Lock()


class RunIn(BaseModel):
    refresh: bool = False
    tickers: list[str] | None = None


@router.post("/api/analysis/run")
def run(body: RunIn) -> dict:
    if not _ANALYSIS_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有分析进行中，请稍候")

    from analyzer.pipeline import EmptyPoolError, run_analysis
    try:
        outcome = run_analysis(refresh=body.refresh, tickers=body.tickers)
        result = outcome["result"]
        return {
            "generated_at": result.generated_at,
            "market_summary": result.market_summary,
            "disclaimer": result.disclaimer,
            "signals": [s.model_dump() for s in result.signals],
            "outputs": {t: o.model_dump() for t, o in outcome.get("outputs", {}).items()},
            "regime_gate": bool(outcome.get("regime") and outcome["regime"].regime_broken()),
            "db_saved": outcome.get("db_saved", False),
        }
    except EmptyPoolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"分析失败（数据源降级耗尽）：{exc}")
    finally:
        _ANALYSIS_LOCK.release()


@router.get("/api/analysis/history")
def history(limit: int = 30) -> dict:
    try:
        from storage import repository
        with repository.get_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT run_id, created_at FROM analysis_runs ORDER BY run_id DESC LIMIT %s",
                (limit,),
            )
            runs = cursor.fetchall()
        return {"runs": runs}
    except Exception as exc:
        return {"runs": [], "message": f"历史读取失败（DB）：{exc}"}
