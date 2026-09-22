# 09-交付 ｜ 实施路线（P0–P9）

> 模块：09 交付与运维 ｜ 成分：分阶段路线 ｜ 实施阶段：全部 ｜ 
> 来源：原方案 §11

| 阶段 | 内容 | 验收标准 | 精读文档 |
|---|---|---|---|
| P0 骨架 0.5d | uv 工程、依赖、.env.example、settings.py、目录树 | `uv sync` 成功；settings 可打印全部配置 | 01、10 |
| P1 模型+配置 0.5d | domain/*、三个 YAML、模板复制、空池友好提示 | pytest：空池提示正确、非法 symbol 拒绝 | 02 |
| P2 存储 0.5d | db.py、repository.py、种子事件 loader | pytest：UPSERT/CRUD/帖子去重 | 07、04(seed) |
| P3 采集 2d | market/macro/news/mock + ttl_cache + **事件增量管道** | `refresh_data.py --scope market` 打印行情与 MA/RSI；事件管道连续轮询两轮，验证去重与增量只增新事件 | 03 |
| P4 事件库 1d | build_events.py 事实层生成、backfill_events.py 量化回填、matcher 两级匹配 | 事实层日期经双源交叉验证；回填数字与公开报道吻合；构造"对华管制升级"假事件应命中 2023-10 轮次 | 04 |
| P5 评分 1d | 四 scorer + engine | pytest：各维分数方向/区间正确、权重生效 | 05 |
| P6 LLM 研判 1d | llm.py、prompts、pipeline | `analyze.py --ticker NVDA` 真实跑通，输出信号+免责声明 | 06 |
| P7 X 采集 1d | export_x_cookie、x_crawler、打标 | `crawl_x.py` 抓到帖子入库（**实施期增补：x_source 双通道路由 + x_api（twitterapi.io）+ reply_to 回复抓取**；打标管线为规划） | 03(x-api/x-crawler) |
| P8 Web 1.5d | FastAPI api/*、前端页签、vendor 本地化 | 浏览器全流程：刷新→分析→看卡片/图表/事件/历史（**实施期增补：第六页签"对话"研究助理**） | 08 |
| P9 收尾 1d | **调度器四类任务**（+自动沉淀）、新事件通知、经济日历、MOCK_MODE 全链路、README | mock 模式端到端；真实模式事件轮询稳定运行 24h，无重复入库、单源失效不影响整体 | 03(scheduler)、04(auto/calendar) |
| **实施期增补（P9 后，2026-09）** | 回调波段挖掘器（mine/mine_events，种子库 26→31 条）；当前事件价格反应富化（reaction，随管道入库）；X 双通道与 API 通道（x_source/x_api，15 测试）；对话式研究助理（analyzer/chat + /api/chat，4 测试） | mine_events 检出波段与公开复盘吻合；事件行携带价格反应徽章；X_MODE=api 免登录抓帖+回复+引用；对话页签可多轮追问 | 04(mine/reaction)、03(x-api)、06/08(chat) |

依赖顺序：P2←P1，P4←P2/P3，P6←P4/P5，P8←全部。总工作量约 9~11 个业余工作日。
