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
    message["Subject"] = "Verify your account"
    message["From"] = SMTP_SENDER or SMTP_USER
    message["To"] = recipient_email
    message.set_content(
        "Use the verification code below to verify your account:\n\n"
        f"{code}\n\n"
        "If you did not sign up, you can ignore this email."
    )

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
    response = RedirectResponse(url="/app1/", status_code=status.HTTP_303_SEE_OTHER)
    return response


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)


ensure_tables()



