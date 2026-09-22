# 03-采集 ｜ X 第三方 API（x_api.py + x_source.py）

> 模块：03 数据采集层 ｜ 成分：twitterapi.io 接口采集 + 双通道路由 ｜ 对应代码：collectors/x_api.py、collectors/x_source.py ｜ 实施阶段：P7 增补
> 来源：实施期增补（用户需求：同时获取博主发帖与回复；接口文档 https://docs.twitterapi.io ）

## 为什么引入 API 通道

Playwright 爬虫（[x-crawler.md](x-crawler.md)）有两个结构性短板：

1. **登录态维护成本**：需 X 账号 + 定期重跑 cookie 导出，失效即整轮终止；
2. **引用推文丢上下文**：博主"短评 + 引用别人原文"的帖子，DOM 里被引原文是嵌入卡片，爬虫只能抓到短评——而这恰是财经博主最常见的表态方式之一。

twitterapi.io（第三方逆向接口，非 X 官方）一次调用即可拿到**发帖 + 回复 + 引用上下文 + 完整互动数据**，且免登录态；代价是按量付费。

## 双通道路由（collectors/x_source.py）

`X_MODE` 三态，调度器与 CLI（scripts/crawl_x.py）统一从 `x_source.crawl_and_store()` 进入：

| X_MODE | 通道 | 说明 |
|---|---|---|
| `api`（推荐） | collectors/x_api.py | twitterapi.io 接口；需 `X_API_KEY`；约 $0.15/千条推文 |
| `crawl`（默认） | collectors/x_crawler.py | Playwright 本地爬虫；免 API 费用，需登录态 |
| `off` | — | 关闭 X 采集（直接返回空结果，不触达 DB） |

两通道实现**同一 `crawl(influencers, pool_tickers) -> {"posts", "skipped", "error"}` 接口**；节流（crawl_state 每博主每天 1 次）与入库（put_x_posts，post_id 去重）在 x_source.py 共用。48h+关注词过滤（filter_posts）为共享纯函数，两通道语义一致。

## 使用的接口（仅 2 个）

| 端点 | 用途 | 关键参数 |
|---|---|---|
| `GET /twitter/user/info` | handle → userId 解析（userId 更稳定更快） | `userName`；**进程内缓存**（进程生命周期有效，重启后重新解析一次） |
| `GET /twitter/user/last_tweets` | 时间线（**发帖+回复一次拿全**） | `userId`、`includeReplies=true`、`cursor` 翻页（20 条/页） |

认证：`X-API-Key` 请求头（控制台 https://twitterapi.io/dashboard 获取），非 OAuth。

**可选预留**：`GET /twitter/tweets?tweet_ids=a,b,c`（批量补全被回复的父帖正文）。回复推文自带 `inReplyToId/Username` 但不含父帖正文；若后续要求"无关键词的回复也按父帖语境过滤/打标"，再用它按需补全，第一期不调用。

## 字段映射（API → XPost）

| API 字段 | XPost 字段 | 说明 |
|---|---|---|
| `id` | post_id | 去重唯一键 |
| `text` | content | 正文；**quoted_tweet 拼接在后**（见下） |
| `createdAt` | posted_at | 格式 `Tue Dec 10 07:00:30 +0000 2024`，解析失败置 None |
| `likeCount` | likes | 爬虫通道无互动数据（likes 恒空），API 通道把 likeCount 入库 likes |
| `url` | url | 缺失时回退拼接 `x.com/{handle}/status/{id}` |
| `isReply` + `inReplyToUsername` | reply_to | **仅回复别人时填**；自回复（楼主续帖）视为原创 → None（与爬虫 pick_reply_handle 语义一致） |
| `quoted_tweet`（嵌套对象） | content 尾部 | 拼 `「引用 @原作者：原文前 120 字…」`——情绪打标能看到被引语境，这是 API 通道独有的增益 |

## 翻页与成本控制

- 时间线新→旧：**本页最老帖子早于 `X_POST_HOURS_BACK` 时间窗即停止翻页**（增量已取完）；
- 页数硬上限 5 页（100 条/博主/天），单博主单次成本封顶 ~$0.015；
- 之后仍走 filter_posts（48h 窗口 + 关注词/ticker），与爬虫通道一致。

**费用估算**：$0.15/千条 + 单请求最低 $0.00015。5 博主 × 每天 1 轮 × ~2 页 = ~200 条/天 ≈ **$0.03/天，$1/月**（对比 X 官方 API ~$0.005/条 ≈ $24/月，低两个数量级）。

## 错误语义

| 场景 | 行为 |
|---|---|
| `X_API_KEY` 未配置 / 401/403 / 额度用尽 / 响应体 `status=="error"` | 抛 `XApiKeyError` → 整轮终止（outcome.error，语义对齐爬虫通道的 XCookieExpired） |
| handle 解析不到用户（改名/封号） | 同样抛 `XApiKeyError` → **整轮终止**（当前与 key 错误共用异常类型，语义待拆分） |
| 单博主其他异常（网络等） | 记入 skipped，其余博主继续 |
| 网络瞬时失败 | tenacity 指数退避重试 2 次（network_retry，与其他采集器一致） |

## 验收

- 单元：tests/test_x_api.py（15 条）——字段映射/引用拼接/翻页终止/userId 缓存/key 错误/单博主跳过/off 路由/节流入库编排；
- 手动：`.env` 配 `X_MODE=api` + `X_API_KEY` → `uv run python scripts/crawl_x.py`，输出应含 `→@被回复人` 的回复行与 `「引用 @…」` 上下文。
