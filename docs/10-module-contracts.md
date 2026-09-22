# 10 ｜ 模块交互与接口契约

> **职责**：定义模块间的调用关系与依赖方向、核心接口协议（Python 签名）、跨模块数据契约（生产者→消费者矩阵）、关键运行时时序、错误降级协议与配置契约——实施时的"模块间接缝"规范。
> **对应代码**：跨模块（接口分散在各模块的边界文件中） ｜ **依赖模块**：全部（本文档是其公共规范） ｜ **实施阶段**：P0 敲定协议骨架，各阶段遵守
> **内容来源**：v1.1 新增，由原方案 §2/§4/§6/§7/§9 的隐式约定显式化而来

---

## 10.1 依赖方向规则（谁可以调用谁）

```
                    ┌────────────────────────────┐
                    │  08 Web（web/app.py + api/）│  人工入口
                    └──────────────┬─────────────┘
                                   │ REST / 直接函数调用
                    ┌──────────────▼─────────────┐
                    │  06 编排（analyzer/pipeline）│  run_analysis()
                    └──┬─────────┬─────────┬─────┘
                       │         │         │
          ┌────────────▼──┐ ┌────▼─────┐ ┌─▼──────────────┐
          │ 03 采集        │ │ 04 事件库 │ │ 05 评分         │
          │ collectors/   │ │ events_  │ │ scoring/       │
          │               │ │ lib/     │ │                │
          └──────┬────────┘ └────┬─────┘ └───┬────────────┘
                 │               │           │
                 └───────┬───────┴───────────┘
                         ▼
              ┌─────────────────────┐      ┌──────────────────────┐
              │ 07 存储 storage/     │      │ 02 模型 domain/       │
              │ （MySQL 唯一落地点） │      │ （被所有层 import，    │
              └─────────────────────┘      │  不 import 任何业务层）│
                                          └──────────────────────┘
   09 交付物（scheduler/scripts/tests）：scripts 直连 03/04；scheduler 复用 06 的 pipeline 与 03 的管道
```

**硬性规则**：

1. **依赖单向向下**：web → analyzer → (collectors / events_lib / scoring) → (storage, domain)。下层禁止 import 上层（collectors 不知道 analyzer 的存在）。
2. **domain/ 是纯模型层**：只被 import，不 import 任何业务模块；模块间传值一律用 pydantic 模型，禁止裸 dict 穿层。
3. **MySQL 只经 storage/repository 写入**：其他模块不得直连 DB 写数据（读也建议经 repository，保证锁与事务约定集中）。
4. **配置单一入口**：只有 config/settings.py 读 .env/YAML，其余模块经依赖注入拿 `Settings` 实例；禁止散落的 `os.getenv`。
5. **跨模块通信仅三种载体**：函数调用 + pydantic 模型（同步链路）、MySQL 表（跨进程/跨时间的数据交接）、.env/YAML（静态配置）。不引消息队列/Redis（见 01 §3"明确不用"）。

---

## 10.2 核心接口协议（签名参考）

> 以下签名为实施参考（P0 定骨架、允许微调），字段与校验以 [02-domain-models/](02-domain-models/README.md)、[04-events/schema.md](04-events/schema.md)、[05-scoring/](05-scoring/README.md) 的模型定义为准。其中 `IndexRegime`、`AnalogyConclusion`、`DailyBar`、`MacroPoint`、`RawArticle` 为 v1.1 显式化的新增载体模型，建议补入 domain/ 对应文件。

**① 采集层（collectors/base.py 定义协议，各源实现）**

