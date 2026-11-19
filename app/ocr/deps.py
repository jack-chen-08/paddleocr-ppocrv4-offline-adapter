"""OCR 引擎注入与数据库会话（最小装配，供 router 使用）。"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ocr.models import Base
from app.ocr.paddle_engine import PaddleOcrEngine
from app.ocr.service import OcrService
from app.ocr.storage import LocalObjectStore


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite+pysqlite:///./var/ocr.db")


def _ocr_root() -> str:
    return os.getenv("OCR_OBJECT_ROOT", "./var/objects")


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker[Session]:
    url = _database_url()
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@lru_cache(maxsize=1)
def get_service() -> OcrService:
    engine = PaddleOcrEngine(lang=os.getenv("OCR_LANG", "ch"))
    store = LocalObjectStore(_ocr_root())
    return OcrService(engine=engine, store=store)
