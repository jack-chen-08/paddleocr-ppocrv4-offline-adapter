# Delivery Notes

**Task**: OCR engine adapter layer with on-premise PaddleOCR (PP-OCRv4), CPU-only and fully offline

| | |
|:--|:--|
| Delivery | public git repository（交付链接即仓库地址；干净 clone 即可复跑，无需任何外部下载） |
| Engine | PaddleOCR **PP-OCRv4 mobile** (det + rec), CPU only — 任务指定 PP-OCRv4 中文模型 |
| Offline weights | `dist/paddleocr_offline_models.tar.gz` 13.7 MiB + sha256 + MANIFEST（随仓库提交） |
| Tests | **35 passed**（含 14 个印章单测），原始输出 `docs/evidence/pytest.txt` |
| Acceptance | **4 / 4 PASS** —— 四条都在**同一个镜像内**重新测过，数字只出自这一轮 |

> 本轮相对上一版的改动（均为评审意见直接对应项）：
> ① 离线证据从宿主机 `unshare -rn` 换成**真容器** `docker run --network none`，日志 `docs/evidence/docker_offline_proof.log`；
> ② 评估集从 10 页扩到 **15 页（10 原件 + 5 扫描件）**，补上扫描件这个真实场景；
> ③ 延迟用**三次同镜像、同命令、同绑核的容器内 30 样本运行**（P95 3.987 / 3.537 / 4.431 s）说明，取最差一次报余量，不是三次不同时刻拼数；
> ④ README 的镜像体积（原写 1.0 GB → 实测 **2.6 GB**）、测试数（原写 30 → **35**）、权重来源（原写「随仓库分发」→ `official_models/` 已 gitignore，唯一来源是 `dist/*.tar.gz`）三处错误已改；
> ⑤ 全部报告与日志由同一提交、同一次运行生成。

---

## 1. Quick start — 三步跑起来

```bash
git clone https://github.com/jack-chen-08/paddleocr-ppocrv4-offline-adapter && cd paddleocr-ppocrv4-offline-adapter

# 模型以离线包形式随仓库提供，构建期解包并校验 sha256，运行期零外网
docker build -t member-ocr:1.0 .

docker run -d -p 8000:8000 -v $PWD/data:/app/data --name ocr member-ocr:1.0
curl http://127.0.0.1:8000/api/ocr/engine
```

Verify it works — 验证一条:

```bash
curl -F "file=@data/pages/page_01.png" \
  http://127.0.0.1:8000/api/ocr/contracts/C-2026-001/pages/1
```

Expected: line-level JSON, each line carrying `text`, `bbox` (4 corner points), `confidence`, `stamp_overlap`. Result is persisted at `ocr/{contract_id}/{page_no}.json`

非容器方式（本地 pip 环境）见 README「三、快速开始 · 本地」。

---

## 2. Acceptance results — 验收结果（4 条，对应任务原文）

| # | Criterion (任务原文) | Measured — 实测 | Verdict |
|:-:|:--|:--|:-:|
| 1 | 10 张虚构测试页的字符级准确率 ≥ 97%（附计算脚本与输出） | **15 页整体 99.64%**（编辑距离 25 / 6,910 标注字符）；其中 10 页原件 **99.70%**（14 / 4,611）、5 页扫描件 **99.52%**（11 / 2,299）；**单页最低 98.98%**，无单页 < 97% | **PASS** |
| 2 | 断网环境下容器内识别可正常完成（离线运行日志） | **真容器** `docker run --network none`：容器内 `socket.create_connection("pypi.org",443)` → **BLOCKED (gaierror)**，同进程完成 page_03 识别：24 行、均置信度 0.9882、7,223 ms（含引擎初始化）。日志 `docs/evidence/docker_offline_proof.log` | **PASS** |
| 3 | 单页 P95 耗时 ≤ 6 秒（4 核 CPU 压测输出） | 容器内 30 样本（15 页 × 2 轮）、affinity `[0,1,2,3]`：**P50 1.828 s / P95 3.987 s / max 4.179 s**；独立复跑 P95 3.537 s / max 3.933 s（`reports/benchmark_run2.json`）、第三轮 P95 4.431 s / max 4.793 s（`docs/evidence/benchmark_run3.log`） | **PASS**（三轮最差余量 1.35 倍，见 note ③） |
| 4 | 被印章遮挡的行带 stamp_overlap 标记且置信度已降权（单元测试通过） | `tests/test_stamp.py` 6/6 + `tests/test_stamp_second_pass.py` 8/8 passed（全套 35 passed）；penalty `0.8` 每行只施加一次，环形字整行剔除不进正文 | **PASS** |

