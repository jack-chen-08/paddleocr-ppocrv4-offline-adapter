#!/usr/bin/env python3
"""从干净渲染页派生「模拟扫描件」页：倾斜 ±2°、高斯噪点、轻度模糊。

买家返工意见：原 10 页是干净数字渲染图，需补几张模拟真实扫描效果的页面，
一并计入准确率与耗时统计。

做法（固定随机种子，可复现）：
  scan_11  ← page_02  倾斜 +2.0°
  scan_12  ← page_04  倾斜 -2.0°
  scan_13  ← page_05  高斯噪点 σ=12
  scan_14  ← page_07  轻度模糊 radius=0.9
  scan_15  ← page_06  倾斜 +1.5° + 噪点 σ=8 + 模糊 0.6（带红章页，覆盖组合退化）

标注（ground truth）沿用源页文本：扫描退化不改变文字内容，只改变成像质量。
写入 data/pages/scan_*.png，并把对应条目合并进 data/labels.json（带 variant 字段）。

用法：python tools/gen_scan_pages.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "data" / "pages"
LABELS = ROOT / "data" / "labels.json"

# (输出名, 源页, 变换参数, page_no)
VARIANTS = [
    ("scan_11.png", "page_02.png", {"rotate_deg": 2.0}, 11),
    ("scan_12.png", "page_04.png", {"rotate_deg": -2.0}, 12),
    ("scan_13.png", "page_05.png", {"gaussian_sigma": 12.0}, 13),
    ("scan_14.png", "page_07.png", {"blur_radius": 0.9}, 14),
    ("scan_15.png", "page_06.png", {"rotate_deg": 1.5, "gaussian_sigma": 8.0, "blur_radius": 0.6}, 15),
]


def degrade(img: Image.Image, spec: dict, seed: int) -> Image.Image:
    out = img.convert("RGB")
    if "rotate_deg" in spec:
        # 白底填充、不扩画布：与扫描仪轻微走纸歪斜一致
        out = out.rotate(spec["rotate_deg"], resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    if "gaussian_sigma" in spec:
        arr = np.asarray(out).astype(np.float32)
        noise = np.random.default_rng(seed).normal(0.0, spec["gaussian_sigma"], arr.shape)
        out = Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))
    if "blur_radius" in spec:
        out = out.filter(ImageFilter.GaussianBlur(spec["blur_radius"]))
    return out


def main() -> None:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    # 幂等：先清掉上一次生成的 scan_* 条目
    for key in [k for k in labels if k.startswith("scan_")]:
        labels.pop(key)

    for name, src, spec, page_no in VARIANTS:
        src_path = PAGES / src
        if not src_path.exists():
            raise SystemExit(f"缺少源页 {src_path}，请先跑 python tools/gen_test_pages.py")
        img = Image.open(src_path)
        out = degrade(img, spec, seed=page_no)
        out.save(PAGES / name, dpi=(200, 200))

        meta = labels[src]
        labels[name] = {
            "page_no": page_no,
            "width": meta["width"],
            "height": meta["height"],
            "variant": "scanned",
            "source": src,
            "degradation": spec,
            "lines": list(meta["lines"]),
        }
        print(f"{name} ← {src}  {spec}  {len(meta['lines'])} 行")

    LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    clean = [k for k in labels if not k.startswith("scan_")]
    scan = [k for k in labels if k.startswith("scan_")]
    print(f"labels.json: 干净页 {len(clean)} + 扫描模拟页 {len(scan)} = {len(labels)} 页")


if __name__ == "__main__":
    main()
