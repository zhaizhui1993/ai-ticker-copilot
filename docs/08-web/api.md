# 08-Web ｜ REST API 完整接口文档

> 模块:08 Web 面板 ｜ 对应代码:`web/api/`(六个路由组)+ `web/app.py`(/api/health、静态资源) ｜ 实施阶段:P8(对话为增补)
> 本文按端点逐一给出:请求参数/请求体/响应结构/错误码/降级行为,全部对照源码核实(v1.6-a)。

## 全局约定

- **Base URL**:`http://127.0.0.1:8000`(本地单用户,无鉴权)
- **请求/响应**:JSON(`Content-Type: application/json`);错误统一 FastAPI 格式 `{"detail": "中文说明"}`
- **分析互斥**:`POST /api/analysis/run` 由 web 层模块级 `threading.Lock` 串行化(与调度器并发),重复提交 **409**
- **静态资源**:`/static`(vendor 本地化);`/` 返回前端 `index.html`
- **启动行为**:lifespan 建库建表 + 种子 upsert + 按 `SCHEDULER_ENABLED` 拉起调度器;`SKIP_DB_CHECK=true` 为开发逃生门(DB 失败仅警告)
- 涉及日期均美东(ET);金额均为 USD

## 快速索引

| # | 方法 | 路径 | 用途 |
|---|---|---|---|
| 1 | GET | /api/health | 运行状态 |
| 2 | GET | /api/dashboard | 总览聚合(卡片/体制层/数据源) |
| 3 | GET | /api/stocks | 读股票池 |
| 4 | PUT | /api/stocks | 写股票池 |
| 5 | GET | /api/stocks/{symbol} | 个股 K 线与技术指标 |
| 6 | GET | /api/events | 当前事件列表 |
| 7 | GET | /api/events/poll | 增量拉新事件 |
| 8 | GET | /api/calendar | 经济日历(未来 7 天) |
| 9 | GET | /api/events/lib | 历史事件库浏览 |
| 10 | PUT | /api/events/lib | 新增历史事件(source=user) |
| 11 | PATCH | /api/events/{event_id}/status | 事件状态变更(写审计) |
| 12 | POST | /api/events/{event_id}/merge | 事件合并(写审计) |
| 13 | GET | /api/events/{event_id}/changes | 事件变更审计轨迹 |
| 14 | POST | /api/analysis/run | 触发完整分析(全局锁) |
| 15 | GET | /api/analysis/history | 分析历史列表 |
| 16 | GET | /api/config | 配置读取(博主/权重/数据源) |
| 17 | PUT | /api/config | 配置更新(博主/权重) |
| 18 | POST | /api/chat | 研究助理多轮对话 |

规划未实现:`GET /api/x/posts`(帖子流+情绪分布,P7)。

---

## 1. GET /api/health

运行状态自检(不触碰外部数据源)。

**响应**:

```json
{"status": "ok", "app": "ai-ticker-copilot", "mock_mode": false,
 "scheduler_enabled": true, "llm_model": "glm-4.x 或 (未配置)", "db_host": "127.0.0.1"}
```

---

## 2. GET /api/dashboard

总览页聚合:股票池卡片 + 指数体制层 + 数据源状态。

**Query**:

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| refresh | bool | false | true 时实时拉报价(`get_quote`,防限频默认读 30 天内快照);mock 模式恒实时 |

**响应字段**:

| 字段 | 类型 | 说明 |
|---|---|---|
| empty | bool | 股票池为空时 true,message 给出指引 |
| cards[] | StockCard | 每票一卡:symbol/segment/position/cost_basis/price/change_pct/signal/valuation/signal_note |
| cards[].signal | string\|null | **展示层防护**:快照为 accumulate/watch_add 但版本非 1.5/1.6-a → 改标 watch + note"旧版信号缺少当前准入检查";估值未过 → watch + valuation.reason |
| cards[].valuation | ValuationAssessment | 系统按最新快照价现算(七态,见 §4) |
| regime | object | broken(破位布尔)/vix/sox_atr14/indexes[]:{symbol,close,ma200,below};失败时 `{"error": "指数数据获取失败:…"}` |
| sources | object | market{name,mode}/macro{name,configured}/llm{name,configured,model}/x{name,cookie_ready}/scheduler{enabled} |

