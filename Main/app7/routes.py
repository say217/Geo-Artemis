"""
app7 Geo Artemis AI Intelligence Terminal
Gemini 2.5 Flash-powered chat with dynamic tool-based data retrieval.
just chat with ai if u need any query
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import google.generativeai as genai
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


_HERE = Path(__file__).resolve().parent   # Main/app7/
_MAIN = _HERE.parent                       # Main/

router    = APIRouter()
templates = Jinja2Templates(directory=str(_HERE / "templates"))

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY",  "")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_MODEL    = "gemini-2.5-flash"


EXCLUDED_FILES = {"events_earthquake.json"}
MAX_RESULTS    = 30    # Max records returned per tool call
MAX_TOOL_CALLS = 5     # Max search iterations per user turn (safety cap)


_chat_sessions: dict[str, list[dict]] = {}
_data_index:    dict[str, Any] | None = None   # metadata index (built once)
_data_cache:    dict[str, list[dict]] = {}     # file-name → parsed records



def _resolve_glob_dir() -> Path:
    candidates = [
        _MAIN / "app3" / "Glob_data",
        Path.cwd() / "Main" / "app3" / "Glob_data",
        Path.cwd() / "app3" / "Glob_data",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _normalize_record(item: Any) -> dict:
    """Ensure every record is a flat dict (wrap scalars/lists as needed)."""
    if isinstance(item, dict):
        return item
    return {"value": item}


def _load_all_data() -> dict[str, list[dict]]:
    """
    Load every eligible JSON file into memory as a list of dicts.
    Runs once on first call; result is cached in _data_cache.
    """
    global _data_cache
    if _data_cache:
        return _data_cache

    data_dir = _resolve_glob_dir()
    if not data_dir.exists():
        print(f"[App7] WARNING: Glob_data not found at {data_dir}")
        return {}

    json_files = sorted(
        f for f in data_dir.glob("*.json")
        if f.name not in EXCLUDED_FILES
    )

    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8", errors="replace") as fh:
                raw = json.load(fh)

            records: list[dict] = []
            if isinstance(raw, list):
                records = [_normalize_record(item) for item in raw]
            elif isinstance(raw, dict):
                # Treat each top-level key as a record
                records = [{"_key": k, **(_normalize_record(v))} for k, v in raw.items()]
            else:
                records = [{"value": raw}]

            _data_cache[jf.name] = records
            print(f"[App7] Loaded {jf.name}: {len(records)} records")

        except Exception as exc:
            print(f"[App7] Failed to load {jf.name}: {exc}")

    return _data_cache


def _build_data_index() -> dict[str, Any]:
    """
    Build a lightweight metadata index: file names, record counts, sample fields.
    This is what goes into the system prompt — NOT the actual data.
    """
    global _data_index
    if _data_index is not None:
        return _data_index

    all_data = _load_all_data()
    index: dict[str, Any] = {}

    for fname, records in all_data.items():
        label = fname.replace("_", " ").replace(".json", "").title()
        # Collect all field names from the first 20 records
        fields: set[str] = set()
        for rec in records[:20]:
            fields.update(rec.keys())
        # Sample 3 records as examples
        sample_values: dict[str, list] = {}
        for field in list(fields)[:8]:
            vals = [str(r.get(field, ""))[:60] for r in records[:5] if field in r]
            if vals:
                sample_values[field] = vals[:3]

        index[fname] = {
            "label":         label,
            "record_count":  len(records),
            "fields":        sorted(fields - {"_key"}),
            "sample_values": sample_values,
        }

    _data_index = index
    return _data_index



def search_geospatial_data(
    query: str,
    dataset: str | None = None,
    field_filter: dict[str, str] | None = None,
    sort_by: str | None = None,
    limit: int = MAX_RESULTS,
) -> dict:
    """
    Search the geospatial datasets.

    Args:
        query:        Free-text search string (matched against all string fields).
        dataset:      Optional filename (e.g. "events_fire.json") to restrict search.
                      If omitted, all datasets are searched.
        field_filter: Optional dict of {field: value} for exact/substring matching.
        sort_by:      Optional field name to sort results by (ascending).
        limit:        Max number of records to return (hard-capped at MAX_RESULTS).

    Returns:
        A dict with keys: results, total_matched, datasets_searched, query_info
    """
    limit = min(limit, MAX_RESULTS)
    all_data = _load_all_data()

    if not all_data:
        return {
            "results":          [],
            "total_matched":    0,
            "datasets_searched": [],
            "query_info":       {"error": "No data available"},
        }

    # Determine which files to search
    if dataset:
       
        target_files = [
            fname for fname in all_data
            if dataset.lower() in fname.lower()
        ]
        if not target_files:
            return {
                "results":          [],
                "total_matched":    0,
                "datasets_searched": [],
                "query_info":       {"error": f"Dataset '{dataset}' not found. Available: {list(all_data.keys())}"},
            }
    else:
        target_files = list(all_data.keys())

    # Build keyword tokens from query
    query_tokens = [t.lower() for t in re.split(r"\W+", query) if len(t) > 2]

    matched: list[dict] = []

    for fname in target_files:
        records = all_data[fname]
        label   = fname.replace("_", " ").replace(".json", "").title()

        for rec in records:
            # 1. Field filter (exact / substring match, case-insensitive)
            if field_filter:
                if not all(
                    str(rec.get(k, "")).lower().find(str(v).lower()) >= 0
                    for k, v in field_filter.items()
                ):
                    continue

            # 2. Keyword search across all string fields
            if query_tokens:
                rec_text = " ".join(str(v) for v in rec.values()).lower()
                if not any(tok in rec_text for tok in query_tokens):
                    continue

            matched.append({"_dataset": label, "_file": fname, **rec})

    # Sort if requested
    if sort_by and matched:
        try:
            matched.sort(key=lambda r: r.get(sort_by, ""), reverse=False)
        except Exception:
            pass

    total_matched = len(matched)
    results       = matched[:limit]

    # Sanitise output — truncate very long string values
    clean_results = []
    for rec in results:
        clean = {}
        for k, v in rec.items():
            if isinstance(v, str) and len(v) > 300:
                clean[k] = v[:300] + "…"
            elif isinstance(v, (dict, list)):
                clean[k] = json.dumps(v, ensure_ascii=False)[:300]
            else:
                clean[k] = v
        clean_results.append(clean)

    return {
        "results":           clean_results,
        "total_matched":     total_matched,
        "datasets_searched": target_files,
        "query_info": {
            "query":        query,
            "dataset":      dataset,
            "field_filter": field_filter,
            "sort_by":      sort_by,
            "limit":        limit,
        },
    }


# ===========================================================================
#  System Prompt (lean — metadata only)
# ===========================================================================

def _build_system_prompt() -> str:
    index = _build_data_index()

    # Compact metadata block
    meta_lines = []
    for fname, info in index.items():
        fields_str = ", ".join(info["fields"][:12])
        meta_lines.append(
            f"  • {info['label']} ({fname}): {info['record_count']} records | "
            f"fields: {fields_str}"
        )
    meta_block = "\n".join(meta_lines) if meta_lines else "  [No datasets loaded]"

    return (
        "You are GEO-ARTEMIS INTEL, an advanced geospatial intelligence AI embedded "
        "in the Geo Artemis monitoring platform.\n\n"

        "## How you access data\n"
        "You have a tool: `search_geospatial_data`. Call it whenever you need data to answer "
        "a question. Do NOT guess or fabricate — always search first.\n"
        "- You may call the tool multiple times per turn (e.g. refine a query, search a "
        "  different dataset, filter by field).\n"
        "- Pass `dataset` to restrict to a specific file; omit it to search all datasets.\n"
        "- Use `field_filter` for precise filtering (e.g. {\"country\": \"Indonesia\"}).\n"
        "- Use `sort_by` to order results (e.g. sort by magnitude, date, severity).\n"
        "- Increase `limit` for aggregate questions (up to 30); keep it low (5–10) for "
        "  specific lookups.\n\n"

        "## Available datasets (metadata only — search for actual records)\n"
        + meta_block + "\n\n"

        "## Communication style\n"
        "- Interpret and summarise data — never dump raw JSON or arrays at the user.\n"
        "- Translate data into insights: trends, anomalies, comparisons, context.\n"
        "- Use plain language first; technical terms only when they add precision.\n"
        "- Bullet points or short tables only when they genuinely aid clarity.\n"
        "- When referencing data, say 'based on fetched data' or 'according to platform data' — "
        "  never expose filenames, paths, or internal dataset names.\n"
        "- Round numbers naturally: magnitudes to 1 decimal, coordinates only if asked.\n\n"

        "## Response rules\n"
        "- If asked 'how many', give the count + a brief pattern or highlight.\n"
        "- If asked 'where', give region/country names, not raw lat/lon unless asked.\n"
        "- If asked 'what happened', give a narrative summary with key facts.\n"
        "- If the search returns no results, say so and suggest what might be available.\n"
        "- If asked about earthquakes specifically: 'Earthquake event data is currently "
        "  excluded from my active dataset due to its size. I can discuss general seismic "
        "  patterns if helpful.'\n"
        "- Never fabricate events, coordinates, or statistics.\n\n"

        "## Edge cases\n"
        "- Vague query → ask one clarifying question.\n"
        "- Outside geospatial scope → 'I'm specialised in geospatial intelligence. Could you "
        "  ask something related to geographic events, natural phenomena, or location-based data?'\n"
        "- Sensitive/harmful query → decline professionally.\n"
    )


_SYSTEM_PROMPT: str = ""

def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if not _SYSTEM_PROMPT:
        _SYSTEM_PROMPT = _build_system_prompt()
    return _SYSTEM_PROMPT


# ===========================================================================
#  Gemini Tool Definition
# ===========================================================================

GEMINI_TOOLS = [
    genai.types.Tool(
        function_declarations=[
            genai.types.FunctionDeclaration(
                name="search_geospatial_data",
                description=(
                    "Search the geospatial platform datasets. Use this to find events, "
                    "incidents, locations, statistics, or any other data needed to answer "
                    "the user's question. You can call this multiple times per turn to "
                    "refine results or search different datasets."
                ),
                parameters=genai.types.Schema(
                    type=genai.types.Type.OBJECT,
                    properties={
                        "query": genai.types.Schema(
                            type=genai.types.Type.STRING,
                            description=(
                                "Free-text search string. Keywords are matched against all "
                                "text fields in the records. E.g. 'wildfire California 2024', "
                                "'flooding Southeast Asia', 'magnitude 7'."
                            ),
                        ),
                        "dataset": genai.types.Schema(
                            type=genai.types.Type.STRING,
                            description=(
                                "Optional: restrict search to a specific dataset file. "
                                "Use a partial name, e.g. 'fire', 'flood', 'cyclone'. "
                                "Omit to search all datasets."
                            ),
                        ),
                        "field_filter": genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            description=(
                                "Optional: exact/substring field matching. "
                                'E.g. {"country": "Indonesia"} or {"severity": "high"}.'
                            ),
                            additional_properties=genai.types.Schema(
                                type=genai.types.Type.STRING
                            ),
                        ),
                        "sort_by": genai.types.Schema(
                            type=genai.types.Type.STRING,
                            description=(
                                "Optional: sort results by this field name (ascending). "
                                "E.g. 'magnitude', 'date', 'severity', 'deaths'."
                            ),
                        ),
                        "limit": genai.types.Schema(
                            type=genai.types.Type.INTEGER,
                            description=(
                                "Max records to return (1–30). Use 5–10 for specific lookups, "
                                "30 for aggregate/counting questions. Default: 20."
                            ),
                        ),
                    },
                    required=["query"],
                ),
            )
        ]
    )
]


# ===========================================================================
#  Gemini Call with Tool Loop
# ===========================================================================

def _is_rate_limit_or_auth_error(exc: Exception) -> bool:
    err_str = str(exc).lower()
    keywords = [
        "quota", "rate limit", "rate_limit", "resource exhausted",
        "429", "too many requests", "api key", "invalid key",
        "permission denied", "403", "unauthorized", "401",
    ]
    return any(kw in err_str for kw in keywords)


async def _call_gemini_with_tools(
    api_key: str,
    history: list[dict],
    message: str,
) -> str:
    """
    Send a message to Gemini with the search tool available.
    Handles the tool-call loop: Gemini calls search_geospatial_data,
    we execute it locally and feed the result back, repeat until done.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=_get_system_prompt(),
        tools=GEMINI_TOOLS,
    )

    # Convert our simple history to Gemini format
    gemini_history = [
        {"role": msg["role"], "parts": [msg["content"]]}
        for msg in history
    ]

    chat = model.start_chat(history=gemini_history)
    response = await chat.send_message_async(message)

    tool_calls_made = 0

    # Agentic loop: keep responding to tool calls until we get a text reply
    while True:
        # Check if any part is a function call
        fn_calls = [
            part.function_call
            for part in response.parts
            if hasattr(part, "function_call") and part.function_call
        ]

        if not fn_calls:
            # Final text response
            break

        if tool_calls_made >= MAX_TOOL_CALLS:
            # Safety valve — stop tool loop and ask AI to answer with what it has
            print(f"[App7] Tool call limit ({MAX_TOOL_CALLS}) reached — forcing final answer")
            tool_results = [
                genai.types.Part(
                    function_response=genai.types.FunctionResponse(
                        name=fc.name,
                        response={"result": "Search limit reached. Please summarise with available information."},
                    )
                )
                for fc in fn_calls
            ]
            response = await chat.send_message_async(tool_results)
            break

        # Execute each function call
        tool_results = []
        for fc in fn_calls:
            if fc.name == "search_geospatial_data":
                args = dict(fc.args)
                # field_filter comes as a MapComposite — convert to plain dict
                if "field_filter" in args and args["field_filter"]:
                    args["field_filter"] = dict(args["field_filter"])
                if "limit" in args:
                    args["limit"] = int(args["limit"])

                print(f"[App7] Tool call #{tool_calls_made + 1}: search_geospatial_data({args})")
                result = search_geospatial_data(**args)
                print(f"[App7] → matched {result['total_matched']} records, returning {len(result['results'])}")

                tool_results.append(
                    genai.types.Part(
                        function_response=genai.types.FunctionResponse(
                            name="search_geospatial_data",
                            response={"result": json.dumps(result, ensure_ascii=False)},
                        )
                    )
                )
            else:
                # Unknown tool — return an error
                tool_results.append(
                    genai.types.Part(
                        function_response=genai.types.FunctionResponse(
                            name=fc.name,
                            response={"result": f"Unknown tool: {fc.name}"},
                        )
                    )
                )

        tool_calls_made += len(fn_calls)
        response = await chat.send_message_async(tool_results)

    # Extract text from final response
    text_parts = [
        part.text
        for part in response.parts
        if hasattr(part, "text") and part.text
    ]
    return "\n".join(text_parts).strip()


