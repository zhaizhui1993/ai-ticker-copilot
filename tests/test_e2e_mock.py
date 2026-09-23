"""P9 端到端验收（MOCK 路径，docs/09-delivery/testing.md §12.1）：

数据 → 评分 → 事件匹配 → 信号 → 返回，全程无网、无 key、无 LLM、无 DB
（DB 降级路径被一并验证）。需要 MySQL 的完整落库验证在 test_storage.py。
"""

from datetime import date

import pytest

from analyzer import llm
from analyzer.pipeline import EmptyPoolError, run_analysis
from config import settings as settings_module


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module.Settings, "model_config",
                        settings_module.Settings.model_config, raising=False)
    monkeypatch.setattr(settings_module.settings, "mock_mode", True)
    monkeypatch.setattr(settings_module.settings, "cache_dir", str(tmp_path / "cache"))


def test_e2e_mock_analysis_produces_signals() -> None:
    assert settings_module.settings.mock_mode is True
    outcome = run_analysis(refresh=True, tickers=["NVDA"])

    result = outcome["result"]
    assert result.disclaimer == "本报告仅供个人研究参考，不构成投资建议。"
    assert result.market_summary                    # 宏观 rationale 非空
    assert result.signals, "应至少产出一条信号"
    signal = result.signals[0]
    assert signal.ticker == "NVDA"
    assert signal.action.value in ("accumulate", "watch_add", "watch", "reduce")
    assert "总分" in signal.reason                   # 规则版理由必须引用分数
    assert signal.risks                             # 至少一条风险
    assert llm.llm_available() is False             # 无 key → 规则版（降级语义正确）

    # 体制层：mock regime 为健康样本 → 分级约束不触发
    assert outcome["regime"] is not None
    assert outcome["regime"].regime_broken() is False
    output = outcome["outputs"]["NVDA"]
    assert 0 <= output.weighted_total <= 100
    assert output.regime_gate_applied is False

    # DB 不可用 → 分析照常返回（降级协议）
    assert outcome["db_saved"] is False
    assert outcome["cached"] is False


def test_e2e_empty_pool_friendly_message(monkeypatch) -> None:
    from analyzer import pipeline

    monkeypatch.setattr(pipeline, "load_stocks", lambda: [])
    with pytest.raises(EmptyPoolError) as exc_info:
        run_analysis(refresh=True)
    assert "股票池为空" in str(exc_info.value)
