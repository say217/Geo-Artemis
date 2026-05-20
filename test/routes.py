"""
GEO ARTEMIS — Email Authentication System
==========================================
Full flow: Register → Email Verify → Login → Session → Logout
"""
"""
GEO ARTEMIS — Email Authentication System
"""

# ── Load .env FIRST — before any os.environ.get() calls ──────────────────────
from dotenv import load_dotenv
load_dotenv()  # looks for .env in the project root automatically
# ─────────────────────────────────────────────────────────────────────────────

import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
import traceback
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

EMAIL_HOST    = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT    = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USER    = os.environ.get("EMAIL_USER", "")
EMAIL_PASS    = os.environ.get("EMAIL_PASS", "")
APP_BASE_URL  = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SECRET_KEY    = os.environ.get("SECRET_KEY", "change-me-to-something-random-and-long")

# ── Temporary: remove once email is confirmed working ─────────────────────────
print(f"[EMAIL CFG] USER={repr(EMAIL_USER)}  PASS_SET={bool(EMAIL_PASS)}  HOST={EMAIL_HOST}")

TOKEN_EXPIRY_HOURS = 24


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             VARCHAR(100) NOT NULL,
                email            VARCHAR(255) NOT NULL UNIQUE,
                password_hash    VARCHAR(255) NOT NULL DEFAULT '',
                is_verified      INTEGER NOT NULL DEFAULT 0,
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        existing_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "password_hash" not in existing_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NOT NULL DEFAULT ''"
            )
            print("[DB Migration] Added column: password_hash")

        if "is_verified" not in existing_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0"
            )
            print("[DB Migration] Added column: is_verified")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token      VARCHAR(128) NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.commit()
    finally:
        conn.close()


# ── Password Hashing ───────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2$sha256$260000${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        _, algo, iterations, salt, dk_hex = stored_hash.split("$")
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── Token Generation ───────────────────────────────────────────────────────────

def create_verification_token(user_id: int) -> str:
    """
    Invalidates all previous unused tokens for this user, then creates a
    fresh one. This ensures each user always has exactly one live token,
    and re-registration / resend always works cleanly.
    """
    conn = get_db_connection()
    try:
        # Mark every previous token for this user as used so old links stop working
        conn.execute(
            "UPDATE email_tokens SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
        conn.execute(
            "INSERT INTO email_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user_id, token, expires_at.isoformat()),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def consume_verification_token(token: str):
    """Returns user_id if token is valid & unused, else None."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, user_id, expires_at, used FROM email_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        if row["used"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
            return None
        conn.execute("UPDATE email_tokens SET used = 1 WHERE id = ?", (row["id"],))
        conn.commit()
        return row["user_id"]
    finally:
        conn.close()


# ── Email Sending ──────────────────────────────────────────────────────────────

def send_verification_email(to_email: str, to_name: str, token: str):
    verify_url = f"{APP_BASE_URL}/app2/verify-email?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "GEO ARTEMIS — Verify Your Email"
    msg["From"]    = f"GEO ARTEMIS <{EMAIL_USER}>"
    msg["To"]      = to_email

    text_body = f"""
GEO ARTEMIS — EMAIL VERIFICATION
===================================

Hello {to_name},

Click the link below to verify your email and activate your account:

{verify_url}

This link expires in {TOKEN_EXPIRY_HOURS} hours.

If you did not register, ignore this email.

— GEO ARTEMIS Security System
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ background: #060608; color: #f0f0f0; font-family: 'Courier New', monospace; padding: 0; margin: 0; }}
    .wrap {{ max-width: 520px; margin: 40px auto; padding: 0 20px; }}
    .card {{ border: 1px solid rgba(255,51,51,0.3); padding: 2rem; position: relative; background: rgba(255,51,51,0.03); }}
    h1 {{ font-size: 2rem; letter-spacing: 6px; color: #ff3333; margin: 0 0 0.3rem; font-family: Georgia, serif; }}
    .sub {{ font-size: 0.6rem; letter-spacing: 4px; color: rgba(255,255,255,0.3); margin-bottom: 1.5rem; }}
    p {{ font-size: 0.8rem; color: rgba(255,255,255,0.5); line-height: 1.7; margin: 0 0 1.2rem; }}
    .btn {{ display: inline-block; padding: 0.8rem 2rem; background: #ff3333; color: #fff; text-decoration: none; font-size: 0.7rem; letter-spacing: 4px; text-transform: uppercase; }}
    .url {{ font-size: 0.65rem; color: rgba(255,255,255,0.2); word-break: break-all; margin-top: 1rem; }}
    .footer {{ font-size: 0.58rem; color: rgba(255,255,255,0.2); letter-spacing: 2px; margin-top: 1.5rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>GEO ARTEMIS</h1>
      <div class="sub">GEOSPATIAL INTELLIGENCE PLATFORM</div>
      <p>Hello <strong style="color:#f0f0f0">{to_name}</strong>,<br>
      Verify your email to activate your account and gain access to GEO ARTEMIS systems.</p>
      <a href="{verify_url}" class="btn">&#9654; VERIFY EMAIL</a>
      <div class="url">{verify_url}</div>
      <div class="footer">Link expires in {TOKEN_EXPIRY_HOURS} hours &nbsp;///&nbsp; If you did not register, ignore this email.</div>
    </div>
  </div>
</body>
</html>
"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, to_email, msg.as_string())


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/")
def home(request: Request):
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


# ── Register ───────────────────────────────────────────────────────────────────

@router.get("/register")
def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/register")
def register(
    request: Request,
    name: str             = Form(...),
    email: str            = Form(...),
    password: str         = Form(...),
    confirm_password: str = Form(...),
):
    email = email.strip().lower()
    name  = name.strip()

    if len(password) < 8:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "PASSWORD MUST BE AT LEAST 8 CHARACTERS",
        })

    if password != confirm_password:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "PASSWORDS DO NOT MATCH",
        })

    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT id, is_verified FROM users WHERE email = ?", (email,)
        ).fetchone()

        if existing:
            if existing["is_verified"]:
                # Already a fully verified account — just tell them to log in
                return templates.TemplateResponse("register.html", {
                    "request": request,
                    "error": "EMAIL ALREADY REGISTERED — SIGN IN INSTEAD",
                })
            else:
                # ── Unverified account: update name/password and resend email ──
                # This lets someone who mistyped their password during first
                # registration, or never received the email, try again cleanly.
                password_hash = hash_password(password)
                conn.execute(
                    "UPDATE users SET name = ?, password_hash = ? WHERE id = ?",
                    (name, password_hash, existing["id"]),
                )
                conn.commit()
                user_id = existing["id"]
        else:
            password_hash = hash_password(password)
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash, is_verified) VALUES (?, ?, ?, 0)",
                (name, email, password_hash),
            )
            user_id = cursor.lastrowid
            conn.commit()

    except Exception as e:
        print(f"[Register] DB error: {e}\n{traceback.format_exc()}")
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "SYSTEM ERROR — PLEASE TRY AGAIN",
        })
    finally:
        conn.close()

    try:
        token = create_verification_token(user_id)
        send_verification_email(email, name, token)
    except Exception as e:
        print(f"[Register] Email error: {e}\n{traceback.format_exc()}")

    return templates.TemplateResponse("verify_email.html", {
        "request": request,
        "email": email,
    })