**降级**:DB 不可用 → 无信号卡片;行情失败 → price 为空仍出卡片;空池 → `{"empty": true, …}`。

---

## 3. GET /api/stocks

**响应**:`{"stocks": [StockConfig…]}`,字段结构与 §4 请求体相同。

---

## 4. PUT /api/stocks

整体覆盖式保存股票池(写 `config_files/stocks.yaml`,写后重读校验)。

**请求体**:`{"stocks": [StockIn…]}`,每条:

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| symbol | string | ✓ | `^[A-Z0-9.\-]{1,5}$`(支持 BRK.B) |
| segment | string | | 枚举 12 值:gpu/foundry/equipment/cloud/software/power/etf/custom_interconnect/optical/turnaround/energy_infra/other |
| position | string | | holding \| watchlist(默认 watchlist) |
| cost_basis | number\|null | | 持仓成本,仅展示 |
| valuation | object\|null | | ValuationEvidence(见下);**老客户端未提交该字段时自动保留库内已有值,显式 null 才清除** |

`valuation` 字段(全部 pydantic 强校验,`extra="forbid"`):`method`(dcf/multiples/scenario/sotp)、`conservative_value`(>0)、`minimum_margin`([0,1))、`as_of`、`valid_until`(≥as_of)、`assumptions[]`/`sources[]`(非空字符串列表)、`rationale`(非空)、`reviewed`(默认 false)。

**响应**:`{"saved": N}`;**错误**:400(ConfigError,含非法 symbol/非法估值字段)。

---

## 5. GET /api/stocks/{symbol}

个股 K 线与分层技术指标。

**Query**:`window` ∈ {3M, 6M, 1Y}(默认 6M;非法值回落 6M)。

**响应**:

| 字段 | 说明 |
|---|---|
| bars[] | 窗口内逐日 {date, open, high, low, close, volume} |
| indicators.close / ma20 / ma50 | 窗口口径 |
| indicators.ma200 / drawdown_52w / bias_ma200 | **全量序列口径**(需 200/252 根,窗口不够时用底层完整序列计算) |
| indicators.rsi14 / atr14_pct / volume_ratio | 窗口口径 |

**错误**:503(行情获取失败)。

---

## 6. GET /api/events

当前事件列表(含价格反应)。

**Query**:`scope`(macro_policy/geopolitical/industry/company 可选筛选)、`limit`(1~1000,默认 100)。

**响应**:`{"events": [CurrentEvent…], "db_ok": true}`;每事件含 `title/summary/scope/category/keywords/tickers_mentioned/occurred_date(+date_basis)/status/price_reactions[]`(五项价格反应:event_day_pct/prior_5d_pct/prior_20d_pct/drawdown_52w/volume_ratio + as_of/note)。
**降级**:DB 失败 → `{"events": [], "db_ok": false, "message": …}`(HTTP 200)。

---

## 7. GET /api/events/poll

前端轮询驱动未读徽章:返回参考日 ≥ since 的事件子集。

**Query**:`since`(ISO 日期,默认今天)。

**响应**:`{"events": [CurrentEvent…(≤50)], "count": n}`;失败 → `{"events": [], "count": 0, "message": …}`。

---

## 8. GET /api/calendar

经济日历:未来 7 天全池事件窗口。

**响应**:`{"today", "upcoming": [{date, type: FOMC|earnings, name}…按日期排序去重], "note"}`;note 汇总每股日历提示(如"财报日期未知")+ 宏观发布惯例说明。

---

## 9. GET /api/events/lib

历史事件库浏览。

**Query**:`source`(seed/user/auto 可选)。
**响应**:`{"events": [HistoricalEvent…]}`;**降级**:MySQL 不可用 → 返回 `seed_events.yaml` 文件内容 + message 标注。

---

## 10. PUT /api/events/lib

新增历史事件(source 固定 `user`,参与类比匹配)。

**请求体** EventIn:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| event_id | string | ✓ | 唯一标识(如 2025-04-liberation-day-tariffs) |
| name | string | ✓ | 事件名 |
| start_date | date | ✓ | 发生日(T0) |
| category | string | ✓ | macro/monetary/regulation/tech/crisis |
| summary | string | | 截 200 字 |
| mechanism | string | | 传导机制 |
| keywords | string[] | | 检索词 |
| tickers | string[] | | 受影响标的;**direction/magnitude 当前固定 -1/0.5,量化影响需人工回填** |

