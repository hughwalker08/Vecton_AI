"""
Entry point for the Vecton AI Construction Compliance Assistant backend.

This is a skeleton only — no business logic is implemented yet.
Run locally with:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import chat, upload, health

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-powered assistant for NSW construction compliance research (NCC 2025 Vol. 2 + ABCB Housing Provisions).",
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


@app.get("/")
def root():
    return {"message": f"{settings.PROJECT_NAME} API is running."}
