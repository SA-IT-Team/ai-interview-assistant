import openai
from typing import List
from app.config import OPENAI_API_KEY
from app.schemas import Message

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def get_interview_response(messages: List[Message], job_role: str, resume_text: str = None) -> str:
    system_prompt = f"""You are an expert technical interviewer conducting an interview for the position of {job_role}. 
Your role is to:
1. Ask relevant technical and behavioral questions
2. Follow up on candidate answers with probing questions
3. Keep the conversation professional and encouraging
4. Evaluate responses thoughtfully

{"The candidate's resume: " + resume_text if resume_text else ""}

Start by introducing yourself and asking the first question. Keep responses concise and natural."""

    formatted_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        formatted_messages.append({"role": msg.role, "content": msg.content})
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=formatted_messages,
        temperature=0.7,
        max_tokens=500
    )
    
    return response.choices[0].message.content

def generate_evaluation(messages: List[Message], job_role: str) -> str:
    conversation_text = "\n".join([f"{m.role}: {m.content}" for m in messages])
    
    eval_prompt = f"""Analyze this interview for a {job_role} position and provide a detailed evaluation:

{conversation_text}

Provide evaluation in this format:
## Overall Score: X/10

## Strengths
- [List key strengths]

## Areas for Improvement  
- [List areas to improve]

## Technical Assessment
[Evaluate technical knowledge]

## Communication Skills
[Evaluate communication]

## Recommendation
[Hire/Consider/Pass recommendation with reasoning]"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": eval_prompt}],
        temperature=0.5,
        max_tokens=1000
    )
    
    return response.choices[0].message.content
