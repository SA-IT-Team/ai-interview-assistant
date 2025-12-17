from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


class ResumeContext(BaseModel):
    summary: Optional[str] = None
    roles: List[str] = []
    skills: List[str] = []
    tools: List[str] = []
    projects: List[str] = []
    education: List[str] = []
    certifications: List[str] = []
    achievements: List[str] = []
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
    answer_score: int
    rationale: str
    red_flags: List[str] = []
    end_interview: bool = False
    final_summary: Optional[str] = None
    final_json: Optional[dict] = None
    question_type: Optional[str] = None  # "intro", "technical", "behavioral", "followup"


class SessionState(BaseModel):
    role: str
    level: str
    candidate_name: Optional[str] = None
    resume_context: Optional[ResumeContext] = None
    history: list = []
    question_count: int = 0
    has_asked_intro: bool = False
    has_asked_behavioral: bool = False
    interview_started_at: Optional[str] = None
    consent_given: bool = False



