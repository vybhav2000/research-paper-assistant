from __future__ import annotations

from fastapi import HTTPException
from openai import OpenAI

from app.config import get_settings


def get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is missing in .env")
    return OpenAI(api_key=settings.openai_api_key)
