---
inclusion: always
---

# Ürün: TazeRota · SKT Kurtarma Paneli (Takım Wakanda)

## Problem
Merkez depodaki (DEPO-01) lotların sakıncalı sevk tarihi (SKT − sakıncalı sevk süresi) geçerse lot bayilere sevk edilemez ve imha edilir. Amaç imha oranını düşürmek.

## Çözüm
- **Panel** (web): KPI kartları, riskli lot listesi, lot detayı (bayi bazında 15 günlük satış, stok, kapasite, öneri), lot dağılımı, erken uyarı, raporlar. Panel sayıları deterministik motordan gelir.
- **TazeRota Ajanı** (Strands + Bedrock Claude, AgentCore Runtime): planı Türkçe açıklar, soruları araçlarla yanıtlar. Sayı hesaplamaz.
- **Onayla:** planı `tazerota-approvals` tablosuna kaydeder. **Eşiği değiştir:** riskli (60) ve erken uyarı (180) eşiklerini değiştirip yeniden hesaplar. **Raporlar:** senaryo karşılaştırması, CSV/JSON indirme.

Karar sırası: en yüksek kapasiteli bayiye sevk → kalan bağış (kalite ve mevzuat kontrolü gerekir) → bağışa uygun değilse imha. Kurallar `data-contracts.md` bölüm 3'te.

## Demo sonuçları (25.11.2026, 60/180 gün)
6 riskli lot, 967 adet; bayilere 885 (%91,5), bağış 82 (%8,5), imha %0 (müdahalesiz %15,6). Erken uyarı: 3 lot (mevsimsel soğuk içecek), ~275 adet fazla.

## Kapsam dışı
ERP/WMS entegrasyonu, rota/mesafe (`Adres` depo raf adresidir), çok kullanıcılı yetkilendirme, fiyat/TL hesabı, bağış kurumu kapasitesi.