```python
class DataSource(Protocol):
    name: str                                   # 数据源标识（状态页/日志用）

class MarketCollector(DataSource):
    def get_quote(self, symbol: str) -> MarketQuote: ...
    def get_daily_bars(self, symbol: str, window: int = 300) -> list[DailyBar]: ...
        # DailyBar: date/open/high/low/close/volume（MA/RSI/ATR/量比由消费方经 domain/technicals 自算）
    def get_daily_bars_between(self, symbol: str, start: date, end: date) -> list[DailyBar]: ...
        # 事件窗口取数（TTL 24h）：04 回填/挖掘器/自动沉淀共用
    def get_index_regime(self) -> IndexRegime: ...
        # IndexRegime: indexes: list[IndexLevel]（spx/ndx/sox 各含 close/ma200）+ vix + sox_atr14
        # + regime_broken()（体制层判定，见 05 §6.1.1）
    def get_financials(self, symbol: str) -> Financials: ...      # 营收YoY/毛利/ROE/PE(TTM)（净利YoY/FCF 预留）
    def get_earnings_dates(self, symbol: str, limit: int = 4) -> list[date]: ...  # 经济日历用（04 §6.5）

class MacroCollector(DataSource):
    def get_series(self, series_id: str) -> MacroPoint: ...       # 单系列（系列清单硬编码于 macro.py）
    def get_all(self) -> dict[str, MacroPoint | None]: ...        # 7 系列批量；单系列失败以 None 占位

class NewsCollector(DataSource):
    def poll_once(self, pool_tickers: list[str]) -> dict: ...
        # 返回 {fetched/new/filtered/stored/events}；另有 poll_once_async 包装
        # RawArticle: source/raw_url/title/summary/fetched_at；去重键 = raw_url + 标题 hash

class XSource:                                                  # X 双通道统一入口（x_source.py）
    def crawl_and_store(self, influencers: list[InfluencerConfig],
                        pool_tickers: list[str]) -> dict: ...
        # X_MODE 路由（api→x_api / crawl→x_crawler / off→空结果）→ 节流 → 抓取 → 入库
        # 返回 {posts/stored/throttled/skipped/error/mode}；两通道实现同一 crawl() 接口
```

**契约要点**：采集层返回**原始/半成品数据**，不做 LLM 调用、不写业务表（mock.py 实现同一组接口，MOCK_MODE 切换零成本）；所有实现走 `@ttl_cache` + tenacity 退避；news 管道在入库前调用 04 的 `reaction.enrich_events` 富化价格反应（见②）。

**② 事件库（events_lib/）**

```python
# matcher.py —— 两级匹配
def hard_retrieve(event: CurrentEvent, lib: list[HistoricalEvent], k: int = 5) -> list[HistoricalEvent]: ...
    # 规则打分：category 相同+10 / keywords 交集每词+5 / tickers 交集每+8 / 月份邻近+3
def rule_rerank(event: CurrentEvent, candidates: list[HistoricalEvent]) -> list[EventMatchResult]: ...
    # 规则版精排（可解释成分：category 0.3 + 关键词覆盖 0.4 + 标的 0.2 + 月份 0.1），confidence='low'
def llm_rerank(event: CurrentEvent, candidates) -> list[EventMatchResult]: ...
    # 占位别名（当前直接委托 rule_rerank）；真 LLM 精排 = analyzer/llm.rerank_matches（见④），
    # 由 pipeline 内联调用并回落 rule_rerank
def synthesize_analogy(matches: list[EventMatchResult], lib: list[HistoricalEvent]) -> AnalogyConclusion: ...
    # 库函数（测试/复用）：聚合 平均回撤/达底/恢复天数 + confidence('high'|'low') + 样本量 n

# reaction.py —— 当前事件价格反应富化（入库前，news 管道调用）
def compute_reaction(ticker: str, bars: list[DailyBar], event_date: date) -> PriceReaction | None: ...
    # 五指标：event_day_pct/prior_5d_pct/prior_20d_pct/drawdown_52w/volume_ratio；以事件日截断
def enrich_events(events: list[CurrentEvent], market) -> list[CurrentEvent]: ...
    # 每事件 tickers_mentioned 前 ≤3 只；单 ticker 行情失败静默降级不阻断入库

# mine.py —— 回调波段挖掘（zigzag 变体）
def detect_pullbacks(bars: list[DailyBar], min_dd: float = 5, rebound: float = 3) -> list[dict]: ...
    # 输出峰/谷日期与价格、回撤%、达底/恢复交易日数（未收复=None 开放波段）

# linkage.py —— 联动层回填算法（backfill 脚本与自动沉淀共用）
def compute_linkage(bars: list[DailyBar], t0: date) -> dict | None: ...
    # 回撤/达底/恢复天数（前高含 T0 收盘、180 交易日窗）

# auto_sediment.py —— 自动沉淀
def sediment_due_events(...) -> ...   # T+60/T+180（±3 天）到点事件 → source='auto' 草稿
```

**契约要点**：`similarity≥0.6` 才计入聚合；同类事件 **n<3 时输出"样本不足"而非平均值**；LLM 不可用时降级为规则精排结果、`confidence='low'`（消费方必须在 rationale 标注）。

**③ 评分层（scoring/，四个 Scorer + Engine）**

