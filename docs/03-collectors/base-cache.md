# 03-采集 ｜ DataSource 协议与 TTL 缓存（base.py）

> 模块：03 数据采集层 ｜ 成分：采集基座 ｜ 对应代码：collectors/base.py ｜ 实施阶段：P3
> 来源：原方案 §6.4（TTL 缓存条目）+ §10.2① 契约

## DataSource 协议

所有采集源实现统一协议（签名详见 [10-module-contracts.md §10.2①](../10-module-contracts.md)）：

```python
class DataSource(Protocol):
    name: str                                   # 数据源标识（状态页/日志用）
```

- 采集层返回**原始/半成品数据**，不做 LLM 调用、不写业务表；
- mock.py 实现同一组接口，`MOCK_MODE=true` 时全链路切换零成本；
- 接口语义：`get_daily_bars` 只返 OHLCV（MA/RSI/ATR/量比由消费方自算，采集层不预置指标）。

## TTL 两级缓存（@ttl_cache）

- 内存 dict + 磁盘 pickle（data/cache/）两级；**TTL 过期后重新拉取，异常直接上抛**（由调用方按 §10.5 降级协议处理，当前无"读旧值标注陈旧"的自动回退）；
- TTL 约定（分级）：行情/体制层 15min、financials/earnings 12h、事件窗口取数（bars_range）24h、FRED 12h；**X 不走缓存 TTL**——每博主每天 1 次的节流在 crawl_state 表（DB 锁，见 [x-api.md](x-api.md)）；**事件管道不依赖缓存**（增量去重本身防重）。

## 重试与防限频

- yfinance 调用：串行 + 0.5~1s 随机 sleep + tenacity 指数退避重试 2 次（2~30s），**避免高频调 `.info`**；
- `@network_retry`（tenacity）只重试网络类错误；业务类错误（429/登录墙/HTTP 401、403）直接上抛，由调用方按 [10-module-contracts.md §10.5](../10-module-contracts.md) 降级协议处理（对应维度计中性分并标注"数据缺失"）。
