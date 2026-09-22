# 03-采集 ｜ X 爬虫·crawl 通道（x_crawler.py）

> 模块：03 数据采集层 ｜ 成分：Playwright X 采集（X_MODE=crawl 通道） ｜ 对应代码：collectors/x_crawler.py、scripts/export_x_cookie.py、scripts/crawl_x.py ｜ 实施阶段：P7
> 来源：原方案 §6.3
>
> **双通道说明**：X 采集由 `X_MODE` 路由（api / crawl / off），路由与节流/入库编排在 collectors/x_source.py，接口与字段映射见 [x-api.md](x-api.md)。本文档只描述 Playwright 爬虫通道。

## 登录态

`scripts/export_x_cookie.py` 启动有头浏览器 → 用户手动登录 x.com（含二次验证）→ 轮询检测登录态 → `context.storage_state(path="data/x_state/state.json")` 保存。选 storage_state 而非手工转 cookie 格式：cookies + localStorage 一次打包，是 Playwright 官方机制。爬虫 `new_context(storage_state=...)` 注入。cookie 失效时（页面出现登录墙），Web 端提示重跑导出脚本，或改用 `X_MODE=api`（免登录态，见 [x-api.md](x-api.md)）。

## 抓取流程

1. 调用方（scheduler / scripts/crawl_x.py）经 config/loader.py 读 influencers.yaml（空列表则跳过并在 UI 提示），与股票池 ticker 一并传入。
2. 对每个博主**串行**，抓**两个页签**并按 post_id 去重合并：
   - `x.com/{handle}`（主页帖）
   - `x.com/{handle}/with_replies`（帖子 + **回复别人的内容**）
   每页：等待 `article[data-testid="tweet"]`（15s 超时）→ 滚动 3~5 次（随机 2-4s 间隔）→
   提取正文 `[data-testid="tweetText"]`、时间、status URL（取 post_id）、
   **回复对象 reply_to**（从 "Replying to @x" 上下文提取；自续帖视为原创，值为 NULL）。
   爬虫通道**不提取互动数**（likes 恒空）与被引推文原文——这两项是 API 通道（[x-api.md](x-api.md)）的增益。
3. 过滤：仅保留 48h 内且正文命中关注词（股票池 ticker、$ 符号、AI/chip/Fed/tariff 等）的帖子。
4. 入库：post_id 唯一键去重（增量抓取天然幂等）。**抓取时不调 LLM**。

## 防风控策略（按优先级）

1. 频率克制是核心：每博主每天最多 1 次（MySQL crawl_state 表记 last_crawl_at，**先拿锁再抓取**——抓取失败当日额度不退还）；博主间随机 sleep 30~90s；全程单线程；`MAX_X_BLOGGERS_PER_RUN`（默认 5）为单轮上限配置（当前按博主列表全量执行，截断逻辑预留）。
2. 每博主只滚动 3~5 次，不深挖历史。
3. 异常识别：出现 "Something went wrong"/"Retry"/登录弹窗 → **立即终止本轮**并返回结构化错误（cookie 失效提示），不硬刚重试。
4. 可选增强：移动端 UA + viewport；每轮新建 context 不复用。

## 情绪打标（规划；存储层就绪、LLM 打标未接线）

对 x_posts 中最新未打标帖子批量一次调用 LLM 的设计保留（`get_unlabeled_posts` / `mark_sentiment` 存储接口已就绪，见 [07-storage](../07-storage/README.md)），但 LLM 打标函数尚未实现——当前 pipeline 事件面评分的 X 情绪腿恒为中性（详见 [05-scoring/event-score.md](../05-scoring/event-score.md)；规划中的调用形态见 [06-analyzer/calls.md](../06-analyzer/calls.md)）。
