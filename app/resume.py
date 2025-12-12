import io
import json
from typing import Optional
from pypdf import PdfReader
from openai import AsyncOpenAI
from .config import get_settings

RESUME_SUMMARY_PROMPT = (
    "Extract key items from the resume text. "
    "Return JSON with keys: summary (short), roles (list), skills (list), projects (list), experience_years (number), "
    "claims (list of notable assertions). Use concise bullet-like strings. If unknown, leave empty."
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

