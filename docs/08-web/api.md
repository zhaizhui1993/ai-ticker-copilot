# 08-Web ｜ REST API 清单

> 模块：08 Web 面板 ｜ 成分：API 路由 ｜ 对应代码：web/api/ ｜ 实施阶段：P8
> 来源：原方案 §8.1

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/dashboard | 股票池卡片聚合：现价/涨跌/信号/总分/四维分/近 30 日信号序列/宏观仪表条/数据源状态 |
| GET | /api/stocks | 读取股票池 |
| PUT | /api/stocks | 保存股票池（校验 symbol 合法） |
| GET | /api/stocks/{symbol} | 个股详情：K 线（3M/6M/1Y）、四维分、基本面表、相关事件与类比 |
| GET | /api/events | 当前事件列表（按 scope 四类筛选）+ 各自的历史类比卡片 |
| GET | /api/events/poll?since= | 增量拉取新事件（前端 30s 轮询，驱动未读徽章与实时流） |
| GET | /api/calendar | 经济日历（FOMC/CPI/非农/财报日，未来 7 天） |
| GET | /api/events/lib | 历史事件库浏览（分页） |
| PUT | /api/events/lib | 用户新增历史事件（source='user'） |
| POST | /api/analysis/run | 触发分析；body `{refresh: bool}` 区分"用现有数据"与"刷新并分析"；返回 run 结果 |
| GET | /api/analysis/history | 历史分析记录（snapshots + analysis_runs） |
| GET | /api/config | 博主列表、评分权重、数据源状态（最近抓取时间、cookie 状态） |
| PUT | /api/config | 更新博主列表 / 权重 |
| GET | /api/x/posts | X 帖子流（按博主/股票筛选）+ 情绪分布聚合 |

全局：分析接口由 asyncio.Lock 串行化，重复提交返回 409（已有分析进行中）。
