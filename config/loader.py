"""三个用户 YAML 的加载、校验与模板复制。

规格：docs/02-domain-models/config-files.md
- stocks.yaml / influencers.yaml 属个人隐私 → gitignore，首次运行自动从 *.example 复制
- symbol 校验 ``^[A-Z0-9.\\-]{1,5}$``；非法条目报错并列出明细（个人数据写错必须明说，不静默跳过）
- 空池是合法状态，调用方用 EMPTY_POOL_MESSAGE 显示固定中文提示（不抛堆栈）
- scoring_weights.yaml 随仓库提交，四维权重合计必须 = 1.0，非法即拒启
"""

import re
import shutil
from pathlib import Path

import yaml
from pydantic import ValidationError

from domain.events import EventScope  # noqa: F401  （P3 事件关键词过滤将复用）
from domain.stock import InfluencerConfig, StockConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config_files"

SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,5}$")

EMPTY_POOL_MESSAGE = "股票池为空：请编辑 config_files/stocks.yaml 填入你的关注股票后刷新"
EMPTY_INFLUENCERS_MESSAGE = "博主列表为空：请编辑 config_files/influencers.yaml 填入要跟进的 X 博主"

WEIGHT_KEYS = ("macro", "event", "industry", "company")


class ConfigError(Exception):
    """配置文件非法（含明细），启动即报错"""


def _ensure_user_yaml(path: Path) -> Path:
    """首次运行从同名 .example 复制用户 YAML（隐私文件不入库）。"""
    if not path.exists():
        example = path.with_name(path.name + ".example")
        if not example.exists():
            raise ConfigError(f"缺少配置模板：{example}")
        shutil.copy(example, path)
    return path


def _read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_stocks(path: Path | None = None) -> list[StockConfig]:
    """加载股票池。空池返回 []（合法）；非法条目抛 ConfigError 并列出全部明细。"""
    path = _ensure_user_yaml(path or CONFIG_DIR / "stocks.yaml")
    raw = _read_yaml(path).get("stocks") or []

    stocks: list[StockConfig] = []
    errors: list[str] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"第 {i} 条不是映射结构：{item!r}")
            continue
        symbol = str(item.get("symbol", ""))
        if not SYMBOL_RE.match(symbol):
            errors.append(
                f"第 {i} 条 symbol 非法：{symbol!r}"
                f"（须匹配 ^[A-Z0-9.\\-]{{1,5}}$，大写，如 NVDA、BRK.B）"
            )
            continue
        try:
            stocks.append(StockConfig(**item))
        except ValidationError as exc:
            errors.append(f"第 {i} 条（{symbol}）字段无效：{exc.errors()[0]['msg']}")

    if errors:
        raise ConfigError("stocks.yaml 存在非法条目，请修正后再运行：\n" + "\n".join(f"- {e}" for e in errors))
    return stocks


def load_influencers(path: Path | None = None) -> list[InfluencerConfig]:
    """加载 X 博主列表。空列表返回 []（爬虫跳过并由 UI 提示）。"""
    path = _ensure_user_yaml(path or CONFIG_DIR / "influencers.yaml")
    raw = _read_yaml(path).get("influencers") or []

    result: list[InfluencerConfig] = []
    errors: list[str] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or not str(item.get("handle", "")).strip():
            errors.append(f"第 {i} 条缺少 handle（X 用户名，不带 @）：{item!r}")
            continue
        try:
            result.append(InfluencerConfig(handle=str(item["handle"]).strip(), **{
                k: v for k, v in item.items() if k != "handle"}))
        except ValidationError as exc:
            errors.append(f"第 {i} 条字段无效：{exc.errors()[0]['msg']}")

    if errors:
        raise ConfigError("influencers.yaml 存在非法条目，请修正后再运行：\n" + "\n".join(f"- {e}" for e in errors))
    return result


def load_scoring_weights(path: Path | None = None) -> dict[str, float]:
    """加载四维权重并校验合计 = 1.0，非法即拒启（docs/05-scoring/engine.md）。"""
    path = path or CONFIG_DIR / "scoring_weights.yaml"  # 随仓库提交，无需 example 复制
    data = _read_yaml(path)
    missing = [k for k in WEIGHT_KEYS if k not in data]
    if missing:
        raise ConfigError(f"scoring_weights.yaml 缺少权重项：{', '.join(missing)}")

    weights = {k: float(data[k]) for k in WEIGHT_KEYS}
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        raise ConfigError(
            f"scoring_weights.yaml 四维权重合计必须为 1.0，当前为 {total:.4f}"
            f"（{' / '.join(f'{k}={v}' for k, v in weights.items())}）"
        )
    return weights
