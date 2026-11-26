#!/usr/bin/env python3
"""Bir datasetin ham dosyalarını datasets/<ad>.toml'daki kaynaktan indirir ve doğrular.

Kullanım:
    python scripts/download_data.py cicids2017            # data/raw/cicids2017/ altına
    python scripts/download_data.py cicids2017 --dest DIR # başka bir klasöre
    python scripts/download_data.py cicids2017 --force    # dosyalar varsa bile yeniden indir

Desteklenen kaynaklar ([source] type):
    kaggle  ref = "sahip/dataset"   herkese açık Kaggle dataseti (hesap gerekmez; reddedilirse
                                    KAGGLE_USERNAME/KAGGLE_KEY ya da ~/.kaggle/kaggle.json kullanılır)
    url     url = "https://..."     zip arşivi ya da tek dosya

Config'te bytes/sha256 verilmemiş dosyaların değerleri indirmeden sonra yazdırılır;
config'e eklerseniz sonraki indirmeler bunlarla doğrulanır.
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import registry  # noqa: E402

USER_AGENT = "dataset-downloader/1.0"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify(files, dest):
    """Eksik ya da beklenenden farklı dosyaların listesini döndürür (boşsa her şey yolunda)."""
    problems = []
    for name, meta in files.items():
        path = dest / name
        if not path.exists():
            problems.append(f"eksik: {name}")
            continue
        size = path.stat().st_size
        if "bytes" in meta and size != meta["bytes"]:
            problems.append(f"boyut farklı: {name} ({size} != {meta['bytes']})")
        elif "sha256" in meta and sha256_of(path) != meta["sha256"]:
            problems.append(f"sha256 farklı: {name}")
    return problems


def source_url(source):
    kind = source.get("type")
    if kind == "kaggle":
        return "https://www.kaggle.com/api/v1/datasets/download/" + source["ref"]
    if kind == "url":
        return source["url"]
    raise SystemExit(f"Desteklenmeyen kaynak türü: {kind!r} (kaggle ya da url olmalı)")


def kaggle_auth_header():
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if not (user and key):
        cfg = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle")) / "kaggle.json"
        if cfg.exists():
            creds = json.loads(cfg.read_text())
            user, key = creds.get("username"), creds.get("key")
    if user and key:
        return "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode()
    return None


def open_download(url, source):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if source.get("type") != "kaggle" or e.code not in (401, 403):
            raise
        auth = kaggle_auth_header()
        if auth is None:
            raise SystemExit(
                f"Kaggle anonim indirmeyi reddetti (HTTP {e.code}). "
                "KAGGLE_USERNAME/KAGGLE_KEY ayarlayın ya da ~/.kaggle/kaggle.json oluşturun."
            )
        log("Anonim indirme reddedildi, Kaggle kimlik bilgileriyle deneniyor...")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # Yönlendirilen depolama adresine kimlik bilgisi gönderilmesin
        req.add_unredirected_header("Authorization", auth)
        return urllib.request.urlopen(req, timeout=60)


def download(url, source, out):
    part = out.with_name(out.name + ".part")
    with open_download(url, source) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done, last_pct = 0, -1
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            f.write(block)
            done += len(block)
            if total:
                pct = done * 100 // total
                if pct != last_pct and pct % 5 == 0:
                    log(f"  indiriliyor: %{pct:>3}  ({done / 1e6:,.0f} / {total / 1e6:,.0f} MB)")
                    last_pct = pct
            elif done % (50 << 20) < (1 << 20):
                log(f"  indiriliyor: {done / 1e6:,.0f} MB")
    if total and done != total:
        part.unlink()
        raise SystemExit(f"İndirme yarım kaldı: {done} / {total} bayt")
    part.replace(out)


def extract(archive, files, dest):
    """Zip'ten sadece config'teki dosyaları düz isimleriyle dest/ altına çıkarır.
    İndirilen şey zip değilse ve config'te tek dosya varsa onu o isimle kaydeder."""
    if not zipfile.is_zipfile(archive):
        if len(files) != 1:
            raise SystemExit("İndirilen dosya zip değil ama config'te birden fazla dosya var.")
        archive.replace(dest / next(iter(files)))
        return
    found = set()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = Path(member.filename).name
            if member.is_dir() or name not in files:
                continue
            log(f"  çıkarılıyor: {name}")
            with zf.open(member) as src, open(dest / name, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            found.add(name)
        missing = set(files) - found
        if missing:
            available = sorted(Path(m).name for m in zf.namelist() if not m.endswith("/"))
            raise SystemExit(
                "Arşivde bulunamayan dosyalar: " + ", ".join(sorted(missing))
                + "\nArşivdeki dosyalar: " + ", ".join(available[:50])
            )


def main():
    ap = argparse.ArgumentParser(description="Dataset ham dosyalarını indirir ve doğrular.")
    ap.add_argument("dataset", choices=registry.list_datasets())
    ap.add_argument("--dest", type=Path, help="hedef klasör (varsayılan: data/raw/<dataset>)")
    ap.add_argument("--force", action="store_true", help="dosyalar mevcut olsa bile yeniden indir")
    ap.add_argument("--keep-archive", action="store_true", help="indirilen arşivi silme")
    args = ap.parse_args()

    cfg = registry.load_dataset(args.dataset)
    files, source = cfg["files"], cfg["source"]
    dest = (args.dest or registry.raw_dir(args.dataset)).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    if not args.force and all((dest / n).exists() for n in files):
        log(f"Dosyalar zaten mevcut, doğrulanıyor: {dest}")
        problems = verify(files, dest)
        if not problems:
            log("Tüm dosyalar doğru. İndirmeye gerek yok (yeniden indirmek için --force).")
            return 0
        log("Sorunlu dosyalar bulundu, yeniden indirilecek:\n  " + "\n  ".join(problems))

    expected_bytes = sum(m.get("bytes", 0) for m in files.values())
    free = shutil.disk_usage(dest).free
    if expected_bytes and free < expected_bytes * 1.3:
        raise SystemExit(f"Yetersiz disk alanı: {free / 1e9:.1f} GB boş, ~{expected_bytes * 1.3 / 1e9:.1f} GB gerekli.")

    url = source_url(source)
    archive = dest / f".{args.dataset}.download"
    log(f"Kaynak: {source.get('page') or url}")
    log(f"İndiriliyor → {archive}")
    download(url, source, archive)

    log("Açılıyor...")
    extract(archive, files, dest)
    if archive.exists() and not args.keep_archive:
        archive.unlink()

    log("Doğrulanıyor...")
    problems = verify(files, dest)
    if problems:
        log("HATA: indirilen dosyalar beklenenle eşleşmiyor:\n  " + "\n  ".join(problems))
        return 1

    unverified = [n for n, m in files.items() if "sha256" not in m]
    if unverified:
        log("\nBu dosyalar için config'te sha256 yok. Doğrulama için datasets/"
            f"{args.dataset}.toml dosyasına ekleyebilirsiniz:")
        for n in unverified:
            p = dest / n
            log(f'  [files."{n}"]  bytes = {p.stat().st_size}  sha256 = "{sha256_of(p)}"')

    total = sum((dest / n).stat().st_size for n in files)
    log(f"Tamam: {len(files)} dosya, {total / 1e6:,.0f} MB → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
