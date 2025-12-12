from typing import List, Optional
from pydantic import BaseModel


class ResumeContext(BaseModel):
    summary: Optional[str] = None
    roles: List[str] = []
    skills: List[str] = []
    projects: List[str] = []
    experience_years: Optional[float] = None
    claims: List[str] = []


class StartPayload(BaseModel):
    role: str
    level: str
    candidate_name: Optional[str] = None
    initial_question: Optional[str] = None
    resume_context: Optional[ResumeContext] = None


class AnswerPayload(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"


class LlmResult(BaseModel):
    next_question: str
    expected_response_length: str = "medium"
    answer_score: int
    rationale: str
    red_flags: List[str] = []
    end_interview: bool = False
    final_summary: Optional[str] = None
    final_json: Optional[dict] = None


class SessionState(BaseModel):
    role: str
    level: str
    candidate_name: Optional[str] = None
    resume_context: Optional[ResumeContext] = None
    history: list = []