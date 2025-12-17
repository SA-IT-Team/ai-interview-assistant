import json
from typing import List, Optional
from openai import AsyncOpenAI
from .config import get_settings
from .schemas import LlmResult, ResumeContext


SYSTEM_PROMPT = (
    "You are a real-time automated screening interviewer conducting a natural conversation. "
    "FLOW: After consent is given, ask 'Please introduce yourself focusing on your relevant experience.' "
    "Then ask 3-6 resume-based questions targeting: specific skills listed, tools mentioned, achievements/claims, project details. "
    "Ask follow-ups using Socratic method (Why? How? Can you give an example?) to probe depth. "
    "Include exactly 1 behavioral question (e.g., 'Describe a time you disagreed with your manager and what you did'). "
    "Keep questions concise (under 30 words), friendly, natural. "
    "If candidate struggles twice on same topic, smoothly move to next question. "
    "Avoid illegal/sensitive personal info (race, religion, age, marital status, etc.). "
    "After 3-6 technical questions + 1 behavioral, end with 'Thank you for your time.' "
    "EVALUATION: When ending, produce JSON with exact schema: "
    '{"status": "completed|canceled", "questions_and_answers": [{"q": str, "a": str}], '
    '"scores": {"communication": 1-5, "technical": 1-5, "problem_solving": 1-5, "culture_fit": 1-5}, '
    '"recommendation": "move_forward|hold|reject"}. '
    "Always respond ONLY in JSON with keys: "
    "next_question, answer_score (1-5), rationale, red_flags (list), question_type (optional: intro|technical|behavioral|followup), "
    "end_interview (bool), final_summary (optional 2-4 sentence human summary), final_json (optional evaluation object). "
    "Generate resume-specific questions from: skills, tools, projects, achievements, claims. "
    "For claims like 'reduced costs by 20%', ask how and what measurements were used."
)


async def call_llm(
    role: str,
    level: str,
    history: List[dict],
    transcript: str,
    resume: Optional[ResumeContext],
    has_asked_intro: bool = False,
    has_asked_behavioral: bool = False,
    question_count: int = 0,
) -> LlmResult:
    """
    Call the LLM to grade the latest answer and generate the next question.
    History is a list of dicts with keys q, a, score.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    # Keep a short, structured conversation context
    history_summary = "\n".join(f"Q: {turn['q']}\nA: {turn['a']}\nScore: {turn.get('score','?')}" for turn in history[-3:])
    resume_text = (
        f"Summary: {resume.summary}\n"
        f"Roles: {', '.join(resume.roles)}\n"
        f"Skills: {', '.join(resume.skills)}\n"
        f"Tools: {', '.join(resume.tools)}\n"
        f"Projects: {', '.join(resume.projects)}\n"
        f"Education: {', '.join(resume.education)}\n"
        f"Certifications: {', '.join(resume.certifications)}\n"
        f"Achievements: {', '.join(resume.achievements)}\n"
        f"Claims: {', '.join(resume.claims)}\n"
        f"Experience years: {resume.experience_years}"
        if resume
        else "None provided"
    )
    remaining = max(0, 8 - question_count)  # Allow up to 8 questions total
    flow_context = f"Has asked intro: {has_asked_intro}, Has asked behavioral: {has_asked_behavioral}, Question count: {question_count}"
    user_content = (
        f"Role: {role}\nLevel: {level}\n"
        f"Resume context:\n{resume_text}\n"
        f"Flow status: {flow_context}\n"
        f"Recent turns ({remaining} questions remaining):\n{history_summary or 'None'}\n"
        f"Candidate's latest answer:\n{transcript}\n"
        "Return JSON only."
    )
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    parsed = {
        "next_question": parsed.get("next_question") or "Please share more about your recent work.",
        "answer_score": parsed.get("answer_score") or 3,
        "rationale": parsed.get("rationale") or "Not provided",
        "red_flags": parsed.get("red_flags") or [],
        "end_interview": bool(parsed.get("end_interview")) if parsed.get("end_interview") is not None else False,
        "final_summary": parsed.get("final_summary"),
        "final_json": parsed.get("final_json"),
        "question_type": parsed.get("question_type"),
    }
    return LlmResult(**parsed)



