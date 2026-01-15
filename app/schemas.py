from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


class ResumeContext(BaseModel):
    """
    Parsed resume summary used to drive interview questions.
    """
    name: Optional[str] = None
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
    """
    Initial WebSocket start payload from the frontend.
    """
    role: str
    level: str
    candidate_name: Optional[str] = None
    initial_question: Optional[str] = None
    resume_context: Optional[ResumeContext] = None


class AnswerPayload(BaseModel):
    """
    Audio answer frame from the frontend (base64-encoded audio).
    """
    audio_base64: str
    mime_type: str = "audio/webm"


class QaItem(BaseModel):
    """
    Single question/answer pair for the final JSON payload.
    """
    q: str
    a: str


class EvaluationScores(BaseModel):
    """
    Final evaluation scores for the simplified JSON schema.
    """
    communication: int
    technical: int
    problem_solving: int
    culture_fit: int
    recommendation: str  # "move_forward" | "hold" | "reject"


class FinalEvaluation(BaseModel):
    """
    Top-level evaluation object returned at the end of the interview.
    """
    status: str  # "completed" | "canceled"
    resume_summary: Optional[str] = None
    questions: List[QaItem] = []
    evaluation: EvaluationScores


class LlmResult(BaseModel):
    """
    Normalised result from the LLM per turn.
    """
    next_question: str
    answer_score: int
    rationale: str
    red_flags: List[str] = []
    end_interview: bool = False
    # Optional fields for when the LLM decides to end the interview.
    final_summary: Optional[str] = None
    final_json: Optional[dict] = None  # Expected to conform to FinalEvaluation
    # Flow control metadata
    question_type: Optional[str] = None  # "intro", "technical", "behavioral", "followup"


class SessionState(BaseModel):
    """
    Server-side state for a single interview session.
    """
    role: str
    level: str
    candidate_name: Optional[str] = None
    resume_context: Optional[ResumeContext] = None
    # Turn-level history: list of dicts with keys q, a, score, type
    history: list = []
    question_count: int = 0
    has_asked_intro: bool = False
    has_asked_behavioral: bool = False
    # Simple counters for clarification / struggle tracking (used by flow logic)
    clarification_attempts: int = 0
    struggle_streak: int = 0
    # Follow-up tracking: prevent getting stuck on same topic
    current_topic: Optional[str] = None  # Current topic being discussed
    followup_count: int = 0  # Number of consecutive follow-ups on current_topic
    # Clarification depth tracking: prevent infinite clarification loops
    clarification_depth: int = 0  # Track consecutive clarifications on same topic
    last_clarification_topic: Optional[str] = None  # Track what we're clarifying
    # Topic coverage tracking: prevent getting stuck on single topic
    covered_topics: List[str] = []  # List of resume topics (skills, projects, roles, tools) that have been discussed
    covered_dimensions: dict = {}  # Track which interview dimensions have been covered
    max_questions_per_topic: int = 4  # Configurable limit (3-4 questions per topic)
    # Timestamps / flags
    interview_started_at: Optional[str] = None
    interview_start_time: Optional[float] = None  # Unix timestamp for duration tracking
    consent_given: bool = False



