"""宏观面评分（权重 25%）。规则表：docs/05-scoring/macro-score.md

每项指标映射 0-100 后按子权重加权；FRED 只有最近两期观测时以
value/prev_value 方向近似"近 3 月方向"（指标近似口径随 indicators 落库，
供 LLM 与回放核对）。数据缺失 → 该项计 50 并整体 degraded 标注。
"""

from domain.scoring import MacroPoint, ScoreBreakdown

# 子权重（docs/05-scoring/macro-score.md）
WEIGHTS: dict[str, float] = {
    "FEDFUNDS": 0.30,
    "DGS10": 0.15,
    "T10Y2Y": 0.15,
    "CPIAUCSL": 0.20,
    "UNRATE": 0.10,
    "VIX": 0.10,
}


def _dir(value: float | None, prev: float | None) -> str:
    if value is None or prev is None:
        return "未知"
    if value > prev:
        return "上行"
    if value < prev:
        return "下行"
    return "持平"


class MacroScorer:
    name = "macro"

    def score(
        self,
        series: dict[str, MacroPoint | None],
        vix: float | None = None,
    ) -> ScoreBreakdown:
        indicators: dict = {}
        subs: dict[str, float] = {}

        for sid in WEIGHTS:
            point = series.get(sid)
            indicators[sid] = point.value if point else None
            subs[sid] = self._score_series(sid, point)

        indicators["VIX"] = vix
        subs["VIX"] = self._score_vix(vix)
        indicators["CPI_同比"] = self._cpi_yoy_proxy(series.get("CPIAUCSL"))

        total = round(sum(subs[k] * w for k, w in WEIGHTS.items()), 1)

        missing = [k for k in WEIGHTS if k != "VIX" and series.get(k) is None]
        if vix is None:
            missing.append("VIX")
        if self._cpi_yoy_proxy(series.get("CPIAUCSL")) is None and "CPIAUCSL" not in missing:
            missing.append("CPI去年同月")
        note = f"宏观数据缺失：{','.join(missing)}（缺失项计中性 50）" if missing else ""

        fed = series.get("FEDFUNDS")
        cpi = indicators["CPI_同比"]
        tone = "偏多" if total >= 60 else ("偏空" if total <= 40 else "中性")
        rationale = (
            f"联邦利率{_dir(fed.value if fed else None, fed.prev_value if fed else None)}"
            f"（{fed.value if fed else '-'}%）、CPI 同比 {cpi if cpi is not None else '-'}%、"
            f"VIX {vix if vix is not None else '-'}，宏观面{tone}。"
        )
        return ScoreBreakdown(
            score=total, indicators={**indicators, **{f"sub_{k}": v for k, v in subs.items()}},
            rationale=rationale, degraded=bool(missing), degraded_note=note,
        )

    def _score_series(self, sid: str, p: MacroPoint | None) -> float:
        if p is None or p.value is None:
            return 50.0
        v, prev = p.value, p.prev_value
        if sid == "FEDFUNDS":
            if prev is not None and v < prev:
                return 80.0                       # 近 3 月下行（两期近似）
            if (prev is not None and v > prev) or v > 5.0:
                return 20.0                       # 上行或绝对值 >5%
            return 50.0
        if sid == "DGS10":
            if prev is not None and v < prev:
                return 75.0
            if prev is not None and v > prev and v > 4.5:
                return 25.0
            return 50.0
        if sid == "T10Y2Y":
            if v > 0 and (prev is None or v >= prev):
                return 75.0                       # 走阔/转正
            if prev is not None and v < prev < 0:
                return 25.0                       # 倒挂加深
            return 40.0 if v < 0 else 55.0
        if sid == "CPIAUCSL":
            yoy = self._cpi_yoy_proxy(p)
            if yoy is None:
                return 50.0
            if yoy > 4.0:
                return 25.0
            if yoy < 3.0:
                return 75.0
            return 50.0
        if sid == "UNRATE":
            if prev is not None and v - prev >= 0.2:
                return 35.0                       # 月度升幅显著（0.5pct/3月 的近似）
            if v < 4.5:
                return 75.0
            return 45.0
        return 50.0

    @staticmethod
    def _score_vix(vix: float | None) -> float:
        if vix is None:
            return 50.0
        if vix < 15:
            return 80.0
        if vix > 25:
            return 20.0
        return 50.0

    @staticmethod
    def _cpi_yoy_proxy(p: MacroPoint | None) -> float | None:
        """CPI 同比：最新指数 / 去年同月指数 - 1；缺失不使用环比年化替代。"""
        if p is None or p.year_ago_value in (None, 0):
            return None
        return round((p.value / p.year_ago_value - 1) * 100, 2)