Reproduce all four — 四条全部可复现（干净 clone 内，逐条对应）:

```bash
bash tools/package_models.sh --verify                                    # 权重包 sha256 与 MANIFEST 一致性
docker build -t member-ocr:1.0 .                                         # 构建期校验并解包权重
bash tools/ci_offline_proof.sh --docker                                  # AC2 → docs/evidence/docker_offline_proof.log
docker run --rm --network none -v $PWD/data:/app/data:ro -v $PWD/reports:/app/reports \
  member-ocr:1.0 python tools/eval_accuracy.py                           # AC1 → reports/accuracy.json
docker run --rm --network none -v $PWD/data:/app/data:ro -v $PWD/reports:/app/reports \
  member-ocr:1.0 python tools/benchmark_p95.py --rounds 2 --cores 4      # AC3 → reports/benchmark.json
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
tools/              eval_accuracy / benchmark_p95 / audit_pages / ci_offline_proof / package_models / gen_test_pages
tests/              35 tests: contract, engine behavior, normalization, stamp rules, stamp second pass
data/               15 synthetic A4 contract pages (10 clean + 5 scanned) + labels.json
dist/               paddleocr_offline_models.tar.gz (13.7 MiB) + .sha256 + MANIFEST.json
reports/            accuracy.json, benchmark.json, benchmark_run2.json, page_audit.md
docs/evidence/      pytest.txt, docker_offline_proof.log, clone_verify.log
docs/ACCEPTANCE.md  acceptance mapping, per-page numbers, known items
models/             运行时解包目录（official_models/ 已 gitignore，不入库）
```

---

## 4. Notes — 三点须知（诚实口径）

**① AC2 已经是字面意义的「容器内」**
`docker run --network none` 跑的就是本仓库 Dockerfile 构建的镜像，镜像内权重来自 `dist/*.tar.gz`（构建期 `sha256sum -c` 校验）。上一版因本机 docker socket 无权限用的是 `unshare -rn`，本轮权限已解决，改成真容器，并保留了脚本两条路径（`tools/ci_offline_proof.sh --docker|--local`）以便在任意环境复现。

**② page 3 曾是最差页，已加固到 100.00%**
Page 3 carries a red stamp sitting directly over a body line. The failure was **not** character-level confusion but detection: the whole line `乙方（盖章）：沐石供应链有限公司` was dropped because the stamp ink covered it, which alone cost 16 characters (96.67%). Fixed by a second pass on the red channel — red ink reads as near-paper-white in the R channel while black body text stays dark, so the covered line is detected and read at 0.99 confidence. The pass runs only on pages that contain a stamp and accepts only lines intersecting the stamp box; results are re-sorted into reading order.
（p03 原 96.67% 的成因是红章压盖导致**整行在检测阶段丢失**，不是错识字。加 R 通道二次识别后该页 100.00%；二次识别仅在含印章页触发，只接收印章区附近的新增行，合并后按阅读顺序重排。）

**③ 延迟余量不是舒适区，明写**
三次独立容器运行整体 P95 分别为 3.987 s / 3.537 s / 4.431 s，按**最差**的 4.431 s 对 6 s 阈值余量 **1.35 倍**，波动区间 3.54–4.43 s，最差单页 4.793 s。瓶颈页是含红章的页（二次识别多一遍）。若 4 核被其它进程抢占，单页 max 会涨到 6 s 以上（README「九、已知边界」已列），生产部署须为 OCR 预留 4 核。不把这条写成「余量充足」。

**④ 模型版本**
The scaffold shipped with PP-OCRv5; per the task's explicit requirement this delivery is on **PP-OCRv4 mobile** and all four criteria were re-measured on it. v4 vs v5 精度基本持平（99.64% vs 99.72%），两者均过 97% 阈值。Switching is a single environment variable:
`PADDLE_OCR_DET_MODEL_NAME=PP-OCRv5_mobile_det PADDLE_OCR_REC_MODEL_NAME=PP-OCRv5_mobile_rec`

---

## 5. Scope compliance — 范围硬条款

OCR output always enters the **human review queue**; no business data is written and nothing is sent outbound before a human confirms. Neither OCR nor AI computes any amount. All 15 test pages are synthetic (generated by `tools/gen_test_pages.py`, no real company names, IDs, or account numbers).
（OCR 结果一律进人工核对队列，确认前不写业务数据、不对外发送；不计算金额；15 页测试页全部虚构。）
