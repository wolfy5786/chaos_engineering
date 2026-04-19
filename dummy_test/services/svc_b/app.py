"""Leaf FastAPI service — no downstream calls."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="dummy svc-b", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "svc-b"}


@app.get("/leaf")
def leaf() -> dict[str, str]:
    return {"service": "svc-b", "role": "leaf"}
