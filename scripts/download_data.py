#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
import registry  # noqa: E402


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def make_progress():
    last = {"pct": -1}

    def progress(done, total):
        if not total:
            return
        pct = done * 100 // total
        if pct != last["pct"] and pct % 5 == 0:
            log(f"  %{pct:>3}  ({done / 1e6:,.0f} / {total / 1e6:,.0f} MB)")
            last["pct"] = pct
    return progress


def main():
    ap = argparse.ArgumentParser(description="Dataset ham dosyalarını indirir ve doğrular.")
    ap.add_argument("dataset", choices=registry.list_datasets())
    ap.add_argument("--dest", type=Path, help="hedef klasör (varsayılan: data/raw/<dataset>)")
    ap.add_argument("--force", action="store_true", help="dosyalar mevcut olsa bile yeniden indir")
    ap.add_argument("--keep-archive", action="store_true", help="indirilen arşivi silme")
    args = ap.parse_args()

    try:
        dest = ingest.download_registered(
            args.dataset, dest=args.dest, force=args.force, keep_archive=args.keep_archive,
            log=log, progress=make_progress(),
        )
    except ingest.IngestError as e:
        log(f"HATA: {e}")
        return 1

    files = registry.load_dataset(args.dataset)["files"]
    unverified = [n for n, m in files.items() if "sha256" not in m]
    if unverified:
        log(f"\nBu dosyalar için config'te sha256 yok. datasets/{args.dataset}.toml'a ekleyebilirsiniz:")
        for n in unverified:
            p = dest / n
            log(f'  [files."{n}"]  bytes = {p.stat().st_size}  sha256 = "{ingest.sha256_of(p)}"')

    total = sum((dest / n).stat().st_size for n in files)
    log(f"Tamam: {len(files)} dosya, {total / 1e6:,.0f} MB → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
