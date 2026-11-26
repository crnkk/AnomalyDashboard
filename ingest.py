"""Veri edinme: indirme, zip açma, yüklenen dosyaları diske alma.

Hem scripts/download_data.py hem dashboard kullanır. Her kaynak (kayıtlı dataset,
tarayıcıdan yüklenen CSV/ZIP, Kaggle linki/URL) sonunda diskte CSV'lerden oluşan
bir klasöre dönüşür; büyük dosyalar belleğe alınmadan parça parça işlenir.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import registry

USER_AGENT = "dataset-downloader/1.0"
UPLOADS_DIR = registry.ROOT / "data" / "uploads"
DONE_MARKER = ".tamam"
CHUNK = 1 << 20


class IngestError(Exception):
    """Kullanıcıya gösterilecek, anlaşılır veri edinme hatası."""


def _noop(*_args, **_kwargs):
    pass


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


# ── İndirme ──────────────────────────────────────────────────────
KAGGLE_PAGE_RE = re.compile(r"^https?://(?:www\.)?kaggle\.com/datasets/([\w-]+)/([\w-]+)")
KAGGLE_REF_RE = re.compile(r"^([\w-]+)/([\w-]+)$")


def kaggle_download_url(ref):
    return "https://www.kaggle.com/api/v1/datasets/download/" + ref


def resolve_url(text):
    """Kaggle sayfa linki, 'sahip/dataset' ya da doğrudan URL → (indirme URL'si, kaynak türü)."""
    text = text.strip()
    m = KAGGLE_PAGE_RE.match(text) or KAGGLE_REF_RE.match(text)
    if m:
        return kaggle_download_url(f"{m.group(1)}/{m.group(2)}"), "kaggle"
    if text.startswith(("http://", "https://")):
        return text, "url"
    raise IngestError("Geçerli bir Kaggle linki (kaggle.com/datasets/...) ya da http(s) adresi girin.")


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


def _open(url, source_type):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if source_type != "kaggle" or e.code not in (401, 403):
            raise IngestError(f"İndirme başarısız (HTTP {e.code}).") from e
        auth = kaggle_auth_header()
        if auth is None:
            raise IngestError(
                f"Kaggle indirmeyi reddetti (HTTP {e.code}). Dataset gizli olabilir; "
                "KAGGLE_USERNAME/KAGGLE_KEY ya da ~/.kaggle/kaggle.json gerekli."
            ) from e
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # Yönlendirilen depolama adresine kimlik bilgisi gönderilmesin
        req.add_unredirected_header("Authorization", auth)
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.URLError as e:
        raise IngestError(f"Adrese ulaşılamadı: {e.reason}") from e


def download(url, source_type, out, progress=_noop):
    """URL'yi out dosyasına parça parça indirir. progress(indirilen_bayt, toplam_bayt)."""
    part = out.with_name(out.name + ".part")
    with _open(url, source_type) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            f.write(block)
            done += len(block)
            progress(done, total)
    if total and done != total:
        part.unlink()
        raise IngestError(f"İndirme yarım kaldı: {done} / {total} bayt")
    part.replace(out)
    return out


# ── Zip açma ─────────────────────────────────────────────────────
def extract_csvs(archive, dest, only=None, progress=_noop):
    """Zip'teki CSV'leri düz isimleriyle dest/ altına parça parça çıkarır.

    only verilirse sadece o isimdeki dosyalar alınır. Çıkarılan dosya adlarını döndürür.
    """
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist()
                   if not m.is_dir() and m.filename.lower().endswith(".csv")
                   and not Path(m.filename).name.startswith(("._", "."))]
        if only is not None:
            members = [m for m in members if Path(m.filename).name in only]
        if not members:
            raise IngestError("Zip içinde CSV dosyası bulunamadı.")

        need = sum(m.file_size for m in members)
        free = shutil.disk_usage(dest).free
        if need > free * 0.9:
            raise IngestError(f"Disk alanı yetersiz: açılınca {need / 1e9:.1f} GB, boş {free / 1e9:.1f} GB.")

        names, done = [], 0
        for m in members:
            name = Path(m.filename).name
            if name in names:                       # farklı klasörlerde aynı ad
                name = f"{Path(m.filename).parent.name}_{name}"
            with zf.open(m) as src, open(dest / name, "wb") as dst:
                for block in iter(lambda: src.read(CHUNK), b""):
                    dst.write(block)
                    done += len(block)
                    progress(done, need)
            names.append(name)
    return names


