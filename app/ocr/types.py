"""OCR 抽象接口与数据契约。

本模块只定义类型，不依赖任何 OCR 引擎，便于上层（字段抽取、人工核对队列）
与具体实现（PaddleOCR / mock / 未来的其他引擎）解耦。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

Point = tuple[float, float]


@dataclass
class OcrLine:
    """行级识别结果。

    bbox: 四点坐标，顺序为 左上 / 右上 / 右下 / 左下（与 PaddleOCR 输出一致）。
    """

    text: str
    bbox: list[Point]
    confidence: float
    stamp_overlap: bool = False

    def __post_init__(self) -> None:
        if len(self.bbox) != 4:
            raise ValueError("bbox 必须是四点坐标")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须在 [0, 1] 内")
        self.bbox = [(float(x), float(y)) for x, y in self.bbox]

    @property
    def x_min(self) -> float:
        return min(p[0] for p in self.bbox)

    @property
    def x_max(self) -> float:
        return max(p[0] for p in self.bbox)

    @property
    def y_min(self) -> float:
        return min(p[1] for p in self.bbox)

    @property
    def y_max(self) -> float:
        return max(p[1] for p in self.bbox)

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": [[round(x, 2), round(y, 2)] for x, y in self.bbox],
            "confidence": round(self.confidence, 4),
            "stamp_overlap": self.stamp_overlap,
        }


@dataclass
class OcrPage:
    """单页识别结果，落盘为 ocr/{contract_id}/{page_no}.json。"""

    page_no: int
    width: int
    height: int
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = ""
    elapsed_ms: float = 0.0
    stamp_regions: list[list[Point]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def avg_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.confidence for line in self.lines) / len(self.lines)

    @property
    def stamp_overlap_lines(self) -> list[OcrLine]:
        return [line for line in self.lines if line.stamp_overlap]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_no": self.page_no,
            "width": self.width,
            "height": self.height,
            "engine": self.engine,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "avg_confidence": round(self.avg_confidence, 4),
            "stamp_regions": [
                [[round(x, 2), round(y, 2)] for x, y in region] for region in self.stamp_regions
            ],
            "lines": [line.to_dict() for line in self.lines],
        }


@runtime_checkable
class OcrEngine(Protocol):
    """OCR 引擎抽象接口。

    契约：
      * 入参 page_image 可以是 bytes（图片二进制）或本地图片路径；
      * 出参必须是 OcrPage，行级结果包含 text / bbox（四点）/ confidence；
      * 不得在识别过程中调用任何境外或公有云 OCR 接口（离线可运行）。
    """

    name: str

    def recognize(self, page_image: bytes | str, *, page_no: int = 1) -> OcrPage:
        ...


def lines_from_raw(raw_lines: Sequence[dict[str, Any]]) -> list[OcrLine]:
    """把引擎原始行字典转换为 OcrLine（供各实现共用）。"""
    out: list[OcrLine] = []
    for item in raw_lines:
        out.append(
            OcrLine(
                text=str(item["text"]),
                bbox=item["bbox"],
                confidence=float(item["confidence"]),
                stamp_overlap=bool(item.get("stamp_overlap", False)),
            )
        )
    return out
