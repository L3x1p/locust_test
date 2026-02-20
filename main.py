import re
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db, create_tables
from models import Message


def clean_model_output(text: str) -> str:
    """Убирает служебные токены vLLM и лишние переносы из ответа модели."""
    if not text:
        return ""
    # Служебные токены vLLM/chat-моделей
    text = re.sub(r"<\|im_end\|>\s*", "", text)
    text = re.sub(r"<\|im_start\|>\s*", "", text)
    text = re.sub(r"<\|[^|]+\|>\s*", "", text)  
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="Chat API", lifespan=lifespan)


class ChatRequest(BaseModel):
    content: str
    session_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    sid = body.session_id or str(uuid.uuid4())

    # Сохраняем сообщение пользователя
    user_msg = Message(session_id=sid, role="user", content=body.content.strip())
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Собираем историю для контекста (все сообщения сессии)
    history = (
        db.query(Message)
        .filter(Message.session_id == sid)
        .order_by(Message.created_at)
        .all()
    )
    messages_for_vllm = [
        {"role": m.role, "content": m.content}
        for m in history
    ]
    # Системный промпт: отвечать по теме запроса, не подменять другими темами
    system_prompt = (
        "Ты полезный помощник. Отвечай по теме сообщения пользователя. Отвечай только на русском языке. Отвечай кратко и понятно."
    )
    messages_for_vllm = [{"role": "system", "content": system_prompt}] + messages_for_vllm

    # Запрос к vLLM
    url = f"{settings.vllm_base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": settings.vllm_model,
        "messages": messages_for_vllm,
        "max_tokens": settings.vllm_max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {settings.vllm_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"vLLM request failed: {e}",
        )

    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise HTTPException(status_code=502, detail="vLLM returned no choices")
    assistant_content = (choices[0].get("message") or {}).get("content") or ""
    assistant_content = clean_model_output(assistant_content)

    # Сохраняем ответ модели
    assistant_msg = Message(
        session_id=sid,
        role="assistant",
        content=assistant_content,
    )
    db.add(assistant_msg)
    db.commit()

    return {
        "session_id": sid,
        "message": assistant_content,
    }


@app.get("/chat/{session_id}")
def get_chat_history(session_id: str, db: Session = Depends(get_db)):
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at)
        .all()
    )
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": clean_model_output(m.content) if m.role == "assistant" else m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }
