# 离线可运行的 OCR 服务镜像（CPU 版）
# 构建： docker build -t member-ocr:1.0 .
# 运行： docker run -p 8000:8000 -v $PWD/data:/app/data member-ocr:1.0
# 说明： 模型文件随镜像分发（models/ 目录），容器运行时**不需要外网**。
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_CACHE_HOME=/app/models \
    HF_HUB_OFFLINE=1

# PaddleOCR / OpenCV 运行时依赖（精简，不含 X11 桌面组件）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 libsm6 libxext6 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) 依赖层（变动少，单独成层）
COPY requirements.txt requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-ocr.txt

# 2) 模型层（离线资产，随镜像走）
COPY models/ /app/models/

# 3) 代码层
COPY app/ /app/app/
COPY tools/ /app/tools/

RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
