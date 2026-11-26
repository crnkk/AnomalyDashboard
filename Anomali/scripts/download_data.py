#!/usr/bin/env python3
"""CIC-IDS2017 (MachineLearningCVE CSV dosyaları) Kaggle'dan indirir ve doğrular.

Kullanım:
    python scripts/download_data.py              # data/raw/cicids2017/ altına indirir
    python scripts/download_data.py --dest DIR   # başka bir klasöre indirir
    python scripts/download_data.py --force      # dosyalar varsa bile yeniden indirir

Sadece standart kütüphane kullanır. Dataset herkese açık olduğu için Kaggle hesabı
gerekmez; anonim indirme reddedilirse KAGGLE_USERNAME / KAGGLE_KEY ortam
değişkenleri ya da ~/.kaggle/kaggle.json kullanılır.
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

KAGGLE_REF = "chethuhn/network-intrusion-dataset"
KAGGLE_PAGE = "https://www.kaggle.com/datasets/" + KAGGLE_REF
DOWNLOAD_URL = "https://www.kaggle.com/api/v1/datasets/download/" + KAGGLE_REF

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = ROOT / "data" / "raw" / "cicids2017"

# dosya adı -> (bayt, sha256)
EXPECTED = {
    "Monday-WorkingHours.pcap_ISCX.csv":
        (176927918, "852c4beb34eda186f32561fa79df7a0747e92e1a6535b01270820dd9ffe17f34"),
    "Tuesday-WorkingHours.pcap_ISCX.csv":
        (135078995, "52b8692ae8c7d2ed04671fe2b98335693c0a92c7ab157d8c8b534d6523080851"),
    "Wednesday-workingHours.pcap_ISCX.csv":
        (225166395, "893c27dc968bf7a8adef1689f90be55ca4a4dc3088fb63d6ff247ac56856df2a"),
    "Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv":
        (52023263, "d67066211fb1689c78406f1506f4c44704ecb92088353d5c96d96d6474eb819d"),
    "Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv":
        (83102436, "6bcda3857c2504676034e3ea57762d38393cc734cb377a726bd5cb153961b1b5"),
    "Friday-WorkingHours-Morning.pcap_ISCX.csv":
        (58316725, "53a41c24d570ea83b7ac55b2e94df94e7a8216aeb80a2af0246b6bc8bb543000"),
    "Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv":
        (76906168, "ca1824c51bfbb7b3c72290a11be04366ba8815878c6a1cc5c44cb1cee269e99b"),
    "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv":
        (77123859, "6ff1580f5f81c0ae28a26f7631721018577f5f7c5e0feac28b795fcfe7b411ee"),
}
TOTAL_BYTES = sum(size for size, _ in EXPECTED.values())
ZIP_BYTES_APPROX = 241_000_000


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify(dest):
    """Eksik ya da beklenenden farklı dosyaların listesini döndürür (boşsa her şey yolunda)."""
    problems = []
    for name, (size, digest) in EXPECTED.items():
        path = dest / name
        if not path.exists():
            problems.append(f"eksik: {name}")
        elif path.stat().st_size != size:
            problems.append(f"boyut farklı: {name} ({path.stat().st_size} != {size})")
        elif sha256_of(path) != digest:
            problems.append(f"sha256 farklı: {name}")
    return problems


def kaggle_auth_header():
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if not (user and key):
        cfg_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
        cfg = cfg_dir / "kaggle.json"
        if cfg.exists():
            creds = json.loads(cfg.read_text())
            user, key = creds.get("username"), creds.get("key")
    if user and key:
        return "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode()
    return None


def open_download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-downloader/1.0"})
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise
        auth = kaggle_auth_header()
        if auth is None:
            raise SystemExit(
                f"Kaggle anonim indirmeyi reddetti (HTTP {e.code}). "
                "KAGGLE_USERNAME/KAGGLE_KEY ayarlayın ya da ~/.kaggle/kaggle.json oluşturun."
            )
        log("Anonim indirme reddedildi, Kaggle kimlik bilgileriyle deneniyor...")
        req = urllib.request.Request(url, headers={"User-Agent": "dataset-downloader/1.0"})
        # Yönlendirilen depolama adresine kimlik bilgisi gönderilmesin
        req.add_unredirected_header("Authorization", auth)
        return urllib.request.urlopen(req, timeout=60)


def download(url, out):
    part = out.with_name(out.name + ".part")
    with open_download(url) as resp, open(part, "wb") as f:
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
    if total and done != total:
        part.unlink()
        raise SystemExit(f"İndirme yarım kaldı: {done} / {total} bayt")
    part.replace(out)


def extract(archive, dest):
    """Arşivden sadece beklenen CSV'leri, düz isimleriyle dest/ altına çıkarır."""
    found = set()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = Path(member.filename).name
            if member.is_dir() or name not in EXPECTED:
                continue
            log(f"  çıkarılıyor: {name}")
            with zf.open(member) as src, open(dest / name, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            found.add(name)
    missing = set(EXPECTED) - found
    if missing:
        raise SystemExit("Arşivde bulunamayan dosyalar: " + ", ".join(sorted(missing)))


def main():
    ap = argparse.ArgumentParser(description="CIC-IDS2017 CSV dosyalarını Kaggle'dan indirir.")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"hedef klasör (varsayılan: {DEFAULT_DEST})")
    ap.add_argument("--force", action="store_true", help="dosyalar mevcut olsa bile yeniden indir")
    ap.add_argument("--keep-zip", action="store_true", help="indirilen zip dosyasını silme")
    args = ap.parse_args()

    dest = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    if not args.force and all((dest / n).exists() for n in EXPECTED):
        log(f"Dosyalar zaten mevcut, doğrulanıyor: {dest}")
        problems = verify(dest)
        if not problems:
            log("Tüm dosyalar doğru. İndirmeye gerek yok (yeniden indirmek için --force).")
            return 0
        log("Sorunlu dosyalar bulundu, yeniden indirilecek:\n  " + "\n  ".join(problems))

    need = ZIP_BYTES_APPROX + TOTAL_BYTES
    free = shutil.disk_usage(dest).free
    if free < need:
        raise SystemExit(f"Yetersiz disk alanı: {free / 1e9:.1f} GB boş, ~{need / 1e9:.1f} GB gerekli.")

    archive = dest / ".cicids2017.zip"
    log(f"Kaynak: {KAGGLE_PAGE}")
    log(f"İndiriliyor (~{ZIP_BYTES_APPROX / 1e6:.0f} MB) → {archive}")
    download(DOWNLOAD_URL, archive)

    log("Arşiv açılıyor...")
    extract(archive, dest)
    if not args.keep_zip:
        archive.unlink()

    log("Doğrulanıyor (boyut + sha256)...")
    problems = verify(dest)
    if problems:
        log("HATA: indirilen dosyalar beklenenle eşleşmiyor:\n  " + "\n  ".join(problems))
        return 1
    log(f"Tamam: {len(EXPECTED)} dosya, {TOTAL_BYTES / 1e6:,.0f} MB → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
