"""
app7/routes.py  —  ARTEMIS 2.2  |  Geo Intelligence Terminal
═══════════════════════════════════════════════════════════════
Agentic LangGraph pipeline:
  Router → [Search?] → Rerank → Generate → Parse

Key improvements over v2.1:
  • `import re` moved to top (was causing NameError)
  • Smarter router: topic-intent detection, not just keyword matching
  • Relevance-gated search injection (only results ≥ MIN_SCORE fed to LLM)
  • Dedicated Rerank node strips low-signal results before generation
  • Query expansion: builds a richer search string from detected intents
  • Proper `searched` flag in response (reads state correctly)
  • Duplicate-image deduplication pipeline
  • All cache/history utilities unchanged
"""

from __future__ import annotations

import re
import json
import os
import uuid
import asyncio
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TypedDict, Annotated, Sequence

# ── LangGraph / LangChain ─────────────────────────────────────────────────────
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.tools.tavily_search import TavilySearchResults

# ── FastAPI ───────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
#  Path Resolution
# ─────────────────────────────────────────────────────────────────────────────
_HERE  = Path(__file__).resolve().parent   # Main/app7/
_MAIN  = _HERE.parent                      # Main/
DATA_DIR = _HERE / "data"

CHAT_HISTORY_DIR = DATA_DIR / "chat_history"
CACHE_DIR        = DATA_DIR / "cache"
IMAGE_CACHE_DIR  = DATA_DIR / "images"
SEARCH_CACHE_DIR = CACHE_DIR / "search"

