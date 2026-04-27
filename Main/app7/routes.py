"""
app7/routes.py  -  Geo Artemis AI Intelligence Terminal
Gemini 2.5 Flash-powered chat with JSON data context awareness.

Data loading strategy:
  - Each JSON file is serialised line-by-line (one JSON line per record/key).
  - Only the first MAX_LINES_PER_FILE lines are fed to the AI.
  - Lines are sampled with equal spacing (load-balanced) so the AI sees a
    representative spread across the whole file, not just the top.
  - Total context is further capped at MAX_TOTAL_LINES across all files.
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
# -----------------------------------------------------------------------------
_HERE  = Path(__file__).resolve().parent   # Main/app7/
_MAIN  = _HERE.parent                      # Main/

router    = APIRouter()
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# -----------------------------------------------------------------------------
#  Gemini API Keys — Primary + Fallback
# -----------------------------------------------------------------------------
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")

GEMINI_MODEL = "gemini-2.5-flash"

# -----------------------------------------------------------------------------
#  Data Source Config
# -----------------------------------------------------------------------------
EXCLUDED_FILES     = {"events_earthquake.json"}
MAX_LINES_PER_FILE = 200   # Hard cap: lines fed to AI per JSON file
MAX_TOTAL_LINES    = 800 # Hard cap: total lines across ALL files combined

_chat_sessions: dict[str, list[dict]] = {}
_SYSTEM_PROMPT: str = ""


def _resolve_glob_dir() -> Path:
    candidates = [
        _MAIN / "app3" / "Glob_data",
        Path.cwd() / "Main" / "app3" / "Glob_data",
        Path.cwd() / "app3" / "Glob_data",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _json_to_lines(data: object) -> list[str]:
    """
    Convert any parsed JSON value into a flat list of human-readable lines.

    Strategy by type:
      • list of dicts  → one compact JSON object per line (most common: event arrays)
      • list of others → one item per line
      • dict           → one "key: value" line per top-level key
      • scalar         → single line
    """
    if isinstance(data, list):
        lines: list[str] = []
        for item in data:
            if isinstance(item, dict):
                lines.append(json.dumps(item, separators=(",", ":"), ensure_ascii=False))
            else:
                lines.append(str(item))
        return lines

    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{k}: {json.dumps(v, separators=(',', ':'), ensure_ascii=False)}")
            else:
                lines.append(f"{k}: {v}")
        return lines

    return [str(data)]


def _balanced_sample(lines: list[str], n: int) -> list[str]:
    """
    Return exactly `n` lines sampled with uniform spacing across `lines`.
    Guarantees the first and last line are always included so the AI
    sees the beginning and end of the dataset.

    If len(lines) <= n, returns all lines unchanged.
    """
    total = len(lines)
    if total <= n:
        return lines

    # Build n evenly-spaced indices across [0, total-1]
    indices: list[int] = []
    for i in range(n):
        # Linear interpolation: maps i in [0, n-1] → index in [0, total-1]
        idx = int(round(i * (total - 1) / (n - 1)))
        indices.append(idx)

    # Deduplicate while preserving order (can occur when n is close to total)
    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)

    return [lines[i] for i in unique]


def _load_glob_data() -> str:
    """
    Load every *.json in Glob_data/ (except EXCLUDED_FILES).

    Per-file budget  : MAX_LINES_PER_FILE lines, sampled with equal spacing.
    Global budget    : MAX_TOTAL_LINES across all files; each file gets an
                       equal share (floor division), remainder distributed to
                       the first files — this is the load-balancing step.
    """
    data_dir = _resolve_glob_dir()

    print(f"[App7/Intel] Glob_data path  -> {data_dir}")
    print(f"[App7/Intel] Path exists     -> {data_dir.exists()}")

    if not data_dir.exists():
        print(f"[App7/Intel] WARNING: Glob_data directory not found at: {data_dir}")
        return "[DATA UNAVAILABLE: Source directory not found.]"

    json_files = sorted(
        f for f in data_dir.glob("*.json")
        if f.name not in EXCLUDED_FILES
    )
    print(f"[App7/Intel] Files to load   -> {[f.name for f in json_files]}")

    if not json_files:
        return "[DATA UNAVAILABLE: No usable data files found after exclusions.]"

    n_files = len(json_files)

    # ── Load-balancing: divide the global line budget evenly across files ──
    # Each file gets at most MAX_LINES_PER_FILE AND at most its fair global share.
    base_share    = MAX_TOTAL_LINES // n_files          # floor share per file
    remainder     = MAX_TOTAL_LINES % n_files           # extra lines for first N files
    # Clamp each share to the per-file hard cap
    file_budgets  = [
        min(MAX_LINES_PER_FILE, base_share + (1 if i < remainder else 0))
        for i in range(n_files)
    ]

    print(
        f"[App7/Intel] Line budget     -> {MAX_TOTAL_LINES} total / "
        f"{MAX_LINES_PER_FILE} per file / shares={file_budgets}"
    )

    summaries: list[str] = []

    for json_file, budget in zip(json_files, file_budgets):
        label = json_file.stem.replace("_", " ").title()
        try:
            with open(json_file, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)

            all_lines  = _json_to_lines(data)
            total_recs = len(all_lines)

            if total_recs == 0:
                summaries.append(f"### DATASET: {label}\n[No records found]")
                print(f"[App7/Intel] {json_file.name} → 0 records, skipped")
                continue

            sampled    = _balanced_sample(all_lines, budget)
            kept       = len(sampled)
            truncated  = kept < total_recs

            header = (
                f"### DATASET: {label}\n"
                f"# Records in dataset: {total_recs} | "
                f"Lines fed to AI: {kept}"
                + (" (evenly sampled)" if truncated else "")
                + "\n"
            )
            block = header + "\n".join(sampled)
            summaries.append(block)

            print(
                f"[App7/Intel] {json_file.name} → "
                f"{total_recs} records, fed {kept} lines "
                f"(budget={budget}, sampled={truncated})"
            )

        except json.JSONDecodeError as exc:
            summaries.append(f"### DATASET: {label}\n[Parse error — data unavailable]")
            print(f"[App7/Intel] JSON error in {json_file.name}: {exc}")
        except Exception as exc:
            summaries.append(f"### DATASET: {label}\n[Load error — data unavailable]")
            print(f"[App7/Intel] Error reading {json_file.name}: {exc}")

    if not summaries:
        return "[DATA UNAVAILABLE: All files failed to load.]"

    return "\n\n".join(summaries)


def _build_system_prompt() -> str:
    data_context = _load_glob_data()

    prompt = (
        "You are GEO-ARTEMIS INTEL, an advanced geospatial intelligence AI embedded "
        "in the Geo Artemis monitoring platform.\n\n"

        "## Communication Style\n"
        "- Be concise and analytical. No walls of text unless detail is explicitly requested.\n"
        "- Interpret and summarize data — never dump raw JSON, numbers, or arrays at the user.\n"
        "- Translate data into meaningful insights: trends, anomalies, comparisons, context.\n"
        "- Use plain language first; use technical terms only when they add precision.\n"
        "- Format with bullet points or short tables only when it genuinely aids clarity.\n"
        "- When referencing data, say 'based on fetched data' or 'according to platform data' — "
        "never expose filenames, file paths, or internal dataset names to the user.\n\n"

        "## Response Rules\n"
        "- Summarize findings, not raw values. E.g. instead of listing 40 coordinates, "
        "say 'Activity is concentrated in Southeast Asia, with the highest density near [region]'.\n"
        "- If a user asks 'how many', give the count plus a brief pattern or highlight.\n"
        "- If a user asks 'where', give region/country names, not raw lat/lon unless asked.\n"
        "- If a user asks 'what happened', give a narrative summary with key facts.\n"
        "- Always round/clean numbers naturally: magnitudes to 1 decimal, coordinates only if explicitly asked.\n"
        "- If the data is absent or incomplete for a query, say: "
        "'I don't have sufficient data to answer that right now.' — never fabricate.\n"
        "- If asked about earthquakes specifically, say: "
        "'Earthquake event data is currently excluded from my active dataset due to its size. "
        "I can discuss general seismic patterns if helpful.'\n"
        "- Never reproduce raw JSON, array dumps, or internal structure in your reply.\n"
        "- Never fabricate events, coordinates, or statistics not present in the loaded data.\n\n"

        "## Edge Case Handling\n"
        "- Empty or vague query → ask one clarifying question.\n"
        "- Query outside geospatial scope → politely redirect: "
        "'I'm specialized in geospatial intelligence. Could you ask something related to "
        "geographic events, natural phenomena, or location-based data?'\n"
        "- Sensitive/harmful query → decline professionally without explanation of internals.\n"
        "- Data unavailable for a region → say so clearly and suggest what is available.\n\n"

        "=== PLATFORM DATA (INTERNAL — DO NOT EXPOSE TO USER) ===\n"
        + data_context
        + "\n=== END OF PLATFORM DATA ===\n"
    )
    return prompt


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if not _SYSTEM_PROMPT:
        _SYSTEM_PROMPT = _build_system_prompt()
    return _SYSTEM_PROMPT


def _is_rate_limit_or_auth_error(exc: Exception) -> bool:
    """Detect quota exhaustion, rate limiting, or invalid key errors from Gemini."""
    err_str = str(exc).lower()
    keywords = [
        "quota", "rate limit", "rate_limit", "resource exhausted",
        "429", "too many requests", "api key", "invalid key",
        "permission denied", "403", "unauthorized", "401",
    ]
    return any(kw in err_str for kw in keywords)


async def _call_gemini(api_key: str, history: list[dict], message: str) -> str:
    """Configure Gemini with a given key and send the message. Returns reply text."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=_get_system_prompt(),
    )
    gemini_history = [
        {"role": msg["role"], "parts": [msg["content"]]}
        for msg in history
    ]
    chat_session = model.start_chat(history=gemini_history)
    response = await chat_session.send_message_async(message)
    return response.text


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
    Automatically falls back to GEMINI_API_KEY2 on rate limit or auth errors.
    """
    if not GEMINI_API_KEY and not GEMINI_API_KEY2:
        return JSONResponse(
            status_code=500,
            content={"error": "No Gemini API keys configured. Set GEMINI_API_KEY or GEMINI_API_KEY2 in your .env file."},
        )

    session_id = payload.session_id or str(uuid.uuid4())
    if session_id not in _chat_sessions:
        _chat_sessions[session_id] = []

    history = _chat_sessions[session_id]
    reply: str = ""
    last_error: Exception | None = None

    # Build ordered list of available keys: primary first, fallback second
    keys_to_try: list[tuple[str, str]] = []
    if GEMINI_API_KEY:
        keys_to_try.append(("primary", GEMINI_API_KEY))
    if GEMINI_API_KEY2:
        keys_to_try.append(("fallback", GEMINI_API_KEY2))

    for label, api_key in keys_to_try:
        try:
            print(f"[App7/Intel] Attempting Gemini call with {label} key...")
            reply = await _call_gemini(api_key, history, payload.message)
            print(f"[App7/Intel] Success with {label} key.")
            break  # Got a valid response — stop trying

        except Exception as exc:
            last_error = exc
            if _is_rate_limit_or_auth_error(exc):
                print(f"[App7/Intel] {label} key failed (rate limit / auth): {exc}")
                continue  # Try next key
            else:
                # Non-recoverable error — don't try fallback
                print(f"[App7/Intel] {label} key failed (non-recoverable): {exc}")
                return JSONResponse(
                    status_code=500,
                    content={"error": "The intelligence system encountered an unexpected error. Please try again."},
                )

    if not reply:
        # All keys exhausted
        print(f"[App7/Intel] All API keys exhausted. Last error: {last_error}")
        return JSONResponse(
            status_code=429,
            content={"error": "All API keys are currently rate-limited or unavailable. Please try again shortly."},
        )

    # Persist exchange
    history.append({"role": "user",  "content": payload.message})
    history.append({"role": "model", "content": reply})

    # Cap at 40 entries (20 exchanges)
    if len(history) > 40:
        _chat_sessions[session_id] = history[-40:]

    return JSONResponse({"reply": reply, "session_id": session_id})


@router.post("/chat/clear")
async def clear_chat(payload: ClearSession):
    """Wipe a session's server-side chat history."""
    _chat_sessions.pop(payload.session_id, None)
    return JSONResponse({"status": "cleared"})


@router.get("/chat/sessions")
async def list_sessions():
    """Debug endpoint - active session IDs and message counts."""
    return JSONResponse({sid: len(msgs) for sid, msgs in _chat_sessions.items()})