#!/usr/bin/env bash
# 打交付包 v2：只带 PP-OCRv4 权重（v5/v6 留开发机），排除 venv/缓存
set -euo pipefail
SRC="$PWD"
NAME="ocr_adapter_delivery"
STAGE="/tmp/pack_$$/$NAME"
OUT="$SRC/dist/ocr_adapter_delivery.zip"

rm -rf "/tmp/pack_$$"
mkdir -p "$STAGE/models/official_models" "$STAGE/dist"

# 代码、测试、数据、文档、报告
for d in app tools tests data docs reports; do
  [ -d "$SRC/$d" ] && cp -a "$SRC/$d" "$STAGE/$d"
done
for f in README.md DELIVERY.md requirements.txt requirements-ocr.txt Dockerfile Makefile; do
  [ -f "$SRC/$f" ] && cp -a "$SRC/$f" "$STAGE/$f"
done

# 权重只以 dist/*.tar.gz 形式交付（tar 内已含 official_models/PP-OCRv4_*，解压即成形）
# 不再重复拷一份明文到 models/，避免包体翻倍

# 离线模型包 + 清单
cp -a "$SRC/dist/paddleocr_offline_models.tar.gz" \
      "$SRC/dist/paddleocr_offline_models.tar.gz.sha256" \
      "$SRC/dist/paddleocr_offline_models.MANIFEST.json" "$STAGE/dist/"

# 清理缓存
find "$STAGE" -type d \( -name __pycache__ -o -name .pytest_cache -o -name .venv \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true

# 不先删目标：先写临时包并自校验，通过后才原子替换（避免打包中途失败丢掉旧包）
TMPOUT="/tmp/ocr_adapter_delivery_v2.$$.zip"
rm -f "$TMPOUT"
cd "/tmp/pack_$$"
zip -qr "$TMPOUT" "$NAME" -x '*.pyc'
cd "$SRC"

echo "=== INTEGRITY (tmp) ==="
unzip -t "$TMPOUT" 2>&1 | tail -2
if ! unzip -t "$TMPOUT" > /dev/null 2>&1; then echo "FATAL: tmp zip failed integrity, old package kept"; rm -f "$TMPOUT"; rm -rf "/tmp/pack_$$"; exit 1; fi
mv -f "$TMPOUT" "$OUT"

echo "=== ZIP ==="
ls -l "$OUT" | awk '{print $5" bytes  "$9}'
sha256sum "$OUT" | awk '{print "sha256 "$1}'
echo "=== FILE COUNT BY DIR ==="
unzip -Z1 "$OUT" | awk -F/ 'NF>2{print $2}' | sort | uniq -c | sort -rn
echo "=== TOP LEVEL ==="
unzip -Z1 "$OUT" | awk -F/ 'NF==2 && $2!=""{print}' | sort
LIST="/tmp/zip_list_$$.txt"
unzip -Z1 "$OUT" > "$LIST"
echo "=== 权重出现位置（应在 dist tar.gz 内，models/ 下不重复）==="
echo "models/ 下 v4 条目: $(grep -c "models/official_models/PP-OCRv4" "$LIST" || true)  (期望 0)"
echo "v5/v6 残留: $(grep -cE "PP-OCRv5|PP-OCRv6" "$LIST" || true)  (期望 0)"
echo "=== KEY FILES PRESENT ==="
MISS=0
for k in README.md DELIVERY.md docs/ACCEPTANCE.md tools/package_models.sh tools/verify_offline.sh \
         tools/eval_accuracy.py tools/benchmark_p95.py tools/audit_pages.py \
         tests/test_stamp_second_pass.py reports/page_audit.md \
         reports/accuracy.json reports/benchmark.json reports/offline_verify.json \
         dist/paddleocr_offline_models.tar.gz dist/paddleocr_offline_models.tar.gz.sha256 \
         data/labels.json app/ocr/paddle_engine.py app/ocr/types.py; do
  if grep -Fxq "$NAME/$k" "$LIST"; then echo "OK   $k"; else echo "MISS $k"; MISS=$((MISS+1)); fi
done
echo "=== MISSING TOTAL: $MISS (期望 0) ==="
rm -f "$LIST"
rm -rf "/tmp/pack_$$"
