import io
import json
from typing import Optional
from pypdf import PdfReader
from openai import AsyncOpenAI
from .config import get_settings

RESUME_SUMMARY_PROMPT = (
    "Extract key items from the resume text. "
    "Return JSON with keys: "
    "name (candidate's full name if available), "
    "summary (1-2 sentence summary), "
    "roles (list of job titles), "
    "skills (list of technical skills), "
    "tools (list of tools/frameworks/platforms), "
    "projects (list of project names or descriptions), "
    "education (list of degrees/institutions), "
    "certifications (list of certifications), "
    "achievements (list of notable achievements), "
    "experience_years (number), "
    "claims (list of notable assertions like 'reduced costs by 20%' or 'improved performance by X%'). "
    "Use concise strings. If unknown, leave empty or use empty list."
)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


async def summarize_resume(text: str) -> dict:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    # Clip overly long resumes
    trimmed = text[:12000]
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": RESUME_SUMMARY_PROMPT},
            {"role": "user", "content": trimmed},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)

