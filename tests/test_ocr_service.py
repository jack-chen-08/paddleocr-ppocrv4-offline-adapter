"""编排层契约：识别 -> 对象存储 -> 索引表回写 -> 人工核对队列。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ocr.mock_engine import MockOcrEngine
from app.ocr.models import Base, DocContractPage
from app.ocr.service import OcrService
from app.ocr.storage import LocalObjectStore, ocr_object_key


@pytest.fixture()
def env(tmp_path):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    store = LocalObjectStore(tmp_path / "objects")
    return OcrService(engine=MockOcrEngine(), store=store), store, Session


def test_recognize_writes_object_and_review_item(env):
    service, store, _ = env
    res = service.recognize("C-001", 3, b"\x89PNG fake")

    assert res.object_key == "ocr/C-001/3.json"
    payload = store.get_json(res.object_key)
    assert payload["page_no"] == 3
    assert payload["engine"] == "mock"
    assert len(payload["lines"]) == 3
    assert payload["lines"][2]["stamp_overlap"] is True  # 遮挡标记原样落盘

    item = res.review_item
    assert item["queue"] == "manual_review"
    assert item["status"] == "pending_review"   # 一律进人工核对队列
    assert item["amount_computed"] is False     # OCR 不计算金额
    assert item["stamp_overlap_line_count"] == 1


def test_db_row_written_when_session_given(env):
    service, _, Session = env
    with Session() as s:
        res = service.recognize("C-002", 1, b"img", session=s, org_id="org-9", created_by="u-1")
        s.commit()
        row = s.query(DocContractPage).filter_by(contract_id="C-002", page_no=1).one()
        assert row.ocr_object_key == res.object_key
        assert row.ocr_engine == "mock"
        assert row.ocr_line_count == 3
        assert row.ocr_avg_confidence == pytest.approx(res.page.avg_confidence, abs=1e-4)
        assert row.ocr_status == "recognized"
        assert row.org_id == "org-9"


def test_repeat_recognize_is_idempotent_per_page(env):
    service, _, Session = env
    with Session() as s:
        service.recognize("C-003", 1, b"img", session=s)
        service.recognize("C-003", 1, b"img", session=s)
        s.commit()
        assert s.query(DocContractPage).filter_by(contract_id="C-003", page_no=1).count() == 1


def test_object_key_layout():
    assert ocr_object_key("C-9", 12) == "ocr/C-9/12.json"


def test_object_key_rejects_bad_input():
    for bad in ("", "a/b", "../etc"):
        with pytest.raises(ValueError):
            ocr_object_key(bad, 1)
    with pytest.raises(ValueError):
        ocr_object_key("C-1", 0)


def test_local_store_roundtrip(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put_json("ocr/a/1.json", {"ok": True})
    assert store.get_json("ocr/a/1.json") == {"ok": True}
    assert json.loads((tmp_path / "ocr/a/1.json").read_text()) == {"ok": True}
