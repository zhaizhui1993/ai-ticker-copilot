"""对话功能测试：上下文打包、无 key 降级、端点路由（不真调 LLM）。"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_env(monkeypatch, tmp_path):
    from config import settings as settings_module
    monkeypatch.setattr(settings_module.settings, "mock_mode", True)
    monkeypatch.setattr(settings_module.settings, "cache_dir", str(tmp_path / "cache"))
    # 确保无 LLM key（测试降级路径）
    monkeypatch.setattr(settings_module.settings, "llm_api_key", "")
    monkeypatch.setattr(settings_module.settings, "llm_model", "")


def test_build_chat_context_grounded() -> None:
    from analyzer.chat import build_chat_context

    ctx = build_chat_context()
    assert "NVDA" in ctx["pool"]                       # 股票池入上下文
    assert ctx["lib_count"] == 43                      # 历史事件库摘要（v1.3 对照批次后）
    assert "2026-07-ai-valuation-pullback" in ctx["lib"]
    assert "LLM 未配置" in ctx["degraded"]             # 降级状态如实标注
    assert ("不可用" in ctx["events"]) or ("暂无" in ctx["events"]) or ("[" in ctx["events"])


def test_chat_without_llm_raises_structured() -> None:
    from analyzer.chat import LLMNotConfigured, chat

    with pytest.raises(LLMNotConfigured) as exc_info:
        chat([{"role": "user", "content": "为什么 NVDA 是 watch_add？"}])
    assert "LLM_API_KEY" in str(exc_info.value)        # 指引落点正确


def test_chat_empty_messages_rejected() -> None:
    from analyzer.chat import LLMNotConfigured, chat

    # 无 key 先触发 LLMNotConfigured；有 key 时空消息应 ValueError——这里验证前者
    with pytest.raises((LLMNotConfigured, ValueError)):
        chat([])


def test_chat_endpoint_wiring() -> None:
    from web.app import create_app

    client = TestClient(create_app())  # 不进入 lifespan（无 with）
    response = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert response.status_code == 503                  # 无 key → 503 + 指引
    assert "LLM_API_KEY" in response.json()["detail"]

    bad = client.post("/api/chat", json={"messages": []})
    assert bad.status_code == 422                       # 空消息校验拒绝
