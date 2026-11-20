#!/usr/bin/env python3
"""逐页核对：把识别结果与人工标注按「行」对齐，输出每页的差异明细。

与 eval_accuracy.py 的区别：那个只看整页字符串的编辑距离（一个数字）；
这个按行对齐，指到具体是第几行、哪个字符错、错成什么，供人工逐页核对使用。

用法：
  python tools/audit_pages.py                 # 全部 15 页
  python tools/audit_pages.py --pages 3       # 只看第 3 页（详细模式）
输出：
  reports/page_audit.md    人读的逐页核对表
  reports/page_audit.json  机器可读的逐行差异
"""
from __future__ import annotations

import argparse
import difflib
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


def inline_diff(gt: str, pred: str) -> str:
    """把两个串的差异写成可读形式：[-缺-]{+多+} 风格换成中文标注。"""
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, gt, pred).get_opcodes():
        if tag == "equal":
            seg = gt[i1:i2]
            out.append(seg if len(seg) <= 12 else seg[:6] + "…" + seg[-6:])
        elif tag == "delete":
            out.append(f"[漏『{gt[i1:i2]}』]")
        elif tag == "insert":
            out.append(f"[多『{pred[j1:j2]}』]")
        else:
            out.append(f"[错『{gt[i1:i2]}』→『{pred[j1:j2]}』]")
    return "".join(out)


