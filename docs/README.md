# 美股 AI 股票分析系统 — 技术方案（模块化文档）

> **v1.4 修订优先**：当前契约见 [AI 产业链研究方案修订](11-ai-investment-revision.md)；下文保留早期设计背景，冲突处以修订为准。

> 版本：v1.2（2026-09-19）｜ 状态：方案评审稿，待确认后实施
> **文档组织**：每个系统模块一个目录，模块内的每个成分（子模块/子主题）单独成文，粒度对齐代码文件；各目录的 README.md 是模块导读（职责/依赖/成分索引）。
> 本目录由单文件方案《股市》（v1.1）拆分而来，原文件保留作全文存档；后续更新以本目录为准。
> v1.1 修订要点：技术面分层指标体系（[05-scoring/layered-technicals.md](05-scoring/layered-technicals.md)）、破位×事件分级规则（[04-events/breach-classification.md](04-events/breach-classification.md)）、当前事件自动沉淀（[04-events/auto-sedimentation.md](04-events/auto-sedimentation.md)）、种子事件库扩充至 10 条（[04-events/seed-events.md](04-events/seed-events.md)）、体制层硬约束（[05-scoring/engine.md](05-scoring/engine.md)）。
> **v1.2 修订：LLM 供应商无关化**——移除对 DeepSeek 的绑定，密钥/端点/模型名统一为 `LLM_*` 环境变量，任意 OpenAI 兼容大模型可切换（见 [06-analyzer/provider.md](06-analyzer/provider.md)）。
> **实施期增补（2026-09）**：种子库扩至 31 条（含 2024+ 纳指全部波段回调）、回调波段挖掘器（[04-events/mine.md](04-events/mine.md)）、当前事件价格反应富化（[04-events/reaction.md](04-events/reaction.md)）、对话式研究助理（analyzer/chat.py，见 [06-analyzer](06-analyzer/README.md)）、X 双通道（[03-collectors/x-api.md](03-collectors/x-api.md)：X_MODE=api/crawl/off，含回复抓取与 reply_to 字段）。

## 目录结构

```
docs/
├── README.md                  # 本索引
├── 10-module-contracts.md     # 模块交互与接口契约（横切规范）
├── 01-overview/               # 总览与架构（背景 / 架构 / 选型 / 目录结构）
├── 02-domain-models/          # 数据模型（用户配置 / 事件与信号模型）
├── 03-collectors/             # 数据采集层（缓存基座 / market / macro / 新闻管道 / X 双通道 api·crawl / 调度器）
├── 04-events/                 # 历史事件库（schema / 31 条种子 / 初始化 / 挖掘器 / 价格反应 / 自动沉淀 / 匹配 / 分级 / 日历）
├── 05-scoring/                # 评分引擎（四维 scorer / 分层指标 / engine）
├── 06-analyzer/               # LLM 研判层（接入 / 调用边界 / prompts）
├── 07-storage/                # 存储层（DDL / 事务）
├── 08-web/                    # Web 面板（API / 页签 / 前端要点）
└── 09-delivery/               # 交付与运维（runbook / 路线 / 测试 / 风险 / 演进）
```

## 模块总览

| 目录 | 模块 | 对应代码 | 依赖 | 实施阶段 |
|---|---|---|---|---|
| [01-overview/](01-overview/README.md) | 总览与架构 | 全局 | — | P0 |
| [02-domain-models/](02-domain-models/README.md) | 数据模型 | domain/ + config_files/ | 01 | P1 |
| [03-collectors/](03-collectors/README.md) | 数据采集层 | collectors/ + scheduler.py | 02, 07 | P3 / P7 / P9 |
| [04-events/](04-events/README.md) | 历史事件库与类比 | events_lib/ + scripts | 02, 03, 05 | P2 / P4 / P9 / 增补（挖掘器·价格反应） |
| [05-scoring/](05-scoring/README.md) | 评分引擎 | scoring/ | 02, 03, 04 | P5 |
| [06-analyzer/](06-analyzer/README.md) | LLM 研判层 | analyzer/ + prompts/ | 04, 05 | P6 |
| [07-storage/](07-storage/README.md) | 存储层 | storage/ | 02 | P2 |
| [08-web/](08-web/README.md) | Web 面板 | web/ | 全部 | P8 |
| [09-delivery/](09-delivery/README.md) | 交付与运维 | 根目录 + scripts/ + tests/ | 全部 | P0–P9 |
| [10-module-contracts.md](10-module-contracts.md) | 模块交互与接口契约 | 跨模块 | 全部 | P0 定契约 |

## 模块依赖关系

```
01 总览与架构
 └─ 02 数据模型
     ├─ 03 数据采集层（行情/宏观/新闻事件管道/X）
     ├─ 07 存储层（MySQL）
     └─ 04 历史事件库与类比 ←── 引用 05 的体制层判定
         └─ 05 评分引擎
             └─ 06 LLM 研判层
                 └─ 08 Web 面板
09 交付与运维（贯穿 P0–P9 全程）
10 模块交互与接口契约（横切规范：定义以上所有模块的接缝，P0 敲定）
```

## 导读顺序

- **评审者**：[01-overview](01-overview/README.md) → [10-module-contracts](10-module-contracts.md) → [02](02-domain-models/README.md) → [05](05-scoring/README.md) → [04](04-events/README.md) → [06](06-analyzer/README.md) → [03](03-collectors/README.md) → [07](07-storage/README.md) → [08](08-web/README.md) → [09](09-delivery/README.md)（先看决策骨架与接缝规范，再看支撑模块）
- **实施者**：P0 阶段先精读 [09-delivery/roadmap](09-delivery/roadmap.md) 与 [10-module-contracts](10-module-contracts.md)，随后按 P0–P9 顺序，每阶段开工前精读对应模块目录的 README 及该阶段涉及的成分文档

## 术语表（原附录 A）

| 术语 | 含义 |
|---|---|
| 类比（analogy） | 当前事件与历史事件的相似度匹配及影响推演 |
| 四维分 | 宏观面/事件面/产业面/公司面四个 0-100 分数 |
| 信号（signal） | accumulate/watch_add/watch/reduce 四档操作倾向 |
| 快照（snapshot） | 某交易日某股票的行情+分数+信号完整记录 |
| MOCK_MODE | 全链路假数据模式，用于无网验证 |
| 体制层（v1.1） | 指数级市场环境判定（^GSPC/^NDX/^SOX vs MA200 + VIX + 费半 ATR），只做门槛不进加权求和 |
| 乖离率（v1.1） | 价格相对 MA200 的偏离百分比，与 52 周回撤共同构成伤害度量主指标 |
| 事件前降级（v1.1） | 财报/FOMC/重要数据前 N 天内，技术买点信号自动降级为"等事件落地" |
| 破位×事件分级（v1.1） | 按指数体制层与事件类比命中的组合，把技术破位分为体制警报/深回调买点候选/事件前降级三档 |

## 待确认事项（原附录 B）

1. 实施前确定所用大模型，填 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`（任意 OpenAI 兼容端点：GPT / Qwen / GLM / Kimi / DeepSeek 等均可）。
2. 新闻 RSS 默认源清单（CNBC/MarketWatch/YahooFinance 等）实施时确认可达性；Reuters 公开 RSS 已停服不列入。
3. 种子事件的量化回填需实施时用 yfinance 实测，与记忆中的市场数据可能有出入，以实测为准。
