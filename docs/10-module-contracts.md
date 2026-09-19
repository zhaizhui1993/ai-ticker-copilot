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
        # DailyBar: date/open/high/low/close/volume（MA/RSI/ATR/量比由消费方自算，采集层不预置指标）
    def get_index_regime(self) -> IndexRegime: ...
        # IndexRegime: spx/ndx/sox 的 close 与 ma200、vix、sox_atr14（体制层输入，见 05 §6.1.1）
    def get_financials(self, symbol: str) -> Financials: ...      # 营收/净利 YoY、毛利、FCF、ROE
    def get_earnings_dates(self, symbol: str) -> list[date]: ...  # 经济日历用（04 §6.5）

class MacroCollector(DataSource):
    def get_series(self, series_id: str) -> MacroPoint: ...       # 系列 id 见 03 采集源清单

class NewsCollector(DataSource):
    async def poll_once(self) -> list[RawArticle]: ...
        # RawArticle: source/raw_url/title/summary/fetched_at；去重键 = raw_url + 标题 hash
```

**契约要点**：采集层返回**原始/半成品数据**，不做 LLM 调用、不写业务表（mock.py 实现同一组接口，MOCK_MODE 切换零成本）；所有实现走 `@ttl_cache` + tenacity 退避。

**② 事件库（events_lib/matcher.py）**

```python
def hard_retrieve(event: CurrentEvent, lib: list[HistoricalEvent], k: int = 5) -> list[HistoricalEvent]: ...
    # 规则打分：category 相同+10 / keywords 交集每词+5 / tickers 交集每+8 / 月份邻近+3
async def llm_rerank(event: CurrentEvent, candidates: list[HistoricalEvent]) -> list[EventMatchResult]: ...
    # EventMatchResult: event_id/similarity 0~1/direction/magnitude/affected_tickers/analogy_notes
def synthesize_analogy(matches: list[EventMatchResult], lib: list[HistoricalEvent]) -> AnalogyConclusion: ...
    # AnalogyConclusion: 聚合的 平均回撤/达底/恢复天数 + confidence('high'|'low') + 样本量 n
```

**契约要点**：`similarity≥0.6` 才进入聚合；同类事件 **n<3 时输出"样本不足"而非平均值**；LLM 不可用时降级为硬检索 top-2 直接合成、`confidence='low'`（消费方必须在 rationale 标注）。

**③ 评分层（scoring/，四个 Scorer + Engine）**

```python
class MacroScorer:   def score(self, macro: list[MacroPoint], vix: float) -> ScoreBreakdown: ...
class EventScorer:   def score(self, ticker: str, analogy: AnalogyConclusion,
                               x_sentiment: float | None) -> ScoreBreakdown: ...   # None → 中性50+标注
class IndustryScorer: def score(self, segment: str, basket: list[MarketQuote]) -> ScoreBreakdown: ...
class CompanyScorer: def score(self, ticker: str, bars: list[DailyBar],
                               fin: Financials, regime: IndexRegime) -> ScoreBreakdown: ...
class Engine:
    def run(self, four: FourDimScores, regime: IndexRegime) -> EngineOutput: ...
        # EngineOutput: weighted_total + 分档 + regime_gate_applied: bool（体制层硬约束，见 05）
```

**契约要点**：Scorer 是**纯函数**（同输入同输出、无 IO、无 LLM）；规则参数集中在文件顶部常量区；体制层硬约束只在 Engine 施加，Scorer 不感知。

**④ LLM 层（analyzer/llm.py，全部 `with_structured_output(method="function_calling")`）**

```python
async def extract_events(articles: list[RawArticle]) -> list[CurrentEvent]: ...   # 批量一次调用
async def rerank_matches(event: CurrentEvent, candidates) -> list[EventMatchResult]: ...  # 供 04 调用
async def label_sentiment(posts: list[XPost]) -> list[SentimentLabel]: ...        # {post_id, sentiment, tickers, note}
async def judge(inputs: AnalysisInput) -> AnalysisResult: ...
    # AnalysisInput: 四维分+各维 indicators 原始值 + AnalogyConclusion + X 摘要 + 持仓状态(holding/watchlist)
