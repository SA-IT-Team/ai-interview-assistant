import json
import logging
from typing import List, Optional
from openai import AsyncOpenAI
from .config import get_settings
from .schemas import LlmResult, ResumeContext

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are Saj, an AI interviewer from SA Technologies conducting a real-time screening interview. "
    "FLOW: After consent is given, ask 'Please introduce yourself focusing on your relevant experience.' "
    "Then ask adaptive, high-impact questions that are DYNAMICALLY GENERATED based on the candidate's previous answers. "
    "CRITICAL: Each question must be derived from what the candidate just said, not just from the resume. "
    "NEVER repeat a question that has already been asked. "
    "NEVER ask the same question twice, even if the candidate's answer was brief. "
    
    "RESPONSE QUALITY ASSESSMENT: You MUST evaluate whether the candidate's answer contains meaningful, substantive information. "
    "Consider the answer in context of the question asked. "
    "If the answer is non-informative (e.g., just 'Thank you', 'OK', 'Yes', 'No', or other filler responses that don't address the question), "
    "too brief to provide useful information, just repeating the question, or lacking substantive content, then: "
    "1. Set answer_score to 1 (lowest score) "
    "2. Add 'Response quality: Answer was non-informative or too brief' to red_flags "
    "3. Generate a clarification question in 'next_question' asking them to elaborate "
    "4. Set question_type to 'clarification' "
    "5. Do NOT generate follow-up questions based on non-informative responses - ask for clarification instead "
    "6. In your rationale, explain why the answer was insufficient "
    
    "COMPREHENSIVE RESUME VALIDATION: You MUST intelligently cross-check EVERY aspect of the candidate's spoken answers against their resume data. "
    "Use your semantic understanding to detect inconsistencies in: "
    "- Current employer/company name (e.g., resume says 'SA Technologies' but candidate says 'Infosys') "
    "- Job titles and roles (e.g., resume says 'Senior Engineer' but candidate says 'Junior Developer') "
    "- Skills and technologies (e.g., resume shows technical skills like Python/Java but candidate only mentions non-technical skills like 'communication') "
    "- Years of experience (e.g., resume says '5 years' but candidate says '2 years') "
    "- Projects and achievements (e.g., candidate claims projects not mentioned in resume) "
    "- Education and certifications (e.g., candidate mentions degree/certification not in resume) "
    "- Tools and frameworks (e.g., resume mentions React but candidate says they only know Angular) "
    "- Any other claims or statements that contradict resume data "
    "Be intelligent about variations (e.g., 'SA Tech' vs 'SA Technologies' might be the same, but 'Infosys' vs 'SA Technologies' is different). "
    "If you detect ANY inconsistency, you should: "
    "1. Add this to 'red_flags' list with a clear, specific description (e.g., 'Resume shows current company as SA Technologies but candidate said Infosys', "
    "   or 'Resume lists technical skills (Python, Java) but candidate only mentioned non-technical skills') "
    "2. Generate a clarifying follow-up question in 'next_question' that specifically addresses the inconsistency "
    "   (e.g., 'Your resume mentions you are currently at SA Technologies, but you mentioned Infosys. Could you clarify your current employment?', "
    "   or 'I see your resume highlights technical skills like Python and Java, but you mentioned non-technical skills. Could you tell me about your technical experience?') "
    "3. Set 'question_type' to 'clarification' "
    "4. Set answer_score to 2 (low score for inconsistency) "
    "5. In your rationale, explain the specific inconsistency detected "
    "6. Do NOT end the interview due to inconsistencies—ask for clarification first "
    
    "Use the candidate's responses to: "
    "- Probe deeper into topics they mentioned (Why? How? Can you give an example? What was the outcome?) "
    "- Clarify vague statements or claims "
    "- Explore technical depth on skills/tools they discussed "
    "- Understand their problem-solving approach from examples they gave "
    "- Assess communication quality from how they structured their answers "
    "- Verify consistency between spoken answers and resume data across ALL dimensions "
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
    "question_type (optional: intro|technical|behavioral|followup|clarification), "
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


