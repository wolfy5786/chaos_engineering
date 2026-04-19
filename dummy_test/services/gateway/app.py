"""Gateway FastAPI service — entrypoint; calls svc-a over HTTP; proxies auth."""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("gateway")

app = FastAPI(title="dummy gateway", version="0.1.0")

SVC_A_URL = os.environ.get("SVC_A_URL", "http://127.0.0.1:8001").rstrip("/")
AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://127.0.0.1:8003").rstrip("/")


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
