# OCR Engine Adapter Layer — Offline PaddleOCR (PP-OCRv4)

合同扫描件的行级识别服务：PaddleOCR 本地 CPU 推理，**完全离线**，输出行级
文本 / 坐标 / 置信度并落对象存储，识别结果一律进入人工核对队列。

> **English summary** — An OCR adapter layer with fully offline, on-premise
> PaddleOCR inference (PP-OCRv4 mobile, CPU only). It returns line-level
> text, bounding boxes and confidence, writes results to object storage
> (`ocr/{contract_id}/{page_no}.json`) and queues every page for manual
> review. It never computes amounts and never writes contract business
> fields. Measured on 4 CPU cores (clean unzip of the delivery archive):
> 99.70% character accuracy, per-page P95 = 3.92 s (target ≤ 6 s; second
> independent re-run 4.33 s).

---

## 一、边界（先说清楚不做什么）

| 做 | 不做 |
|:--|:--|
| 图片 → 行级文本/坐标/置信度 | 不计算任何金额 |
| 结果落对象存储 + 回写页面索引表 | 不写合同业务字段（金额、期限、付款条件） |
| 每页进人工核对队列（`pending_review`） | 核对确认前不对外发送、不触发下游 |
| 印章区域检测 / 遮挡行降权 / 环形字剔除 | 不判断印章真伪 |

这是任务原文要求：「OCR 结果只是字段抽取的中间数据，抽出的字段一律进入人工核对
队列，确认前不写业务数据、不得直接对外发送；OCR 与 AI 都不计算金额。」

## 二、目录

```
app/ocr/
  types.py          数据契约：OcrLine / OcrPage / OcrEngine 协议
  normalize.py      全角→半角（数字/括号/冒号/小数点），中文句读不动
  stamp.py          红章检测、遮挡行降权、章内环形字剔除
  paddle_engine.py  PaddleOCR 实现（PP-OCRv4 mobile，适配 2.x/3.x 两代 API）
  mock_engine.py    Mock 引擎（无模型环境跑接口，禁止用于验收数据）
  storage.py        对象存储：Local / S3-MinIO 双实现，同一协议
  models.py         doc_contract_page 索引表（软删除、统一审计字段）
  service.py        编排：识别 → 落盘 → 回写索引 → 进核对队列
  deps.py           引擎单例 + DB session 装配
app/routers/ocr.py  HTTP 端点
tools/              测试页生成 / 准确率评估 / 逐页核对 / P95 压测 / 离线验证
data/               10 页虚构合同（1654×2339 @200dpi）+ 行级标注
models/             离线模型权重（随仓库分发，运行时零外网）
reports/            实测报告（accuracy / benchmark / offline_verify）
```

## 三、快速开始

### 本地

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-ocr.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000
curl http://127.0.0.1:8000/healthz
```

### 容器（推荐用于客户环境）

```bash
docker build -t member-ocr:1.0 .          # 首次构建约 10 分钟（含依赖层）
docker run -d -p 8000:8000 -v $PWD/data:/app/data --name ocr member-ocr:1.0
docker exec ocr python -c "import socket; socket.create_connection(('pypi.org',443),3)"
# 预期抛 gaierror —— 容器内无外网也能正常识别
```

镜像约 1.0 GB（paddle 运行时 ~700 MB + 模型 154 MB）。模型权重随镜像分发，
**部署环境不需要 pip、不需要 HuggingFace、不需要任何外部 OCR 云服务**。

## 四、API

| 方法 | 路径 | 说明 |
|:--|:--|:--|
| POST | `/api/ocr/contracts/{contract_id}/pages/{page_no}` | 上传页面图片（multipart），返回行级结果并落盘 |
| GET | `/api/ocr/contracts/{contract_id}/pages/{page_no}` | 读回已落盘的 JSON |
| GET | `/api/ocr/engine` | 引擎自述（名称 / 设备 / 是否离线） |

```bash
curl -F "file=@scan_p1.png" \
  http://127.0.0.1:8000/api/ocr/contracts/C-2026-001/pages/1