def align(gt_lines: list[str], pred_lines: list[str]):
    """按相似度做行级对齐，返回 [(gt_idx|None, pred_idx|None)]。"""
    g = [squash(x) for x in gt_lines]
    p = [squash(x) for x in pred_lines]
    sm = difflib.SequenceMatcher(None, g, p, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((i1 + k, j1 + k))
        elif tag == "replace":
            # 段内按顺序配对，多出的记 None
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                gi = i1 + k if i1 + k < i2 else None
                pj = j1 + k if j1 + k < j2 else None
                pairs.append((gi, pj))
        elif tag == "delete":
            for k in range(i1, i2):
                pairs.append((k, None))
        else:  # insert
            for k in range(j1, j2):
                pairs.append((None, k))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="*", type=int, default=None)
    ap.add_argument("--detail", action="store_true", help="打印逐行明细到控制台")
    ap.add_argument("--out-md", default=str(ROOT / "reports" / "page_audit.md"))
    ap.add_argument("--out-json", default=str(ROOT / "reports" / "page_audit.json"))
    args = ap.parse_args()

    labels = json.loads((ROOT / "data" / "labels.json").read_text(encoding="utf-8"))
    engine = PaddleOcrEngine(lang="ch")

    pages_out: list[dict] = []
    tot_dist = tot_len = 0
    tot_ms = 0.0

    for name, meta in sorted(labels.items()):
        if args.pages and meta["page_no"] not in args.pages:
            continue
        t0 = time.perf_counter()
        page = engine.recognize(ROOT / "data" / "pages" / name, page_no=meta["page_no"])
        ms = (time.perf_counter() - t0) * 1000.0
        tot_ms += ms

        gt_lines: list[str] = meta["lines"]
        pred_lines = [line.text for line in page.lines]
        gt = squash("".join(gt_lines))
        pred = squash("".join(pred_lines))
        dist = edit_distance(gt, pred)
        tot_dist += dist
        tot_len += len(gt)
        acc = (1 - dist / len(gt)) * 100 if gt else 100.0

        rows = []
        for gi, pj in align(gt_lines, pred_lines):
            gt_raw = gt_lines[gi] if gi is not None else None
            pred_raw = pred_lines[pj] if pj is not None else None
            gt_s = squash(gt_raw) if gt_raw is not None else ""
            pred_s = squash(pred_raw) if pred_raw is not None else ""
            d = edit_distance(gt_s, pred_s)
            line = page.lines[pj] if pj is not None else None
            rows.append(
                {
                    "gt_no": gi + 1 if gi is not None else None,
                    "gt": gt_raw,
                    "pred": pred_raw,
                    "dist": d,
                    "ok": d == 0,
                    "diff": inline_diff(gt_s, pred_s) if d else "",
                    "stamp_overlap": bool(line.stamp_overlap) if line else False,
                    "confidence": round(line.confidence, 4) if line else None,
                }
            )

        pages_out.append(
            {
                "page_no": meta["page_no"],
                "file": name,
                "variant": "scanned" if meta.get("variant") == "scanned" else "clean",
                "width": meta["width"],
                "height": meta["height"],
                "gt_lines": len(gt_lines),
                "pred_lines": len(pred_lines),
                "gt_chars": len(gt),
                "dist": dist,
                "accuracy_pct": round(acc, 2),
                "elapsed_ms": round(ms, 1),
                "stamp_regions": len(page.stamp_regions),
                "rows": rows,
            }
        )
        print(f"page_{meta['page_no']:02d}  acc={acc:6.2f}%  dist={dist:3d}/{len(gt):4d}  "
              f"lines gt/pred={len(gt_lines)}/{len(pred_lines)}  {ms:7.1f} ms")

    overall = (1 - tot_dist / tot_len) * 100 if tot_len else 100.0
    print(f"OVERALL  acc={overall:6.2f}%  dist={tot_dist}/{tot_len}  total={tot_ms/1000:.2f} s")

    if args.detail:
        for pg in pages_out:
            print(f"\n===== page_{pg['page_no']:02d} ({pg['accuracy_pct']}%) =====")
            for r in pg["rows"]:
                if not r["ok"]:
                    print(f"  行{r['gt_no']}\n    标注: {r['gt']}\n    识别: {r['pred']}\n    差异: {r['diff']}")

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    n_scanned = sum(1 for pg in pages_out if pg["variant"] == "scanned")
    n_clean = len(pages_out) - n_scanned
    md = ["# 逐页核对报告", "",
          f"整体字符准确率 **{overall:.2f}%**（编辑距离 {tot_dist} / {tot_len} 字符），"
          f"{n_clean} 张干净页 + {n_scanned} 张扫描模拟页共 {len(pages_out)} 页，总耗时 {tot_ms/1000:.2f} s。", "",
          "## 总览", "",
          "| 页 | 标注行 | 识别行 | 标注字符 | 编辑距离 | 准确率 | 耗时(ms) | 印章区 |",
          "|:--|--:|--:|--:|--:|--:|--:|--:|"]
    for pg in pages_out:
        md.append(
            f"| page_{pg['page_no']:02d} | {pg['gt_lines']} | {pg['pred_lines']} | {pg['gt_chars']} | "
            f"{pg['dist']} | {pg['accuracy_pct']}% | {pg['elapsed_ms']} | {pg['stamp_regions']} |"
        )
    md += ["", "## 逐页明细", ""]
    for pg in pages_out:
        md += [f"### page_{pg['page_no']:02d} — {pg['accuracy_pct']}%", ""]
        bad = [r for r in pg["rows"] if not r["ok"]]
        if not bad:
            md += ["全部行一致。", ""]
            continue
        md += ["| 标注行号 | 人工标注 | 识别结果 | 差异 | 印章遮挡 |", "|:--:|:--|:--|:--|:--:|"]
        for r in bad:
            md.append(
                f"| {r['gt_no']} | {r['gt'] or '—（该行漏识别）'} | {r['pred'] or '—（多出该行）'} | "
                f"{r['diff']} | {'是' if r['stamp_overlap'] else ''} |"
            )
        md.append("")
    out_md.write_text("\n".join(md), encoding="utf-8")
    Path(args.out_json).write_text(
        json.dumps({"overall_accuracy_pct": round(overall, 2), "total_dist": tot_dist,
                    "total_chars": tot_len, "pages": pages_out}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写出 {out_md}\n写出 {args.out_json}")


if __name__ == "__main__":
    main()
