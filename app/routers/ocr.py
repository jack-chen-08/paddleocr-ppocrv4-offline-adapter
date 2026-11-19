"""OCR 接口路由。

POST /api/ocr/contracts/{contract_id}/pages/{page_no}  上传页面图片，返回行级结果
GET  /api/ocr/contracts/{contract_id}/pages/{page_no}  读回已落盘的 OCR JSON
GET  /api/ocr/engine                                   引擎元信息（离线自检用）
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.ocr.deps import get_service, session_factory

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

MAX_PAGE_BYTES = 20 * 1024 * 1024


@router.get("/engine")
def engine_info() -> dict:
    return {
        "interface": "OcrEngine.recognize(page_image) -> OcrPage",
        "engine": get_service().engine.name,
        "offline": True,
        "cloud_ocr": False,
    }


@router.post("/contracts/{contract_id}/pages/{page_no}")
async def recognize_page(contract_id: str, page_no: int, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="EMPTY_FILE")
    if len(data) > MAX_PAGE_BYTES:
        raise HTTPException(status_code=413, detail="PAGE_TOO_LARGE")
    service = get_service()
    with session_factory()() as session:
        result = service.recognize(contract_id, page_no, data, session=session)
        session.commit()
    body = result.page.to_dict()
    body["object_key"] = result.object_key
    body["review_item"] = result.review_item
    return body


@router.get("/contracts/{contract_id}/pages/{page_no}")
def read_page(contract_id: str, page_no: int) -> dict:
    return get_service().load_page(contract_id, page_no)
