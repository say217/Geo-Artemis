"""
app7/routes.py  -  Geo Artemis AI Intelligence Terminal
Gemini 2.5 Flash-powered chat with JSON data context awareness.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# -----------------------------------------------------------------------------
#  Path Resolution
#  __file__ = .../Main/app7/routes.py
#  _HERE    = .../Main/app7/
#  _MAIN    = .../Main/
#  Target   = .../Main/app3/Glob_data/
# -----------------------------------------------------------------------------
_HERE  = Path(__file__).resolve().parent   # Main/app7/
_MAIN  = _HERE.parent                      # Main/

router    = APIRouter()
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# -----------------------------------------------------------------------------
#  Gemini Setup
# -----------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)

GEMINI_MODEL = "gemini-2.5-flash"

# -----------------------------------------------------------------------------
#  Data Source Config
# -----------------------------------------------------------------------------
EXCLUDED_FILES = {"events_earthquake.json"}  # Too large — excluded from context

# In-memory session store  {session_id: [{"role": ..., "content": ...}, ...]}
_chat_sessions: dict[str, list[dict]] = {}

# System prompt cache (built once on first request, refreshed on server restart)
_SYSTEM_PROMPT: str = ""


def _resolve_glob_dir() -> Path:
    """
    Find Main/app3/Glob_data/ regardless of the CWD uvicorn is launched from.
    Tries three candidates in priority order.
    """
    candidates = [
        _MAIN / "app3" / "Glob_data",                    # always correct (from __file__)
        Path.cwd() / "Main" / "app3" / "Glob_data",      # launched from project root
        Path.cwd() / "app3" / "Glob_data",               # launched from inside Main/
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]  # return authoritative path even if missing (error surfaces below)


def _load_glob_data() -> str:
    """
    Load every *.json in Glob_data/ except EXCLUDED_FILES.
    Each file is compacted and capped at 80 KB before injection into the prompt.
    """
    data_dir = _resolve_glob_dir()

    print(f"[App7/Intel] Glob_data path  -> {data_dir}")
    print(f"[App7/Intel] Path exists     -> {data_dir.exists()}")

    if not data_dir.exists():
        warning = (
            f"Glob_data directory not found at: {data_dir}. "
            "Ensure Main/app3/Glob_data/ exists and contains JSON files."
        )
        print(f"[App7/Intel] WARNING: {warning}")
        return warning

    json_files = sorted(
        f for f in data_dir.glob("*.json")
        if f.name not in EXCLUDED_FILES
    )
    print(f"[App7/Intel] Files to load   -> {[f.name for f in json_files]}")

    if not json_files:
        return f"No usable JSON files found in {data_dir} (after exclusions)."

    summaries: list[str] = []
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
            raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            if len(raw) > 80_000:
                raw = raw[:80_000] + "...[truncated - file too large]"
            summaries.append(f"### FILE: {json_file.name}\n{raw}")
            print(f"[App7/Intel] Loaded {json_file.name} ({len(raw):,} chars)")
        except json.JSONDecodeError as exc:
            summaries.append(f"### FILE: {json_file.name}\n[JSON parse error: {exc}]")
            print(f"[App7/Intel] JSON error in {json_file.name}: {exc}")
        except Exception as exc:
            summaries.append(f"### FILE: {json_file.name}\n[Read error: {exc}]")
            print(f"[App7/Intel] Error reading {json_file.name}: {exc}")

    return "\n\n".join(summaries)


def _build_system_prompt() -> str:
    data_context = _load_glob_data()

    # NOTE: keep this string clean — no example conversations, no stray text.
    # The f-string only interpolates {data_context}; all other braces must be
    # escaped as {{ }} if needed (there are none here).
    prompt = (
        "You are GEO-ARTEMIS INTEL, an advanced geospatial intelligence AI embedded "
        "in the Geo Artemis monitoring platform.\n"
        "You have access to real-time geospatial event data loaded from the platform's data store.\n"
        "Personality: precise, analytical, mission-critical. "
        "Use concise technical language. Never be verbose unless the user explicitly requests detail.\n"
        "You can answer questions about natural events, geographic patterns, satellite observations, "
        "and anything present in the loaded datasets below.\n\n"
        "=== LOADED GEOSPATIAL DATA ===\n"
        + data_context
        + "\n=== END OF DATA ===\n\n"
        "Rules:\n"
        "- Always cite the source filename when referencing data.\n"
        "- Format coordinates to 4 decimal places, magnitudes to 2 decimal places.\n"
        "- If asked about earthquakes, note that events_earthquake.json is excluded due to size.\n"
        "- Use markdown tables or bullet lists only when they genuinely improve clarity.\n"
        "- Never fabricate data that is not present in the loaded files.\n"
        "- Never reproduce example conversations or prior chat turns in your replies.\n"
    )
    return prompt


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if not _SYSTEM_PROMPT:
        _SYSTEM_PROMPT = _build_system_prompt()
    return _SYSTEM_PROMPT


# -----------------------------------------------------------------------------
#  Pydantic Models
# -----------------------------------------------------------------------------
class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


class ClearSession(BaseModel):
    session_id: str


# -----------------------------------------------------------------------------
#  Routes
# -----------------------------------------------------------------------------
@router.get("/")
def home(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("home7.html", {"request": request})


@router.post("/chat")
async def chat(payload: ChatMessage):
    """
    Accept a user message, maintain per-session history, and return
    a Gemini 2.5 Flash response grounded in the geospatial data context.
    """
    if not GEMINI_API_KEY:
        return JSONResponse(
            status_code=500,
            content={"error": "GEMINI_API_KEY is not set. Add it to your .env file."},
        )

    session_id = payload.session_id or str(uuid.uuid4())
    if session_id not in _chat_sessions:
        _chat_sessions[session_id] = []

    history = _chat_sessions[session_id]

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=_get_system_prompt(),
        )

        # Rebuild Gemini-format history from stored messages
        gemini_history = [
            {"role": msg["role"], "parts": [msg["content"]]}
            for msg in history
        ]

        chat_session = model.start_chat(history=gemini_history)
        response = await chat_session.send_message_async(payload.message)
        reply = response.text

        # Persist exchange
        history.append({"role": "user",  "content": payload.message})
        history.append({"role": "model", "content": reply})

        # Cap at 40 entries (20 exchanges) to prevent unbounded memory growth
        if len(history) > 40:
            _chat_sessions[session_id] = history[-40:]

        return JSONResponse({"reply": reply, "session_id": session_id})

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Gemini API error: {exc}"},
        )


@router.post("/chat/clear")
async def clear_chat(payload: ClearSession):
    """Wipe a session's server-side chat history."""
    _chat_sessions.pop(payload.session_id, None)
    return JSONResponse({"status": "cleared"})


@router.get("/chat/sessions")
async def list_sessions():
    """Debug endpoint - active session IDs and message counts."""
    return JSONResponse({sid: len(msgs) for sid, msgs in _chat_sessions.items()})