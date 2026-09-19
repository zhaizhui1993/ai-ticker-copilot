# 05 ｜ 评分引擎（scoring/）

> **职责**：四维规则评分（宏观/事件/产业/公司）、技术面分层指标体系、体制层硬约束、加权汇总与信号分档——全系统可解释、可复现的分数锚点，LLM 不可用时仍可独立产出。
> **对应代码**：scoring/（macro_score / event_score / industry_score / company_score / engine）+ domain/scoring.py（ScoreBreakdown / FourDimScores） ｜ **依赖模块**：02（模型）、03（采集数据）、04（事件类比结果） ｜ **实施阶段**：P5
> **内容来源**：原方案 §6.1（含 §6.1.1 分层指标体系与汇总分档/体制层硬约束）

## 统一约定

每个维度统一产出 `ScoreBreakdown{score: 0-100, indicators: dict, rationale: str}`，rationale 由规则模板生成中文一句话（保证 LLM 不可用时分数本身可读）。所有规则参数集中在各 scorer 文件顶部常量区，便于调参。

Scorer 是**纯函数**（同输入同输出、无 IO、无 LLM）；体制层硬约束只在 Engine 施加，Scorer 不感知（契约见 [10-module-contracts.md §10.2③](../10-module-contracts.md)）。

## 成分文档

| 文档 | 对应代码 | 内容 | 权重 |
|---|---|---|---|
| [macro-score.md](macro-score.md) | scoring/macro_score.py | 宏观面：FRED 规则表 | 25% |
| [event-score.md](event-score.md) | scoring/event_score.py | 事件面：历史类比 80% + X 情绪 20% | 25% |
| [industry-score.md](industry-score.md) | scoring/industry_score.py | 产业面：相对强弱 + 财报动量 + AI 词频 | 25% |
| [company-score.md](company-score.md) | scoring/company_score.py | 公司面：成长/估值/质量/技术面 | 25% |
| [layered-technicals.md](layered-technicals.md) | 技术面子体系（v1.1） | 分层指标体系：体制/趋势/择时三层 | — |
| [engine.md](engine.md) | scoring/engine.py | 加权汇总、信号分档、体制层硬约束 | — |
