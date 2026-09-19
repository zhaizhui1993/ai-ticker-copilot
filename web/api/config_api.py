"""config 路由：博主列表、评分权重、数据源状态。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.loader import (
    ConfigError,
    CONFIG_DIR,
    load_influencers,
    load_scoring_weights,
    load_stocks,
)

router = APIRouter()


@router.get("/api/config")
def get_config() -> dict:
    weights = load_scoring_weights()
    influencers = load_influencers()
    from web.api.dashboard import _sources
    return {
        "pool_size": len(load_stocks()),
        "influencers": [i.model_dump() for i in influencers],
        "weights": weights,
        "sources": _sources(),
    }


class InfluencerIn(BaseModel):
    handle: str
    note: str = ""
    tickers: list[str] = []


class ConfigIn(BaseModel):
    influencers: list[InfluencerIn] | None = None
    weights: dict[str, float] | None = None


@router.put("/api/config")
def put_config(body: ConfigIn) -> dict:
    import yaml
    saved = []

    if body.influencers is not None:
        target = CONFIG_DIR / "influencers.yaml"
        data = {"influencers": [i.model_dump() for i in body.influencers]}
        target.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")
        load_influencers(target)  # 写后重读校验
        saved.append("influencers")

    if body.weights is not None:
        target = CONFIG_DIR / "scoring_weights.yaml"
        target.write_text(yaml.dump(body.weights, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")
        load_scoring_weights(target)  # 合计=1.0 校验，非法抛 ConfigError
        saved.append("weights")

    if not saved:
        raise HTTPException(status_code=400, detail="无可保存项")
    return {"saved": saved}