# ── Tarayıcıdan yüklenen dosya / URL → klasör ────────────────────
def _finish(folder, original_name):
    (folder / DONE_MARKER).write_text(original_name, encoding="utf-8")
    return folder


def _store(tmp, folder, original_name, progress):
    """İndirilmiş/yüklenmiş geçici dosyayı (zip ya da csv) klasöre yerleştirir."""
    if zipfile.is_zipfile(tmp):
        extract_csvs(tmp, folder, progress=progress)
        tmp.unlink()
    elif original_name.lower().endswith(".csv"):
        tmp.replace(folder / Path(original_name).name)
    else:
        tmp.unlink()
        raise IngestError("Sadece CSV ya da içinde CSV olan ZIP dosyaları desteklenir.")
    return _finish(folder, original_name)


def ingest_file(fileobj, filename, progress=_noop):
    """Yüklenen dosyayı (CSV ya da ZIP) diske alır, CSV klasörünün yolunu döndürür.

    Aynı içerik ikinci kez yüklenirse yeniden işlenmez (klasör içerik hash'iyle adlandırılır).
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    fileobj.seek(0)
    for block in iter(lambda: fileobj.read(CHUNK), b""):
        h.update(block)
    folder = UPLOADS_DIR / h.hexdigest()[:16]
    if (folder / DONE_MARKER).exists():
        return folder

    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    tmp = folder / ".yukleme"
    fileobj.seek(0)
    with open(tmp, "wb") as f:
        shutil.copyfileobj(fileobj, f, CHUNK)
    try:
        return _store(tmp, folder, filename, progress)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def ingest_url(text, progress=_noop):
    """Kaggle linkini ya da URL'yi indirir, CSV klasörünün yolunu döndürür."""
    url, source_type = resolve_url(text)
    folder = UPLOADS_DIR / ("url-" + hashlib.sha256(url.encode()).hexdigest()[:16])
    if (folder / DONE_MARKER).exists():
        return folder

    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    name = Path(urllib.parse.urlparse(url).path).name or "veri.csv"
    try:
        tmp = download(url, source_type, folder / ".indirme", progress)
        return _store(tmp, folder, name if source_type == "url" else "kaggle.zip", progress)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


# ── Kayıtlı dataset (datasets/<ad>.toml) ─────────────────────────
def verify(files, dest):
    """Eksik ya da config'teki boyut/sha256 ile uyuşmayan dosyaların listesi."""
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


