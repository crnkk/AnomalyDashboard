import streamlit as st
import pandas as pd
import numpy as np
import os
import glob
import time
from pathlib import Path

# ── Sayfa ayarları ──────────────────────────────────────────────
st.set_page_config(
    page_title="CIC-IDS2017 Anomali Tespit",
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
    background: #FFF8E1;
    border-left: 4px solid #F9A825;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 8px 0;
}
.info-box {
    background: #E3F2FD;
    border-left: 4px solid #1565C0;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 8px 0;
}
.success-box {
    background: #E8F5E9;
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
BASE_DIR   = Path(__file__).resolve().parent
RAW_DIR    = BASE_DIR / 'data' / 'raw' / 'cicids2017'      # scripts/download_data.py
SAMPLE_DIR = BASE_DIR / 'data' / 'sample' / 'cicids2017'   # repoda gelen küçük örnek

def default_data_dir():
    """ANOMALI_DATA_DIR > tam veri (indirildiyse) > örnek veri."""
    env_dir = os.environ.get('ANOMALI_DATA_DIR')
    if env_dir:
        return env_dir
    if any(RAW_DIR.glob('*.csv')):
        return str(RAW_DIR)
    return str(SAMPLE_DIR)

FILE_MAP = {
    'Monday-WorkingHours.pcap_ISCX.csv':                         'monday',
    'Tuesday-WorkingHours.pcap_ISCX.csv':                        'tuesday',
    'Wednesday-workingHours.pcap_ISCX.csv':                      'wednesday',
    'Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv':    'thursday_am',
    'Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv':'thursday_pm',
    'Friday-WorkingHours-Morning.pcap_ISCX.csv':                 'friday_am',
    'Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv':      'friday_pm_port',
    'Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv':          'friday_pm_ddos',
}

DAY_LABELS = {
    'monday':        'Pazartesi (Referans normal)',
    'tuesday':       'Salı — Brute Force',
    'wednesday':     'Çarşamba — DoS/DDoS',
    'thursday_am':   'Perşembe sabah — Web Attack',
    'thursday_pm':   'Perşembe öğleden sonra — Infiltration',
    'friday_am':     'Cuma sabah — Bot',
    'friday_pm_port':'Cuma öğleden sonra — PortScan',
    'friday_pm_ddos':'Cuma öğleden sonra — DDoS',
}

ATTACK_GROUPS = {
    'BENIGN':                       -1,
    'FTP-Patator':                   0,
    'SSH-Patator':                   0,
    'DoS Hulk':                      1,
    'DoS GoldenEye':                 1,
    'DoS slowloris':                 1,
    'DoS Slowhttptest':              1,
    'Heartbleed':                    1,
    'DDoS':                          1,
    'Web Attack - Brute Force':      2,
    'Web Attack - XSS':              2,
    'Web Attack - Sql Injection':    2,
    'PortScan':                      3,
    'Bot':                           4,
    'Infiltration':                  4,
}

GROUP_NAMES = {
    0: 'Brute Force (FTP/SSH)',
    1: 'DoS / DDoS',
    2: 'Web Attack',
    3: 'Port Scan',
    4: 'Bot / Infiltration',
}

DROP_COLS = {'Label', 'binary_label', 'multi_label', 'day'}

# ══════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.title("🛡️ CIC-IDS2017")
    st.caption("Anomali Tespit Pipeline")
    st.divider()

    DATA_DIR = pd.read_csv('config.csv').columns[0]

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
    st.caption("Tüm aşamalar önbelleğe alınır. Dizin değişirse yeniden hesaplanır.")

# ══════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════
def normalize_labels(labels):
    """Web Attack etiketlerindeki tire dağıtıma göre '\\x96' (cp1252) ya da
    '\\ufffd' (�) olarak bozuk gelir; hepsini '-' yapar."""
    return (labels.astype(str)
                  .str.replace('\ufffd', '-', regex=False)
                  .str.replace('\x96', '-', regex=False)
                  .str.strip())

def safe_map(label):
    for key, val in ATTACK_GROUPS.items():
        if key.lower() in str(label).lower():
            return val
    return -1

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
def load_data(data_dir):
    frames = []
    load_log = []
    missing = []

    for fname, day_tag in FILE_MAP.items():
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            missing.append(fname)
            continue
        df = pd.read_csv(path, encoding='utf-8', low_memory=False)
        df.columns = df.columns.str.strip()
        df['Label'] = normalize_labels(df['Label'])
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
        return None, load_log, missing

    data = pd.concat(frames, ignore_index=True)
    return data, load_log, missing

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
    df['binary_label'] = (df['Label'] != 'BENIGN').astype(int)
    df['multi_label']  = df['Label'].apply(safe_map)

    unmatched = df[df['multi_label'] == -1]['Label'].unique()
    benign_unmatched = [l for l in unmatched if l != 'BENIGN']

    return df, benign_unmatched

# ══════════════════════════════════════════════════════
# BAŞLIK
# ══════════════════════════════════════════════════════
st.markdown("""
<div class="stage-header">
    <h1 style="margin:0;font-size:1.8rem">🛡️ CIC-IDS2017 Anomali Tespit Pipeline</h1>
    <p style="margin:4px 0 0;opacity:0.85">Paralel + Seri Neural Network · 5 Saldırı Grubu · İnanç Filtresi</p>
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
        load_btn = st.button("🚀 Veriyi Yükle", type="primary", use_container_width=True)

    if load_btn or 'data' in st.session_state:

        if 'data' not in st.session_state or load_btn:
            with st.spinner("CSV dosyaları okunuyor..."):
                progress = st.progress(0, text="Dosyalar taranıyor...")
                data, load_log, missing = load_data(DATA_DIR)
                for i in range(100):
                    time.sleep(0.005)
                    progress.progress(i + 1, text=f"Yükleniyor... %{i+1}")
                progress.empty()

            if data is None:
                st.error(f"❌ Hiçbir CSV bulunamadı: `{DATA_DIR}`")
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
            lambda x: '🟢 Normal' if x == 'BENIGN' else '🔴 Saldırı'
        )
        st.dataframe(label_counts, use_container_width=True, hide_index=True)

        # Gün bazlı dağılım grafiği
        st.markdown("#### Gün bazlı kayıt dağılımı")
        day_counts = data.groupby('day').agg(
            Toplam=('Label', 'count'),
            Normal=('Label', lambda x: (x == 'BENIGN').sum()),
            Saldiri=('Label', lambda x: (x != 'BENIGN').sum())
        ).reset_index()
        day_counts['Gün'] = day_counts['day'].map(DAY_LABELS)
        st.bar_chart(day_counts.set_index('Gün')[['Normal', 'Saldiri']])

        st.markdown('<div class="success-box">✅ Veri başarıyla yüklendi. "Temizleme" sekmesine geçebilirsiniz.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">ℹ️ Veriyi yüklemek için yukarıdaki butona tıklayın. Dizin yolunu soldaki panelden değiştirebilirsiniz.</div>',
                    unsafe_allow_html=True)
        st.code(f'DATA_DIR = "{DATA_DIR}"', language='python')

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
                data_hash = str(len(raw_data))
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
                data_hash = str(len(clean))
                labeled, benign_unmatched = label_data(data_hash, clean)
                st.session_state['labeled_data']       = labeled
                st.session_state['benign_unmatched']   = benign_unmatched

        labeled           = st.session_state['labeled_data']
        benign_unmatched  = st.session_state['benign_unmatched']

        # Eşleşmeyen etiketler
        if benign_unmatched:
            st.markdown(f'<div class="danger-box">❌ <b>Eşleşmeyen etiketler</b> (BENIGN hariç): {", ".join(benign_unmatched)}</div>',
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
    y_mul_only = y_mul_only[y_mul_only >= 0].astype(int)   # -1 (BENIGN) çıkar
    existing_classes = np.unique(y_mul_only)               # gerçekte var olan sınıflar
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