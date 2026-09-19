"""chat 路由：多轮对话（基于系统数据）。

会话状态在客户端（前端持历史随请求带回）；服务端截断最近 20 轮。
LLM 未配置 → 503 + .env 指引（对话是全系统唯一强依赖 LLM 的功能）。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=60)


@router.post("/api/chat")
def chat(body: ChatIn) -> dict:
    from analyzer.chat import LLMNotConfigured, chat as do_chat
    try:
        reply = do_chat([m.model_dump() for m in body.messages])
        return {"reply": reply, "disclaimer": "本对话仅供个人研究参考，不构成投资建议。"}
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败（可重试）：{exc}")