def download_registered(name, dest=None, force=False, keep_archive=False,
                        log=_noop, progress=_noop):
    """Kayıtlı bir datasetin ham dosyalarını config'teki kaynaktan indirir ve doğrular."""
    cfg = registry.load_dataset(name)
    files, source = cfg["files"], cfg["source"]
    dest = Path(dest or registry.raw_dir(name)).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    if not force and all((dest / n).exists() for n in files):
        log(f"Dosyalar zaten mevcut, doğrulanıyor: {dest}")
        problems = verify(files, dest)
        if not problems:
            log("Tüm dosyalar doğru. İndirmeye gerek yok.")
            return dest
        log("Sorunlu dosyalar, yeniden indirilecek:\n  " + "\n  ".join(problems))

    if source.get("type") == "kaggle":
        url, source_type = kaggle_download_url(source["ref"]), "kaggle"
    elif source.get("type") == "url":
        url, source_type = source["url"], "url"
    else:
        raise IngestError(f"Desteklenmeyen kaynak türü: {source.get('type')!r}")

    archive = dest / f".{name}.download"
    log(f"Kaynak: {source.get('page') or url}")
    download(url, source_type, archive, progress)

    log("Açılıyor...")
    if zipfile.is_zipfile(archive):
        found = extract_csvs(archive, dest, only=set(files), progress=progress)
        missing = set(files) - set(found)
        if missing:
            raise IngestError("Arşivde bulunamayan dosyalar: " + ", ".join(sorted(missing)))
        if not keep_archive:
            archive.unlink()
    elif len(files) == 1:
        archive.replace(dest / next(iter(files)))
    else:
        raise IngestError("İndirilen dosya zip değil ama config'te birden fazla dosya var.")

    log("Doğrulanıyor...")
    problems = verify(files, dest)
    if problems:
        raise IngestError("İndirilen dosyalar beklenenle eşleşmiyor:\n  " + "\n  ".join(problems))
    return dest


# ── data/uploads/ temizliği ──────────────────────────────────────
UPLOAD_MAX_BYTES = 5 * 10**9         # toplam boyut bunu aşarsa en eski kullanılanlar silinir
UPLOAD_MAX_AGE_DAYS = 7              # bu kadar gün kullanılmayan klasörler silinir
INCOMPLETE_MAX_AGE_SEC = 3600        # yarım kalmış (işaretsiz) klasörler 1 saat sonra silinir


def _folder_size(folder):
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def touch(folder):
    """Klasörü 'şimdi kullanıldı' olarak işaretler (temizlikte son kullanım zamanı budur)."""
    marker = Path(folder) / DONE_MARKER
    if marker.exists():
        marker.touch()


def list_uploads():
    """(klasör, boyut, son kullanım zamanı, tamamlandı mı) listesi; en eski kullanılan başta."""
    if not UPLOADS_DIR.exists():
        return []
    items = []
    for folder in UPLOADS_DIR.iterdir():
        if not folder.is_dir():
            continue
        marker = folder / DONE_MARKER
        done = marker.exists()
        last_used = (marker if done else folder).stat().st_mtime
        items.append((folder, _folder_size(folder), last_used, done))
    return sorted(items, key=lambda x: x[2])


def delete_upload(folder):
    folder = Path(folder).resolve()
    if folder.parent == UPLOADS_DIR.resolve():      # sadece uploads altındakiler silinir
        shutil.rmtree(folder, ignore_errors=True)


def delete_all_uploads():
    for folder, *_ in list_uploads():
        delete_upload(folder)


def cleanup_uploads(keep=(), max_bytes=UPLOAD_MAX_BYTES, max_age_days=UPLOAD_MAX_AGE_DAYS, now=None):
    """Eski ve fazla yüklemeleri siler; silinen klasörleri döndürür. keep: dokunulmayacaklar."""
    now = now or time.time()
    keep = {Path(k).resolve() for k in keep}
    removed, remaining = [], []
    for folder, size, last_used, done in list_uploads():
        age = now - last_used
        if folder.resolve() in keep:
            remaining.append((folder, size))
        elif (not done and age > INCOMPLETE_MAX_AGE_SEC) or age > max_age_days * 86400:
            delete_upload(folder)
            removed.append(folder)
        else:
            remaining.append((folder, size))

    # Boyut sınırı: en eski kullanılandan başlayarak sil. En son kullanılan kaynak,
    # tek başına sınırı aşsa bile korunur (büyük bir dataseti açılışta silmemek için).
    newest = remaining[-1][0].resolve() if remaining else None
    total = sum(size for _, size in remaining)
    for folder, size in remaining:                  # en eski kullanılan başta
        if total <= max_bytes:
            break
        if folder.resolve() in keep or folder.resolve() == newest:
            continue
        delete_upload(folder)
        removed.append(folder)
        total -= size
    return removed