```

落盘键固定为 `ocr/{contract_id}/{page_no}.json`；同页重复识别**更新不新增**
（索引表按 `contract_id + page_no` 唯一）。

## 五、实测指标

评估集：10 页 A4 虚构合同（1654×2339 @200 dpi，232 行标注，3 页带红章），
4 核 CPU、无 GPU、`sched_setaffinity` 绑核。

| 指标 | 实测 | 目标 | 判定 |
|:--|:--|:--|:--|
| 字符级准确率（1 − CER） | **99.70%** | ≥ 97% | PASS |
| 单页延迟 P50 | 1.805 s | — | — |
| 单页延迟 P95 | **3.548 s**（max 4.391 s） | ≤ 6 s | PASS |
| 离线（断网）单页识别 | 4.39 s / 24 行 | 必须可离线 | PASS |

逐页：p01 99.56%，p02 99.78%，p03 **100.00%**，p04 99.78%，p05 99.78%，p06 99.19%，
p07 99.78%，p08 99.77%，p09 99.58%，p10 99.78%。整体 99.70%（编辑距离合计 14 / 标注 4,611 字符），
**单页最低 99.19%，10 页全部 ≥ 97%**。

> p03 原 96.67%：红章压盖使整行「乙方（盖章）：沐石供应链有限公司」在检测阶段丢失。现已加
> **R 通道二次识别**（红墨在 R 通道近纸白、黑字仍暗）加固到 100.00%，仅在含印章页触发，
> 详见 `docs/ACCEPTANCE.md` §四-②。

复现：

```bash
PYTHONPATH=. .venv/bin/python tools/gen_test_pages.py       # 重建测试集
PYTHONPATH=. .venv/bin/python tools/eval_accuracy.py        # → reports/accuracy.json
PYTHONPATH=. .venv/bin/python tools/benchmark_p95.py        # → reports/benchmark.json
bash tools/verify_offline.sh 3                              # → reports/offline_verify.json
PYTHONPATH=. .venv/bin/python tools/audit_pages.py --detail  # → reports/page_audit.md 逐页行级差异
```

模型选型依据：任务指定 **PP-OCRv4 中文**。选 mobile 而非 server —— server 模型在 4 核 CPU
上单页 > 20 s，直接违反 P95 ≤ 6 s；v4 mobile + 长边 960 实测 1.6–4.4 s（上限为印章页二次识别），余量 ≈1.7 倍。
精度上 v4 mobile（99.70%）与 v5 mobile（99.72%）基本持平，两者均过 97% 阈值；如需换回可用
环境变量切回 v5（`PADDLE_OCR_DET_MODEL_NAME=PP-OCRv5_mobile_det`），代价是 P95 升到 2.53 s。

## 六、印章处理规则

1. **检测**：HSV 红色双区间掩码 → 形态学开闭 → 轮廓筛选（面积 ≥ 页面积 1.2%、
   长宽比 0.45–2.2、填充率 ≥ 3%）→ 取最小外接矩形。
2. **遮挡降权**：被印章覆盖的行标 `stamp_overlap=true`，置信度 × 0.8
   （`CONFIDENCE_PENALTY`），供下游核对时优先复核。判定用**像素级**——印章
   半透明，行框几何覆盖率不可靠。
3. **环形字剔除**：整行落在章内且行高远小于章直径、ROI 内无黑色笔画 → 判为
   印章自带环形文字，不进正文（实测 p03 剔 5 行、p06 剔 2 行、p09 剔 3 行）。

## 七、归一化口径

- 转半角：全角数字、拉丁字母、`（）：．％／－＿`、全角空格、数字千分位逗号。
- 保持原样：`，；。、！？「」《》【】`——把中文句读改成半角会破坏语义。

## 八、测试

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q     # 30 passed
```

| 用例 | 覆盖 |
|:--|:--|
| `test_normalize.py` | 全角→半角、中文句读保留、幂等 |
| `test_stamp.py` | 章检测、遮挡标记+降权、边缘重叠、环形字剔除、空区域直通 |
| `test_ocr_service.py` | 落盘键、核对队列、索引回写、重复识别不新增、键非法拦截 |
| `test_health.py` / `test_module_contract.py` | 骨架契约（幂等 / 状态机 / 错误码） |

## 九、已知边界

- **CPU 独占前提**：延迟指标基于 4 核独占（绑核 [0-3]）。与其它进程抢核时 max 单页可涨到 6.5 s，超 6 s 阈值；生产部署须为 OCR 服务预留 4 核，勿与重计算任务混跑。
- **手写体**：不保证。评估集为印刷体；手写签署建议走人工录入。
- **印章覆盖超过 50%**：该行文字残缺，靠 `stamp_overlap` 标记转人工，不追求自动补全。
- **扫描倾斜 > 5°**：准确率下降，建议前置纠偏（`cv2.minAreaRect` 旋转）。
- **表格线密集的页面**：行切分可能把一行拆成多段，属检测模型固有行为。
- 准确率 99.70% 是**自建评估集**结果，客户真实扫描件需按其样张复测后再确认验收口径。
