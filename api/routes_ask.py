"""
hormuz_watch/api/routes_ask.py

"Ask HormuzWatch" — the Layer 6 RAG assistant exposed over the API.
JWT-gated and rate-limited like every other data endpoint.
"""

import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import get_current_user
from .models import User
from .rate_limit import check_rate_limit

sys.path.insert(0, str(Path(__file__).parent.parent / "genai"))

router = APIRouter(prefix="/ask", tags=["ask"])


def _guard(current_user: User = Depends(get_current_user)) -> User:
    check_rate_limit(str(current_user.id), current_user.tier)
    return current_user


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


@router.post("")
def ask(payload: AskRequest, current_user: User = Depends(_guard)) -> Dict[str, Any]:
    from rag import answer, is_configured  # local import — genai/ pulls in google-genai lazily

    if not is_configured():
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured — Ask HormuzWatch is unavailable")

    result = answer(payload.question)
    return {
        "question": result["question"],
        "answer": result["answer"],
        "sources": [
            {"source": d["source"], "date": d.get("date"), "url": d.get("url"), "similarity": d["similarity"]}
            for d in result["retrieved_documents"]
        ],
    }
