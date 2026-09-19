"""P1 验收：空池提示、非法 symbol 拒绝、权重合计校验、模板复制（docs/09-delivery/testing.md §12.4）。"""

from pathlib import Path

import pytest

from config.loader import (
    EMPTY_POOL_MESSAGE,
    ConfigError,
    load_influencers,
    load_scoring_weights,
    load_stocks,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------- 股票池 ----------


def test_empty_pool_returns_empty_list(tmp_path: Path) -> None:
    stocks = load_stocks(_write(tmp_path / "stocks.yaml", "stocks: []\n"))
    assert stocks == []
    # 空池是合法状态，调用方显示固定中文提示
    assert "股票池为空" in EMPTY_POOL_MESSAGE
    assert "stocks.yaml" in EMPTY_POOL_MESSAGE


def test_valid_stocks_load(tmp_path: Path) -> None:
    stocks = load_stocks(_write(tmp_path / "stocks.yaml", """
stocks:
  - symbol: NVDA
    segment: gpu
    position: holding
    cost_basis: 120.5
  - symbol: BRK.B
"""))
    assert [s.symbol for s in stocks] == ["NVDA", "BRK.B"]
    assert stocks[0].cost_basis == 120.5
    assert stocks[1].segment.value == "other"      # 缺省值
    assert stocks[1].position.value == "watchlist"  # 缺省值


def test_illegal_symbols_rejected_with_details(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_stocks(_write(tmp_path / "stocks.yaml", """
stocks:
  - symbol: nvda
  - symbol: TOOLONGSYMBOL
  - symbol: OK1
"""))
    message = str(exc_info.value)
    assert "nvda" in message                 # 非法条目逐一列出
    assert "toolongsymbol" in message.lower()
    assert "OK1" not in message              # 合法条目不出现在错误里


def test_template_copied_from_example_on_first_run(tmp_path: Path) -> None:
    example = _write(tmp_path / "stocks.yaml.example", "stocks: []\n")
    target = tmp_path / "stocks.yaml"
    assert not target.exists()
    load_stocks(target)  # 首次运行自动复制
    assert target.exists()
    assert target.read_text(encoding="utf-8") == example.read_text(encoding="utf-8")


def test_missing_template_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="缺少配置模板"):
        load_stocks(tmp_path / "stocks.yaml")


# ---------- 博主列表 ----------


def test_influencers_load_and_validation(tmp_path: Path) -> None:
    influencers = load_influencers(_write(tmp_path / "influencers.yaml", """
influencers:
  - handle: elonmusk
    note: 半导体/AI
    tickers: [NVDA]
"""))
    assert influencers[0].handle == "elonmusk"
    assert influencers[0].tickers == ["NVDA"]

    assert load_influencers(_write(tmp_path / "influencers2.yaml", "influencers: []\n")) == []

    with pytest.raises(ConfigError, match="handle"):
        load_influencers(_write(tmp_path / "influencers3.yaml", """
influencers:
  - note: 缺少 handle
"""))


# ---------- 评分权重 ----------


def test_default_weights_ok(tmp_path: Path) -> None:
    weights = load_scoring_weights(_write(tmp_path / "scoring_weights.yaml", """
macro: 0.25
event: 0.25
industry: 0.25
company: 0.25
"""))
    assert weights == {"macro": 0.25, "event": 0.25, "industry": 0.25, "company": 0.25}


def test_weights_sum_must_be_one(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="合计必须为 1.0"):
        load_scoring_weights(_write(tmp_path / "scoring_weights.yaml", """
macro: 0.3
event: 0.3
industry: 0.2
company: 0.1
"""))


def test_weights_missing_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="缺少权重项"):
        load_scoring_weights(_write(tmp_path / "scoring_weights.yaml", "macro: 1.0\n"))
