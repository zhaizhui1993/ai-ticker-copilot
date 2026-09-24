"""宏观采集（FRED）。

规格：docs/03-collectors/macro.md
- 直连 FRED REST（observations 接口，稳定契约），取最近两期观测 → MacroPoint
- TTL 12h（日频数据，高频无意义）；key 未填时抛 FREDKeyMissing，由调用方降级为
  "宏观数据缺失"中性分（docs/10-module-contracts.md §10.5）
"""

import httpx

from collectors.base import network_retry, ttl_cache
from config.settings import settings
from domain.scoring import MacroPoint

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

# v1.1 起 7 个系列：前 5 个进宏观评分规则表，核心 PCE / HY 利差作环境参考
FRED_SERIES = (
    "FEDFUNDS",        # 联邦基金利率
    "DGS10",           # 十年期收益率
    "T10Y2Y",          # 期限利差
    "CPIAUCSL",        # CPI（水平值，同比由评分侧计算）
    "UNRATE",          # 失业率
    "PCEPILFE",        # 核心 PCE（v1.1）
    "BAMLH0A0HYM2",    # 高收益债利差 OAS（v1.1）
)


class FREDKeyMissing(Exception):
    """FRED_API_KEY 未配置：宏观分应降级中性并标注。"""


class MacroCollector:
    name = "fred"

    @ttl_cache("macro_series_v14", ttl_seconds=12 * 3600)
    @network_retry
    def get_series(self, series_id: str) -> MacroPoint:
        if not settings.fred_api_key:
            raise FREDKeyMissing("FRED_API_KEY 未配置（https://fred.stlouisfed.org 免费注册）")
        response = httpx.get(
            FRED_API_URL,
            params={
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 14 if series_id == "CPIAUCSL" else 10,
            },
            timeout=15,
        )
        response.raise_for_status()
        observations = response.json().get("observations", [])
        valid = [o for o in observations if o.get("value", ".") not in (".", "")]
        if not valid:
            raise RuntimeError(f"FRED 系列 {series_id} 无有效观测")
        latest = valid[0]
        prev = valid[1] if len(valid) > 1 else None
        prior_date = str(int(latest["date"][:4]) - 1) + latest["date"][4:]
        year_ago = next((o for o in valid if o["date"] == prior_date), None)
        return MacroPoint(
            series_id=series_id,
            as_of=latest["date"],
            value=float(latest["value"]),
            year_ago_value=float(year_ago["value"]) if year_ago else None,
            prev_value=float(prev["value"]) if prev else None,
        )

    def get_all(self) -> dict[str, MacroPoint]:
        """全部系列；单系列失败跳过并占位 None（不中断整体，降级协议）。"""
        result: dict[str, MacroPoint | None] = {}
        for series_id in FRED_SERIES:
            try:
                result[series_id] = self.get_series(series_id)
            except FREDKeyMissing:
                raise  # key 缺失直接上抛：调用方统一降级
            except Exception as exc:
                result[series_id] = None
                print(f"[macro] {series_id} 获取失败，降级为缺失：{exc}")
        return result
