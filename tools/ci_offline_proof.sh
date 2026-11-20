#!/usr/bin/env bash
# =============================================================================
# AC2 离线证明 / Offline proof for "断网容器内识别可正常完成"
#
# 本脚本只有两种模式，都必须真实执行、不伪造日志：
#   bash tools/ci_offline_proof.sh --docker   # 有 docker 权限时用（唯一字面满足「容器内」的方式）
#   bash tools/ci_offline_proof.sh --local    # 无 docker 权限时用：unshare -rn（CLONE_NEWNET）等价隔离
#
# 两种模式做同一件事：
#   1. 只从 dist/paddleocr_offline_models.tar.gz 解包权重（不碰仓库 models/，干净克隆里它不存在）
#   2. PADDLE_OCR_DET_MODEL_DIR / PADDLE_OCR_REC_MODEL_DIR 指向解出来的目录
#   3. 断网状态下先证明外网不可达，再跑一页真实识别并打印行数/置信度/耗时
#
# 依赖：python3 + requirements-ocr.txt（paddleocr / paddlepaddle）
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARBALL="$ROOT/dist/paddleocr_offline_models.tar.gz"
SHAFILE="$ROOT/dist/paddleocr_offline_models.tar.gz.sha256"
PAGE="${PAGE:-$ROOT/data/pages/page_03.png}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

MODE="${1:---local}"
IMAGE="${IMAGE:-member-ocr:offline}"

[[ -f "$TARBALL" ]] || { echo "ERROR: 缺少 $TARBALL" >&2; exit 1; }

# ---- 识别一页的自检程序（容器内外共用同一份）--------------------------------
read -r -d '' PROOF_PY <<'PY' || true
import os, socket, sys, time
from pathlib import Path

det = os.environ["PADDLE_OCR_DET_MODEL_DIR"]
rec = os.environ["PADDLE_OCR_REC_MODEL_DIR"]
print(f"[proof] det_model_dir = {det}")
print(f"[proof] rec_model_dir = {rec}")
for p in (det, rec):
    assert Path(p, "inference.pdiparams").is_file(), f"missing weights: {p}"
    assert Path(p, "inference.json").is_file(), f"missing graph: {p}"

# 1) 先证明网络确实断了
try:
    socket.setdefaulttimeout(3)
    socket.create_connection(("pypi.org", 443), 3)
    print("[proof] NETWORK: REACHABLE -> 隔离失败，本次证据无效")
    sys.exit(2)
except Exception as e:
    print(f"[proof] NETWORK: BLOCKED -> {type(e).__name__}: {e}")

# 2) 断网下跑一页识别
from app.ocr.paddle_engine import PaddleOcrEngine
page_path = Path(sys.argv[1])
t0 = time.perf_counter()
engine = PaddleOcrEngine(lang="ch")
page = engine.recognize(page_path, page_no=3)
dt = time.perf_counter() - t0
print(f"[proof] page          = {page_path.name}")
print(f"[proof] lines         = {len(page.lines)}")
print(f"[proof] avg_confidence= {page.avg_confidence:.4f}")
print(f"[proof] stamp_overlap = {len(page.stamp_overlap_lines)} line(s)")
print(f"[proof] elapsed       = {dt*1000:.0f} ms (engine init + inference)")
for line in page.lines[:3]:
    print(f"[proof]   {line.confidence:.4f}  {line.text}")
print("[proof] RESULT: OK — 断网状态下识别完成")
PY

run_local() {
  echo "=== 模式：unshare -rn（CLONE_NEWNET，与 docker run --network none 同一内核机制）==="
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  echo "--- 1. 从 dist 解包权重（仓库 models/ 完全不参与）"
  ( cd "$(dirname "$TARBALL")" && sha256sum -c "$(basename "$SHAFILE")" )
  tar -xzf "$TARBALL" -C "$WORK"
  du -sh "$WORK"
  echo "--- 2. 断网 + 指向解包后的权重，跑一页"
  cd "$ROOT"
  unshare -rn env \
    PADDLE_OCR_DET_MODEL_DIR="$WORK/official_models/PP-OCRv4_mobile_det" \
    PADDLE_OCR_REC_MODEL_DIR="$WORK/official_models/PP-OCRv4_mobile_rec" \
    PADDLE_PDX_CACHE_HOME="$WORK" \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PYTHONPATH="$ROOT" \
    "$PYTHON" -c "$PROOF_PY" "$PAGE"
}

run_docker() {
  echo "=== 模式：docker build + docker run --network none（字面意义的容器内）==="
  echo "--- 1. 构建（Dockerfile 在构建期解包 dist/*.tar.gz 到 /app/models 并校验 sha256）"
  docker build -t "$IMAGE" "$ROOT"
  echo "--- 2. 断网容器内跑一页识别（镜像内已设 PADDLE_OCR_DET/REC_MODEL_DIR）"
  docker run --rm --network none \
    -v "$ROOT/data:/app/data:ro" \
    "$IMAGE" \
    python -c "$PROOF_PY" /app/data/pages/page_03.png
}

case "$MODE" in
  --local)  run_local ;;
  --docker) run_docker ;;
  *) echo "用法: $0 [--local|--docker]" >&2; exit 1 ;;
esac
