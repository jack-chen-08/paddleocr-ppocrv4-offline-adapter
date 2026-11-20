#!/usr/bin/env bash
# 离线验收：断网条件下完成一页识别，证明不依赖任何外部服务。
# 权重只来自 dist/paddleocr_offline_models.tar.gz（不依赖仓库 models/，干净克隆下它不存在）。
# 用法： bash tools/verify_offline.sh [页码，默认 3]
set -euo pipefail
cd "$(dirname "$0")/.."

PAGE="${1:-3}"
IMG="data/pages/page_$(printf '%02d' "$PAGE").png"
OUT="reports/offline_verify.json"
mkdir -p reports

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar -xzf dist/paddleocr_offline_models.tar.gz -C "$WORK"

PADDLE_OCR_DET_MODEL_DIR="$WORK/official_models/PP-OCRv4_mobile_det" \
PADDLE_OCR_REC_MODEL_DIR="$WORK/official_models/PP-OCRv4_mobile_rec" \
PADDLE_PDX_CACHE_HOME="$WORK" \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
PYTHONPATH=. unshare -rn .venv/bin/python - "$IMG" "$PAGE" "$OUT" <<'PY'
import json, socket, sys, time
from pathlib import Path

img, page_no, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])

try:
    socket.create_connection(("pypi.org", 443), timeout=3)
    net = "OPEN"
except Exception:
    net = "BLOCKED"

from app.ocr.paddle_engine import PaddleOcrEngine

engine = PaddleOcrEngine()
t0 = time.perf_counter()
page = engine.recognize(img, page_no=page_no)
ms = round((time.perf_counter() - t0) * 1000, 1)

rec = {
    "network": net,
    "image": img,
    "page_no": page_no,
    "engine": page.engine,
    "line_count": len(page.lines),
    "avg_confidence": round(page.avg_confidence, 4),
    "stamp_overlap_lines": len(page.stamp_overlap_lines),
    "elapsed_ms": ms,
    "weights_source": "dist/paddleocr_offline_models.tar.gz",
    "verdict": "PASS" if net == "BLOCKED" and page.lines else "FAIL",
}
out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(rec, ensure_ascii=False))
PY
