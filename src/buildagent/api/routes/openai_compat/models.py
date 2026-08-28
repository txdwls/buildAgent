"""OpenAI-compatible /v1/models endpoint.

Open WebUI and the OpenAI SDK probe this to populate the model picker. We
expose one model id, `MODEL_ID`, which downstream requests should also send
as `model` in /v1/chat/completions. The value the request carries is ignored
by the loop (the real model is chosen from settings), but a matching id here
keeps the UX from showing "no models".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

MODEL_ID = "buildagent"

router = APIRouter()


@router.get("/v1/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "buildagent",
            }
        ],
    }
