import io
import json
import logging
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from pypdf import PdfReader
from openai import AsyncOpenAI
from .config import get_settings

logger = logging.getLogger(__name__)

# Create a thread pool executor for CPU-bound tasks
_executor = ThreadPoolExecutor(max_workers=2)

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


def _extract_text_from_pdf_sync(file_bytes: bytes, request_id: str = "unknown") -> str:
    """Synchronous PDF extraction - runs in thread pool."""
    start_time = time.time()
    
    try:
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Extracting text from PDF: {len(file_bytes)} bytes")
        pdf = PdfReader(io.BytesIO(file_bytes))
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] PDF parsed: {len(pdf.pages)} pages")
        
        pages = []
        for i, page in enumerate(pdf.pages):
            page_start = time.time()
            try:
                page_text = page.extract_text() or ""
                pages.append(page_text)
                page_elapsed = time.time() - page_start
                logger.debug(f"[{request_id}] [{page_elapsed:.2f}s] Extracted {len(page_text)} characters from page {i+1}")
            except Exception as e:
                page_elapsed = time.time() - page_start
                logger.warning(f"[{request_id}] [{page_elapsed:.2f}s] Error extracting text from page {i+1}: {str(e)}")
                pages.append("")
        
        text = "\n".join(pages)
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Total extracted text length: {len(text)} characters")
        return text
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{request_id}] [{elapsed:.2f}s] Failed to extract text from PDF: {str(e)}", exc_info=True)
        raise ValueError(f"PDF extraction failed: {str(e)}")


async def extract_text_from_pdf(file_bytes: bytes, request_id: str = "unknown") -> str:
    """Extract text from PDF file bytes (async wrapper)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _extract_text_from_pdf_sync, file_bytes, request_id)


async def summarize_resume(text: str, request_id: str = "unknown") -> dict:
    """Summarize resume text using OpenAI API."""
    start_time = time.time()
    
    settings = get_settings()
    # Increase timeout to 60 seconds to match frontend and handle slower API responses
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)
    
    try:
        # Clip overly long resumes
        trimmed = text[:12000]
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Summarizing resume: {len(text)} chars (trimmed to {len(trimmed)})")
        
        # Wrap the API call in asyncio timeout as additional safety
        api_start = time.time()
        try:
            elapsed = time.time() - start_time
            logger.info(f"[{request_id}] [{elapsed:.2f}s] Making OpenAI API call...")
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": RESUME_SUMMARY_PROMPT},
                        {"role": "user", "content": trimmed},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                ),
                timeout=65.0  # Slightly longer than client timeout
            )
            api_elapsed = time.time() - api_start
            elapsed = time.time() - start_time
            logger.info(f"[{request_id}] [{elapsed:.2f}s] OpenAI API call completed (API took {api_elapsed:.2f}s)")
        except asyncio.TimeoutError:
            api_elapsed = time.time() - api_start
            elapsed = time.time() - start_time
            logger.error(f"[{request_id}] [{elapsed:.2f}s] OpenAI API call timed out after {api_elapsed:.2f}s (65s limit)")
            raise ValueError("Resume summarization timed out. Please try again.")
        
        elapsed = time.time() - start_time
        content = resp.choices[0].message.content or "{}"
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Received response from OpenAI: {len(content)} characters")
        
        parse_start = time.time()
        try:
            summary = json.loads(content)
            parse_elapsed = time.time() - parse_start
            elapsed = time.time() - start_time
            logger.info(f"[{request_id}] [{elapsed:.2f}s] Successfully parsed resume summary with keys: {list(summary.keys())} (parsing took {parse_elapsed:.2f}s)")
            return summary
        except json.JSONDecodeError as e:
            parse_elapsed = time.time() - parse_start
            elapsed = time.time() - start_time
            logger.error(f"[{request_id}] [{elapsed:.2f}s] Failed to parse JSON response: {str(e)} (parsing took {parse_elapsed:.2f}s)")
            logger.error(f"[{request_id}] Response content: {content[:500]}")
            # Return a default structure if JSON parsing fails
            return {
                "name": "",
                "summary": text[:200] if text else "Resume extracted but could not be summarized.",
                "roles": [],
                "skills": [],
                "tools": [],
                "projects": [],
                "education": [],
                "certifications": [],
                "achievements": [],
                "experience_years": 0,
                "claims": []
            }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{request_id}] [{elapsed:.2f}s] Failed to summarize resume: {str(e)}", exc_info=True)
        # Check if it's a timeout error
        error_str = str(e).lower()
        if "timeout" in error_str or "timed out" in error_str:
            logger.error(f"[{request_id}] [{elapsed:.2f}s] OpenAI API timeout - this may indicate network issues or API slowness")
            raise ValueError("Resume summarization timed out. Please try again.")
        raise