```python
class MacroScorer:
    def score(self, series: dict[str, MacroPoint | None], vix: float | None = None) -> ScoreBreakdown: ...
class EventScorer:
    def score(self, ticker: str, matches: list[tuple[EventMatchResult, int]] | None,
              x_sentiment: float | None = None) -> ScoreBreakdown: ...
        # matches = (精排结果, 事件距今天数) 列表（新鲜度衰减在评分内算）；None → 中性50+标注
class IndustryScorer:
    def score(self, segment: str, bars_by_symbol: dict[str, list[DailyBar]],
              spy_bars: list[DailyBar] | None = None,
              financials: Financials | None = None,      # pipeline 当前未喂 → 财报动量子项恒中性
              ai_word_delta: float | None = None) -> ScoreBreakdown: ...   # 同上，AI 景气度恒中性
class CompanyScorer:
    def score(self, ticker: str, bars: list[DailyBar],
              fin: Financials | None = None) -> ScoreBreakdown: ...        # fin 缺失 → 基面子项中性
class Engine:
    def __init__(self, weights: dict[str, float] | None = None): ...      # 权重合计≠1.0 即抛错
    def run(self, four: FourDimScores, regime: IndexRegime) -> EngineOutput: ...
        # EngineOutput: weighted_total + 分档 + regime_note（体制层硬约束：破位时档位上限压至中性偏多）
```

**契约要点**：Scorer 是**纯函数**（同输入同输出、无 IO、无 LLM）；规则参数集中在文件顶部常量区；体制层硬约束只在 Engine 施加，Scorer 不感知。

**④ LLM 层（analyzer/llm.py，结构化调用均 `with_structured_output(method="function_calling")`；全部同步函数）**

```python
def llm_available() -> bool: ...
def extract_events(articles: list[RawArticle], pool_tickers: list[str],
                   seq_start: int = 1, today: date | None = None) -> list[CurrentEvent]: ...
    # 批量一次调用；无 key/失败自动降级 rule_extract 规则版
def rerank_matches(event, candidates) -> list[EventMatchResult] | None: ...
    # 真 LLM 精排（供 pipeline 调用）；返回 None = 降级（走 matcher.rule_rerank）
def judge(ctx: dict, ticker_ctx: dict) -> AnalysisResult: ...
    # ctx=全局上下文（日期/体制层/事件匹配），ticker_ctx=个股四维分与 indicators；无 key 用 rule_judge
def label_sentiment(posts: list[XPost]) -> list[SentimentLabel]: ...   # 规划未实现（存储侧接口已就绪）

# analyzer/chat.py —— 研究助理对话（实施期增补；唯一强依赖 LLM 的功能，无降级）
def build_chat_context() -> dict: ...   # 六块上下文（池/信号/体制/事件含价格反应/事件库/降级说明），各块独立降级
def chat(messages: list[dict]) -> str: ...   # 服务端截最近 MAX_HISTORY=20 轮；未配置 key 抛 LLMNotConfigured
```

**契约要点**：所有 LLM 请求经 analyzer/llm.py 的 `_chat()` 统一发起——供应商无关，换模型只改 .env 的 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 三项；结构化调用输出必为 pydantic 模型（chat 返回纯文本为例外）；judge 的 prompt 规则见 06 §9.3（偏离分档必须说明、免责声明固定）。

**⑤ 存储层（storage/repository.py，MySQL 唯一读写口）**

```python
def upsert_snapshot(row: SnapshotRow) -> None: ...            # ON DUPLICATE KEY UPDATE，同日覆盖
def get_snapshots(ticker: str, since: date) -> list[SnapshotRow]: ...
def put_event(event: HistoricalEvent, source: str = "seed") -> None: ...
def list_events(source: str | None = None) -> list[HistoricalEvent]: ...
def put_x_posts(posts: list[XPost]) -> int: ...               # 返回新增条数（post_id 去重）
def mark_sentiment(labels: list[SentimentLabel]) -> int: ...  # 打标回填（独立于 put_x_posts），返回更新条数
def get_unlabeled_posts(limit: int = 100) -> list[XPost]: ...
def try_crawl_lock(state_key: str) -> bool: ...               # crawl_state：每博主每天一次的节流（先锁后抓）
# ---- 当前事件（news 管道产物）----
def article_hash(raw_url: str, title: str) -> str: ...        # SHA-256(raw_url|title)，去重键
def put_current_events(events: list, title_hashes: list[str] | None = None) -> int: ...  # INSERT IGNORE
def has_title_hashes(hashes: list[str]) -> set[str]: ...      # 入库前预查
def list_current_events(since_date=None, scope: str | None = None, limit: int = 100) -> list: ...
def append_analysis_run(input_json: dict, result_json: dict) -> int: ...  # 只追加
```

