# 04-事件库 ｜ 数据初始化（事实层 + 联动层）

> 模块：04 历史事件库 ｜ 成分：初始化工具链 ｜ 对应代码：scripts/build_events.py、scripts/backfill_events.py ｜ 实施阶段：P4
> 来源：原方案 §5.3.1（①②③ 与多轮约定）

历史事件库每条记录 = **事实层**（事件/政策本身，人工整理）+ **联动层**（股市反应量化，脚本实测回填）：

## ① 事实层初始化（LLM 辅助整理 + 人工核对，scripts/build_events.py）

> **实现现状**：脚本当前为 P4 占位骨架版（`--list/--draft/--category/--date/--keywords/--tickers`，`--draft` 只打印空的 HistoricalEvent 骨架，direction 固定 -1、量化字段全空）；下述"检索 + LLM 结构化 + 自动校验"为 P6 接入后的目标形态。

事实层不靠人工回忆整理，由工具链自动完成（目标流程）：

1. 输入：种子事件主题清单（如"2023 年 10 月美国对华芯片出口管制升级"）；
2. 对每个主题：权威源检索（BIS/federalreserve.gov 公告原文、路透/彭博当日报道、复盘文章）→ LLM 阅读检索结果，结构化输出 HistoricalEvent 草稿（公告日期、事件定性、传导机制、关键词、受影响标的；量化字段留空）→ 输出 YAML 片段；
3. 脚本内置校验：公告日期在合理历史区间、两个独立来源交叉印证日期、tickers_affected 非空、category/keywords 合法；
4. 人工只做**核对确认**（不负责整理），核对清单固定三条：公告日期对不对、传导机制是否符合常识、受影响标的是否合理；
5. 核对通过 → 写入 seed_events.yaml（随仓库版本管理）。

- 原则：只收录"可明确归因"的事件（公告日清晰、传导机制公认），模糊事件宁缺勿滥，避免污染类比库。
- Web 端用户新增历史事件（`PUT /api/events/lib`，direction/magnitude 当前固定 -1/0.5）为简化版表单，检索抽取流程待接入。

## ② 联动层初始化（脚本实测回填，scripts/backfill_events.py + events_lib/linkage.py）

对每个种子事件，`--event event_id` 指定事件（T0 与标的列表自动从 seed yaml 读取），脚本用 yfinance 日线（窗口 T0 前 30 天 ~ T0 后 180 个交易日，`get_daily_bars_between`）计算：

| 字段 | 算法 |
|---|---|
| drawdown（最大回撤 %） | 窗口内 max(1 − 收盘价/事件前高)；前高 = T0 前 30 日高点与 T0 收盘取 max |
| drawdown_days（达底天数） | T0 → 窗口内最低点的交易日数 |
| recovery_days（收复天数） | 最低点 → 重新站上前高的交易日数；180 个交易日内未收复记 None |
| market.sp500_1w / sp500_1m | SPY 在 T0 后 5 / 21 个交易日涨跌 % |
| market.vix_peak | 窗口内 ^VIX 最高值 |
| fed_rate_change_bps | 政策事实（利率事件人工填，非利率事件留空） |

脚本产出直接打印为 YAML 片段，**人工核对后**写入 seed_events.yaml——核对点：回撤数字与公开报道一致（如 DeepSeek 冲击 NVDA 单日约 −17%），不一致说明 T0 或窗口设定有误，调整后重跑。加 `--write` 可自动回写，但**只回写 market 指标**（sp500_1w/1m、vix_peak 等）；个股回撤刻意不自动回写，保持人工核对关口。

## ③ 初始化流程（实施 P4 阶段）

1. 运行 `scripts/build_events.py`：种子主题生成事实层草稿骨架（当前为占位版，见①），人工按三条清单核对后写入 seed_events.yaml（量化字段暂留空）；
2. 运行 `scripts/backfill_events.py` 逐条实测回填量化字段；
3. 人工核对修正 → loader upsert 入库（source='seed'，空库/非法条目/重复 event_id 启动即抛 SeedEventError）；
4. 用户在 Web 端新增/修正历史事件（source='user'）为简化表单（检索抽取流程待接入）。

## 多轮事件的处理约定

跨多轮的事件（如 2018-19 贸易摩擦）主事件取首轮冲击（2018-03-22 301 调查公告），后续升级轮次拆为独立条目（与三轮芯片管制一致），保证"单一公告日 → 单一市场反应"的归因清晰。
