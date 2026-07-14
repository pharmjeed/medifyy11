"""بيئة Alembic — الهجرات تعمل بدور المالك (migrations_database_url أو DATABASE_URL)."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    s = get_settings()
    return (
        os.environ.get("MIGRATIONS_DATABASE_URL")
        or s.migrations_database_url
        or os.environ.get("DATABASE_URL")
        or s.database_url
    )


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
