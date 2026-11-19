#!/usr/bin/env bash
# 客户视角冒烟：只从交付 zip 解压出来的干净副本重跑四项验收
set -uo pipefail
ZIP="./dist/ocr_adapter_delivery.zip"
W=/tmp/cust_$$
rm -rf "$W"; mkdir -p "$W"; cd "$W"
unzip -q "$ZIP"
cd ocr_adapter_delivery
# 客户环境自建 venv：python3 -m venv .venv && . .venv/bin/activate

echo "=== S0 sha256 自校验（客户第一条命令）==="
cd dist && sha256sum -c paddleocr_offline_models.tar.gz.sha256; cd ..

echo "=== S1 解包权重 ==="
mkdir -p models && tar -xzf dist/paddleocr_offline_models.tar.gz -C models
ls models/official_models/

echo "=== S2 pytest（30 用例）==="
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3

echo "=== S3 AC1 字符准确率 ==="
PADDLE_PDX_CACHE_HOME="$PWD/models" PYTHONPATH=. .venv/bin/python tools/eval_accuracy.py 2>&1 | grep -Ei "overall|PASS|FAIL|accuracy" | tail -4

echo "=== S4 AC2 断网识别 ==="
bash tools/verify_offline.sh 2>&1 | tail -2

echo "=== S5 AC3 P95（2 轮）==="
PADDLE_PDX_CACHE_HOME="$PWD/models" PYTHONPATH=. .venv/bin/python tools/benchmark_p95.py --rounds 2 2>&1 | grep -Ei "p50|p95|max|PASS|FAIL" | tail -5

echo "=== S6 AC4 印章单测（含二次识别）==="
PYTHONPATH=. .venv/bin/python -m pytest tests/test_stamp.py tests/test_stamp_second_pass.py -q 2>&1 | tail -2

echo "=== S7 包体 ==="
du -sh "$W/ocr_adapter_delivery"
cd /; rm -rf "$W"
echo "SMOKE_DONE"
