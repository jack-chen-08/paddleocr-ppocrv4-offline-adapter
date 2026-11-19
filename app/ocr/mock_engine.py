"""Mock 引擎：无模型环境下跑通接口与流水线（MOCK_MODE=1 或单测用）。

真实识别必须走 PaddleOcrEngine；本类只用于契约测试与前端联调，
输出内容是固定的假数据，禁止用于任何验收数据。
"""
from __future__ import annotations

import time

from app.ocr.types import OcrLine, OcrPage


class MockOcrEngine:  # 结构上满足 OcrEngine 协议（不显式继承 Protocol）
    name = "mock"

    def __init__(self, lines: list[tuple[str, float, bool]] | None = None) -> None:
        self._lines = lines or [
            ("甲方（委托方）：星澜产业园管理有限公司", 0.98, False),
            ("合同总价：人民币98,000.00元", 0.97, False),
            ("签署日期：2026年1月12日", 0.72, True),
        ]

    def recognize(self, page_image, *, page_no: int = 1) -> OcrPage:
        started = time.perf_counter()
        lines = [
            OcrLine(
                text=text,
                bbox=[(100.0, 100.0 + i * 40), (600.0, 100.0 + i * 40), (600.0, 130.0 + i * 40), (100.0, 130.0 + i * 40)],
                confidence=conf,
                stamp_overlap=ov,
            )
            for i, (text, conf, ov) in enumerate(self._lines)
        ]
        return OcrPage(
            page_no=page_no,
            width=1654,
            height=2339,
            lines=lines,
            engine=self.name,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
