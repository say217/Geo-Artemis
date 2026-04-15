import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import bcrypt
import mysql.connector
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)

SECRET_KEY = os.getenv("SECRET_KEY", "")

DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = get_env_int("MYSQL_PORT", 3306)
DB_USER = os.getenv("MYSQL_USER", "admin")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "admin")
DB_NAME = os.getenv("MYSQL_DATABASE", "admin")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = get_env_int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_SENDER = os.getenv("SMTP_SENDER", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
VERIFY_TOKEN_TTL_MINUTES = get_env_int("VERIFY_CODE_EXP_MINUTES", 10)


def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def ensure_tables():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                is_verified TINYINT(1) NOT NULL DEFAULT 0,
                verification_code VARCHAR(10),
                code_expires_at DATETIME
            )
            """
        )
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'verification_code'
            """,
            (DB_NAME,),
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE users ADD COLUMN verification_code VARCHAR(10)")

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'code_expires_at'
            """,
            (DB_NAME,),
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE users ADD COLUMN code_expires_at DATETIME")
        conn.commit()
    finally:
        conn.close()


def send_verification_email(recipient_email: str, code: str) -> str | None:
    if not SMTP_USER or not SMTP_PASSWORD:
        return "SMTP credentials are missing. Set SMTP_USER and SMTP_PASSWORD."

    message = EmailMessage()
    message["Subject"] = "Geo Artemis - Verify Your Account"
    message["From"] = SMTP_SENDER or SMTP_USER
    message["To"] = recipient_email
    message.set_content(
        f"Welcome to Geo Artemis.\n\n"
        f"To verify your account, use the code: {code}\n\n"
        f"This code expires in 24 hours.\n\n"
        f"If you did not create this account, please ignore this email.\n\n"
        f"— Geo Artemis Security Team"
    )

    html = f"""
    <html><body style="margin:0;padding:0;background:#0a0a0e;">
      <div style="background:#0a0a0e;padding:28px 12px;font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:#e5e5e5;">
        <div style="max-width:540px;margin:0 auto;border:1px solid #ff4444;border-radius:2px;background:#0f0f14;box-shadow:0 0 24px rgba(255,68,68,0.2);overflow:hidden;">
          <!-- Header -->
          <div style="padding:18px 24px;border-bottom:1px solid rgba(255,68,68,0.3);background:linear-gradient(135deg,#0a0a0e 0%,#0f0f14 100%);">
            <div style="color:#ff4444;font-size:11px;letter-spacing:3px;text-transform:uppercase;font-weight:600;margin:0;">SECURITY VERIFICATION</div>
            <div style="font-size:18px;color:#ffffff;font-weight:300;margin:6px 0 0 0;letter-spacing:1px;">Account Verification Required</div>
          </div>
          <!-- Content -->
          <div style="padding:24px;">
            <p style="margin:0 0 14px 0;color:#d0d0d8;font-size:14px;line-height:1.6;">Welcome to Geo Artemis. To complete your account setup and access our hazard intelligence network, please verify your email address using the code below.</p>
            <div style="margin:20px 0;padding:1px;background:linear-gradient(90deg,#ff4444 0%,rgba(255,68,68,0.4) 100%);border-radius:1px;">
              <div style="padding:16px;background:#0f0f14;text-align:center;">
                <div style="font-size:11px;color:#9a9a9e;letter-spacing:2px;text-transform:uppercase;margin:0 0 8px 0;">Your Verification Code</div>
                <div style="font-size:28px;color:#ffffff;letter-spacing:8px;font-weight:bold;font-family:'Courier New',monospace;margin:0;">{code}</div>
              </div>
            </div>
            <p style="margin:14px 0 0 0;color:#9a9a9e;font-size:12px;line-height:1.5;"><strong>Note:</strong> This code expires in 24 hours. If you did not request this verification, please disregard this message or contact our support team.</p>
          </div>
          <!-- Footer -->
          <div style="padding:12px 24px;border-top:1px solid rgba(255,68,68,0.2);background:#0a0a0e;color:#7a7a82;font-size:10px;line-height:1.5;">
            <div style="margin:0;">Geo Artemis Security Layer | Protected Network</div>
            <div style="margin:4px 0 0 0;">Questions? Visit our support portal or reply to this email.</div>
          </div>
        </div>
      </div>
    </body></html>
    """
    message.add_alternative(html, subtype="html")

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)

    return None


def send_welcome_email(recipient_email: str) -> str | None:
    if not SMTP_USER or not SMTP_PASSWORD:
        return "SMTP credentials are missing. Set SMTP_USER and SMTP_PASSWORD."

    message = EmailMessage()
    message["Subject"] = "Geo Artemis - Welcome to the Network"
    message["From"] = SMTP_SENDER or SMTP_USER
    message["To"] = recipient_email
    message.set_content(
        "Welcome to Geo Artemis.\n\n"
        "Your account has been verified and is now active.\n\n"
        "You can now access the live hazard intelligence dashboard to:\n"
        "• Monitor global disaster events in real-time\n"
        "• View hazard clustering and hotspot analysis\n"
        "• Access advanced predictive analytics\n"
        "• Set up custom alerts and notifications\n\n"
        "Log in now: https://artemis.example.com/app1/\n\n"
        "Thank you for joining Geo Artemis.\n"
        "— The Geo Artemis Team"
    )

    html = """
    <html><body style="margin:0;padding:0;background:#0a0a0e;">
      <div style="background:#0a0a0e;padding:28px 12px;font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:#e5e5e5;">
        <div style="max-width:540px;margin:0 auto;border:1px solid #ff4444;border-radius:2px;background:#0f0f14;box-shadow:0 0 24px rgba(255,68,68,0.2);overflow:hidden;">
          <!-- Header -->
          <div style="padding:18px 24px;border-bottom:1px solid rgba(255,68,68,0.3);background:linear-gradient(135deg,#0a0a0e 0%,#0f0f14 100%);">
            <div style="color:#ff4444;font-size:11px;letter-spacing:3px;text-transform:uppercase;font-weight:600;margin:0;">✓ ACCESS CONFIRMED</div>
            <div style="font-size:18px;color:#ffffff;font-weight:300;margin:6px 0 0 0;letter-spacing:1px;">Welcome to Geo Artemis</div>
          </div>
          <!-- Content -->
          <div style="padding:24px;">
            <p style="margin:0 0 16px 0;color:#d0d0d8;font-size:14px;line-height:1.6;">Your account is now verified and active. Welcome to the Geo Artemis hazard intelligence network. You now have full access to real-time global disaster monitoring, predictive analytics, and advanced event intelligence.</p>
            
            <div style="margin:18px 0;padding:12px 16px;border-left:3px solid #ff4444;background:rgba(255,68,68,0.08);">
              <div style="color:#ff4444;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px 0;">What You Can Do Now</div>
              <ul style="margin:0;padding:0 0 0 18px;color:#c0c0c8;font-size:13px;line-height:1.7;">
                <li>Monitor live global hazard events 24/7</li>
                <li>Access historical data and event clustering analysis</li>
                <li>View AI-powered predictive maps and models</li>
                <li>Download reports and visualizations</li>
                <li>Configure custom alerts for regions of interest</li>
              </ul>
            </div>
            
            <div style="margin:18px 0;padding:0;">
              <p style="margin:0 0 10px 0;color:#d0d0d8;font-size:14px;line-height:1.6;">Get started now by logging into the dashboard:</p>
              <div style="padding:12px 16px;background:linear-gradient(135deg,#ff4444 0%,rgba(255,68,68,0.7) 100%);border-radius:1px;text-align:center;">
                <a href="https://artemis.example.com/app1/" style="color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;letter-spacing:1px;text-transform:uppercase;">Open Dashboard &#x2192;</a>
              </div>
            </div>
            
            <p style="margin:16px 0 0 0;color:#9a9a9e;font-size:12px;line-height:1.5;">If you have any questions or need assistance, our support team is available 24/7.</p>
          </div>
          <!-- Footer -->
          <div style="padding:12px 24px;border-top:1px solid rgba(255,68,68,0.2);background:#0a0a0e;color:#7a7a82;font-size:10px;line-height:1.5;">
            <div style="margin:0;">Geo Artemis Network | Global Hazard Intelligence</div>
            <div style="margin:4px 0 0 0;">Secure. Real-time. Predictive. | Your trusted source for disaster awareness.</div>
          </div>
        </div>
      </div>
    </body></html>
    """
    message.add_alternative(html, subtype="html")

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)

    return None

@router.get("/")
def home(request: Request):
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/signup")
def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@router.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE email = %s OR username = %s", (email, username))
        if cursor.fetchone():
            return templates.TemplateResponse(
                "signup.html",
                {"request": request, "error": "Email or username already exists."},
            )

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        verification_code = f"{secrets.randbelow(1000000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=VERIFY_TOKEN_TTL_MINUTES)

        cursor.execute(
            """
            INSERT INTO users (email, username, password_hash, is_verified, verification_code, code_expires_at)
            VALUES (%s, %s, %s, 0, %s, %s)
            """,
            (email, username, password_hash, verification_code, expires_at),
        )
        conn.commit()
    finally:
        conn.close()

    error = send_verification_email(email, verification_code)
    if error:
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "error": error, "email": email},
        )

    return templates.TemplateResponse(
        "verify.html",
        {"request": request, "email": email, "message": "Verification code sent."},
    )


@router.get("/verify")
def verify_form(request: Request, email: str | None = None):
    return templates.TemplateResponse(
        "verify.html",
        {"request": request, "email": email},
    )


@router.post("/verify")
def verify_account(request: Request, email: str = Form(...), code: str = Form(...)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, code_expires_at, is_verified, verification_code
            FROM users
            WHERE email = %s
            """,
            (email,),
        )
        user = cursor.fetchone()

        if not user:
            return templates.TemplateResponse(
                "verify.html",
                {"request": request, "error": "Email not found.", "email": email},
            )

        if user["is_verified"]:
            request.session["user_id"] = user["id"]
            request.session["is_verified"] = True
            return RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)

        if user["code_expires_at"] and user["code_expires_at"] < datetime.utcnow():
            return templates.TemplateResponse(
                "verify.html",
                {"request": request, "error": "Verification code has expired.", "email": email},
            )

        if user["verification_code"] != code:
            return templates.TemplateResponse(
                "verify.html",
                {"request": request, "error": "Invalid verification code.", "email": email},
            )

        cursor.execute(
            """
            UPDATE users
            SET is_verified = 1, verification_code = NULL, code_expires_at = NULL
            WHERE id = %s
            """,
            (user["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    request.session["user_id"] = user["id"]
    request.session["is_verified"] = True
    return RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, password_hash, is_verified FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
    finally:
        conn.close()

    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."},
        )

    if not user["is_verified"]:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Please verify your email before logging in.",
                "email": email,
            },
        )

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."},
        )

    request.session["user_id"] = user["id"]
    request.session["is_verified"] = True
    send_welcome_email(email)
    response = RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)
    return response


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


ensure_tables()