**契约要点**：事务边界集中在 repository（见 07 事务约定，autocommit + 单语句原子）；调用方不手写 SQL、不管理连接。

**⑥ 编排入口（analyzer/pipeline.py）**

```python
def run_analysis(refresh: bool = False, tickers: list[str] | None = None) -> dict: ...
    # 返回 {result: AnalysisResult, outputs: dict, regime: IndexRegime|None, db_saved: bool, cached: bool}
```

**契约要点**：并发防护在 **Web 层模块级 `threading.Lock`**（进行中再触发 → 409）+ 调度器 `max_instances=1`，pipeline 自身无锁；当日快照已存在且 `refresh=False` 时直接返回已存结果（`cached=True`，不重复调 LLM；mock 模式跳过幂等）；DB 不可用时跳过落库照常出结果（`db_saved=False`）。

---

## 10.3 数据契约（生产者 → 消费者矩阵）

| # | 数据 | 生产者 | 消费者 | 载体 / 格式 | 时效 / 频率 |
|---|---|---|---|---|---|
| 1 | 日线与技术原始数据 | 03 market.py | 05 评分、08 Web | `DailyBar[]`（内存）→ snapshots 表 | 分级 TTL（15min/12h/24h） |
| 2 | 指数体制层状态 | 03 market.py | 05 Engine（硬约束）、04 §6.2.1 分级 | `IndexRegime` | 按需计算（15min TTL） |
| 3 | 宏观序列 | 03 macro.py | 05 MacroScorer | `dict[str, MacroPoint]`（get_all） | 12h TTL |
| 4 | 原始文章 | 03 news.py | 06 extract_events | `RawArticle[]`（去重键 raw_url+标题hash） | 轮询即消费 |
| 5 | 当前事件（含价格反应） | 06 extract_events + 04 reaction 富化 | 06 pipeline 匹配、08 事件中心、06 chat 上下文 | CurrentEvent（含 price_reactions）→ **current_events 表** | 准实时 |
| 6 | 历史事件 | scripts build/backfill/mine、用户、④自动沉淀 | 04 matcher | events 表 `payload_json` | 持久 |
| 7 | 事件匹配结果 | 06 pipeline（hard_retrieve + llm.rerank_matches） | 05 EventScorer（每事件 top-3）、06 judge | `EventMatchResult[]`（随 analysis_runs 落档） | 单次分析内 |
| 8 | X 帖子（含 reply_to/引用） | 03 **x_source**（api/crawl 双通道） | 08 X 观点页；label_sentiment（规划） | x_posts 表 | 48h 窗口 |
| 9 | 情绪标签 | 06 label_sentiment（**规划未实现**） | 05 EventScorer | x_posts.sentiment 回填 | 单次分析 |
| 10 | 四维分数 | 05 scoring | 06 judge、08 Web | snapshots.`scores_json` | 日度 |
| 11 | 最终信号 | 06 judge / rule_judge | 08 分析页、回测演进 | snapshots.`analysis_json` / analysis_runs | 日度 |
| 12 | 抓取节流状态 | 03 x_source | 自身 | crawl_state 表 | 每天每博主 1 次 |
| 13 | 分析输入快照 | 06 pipeline | 回放/回测（演进路径） | analysis_runs.`input_json` | 只追加 |
| 14 | 对话消息 | 08 Web（浏览器持有历史） | 06 chat（截 20 轮） | `POST /api/chat`（不落库） | 会话内 |

---

## 10.4 关键运行时时序

**场景 A：事件轮询（scheduler 默认每 20min；链路止于入库，不触发分析与匹配）**

```
scheduler ──► news.poll_once(pool_tickers) ──► [内置 RSS / NEWS_RSS_FEEDS / Google News 主题流+关键词流]
                 │ 48h 年龄过滤 → 去重预查：title_hash vs current_events → 命中即丢弃
                 │ 预过滤：四类事件关键词 或 提及股票池 ticker（rule_extract）
                 ├──（有新文章）──► llm.extract_events() ──► CurrentEvent[]
                 │                     └─ reaction.enrich_events()（≤3 只标的价格反应）
                 │                     └─ put_current_events()：INSERT IGNORE + title_hash 唯一键去重
                 └── 本轮有新增 ──► Web 未读徽章；NEW_EVENT_NOTIFY=true 时发系统通知
```

