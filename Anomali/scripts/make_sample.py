#!/usr/bin/env python3
"""Tam CIC-IDS2017 verisinden küçük, tabakalı (stratified) bir örnek üretir.

Her dosyada her etiketten oransal olarak --frac kadar satır alınır; nadir sınıflar
kaybolmasın diye her etiketten en az --min-per-class satır (ya da hepsi) tutulur.
Çıktı, orijinal dosya adları ve biçimiyle data/sample/cicids2017/ altına yazılır,
böylece dashboard örnek veriyle de aynı şekilde çalışır.

Kullanım:
    python scripts/make_sample.py
    python scripts/make_sample.py --frac 0.01 --min-per-class 100
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from download_data import DEFAULT_DEST, EXPECTED  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "sample" / "cicids2017"


def sample_file(path, frac, min_per_class, seed):
    df = pd.read_csv(path, low_memory=False)
    label_col = next(c for c in df.columns if c.strip() == "Label")
    parts = []
    for _, group in df.groupby(label_col, sort=False):
        n = max(round(len(group) * frac), min(len(group), min_per_class))
        parts.append(group.sample(n=n, random_state=seed))
    return pd.concat(parts).sort_index(), label_col


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--frac", type=float, default=0.005)
    ap.add_argument("--min-per-class", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in EXPECTED:
        src = args.src / name
        if not src.exists():
            raise SystemExit(f"Bulunamadı: {src}  (önce: python scripts/download_data.py)")
        sample, label_col = sample_file(src, args.frac, args.min_per_class, args.seed)
        sample.to_csv(args.out / name, index=False)
        total += len(sample)
        counts = ", ".join(f"{k}={v}" for k, v in sample[label_col].value_counts().items())
        print(f"{name}: {len(sample):,} satır  [{counts}]")
    size_mb = sum(p.stat().st_size for p in args.out.glob("*.csv")) / 1e6
    print(f"Toplam {total:,} satır, {size_mb:.1f} MB → {args.out}")


if __name__ == "__main__":
    main()
