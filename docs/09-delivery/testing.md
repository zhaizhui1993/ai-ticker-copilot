# 09-交付 ｜ 验证方案

> 模块：09 交付与运维 ｜ 成分：测试与验证 ｜ 对应代码：tests/ ｜ 实施阶段：各阶段 + P9
> 来源：原方案 §12

跑测命令：`uv run pytest`（无 MySQL 时 DB 相关自动 skip，其余不依赖 DB/网络/key）。

## 12.1 Mock 路径（无网、无 key、无 LLM）

`MOCK_MODE=true` → 采集全部走 mock.py（**固定随机种子确定性生成**，不依赖 fixtures 文件；同样执行价格反应富化，与真实管道对齐），LLM 各调用走规则版降级（对话除外——chat 强依赖 LLM）。验证完整链路：数据→评分→事件匹配→信号→MySQL 落库→Web 展示（需 MySQL 实例在跑；mock 模式跳过同日幂等与落库）。pytest 测试均内联构造数据/monkeypatch，不依赖外部 fixtures。

## 12.2 真实路径（分步渐进）

1. 填 LLM_API_KEY（含 LLM_BASE_URL / LLM_MODEL）+ FRED_API_KEY；
2. `refresh_data.py --scope market|macro|news|all` 看行情/宏观/事件管道；
3. `crawl_x.py` 验证 X 采集（X_MODE=api 配 X_API_KEY，或 crawl 先跑 export_x_cookie.py）；
4. `analyze.py --ticker NVDA` 看完整报告；
5. `uv run python main.py` 起服务，浏览器走一遍全流程（含对话页签追问）；
6. 次日二次运行：验证快照历史、同日重复分析不重复调 LLM。

## 12.3 前端验证

断网加载页面验证 vendor 本地化；mock 数据固定，图表渲染可反复对照。

## 12.4 测试清单（tests/，14 个文件 / 84 条用例）

| 文件 | 条数 | 覆盖 |
|---|---|---|
| test_x_api.py | 15 | twitterapi.io 字段映射/引用拼接/翻页终止/userId 缓存/key 错误/单博主跳过/off 路由/节流入库编排 |
| test_config.py | 9 | 空池提示、非法 symbol、权重合计校验、模板复制 |
| test_crawler.py | 7 | 爬虫帖子过滤规则、去重、回复对象提取、节流判断（不真打 X） |
| test_technicals.py | 7 | 技术指标纯函数（sma/rsi/atr/量比/回撤/乖离/破位） |
| test_collectors.py | 6 | market/macro/news 采集器（含 news 管道与降级） |
| test_storage.py | 6 | 快照 UPSERT 覆盖、事件 CRUD 与种子 upsert、帖子去重、crawl_state 每日节流锁、日志追加（需可用 MySQL 实例，无实例自动 skip） |
| test_linkage.py | 6 | 联动层回填算法（回撤/达底/恢复/SPY/VIX 峰值） |
| test_scoring.py | 6 | 四维分数方向与区间（构造边界数据）、权重生效、分档正确 |
| test_matcher.py | 5 | 硬检索排序、top-K、LLM 降级路径、类比聚合计算 |
| test_mine.py | 5 | 回调波段挖掘（峰谷/幅度/开放波段/CSV 模式） |
| test_chat.py | 4 | 对话上下文组装（各块独立降级）、历史截断、LLM 未配置语义 |
| test_reaction.py | 4 | 价格反应口径（事件日截断/前趋势不含事件日/量比/降级） |
| test_e2e_mock.py | 2 | P9 端到端验收（mock 全链路：评分+信号+落库） |
| test_settings.py | 2 | 配置默认值与环境变量读取 |
