# 产业研究与评分（v1.4）

分析编排预取股票所在完整篮子及 SPY 行情、篮子财务，再传入 IndustryScorer；不再仅传当前股票。

| segment | 研究篮子 |
|---|---|
| gpu | NVDA / AMD |
| custom_interconnect | MRVL / AVGO |
| optical | LITE / COHR |
| turnaround | INTC |
| energy_infra | BE |
| cloud | MSFT / GOOGL / AMZN |
| foundry / equipment / software / power / etf | 保留原篮子映射 |

单成员篮子必须理解为个股代理，不能当作独立产业确认。
当前子项是相对强弱40%、营收中位数30%、AI词频30%；词频未接入，缺失显式标注与归一化。相对强弱需要 21/63 个交易日区间；采集接口 window 表示日线根数，使用更长自然日请求窗口。

上述指标是市场动量和营收代理，不能冒充订单/交付/良率/资本开支景气。AI资本开支传导、客户集中度、利润兑现仍待证据模块建设，见 [修订方案](../11-ai-investment-revision.md)。
