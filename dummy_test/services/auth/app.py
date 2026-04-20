"""Auth FastAPI service — signup/login via Supabase Auth (email + password).

Passwords are logged intentionally for this lab playbook; never do this in production.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
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

# #region agent log
def _agent_debug_log_path() -> Path:
    env = os.environ.get("DEBUG_AGENT_LOG", "").strip()
    if env:
        return Path(env)
    f = Path(__file__).resolve()
    if len(f.parents) > 3:
        return f.parents[3] / "debug-7388ce.log"
    return Path.cwd() / "debug-7388ce.log"


_AGENT_DEBUG_LOG = _agent_debug_log_path()


def _agent_debug_ndjson(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
    *,
    run_id: str = "pre-fix",
) -> None:
    payload = {
        "sessionId": "7388ce",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_AGENT_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError:
        pass


class _AgentRequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        _agent_debug_ndjson(
            "A",
            "app.py:_AgentRequestLogMiddleware",
            "incoming",
            {"method": request.method, "path": request.url.path},
        )
        response = await call_next(request)
        _agent_debug_ndjson(
            "A",
            "app.py:_AgentRequestLogMiddleware",
            "outgoing",
            {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )
        return response


app.add_middleware(_AgentRequestLogMiddleware)
# #endregion


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
    # #region agent log
    _agent_debug_ndjson(
        "B",
        "app.py:_startup",
        "auth_app_started",
        {"log_file": str(_AGENT_DEBUG_LOG)},
    )
    # #endregion
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
@app.post("/auth/signup")
def signup(body: Credentials) -> JSONResponse:
    # #region agent log
    _agent_debug_ndjson(
        "C",
        "app.py:signup",
        "signup_handler_entered",
        {"path": "/signup"},
    )
    # #endregion
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
@app.post("/auth/login")
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
