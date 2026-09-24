"""汇总引擎：加权求和 → 信号分档 → 体制层分级约束 + 公司面短板门槛。

规格：docs/05-scoring/engine.md
- 默认权重 0.25×4（scoring_weights.yaml 可调，合计必须 = 1.0，loader 校验）
- 分档：≥70 积极 / 50~70 中性偏多 / 30~50 中性偏空 / <30 防御
- 体制层分级约束（v1.2 / P0-2，替代 v1.1 一刀切压至"观望"）：
  IndexRegime.regime_broken() 为真时，档位上限压至"中性偏多"，
  并输出仓位上限系数 0.3（信号降为小仓试探，而不是完全关门——
  破位期一刀切观望会系统性错过恐慌底部的建仓窗口）。
- 公司面短板门槛（v1.2 / P1-1）：公司分 < 35 时档位封顶"中性偏多"
  ——基本面恶化不允许被宏观/事件/产业的强势平均掉。
"""

from domain.scoring import EngineOutput, FourDimScores, IndexRegime

DEFAULT_WEIGHTS = {"macro": 0.25, "event": 0.25, "industry": 0.25, "company": 0.25}

BAND_POSITIVE = "积极"
BAND_LEAN_BULL = "中性偏多"
BAND_LEAN_BEAR = "中性偏空"
BAND_DEFENSIVE = "防御"

# 仓位上限系数（体制层风险参数，研判侧照抄不得调高）
POSITION_CAP_NORMAL = 1.0
POSITION_CAP_BROKEN = 0.3

# 公司面短板门槛：低于该分则档位封顶（不被其他三维平均掉）
COMPANY_FLOOR = 35.0


def band_of(total: float) -> str:
    if total >= 70:
        return BAND_POSITIVE
    if total >= 50:
        return BAND_LEAN_BULL
    if total >= 30:
        return BAND_LEAN_BEAR
    return BAND_DEFENSIVE


# 上限档位约束下允许的最高档（积极 → 中性偏多）
_GATE_CEILING = {BAND_POSITIVE: BAND_LEAN_BULL}


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
        notes = []

        company_gate = four.company.score < COMPANY_FLOOR
        if four.company.score < COMPANY_FLOOR and band == BAND_POSITIVE:
            band = _GATE_CEILING[band]
            company_gate = True
            notes.append(
                f"公司面短板门槛（公司分 {four.company.score:.0f} < {COMPANY_FLOOR:.0f}）："
                f"档位封顶至「{BAND_LEAN_BULL}」——基本面恶化不被其他维度平均掉"
            )

        gate_applied = regime.regime_broken()
        position_cap = POSITION_CAP_BROKEN if gate_applied else POSITION_CAP_NORMAL
        if gate_applied:
            capped = _GATE_CEILING.get(band, band)
            broken = [i.symbol for i in regime.indexes if i.below_ma200]
            notes.append(
                f"体制层分级约束（破位指数：{'、'.join(broken)}；VIX {regime.vix}）——"
                f"档位由「{band}」压至「{capped}」，信号上限=观望偏加仓（小仓），"
                f"仓位上限系数 {POSITION_CAP_BROKEN}；LLM 上偏须援引事件类比依据"
            )
            band = capped

        return EngineOutput(
            weighted_total=total, band=band,
            regime_gate_applied=gate_applied, regime_note="；".join(notes),
            company_gate_applied=company_gate, position_cap=position_cap,
        )
