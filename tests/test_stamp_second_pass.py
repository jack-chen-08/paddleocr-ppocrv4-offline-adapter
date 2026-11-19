"""二次识别（红色抑制）与行合并的单元测试。

背景：page_03 的「乙方（盖章）：沐石供应链有限公司」一行被红章压盖，一次识别在
**检测阶段**就整行丢失（不是识别错字）。补一次 R 通道识别可恢复该行；本文件锁住
这条链路上四个容易回归的点：R 通道视图性质、只收印章附近的行、同行去重、
以及合并后必须按阅读顺序重排。
"""
from __future__ import annotations

import numpy as np

from app.ocr.stamp import (
    StampRegion,
    merge_secondary,
    red_suppressed_view,
)
from app.ocr.types import OcrLine


def _line(text: str, x1: float, y1: float, x2: float, y2: float, conf: float = 0.99) -> OcrLine:
    return OcrLine(text=text, bbox=[(x1, y1), (x2, y1), (x2, y2), (x1, y2)], confidence=conf)


STAMP = StampRegion(x1=520.0, y1=1809.0, x2=821.0, y2=2110.0, area_ratio=0.0183)


# ---------- 红色抑制视图 ----------

def test_red_suppressed_view_turns_stamp_red_into_paper_white():
    """红墨在 R 通道接近纸白：红块变亮，黑字仍暗。"""
    img = np.full((40, 40, 3), 255, dtype=np.uint8)  # 白底
    img[5:15, 5:25] = (40, 40, 200)  # BGR 红章 -> R=200
    img[20:30, 5:25] = (20, 20, 20)  # BGR 黑字 -> R=20

    view = red_suppressed_view(img)

    assert view.shape == img.shape
    red_area = view[5:15, 5:25].mean()
    ink_area = view[20:30, 5:25].mean()
    assert red_area > 180, "红章在 R 通道应接近纸白，才能不干扰检测"
    assert ink_area < 60, "黑字在 R 通道必须仍然很暗，否则字会一起被抹掉"
    assert red_area - ink_area > 100


def test_red_suppressed_view_is_noop_on_empty_image():
    assert red_suppressed_view(None) is None  # type: ignore[arg-type]


# ---------- 合并：只收印章附近 ----------

def test_merge_adds_missing_line_near_stamp():
    """一次识别漏掉的印章压盖行，二次识别补回后应被追加。"""
    primary = [_line("签署日期：2026年1月12日", 148, 1815, 700, 1849)]
    secondary = [
        _line("签署日期：2026年1月12日", 148, 1818, 700, 1852),
        _line("乙方（盖章）：沐石供应链有限公司", 145, 1856, 700, 1903),
    ]

    merged, added, replaced = merge_secondary(primary, secondary, [STAMP])

    assert added == 1 and replaced == 0
    assert len(merged) == 2
    assert any("乙方" in line.text for line in merged)


def test_merge_ignores_lines_far_from_stamp():
    """页面上远离印章的新增行一律不接收（最小侵入）。"""
    primary = [_line("第一条 服务内容", 150, 1084, 900, 1118)]
    secondary = [_line("页眉噪声", 100, 100, 400, 130)]

    merged, added, _ = merge_secondary(primary, secondary, [STAMP])

    assert added == 0
    assert merged == primary


def test_merge_dedupes_same_row_with_equal_confidence():
    """同行同文本、置信度不更高时不重复计入，否则字符会被算两遍。"""
    primary = [_line("合同专用章", 566, 1988, 763, 2047, conf=0.993)]
    secondary = [_line("合同专用章", 569, 1988, 763, 2049, conf=0.988)]

    merged, added, replaced = merge_secondary(primary, secondary, [STAMP])

    assert added == 0 and replaced == 0
    assert len(merged) == 1
    assert merged[0].confidence == 0.993


def test_merge_replaces_when_secondary_is_clearly_better():
    primary = [_line("沐石供应锥有限公司", 145, 1856, 700, 1903, conf=0.70)]
    secondary = [_line("沐石供应链有限公司", 145, 1856, 700, 1903, conf=0.99)]

    merged, added, replaced = merge_secondary(primary, secondary, [STAMP])

    assert added == 0 and replaced == 1
    assert "供应链" in merged[0].text


# ---------- 合并后顺序 ----------

def test_merge_keeps_reading_order():
    """追加的行原本落在末尾，必须重排；否则按行序对齐会整段错位（曾致准确率 100%→93%）。"""
    primary = [
        _line("签署日期：2026年1月12日", 148, 1818, 700, 1852),
        _line("授权代表（签字）：", 148, 1910, 400, 1944),
        _line("第3页/共10页", 729, 2256, 900, 2290),
    ]
    secondary = [_line("乙方（盖章）：沐石供应链有限公司", 145, 1856, 700, 1903)]

    merged, added, _ = merge_secondary(primary, secondary, [STAMP])

    assert added == 1
    texts = [line.text for line in merged]
    assert texts[1].startswith("乙方"), f"补回的行必须落在两行签署日期之间，实际顺序：{texts}"
    assert texts[-1].startswith("第3页")


def test_merge_without_regions_returns_primary_copy():
    primary = [_line("正文", 150, 500, 400, 534)]
    merged, added, replaced = merge_secondary(primary, [_line("别的", 150, 900, 400, 934)], [])

    assert added == 0 and replaced == 0
    assert merged == primary
    assert merged is not primary
