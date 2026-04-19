"""Middle FastAPI service — calls svc-b over HTTP."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI

app = FastAPI(title="dummy svc-a", version="0.1.0")

SVC_B_URL = os.environ.get("SVC_B_URL", "http://127.0.0.1:8002").rstrip("/")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "svc-a"}


@app.get("/forward")
async def forward() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{SVC_B_URL}/leaf")
        r.raise_for_status()
        downstream = r.json()
    return {"service": "svc-a", "downstream": downstream}
