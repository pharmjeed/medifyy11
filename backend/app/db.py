"""محرك القاعدة وجلسة RLS — العزل يُنفَّذ في قاعدة البيانات (DOC-04 §٧, D-12)."""
from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine = None
_SessionLocal: sessionmaker[Session] | None = None
_system_engine = None
_SystemSessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def _system_session_factory() -> sessionmaker[Session]:
    """محرك النظام (دور المالك — يتجاوز RLS): حصراً للمسارات العامة المكتوبة بعناية
    (login/register/استعادة كلمة المرور/webhook السداد/عامل الرفع/المزامنة) — D-19."""
    global _system_engine, _SystemSessionLocal
    if _system_engine is None:
        s = get_settings()
        url = s.migrations_database_url or s.database_url
        _system_engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
        _SystemSessionLocal = sessionmaker(bind=_system_engine, autoflush=False, expire_on_commit=False)
    assert _SystemSessionLocal is not None
    return _SystemSessionLocal


def get_system_db() -> Generator[Session, None, None]:
    """اعتمادية للمسارات العامة (بلا JWT) — لا تُستخدم في أي نقطة مصادَقة."""
    db = _system_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def system_session() -> Generator[Session, None, None]:
    db = _system_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_rls_context(
    db: Session,
    facility_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None = None,
    role: str | None = None,
) -> None:
    """تضبط متغيرات جلسة RLS داخل المعاملة الحالية (SET LOCAL) — تُستدعى بعد التحقق من JWT."""
    db.execute(text("SELECT set_config('app.facility_id', :f, true)"), {"f": str(facility_id)})
    if user_id is not None:
        db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
    if role is not None:
        db.execute(text("SELECT set_config('app.user_role', :r, true)"), {"r": role})


@contextmanager
def rls_session(
    facility_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None = None,
    role: str | None = None,
) -> Generator[Session, None, None]:
    """جلسة معزولة بمنشأة محددة — للاستخدام خارج دورة الطلب (خطوط المعالجة، مهام الرفع)."""
    db = session_factory()()
    try:
        set_rls_context(db, facility_id, user_id, role)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    """اعتمادية FastAPI — الجلسة بلا سياق RLS (يضبطه deps.authenticated بعد JWT)."""
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
