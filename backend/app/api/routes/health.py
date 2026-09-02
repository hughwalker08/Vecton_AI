from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    """Basic liveness check."""
    return {"status": "ok"}
