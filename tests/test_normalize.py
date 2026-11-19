"""全角/半角归一化用例。

口径：数字、括号、冒号、小数点统一为半角（需求原文）；中文句读
（，；。、）与书名号保持原样，避免把中文句子改成半角句点。
"""
from app.ocr.normalize import normalize_text, to_halfwidth


def test_fullwidth_digits_and_punct_become_halfwidth():
    src = "合同总价：９８，０００．００元；分（３）期支付；占比５０％"
    out = to_halfwidth(src)
    assert "98,000.00" in out
    assert "(3)" in out
    assert "50%" in out
    assert "：" not in out  # 冒号统一为半角
    assert "９" not in out


def test_chinese_sentence_punctuation_preserved():
    src = "双方应友好协商；协商不成的，提交仲裁。「附件一」见《服务清单》"
    out = to_halfwidth(src)
    assert "；" in out and "，" in out and "。" in out
    assert "「附件一」" in out and "《服务清单》" in out


def test_normalize_is_idempotent():
    src = "第１０条（保密）——金额９８，０００．００元"
    once = normalize_text(src)
    twice = normalize_text(once)
    assert once == twice


def test_halfwidth_input_unchanged():
    src = "合同编号:HT-2026-003 / 页码 3/10"
    assert normalize_text(src) == src


def test_fullwidth_colon_normalised_in_place():
    assert normalize_text("甲方：星澜产业园") == "甲方:星澜产业园"
