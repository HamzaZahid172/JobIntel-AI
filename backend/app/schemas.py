from datetime import date
from pydantic import BaseModel, ConfigDict, Field

class ApplicationCreate(BaseModel):
    company: str
    role: str
    location: str = "Germany"
    url: str = ""
    status: str = "Applied"
    cv_version: str = "Data Engineer CV v3"
    match_score: float = Field(0, ge=0, le=100)
    applied_date: date = Field(default_factory=date.today)
    notes: str = ""

class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    match_score: float | None = Field(None, ge=0, le=100)

class ApplicationOut(ApplicationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int

class MatchRequest(BaseModel):
    cv_text: str
    job_description: str

class AssistantRequest(BaseModel):
    message: str