# ===========================================================================
#  Pydantic Models
# ===========================================================================

class ChatMessage(BaseModel):
    message:    str
    session_id: Optional[str] = None


class ClearSession(BaseModel):
    session_id: str


# ===========================================================================
#  Routes
# ===========================================================================

@router.get("/")
def home(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("home7.html", {"request": request})


@router.post("/chat")
async def chat(payload: ChatMessage):
    """
    Accept a user message, maintain per-session history, and return
    a Gemini 2.5 Flash response that dynamically searches geospatial data
    using tool calls — no bulk data dump in the prompt.
    """
    if not GEMINI_API_KEY and not GEMINI_API_KEY2:
        return JSONResponse(
            status_code=500,
            content={"error": "No Gemini API keys configured. Set GEMINI_API_KEY or GEMINI_API_KEY2."},
        )

    session_id = payload.session_id or str(uuid.uuid4())
    if session_id not in _chat_sessions:
        _chat_sessions[session_id] = []

    history    = _chat_sessions[session_id]
    reply: str = ""
    last_error: Exception | None = None

    keys_to_try: list[tuple[str, str]] = []
    if GEMINI_API_KEY:
        keys_to_try.append(("primary",  GEMINI_API_KEY))
    if GEMINI_API_KEY2:
        keys_to_try.append(("fallback", GEMINI_API_KEY2))

    for label, api_key in keys_to_try:
        try:
            print(f"[App7] Attempting Gemini call with {label} key...")
            reply = await _call_gemini_with_tools(api_key, history, payload.message)
            print(f"[App7] Success with {label} key.")
            break

        except Exception as exc:
            last_error = exc
            if _is_rate_limit_or_auth_error(exc):
                print(f"[App7] {label} key rate-limited/auth error: {exc}")
                continue
            else:
                print(f"[App7] {label} key non-recoverable error: {exc}")
                return JSONResponse(
                    status_code=500,
                    content={"error": "The intelligence system encountered an unexpected error. Please try again."},
                )

    if not reply:
        print(f"[App7] All keys exhausted. Last error: {last_error}")
        return JSONResponse(
            status_code=429,
            content={"error": "All API keys are currently rate-limited or unavailable. Please try again shortly."},
        )

    # Persist exchange
    history.append({"role": "user",  "content": payload.message})
    history.append({"role": "model", "content": reply})

    # Cap history at 40 entries (20 exchanges)
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
    """Debug endpoint — active session IDs and message counts."""
    return JSONResponse({sid: len(msgs) for sid, msgs in _chat_sessions.items()})


@router.get("/data/index")
async def data_index():
    """Debug endpoint — shows the metadata index (what datasets are loaded)."""
    return JSONResponse(_build_data_index())


@router.post("/data/search")
async def data_search(payload: dict):
    """
    Direct search endpoint — bypasses AI, useful for debugging tool calls.
    Body: {"query": "...", "dataset": "...", "field_filter": {...}, "limit": 10}
    """
    result = search_geospatial_data(
        query=payload.get("query", ""),
        dataset=payload.get("dataset"),
        field_filter=payload.get("field_filter"),
        sort_by=payload.get("sort_by"),
        limit=int(payload.get("limit", MAX_RESULTS)),
    )
    return JSONResponse(result)