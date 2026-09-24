"""信号评测（P0-3 演进）：基准对照 + LLM 偏离质量 + 校准曲线 + 月度评估存档。

评测哲学（对应评审框架，不要求 100% 胜率）：
- 不评测单次结论对错，评测「过程可审计 + 统计上有增量」；
- 一切收益看**相对全池等权同期基准的超额**——AI 板块牛市里绝对胜率被 β 主导，无意义；
- 月度报告追加式存档（data/eval/monthly-YYYY-MM.md，只追加永不覆盖），
  固定指标集固定口径，历史报告不可回改——防自欺机制。

数据源：MySQL snapshots（signal/close/confidence/analysis{band,regime_gate,signals}）
+ 真实日线（collectors market.get_daily_bars_between）。
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from scoring.engine import band_of

HORIZONS = (5, 20, 60)          # 前瞻窗口（交易日）
MAE_WINDOW = 20                 # 最大不利变动窗口
WHIPSAW_MAX_DAYS = 20           # 破位段短于该天数且深度浅于 -5% 判为假信号
WHIPSAW_MAX_DEPTH = -5.0        # %（相对 MA200）

# 分档 → 隐含动作（Engine 分档语义；stored band 为门槛后档位）
BAND_TO_ACTION = {"积极": "accumulate", "中性偏多": "watch_add",
                  "中性偏空": "watch", "防御": "reduce"}
_ACTION_RANK = {"reduce": 0, "watch": 1, "watch_add": 2, "accumulate": 3}

# 校准分箱（左闭右开，末箱到 1.0）
CONFIDENCE_BINS = ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01))


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else float("nan")


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else float("nan")


def _fmt(v: float) -> str:
    return f"{v:+.1f}%" if v == v else "n/a"


def _rate(values: list[float], pred) -> float:
    return (sum(1 for v in values if pred(v)) / len(values) * 100) if values else float("nan")


# ---------- 数据装载 ----------


def load_signal_records(tickers: list[str] | None = None,
                        since: date | None = None) -> list[dict]:
    """从快照表读取信号记录（action/close/confidence/band/regime_gate/source）。

    band 优先取落库的门槛后档位（analysis.band）；历史行缺失时按四维等权
    均值近似（未含体制/公司门槛，降级口径）。source 区分 LLM 与规则产物。
    """
    from storage import repository

    tickers = tickers or repository.list_snapshot_tickers()
    since = since or date(2000, 1, 1)
    records = []
    for ticker in tickers:
        for row in repository.get_snapshots(ticker, since):
            if not (row.signal and row.close):
                continue
            analysis = row.analysis or {}
            # Do not backdate a signal generated on a later calendar day to stale prices.
            if analysis.get("price_date") and analysis["price_date"] != str(row.snapshot_date):
                continue
            band = analysis.get("band")
            if not band and row.scores:
                s = row.scores
                total = (s.macro.score + s.event.score + s.industry.score
                         + s.company.score) / 4
                band = band_of(total)
            sig_meta = next((s for s in analysis.get("signals", [])
                             if s.get("ticker") == ticker), None)
            source = "unknown"
            if sig_meta:
                source = "rule" if "LLM 降级" in (sig_meta.get("reason") or "") else "llm"
            records.append({
                "ticker": ticker, "date": date.fromisoformat(analysis["price_date"]) if analysis.get("price_date") else row.snapshot_date, "action": row.signal,
                "band": band, "confidence": row.confidence, "close": row.close,
                "regime_gate": bool(analysis.get("regime_gate", False)),
                "source": analysis.get("source", source),
            })
    return records


def attach_forward_returns(records: list[dict], market) -> int:
    """给每条记录挂前瞻收益 + 全池等权同期基准 + 超额；返回未匹配行情的条数。

    基准口径：同日有快照的全池 tickers，各自用自身日线算 fwd，等权平均。
    """
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_ticker[r["ticker"]].append(r)

    missed = 0
    bars_by_ticker: dict[str, list] = {}
    idx_by_ticker: dict[str, dict] = {}
    for ticker, group in by_ticker.items():
        start = min(r["date"] for r in group) - timedelta(days=10)
        try:
            bars = market.get_daily_bars_between(ticker, start, date.today())
        except Exception:
            missed += len(group)
            continue
        bars_by_ticker[ticker] = bars
        idx_by_ticker[ticker] = {b.date: i for i, b in enumerate(bars)}
        index = idx_by_ticker[ticker]
        for r in group:
            i = index.get(r["date"])
            if i is None:
                missed += 1
                continue
            for h in HORIZONS:
                j = i + h
                r[f"fwd_{h}d"] = (bars[j].close / bars[i].close - 1) * 100 if j < len(bars) else None
            mae_window = bars[i + 1: i + 1 + MAE_WINDOW]
            r["mae_20d"] = (min(b.low for b in mae_window) / bars[i].close - 1) * 100 if len(mae_window) == MAE_WINDOW else None

    # 全池等权同期基准（用行情自身收盘，避免快照 close 口径混用）
    for r in records:
        for h in HORIZONS:
            r[f"bench_{h}d"] = None
            r[f"excess_{h}d"] = None
    for d in {r["date"] for r in records}:
        for h in HORIZONS:
            vals = []
            day_tickers = {r["ticker"] for r in records if r["date"] == d}
            for ticker, bars in bars_by_ticker.items():
                if ticker not in day_tickers:
                    continue
                i = idx_by_ticker[ticker].get(d)
                if i is not None and i + h < len(bars) and bars[i].close:
                    vals.append((bars[i + h].close / bars[i].close - 1) * 100)
            if vals:
                bench = _mean(vals)
                for r in records:
                    if r["date"] == d and r.get(f"fwd_{h}d") is not None:
                        r[f"bench_{h}d"] = bench
                        r[f"excess_{h}d"] = r[f"fwd_{h}d"] - bench
    return missed


# ---------- ① 信号前瞻研究（含基准对照） ----------


def report_signals(records: list[dict]) -> str:
    groups: dict[tuple[str, bool], list[dict]] = defaultdict(list)
    for r in records:
        groups[(r["action"], r["regime_gate"])].append(r)

    lines = [f"== 信号前瞻研究（{len(records)} 条信号；按 信号 × 体制破位 分组；收益均为相对全池等权同期的口径）=="]
    header = (f"{'信号':<11}{'破位':<4}{'n':>5}{'20d均值':>9}{'20d基准':>9}{'20d超额':>9}"
              f"{'60d超额':>9}{'20d胜率':>8}{'跑赢基准':>9}{'MAE中位':>9}")
    lines += [header, "-" * len(header)]
    for (action, gate), group in sorted(groups.items()):
        f20 = [r["fwd_20d"] for r in group if r.get("fwd_20d") is not None]
        e20 = [r["excess_20d"] for r in group if r.get("excess_20d") is not None]
        e60 = [r["excess_60d"] for r in group if r.get("excess_60d") is not None]
        b20 = [r["bench_20d"] for r in group if r.get("bench_20d") is not None]
        maes = [r["mae_20d"] for r in group if r.get("mae_20d") is not None]
        win20 = f"{_rate(f20, lambda v: v > 0):.1f}%" if f20 else "n/a"
        beat = f"{_rate(e20, lambda v: v > 0):.1f}%" if e20 else "n/a"
        lines.append(f"{action:<11}{'是' if gate else '否':<4}{len(group):>5}"
                     f"{_fmt(_mean(f20)):>9}{_fmt(_mean(b20)):>9}{_fmt(_mean(e20)):>9}"
                     f"{_fmt(_mean(e60)):>9}{win20:>8}{beat:>9}{_fmt(_median(maes)):>9}")
    lines += ["",
              "读法：四组 20d/60d 超额应随信号档位单调递减（accumulate→reduce）；",
              "『跑赢基准』= fwd > 同期全池等权的信号占比，>50% 才说明含 β 之外的增量信息；",
              "accumulate×破位 的 MAE 若不深于 accumulate×正常，说明体制约束没有兑现保护价值。"]
    return "\n".join(lines)


# ---------- ② LLM 偏离质量追踪 ----------


def deviation_tag(record: dict) -> str | None:
    """偏离分类：compliant / '{implied}->{actual}'；band 未知返回 None。"""
    implied = BAND_TO_ACTION.get(record.get("band") or "")
    if implied is None:
        return None
    actual = record["action"]
    return "compliant" if implied == actual else f"{implied}->{actual}"


def report_deviation(records: list[dict]) -> str:
    tagged = [(r, deviation_tag(r)) for r in records]
    tagged = [(r, t) for r, t in tagged if t is not None]
    compliant = [r for r, t in tagged if t == "compliant"]
    deviant = [(r, t) for r, t in tagged if t != "compliant"]
    violations = [r for r in records if r.get("regime_gate") and r.get("action") == "accumulate"]

    lines = [f"== LLM 偏离质量追踪（可判定 {len(tagged)} 条：遵守 {len(compliant)} / 偏离 {len(deviant)}）=="]

    def _block(name: str, group: list[dict]) -> None:
        f20 = [r["fwd_20d"] for r in group if r.get("fwd_20d") is not None]
        e20 = [r["excess_20d"] for r in group if r.get("excess_20d") is not None]
        e60 = [r["excess_60d"] for r in group if r.get("excess_60d") is not None]
        lines.append(f"  {name}：n={len(group)}  20d超额均值 {_fmt(_mean(e20))}"
                     f"（胜率 {_rate(e20, lambda v: v > 0):.0f}%）"
                     f"  60d超额均值 {_fmt(_mean(e60))}  绝对20d {_fmt(_mean(f20))}")

    _block("遵守分档组", compliant)
    _block("偏离分档组", [r for r, _ in deviant])

    by_transition: dict[str, list[dict]] = defaultdict(list)
    for r, t in deviant:
        by_transition[t].append(r)
    if by_transition:
        lines.append("  偏离明细（隐含→实际）：")
        for transition, group in sorted(by_transition.items(), key=lambda kv: -len(kv[1])):
            src, dst = transition.split("->")
            direction = "上偏" if _ACTION_RANK[dst] > _ACTION_RANK[src] else "下偏"
            e20 = [r["excess_20d"] for r in group if r.get("excess_20d") is not None]
            lines.append(f"    {transition}（{direction}）：n={len(group)}  "
                         f"20d超额均值 {_fmt(_mean(e20))}  "
                         f"样本：{'、'.join(f'{r['ticker']}@{r['date']}' for r in group[:5])}"
                         + ("…" if len(group) > 5 else ""))
    lines.append(f"  体制封顶违背（破位日仍输出 accumulate）：{len(violations)} 条"
                 + ("（prompt 规则 5 未被遵守，需检查 LLM 输出）" if violations else ""))
    lines += ["", "读法：偏离组 20d/60d 超额不优于遵守组 → LLM 偏离是噪音，应收紧偏离权限；",
              "上偏与下偏分开看：下偏（更谨慎）通常无害，上偏必须有事件类比依据（prompt 规则 3/5）。"]
    return "\n".join(lines)


# ---------- ③ 校准曲线（置信度 vs 实际胜率） ----------


def _confidence_bin(confidence: float) -> int | None:
    for i, (lo, hi) in enumerate(CONFIDENCE_BINS):
        if lo <= confidence < hi:
            return i
    return None


def report_calibration(records: list[dict], source: str = "all") -> str:
    pool = [r for r in records if r.get("confidence") is not None]
    if source != "all":
        pool = [r for r in pool if r.get("source") == source]
    label = {"all": "全部", "llm": "仅 LLM 产物", "rule": "仅规则产物"}[source]

    lines = [f"== 校准曲线（{label}，{len(pool)} 条含置信度信号）=="]
    lines.append("动作按 20d 超额定义成功：加仓>0、减仓<0；观望无方向，不计算胜率。")
    for action in ("accumulate", "watch_add", "reduce", "watch"):
        group = [r for r in pool if r["action"] == action]
        if not group:
            continue
        lines.append(f"  {action}：{len(group)} 条")
        for i, (lo, hi) in enumerate(CONFIDENCE_BINS):
            bucket = [r for r in group if _confidence_bin(float(r["confidence"])) == i]
            if not bucket:
                continue
            mature = [r for r in bucket if r.get("excess_20d") is not None]
            label = f"[{lo:.1f}, {min(hi, 1.0):.1f})"
            if action == "watch" or not mature:
                lines.append(f"    {label} n={len(bucket)} 校准差 n/a（观望或窗口未成熟）")
                continue
            sign = -1 if action == "reduce" else 1
            win = _rate([sign * r["excess_20d"] for r in mature], lambda v: v > 0)
            avg = _mean([float(r["confidence"]) for r in mature])
            lines.append(f"    {label} n={len(mature)} 平均置信 {avg:.2f} "
                         f"动作成功率 {win:.1f}% 校准差 {avg * 100 - win:+.1f}pt")
    return "\n".join(lines)


# ---------- 体制层 whipsaw 统计（P1-3 可证伪口径） ----------


def regime_whipsaw(market, symbol: str, years: float = 6.0) -> str:
    start = date.today() - timedelta(days=int(years * 365))
    bars = market.get_daily_bars_between(symbol, start, date.today())
    if len(bars) < 210:
        return f"[{symbol}] 日线不足（{len(bars)} 根，需 ≥210）"

    closes = [b.close for b in bars]
    depth = [None] * len(bars)
    for i in range(199, len(bars)):
        ma200 = sum(closes[i - 199: i + 1]) / 200
        depth[i] = (closes[i] - ma200) / ma200 * 100

    episodes = []
    i = 200
    while i < len(bars):
        if depth[i] is not None and depth[i] < 0:
            j, min_d = i, depth[i]
            while j < len(bars) and depth[j] is not None and depth[j] < 0:
                min_d = min(min_d, depth[j])
                j += 1
            episodes.append({"start": bars[i].date, "end": bars[j - 1].date,
                             "days": j - i, "min_depth": min_d})
            i = j
        else:
            i += 1

    if not episodes:
        return f"== {symbol} MA200 体制统计：近 {years:g} 年无破位段 =="

    whipsaws = [e for e in episodes
                if e["days"] <= WHIPSAW_MAX_DAYS and e["min_depth"] > WHIPSAW_MAX_DEPTH]
    lines = [f"== {symbol} MA200 体制统计（{bars[200].date} ~ {bars[-1].date}，{len(episodes)} 段破位）==",
             f"假信号（whipsaw）：{len(whipsaws)}/{len(episodes)} = {len(whipsaws) / len(episodes) * 100:.0f}%"
             f"（判定：≤{WHIPSAW_MAX_DAYS} 交易日且最深未破 {WHIPSAW_MAX_DEPTH}%）",
             f"破位段时长：均值 {statistics.fmean(e['days'] for e in episodes):.0f} 天 / "
             f"中位 {_median([e['days'] for e in episodes]):.0f} 天；"
             f"最深幅度中位 {_fmt(_median([e['min_depth'] for e in episodes]))}"]
    for e in episodes[:30]:
        verdict = "whipsaw" if e in whipsaws else "真转折"
        lines.append(f"  {e['start']} ~ {e['end']}  {e['days']:>3} 天  {e['min_depth']:>6.1f}%  {verdict}")
    lines += ["", "读法：whipsaw 率 >50% 说明 MA200 门槛在此标的上信噪比不足（P1-3 前向证伪口径）；",
              "每段从破位到收复的天数即体制约束的最小迟到成本。"]
    return "\n".join(lines)


# ---------- ④ 月度评估：全量报告 + 追加式存档 ----------


def build_full_report(market, since: date | None = None) -> str:
    """固定指标集的月度评估（任一段失败降级标注，不中断其他段）。"""
    lines = [f"# 信号评测月报（生成于 {datetime.now():%Y-%m-%d %H:%M}）", ""]

    try:
        records = load_signal_records(since=since)
    except Exception as exc:
        return "\n".join(lines + ["## 数据读取失败", f"{exc}",
                                  "（需真实模式 + MySQL 快照积累）"])
    if not records:
        return "\n".join(lines + ["无历史信号可评测（先在真实模式跑若干天分析）"])

    missed = attach_forward_returns(records, market)
    usable = [r for r in records if any(r.get(f"fwd_{h}d") is not None for h in HORIZONS)]
    lines.append(f"样本：{len(records)} 条信号，{missed} 条未匹配行情被剔除，"
                 f"有效 {len(usable)} 条；池内标的 {len({r['ticker'] for r in records})} 只。")
    lines.append("")

    sections = [("信号前瞻研究（含基准对照）", lambda: report_signals(usable)),
                ("LLM 偏离质量追踪", lambda: report_deviation(usable)),
                ("校准曲线（全体）", lambda: report_calibration(usable, "all")),
                ("校准曲线（仅 LLM 产物）", lambda: report_calibration(usable, "llm")),
                ("体制层 whipsaw（^SOX）", lambda: regime_whipsaw(market, "^SOX", 6.0))]
    for title, build in sections:
        lines.append(f"## {title}")
        try:
            lines.append(build())
        except Exception as exc:
            lines.append(f"（本段生成失败，降级标注：{exc}）")
        lines.append("")

    lines.append("## 验收口径（固定，防挑好看数字）")
    lines.append("- 分档单调：accumulate→reduce 的 20d/60d 超额均值单调递减")
    lines.append("- 增量信息：accumulate 组『跑赢基准』占比 >50%")
    lines.append("- 校准：LLM 产物各档 |平均置信度 − 20d动作超额成功率| ≤10pt")
    lines.append("- 组件有效性：偏离组不优于遵守组时收紧偏离权限；whipsaw 率 <50%")
    lines.append("- 样本纪律：每组 <30 条信号只作观察，不作结论；同段行情信号按 1 个有效样本折算")
    return "\n".join(lines)


def archive_report(text: str, out_dir: str | None = None) -> Path:
    """追加式存档：monthly-YYYY-MM.md 只追加不覆盖（历史报告不可回改）。"""
    root = Path(out_dir) if out_dir else Path("data/eval")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"monthly-{datetime.now():%Y-%m}.md"
    with path.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n\n---\n\n")
    return path


def run_monthly_report() -> Path | None:
    """调度器入口：真实模式生成月报并存档；mock 模式跳过。"""
    from config.settings import settings

    if settings.mock_mode:
        print("[evaluation] MOCK_MODE：跳过月度评估（数字无意义）")
        return None
    from collectors import get_market
    text = build_full_report(get_market())
    path = archive_report(text)
    print(f"[evaluation] 月度评估已存档：{path}（{len(text)} 字符）")
    return path
