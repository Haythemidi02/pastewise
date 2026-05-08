# backend/models.py
# Pydantic v2 schemas for every request body and response payload.

from pydantic import BaseModel, Field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ══════════════════════════════════════════════════════════════════════════════

class ExplainRequest(BaseModel):
    code: str = Field(..., description="Raw code text copied from the web.")
    mode: str = Field(
        default="quick",
        description="'quick' for a 3-sentence summary, 'deep' for line-by-line.",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "code": "const add = (a, b) => a + b;",
            "mode": "quick",
        }
    }}


class PasteEventRequest(BaseModel):
    read_first: bool = Field(
        default=False,
        description="True if the user read the explanation before pasting.",
    )
    snippet: Optional[str] = Field(
        default=None,
        description="First 120 chars of the pasted code (for dashboard history).",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Concept tags returned by the explain endpoint.",
    )


class ConfigUpdateRequest(BaseModel):
    api_key:    Optional[str] = None
    model:      Optional[str] = None
    max_tokens: Optional[int] = None
    provider:   Optional[str] = None
    cache:      Optional[bool] = None
    history:    Optional[bool] = None


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class ExplainResponse(BaseModel):
    summary:        str       = ""
    tags:           list[str] = []
    coverage_score: int       = 0       # 0–100
    language:       str       = "unknown"


class LineAnnotation(BaseModel):
    code:    str = ""
    comment: str = ""


class DeepDiveResponse(BaseModel):
    lines:    list[LineAnnotation] = []
    language: str                  = "unknown"


class ConceptCount(BaseModel):
    tag:   str
    count: int


class DailyCount(BaseModel):
    date:  str   # "YYYY-MM-DD"
    count: int


class StatsResponse(BaseModel):
    total_intercepts:  int                = 0
    read_before_paste: int                = 0
    total_concepts:    int                = 0
    streak_days:       int                = 0
    today_intercepts:  int                = 0
    today_read:        int                = 0
    top_concepts:      list[ConceptCount] = []
    active_days:       list[str]          = []   # ["YYYY-MM-DD", …]
    daily_counts:      list[DailyCount]   = []


class PasteRecord(BaseModel):
    snippet:    str       = ""
    tags:       list[str] = []
    read_first: bool      = False
    created_at: str       = ""   # ISO-8601 string


class RecentPastesResponse(BaseModel):
    pastes: list[PasteRecord] = []


class HealthResponse(BaseModel):
    status:  str = "ok"
    version: str = "1.0.0"


class ResetResponse(BaseModel):
    ok:      bool = True
    message: str  = ""