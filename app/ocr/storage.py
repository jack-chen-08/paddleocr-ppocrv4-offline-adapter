"""对象存储写入：ocr/{contract_id}/{page_no}.json

生产用 S3 兼容对象存储（客户自有云账号 / MinIO），测试用本地目录实现。
两条实现都满足同一个 ObjectStore 协议，业务代码不感知后端。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from app.ocr.types import OcrPage


def ocr_object_key(contract_id: str, page_no: int) -> str:
    """统一的存储键：ocr/{contract_id}/{page_no}.json"""
    if not contract_id or "/" in contract_id or ".." in contract_id:
        raise ValueError("contract_id 非法")
    if page_no < 1:
        raise ValueError("page_no 必须 >= 1")
    return f"ocr/{contract_id}/{page_no}.json"


class ObjectStore(Protocol):
    def put_json(self, key: str, payload: dict[str, Any]) -> str: ...
    def get_json(self, key: str) -> dict[str, Any]: ...


class LocalObjectStore:
    """本地目录实现（测试 / 单机离线部署）。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("key 越界")
        return p

    def put_json(self, key: str, payload: dict[str, Any]) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return key

    def get_json(self, key: str) -> dict[str, Any]:
        return json.loads(self._path(key).read_text(encoding="utf-8"))


class S3ObjectStore:
    """S3 / MinIO 兼容实现。boto3 延迟导入，未安装时只有显式使用才报错。"""

    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        import boto3  # 延迟导入

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def put_json(self, key: str, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json"
        )
        return key

    def get_json(self, key: str) -> dict[str, Any]:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))


def store_page(store: ObjectStore, contract_id: str, page: OcrPage) -> str:
    """把 OcrPage 落盘到 ocr/{contract_id}/{page_no}.json，返回存储键。"""
    key = ocr_object_key(contract_id, page.page_no)
    store.put_json(key, page.to_dict())
    return key
