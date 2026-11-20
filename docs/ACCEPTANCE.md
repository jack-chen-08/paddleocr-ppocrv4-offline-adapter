# 验收对照表

**验收标准来源**：任务要求原文 4 条，交付前逐条对照实测，证据可复跑。
**本轮口径**：全部数字出自**同一个提交、同一个镜像、同一次运行**（`docker run --network none`）。原始日志 `docs/evidence/`，原始 JSON `reports/`，一一对应，没有跨时刻拼数。

---

## 一、验收标准（4 条，逐字）

| # | 验收标准（原文） | 实测结果 | 判定 | 证据 |
|:-:|:--|:--|:-:|:--|
| 1 | 10 张虚构测试页的字符级准确率 ≥ 97%（附计算脚本与输出） | **主指标严格按工单约定的标准测试集统计**：10 页原件 **99.70%**（编辑距离 14 / 标注 4,611 字符）；另加 5 页扫描畸变样本作鲁棒性补充，两组单列——扫描组 99.52%（11 / 2,299）、15 页整体 99.64%（25 / 6,910），**两组均高于 97% 门槛**，无择优挑样本；**单页最低 98.98%（scan_15），无单页 < 97%** | **PASS** | `tools/eval_accuracy.py` → `reports/accuracy.json`；日志 `docs/evidence/accuracy_run.log` |
| 2 | 断网环境下容器内识别可正常完成（离线运行日志） | **真容器** `docker run --network none`（镜像由本仓库 Dockerfile 构建，权重在构建期从 `dist/*.tar.gz` 校验解包）：容器内 `socket.create_connection("pypi.org",443)` → **BLOCKED (gaierror)**；同进程完成 page_03 识别：24 行、avg_conf 0.9882、7,223 ms（含引擎初始化） | **PASS** | `tools/ci_offline_proof.sh --docker` → `docs/evidence/docker_offline_proof.log` |
| 3 | 单页 P95 耗时 ≤ 6 秒（4 核 CPU 压测输出） | 容器内 30 样本（15 页 × 2 轮）、`sched_setaffinity` 绑核 [0,1,2,3]：**P50 1.828 s / P95 3.987 s / max 4.179 s**；独立复跑（同一镜像、`reports/benchmark_run2.json`）P95 **3.537 s** / max 3.933 s。**对 6 s 余量 1.50 倍**（按两轮里较差的一次算，见 §四-③） | **PASS** | `tools/benchmark_p95.py --rounds 2 --cores 4` → `reports/benchmark.json`、`reports/benchmark_run2.json` |
| 4 | 被印章遮挡的行带 stamp_overlap 标记且置信度已降权（单元测试通过） | `tests/test_stamp.py` 6 + `tests/test_stamp_second_pass.py` 8 全通过（全套 **35 passed**）；降权系数 0.8（`CONFIDENCE_PENALTY`），每行只施加一次；章内环形字整行剔除不进正文 | **PASS** | `docs/evidence/pytest.txt` |

**复现（干净 clone 内，全部只读本地，不需要任何外部下载）**

```bash
git clone https://github.com/jack-chen-08/paddleocr-ppocrv4-offline-adapter && cd paddleocr-ppocrv4-offline-adapter
bash tools/package_models.sh --verify                                        # 权重包 sha256 + MANIFEST 一致性
docker build -t member-ocr:1.0 .                                             # 构建期校验并解包权重
bash tools/ci_offline_proof.sh --docker                                      # AC2
docker run --rm --network none -v $PWD/data:/app/data:ro -v $PWD/reports:/app/reports \
  member-ocr:1.0 python tools/eval_accuracy.py                               # AC1
docker run --rm --network none -v $PWD/data:/app/data:ro -v $PWD/reports:/app/reports \
  member-ocr:1.0 python tools/benchmark_p95.py --rounds 2 --cores 4          # AC3
PYTHONPATH=. python -m pytest tests/ -q                                      # AC4（35 passed）
```

### AC1 逐页明细（不是抽样，15 页全列）

