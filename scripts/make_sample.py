#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import registry  # noqa: E402


def sample_file(path, label_col, frac, min_per_class, seed):
    df = pd.read_csv(path, low_memory=False)
    col = next(c for c in df.columns if c.strip() == label_col)
    parts = []
    for _, group in df.groupby(col, sort=False):
        n = max(round(len(group) * frac), min(len(group), min_per_class))
        parts.append(group.sample(n=n, random_state=seed))
    return pd.concat(parts).sort_index(), col


def main():
    ap = argparse.ArgumentParser(description="Tam veriden tabakalı örnek üretir.")
    ap.add_argument("dataset", choices=registry.list_datasets())
    ap.add_argument("--src", type=Path, help="varsayılan: data/raw/<dataset>")
    ap.add_argument("--out", type=Path, help="varsayılan: data/sample/<dataset>")
    ap.add_argument("--frac", type=float, default=0.005)
    ap.add_argument("--min-per-class", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg = registry.load_dataset(args.dataset)
    src_dir = args.src or registry.raw_dir(args.dataset)
    out_dir = args.out or registry.sample_dir(args.dataset)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for name in cfg["files"]:
        src = src_dir / name
        if not src.exists():
            raise SystemExit(f"Bulunamadı: {src}  (önce: python scripts/download_data.py {args.dataset})")
        sample, col = sample_file(src, cfg["label_column"], args.frac, args.min_per_class, args.seed)
        sample.to_csv(out_dir / name, index=False)
        total += len(sample)
        counts = ", ".join(f"{k}={v}" for k, v in sample[col].value_counts().items())
        print(f"{name}: {len(sample):,} satır  [{counts}]")
    size_mb = sum((out_dir / n).stat().st_size for n in cfg["files"]) / 1e6
    print(f"Toplam {total:,} satır, {size_mb:.1f} MB → {out_dir}")


if __name__ == "__main__":
    main()
