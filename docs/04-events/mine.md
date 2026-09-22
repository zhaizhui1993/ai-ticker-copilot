# 04-事件库 ｜ 回调波段挖掘器（mine.py / mine_events.py）

> 模块：04 历史事件库 ｜ 成分：价格异常挖掘 ｜ 对应代码：events_lib/mine.py、scripts/mine_events.py ｜ 实施阶段：实施期增补
> 来源：种子库增长路线④（"从市场反应反推事件"）；2026-09 交付

## 定位

从最新指数/个股日线自动检出**回调波段**（距滚动高点回撤 ≥ 阈值），产出事件草稿骨架——与 auto-sedimentation（面向未来事件）互补，是事件库的第二个自动化增长引擎（面向历史）。核心思想：**市场真在意的事件必然留下价格痕迹**，从价格反推比从新闻清单正推覆盖更完整。

## 算法（zigzag 变体，`detect_pullbacks` 纯函数）

```
维护滚动峰值 peak ──► 自 peak 回撤 ≥ min_dd（默认 5%）→ 进入"回调中"
                    ──► 谷底继续下移则更新 trough
                    ──► 自 trough 反弹 ≥ rebound（默认 3%）或收复 peak → 波段确认结束
输出每段：峰/谷日期与价格、回撤 %、达底交易日数、恢复交易日数（未收复=None 开放波段）
```

- 阈值语义：**≥5% 才算回调**（<5% 视为噪声不收录，防止库被碎片淹没）；
- 口径与 [linkage](initialization.md) 一致：交易日计数、收盘价基准。

## CLI

```bash
# 真实行情（行情通道恢复后）
uv run python scripts/mine_events.py --symbol ^IXIC --since 2024-01-01 --min-dd 5
# 离线 CSV（Date,Close[,Open,High,Low]）——通道被封时的替代路径
uv run python scripts/mine_events.py --csv data/ixic.csv --since 2024-01-01
```

输出：检出波段一览 + 每段一个 `HistoricalEvent` YAML 骨架（`tags: [挖掘器产出, 待归因, 待核对]`）。

## 数据纪律（与种子库一致）

挖掘器只产出**量化骨架**；事件名称、机制归因、category 由人工（或 P6 后的 LLM 检索核验）补全，核对后入库——机器算数、人把质量关。2026-09 首次应用：纳指 2024+ 全部波段级回调（8 段）经此流程核对入种子库，其中 5 条为新增条目（见 [seed-events.md](seed-events.md) 指数回调波段章节），另 3 段（2024-07 轮动、2024-08 日元套息、2025-04 对等关税等）此前已收录于其他分组；量化数字暂用公开报道锚点，待通道恢复后用本工具实测复核。