| 页 | 组 | 标注字符 | 编辑距离 | 准确率 | 行数 | 印章遮挡行 | 耗时 |
|:--|:--|--:|--:|--:|--:|--:|--:|
| page_01.png | clean | 459 | 2 | 99.56% | 23 | 0 | 2.87 s |
| page_02.png | clean | 453 | 1 | 99.78% | 23 | 0 | 2.16 s |
| page_03.png | clean | 480 | 0 | **100.00%** | 24 | 1 | 4.16 s |
| page_04.png | clean | 452 | 1 | 99.78% | 22 | 0 | 1.64 s |
| page_05.png | clean | 451 | 1 | 99.78% | 22 | 0 | 1.71 s |
| page_06.png | clean | 491 | 4 | 99.19% | 23 | 1 | 3.82 s |
| page_07.png | clean | 452 | 1 | 99.78% | 23 | 0 | 1.87 s |
| page_08.png | clean | 440 | 1 | 99.77% | 22 | 0 | 1.90 s |
| page_09.png | clean | 481 | 2 | 99.58% | 23 | 1 | 3.75 s |
| page_10.png | clean | 452 | 1 | 99.78% | 22 | 0 | 1.91 s |
| scan_11.png | scanned | 453 | 1 | 99.78% | 23 | 0 | 1.60 s |
| scan_12.png | scanned | 452 | 0 | **100.00%** | 22 | 0 | 1.57 s |
| scan_13.png | scanned | 451 | 4 | 99.11% | 22 | 0 | 2.09 s |
| scan_14.png | scanned | 452 | 1 | 99.78% | 23 | 0 | 2.08 s |
| scan_15.png | scanned | 491 | 5 | 98.98% | 23 | 1 | 3.48 s |
| **合计/整体** | — | **6,910** | **25** | **99.64%** | — | 4 | — |

> 口径说明：AC1 任务原文写「10 张虚构测试页」，本轮**主动扩到 15 页**并分组统计——原件 10 页单列，可直接对原条款；扫描件 5 页是补强项（真实合同多为扫描件）。**单页最低 98.98%（scan_15）**，15 页无一低于 97%，「整体」与「每页」两种口径同时成立。
> page_03（红章压盖页）已从 96.67% 加固到 **100.00%**，加固方式见 §四-②。

---

## 二、本单范围硬条款符合性（任务「本单范围」逐条）

| # | 范围原文要点 | 实现落点 | 状态 |
|:-:|:--|:--|:-:|
| 1 | `OcrEngine.recognize(page_image) -> OcrPage` | `app/ocr/types.py` 的 `OcrEngine` Protocol：`recognize(page_image: bytes\|str, *, page_no:int=1) -> OcrPage` | ✅ |
| 2 | 输出行级 `[{text, bbox（四点坐标）, confidence}]` | `OcrLine{text, bbox[4][2], confidence, stamp_overlap}` | ✅ |
| 3 | 本地部署 PaddleOCR，**PP-OCRv4 中文模型**，模型文件随镜像离线提供，CPU 推理 | 默认 `PP-OCRv4_mobile_det` + `PP-OCRv4_mobile_rec`；权重固化为 **13.7 MiB 离线包** `dist/paddleocr_offline_models.tar.gz`（sha256 + MANIFEST 双向校验），**构建期**解包进镜像，运行期零外网 | ✅ |
| 4 | 不得调用任何境外或公有云 OCR 接口（离线可运行） | 代码路径无任何外呼；`docker run --network none` 实测 `BLOCKED` 下识别成功 | ✅ |
| 5 | 红色印章区域检测 | `app/ocr/stamp.py::detect_stamps`（HSV 红色双段阈值 + 轮廓面积/圆形度过滤） | ✅ |
| 6 | 遮挡行 confidence × 0.8 并打 `stamp_overlap` | `CONFIDENCE_PENALTY = 0.8`；`apply_stamp_rules` 按行框与印章区域交叠判定 | ✅ |
| 7 | 环形文字不进入正文 | `drop_ring_text`：印章区内的环形排列短行剔除（实测 page_03 剔 7 行 / page_06 剔 6 行 / page_09 剔 5 行 / scan_15 剔 6 行） | ✅ |
| 8 | 全角半角统一（数字、括号、冒号、小数点） | `app/ocr/normalize.py::normalize_text`；`tests/test_normalize.py` 5 用例（含幂等性、中文句读保留） | ✅ |
| 9 | 结果写入 `ocr/{contract_id}/{page_no}.json` | `app/ocr/storage.py::ocr_object_key`；`tests/test_ocr_service.py::test_object_key_layout` | ✅ |
| 10 | 回写 `doc_contract_page.ocr_avg_confidence` | `app/ocr/service.py` 写 `row.ocr_avg_confidence = round(page.avg_confidence, 4)`；`test_db_row_written_when_session_given` | ✅ |
| 11 | P95 ≤ 6 s @ 4 核 | 容器内实测 P95 3.987 s（复跑 3.537 s）；仅含印章页跑二次识别 | ✅ |
| 12 | OCR 字段一律进人工核对队列，确认前不写业务数据、不对外发送 | 识别后写 `review_item`（pending），不写任何业务表、不发任何外呼 | ✅ |
| 13 | OCR 与 AI 都不计算金额 | 结果体不含金额字段；`amount_computed` 恒为 false | ✅ |
| 14 | 测试页全部虚构 | `tools/gen_test_pages.py` + `tools/gen_scan_pages.py` 程序化生成，公司名/证件号/账号全部合成 | ✅ |

