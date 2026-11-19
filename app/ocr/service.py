"""OCR 编排层：识别 -> 落对象存储 -> 回写索引表 -> 进人工核对队列。

业务边界（任务原文）：
  * OCR 结果只是字段抽取的中间数据；
  * 抽出的字段一律进入人工核对（复核）队列，确认前不写业务数据、不得直接对外发送；
  * OCR 与 AI 都不计算金额。
本模块只做识别与落盘，不计算金额、不写合同业务字段。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ocr.models import DocContractPage
from app.ocr.storage import ObjectStore, store_page
from app.ocr.types import OcrEngine, OcrPage


@dataclass
class RecognizeResult:
    page: OcrPage
    object_key: str
    review_item: dict


class OcrService:
    def __init__(self, engine: OcrEngine, store: ObjectStore) -> None:
        self.engine = engine
        self.store = store

    def recognize(
        self,
        contract_id: str,
        page_no: int,
        image_bytes: bytes,
        session: Session | None = None,
        org_id: str | None = None,
        site_id: str | None = None,
        created_by: str | None = None,
    ) -> RecognizeResult:
        page = self.engine.recognize(image_bytes, page_no=page_no)
        key = store_page(self.store, contract_id, page)

        if session is not None:
            row = session.execute(
                select(DocContractPage).where(
                    DocContractPage.contract_id == contract_id,
                    DocContractPage.page_no == page_no,
                    DocContractPage.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                row = DocContractPage(
                    id=str(uuid.uuid4()),
                    contract_id=contract_id,
                    page_no=page_no,
                    created_by=created_by,
                )
                session.add(row)
            row.org_id = org_id
            row.site_id = site_id
            row.ocr_object_key = key
            row.ocr_engine = page.engine
            row.ocr_line_count = len(page.lines)
            row.ocr_avg_confidence = round(page.avg_confidence, 4)
            row.ocr_status = "recognized"
            row.updated_at = datetime.now(timezone.utc)
            session.flush()

        review_item = {
            "contract_id": contract_id,
            "page_no": page_no,
            "ocr_object_key": key,
            "avg_confidence": round(page.avg_confidence, 4),
            "line_count": len(page.lines),
            "stamp_overlap_line_count": len(page.stamp_overlap_lines),
            "queue": "manual_review",
            "status": "pending_review",
            "amount_computed": False,
        }
        return RecognizeResult(page=page, object_key=key, review_item=review_item)

    def load_page(self, contract_id: str, page_no: int) -> dict:
        from app.ocr.storage import ocr_object_key

        return self.store.get_json(ocr_object_key(contract_id, page_no))
