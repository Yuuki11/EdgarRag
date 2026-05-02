"""Pydantic API contracts shared by FastAPI routes and the React client."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyYears(BaseModel):
    ticker: str
    name: str
    sector: str
    years: list[int]


class CompaniesResponse(BaseModel):
    companies: list[CompanyYears]


class Health(BaseModel):
    ollama_reachable: bool
    ollama_host: str
    ollama_model: str
    indexed_companies: int
    xbrl_cache_warm: bool
    compute_mode: str  # "cpu" when FINEDGAR_FORCE_CPU=1, else "auto"


class AdminMetric(BaseModel):
    label: str
    value: int | float | str | bool | None
    status: str = "neutral"
    detail: str | None = None


class AdminDataArtifact(BaseModel):
    name: str
    path: str
    present: bool
    files: int
    detail: str | None = None


class AdminAuthEvent(BaseModel):
    event_type: str
    email: str | None = None
    created_at: str


class AdminRuntime(BaseModel):
    environment: str
    release: str
    pod_name: str | None = None
    namespace: str | None = None
    node_name: str | None = None
    running_in_kubernetes: bool


class AdminOverview(BaseModel):
    generated_at: str
    runtime: AdminRuntime
    health: Health
    metrics: list[AdminMetric]
    data_artifacts: list[AdminDataArtifact]
    recent_auth_events: list[AdminAuthEvent]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    ticker: str | None = None
    years: list[int] | None = None
    conversation_id: str | None = None
    route_override: str | None = Field(
        default=None, description="Force 'xbrl', 'rag', or 'hybrid' (default: auto)"
    )


class Citation(BaseModel):
    index: int
    ticker: str | None = None
    year: int | None = None
    section: str | None = None
    doc_type: str | None = None
    fiscal_period: str | None = None
    snippet: str | None = None


class XbrlEvidence(BaseModel):
    concept: str | None = None
    value: float | str | None = None
    unit: str | None = None
    period: str | None = None
    accession: str | None = None
    form: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str | None = None
    message_id: str | None = None
    answer: str
    route: str
    operation: str
    ticker: str | None
    years: list[int]
    metrics: list[str]
    citations: list[Citation] = []
    xbrl_evidence: list[XbrlEvidence] = []
    latency_ms: float
    fallback_used: bool
    error: str = ""


class UserPublic(BaseModel):
    id: str
    email: str
    is_verified: bool


class AuthStatus(BaseModel):
    user: UserPublic | None = None


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)


class TokenRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=300)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=300)
    password: str = Field(..., min_length=12, max_length=256)


class MessageHistory(BaseModel):
    id: str
    role: str
    content: str
    ticker: str | None = None
    years: list[int] | None = None
    response: ChatResponse | None = None
    created_at: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationsResponse(BaseModel):
    conversations: list[ConversationSummary]


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=160)


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)


class ConversationMessagesResponse(BaseModel):
    conversation: ConversationSummary
    messages: list[MessageHistory]
