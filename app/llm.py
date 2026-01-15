import asyncio
import json
import logging
from typing import List, Optional, AsyncIterator
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
    "TOPIC MANAGEMENT: You MUST distribute questions across multiple resume topics. "
    "After 3-4 questions on a single topic, you MUST transition to a new topic. "
    "Track which topics have been covered (skills, projects, roles, tools) and prioritize uncovered topics. "
    "Ensure coverage across dimensions: technical skills, projects/impact, problem-solving, and communication. "
    "When transitioning topics, explicitly select from uncovered resume topics to create a balanced interview. "
    "Do NOT get stuck asking multiple follow-ups on the same topic - move to new topics after 3-4 questions. "
    "DURATION & ENDING: The interview MUST run for 15-20 minutes. "
    "Do NOT end the interview early based on question count or signal quality alone. "
    "Continue asking relevant, probing questions until: "
    "- You have assessed technical skills in depth (multiple technical questions) "
    "- You have asked at least 1 behavioral question "
    "- You have explored problem-solving through examples "
    "- You have evaluated communication quality across multiple answers "
    "- The interview has run for at least 15 minutes "
    "ONLY set end_interview=True if ALL of the following are true: "
    "1. The interview has run for at least 15 minutes AND "
    "2. You have comprehensive signals across all dimensions (technical, behavioral, communication, problem-solving) AND "
    "3. You have asked sufficient questions to make a confident evaluation (typically 8-12+ questions) "
    "Otherwise, continue asking follow-up questions or explore new topics from the resume. "
    "The number of questions is not a limiting factor - focus on interview duration and signal quality. "
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
    
    # Build topic coverage context
    coverage_context = ""
    if force_new_topic and state.resume_context:
        # Initialize covered_dimensions if not already set
        if not state.covered_dimensions:
            state.covered_dimensions = {
                "skills": False,
                "projects": False,
                "impact": False,
                "problem_solving": False,
                "communication": False
            }
        
        # Identify uncovered topics
        all_topics = {
            "skills": state.resume_context.skills or [],
            "projects": state.resume_context.projects or [],
            "roles": state.resume_context.roles or [],
            "tools": state.resume_context.tools or [],
        }
        
        uncovered_topics = []
        for category, topics in all_topics.items():
            for topic in topics:
                if topic and topic not in state.covered_topics:
                    uncovered_topics.append(f"{category}: {topic}")
        
        covered_summary = ", ".join(state.covered_topics[:5]) if state.covered_topics else "None"
        uncovered_summary = ", ".join(uncovered_topics[:10]) if uncovered_topics else "None"
        
        coverage_context = f"""
TOPIC COVERAGE ANALYSIS:
- Topics already covered: {covered_summary}{"..." if len(state.covered_topics) > 5 else ""}
- Topics NOT yet covered: {uncovered_summary}{"..." if len(uncovered_topics) > 10 else ""}
- Dimension coverage: Skills={state.covered_dimensions.get('skills', False)}, Projects={state.covered_dimensions.get('projects', False)}, Impact={state.covered_dimensions.get('impact', False)}, Problem-solving={state.covered_dimensions.get('problem_solving', False)}

CRITICAL: Generate a NEW question from an UNCOVERED topic above. Do NOT ask about topics already covered.
Prioritize topics that fill coverage gaps in dimensions (skills, projects, impact, problem-solving).
"""
    
    # Prepare follow-up instruction
    max_questions_per_topic = getattr(state, 'max_questions_per_topic', 4)
    followup_instruction = ""
    if force_new_topic:
        followup_instruction = f"\n\n{coverage_context}\n\nCRITICAL: {max_questions_per_topic} questions reached on current topic. Generate NEW question from UNCOVERED resume topics, NOT a followup."
    elif followup_count >= 3:  # Warn at 3, enforce at 4
        followup_instruction = f"\n\nNOTE: {followup_count} follow-ups on current topic. After {max_questions_per_topic}, you MUST move to a new topic from the resume."
    
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
        "coverage_context": coverage_context,
        "covered_topics": getattr(state, 'covered_topics', []),
        "covered_dimensions": getattr(state, 'covered_dimensions', {}),
    }


async def interpret_consent(transcript: str, consent_question: str) -> str:
    """
    Use AI to intelligently interpret candidate's response to consent question.
    Optimized for speed with minimal tokens and fast timeout.
    Returns: "granted", "denied", or "unclear"
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=5.0)  # Fast timeout
    
    # Concise prompt for faster processing
    prompt = f"""Question: "{consent_question}"
