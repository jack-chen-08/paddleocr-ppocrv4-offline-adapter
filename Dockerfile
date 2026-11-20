# 离线可运行的 OCR 服务镜像（CPU 版）
# 构建： docker build -t member-ocr:1.0 .
# 运行： docker run --rm -p 8000:8000 -v $PWD/data:/app/data member-ocr:1.0
#
# 离线保证（三道）：
#   1. 构建期把 dist/paddleocr_offline_models.tar.gz 解包进镜像 /app/models，
#      并校验 sha256 —— 不依赖仓库里的 models/ 目录（该目录被 .gitignore 忽略，
#      干净克隆下只有 6 个空 .lock，COPY 进去等于没有权重）。
#   2. 用 PADDLE_OCR_DET_MODEL_DIR / PADDLE_OCR_REC_MODEL_DIR 显式指向镜像内目录，
#      运行时 PaddleOCR 不会去默认缓存里找模型、更不会联网下载。
#   3. 应用侧 fail-closed：目录不存在或缺 inference.pdiparams 直接抛
#      ModelWeightsMissing（见 app/ocr/paddle_engine.py），不会静默回落到下载。
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

# PaddleOCR / OpenCV 运行时依赖（精简，不含 X11 桌面组件）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 libsm6 libxext6 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) 依赖层（变动少，单独成层）
# 构建期联网只发生在这里（拉 PyPI 轮子）。运行期完全不联网。
# 默认走清华镜像；海外环境可 --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt requirements-ocr.txt ./
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt \
    && pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements-ocr.txt \
    && pip config set global.index-url "$PIP_INDEX_URL"

# 2) 模型层：构建期解包离线权重包（唯一权重来源，14.4 MiB 的 tar.gz）
COPY dist/paddleocr_offline_models.tar.gz \
     dist/paddleocr_offline_models.tar.gz.sha256 \
     dist/paddleocr_offline_models.MANIFEST.json \
     /tmp/models_pkg/
RUN cd /tmp/models_pkg \
    && sha256sum -c paddleocr_offline_models.tar.gz.sha256 \
    && mkdir -p /app/models \
    && tar -xzf paddleocr_offline_models.tar.gz -C /app/models \
    && test -s /app/models/official_models/PP-OCRv4_mobile_det/inference.pdiparams \
    && test -s /app/models/official_models/PP-OCRv4_mobile_det/inference.json \
    && test -s /app/models/official_models/PP-OCRv4_mobile_rec/inference.pdiparams \
    && test -s /app/models/official_models/PP-OCRv4_mobile_rec/inference.json \
    && rm -rf /tmp/models_pkg \
    && du -sh /app/models

# 3) 权重定位：显式环境变量（Dockerfile 与 README 使用同一组变量名）
ENV PADDLE_OCR_DET_MODEL_DIR=/app/models/official_models/PP-OCRv4_mobile_det \
    PADDLE_OCR_REC_MODEL_DIR=/app/models/official_models/PP-OCRv4_mobile_rec \
    PADDLE_PDX_CACHE_HOME=/app/models

# 4) 代码层
COPY app/ /app/app/
COPY tools/ /app/tools/

# 5) 构建期自检：用应用自身的 fail-closed 解析逻辑验证权重就位（不通过则构建失败）
RUN python -c "from app.ocr.paddle_engine import resolve_model_dir as r; \
d=r('PADDLE_OCR_DET_MODEL_DIR','PP-OCRv4_mobile_det'); \
c=r('PADDLE_OCR_REC_MODEL_DIR','PP-OCRv4_mobile_rec'); \
print('weights ok:', d, c)"

RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
