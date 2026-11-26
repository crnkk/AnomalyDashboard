"""Dataset kaydı: datasets/*.toml dosyalarını okur, veri klasörlerini çözer.

Yeni dataset eklemek için datasets/<ad>.toml yazmak yeterlidir; kodda
dataset'e özel bir şey tutulmaz.
"""
import os
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent
DATASETS_DIR = ROOT / "datasets"
LOCAL_CONFIG = ROOT / "config.local.toml"


def _read_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_taxonomy():
    """Grup anahtarı → {'id': int, 'title': str}"""
    return _read_toml(DATASETS_DIR / "taxonomy.toml")["groups"]


def list_datasets():
    return sorted(p.stem for p in DATASETS_DIR.glob("*.toml") if p.stem != "taxonomy")


def load_dataset(name):
    path = DATASETS_DIR / f"{name}.toml"
    if not path.exists():
        raise ValueError(f"Bilinmeyen dataset: {name!r}. Mevcut: {', '.join(list_datasets())}")
    cfg = _read_toml(path)
    cfg["name"] = name
    groups = load_taxonomy()
    unknown = sorted({g for g in cfg.get("labels", {}).values() if g not in groups})
    if unknown:
        raise ValueError(f"{path.name}: taxonomy.toml'da olmayan grup(lar): {', '.join(unknown)}")
    return cfg


def label_group_ids(cfg):
    """Ham etiket → grup id (normal = -1)."""
    groups = load_taxonomy()
    return {label: groups[g]["id"] for label, g in cfg.get("labels", {}).items()}


def group_titles():
    """Saldırı grup id → başlık (normal hariç)."""
    return {g["id"]: g["title"] for g in load_taxonomy().values() if g["id"] >= 0}


def normalize_labels(labels, cfg):
    """pandas Series'teki etiketlere config'teki düzeltmeleri uygular."""
    out = labels.astype(str)
    for old, new in cfg.get("label_normalize", {}).get("replace", []):
        out = out.str.replace(old, new, regex=False)
    return out.str.strip()


def raw_dir(name):
    return ROOT / "data" / "raw" / name


def sample_dir(name):
    return ROOT / "data" / "sample" / name


def local_config():
    return _read_toml(LOCAL_CONFIG) if LOCAL_CONFIG.exists() else {}


def resolve_data_dir(name):
    """config.local.toml [data_dirs] > tam veri (indirildiyse) > örnek veri."""
    override = local_config().get("data_dirs", {}).get(name)
    if override:
        return Path(override).expanduser()
    if any(raw_dir(name).glob("*.csv")):
        return raw_dir(name)
    return sample_dir(name)
