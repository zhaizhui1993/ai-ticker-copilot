# 06-LLM ｜ 模型接入要点（供应商无关）

> 模块：06 LLM 研判层 ｜ 成分：模型接入 ｜ 对应代码：analyzer/llm.py ｜ 实施阶段：P6
> 来源：原方案 §9.1；v1.2 起供应商无关化——不绑定任何厂商，任意 OpenAI 兼容大模型可切换

## 接入方式

`ChatOpenAI(openai_api_base=settings.llm_base_url, model=settings.llm_model, api_key=settings.llm_api_key)`——凡兼容 OpenAI Chat Completions 协议的服务均可接入（GPT / Qwen / GLM / Kimi / DeepSeek / Claude 兼容网关等）。

**换供应商 = 改 .env 三项（`LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`），代码零改动。**所有 LLM 请求经 analyzer/llm.py 的 `_chat()` 发起（抽取/精排/研判/对话四类调用共用，全系统唯一出口，见 [10-module-contracts.md §10.2④](../10-module-contracts.md)），这是可移植性的结构保证。`llm_available()` 统一判断 key 是否已配置。

## 结构化输出

- **硬编码 `with_structured_output(method="function_calling")`**（抽取/精排/研判三处一致）：这是 OpenAI 兼容端点之间兼容性最好的方式——部分供应商不支持 `response_format: json_schema`，直用默认 method 会 422。
- 若已确认所选模型支持原生结构化输出（json_schema/json_mode），需改 llm.py 三处 method 换取更严格的格式约束（当前无 settings 开关）；**默认保持 function_calling 以保证跨供应商可移植**。对话调用（chat）不走结构化输出，返回纯文本。

## 配置与成本

- 模型名不预置默认值，`.env` 必填 `LLM_MODEL`；temperature 默认 0.3。
- 成本参考基准：单次分析约 12k in + 2k out tokens（以 DeepSeek 计价约 ¥0.02/次、月 <¥1）；换用其他模型按其计价重估，token 用量与调用次数不变。
- 控成本三手段（与供应商无关）：不引 embedding、事件抽取批量单次调用（情绪打标批量调用随该管线规划）、同日重复分析直接返回快照。

## 降级

LLM 不可用（未配置 key/超时/422/限频）→ 分数照常产出、事件抽取降级规则版、精排降级规则版、judge 降级 rule_judge 按分档直接给倾向并标注"LLM 降级"（统一协议见 [10-module-contracts.md §10.5](../10-module-contracts.md)）。**唯一例外**：研究助理对话强依赖 LLM——未配置 key 时抛 `LLMNotConfigured`，Web 层转 503，不做降级（见 [README.md](README.md) 对话一节）。