```

**契约要点**：LLM 层是**全系统唯一的 LLM 出口**（04 的精排也经此处函数）——供应商无关，换模型只改 .env 的 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 三项；输出必为 pydantic 模型；judge 的 prompt 规则见 06 §9.3（偏离分档必须说明、免责声明固定）。

**⑤ 存储层（storage/repository.py，MySQL 唯一读写口）**

```python
def upsert_snapshot(row: SnapshotRow) -> None: ...            # ON DUPLICATE KEY UPDATE，同日覆盖
def get_snapshots(ticker: str, since: date) -> list[SnapshotRow]: ...
def put_event(ev: HistoricalEvent, source: Literal["seed","user","auto"]) -> None: ...
def list_events(source: str | None = None) -> list[HistoricalEvent]: ...
def put_x_posts(posts: list[XPost]) -> int: ...               # 返回新增条数（post_id 去重）
def mark_sentiment(labels: list[SentimentLabel]) -> None: ... # 与 put 同事务的场景见 07
def get_unlabeled_posts(limit: int) -> list[XPost]: ...
def try_crawl_lock(state_key: str) -> bool: ...               # crawl_state：每博主每天一次的节流
def append_analysis_run(input_json: dict, result_json: dict) -> int: ...  # 只追加
```

**契约要点**：事务边界集中在 repository（见 07 事务约定）；调用方不手写 SQL、不管理连接。

**⑥ 编排入口（analyzer/pipeline.py）**

```python
async def run_analysis(refresh: bool = False, tickers: list[str] | None = None) -> AnalysisResult: ...
```

**契约要点**：模块级 `asyncio.Lock` 串行——已在运行时再次调用立即返回进行中状态（Web 层转 409）；当日快照已存在且 `refresh=False` 时直接返回已存结果（不重复调 LLM）。

---

## 10.3 数据契约（生产者 → 消费者矩阵）

| # | 数据 | 生产者 | 消费者 | 载体 / 格式 | 时效 / 频率 |
|---|---|---|---|---|---|
| 1 | 日线与技术原始数据 | 03 market.py | 05 评分、08 Web | `DailyBar[]`（内存）→ snapshots 表 | 15min TTL |
| 2 | 指数体制层状态 | 03 market.py | 05 Engine（硬约束）、04 §6.2.1 分级 | `IndexRegime` | 日频计算、周频复核 |
| 3 | 宏观序列 | 03 macro.py | 05 MacroScorer | `MacroPoint` | 12h TTL |
| 4 | 原始文章 | 03 news.py | 06 extract_events | `RawArticle[]`（去重键 raw_url+标题hash） | 轮询即消费 |
| 5 | 当前事件 | 06 extract_events | 04 matcher、05 EventScorer、08 事件中心 | CurrentEvent → MySQL events 相关表 | 准实时 |
| 6 | 历史事件 | scripts build/backfill、用户、④自动沉淀 | 04 matcher | events 表 `payload_json` | 持久 |
| 7 | 类比结论 | 04 matcher | 05 EventScorer、06 judge、08 类比卡 | `AnalogyConclusion`（随 analysis_runs 落档） | 单次分析内 |
| 8 | X 帖子 | 03 x_crawler | 06 label_sentiment | x_posts 表 | 48h 窗口 |
| 9 | 情绪标签 | 06 label_sentiment | 05 EventScorer | x_posts.sentiment 回填 | 单次分析 |
| 10 | 四维分数 | 05 scoring | 06 judge、08 Web | snapshots.`scores_json` | 日度 |
| 11 | 最终信号 | 06 judge | 08 分析页、回测演进 | snapshots.`analysis_json` / analysis_runs | 日度 |
| 12 | 抓取节流状态 | 03 x_crawler | 自身 | crawl_state 表 | 每天每博主 1 次 |
| 13 | 分析输入快照 | 06 pipeline | 回放/回测（演进路径） | analysis_runs.`input_json` | 只追加 |

---

## 10.4 关键运行时时序

**场景 A：事件轮询（scheduler 每 15~30min；链路止于入库+类比，不触发分析）**

```
scheduler ──► news.poll_once() ──► [RSS / Google News / WebSearch]
                 │ 去重：raw_url+标题hash vs 已入库 → 命中即丢弃
                 │ 预过滤：四类事件关键词 或 提及股票池 ticker
                 ├──（有新文章）──► llm.extract_events() ──► CurrentEvent[]
                 │                     └─ 事务入库：events + crawl_state 同事务提交
                 ├── matcher.hard_retrieve ──► llm_rerank ──► synthesize_analogy
                 └── 本轮有新增 ──► Web 未读徽章；NEW_EVENT_NOTIFY=true 时发系统通知
