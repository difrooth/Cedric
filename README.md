# Trendyol satış verisi çekme ve aylık maliyet hesaplama

Bu repo, Trendyol Satıcı Paneli'nde **Raporlar > Satış & Operasyon > Satış** ekranında seçtiğiniz tarih aralığına göre:

- `model_code`
- `net_sales_quantity`

alanlarını alıp CSV üretmek için örnek script içerir.

Opsiyonel olarak ürün maliyetlerini (`model_code,cost_per_unit`) verip toplam maliyeti de hesaplar.

## Kurulum

```bash
pip install playwright
playwright install chromium
```

## Maliyet dosyası formatı (opsiyonel)

`urun_maliyet.csv`

```csv
model_code,cost_per_unit
ABC123,180.50
XYZ999,75.00
```

## Çalıştırma

```bash
python trendyol_sales_report.py --start 2026-01-01 --end 2026-01-31 --costs urun_maliyet.csv
```

> Tarayıcı açılır, siz giriş yaparsınız. Satış sayfasında tarih aralığını seçip listeyi yükledikten sonra terminalde Enter'a basın.

## Çıktı

Varsayılan çıktı: `trendyol_satis_ozet.csv`

Maliyet dosyası verilirse ek kolonlar:

- `cost_per_unit`
- `total_cost`
