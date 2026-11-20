"""离线权重解析的 fail-closed 行为（对应返工意见 #1/#2）。

用真实文件系统验证：权重目录缺失、只有 .lock 空壳、缺 inference.pdiparams 时，
必须在 PaddleOCR 初始化之前抛出 ModelWeightsMissing，绝不允许回落到默认缓存联网下载。
"""
from __future__ import annotations

import pytest

from app.ocr.paddle_engine import ModelWeightsMissing, PaddleOcrEngine, resolve_model_dir

DET_KEYS = ("inference.pdiparams", "inference.json")


def _make_model_dir(root, name="PP-OCRv4_mobile_det", *, graph=True, params=True):
    d = root / name
    d.mkdir(parents=True)
    if graph:
        (d / "inference.json").write_text("{}", encoding="utf-8")
    if params:
        (d / "inference.pdiparams").write_bytes(b"weights")
    return d


def test_missing_dir_raises(tmp_path):
    with pytest.raises(ModelWeightsMissing) as exc:
        resolve_model_dir("PADDLE_OCR_DET_MODEL_DIR", "PP-OCRv4_mobile_det", tmp_path / "not_here")
    assert "已拒绝回落到在线下载" in str(exc.value)


def test_lock_only_dir_is_incomplete(tmp_path):
    """干净克隆下的空壳目录（只有 .lock）必须被判为不完整，而不是交给 PaddleOCR。"""
    d = tmp_path / "PP-OCRv4_mobile_det"
    d.mkdir()
    (d / "abc.lock").write_text("", encoding="utf-8")
    with pytest.raises(ModelWeightsMissing) as exc:
        resolve_model_dir("PADDLE_OCR_DET_MODEL_DIR", "PP-OCRv4_mobile_det", d)
    assert "inference.pdiparams" in str(exc.value)
    assert "拒绝联网下载" in str(exc.value)


def test_missing_params_raises(tmp_path):
    d = _make_model_dir(tmp_path, params=False)
    with pytest.raises(ModelWeightsMissing):
        resolve_model_dir("PADDLE_OCR_DET_MODEL_DIR", "PP-OCRv4_mobile_det", d)


def test_complete_dir_accepted(tmp_path):
    d = _make_model_dir(tmp_path)
    assert resolve_model_dir("PADDLE_OCR_DET_MODEL_DIR", "PP-OCRv4_mobile_det", d) == d


def test_engine_init_fails_before_paddleocr(monkeypatch, tmp_path):
    """构造引擎时权重缺失 → 直接抛错（早于 import paddleocr），不会静默联网。"""
    monkeypatch.setenv("PADDLE_OCR_DET_MODEL_DIR", str(tmp_path / "absent"))
    monkeypatch.delenv("PADDLE_OCR_CLS_MODEL_DIR", raising=False)
    with pytest.raises(ModelWeightsMissing):
        PaddleOcrEngine(lang="ch")
