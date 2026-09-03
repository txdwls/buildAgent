"""OpenAI-compatible /v1/models endpoint.

Open WebUI and the OpenAI SDK probe this to populate the model picker.
The whitelist is `settings.openai_model` plus any comma-separated ids in
`OPENAI_EXTRA_MODELS`. Requests to /v1/chat/completions honor a `model`
field that matches this list; anything else falls back to the default.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from buildagent.api.dependencies import get_settings_dep
from buildagent.config import Settings

router = APIRouter()


@router.get("/v1/models")
async def list_models(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": "buildagent",
            }
            for model_id in settings.openai_model_whitelist
        ],
    }
