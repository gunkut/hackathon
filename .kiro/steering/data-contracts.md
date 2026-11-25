---
inclusion: fileMatch
fileMatchPattern: ["src/data/**", "data/**", "**/tests/**", "**/engine/**"]
---

# Veri Sözleşmeleri

Tek veri kaynağı `data/input/dataa.xlsx`. (`products.xlsx` artık kullanılmaz.) Sentetik veri ve fiyat/TL yoktur. Bağış emirleri tek alıcıya gider: `DONATION_PARTNER_NAME` (varsayılan "Umut Gıda Bankası").
Hesap tarihi sabittir: `AS_OF_DATE = 2026-11-25` (satış verisi 24.11.2026'da biter).

## 1. Excel sayfaları
| Sayfa | Tür | Kullanım |
|---|---|---|
| `Urunler` (50 lot) | Ham + türetilmiş kolon | Ham kolonlar DB'ye yüklenir. `Sakıncalı Sevk Tarihi`, `Sakıncalı Sevke Kalan Gün`, `Risk Durumu` türetilmiştir, saklanmaz |
| `Bayiler` (5) | Ham | `Bayi ID, Bayi Adı, Teslim Süresi (gün)` |
| `Bayi_Stok` (230) | Ham | Bayi × ürün stoğu |
| `Satis_15G` (3.450) | Ham | 10–24.11.2026 günlük satış (15 gün × 5 bayi × 46 ürün) |
| `Satis_ve_Stok` | Türetilmiş (pivot) | Yalnızca `Ürün Grubu` kolonu alınır (başka yerde yok) |
| `Riskli_Lot_Kontrol` | Türetilmiş | DB'ye girmez; testlerde beklenen sonuç |
| `Erken_Uyari` | Türetilmiş | DB'ye girmez; testlerde beklenen sonuç |

Okuyucu: `src/data/excel_source.py` (`read_workbook`, `read_expected`, `ExcelRepository`).

## 2. DynamoDB (us-east-1, on-demand)
| Tablo | Anahtar | İçerik |
|---|---|---|
| `tazerota-lots` | `lot_id` | `product_id, product_code (P001…), product_name, food_type, product_group, expiry_date, location, quantity, unsafe_ship_days, donation_eligible` |
| `tazerota-dealers` | `dealer_id` + `sk` | `sk=PROFILE`: `dealer_name, lead_time_days`. `sk=STOCK#<product_code>`: `product_code, on_hand_qty` |
| `tazerota-sales` | `pk=<dealer_id>#<product_code>` + `sk=<YYYY-MM-DD>` | `dealer_id, product_code, qty_sold` |
| `tazerota-approvals` | `plan_key=<as_of>\|r<risk>\|e<early>#<lot_id>` | Lot bazında insan onayı: `lot_id, status` (APPROVED → DISPATCHED), `approved_at, approved_by, dispatched_at, order_count`, lot miktarları |
| `tazerota-orders` | `plan_key` + `order_id` (`SE-<YYYYMMDD>-<nnn>` bayi, `BG-…` bağış) | `seq, type, lot_id, product_*, recipient_*, qty, order_date, delivery_date (= as_of + teslim süresi), status, notification{status, title, body, sent_at}` |

Kurulum (app/agent içinden): `uv run python ../../src/data/create_tables.py`, sonra `PYTHONPATH=../../src/data uv run python ../../src/data/seed_dynamodb.py`.
Eski `skt-*` tabloları kullanılmıyor; kullanıcı onayıyla silinecek.

## 3. İş kuralları (`app/agent/engine/planner.py`)
- Sakıncalı sevk tarihi = SKT − sakıncalı sevk süresi. Kalan günler `AS_OF_DATE`'e göre.
- Günlük talep (bayi × ürün) = 0,6 × son 7 gün ort. + 0,4 × 15 gün ort.
- **Riskli lot:** sevke kalan gün ≤ `risk_days` (varsayılan 60).
  - Bayi kapasitesi = ⌊talep × (SKT'ye kalan gün − teslim süresi) − bayi stoğu⌋, en az 0.
  - Lotlar SKT sırasıyla işlenir; aynı ürünün erken SKT'li lotu bayi kapasitesini önce kullanır.
  - En yüksek kapasiteli bayiden başlayarak sevk; kalan → `Bağışa Uygun = Evet` ise bağış, değilse imha.
  - Durum: `Sorun yok` / `Kısmi bağış` / `Kısmi imha` / `Bağış` / `İmha`.
- **Müdahalesiz senaryo:** satılan = ⌊Σ talep × sevke kalan gün − Σ stok⌋ (aynı ürünün önceki lotları düşülür); kalan imha.
- **Erken uyarı:** `risk_days` < sevke kalan gün ≤ `early_days` (varsayılan 180). Kapasite = ⌊Σ talep × (SKT'ye kalan − teslim) − Σ stok⌋ − önceki lotların kullandığı; fazla = depo − kapasite; stok biter = depo / Σ talep.
- Her riskli lotta sevk + bağış + imha = lot miktarı (kodda kontrol edilir).

## 4. Doğrulama
`app/agent/tests/test_planner.py` motoru ham sayfalarla çalıştırıp `Riskli_Lot_Kontrol` ve `Erken_Uyari` ile karşılaştırır.
Riskli lotlar birebir tutar (6 lot, 967 / 885 / 82, müdahalesiz 151 = %15,6). Erken uyarı kapasitesinde Excel yuvarlamasından ±2 adet fark **kabul edilmiştir** (ör. toplam fazla 275 vs 274).

## 5. Sevk iş akışı (`engine/dispatch.py`, Mod: İnsan onayı)
Her lot için ayrı: Öneri → Onay (panelde lot seçilip "Onayla") → Sevk emri → Bildirim. Yalnızca onaylanan lot "Sevk edildi" olur; diğer lotların emirleri taslak kalır.
- Onaydan önce emirler taslaktır (saklanmaz); numaralar deterministiktir ve onay sonrası aynı kalır (ör. Pınar Hindi Çınar = `SE-20261125-009`, bağış `BG-20261125-003`). 60/180 günde 22 bayi emri (885 adet) + 4 bağış emri (82 adet).
- Emirleri ajan `create_dispatch_orders(lot)` ile yalnızca o lot için oluşturur; araç lotun onay kaydı yoksa reddeder (kod düzeyinde), tekrar çağrılırsa yeni emir açmaz. Numaralar onay sırasından bağımsızdır.
- Bildirimler kayıttır; e-posta/SMS gönderilmez. "Demoyu sıfırla" (`POST /api/reset`, isteğe bağlı `lot_id`) onayları ve emirleri siler.
