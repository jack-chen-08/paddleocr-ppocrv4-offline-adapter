"""印章检测 / 遮挡降权 / 环形文字剔除（对应验收标准 AC4）。

AC4 原文：印章遮挡的行带 stamp_overlap 且降权（单测通过）。
本文件用构造图与构造行做确定性断言，不依赖 PaddleOCR 模型。
"""
from __future__ import annotations

import cv2
import numpy as np

from app.ocr.stamp import (
    CONFIDENCE_PENALTY,
    apply_stamp_rules,
    coverage_ratio,
    detect_stamps,
)
from app.ocr.types import OcrLine


def _page_with_stamp() -> tuple[np.ndarray, tuple[int, int, int]]:
    """白底 + 红色圆章（圆心 400,300 半径 100）。返回 (图, (cx,cy,r))。"""
    img = np.full((600, 800, 3), 255, dtype=np.uint8)
    cx, cy, r = 400, 300, 100
    red = (30, 30, 200)  # BGR 红
    cv2.circle(img, (cx, cy), r, red, 8)
    cv2.circle(img, (cx, cy), r - 14, red, 2)
    return img, (cx, cy, r)


def _line(x1: int, y1: int, x2: int, y2: int, text: str = "正文行", conf: float = 0.9) -> OcrLine:
    return OcrLine(text=text, bbox=[(x1, y1), (x2, y1), (x2, y2), (x1, y2)], confidence=conf)


def test_detect_red_stamp_region():
    img, (cx, cy, r) = _page_with_stamp()
    regions = detect_stamps(img)
    assert len(regions) == 1
    reg = regions[0]
    assert abs((reg.x1 + reg.x2) / 2 - cx) <= 12
    assert abs((reg.y1 + reg.y2) / 2 - cy) <= 12
    assert reg.width >= 2 * r - 12


def test_no_stamp_no_region():
    blank = np.full((600, 800, 3), 255, dtype=np.uint8)
    assert detect_stamps(blank) == []


def test_overlapped_line_marked_and_penalised():
    img, (cx, cy, _) = _page_with_stamp()
    regions = detect_stamps(img)
    overlapped = _line(cx - 130, cy - 12, cx + 130, cy + 12, "被章压住的一行", 0.9)
    clean = _line(120, 60, 380, 84, "页眉干净行", 0.9)

    kept, dropped = apply_stamp_rules([overlapped, clean], regions, bgr=img)

    assert dropped == []
    hit = [ln for ln in kept if ln.text == "被章压住的一行"][0]
    miss = [ln for ln in kept if ln.text == "页眉干净行"][0]
    assert hit.stamp_overlap is True
    assert abs(hit.confidence - 0.9 * CONFIDENCE_PENALTY) < 1e-6
    assert miss.stamp_overlap is False
    assert miss.confidence == 0.9


def test_partial_overlap_near_edge_still_marked():
    """生产实测：印章是半透明覆盖，行框会收缩，边缘重叠也必须判遮挡。"""
    img, (cx, cy, _) = _page_with_stamp()
    regions = detect_stamps(img)
    shrunk = _line(cx - 200, cy - 10, cx - 88, cy + 10, "行尾被章压住", 0.85)
    assert coverage_ratio(shrunk, regions[0]) < 0.3  # 几何覆盖率很低
    kept, _ = apply_stamp_rules([shrunk], regions, bgr=img)
    assert kept[0].stamp_overlap is True


def test_ring_text_dropped_but_black_text_kept():
    """印章自带红字剔除；被印章切开的黑字正文必须保留。"""
    img, (cx, cy, r) = _page_with_stamp()
    regions = detect_stamps(img)
    # 红字：行框落在章内，笔画是红色（无黑像素）
    ring = _line(cx - 20, cy - 60, cx + 20, cy - 40, "合", 0.2)
    roi = img[int(ring.y_min) : int(ring.y_max), int(ring.x_min) : int(ring.x_max)]
    roi[:] = (30, 30, 200)
    # 黑字：同样落在章内，但笔画是黑色
    body = _line(cx - 30, cy + 40, cx + 30, cy + 60, "月12日", 0.8)
    roi2 = img[int(body.y_min) : int(body.y_max), int(body.x_min) : int(body.x_max)]
    roi2[:] = 255
    roi2[4:8, 4:20] = (0, 0, 0)

    kept, dropped = apply_stamp_rules([ring, body], regions, bgr=img)
    assert [ln.text for ln in dropped] == ["合"]
    assert [ln.text for ln in kept] == ["月12日"]
    assert kept[0].stamp_overlap is True


def test_empty_regions_passthrough():
    lines = [_line(10, 10, 100, 30, conf=0.7)]
    kept, dropped = apply_stamp_rules(lines, [], bgr=None)
    assert dropped == []
    assert kept[0].confidence == 0.7 and kept[0].stamp_overlap is False
