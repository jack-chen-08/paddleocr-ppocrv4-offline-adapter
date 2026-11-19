"""PaddleOCR 实现（PP-OCRv4 中文，CPU 推理，完全离线）。

适配 PaddleOCR 2.x / 3.x 两代 API：
  * 3.x: PaddleOCR(...).predict(input=path) -> [ {rec_texts, rec_scores, rec_polys} ]
  * 2.x: PaddleOCR(...).ocr(path, cls=True) -> [[ [box, (text, score)], ... ]]

模型来源可用环境变量固定为镜像内目录：
  PADDLE_OCR_DET_MODEL_DIR / PADDLE_OCR_REC_MODEL_DIR / PADDLE_OCR_CLS_MODEL_DIR
未设置时读 PaddleOCR 默认缓存（首次运行需联网下载，打包脚本会把它固化进镜像）。
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.ocr.normalize import normalize_text
from app.ocr.stamp import (
    StampRegion,
    apply_stamp_rules,
    detect_stamps,
    merge_secondary,
    red_suppressed_view,
)
from app.ocr.types import OcrLine, OcrPage

# 关闭所有会联网或非必要的扩展，保证离线与确定性
_DISABLE_FLAGS = (
    "use_doc_orientation_classify",
    "use_doc_unwarping",
    "use_textline_orientation",
)


class PaddleOcrEngine:
    """本地 PaddleOCR 引擎。线程不安全，多进程部署时每进程一个实例。

    默认用 PP-OCRv4 mobile 检测/识别模型（任务指定 PP-OCRv4 中文模型）：
    server/medium 模型在 4 核 CPU 上单页 >20s，不满足本单 P95 ≤6s 的硬指标；
    mobile + 长边 960 在同样环境下约 2–3s。如需换模型，用环境变量覆盖：
      PADDLE_OCR_DET_MODEL_NAME / PADDLE_OCR_REC_MODEL_NAME（见 README §五）
    """

    name = "paddleocr-ppocrv4-mobile"

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
        cpu_threads: int = 4,
        det_limit_side_len: int = 960,
        det_model_dir: str | None = None,
        rec_model_dir: str | None = None,
        cls_model_dir: str | None = None,
    ) -> None:
        from paddleocr import PaddleOCR  # 延迟导入：无模型环境也能跑单测

        import inspect

        sig = inspect.signature(PaddleOCR.__init__)
        params = set(sig.parameters)
        has_varkw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

        kwargs: dict[str, Any] = {"lang": lang}
        if "use_gpu" in params:
            kwargs["use_gpu"] = use_gpu
        elif "device" in params:
            kwargs["device"] = "cpu"
        for flag in _DISABLE_FLAGS:
            kwargs[flag] = False

        if "text_detection_model_name" in params:
            det_name = os.getenv("PADDLE_OCR_DET_MODEL_NAME", "PP-OCRv4_mobile_det")
            rec_name = os.getenv("PADDLE_OCR_REC_MODEL_NAME", "PP-OCRv4_mobile_rec")
            kwargs["text_detection_model_name"] = det_name
            kwargs["text_recognition_model_name"] = rec_name
            kwargs["text_det_limit_side_len"] = det_limit_side_len
            kwargs["text_det_limit_type"] = "max"
            # 孤立的句号/逗号框置信度低，默认 0.6 会被当噪声丢掉；允许下调，
            # 但下调过多会引入噪声行，故上限锁在 0.3，且默认保持 0.6 不变。
            box_thresh = float(os.getenv("PADDLE_OCR_DET_BOX_THRESH", "0.6"))
            if "text_det_box_thresh" in params:
                kwargs["text_det_box_thresh"] = max(0.3, min(0.9, box_thresh))
            self.name = f"paddleocr-{det_name.lower()}"

        # 3.x：CPU 推理线程数与 oneDNN 加速
        if has_varkw or "cpu_threads" in params:
            kwargs["cpu_threads"] = cpu_threads
            kwargs["enable_mkldnn"] = True

        # 目录覆盖（离线打包/自定义模型）
        det = det_model_dir or os.getenv("PADDLE_OCR_DET_MODEL_DIR")
        rec = rec_model_dir or os.getenv("PADDLE_OCR_REC_MODEL_DIR")
        cls = cls_model_dir or os.getenv("PADDLE_OCR_CLS_MODEL_DIR")
        for key, val in (
            ("text_detection_model_dir", det),
            ("text_recognition_model_dir", rec),
        ):
            if val and key in params:
                kwargs[key] = val
        if cls and "cls_model_dir" in params:
            kwargs["cls_model_dir"] = cls

        # 2.x 专属参数：只在签名里存在时传
        for key in list(kwargs):
            if not has_varkw and key not in params:
                kwargs.pop(key)

        self._legacy = not hasattr(PaddleOCR, "predict")
        self._is_v3 = not self._legacy
        self._ocr = PaddleOCR(**kwargs)

    # ---------- 内部：读图 ----------
    @staticmethod
    def _load_bgr(page_image: bytes | str | Path) -> np.ndarray:
        import cv2

        if isinstance(page_image, (bytes, bytearray)):
            arr = np.frombuffer(page_image, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        else:
            img = cv2.imread(str(page_image), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("无法解码页面图片")
        return img

    # ---------- 内部：调用引擎 ----------
    def _raw_lines(self, img: np.ndarray, tmp_path: Path | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if hasattr(self._ocr, "predict") and not getattr(self, "_legacy", False):
            results = self._ocr.predict(input=img)
            for res in results or []:
                data = res if isinstance(res, dict) else getattr(res, "json", {}).get("res", {})
                polys = data.get("rec_polys") or data.get("dt_polys") or []
                texts = data.get("rec_texts") or []
                scores = data.get("rec_scores") or []
                for poly, text, score in zip(polys, texts, scores):
                    out.append({"text": text, "bbox": [tuple(map(float, p)) for p in poly], "confidence": float(score)})
            return out

        # 2.x
        assert tmp_path is not None
        results = self._ocr.ocr(str(tmp_path), cls=True)
        for page in results or []:
            for item in page or []:
                box, (text, score) = item[0], item[1]
                out.append({"text": text, "bbox": [tuple(map(float, p)) for p in box], "confidence": float(score)})
        return out

    # ---------- 对外接口 ----------
    def recognize(self, page_image: bytes | str, *, page_no: int = 1) -> OcrPage:
        import cv2
        import tempfile

        img = self._load_bgr(page_image)
        h, w = img.shape[:2]

        tmp_path: Path | None = None
        if isinstance(page_image, (bytes, bytearray)):
            fd, name = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            tmp_path = Path(name)
            cv2.imwrite(str(tmp_path), img)

        started = time.perf_counter()
        two_pass = False
        added = replaced = 0
        try:
            raw = self._raw_lines(img, tmp_path)
            lines = [
                OcrLine(text=normalize_text(r["text"]), bbox=r["bbox"], confidence=r["confidence"])
                for r in raw
                if r["text"] and r["text"].strip()
            ]

            regions: list[StampRegion] = detect_stamps(img)
            # 红章压盖会让检测阶段直接丢行（不是识别错字），故有印章时补一次
            # R 通道识别，只把印章附近新增/更可信的行并回来。
            if regions:
                view = red_suppressed_view(img)
                raw2 = self._raw_lines(view, tmp_path)
                secondary = [
                    OcrLine(text=normalize_text(r["text"]), bbox=r["bbox"], confidence=r["confidence"])
                    for r in raw2
                    if r["text"] and r["text"].strip()
                ]
                lines, added, replaced = merge_secondary(lines, secondary, regions)
                two_pass = True
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        lines, dropped = apply_stamp_rules(lines, regions, bgr=img)
        # 环形文字被剔除的事实写入日志，便于人工核对时解释「少了几行」
        if dropped:
            print(f"[ocr] page {page_no}: dropped {len(dropped)} ring-text lines inside stamp")
        if two_pass:
            print(
                f"[ocr] page {page_no}: stamp two-pass added {added} / replaced {replaced} line(s) "
                f"({elapsed_ms:.0f} ms total)"
            )

        return OcrPage(
            page_no=page_no,
            width=int(w),
            height=int(h),
            lines=lines,
            engine=self.name,
            elapsed_ms=elapsed_ms,
            stamp_regions=[r.bbox for r in regions],
        )


class StubOcrEngine:
    """接口桩：无模型环境（单测 / 联调）按固定行返回，保证上层可先跑通。"""

    name = "stub"

    def __init__(self, lines: list[OcrLine] | None = None) -> None:
        self._lines = lines or []

    def recognize(self, page_image: bytes | str, *, page_no: int = 1) -> OcrPage:
        return OcrPage(page_no=page_no, width=0, height=0, lines=list(self._lines), engine=self.name)
