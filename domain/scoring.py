"""评分域模型：四维分数、指数体制层与汇总输出。

规格：docs/05-scoring/README.md（ScoreBreakdown / FourDimScores）
     docs/05-scoring/layered-technicals.md（IndexRegime 体制层）
     docs/05-scoring/engine.md（体制层分级约束判定）
     docs/10-module-contracts.md §10.2①③（MacroPoint / EngineOutput）
"""

from pydantic import BaseModel, Field

# 信号分档阈值（docs/05-scoring/engine.md）
BAND_POSITIVE = 70.0    # ≥70 积极：建仓/加仓
BAND_LEAN_BULL = 50.0   # 50~70 中性偏多：观望偏加仓
BAND_LEAN_BEAR = 30.0   # 30~50 中性偏空：观望；<30 防御：减仓/回避


class ScoreBreakdown(BaseModel):
    """每个评分维度的统一产物（规则模板生成中文 rationale）"""

    score: float = Field(ge=0, le=100)
    indicators: dict[str, float | int | str | None] = Field(default_factory=dict)
    rationale: str = ""
    degraded: bool = False          # 数据缺失时 True（中性兜底必须带标注）
    degraded_note: str = ""         # 如"X 数据缺失""宏观数据缺失"


class FourDimScores(BaseModel):
    macro: ScoreBreakdown
    event: ScoreBreakdown
    industry: ScoreBreakdown
    company: ScoreBreakdown


class MacroPoint(BaseModel):
    """FRED 单系列最新观测（macro.get_series 产物）"""

    series_id: str                  # 如 FEDFUNDS / DGS10 / CPIAUCSL
    as_of: str                      # 观测日期（FRED 为字符串 yyyy-mm-dd）
    value: float
    prev_value: float | None = None  # 前值（方向判断用）


class IndexLevel(BaseModel):
    """单一指数的体制层读数"""

    symbol: str                     # ^GSPC / ^NDX / ^SOX
    close: float
    ma200: float

    @property
    def below_ma200(self) -> bool:
        return self.close < self.ma200


class IndexRegime(BaseModel):
    """指数体制层（v1.1）：只做门槛，不进加权求和。

    风险仪表以 ^SOX 的 ATR 与板块宽度为主，VIX 仅作大盘参考
    （VIX 对板块集中回调失真，docs/05-scoring/layered-technicals.md）。
    """

    indexes: list[IndexLevel] = Field(min_length=1)
    vix: float | None = None
    sox_atr14: float | None = None  # 费城半导体 ATR14（%）

    def regime_broken(self) -> bool:
        """体制层分级约束判定（docs/05-scoring/engine.md）：

        两个及以上指数收盘 < MA200，或任一指数 < MA200 且 VIX>25。
        触发后由 Engine 档位封顶"中性偏多"并输出仓位上限系数 0.3。
        """
        below = [i for i in self.indexes if i.below_ma200]
        if len(below) >= 2:
            return True
        return len(below) >= 1 and self.vix is not None and self.vix > 25


class EngineOutput(BaseModel):
    """加权汇总 + 分档 + 体制层分级约束结果"""

    weighted_total: float = Field(ge=0, le=100)
    band: str                       # 分档参考（积极/中性偏多/中性偏空/防御）
    regime_gate_applied: bool = False  # 体制层破位时 True：档位封顶 + 仓位上限系数
    regime_note: str = ""
    company_gate_applied: bool = False  # 公司面短板门槛触发（v1.2：公司分过低时封顶档位）
    position_cap: float = Field(default=1.0, ge=0.0, le=1.0)  # 仓位上限系数（破位 0.3，正常 1.0）
