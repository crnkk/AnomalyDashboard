# CIC-IDS2017 Anomali Tespit Pipeline

CIC-IDS2017 ağ trafiği verisi üzerinde iki aşamalı (binary → saldırı grubu) anomali tespiti için
veri hazırlama adımlarını gösteren Streamlit dashboard'u: yükleme, temizleme, etiketleme,
dengesizlik (imbalance) analizi ve paralel NN için feature gruplandırma.

## Kurulum

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Veri

Repoda yalnızca küçük bir **örnek veri** bulunur (`data/sample/cicids2017/`, ~14 bin satır, ~5 MB).
Her etiketten orantılı satır içerir; nadir sınıflar (Heartbleed, Infiltration, SQL Injection)
eksiksiz tutulmuştur. Dashboard'u denemek için yeterlidir.

**Tam veri** (8 CSV, ~2,8 milyon satır, 885 MB) Kaggle'dan indirilir. Kaggle hesabı gerekmez:

```bash
python scripts/download_data.py
```

Script ~241 MB'lık arşivi indirir, `data/raw/cicids2017/` altına açar ve her dosyayı boyut ve
SHA-256 ile doğrular. Dosyalar zaten varsa ve doğruysa tekrar indirmez.

Örnek veriyi tam veriden yeniden üretmek için: `python scripts/make_sample.py`

## Çalıştırma

```bash
streamlit run anomali.py
```

Uygulama tam veri indirildiyse onu, indirilmediyse örnek veriyi kullanır. Farklı bir klasör için
`ANOMALI_DATA_DIR=/yol/klasor streamlit run anomali.py`.

## Klasör yapısı

```
anomali.py                 Streamlit dashboard
scripts/download_data.py   Tam veriyi Kaggle'dan indirir ve doğrular
scripts/make_sample.py     Tam veriden tabakalı örnek üretir
data/sample/cicids2017/    Örnek veri (repoda)
data/raw/cicids2017/       Tam veri (indirilir, git'e eklenmez)
```

## Notlar

- Orijinal CSV'lerde "Web Attack – Brute Force" gibi etiketlerdeki tire, dağıtıma göre bozuk
  karakter olarak gelir (`\x96` ya da `�`). Yükleme sırasında `-` olarak normalize edilir.

## Kaynak

- Veri seti: Canadian Institute for Cybersecurity, University of New Brunswick —
  <https://www.unb.ca/cic/datasets/ids-2017.html>
- Kullanılan Kaggle kopyası (MachineLearningCVE CSV'leri):
  <https://www.kaggle.com/datasets/chethuhn/network-intrusion-dataset>

Veri setini kullanırsanız orijinal makaleye atıf yapın:

> Iman Sharafaldin, Arash Habibi Lashkari, Ali A. Ghorbani. "Toward Generating a New Intrusion
> Detection Dataset and Intrusion Traffic Characterization." ICISSP 2018.
