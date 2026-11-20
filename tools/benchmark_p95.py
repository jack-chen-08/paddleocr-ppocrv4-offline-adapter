#!/usr/bin/env python3
"""单页延迟压测：统计 P50 / P95 / max，判定 P95 ≤ 6s。

约束：4 核 CPU 推理（脚本内用 sched_setaffinity 绑定 0-3），关掉超线程外的并行假设。
用法：python tools/benchmark_p95.py [--rounds 2] [--cores 4]
输出：reports/benchmark.json + 控制台摘要
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ocr.paddle_engine import PaddleOcrEngine  # noqa: E402


def _pin_cores(cores: int) -> str:
    try:
        os.sched_setaffinity(0, set(range(cores)))
        return f"affinity={sorted(os.sched_getaffinity(0))}"
    except AttributeError:
        return "affinity=unsupported"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "reports" / "benchmark.json"))
    args = ap.parse_args()

    pinned = _pin_cores(args.cores)
    pages = sorted((ROOT / "data" / "pages").glob("*.png"))
    labels_path = ROOT / "data" / "labels.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
    engine = PaddleOcrEngine(lang="ch")

    times: list[float] = []
    per_page: list[dict] = []
    group_times: dict[str, list[float]] = {"clean": [], "scanned": []}
    for r in range(args.rounds):
        for p in pages:
            t0 = time.perf_counter()
            page = engine.recognize(p, page_no=int(p.stem.split("_")[1]))
            dt = time.perf_counter() - t0
            variant = "scanned" if labels.get(p.name, {}).get("variant") == "scanned" else "clean"
            times.append(dt)
            group_times[variant].append(dt)
            per_page.append(
                {
                    "round": r + 1,
                    "page": p.name,
                    "variant": variant,
                    "elapsed_s": round(dt, 3),
                    "lines": len(page.lines),
                }
            )
            print(f"round{r+1} {p.name} {dt:.2f}s lines={len(page.lines)} variant={variant}")

    times_sorted = sorted(times)
    p50 = statistics.median(times_sorted)
    p95 = times_sorted[max(0, int(round(0.95 * len(times_sorted))) - 1)]
    groups = {}
    for g, ts in group_times.items():
        if not ts:
            continue
        ss = sorted(ts)
        groups[g] = {
            "samples": len(ts),
            "p50_s": round(statistics.median(ss), 3),
            "p95_s": round(ss[max(0, int(round(0.95 * len(ss))) - 1)], 3),
            "max_s": round(max(ss), 3),
        }
    result = {
        "cores": args.cores,
        "affinity": pinned,
        "cpu": platform.processor() or platform.machine(),
        "model": getattr(engine, "name", "paddleocr"),
        "pages": len(pages),
        "rounds": args.rounds,
        "samples": len(times),
        "p50_s": round(p50, 3),
        "p95_s": round(p95, 3),
        "max_s": round(max(times), 3),
        "min_s": round(min(times), 3),
        "threshold_p95_s": 6.0,
        "verdict": "PASS" if p95 <= 6.0 else "FAIL",
        "groups": groups,
        "detail": per_page,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-" * 60)
    print(f"samples={len(times)}  P50={p50:.3f}s  P95={p95:.3f}s  max={max(times):.3f}s  {pinned}")
    for g, v in groups.items():
        print(f"  {g:8s} samples={v['samples']:3d} P50={v['p50_s']:.3f}s P95={v['p95_s']:.3f}s max={v['max_s']:.3f}s")
    print(f"判定：{result['verdict']}（阈值 P95 ≤ 6.000s）")


if __name__ == "__main__":
    main()
