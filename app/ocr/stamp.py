"""红色印章检测、遮挡判定与降权。

规则（对应任务【本单范围】）：
  * 检测红色印章区域；
  * 被印章遮挡的行：confidence × 0.8，并打标 stamp_overlap；
  * 印章内环形文字不进入正文；
  * 仅依赖 OpenCV，不联网。

两个判据的经验依据（本次 10 页真实跑测）：
  1) 遮挡判定不能只看 bbox 覆盖率。印章是半透明红色覆盖，被遮住的行 OCR 只能框到
     未被遮的左半段，bbox 会收缩，覆盖率往往只有 0.02–0.10。故：行 bbox 外扩
     PAD 像素后与印章 bbox 相交面积占比 ≥ 3% 即判遮挡；行中心落在印章 bbox 内也判遮挡。
  2) 环形文字剔除不能只看「整行在印章内 + 行高小」：正文被印章切开的尾段（如
     「1月12日」）同样满足这两个条件，会被误删。真实区别在颜色——印章自带文字是红字，
     正文是黑字。故：只有落在印章内、且行内黑色像素占比 < 0.5% 的行才判为环形文字。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.ocr.types import OcrLine, Point

# 印章红色在两段 HSV 区间内
_RED_RANGES = (
    ((0, 70, 50), (10, 255, 255)),
    ((160, 70, 50), (180, 255, 255)),
)

MIN_AREA_RATIO = 0.012  # 印章面积下限（占页面面积），排除红色小图标
OVERLAP_THRESHOLD = 0.03  # 行 bbox（外扩 PAD）与印章区域相交占比阈值
OVERLAP_PAD = 16  # bbox 外扩像素：遮挡会让 OCR 框收缩，需要容差
CONFIDENCE_PENALTY = 0.8  # 遮挡行置信度降权系数
RING_TEXT_MAX_HEIGHT_RATIO = 0.34  # 行高 < 印章直径 34% 才可能是环形文字
RING_TEXT_DARK_RATIO = 0.005  # 行内黑色像素占比 < 0.5% -> 印章自身红字，不是正文

# 二次识别（红色抑制）参数
SECOND_PASS_PAD = OVERLAP_PAD  # 二次识别行与印章相交的容差，与遮挡判定一致
DUP_CENTER_RATIO = 0.6  # 两行纵向中心距 < 较高行高 × 0.6 才可能同行
DUP_H_OVERLAP = 0.5  # 横向重叠占较短行宽 ≥ 50% 才可能同行
REPLACE_CONF_MARGIN = 0.05  # 二次识别置信度高出这么多才替换一次识别结果


@dataclass
class StampRegion:
    """印章区域（轴对齐外接矩形，四点表示）。"""

    x1: float
    y1: float
    x2: float
    y2: float
    area_ratio: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def bbox(self) -> list[Point]:
        return [(self.x1, self.y1), (self.x2, self.y1), (self.x2, self.y2), (self.x1, self.y2)]

    def to_dict(self) -> dict:
        return {
            "bbox": [[round(x, 2), round(y, 2)] for x, y in self.bbox],
            "area_ratio": round(self.area_ratio, 4),
        }


def _red_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lo, hi in _RED_RANGES:
        mask |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def detect_stamps(bgr: np.ndarray, min_area_ratio: float = MIN_AREA_RATIO) -> list[StampRegion]:
    """返回页面中的印章候选区域，按面积降序。"""
    if bgr is None or bgr.size == 0:
        return []
    h, w = bgr.shape[:2]
    page_area = float(h * w)
    mask = _red_mask(bgr)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[StampRegion] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area / page_area < min_area_ratio:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw <= 0 or bh <= 0:
            continue
        # 印章应是近方形的块状区域；极端细长的红色条（下划线、批注线）排除
        aspect = bw / bh
        if aspect < 0.45 or aspect > 2.2:
            continue
        # 轮廓内部红色填充率（实心章高、空心章低），低于 3% 视为噪点
        if area / float(bw * bh) < 0.03:
            continue
        regions.append(
            StampRegion(
                x1=float(x),
                y1=float(y),
                x2=float(x + bw),
                y2=float(y + bh),
                area_ratio=area / page_area,
            )
        )
    regions.sort(key=lambda r: -r.area_ratio)
    return regions


def _intersection_area(line: OcrLine, region: StampRegion, pad: float = 0.0) -> float:
    ix1 = max(line.x_min, region.x1 - pad)
    iy1 = max(line.y_min, region.y1 - pad)
    ix2 = min(line.x_max, region.x2 + pad)
    iy2 = min(line.y_max, region.y2 + pad)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def coverage_ratio(line: OcrLine, region: StampRegion, pad: float = OVERLAP_PAD) -> float:
    """行 bbox（外扩 pad）被印章矩形覆盖的面积比例。"""
    line_area = max(line.x_max - line.x_min, 1e-6) * max(line.y_max - line.y_min, 1e-6)
    return min(_intersection_area(line, region, pad) / line_area, 1.0)


def _contained(line: OcrLine, region: StampRegion, margin: float = 2.0) -> bool:
    return (
        line.x_min >= region.x1 - margin
        and line.x_max <= region.x2 + margin
        and line.y_min >= region.y1 - margin
        and line.y_max <= region.y2 + margin
    )


def _dark_ratio(bgr: np.ndarray, line: OcrLine) -> float:
    """行框内「黑色正文像素」占比：黑字低亮度、低饱和；红色印章像素不满足。"""
    h, w = bgr.shape[:2]
    x1 = max(0, int(line.x_min))
    y1 = max(0, int(line.y_min))
    x2 = min(w, int(line.x_max) + 1)
    y2 = min(h, int(line.y_max) + 1)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    roi = bgr[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    dark = (hsv[:, :, 2] < 110) & (hsv[:, :, 1] < 90)
    return float(dark.mean())


def _is_overlapped(line: OcrLine, region: StampRegion) -> bool:
    if coverage_ratio(line, region) >= OVERLAP_THRESHOLD:
        return True
    cx = (line.x_min + line.x_max) / 2
    cy = (line.y_min + line.y_max) / 2
    return region.x1 <= cx <= region.x2 and region.y1 <= cy <= region.y2


def apply_stamp_rules(
    lines: list[OcrLine],
    regions: list[StampRegion],
    bgr: np.ndarray | None = None,
    overlap_threshold: float = OVERLAP_THRESHOLD,
    penalty: float = CONFIDENCE_PENALTY,
) -> tuple[list[OcrLine], list[OcrLine]]:
    """执行「降权 + 去环形文字」两条规则。

    返回 (保留的行, 被剔除的环形文字行)，入参行对象不被原地修改。
    bgr 为空时退化为只用几何判据（环形文字剔除会变激进，仅用于单测）。
    """
    if not regions:
        return list(lines), []

    kept: list[OcrLine] = []
    dropped: list[OcrLine] = []
    for line in lines:
        in_ring = False
        for r in regions:
            if not (_contained(line, r) and line.height < r.height * RING_TEXT_MAX_HEIGHT_RATIO):
                continue
            if bgr is not None and _dark_ratio(bgr, line) >= RING_TEXT_DARK_RATIO:
                continue  # 黑字正文被印章切开，不是环形文字
            in_ring = True
            break
        if in_ring:
            dropped.append(line)
            continue

        overlap = max((coverage_ratio(line, r) for r in regions), default=0.0) >= overlap_threshold or any(
            _is_overlapped(line, r) for r in regions
        )
        new_line = OcrLine(
            text=line.text,
            bbox=list(line.bbox),
            confidence=round(line.confidence * penalty, 4) if overlap else line.confidence,
            stamp_overlap=overlap,
        )
        kept.append(new_line)
    return kept, dropped


def red_suppressed_view(bgr: np.ndarray) -> np.ndarray:
    """红色印章抑制视图：只保留 R（红）通道，再还原成三通道供引擎调用。

    原理：红墨在 R 通道上的亮度接近纸白，而黑色正文在 R 通道仍是暗值；因此这一步
    相当于「擦掉红章、留下黑字」，不需要调任何阈值。

    本机 page_03 实测：原图在检测阶段就因红章压盖丢掉整行「乙方（盖章）：沐石供应链
    有限公司」（该行 y=1856 恰在印章 y=1809 起的上沿），改在该视图重识别后该行
    conf=0.99 完整恢复；印章自身红字（合同专用章等）在 R 通道变亮，重识别后仍会被
    apply_stamp_rules 的环形文字规则剔除。
    """
    if bgr is None or getattr(bgr, "size", 0) == 0:
        return bgr
    red = bgr[:, :, 2]
    return cv2.cvtColor(red, cv2.COLOR_GRAY2BGR)


def _touches_region(line: OcrLine, region: StampRegion, pad: float = SECOND_PASS_PAD) -> bool:
    """行是否与印章区域（外扩 pad）有交叠。"""
    return _intersection_area(line, region, pad) > 0.0


def _same_row(a: OcrLine, b: OcrLine) -> bool:
    """两行是否指向同一行正文：纵向中心相近且横向重叠过半。"""
    ha = max(a.height, 1e-6)
    hb = max(b.height, 1e-6)
    cy_a = (a.y_min + a.y_max) / 2
    cy_b = (b.y_min + b.y_max) / 2
    if abs(cy_a - cy_b) > max(ha, hb) * DUP_CENTER_RATIO:
        return False
    overlap = min(a.x_max, b.x_max) - max(a.x_min, b.x_min)
    span = min(a.x_max - a.x_min, b.x_max - b.x_min)
    return span > 0 and overlap / span >= DUP_H_OVERLAP


def merge_secondary(
    primary: list[OcrLine],
    secondary: list[OcrLine],
    regions: list[StampRegion],
    pad: float = SECOND_PASS_PAD,
) -> tuple[list[OcrLine], int, int]:
    """把二次识别结果并入主结果，只接收「与印章区相交」的行。

    合并规则：
      * 只在印章附近生效，页面上其他位置一律以一次识别为准（最小侵入）；
      * 与主结果同行且置信度未明显更高 -> 丢弃（避免重复计入字符）；
      * 与主结果同行但置信度高出 REPLACE_CONF_MARGIN -> 替换；
      * 主结果没有的行 -> 追加（正是红章压盖丢失的那类行）。

    返回 (合并后的行, 追加行数, 替换行数)。降权与环形文字剔除由调用方统一做一次。
    """
    out = [OcrLine(text=l.text, bbox=list(l.bbox), confidence=l.confidence, stamp_overlap=l.stamp_overlap) for l in primary]
    if not regions or not secondary:
        return out, 0, 0

    added = replaced = 0
    for cand in secondary:
        if not any(_touches_region(cand, r, pad) for r in regions):
            continue
        hit = next((i for i, cur in enumerate(out) if _same_row(cur, cand)), None)
        if hit is None:
            out.append(cand)
            added += 1
        elif cand.confidence > out[hit].confidence + REPLACE_CONF_MARGIN:
            out[hit] = cand
            replaced += 1
    if added or replaced:
        # 追加的行原本落在末尾，必须按阅读顺序重排，否则下游按行序对齐会整体错位
        out.sort(key=lambda l: (round(l.y_min / 8.0), l.x_min))
    return out, added, replaced
