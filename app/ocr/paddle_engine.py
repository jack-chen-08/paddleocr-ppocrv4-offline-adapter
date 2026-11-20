"""PaddleOCR 实现（PP-OCRv4 中文，CPU 推理，完全离线）。

适配 PaddleOCR 2.x / 3.x 两代 API：
  * 3.x: PaddleOCR(...).predict(input=path) -> [ {rec_texts, rec_scores, rec_polys} ]
  * 2.x: PaddleOCR(...).ocr(path, cls=True) -> [[ [box, (text, score)], ... ]]

模型来源由环境变量固定为镜像内目录：
  PADDLE_OCR_DET_MODEL_DIR / PADDLE_OCR_REC_MODEL_DIR / PADDLE_OCR_CLS_MODEL_DIR
未设置时只回落 `models/official_models/<模型名>`（仓库/镜像内的离线目录），
两者都不存在则 **fail-closed 抛 ModelWeightsMissing**，绝不交给 PaddleOCR 的默认
缓存去联网下载（HF_HUB_OFFLINE 只挡 HuggingFace，挡不住 ModelScope / BOS 下载）。
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

# 权重文件特征：3.x 用 inference.json / inference.yml，2.x 用 inference.pdmodel；
# 两者都必须带 inference.pdiparams。缺任一 → 判为权重不完整，直接失败。
_WEIGHT_PARAMS = "inference.pdiparams"
_WEIGHT_GRAPHS = ("inference.json", "inference.pdmodel")

# 仓库 / 镜像内的离线权重根目录（app/ocr/paddle_engine.py → 上两级）
DEFAULT_MODELS_ROOT = Path(__file__).resolve().parents[2] / "models" / "official_models"


class ModelWeightsMissing(RuntimeError):
    """离线权重缺失/不完整。fail-closed：绝不允许回落到联网下载。"""


def _validate_model_dir(path: Path, env_key: str, model_name: str) -> Path:
    """校验目录里确实有可推理的权重；不完整就抛错，不把决定权交回 PaddleOCR。"""
    if not path.is_dir():
        raise ModelWeightsMissing(
            f"离线权重目录不存在：{path}（{env_key} / 模型 {model_name}）。"
            f"请设置 {env_key} 指向镜像内的 official_models/{model_name}，"
            f"或先执行 bash tools/package_models.sh 解包权重。已拒绝回落到在线下载。"
        )
    missing = []
    if not (path / _WEIGHT_PARAMS).is_file():
        missing.append(_WEIGHT_PARAMS)
    if not any((path / g).is_file() for g in _WEIGHT_GRAPHS):
        missing.append(" 或 ".join(_WEIGHT_GRAPHS))
    if missing:
        raise ModelWeightsMissing(
            f"离线权重不完整：{path} 缺少 {' / '.join(missing)}（{env_key}）。"
            f"该目录可能是被 .gitignore 忽略后残留的空壳（只剩 .lock 文件）。"
            f"请从 dist/paddleocr_offline_models.tar.gz 解包后重试；已拒绝联网下载。"
        )
    return path


def resolve_model_dir(env_key: str, model_name: str, explicit: str | Path | None = None) -> Path:
    """按 显式参数 → 环境变量 → 仓库内离线目录 的顺序解析权重目录。

    三条路径都会做完整性校验；全部落空即抛 ModelWeightsMissing。
    """
    candidate = explicit or os.getenv(env_key)
    if candidate:
        return _validate_model_dir(Path(candidate).expanduser(), env_key, model_name)
    local = DEFAULT_MODELS_ROOT / model_name
    if local.is_dir():
        return _validate_model_dir(local, env_key, model_name)
    raise ModelWeightsMissing(
        f"{env_key} 未设置，且默认离线目录 {local} 不存在。"
        f"拒绝使用 PaddleOCR 默认缓存（首次运行会联网下载，断网容器内必然失败）。"
        f"离线部署请设置 {env_key} 指向镜像内权重目录。"
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
        # ---- 先解析权重目录：缺失即 fail-closed，早于任何 PaddleOCR 初始化 ----
        det_name = os.getenv("PADDLE_OCR_DET_MODEL_NAME", "PP-OCRv4_mobile_det")
        rec_name = os.getenv("PADDLE_OCR_REC_MODEL_NAME", "PP-OCRv4_mobile_rec")
        det_path = resolve_model_dir("PADDLE_OCR_DET_MODEL_DIR", det_name, det_model_dir)
        rec_path = resolve_model_dir("PADDLE_OCR_REC_MODEL_DIR", rec_name, rec_model_dir)
        cls_path = None
        cls_raw = cls_model_dir or os.getenv("PADDLE_OCR_CLS_MODEL_DIR")
        if cls_raw:
            cls_path = resolve_model_dir(
                "PADDLE_OCR_CLS_MODEL_DIR", os.getenv("PADDLE_OCR_CLS_MODEL_NAME", "ch_ppocr_mobile_v2.0_cls"), cls_raw
            )

        # 兜底关掉任何缓存型下载入口（只作为第二道闸，第一道是上面的目录校验）
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(det_path.parent.parent))

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

        # 权重目录覆盖（3.x 命名 text_detection_model_dir / 2.x 命名 det_model_dir）
        if "text_detection_model_dir" in params:
            kwargs["text_detection_model_dir"] = str(det_path)
            kwargs["text_recognition_model_dir"] = str(rec_path)
            if cls_path is not None:
                kwargs["textline_orientation_model_dir"] = str(cls_path)
        elif "det_model_dir" in params:
            kwargs["det_model_dir"] = str(det_path)
            kwargs["rec_model_dir"] = str(rec_path)
            if cls_path is not None:
                kwargs["cls_model_dir"] = str(cls_path)
            if "use_angle_cls" in params:
                kwargs["use_angle_cls"] = cls_path is not None
        else:
            raise ModelWeightsMissing(
                "当前 PaddleOCR 版本的构造函数不接受本地模型目录参数，"
                "无法保证离线；请使用 requirements-ocr.txt 锁定的版本。"
            )

        # 2.x 专属参数：只在签名里存在时传
        for key in list(kwargs):
            if not has_varkw and key not in params:
                kwargs.pop(key)

        self.det_model_dir = det_path
        self.rec_model_dir = rec_path
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
