"""doc_contract_page：合同页 OCR 结果索引表。

业务表统一字段：id(UUID) / org_id / site_id / created_at / created_by /
updated_at / deleted_at（软删除）；金额以「分」存整数（本表无金额字段）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DocContractPage(Base):
    __tablename__ = "doc_contract_page"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), index=True)
    site_id: Mapped[str | None] = mapped_column(String(36), index=True)
    contract_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_object_key: Mapped[str | None] = mapped_column(String(512))
    ocr_object_key: Mapped[str | None] = mapped_column(String(512))
    ocr_engine: Mapped[str | None] = mapped_column(String(64))
    ocr_line_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_avg_confidence: Mapped[float | None] = mapped_column(Float)
    ocr_status: Mapped[str] = mapped_column(String(16), default="recognized")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
