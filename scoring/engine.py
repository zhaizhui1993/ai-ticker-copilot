"""汇总引擎：加权求和 → 信号分档 → 体制层硬约束。

规格：docs/05-scoring/engine.md
- 默认权重 0.25×4（scoring_weights.yaml 可调，合计必须 = 1.0，loader 校验）
- 分档：≥70 积极 / 50~70 中性偏多 / 30~50 中性偏空 / <30 防御
- 体制层硬约束（v1.1）：IndexRegime.regime_broken() 为真时，
  档位上限压至"观望"——环境只做门槛，不进加权求和
"""

from domain.scoring import EngineOutput, FourDimScores, IndexRegime

DEFAULT_WEIGHTS = {"macro": 0.25, "event": 0.25, "industry": 0.25, "company": 0.25}

BAND_POSITIVE = "积极"
BAND_LEAN_BULL = "中性偏多"
BAND_LEAN_BEAR = "中性偏空"
BAND_DEFENSIVE = "防御"


def band_of(total: float) -> str:
    if total >= 70:
        return BAND_POSITIVE
    if total >= 50:
        return BAND_LEAN_BULL
    if total >= 30:
        return BAND_LEAN_BEAR
    return BAND_DEFENSIVE


# 体制层硬约束下允许的最高档（docs：上限压至"观望"）
_GATE_CEILING = {BAND_POSITIVE: BAND_LEAN_BULL, BAND_LEAN_BULL: BAND_LEAN_BULL}


class Engine:
    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        if abs(sum(self.weights.values()) - 1.0) > 1e-9:
            raise ValueError(f"四维权重合计必须为 1.0，当前 {sum(self.weights.values()):.4f}")

    def run(self, four: FourDimScores, regime: IndexRegime) -> EngineOutput:
        total = round(
            four.macro.score * self.weights["macro"]
            + four.event.score * self.weights["event"]
            + four.industry.score * self.weights["industry"]
            + four.company.score * self.weights["company"],
            1,
        )
        band = band_of(total)
        gate_applied = regime.regime_broken()

        note = ""
        if gate_applied:
            capped = _GATE_CEILING.get(band, band)
            broken = [i.symbol for i in regime.indexes if i.below_ma200]
            note = (f"体制层硬约束生效（破位指数：{'、'.join(broken)}；"
                    f"VIX {regime.vix}）——档位由「{band}」压至「{capped}」，信号上限=观望；"
                    f"LLM 上偏须援引事件类比依据")
            band = capped

        return EngineOutput(
            weighted_total=total, band=band,
            regime_gate_applied=gate_applied, regime_note=note,
        )
