import sqlite3
import traceback
from pathlib import Path

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


# ── DB ─────────────────────────────────────────────────────────────────────────

def get_db_connection():
    INSTANCE_DIR = Path(__file__).resolve().parent.parent.parent / "instance"
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = INSTANCE_DIR / "geoartemis.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    conn = get_db_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  VARCHAR(100) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/")
def home(request: Request):
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
):
    try:
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO users (name, email) VALUES (?, ?)",
                (name.strip(), email.strip().lower()),
            )
            conn.commit()
            user = conn.execute(
                "SELECT id FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
            user_id = user["id"] if user else None
        finally:
            conn.close()
    except Exception as e:
        print(f"[Login] DB error: {e}\n{traceback.format_exc()}")
        user_id = None

    # ── Set session keys — is_verified is required by app1 to let the user in ──
    request.session["user_id"]    = user_id
    request.session["name"]       = name.strip()
    request.session["is_verified"] = True        # ← this is the key app1 checks

    return RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


ensure_tables()