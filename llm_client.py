"""
Shared LLM client — singletons, config, and call helpers.
Imported by extraction.py, review.py, qa.py, and ingestion.py.
"""

import asyncio
import json
import logging
import os
import re

import httpx
from openai import AsyncOpenAI, OpenAI

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None

logger = logging.getLogger("legal_copilot")

# ── Config ────────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1:8b")
OLLAMA_CHAT_TIMEOUT = float(os.getenv("OLLAMA_CHAT_TIMEOUT", "300"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "60"))
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GOOGLE_GENAI_USE_VERTEXAI = (
    os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() in {"1", "true", "yes", "on"}
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _init_gemini_client():
    if LLM_PROVIDER != "gemini" or genai is None:
        return None
    try:
        if GOOGLE_GENAI_USE_VERTEXAI:
            if not GOOGLE_CLOUD_PROJECT:
                logger.warning(
                    "LLM_PROVIDER=gemini but GOOGLE_CLOUD_PROJECT not set; using local fallback"
                )
                return None
            return genai.Client(
                vertexai=True,
                project=GOOGLE_CLOUD_PROJECT,
                location=GOOGLE_CLOUD_LOCATION,
            )
        if GEMINI_API_KEY:
            return genai.Client(api_key=GEMINI_API_KEY)
        logger.warning("LLM_PROVIDER=gemini but no auth configured; using local fallback")
        return None
    except Exception:
        logger.exception("Failed to initialize Gemini client")
        return None


# ── Singletons ────────────────────────────────────────────────────────────────
gemini_client = _init_gemini_client()
openai_chat_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=OPENAI_API_KEY)
    if (LLM_PROVIDER == "openai" and OPENAI_API_KEY)
    else None
)
openai_embed_client: OpenAI | None = (
    OpenAI(api_key=OPENAI_API_KEY)
    if (LLM_PROVIDER == "openai" and OPENAI_API_KEY)
    else None
)


def llm_mode() -> str:
    if openai_chat_client:
        return f"openai:{OPENAI_MODEL}"
    if LLM_PROVIDER == "ollama":
        return f"ollama:{OLLAMA_CHAT_MODEL}"
    if gemini_client:
        return f"gemini:{GEMINI_MODEL}"
    return "local_fallback"


# ── Text utilities ─────────────────────────────────────────────────────────────

def normalize_for_match(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def resolve_chunk_for_quote(chunks: list[dict], quote: str | None) -> dict | None:
    if not chunks:
        return None
    q = normalize_for_match(quote)
    if not q:
        return None
    for c in chunks:
        if q in normalize_for_match(c.get("text")):
            return c
    return None


def extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return None
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ── LLM call helpers ──────────────────────────────────────────────────────────

async def ollama_chat_json(system: str, user: str) -> dict | None:
    try:
        timeout = httpx.Timeout(connect=10.0, read=OLLAMA_CHAT_TIMEOUT, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
            return json.loads(content)
    except Exception:
        logger.exception("Ollama JSON chat failed (model=%s)", OLLAMA_CHAT_MODEL)
        return None


async def gemini_chat_json(system: str, user: str) -> dict | None:
    if not gemini_client:
        return None
    prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user}"

    def _call() -> str:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        return (getattr(resp, "text", None) or "").strip()

    try:
        text = await asyncio.wait_for(asyncio.to_thread(_call), timeout=GEMINI_TIMEOUT)
        return extract_json_object(text)
    except asyncio.TimeoutError:
        logger.error(
            "Gemini JSON chat timed out after %ss (model=%s)", GEMINI_TIMEOUT, GEMINI_MODEL
        )
        return None
    except Exception:
        logger.exception("Gemini JSON chat failed (model=%s)", GEMINI_MODEL)
        return None


async def ollama_chat_text(messages: list[dict]) -> str:
    try:
        timeout = httpx.Timeout(connect=10.0, read=OLLAMA_CHAT_TIMEOUT, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "stream": False,
                    "messages": messages,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
    except Exception:
        logger.exception("Ollama text chat failed (model=%s)", OLLAMA_CHAT_MODEL)
        raise RuntimeError("Ollama chat failed")


async def gemini_chat_text(messages: list[dict]) -> str:
    if not gemini_client:
        raise RuntimeError("Gemini client not configured")
    prompt = "\n\n".join(
        f"{m.get('role', 'user').upper()}:\n{m.get('content', '')}" for m in messages
    )

    def _call() -> str:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"temperature": 0},
        )
        return (getattr(resp, "text", None) or "").strip()

    try:
        return await asyncio.wait_for(asyncio.to_thread(_call), timeout=GEMINI_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(
            "Gemini text chat timed out after %ss (model=%s)", GEMINI_TIMEOUT, GEMINI_MODEL
        )
        raise RuntimeError("Gemini chat timed out")
    except Exception:
        logger.exception("Gemini text chat failed (model=%s)", GEMINI_MODEL)
        raise RuntimeError("Gemini chat failed")
