from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    email: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    target_roles: str | None = None
    target_locations: str | None = None


class ApplicationCreate(BaseModel):
    company: str
    role: str
    location: str = "Germany"
    url: str = ""
    status: str = "Applied"
    cv_version: str = "Current CV"
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


class ManualJobImport(BaseModel):
    source: str = "Manual"
    title: str
    company: str
    location: str = "Germany"
    url: str = ""
    description: str
    remote: bool = False


class BulkJobImport(BaseModel):
    jobs: list[ManualJobImport]


class CollectorTargetCreate(BaseModel):
    provider: str
    identifier: str
    label: str
    enabled: bool = True


class ApplicationPreparationRequest(BaseModel):
    minimum_match: float = Field(70, ge=0, le=100)
    cv_id: int | None = Field(None, gt=0)


class ApplicationPackageAnswerUpdate(BaseModel):
    answers: dict[str, str]

class ApprovedFollowupSend(BaseModel):
    recipient: str = Field(min_length=5, max_length=254)
    subject: str = Field(min_length=3, max_length=240)
    body: str = Field(min_length=10, max_length=12000)

class CandidateProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firstName: str = Field("", max_length=120)
    lastName: str = Field("", max_length=120)
    phone: str = Field("", max_length=80)
    city: str = Field("", max_length=120)
    country: str = Field("", max_length=120)
    linkedin: str = Field("", max_length=250)
    github: str = Field("", max_length=250)
    portfolio: str = Field("", max_length=250)
    education: str = Field("", max_length=1500)
    employment: str = Field("", max_length=4000)
    languages: str = Field("", max_length=500)

class CoverLetterDraft(BaseModel):
    text: str = Field(min_length=80, max_length=12000)


class InterviewAnswer(BaseModel):
    question_index: int = Field(ge=0,le=50)
    answer: str = Field(min_length=20,max_length=6000)
