"""
Entry point for the Vecton AI Construction Compliance Assistant backend.

This is a skeleton only — no business logic is implemented yet.
Run locally with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, compliance, health, upload
from app.core.config import settings



@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Every plain `def` route (chat, compliance, health, ...) runs on a worker
    # thread, and Starlette shares one pool of them, 40 by default. A chat
    # request holds its thread for the whole embed -> search -> rerank -> LLM
    # round trip (seconds, nearly all of it waiting on Gemini/Hugging Face),
    # so 40 simultaneous chats used to fill the pool and queue everything
    # else behind them -- even /health. Waiting threads cost memory, not CPU,
    # so the pool is sized for the concurrency we expect instead.
    anyio.to_thread.current_default_thread_limiter().total_tokens = settings.WORKER_THREADS
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.PROJECT_NAME,
    description=(
        "AI-powered assistant for NSW construction compliance research "
        "(NCC 2025 Vol. 2 + ABCB Housing Provisions)."
    ),
    version="0.1.0",
)

# CORS - wide open for local dev, tighten before deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(compliance.router, prefix="/api/compliance", tags=["compliance"])


@app.get("/")
def root():
    return {"message": f"{settings.PROJECT_NAME} API is running."}
