"""
Shared pytest fixtures for the backend test suite.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import glossary


@pytest.fixture()
def client() -> TestClient:
    """A FastAPI test client wired to the real app, no network/DB calls made."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _empty_glossary():
    """services/glossary.py reads definitions from the DB on first use --
    preload an empty glossary so no test makes that query. Glossary tests
    set their own terms on top of this."""
    glossary._set_terms({})
    yield
    glossary._set_terms({})
