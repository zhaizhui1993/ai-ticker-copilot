# ai-ticker-copilot

美股 AI 股票分析辅助系统：**四维评分 + 历史事件类比 + 准实时事件跟进**。

- 个人使用、本地运行、单用户；仅美股（USD）
- 输出建仓/加仓/观望/减仓信号 + 理由 + 风险 + 免责声明
- **辅助参考**：不自动下单、不接入券商、不构成投资建议

## 快速开始

```bash
# 0. 准备 MySQL 8（二选一）：
#    A. 复用本机已有实例：只需在 .env 填连接信息（建库建表由应用启动时自动完成）
#    B. Docker：docker compose up -d mysql
cp .env.example .env        # 填 LLM_* 与 FRED_API_KEY（MOCK_MODE=true 可无 key 跑通）
uv sync                     # 首次会自动安装 Python 3.13.9 与全部依赖
uv run python main.py       # 起 Web 面板 → http://127.0.0.1:8000
```

CLI 备选（后续阶段交付）：`scripts/refresh_data.py`、`scripts/analyze.py`。

## 填股票池

编辑 `config_files/stocks.yaml`（首次运行自动从 `.example` 复制），填入你关注的 AI 产业链美股。

## 文档

完整技术方案（模块化文档）见 [docs/](docs/README.md)：

- 总览与架构：[docs/01-overview/](docs/01-overview/README.md)
- 模块交互与接口契约：[docs/10-module-contracts.md](docs/10-module-contracts.md)
- 实施路线（P0–P9）：[docs/09-delivery/roadmap.md](docs/09-delivery/roadmap.md)

## 免责声明

本系统仅供个人研究参考，不构成投资建议。
