from pydantic import BaseModel
from typing import Optional, List

class InterviewConfig(BaseModel):
    job_role: str
    resume_text: Optional[str] = None
    num_questions: int = 5

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: List[Message] = []
    job_role: str
    resume_text: Optional[str] = None

class TTSRequest(BaseModel):
    text: str

class EvaluationRequest(BaseModel):
    conversation_history: List[Message]
    job_role: str