---

## 三、交付物清单对照（任务「交付物」5 项）

| # | 交付物原文 | 交付路径 | 实测 |
|:-:|:--|:--|:-:|
| 1 | OcrEngine 接口与 PaddleOCR 实现 | `app/ocr/types.py`、`app/ocr/paddle_engine.py` | ✅ |
| 2 | 离线模型打包脚本 | `tools/package_models.sh`（MANIFEST + sha256 双向校验，`--verify` 可在干净 clone 内独立跑） | ✅ 实跑通过 |
| 3 | 虚构合同页图片及标注文本 | `data/pages/page_01..10.png` + `scan_11..15.png` + `data/labels.json`（15 页） | ✅ |
| 4 | 准确率与性能测试报告 | `reports/accuracy.json`、`reports/benchmark.json`、`reports/benchmark_run2.json`、`reports/page_audit.md`、`docs/evidence/*.log` | ✅ |
| 5 | README | `README.md`（安装/运行/模型替换/部署/已知边界） | ✅ |

---

## 四、已知项与未验证项（不隐瞒）

① **AC2 已是字面意义的「容器内」**——本轮 `docker run --network none` 跑的就是本仓库 Dockerfile 构建的镜像，构建期 `sha256sum -c` 校验权重包后解包到 `/app/models`。上一版因本机 docker socket 无权限改用 `unshare -rn`，本轮已解决；脚本保留 `--docker|--local` 两条路径，任选其一可复现。

② **page_03 已从 96.67% 加固到 100.00%**：原失分不是错识字，而是红章压盖导致整行 `乙方（盖章）：沐石供应链有限公司` 在**检测阶段整行丢失**（16 字符）。
加固方式：对含印章页追加一次 **R 通道识别**（红墨在 R 通道接近纸白、黑字仍暗，故章下正文显现），只接收与印章区相交的新增行，与原结果同行去重后按阅读顺序重排，最后统一做一次降权与环形文字剔除。
代价：仅印章页耗时增加（实测该页 2.9–4.2 s），整体 P95 3.987 s，仍 < 6 s。

③ **延迟余量与镜像体积，都明写**：
- P95 3.987 s 对 6 s 的余量 **1.50 倍**（两轮容器运行 3.537–3.987 s，按较差的一轮算）。若 4 核被其它进程抢占，单页 max 会冲破 6 s，生产部署须为 OCR 预留独占 4 核。
- 镜像实测 **2.6 GB**（paddlepaddle CPU 轮子解包 ~1.1 GB + 依赖 ~1.4 GB + 权重 16 MB）。上一版 README 写「约 1.0 GB」是错的，已改。若需瘦身可换精简轮子或改 ONNX Runtime 推理，属后续优化项，不影响本轮验收。

④ **模型版本**：脚手架原为 PP-OCRv5，按任务要求切到 **PP-OCRv4 mobile** 并重跑全部四项。v4 精度 99.64% vs v5 99.72%，均过阈值；可用环境变量切回：
`PADDLE_OCR_DET_MODEL_NAME=PP-OCRv5_mobile_det PADDLE_OCR_REC_MODEL_NAME=PP-OCRv5_mobile_rec`。

---

## 五、判定汇总

| AC | 阈值 | 实测 | 判定 |
|:-:|:--|:--|:-:|
| 1 | ≥ 97% | 99.64%（15 页；单页最低 98.98%） | PASS |
| 2 | 断网容器内可完成 | `--network none` 容器内 BLOCKED + 识别成功（24 行 / 0.9882） | PASS |
| 3 | P95 ≤ 6 s | 3.987 s（max 4.179 s；复跑 3.537 s） | PASS |
| 4 | 标记 + 降权 + 单测 | 14/14（全套 35 passed） | PASS |

**4/4 通过**，无遗留待确认项。
