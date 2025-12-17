import json
import time
from typing import List, Optional
from openai import AsyncOpenAI
from .config import get_settings
from .schemas import LlmResult, ResumeContext


SYSTEM_PROMPT = (
    "You are an automated screening interviewer. "
    "Process: greet and confirm start; ask for a brief self-introduction; ask 3-6 questions "
    "based on resume skills/roles/projects/claims with follow-ups; include 1 behavioral question; "
    "if a response is unclear, ask once for clarification; if the candidate struggles twice, move on; "
    "be concise, friendly, and keep each question under 30 words; avoid illegal/sensitive topics. "
    "When finishing, produce a short human-readable summary and a JSON evaluation object with schema: "
    "{\"status\": \"completed|canceled\", \"resume_summary\": str, "
    "\"questions\": [{\"q\": str, \"a\": str}], "
    "\"evaluation\": {\"communication\": 1-5, \"technical\": 1-5, \"problem_solving\": 1-5, "
    "\"culture_fit\": 1-5, \"recommendation\": \"move_forward|hold|reject\"}}. "
    "Always respond ONLY in JSON with keys: "
    "next_question, expected_response_length (\"short\" for yes/no/consent questions, \"medium\" for introductions/brief explanations, \"long\" for technical/behavioral questions), answer_score (1-5), rationale, red_flags (list of short strings), "
    "end_interview (bool), final_summary (optional string), final_json (optional object). "
    "Stop after the interviewer signals end_interview or after the 6th question."
)


async def call_llm(
    role: str,
    level: str,
    history: List[dict],
    transcript: str,
    resume: Optional[ResumeContext],
) -> LlmResult:
    """
    Call the LLM to grade the latest answer and generate the next question.
    History is a list of dicts with keys q, a, score.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    print(f"[LLM] Processing transcript: '{transcript[:100]}...' ({len(transcript)} chars)")
    start_time = time.time()
    
    # Keep a short, structured conversation context
    history_summary = "\n".join(f"Q: {turn['q']}\nA: {turn['a']}\nScore: {turn.get('score','?')}" for turn in history[-3:])
    resume_text = (
        f"Summary: {resume.summary}\nSkills: {', '.join(resume.skills)}\nRoles: {', '.join(resume.roles)}\n"
        f"Projects: {', '.join(resume.projects)}\nClaims: {', '.join(resume.claims)}\n"
        f"Experience years: {resume.experience_years}"
        if resume
        else "None provided"
    )
    remaining = max(0, 6 - len(history))
    user_content = (
        f"Role: {role}\nLevel: {level}\n"
        f"Resume context:\n{resume_text}\n"
        f"Recent turns ({remaining} turns remaining):\n{history_summary or 'None'}\n"
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
    
    elapsed = time.time() - start_time
    print(f"[LLM] Response received in {elapsed:.2f}s")
    
    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    parsed = {
        "next_question": parsed.get("next_question") or "Please share more about your recent work.",
        "expected_response_length": parsed.get("expected_response_length") or "medium",
        "answer_score": parsed.get("answer_score") or 3,
        "rationale": parsed.get("rationale") or "Not provided",
        "red_flags": parsed.get("red_flags") or [],
        "end_interview": bool(parsed.get("end_interview")) if parsed.get("end_interview") is not None else False,
        "final_summary": parsed.get("final_summary"),
        "final_json": parsed.get("final_json"),
    }
    
    print(f"[LLM] Next question: '{parsed['next_question'][:50]}...'")
    
    return LlmResult(**parsed)