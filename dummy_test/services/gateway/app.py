"""Gateway FastAPI service — entrypoint; calls svc-a over HTTP; proxies auth."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("gateway")

app = FastAPI(title="dummy gateway", version="0.1.0")

SVC_A_URL = os.environ.get("SVC_A_URL", "http://127.0.0.1:8001").rstrip("/")
AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://127.0.0.1:8003").rstrip("/")

# #region agent log
def _gw_agent_log_path() -> Path:
    env = os.environ.get("DEBUG_AGENT_LOG", "").strip()
    if env:
        return Path(env)
    f = Path(__file__).resolve()
    if len(f.parents) > 3:
        return f.parents[3] / "debug-7388ce.log"
    return Path.cwd() / "debug-7388ce.log"


_GW_AGENT_LOG = _gw_agent_log_path()


def _gw_agent_ndjson(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
) -> None:
    payload = {
        "sessionId": "7388ce",
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload)
    try:
        with open(_GW_AGENT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    logger.info("AGENT_DEBUG7388CE %s", line)


class _GwRequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        _gw_agent_ndjson(
            "D",
            "gateway:middleware",
            "incoming",
            {"method": request.method, "path": request.url.path},
        )
        response = await call_next(request)
        _gw_agent_ndjson(
            "D",
            "gateway:middleware",
            "outgoing",
            {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )
        return response


app.add_middleware(_GwRequestLogMiddleware)


@app.on_event("startup")
def _gw_startup() -> None:
    _gw_agent_ndjson(
        "G",
        "gateway:startup",
        "gateway_started",
        {
            "AUTH_SERVICE_URL": AUTH_SERVICE_URL,
            "SVC_A_URL": SVC_A_URL,
            "log_file": str(_GW_AGENT_LOG),
        },
    )


# #endregion


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@app.get("/chain")
async def chain() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{SVC_A_URL}/forward")
        r.raise_for_status()
        body = r.json()
    return {
        "path": ["gateway", "svc-a", "svc-b"],
        "hop": "gateway",
        "downstream": body,
    }


@app.post("/auth/signup")
async def auth_signup(request: Request) -> JSONResponse:
    body = await request.json()
    email = body.get("email")
    password = body.get("password")
    # Intentional credential logging for this lab only (insecure in production).
    logger.info("POST /auth/signup proxy step=request email=%s password=%s", email, password)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{AUTH_SERVICE_URL}/signup", json=body)
    # #region agent log
    _gw_agent_ndjson(
        "E",
        "gateway:auth_signup",
        "upstream_done",
        {
            "POST_URL": f"{AUTH_SERVICE_URL}/signup",
            "upstream_status": r.status_code,
        },
    )
    # #endregion
    logger.info(
        "POST /auth/signup proxy step=response status=%s email=%s password=%s",
        r.status_code,
        email,
        password,
    )
    try:
        content: dict | list = r.json()
    except Exception:
        content = {"detail": r.text}
    if not isinstance(content, dict):
        content = {"data": content}
    return JSONResponse(status_code=r.status_code, content=content)


@app.post("/auth/login")
async def auth_login(request: Request) -> JSONResponse:
    body = await request.json()
    email = body.get("email")
    password = body.get("password")
    logger.info("POST /auth/login proxy step=request email=%s password=%s", email, password)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{AUTH_SERVICE_URL}/login", json=body)
    # #region agent log
    _gw_agent_ndjson(
        "E",
        "gateway:auth_login",
        "upstream_done",
        {
            "POST_URL": f"{AUTH_SERVICE_URL}/login",
            "upstream_status": r.status_code,
        },
    )
    # #endregion
    logger.info(
        "POST /auth/login proxy step=response status=%s email=%s password=%s",
        r.status_code,
        email,
        password,
    )
    try:
        content: dict | list = r.json()
    except Exception:
        content = {"detail": r.text}
    if not isinstance(content, dict):
        content = {"data": content}
    return JSONResponse(status_code=r.status_code, content=content)
