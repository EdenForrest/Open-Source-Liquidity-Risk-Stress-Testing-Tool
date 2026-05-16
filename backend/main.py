"""
FastAPI entry point.

Start (from project root):
    uvicorn backend.main:app --reload --port 8080
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import portfolio, analysis

app = FastAPI(
    title="Liquidity Risk Tool API",
    description="FastAPI wrapper around the liquidity risk analytics backend.",
    version="1.0.0",
)

_cors_origins_env = os.getenv("CORS_ORIGINS", "")
_extra_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
_allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"] + _extra_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