```

**场景 B：完整分析（美东 17:35 cron 或 `POST /api/analysis/run`；06 pipeline 主导）**

```
触发 ──► pipeline.run_analysis(refresh, tickers)
  │ 0  全局锁检查：进行中 → 返回 409；当日已有快照且 !refresh → 直接返回旧结果
  │ 1  refresh=true → collectors 刷新（market/macro；X 若当日未抓则抓）→ 部分落库
  │ 2  取当日 CurrentEvent → matcher（04）→ AnalogyConclusion
  │ 3  market.get_index_regime() → IndexRegime
  │ 4  四个 Scorer 并行打分 → FourDimScores → Engine.run()（含体制层硬约束）
  │ 5  llm.judge(四维分 + indicators 原始值 + 类比结论 + X 摘要 + 持仓状态) → AnalysisResult
  └ 6  repository.upsert_snapshot()（同日覆盖）+ append_analysis_run() → 返回结果
```

**场景 C：Web 事件流（前端 30s 轮询）**

```
前端 ──► GET /api/events/poll?since=<last_id> ──► events 表增量读取 ──► JSON（含各自类比卡数据）
```

**场景 D：当前事件自动沉淀（T+60/T+180 天，调度器）**

```
scheduler ──► 复用 backfill 逻辑对该事件回填实测市场反应 ──► source='auto' 草稿（不参与匹配）
          ──► Web 事件库页"待核对"清单 ──► 人工确认后转正式历史事件
```

---

## 10.5 错误与降级协议（跨模块统一约定）

| 故障点 | 契约行为 | 标注义务 |
|---|---|---|
| yfinance 429/超时 | tenacity 退避重试 2 次 → 读磁盘缓存旧值 | rationale 注"数据陈旧（缓存于 X）" |
| LLM 服务不可用（超时/422/限频） | 分数照常产出；judge 降级为按分档直接给倾向；类比降级为硬检索 top-2 | 信号标"LLM 降级"、类比标 confidence='low' |
| X cookie 失效/风控 | 情绪分=50 中性；本轮终止不硬刚 | 标"X 数据缺失"；Web 提示重跑导出脚本 |
| FRED key 未填/失败 | 宏观分=50 中性 | 标"宏观数据缺失" |
| 单新闻源失败 | 跳过该源、记录状态、其余源继续；连续失败自动降频 | 数据源状态页可见 |
| **MySQL 不可达** | **启动即失败并给中文指引（全系统唯一不降级的依赖）** | — |

**总原则**：降级必须"**带标注地继续**"——任何中性填充值都要能在 rationale/API 响应中看出是缺数据的兜底，禁止静默空值（这是 01 §2.2 原则 4 的接口化表述）。

---

## 10.6 配置契约（谁消费什么）

| 配置 | 唯一读取点 | 消费模块 |
|---|---|---|
| .env（DB/LLM/FRED/MOCK/调度） | config/settings.py | 全部（经依赖注入，禁止散读） |
| stocks.yaml | config/loader.py | 03（Google News 关键词、产业篮子）、05（产业/公司评分）、08（展示） |
| influencers.yaml | config/loader.py | 03 X 爬虫、08 X 观点页 |
| scoring_weights.yaml | config/loader.py | 05 Engine（启动校验合计=1.0，非法即拒启） |
| seed_events.yaml | events_lib/loader.py | 04（启动 upsert，source='seed'） |