**响应**:`{"saved": event_id}`;**错误**:400(DB 或字段非法,含非法 category)。

---

## 11. PATCH /api/events/{event_id}/status

事件状态变更,原子写 `event_changes` 审计(before/after/reason)。

**请求体**:`{"status": "active|resolved|retracted", "reason": "1~2000 字必填"}`。
**响应**:`{"event": CurrentEvent(变更后)}`;**错误**:404(事件不存在)/ 400(非法状态迁移)/ 503(DB 不可用,变更未保存)。

## 12. POST /api/events/{event_id}/merge

把当前事件合并进目标事件;影响年龄经 `influence_start_date` 延续到目标,不重置。

**请求体**:`{"target_event_id": "1~64 字", "reason": "1~2000 字必填"}`。
**响应/错误**:同 §11。

## 13. GET /api/events/{event_id}/changes

事件完整审计轨迹(状态变更与合并历史)。

**响应**:`{"changes": [{change_id, event_id, before_json, after_json, reason, changed_at}…]}`;**错误**:503(DB)。

---

## 14. POST /api/analysis/run

触发完整分析(`run_analysis`,决策主链见 [14-技术实现文档](../14-technical-implementation.md) §3.2)。**全局锁:与调度器/其他手动触发互斥,后到者 409**。

**请求体** RunIn:

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| refresh | bool | false | true=先刷新数据再分析("刷新并分析"按钮) |
| tickers | string[]\|null | null | 只分析池内子集(不匹配时回落全池) |
| mode | string | eod | eod \| intraday_observe(盘中观察,cap=0) |

**响应**(逐字段):

| 字段 | 说明 |
|---|---|
| generated_at | ISO 时间戳(ET) |
| market_summary | 宏观与事件面总述(中文 2~3 句) |
| disclaimer | 固定"本报告仅供个人研究参考,不构成投资建议。" |
| signals[] | 每票终裁信号:{ticker, action(四档), confidence(0~1), reason(含系统约束追加), risks[], price_target_hint, position_cap, valuation(系统计算覆盖,非 LLM 评估)} |
| outputs{ticker} | EngineOutput:{weighted_total, band, regime_gate_applied, company_gate_applied, position_cap, regime_note} |
| regime_gate | bool(体制破位) |
| db_saved / run_id | 落库成功标志与审计 run_id(可回放) |
| analysis_clock | {decision_at, mode, price_session_limit} |

**错误**:409(已有分析进行中)/ 400(空池 EmptyPoolError)/ 503(数据源降级耗尽等)。

---

## 15. GET /api/analysis/history

**Query**:`limit`(默认 30)。
**响应**:`{"runs": [{run_id, created_at}…倒序]}`;DB 失败 → `{"runs": [], "message": …}`。

---

## 16. GET /api/config

**响应**:`{"pool_size", "influencers": [{handle, note, tickers}], "weights": {macro,event,industry,company}, "sources": (同 §2)}`。

## 17. PUT /api/config

按提交项分别覆盖写 `influencers.yaml` / `scoring_weights.yaml`(写后重读校验;权重合计必须 = 1.0,非法拒启语义同启动校验)。

**请求体**:`{"influencers": [{handle 必填, note, tickers}]?, "weights": {macro: 0.25,…}?}`(至少一项,否则 400"无可保存项")。
**响应**:`{"saved": ["influencers", "weights"]}`;**错误**:400(ConfigError,权重非法/博主 handle 空)。

---

## 18. POST /api/chat

研究助理多轮对话。会话历史由**客户端持有**随请求带回,服务端截取最近 20 轮;LLM 未配置 → 503(**全系统唯一强依赖 LLM 的功能**,其余均有规则降级)。

**请求体** ChatIn:

| 字段 | 约束 |
|---|---|
| messages | 1~60 条 |
| messages[].role | user \| assistant |
| messages[].content | 1~4000 字 |

**响应**:`{"reply": "…", "disclaimer": "本对话仅供个人研究参考,不构成投资建议。"}`。
**错误**:503(LLM 未配置,detail 含 .env 指引)/ 400(消息非法)/ 502(LLM 调用失败,可重试)。
**纪律**(服务端保证):回答只引用系统数据(四维分/指标/最近快照/事件/历史库),未采集直说;估值未过 allows_add 时不得给加仓倾向;情景推演标注"情景假设"。
