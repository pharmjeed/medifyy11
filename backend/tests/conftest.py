"""تهيئة الاختبارات — عنقود PostgreSQL حقيقي (RLS/triggers لا تُختبر على SQLite).

- التطبيق يتصل بدور medify_app (خاضع لكل سياسات RLS) — كما في الإنتاج.
- الهجرات والبذر بدور المالك medify_owner.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = os.environ.get("TEST_PG_PORT", "5544")
TEST_DB = os.environ.get("TEST_PG_DB", "medify_pytest")
OWNER_URL = f"postgresql+psycopg://medify_owner@{PG_HOST}:{PG_PORT}"
APP_URL = f"postgresql+psycopg://medify_app:medify_app@{PG_HOST}:{PG_PORT}"

# تُضبط قبل استيراد app.config (lru_cache)
os.environ.update({
    "DATABASE_URL": f"{APP_URL}/{TEST_DB}",
    "MIGRATIONS_DATABASE_URL": f"{OWNER_URL}/{TEST_DB}",
    "ENVIRONMENT": "dev",
    "LLM_ENGINE": "mock",
    "STT_ENGINE": "mock",
    "INTEGRATION_ENGINE": "mock",
    "EMAIL_ENGINE": "mock",
    "RATE_LIMIT_DEFAULT": "100000",
    "RATE_LIMIT_AI": "100000",
    "RECORDINGS_DIR": str(BACKEND / "var" / "test-recordings"),
    "OUTBOX_DIR": str(BACKEND / "var" / "test-outbox"),
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def _bootstrap_database() -> None:
    admin_engine = create_engine(f"{OWNER_URL}/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :db AND pid <> pg_backend_pid()"
        ), {"db": TEST_DB})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}" OWNER medify_owner'))
    admin_engine.dispose()

    env = os.environ.copy()
    python = sys.executable
    subprocess.run([python, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    subprocess.run([python, str(REPO / "scripts" / "seed.py")], cwd=BACKEND, env=env, check=True,
                   capture_output=True)


_bootstrap_database()

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, facility: str, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={
        "facility": facility, "username": username, "password": password,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    return _login(client, "1010456789", "admin", "Admin@12345")


@pytest.fixture(scope="session")
def doctor_token(client) -> str:
    """د. أحمد الغامدي — منشأة 1."""
    return _login(client, "1010456789", "dr.ahmad", "Doctor@12345")


@pytest.fixture(scope="session")
def doctor2_same_facility_token(client) -> str:
    """د. نورة القحطاني — نفس المنشأة، دكتورة أخرى (اختبار عزل الدكاترة)."""
    return _login(client, "1010456789", "dr.noura", "Doctor@12345")


@pytest.fixture(scope="session")
def foreign_admin_token(client) -> str:
    """أدمن المنشأة الثانية (اختبار عزل المنشآت)."""
    return _login(client, "2020987654", "admin", "Admin@12345")


@pytest.fixture(scope="session")
def foreign_doctor_token(client) -> str:
    return _login(client, "2020987654", "dr.salem", "Doctor@12345")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def owner_engine():
    engine = create_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine():
    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()
