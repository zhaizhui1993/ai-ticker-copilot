# 03-采集 ｜ 宏观采集（macro.py）

> 模块：03 数据采集层 ｜ 成分：FRED 宏观源 ｜ 对应代码：collectors/macro.py ｜ 实施阶段：P3
> 来源：原方案 §6.1① 系列 + v1.1 扩充

## 职责

FRED 官方 API（fred-py-api，免费 key，120 req/min）拉取宏观系列，接口 `get_series(series_id) -> MacroPoint`：

| 系列 id | 指标 | 用途 |
|---|---|---|
| FEDFUNDS | 联邦基金利率 | 宏观分（子权重 30%） |
| DGS10 | 十年期收益率 | 宏观分（15%） |
| T10Y2Y | 期限利差 | 宏观分（15%） |
| CPIAUCSL | CPI | 宏观分（20%） |
| UNRATE | 失业率 | 宏观分（10%） |
| PCEPILFE（v1.1 新增） | 核心 PCE（美联储真正盯的通胀指标） | 宏观分参考输入 / LLM 原始上下文 |
| BAMLH0A0HYM2（v1.1 新增） | 高收益债利差 OAS | 风险偏好环境变量 / LLM 原始上下文 |

## 约定

- TTL 12h（日频数据，高频无意义）；
- 系列 id 可在 settings 配置，评分规则表见 [05-scoring/macro-score.md](../05-scoring/macro-score.md)；
- key 未填/失败：宏观分降级中性并标注"宏观数据缺失"（降级协议见 [10-module-contracts §10.5](../10-module-contracts.md)）。