async def prepare_llm_context(
    state: "SessionState",
    current_question: str,
    role: str,
    level: str,
    has_asked_intro: bool = False,
    has_asked_behavioral: bool = False,
    question_count: int = 0,
    followup_count: int = 0,
    force_new_topic: bool = False,
) -> dict:
    """
    Pre-compute LLM context while transcription is running.
    This allows parallel preparation to reduce latency.
    """
    # Prepare resume text (static, can be pre-computed)
    resume_text = (
        f"Name: {state.resume_context.name or 'Not provided'}\n"
        f"Summary: {state.resume_context.summary}\n"
        f"Roles: {', '.join(state.resume_context.roles)}\n"
        f"Skills: {', '.join(state.resume_context.skills)}\n"
        f"Tools: {', '.join(state.resume_context.tools)}\n"
        f"Projects: {', '.join(state.resume_context.projects)}\n"
        f"Education: {', '.join(state.resume_context.education)}\n"
        f"Certifications: {', '.join(state.resume_context.certifications)}\n"
        f"Achievements: {', '.join(state.resume_context.achievements)}\n"
        f"Claims: {', '.join(state.resume_context.claims)}\n"
        f"Experience years: {state.resume_context.experience_years}"
        if state.resume_context
        else "None provided"
    )
    
    # Prepare history summary (can be pre-computed)
    history_summary = "\n".join(
        f"Q: {turn['q']}\nA: {turn['a']}\nScore: {turn.get('score','?')}" 
        for turn in state.history
    )
    
    # Calculate signal quality metrics (can be pre-computed)
    if state.history:
        avg_score = sum(turn.get('score', 3) for turn in state.history) / len(state.history)
        high_score_count = sum(1 for turn in state.history if turn.get('score', 3) >= 4)
        low_score_count = sum(1 for turn in state.history if turn.get('score', 3) <= 2)
        answer_lengths = [len(turn.get('a', '')) for turn in state.history]
        avg_answer_length = sum(answer_lengths) / len(answer_lengths) if answer_lengths else 0
    else:
        avg_score = 0
        high_score_count = 0
        low_score_count = 0
        avg_answer_length = 0
    
    signal_quality = "strong" if avg_score >= 4 and high_score_count >= 2 else "moderate" if avg_score >= 3 else "weak"
    
    # Prepare follow-up instruction
    followup_instruction = ""
    if force_new_topic:
        followup_instruction = "\n\nCRITICAL: 3 follow-ups reached. Generate NEW question from resume, NOT followup."
    elif followup_count >= 2:
        followup_instruction = f"\n\nNOTE: {followup_count} follow-ups. After 3, move to new topic."
    
    return {
        "resume_text": resume_text,
        "history_summary": history_summary,
        "signal_quality": signal_quality,
        "avg_score": avg_score,
        "high_score_count": high_score_count,
        "low_score_count": low_score_count,
        "avg_answer_length": avg_answer_length,
        "role": role,
        "level": level,
        "has_asked_intro": has_asked_intro,
        "has_asked_behavioral": has_asked_behavioral,
        "question_count": question_count,
        "followup_count": followup_count,
        "followup_instruction": followup_instruction,
    }


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
    followup_count: int = 0,
    force_new_topic: bool = False,
    prepared_context: Optional[dict] = None,
    current_question: Optional[str] = None,
) -> LlmResult:
    """
    Call the LLM to grade the latest answer and generate the next question.
    History is a list of dicts with keys q, a, score.
    
    OPTIMIZATION: If prepared_context is provided, use it to skip redundant computation.
    """
    import time
    start_time = time.time()
    
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=15.0)  # Reduced timeout for faster failure
    
    # Use prepared context if available, otherwise compute it
    if prepared_context:
        resume_text = prepared_context["resume_text"]
        history_summary = prepared_context["history_summary"]
        signal_quality = prepared_context["signal_quality"]
        avg_score = prepared_context["avg_score"]
        high_score_count = prepared_context["high_score_count"]
        low_score_count = prepared_context["low_score_count"]
        avg_answer_length = prepared_context["avg_answer_length"]
        followup_instruction = prepared_context["followup_instruction"]
        flow_context = f"Intro: {prepared_context['has_asked_intro']}, Behavioral: {prepared_context['has_asked_behavioral']}, Q#{prepared_context['question_count']}, Follow-ups: {prepared_context['followup_count']}"
    else:
        # Fallback to original logic if not prepared
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
        
        signal_quality = "strong" if avg_score >= 4 and high_score_count >= 2 else "moderate" if avg_score >= 3 else "weak"
        flow_context = f"Intro: {has_asked_intro}, Behavioral: {has_asked_behavioral}, Q#{question_count}, Follow-ups: {followup_count}"
        
        # Add follow-up limit instruction
        followup_instruction = ""
        if force_new_topic:
            followup_instruction = "\n\nCRITICAL: 3 follow-ups reached. Generate NEW question from resume, NOT followup."
        elif followup_count >= 2:
            followup_instruction = f"\n\nNOTE: {followup_count} follow-ups. After 3, move to new topic."
    
    # OPTIMIZATION: Streamline user content (reduce token count for faster processing)
    # Truncate resume and history if too long
    resume_text_trimmed = resume_text[:800] + "..." if len(resume_text) > 800 else resume_text
    history_summary_trimmed = history_summary[-1200:] if len(history_summary) > 1200 else history_summary
    
    # Build comprehensive validation instructions
    current_q_context = f"\nQUESTION THAT WAS ASKED: {current_question}\n" if current_question else ""
    
    user_content = (
        f"Role: {role}\nLevel: {level}\n"
        f"\n=== RESUME DATA (for validation) ===\n"
        f"{resume_text_trimmed}\n"
        f"=== END RESUME ===\n\n"
        f"Flow status: {flow_context}\n"
        f"Conversation history:\n{history_summary_trimmed or 'None'}\n"
        f"\n=== CANDIDATE'S LATEST ANSWER ===\n{transcript}\n=== END ANSWER ===\n"
        f"{current_q_context}\n"
        f"CRITICAL VALIDATION TASKS (use your intelligence):\n\n"
        f"1. RESPONSE QUALITY: Assess if the answer contains meaningful information relevant to the question. "
        f"   - If non-informative (just 'Thank you', 'OK', etc.), set score=1 and ask for clarification\n"
        f"   - If too brief or lacks substance, set score=1-2 and ask for clarification\n"
        f"   - Only generate follow-up questions if answer contains substantive information\n\n"
        f"2. COMPREHENSIVE RESUME VALIDATION: Cross-check ALL aspects of the answer against resume data:\n"
        f"   - Company/Employer: Compare what candidate says vs. resume (be smart about variations)\n"
        f"   - Skills: Check if candidate mentions skills that match resume (technical vs non-technical, specific technologies)\n"
        f"   - Experience: Verify years of experience, job titles, roles match resume\n"
        f"   - Projects: Check if candidate mentions projects/achievements that align with resume\n"
        f"   - Technologies/Tools: Verify candidate's claims match resume's technical stack\n"
        f"   - Education/Certifications: Check if candidate mentions credentials that match resume\n"
        f"   - Any other claims that should be validated against resume data\n"
        f"   - If ANY inconsistency detected, flag it in red_flags and ask specific clarification question\n\n"
        f"3. CONTEXT AWARENESS: Consider the question asked - is the answer appropriate, complete, and consistent?\n\n"
        f"Generate your response with: "
        f"- answer_score: 1-5 based on answer quality, completeness, and consistency with resume "
        f"- rationale: Explain your assessment, including any quality issues or specific inconsistencies detected "
        f"- red_flags: List any issues found (response quality, specific resume inconsistencies with details) "
        f"- next_question: If answer is insufficient or inconsistent, ask specific clarification. If sufficient, generate intelligent follow-up. "
        f"- question_type: 'clarification' if asking for better answer or resolving inconsistency, otherwise appropriate type "
        f"\n{followup_instruction}"
        f"\nSignal quality: {signal_quality} (avg: {avg_score:.1f})\n"
        "Return JSON only."
    )
    
    prep_time = time.time() - start_time
    logger.info(f"LLM prep time: {prep_time:.2f}s")
    
    api_start = time.time()
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
        max_tokens=300,  # OPTIMIZATION: Limit response size for faster generation
    )
    api_time = time.time() - api_start
    total_time = time.time() - start_time
    logger.info(f"LLM API call: {api_time:.2f}s, Total LLM time: {total_time:.2f}s")
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



