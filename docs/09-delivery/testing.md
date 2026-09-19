# 09-交付 ｜ 验证方案

> 模块：09 交付与运维 ｜ 成分：测试与验证 ｜ 对应代码：tests/ ｜ 实施阶段：各阶段 + P9
> 来源：原方案 §12

## 12.1 Mock 路径（无网、无 key、无 LLM）

`MOCK_MODE=true` → 采集全部走 mock.py（读 tests/fixtures 静态 JSON），分析走 MockAnalyzer 返回固定 AnalysisResult。验证完整链路：数据→评分→事件匹配→信号→MySQL 落库→Web 展示（需 MySQL 实例在跑）。pytest 基于同一套 fixtures。

## 12.2 真实路径（分步渐进）

1. 填 LLM_API_KEY（含 LLM_BASE_URL / LLM_MODEL）+ FRED_API_KEY；
2. `refresh_data.py --scope market` 看行情 → `--scope macro` 看 FRED；
3. `analyze.py --ticker NVDA` 看完整报告；
4. `uv run python main.py` 起服务，浏览器走一遍全流程；
5. 次日二次运行：验证快照历史折线、同日重复分析不重复调 LLM。

## 12.3 前端验证

断网加载页面验证 vendor 本地化；mock 数据固定，图表渲染可反复对照。

## 12.4 测试清单（tests/）

| 文件 | 覆盖 |
|---|---|
| test_config.py | 空池提示、非法 symbol、权重合计校验、模板复制 |
| test_storage.py | 快照 UPSERT 覆盖、事件 CRUD、帖子去重、日志追加（需可用 MySQL 实例，无实例时自动 skip；其余测试不依赖 DB） |
| test_scoring.py | 四维分数方向与区间（构造边界数据）、权重生效、分档正确 |
| test_matcher.py | 硬检索排序、top-K、LLM 降级路径、类比聚合计算 |
| test_crawler.py | 帖子过滤规则、去重、节流判断（不真打 X） |
