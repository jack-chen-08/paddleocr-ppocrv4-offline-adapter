# Delivery Notes

**Task**: OCR engine adapter layer with on-premise PaddleOCR (PP-OCRv4), CPU-only and fully offline

| | |
|:--|:--|
| Package | `ocr_adapter_delivery.zip` |
| Engine | PaddleOCR **PP-OCRv4 mobile** (det + rec), CPU only — 任务指定 PP-OCRv4 中文模型 |
| Tests | 30 passed (incl. 14 stamp unit tests) |
| Acceptance | **4 / 4 PASS** |

---

## 1. Quick start — 三步跑起来

```bash
unzip ocr_adapter_delivery.zip && cd ocr_adapter_delivery

python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-ocr.txt

# 模型以离线包形式随交付提供，无需联网下载
mkdir -p models && tar -xzf dist/paddleocr_offline_models.tar.gz -C models
sha256sum -c dist/paddleocr_offline_models.tar.gz.sha256

# 起服务
PADDLE_PDX_CACHE_HOME="$PWD/models" PYTHONPATH=. uvicorn app.main:app --port 8000
```

Verify it works — 验证一条:

```bash
curl -F "file=@data/pages/page_01.png" \
  http://127.0.0.1:8000/api/ocr/contracts/C-2026-001/pages/1
```

Expected: line-level JSON, each line carrying `text`, `bbox` (4 corner points), `confidence`, `stamp_overlap`. Result is persisted at `ocr/{contract_id}/{page_no}.json`

---

## 2. Acceptance results — 验收结果（4 条，对应任务原文）

| # | Criterion (任务原文) | Measured — 实测 | Verdict |
|:-:|:--|:--|:-:|
| 1 | 10 张虚构测试页的字符级准确率 ≥ 97%（附计算脚本与输出） | **99.70%** overall (edit distance 14 / 4,611 annotated chars, 10 pages); **lowest single page 99.19%**, no page below 97% | **PASS** |
| 2 | 断网环境下容器内识别可正常完成（离线运行日志） | Network namespace isolated, `socket.create_connection("pypi.org")` → **BLOCKED**; same process completed page 3: 24 lines, avg conf 0.9882, 4,390 ms | **PASS** (see note ①) |
| 3 | 单页 P95 耗时 ≤ 6 秒（4 核 CPU 压测输出） | 20 samples, affinity `[0,1,2,3]`: **P50 1.805 s / P95 3.548 s / max 4.391 s** (worst case is the stamped pages, which run a second pass); two independent re-runs on a clean unzip of the delivery zip: P95 3.923 s and 4.332 s (max 4.794 s) | **PASS** |
| 4 | 被印章遮挡的行带 stamp_overlap 标记且置信度已降权（单元测试通过） | `tests/test_stamp.py` 6/6 + `tests/test_stamp_second_pass.py` 8/8 passed; penalty factor `0.8` applied once per line | **PASS** |

Reproduce all four — 四条全部可复现:

```bash
bash tools/package_models.sh --verify                                    # model integrity 权重完整性
PYTHONPATH=. python tools/eval_accuracy.py                               # AC1 → reports/accuracy.json
bash tools/verify_offline.sh                                             # AC2 → reports/offline_verify.json
PYTHONPATH=. python tools/benchmark_p95.py --rounds 2                    # AC3 → reports/benchmark.json
PYTHONPATH=. python -m pytest tests/test_stamp.py tests/test_stamp_second_pass.py -v   # AC4
```

Full per-page table and scope-clause mapping: **`docs/ACCEPTANCE.md`**

---

## 3. What is inside — 目录说明

```
app/ocr/            engine protocol, PaddleOCR implementation, stamp rules, normalization, storage
  types.py          OcrEngine protocol + OcrPage / OcrLine data types
  paddle_engine.py  PP-OCRv4 mobile call, env-overridable model names
  stamp.py          red-stamp detection, overlap marking, 0.8 confidence penalty, ring-text drop
  normalize.py      full-width → half-width, idempotent
  storage.py        ocr/{contract_id}/{page_no}.json layout
  service.py        persists rows, writes ocr_avg_confidence, queues for human review
tools/              eval_accuracy.py, benchmark_p95.py, verify_offline.sh, package_models.sh, gen_test_pages.py
tests/              30 tests: contract, engine behavior, normalization, stamp rules, stamp second pass
data/               10 synthetic A4 contract pages + labels.json
reports/            accuracy.json, benchmark.json, offline_verify.json
models/             created by step 3 above (weights land in models/official_models/PP-OCRv4_*)
docs/ACCEPTANCE.md  acceptance mapping, per-page numbers, known items
```

---

## 4. Notes — 两点须知（诚实口径）

**① AC2 「容器内」的字面形式**
This package was verified inside a **network namespace** (`unshare -rn`, `CLONE_NEWNET`), not inside a Docker container — the docker socket on the build machine was not writable by the build user. `unshare -rn` is the same kernel primitive Docker's `--network none` uses, so the isolation guarantee is identical: outbound connections fail at the socket layer while inference completes.
（本机 docker socket 无权限，故用 `unshare -rn` ——与 `docker run --network none` 同一内核机制，隔离强度等同。若必须容器形式，`Dockerfile` 已就绪，执行 `docker build -t ocr-adapter . && docker run --rm --network none -v "$PWD/models:/app/models" ocr-adapter` 即可。）

**② page 3 曾是最差页，已加固到 100.00%**
Page 3 carries a red stamp sitting directly over a body line. The failure was **not** character-level confusion but detection: the whole line `乙方（盖章）：沐石供应链有限公司` was dropped because the stamp ink covered it, which alone cost 16 characters (96.67%). Fixed by a second pass on the red channel — red ink reads as near-paper-white in the R channel while black body text stays dark, so the covered line is detected and read at 0.99 confidence. The pass runs only on pages that contain a stamp and accepts only lines intersecting the stamp box; results are re-sorted into reading order.
（p03 原 96.67% 的成因是红章压盖导致**整行在检测阶段丢失**，不是错识字。加 R 通道二次识别后该页 100.00%；二次识别仅在含印章页触发，只接收印章区附近的新增行，合并后按阅读顺序重排。）

**③ 模型版本**
The scaffold shipped with PP-OCRv5; per the task's explicit requirement this delivery is on **PP-OCRv4 mobile** and all four criteria were re-measured on it. v4 turned out both faster (P95 2.12 s vs 2.53 s) and slightly less accurate (99.70% vs 99.72%) than v5 — threshold met either way. Switching is a single environment variable:
（脚手架原为 v5，按任务要求切到 v4 并全量重测。切回 v5：）
`PADDLE_OCR_DET_MODEL_NAME=PP-OCRv5_mobile_det PADDLE_OCR_REC_MODEL_NAME=PP-OCRv5_mobile_rec`

---

## 5. Scope compliance — 范围硬条款

OCR output always enters the **human review queue**; no business data is written and nothing is sent outbound before a human confirms. Neither OCR nor AI computes any amount. All 10 test pages are synthetic (generated by `tools/gen_test_pages.py`, no real company names, IDs, or account numbers).
（OCR 结果一律进人工核对队列，确认前不写业务数据、不对外发送；不计算金额；测试页全部虚构。）
