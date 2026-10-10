"""Valuation admission is independent of business quality and LLM opinions."""
from datetime import date
from decimal import Decimal
from math import isfinite

from domain.stock import DailyBar
from domain.valuation import ValuationAssessment, ValuationEvidence


def assess_valuation(evidence: ValuationEvidence | None, bars: list[DailyBar],
                     today: date) -> ValuationAssessment:
    latest = max(bars, key=lambda b: b.date) if bars else None
    price = latest.close if latest and isfinite(latest.close) and latest.close > 0 else None
    fields = {"evidence": evidence, "price": price,
              "price_date": latest.date if latest else None}
    if evidence is None:
        return ValuationAssessment(status="missing", reason="缺少经复核的估值证据", **fields)
    if not evidence.reviewed:
        return ValuationAssessment(status="unreviewed", reason="估值证据尚未人工复核", **fields)
    if evidence.as_of > today:
        return ValuationAssessment(status="future", reason="估值研究日期晚于分析日期", **fields)
    if evidence.valid_until < today:
        return ValuationAssessment(status="expired", reason="估值证据已过期，需重新复核", **fields)
    if (price is None or not latest or not evidence.as_of <= latest.date <= today
            or (today - latest.date).days > 5):
        return ValuationAssessment(status="invalid_price", reason="行情无效、过期或早于估值研究日期", **fields)
    exact_margin = 1 - Decimal(str(price)) / Decimal(str(evidence.conservative_value))
    margin = float(exact_margin)
    if not isfinite(margin):
        return ValuationAssessment(status="invalid_price", reason="估值与价格比例超出有效数值范围", **fields)
    passed = exact_margin >= Decimal(str(evidence.minimum_margin))
    return ValuationAssessment(
        status="passed" if passed else "insufficient_margin", allows_add=passed,
        margin=margin, reason=(f"按复核假设计算安全边际 {margin:.1%}，"
                             f"{'达到' if passed else '未达到'}要求 {evidence.minimum_margin:.1%}"), **fields)
