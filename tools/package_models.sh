#!/usr/bin/env bash
# =============================================================================
# 离线模型打包脚本 / Offline model packaging script
#
# 作用：把 PaddleOCR 推理权重固化成可离线搬运的单一压缩包 + 清单（MANIFEST.json），
#       镜像构建时直接 COPY，运行期不再联网（对应任务要求「模型文件随镜像离线提供」）。
#
# 用法 / Usage:
#   bash tools/package_models.sh                 # 打包 + 自校验
#   bash tools/package_models.sh --verify        # 只校验已有包，不重新打包
#   bash tools/package_models.sh --models PP-OCRv4_mobile_det PP-OCRv4_mobile_rec
#
# 退出码：0 成功；2 权重缺失；3 校验失败
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_ROOT="$ROOT/models"
OFFICIAL_DIR="$MODELS_ROOT/official_models"
DIST_DIR="$ROOT/dist"
REQUIRED_MODELS=("PP-OCRv4_mobile_det" "PP-OCRv4_mobile_rec")
VERIFY_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify) VERIFY_ONLY=1; shift ;;
    --models) shift; REQUIRED_MODELS=(); while [[ $# -gt 0 && "$1" != --* ]]; do REQUIRED_MODELS+=("$1"); shift; done ;;
    --models-dir) MODELS_ROOT="$2"; OFFICIAL_DIR="$2/official_models"; shift 2 ;;
    --out-dir) DIST_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

PKG_NAME="paddleocr_offline_models"
TARBALL="$DIST_DIR/${PKG_NAME}.tar.gz"
MANIFEST="$DIST_DIR/${PKG_NAME}.MANIFEST.json"

log() { printf '[package_models] %s\n' "$*"; }
die() { printf '[package_models] ERROR: %s\n' "$*" >&2; exit "${2:-3}"; }

# --- 1. 权重存在性检查 -------------------------------------------------------
missing=()
for m in "${REQUIRED_MODELS[@]}"; do
  [[ -d "$OFFICIAL_DIR/$m" ]] || missing+=("$m")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  cat >&2 <<EOF
[package_models] ERROR: 缺少权重目录 ${missing[*]}（在 $OFFICIAL_DIR 下）
首次准备（需联网一次，之后永久离线）：
  PADDLE_PDX_CACHE_HOME="\$PWD/models" python -c "
from paddleocr import PaddleOCR
PaddleOCR(lang='ch', device='cpu',
          text_detection_model_name='PP-OCRv4_mobile_det',
          text_recognition_model_name='PP-OCRv4_mobile_rec',
          use_doc_orientation_classify=False, use_doc_unwarping=False,
          use_textline_orientation=False)"
EOF
  exit 2
fi

mkdir -p "$DIST_DIR"

# --- 2. 校验模式 -------------------------------------------------------------
if [[ $VERIFY_ONLY -eq 1 ]]; then
  [[ -f "$TARBALL" ]] || die "包不存在：$TARBALL"
  [[ -f "$MANIFEST" ]] || die "清单不存在：$MANIFEST"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  log "解包校验 $TARBALL"
  tar -xzf "$TARBALL" -C "$TMP"
  python3 - "$MANIFEST" "$TMP" <<'PY'
import hashlib, json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
root = pathlib.Path(sys.argv[2])
bad = []
for f in manifest["files"]:
    p = root / f["path"]
    if not p.exists():
        bad.append((f["path"], "missing")); continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != f["sha256"]:
        bad.append((f["path"], f"sha256 {h[:12]} != {f['sha256'][:12]}"))
    elif p.stat().st_size != f["bytes"]:
        bad.append((f["path"], "size mismatch"))
# 反向检查：包内不得有清单外的文件（防「清单说 15MiB、包却有 132MiB」式漂移）
listed = {f["path"] for f in manifest["files"]}
extra = [p.relative_to(root).as_posix() for p in root.rglob("*")
         if p.is_file() and p.relative_to(root).as_posix() not in listed]
if extra:
    bad.append((extra[0], f"清单外文件 {len(extra)} 个（首个）"))
if bad:
    for p, r in bad[:20]:
        print(f"FAIL {p}: {r}", file=sys.stderr)
    sys.exit(3)
print(f"OK: {len(manifest['files'])} 个文件全部通过 sha256 校验，无清单外文件")
PY
  log "校验通过 ✅"
  exit 0
fi

# --- 3. 生成清单 -------------------------------------------------------------
log "扫描权重目录 $OFFICIAL_DIR"
python3 - "$OFFICIAL_DIR" "$MANIFEST" "${REQUIRED_MODELS[@]}" <<'PY'
import hashlib, json, pathlib, subprocess, sys, datetime

official = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path(sys.argv[2])
models = sys.argv[3:]

def ver(pkg):
    try:
        out = subprocess.run([sys.executable, "-c", f"import {pkg};print({pkg}.__version__)"],
                             capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"

files = []
total = 0
per_model = {}
for m in models:
    mdir = official / m
    mbytes = 0
    mcount = 0
    for p in sorted(mdir.rglob("*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        rel = p.relative_to(official.parent).as_posix()  # models/official_models/<m>/...
        files.append({"path": rel, "bytes": len(data), "sha256": h})
        total += len(data); mbytes += len(data); mcount += 1
    per_model[m] = {"files": mcount, "bytes": mbytes}

manifest = {
    "package": "paddleocr_offline_models",
    "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "models": per_model,
    "runtime": {
        "paddleocr": ver("paddleocr"),
        "paddlepaddle": ver("paddlepaddle"),
        "numpy": ver("numpy"),
    },
    "total_bytes": total,
    "file_count": len(files),
    "files": files,
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"清单已写：{manifest_path}（{len(files)} 文件 / {total/1024/1024:.1f} MiB）")
for m, v in per_model.items():
    print(f"  {m}: {v['files']} 文件 / {v['bytes']/1024/1024:.1f} MiB")
PY

# --- 4. 打包 -----------------------------------------------------------------
log "打包 → $TARBALL"
TAR_PATHS=()
for m in "${REQUIRED_MODELS[@]}"; do TAR_PATHS+=("official_models/$m"); done
tar -czf "$TARBALL" -C "$MODELS_ROOT" "${TAR_PATHS[@]}"
PKG_SHA="$(sha256sum "$TARBALL" | cut -d' ' -f1)"
PKG_BYTES="$(stat -c%s "$TARBALL")"
printf '%s  %s\n' "$PKG_SHA" "$(basename "$TARBALL")" > "${TARBALL}.sha256"
log "完成：$(basename "$TARBALL")  $((PKG_BYTES/1024/1024)) MiB  sha256=$PKG_SHA"

# --- 5. 打完自校验 -----------------------------------------------------------
log "自校验（解包重算 sha256）"
bash "${BASH_SOURCE[0]}" --verify --out-dir "$DIST_DIR" ${REQUIRED_MODELS[*]/#/--models } >/dev/null 2>&1 \
  || bash "${BASH_SOURCE[0]}" --verify --out-dir "$DIST_DIR"
echo
echo "镜像内使用方式（Dockerfile COPY）："
echo "  COPY $PKG_NAME.tar.gz /tmp/"
echo "  RUN tar -xzf /tmp/$PKG_NAME.tar.gz -C /app/models && rm /tmp/$PKG_NAME.tar.gz"
echo "  ENV PADDLE_PDX_CACHE_HOME=/app/models HF_HUB_OFFLINE=1"