Response: "{transcript}"

Interpret intent: granted/denied/unclear. Reply with one word only."""
    
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Interpret interview consent. Reply: granted, denied, or unclear. One word only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # Low temperature for consistency
            max_tokens=5,  # Minimal tokens for speed
        )
        result = resp.choices[0].message.content.strip().lower()
        
        # Fast validation
        if "granted" in result or result == "yes":
            logger.info(f"Consent: GRANTED - '{transcript[:30]}...'")
            return "granted"
        elif "denied" in result or result == "no":
            logger.info(f"Consent: DENIED - '{transcript[:30]}...'")
            return "denied"
        else:
            logger.info(f"Consent: UNCLEAR - '{transcript[:30]}...'")
            return "unclear"
    except Exception as e:
        logger.error(f"Error interpreting consent: {str(e)}, defaulting to 'unclear'")
        return "unclear"


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
    elapsed_time: float = 0.0,
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
        coverage_context = prepared_context.get("coverage_context", "")
        covered_topics = prepared_context.get("covered_topics", [])
        covered_dimensions = prepared_context.get("covered_dimensions", {})
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
        coverage_context = ""
        covered_topics = []
        covered_dimensions = {}
        if force_new_topic:
            followup_instruction = "\n\nCRITICAL: 4 follow-ups reached. Generate NEW question from resume, NOT followup."
        elif followup_count >= 3:
            followup_instruction = f"\n\nNOTE: {followup_count} follow-ups. After 4, move to new topic."
    
    # OPTIMIZATION: Streamline user content (reduce token count for faster processing)
    # Truncate resume and history if too long
    resume_text_trimmed = resume_text[:800] + "..." if len(resume_text) > 800 else resume_text
    history_summary_trimmed = history_summary[-1200:] if len(history_summary) > 1200 else history_summary
    
    # Build comprehensive validation instructions
    current_q_context = f"\nQUESTION THAT WAS ASKED: {current_question}\n" if current_question else ""
    
    # Calculate duration context for LLM
    MAX_INTERVIEW_DURATION = 20 * 60  # 20 minutes
    MIN_INTERVIEW_DURATION = 15 * 60  # 15 minutes
    remaining_time = max(0, MAX_INTERVIEW_DURATION - elapsed_time)
    time_until_min = max(0, MIN_INTERVIEW_DURATION - elapsed_time)
    
    duration_context = f"""
INTERVIEW DURATION CONTEXT:
- Current interview time: {elapsed_time/60:.1f} minutes
- Target duration: 15-20 minutes
- Minimum remaining: {time_until_min/60:.1f} minutes (must continue until at least 15 minutes)
- Maximum remaining: {remaining_time/60:.1f} minutes
- Continue asking questions until at least 15 minutes have elapsed
- Only end if you have comprehensive evaluation AND minimum duration (15 min) reached
- Do NOT end based on question count - focus on time and signal quality
"""
    
    # Add topic transition guidance when forcing new topic
    topic_transition_guidance = ""
    if force_new_topic:
        topic_transition_guidance = f"""
{coverage_context}

TOPIC TRANSITION REQUIRED:
You have asked {followup_count} questions on the current topic. You MUST now:
1. Select a NEW topic from the UNCOVERED topics listed above
2. Generate a question that explores a different dimension (skills, projects, impact, problem-solving)
3. Ensure the new topic is relevant to the role ({role}) and level ({level})
4. Do NOT return to topics already covered unless absolutely necessary for clarification

