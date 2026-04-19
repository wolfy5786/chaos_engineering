"""Auth FastAPI service — signup/login via Supabase Auth (email + password).

Passwords are logged intentionally for this lab playbook; never do this in production.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from supabase import Client, create_client

_AUTH_DIR = Path(__file__).resolve().parent
_ENV_FILE = _AUTH_DIR / ".env"
if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("auth")

app = FastAPI(title="dummy auth", version="0.1.0")


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


def _env_required(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = _env_required("SUPABASE_URL")
        key = _env_required("SUPABASE_KEY")
        logger.info("Initializing Supabase client (url present=%s)", bool(url))
        _client = create_client(url, key)
        logger.info("Supabase client ready")
    return _client


def _dump_model(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return {"repr": repr(obj)}


@app.on_event("startup")
def _startup() -> None:
    logger.info(
        "Auth service starting; SUPABASE_URL set=%s SUPABASE_KEY set=%s",
        bool(os.environ.get("SUPABASE_URL")),
        bool(os.environ.get("SUPABASE_KEY")),
    )


@app.get("/health")
def health() -> dict[str, str]:
    logger.info("GET /health")
    return {"status": "ok", "service": "auth"}


@app.post("/signup")
def signup(body: Credentials) -> JSONResponse:
    # Deliberately insecure: log credentials for lab visibility (not for production).
    logger.info(
        "POST /signup step=request_received email=%s password=%s",
        body.email,
        body.password,
    )
    try:
        supabase = get_supabase()
    except RuntimeError as e:
        logger.info("POST /signup step=config_error email=%s password=%s err=%s", body.email, body.password, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    logger.info("POST /signup step=calling_supabase_sign_up email=%s password=%s", body.email, body.password)
    try:
        response = supabase.auth.sign_up(
            {"email": body.email, "password": body.password},
        )
    except Exception as e:
        logger.info(
            "POST /signup step=supabase_error email=%s password=%s error=%s",
            body.email,
            body.password,
            e,
            exc_info=True,
        )
        detail = getattr(e, "message", str(e))
        code = getattr(e, "status", None)
        status = int(code) if code and str(code).isdigit() else 400
        raise HTTPException(status_code=status, detail=detail) from e

    logger.info(
        "POST /signup step=supabase_success email=%s password=%s user_present=%s session_present=%s",
        body.email,
        body.password,
        response.user is not None,
        response.session is not None,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "user": _dump_model(response.user),
        "session": _dump_model(response.session),
    }
    logger.info("POST /signup step=response_ready email=%s password=%s", body.email, body.password)
    return JSONResponse(status_code=201, content=payload)


@app.post("/login")
def login(body: Credentials) -> JSONResponse:
    logger.info(
        "POST /login step=request_received email=%s password=%s",
        body.email,
        body.password,
    )
    try:
        supabase = get_supabase()
    except RuntimeError as e:
        logger.info("POST /login step=config_error email=%s password=%s err=%s", body.email, body.password, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    logger.info("POST /login step=calling_supabase_sign_in email=%s password=%s", body.email, body.password)
    try:
        response = supabase.auth.sign_in_with_password(
            {"email": body.email, "password": body.password},
        )
    except Exception as e:
        logger.info(
            "POST /login step=supabase_error email=%s password=%s error=%s",
            body.email,
            body.password,
            e,
            exc_info=True,
        )
        detail = getattr(e, "message", str(e))
        code = getattr(e, "status", None)
        status = int(code) if code and str(code).isdigit() else 401
        if status < 400 or status >= 600:
            status = 401
        raise HTTPException(status_code=status, detail=detail) from e

    logger.info(
        "POST /login step=supabase_success email=%s password=%s session_present=%s",
        body.email,
        body.password,
        response.session is not None,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "user": _dump_model(response.user),
        "session": _dump_model(response.session),
    }
    logger.info("POST /login step=response_ready email=%s password=%s", body.email, body.password)
    return JSONResponse(status_code=200, content=payload)