# ── Email Verification ─────────────────────────────────────────────────────────

@router.get("/verify-email")
def verify_email(request: Request, token: str = ""):
    if not token:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "INVALID VERIFICATION LINK",
            "message": None,
        })

    user_id = consume_verification_token(token)
    if not user_id:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "LINK EXPIRED OR ALREADY USED — REQUEST A NEW ONE",
            "message": None,
        })

    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "message": "EMAIL VERIFIED — YOU CAN NOW SIGN IN",
    })


# ── Resend Verification ────────────────────────────────────────────────────────

@router.post("/resend-verification")
def resend_verification(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    conn = get_db_connection()
    try:
        user = conn.execute(
            "SELECT id, name, is_verified FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()

    if user and not user["is_verified"]:
        try:
            token = create_verification_token(user["id"])  # old tokens auto-invalidated
            send_verification_email(email, user["name"], token)
        except Exception as e:
            print(f"[Resend] Email error: {e}\n{traceback.format_exc()}")

    return templates.TemplateResponse("verify_email.html", {
        "request": request,
        "email": email,
    })


# ── Login ──────────────────────────────────────────────────────────────────────

@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "message": None,
    })


@router.post("/login")
def login(
    request: Request,
    email: str    = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()

    conn = get_db_connection()
    try:
        user = conn.execute(
            "SELECT id, name, password_hash, is_verified FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()

    BAD_CREDS = "INVALID EMAIL OR PASSWORD"

    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": BAD_CREDS,
            "message": None,
        })

    if not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": BAD_CREDS,
            "message": None,
        })

    if not user["is_verified"]:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "EMAIL NOT VERIFIED — CHECK YOUR INBOX OR RESEND",
            "message": None,
        })

    request.session["user_id"]     = user["id"]
    request.session["name"]        = user["name"]
    request.session["is_verified"] = True

    return RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)


# ── Logout ─────────────────────────────────────────────────────────────────────

@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


# ── Init ───────────────────────────────────────────────────────────────────────

ensure_tables()