The goal is to create a well-distributed interview across multiple resume topics and dimensions.
"""
    
    user_content = (
        f"{duration_context}\n"
        f"{topic_transition_guidance}\n"
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


async def call_llm_streaming(
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
) -> AsyncIterator[str]:
    """
    Stream LLM response - yield question text as soon as it's generated,
    before scoring/analysis is complete.
    """
    import time
    start_time = time.time()
    
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=15.0)
    
    # Use prepared context if available
    if prepared_context:
        resume_text = prepared_context["resume_text"]
        history_summary = prepared_context["history_summary"]
        signal_quality = prepared_context["signal_quality"]
        avg_score = prepared_context["avg_score"]
        followup_instruction = prepared_context["followup_instruction"]
        flow_context = f"Intro: {prepared_context['has_asked_intro']}, Behavioral: {prepared_context['has_asked_behavioral']}, Q#{prepared_context['question_count']}, Follow-ups: {prepared_context['followup_count']}"
    else:
        history_summary = "\n".join(f"Q: {turn['q']}\nA: {turn['a']}\nScore: {turn.get('score','?')}" for turn in history)
        resume_text = (
            f"Name: {resume.name or 'Not provided'}\n"
            f"Summary: {resume.summary}\n"
            f"Roles: {', '.join(resume.roles)}\n"
            f"Skills: {', '.join(resume.skills)}\n"
            if resume else "None provided"
        )
        signal_quality = "moderate"
        avg_score = 3
        followup_instruction = ""
        flow_context = f"Intro: {has_asked_intro}, Behavioral: {has_asked_behavioral}, Q#{question_count}, Follow-ups: {followup_count}"
    
    resume_text_trimmed = resume_text[:800] + "..." if len(resume_text) > 800 else resume_text
    history_summary_trimmed = history_summary[-1200:] if len(history_summary) > 1200 else history_summary
    current_q_context = f"\nQUESTION THAT WAS ASKED: {current_question}\n" if current_question else ""
    
    user_content = (
        f"Role: {role}\nLevel: {level}\n"
        f"\n=== RESUME DATA ===\n{resume_text_trimmed}\n=== END RESUME ===\n\n"
        f"Flow status: {flow_context}\n"
        f"Conversation history:\n{history_summary_trimmed or 'None'}\n"
        f"\n=== CANDIDATE'S LATEST ANSWER ===\n{transcript}\n=== END ANSWER ===\n"
        f"{current_q_context}\n"
        f"Generate the next question. Return ONLY the question text, nothing else. "
        f"Keep it concise (under 30 words), friendly, and natural."
        f"{followup_instruction}"
    )
    
    try:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Saj, an AI interviewer. Generate the next interview question based on the candidate's answer. Return only the question text."},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            max_tokens=100,  # Minimal for question text only
            stream=True,
        )
        
        question_text = ""
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                question_text += content
                # Yield partial question as it's generated
                if len(question_text) > 20:  # Once we have enough context
                    yield question_text
        
        # Yield final question
        if question_text:
            yield question_text.strip()
            
    except Exception as e:
        logger.error(f"Streaming LLM failed: {str(e)}")
        yield "Can you tell me more about that?"


async def generate_speculative_questions(
    current_question: str,
    question_type: str,
    state,
    prepared_context: dict,
    call_llm_func
) -> List[str]:
    """
    Pre-generate likely follow-up questions based on current question type.
    These can be used if early reasoning confirms the direction.
    """
    if not current_question:
        return []
    
    # Generate 2-3 likely questions based on question type
    speculative_prompts = []
    
    if question_type == "intro" or "introduce" in current_question.lower():
        speculative_prompts = [
            "Generate a technical follow-up question about the candidate's experience",
            "Generate a question asking for a specific example from their work",
        ]
    elif question_type == "technical" or any(tech in current_question.lower() for tech in ["python", "java", "react", "system", "project"]):
        speculative_prompts = [
            "Generate a deeper technical question about challenges they faced",
            "Generate a question about how they solved a specific problem",
        ]
    else:
        speculative_prompts = [
            "Generate a follow-up question asking for more details",
            "Generate a clarification question",
        ]
    
    # Generate questions in parallel (limit to 2 for speed)
    tasks = []
    for prompt in speculative_prompts[:2]:
        # Create a simplified LLM call for speculative generation
        task = asyncio.create_task(
            _generate_single_question_async(prompt, current_question, state, prepared_context)
        )
        tasks.append(task)
    
    try:
        speculative_questions = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=2.0  # Fast timeout
        )
        return [q for q in speculative_questions if isinstance(q, str) and len(q) > 10]
    except asyncio.TimeoutError:
        logger.warning("Speculative question generation timed out")
        return []


async def _generate_single_question_async(
    prompt: str,
    current_question: str,
    state,
    prepared_context: dict
) -> str:
    """Helper to generate a single speculative question quickly."""
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=3.0)
    
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Generate a concise interview question (under 30 words). Return only the question."},
                {"role": "user", "content": f"{prompt}\n\nContext: Current question was: {current_question}"},
            ],
            temperature=0.6,
            max_tokens=50,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Speculative question generation failed: {str(e)}")
        return ""


async def validate_question_relevance(
    question: str,
    full_transcript: str,
    original_question: str
) -> dict:
    """
    Quick validation to check if a question is still relevant after full transcript.
    Returns: {"is_relevant": bool, "confidence": float}
    """
    # Simple heuristic: if full transcript is very different from partial, question might not be relevant
    # For now, return high confidence (we'll refine this)
    return {"is_relevant": True, "confidence": 0.8}