**场景 B：完整分析（美东 17:35 cron 或 `POST /api/analysis/run`；06 pipeline 主导）**

```
触发 ──► pipeline.run_analysis(refresh, tickers)   # Web 层 threading.Lock：进行中 → 409
  │ 0  当日已有快照且 !refresh → 直接返回旧结果（cached）；mock 模式跳过幂等
  │ 1  取数：逐票 get_daily_bars/get_financials + get_index_regime + macro.get_all
  │    （X 不在此链路——由调度器每日 ET 9:00 独立任务抓取）
  │ 2  取最近当前事件 → matcher.hard_retrieve(top-5) → llm.rerank_matches（None 则 rule_rerank）→ 每事件 top-3
  │ 3  四个 Scorer 打分 → FourDimScores → Engine.run()（体制层硬约束：破位时档位上限压至中性偏多）
  │ 4  llm.judge(ctx, ticker_ctx)（无 key → rule_judge）→ AnalysisResult
  └ 5  repository.upsert_snapshot()（同日覆盖）+ append_analysis_run() → 返回 {result, outputs, regime, db_saved, cached}
```

**场景 C：Web 事件流（前端轮询）**

```
前端 ──► GET /api/events/poll?since=<ISO日期> ──► current_events 表按 occurred_date 增量读取（limit 50）──► JSON（含 price_reactions）
```

**场景 D：当前事件自动沉淀（T+60/T+180 天 ±3，调度器每日 ET 8:00）**

```
scheduler ──► auto_sediment：到点事件（池内标的优先，≤6 只）──► 复用 linkage.compute_linkage 回填实测反应
          ──► source='auto' 草稿（不参与匹配；类比库 = seed + user）
          ──► Web 事件库页"待核对"清单 ──► 人工确认后转正式历史事件
```

---

## 10.5 错误与降级协议（跨模块统一约定）

| 故障点 | 契约行为 | 标注义务 |
|---|---|---|
| yfinance 429/超时 | tenacity 退避重试 2 次 → 仍失败则上抛，对应维度计中性（读旧值回退未实现） | rationale 注"数据缺失" |
| LLM 服务不可用（无 key/超时/422/限频） | 分数照常产出；抽取降级 rule_extract、精排降级 rule_rerank、judge 降级 rule_judge 按分档直接给倾向；**chat 例外：503 不降级** | 信号标"LLM 降级"、类比标 confidence='low' |
| X crawl cookie 失效/风控 | 情绪分=50 中性；本轮终止不硬刚；可切 X_MODE=api | 标"X 数据缺失"；Web 提示重跑导出脚本或切 API 通道 |
| X api key 无效/额度尽（XApiKeyError） | 整轮终止并提示查 twitterapi.io 控制台；可切 X_MODE=crawl | outcome.error 透出 |
| FRED key 未填/失败 | 宏观分=50 中性 | 标"宏观数据缺失" |
| 单新闻源失败 | 跳过该源、打印状态、其余源继续 | 轮询摘要可见 |
| 反应富化单标的行情失败 | 该 PriceReaction 缺省（None），事件照常入库 | note/as_of 记录口径 |
| **MySQL 不可达** | **启动即失败并给中文指引（全系统唯一不降级的依赖；SKIP_DB_CHECK=true 逃生门除外）**；分析运行中 DB 挂 → 跳过落库照常出结果 | — |

**总原则**：降级必须"**带标注地继续**"——任何中性填充值都要能在 rationale/API 响应中看出是缺数据的兜底，禁止静默空值（这是 01 §2.2 原则 4 的接口化表述）。

---

## 10.6 配置契约（谁消费什么）

| 配置 | 唯一读取点 | 消费模块 |
|---|---|---|
| .env（DB/LLM/FRED/MOCK/X_MODE/X_API_KEY/X_API_BASE/调度） | config/settings.py | 全部（经依赖注入，禁止散读；唯一例外：SKIP_DB_CHECK 由 web/app.py 直读 os.environ，属开发逃生门） |
| stocks.yaml | config/loader.py | 03（Google News 关键词、产业篮子）、05（产业/公司评分）、08（展示） |
| influencers.yaml | config/loader.py | 03 X 采集（x_source 路由 → api/crawl 通道）、08 X 观点页 |
| scoring_weights.yaml | config/loader.py | 05 Engine（启动校验合计=1.0，非法即拒启） |
| seed_events.yaml | events_lib/loader.py | 04（启动 upsert，source='seed'） |
