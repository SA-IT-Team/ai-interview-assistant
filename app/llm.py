import json
from typing import List, Optional
from openai import AsyncOpenAI
from .config import get_settings
from .schemas import LlmResult, ResumeContext


SYSTEM_PROMPT = (
    "You are Saj, an AI interviewer from SA Technologies conducting a real-time screening interview. "
    "FLOW: After consent is given, ask 'Please introduce yourself focusing on your relevant experience.' "
    "Then ask adaptive, high-impact questions that are DYNAMICALLY GENERATED based on the candidate's previous answers. "
    "CRITICAL: Each question must be derived from what the candidate just said, not just from the resume. "
    "NEVER repeat a question that has already been asked. "
    "NEVER ask the same question twice, even if the candidate's answer was brief. "
    "Use the candidate's responses to: "
    "- Probe deeper into topics they mentioned (Why? How? Can you give an example? What was the outcome?) "
    "- Clarify vague statements or claims "
    "- Explore technical depth on skills/tools they discussed "
    "- Understand their problem-solving approach from examples they gave "
    "- Assess communication quality from how they structured their answers "
    "Ask follow-ups using the Socratic method to probe depth and verify understanding. "
    "Include exactly 1 behavioral question (e.g., 'Describe a time you disagreed with your manager and what you did'). "
    "If a response is unclear, ask for clarification once. If the candidate struggles twice on the same topic, move on. "
    "Keep questions concise (under 30 words), friendly, and natural. "
    "Avoid illegal/sensitive personal info (race, religion, age, marital status, pregnancy, health, politics, etc.). "
    "QUESTION COUNT: The number of questions should be DYNAMIC based on: "
    "- Signal quality: If you have strong signals (high scores, detailed answers) after 4-5 questions, you can end earlier. "
    "- Answer depth: If answers are shallow or unclear, ask more follow-ups. "
    "- Coverage: Ensure you've assessed technical skills, communication, problem-solving, and culture fit. "
    "End the interview when you have sufficient signals to make a confident evaluation (typically 4-8 questions, but adapt based on quality). "
    "EVALUATION: When ending, produce ONE evaluation object with EXACT schema: "
    '{"status": "completed|canceled", '
    '"resume_summary": "<short 1-2 sentence summary of the resume and interview>", '
    '"questions": [{"q": "<question text>", "a": "<candidate answer>"}], '
    '"evaluation": {'
    '"communication": 1-5, "technical": 1-5, "problem_solving": 1-5, "culture_fit": 1-5, '
    '"recommendation": "move_forward|hold|reject"'
    "}}. "
    "Always respond ONLY in JSON with keys: "
    "next_question, answer_score (1-5), rationale, red_flags (list), "
    "question_type (optional: intro|technical|behavioral|followup), "
    "end_interview (bool), final_summary (optional 2-4 sentence human-readable summary), "
    "final_json (optional evaluation object matching the schema above). "
    "Generate questions that are HIGH-IMPACT and INSIGHTFUL, not generic. "
    "Each question should help meaningfully assess skills, communication, problem-solving, and overall suitability. "
    "Use resume context as a starting point, but prioritize building on candidate responses for deeper evaluation."
)

GREETING_PROMPT = (
    "Generate a friendly, professional greeting introducing yourself as Saj (pronounced as a single name, not spelled out letter by letter) from SA Technologies. "
    "The greeting must include: 'Hi, I am Saj from SA Technologies. I will ask you some questions based on your profile. Shall we start?' "
    "Vary the wording, tone, and structure each time while keeping it natural and professional. "
    "You can add a brief personal touch or variation, but always include the core message. "
    "Return ONLY the greeting text, nothing else."
)


async def generate_greeting(candidate_name: Optional[str] = None) -> str:
    """
    Generate a varied greeting introducing SAJ from SA Technologies.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    user_prompt = GREETING_PROMPT
    if candidate_name:
        user_prompt += f"\n\nCandidate's name is {candidate_name}. You may personalize the greeting if appropriate."
    
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a professional AI assistant generating interview greetings."},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )
    greeting = resp.choices[0].message.content or "Hi, I am Saj from SA Technologies. I will ask you some questions based on your profile. Shall we start?"
    return greeting.strip()


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
    # Include full history for better context (not just last 3)
    history_summary = "\n".join(f"Q: {turn['q']}\nA: {turn['a']}\nScore: {turn.get('score','?')}" for turn in history)
    resume_text = (
        f"Name: {resume.name or 'Not provided'}\n"
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
    
    # Calculate signal quality metrics
    if history:
        avg_score = sum(turn.get('score', 3) for turn in history) / len(history)
        high_score_count = sum(1 for turn in history if turn.get('score', 3) >= 4)
        low_score_count = sum(1 for turn in history if turn.get('score', 3) <= 2)
        answer_lengths = [len(turn.get('a', '')) for turn in history]
        avg_answer_length = sum(answer_lengths) / len(answer_lengths) if answer_lengths else 0
    else:
        avg_score = 0
        high_score_count = 0
        low_score_count = 0
        avg_answer_length = 0
    
    # Dynamic question guidance based on signal quality
    signal_quality = "strong" if avg_score >= 4 and high_score_count >= 2 else "moderate" if avg_score >= 3 else "weak"
    flow_context = f"Has asked intro: {has_asked_intro}, Has asked behavioral: {has_asked_behavioral}, Question count: {question_count}, Signal quality: {signal_quality}, Avg score: {avg_score:.1f}"
    user_content = (
        f"Role: {role}\nLevel: {level}\n"
        f"Resume context:\n{resume_text}\n"
        f"Flow status: {flow_context}\n"
        f"Full conversation history:\n{history_summary or 'None'}\n"
        f"\n=== CRITICAL: CANDIDATE'S LATEST ANSWER ===\n"
        f"{transcript}\n"
        f"=== END LATEST ANSWER ===\n\n"
        f"IMPORTANT: The 'next_question' you generate MUST be a follow-up question based on what the candidate just said above. "
        f"Do NOT repeat any question from the conversation history. "
        f"Extract specific topics, projects, skills, or experiences mentioned in their latest answer and ask about those. "
        f"For example, if they mentioned 'AI chatbot project', ask about that project specifically. "
        f"If they mentioned '5.5 years of experience', ask about a specific challenging project from that experience. "
        f"If they mentioned 'generative AI', ask them to explain how they've used it or what challenges they faced. "
        f"\nSignal quality assessment: {signal_quality} (avg score: {avg_score:.1f}, high scores: {high_score_count}, low scores: {low_score_count}, avg answer length: {int(avg_answer_length)} chars)\n"
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



