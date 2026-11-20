#!/usr/bin/env python3
"""字符级准确率评估：对全部虚构合同页（10 原件 + 5 扫描件）逐页识别，与标注文本比较。

指标：
  字符准确率 = 1 - CER，CER = 编辑距离(标注拼接串, 识别拼接串) / len(标注拼接串)
比较前双方都做一次全角半角归一，并把所有空白去掉（版面差异不计入）。

用法：
  python tools/eval_accuracy.py                 # 全量 15 页
  python tools/eval_accuracy.py --pages 1 2 3   # 指定页
输出：控制台表格 + reports/accuracy.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ocr.normalize import normalize_text  # noqa: E402
from app.ocr.paddle_engine import PaddleOcrEngine  # noqa: E402

WS = re.compile(r"\s+")


def squash(text: str) -> str:
    return WS.sub("", normalize_text(text))


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="*", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "reports" / "accuracy.json"))
    args = ap.parse_args()

    labels = json.loads((ROOT / "data" / "labels.json").read_text(encoding="utf-8"))
    engine = PaddleOcrEngine(lang="ch")
    rows = []
    total_dist = total_len = 0
    group_acc: dict[str, dict[str, int]] = {"clean": {"dist": 0, "len": 0}, "scanned": {"dist": 0, "len": 0}}

    items = sorted(labels.items())
    for name, meta in items:
        if args.pages and meta["page_no"] not in args.pages:
            continue
        t0 = time.perf_counter()
        page = engine.recognize(ROOT / "data" / "pages" / name, page_no=meta["page_no"])
        elapsed = time.perf_counter() - t0
        gt = squash("".join(meta["lines"]))
        pred = squash("".join(line.text for line in page.lines))
        dist = edit_distance(gt, pred)
        total_dist += dist
        total_len += len(gt)
        group = "scanned" if meta.get("variant") == "scanned" else "clean"
        group_acc[group]["dist"] += dist
        group_acc[group]["len"] += len(gt)
        acc = 1.0 - dist / max(len(gt), 1)
        rows.append(
            {
                "page": name,
                "page_no": meta["page_no"],
                "variant": group,
                "chars_gt": len(gt),
                "chars_pred": len(pred),
                "edit_distance": dist,
                "char_accuracy": round(acc, 4),
                "lines": len(page.lines),
                "stamp_overlap_lines": len(page.stamp_overlap_lines),
                "elapsed_s": round(elapsed, 2),
            }
        )
        print(
            f"{name}  字符={len(gt):4d}  编辑距离={dist:3d}  准确率={acc*100:6.2f}%  "
            f"行={len(page.lines):3d}  印章行={len(page.stamp_overlap_lines):2d}  {elapsed:5.2f}s"
        )

    overall = 1.0 - total_dist / max(total_len, 1)
    groups = {
        g: {
            "pages": sum(1 for r in rows if r["variant"] == g),
            "chars_gt": v["len"],
            "edit_distance": v["dist"],
            "char_accuracy": round(1.0 - v["dist"] / max(v["len"], 1), 4),
        }
        for g, v in group_acc.items()
    }
    print("-" * 78)
    for g, v in groups.items():
        print(f"{g:8s} {v['pages']:2d} 页  编辑距离 {v['edit_distance']:3d} / {v['chars_gt']:5d} 字符  准确率 {v['char_accuracy']*100:6.2f}%")
    print(f"整体字符级准确率 = {overall*100:.2f}%  （阈值 97.00%）  判定：{'PASS' if overall >= 0.97 else 'FAIL'}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "overall_char_accuracy": round(overall, 4),
                "threshold": 0.97,
                "groups": groups,
                "pages": rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
