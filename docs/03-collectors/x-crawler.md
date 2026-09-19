# 03-采集 ｜ X 爬虫（x_crawler.py）

> 模块：03 数据采集层 ｜ 成分：Playwright X 采集 ｜ 对应代码：collectors/x_crawler.py、scripts/export_x_cookie.py、scripts/crawl_x.py ｜ 实施阶段：P7
> 来源：原方案 §6.3

## 登录态

`scripts/export_x_cookie.py` 启动有头浏览器 → 用户手动登录 x.com（含二次验证）→ 轮询检测登录态 → `context.storage_state(path="data/x_state/state.json")` 保存。选 storage_state 而非手工转 cookie 格式：cookies + localStorage + indexedDB 一次打包，是 Playwright 官方机制。爬虫 `new_context(storage_state=...)` 注入。cookie 失效时（页面出现登录墙），Web 端提示重跑导出脚本。

## 抓取流程

1. 读 influencers.yaml（空列表则跳过并在 UI 提示）。
2. 对每个博主**串行**：打开 `x.com/{handle}` → 等 `article[data-testid="tweet"]`（15s 超时）→ 滚动 3~5 次（随机 2-4s 间隔）→ 提取正文 `[data-testid="tweetText"]`、时间、互动数、status URL（取 post_id）。
3. 过滤：仅保留 48h 内且正文命中关注词（股票池 ticker、$ 符号、AI/chip/Fed/tariff 等）的帖子。
4. 入库：post_id 唯一键去重（增量抓取天然幂等）。**抓取时不调 LLM**。

## 防风控策略（按优先级）

1. 频率克制是核心：每博主每天最多 1 次（MySQL crawl_state 表记 last_crawl_at）；博主间随机 sleep 30~90s；全程单线程；单轮上限 20 人（settings 可配）。
2. 每博主只滚动 3~5 次，不深挖历史。
3. 异常识别：出现 "Something went wrong"/"Retry"/登录弹窗 → **立即终止本轮**并返回结构化错误（cookie 失效提示），不硬刚重试；网络类错误 tenacity 重试 2 次、间隔 5 分钟。
4. 可选增强：移动端 UA + viewport；每轮新建 context 不复用。

## 情绪打标（仅"全量分析"时触发）

对 x_posts 中最新未打标帖子（过滤后通常 ≤100 条）**批量一次调用** LLM（经 [analyzer/llm.py](../06-analyzer/provider.md) 统一出口），输出 `{post_id, sentiment -1/0/1, tickers_mentioned, note}` 列表，回填 x_posts，聚合进事件面情绪分（评分侧见 [05-scoring/event-score.md](../05-scoring/event-score.md)；打标调用见 [06-analyzer/calls.md](../06-analyzer/calls.md)）。