for _d in [CHAT_HISTORY_DIR, CACHE_DIR, IMAGE_CACHE_DIR, SEARCH_CACHE_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

router    = APIRouter()
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# ─────────────────────────────────────────────────────────────────────────────
#  API Keys & Model
# ─────────────────────────────────────────────────────────────────────────────
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY", "")

GEMINI_MODEL = "gemini-2.5-flash"

# ─────────────────────────────────────────────────────────────────────────────
#  Data Source Config
# ─────────────────────────────────────────────────────────────────────────────
EXCLUDED_FILES     = {"events_earthquake.json"}
MAX_LINES_PER_FILE = 200
MAX_TOTAL_LINES    = 800

# Minimum relevance score for a search result to be injected into the prompt
MIN_RELEVANCE_SCORE = 0.35

# ─────────────────────────────────────────────────────────────────────────────
#  Intent / Keyword Taxonomy
# ─────────────────────────────────────────────────────────────────────────────

# Broad signals that fresh web data is needed
SEARCH_TRIGGER_KEYWORDS = [
    "latest", "current", "recent", "today", "now", "breaking", "news",
    "what happened", "update", "today's", "this week", "this month",
    "right now", "happening", "active", "ongoing", "live", "just",
    "new", "reported", "announcement", "declared", "confirmed",
]

# Patterns that strongly imply news-seeking even without trigger words
SEARCH_INTENT_PATTERNS = [
    r"\bnews\b",           # "news about X"
    r"\bwho is\b",        # "who is the PM of India"
    r"\bwhat is\b.{0,30}\b(today|now|currently)\b",
    r"\bstatus of\b",
    r"\bsituation in\b",
    r"\bupdate on\b",
    r"\bhappened (in|to|at)\b",
    r"\bwhen did\b",
    r"\bwhy did\b",
    r"\blatest on\b",
]

STATS_KEYWORDS = [
    "how many", "count", "total", "number", "statistics", "stats", "trend",
    "data", "analysis", "average", "median", "peak", "lowest", "highest",
]

LOCATION_KEYWORDS = [
    "where", "location", "region", "area", "zone", "country", "state",
    "city", "coordinates", "lat", "lon", "latitude", "longitude",
]

EVENT_KEYWORDS = [
    "cyclone", "typhoon", "hurricane", "earthquake", "tsunami", "flood",
    "wildfire", "volcano", "landslide", "tornado", "storm", "drought",
    "avalanche", "eruption", "seismic", "disaster", "event", "hazard",
]

POLITICAL_KEYWORDS = [
    "modi", "pm", "prime minister", "president", "government", "minister",
    "election", "parliament", "policy", "bilateral", "summit", "treaty",
    "sanctions", "diplomacy", "geopolitical",
]

# ─────────────────────────────────────────────────────────────────────────────
#  Cached system prompt
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT: str = ""


# ═════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ═════════════════════════════════════════════════════════════════════════════

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
    total = len(lines)
    if total <= n:
        return lines
    indices: list[int] = []
    for i in range(n):
        idx = int(round(i * (total - 1) / (n - 1)))
        indices.append(idx)
    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    return [lines[i] for i in unique]


def _load_glob_data() -> str:
    data_dir = _resolve_glob_dir()
    print(f"[App7/Intel] Glob_data path  -> {data_dir}")
    print(f"[App7/Intel] Path exists     -> {data_dir.exists()}")

    if not data_dir.exists():
        print(f"[App7/Intel] WARNING: Glob_data not found at: {data_dir}")
        return "[DATA UNAVAILABLE: Source directory not found.]"

    json_files = sorted(
        f for f in data_dir.glob("*.json")
        if f.name not in EXCLUDED_FILES
    )
    print(f"[App7/Intel] Files to load   -> {[f.name for f in json_files]}")

    if not json_files:
        return "[DATA UNAVAILABLE: No usable data files found after exclusions.]"

    n_files      = len(json_files)
    base_share   = MAX_TOTAL_LINES // n_files
    remainder    = MAX_TOTAL_LINES % n_files
    file_budgets = [
        min(MAX_LINES_PER_FILE, base_share + (1 if i < remainder else 0))
        for i in range(n_files)
    ]

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
                continue
            sampled   = _balanced_sample(all_lines, budget)
            kept      = len(sampled)
            truncated = kept < total_recs
            header = (
                f"### DATASET: {label}\n"
                f"# Records in dataset: {total_recs} | "
                f"Lines fed to AI: {kept}"
                + (" (evenly sampled)" if truncated else "")
                + "\n"
            )
            summaries.append(header + "\n".join(sampled))
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
    return (
        "You are ARTEMIS 2.2, an advanced geospatial intelligence AI embedded "
        "in the Geo Artemis monitoring platform.\n\n"

        "## Communication Style\n"
        "- Be concise and analytical. No walls of text unless detail is explicitly requested.\n"
        "- Interpret and summarize data — never dump raw JSON, numbers, or arrays at the user.\n"
        "- Do NOT start your response with phrases like 'Based on fetched data' or "
        "'Based on web search'. Deliver intelligence directly.\n"
        "- Translate data into meaningful insights: trends, anomalies, comparisons, context.\n"
        "- Use plain language first; technical terms only when they add precision.\n"
        "- Format with bullet points or short tables ONLY when it genuinely aids clarity.\n"
        "- When referencing platform data, say 'platform records indicate' or 'data shows' — "
        "never expose filenames, paths, or internal dataset names.\n\n"

        "## Web Search Integration\n"
        "- You have access to live web search results injected into your context.\n"
        "- When search results are provided, treat them as ground truth for current events.\n"
        "- Synthesize findings naturally — do NOT preface with 'According to web search'.\n"
        "- Cite sources by domain name: 'reuters.com reports' or 'according to ndtv.com'.\n"
        "- Only use information from search results that is DIRECTLY relevant to the query.\n"
        "- Discard tangentially related content — do NOT summarise off-topic articles.\n"
        "- If image URLs are provided in search context, include at most 4 at the end "
        "formatted as: [IMAGE: <url>]\n\n"

        "## Response Rules\n"
        "- Summarize findings, not raw values.\n"
        "- If asked 'how many', give count plus a brief pattern or highlight.\n"
        "- If asked 'where', give region/country names, not raw lat/lon unless asked.\n"
        "- If asked 'what happened', give a narrative summary with key facts.\n"
        "- Always round/clean numbers naturally.\n"
        "- If data is absent or incomplete, say: "
        "'I don't have sufficient data to answer that right now.' — never fabricate.\n"
        "- If asked about earthquakes: 'Earthquake event data is currently excluded from "
        "my active dataset due to its size. I can discuss general seismic patterns if helpful.'\n"
        "- Never reproduce raw JSON, array dumps, or internal structure.\n"
        "- Never fabricate events, coordinates, or statistics.\n\n"

        "## Edge Case Handling\n"
        "- Empty or vague query → ask one clarifying question.\n"
        "- Query outside geospatial scope → politely redirect.\n"
        "- Sensitive/harmful query → decline professionally.\n"
        "- Data unavailable for a region → say so and suggest what is available.\n\n"

        "=== PLATFORM DATA (INTERNAL — DO NOT EXPOSE TO USER) ===\n"
        + data_context
        + "\n=== END OF PLATFORM DATA ===\n"
    )


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if not _SYSTEM_PROMPT:
        _SYSTEM_PROMPT = _build_system_prompt()
    return _SYSTEM_PROMPT


# ═════════════════════════════════════════════════════════════════════════════
#  CACHE UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

SEARCH_CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _load_search_cache(query: str) -> dict | None:
    key  = _cache_key(query)
    path = SEARCH_CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if time.time() - cached.get("timestamp", 0) < SEARCH_CACHE_TTL_SECONDS:
            print(f"[App7/Cache] HIT: {query[:60]}")
            return cached["data"]
    except Exception:
        pass
    return None


def _save_search_cache(query: str, data: dict) -> None:
    key  = _cache_key(query)
    path = SEARCH_CACHE_DIR / f"{key}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "data": data}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[App7/Cache] Failed to save: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  CHAT HISTORY PERSISTENCE
# ═════════════════════════════════════════════════════════════════════════════

def _history_path(session_id: str) -> Path:
    return CHAT_HISTORY_DIR / f"{session_id}.json"


def _load_history(session_id: str) -> list[dict]:
    path = _history_path(session_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(session_id: str, history: list[dict]) -> None:
    path = _history_path(session_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history[-40:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[App7/History] Failed to save {session_id}: {e}")


def _delete_history(session_id: str) -> None:
    path = _history_path(session_id)
    if path.exists():
        path.unlink()


# ═════════════════════════════════════════════════════════════════════════════
#  QUERY ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def _analyze_query(query: str) -> dict:
    """
    Deep query analysis: intent, topic domain, named entities, temporal signals.
    Returns a context dict used by router, search, and rerank nodes.
    """
    q = query.lower()

    # ── Intent detection ──────────────────────────────────────────────────
    intents: list[str] = []
    if any(kw in q for kw in ["what", "how", "why", "explain", "describe"]):
        intents.append("explanatory")
    if any(kw in q for kw in SEARCH_TRIGGER_KEYWORDS):
        intents.append("current_events")
    if any(re.search(p, q) for p in SEARCH_INTENT_PATTERNS):
        intents.append("news_seeking")
    if any(kw in q for kw in STATS_KEYWORDS):
        intents.append("statistics")
    if any(kw in q for kw in LOCATION_KEYWORDS):
        intents.append("geographic")
    if any(kw in q for kw in POLITICAL_KEYWORDS):
        intents.append("political")

    # ── Topic domains ─────────────────────────────────────────────────────
    event_types = [e for e in EVENT_KEYWORDS if e in q]
    geo_terms   = [t for t in [
        "africa", "asia", "europe", "america", "caribbean", "pacific",
        "mediterranean", "india", "china", "usa", "uk", "russia",
        "north", "south", "east", "west", "central",
    ] if t in q]
    time_terms = [t for t in [
        "yesterday", "today", "tonight", "tomorrow", "week",
        "month", "year", "hour", "minute",
    ] if t in q]

    # ── Needs live data? ──────────────────────────────────────────────────
    needs_web = (
        "current_events" in intents
        or "news_seeking" in intents
        or "political" in intents
        or bool(event_types)  # natural disaster queries always benefit from live data
    )

    if not intents:
        intents.append("general")

    return {
        "intents":      intents,
        "event_types":  event_types,
        "geo_terms":    geo_terms,
        "time_terms":   time_terms,
        "needs_web":    needs_web,
        "is_detailed":  len(query) > 80,
        "raw_query":    query,
    }


def _build_search_query(query: str, context: dict) -> str:
    """
    Expand the user query into a richer search string.
    Adds temporal anchors and domain terms for better Tavily results.
    """
    parts = [query.strip()]

    # Add temporal anchor for news-seeking queries
    if "news_seeking" in context["intents"] or "current_events" in context["intents"]:
        year = datetime.utcnow().year
        parts.append(str(year))

    # Append top event term if not already in query
    if context["event_types"]:
        for ev in context["event_types"][:1]:
            if ev not in query.lower():
                parts.append(ev)

    return " ".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
#  SEARCH RESULT PROCESSING
# ═════════════════════════════════════════════════════════════════════════════

def _score_result(result: dict, context: dict) -> float:
    """
    Compute a relevance score [0, 1] for a single search result against the
    query context. Combines Tavily's own score with keyword boosting.
    """
    base_score    = float(result.get("score", 0.5))
    content_lower = (result.get("content", "") + " " + result.get("title", "")).lower()
    boost         = 0.0

    # Query terms present in result
    raw_words = re.findall(r'\b\w+\b', context["raw_query"].lower())
    significant_words = [w for w in raw_words if len(w) > 3]
    for w in significant_words:
        if w in content_lower:
            boost += 0.04  # up to ~0.32 for an 8-word query

    # Topic domain boosts
    for ev in context["event_types"]:
        if ev in content_lower:
            boost += 0.12

    for geo in context["geo_terms"]:
        if geo in content_lower:
            boost += 0.08

    for tt in context["time_terms"]:
        if tt in content_lower:
            boost += 0.06

    # Political queries need political content
    if "political" in context["intents"]:
        for kw in POLITICAL_KEYWORDS:
            if kw in content_lower:
                boost += 0.10
                break

    return min(1.0, base_score + boost)


def _format_results(raw: list[dict], context: dict) -> list[dict]:
    """Score, annotate, and sort search results by relevance."""
    formatted = []
    for idx, r in enumerate(raw):
        url    = r.get("url", "")
        domain = url.split("/")[2] if "/" in url else url
        score  = _score_result(r, context)
        formatted.append({
            "url":       url,
            "domain":    domain,
            "title":     r.get("title", "Untitled"),
            "content":   r.get("content", "")[:600],
            "score":     score,
            "position":  idx + 1,
        })
    formatted.sort(key=lambda x: x["score"], reverse=True)
    return formatted


def _extract_images(results: list[dict], max_images: int = 4) -> list[str]:
    """Extract unique, non-trivial image URLs from search results."""
    images: list[str] = []
    SKIP_TOKENS = {"icon", "logo", "pixel", "avatar", "1x1", "transparent", "spacer", "blank"}

    for r in results:
        candidates = []

        img = r.get("image_url") or r.get("image")
        if img:
            candidates.append(img)

        url = r.get("url", "")
        if url.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            candidates.append(url)

        # Fallback: pull first image URL from content
        for m in re.finditer(r'(https?://\S+\.(?:jpg|jpeg|png|gif|webp))', r.get("content", ""), re.I):
            candidates.append(m.group(1))

        for img in candidates:
            if not img or not img.startswith("http"):
                continue
            if img in images:
                continue
            if any(t in img.lower() for t in SKIP_TOKENS):
                continue
            images.append(img)

        if len(images) >= max_images:
            break

    return images[:max_images]


# ═════════════════════════════════════════════════════════════════════════════
#  LANGGRAPH STATE
# ═════════════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    messages:       Annotated[Sequence[BaseMessage], add_messages]
    query_context:  dict           # filled by router
    search_results: list[dict]     # filled by search node, pruned by rerank
    images:         list[str]
    needs_search:   bool
    searched:       bool           # True only if search actually ran
    final_response: str


# ═════════════════════════════════════════════════════════════════════════════
#  HELPER FACTORIES
# ═════════════════════════════════════════════════════════════════════════════

def _make_llm(api_key: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=api_key,
        temperature=0.7,
        max_tokens=2048,
    )


def _make_search_tool() -> TavilySearchResults | None:
    if not TAVILY_API_KEY:
        return None
    return TavilySearchResults(
        max_results=8,
        include_answer=True,
        include_images=True,
        tavily_api_key=TAVILY_API_KEY,
    )


def _last_user_message(state: AgentState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


# ═════════════════════════════════════════════════════════════════════════════
#  NODE 1 — ROUTER
#  Analyses the query and decides whether web search is needed.
# ═════════════════════════════════════════════════════════════════════════════

def router_node(state: AgentState) -> AgentState:
    user_msg = _last_user_message(state)
    ctx      = _analyze_query(user_msg)

    print(
        f"[App7/Router] intents={ctx['intents']} "
        f"events={ctx['event_types']} needs_web={ctx['needs_web']}"
    )

    return {
        **state,
        "query_context": ctx,
        "needs_search":  ctx["needs_web"],
        "searched":      False,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  NODE 2 — SEARCH
#  Runs Tavily with an expanded query; scores and formats results.
# ═════════════════════════════════════════════════════════════════════════════

def search_node(state: AgentState) -> AgentState:
    if not state.get("needs_search"):
        return state

    user_msg = _last_user_message(state)
    ctx      = state.get("query_context", _analyze_query(user_msg))

    # Cache lookup (keyed on original query)
    cached = _load_search_cache(user_msg)
    if cached:
        return {
            **state,
            "search_results": cached.get("results", []),
            "images":         cached.get("images", []),
            "searched":       True,
        }

    search_tool = _make_search_tool()
    if not search_tool:
        print("[App7/Search] No Tavily key — skipping.")
        return {**state, "search_results": [], "images": [], "searched": False}

    expanded_query = _build_search_query(user_msg, ctx)
    print(f"[App7/Search] Query: {expanded_query[:120]}")

    try:
        raw = search_tool.invoke({"query": expanded_query})
        results = raw if isinstance(raw, list) else []

        formatted = _format_results(results, ctx)
        images    = _extract_images(formatted)

        _save_search_cache(user_msg, {"results": formatted, "images": images})

        top = [f"{r['score']:.2f}" for r in formatted[:3]]
        print(f"[App7/Search] {len(formatted)} results | top scores: {top}")

        return {**state, "search_results": formatted, "images": images, "searched": True}

    except Exception as e:
        print(f"[App7/Search] Failed: {e}")
        return {**state, "search_results": [], "images": [], "searched": False}


# ═════════════════════════════════════════════════════════════════════════════
#  NODE 3 — RERANK
#  Filters out low-relevance results so the LLM is not distracted by
#  tangentially related content (the root cause of the Modi/Fed mixup).
# ═════════════════════════════════════════════════════════════════════════════

def rerank_node(state: AgentState) -> AgentState:
    results = state.get("search_results", [])
    if not results:
        return state

    # Hard threshold: drop anything below MIN_RELEVANCE_SCORE
    filtered = [r for r in results if r.get("score", 0) >= MIN_RELEVANCE_SCORE]

    # Safety: always keep at least the top result even if below threshold
    if not filtered and results:
        filtered = results[:1]

    # Cap at 5 results to keep prompt compact
    filtered = filtered[:5]

    dropped = len(results) - len(filtered)
    if dropped:
        print(f"[App7/Rerank] Dropped {dropped} low-relevance result(s) (threshold={MIN_RELEVANCE_SCORE})")

    return {**state, "search_results": filtered}


# ═════════════════════════════════════════════════════════════════════════════
#  NODE 4 — GENERATE
#  Builds the full prompt, calls Gemini (with key fallback), returns reply.
# ═════════════════════════════════════════════════════════════════════════════

def generate_node(state: AgentState) -> AgentState:
    system_prompt  = _get_system_prompt()
    search_results = state.get("search_results", [])
    images         = state.get("images", [])
    ctx            = state.get("query_context", {})

    # ── Build search context block ────────────────────────────────────────
    search_context = ""
    if search_results:
        high   = [r for r in search_results if r.get("score", 0) >= 0.65]
        medium = [r for r in search_results if 0.35 <= r.get("score", 0) < 0.65]

        blocks: list[str] = []

        if high:
            blocks.append("=== HIGH-RELEVANCE FINDINGS ===")
            for r in high[:3]:
                match_info = ""
                if ctx.get("event_types"):
                    events_found = [e for e in ctx["event_types"] if e in r["content"].lower()]
                    if events_found:
                        match_info = f" [matches: {', '.join(events_found)}]"
                blocks.append(
                    f"\n[{r['domain']}]{match_info}\n"
                    f"Title: {r['title']}\n"
                    f"{r['content']}"
                )

        if medium:
            blocks.append("\n=== SUPPORTING CONTEXT ===")
            for r in medium[:2]:
                blocks.append(f"\n[{r['domain']}] {r['title']}\n{r['content'][:350]}")

        search_context = (
            "\n\n=== LIVE WEB SEARCH RESULTS (synthesize — do NOT dump verbatim) ===\n"
            + "\n".join(blocks)
            + "\n=== END SEARCH RESULTS ==="
            "\n\nSYNTHESIS RULES:"
            "\n- Answer ONLY what the user asked. Discard off-topic results entirely."
            "\n- Cite sources by domain (e.g., 'ndtv.com reports')."
            "\n- Do NOT preface with 'Based on search results' or similar."
            "\n- If results are insufficient, say so — never fabricate."
        )

        if images:
            search_context += (
                "\n\nIf relevant, include up to 4 image URLs at the END of your response:\n"
                + "\n".join(f"[IMAGE: {img}]" for img in images)
            )

    full_system  = system_prompt + search_context
    lc_messages: list[BaseMessage] = [SystemMessage(content=full_system)]
    lc_messages.extend(state["messages"])

    # ── API key rotation ──────────────────────────────────────────────────
    keys_to_try: list[tuple[str, str]] = []
    if GEMINI_API_KEY:
        keys_to_try.append(("primary",  GEMINI_API_KEY))
    if GEMINI_API_KEY2:
        keys_to_try.append(("fallback", GEMINI_API_KEY2))

    if not keys_to_try:
        return {**state, "final_response": "ERROR: No Gemini API keys configured."}

    last_error = None
    for label, api_key in keys_to_try:
        try:
            print(f"[App7/Generate] Calling Gemini ({label} key)...")
            llm      = _make_llm(api_key)
            response = llm.invoke(lc_messages)
            reply    = response.content
            print(f"[App7/Generate] Success ({label} key).")
            return {
                **state,
                "final_response": reply,
                "messages":       list(state["messages"]) + [AIMessage(content=reply)],
            }
        except Exception as exc:
            last_error  = exc
            err_lower   = str(exc).lower()
            recoverable = any(kw in err_lower for kw in [
                "quota", "rate limit", "rate_limit", "resource exhausted",
                "429", "too many requests", "api key", "invalid key",
                "permission denied", "403", "unauthorized", "401",
            ])
            print(f"[App7/Generate] {label} key failed ({'recoverable' if recoverable else 'fatal'}): {exc}")
            if not recoverable:
                break

    return {
        **state,
        "final_response": f"RATE_LIMITED: All API keys exhausted. Last error: {last_error}",
    }


# ═════════════════════════════════════════════════════════════════════════════
#  CONDITIONAL EDGES
# ═════════════════════════════════════════════════════════════════════════════

def route_after_router(state: AgentState) -> str:
    return "search" if state.get("needs_search") else "generate"


def route_after_search(state: AgentState) -> str:
    # Always pass through rerank if we ran a search (even on cache hit)
    return "rerank" if state.get("searched") else "generate"


# ═════════════════════════════════════════════════════════════════════════════
#  BUILD LANGGRAPH
# ═════════════════════════════════════════════════════════════════════════════

def _build_graph():
    g = StateGraph(AgentState)

    g.add_node("router",   router_node)
    g.add_node("search",   search_node)
    g.add_node("rerank",   rerank_node)
    g.add_node("generate", generate_node)

    g.set_entry_point("router")

    g.add_conditional_edges("router", route_after_router, {
        "search":   "search",
        "generate": "generate",
    })
    g.add_conditional_edges("search", route_after_search, {
        "rerank":   "rerank",
        "generate": "generate",
    })
    g.add_edge("rerank",   "generate")
    g.add_edge("generate", END)

    return g.compile()


_AGENT_GRAPH = None


def _get_agent():
    global _AGENT_GRAPH
    if _AGENT_GRAPH is None:
        _AGENT_GRAPH = _build_graph()
        print("[App7/Agent] LangGraph pipeline compiled: router→search→rerank→generate")
    return _AGENT_GRAPH


# ═════════════════════════════════════════════════════════════════════════════
#  RESPONSE PARSER
# ═════════════════════════════════════════════════════════════════════════════

_IMAGE_RE = re.compile(r'\[IMAGE:\s*(https?://[^\]]+)\]', re.IGNORECASE)


def _parse_response(raw: str) -> tuple[str, list[str]]:
    images = _IMAGE_RE.findall(raw)
    clean  = _IMAGE_RE.sub("", raw).strip()
    return clean, images


# ═════════════════════════════════════════════════════════════════════════════
#  IN-MEMORY SESSION INDEX
# ═════════════════════════════════════════════════════════════════════════════

_session_cache: dict[str, list[dict]] = {}


def _get_session_history(session_id: str) -> list[dict]:
    if session_id not in _session_cache:
        _session_cache[session_id] = _load_history(session_id)
    return _session_cache[session_id]


def _update_session_history(session_id: str, history: list[dict]) -> None:
    _session_cache[session_id] = history
    _save_history(session_id, history)


# ═════════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ═════════════════════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    message:    str
    session_id: Optional[str] = None


class ClearSession(BaseModel):
    session_id: str


# ═════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/")
def home(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("home7.html", {"request": request})


@router.post("/chat")
async def chat(payload: ChatMessage):
    """
    Main chat endpoint.
    Pipeline: router → [search → rerank]? → generate
    Returns structured JSON with reply, images, sources, and metadata.
    """
    if not GEMINI_API_KEY and not GEMINI_API_KEY2:
        return JSONResponse(
            status_code=500,
            content={"error": "No Gemini API keys configured. Set GEMINI_API_KEY or GEMINI_API_KEY2."},
        )

    session_id = payload.session_id or str(uuid.uuid4())
    history    = _get_session_history(session_id)

    # Reconstruct LangChain message history
    lc_history: list[BaseMessage] = []
    for msg in history:
        role    = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            lc_history.append(HumanMessage(content=content))
        elif role in ("model", "assistant"):
            lc_history.append(AIMessage(content=content))

    lc_history.append(HumanMessage(content=payload.message))

    initial_state: AgentState = {
        "messages":       lc_history,
        "query_context":  {},
        "search_results": [],
        "images":         [],
        "needs_search":   False,
        "searched":       False,
        "final_response": "",
    }

    try:
        agent  = _get_agent()
        result = await asyncio.to_thread(agent.invoke, initial_state)
    except Exception as exc:
        print(f"[App7/Agent] Graph execution failed: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "The intelligence system encountered an unexpected error. Please try again."},
        )

    raw_reply = result.get("final_response", "")

    if raw_reply.startswith("ERROR:"):
        return JSONResponse(status_code=500, content={"error": raw_reply})
    if raw_reply.startswith("RATE_LIMITED:"):
        return JSONResponse(
            status_code=429,
            content={"error": "All API keys are currently rate-limited. Please try again shortly."},
        )

    # Parse [IMAGE: url] tags out of reply text
    clean_reply, inline_images = _parse_response(raw_reply)

    # Merge: model-chosen images first, then search-extracted, deduplicated
    all_images = list(dict.fromkeys(inline_images + result.get("images", [])))[:4]

    # Persist exchange
    history.append({"role": "user",  "content": payload.message})
    history.append({"role": "model", "content": clean_reply, "images": all_images})
    _update_session_history(session_id, history)

    # Build source citations from top search results
    sources: list[dict] = []
    for r in result.get("search_results", [])[:3]:
        if r.get("url"):
            sources.append({"title": r.get("title", ""), "url": r["url"]})

    return JSONResponse({
        "reply":      clean_reply,
        "session_id": session_id,
        "images":     all_images,
        "sources":    sources,
        "searched":   result.get("searched", False),   # ← fixed: reads correct state key
        "intents":    result.get("query_context", {}).get("intents", []),
        "timestamp":  datetime.utcnow().isoformat() + "Z",
    })


@router.post("/chat/clear")
async def clear_chat(payload: ClearSession):
    """Wipe a session's in-memory and on-disk chat history."""
    _session_cache.pop(payload.session_id, None)
    _delete_history(payload.session_id)
    return JSONResponse({"status": "cleared"})


@router.get("/chat/sessions")
async def list_sessions():
    """Debug: active session IDs and message counts."""
    return JSONResponse({sid: len(msgs) for sid, msgs in _session_cache.items()})


@router.get("/chat/history/{session_id}")
async def get_history(session_id: str):
    """Return the persisted chat history for a session."""
    history = _get_session_history(session_id)
    return JSONResponse({"session_id": session_id, "history": history, "count": len(history)})


@router.delete("/cache/search")
async def clear_search_cache():
    """Dev: purge all cached search results."""
    count = sum(1 for f in SEARCH_CACHE_DIR.glob("*.json") if f.unlink() or True)
    return JSONResponse({"status": "cleared", "files_deleted": count})