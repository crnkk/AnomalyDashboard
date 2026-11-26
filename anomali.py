import streamlit as st
import pandas as pd
import numpy as np
import os
import glob
import time
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest  # noqa: E402
import registry  # noqa: E402

# ── Sayfa ayarları ──────────────────────────────────────────────
st.set_page_config(
    page_title="Anomali Tespit",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem !important; }
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    padding: 8px 20px;
    font-weight: 500;
}
.stage-header {
    background: linear-gradient(135deg, #0F6E56, #1D9E75);
    color: white;
    padding: 16px 24px;
    border-radius: 12px;
    margin-bottom: 20px;
}
.warn-box {
    background: #a17b00;
    border-left: 4px solid #F9A825;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 8px 0;
}
.info-box {
    background: #3b6787;
    border-left: 4px solid #1565C0;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 8px 0;
}
.success-box {
    background: #36a83c;
    border-left: 4px solid #2E7D32;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 8px 0;
}
.danger-box {
    background: #FFEBEE;
    border-left: 4px solid #C62828;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 8px 0;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SABİTLER
# ══════════════════════════════════════════════════════
DROP_COLS = {'Label', 'binary_label', 'multi_label', 'day'}

# ══════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════
MODE_UPLOAD = "⬆️ Dosya yükle (CSV / ZIP)"
MODE_URL    = "🔗 Kaggle linki / URL"
MAX_CSV     = 10    # aynı anda analize alınabilecek en fazla CSV
RAM_FACTOR  = 15    # ölçüm: 885 MB CSV, üç aşama boyunca ~13,6 GB tepe bellek

def total_ram_bytes():
    try:
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (ValueError, OSError, AttributeError):
        return None

def progress_bar(text):
    """st.progress'i ingest modülünün progress(done, total) arayüzüne bağlar."""
    bar = st.progress(0.0, text=text)
    def update(done, total):
        if total:
            bar.progress(min(done / total, 1.0), text=f"{text} {done / 1e6:,.0f} / {total / 1e6:,.0f} MB")
        else:
            bar.progress(0.0, text=f"{text} {done / 1e6:,.0f} MB")
    return bar, update

@st.cache_data(show_spinner="Dosyalar tanınıyor...")
def detect_csvs(paths):
    """CSV dosyalarının hangi kayıtlı datasete ait olduğunu bulur (None = tanınmadı)."""
    first = Path(paths[0])
    columns = pd.read_csv(first, nrows=0).columns.tolist()

    def read_label_column(col):
        return pd.read_csv(first, usecols=lambda c: c.strip() == col, low_memory=False).iloc[:, 0]

    name = registry.detect_dataset([Path(p).name for p in paths], columns, read_label_column)
    return name, registry.guess_label_column(columns)

def reset_uploads():
    """Silme sonrası: oturumdaki yükleme kayıtlarını ve yükleme kutusunu sıfırlar."""
    for key in ['ingested', 'url_folder', 'data', 'load_log', 'missing', 'clean_data',
                'clean_stats', 'labeled_data', 'benign_unmatched', 'source_key']:
        st.session_state.pop(key, None)
    st.session_state['uploader_gen'] = st.session_state.get('uploader_gen', 0) + 1
    st.rerun()

# Uygulama açılırken (oturum başına bir kez) eski ve fazla yüklemeleri temizle
if 'uploads_cleaned' not in st.session_state:
    ingest.cleanup_uploads()
    st.session_state['uploads_cleaned'] = True

with st.sidebar:
    st.title("🛡️ Anomali Tespit")
    st.caption("Veri hazırlama pipeline'ı")
    st.divider()

    MODE = st.radio("Veri kaynağı", [MODE_UPLOAD, MODE_URL])
    csv_paths, MISSING, folders = [], [], []

    if MODE == MODE_UPLOAD:
        uploads = st.file_uploader(
            f"CSV ya da ZIP dosyaları (en fazla {MAX_CSV})",
            type=["csv", "zip"],
            accept_multiple_files=True,
            key=f"uploader_{st.session_state.get('uploader_gen', 0)}",
            help="ZIP içindeki tüm CSV'ler açılır. Çok büyük veriler için "
                 "'Kaggle linki / URL' seçeneği daha hızlıdır.",
        )
        uploads = uploads or []
        if len(uploads) > MAX_CSV:
            st.error(f"En fazla {MAX_CSV} dosya yüklenebilir; ilk {MAX_CSV} dosya kullanılıyor.")
            uploads = uploads[:MAX_CSV]
        ingested = st.session_state.setdefault('ingested', {})
        for up in uploads:
            if up.file_id not in ingested:
                bar, update = progress_bar(f"{up.name} açılıyor:")
                try:
                    ingested[up.file_id] = str(ingest.ingest_file(up, up.name, progress=update))
                except (ingest.IngestError, zipfile.BadZipFile) as e:
                    st.error(f"{up.name}: {e}")
                    continue
                finally:
                    bar.empty()
            folders.append(Path(ingested[up.file_id]))
    else:
        url = st.text_input("Kaggle linki ya da dosya URL'si",
                            placeholder="https://www.kaggle.com/datasets/sahip/dataset")
        if st.button("⬇️ İndir", use_container_width=True, disabled=not url.strip()):
            bar, update = progress_bar("İndiriliyor:")
            try:
                st.session_state['url_folder'] = (url.strip(), str(ingest.ingest_url(url, progress=update)))
            except ingest.IngestError as e:
                st.error(str(e))
            finally:
                bar.empty()
        saved = st.session_state.get('url_folder')
        if saved and saved[0] == url.strip():
            folders.append(Path(saved[1]))

    for folder in folders:
        ingest.touch(folder)

    seen = set()
    for folder in folders:
        for p in sorted(folder.glob("*.csv")):
            if p.name not in seen:
                seen.add(p.name)
                csv_paths.append(p)

    if csv_paths:
        name, guessed_label = detect_csvs(tuple(str(p) for p in csv_paths))
        if name:
            DATASET, CFG = name, registry.load_dataset(name)
            st.success(f"Tanınan dataset: **{CFG['title']}**")
        else:
            DATASET, CFG = '_bilinmeyen', registry.generic_config(guessed_label)
            st.info(f"Dataset tanınmadı. Etiket sütunu: **{guessed_label}**. "
                    "Kalıcı eşleme için `datasets/` altına bir .toml ekleyin.")
    else:
        DATASET, CFG = '_bos', registry.generic_config('Label')

    def file_meta(fname):
        stem = Path(fname).stem.replace('.pcap_ISCX', '')
        return CFG['files'].get(fname, {'segment': stem, 'title': stem})

    if csv_paths:
        names = [p.name for p in csv_paths]
        if len(names) > MAX_CSV:
            st.warning(f"{len(names)} CSV bulundu; aynı anda en fazla {MAX_CSV} tanesi seçilebilir.")
        selected = st.multiselect(
            "CSV dosyaları",
            names,
            default=names[:MAX_CSV],
            max_selections=MAX_CSV,
            format_func=lambda f: file_meta(f).get('title', f),
            help="Analize dahil edilecek dosyalar",
        )
        SOURCES = [p for p in csv_paths if p.name in selected]

        size = sum(p.stat().st_size for p in SOURCES)
        need = size * RAM_FACTOR
        st.caption(f"Seçilen: {size / 1e6:,.0f} MB · işlerken gereken bellek ~{need / 1e9:,.1f} GB")
        ram = total_ram_bytes()
        if ram and need > ram * 0.6:
            st.warning(f"Bu seçim bilgisayarın belleğini ({ram / 1e9:,.0f} GB) zorlayabilir. "
                       "Daha az dosya seçin.")
    else:
        SOURCES = []

    uploads_on_disk = ingest.list_uploads()
    if uploads_on_disk:
        disk_total = sum(size for _, size, _, _ in uploads_on_disk)
        with st.expander(f"🗑️ Yüklenen veriler ({disk_total / 1e9:,.2f} GB)"):
            st.caption(f"Diskte {len(uploads_on_disk)} kaynak var. "
                       f"{ingest.UPLOAD_MAX_AGE_DAYS} gün kullanılmayanlar ve toplam "
                       f"{ingest.UPLOAD_MAX_BYTES / 1e9:.0f} GB'ı aşan kısım (en eski kullanılandan "
                       "başlayarak) uygulama açılırken otomatik silinir.")
            del_current, del_all = st.columns(2)
            if del_current.button("Bu kaynağı sil", disabled=not folders, use_container_width=True):
                for folder in folders:
                    ingest.delete_upload(folder)
                reset_uploads()
            if del_all.button("Tümünü sil", use_container_width=True):
                ingest.delete_all_uploads()
                reset_uploads()

    st.divider()
    st.markdown("### Pipeline aşamaları")
    st.markdown("""
    1. 📂 **Veri Yükleme**
    2. 🧹 **Temizleme**
    3. 🏷️ **Etiketleme**
    4. ⚖️ **Imbalance Analizi**
    5. 📊 **Feature Grupları**
    """)
    st.divider()
    st.caption("Tüm aşamalar önbelleğe alınır. Seçim değişirse yeniden hesaplanır.")

# ── Seçimden türetilen tablolar ─────────────────────────
FILE_MAP      = {p.name: file_meta(p.name)['segment'] for p in SOURCES}
DAY_LABELS    = {file_meta(p.name)['segment']: file_meta(p.name).get('title', p.name) for p in SOURCES}
ATTACK_GROUPS = registry.label_group_ids(CFG)   # ham etiket → grup id (normal = -1)
GROUP_NAMES   = registry.group_titles()         # grup id → başlık
LABEL_COL     = CFG['label_column']
NORMAL_LABELS = ([lbl for lbl, gid in ATTACK_GROUPS.items() if gid == -1]
                 or list(registry.NORMAL_LABEL_GUESSES))

# Seçim değişince önceki aşamaların sonuçlarını unut
SOURCE_KEY = f"{DATASET}:" + "|".join(f"{p.resolve()}@{p.stat().st_mtime_ns}" for p in SOURCES)
if st.session_state.get('source_key') != SOURCE_KEY:
    for key in ['data', 'load_log', 'missing', 'clean_data', 'clean_stats',
                'labeled_data', 'benign_unmatched']:
        st.session_state.pop(key, None)
    st.session_state['source_key'] = SOURCE_KEY

# ══════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════
def safe_map(label):
    return ATTACK_GROUPS.get(label, -1)

def color_ratio(ratio):
    if ratio < 1:
        return "🔴"
    elif ratio < 5:
        return "🟠"
    elif ratio < 20:
        return "🟡"
    else:
        return "🟢"

@st.cache_data(show_spinner=False)
def load_data(source_key, _sources):
    """_sources: CSV yolları. Önbellek anahtarı source_key (dataset + yollar + değişme zamanı)."""
    frames = []
    load_log = []

    for path in _sources:
        fname = path.name
        df = pd.read_csv(path, encoding='utf-8', low_memory=False)
        df.columns = df.columns.str.strip()
        if LABEL_COL not in df.columns:
            raise ValueError(f"{fname}: '{LABEL_COL}' etiket sütunu bulunamadı")
        if LABEL_COL != 'Label':
            df = df.drop(columns=['Label'], errors='ignore').rename(columns={LABEL_COL: 'Label'})
        df['Label'] = registry.normalize_labels(df['Label'], CFG)
        day_tag = FILE_MAP[fname]
        df['day'] = day_tag
        classes = df['Label'].unique().tolist()
        load_log.append({
            'Dosya': fname.replace('.pcap_ISCX.csv', ''),
            'Gün': DAY_LABELS[day_tag],
            'Kayıt': len(df),
            'Sınıflar': len(classes),
            'Etiketler': ', '.join(sorted(classes))
        })
        frames.append(df)

    if not frames:
        return None, load_log

    data = pd.concat(frames, ignore_index=True)
    return data, load_log

@st.cache_data(show_spinner=False)
def clean_data(data_hash, _data):
    before = len(_data)
    df = _data.copy()
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    inf_counts = (_data.isin([np.inf, -np.inf])).sum()
    nan_counts = _data.isna().sum()

    df.dropna(inplace=True)
    after = len(df)
    dropped = before - after
    return df, before, after, dropped, inf_counts, nan_counts

@st.cache_data(show_spinner=False)
def label_data(data_hash, _data):
    df = _data.copy()
    df['binary_label'] = (~df['Label'].isin(NORMAL_LABELS)).astype(int)
    df['multi_label']  = df['Label'].apply(safe_map)

    # Config'te [labels] altında olmayan etiketler (yeni dataset eklerken buradan görülür)
    benign_unmatched = sorted(set(df['Label'].unique()) - set(ATTACK_GROUPS))

    return df, benign_unmatched

# ══════════════════════════════════════════════════════
# BAŞLIK
# ══════════════════════════════════════════════════════
st.markdown(f"""
<div class="stage-header">
    <h1 style="margin:0;font-size:1.8rem">🛡️ {CFG["title"]} Anomali Tespit Pipeline</h1>
    <p style="margin:4px 0 0;opacity:0.85">Paralel + Seri Neural Network · {len(GROUP_NAMES)} Saldırı Grubu · İnanç Filtresi</p>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SEKMELİ GÖRÜNÜM
# ══════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📂 Veri Yükleme",
    "🧹 Temizleme",
    "🏷️ Etiketleme",
    "⚖️ Imbalance",
    "📊 Feature Grupları",
])

# ══════════════════════════════════════════════════════
# TAB 1: VERİ YÜKLEME
# ══════════════════════════════════════════════════════
with tab1:
    st.subheader("Aşama 0 — Veri Yükleme")

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        load_btn = st.button("🚀 Veriyi Yükle", type="primary", use_container_width=True,
                             disabled=not SOURCES)

    if load_btn or 'data' in st.session_state:

        if 'data' not in st.session_state or load_btn:
            with st.spinner("CSV dosyaları okunuyor..."):
                progress = st.progress(0, text="Dosyalar taranıyor...")
                data, load_log = load_data(SOURCE_KEY, SOURCES)
                missing = MISSING
                for i in range(100):
                    time.sleep(0.005)
                    progress.progress(i + 1, text=f"Yükleniyor... %{i+1}")
                progress.empty()

            if data is None:
                st.error("❌ Yüklenecek CSV seçilmedi. Soldaki panelden dosya seçin.")
                st.stop()

            st.session_state['data']     = data
            st.session_state['load_log'] = load_log
            st.session_state['missing']  = missing

        data     = st.session_state['data']
        load_log = st.session_state['load_log']
        missing  = st.session_state['missing']

        # Özet metrikler
        st.markdown("#### Özet")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Toplam kayıt", f"{len(data):,}")
        m2.metric("Yüklenen dosya", len(load_log))
        m3.metric("Sütun sayısı", len(data.columns))
        m4.metric("Eksik dosya", len(missing))

        # Yükleme logu
        st.markdown("#### Dosya detayları")
        log_df = pd.DataFrame(load_log)
        st.dataframe(log_df, use_container_width=True, hide_index=True)

        # Eksik dosyalar
        if missing:
            st.markdown('<div class="warn-box">⚠️ <b>Bulunamayan dosyalar:</b><br>' +
                        '<br>'.join(f'• {f}' for f in missing) + '</div>',
                        unsafe_allow_html=True)

        # Genel Label dağılımı
        st.markdown("#### Tüm veri sınıf dağılımı")
        label_counts = data['Label'].value_counts().reset_index()
        label_counts.columns = ['Etiket', 'Sayı']
        label_counts['Oran %'] = (label_counts['Sayı'] / len(data) * 100).round(3)
        label_counts['Tür'] = label_counts['Etiket'].apply(
            lambda x: '🟢 Normal' if x in NORMAL_LABELS else '🔴 Saldırı'
        )
        st.dataframe(label_counts, use_container_width=True, hide_index=True)

        # Gün bazlı dağılım grafiği
        st.markdown("#### Gün bazlı kayıt dağılımı")
        day_counts = data.groupby('day').agg(
            Toplam=('Label', 'count'),
            Normal=('Label', lambda x: x.isin(NORMAL_LABELS).sum()),
            Saldiri=('Label', lambda x: (~x.isin(NORMAL_LABELS)).sum())
        ).reset_index()
        day_counts['Gün'] = day_counts['day'].map(DAY_LABELS)
        st.bar_chart(day_counts.set_index('Gün')[['Normal', 'Saldiri']])

        st.markdown('<div class="success-box">✅ Veri başarıyla yüklendi. "Temizleme" sekmesine geçebilirsiniz.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">ℹ️ Soldaki panelden veri kaynağını ve CSV dosyalarını seçin, '
                    'sonra yukarıdaki butona tıklayın.</div>',
                    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# TAB 2: TEMİZLEME
# ══════════════════════════════════════════════════════
with tab2:
    st.subheader("Aşama 1 — Veri Temizleme")

    if 'data' not in st.session_state:
        st.warning("Önce **Veri Yükleme** sekmesinden veriyi yükleyin.")
        st.stop()

    raw_data = st.session_state['data']

    clean_btn = st.button("🧹 Temizlemeyi Başlat", type="primary")

    if clean_btn or 'clean_data' in st.session_state:
        if 'clean_data' not in st.session_state or clean_btn:
            with st.spinner("Inf ve NaN değerler temizleniyor..."):
                data_hash = f"{SOURCE_KEY}:{len(raw_data)}"
                clean, before, after, dropped, inf_counts, nan_counts = clean_data(data_hash, raw_data)
                st.session_state['clean_data'] = clean
                st.session_state['clean_stats'] = (before, after, dropped, inf_counts, nan_counts)

        clean = st.session_state['clean_data']
        before, after, dropped, inf_counts, nan_counts = st.session_state['clean_stats']

        # Metrikler
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Temizleme öncesi", f"{before:,}")
        c2.metric("Temizleme sonrası", f"{after:,}")
        c3.metric("Silinen satır", f"{dropped:,}",
                  delta=f"-{dropped/before*100:.2f}%", delta_color="inverse")
        c4.metric("Veri kaybı", f"{dropped/before*100:.3f}%")

        st.divider()

        col_inf, col_nan = st.columns(2)

        with col_inf:
            st.markdown("#### Inf değer dağılımı (feature bazlı)")
            inf_df = inf_counts[inf_counts > 0].reset_index()
            if len(inf_df) > 0:
                inf_df.columns = ['Feature', 'Inf Sayısı']
                st.dataframe(inf_df, use_container_width=True, hide_index=True)
            else:
                st.success("Inf değer bulunamadı.")

        with col_nan:
            st.markdown("#### NaN değer dağılımı (feature bazlı)")
            nan_df = nan_counts[nan_counts > 0].reset_index()
            if len(nan_df) > 0:
                nan_df.columns = ['Feature', 'NaN Sayısı']
                st.dataframe(nan_df, use_container_width=True, hide_index=True)
            else:
                st.success("NaN değer bulunamadı.")

        st.divider()
        st.markdown("#### Temiz veriden ilk 5 satır önizleme")
        st.dataframe(clean.head(), use_container_width=True)

        st.markdown('<div class="success-box">✅ Temizleme tamamlandı. "Etiketleme" sekmesine geçebilirsiniz.</div>',
                    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# TAB 3: ETİKETLEME
# ══════════════════════════════════════════════════════
with tab3:
    st.subheader("Aşama 2 — Binary & Multi-class Etiketleme")

    if 'clean_data' not in st.session_state:
        st.warning("Önce **Temizleme** sekmesini çalıştırın.")
        st.stop()

    clean = st.session_state['clean_data']

    label_btn = st.button("🏷️ Etiketlemeyi Başlat", type="primary")

    if label_btn or 'labeled_data' in st.session_state:
        if 'labeled_data' not in st.session_state or label_btn:
            with st.spinner("Etiketler oluşturuluyor..."):
                data_hash = f"{SOURCE_KEY}:{len(clean)}"
                labeled, benign_unmatched = label_data(data_hash, clean)
                st.session_state['labeled_data']       = labeled
                st.session_state['benign_unmatched']   = benign_unmatched

        labeled           = st.session_state['labeled_data']
        benign_unmatched  = st.session_state['benign_unmatched']

        # Eşleşmeyen etiketler
        if benign_unmatched:
            st.markdown(f'<div class="danger-box">❌ <b>Config\'te eşlemesi olmayan etiketler</b>: {", ".join(benign_unmatched)}<br>datasets/{DATASET}.toml → [labels] altına ekleyin.</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="success-box">✅ Tüm saldırı etiketleri gruplara başarıyla eşlendi.</div>',
                        unsafe_allow_html=True)

        st.divider()

        col_bin, col_multi = st.columns(2)

        with col_bin:
            st.markdown("#### Binary etiket (Stage 1 — 1. Elek)")
            bin_counts = labeled['binary_label'].value_counts().reset_index()
            bin_counts.columns = ['Etiket (0/1)', 'Sayı']
            bin_counts['Açıklama'] = bin_counts['Etiket (0/1)'].map({0: '🟢 Normal', 1: '🔴 Anomali'})
            bin_counts['Oran %']   = (bin_counts['Sayı'] / len(labeled) * 100).round(3)
            st.dataframe(bin_counts, use_container_width=True, hide_index=True)

            anomali_oran = labeled['binary_label'].mean() * 100
            if anomali_oran < 1:
                st.markdown(f'<div class="danger-box">⚠️ Anomali oranı <b>%{anomali_oran:.3f}</b> → %1 altında! SMOTE zorunlu.</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="info-box">ℹ️ Anomali oranı <b>%{anomali_oran:.2f}</b> → class_weight yeterli.</div>',
                            unsafe_allow_html=True)

        with col_multi:
            st.markdown("#### Multi-class etiket (Stage 2 — 2. Elek)")
            multi_counts = (
                labeled[labeled['binary_label'] == 1]['multi_label']
                .value_counts().reset_index()
            )
            multi_counts.columns = ['Grup ID', 'Sayı']
            multi_counts['Grup Adı'] = multi_counts['Grup ID'].map(GROUP_NAMES)
            multi_counts['Oran %']   = (multi_counts['Sayı'] /
                                         multi_counts['Sayı'].sum() * 100).round(2)
            multi_counts['Strateji'] = multi_counts['Sayı'].apply(
                lambda x: '🔴 SMOTE zorunlu' if x < 50
                else ('🟡 CW dikkat' if x < 2000 else '🟢 class_weight')
            )
            st.dataframe(multi_counts.sort_values('Grup ID'),
                         use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### Attack group haritası")
        group_table = pd.DataFrame([
            {'Grup': k, 'ID': v, 'Grup Adı': GROUP_NAMES.get(v, 'Normal (kullanılmaz)')}
            for k, v in ATTACK_GROUPS.items()
        ])
        st.dataframe(group_table, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════
# TAB 4: IMBALANCE ANALİZİ
# ══════════════════════════════════════════════════════
with tab4:
    st.subheader("Aşama 3 — Imbalance Analizi & Class Weight")

    if 'labeled_data' not in st.session_state:
        st.warning("Önce **Etiketleme** sekmesini çalıştırın.")
        st.stop()

    labeled = st.session_state['labeled_data']

    from sklearn.utils.class_weight import compute_class_weight

    st.markdown("#### Binary class weight (Stage 1)")

    y_bin = labeled['binary_label'].values
    if len(np.unique(y_bin)) < 2:
        only = "normal" if y_bin.max() == 0 else "saldırı"
        st.info(f"Seçilen veride sadece **{only}** trafik var; binary class weight hesaplanamaz. "
                "Hem normal hem saldırı içeren dosyaları seçin.")
    else:
        w = compute_class_weight('balanced', classes=np.array([0, 1]), y=y_bin)
        cw_bin = {0: float(w[0]), 1: float(w[1])}

        cw1, cw2, cw3 = st.columns(3)
        cw1.metric("Normal ağırlığı (0)", f"{cw_bin[0]:.4f}")
        cw2.metric("Anomali ağırlığı (1)", f"{cw_bin[1]:.4f}")
        cw3.metric("Ağırlık oranı (1/0)", f"{cw_bin[1]/cw_bin[0]:.1f}x")

    st.markdown('<div class="info-box">ℹ️ class_weight=\'balanced\' formülü: <b>N_total / (N_classes × N_class_i)</b>.<br>'
                'Anomali ağırlığı yüksekse model anomaliyi daha fazla önemser — kayıp fonksiyonunda penalize edilir.</div>',
                unsafe_allow_html=True)

    st.divider()
    st.markdown("#### Gün bazlı imbalance özeti")

    day_imbalance = []
    for day_tag in FILE_MAP.values():
        if day_tag not in labeled['day'].values:
            continue
        sub = labeled[labeled['day'] == day_tag]
        total = len(sub)
        normal = (sub['binary_label'] == 0).sum()
        atk    = (sub['binary_label'] == 1).sum()
        ratio  = atk / total * 100
        day_imbalance.append({
            'Gün': DAY_LABELS.get(day_tag, day_tag),
            'Toplam': total,
            'Normal': normal,
            'Saldırı': atk,
            'Anomali %': round(ratio, 3),
            'Durum': ('🔴 SMOTE' if ratio < 1 and atk > 0
                      else ('🟡 CW' if ratio < 5
                            else ('🟢 Dengeli' if ratio > 40 else '🟡 CW'))),
        })
    imb_df = pd.DataFrame(day_imbalance)
    st.dataframe(imb_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### Multi-class (Stage 2) class weight")

    y_mul_only = labeled[labeled['binary_label'] == 1]['multi_label'].values
    y_mul_only = y_mul_only[y_mul_only >= 0].astype(int)   # -1 (normal) çıkar
    existing_classes = np.unique(y_mul_only)               # gerçekte var olan sınıflar
    if len(existing_classes) == 0:
        st.info("Gruplara eşlenmiş saldırı etiketi yok (veride saldırı yok ya da dataset "
                "tanınmadı), Stage 2 ağırlıkları hesaplanamaz.")
        cw_mul = {}
    else:
        w_mul = compute_class_weight('balanced', classes=existing_classes, y=y_mul_only)
        cw_mul = {int(cls): float(w) for cls, w in zip(existing_classes, w_mul)}

    cw_df = pd.DataFrame([
        {
            'Grup ID': k,
            'Grup Adı': GROUP_NAMES.get(k, '?'),
            'Sayı': int((y_mul_only == k).sum()),
            'Class Weight': round(v, 4),
            'SMOTE gerekli?': '🔴 Evet' if (y_mul_only == k).sum() < 50 else '🟢 Hayır',
        }
        for k, v in cw_mul.items()
    ])
    st.dataframe(cw_df, use_container_width=True, hide_index=True)

    st.markdown('<div class="warn-box">⚠️ <b>SMOTE hedefi:</b> 50\'den az örnek içeren sınıflar (Heartbleed, Infiltration, SQLi) '
                'için minimum 2000 sentetik örnek üretilecek.</div>', unsafe_allow_html=True)

    with st.expander("Python kodu — class_weight hesaplama"):
        st.code("""
from sklearn.utils.class_weight import compute_class_weight
import numpy as np

# Binary (Stage 1)
w = compute_class_weight('balanced', classes=np.array([0,1]), y=y_bin)
class_weight_s1 = {0: float(w[0]), 1: float(w[1])}

# Multi-class (Stage 2 — sadece anomali örnekler)
y_mul_only = y_mul[y_bin == 1].astype(int)
w_mul = compute_class_weight('balanced', classes=np.arange(5), y=y_mul_only)
class_weight_s2 = {i: float(w_mul[i]) for i in range(5)}
        """, language='python')

# ══════════════════════════════════════════════════════
# TAB 5: FEATURE GRUPLARI
# ══════════════════════════════════════════════════════
with tab5:
    st.subheader("Aşama 4 — Feature Gruplandırma (Paralel NN için)")

    if 'labeled_data' not in st.session_state:
        st.warning("Önce **Etiketleme** sekmesini çalıştırın.")
        st.stop()

    labeled = st.session_state['labeled_data']
    feature_cols = [c for c in labeled.columns if c not in DROP_COLS]

    st.metric("Toplam feature sayısı", len(feature_cols))

    # Feature grupları
    FLOW_NAMES = [
        'Flow Duration', 'Flow Bytes/s', 'Flow Packets/s',
        'Flow IAT Mean', 'Flow IAT Std', 'Flow IAT Max', 'Flow IAT Min',
        'Fwd IAT Total', 'Fwd IAT Mean', 'Fwd IAT Std', 'Fwd IAT Max', 'Fwd IAT Min',
        'Bwd IAT Total', 'Bwd IAT Mean', 'Bwd IAT Std', 'Bwd IAT Max', 'Bwd IAT Min',
    ]
    PACKET_NAMES = [
        'Total Fwd Packets', 'Total Backward Packets',
        'Total Length of Fwd Packets', 'Total Length of Bwd Packets',
        'Fwd Packet Length Max', 'Fwd Packet Length Min',
        'Fwd Packet Length Mean', 'Fwd Packet Length Std',
        'Bwd Packet Length Max', 'Bwd Packet Length Min',
        'Bwd Packet Length Mean', 'Bwd Packet Length Std',
        'Min Packet Length', 'Max Packet Length',
        'Packet Length Mean', 'Packet Length Std', 'Packet Length Variance',
        'Average Packet Size', 'Avg Fwd Segment Size', 'Avg Bwd Segment Size',
    ]
    TIME_NAMES = [
        'Active Mean', 'Active Std', 'Active Max', 'Active Min',
        'Idle Mean', 'Idle Std', 'Idle Max', 'Idle Min',
    ]
    FLAG_NAMES = [
        'Fwd PSH Flags', 'Bwd PSH Flags', 'Fwd URG Flags', 'Bwd URG Flags',
        'FIN Flag Count', 'SYN Flag Count', 'RST Flag Count', 'PSH Flag Count',
        'ACK Flag Count', 'URG Flag Count', 'CWE Flag Count', 'ECE Flag Count',
        'Down/Up Ratio',
        'Subflow Fwd Packets', 'Subflow Fwd Bytes',
        'Subflow Bwd Packets', 'Subflow Bwd Bytes',
    ]

    def safe_subset(req, avail):
        return [f for f in req if f in avail]

    flow_feats   = safe_subset(FLOW_NAMES,   feature_cols)
    packet_feats = safe_subset(PACKET_NAMES, feature_cols)
    time_feats   = safe_subset(TIME_NAMES,   feature_cols)
    flag_feats   = safe_subset(FLAG_NAMES,   feature_cols)
    used = set(flow_feats + packet_feats + time_feats + flag_feats)
    remaining = [f for f in feature_cols if f not in used]
    packet_feats = packet_feats + remaining  # geri kalanları packet'e ekle

    groups = {
        '🌊 Paket 1 — Flow Stats':      flow_feats,
        '📦 Paket 2 — Packet Details':  packet_feats,
        '⏱️ Paket 3 — Time Features':   time_feats,
        '🚩 Paket 4 — Flags & TCP':     flag_feats,
    }

    # Özet
    g1, g2, g3, g4 = st.columns(4)
    cols_list = [g1, g2, g3, g4]
    for col, (gname, gfeats) in zip(cols_list, groups.items()):
        col.metric(gname.split('—')[1].strip(), f"{len(gfeats)} feature")

    st.divider()

    for gname, gfeats in groups.items():
        with st.expander(f"{gname} ({len(gfeats)} feature)"):
            if gfeats:
                feat_df = pd.DataFrame({
                    'Feature': gfeats,
                    'Veri tipi': [str(labeled[f].dtype) for f in gfeats],
                    'Min': [labeled[f].min() for f in gfeats],
                    'Max': [labeled[f].max() for f in gfeats],
                    'Ortalama': [labeled[f].mean() for f in gfeats],
                    'Std': [labeled[f].std() for f in gfeats],
                })
                st.dataframe(feat_df.round(4), use_container_width=True, hide_index=True)
            else:
                st.info("Bu grupta eşleşen feature bulunamadı.")

    st.divider()
    st.markdown("#### Tüm feature listesi")
    all_feat_df = pd.DataFrame({
        'Feature': feature_cols,
        'Grup': [
            'Flow' if f in flow_feats else
            'Time' if f in time_feats else
            'Flag' if f in flag_feats else
            'Packet'
            for f in feature_cols
        ],
        'Dtype': [str(labeled[f].dtype) for f in feature_cols],
    })
    st.dataframe(all_feat_df, use_container_width=True, hide_index=True)

    with st.expander("Python kodu — feature grupları ve index hazırlama"):
        st.code("""
def safe_idx(names, all_cols):
    return [all_cols.index(n) for n in names if n in all_cols]

idx_flow   = safe_idx(flow_feats,   feature_cols)
idx_packet = safe_idx(packet_feats, feature_cols)
idx_time   = safe_idx(time_feats,   feature_cols)
idx_flag   = safe_idx(flag_feats,   feature_cols)

X_flow   = X_scaled[:, idx_flow]
X_packet = X_scaled[:, idx_packet]
X_time   = X_scaled[:, idx_time]
X_flag   = X_scaled[:, idx_flag]

# Paralel NN'e giriş:
model_s1.fit(
    [X_flow, X_packet, X_time, X_flag], y_bin,
    class_weight=class_weight_s1
)
        """, language='python')

    st.markdown('<div class="success-box">✅ Tüm ön işleme aşamaları tamamlandı. '
                'Bir sonraki adım: StandardScaler + train/test split + Keras model inşası.</div>',
                unsafe_allow_html=True)