"""股票池与行情数据模型。

规格：docs/02-domain-models/config-files.md（StockConfig）
     docs/10-module-contracts.md §10.2①（MarketQuote / DailyBar / Financials 载体）
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Segment(str, Enum):
    """产业链环节（产业面评分的篮子映射键）"""

    GPU = "gpu"
    FOUNDRY = "foundry"
    EQUIPMENT = "equipment"
    CLOUD = "cloud"
    SOFTWARE = "software"
    POWER = "power"
    ETF = "etf"
    CUSTOM_INTERCONNECT = "custom_interconnect"
    OPTICAL = "optical"
    TURNAROUND = "turnaround"
    ENERGY_INFRA = "energy_infra"
    OTHER = "other"


class Position(str, Enum):
    HOLDING = "holding"      # 持仓
    WATCHLIST = "watchlist"  # 关注未建仓


class StockConfig(BaseModel):
    """股票池条目（config_files/stocks.yaml）"""

    symbol: str = Field(pattern=r"^[A-Z0-9.\-]{1,5}$")  # 支持 BRK.B 等
    segment: Segment = Segment.OTHER
    position: Position = Position.WATCHLIST
    cost_basis: float | None = None  # 持仓成本 USD（可选，仅展示盈亏）


class InfluencerConfig(BaseModel):
    """X 博主条目（config_files/influencers.yaml）"""

    handle: str = Field(min_length=1)  # X 用户名（不带 @）
    note: str = ""
    tickers: list[str] = Field(default_factory=list)  # 主要跟踪标的（弱关联用）


class MarketQuote(BaseModel):
    """实时报价快照（market.get_quote 的产物）"""

    symbol: str
    price: float
    change_pct: float | None = None
    volume: float | None = None
    quoted_at: datetime | None = None


class DailyBar(BaseModel):
    """单根日线 OHLCV。

    采集层只返原始 OHLCV；MA/RSI/ATR/量比由消费方自算（契约 §10.2①）。
    """

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Financials(BaseModel):
    """财报基本面（market.get_financials 的产物，公司面评分输入）"""

    revenue_yoy: float | None = None        # 营收同比 %
    net_income_yoy: float | None = None     # 净利同比 %
    gross_margin: float | None = None       # 毛利率 %
    fcf_positive: bool | None = None        # 自由现金流是否为正
    roe: float | None = None                # 净资产收益率 %
    pe_ttm: float | None = None             # 当前 PE(TTM)，分位由评分侧计算

    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None  # 正数现金支出
    free_cash_flow: float | None = None
    net_debt: float | None = None
    shares_outstanding: float | None = None
    period_end: date | None = None
    collected_at: datetime | None = None
    source: str = "unknown"
