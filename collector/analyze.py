#!/usr/bin/env python3
"""Turn the collected CSVs into ratio tables and a claim verdict table.

Standard library only. GitHub-hosted runners are the baseline for every ratio.
A ratio above 1.0 means the vendor is faster or cheaper than GitHub.

Usage:
  python3 collector/analyze.py
  python3 collector/analyze.py --raw results/raw --out results/tables
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import statistics as st
import sys
from collections import defaultdict

BASELINE = "github"
VENDORS = ["blacksmith", "namespace", "warpbuild"]
BOOTSTRAP = 10_000
PAYLOAD_MB = 512

# USD per minute, 4 vCPU Linux x64. Fetched 2026-09-04. Re-check before
# publishing. GitHub is priced as a private repo on a larger runner, which is
# the buyer's situation. The public-repo view prices GitHub at zero.
PRICE_PER_MIN = {
    "github": 0.012,
    "blacksmith": 0.008,
    "namespace": 0.006,
    "warpbuild": 0.008,
}

# claim id -> (vendor, human claim, metric key, comparison, threshold)
# comparison: "ratio_ge" needs ratio >= threshold
#             "abs_le"   needs the absolute value <= threshold
#             "abs_ge"   needs the absolute value >= threshold
#             "report"   no threshold, record the number
CLAIMS = [
    ("B1", "blacksmith", "2x faster than GitHub's runners",
     "speedup:w1:warm", "ratio_ge", 1.8),
    ("B1b", "blacksmith", "2x faster, Rust build",
     "speedup:w2:warm", "ratio_ge", 1.8),
    ("B2", "blacksmith", "4x faster cache downloads, 400MB/s",
     "cache_restore_mbps", "abs_ge", 350.0),
    ("B2r", "blacksmith", "4x faster cache downloads, ratio form",
     "speedup:cache_restore", "ratio_ge", 3.5),
    ("B3", "blacksmith", "2x to 40x faster Docker builds",
     "speedup:w4:warm", "ratio_ge", 2.0),
    ("B4", "blacksmith", "Runners boot in under 3 seconds",
     "queue_p50", "abs_le", 3.0),
    ("B5", "blacksmith", "67% total cost savings",
     "cost_ratio:w1:warm", "ratio_ge", 3.0),
    ("N1", "namespace", "Cache volumes give instant access",
     "cache_restore_s", "abs_le", 5.0),
    ("N2", "namespace", "Image pulls in seconds rather than minutes",
     "image_pull_s", "abs_le", 15.0),
    ("N3", "namespace", "Monorepo speed",
     "speedup:w1:warm", "report", None),
    ("W1c", "warpbuild", "2-10x faster builds, monorepo",
     "speedup:w1:warm", "ratio_ge", 2.0),
    ("W1d", "warpbuild", "2-10x faster builds, Rust",
     "speedup:w2:warm", "ratio_ge", 2.0),
    ("W2c", "warpbuild", "50% cheaper than GitHub Actions",
     "cost_ratio:w1:warm", "ratio_ge", 2.0),
    ("W3c", "warpbuild", "Cold start under 10 seconds",
     "queue_p50", "abs_le", 10.0),
]

# Claims recorded for every vendor with no pass threshold.
REPORT_ONLY = [
    ("X1", "Lightweight jobs may gain little or become slower",
     "speedup:w5:cold"),
    ("X2", "Datawrapper reported 22% faster and 45% cheaper",
     "speedup_mean"),
]


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        print(f"missing {path}", file=sys.stderr)
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def as_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "None") else None
    except ValueError:
        return None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(int(round(q * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def bootstrap_ratio_ci(base: list[float], vendor: list[float],
                       rounds: int = BOOTSTRAP) -> tuple[float, float] | None:
    """95% CI for median(base) / median(vendor)."""
    if len(base) < 3 or len(vendor) < 3:
        return None

    rng = random.Random(20260904)
    ratios = []
    for _ in range(rounds):
        b = st.median(rng.choices(base, k=len(base)))
        v = st.median(rng.choices(vendor, k=len(vendor)))
        if v > 0:
            ratios.append(b / v)

    if not ratios:
        return None
    return percentile(ratios, 0.025), percentile(ratios, 0.975)


def gather(jobs: list[dict], steps: list[dict]) -> dict:
    """Build the metric store: metric key -> vendor -> list of samples."""
    store: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))

    for row in jobs:
        vendor, workload = row["vendor"], row["workload"]
        arm, cache_arm = row["arm"], row["cache_arm"]

        # Correctness gate. A faster runner that fails is not faster.
        if row["conclusion"] != "success":
            store["dropped"][vendor].append(1.0)
            continue

        duration = as_float(row["job_duration_s"])
        queue = as_float(row["queue_time_s"])

        if arm == "burst" and queue is not None:
            store["queue"][vendor].append(queue)
            continue

        if duration is None:
            continue

        if arm == "a" and workload in ("w1", "w2", "w4", "w5"):
            store[f"dur:{workload}:{cache_arm}"][vendor].append(duration)
            billable = -(-duration // 60)
            store[f"cost:{workload}:{cache_arm}"][vendor].append(
                billable * PRICE_PER_MIN.get(vendor, 0.0))

        if arm == "b" and workload in ("w1", "w2"):
            store[f"durB:{workload}:{cache_arm}"][vendor].append(duration)

    for row in steps:
        name = (row["step_name"] or "").strip()
        vendor = row["vendor"]
        seconds = as_float(row["step_duration_s"])
        if seconds is None or row["step_conclusion"] != "success":
            continue

        if name == "Restore cache payload":
            store["cache_restore_s"][vendor].append(seconds)
            if seconds > 0:
                store["cache_restore_mbps"][vendor].append(PAYLOAD_MB / seconds)
        elif name in ("Save cache payload",
                      "Post Seed the cache-throughput payload"):
            store["cache_save_s"][vendor].append(seconds)
            if seconds > 0:
                store["cache_save_mbps"][vendor].append(PAYLOAD_MB / seconds)
        elif name == "Pull large image":
            store["image_pull_s"][vendor].append(seconds)

    return store


def median_of(store: dict, key: str, vendor: str) -> float | None:
    values = store.get(key, {}).get(vendor, [])
    return st.median(values) if values else None


def resolve(store: dict, metric: str, vendor: str) -> tuple:
    """Return (value, n, ci) for a metric key such as 'speedup:w1:warm'."""
    if metric.startswith("speedup:"):
        target = metric.split("speedup:", 1)[1]
        key = "cache_restore_s" if target == "cache_restore" else f"dur:{target}"
        base = store.get(key, {}).get(BASELINE, [])
        vend = store.get(key, {}).get(vendor, [])
        if not base or not vend:
            return None, 0, None
        return (st.median(base) / st.median(vend),
                len(vend),
                bootstrap_ratio_ci(base, vend))

    if metric.startswith("cost_ratio:"):
        target = metric.split("cost_ratio:", 1)[1]
        key = f"cost:{target}"
        base = store.get(key, {}).get(BASELINE, [])
        vend = store.get(key, {}).get(vendor, [])
        if not base or not vend:
            return None, 0, None
        vm = st.median(vend)
        return (st.median(base) / vm if vm > 0 else None,
                len(vend),
                bootstrap_ratio_ci(base, vend))

    if metric == "queue_p50":
        values = store.get("queue", {}).get(vendor, [])
        return percentile(values, 0.5), len(values), None

    if metric == "speedup_mean":
        ratios = []
        for wl, arm in (("w1", "warm"), ("w2", "warm"),
                        ("w4", "warm"), ("w5", "cold")):
            b = median_of(store, f"dur:{wl}:{arm}", BASELINE)
            v = median_of(store, f"dur:{wl}:{arm}", vendor)
            if b and v:
                ratios.append(b / v)
        return (st.mean(ratios) if ratios else None, len(ratios), None)

    values = store.get(metric, {}).get(vendor, [])
    return (st.median(values) if values else None, len(values), None)


def verdict(comparison: str | None, value: float | None,
            threshold: float | None, ci: tuple | None) -> str:
    if value is None:
        return "No data"
    if comparison in (None, "report"):
        return "Reported"

    if comparison == "ratio_ge":
        if value < threshold:
            return "Not supported"
        return "Supported" if ci and ci[0] >= 1.0 else "Supported, wide CI"
    if comparison == "abs_le":
        return "Supported" if value <= threshold else "Not supported"
    if comparison == "abs_ge":
        return "Supported" if value >= threshold else "Not supported"
    return "Unknown check"


def fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def write_verdicts(store: dict, out_dir: str) -> None:
    lines = [
        "# Claim verdicts",
        "",
        "GitHub-hosted `ubuntu-24.04` is the baseline. A ratio above 1.0 means",
        "the vendor beats GitHub. CI is a 95% bootstrap interval on the ratio.",
        "",
        "| ID | Vendor | Claim | Metric | Measured | Threshold | 95% CI | n | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for cid, vendor, claim, metric, comparison, threshold in CLAIMS:
        value, n, ci = resolve(store, metric, vendor)
        ci_text = f"{fmt(ci[0])} to {fmt(ci[1])}" if ci else "n/a"
        lines.append(
            f"| {cid} | {vendor} | {claim} | `{metric}` | {fmt(value)} | "
            f"{fmt(threshold) if threshold else 'report'} | {ci_text} | {n} | "
            f"{verdict(comparison, value, threshold, ci)} |"
        )

    lines += ["", "## Report-only observations", "",
              "| ID | Observation | Metric | " +
              " | ".join(VENDORS) + " |",
              "| --- | --- | --- | " + " | ".join("---" for _ in VENDORS) + " |"]

    for cid, text, metric in REPORT_ONLY:
        cells = [fmt(resolve(store, metric, v)[0]) for v in VENDORS]
        lines.append(f"| {cid} | {text} | `{metric}` | " + " | ".join(cells) + " |")

    lines += ["", "## Reliability", "",
              "| Vendor | Failed or cancelled jobs |",
              "| --- | --- |"]
    for vendor in [BASELINE] + VENDORS:
        lines.append(f"| {vendor} | {len(store.get('dropped', {}).get(vendor, []))} |")

    path = os.path.join(out_dir, "verdicts.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def write_durations(store: dict, out_dir: str) -> None:
    lines = ["# Job duration by runner", "",
             "Median seconds, with the sample count in brackets.", "",
             "| Workload | Cache | " + " | ".join([BASELINE] + VENDORS) +
             " | best ratio |",
             "| --- | --- | " + " | ".join("---" for _ in range(len(VENDORS) + 2))
             + " |"]

    for workload in ("w1", "w2", "w4", "w5"):
        for arm in ("cold", "warm"):
            key = f"dur:{workload}:{arm}"
            if not store.get(key):
                continue

            cells, ratios = [], []
            base = median_of(store, key, BASELINE)
            for vendor in [BASELINE] + VENDORS:
                values = store[key].get(vendor, [])
                med = st.median(values) if values else None
                cells.append(f"{fmt(med, 1)} ({len(values)})")
                if vendor != BASELINE and base and med:
                    ratios.append(base / med)

            best = f"{max(ratios):.2f}x" if ratios else "n/a"
            lines.append(f"| {workload} | {arm} | " + " | ".join(cells) +
                         f" | {best} |")

    lines += ["", "# Cache and boot metrics", "",
              "| Metric | " + " | ".join([BASELINE] + VENDORS) + " |",
              "| --- | " + " | ".join("---" for _ in range(len(VENDORS) + 1)) + " |"]

    for metric, digits in (("cache_restore_s", 1), ("cache_restore_mbps", 0),
                           ("cache_save_s", 1), ("cache_save_mbps", 0),
                           ("image_pull_s", 1)):
        cells = [fmt(median_of(store, metric, v), digits)
                 for v in [BASELINE] + VENDORS]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")

    queue_cells_50, queue_cells_95 = [], []
    for vendor in [BASELINE] + VENDORS:
        values = store.get("queue", {}).get(vendor, [])
        queue_cells_50.append(fmt(percentile(values, 0.5), 1))
        queue_cells_95.append(fmt(percentile(values, 0.95), 1))
    lines.append("| queue_p50_s | " + " | ".join(queue_cells_50) + " |")
    lines.append("| queue_p95_s | " + " | ".join(queue_cells_95) + " |")

    lines += ["", "# Arm A versus arm B", "",
              "Vendor cache action against actions/cache on the same runner.",
              "A ratio above 1.0 means the vendor action is faster.", "",
              "| Vendor | Workload | arm A warm | arm B warm | ratio |",
              "| --- | --- | --- | --- | --- |"]

    for vendor in VENDORS:
        for workload in ("w1", "w2"):
            a = median_of(store, f"dur:{workload}:warm", vendor)
            b = median_of(store, f"durB:{workload}:warm", vendor)
            ratio = f"{a / b:.2f}" if a and b else "n/a"
            lines.append(f"| {vendor} | {workload} | {fmt(a, 1)} | "
                         f"{fmt(b, 1)} | {ratio} |")

    path = os.path.join(out_dir, "durations.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="results/raw")
    ap.add_argument("--out", default="results/tables")
    args = ap.parse_args()

    jobs = read_csv(os.path.join(args.raw, "jobs.csv"))
    steps = read_csv(os.path.join(args.raw, "steps.csv"))
    if not jobs:
        print("no job rows, run pull_jobs.py first", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    store = gather(jobs, steps)

    write_verdicts(store, args.out)
    write_durations(store, args.out)
    print(f"analysed {len(jobs)} jobs and {len(steps)} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
